"""Backfill after boot: the heavy work, on a copy, swapped in when it is done.

start.sh runs every ingest and the equity refresh BEFORE it binds the port,
because DuckDB takes one writer and the API holds the served file open. That
is right for the nightly refresh and wrong for anything big: with a volume
mounted, the platform stops the old container before it starts the new one,
so boot time is downtime, and a boot that outlives the healthcheck window is
killed with the site already down. That is what population-jp-municipal did
on 2026-09-05 and the financials extractor on 2026-09-09 — and the levers
that lifted them out of the boot path (INGEST_DATASETS, EQUITY_CATCH_UP_DAYS)
also stopped them from ever being loaded: two datasets never published in
production, and five equity extractors frozen at the depth of their first
run.

This module is the other half of those levers. It runs in the background
once the server is up, and it never touches a file the server is reading:

  1. copy the served database to a work file beside it;
  2. run the ingest, or one bounded slice of the equity catch-up, against
     the copy — the server keeps reading the original the whole time;
  3. if that run published something, rename the copy over the original.

The rename is atomic, and both API readers reopen when the file under them
changes, so the swap costs the next request one reconnect. A run that fails
publishes nothing: the copy is deleted and the served file was never opened
for writing. A container stopped mid-run loses only that slice — the swap
after each slice is what makes progress durable.

It is killed by start.sh the moment the server exits, before the nightly
ingests write the served files, so the two writers can never overlap; and it
is never started on a fast-restart cycle.

Environment (all optional):
  BACKFILL_DATASETS         macro datasets to publish, space-separated
                            (default: the two the boot path leaves out)
  BACKFILL_CATCH_UP_DAYS    archive days per equity slice (default 40)
  BACKFILL_MAX_SLICES       stop after this many equity slices (default 400)
"""
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time

import duckdb

from . import db

ROOT = db.ROOT
DATA_DIR = db.DATA_DIR
# The SERVED files, by their fixed names — not db.DB_PATH, which this module
# points elsewhere for the child it runs.
LIVE_MACRO = DATA_DIR / "observatory.duckdb"
LIVE_EQUITY = pathlib.Path(os.environ.get("EQUITY_DB_PATH")
                           or str(DATA_DIR / "equity.duckdb"))

DEFAULT_DATASETS = "accommodation-jp population-jp-municipal"

_child = None
_stopping = False


def log(msg):
    print("BACKFILL %s" % msg, flush=True)


def _on_term(signum, frame):
    global _stopping
    _stopping = True
    if _child is not None and _child.poll() is None:
        _child.terminate()


def _wal(path):
    return path.with_name(path.name + ".wal")


def _discard(work):
    for p in (work, _wal(work)):
        try:
            p.unlink()
        except OSError:
            pass


def fresh_copy(live, work):
    """A copy of the served file to work on, or None when it cannot be taken.

    A write-ahead log beside the served file means its last writer did not
    checkpoint; copying the main file alone would silently drop those rows,
    so the copy is refused rather than risked.
    """
    _discard(work)
    if not live.exists():
        log("%s does not exist yet; nothing to copy" % live.name)
        return None
    wal = _wal(live)
    if wal.exists() and wal.stat().st_size > 0:
        log("%s has an unflushed write-ahead log; leaving it alone" % live.name)
        return None
    shutil.copyfile(str(live), str(work))
    return work


def swap(work, live):
    """Checkpoint the copy, then rename it over the served file."""
    con = duckdb.connect(str(work))
    try:
        con.execute("CHECKPOINT")
    finally:
        con.close()
    _discard_wal_only(work)
    os.replace(str(work), str(live))
    log("swapped %s in (%d bytes)" % (live.name, live.stat().st_size))


def _discard_wal_only(work):
    try:
        _wal(work).unlink()
    except OSError:
        pass


