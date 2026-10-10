#!/usr/bin/env bash
# gh-deploy.sh — the only thing GitHub Actions' key may run on the server.
#
# Installed as a forced command in /root/.ssh/authorized_keys:
#   command="/opt/plover/gh-deploy.sh",restrict ssh-ed25519 … github-actions-deploy
# so whatever the workflow asks for arrives in $SSH_ORIGINAL_COMMAND and this
# decides. It runs from /opt/plover/gh-deploy.sh, a copy outside the checkout,
# because deploy.sh resets the checkout while this is still running.
# Accepted: "deploy <commit sha>" (7–40 hex) or "deploy main". No
# shell, no port forwarding, no other command. One deploy at a time (flock);
# every run is appended to /var/log/plover-deploy.log.
set -euo pipefail
LOG=/var/log/plover-deploy.log
REQ="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "$REQ" =~ ^deploy\ ([0-9a-f]{7,40}|main)$ ]]; then
  echo "refused: expected 'deploy <commit sha>' or 'deploy main'" >&2
  echo "$(date -u +%FT%TZ) refused: ${REQ:0:80}" >> "$LOG"
  exit 2
fi
REF="${BASH_REMATCH[1]}"
exec 9>/run/plover-deploy.lock
if ! flock -w 900 9; then
  echo "another deploy has held the lock for 15 minutes; giving up" >&2
  exit 3
fi
echo "$(date -u +%FT%TZ) deploy $REF (from GitHub Actions)" >> "$LOG"
set +e
/opt/plover/repo/observatory/deploy/deploy.sh "$REF" 2>&1 | tee -a "$LOG"
status=${PIPESTATUS[0]}
echo "$(date -u +%FT%TZ) deploy $REF exit $status" >> "$LOG"
exit "$status"
