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
- **Backfill complete (2026-08-12).** The full reachable EDINET window
  `2021-08-09..2026-08-06` finished with
  `archived:174523  skipped(existing):6073  failed:1  list-failures:0` —
  **178,690 documents, 33.5GB, 1,214 filing dates**, plus 1,304 daily indexes.
  The single failure is `2022-06-30 S100OJ8Y t5` (EDINET served a 154-byte
  non-zip); the zip-magic check caught it and the document's other package is
  archived.
- **Now in daily mode:** `CAPTURE_ARGS=--days 7`, cron `0 12 * * *`
  (12:00 UTC = 21:00 JST, after the JST business day), restart policy NEVER.
  The trailing 7-day window means a missed day heals itself on the next run.
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

## M2b — TDnet daily capture (`tdnet_capture.py`)

The fast tape: earnings releases (決算短信 + XBRL), management **forecast
revisions**, buyback/dividend resolutions, deal announcements — **TDnet deletes
after ~31 days**, so this archive can only ever start from its first run
(2026-08-10; nothing before that date is recoverable). No official API — the
collector parses the public daily list pages (`I_list_NNN_YYYYMMDD.html`,
100 rows/page, 404 past the last page = end-of-list). Captures **everything**
(no title filtering — fragile), storing raw list HTML + parsed JSON + every
PDF and XBRL zip under `tdnet/` (same bucket in S3 mode, `data/raw/tdnet/`
locally), same manifest/SHA-256/idempotency discipline as `capture.py`.

```bash
../observatory/.venv/bin/python tdnet_capture.py --days 31   # rescue window
```

Cloud: service `tdnet-capture-job`, same image (`CAPTURE_CMD=tdnet_capture.py`
selects the collector). Expect ~2–4GB/yr quiet months, much more in earnings
seasons (a peak day is ~1,700 disclosures). If a run suddenly reports zero
disclosures on a weekday, TSE likely redesigned the page — repair the parser.

## BOJ vintage snapshots (`boj_capture.py`)

The BOJ API never deletes — but it **overwrites on revision** (money stock,
Flow of Funds, Tankan revise heavily). This job takes a dated, complete
snapshot of every database in the BOJ Time-Series Data Search (49 DBs:
metadata + full history of every series, batched — the API caps requests at
<1,250 series and weekly variants must not be mixed in one request), stored
under `boj/{date}/{db}/` in the bucket (`data/raw/boj/` locally). Monthly
cron (service `boj-capture-job`, 1st 23:00 JST): each run is one vintage;
the revision history accumulates from 2026-08-10.

Obligations when this data is served publicly: notify BOJ's Research and
Statistics Dept by email, and display the credit line — *"This service uses
the API provided by the 'Bank of Japan Time-Series Data Search.' The Bank of
Japan does not guarantee the content of the service."*

**The first cloud vintage (`boj/2026-08-10/`) is partial and non-canonical.**
It ran on an image built before two fixes (exact-FREQUENCY grouping and
`%`-encoding of series codes), so 13 PR01/PR02 batches are missing and its
data files use a coarser frequency slug in their names than every later
vintage will. Left untouched on purpose — a stored vintage is never
back-filled or renamed (P0). The **complete** 2026-08-10 snapshot (1,879
objects, 50 DBs, 331,235 series, 627MB) exists on the laptop under
`data/raw/boj/`. Canonical cloud vintages begin with the 1 Sep 2026 cron run.

### Operational note: a cron'd service ignores manual deploys

Once `cronSchedule` is set, Railway marks a manual `redeploy`/`serviceInstanceDeployV2`
as SUCCESS but **does not execute the container** — it waits for the schedule
(verified 2026-08-10: the deploy sat 5h with zero log output, while
`tdnet-capture-job` fired normally at its 12:30 UTC slot). To force a run,
clear the cron, deploy, then restore it:

```bash
railway api 'mutation { serviceInstanceUpdate(serviceId: "<id>", environmentId: "e97325e3-a9df-4d1b-83ef-c5945861bc86", input: {cronSchedule: null}) }'
railway api 'mutation { serviceInstanceDeployV2(serviceId: "<id>", environmentId: "e97325e3-a9df-4d1b-83ef-c5945861bc86") }'
# …then set cronSchedule back once the run has started
```

## M4 — full-universe extraction (`extract.py --all --source s3`)

The laptop archive holds a fraction of the filings; the five-year history is in
the bucket. `--source s3` discovers filings from the object listing, caches the
1,261 daily lists locally (they carry edinetCode/secCode/periodEnd), and fetches
in parallel while DuckDB writes stay single-threaded.

```bash
# credentials: the same EDINET_S3_* vars the capture job uses
lsof -ti:8007 | xargs kill          # DuckDB counts the API's reader as a
../observatory/.venv/bin/python extract.py --all --source s3 --workers 16
```

**Stop the local API server first.** DuckDB treats the serving process's
read-only connection as a conflicting lock, so the extractor fails on connect
while `uvicorn` is up. Production is unaffected — separate processes, separate
boxes.

Provenance: the SHA-256 stored on each filing is computed from **the bytes
actually parsed**, not copied from a manifest field, so every row's hash is
verifiable against the archive. (The first S3 run shipped null hashes because
discovery carried no manifest — caught by the company page, which renders the
hash.)

Multi-year needs no schema change: one doc_id and one period_end per filing.
The API keeps every cross-sectional surface on **one filing per company** —
summing book value across five years would overstate the total several-fold —
with `?year=` to pin a fiscal year and `/history` for the year-on-year series.

## Monitoring — dead-man's-switch (`heartbeat.py`)

The dangerous failure is a job that **stops running**: a cron that quietly
stops firing produces no error, no log and no alert — the archive just stops
growing and nobody notices for weeks. So the alert is inverted: each job POSTs
its summary line to `HEARTBEAT_URL` when it finishes, and the monitor alerts
when a ping **fails to arrive**. Silence is the alarm.

- `heartbeat.ping(summary, failed=…)` never raises — a dead monitor must not
  be able to kill a capture — and is a **no-op when `HEARTBEAT_URL` is unset**,
  so local runs stay silent.
- What counts as a failure ping (`…/fail`): EDINET/TDnet only when a *list*
  fetch failed (a whole day may be missing); individual document failures are
  routine and heal on the next trailing-window run. BOJ on any failed batch,
  since it runs monthly and a missed batch is missing series in a vintage that
  can never be re-taken for that date.

Setup — one check per job on any ping-URL monitor (healthchecks.io free tier
covers this), then:

```bash
railway variables --service edinet-capture-job --set "HEARTBEAT_URL=https://hc-ping.com/<uuid>" --skip-deploys
railway variables --service tdnet-capture-job  --set "HEARTBEAT_URL=https://hc-ping.com/<uuid>" --skip-deploys
railway variables --service boj-capture-job    --set "HEARTBEAT_URL=https://hc-ping.com/<uuid>" --skip-deploys
```

Grace periods: EDINET and TDnet daily → ~26h. BOJ monthly → ~35 days.

## M1 — extraction prototype (`m1/`)

See [m1/README.md](m1/README.md): 7 financials, 817 named holdings, 100% entity
match, reconciliation gates, and the extraction traps M3 must inherit.
