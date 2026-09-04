# PLAN — API & MCP v2: manifest-driven, six generic tools, composed company endpoint

> **Status:** PROPOSAL v1 — plan only, awaiting go-ahead. No code written.
>
> **One-liner:** make the dataset *registry* the product. One machine-readable manifest per
> dataset generates the catalog, the MCP tool surface, the composed company endpoint and
> (later) the company page — so dataset number 200 is a manifest plus an adapter, not a
> page, a tool and a hand-written API module.
>
> **Companion docs:** [PLAN-JAPAN-MACRO-OBSERVATORY.md](PLAN-JAPAN-MACRO-OBSERVATORY.md) ·
> [PLAN-CROSS-SHAREHOLDING-DB.md](PLAN-CROSS-SHAREHOLDING-DB.md) (M5: API keys, still open) ·
> `app/mcp.py` and `app/tools.py` module docstrings (current MCP).

---

## 1. Interpretation

Replace the current 19 dataset-specific MCP tools with six generic ones whose `dataset`
argument is resolved through a per-dataset manifest; serve those manifests as MCP resources
and as a catalog endpoint; add one composed `GET /api/v1/company/{code}` that assembles
every dataset's company view; make `as_of` a first-class parameter on the equity side as it
already is on the macro side; and gate access with API keys — all in Python 3.9 with no MCP
SDK, without changing the core schema, any existing endpoint, or any page.

## 2. Approach (first principles)

### 2.1 What already exists and is kept
- **Stateless Streamable-HTTP MCP** in `app/mcp.py`: JSON-RPC over one POST route, handles
  `initialize`, `ping`, `tools/list`, `tools/call`, per-IP rate limit. Sound; extended, not
  rewritten.
