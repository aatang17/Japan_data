# equity/ — product #2: Japanese equities governance data

Documents-and-events data (cross-shareholdings, 5% filings, buybacks), deliberately
**outside** the macro core schema. Plan:
[docs/plans/PLAN-CROSS-SHAREHOLDING-DB.md](../docs/plans/PLAN-CROSS-SHAREHOLDING-DB.md).

## M2 — daily capture (`capture.py`)

The compounding archive. EDINET's list API reaches back only ~5 years and files are
deleted 10 years after filing — what we don't capture, nobody can rebuild later.
**Capture ≠ parse:** this job only archives raw files; extraction improves separately
against the already-captured archive.

```bash
../observatory/.venv/bin/python capture.py                  # trailing 7 days
../observatory/.venv/bin/python capture.py --days 30        # wider catch-up
../observatory/.venv/bin/python capture.py --start 2026-06-01 --end 2026-06-30
```

- **Captured types** (verified empirically; expanded 2026-08-07): periodic reports
  120/130 有報 + 160/170 半期 · extraordinary reports 180/190 (M&A resolutions, AGM
  per-proposal voting results) · tender-offer family 240/250/270/290/300 (terms,
  bumps, results, target board opinion) · capital raises 030/040 (third-party
  allotment red flag) · 5% family 350/360 · buybacks 220. Skipped on purpose:
  135 確認書, 235 内部統制 (no analytical content). For periodic reports both the
  full XBRL (type=1) and the CSV package (type=5, extractor input) are stored.
- **Layout:** `data/raw/edinet/lists/YYYY-MM-DD.json` (full daily index) ·
  `data/raw/edinet/docs/YYYY-MM-DD/{docID}_t{1|5}.zip` · append-only
  `manifest.jsonl` (SHA-256, bytes, filer, status).
- **Idempotent & self-healing:** re-runs skip anything the manifest records as ok;
  the trailing `--days 7` window means a missed day is picked up automatically.
  Failures are logged and retried next run. Zip magic verified before recording;
  writes are atomic (`.part` then rename). Lock file prevents concurrent runs.
- **Polite client:** 0.7s throttle between downloads — EDINET restricts heavy users.
- Key from `EDINET_API_KEY` env or `../observatory/.env` (gitignored).
- `equity/data/` is gitignored — the archive is data, not code.

### Cloud capture (Railway — the durable home, set up 2026-08-06)

- **Bucket `edinet-archive`** (S3-compatible, Singapore region) in the `observatory`
  Railway project. Same layout as local, except the manifest is one small JSON object
  per document under `meta/` (S3 has no append).
- **Service `edinet-capture-job`** runs the image `ghcr.io/aatang-gsa/edinet-capture`
  (public; built from `Dockerfile` here — code only, no secrets; keys live in Railway
  env vars `EDINET_API_KEY`, `EDINET_S3_*`). `railway up` was broken ("prefix not
  found"), hence the image route: rebuild+push with
  `docker build --platform linux/amd64 -t ghcr.io/aatang-gsa/edinet-capture:latest . && docker push …`,
  then `railway redeploy --service edinet-capture-job --yes`.
- **Currently in backfill phase:** `CAPTURE_ARGS=--start 2021-08-09 --end 2026-08-06`
  (the full reachable EDINET window), cron intentionally OFF so only one polite client
  runs, restart policy NEVER. Expect ~3 days runtime, ~15–25GB.
- **When the backfill completes** (deployment status SUCCESS/exited, log line
  `capture 2021-08-09..…`), flip to daily mode:

  ```bash
  railway variables --service edinet-capture-job --set "CAPTURE_ARGS=--days 7" --skip-deploys
  railway api 'mutation { serviceInstanceUpdate(serviceId: "9699a669-dabb-42b0-8b71-a8bf183d1d89", environmentId: "e97325e3-a9df-4d1b-83ef-c5945861bc86", input: {cronSchedule: "0 12 * * *", restartPolicyType: NEVER}) }'
  railway redeploy --service edinet-capture-job --yes
  ```

  (12:00 UTC = 21:00 JST, after the JST business day.)
- The laptop archive (`data/` here) is now the **backup copy**; the launchd agent
  below is optional redundancy.

### Scheduling (macOS)

launchd (not cron: it fires after wake if the Mac was asleep). One-time install:

```bash
cp equity/launchd/com.japanobservatory.edinet-capture.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.japanobservatory.edinet-capture.plist
```

Runs daily 20:00 local, logs to `equity/data/capture.log`. Remove with
`launchctl unload …` + delete the plist. **Laptop scheduling is interim** — the
durable home is a scheduled job next to the production volume (Railway), decided
separately.

## M1 — extraction prototype (`m1/`)

See [m1/README.md](m1/README.md): 7 financials, 817 named holdings, 100% entity
match, reconciliation gates, and the extraction traps M3 must inherit.
