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

## M1 — buyback execution prototype (`buyback_m1/`)

EDINET type 220. HTML table parsing, gated by recomputing the filer's own stated
progress percentage.

## M1 — boards and pay prototype (`board_m1/`)

See [board_m1/README.md](board_m1/README.md): the gates, and the eight extraction traps
the production extractor inherits. Superseded for data by M2 below.

## M2 — boards and pay, full universe (`board_extract.py`)

Same annual-report `type=5` package as the holdings extractor — **no new capture**.
Writes `eq_board`, `eq_pay_category`, `eq_pay_named` and `eq_company_year` into the
same equity DuckDB. Plan: [PLAN-BOARD-AND-PAY.md](../docs/plans/PLAN-BOARD-AND-PAY.md) ·
methodology: [METHODOLOGY-BOARDS-AND-PAY.md](../docs/METHODOLOGY-BOARDS-AND-PAY.md).

```bash
lsof -ti:8007 | xargs kill          # DuckDB counts the API's reader as a lock
../observatory/.venv/bin/python board_extract.py --all --source s3 --workers 16
../observatory/.venv/bin/python board_extract.py --docs S100XV05,S100VIG1   # fix a subset
```

Full run (2026-08-23): **21,099 filings, fiscal periods ending 2020-12-31 → 2026-05-31**
— 195,097 board seats, 61,968 pay rows, 5,605 named individuals paid on a consolidated
basis, **99.4% clean among listed filers**.

It deliberately does **not** write `eq_filings`: that row is the holdings extractor's
vintage record and two writers would fight over `status`. `eq_company_year` carries this
dataset's own status and the SHA-256 of the bytes it parsed.

## M2 — shareholder register (`ownership_extract.py`, parser `own-1`)

大株主の状況 + 所有者別状況 from the same annual-report `type=5` package the
holdings and boards extractors already read — **no new capture**. Writes
`eq_major_shareholders`, `eq_own_category` and `eq_own_filings`. Plan:
[PLAN-CROSS-SHAREHOLDING-DB.md](../docs/plans/PLAN-CROSS-SHAREHOLDING-DB.md) ·
methodology: [METHODOLOGY-OWNERSHIP.md](../docs/METHODOLOGY-OWNERSHIP.md).

```bash
lsof -ti:8007 | xargs kill          # DuckDB counts the API's reader as a lock
../observatory/.venv/bin/python ownership_extract.py --all              # local
../observatory/.venv/bin/python ownership_extract.py --all --source s3 --workers 16
```

Local-archive run (2026-09-01, `own-1`): **2,503 filings → 2,445 clean · 13
partial · 45 unsupported form** — 24,353 named holders, 16,321 category rows,
7,748 holders entity-matched, **5,294 rows classified as custody accounts**.

Traps this parser exists to survive:

- **The register is not ownership.** A fifth of all named rows are nominee trust
  banks and global custodians holding for someone else. `holder_kind` is ours,
  derived from the name, and the custodian test runs on the name with its
  bracketed qualifier stripped — that bracket is usually the holder's 常任代理人,
  and GOVERNMENT OF NORWAY（常任代理人 シティバンク）is Norway's own money, not a
  Citibank account.
- **A natural person is never entity-matched.** EDINET codes individuals who
  file 5% reports, so a name lookup would return a hit and a collision would
  attribute one person's holdings to another.
- **Filers truncate as often as they round.** Ono prints 1.80 for an exact
  1.8064 and its 計 is the truncated sum; Toyota's ten rows sum two hundredths
  above its 計. The percentage gates therefore allow a full last digit per row
  below the filed total and half a digit above it.
- **Past row 15 the member context carries the filer's own namespace**
  (`…E03738-000No16MajorShareholdersMember`) — the same trap the holdings and
  boards extractors hit.
- **A holder's share count is tested against ALL share classes.** TEPCO's rescue
  fund and Mitsubishi Corp's Chiyoda stake are largely preferred shares;
  measuring them against the ordinary count reports a holder owning more of a
  company than exists.

## M1 — 5% filings (`lvh_extract.py`, parser `lvh-1`)

EDINET types 350/360, the 大量保有報告書 family — **no new capture**, the daily
job has banked them since 2021. The only extractor here that reads the **t1
inline-XBRL** package, because EDINET publishes no CSV rendition of this form.
Writes `eq_lvh_filings` + `eq_lvh_holders`, including each holder's stated
事業内容 and 職業 — the inputs the serve-time filer-type labels read.
Methodology:
[METHODOLOGY-5PCT-FILINGS.md](../docs/METHODOLOGY-5PCT-FILINGS.md).

