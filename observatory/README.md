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
  main.py            FastAPI app: API + static frontend
web/
  assets/tokens.css  design tokens (single source of truth for colour, incl. dark mode)
  assets/format.js   centralised number/date/trust-label formatters
  assets/charts.js   house chart chrome for ECharts (vendored, self-hosted)
  index.html         Overview        (+ assets/overview.js)
  explorer.html      Item Explorer   (+ assets/explorer.js)
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
