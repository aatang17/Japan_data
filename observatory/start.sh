#!/bin/sh
# Refresh official data, then serve — and keep doing both, once a day, forever.
#
# DuckDB takes a single writer and the API holds a read-only handle on the
# same file, so the ingest cannot run alongside the server. Refreshing data
# therefore means restarting: ingest, serve, and when the server ends, ingest
# again. This script is that supervisor, and app/refresh.py is what ends the
# server on the clock (18:00 Asia/Tokyo by default, after the Ministry of
# Finance posts the day's yield curve).
#
# The loop lives here rather than in a Railway cron service on purpose. The
# README recommended that second service for a month, it was never created,
# and the site quietly served three-day-old yields because nothing restarted
# it. A container that refreshes itself cannot be forgotten, needs no API
# token, and behaves the same under Docker and on a laptop. It also means the
# platform's restart policy is never load-bearing: the container itself never
# exits, so nothing depends on how the host counts retries.
#
# Ingest is idempotent and fail-safe: an unchanged source file publishes
# nothing, and a failed fetch or validation leaves the last good release live.
# So a cycle with no upstream reachable still serves the previous data.
set -u

# Seed point-in-time history from whatever the live table already holds, and
# do it BEFORE the first ingest. Live observations carry the release that
# produced them, so this recovers the first vintage exactly — but only while
# those values are still in the table. Run it after an ingest and the
# pre-existing vintage is gone for good. Idempotent: it inserts only rows not
# already recorded, so it costs nothing on later boots. Once per container,
# not once per cycle: after the first pass there is nothing left to recover.
python -m app.vintages seed || echo "vintage seed did not run"

# Stop cleanly when the platform stops us, so a redeploy is not held up
# waiting for a shell that is ignoring SIGTERM.
child=""
backfill=""
stopping=""
stop_backfill() {
    # Always before anything writes a served file: the backfill works on a
    # copy and swaps it in, and a swap landing on top of a nightly ingest
    # would discard that ingest.
    if [ -n "$backfill" ]; then
        kill -TERM "$backfill" 2>/dev/null || true
        wait "$backfill" 2>/dev/null || true
        backfill=""
    fi
}
on_term() {
    stopping=1
    stop_backfill
    if [ -n "$child" ]; then
        kill -TERM "$child" 2>/dev/null || true
        wait "$child" 2>/dev/null || true
    fi
    exit 0
}
trap on_term TERM INT

# What to refresh, and in what order. The curated order leads — headline CPI
# before the long tail, so the most-read pages settle first — and everything
# else registered in app/ingest.py follows it, whether or not this script
# names it. Reading the registry rather than duplicating it is the point: the
# golden rule already makes ADAPTERS the one place a dataset is declared, and
# a dataset that has to be copied into a shell script to keep refreshing is a
# dataset that will one day stop refreshing quietly (Ingest Guardrail 6).
#
# Falls back to the curated list alone if the registry cannot be imported —
# in which case the ingests are broken anyway, and the site still serves.
CURATED="cpi-jp cpi-jp-items cpi-jp-goods-services cpi-jp-sa cpi-jp-long
         cpi-tokyo cpi-tokyo-items boj-assets jgb-yields jnto-visitors
         accommodation-jp population-jp population-jp-history population-jp-municipal
         trade-semis trade-inputs trade-autos trade-energy
         trade-machinery trade-pharma trade-food
         rice-prices-jp rice-inventory-jp agri-prices rice-production-cost
         ja-statistics gdp-jp corporate-finance-jp
         fsa-npl fsa-bank-results jba-banks"

ALL_DATASETS=$(CURATED="$CURATED" python - <<'PY' 2>/dev/null
import os
curated = os.environ["CURATED"].split()
try:
    from app.ingest import ADAPTERS
except Exception:
    registered = None
else:
    registered = set(ADAPTERS)
order = curated + sorted(registered - set(curated)) if registered else curated
if registered is not None:
    order = [d for d in order if d in registered]
print(" ".join(order))
PY
)
if [ -z "$ALL_DATASETS" ]; then
    echo "ATTENTION could not read the dataset registry; refreshing the curated list only"
    ALL_DATASETS="$CURATED"
fi


