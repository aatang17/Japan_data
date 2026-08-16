#!/bin/sh
# Refresh official data, then serve. Ingest runs before uvicorn so the single
# DuckDB writer never competes with the read-only API connections.
#
# Ingest is idempotent and fail-safe: an unchanged source file publishes
# nothing, and a failed fetch or validation leaves the last good release live.
# So a boot with no upstream reachable still serves the previous data.
set -u

for dataset in cpi-jp cpi-jp-items boj-assets; do
    python -m app.ingest "$dataset" \
        || echo "ingest $dataset did not publish; serving last published release"
done

# Cross-shareholding serving DB: built offline by equity/extract.py and
# shipped with the image as a seed. The image copy always wins — extraction
# happens off-server, so the seed is the newest data this deploy knows. The
# raw filing archive never ships; this file is derived and replaceable.
if [ -f seed/equity.duckdb ]; then
    cp seed/equity.duckdb data/equity.duckdb \
        || echo "equity seed copy failed; serving without cross-shareholding data"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8007}"
