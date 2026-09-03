# PLAN — API & MCP v2, milestone M1: manifests, registry, catalog

> **Status:** PROPOSAL — plan only, awaiting go-ahead. No code written.
>
> **Parent:** [PLAN-API-MCP-V2.md](PLAN-API-MCP-V2.md) §2.2–2.3, §2.9 M1.
>
> **One-liner:** give every one of the 13 live datasets one machine-readable
> description, collect them into a registry that refuses a description that
> doesn't match reality, and serve them at `/api/v1/catalog/manifests`.
> Additive only: no existing endpoint, page, ingest or schema changes.

---

## 1. Interpretation

Write a `MANIFEST` constant for each of the 13 datasets (7 macro adapters + 6 equity
API modules), add `app/registry.py` that collects and validates them — every declared
endpoint must resolve to a real FastAPI route, every calculated measure must carry a
formula — and expose them over three new read-only catalog endpoints, with validation
failures surfaced rather than allowed to take the site down.

## 2. Approach

### 2.1 The 13 datasets and their ids

| # | id | section | shape | module | page |
|---|---|---|---|---|---|
| 1 | `cpi-jp` | prices | series | `adapters/cpi_jp.py` | cpi.html |
| 2 | `cpi-jp-items` | prices | series | `adapters/cpi_jp_items.py` | cpi.html |
| 3 | `boj-assets` | monetary | series | `adapters/boj_assets.py` | boj.html |
| 4 | `jgb-yields` | rates | series | `adapters/mof_jgb.py` | rates.html |
| 5 | `jnto-visitors` | tourism | series | `adapters/jnto_visitors.py` | inbound.html |
| 6 | `population-jp` | demography | series | `adapters/juki_population.py` | population.html |
| 7 | `population-jp-history` | demography | series | `adapters/ssds_population.py` | population.html |
| 8 | `cross-shareholdings` | ownership | company | `equity_api.py` | holdings.html |
| 9 | `shareholder-register` | ownership | company | `ownership_api.py` | ownership.html |
| 10 | `large-shareholdings` | ownership | events | `lvh_api.py` | stakes.html |
| 11 | `boards-and-pay` | governance | company | `governance_api.py` | governance.html |
| 12 | `buybacks` | capital-returns | events | `buyback_api.py` | buyback.html |
| 13 | `facilities` | assets | company | `facility_api.py` | facilities.html |

Macro ids **must** equal the DuckDB `datasets.slug` — they are already in URLs and in the
`datasets` table, so they are a published contract. Equity ids are new (equity has never
appeared in `/api/v1/catalog/datasets`), so we are free to choose; see open question 2.

`SECTIONS` is a fixed ordered tuple in `registry.py`:
`prices · monetary · rates · demography · tourism · ownership · governance · capital-returns · assets`.

### 2.2 Manifest = pure data, not callables

The parent plan's `capabilities: {"company": fn, ...}` **cannot be done for the macro
side**: the macro read functions live in `api.py`, and `api.py` imports the adapters, so an
adapter referencing `api.observations` is a circular import. It also contradicts the plan's
own claim that a manifest is "JSON-serialisable by construction".

Decision: **manifests are plain JSON-serialisable dicts.** `capabilities` is a list of
capability *names* (`["series", "search", "screen", "company"]`). The name → function
binding table lives in `registry.py` (M2 fills it in when `tools_v2.py` needs it). This
keeps the adapter modules dependency-free, keeps `/catalog/manifests` a straight
`JSONResponse(manifest)` with no projection step, and lets M1 validate capability names
against a closed vocabulary today.

### 2.3 Manifest schema

