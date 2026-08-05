# IMPLEMENTATION — Japan Inflation Observatory

> **Status:** PROPOSAL — implementation companion to [PLAN-JAPAN-INFLATION-OBSERVATORY.md](PLAN-JAPAN-INFLATION-OBSERVATORY.md).
>
> **Team assumption:** two full-stack/data engineers plus a part-time third for frontend/data quality. MVP ≈ 12–16 weeks once M0 decisions close. Milestones are outcome gates, not calendar promises.

## 1. Architecture overview

Two layers, strictly separated:

- **Observatory core (dataset-agnostic):** source registry, immutable artefact archive, releases/vintages, versioned series and classifications, observations, derived-run tracking, trust labels, provenance API envelope, validation framework, publish workflow.
- **Dataset verticals (config + adapters):** per-dataset ingestion adapters, classification records, derived-indicator definitions, and UI workspaces. Japan CPI is vertical #1; Japan-specific logic (e-Stat parsing, 2020→2025 base transition, Tokyo geography) lives only here.

**Generality test:** onboarding a second dataset requires a new adapter and new classification/config records — never a core schema migration.

### Data layers

1. **Immutable source archive** — original API responses/CSV/XLSX/PDF in object storage with URL, checksum, retrieval time, parser version.
2. **Normalized official data** — series, hierarchies, observations, weights, geographies, mappings, releases. No analytics here.
3. **Derived analytics** — rates, momentum, contributions, breadth, baskets; every result points to a `derived_runs` record.
4. **Presentation/read models** — cached overview, rankings, search documents; rebuilt atomically only after validation passes.

## 2. Tech stack

| Concern | Choice | Note |
| --- | --- | --- |
| Ingestion/analysis | Python 3.12, Polars, DuckDB for local validation | Scale is modest; reproducibility matters most |
| Transactional store | PostgreSQL + materialized views | Versioned metadata and provenance need relational integrity |
| Archive/exports | Existing S3-compatible object storage; Parquet for bulk | Immutable, cheap |
| API | NestJS conventions **or** dedicated FastAPI service behind the same gateway — one ownership model, decided in M0 | Avoid duplicate auth/observability |
| Frontend | Next.js; server-render item/methodology pages (SEO/citability), client-render exploration | |
| Charts/tables | ECharts or Plotly; virtualized tables | Hundreds of series per view |
| Search | PostgreSQL full-text + trigram over aliases/transliterations | No OpenSearch in MVP |
| Jobs | Scheduled idempotent release jobs with manual approval gate | |
| Billing (Phase 2) | Stripe subscriptions + API keys with rate limiting | Paywall line decided in M0 |

Do **not** introduce a time-series database, search cluster, or streaming platform in MVP; metadata quality and traceability are the constraints, not volume.

## 3. Core data model

All tables carry audit fields. Names are dataset-agnostic; Japan CPI values are rows, not columns.

| Entity | Essentials |
| --- | --- |
| `datasets` | Dataset ID, country, agency, cadence, adapter identifier, license/terms reference |
| `series_versions` | `dataset_id`, `vintage_scheme` value (e.g. CPI base 2020/2025), official code, names JA/EN, aggregate flag, active dates, parent/predecessor/successor, classification refs (COICOP, goods/services, durability, energy/fresh-food flags, collection method, frequency), source document |
| `series_aliases` | `series_version_id`, locale, normalized alias, type (official, translation, synonym, romaji) |
| `geographies` | Stable ID, parent, names JA/EN, coverage type, effective dates |
| `observations` | `series_version_id`, `geography_id`, period/frequency, measure, value/unit, seasonal-adjustment flag, trust label, `release_id`, source table/status, retrieval time, calc version if derived. Missing ≠ zero, enforced at storage and API level |
| `weights` | Series/geography/household-type/reference-year, raw and per-10,000 weight, vintage, source release |
| `vintage_mappings` | Old/new series versions, relationship (`unchanged`, `renamed`, `split`, `merged`, `added`, `removed`, `concept_changed`, `methodology_changed`), mapping quality, review notes |
| `release_vintages` | Agency, dataset, reference period, publication/ingestion times, vintage, checksum, source URL, superseded-by. **Immutable once published** |
| `source_artifacts` | Object key, URL, content type, checksum, retrieval time, parser version, release |
| `derived_runs` | Indicator name/version, input release IDs, formula/config hash, completed time, quality state |
| `basket_definitions` / `basket_runs` | Preset or normalized allocation, series mapping, expenditure vintage, result, input hash; no personal budgets persisted without explicit consent |

