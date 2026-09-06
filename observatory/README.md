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

and one trade dataset:

- **trade-semis** — Japan's semiconductor trade by partner country: monthly customs value
  (¥1,000) and quantity for integrated circuits, discrete semiconductors, thermionic tubes,
  the published component group, and semiconductor manufacturing equipment, in **both
  directions**, from January 2001 (2,544 series, 225 partners). From the principal-commodity
  by country tables (概況品別国別表) of the Ministry of Finance's Trade Statistics of Japan,
  via the e-Stat API. **Needs `ESTAT_APP_ID`.** Three things to know before using it:
  export and import commodity codes are separate vocabularies whose codes do not correspond
  (`70311000` is semiconductors on the import side, audio equipment on the export side); a
  published group always exceeds the sum of the items carried beneath it; and the Ministry
  publishes months it has not yet compiled as `0`, which the adapter drops rather than
  storing as fabricated zeros. Uniquely among the sources here the data is **natively
  vintaged** — every month passes through 速報 → 確報 → 確々報 → 確定 — so the point-in-time
  history is the source's own revision cycle rather than an artefact of when we fetched.
  Year-blocks the Ministry has closed are cached on the data volume under its own
  `UPDATED_DATE`, so a routine run re-downloads only the current year.

- **trade-inputs** — the step upstream of `trade-semis`: silicon wafers (HS 3818.00) by partner
  country, monthly from January 2001, both directions, value (¥1,000) and quantity (kg), from the
  HS-detail commodity by country tables (品別国別表). Same adapter machinery and series-code shape
  as `trade-semis`, so `/trade` serves it unchanged. Two traps it carries so you don't have to:
  e-Stat publishes **no names** for HS lines (they are curated here from the tariff schedule), and
  the export and import schedules split 3818.00 differently (`-100`/`-900` vs `-010`/`-020`).
  **Needs `ESTAT_APP_ID`.**

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
- **population-jp-municipal** — the same register release at municipality level: every city,
  town, village and ward in Japan, about **1,900 of them**, three resident segments deep, with
  the year's register flows and five-year age bands (584,781 series). The workbook mixes four
  levels of area in one column — adding every municipality row gives 160 million people in a
  country of 124 million — because designated cities are published alongside their own wards,
  districts alongside their towns, and Tokyo's islands as one `島しょ` row. The 328 grouping
  rows are identified by name containment plus the workbook's outline structure and **proved**
  by reconciliation: the 1,898 municipalities sum to their prefecture exactly, in all three
  segments. Grouping rows are stored but carry `level: "group"` and must never be added to the
  rest. Small cells are suppressed by the ministry (17,829 of them, foreign age bands only) and
  are missing, never zero. Because 584,781 series is not a payload,
  `/api/v1/population-jp-municipal/prefectures` **requires** `?prefecture=NN`.
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

### Hand-edited reference lists

Two curated Python modules, both applied at serve time so an edit costs a redeploy and never a
re-extraction or a rewritten vintage:

- [`app/filer_labels.py`](app/filer_labels.py) — **investors.** What kind of institution a
  5%-filer is (read from its own filed 事業内容) and which family it belongs to (curated:
  BlackRock files under sixteen EDINET codes and no document names the parent).
- [`app/company_labels.py`](app/company_labels.py) — **companies.** English names, the
  alternative spellings filers actually use for the same buyer, corporate families, and theme
  tags (`memory`, `semicap`, `wafer`, `materials`, …). Toyota is written two ways and Honda
  three; no filing says they are the same company. The name as filed is never replaced, nothing
  is translated, and a subsidiary is never rolled into its parent.
  `python -m app.company_labels --check` reports aliases that no longer appear in any filing
  and the most-named companies still missing from the list.

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
./.venv/bin/python -m app.ingest population-jp-municipal # ~12 min: 585k series
./.venv/bin/python -m app.ingest trade-semis             # needs ESTAT_APP_ID
./.venv/bin/python -m app.ingest trade-inputs            # needs ESTAT_APP_ID

# segment notes (revenue by region, named customers, reportable segments) from the
# annual reports already archived — the company side of the Company Lens
cd equity && ../.venv/bin/python seg_extract.py --all --source local --workers 8 && cd ..

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

## Admin console

