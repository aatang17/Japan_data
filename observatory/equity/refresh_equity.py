# -*- coding: utf-8 -*-
"""The nightly equity refresh — every EDINET-derived dataset, incrementally.

Why this exists
---------------
The capture jobs archive EDINET every day and have done so reliably. The
extractors that turn that archive into the served database were hand-run on a
laptop, and in August 2026 that gap showed: capture moved to the cloud bucket
on the 6th, the extractors kept being pointed at the laptop's frozen copy, and
the 5% filings silently stopped four weeks short of the archive while every
dashboard still looked healthy. Nothing was broken; nobody was running it.

So this runs where the data is served, on the same clock as everything else.
`observatory/start.sh` calls it once per refresh cycle, in the window where
the server is stopped and the database has a single writer.

Why subprocesses
----------------
Each extractor is a program with its own argv, module-level state and parser
version. Running them in-process would couple seven parsers into one failure
domain; as subprocesses, a parser that throws costs its own dataset and
nothing else. That matters more than the startup cost: this job must never be
the reason the site fails to come back up, so a failing extractor is reported
and stepped over, exactly as a failing ingest is.

Cost
----
Incremental. Discovery lists the bucket once and shares it (EDINET_LISTING_CACHE),
each extractor takes only documents archived since its own recorded watermark,
and the database is compacted once at the end rather than seven times. A
routine night is one day of filings — roughly 130 documents.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# (script, label, extra args). Order matters only at the front: extract.py
# refreshes the entity registry and eq_company_year that the other annual-report
# extractors read for company identity, so it goes first.
EXTRACTORS = [
    ("extract.py",            "cross-shareholdings",  ["--all"]),
    ("ownership_extract.py",  "shareholder-register", ["--all"]),
    ("board_extract.py",      "boards-and-pay",       ["--all"]),
    ("facility_extract.py",   "facilities",           ["--all"]),
    ("rental_extract.py",     "rental-property",      ["--all"]),
    # NOT in the boot path yet. Every other extractor resumes from a watermark
    # the shipped seed already carries, so a boot is one incremental night.
    # financials has no watermark and no eq_fin_* tables in the seed, so its
    # first run is the whole archive — 1,315 daily lists — and start.sh does
    # not bind the port until the refresh returns. That is what failed the
    # 2026-09-03 deploy: the container was alive, the healthcheck window (15m)
    # expired, and the site was down. History gets extracted offline and
    # shipped in the seed, the way every other dataset was; re-enable this line
    # once seed/equity.duckdb carries a "financials" row in eq_extract_runs.
    # ("fin_extract.py",      "financials",           []),
    ("lvh_extract.py",        "5pct-filings",         []),
    ("agm_extract.py",        "agm-votes",            []),
    ("buyback.py",            "buybacks",             []),
]

# buyback.py takes neither --db nor --no-compact; it reads EQUITY_DB_PATH and
# never compacts on its own.
NO_DB_FLAG = {"buyback.py"}


def run_one(script, label, extra, args, env):
    cmd = [sys.executable, os.path.join(HERE, script),
           "--source", args.source, "--workers", str(args.workers)]
    if args.new_only:
        cmd.append("--new-only")
    if script not in NO_DB_FLAG:
        cmd += ["--db", args.db, "--no-compact"]
    cmd += extra
    print("\n=== %s (%s) ===" % (label, script), flush=True)
    started = time.time()
    try:
        r = subprocess.run(cmd, env=env, cwd=HERE)
    except Exception as e:                                   # noqa: BLE001
        print("EQUITY %s did not run: %s" % (label, e), flush=True)
        return False
    took = time.time() - started
    if r.returncode != 0:
        print("EQUITY %s FAILED (exit %d, %.0fs) — its previous data stays live"
              % (label, r.returncode, took), flush=True)
        return False
    print("EQUITY %s ok (%.0fs)" % (label, took), flush=True)
    return True


def watermark(db_path):
    """The furthest archive date any extractor in this file has read, or None."""
    import duckdb
    if not os.path.exists(db_path):
        return None
    con = duckdb.connect(db_path, read_only=True)
    try:
        names = {r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables()").fetchall()}
        if "eq_extract_runs" not in names:
            return None
        return con.execute("SELECT max(through_date) FROM eq_extract_runs").fetchone()[0]
    except Exception:                                        # noqa: BLE001
        return None
    finally:
        con.close()


def adopt_seed(seed_path, db_path):
    """Install the shipped seed only when it is genuinely ahead of the volume.

    The old rule was "copy the seed over the volume on every boot", which was
    right while extraction happened offline and the image was always the
    newest thing anyone had. It is now wrong and dangerous: the volume copy is
    topped up nightly, so an unconditional copy would throw away every night
    of extraction since the image was built, and keep doing it on every
    redeploy.

    So compare watermarks and take the newer. A seed built from a fresh
    offline re-extraction (a parser fix, say) still wins and is still how a
    rebuild reaches production; a seed that has fallen behind is ignored.
    """
    if not os.path.exists(seed_path):
        return
    live, shipped = watermark(db_path), watermark(seed_path)
    if not os.path.exists(db_path):
        why = "no equity database on the volume yet"
    elif live is None and shipped is not None:
        why = "the volume copy predates run tracking"
    elif shipped is not None and live is not None and shipped > live:
        why = "the shipped seed reads through %s, the volume through %s" % (shipped, live)
    else:
        print("EQUITY volume database kept (through %s; seed through %s)"
              % (live, shipped))
        return
    print("EQUITY installing the shipped seed: %s" % why)
    shutil.copyfile(seed_path, db_path)


def coverage(db_path):
    """What each extractor now says it has read, straight from the database."""
    import duckdb
    con = duckdb.connect(db_path, read_only=True)
    try:
        names = {r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables()").fetchall()}
        if "eq_extract_runs" not in names:
            return []
        return con.execute(
            "SELECT extractor, through_date, ran_at FROM eq_extract_runs "
            "ORDER BY extractor").fetchall()
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("local", "s3"), default="s3")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--db", default=os.environ.get(
        "EQUITY_DB_PATH",
        os.path.join(HERE, "..", "data", "equity.duckdb")))
    ap.add_argument("--full", action="store_true",
                    help="re-extract the whole archive instead of resuming "
                         "from each extractor's watermark (hours, not minutes)")
    ap.add_argument("--only", help="comma-separated labels to run")
    ap.add_argument("--seed", help="shipped seed database to install first, but "
                                   "only if it reads further than the live one")
    ap.add_argument("--no-compact", action="store_true")
    args = ap.parse_args()
    args.new_only = not args.full
    args.db = os.path.abspath(args.db)

    # Seed adoption happens even when there is no bucket: a container with no
    # credentials must still serve the data the image shipped with.
    if args.seed:
        adopt_seed(args.seed, args.db)

    if args.source == "s3" and not os.environ.get("EDINET_S3_BUCKET"):
        print("EQUITY refresh skipped: no EDINET_S3_BUCKET configured "
              "(serving whatever the database already holds)")
        return 0

    env = dict(os.environ)
    env["EQUITY_DB_PATH"] = args.db
    # One bucket listing shared by all seven, expiring long before the next run.
    env.setdefault("EDINET_LISTING_CACHE",
                   os.path.join(os.path.dirname(args.db), "listing-cache"))

    todo = EXTRACTORS
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        todo = [e for e in EXTRACTORS if e[1] in want]

    started = time.time()
    ok = [label for script, label, extra in todo
          if run_one(script, label, extra, args, env)]
    failed = [label for _, label, _ in todo if label not in ok]

    # Compact once, after everything: each extractor deletes and reinserts its
    # rows, and DuckDB does not hand that space back on its own.
    if ok and not args.no_compact:
        sys.path.insert(0, HERE)
        from extract import compact
        try:
            compact(args.db)
        except Exception as e:                               # noqa: BLE001
            print("EQUITY compaction skipped: %s" % e, flush=True)

    print("\n--- equity refresh: %d ok, %d failed, %.0fs ---"
          % (len(ok), len(failed), time.time() - started))
    for extractor, through, ran in coverage(args.db):
        print("  %-22s archive read through %s" % (extractor, through))
    if failed:
        print("ATTENTION equity extractors failed: %s" % ", ".join(failed))
    # Always 0: a failed extractor leaves its previous data live and must not
    # stop the server coming back up. The ATTENTION line above is the signal.
    return 0


if __name__ == "__main__":
    sys.exit(main())