```bash
lsof -ti:8007 | xargs kill
../observatory/.venv/bin/python lvh_extract.py                       # local
../observatory/.venv/bin/python lvh_extract.py --source s3 --workers 16
```

Local-archive run (2026-09-01, `lvh-1`): **3,893 reports filed 2026-05-29 →
2026-08-06 → 3,850 clean · 43 partial** — 1,276 issuers, 817 filing groups,
8,287 holder rows, **150 reports stating a 重要提案行為 act**.

Traps this parser exists to survive:

- **Inline XBRL nests, so the scan cannot be a regex.** A text-block fact wraps
  the tagged facts inside it; a non-greedy pattern closes the outer element on
  an inner end tag and resumes past it, losing both. Measured: the holding ratio
  vanished in 36% of filings before the stack-based scanner.
- **The answer to 重要提案行為 lives in one of two elements** — the base one when
  an act is stated, the `…NA` twin when none is — and the field does not exist
  at all on the change report or the special form. `proposal_asked` distinguishes
  "not asked" from "asked and left blank"; null never means no.
- **A departing joint holder is still described in the filing.** Nomura's report
  on Nissui details three holders and its group total is the sum of two.
- **Numbers are taken only when the tag holds a number and nothing else.**
  Filers leave tags open over whole tables, and the single number inside is
  often a different line of the form — Nomura's borrowings tag contains its
  total funding.
- **A holder's EDINET code is sometimes the ISSUER's.** A holder with no
  registration of its own gets the target's code from the filer's XBRL tool —
  Be Brave filed on three companies under three different targets' codes. The
  guard rejects a holder code equal to the issuer's when the names differ (9 of
  8,287 rows) and falls back to `name_key`, the folded name.
- **Dates lie in both directions.** The cover-page filing date is filer-typed
  (a Trusco corrector dated a 2026 filing 2028), so EDINET's own submission
  record is used and the printed date kept beside it; and 提出義務発生日 on a
  change report is routinely the date the holder first crossed 5%, years back.

## M2 — buyback lifecycle (`buyback.py`, parser `bb-2`)

EDINET type 220, the monthly 自己株券買付状況報告書 — **no new capture**, the same
documents the daily job already banks. Parser `bb-2` reads the whole lifecycle out
of the one filing:

| Table / view | What it holds |
| --- | --- |
| `eq_buyback_filings` | one row per filing: filer, submitted, as-of, SHA-256 of the bytes parsed, gate status |
| `eq_buyback_programs` | one row **per resolution table** — resolution date, **acquisition window (取得期間)**, authorised shares/yen, the month's buying, cumulative, the filer's stated 進捗状況 |
| `eq_buyback_treasury` | the 【株式の処理状況及び保有状況】 block — shares **retired (消却)**, disposed by category, and month-end 保有自己株式数 against 発行済株式総数 |
| `eq_buyback_lifecycle` (view) | one row per authorisation, from its latest filing: `completed` · `expired_unspent` · `awaiting_final` · `running` · `unknown` |
| `eq_buyback_cancellations` (view) | filing-months with a non-zero retirement |

Two independent gates, neither of which we invented — the filing publishes both
sums: cumulative ÷ authorised must return the filer's own 進捗状況, and the four
disposal categories must recompute the filer's own 合計.

```bash
lsof -ti:8007 | xargs kill          # DuckDB counts the API's reader as a lock
../observatory/.venv/bin/python buyback.py --source local          # laptop archive only
../observatory/.venv/bin/python buyback.py --source s3 --workers 12 # whole bucket
```

**Credentials** for `--source s3` are the same `EDINET_S3_*` vars the capture job
uses, held as Railway env vars on `edinet-capture-job` (project `observatory`,
already linked from this repo — `railway status` to confirm, `railway link` if not):

```bash
# writes the secrets to a file OUTSIDE the repo; --kv prints raw values
railway variables list --service edinet-capture-job --kv \
  | grep '^EDINET_S3_' > ~/.edinet-s3.env
chmod 600 ~/.edinet-s3.env
set -a; . ~/.edinet-s3.env; set +a       # ENDPOINT / KEY_ID / SECRET / BUCKET / REGION
../observatory/.venv/bin/python buyback.py --source s3 --workers 12
```

Full archive run (2026-08-24, parser `bb-2`): **6,236 filings · 1,248 companies ·
submitted 2025-08-12 → 2026-08-21** — 6,431 programme rows, **1,765 authorisations**,
6,236 treasury rows. Execution gate **5,905/6,027 = 98.0%** of the rows it could
check; disposal gate **855/862 = 99.2%**. 211 filing-months of retirements:
**5.45bn shares, ¥10.99tn**. Lifecycle: 766 completed · **444 window closed with the
authorisation unspent** · 280 running · 33 awaiting the final report · 242
unclassifiable. Windows parsed on 6,401/6,431 rows; 13 rows have no resolution date
because the filer left the form blank.