`/admin.html` — internal operations, unlisted from the public nav. Five views: **Ingest
Health** (per-dataset currency, quiet-ingest detection, artifact fingerprints), **Vintage
Browser** (every stored release and exactly what it introduced, revised, or withdrew),
**Curation Queue** and **Party Profiles** (below), and **Audit Log** (every sign-in and
admin action).

- Enabled only when `ADMIN_PASSWORD` is set (environment or `.env`); without it every
  `/admin/api` endpoint answers 503 and the page says so. Sessions are HttpOnly cookies
  signed with a per-boot secret — a restart signs everyone out.
- The admin surface is read-only against DuckDB (the one-writer rule holds). Everything it
  writes is a file under `data/admin/`: the append-only audit trail `audit.jsonl`, and the
  party registry `parties.json`.
- Routes live under `/admin/api` (`app/admin_api.py`), outside `/api/v1`, so authenticated
  responses never touch the shared response cache.

### Party profiles (`#parties`, `#queue`)

Who each fund, company and person IS, curated by hand — see
[`docs/plans/PLAN-PARTY-PROFILES.md`](../docs/plans/PLAN-PARTY-PROFILES.md). The store is
`app/parties.py`; nothing here touches an `eq_*` table, so no vintage can be rewritten from
the console.

- **Its own identifier, not EDINET's.** BlackRock files under sixteen codes, 17,345 of
  25,320 register rows carry no code at all, and no director has one — so a party has our
  id, and the source keys (`edinet_code`, `name_key`, `sec_code`, `person_key`) hang off it
  as aliases. One key belongs to one profile; a duplicate is refused, because it would
  double-count a ranking.
- **Two levels.** A group parent ("Nomura") plus its arms, each with its own `group_role`
  (Asset management · Securities · Banking · Trust). An arm is never made to stand for the
  group, and the roll-up is never the default arithmetic — Nomura Securities' 5% stake is a
  trading book and Nomura Asset Management's is client money.
- **Three type fields, not one list.** `party_class` (what it legally is) · `strategy`
  (how it invests, zero or many) · `holder_role` (why it is on the register). The third is
  what separates a 信託口 nominee from a beneficial owner — the two most frequent names on
  the Japanese register are custodian trust accounts, not owners.
- **Curated, never Official.** These are our judgement; no filing states a category such as
  "hedge fund". `app/filer_labels.py` keeps deriving `filer_type` from the filing's own
  事業内容 and the form shows it beside the curated class, flagged where the two differ.
  Nothing reaches `/api/v1` in this milestone; every profile carries a `public` flag for
  when something does.

Seed the group structure once from the already-curated group map:

```bash
./.venv/bin/python -m app.parties_seed [--dry-run]   # 19 parents + 109 arms
```

**Back it up.** The live store is on the mounted volume; `Export To Repo` copies it to
`curation/parties.json`, which seeds an *absent* store on boot and is meant to be committed.
An unreadable live store is never silently replaced by the seed.

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

**Daily refresh.** `start.sh` is a supervisor, not a one-shot: it ingests, serves, and when
the server ends, ingests again. `app/refresh.py` ends the server once a day — 13:00 UTC by
default, which is 22:00 in Tokyo: after the Ministry of Finance posts the day's yield curve,
and after the 12:00 UTC EDINET capture job, so the equity extractors read the same day's
archive rather than yesterday's.
So the container refreshes itself and the platform's restart policy is never load-bearing;
the container itself never exits.

This replaces the second Railway cron service this file used to recommend. That service was
never created, and between 1 and 3 September 2026 the site quietly served three-day-old
yields because nothing restarted it. A loop in the repo cannot be forgotten and needs no API
token.

Refreshing still means a short outage — the ingests run with nothing serving, which on the
network-mounted volume takes about four minutes. The next step, if that becomes a problem,
is for ingest to build a new DuckDB file beside the live one and rename it into place:
`db.read_cursor()` already reopens when the file changes underneath it.

| Variable | Default | What it does |
| --- | --- | --- |
| `REFRESH_AT` | `13:00` | Daily refresh time, **UTC**. Japan has no daylight saving, so this is 22:00 JST all year. |
| `REFRESH_ENABLED` | `1` | Kill switch for both the refresh and the health watch. |
| `REFRESH_MAX_AGE_HOURS` | `26` | How old the ingest stamp may get before the refresh counts as broken. |
| `ALERT_WEBHOOK_URL` | unset | Slack-shaped webhook; the server posts to it when something needs attention. |
| `EDINET_S3_*` | unset | Bucket credentials for the nightly equity refresh (below). Unset = the refresh skips itself and the shipped equity data is served as-is. |