def _run(cmd, env, cwd):
    """Run a child, returning its exit code; -1 if we were told to stop."""
    global _child
    if _stopping:
        return -1
    _child = subprocess.Popen(cmd, env=env, cwd=str(cwd))
    try:
        rc = _child.wait()
    finally:
        _child = None
    return -1 if _stopping else rc


# --- macro datasets ----------------------------------------------------------

def _release_count(path):
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute(
            "SELECT count(*) FROM releases WHERE status = 'published'").fetchone()[0]
    except duckdb.Error:
        return 0
    finally:
        con.close()


def backfill_macro(datasets):
    work = DATA_DIR / "observatory.backfill.duckdb"
    for ds in datasets:
        if _stopping:
            return
        if fresh_copy(LIVE_MACRO, work) is None:
            return
        before = _release_count(work)
        env = dict(os.environ, OBSERVATORY_DB_PATH=str(work))
        log("ingest %s into a copy" % ds)
        started = time.time()
        rc = _run([sys.executable, "-m", "app.ingest", ds], env, ROOT)
        took = time.time() - started
        if rc != 0:
            log("ingest %s did not publish (exit %s, %.0fs); served data untouched"
                % (ds, rc, took))
            _discard(work)
            if rc == -1:
                return
            continue
        if _release_count(work) > before:
            swap(work, LIVE_MACRO)
            log("published %s (%.0fs)" % (ds, took))
        else:
            log("%s unchanged (%.0fs); nothing to swap" % (ds, took))
            _discard(work)


# --- equity history ----------------------------------------------------------

def _floors(path):
    """extractor -> (through_date, back_to_date), or {} before run tracking."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        names = {r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables()").fetchall()}
        if "eq_extract_runs" not in names:
            return {}
        cols = {r[1] for r in con.execute(
            "PRAGMA table_info('eq_extract_runs')").fetchall()}
        depth = "back_to_date" if "back_to_date" in cols else "NULL"
        rows = con.execute(
            "SELECT extractor, through_date, %s FROM eq_extract_runs" % depth).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}
    finally:
        con.close()


def backfill_equity(days, max_slices):
    if not os.environ.get("EDINET_S3_BUCKET"):
        log("no EDINET_S3_BUCKET; equity history stays as it is")
        return
    work = DATA_DIR / "equity.backfill.duckdb"
    script = ROOT / "equity" / "refresh_equity.py"
    for n in range(1, max_slices + 1):
        if _stopping:
            return
        if fresh_copy(LIVE_EQUITY, work) is None:
            return
        before = _floors(work)
        env = dict(os.environ, EQUITY_CATCH_UP_DAYS=str(days))
        log("equity slice %d: %d archive days below each floor" % (n, days))
        started = time.time()
        rc = _run([sys.executable, str(script), "--db", str(work), "--no-compact"],
                  env, ROOT)
        took = time.time() - started
        if rc != 0:
            log("equity slice %d did not complete (exit %s, %.0fs); served data untouched"
                % (n, rc, took))
            _discard(work)
            return
        after = _floors(work)
        moved = [x for x in after if after[x] != before.get(x)]
        if not moved:
            log("equity slice %d read nothing new (%.0fs); history is complete" % (n, took))
            _discard(work)
            return
        swap(work, LIVE_EQUITY)
        log("equity slice %d landed (%.0fs): %s" % (n, took, ", ".join(sorted(moved))))


def main():
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    datasets = os.environ.get("BACKFILL_DATASETS", DEFAULT_DATASETS).split()
    days = int(os.environ.get("BACKFILL_CATCH_UP_DAYS", "40") or 0)
    max_slices = int(os.environ.get("BACKFILL_MAX_SLICES", "400") or 0)
    log("starting: datasets=%s, equity slice=%d days" % (" ".join(datasets) or "-", days))
    if datasets:
        backfill_macro(datasets)
    if days > 0 and not _stopping:
        backfill_equity(days, max_slices)
    log("stopped" if _stopping else "done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
