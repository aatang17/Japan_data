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
  BACKFILL_GDP_VINTAGES     0 to skip loading the archived GDP releases
                            (default: on; one cheap check once they are
                            present, loaded in slices otherwise)
  BACKFILL_CATCH_UP_DAYS    archive days per equity slice (default 40)
  BACKFILL_MAX_SLICES       stop after this many equity slices (default 400)
  BACKFILL_SEC_QUARTERS     quarterly SEC data sets to hold in all (default 12; 0 = none)
"""
import errno
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
LIVE_SEC = pathlib.Path(os.environ.get("SEC_DB_PATH") or str(DATA_DIR / "sec.duckdb"))

DEFAULT_DATASETS = "accommodation-jp population-jp-municipal"

_child = None
_stopping = False


def log(msg):
    print("BACKFILL %s" % msg, flush=True)


def record_check(dataset, outcome, detail=None):
    """Note in the journal that the refresh reached this dataset.

    Called for every outcome including 'unchanged', because the alarm asks
    whether the pipeline still reaches a dataset, not whether the source moved.
    """
    from . import heartbeat
    heartbeat.record(dataset, outcome, detail)


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


def _fresh_copy_once(live, work):
    """A copy of the served file to work on, or None when it cannot be taken.

    A write-ahead log beside the served file means its last writer did not
    checkpoint, so the main file alone is missing those rows. Copying the pair
    and letting DuckDB replay the log into the copy keeps them; copying the
    main file alone would silently drop them.

    Refusing instead — which is what this did until 2026-09-20 — looked like
    the safe choice and was a deadlock. The API holds the served file open
    read-only and guardrail 5 forbids it ever writing, so nothing in the
    running system can checkpoint that log away. One killed extractor left a
    log beside equity.duckdb on 2026-09-13 and every nightly refresh from then
    on declined to copy the file, freezing all eleven EDINET extractors for a
    week while the archive kept filling. A guard that cannot clear itself is
    not a guard.
    """
    _discard(work)
    if not live.exists():
        log("%s does not exist yet; nothing to copy" % live.name)
        return None
    shutil.copyfile(str(live), str(work))
    wal = _wal(live)
    if not (wal.exists() and wal.stat().st_size > 0):
        return work
    # Copy the log second and only then check the main file has not moved
    # under us. Nothing should be writing (the API is read-only and the
    # nightly writer runs only while the server is stopped), but a torn pair
    # would replay garbage, and that is the served database.
    stat_before = live.stat()
    shutil.copyfile(str(wal), str(_wal(work)))
    if (live.stat().st_mtime_ns, live.stat().st_size) != (stat_before.st_mtime_ns,
                                                          stat_before.st_size):
        log("%s moved while being copied; leaving it for the next pass" % live.name)
        _discard(work)
        return None
    # Replay and flatten, so the copy is self-contained from here on and the
    # swap has one file to rename rather than a pair to keep consistent.
    try:
        con = duckdb.connect(str(work))
        try:
            con.execute("CHECKPOINT")
        finally:
            con.close()
        _discard_wal_only(work)
    except duckdb.Error as exc:
        log("%s has a write-ahead log that will not replay (%s); left untouched"
            % (live.name, exc))
        _discard(work)
        return None
    log("%s carried an unflushed write-ahead log; replayed %d bytes of it into the copy"
        % (live.name, wal.stat().st_size))
    return work


# Waits between attempts when the volume is full, in seconds. The usual cause
# is the file the previous swap replaced: renaming a copy over the served
# database does not free the old file's space, because the server still holds
# it open until its reader notices the change and reopens. So the space comes
# back seconds to minutes AFTER the swap — and the next dataset's copy starts
# at once. On 2026-09-17 and again on 2026-09-20 that window was enough to fill
# a 5GB volume, and the OSError it raised killed this whole process, so every
# dataset still queued behind it — and the entire equity refresh — never ran.
COPY_RETRY_WAITS = (15, 30, 60, 120, 240)


def _pause(seconds):
    """Sleep, but give up at once if we are told to stop. True if stopping."""
    end = time.time() + seconds
    while time.time() < end:
        if _stopping:
            return True
        time.sleep(min(1.0, max(0.0, end - time.time())))
    return _stopping


def fresh_copy(live, work):
    """A working copy of the served file, or None when one cannot be had.

    A full volume is waited out rather than raised: see COPY_RETRY_WAITS for
    why the space is usually on its way back. Any other failure to copy is
    reported and refused. Either way this returns None instead of raising, so
    one bad copy costs this pass of this step, never the rest of the refresh,
    and the served file is untouched throughout.
    """
    for attempt, wait in enumerate((0,) + tuple(COPY_RETRY_WAITS)):
        if wait:
            log("no room to copy %s; waiting %ds for the space a swap is still "
                "holding (attempt %d of %d)"
                % (live.name, wait, attempt + 1, len(COPY_RETRY_WAITS) + 1))
            if _pause(wait):
                _discard(work)
                return None
        try:
            return _fresh_copy_once(live, work)
        except OSError as exc:
            _discard(work)
            if exc.errno != errno.ENOSPC:
                log("could not copy %s (%s); served data untouched" % (live.name, exc))
                return None
    log("still no room to copy %s after %d attempts; this step is skipped and "
        "served data is untouched" % (live.name, len(COPY_RETRY_WAITS) + 1))
    return None


def swap(work, live):
    """Checkpoint the copy, then rename it over the served file."""
    con = duckdb.connect(str(work))
    try:
        con.execute("CHECKPOINT")
    finally:
        con.close()
    _discard_wal_only(work)
    # Any log beside the served file was already replayed into this copy by
    # fresh_copy, so it is redundant — and about to be actively dangerous,
    # because a log left next to a file it no longer matches is replayed into
    # it by the next reader. Dropped BEFORE the rename, never after: a crash
    # in this window costs the rows that log held, which this copy still
    # carries and the extractors would read again; a crash in the other order
    # leaves a mismatched pair, which is the served database corrupted.
    _discard_wal_only(live)
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

def _release_total(path, dataset):
    """Every release a dataset has ever had, in any status.

    The measure for the archived-GDP loader, which adds releases with status
    'archived': they never become the published one, so _published_mark
    cannot see them. Releases are never deleted, so this only grows, and it
    grows exactly when a slice loaded something.
    """
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute("SELECT count(*) FROM releases WHERE dataset = ?",
                           [dataset]).fetchone()[0]
    except duckdb.Error:
        return 0
    finally:
        con.close()


def _published_mark(path, dataset):
    """Identity of one dataset's published release, or None if it has none.

    Emphatically not a count. ingest.py publishes by marking the previous
    release 'superseded' and inserting the new one in the same transaction,
    so the number of published rows is one per dataset forever — it rises on
    a dataset's first ever publish and never again.

    Counting them was therefore a test that only a brand-new dataset could
    pass, and between 14 and 19 September 2026 it quietly threw away every
    refresh of every mature dataset: August CPI was fetched, validated and
    published into the copy each night, the copy was judged 'unchanged', and
    the site went on serving July. release_id comes from a sequence, so a new
    release is always a new mark.
    """
    con = duckdb.connect(str(path), read_only=True)
    try:
        row = con.execute(
            "SELECT release_id, latest_period FROM releases "
            "WHERE dataset = ? AND status = 'published'", [dataset]).fetchone()
        return tuple(row) if row else None
    except duckdb.Error:
        return None
    finally:
        con.close()


def backfill_macro(datasets):
    work = DATA_DIR / "observatory.backfill.duckdb"
    for ds in datasets:
        if _stopping:
            return
        if fresh_copy(LIVE_MACRO, work) is None:
            if not _stopping:
                record_check(ds, "failed", "no working copy of the database could "
                                           "be taken (volume full or file busy)")
            return
        before = _published_mark(work, ds)
        env = dict(os.environ, OBSERVATORY_DB_PATH=str(work))
        log("ingest %s into a copy" % ds)
        started = time.time()
        rc = _run([sys.executable, "-m", "app.ingest", ds], env, ROOT)
        took = time.time() - started
        if rc != 0:
            log("ingest %s did not publish (exit %s, %.0fs); served data untouched"
                % (ds, rc, took))
            _discard(work)
            record_check(ds, "failed", "ingest exited %s" % rc)
            if rc == -1:
                return
            continue
        after = _published_mark(work, ds)
        if after is not None and after != before:
            swap(work, LIVE_MACRO)
            log("published %s (%.0fs): release %s, data through %s"
                % (ds, took, after[0], after[1]))
            record_check(ds, "published", "release %s through %s" % (after[0], after[1]))
        else:
            log("%s unchanged (%.0fs); nothing to swap" % (ds, took))
            _discard(work)
            record_check(ds, "unchanged", None)


# Archived GDP releases per slice. Loading all 134 takes about three quarters
# of an hour, and a copy that is swapped in only at the end loses every minute
# of it to a restart. A slice is ~8 minutes and lands on the volume, so a
# container stopped mid-backfill loses one slice, not the run.
GDP_VINTAGE_SLICE = 20


def backfill_gdp_vintages(max_slices=20):
    """Load the archived GDP releases a slice at a time, swapping after each.

    Same shape as a macro ingest — work on a copy, swap it in only if it
    gained releases — but repeated, because the whole archive is far longer
    than a container can be relied on to live. The loader records what it has
    already recorded, so each slice resumes where the last one stopped and a
    volume that holds the archive costs one listing call to confirm it.
    """
    work = DATA_DIR / "observatory.backfill.duckdb"
    for n in range(1, max_slices + 1):
        if _stopping:
            return
        if fresh_copy(LIVE_MACRO, work) is None:
            return
        before = _release_total(work, "gdp-jp")
        env = dict(os.environ, OBSERVATORY_DB_PATH=str(work))
        started = time.time()
        rc = _run([sys.executable, "-m", "app.gdp_vintages", "load",
                   "--limit", str(GDP_VINTAGE_SLICE)], env, ROOT)
        took = time.time() - started
        if rc != 0:
            log("GDP vintage slice %d did not finish (exit %s, %.0fs); served data "
                "untouched" % (n, rc, took))
            _discard(work)
            return
        gained = _release_total(work, "gdp-jp") - before
        if gained <= 0:
            log("archived GDP releases complete (%.0fs); nothing to swap" % took)
            _discard(work)
            return
        swap(work, LIVE_MACRO)
        log("GDP vintage slice %d landed: %d release(s) (%.0fs)" % (n, gained, took))


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


# --- the US shelf ------------------------------------------------------------

def _sec_quarters(path):
    """Quarters the SEC shelf file holds, or an empty set before any load."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        names = {r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables()").fetchall()}
        if "sec_quarters" not in names:
            return set()
        return {r[0] for r in con.execute(
            "SELECT quarter FROM sec_quarters WHERE status IN ('ok','partial')").fetchall()}
    finally:
        con.close()