`REFRESH_SUPERVISED` is set by `start.sh` alone and is what arms the daily shutdown. A
development `uvicorn app.main:app` therefore never ends itself, whatever the clock says.

### The nightly equity refresh

The EDINET-derived datasets — 5% filings, cross-shareholdings, boards and pay, buybacks,
facilities, rental property, shareholder registers, financial statements — refresh in the same cycle, from the
same S3 bucket the capture jobs write to:

```
python equity/refresh_equity.py --seed seed/equity.duckdb
```

They used to be extracted by hand on a laptop and shipped as a seed file. That is exactly
how the 5% filings went four weeks stale: capture moved to the cloud bucket on 6 August
2026, the extractors kept being pointed at the laptop's frozen archive, and every page
still rendered a healthy-looking dashboard over month-old data.

- **Incremental.** Each extractor records how far it has read the archive in
  `eq_extract_runs` and resumes from there (minus a 10-day lookback, because EDINET
  back-fills). A routine night is one day of filings — about 130 documents, under a
  minute for all seven. `--full` re-reads five years and takes hours.
- **The bucket listing is shared.** 182k keys is 26 seconds; `EDINET_LISTING_CACHE` keeps
  one answer for an hour so seven extractors ask once.
- **The seed no longer always wins.** `--seed` installs the shipped database only when its
  watermark is ahead of the volume's, so a redeploy never discards accumulated nights. A
  fresh offline re-extraction (after a parser fix) is still ahead, and is still how a
  rebuild reaches production.
- **Fail-safe, like ingest.** A failing extractor logs `ATTENTION`, leaves its previous
  data live, and never stops the server coming back up.
- **Freshness is reported.** `/api/v1/catalog/health` carries an `equity_extractors`
  block: how far each extractor has read, and whether that is more than 7 days behind
  (long enough to survive the New Year closure without crying wolf).

### The MCP surface (v2)

`POST /mcp` serves two tool surfaces, chosen by `MCP_TOOLSET` (`v1` · `v2` · `both`, default
`both`). v2 is six generic tools whose `dataset` argument is resolved through the registry, so
a new dataset needs a manifest and a dispatch row, not a new tool:

| Tool | What it answers |
| --- | --- |
| `list_datasets` | what is published — id, section, shape, capabilities, screens, coverage |
| `describe_dataset` | one dataset's card: source, every measure with its trust label and formula, endpoints, notes, live coverage |
| `search` | companies (name or code) and series (name or code) across datasets, one ranked list |
| `get_company` | one company in one dataset, or — with no dataset — a compact profile across every dataset that knows it, with a coverage list |
| `get_series` | a series' history as the published value or a calculated rate, with `as_of` |
| `screen` | a ranked cross-section from the dataset's own screens; an unknown sort answers with the valid ones |

Every result is one envelope — `tool · dataset · data · provenance · calc · vintage · cite ·
coverage` — and no-data is an answer (`data: null`, `missing: why`), never a JSON-RPC error.
The manifests are also served as MCP resources (`observatory://datasets/{id}`,
`observatory://sections`, `observatory://methodology`), and the `initialize` instructions are
generated from the registry so they name every dataset on the server.

### One company, every dataset

`/api/v1/company/{code}` (`app/company_api.py`) walks the registry, calls each dataset that
declares a company view, and returns one document in section order — holdings, register, 5%
filings, board and pay, buybacks, facilities, financials, AGM votes, segments. It is what the
company page and the MCP `get_company` tool both read, so the two cannot disagree.

Three rules, all consequences of the trust contract. **Every block is independent**: a dataset
that fails becomes an `errors` entry and costs the other eight nothing. **Absence is reported,
never omitted**: a dataset with no rows appears under `coverage.missing` with its reason, so
"no facilities filing for this company" reads differently from "facilities are not published
here", and neither looks like zero. **Nothing is recomputed across blocks**: each carries its
own dataset's `calc`, `provenance` and `cite`; yen book values, voting rights and square metres
never meet in a total.

`?compact=1` drops the tables and keeps the counts (~35 KB for Toyota against ~240 KB full);
`?limit=` caps rows per table and discloses the full count; `?datasets=` and `?sections=`
narrow it. Cold is about 230 ms and repeat hits come from the release cache. It is deliberately
**not** in `WARM_ENDPOINTS`: the cache holds 64 entries and warm-up already fills 42, so
priming companies would evict the dataset payloads every page needs.