```python
MANIFEST = {
  "id": "cross-shareholdings",
  "section": "ownership",
  "name": {"en": "Cross-Shareholdings", "ja": "政策保有株式"},
  "shape": "company",                     # series | company | events
  "summary": "One sentence, plain English.",
  "source": {
      "publisher": "EDINET (Financial Services Agency)",
      "document": "有価証券報告書 · 株式の保有状況",
      "url": "https://disclosure2.edinet-fsa.go.jp/",
      "credit": "Source: company filings on EDINET (FSA).",
      "license_note": "...",
  },
  "keys": ["sec_code", "fiscal_year"],
  "vintage": {
      "unit": "filing",                   # release | filing
      "as_of_basis": "captured_at",       # release-in-force | captured_at
      "as_of_supported": False,           # macro True today; equity lands in M3
      "history_from": "FY2022",
  },
  "measures": [
      {"id": "policy_total_yen", "label": "Policy shareholdings, book value",
       "unit": "JPY", "trust": "official"},
      {"id": "pct_of_equity", "label": "Share of shareholders' equity",
       "unit": "%", "trust": "derived",
       "calc": "total policy shareholdings ÷ shareholders' equity × 100"},
  ],
  "endpoints": {"company": "/api/v1/equity/company/{sec_code}",
                "summary": "/api/v1/equity/summary",
                "screen":  "/api/v1/equity/unwind",
                "search":  "/api/v1/equity/companies"},
  "capabilities": ["company", "screen", "search"],
  "cite": "/holdings.html?c={sec_code}",
  "page": "/holdings.html",
  "notes": ["Book values are as filed at period end, not marked to market.", ...],
}
```

Two fields are **read from existing constants, never restated**, so they cannot drift:

- `vintage.stale_after_days` ← `adapter.PRESENTATION["stale_after_days"]` (still the only
  copy; `api.health()` keeps reading `PRESENTATION` exactly as it does now).
- equity `source.credit` / provenance note ← `equity_api.PROVENANCE["note"]`.

### 2.4 Validation rules (`registry.validate`)

**Tier A — structural, at import, no DB, no app object:**

1. Required keys present; `id` unique; `id` matches `^[a-z0-9][a-z0-9-]*$`.
2. `section ∈ SECTIONS`; `shape ∈ {series, company, events}`.
3. `capabilities ⊆ {series, company, screen, search, summary}` and every capability
   has a matching key in `endpoints`.
4. **Trust contract (the point of the exercise):** `trust ∈ {"official", "derived"}`
   — `"model"` is reserved and rejected; `calc` is **required iff** `trust == "derived"`
   and **forbidden** when `trust == "official"`; `calc` must be a non-empty string.
5. `unit` from a closed vocabulary — `index · % · pp · JPY · JPY_100mn · persons ·
   count · ratio · years · date`. This is what stops a change *of* a percentage being
   labelled `%` instead of `pp`.
6. `cite` and `page` start with `/`; every `{placeholder}` in `cite` appears in `keys`.
7. For `shape == "series"`, `id` must be a key of `api.ADAPTERS`; and each of the four
   generic measures it declares (`index`, `yoy`, `mom`, `ann3m`) must have `trust` equal
   to `api.TRUST[measure]` and `calc` equal to `api._calc_for(measure, unit)`. The
   manifest cannot state a formula the API does not actually use.

**Tier B — route resolution, at start-up, needs the built app:**

8. `registry.bind(app)` — every path in `endpoints`, with any query string stripped,
   must appear verbatim in `{r.path for r in app.routes}`. Path parameter names must
   match (`{sec_code}`, not `{code}`), which is what makes the check meaningful.

**Failure policy — this is the one place I depart from the parent plan.**