- **Tool layer** `app/tools.py`: tools are thin wrappers over the same functions that serve
  `/api/v1`, every call logged with a `cite` URL. The *principle* stays (no tool bypasses the
  public API's numbers); the *list* changes.
- **Macro vintages**: `observation_vintages` + `vintages.values_as_of()` + `api._release(as_of)`.
  Equity vintages are the immutable `eq_filings` rows (one per captured document).
- **Adapters export `PRESENTATION`** (macro). The manifest is a superset of it.

### 2.2 The manifest
A plain Python dict named `MANIFEST` exported by every dataset module — macro adapters and
each equity API module (`equity_api`, `ownership_api`, `lvh_api`, `governance_api`,
`buyback_api`, `facility_api`). Python, not YAML: no new dependency, importable, unit-testable,
and it can reference the module's own functions. JSON-serialisable by construction.

```
MANIFEST = {
  "id": "cross-shareholdings", "section": "ownership",
  "name": {"en": "Cross-Shareholdings", "ja": "政策保有株式"},
  "shape": "company",                       # company | series | events
  "source": {"document": "有価証券報告書 · 株式の保有状況", "publisher": "EDINET (FSA)",
             "credit": "...", "url": "..."},
  "keys": ["sec_code", "fiscal_year"],
  "vintage": {"unit": "filing", "history_from": "FY2022", "as_of": "captured_at"},
  "measures": [ {"id": "policy_total_yen", "unit": "JPY", "trust": "official"},
                {"id": "pct_of_equity", "unit": "%", "trust": "derived",
                 "calc": "policy_total_yen / equity_yen * 100"}, ... ],
  "profile": {"facts": [...4 measure ids...], "chart": {...}, "table": {...}},
  "screens": [ {"id": "largest_books", "title": "...", "sort": "book_value"} ],
  "endpoints": {"company": "/api/v1/equity/holdings/company/{sec_code}", "screen": "...",
                "summary": "..."},
  "cite": "https://.../holdings?c={sec_code}",
  "notes": ["Book values are fair-valued at period end; ..."],
  "capabilities": {"company": fn, "series": None, "screen": fn, "search": fn},   # callables
}
```
`capabilities` are the four read functions the generic tools dispatch to — the same functions
the routers call. They take `as_of` and return plain dicts.

### 2.3 The registry — `app/registry.py`
Collects every `MANIFEST` (macro `ADAPTERS` + equity modules), validates it at import time
(required keys; `trust ∈ {official, derived}`; `calc` present iff derived; every `endpoints`
path resolves to a real FastAPI route; every section id in the fixed section list), and
exposes: `datasets()`, `get(id)`, `by_section()`, `capable(cap)`. Equity manifests are
registered only when the equity DB is present (the existing `equity_available()` rule).

### 2.4 The six tools — `app/tools_v2.py`
| Tool | Args | Dispatch |
| --- | --- | --- |
| `list_datasets` | `section?` | registry → compact rows (id, section, name, shape, coverage, capabilities) |
| `describe_dataset` | `dataset` | registry → manifest minus callables, plus live coverage from the dataset's summary |
| `search` | `query, dataset?` | entity search (companies) + series search; one ranked list with `dataset` on each hit |
| `get_company` | `code, dataset?, as_of?` | no dataset → composed profile; with dataset → that manifest's `company()` |
| `get_series` | `dataset, id, from?, to?, as_of?` | series-shaped datasets (macro) → existing values path |
| `screen` | `dataset, sort, filters?, limit?, as_of?` | manifest's `screen()`; `sort` validated against `manifest.screens` |

Every result carries the same envelope: `data · provenance · calc · vintage · cite · coverage`.
Output size is budgeted per tool (the existing `_trim_points` idea generalised) — a tool that
can return 2,000 rows returns 50 with `next` hints, never the lot.

The `INSTRUCTIONS` text sent at `initialize` is generated from the registry (today it is
hand-written and still CPI-only).

### 2.5 MCP protocol additions — `app/mcp.py`
- `resources/list`: one resource per dataset, `observatory://datasets/{id}` (the manifest),
  plus `observatory://sections` and `observatory://methodology`.
- `resources/read`: returns the JSON manifest (`application/json`).
- Tool set selection by env: `MCP_TOOLSET=v1 | v2 | both` (default `v1` on first deploy,
  flipped to `v2` after parity; `both` for the transition window).
- No sessions, no streams, no SDK — unchanged.

### 2.6 Composed endpoint — `GET /api/v1/company/{code}`
`app/company_api.py`. For every registry dataset with a `company` capability: call it, build
the block from `manifest.profile` (facts resolved by measure id, table columns, chart series),
attach `api`, `mcp`, `cite`, `vintage`. Sections in the fixed order; datasets with no rows
listed under `coverage.missing`, not omitted. Query params: `as_of`, `sections`, `datasets`,
`compact` (facts only, for the MCP path). Cached via `cache.py` keyed on (code, as_of), warmed
for the top-N companies at boot like `WARM_ENDPOINTS`.
Companion: `GET /api/v1/company/{code}/coverage` (the matrix only) and
`GET /api/v1/catalog/manifests[/{id}]`.

### 2.7 `as_of` on the equity side
Semantics: **what the platform had captured on that date** — filings with
`captured_at <= as_of` (fall back to `filed_date` where capture time predates the store).
Each equity reader gains an optional ceiling; the composed endpoint passes it through; the
envelope's `vintage` block states which rule applied. Macro keeps its existing
release-in-force semantics. Immutability guardrail untouched: this is a read filter.

### 2.8 API keys and limits — `app/auth.py`
- Keys are **not** stored in DuckDB (serving process must never write it). A small
  **SQLite** file under `data/` (stdlib, concurrent-safe for this load) holds
  `key_hash, tier, label, created, revoked, daily_limit`; usage counters go to the same file,
  written by a lightweight middleware. Rotating JSONL usage log alongside (like the tool log).
- Header `X-API-Key`; absent → **public tier** (per-IP limit, latest vintage only); present
  → tier limits and `as_of`. Same middleware guards `/mcp`. Admin console (`admin_api.py`,
  `ADMIN_PASSWORD`) gets a keys tab: issue, label, revoke, see usage.
- The existing per-IP limiter in `mcp.py` moves into `auth.py` and is shared.

### 2.9 Milestones
| M | Deliverable | Risk to live site |
| --- | --- | --- |
| M1 | ✅ **Built 2026-09-04** (16 datasets) — see [PLAN-API-MCP-V2-M1.md](PLAN-API-MCP-V2-M1.md) | none — additive endpoints only |
| M2 | ✅ **Built 2026-09-04** — `tools_v2.py` (six tools, envelope, row budgets), `resources/*`, `MCP_TOOLSET` (default **`both`**, not `v1`: no known external users, and the transition window is free while both surfaces coexist), instructions generated from the registry, `lvh_api` 404 `%` bug fixed, 19 tests incl. the per-dataset × capability contract and v1 parity. `get_company` without a dataset already composes across datasets (facts + coverage) — the HTTP composed endpoint stays M3. | none — v1 tools untouched |
| M3 | `company_api.py` composed endpoint + coverage; equity `as_of` ceilings | none — new endpoint; readers gain an optional arg |
| M4 | `auth.py`: keys, tiers, limits, usage; admin keys tab; OpenAPI descriptions from manifests | middleware touches every request — see §4 |
| M5 | Flip `MCP_TOOLSET` default to `v2`; retire v1 tools after the transition window | existing connector users see new tool names |
| M6 | Company page rebuilt from the composed endpoint (own plan; `ui-ux-design` gate) | UI only |

## 3. Files / areas

**New**
- `app/registry.py` — collect + validate manifests; section list.
- `app/tools_v2.py` — the six tools, envelope builder, output budgets.
- `app/company_api.py` — `/api/v1/company/{code}`, `/coverage`, `/catalog/manifests`.
- `app/auth.py` — key store (SQLite under `data/`), tiers, limiter, middleware.
- `tests/test_manifests.py`, `tests/test_mcp_v2.py`, `tests/test_company_api.py`,
  `tests/test_auth.py`.
- `docs/plans/PLAN-API-MCP-V2.md` (this file); `observatory/README.md` API section.

**Changed (additive)**
- `app/adapters/*.py` — add `MANIFEST` (wrapping existing `PRESENTATION`).
- `app/equity_api.py`, `ownership_api.py`, `lvh_api.py`, `governance_api.py`,
  `buyback_api.py`, `facility_api.py` — add `MANIFEST`; readers accept `as_of`.
- `app/mcp.py` — `resources/*`, toolset flag, generated instructions.
- `app/main.py` — include new routers; install auth middleware (M4).
- `app/admin_api.py`, `web/admin.html` — keys tab (M4).
- `.env.example` — `MCP_TOOLSET`, `API_KEYS_DB`, `PUBLIC_DAILY_LIMIT`.
- `web/methodology.html` — `as_of` semantics for equity; envelope fields.

**Untouched**: `app/db.py` (core schema), every existing `/api/v1` route's contract,
`start.sh`, ingest, all pages until M6.

## 4. Risks (0-risk stance)

| Risk | Treatment |
| --- | --- |
| Breaking existing MCP users (tool names in saved prompts, Claude connectors) | `MCP_TOOLSET` flag; `both` during transition; v1 retired only after a dated notice |
| Generic tools confuse the assistant (wrong `dataset` ids, wrong `sort`) | `list_datasets` is compact and always first in the description; unknown ids return the valid list, never a 500; `sort` validated against manifest screens |
| Oversized tool results burn context | per-tool budgets; `compact` mode; row caps with `next` |
| Composed endpoint slow (6+ DuckDB reads) | cache keyed on (code, as_of); warm top companies at boot; each block independently try/except so one failing dataset yields `error` in its block, not a 500 |
| A tool 500s on a no-data company (the `lvh_api` `%` bug is exactly this class) | envelope rule: no-data is a valid response; contract test hits every tool with a company that has no rows |
| Auth middleware affects every request | M4 ships with `AUTH_ENABLED` default off; enabled first on staging; public tier never requires a key, so a misconfiguration degrades to "no keys", not "no service" |
| Key store write path | SQLite, not DuckDB — the one-writer guardrail is untouched; file lives on the `data/` volume |
| Equity `as_of` semantics disputed later | documented in Methodology and in every `vintage` block; capture-date rule is the default, filed-date offered as an option |
| Manifest drift from real endpoints | validation test resolves every manifest endpoint against live FastAPI routes; CI fails on drift |
| Python 3.9 | no `match`, no `X | Y`; nothing here needs 3.10 |

## 5. Test plan

1. **Manifest validation** (unit): every registered dataset passes schema checks; measures
   with `trust: derived` have `calc`; endpoints resolve to routes; sections valid; the
   registry count equals `len(ADAPTERS)` + live equity modules.
2. **MCP protocol** (TestClient): `initialize` → generated instructions mention every
   section; `tools/list` → exactly six under `v2`, 19 under `v1`, 25 under `both`;
   `resources/list` → one per dataset; `resources/read` → valid JSON manifest.
3. **Tool contract**: for every dataset × capability, `tools/call` returns the envelope with
   `cite`, `provenance.trust`, `vintage`; never a JSON-RPC error for a missing company
   (7974 on 5% filings; a delisted code; a code with no annual report).
4. **Parity**: for each of the 19 legacy tools, one generic call whose numbers match exactly
   (Nintendo holdings, Toyota unwind row, CPI headline YoY, JNTO ranking, BOJ balance).
5. **Composed endpoint**: Nintendo returns 6 datasets with rows, the section counts of the
   mockup, and `coverage.missing` lists the rest; `as_of=2025-07-01` drops the FY2026 filing
   and the buyback programme; response time < 300 ms warm, < 2 s cold.
6. **Auth**: no key → public tier and its limit; revoked key → 401; tier limits enforced;
   usage rows written; `AUTH_ENABLED=0` short-circuits everything.
7. **Live round-trip** (mandatory before "done"): real uvicorn on 8007, curl every new
   endpoint, connect Claude to `/mcp` and run a scripted set of ten questions across
   datasets, check every answer cites a URL that loads.
8. **No-regression**: existing test suite green; `catalog/health` unchanged; the six live
   pages render identically (screenshot diff at 1440).

## 6. Open questions (decide before M2)

1. **Transition window for v1 tools** — 30 days after flipping to v2, or retire immediately
   (no known external users yet)?
2. **Key transport for hosted assistants** — claude.ai custom connectors do not send custom
   headers; options are key-in-path (`/mcp/{key}`), OAuth (real work), or MCP stays public
   while the REST API is keyed. Recommendation: keyed REST now, public MCP with per-IP limits,
   key-in-path as an opt-in for Pro.
3. **Equity `as_of` rule** — capture date (what we knew) vs filed date (what existed).
   Recommendation: capture date, with `as_of_basis=filed` as an alternative.
4. **Manifest format** — Python constant (recommended) vs YAML file per dataset.
5. **Envelope on old endpoints** — leave v1 responses exactly as they are (recommended) and
   use the envelope only on new endpoints and tools, or wrap old ones under `/api/v2`?
6. **Which datasets get `screen` first** — all six equity sets have ranked endpoints today;
   macro `screen` (e.g. fastest-rising CPI items) can wait.
7. **Public tier limits** — 1,000 calls/day per IP as in the mockup, or lower?
8. **Do keys land before or after the company page rebuild** — M4 before M6 (recommended:
   keys first; the page is the demo, the key is the customer).