`?as_of=` is **refused with a 400**, on purpose. These datasets are versioned by filing, and
the archive records when a document was *filed* but not when this platform captured it, so a
point-in-time view can only be built on `filed_date` — and that ceiling is not implemented yet.
Returning today's filings under a historical date would be silently wrong, which is worse than
unsupported. Macro series already serve `?as_of=` on `/api/v1/{dataset}/observations`.

### The dataset registry

Every dataset module exports a `MANIFEST` — one plain dict saying what the dataset is,
where its numbers come from, which measures are official and which are calculated (with
the exact formula), where to fetch it and where to cite it. `app/registry.py` collects them
and refuses a card that breaks the trust contract: a calculated measure with no formula, an
official one with a formula, a unit outside the vocabulary (`%` is a share of a level, `pp`
a change of a percentage), a formula for the generic rates that differs from what `api.py`
computes, or an endpoint that is not a real route on the app.

A bad card is **quarantined, never fatal**: the serving process drops that one dataset from
the catalog, keeps serving the rest, and reports it in the `manifests` block of
`/api/v1/catalog/health` (which turns the report to `attention` and alerts). Set
`MANIFEST_STRICT=1` to make a fault refuse to boot instead — for staging, not production.

```bash
./.venv/bin/python -m app.registry --check            # validate every card; exit 1 on a fault
./.venv/bin/python -m app.registry --scaffold cpi-jp  # draft a card for a macro adapter
./.venv/bin/python -m unittest tests.test_manifests
```

A new macro dataset gets its card from `--scaffold`: everything the adapter already declares
is filled in, and what only a person can write — the section, the summary, and above all the
formula for any dataset-specific calculation — is left as `TODO`, which the validator treats
as an error. A draft can never reach the shelf half-finished.

### Knowing when it stops

The per-dataset staleness limits run from 7 days to 950, so a refresh that stops is invisible
inside them for days. The machinery gets its own signal: `start.sh` stamps
`data/ingest_heartbeat.json` at the end of every cycle, and the health report says how long
ago that was.

```bash
curl https://web-production-c9178.up.railway.app/api/v1/catalog/health           # always 200
curl https://web-production-c9178.up.railway.app/api/v1/catalog/health?strict=1  # 503 when unwell
```

Point an uptime monitor at the `strict=1` URL every five minutes and one check covers both
failure modes: stale data or a stopped refresh answers 503, and a service that is down
answers nothing at all. **Do not point Railway's own healthcheck at it** — it would refuse a
deploy over a late source file; that stays on `/api/v1/catalog/datasets`.

The report is deliberately excluded from the response cache (`cache.py`, `NEVER_CACHE`).
Cached, it froze the boot-time answer for the life of the process, so the one endpoint meant
to reveal staleness was the one that could never go stale.

The server also watches itself every 15 minutes, logs `ATTENTION` lines a log rule can key
on, and posts to `ALERT_WEBHOOK_URL` if one is set, at most once every six hours per distinct
fault. That covers detail; it cannot cover the service being down, which is what the external
monitor is for.

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
  refresh.py         daily self-restart (under start.sh only) + the health watch
  heartbeat.py       when the ingest cycle last ran — the stopped-refresh signal
  main.py            FastAPI app: API + static frontend
web/
  assets/tokens.css  design tokens (single source of truth for colour, incl. dark mode)
  assets/format.js   centralised number/date/trust-label formatters
  assets/charts.js   house chart chrome for ECharts (vendored, self-hosted)
  assets/nav.js      the site header, rendered from one list of sections/pages
  index.html         Landing: live directory of every dataset (+ assets/landing.js)
  macro.html         Macro / Overview — all five datasets on one screen (+ assets/macro.js)
  cpi.html           Macro / Inflation (CPI)  (+ assets/overview.js)
  explorer.html      Macro / Item Explorer (+ assets/explorer.js)
  equities.html      Equities / Overview — live summary per dataset (+ assets/equities.js)
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
GET /api/v1/trade-semis/observations?series=exp.70131000.50105.val&period=fiscal_quarter&fy_end=3
                                                   # any monthly FLOW summed into a company's fiscal
                                                   #   quarters or years (period=fiscal_year); refuses an
                                                   #   index, a stock or a rate; complete periods only