The parent plan says validation happens "at import time", which implies raising. A typo
in a manifest would then crash uvicorn on boot and take the live site down. That is the
same failure mode the repo already forbids for ingest ("never make ingest failure fatal
to boot"), so M1 follows the same rule:

| Context | Behaviour |
|---|---|
| `pytest` / `python -m app.registry --check` | **Strict.** Any violation is an error, non-zero exit, full report. |
| Serving process (uvicorn) | **Quarantine.** The offending manifest is excluded from the registry, the reason is recorded in `registry.errors()`, and the other 12 datasets serve normally. |
| `MANIFEST_STRICT=1` | Opt-in fatal, for staging, if you want boot to refuse a bad manifest. |

Quarantined manifests are surfaced, not swallowed: a new `manifests` block on
`/api/v1/catalog/health` (`{"registered": 13, "quarantined": [], "errors": []}`) and, if
`quarantined` is non-empty, the report's overall `status` goes to `attention` — which is
already wired to the admin console and the alert webhook.

### 2.5 Availability

Equity datasets exist only where `data/equity.duckdb` does, and within that file the
buyback and 5% tables are gated separately (`buyback_api._tables_present()`,
`lvh_api._require()`). The registry therefore records, per dataset, an `available`
boolean computed at request time from those existing checks — it never re-implements
them. An unavailable dataset is still **listed** with `available: false`, never hidden:
a catalog that silently omits a dataset teaches a client it doesn't exist.

### 2.6 Endpoints

New router `app/catalog_api.py` (a leaf module: imports `registry`, imported by
`main.py`), included **before** `api.router` so its literal paths can never be shadowed
by the `/{dataset}/...` catch-alls.

| Endpoint | Returns |
|---|---|
| `GET /api/v1/catalog/manifests` | `{"count", "sections", "datasets": [...]}` — every manifest, in section order, each with `available`. |
| `GET /api/v1/catalog/manifests/{id}` | one manifest; on an unknown id, **404 with the list of valid ids**, never a bare message. |
| `GET /api/v1/catalog/sections` | the fixed section list, each with its dataset ids, in display order. |

`GET /api/v1/catalog/datasets` is **not touched** — it is the Railway healthcheck path
(`railway.json`), and it stays byte-identical.

These are plain GETs under `/api/v1`, so `cache.ResponseCache` covers them for free.
They are deliberately **not** added to `WARM_ENDPOINTS`: the cache holds 64 entries and
warm-up already fills 42, and these payloads are small and rarely fetched.

Live coverage (latest period, row counts) is **not** in M1. The manifest stays static and
cacheable; live coverage belongs to M2's `describe_dataset`, which already needs a DB read.

## 3. Files / areas

**New**
- `app/registry.py` — `SECTIONS`, `MANIFESTS`, `validate()`, `bind(app)`, `datasets()`,
  `get(id)`, `by_section()`, `errors()`, `available(id)`, and a `--check` CLI entry point.
- `app/catalog_api.py` — the three endpoints above.
- `tests/test_manifests.py` — §5.
- `docs/plans/PLAN-API-MCP-V2-M1.md` (this file).

**Changed — additive only**
- `app/adapters/{cpi_jp, cpi_jp_items, boj_assets, mof_jgb, jnto_visitors,
  juki_population, ssds_population}.py` — add `MANIFEST` beside `PRESENTATION`.
- `app/{equity_api, ownership_api, lvh_api, governance_api, buyback_api,
  facility_api}.py` — add `MANIFEST` at module top.
- `app/main.py` — `include_router(catalog_router)` before `router`; call
  `registry.bind(app)` inside `lifespan`, before `cache.warm`.
- `app/api.py` — `health()` gains the `manifests` block. No other change.
- `observatory/README.md` — three lines in the API section.
- `observatory/.env.example` — `MANIFEST_STRICT` (documented, default off).

**Untouched:** `app/db.py`, `app/ingest.py`, `start.sh`, `railway.json`,
`/api/v1/catalog/datasets`, every existing route's response shape, every page,
`app/mcp.py`, `app/tools.py`.

## 4. Risks

| Risk | Treatment |
|---|---|
| **A bad manifest crashes boot and the site goes down** | Quarantine, not raise, in the serving process (§2.4). Strict only under pytest and `MANIFEST_STRICT=1`. |
| Circular import (`adapter → api → adapter`) | Manifests are pure data; no adapter imports `api`. `registry` imports `api` and the equity modules; nothing imports `registry` except `catalog_api` and `main`. |
| New route shadowed by `/api/v1/{dataset}/...` | `catalog_api` included before `api.router`; a test asserts all three paths resolve to the catalog handlers. |
| Railway healthcheck | `/api/v1/catalog/datasets` untouched, and `registry.bind()` runs inside `lifespan` *before* the port takes traffic, so a slow or failing bind can never make the healthcheck flap. Bind is pure Python over an in-memory route list — microseconds. |
| Cache eviction of warm entries | New endpoints excluded from `WARM_ENDPOINTS`; payloads are a few KB. |
| Equity DB absent (a server without the file) | `available: false`, dataset still listed, no query attempted. Test runs the whole suite with the equity file hidden. |
| **The formula audit turns up derived numbers with no published formula** | Expected, and the point: rule 4 refuses them. Likely candidates — JGB `2s10s`/`10s30s` spreads (`pp`), the BOJ "from peak" drawdown and 12-month rolling net flow, JNTO's vs-2019 comparison, `pct_of_equity`. Each needs a formula written once, and any that is user-visible also needs a line in `methodology.html`. Budget for it; do not weaken rule 4 to get M1 green. |
| Manifest text drifts from what the API actually computes | Rule 7 cross-checks macro `calc`/`trust` against `api.CALC` / `api.TRUST` at validation time, not just in a test. |
| Python 3.9 | Plain dicts and functions; no `match`, no `X \| Y`, `typing.List` where needed. |
| No CI exists in this repo | `python -m app.registry --check` is a one-line manual gate documented in the README; it is **not** added to `start.sh` (that would risk boot). |

## 5. Test plan

`tests/test_manifests.py`, run with the existing `./.venv/bin/python -m pytest`:

1. **Count** — exactly 13 manifests; ids unique; macro ids == `set(api.ADAPTERS)`.
2. **Schema** — every manifest passes strict `validate()`; parametrised per dataset so a
   failure names the offender.
3. **Trust contract** — for every measure across all 13: `trust` is `official` or
   `derived`; `derived` ⇒ non-empty `calc`; `official` ⇒ no `calc`; no `model`. A
   deliberately broken fixture (derived with no `calc`, and `unit: "percent"`) must be
   rejected with a message naming the field.
4. **Route resolution** — build the real app; every `endpoints` path is in `app.routes`;
   a fixture manifest pointing at `/api/v1/nope` fails `bind()`.
5. **Calc parity** — for each series dataset and each of `index/yoy/mom/ann3m`, the
   manifest string equals `api._calc_for(measure, unit)`.
6. **Quarantine** — with a broken manifest injected and `MANIFEST_STRICT` unset, the app
   still starts, serves the other 12, and `/catalog/health` reports `attention` with the
   dataset named; with `MANIFEST_STRICT=1`, `bind()` raises.
7. **Endpoints** (TestClient) — `/catalog/manifests` returns 13 in section order;
   `/catalog/manifests/cpi-jp` returns that manifest; `/catalog/manifests/nope` is a 404
   whose body lists the valid ids; `/catalog/sections` covers all 13 with no dataset in
   two sections; every response is `json.dumps`-able with no callables in it.
8. **No regression** — `/api/v1/catalog/datasets` byte-identical before and after;
   `tests/test_refresh.py` green; `/catalog/health` keeps every existing field.
9. **Equity-absent** — the suite re-run with `equity_api.DB_PATH` pointed at a
   non-existent file: 13 still listed, 6 with `available: false`, nothing 500s.
10. **Live round-trip** (mandatory before "done") — real uvicorn on 8007; curl all three
    new endpoints and `catalog/datasets` and `catalog/health`; load cpi.html, boj.html,
    rates.html, holdings.html and confirm they are unchanged.

## 6. Open questions

1. **Fatal or quarantine at boot?** I recommend quarantine (§2.4). It's a departure from
   the parent plan's "validate at import time", and it's the single decision that
   determines whether M1 can take the live site down. Confirm.
2. **Equity dataset ids.** `tools.py:list_datasets` already tells MCP clients the
   cross-shareholding slug is `equity-holdings`; the parent plan names it
   `cross-shareholdings`. That id appears in no REST contract, only in tool prose, so
   either works. Recommendation: `cross-shareholdings` (it describes the data, and the
   v1 tool row is rewritten in M2 anyway) — but say so now, because M2 and the company
   page inherit it.
3. **`pp` vs `%` retro-fit.** Enforcing the closed unit vocabulary will label some
   existing derived measures `pp` where the API today calls them `%`. M1 only records
   the correct unit in the manifest and changes no response. Do you want a follow-up
   ticket to reconcile the live responses, or is manifest-only correct for now?
4. **Does `population-jp-history` get its own manifest or ride with `population-jp`?**
   It is a separate slug with its own dating rules, so I'd give it its own (13, as
   stated). Confirm you count it as one of the 13.
5. **Section names.** The nine in §2.1 — these become public ids in the catalog, the MCP
   `list_datasets` filter and eventually the company page's section order, so they are
   hard to change later. Happy with them?
6. **Formula authorship.** Where a derived measure has no written formula today (risk
   table), do you want me to draft the wording and bring it back for approval, or write
   it and flag the ones you should read?
