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

# Cross-shareholding serving DB: built offline by equity/extract.py and
# shipped with the image as a seed. The image copy always wins — extraction
# happens off-server, so the seed is the newest data this deploy knows. The
# raw filing archive never ships; this file is derived and replaceable. Once
# per container: the seed cannot change while the container lives.
if [ -f seed/equity.duckdb ]; then
    cp seed/equity.duckdb data/equity.duckdb \
        || echo "equity seed copy failed; serving without cross-shareholding data"
fi

# Stop cleanly when the platform stops us, so a redeploy is not held up
# waiting for a shell that is ignoring SIGTERM.
child=""
stopping=""
on_term() {
    stopping=1
    if [ -n "$child" ]; then
        kill -TERM "$child" 2>/dev/null || true
        wait "$child" 2>/dev/null || true
    fi
    exit 0
}
trap on_term TERM INT

# A server that dies immediately must not turn into an ingest storm against
# e-Stat, the BOJ and the MoF. After a fast exit the next pass serves straight
# away without re-fetching, and backs off further each time.
fast_exits=0
skip_ingest=""

while true; do
    cycle_start=$(date +%s)

    if [ -n "$skip_ingest" ]; then
        echo "REFRESH restarting without an ingest after $fast_exits fast exit(s)"
    else
        for dataset in cpi-jp cpi-jp-items boj-assets jgb-yields jnto-visitors \
                       population-jp population-jp-history; do
            python -m app.ingest "$dataset" \
                || echo "ingest $dataset did not publish; serving last published release"
        done

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
print("ingest health: %s (last ingest %s)"
      % (report["status"], report.get("last_ingest_at")))
EOF
    fi

    # REFRESH_SUPERVISED is what arms the daily shutdown in app/refresh.py.
    # Nothing else sets it, so a development `uvicorn app.main:app` is never
    # killed by the scheduler no matter what the clock says.
    REFRESH_SUPERVISED=1 uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8007}" &
    child=$!
    wait "$child"
    status=$?
    child=""

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