GET /api/v1/equity/segments/lens/8035              # Company Lens: filed regions, customers and segments
GET /api/v1/equity/segments/lens/8035.csv          #   beside the customs flows the company is mapped to,
GET /api/v1/equity/segments/customers?name=Taiwan  #   in its own fiscal periods; who names whom
GET /api/v1/equity/segments/supply-chain           #   the editorial commodity -> company mapping
GET /api/v1/trade-semis/trade?flow=exp&commodity=70323050
                                                   # one commodity x every partner x every month,
                                                   #   plus world totals for all eleven commodity-flows.
                                                   #   trade-semis series codes are flow.commodity.partner.measure:
                                                   #     flow      exp | imp
                                                   #     commodity the Ministry's 概況品 code, per direction
                                                   #     partner   e-Stat area code (MoF country code + '50')
                                                   #     measure   val (¥1,000) | qty (commodity's own unit)
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
GET /api/v1/catalog/manifests                      # every dataset's card: source, measures, formulas, endpoints
GET /api/v1/catalog/manifests/cpi-jp               # one card; an unknown id answers with the valid ids
GET /api/v1/catalog/sections                       # the fixed section list and which datasets sit in each
GET /api/v1/company/7203                           # every dataset's view of one company, in section order
GET /api/v1/company/7203?compact=1                 # facts and row counts only, no tables
GET /api/v1/company/7203/coverage                  # which datasets hold this company and which do not
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
`observatory/equity/extract.py` into `data/equity.duckdb`) is exposed through the same
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

**Measurement basis.** Every yen figure in this dataset is on one convention —
balance-sheet **carrying amount**, at fiscal year end, from an **annual**
securities report — and that convention is now returned as a typed `basis`
tuple on every response that carries a yen figure (`measurement`,
`entity_scope`, `share_scope`, `trust_included`, `as_of`, `period_type`).
It is *derived*, not stored: `entity_scope` is read from `holder_table`
(`reporting` → `parent_only`, `largest` → `largest_holding_company`,
`second_largest` → …) and `share_scope` from `share_class`, both of which the
filings have always carried. Nothing is backfilled and no stored row is
written to. `app/basis.py` is the source of truth; `equity/extract.py`
projects the vocabulary into `eq_basis_labels` and the view
`v_holdings_basis` so it is queryable in SQL, and the API never reads either —
a database an extract has not touched still serves a correct basis.

This matters because it is *not* the basis the press and IR decks use.
Reduction targets and progress figures are quoted on acquisition cost, often
at commercial-bank level rather than group level, often listed-only, and often
at a half-year date this product does not hold. The differences run to
multiples: Nikkei Asia put the three megabanks at ¥2.56tn at 2025-09-30; the
filings give ¥11.5085tn at 2026-03-31. Both are right.
`entity_scope` is the axis that hides in plain sight — SMFG discloses ¥3.458tn
of listed policy shares under SMBC and ¥153.8bn at the holding company, so a
figure quoted for one entity is not the group figure.

`GET /api/v1/equity/claim-check` (MCP tool `check_claim`) reconciles an
external figure against what the filings support. It **never infers the
claim's basis from its wording**: the caller states it in `claimed_*`
arguments, or the answer says the gap cannot be classified. `context` is
echoed for the record and never parsed. Verdicts describe what this dataset
can corroborate (`consistent`, `cannot_verify`, `date_mismatch`,
`basis_mismatch`, `scope_mismatch`, `measure_not_held`, `coverage_gap`) and
are never a judgement that a published figure is wrong. There is no
book-value-reduction measure here: `sale_proceeds_yen` is cash received over a
fiscal year, and the two are never presented as equivalent.

### Boards and pay (`/api/v1/equity/governance/...`)

The third surface, from the same annual reports and the same DuckDB file
(`observatory/equity/board_extract.py`; see `docs/METHODOLOGY-BOARDS-AND-PAY.md`):

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

### Financials (`/api/v1/equity/financials/...`)

