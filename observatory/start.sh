#!/bin/sh
# Refresh official data, then serve. Ingest runs before uvicorn so the single
# DuckDB writer never competes with the read-only API connections.
#
# Ingest is idempotent and fail-safe: an unchanged source file publishes
# nothing, and a failed fetch or validation leaves the last good release live.
# So a boot with no upstream reachable still serves the previous data.
set -u

for dataset in cpi-jp cpi-jp-items; do
    python -m app.ingest "$dataset" \
        || echo "ingest $dataset did not publish; serving last published release"
done

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8007}"