def backfill_sec(max_quarters, per_slice=2):
    """Deepen data/sec.duckdb a couple of quarters at a time, oldest-loaded
    downwards, until it holds `max_quarters` or the shelf runs out. Same
    copy → load → swap discipline as the equity history: the served file is
    never written in place, and a slice that fails leaves it untouched."""
    if not os.environ.get("EDINET_S3_BUCKET"):
        log("no EDINET_S3_BUCKET; the US shelf stays as it is")
        return
    work = DATA_DIR / "sec.backfill.duckdb"
    script = ROOT / "equity" / "sec_extract.py"
    n = 0
    while not _stopping:
        n += 1
        if fresh_copy(LIVE_SEC, work) is None:
            return
        before = _sec_quarters(work)
        if len(before) >= max_quarters:
            log("US shelf holds %d quarters; cap is %d — history is complete"
                % (len(before), max_quarters))
            _discard(work)
            return
        take = min(per_slice, max_quarters - len(before))
        log("US shelf slice %d: %d older quarter(s) below %s"
            % (n, take, min(before) if before else "nothing loaded"))
        started = time.time()
        rc = _run([sys.executable, str(script), "--source", "s3", "--db", str(work),
                   "--last", "0", "--deepen", str(take)], dict(os.environ), ROOT)
        took = time.time() - started
        if rc != 0:
            log("US shelf slice %d did not complete (exit %s, %.0fs); served data untouched"
                % (n, rc, took))
            _discard(work)
            return
        after = _sec_quarters(work)
        if after == before:
            log("US shelf slice %d found nothing older on the shelf (%.0fs)" % (n, took))
            _discard(work)
            return
        swap(work, LIVE_SEC)
        log("US shelf slice %d landed (%.0fs): %s" % (n, took, ", ".join(sorted(after - before))))