Every tagged number in the annual securities report, kept long
(`observatory/equity/fin_extract.py`, parser `fin-1`; extractor name `financials`
in `eq_extract_runs`, so it reports its own freshness). Four tables:
`eq_fin_filings` (one row per filing: status, accounting standard, the
balance-sheet gate per basis, which statements the filing carries),
`eq_fin_facts` (one row per element × context: every numeric fact in a plain
year context, current and up to four prior years, consolidated and parent),
`eq_fin_lines` (the filing's own presentation order for the five-year summary
and each primary statement, from the t1 package's presentation linkbase) and
`eq_fin_elements` (the element dictionary with the filer's Japanese label and,
where the filing carries one, its English label). Statements and the
key-indicator panel are both views over those tables; adding a note or a
dimensional breakdown later is a filter change in the extractor, not a schema
change.

| Endpoint | What it returns |
| --- | --- |
| `/financials/company/{sec_code}` | the key-indicator panel across fiscal years — each year from the latest filing covering it, the element behind every field, the summary lines as filed; `?basis=`, `?as_filed_in=YYYY` for one filing's five years as first published |
| `/financials/statements/{sec_code}?statement=bs\|pl\|ci\|cf\|ss\|summary` | one statement of one filing, every line in the filer's order with Japanese and English labels, current and prior values; `?basis=`, `?year=` |
| `/financials/facts/{sec_code}?element=` | one element's every filed value across filings and restated years |
| `/financials/elements?q=` | the element dictionary |
| `/financials/screen?metric=` | ranked cross-section, one filing per company; `/screen/metrics` lists them |
| `/financials/summary`, `/financials/companies?q=` | coverage; search scoped to this dataset |

Nothing is recomputed: ratios are the filer's own (`*_pct` = filed fraction ×
100), and the only derived figures are a statement's change columns, computed
on the page. Methodology is on the site's Methodology page under *Financial
statements and key indicators*.

The page is `web/financials.html` (**Equities → Financials**): a market view —
coverage strip and a ranking on any key indicator — and a company view at
`?c={sec_code}` with the record chart, the five-year table and each statement
under tabs. The URL encodes basis, statement, filing year and chart. MCP tools:
`get_financials`, `get_financial_statement`, `get_financials_screen`.

Running it locally reads the laptop archive; `--sec-codes 7203,8306` narrows a
run, `--all --source s3 --new-only` is what the nightly refresh does. The first
production run has no watermark and therefore reads the whole bucket — every
annual report since 2021 — which is hours, not minutes; run it once by hand
before relying on the nightly window.

#### Calculated ratios and the screener

`app/fin_metrics.py` is the one place a financial number is *computed*: ROE and
ROA on average balances, margins, equity ratio, asset turnover, growth, cash
conversion, simple free cash flow, cash to assets, and implied PBR / dividend
yield from the filer's own year-end PER (no price feed exists). Every row
carries the formula, the inputs used (value, element, fiscal-year offset) and
the filer's own ROE and equity ratio with the difference — our ROE reconciles
to the filer's within 0.5 pp for over 99% of companies. Computed on request
over the latest filing per company and memoised per database version (about
0.3 s for the universe).

| Endpoint | What it returns |
| --- | --- |
| `/financials/metrics/{sec_code}` | one company's ratios with formulas, inputs and the filer's own figures |
| `/financials/screener?sort=&order=&industry=&standard=&roe_min=&…` | filtered, ranked cross-section; `/screener/options` lists industries, standards, metrics and formulas |

The page is `web/screener.html` (**Equities → Screener**); the URL carries every
filter and the sort. MCP tools: `get_financial_metrics`, `screen_financial_metrics`.

### Buybacks (`/api/v1/equity/buyback/...`)