Measures include: index, published YoY/MoM, derived YoY/MoM, contribution, retail price (yen), weight, annual/fiscal-year average.

## 4. Japan CPI vertical: 2020→2025 base transition

The transition is a data-contract problem. Store three distinct concepts and never conflate them:

1. **Original-vintage index** — as published in its original base.
2. **Official linked index** — historical levels linked to 2025 base by the Statistics Bureau.
3. **Official published rate** — the rate published for that original period.

Rules:

- Never overwrite an original observation; rate charts default to official published rates; rates computed from linked levels are labelled derived.
- Users choose among the three concepts; the choice persists in URLs and export metadata.
- `vintage` is required in every series identity, API filter, export, tooltip, and calculation input.
- Cross-base continuity is computed only where mapping quality permits; splits/merges/concept changes show explicit discontinuities.
- Each base's weights reconcile to 10,000 independently; never infer a 2025 weight from a 2020 mapping.

## 5. Release pipeline and validation gates

```text
Official release / metadata update
  → fetch and archive (checksum, parser version)
  → schema + checksum checks
  → normalize official records
  → reconciliation and transition tests
  → calculate derived analytics
  → reviewer approves release summary
  → atomically publish API/cache version
  → retain prior public vintage (rollback target)
```

Publication is blocked by any of:

- Unrecognized series code, invalid/cyclic hierarchy, unexplained duplicates or gaps, missing converted to zero.
- Weight totals not reconciling to published totals within documented tolerance.
- Headline values or item counts not matching source; contribution totals not reconciling to headline within disclosed tolerance (official contributions take precedence).
- Source publication time older than prior accepted release without an explicit revision marker.
- Mapping coverage inconsistent with the 2020/2025 catalogues; low-quality mappings block continuity claims.
- Parser change, checksum change, or source schema drift → quarantine for manual review.

Pipeline run, parser version, quarantine counts, and publish decisions are retained as an audit trail.

## 6. API outline

Versioned REST from day one; cursor pagination; provenance object on every response; OpenAPI documents measure semantics and trust-label vocabulary. Paths are dataset-scoped for platform generality:

```text
GET /api/v1/{dataset}/releases
GET /api/v1/{dataset}/overview?geo=japan&vintage=2025
GET /api/v1/{dataset}/series?q=rice&vintage=2025&collection_method=pos
GET /api/v1/{dataset}/series/{vintage}/{code}
GET /api/v1/{dataset}/observations?series=1001&measure=published_yoy
GET /api/v1/{dataset}/contributions?period=2026-06&level=item&direction=positive
GET /api/v1/{dataset}/breadth?period=2026-06&weighting=expenditure
GET /api/v1/{dataset}/vintages/2020/mappings/2025
GET /api/v1/catalog/sources/{sourceId}
```

MVP `{dataset}` = `cpi-jp`. Errors distinguish invalid filters, unavailable data, suppressed comparisons, and quarantined releases. Phase 2 adds API keys, rate limits/tiers, basket computation (non-persistent by default), and export jobs.

## 7. Milestones

| Milestone | Outcome | Exit criteria |
| --- | --- | --- |
| **M0 — Foundations** (wk 1–2) | Source registry, schema decision, provenance/UX contract, paywall line, sample archive | One sample release ingested, versioned, manually traceable end-to-end |
| **M1 — Official data core** (wk 3–5) | Series versions, releases, archive, 2020/2025 mappings, validation harness | Known source values, item counts, weights, mappings pass tests |
| **M2 — API and explorer** (wk 5–8) | Search, series APIs/pages, downloads, vintage-choice UX | rice/米/kome search works; permanent pages; provenance exports |
| **M3 — Overview and analysis** (wk 8–11) | Headline, contributions, breadth, Tokyo comparison, release narrative | Latest release reconciles; every narrative claim links to its calculation |
| **M4 — Release operations + launch** (wk 11–13) | Scheduler, quarantine/review, observability, metrics instrumentation, QA | Two consecutive dry-run releases publish and revert safely |
| **M5 — Monetization** (Phase 2) | Accounts, Pro subscription, alerts/watchlists, public API keys/tiers, baskets, regional, JA UI | Paid conversion live; pilot users reproduce and export expected outputs |
| **M6 — Investor depth + platform proof** (Phase 3) | Pipeline datasets, nowcasts with model cards, licensed data, second dataset onboarded | Model cards published before live use; dataset #2 required no core migration |