# Is there anything to serve right now? This is the whole question a boot has
# to answer. With a volume mounted the platform stops the old container before
# it starts the new one, so every second spent here is the site being down —
# 2026-09-13 spent over half an hour of it re-ingesting data the volume
# already held. A volume carrying a published release needs no ingest before
# the port opens; it needs the port open and a refresh running behind it.
#
# Fails closed on purpose: no file, no releases table, an unreadable file or
# no duckdb at all all mean "nothing to serve", which builds before serving
# exactly as a fresh container always has.
has_published_data() {
    python - <<'PY' 2>/dev/null
import sys
try:
    import duckdb
    from app import db
except Exception:
    sys.exit(1)
path = db.DATA_DIR / "observatory.duckdb"
if not path.exists():
    sys.exit(1)
try:
    con = duckdb.connect(str(path), read_only=True)
except Exception:
    sys.exit(1)
try:
    n = con.execute(
        "SELECT count(*) FROM releases WHERE status = 'published'").fetchone()[0]
except Exception:
    n = 0
finally:
    con.close()
sys.exit(0 if n else 1)
PY
}

# A server that dies immediately must not turn into an ingest storm against
# e-Stat, the BOJ and the MoF. After a fast exit the next pass serves straight
# away without re-fetching, and backs off further each time.
fast_exits=0
skip_ingest=""

while true; do
    cycle_start=$(date +%s)

    if [ -n "$skip_ingest" ]; then
        echo "REFRESH restarting without an ingest after $fast_exits fast exit(s)"
    elif has_published_data; then
        # SERVE FIRST, REFRESH SECOND — the normal path, and the reason a
        # deploy no longer takes the site down for as long as the ingests run.
        # Nothing happens between here and the port being bound: the data on
        # the volume is already good, and app/backfill.py refreshes all of it
        # behind the open port, on a copy that is swapped in when it is done.
        echo "SERVE-FIRST the volume holds published data; binding the port now" \
             "and refreshing behind it"
    else
        # COLD START ONLY — a volume with nothing to serve. There is no data
        # to protect and nothing to keep up, so building before the port is
        # the right trade: the site is not "down", it does not exist yet.
        echo "COLD START nothing published on the volume; building before the port opens"

        # The boot ingest list. Overridable because this loop runs BEFORE the
        # port is bound — a dataset that takes longer to publish than the
        # platform's healthcheck window will take the whole site down with it,
        # which is exactly what population-jp-municipal (584,781 series) did on
        # 2026-09-05. Naming the list in the environment lets a heavy dataset be
        # lifted out of the boot path and ingested out of band, without a
        # deploy. The default stays complete, so a laptop and a fresh container
        # still build everything.
        for dataset in ${INGEST_DATASETS:-$ALL_DATASETS}; do
            python -m app.ingest "$dataset" \
                || echo "ingest $dataset did not publish; serving last published release"
        done

        # BOOT TIME IS A PRODUCTION RISK, not just a slow start. Everything
        # below runs before the port is bound, and the platform kills a
        # deployment whose healthcheck never answers — taking the previously
        # working container with it. On 2026-09-09 a redeploy spent over an
        # hour in the financials extractor, hit Railway's healthcheckTimeout
        # and left the site down until the next successful boot. The two
        # levers, both environment-only so neither needs a deploy to pull:
        # INGEST_DATASETS lifts a heavy dataset out of the ingest loop above,
        # and EQUITY_CATCH_UP_DAYS=0 drops the deep archive backfill from the
        # refresh below. Reach for them before the window, not after.

        # The EDINET-derived datasets: 5% filings, cross-shareholdings,
        # boards and pay, buybacks, facilities, rental property, shareholder
        # registers. These used to be extracted by hand on a laptop and
        # shipped as a seed, which is precisely how they went four weeks
        # stale in August 2026 while the capture jobs kept filling the
        # archive on schedule. Now they refresh on the same clock as
        # everything else, from the same bucket the capture jobs write to.
        #
        # Incremental: each extractor resumes from its own recorded
        # watermark, so a routine night is one day of filings (~130
        # documents, under a minute) rather than five years of them. It runs
        # here, in the window where the server is stopped, because DuckDB
        # takes a single writer and the API holds the same file open.
        #
        # --seed installs the shipped database only if it reads further than
        # the volume's, so a redeploy never discards accumulated nights.
        # --skip bank-irrbb: that collector crawls ~100 bank websites for the
        # Basel rate-risk tables, which are published nowhere else. Its time
        # depends on other people's servers, so it must never sit in front of
        # the healthcheck. app/backfill.py runs it once the port is open.
        python equity/refresh_equity.py --seed seed/equity.duckdb \
            --skip bank-irrbb \
            || echo "equity refresh did not complete; last good equity data stays live"

        # The US comparison shelf: the SEC's quarterly Financial Statement
        # Data Sets, already banked by us_capture.py, loaded into their own
        # file (data/sec.duckdb) — the newest SEC_QUARTERS of them here, and
        # app/backfill.py deepens the history after the port is open. One
        # quarter is ~140MB and a few seconds to load; a routine boot finds
        # nothing new and does nothing. Fail-safe like everything above.
        if [ -n "${EDINET_S3_BUCKET:-}" ]; then
            python equity/sec_extract.py --source s3 --last "${SEC_QUARTERS:-4}" \
                --db data/sec.duckdb \
                || echo "US financials (SEC) refresh did not complete; last good data stays live"
        fi

        # Stamp the end of the cycle. This is the only proof that the refresh
        # machinery ran at all: the per-dataset staleness limits are 7 to 950
        # days, so a refresh that stops is invisible in them for days. The API
        # reports the age of this stamp, and answers /catalog/health?strict=1
        # with a 503 once it passes REFRESH_MAX_AGE_HOURS.
        python -m app.refresh heartbeat || echo "ingest heartbeat was not written"

        # Say out loud what the ingests left behind. Fail-safe ingest is silent
        # by design, and silence is indistinguishable from success — in August
        # 2026 the July CPI file was fetched, archived, and never published,
        # and the site served June for three weeks. These lines are what a log
        # search or an alert rule can key on.
        python - <<'EOF' || echo "health check did not run"
