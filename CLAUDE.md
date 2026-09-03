# Japan Macro Observatory — Project Rules

> Always-true, cross-cutting rules for this repo. The product lives in `observatory/`;
> plans live in `docs/plans/`.

---

## What this product is

- **Scope: Japan, deep — not Asia, wide.** Japan price statistics *plus* Bank of Japan
  monetary and balance-sheet data. Breadth across countries has no moat; depth on one
  market does. Hong Kong is verified and on hold — don't start it without an explicit
  decision.
- **An institutional data product, not a consumer dashboard.** Ordered customers:
  sell-side economists → buy-side/quant data teams → academics (free; citations are the
  point) → discretionary PMs. Judgement calls favour the API, the data, and reproducibility
  over UI polish.
- **The moat is point-in-time vintages.** Everything we ingest is free and public; we sell
  reproducibility, depth, and *history*. Vintage history can only accumulate going
  forward, so the ingest running reliably every month **is** the asset.
- **Distribution is the *Asia Economics Observations* Substack**, not cold outreach. Every
  chart in a post must be a permanent, citable URL on the platform — that's what the
  "URL encodes full view state" design rule is for.

## Golden Rule

**The platform is dataset-agnostic; datasets are adapters.** A new dataset is exactly:
a new module in `observatory/app/adapters/` (exposing `DATASET`, `SOURCE`, `DOWNLOAD_URL`,
`fetch()`, `parse()`, `validate()`, `PRESENTATION`, `ValidationError`) plus registration in
the `ADAPTERS` dicts in `app/ingest.py` and `app/api.py`. **The core schema (`app/db.py`)
and the API contract (`/api/v1/{dataset}/...`) never change for a dataset.** If a new
dataset seems to need a core migration, stop and revisit the design before writing code.
This rule has been exercised (cpi-jp-items, dataset #2, ~740 series: adapter + registry
entries, zero core changes) — keep it that way.

## Trust Contract (P0 — never regress)

Every number on every surface says where it came from:

- **Index levels** → `Official Statistic` badge — exactly as published, never recomputed.
- **Calculated rates** (YoY, MoM, 3-month annualized, contributions, breadth) → **no badge**.
  They carry their **formula** instead: under "Show calculation" on the page and in every
  CSV export header. The API still tags them `trust: "derived"`; the front end renders the
  formula, not a label. `TRUST_LABELS` in `format.js` contains only `official` and `model`.
- **`Model Estimate` badge** — reserved for future nowcasts; not used today.
- **Missing is `—`, never zero.** Gaps stay gaps in charts; a missing value is never
  exported as 0.
- Index levels are exact, but a rate computed from published (rounded) indices can differ
  from the Bureau's published rate by ±0.1 pp — the Methodology page discloses this; don't
  "fix" it by adjusting values.

## Definitions

- **cpi-jp** — national middle-class indices (~80 category series; headline, cores, ten
  major groups). e-Stat statInfId `000032103842`.
- **cpi-jp-items** — national detailed item indices (~740 series). e-Stat statInfId
  `000032103844`. **Leaf item** = code NOT starting with `0` (582 individually priced
  items, weights sum to ~10,000); codes starting `0` are aggregates.
- **Release / vintage** — one accepted ingest of a source file. One live vintage; every
  raw file archived under `data/raw/` with its SHA-256. **A stored vintage is immutable** —
  see Ingest Guardrails.
- **Measure type** — price *change* (index), price *level* (yen), *stock* (holdings),
  *flow* (net purchases). Never rank, aggregate, or chart across types. BOJ data is levels
  in ¥100mn and flows that **go negative**; `weight_per_10000` is meaningless for it.
- **BOJ Time-Series Data Search API** — `https://www.stat-search.boj.or.jp/api/v1/`
  (`getDataCode` · `getMetadata` · `getDataLayer`), JSON/CSV, **no key**. Two mandatory
  obligations: email the Research and Statistics Department on release, and display the
  BOJ credit line. Key DBs: `BS01` accounts · `MD09` stock+flow · `MD01` monetary base ·
  `FF` flow of funds · `PR01`–`PR04` price statistics.