The unspent leg is the one no free source answers: SoftBank left ¥169.7bn of a ¥500bn
authorisation unbought when the window closed, Daiichi Sankyo ¥108.2bn of ¥200bn, and
**Fanuc bought ¥272mn against a ¥50bn authorisation — 0.5%, filed identically every
month for a year, gate clean each time.**

**The AGM path is finally exercised.** M1 warned it had never parsed a populated
株主総会決議 table; the full archive holds three (Popla, Convano ×2), all clean.

### Traps this parser exists to survive

Beyond the three `bb-1` defects above, one more that crashes a naive run:

- **Filers type dates that do not exist.** TENTIAL (S100X8KV) filed 2025年11月31日 as
  its as-of date. There is no honest way to store it and guessing month-end would
  invent a fact, so `scan_dates()` drops it and records
  `filer wrote impossible date(s): 2025-11-31` on the filing row. One filing in 6,236.

**Horizon, permanently.** EDINET purges type 220 after ~12 months — nothing before
**2025-08-12** is retrievable by anyone. The announcement press release (rationale,
% of shares outstanding, and any *abandonment* of a live programme) is TDnet-only,
PDF, no XBRL, ~31-day retention: that history starts at our capture, 2026-07-13.

## M2 — facilities & land (`facility_extract.py`, parser `fac-6`)

主要な設備の状況 from the same annual reports — **no new capture**, but a
different package: the t5 CSV flattens text blocks and destroys the table, so
this extractor reads the **t1 honbun HTML** (see
[METHODOLOGY-FACILITIES.md](../docs/METHODOLOGY-FACILITIES.md)). Writes
`eq_fac_filings` + `eq_facilities`; city-level addresses geocoded to
municipality centroids via `gazetteer_municipalities.csv` (static, Geolonia
CC BY 4.0 — no external API). Prototype and the full trap catalogue:
[facility_m1/](facility_m1/).

```bash
lsof -ti:8007 | xargs kill          # DuckDB counts the API's reader as a lock
../observatory/.venv/bin/python facility_extract.py                  # local
../observatory/.venv/bin/python facility_extract.py --source s3 --workers 12
```

Local-archive run (2026-08-28, `fac-6`): **2,243 filings → 1,949 clean (87%) ·
246 partial · 48 without a parseable table** — 27,244 facility rows, 69%
geocoded. Clean filings disclose **¥55.1tn of land at book over 4,325 km²**.
`fac-6` cracked the big real-estate layouts — Mitsui Fudosan, Mitsubishi
Estate, Sumitomo Realty, Nomura RE, JR West, Keihan and the regional banks
are now clean: rowspan-grouped facilities (buildings sharing one parcel) are
one record; 帳簿価額-in-the-parent land columns are money, ㎡-leaf columns
never are; paginated building lists with one grand 合計 count once; ditto
unknown asset classes (美術骨董品) fold into other. Every fix was verified by
a fac-5-vs-fac-6 diff over all 2,243 filings — the ~17 filings the stricter
parser newly marks partial are genuine filer-side anomalies (e.g. a printed
合計 of 707 against parts summing 707,245) that fac-5 lumped into unverified
rows.
Two gates, both recomputing the filer's own numbers: row sums vs the filed
合計, and facilities land ≤ consolidated balance-sheet land (own + trust).
Cross-company surfaces use clean filings only. The five-year S3 run is the
next step; the extractor takes `--source s3` unchanged.

The geocoder matches ヶ/ケ as one character (袖ケ浦市 = 袖ヶ浦市; fixed
2026-08-28 and backfilled in place — coordinates are derived values, not
filed figures). English municipality names and the derived use category are
serve-time joins in `observatory/app/facility_labels.py`, not extractor
output; see `docs/METHODOLOGY-FACILITIES.md`.

## M3 — rental-property fair value (`rental_extract.py`, parser `rent-1`)

The 賃貸等不動産 note: carrying amount vs year-end fair value (時価) of
rental/investment property, the one filed market value for real estate.
Writes `eq_rental_filings` + `eq_rental_tables`. Two layouts (labels-in-rows
and labels-in-headers), consecutive-year tables recognised by the rolling
balance; gate is 期首 + 増減 = 期末. Local run (2026-08-28): **2,243 filings →
551 clean · 451 immaterial · 1,196 no note (incl. IFRS) · 10 partial · 35
unparsed** — ¥27.2tn carrying, ¥47.2tn fair, ¥20.0tn disclosed unrealized
gain. Same usage flags as the facilities extractor.
