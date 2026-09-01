# Observatory — Japan CPI

Working v1 of the Observatory data platform ([plan](../docs/plans/PLAN-JAPAN-INFLATION-OBSERVATORY.md),
[implementation plan](../docs/plans/IMPL-JAPAN-INFLATION-OBSERVATORY.md)) with two Japan CPI
datasets, both monthly, January 1970 to the latest published month, ingested directly from e-Stat:

- **cpi-jp** — national middle-class indices (~80 category series: headline, cores, ten major
  expenditure groups, and the categories beneath them)
- **cpi-jp-items** — national detailed item indices (~740 series down to individual goods and
  services: rice, electricity, mobile phone charges, ...)

plus two monetary datasets:

- **boj-assets** — Bank of Japan balance-sheet stocks and flows (JGB holdings, purchases,
  redemptions, monetary base; monthly, ¥100mn, from the Bank's time-series API, table MD09)
- **jgb-yields** — the JGB yield curve: Ministry of Finance daily constant-maturity yields,
  15 tenors (1–40Y), every business day since September 1974

and one demand dataset:

- **jnto-visitors** — monthly foreign visitor arrivals to Japan by market (54 series: the
  national total, six regional totals and named markets), from January 2003, published by
  the Japan National Tourism Organization

and one demographic dataset:

- **population-jp** — population by prefecture from the Basic Resident Register (総務省), as
  of 1 January each year: population, households and the year's register flows (births,
  deaths, in- and out-migration, naturalisations), plus population by five-year age band and
  sex — each of those split three ways, all residents / Japanese residents / foreign
  residents, for all 47 prefectures and the national total (12,720 series). Administrative
  counts, not survey estimates. Stocks are dated 1 January of the reference year; flows are
  dated to the calendar year they cover, so population(Y+1) − population(Y) equals the flows
  dated Y. **The ministry keeps only the current year online** — last year's workbook is
  deleted — so the vintage archive here is the history.