Parallel workstreams after M0:

- **Data/methods:** source adapters, archive, mapping curation, validation, derived formulas, model cards.
- **Platform/API:** schema, job orchestration, read models, OpenAPI, exports, observability, billing (M5).
- **Product/UI:** overview, explorer, chart/table interaction, bilingual search, methodology and journalist outputs.

## 8. Acceptance criteria

**Product (MVP):**

- A visitor understands headline, core, goods/services/food/energy, Tokyo, drivers, breadth, and release status from the overview without reading raw index levels.
- Every displayed metric shows trust label, release/vintage, source, and — if derived — formula and inputs.
- Search resolves Japanese, English, code, and romaji queries across both bases; results filter and export.
- Every series page has a stable vintage-qualified URL; the UI never silently computes a published historical rate from a linked index; low-confidence mappings are disclosed.
- Price-change and price-level measures can never be mixed in one ranking.
- Exports carry data dictionary, source/release identifiers, vintage, trust label, retrieval date.

**Data/operations:**

- A release runs from artefact to publish candidate idempotently; re-runs never mutate prior vintages.
- Validation blocks publication on any Section 5 gate; two consecutive dry runs (current + revised/historical release) pass with a human-reviewable diff.
- Published data has a recoverable prior snapshot; approver and validation results are retained.
- API is OpenAPI-documented, paginated, cached, provenance-consistent.

**Commercial (M4–M5):**

- Release-day traffic, return-rate, and conversion metrics instrumented before launch.
- Paywall enforces the M0-decided line without breaking free citations/SEO pages.
- API keys, rate limits, and Stripe billing function end-to-end for at least one paid pilot.

## 9. Prioritized backlog

| Priority | Item | Note |
| --- | --- | --- |
| P0 | Close M0 decisions: boundary, owners, source rights, paywall line | Blocks build |
| P0 | Source registry + immutable artefact archive with checksums | Credibility foundation |
| P0 | Core versioned schema (datasets, series, observations, releases, weights, geographies, mappings) | Dataset-agnostic from day one |
| P0 | 2020/2025 catalogue import + human-review mapping workflow | Precedes continuity features |
| P0 | Release ingestion, quarantine, reconciliation tests, audit trail | Before any public display |
| P0 | Read-only MVP API with provenance envelope + exports | Enables UI and Data Lab |
| P0 | Item Explorer: search, filters, permanent pages | Core differentiator |
| P0 | Overview with trust labels, release status, calculation reveal | Landing experience |
| P0 | Contributions + weighted breadth with reconciliation | Core investor value |
| P1 | Tokyo comparison + measure-type safeguards | MVP if source ready |
| P1 | Accounts, Pro subscription, watchlists, release alerts | Revenue |
| P1 | Public API keys, tiers, Parquet/JSON, Python/R snippets, BibTeX | Revenue |
| P1 | Journalist story cards, citations, embeds | Funnel/distribution |
| P1 | Basket calculator + presets; regional workspace; Japanese UI | Engagement |
| P2 | BOJ pipeline ingestion + pass-through explorer | Investor depth |
| P2 | Tokyo-to-national nowcasts with model cards | Publish validation first |
| P2 | Second dataset onboarding (wages or PPI) | Platform-generality proof |
| P2 | Licensed consensus/surprise/market-reaction | Entitlement required |

## 10. Source inventory

Primary: Statistics Bureau CPI catalogue and release tables, e-Stat API, Retail Price Survey, Family Income and Expenditure Survey, BOJ price/expectation series. Every imported table gets a source-registry record with licensing/terms review. A URL alone is not provenance — each displayed value links to the exact retrieved artefact and release record.

- 2025-base CPI item catalogue: <https://www.stat.go.jp/english/data/cpi/pdf/2025base-list.pdf>
- 2025-base transition info: <https://www.stat.go.jp/english/data/cpi/2025plan.html>
- e-Stat API spec: <https://www.e-stat.go.jp/api/en/api-info/api-spec>
- Retail Price Survey: <https://www.stat.go.jp/english/data/kouri/doukou/qa-1.html>
- Family Income and Expenditure Survey: <https://www.stat.go.jp/english/data/sousetai/es25.html>
- BOJ CGPI: <https://www.boj.or.jp/en/statistics/pi/cgpi_2020/index.htm>