def stamp_cycle():
    """Mark the end of a refresh cycle, and say what it left behind.

    start.sh used to do both, in the window before it bound the port. On the
    serve-first path there is no such window: the port opens on the data the
    volume already holds and this process is the refresh, so the stamp and the
    health report belong here, at the end of it.

    Only on a completed run. The stamp is the one signal that says the refresh
    machinery is alive — /catalog/health reports its age and answers strict
    callers with a 503 once it passes REFRESH_MAX_AGE_HOURS — so a run cut
    short by a redeploy must not claim to be one. The heartbeat is a plain
    file on the volume, never a row: the served database has a single writer
    and it is not this process.
    """
    try:
        from . import heartbeat
        log("refresh heartbeat: %s" % heartbeat.write()["at"])
    except Exception as exc:  # noqa: BLE001 — a missed stamp must not fail the run
        log("ingest heartbeat was not written: %s" % exc)
    try:
        from . import api
        report = api.health()
        for d in report["datasets"]:
            if d["status"] == "attention":
                log("ATTENTION %s: stale=%s unpublished_artifact=%s latest=%s"
                    % (d["dataset"], d.get("stale"), d.get("unpublished_artifact"),
                       d.get("latest_period", "none")))
        for d in report.get("equity_extractors", []):
            if d["status"] == "attention":
                log("ATTENTION equity/%s: archive read only through %s (%s days behind)"
                    % (d["dataset"], d.get("archive_read_through"), d.get("days_behind")))
        log("ingest health: %s (last ingest %s)"
            % (report["status"], report.get("last_ingest_at")))
    except Exception as exc:  # noqa: BLE001
        log("health check did not run: %s" % exc)