- **Weights** — stored as parts per 10,000 (１万分比), not percent. Mis-scaling this is a
  recurring bug class.
- **Ready-to-adapt sibling tables** (same long-run CSV layout, same parser):
  `000032103845` goods/services splits · `000032103846` seasonally adjusted ·
  `000032103843` 1946– all-items-less-imputed-rent.

## Where to look

| Working on…                          | Read                                                                 |
| ------------------------------------ | -------------------------------------------------------------------- |
| Product overview, run/ingest/API     | [`observatory/README.md`](observatory/README.md)                     |
| Any UI change (layout, chart, style) | the **`ui-ux-design` skill** — mandatory, not optional               |
| Formulas, trust labels, limitations  | [`observatory/web/methodology.html`](observatory/web/methodology.html) — keep it in sync with any calculation change |
| Product strategy / scope / roadmap   | [`docs/plans/PLAN-JAPAN-MACRO-OBSERVATORY.md`](docs/plans/PLAN-JAPAN-MACRO-OBSERVATORY.md) — **current**; supersedes the v1 plan on scope, tiers, and customers |
| Trust contract, risk register (v1)   | [`docs/plans/PLAN-JAPAN-INFLATION-OBSERVATORY.md`](docs/plans/PLAN-JAPAN-INFLATION-OBSERVATORY.md) — still valid there, out of date on tiers/scope |
| Cross-shareholding DB (product #2)   | [`docs/plans/PLAN-CROSS-SHAREHOLDING-DB.md`](docs/plans/PLAN-CROSS-SHAREHOLDING-DB.md) — own schema namespace; macro golden rule does **not** apply to it |
| Boards & pay (product surface #3)     | [`docs/plans/PLAN-BOARD-AND-PAY.md`](docs/plans/PLAN-BOARD-AND-PAY.md) |
| Architecture / milestones            | [`docs/plans/IMPL-JAPAN-INFLATION-OBSERVATORY.md`](docs/plans/IMPL-JAPAN-INFLATION-OBSERVATORY.md) |
| e-Stat CSV parsing                   | [`observatory/app/adapters/estat_csv.py`](observatory/app/adapters/estat_csv.py) |
| Ask (LLM Q&A) behaviour and tools    | [`observatory/app/agent.py`](observatory/app/agent.py) module docstring |

## General Rules

- Don't assume I'm correct — do a thorough check. If my request is ambiguous, restate your
  interpretation in one sentence before making changes.
- I'm a businessman, not an engineer — explain things in plain language.
- Never try to please me for the sake of it. Give your professional answer.
- Do not hallucinate. If you cite a number, it must come from the data; if you name a link
  or e-Stat table, verify it exists.
- **Commit or push only when I ask.** No branches, commits, or pushes on your own
  initiative.
- Before concluding there is a bug: check the server is running the current code (uvicorn
  has no auto-reload here — restart it from `observatory/`), the right port (8007), and
  that you're not looking at a cached response.
- Before declaring a feature done: hit the real endpoints and load the real pages, not a
  mock. Data must round-trip: ingest → API → rendered page.
- Numbers shown to users must reconcile: contributions sum to headline (residual disclosed
  and bundled, never hidden); exports match what the chart shows.

### Response Format

- **Lead with a 1–3 sentence executive summary** in plain language — the bottom line first,
  details after.
- After finishing a task: **What changed** (max 4 plain-English bullets) · **What to
  expect** (max 2 lines: which page/URL, what I'll see) · **What to be aware of** (only
  genuinely useful flags; "Nothing to flag." if none). No other sections.

---

## Dev Environment

Single process, no Node build, no Docker needed locally:

```bash
cd observatory
./.venv/bin/python -m app.ingest cpi-jp        # idempotent; archives + validates
./.venv/bin/python -m app.ingest cpi-jp-items
./.venv/bin/uvicorn app.main:app --port 8007
```

- **Local Python is 3.9** — no `match`, no `X | Y` union syntax, no 3.10+ features in
  `app/` code, even though the production container runs 3.12. Code must run on both.
- DuckDB is **pinned `>=1.4,<1.6`** — `INSERT OR REPLACE` semantics around foreign keys
  changed after 1.5 and an unpinned install made production diverge from local. Don't
  loosen the pin.
- `.env` (gitignored, from `.env.example`) holds the ask-provider key only. Everything
  except the ask box works without it.
- Frontend is vanilla JS + vendored ECharts (`web/assets/echarts.min.js`). No new runtime
  dependencies, no CDN references, no build step.

## Deploy (Railway)

- Built from `observatory/Dockerfile`; config pinned in `observatory/railway.json`
  (healthcheck `/api/v1/catalog/datasets`).
- `start.sh` runs both ingests, then uvicorn. Ingest is fail-safe by design: an unreachable
  source or failed validation publishes nothing and the last good release stays live — a
  boot with no upstream still serves data. **Never make ingest failure fatal to boot.**
- `data/` is a mounted volume in production — the DuckDB file and raw archive must survive
  redeploys. Never write anything that matters outside `data/`.

## Ask feature (LLM Q&A)

- **Off, and staying off.** `ASK_ENABLED` is an explicit kill switch — the box stays
  hidden unless it is set truthy, even when a provider key is present. For an
  institutional product this is a settled decision, not a "not yet": professional users
  won't trust an LLM over the numbers, and it is a support and credibility liability.
  Don't propose enabling it without a specific customer asking.
- The agent has **no direct DB access** — it reaches data only through tools wrapping the
  same functions that serve `/api/v1`, and every tool call is recorded and shown to the
  reader. Don't add a tool that bypasses the public API's numbers.
- Providers: DeepSeek (`DEEPSEEK_API_KEY`, checked first) or OpenAI (`OPENAI_API_KEY`);
  same OpenAI-compatible client for both. Bump `SYSTEM_VERSION` in `agent.py` whenever the
  system prompt changes.

## Design Rules

All UI rules live in the **`ui-ux-design` skill**. P0 rules repeated for visibility:

- Colors from `tokens.css` `--obs-*` tokens only (6 series slots); both light and dark
  must work. Tabular numerals for all numbers; true minus sign; `pp` vs `%` used
  correctly (a change *of* a percentage is not a percentage *of* a level).
- Every chart: source line, Download PNG (light-theme, source embedded) and Download CSV
  (metadata header block); URL encodes the full view state so any view is citable.
- **Mandatory look-at-it gate:** never call UI done without screenshots at 1440 (light +
  dark) and true-390. Headless Chrome floors layout at ~500px even in `--headless=new` —
  true-390 checks need the iframe harness; `--virtual-time-budget` does not wait for
  fetches inside iframes.
- **Never kill a browser by application name (P0).** `pkill -f "Google Chrome"` (or
  `killall`, or any pattern matching the app bundle path) terminates my real browser
  window and every other agent's browser on this machine — unsaved tabs and all. Kill
  only the process you launched: match on `--headless=new`, on a `--user-data-dir` you
  chose, or on the PID you started. This rule covers Chrome, Chromium, Safari, Edge and
  the Playwright MCP browsers. The same applies to any long-lived app I might be using;
  scope every `pkill` to something only your own process matches.

## Ingest Guardrails (P0)

1. Ingest is **idempotent and fail-safe**: unchanged file → skip; failed validation →
   publish nothing, previous release stays live. Every downloaded file archived with
   SHA-256 before parsing.
2. **Vintages are immutable — this is the commercial moat, not housekeeping.** A stored
   release is never updated in place, never back-filled, never "corrected". A revision is
   a *new* vintage. Code that could overwrite a stored release is a P0 defect even if
   every displayed number looks right.
3. Validation gates are the product's credibility — never weaken one to make an ingest
   pass. Investigate the data instead.
4. e-Stat CSVs are cp932-encoded; blank cells are missing, never zero.
5. One DuckDB writer at a time: ingest runs before the API starts (see `start.sh`); never
   add a write path to the serving process.

---

## Continuous Improvement

Treat this file as living rules. If you spot a repeat mistake, missing guardrail, or
better convention, propose an update — exact text, why, where — and wait for approval.
Do not update rules automatically.
