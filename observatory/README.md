# Observatory — Japan CPI

Working v1 of the Observatory data platform ([plan](../docs/plans/PLAN-JAPAN-INFLATION-OBSERVATORY.md),
[implementation plan](../docs/plans/IMPL-JAPAN-INFLATION-OBSERVATORY.md)) with two Japan CPI
datasets, both monthly, January 1970 to the latest published month, ingested directly from e-Stat:

- **cpi-jp** — national middle-class indices (~80 category series: headline, cores, ten major
  expenditure groups, and the categories beneath them)
- **cpi-jp-items** — national detailed item indices (~740 series down to individual goods and
  services: rice, electricity, mobile phone charges, ...)

## Run it

```bash
cd observatory
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# fetch, archive, validate, and publish the latest official data
./.venv/bin/python -m app.ingest cpi-jp
./.venv/bin/python -m app.ingest cpi-jp-items

# serve API + frontend on one port
./.venv/bin/uvicorn app.main:app --port 8007
```

Then open <http://localhost:8007>. Pages: **Overview** (headline/core/core-core tiles, main
chart with measure + range controls, major-group breakdown, provenance), **Item Explorer**
(Categories / Detailed items toggle, EN/JA search, sortable, sparklines, per-item detail with
full history), and **Methodology** (how to use, trust labels, formulas, limitations).

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
and a redeploy is a short outage. Refreshing data currently means restarting the service.

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
- One live vintage plus archived raw artifacts per run; full vintage history is roadmap.

## API

```
GET /api/v1/catalog/datasets
GET /api/v1/cpi-jp/overview
GET /api/v1/cpi-jp/series?q=electricity
GET /api/v1/cpi-jp/observations?series=0001,0161&measure=yoy&start=2020-01
GET /api/v1/cpi-jp/contributions?start=2023-01     # pp decomposition of headline YoY by group
GET /api/v1/cpi-jp-items/breadth?threshold=2       # share of the 582 priced items rising/falling
GET /api/v1/cpi-jp/releases
```

Interactive docs at `/api/docs`.

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