- **population-jp-history** — the long run behind it: population, age structure, foreign
  residents, households, births, deaths and migration for the same 47 prefectures back to
  **1975**, from the System of Social and Demographic Statistics (社会・人口統計体系, table A)
  via the e-Stat API. Reference dates differ by indicator and are pinned per series —
  register counts at 1 January of the following year, census/estimates at 1 October, births
  and migration as calendar-year flows — because the API carries no reference date of its
  own. The two datasets join exactly: registered residents were 124,330,690 at 1 Jan 2025
  here, which is the 123,767,642 at 1 Jan 2026 in `population-jp` plus that year's decline.
  **Needs `ESTAT_APP_ID`** (free, https://www.e-stat.go.jp/mypage/view/api); every other
  dataset works without a key.

## Run it

```bash
cd observatory
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# fetch, archive, validate, and publish the latest official data
./.venv/bin/python -m app.ingest cpi-jp
./.venv/bin/python -m app.ingest cpi-jp-items
./.venv/bin/python -m app.ingest boj-assets
./.venv/bin/python -m app.ingest jgb-yields
./.venv/bin/python -m app.ingest jnto-visitors
./.venv/bin/python -m app.ingest population-jp
./.venv/bin/python -m app.ingest population-jp-history   # needs ESTAT_APP_ID

# serve API + frontend on one port
./.venv/bin/uvicorn app.main:app --port 8007
```

Then open <http://localhost:8007>. Pages: **Overview** (headline/core/core-core tiles, main
chart with measure + range controls, major-group breakdown, provenance), **Item Explorer**
(Categories / Detailed items toggle, EN/JA search, sortable, sparklines, per-item detail with
full history), and **Methodology** (how to use, trust labels, formulas, limitations). **Population** (prefecture map on six measures, highest/lowest rankings, one prefecture's fifty-year history, and all 47 in a sortable table).

Re-run the ingest command any time; it is idempotent. A file identical to the last published
one is skipped; a file that fails validation publishes nothing and leaves the previous release
live. Every downloaded file is archived under `data/raw/` with its SHA-256.

## Deploy

`Dockerfile` + `start.sh` build a container that ingests both datasets and then serves them.
`data/` must be a persistent volume — it holds the DuckDB file and the raw source archive.

```bash
railway up            # or: docker build -t observatory . && docker run -v obs:/app/data -p 8007:8007 observatory
```

Live: <https://web-production-c9178.up.railway.app> (Railway project `observatory`, volume at `/app/data`).

Ingest runs before uvicorn binds, because DuckDB takes a single writer and the API holds
read-only connections. A cold boot on network-backed storage therefore takes ~4–5 minutes,
and a redeploy is a short outage. Refreshing data means restarting the service.

**Daily refresh (needed for jgb-yields, which publishes every business day):** add Railway's
cron template ([railway-cron](https://github.com/brody192/railway-cron)) as a second service
in the project, pointed at the web service with action `restart` and schedule `0 9 * * 1-5`
(18:00 JST, after the Ministry of Finance updates the day's file). The restart re-runs
`start.sh`, so all ingests refresh; monthly sources are simply skipped as unchanged. Nothing
about the web service itself changes — ingest stays boot-time-only, one DuckDB writer.

## Layout

```
app/
  db.py              generic core schema (datasets, sources, artifacts, releases,
                     series, observations) — nothing Japan/CPI-specific
  ingest.py          fetch -> archive -> parse -> validate -> publish runner
  adapters/estat_csv.py    shared parser for e-Stat long-run CPI CSV files
  adapters/cpi_jp.py       middle-class indices adapter: source identity,
                           validation gates, presentation roles (headline/core/groups)
  adapters/cpi_jp_items.py detailed item indices adapter (~740 series)
  api.py             dataset-scoped JSON API (/api/v1/{dataset}/...)
  tools.py           shared tool layer over the API functions — the only data
                     path for the ask agent and the MCP endpoint
  agent.py           ask (LLM Q&A) loop; off unless ASK_ENABLED is set
  mcp.py             remote MCP server (POST /mcp) for external AI clients
  main.py            FastAPI app: API + static frontend
web/
  assets/tokens.css  design tokens (single source of truth for colour, incl. dark mode)
  assets/format.js   centralised number/date/trust-label formatters
  assets/charts.js   house chart chrome for ECharts (vendored, self-hosted)
  assets/nav.js      the site header, rendered from one list of sections/pages
  index.html         Landing: what is live, what is planned (+ assets/landing.js)
  cpi.html           Macro / CPI Overview  (+ assets/overview.js)
  explorer.html      Macro / Item Explorer (+ assets/explorer.js)
  holdings.html      Equities / Cross-Shareholdings (+ assets/holdings.js)
  ownership.html     Equities / Register           (+ assets/ownership.js)
  stakes.html        Equities / 5% Filings         (+ assets/stakes.js)
  connect.html       Connect Your AI (MCP setup) · manual.html (MCP manual)
  methodology.html   Methodology / how to use
data/
  raw/               archived source artifacts (checksummed, kept forever)
  observatory.duckdb the database (gitignored; rebuild via ingest)
```

## Adding the next dataset

1. Write `app/adapters/<slug>.py` exposing `DATASET`, `SOURCE`, `DOWNLOAD_URL`, `fetch()`,
   `parse()`, `validate()`, `PRESENTATION`, and a `ValidationError`.
2. Register it in `ADAPTERS` in `app/ingest.py` and `app/api.py`.
3. Run `python -m app.ingest <slug>`.

No core schema change, no API change — that is the platform-generality rule from the plan.
If a new dataset seems to need a core migration, stop and revisit the design first.
The rule has been exercised once already: `cpi-jp-items` (dataset #2, ~740 series) was added
as an adapter plus registry entries with zero changes to the core schema or the API contract.

## Trust contract in v1

- Index levels are **Official Statistic** — exactly as published.
- YoY / MoM / 3-month-annualized carry no badge — they are computed from published index
  values, with the formula shown on every surface ("Show calculation") and in every CSV
  export header. The API still tags them `trust: "derived"`; the front end renders the
  formula instead of a label.
- Missing is `—`, never zero; gaps stay gaps in charts.
- **Point-in-time history is kept.** Every release appends what it introduced or revised
  to an append-only store, so any past view is reproducible — see below.

## API

```
GET /api/v1/catalog/datasets
GET /api/v1/cpi-jp/overview
GET /api/v1/cpi-jp/series?q=electricity
GET /api/v1/cpi-jp/observations?series=0001,0161&measure=yoy&start=2020-01
GET /api/v1/cpi-jp/contributions?start=2023-01     # pp decomposition of headline YoY by group
GET /api/v1/cpi-jp-items/breadth?threshold=2       # share of the 582 priced items rising/falling
GET /api/v1/jgb-yields/curve                       # every date x every tenor, one payload
GET /api/v1/jnto-visitors/arrivals                 # every market x every month, plus the hierarchy
GET /api/v1/population-jp/observations?series=13.all.population,13.fgn.population
                                                   # population-jp series codes are geo.segment.measure:
                                                   #   geo     '00' Japan, '01'-'47' JIS prefecture code
                                                   #   segment all | jp | fgn
                                                   #   measure population, households, births, deaths,
                                                   #           net_change, natural_change, social_change,
                                                   #           in_/out_domestic|overseas|total, ...
                                                   #           age_65_69_female, age_total_male, ...
GET /api/v1/cpi-jp/releases
GET /api/v1/catalog/health                         # is every dataset current, and did an ingest go quiet
```

Interactive docs at `/api/docs`.

### Point-in-time (vintages)

The Statistics Bureau republishes the whole history every month, and past months can
change. `observation_vintages` records what each observation was worth at each release
and is **append-only** — a revision is a new row, never an edit. Two endpoints read it:

```
GET /api/v1/cpi-jp/observations?series=0001&as_of=2026-08-20   # the data as it stood that day
GET /api/v1/cpi-jp/revisions?series=0001&period=2026-07        # how one figure has moved, release by release
```

`as_of` answers what a reader would have seen on a given date, before any later revision
— which is what makes a published chart citable years later and a backtest honest. The
release block in the response describes the vintage that was live then, and the response
echoes `as_of` so the same URL returns the same numbers next year.

The store is **change-only**: a release writes a row for a value it introduces or
changes, not for one it republishes unchanged. Publishing July 2026 CPI wrote 78 rows
against 52,110 observations, because only the new month was new. A withdrawn observation
is written as an explicit `NULL` tombstone, so `as_of` can tell "not published yet" from
"published then retracted". Series rows are upserted rather than replaced, so `series_id`
is stable for the life of the series; a series the source stops publishing is marked
`active = FALSE`, never deleted.

```bash
./.venv/bin/python -m app.vintages status   # vintages held per dataset
./.venv/bin/python -m app.vintages seed     # first vintage, from the live table
./.venv/bin/python -m app.vintages compact  # repair: drop rows restating the value in force
```

`seed` reconstructs the **first** vintage from live observations, which already carry the
release that produced them. Two things about it are load-bearing. It must run *before* an
ingest, not after — an ingest replaces the live values, and the pre-existing vintage is
then unrecoverable except by re-parsing the raw archive; `start.sh` runs it first on every
boot for that reason. And it skips any dataset that already has history: after a later
release the live table holds *that* release's values, so re-seeding would restate the whole
history as a change made by the newest release. It did exactly that once during
development — thousands of phantom revisions and a full copy per release instead of a
delta — which is what `compact` exists to repair.

`compact` deletes rows whose value equals the one already in force. Such a row asserts a
revision that never happened; removing it leaves every as-of view byte-identical, which is
the check to run before and after. `status` warns when any are present.

### Ingest health

Fail-safe ingest is silent by design, and silence looks like success. In August 2026 the
July CPI file was fetched, archived, and never published; the site served June for three
weeks and nothing said so. `/api/v1/catalog/health` reports two signals per dataset:
`stale` (the newest period served is older than the dataset's tolerance) and
`unpublished_artifact` (a file was fetched after the one currently published — always
either a validation failure or a crash). The second is the sharper of the two: in the
August case the staleness threshold had not yet been crossed, and only the orphaned
artifact revealed the problem. `start.sh` prints the same report after each boot's
ingests, so a log rule can alert on it.

## MCP (connect an AI assistant)

`POST /mcp` is a stateless remote MCP server — paste the URL into Claude (or
any MCP client) and its assistant can search series, pull history, and
decompose headline inflation through the same read-only tool layer that backs
`/api/v1`. Every response carries its trust label, its formula where the
figure is calculated, and a permanent `cite` URL on the site. Setup steps for
readers live at `/connect.html`. No key required; per-IP rate limited;
`MCP_ENABLED=0` turns it off. The protocol is implemented directly in
`app/mcp.py` (the official SDK needs Python 3.10+, local dev runs 3.9).
The user manual lives at `/manual.html`.

The cross-shareholding dataset (`/api/v1/equity/...`, built offline by
`equity/extract.py` into `data/equity.duckdb`) is exposed through the same
MCP server; its tools are listed only on servers where the database
file is present. Production receives it as `seed/equity.duckdb` baked into
the image and copied onto the volume at boot by `start.sh`.

A holding that leaves the named policy table has not necessarily been sold:
filers may move it to 純投資目的 (pure investment), which is disclosed in a
table of its own and captured in `eq_reclassified`. `/api/v1/equity/company/
{sec_code}` returns it as `reclassified`, alongside `notes` (the filing's own
footnotes to the table) and `flows` (the filing's own sale proceeds and
acquisition costs, the honest test of what actually moved).
`/api/v1/equity/reclassified` ranks filers by the value reclassified rather
than sold. Named positions also carry `pct_outstanding` — the stake as a share
of the issuer's issued shares less treasury, taken from the issuer's own annual
report *nearest* the holding's fiscal year end and therefore calculated, not
filed. It is withheld, with the reason in `pct_unavailable`, wherever a split
or share issue leaves the share base indeterminate or the result would exceed
100%: a stake measured against the wrong share base overstates it by the whole
split ratio. See `docs/METHODOLOGY-CROSS-SHAREHOLDINGS.md` §4.5–4.7 and §8.5.

`pct_outstanding` sizes a stake against the *issuer*. The `scale` block on
`/api/v1/equity/company/{sec_code}` sizes the policy book against the *filer*:
its total policy shareholdings as a share of shareholders' equity and of total
assets, with `scale_history` giving the same reading per fiscal year. The
numerator is the filing's own total for the whole policy bucket
(`eq_filing_totals`), summed across the entities a filing discloses — **not**
the sum of the named rows, which cover only the largest issues and run about
three quarters of the true total. The denominators are read from the filing's
own 主要な経営指標等の推移 table, and `equity_basis` says which accounting
figure was used: an IFRS or US-GAAP adopter stops tagging the Japanese
consolidated figure but leaves prior years in place, so a naive read falls
through to the parent-only figure and reads several times too high. A
parent-only denominator is labelled, never silently mixed with a group one.
See §4.8–4.9 and §8.7.

### Boards and pay (`/api/v1/equity/governance/...`)

The third surface, from the same annual reports and the same DuckDB file
(`equity/board_extract.py`; see `docs/METHODOLOGY-BOARDS-AND-PAY.md`):

| Endpoint | What it returns |
| --- | --- |
| `/governance/summary` | coverage first, then market aggregates — board size, director age, 70+ share, female ratio, pay per officer. `?listed=true` for listed filers only |
| `/governance/company/{sec_code}` | one filing: the board, the officer-pay table, the named individuals |
| `/governance/history?sec_code=` | that company across every extracted fiscal year |
| `/governance/screen?metric=` | ranked cross-sections; `/screen/metrics` lists them |
| `/governance/named` | highest-paid named individuals |
| `/governance/years` | fiscal years available |

Three things the responses carry because a reader will otherwise get them
wrong. **Named pay is 連結報酬等 — consolidated**, a different basis from the
officer-category table, so the two are never netted (`pay_basis`, and
`named_exceeds_category` where the arithmetic proves it). **Pay components need
not sum to the filed total** — filers disagree on whether 非金銭報酬等 is
additive — so the total is the published number and `components_reconcile`
says whether that row adds up. **`pay_consistency_flag`** marks a filing whose
per-head pay implies an officer above the ¥100m individual-disclosure
threshold while naming nobody: the filer's own figures contradict each other,
and the numbers are still published exactly as filed.

Two endpoints exist for the page rather than the API contract:
`/governance/companies` (search scoped to this dataset — a company can have a
board here and no policy holdings next door) and `/governance/trend`, a matched
panel of the companies with a clean filing in *every* year of the window, one
filing per company per year. Coverage differs by fiscal year, so an unmatched
average would move because the population moved.

The router is registered ahead of the holdings router in `app/main.py` so the
longer `/equity/governance/` prefix is matched first.

The page is `web/governance.html` (**Equities → Boards & Pay**): a market view
— coverage strip, the panel trend chart with a measure picker, ten screens — and
a company view at `?c={sec_code}` with the board, the pay table, the individuals
disclosed and a five-year record. The URL encodes the measure, the screen and the
scope, so any view is citable.

### Buybacks (`/api/v1/equity/buyback/...`)

The fourth surface, and the only one not built from annual reports: EDINET type
220, the **monthly** 自己株券買付状況報告書 a company files while a buyback runs
(`equity/buyback.py`, parser `bb-2`). Announcement → execution → cancellation
all come out of that one filing.

| Endpoint | What it returns |
| --- | --- |
| `/buyback/summary` | coverage, then the market aggregates: yen authorised, yen bought, retirements, and the lifecycle split |
| `/buyback/monthly` | yen bought and yen retired by reporting month — the chart feed; `partial_month` marks the archive's edges |
| `/buyback/programs` | one row per authorisation: announced, executed, unspent. `?lifecycle=`, `?sort=` (see `/programs/sorts`), `?q=` |
| `/buyback/retirements` | filing-months in which shares were cancelled outright |
| `/buyback/company/{sec_code}` | one company: its authorisations, its month-by-month buying, its treasury and retirements |
| `/buyback/companies` | search scoped to companies that filed a buyback report |

Four things the responses carry because a reader will otherwise get them wrong.
**Authorised is a ceiling a board voted for, not spending** — never summed or
netted against what was bought. **The filer publishes its own progress
percentage**, which is official as filed; `completion_pct` is ours and is
returned alongside it, never instead. **A closed window is not an abandoned
programme** — `expired_unspent` means the acquisition period ended with the
authorisation unspent, while a formal 取得中止 is announced on TDnet, which this
dataset does not carry. **Retiring shares (消却) is a different act from buying
them**: bought shares may sit in treasury for years, so retirements are reported
on their own and never netted against purchases.

`unspent_yen` is empty, not zero, where the filing states an authorisation but
no cumulative — unknown is not nothing. `dates_inconsistent` marks a filing
whose own dates put the resolution after the start of the period it authorises
(filers mistype the year); the row is published exactly as filed, and such a
filing also splits one programme into two rows, because the resolution date is
what identifies an authorisation.

Coverage is capped by the source, permanently: **EDINET purges type 220 filings
after about a year**, so the archive begins at 2025-08-12 and no earlier filing
is retrievable by anyone. Everything before that exists only where somebody was
already capturing — which is the whole argument for the daily capture job.

The page is `web/buyback.html` (**Equities → Buybacks**): a market view —
coverage strip, bought-versus-retired by month, the announced-versus-executed
ranking with a lifecycle filter — and a company view at `?c={sec_code}` with
each authorisation, the month-by-month record and the treasury table. The URL
encodes the filter and the ranking, so any view is citable.

### Shareholder register (`/api/v1/equity/ownership/...`)

The reverse of cross-shareholdings: who holds each listed company. Extracted
from the ownership section of the same annual reports (`equity/ownership_extract.py`,
parser `own-1`) — 大株主の状況, the named holders at the top of the register,
and 所有者別状況, the whole register split by investor category. Methodology:
`docs/METHODOLOGY-OWNERSHIP.md`.

| Endpoint | What it answers |
| --- | --- |
| `/ownership/summary` | coverage first, then the market aggregates: foreign ownership, the share held through nominees, the register split |
| `/ownership/company/{sec_code}` | one filing: the named holders, the investor-type split, and the company's year-by-year record |
| `/ownership/holder/{key}` | the reverse view — every top-ten register this holder appears in. `key` is an EDINET code where one resolved, else the filed name |
| `/ownership/holders` | who appears in the most registers; nominee accounts excluded unless `?include_nominees=true` |
| `/ownership/screen?metric=` | companies ranked on one register metric; `/screen/metrics` lists them |
| `/ownership/companies?q=` | search scoped to companies with an extracted register |
| `/ownership/years` | fiscal years available |

Two disclosures travel with every number, because without them the data is
actively misleading. **The register is not beneficial ownership**: two nominee
trust banks sit at the top of almost every register in Japan holding for index
funds and pension money they do not own, and a fifth of all named rows are
custody accounts. Every row carries a `holder_kind` — **ours, derived from the
name, never a filed field** — and the holder ranking excludes nominees by
default because that is the ranking that means something. **The two percentage
columns have different denominators**: a register row's ratio is of shares in
issue *excluding* treasury (the filing's own denominator), while the
investor-category percentages are of *all* issued shares. They are never netted.

Percentages are stored as percent, converted from the XBRL fraction at the
precision the filing states. Gates recompute the filer's own totals — category
units against the 計 row exactly, category and register percentages inside what
the filing's own printing precision allows, and no holder above shares in issue.
A filing that fails one is published anyway, marked `partial`, with the failure
in `detail`.

The page is `web/ownership.html` (**Equities → Register**): a market view —
coverage strip, the holders appearing in the most registers with a nominee
toggle, and screens on foreign ownership, individuals, nominee share and
concentration — plus a company view at `?c={sec_code}` with the register, the
investor-type composition and the year-by-year record, and a holder view at
`?h={edinet_code}`. The URL encodes the screen, its direction and the nominee
toggle, so any view is citable.

### 5% filings (`/api/v1/equity/stakes/...`)

The fast tape: EDINET types 350 and 360, the large-shareholding reports
(`equity/lvh_extract.py`, parser `lvh-1`). Anyone crossing 5% files within five
business days and again on every one-point move, so this names an accumulating
holder before the annual report does. Methodology:
`docs/METHODOLOGY-5PCT-FILINGS.md`.

| Endpoint | What it answers |
| --- | --- |
| `/stakes/summary` | coverage, the current groups at or above 5%, and how many reports state an important-proposal act |
| `/stakes/recent` | the tape, most recently filed first; `?activist=true`, `?report_type=`, `?min_ratio=`, `?min_change=` |
| `/stakes/company/{sec_code}` | who has filed 5% on this company — each group's latest report with its members, plus every report on the company |
| `/stakes/holder/{edinet_code}` | one holder's book: its latest position per issuer, and every report |
| `/stakes/holders` | the most active filers, consolidated into groups by default; `?by=entity`, `?filer_type=`, `?group=`, `?activist=true` |
| `/stakes/holder-types` | the filer types and how many filing entities carry each |
| `/stakes/companies?q=` | search scoped to issuers a report names |

Unlike every other extractor here the source is the **t1 inline-XBRL package** —
EDINET publishes no CSV rendition of this form — and the scan is stack-based,
because inline XBRL nests and a regex silently swallows the facts inside a text
block (measured: the holding ratio lost in 36% of filings).

Four things the responses carry because a reader will otherwise get them wrong.
**A report is an event, not a position**: each is a snapshot at its own trigger
date, and a group that falls below 5% files once more and then stops. **The
group is the unit and is not the sum of its members** — the form deducts claims
between joint holders, and a member that has just left is still described with
last-report figures only, so `in_group_total` says who counts. **重要提案行為 is
not asked on every form**: only the general first-schedule form carries the
field, so `proposal_asked` is false on change reports and on the special form,
and a null answer never means "no". **The ratio is the statutory one**, whose
denominator adds the holder's own potential shares, so it does not equal
`shares_held / shares_outstanding`.

**Filers carry two derived labels**, both applied at serve time in
`app/filer_labels.py` (the extractor stores only what the filing says).
`filer_type` is read from the filer's own 事業内容 plus the filed 法人/個人 flag
and types 99.3% of the 1,340 filing entities — no filing states a category such
as "hedge fund" and none is invented. `group` consolidates a family's filing
entities, and it is curated rather than derived because no document names the
parent: BlackRock files under 16 EDINET codes, Fidelity 13, Nomura 8. A group's
issuer count is the distinct companies its entities cover between them, not the
sum of theirs; a joint venture is its own group, never counted inside either
parent.

`filed_date` is EDINET's own submission record rather than the date printed on
the cover page, which the filer types and occasionally gets wrong (`cover_date`
keeps that one); the tape is ordered by it, because a change report routinely
restates the date the holder first crossed 5% years earlier.

The page is `web/stakes.html` (**Equities → 5% Filings**): a market view — the
tape with filters for important proposals, new 5% holders and moves of a point
or more, plus the most active filers — and a company view at `?c={sec_code}`
with each disclosed group, its members and its stated purpose as filed, and a
holder view at `?h={edinet_code}`.

Companies in that dataset are named in Japanese in the filings, but every
annual report states the filer's own English name on its cover page, so both
names are as filed. Every name-bearing response carries the English one
(`name_en`, `filer_name_en`, `held_name_en`, `holder_name_en`) alongside the
Japanese, and `/companies?q=` matches code, Japanese name and English name
alike. EDINET's filer registry is the fallback for a company that files no
annual report of its own. See `docs/METHODOLOGY-CROSS-SHAREHOLDINGS.md` §5.1.

Quick check:

```
curl -X POST localhost:8007/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
