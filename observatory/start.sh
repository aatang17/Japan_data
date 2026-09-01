#!/bin/sh
# Refresh official data, then serve. Ingest runs before uvicorn so the single
# DuckDB writer never competes with the read-only API connections.
#
# Ingest is idempotent and fail-safe: an unchanged source file publishes
# nothing, and a failed fetch or validation leaves the last good release live.
# So a boot with no upstream reachable still serves the previous data.
set -u

# Seed point-in-time history from whatever the live table already holds, and
# do it BEFORE the ingests. Live observations carry the release that produced
# them, so this recovers the first vintage exactly — but only while those
# values are still in the table. Run it after an ingest and the pre-existing
# vintage is gone for good. Idempotent: it inserts only rows not already
# recorded, so it costs nothing on later boots.
python -m app.vintages seed || echo "vintage seed did not run"

for dataset in cpi-jp cpi-jp-items boj-assets jgb-yields jnto-visitors \
               population-jp population-jp-history; do
    python -m app.ingest "$dataset" \
        || echo "ingest $dataset did not publish; serving last published release"
done

# Say out loud what the ingests left behind. Fail-safe ingest is silent by
# design, and silence is indistinguishable from success — in August 2026 the
# July CPI file was fetched, archived, and never published, and the site
# served June for three weeks. These lines are what a log search or an alert
# rule can key on.
python - <<'EOF' || echo "health check did not run"
from app import api
report = api.health()
for d in report["datasets"]:
    if d["status"] == "attention":
        print("ATTENTION %s: stale=%s unpublished_artifact=%s latest=%s"
              % (d["dataset"], d.get("stale"), d.get("unpublished_artifact"),
                 d.get("latest_period", "none")))
print("ingest health: %s" % report["status"])
EOF

# Cross-shareholding serving DB: built offline by equity/extract.py and
# shipped with the image as a seed. The image copy always wins — extraction
# happens off-server, so the seed is the newest data this deploy knows. The
# raw filing archive never ships; this file is derived and replaceable.
if [ -f seed/equity.duckdb ]; then
    cp seed/equity.duckdb data/equity.duckdb \
        || echo "equity seed copy failed; serving without cross-shareholding data"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8007}"