from app import api
report = api.health()
for d in report["datasets"]:
    if d["status"] == "attention":
        print("ATTENTION %s: stale=%s unpublished_artifact=%s latest=%s"
              % (d["dataset"], d.get("stale"), d.get("unpublished_artifact"),
                 d.get("latest_period", "none")))
for d in report.get("equity_extractors", []):
    if d["status"] == "attention":
        print("ATTENTION equity/%s: archive read only through %s (%s days behind)"
              % (d["dataset"], d.get("archive_read_through"), d.get("days_behind")))
print("ingest health: %s (last ingest %s)"
      % (report["status"], report.get("last_ingest_at")))
EOF
    fi

    # REFRESH_SUPERVISED is what arms the daily shutdown in app/refresh.py.
    # Nothing else sets it, so a development `uvicorn app.main:app` is never
    # killed by the scheduler no matter what the clock says.
    REFRESH_SUPERVISED=1 uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8007}" &
    child=$!

    # The heavy work, AFTER the port is bound. Everything above had to fit
    # the healthcheck window; this does not. app/backfill.py ingests the
    # datasets the boot list leaves out and walks the equity archive back a
    # slice at a time, each on a copy of the served file that is swapped in
    # when it is done — the server keeps reading throughout. It is stopped
    # before the nightly ingests below ever touch a served file, and not
    # started on a fast-restart cycle. BACKFILL_ENABLED=0 turns it off.
    #
    # BACKFILL_DATASETS is set here rather than read from the environment on
    # purpose. It began life as a workaround — a way to lift one heavy dataset
    # out of a boot path that could not afford it — and a workaround that
    # names a subset is exactly how a dataset stops refreshing without anyone
    # noticing. On the serve-first path this process IS the refresh, so it
    # gets the whole list. The lever that remains is INGEST_DATASETS, which
    # only shapes the cold build above, where nothing is being served anyway.
    if [ -z "$skip_ingest" ] && [ "${BACKFILL_ENABLED:-1}" != "0" ]; then
        BACKFILL_DATASETS="$ALL_DATASETS" python -m app.backfill &
        backfill=$!
    fi

    wait "$child"
    status=$?
    child=""
    stop_backfill

    [ -n "$stopping" ] && exit 0

    served=$(( $(date +%s) - cycle_start ))
    if [ "$served" -lt 120 ]; then
        fast_exits=$((fast_exits + 1))
        skip_ingest=1
        backoff=$((fast_exits * 30))
        [ "$backoff" -gt 300 ] && backoff=300
        echo "ATTENTION the server exited after ${served}s (status ${status}) — too fast" \
             "to be a scheduled refresh; retrying in ${backoff}s"
        # Backgrounded and waited on, never a bare `sleep`: the shell runs a
        # trap only once the foreground command returns, so a plain sleep here
        # would make a redeploy wait out the whole backoff before noticing
        # SIGTERM. As $child it is also killed by the handler.
        sleep "$backoff" &
        child=$!
        wait "$child"
        child=""
    else
        fast_exits=0
        skip_ingest=""
        echo "REFRESH server ran ${served}s and exited (status ${status}); re-running the ingests"
    fi
done