def main():
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    datasets = os.environ.get("BACKFILL_DATASETS", DEFAULT_DATASETS).split()
    days = int(os.environ.get("BACKFILL_CATCH_UP_DAYS", "40") or 0)
    max_slices = int(os.environ.get("BACKFILL_MAX_SLICES", "400") or 0)
    # The archived GDP releases: the real-time history of the national
    # accounts, 2002-2019. Long once, nothing every time after, so it is opt-
    # outable rather than opt-in — a fresh volume should acquire it without
    # anyone remembering to ask.
    gdp_vintages = os.environ.get("BACKFILL_GDP_VINTAGES", "1") not in ("", "0")
    log("starting: datasets=%s, equity slice=%d days, gdp vintages=%s"
        % (" ".join(datasets) or "-", days, "yes" if gdp_vintages else "no"))
    if datasets:
        backfill_macro(datasets)
    # Stamp here, not at the end. What follows walks history backwards and can
    # run for hours; the daily cycle stops it long before it is "done", and a
    # heartbeat that waited for that would report the refresh as dead every
    # day. The current data is what the stamp is about, and it is current now.
    if not _stopping:
        stamp_cycle()
    # Current data before history: the equity extractors carry this week's
    # filings, the GDP archive is a one-off load of 2002-2019 releases that is
    # already complete on the production volume.
    if days > 0 and not _stopping:
        _phase("equity", backfill_equity, days, max_slices)
    if gdp_vintages and not _stopping:
        _phase("GDP vintages", backfill_gdp_vintages)
    # The US shelf: how many quarterly SEC data sets to hold in all (each is
    # ~140MB; 12 is three years). 0 leaves the boot-time load as it is.
    sec_max = int(os.environ.get("BACKFILL_SEC_QUARTERS", "12") or 0)
    if sec_max > 0 and not _stopping:
        _phase("SEC", backfill_sec, sec_max)
    log("stopped" if _stopping else "done")
    return 0


def _phase(name, fn, *args):
    """Run one phase; a crash in it is logged and the next phase still runs.

    Until 2026-09-21 the phases ran bare, one after another, so an exception
    in any of them ended the process. A leftover call to a renamed function in
    the GDP archive loader raised NameError every night, and the equity
    refresh, which ran next, never ran at all. The phases do not depend on
    one another, so a fault in one has no reason to cost the rest.
    """
    try:
        fn(*args)
    except Exception as exc:                                 # noqa: BLE001
        import traceback
        traceback.print_exc()
        log("ATTENTION %s phase crashed (%s: %s); moving on to the next phase"
            % (name, type(exc).__name__, exc))


if __name__ == "__main__":
    sys.exit(main())