The fourth surface, and the only one not built from annual reports: EDINET type
220, the **monthly** 自己株券買付状況報告書 a company files while a buyback runs
(`observatory/equity/buyback.py`, parser `bb-2`). Announcement → execution → cancellation
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
from the ownership section of the same annual reports (`observatory/equity/ownership_extract.py`,
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
(`observatory/equity/lvh_extract.py`, parser `lvh-1`). Anyone crossing 5% files within five
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

### AGM votes (`/api/v1/equity/agm/...`)

How every resolution at a Japanese shareholder meeting was voted, and — for
board elections — how much support each named director received
(`observatory/equity/agm_extract.py`, parser `agm-1`; see
`docs/METHODOLOGY-AGM-VOTES.md`). **9,690 meetings, 32,204 resolutions and
62,021 individual director results.** It is the only free, public, structured
measure of a named director's mandate in Japan.

| Endpoint | What it answers |
| --- | --- |
| `/agm/summary` | coverage, the distribution of director support, and medians by proposal type |
| `/agm/directors?order=lowest` | named directors ranked by the support they received — the point of the dataset |
| `/agm/proposals?category=` | resolutions by kind; `?shareholder=true` for shareholder proposals |
| `/agm/company/{sec_code}` | one issuer's meetings, each resolution and each candidate underneath it |

Three things the responses carry because a reader will otherwise get them
wrong. **The percentage is the company's and cannot be rebuilt from the counts
beside it**: 95% of these filings disclose that the issuer stopped counting
attending votes once the outcome was settled, so the denominator behind 賛成割合
is never published. It is stored and shown exactly as filed; our own arithmetic
is served separately as `approval_pct_of_counted` and never sits in the same
column. **A board election has no proposal-level vote** — one result per
candidate and no total — so those vote columns are null by structure, not
missing. **Counts are voting rights (個), not shares**, and are not comparable
with the share counts anywhere else in the product.

Rankings show only rows whose filed percentage the platform can reproduce from
the counts printed beside it (`pct_consistent`). That check exists because it
caught a real bug: a minority of filers publish a trailing `(参考) 反対率`
column, and reading it as the approval rate turned Omron's 99.1% into 0.1% and
put it top of "lowest support". Failing rows are kept and returned by
`include_unverified=true`, flagged — never deleted.

Unlike every other extractor here there is almost nothing to read from the
XBRL: type 180 is 98% "XBRL" by EDINET's flag, but the tagged facts are
cover-page boilerplate plus one free-text block. The substance is an HTML table
in the t1 honbun, parsed with the grid machinery from `facility_extract.py`.
That document type is also a grab-bag — mergers, subsidiary changes, officer
changes — so only about 42% of type-180 filings produce rows, and the rest are
recorded as examined-and-not-a-meeting so the count reconciles with the archive.

**Coverage begins in April 2024 and nothing earlier can be recovered.** 臨時報告書
leave EDINET's public inspection window far sooner than annual reports do; the
earliest one still carrying metadata is 2024-04-01, against 2021-08 for annual
reports and 5% filings. History accumulates forward from here.

The page is `web/agm.html` (**Equities → AGM Votes**): the distribution of
director support, a lowest-support league table with thresholds, contested
business (shareholder proposals, takeover defences, dismissals, pay), medians
by proposal type, and a company view at `?company={sec_code}`.

Companies in that dataset are named in Japanese in the filings, but every
annual report states the filer's own English name on its cover page, so both
names are as filed. Every name-bearing response carries the English one
(`name_en`, `filer_name_en`, `held_name_en`, `holder_name_en`) alongside the
Japanese, and `/companies?q=` matches code, Japanese name and English name
alike. EDINET's filer registry is the fallback for a company that files no
annual report of its own. See `docs/METHODOLOGY-CROSS-SHAREHOLDINGS.md` §5.1.

Nobody types the filed name, though: "MUFG" is in neither
株式会社三菱ＵＦＪフィナンシャル・グループ nor "Mitsubishi UFJ Financial Group,
Inc.", so every `/companies?q=` search also matches a market nickname
(`app/aliases.py`). Two layers, both applied at serve time and neither stored:
initials generated from the filed English name (MUFG, SMFG, MHI), and
`app/curation/company_aliases.json` for what initials cannot reach — JAL,
TEPCO, JR East, Uniqlo, Docomo, brands, and operating subsidiaries that do not
list, each row naming the listed filer and the reason it is there. Matching is
exact on the nickname, so an alias only ever ADDS the company it names; it
never reorders or removes anything the name search already found.

Nor does anyone type the filed name the way EDINET filed it. 181 listed filers
carry a space inside their own name (`株式会社　りそなホールディングス`), 543
carry full-width latin (`ＮＴＴ株式会社`), and 株式会社 sits at whichever end
the company chose — so typing a company's own full legal name returned nothing
at all. Both sides of the name comparison are now folded (`aliases.fold`):
NFKC, upper-case, legal form and punctuation removed, and spaces dropped where
they touch a kana or kanji. A space between two latin words survives on
purpose — welding `ＴＯＹＯ　ＴＡＮＳＯ` into one word would answer a search for
Toyota with a graphite maker — so a name typed with no spaces at all is matched
against the whole de-spaced name only, never a fragment of it. As with the
nicknames, the fold contributes only what the plain substring search missed.

Quick check:

```
curl -X POST localhost:8007/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
