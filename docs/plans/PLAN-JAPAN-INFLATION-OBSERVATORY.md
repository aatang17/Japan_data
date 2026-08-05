# PLAN — Japan Inflation Observatory

> **Status: PROPOSAL**
>
> **Audience:** public users, journalists, economists, investors, researchers, and policy teams.
>
> **Delivery shape:** a standalone CPI product using the platform's existing TypeScript, PostgreSQL, object-storage, and API patterns; it must not couple to publishing-domain tables or reader routes.
>
> **Planning assumption:** the initial public product is national Japanese CPI with Tokyo CPI as the leading regional comparison. The Japan 2020 and 2025 bases coexist as first-class, versioned data.

## 1. Product vision and trust principles

Japan Inflation Observatory answers a simple question quickly—**what is happening to Japanese prices, why, and for whom?**—while letting a professional reproduce every number. It should be more useful than a raw statistical portal without ever obscuring the official record.

### Trust contract

Every metric, chart, table, API response, and export carries one of these mutually exclusive labels:

| Label | Meaning | Requirements |
| --- | --- | --- |
| **Official statistic** | Published directly by an authority. | Agency, table/series ID, release, vintage, and source link shown. |
| **Platform-derived statistic** | Deterministic calculation using stated official inputs. | Formula, inputs, calculation version, and retrieval timestamp shown. |
| **Platform model or estimate** | Nowcast, pass-through estimate, forecast, or other judgement/model output. | Method, training/sample window, uncertainty/performance, and non-official status shown. |

Additional non-negotiable principles:

- Never replace an official published rate with a rate silently recomputed from a rebased series.
- Separate **price change** (CPI index movement) from **price level** (yen retail price or a price-level index).
- Prefer expenditure-weighted analysis; show item-count analysis only as an explicit alternative.
- Keep release vintages immutable and make revisions inspectable.
- Avoid causal language unless a documented research design supports it. Default language is descriptive: “coincides with,” “is associated with,” or “contributed mechanically.”
- Make Japanese and English names, aliases, and source fields searchable; do not hide the rich official catalogue metadata in source spreadsheets.

## 2. Seven workspaces and cross-cutting journalist tools

| Workspace | Primary users | Job to be done | Phase target |
| --- | --- | --- | --- |
| **Inflation Overview** | Everyone | Understand the latest release in 30 seconds. | MVP |
| **Item Explorer** | Academics, journalists | Search, compare, and inspect every CPI item. | MVP |
| **Contributions & Breadth** | Investors, economists | Identify what is driving, broadening, or narrowing inflation. | MVP |
| **Household Baskets** | Public, journalists, policymakers | Estimate inflation for transparent spending baskets. | Phase 2 |
| **Regional Prices** | Journalists, researchers | Compare national, Tokyo, city, and prefectural price measures without conflation. | Phase 2 |
| **Inflation Pipeline** | Investors | Follow upstream price pressures and leading indicators. | Phase 3 |
| **Data Lab** | Academics, analysts | Download, query, cite, and reproduce data. | MVP, expanded in Phase 2 |

Journalist tooling is a cross-cutting capability rather than an eighth top-level workspace. From Overview, Item Explorer, Contributions, and Regional Prices it provides defensible story cards: chart, underlying table, formula, source, neutral suggested headline, citation, and PNG/SVG/embed exports.

## 3. Scope by release

### MVP — credible national CPI foundation

- National CPI overview; all-items, ex-fresh-food, ex-fresh-food-and-energy, goods, services, food, and energy.
- Complete 2020-base explorer and 2025-base catalogue; item pages; searchable base-transition mapping.
- Contribution rankings where official values exist, clearly labelled platform estimates where they do not.
- Major-group and goods/services decompositions; weighted and item-count breadth metrics.
- Tokyo-vs-national comparison.
- CSV and Excel downloads; methodology, provenance, and release pages.
- Automated ingestion, immutable source archive, validation, and a manual publish/review gate.

### Phase 2 — personal, regional, and reusable data products

- Household basket calculator and transparent preset baskets.
- Retail Price Survey / regional retail-price workspace, city comparisons, and geographic coverage indicators.
- Saved item watchlists, release emails, embeds, image exports, and Japanese-language UI.
- Public versioned API; JSON, Parquet, reproducible Python/R snippets, citations, and BibTeX.

### Phase 3 — forward-looking and investor features

- Import prices, CGPI, SPPI, FD-ID, wages, expectations, and GDP-deflator pipeline.
- Tokyo-to-national category signal analysis and documented nowcasts.
- Pass-through studies, inflation-regime matrix, and persistent/flexible/sticky classification.
- Licensed or manually maintained consensus/surprise and market-reaction views only after data-rights review.

Out of scope until explicitly approved: a proprietary “official” household CPI, causal claims from correlation, a paid market-data feed without licensing, and a time-series database or search cluster before scale demands one.

## 4. Functional requirements

### 4.1 Inflation Overview

The landing page answers five questions: current inflation, latest-release drivers, breadth, what changed this month, and release status.

**Headline metrics.** Show current reading, prior month, change from three months earlier, contribution to headline where meaningful, trust label, release date, and vintage for:

- all-items CPI YoY;
- CPI excluding fresh food;
- CPI excluding fresh food and energy;
- MoM and three-month annualized inflation;
- latest Tokyo CPI;
- goods, services, food, and energy inflation.

Index levels may be available in a secondary control but never substitute for rate/contribution-first presentation.

**Latest-release decomposition.** Rank drivers with YoY rate, CPI weight, contribution (percentage points), and change from prior release. Users can switch positive/negative contributors, major groups/subgroups/items, goods/services, and administered/market-price classifications.

**Breadth.** Display expenditure-weighted share above 2% and 4%, declining share, weighted median, weighted trimmed mean, acceleration over 1/3/6 months, diffusion index, and count of items at a five-year high. Present both weighted and item-count variants with a visible default badge.

**Deterministic release summary.** Generate factual prose solely from approved calculation templates, e.g. “Headline inflation slowed by 0.3 percentage points; lower electricity contributions accounted for 0.2 points.” Every sentence exposes “show calculation,” listing inputs and arithmetic.

**Release status.** Display reference month, publication timestamp, base vintage, provisional/final status, next scheduled release, source table, and last successful pipeline refresh.

### 4.2 Item Explorer

The explorer is the core differentiator: permanent, versioned pages such as `/cpi/items/2025/1001` and a dense, downloadable data table.

**Search and filters.** Search Japanese name, English name, romaji/transliteration, aliases, item/group code, COICOP, parent hierarchy, related terms, and methodology. “rice,” `米`, and `kome` must resolve to the relevant rice series. Filters include:

- 2020/2025 base; active/added/removed/merged; hierarchy and COICOP;
- goods, public services, private services; fresh food, energy, public utility;
- durable/semi-durable/non-durable; basic/selective expenditure; purchase frequency;
- POS, web-scraped, retail-survey, model-formula, or seasonal items;
- national/Tokyo/regional availability, survey area, and frequency.

**Table.** Default columns: item, latest YoY, one-month change, current weight, contribution, three-month momentum, and survey method. Users can select and export index, MoM, three/six-month annualized rates, cumulative change from 2019/2020/2022, prior-base weight/weight change, history percentile, volatility, consecutive increases, contribution acceleration, national–Tokyo spread, upstream proxy, and first/last observation.

**Item page.** Include identity (names, codes, base, hierarchy, active dates, predecessor/successor, official definition, sources); time-series transformations; comparison series; collection/quality metadata; and a change log. Comparison choices include parent, headline, goods/services, Tokyo equivalent, retail price in yen where comparable, predecessor, and related CGPI/import series.

### 4.3 Contributions & Breadth

The contribution engine supports major group, subgroup, item, goods/services, food/energy/rent/discretionary, public/private, tradable/non-tradable, purchase-frequency, and essential/selective breakdowns. Views include latest release, release-to-release change, cumulative contribution, acceleration/deceleration contribution, waterfall, and historical stacked series.

Use published official contribution values if available. Derived contributions expose their formula, weight vintage, and reconciliation tolerance.

Distribution views include weighted histogram, percentiles, median, interquartile range, trimmed means, threshold shares, acceleration shares, and common splits. Persistence research measures—positive-MoM run length, autocorrelation, volatility, price-change frequency, and persistent-category share—are platform-derived. Flexible/sticky groups require an explicit platform methodology and never carry an official label.

### 4.4 Household Baskets

Users enter a monthly budget or begin with clearly documented presets: single urban renter, family with children, retired, low/high income, homeowner, renter, student, Tokyo resident, and rural household. The calculator normalizes the basket, preserves the mapping from spending category to CPI items/groups, and returns personal inflation, cumulative purchasing-power loss, difference from official CPI, largest contributors, estimated monthly-cost change, and essential/discretionary split.

Preset expenditure weights should use the Family Income and Expenditure Survey by household type/income group. Results are labelled: **“Platform-calculated CPI using official item indices and household expenditure weights”**—not an official household inflation rate.

### 4.5 Regional Prices

Every regional view identifies exactly one measure type: **index of price change**, **average retail price level**, or **regional price-level index**. It must never rank mixed concepts together.

Provide national/Tokyo CPI comparison, city retail prices for available items, regional difference indices, city rankings and ranking changes, rent/utilities/food comparisons, nationally uniform-price items, and coverage badges. Retail price pages state specification, geography, source, observation date, and whether a city price is unavailable rather than zero.

### 4.6 Inflation Pipeline

Build a transparent sequence: yen/global commodities → import prices → CGPI → retail/distribution prices → consumer-goods CPI → services CPI/wages → expectations. Phase 3 series include BOJ import/export prices, CGPI, SPPI, FD-ID, Tankan price and inflation expectations, wages/real wages, household expectations, and GDP deflator.

Tools: category-specific Tokyo lead relationships with historical error; upstream pass-through comparisons and estimated lags; and a descriptive regime matrix (goods cooling/accelerating × services cooling/accelerating). Mappings, thresholds, regressions, and nowcasts are platform estimates with visible methodology. Release-surprise/market reaction requires approved data licensing.

### 4.7 Data Lab and journalist distribution

All charts expose agency, source table, series code, base, geography, unit, seasonal-adjustment status, transformation/formula, retrieval time, release vintage, revision history, and underlying observations. Downloads support CSV, Excel, Parquet, JSON, and reproducible Python/R snippets plus citation/BibTeX.

Story finder surfaces large positive/negative contributors, acceleration/deceleration, record and cumulative gains, breadth extremes, headline divergences, regional outliers, and everyday-price changes relative to wages. It must offer a neutral headline and supporting evidence, never automated causal copy.

### 4.8 UI/UX design and accessibility standard

Use the same trust-first, professional UI/UX standard used across the GSA projects. The visual system is part of the product's credibility contract, not a later styling pass.

- **Design system first.** Define shared tokens for typography, spacing, color, borders, chart series, trust labels, table states, and responsive containers before building workspace-specific screens. Prefer a small reusable component set over bespoke page-level styling.
- **Trust is visible.** Official, platform-derived, and model/estimate labels remain adjacent to the value or chart they qualify. Source, release vintage, base, and calculation affordances are readable at the point of use—not hidden only in a methodology page.
- **Professional status language.** Use precise labels such as “Official,” “Derived,” “Estimate,” “Provisional,” “Final,” “Validated,” and “Quarantined.” Avoid casual or ambiguous status copy. Status badges are outline-oriented and do not rely on filled colored pills.
- **Responsive by requirement.** Design and verify at 390px, 768px, 1280px, and 1440px widths. Dense tables scroll inside their own container on small screens; sticky headers, filters, tooltips, and chart legends must never cover content or create horizontal page overflow.
- **Accessible by default.** Meet WCAG 2.2 AA intent for contrast, keyboard navigation, focus visibility, semantic headings, form labels, screen-reader names, reduced motion, and non-color encodings. Charts expose an equivalent table or textual summary; Japanese and English text must remain legible with appropriate font fallback.
- **Data-dense interaction.** Every chart has explicit loading, empty, error, and unavailable states; tooltips are keyboard-reachable where practical; tables support column selection, sorting, pagination/virtualization, and export without losing the active filters or provenance context.
- **Server-rendered and citable.** Public overview, item, release, and methodology pages render meaningful content on the server for SEO and academic citation. Client-side enhancement adds exploration but is not the only path to the data.
- **Look-at-it gate.** Before a UI milestone is called complete, inspect the real rendered page at all four widths, verify exact URLs, check chart/table overflow and overlays, and test one keyboard-only and one screen-reader-oriented path. A mock or unrendered screenshot is not sufficient evidence.
- **Bilingual consistency.** Japanese/English labels, aliases, dates, units, and number formatting are versioned content. Layout must tolerate longer translations, Japanese glyph metrics, and mixed-script item names without truncating the trust or provenance labels.

## 5. Data model

Treat classifications as versioned records, not UI constants. All tables include ordinary audit fields; source identifiers and foreign keys below are required unless an observation genuinely lacks one.

| Entity | Essential fields and rules |
| --- | --- |
| `item_versions` | `id`, `base_vintage`, official item/group code, serial, names JA/EN, aggregate flag, active dates, parent/predecessor/successor IDs, COICOP, goods-services, durability, flags (energy/fresh-food/public-utility/etc.), purchase frequency, elasticity, survey-area/characteristic/frequency/months, substitution, collection method, model-formula flag, source document. |
| `item_aliases` | `item_version_id`, locale, normalized alias, alias type (official, translation, synonym, romaji); supports bilingual search without changing canonical names. |
| `geographies` | Stable geography ID, parent geography, name JA/EN, coverage type, and effective dates. |
| `observations` | `series_id`, `item_version_id`, `geography_id`, period/frequency, measure, numeric value/unit, seasonal-adjustment flag, official/derived/model label, `release_id`, source table/status, retrieval time, calculation version where non-official. |
| `weights` | Item/geography/household type/reference year, raw and per-10,000 weight, base vintage, source/release. |
| `base_mappings` | old/new item versions, relationship (`unchanged`, `renamed`, `split`, `merged`, `added`, `removed`, `concept_changed`, `methodology_changed`), effective date, mapping quality, review notes. |
| `release_vintages` | Agency, dataset, reference period, publication/source-update/ingestion times, base, checksum, source URL, superseded release. Immutable once published. |
| `source_artifacts` | Object key, source URL, content type, checksum, retrieval time, parser version, associated release. |
| `derived_runs` | Indicator name/version, inputs and release IDs, formula/config hash, completed time, quality state. |
| `basket_definitions` / `basket_runs` | Preset or user-normalized allocation, CPI mapping, source expenditure vintage, calculated result, input hash; do not persist personal budgets without explicit retention consent. |

Supported observation measures include index, high-precision index, published YoY, published MoM, derived YoY/MoM, contribution, retail price yen, weight, annual average, and fiscal-year average. Distinguish missing values from zeros at storage and API level.

## 6. 2020-to-2025 base-transition rules

The 2025-base transition is a data-contract problem, not a display toggle. Store and expose three distinct concepts:

1. **Original-vintage index** — value published in its original base.
2. **Official linked index** — historical index linked/rebased by the Statistics Bureau to 2025 base.
3. **Official published rate of change** — rate published for that original period.

The Statistics Bureau notes that linked historical index levels and previously published rates should not be treated as interchangeable. Therefore:

- Never overwrite an original observation; retain release and source artefact links.
- Default rate charts to **Official published rates** when available; identify a rate calculated from linked levels as derived.
- Let users choose among “Official published rates,” “Linked 2025-base index levels,” and “Original-vintage data.” Preserve the choice in URLs/download metadata.
- Require `base_vintage` in every item identity, API filter, export, chart tooltip, and calculation input.
- Only calculate cross-base continuity where mapping quality permits it. Splits, merges, concept/method changes, and added/removed items show an explicit discontinuity/qualification rather than false continuity.
- Reconcile each base’s published weights to 10,000 independently; never infer a 2025 weight from a 2020 item mapping.

## 7. Ingestion, validation, and publish architecture

### Data layers

1. **Immutable source archive:** original API responses, CSV/XLSX/PDF, release pages, and metadata snapshots in object storage with URL, checksum, retrieval time, and parser version.
2. **Normalized official data:** items, hierarchies, observations, weights, geographies, classifications, mappings, and releases. No analytics generated in this layer.
3. **Derived analytics:** rates, annualized momentum, contributions, breadth, percentiles, cumulative inflation, household baskets, and mapping diagnostics. Every result points to `derived_runs`.
4. **Presentation tables:** cache/materialize latest overview, contribution rankings, search documents, breadth snapshots, and common comparisons; rebuild atomically only after validation passes.

### Release workflow

```text
Official release / metadata update
  → fetch and archive
  → schema + checksum checks
  → normalize official records
  → reconciliation and transition tests
  → calculate derived analytics
  → reviewer approves release summary
  → atomically publish API/cache version
  → retain prior public vintage
```

### Automated validation gates

- Every official item code and hierarchy is recognized; parent chains are valid and acyclic.
- Base-specific weight totals reconcile to published totals/10,000 within documented tolerance.
- No unexplained duplicate series, gaps, or new schema fields; missing is not converted to zero.
- Published headline values and expected item counts match source releases; bilingual names are present where source provides them.
- Contribution totals reconcile to headline within a disclosed tolerance; official contributions take precedence.
- Source publication time is newer than the prior accepted release unless a revision is explicitly detected.
- Mapping coverage and relationship types reconcile to the 2020/2025 catalogues; low-quality mappings block continuity claims.
- Parser changes, checksum changes, or source schema drift quarantine the release for manual review.

Release health is observable: pipeline run, parser version, source status, number of quarantined records, and publish decision are retained as an audit trail.

## 8. API outline

Version REST responses from day one, use cursor pagination for item/observation lists, and return a provenance object on every response. Initial read-only endpoints:

```text
GET /api/v1/cpi/releases
GET /api/v1/cpi/releases/{releaseDate}
GET /api/v1/cpi/overview?geo=japan&base=2025
GET /api/v1/cpi/items?q=rice&base=2025&collection_method=pos
GET /api/v1/cpi/items/{base}/{itemCode}
GET /api/v1/cpi/observations?item=1001&geo=japan&measure=published_yoy
GET /api/v1/cpi/contributions?period=2026-06&level=item&direction=positive
GET /api/v1/cpi/breadth?period=2026-06&weighting=expenditure
GET /api/v1/cpi/bases/2020/mappings/2025
GET /api/v1/cpi/regions?measure=retail_price_yen&item=1001&period=2026-06
GET /api/v1/catalog/sources/{sourceId}
```

Phase 2 adds basket computation with a rate-limited, non-persistent-by-default request contract and export jobs. API error payloads distinguish invalid filters, unavailable data, suppressed/unsupported comparisons, and unpublished/quarantined release data. OpenAPI describes measure semantics and trust label vocabulary.

## 9. Technical architecture

Use existing platform conventions where they fit, while isolating inflation data and services from publishing-domain code.

| Concern | Recommendation | Rationale |
| --- | --- | --- |
| Ingestion/analysis | Python 3.12, Polars (pandas acceptable for small exceptions), DuckDB for local inspection/validation | Strong tabular/reproducibility workflow; scale is modest. |
| Transactional store | PostgreSQL with ordinary relational tables and materialized views | Versioned metadata, provenance, and release queries need relational integrity. |
| Research files/archive | Existing S3-compatible object storage; Parquet for bulk exports | Immutable, economical source and download storage. |
| API | Existing NestJS API conventions or a dedicated FastAPI data service behind the same gateway; choose one ownership model before build | Avoid duplicate auth, observability, and OpenAPI behavior. |
| Frontend | Existing Next.js application or dedicated Next.js app; server-render methodology/item pages and client-render exploration | SEO/citability plus dense interactive use. |
| Charts/tables | ECharts or Plotly; virtualized tables | Supports dense time series and hundreds of items. |
| Search | PostgreSQL full-text + trigram/aliases/transliterations first | Japanese/English search works without premature OpenSearch. |
| Jobs | Scheduled idempotent release jobs with explicit manual approval | Reliable official-release processing and easy reruns. |
| UI/UX system | Shared design tokens/components, ECharts or Plotly wrappers, accessible table primitives, and responsive visual QA | Keeps trust, density, bilingual layout, and accessibility consistent across seven workspaces. |

Do not introduce a specialized time-series database, OpenSearch, or streaming platform in MVP. Metadata quality, official base changes, and traceability—not data volume—are the critical constraints.

## 10. Source inventory and provenance policy

Primary sources are the Statistics Bureau CPI catalogue/release tables, e-Stat metadata/observations, Retail Price Survey, Family Income and Expenditure Survey, and Bank of Japan price/expectation series. Store a source-registry record for every imported table, including licensing/terms review and an operator-facing retrieval method.

Relevant official starting points:

- Statistics Bureau 2025-base CPI item catalogue: <https://www.stat.go.jp/english/data/cpi/pdf/2025base-list.pdf>
- Statistics Bureau 2025-base transition information: <https://www.stat.go.jp/english/data/cpi/2025plan.html>
- e-Stat API specification: <https://www.e-stat.go.jp/api/en/api-info/api-spec>
- Retail Price Survey methodology/coverage: <https://www.stat.go.jp/english/data/kouri/doukou/qa-1.html>
- Family Income and Expenditure Survey: <https://www.stat.go.jp/english/data/sousetai/es25.html>
- BOJ CGPI and related price indices: <https://www.boj.or.jp/en/statistics/pi/cgpi_2020/index.htm>

No source URL alone is provenance: each displayed value must link through to the exact retrieved artefact and release record used.

## 11. Milestones and workstreams for a 2–3 engineer team

Assume two full-stack/data engineers, with a third engineer part-time for frontend/release UX or data quality. Milestones are outcome gates, not calendar promises; a practical MVP is approximately 12–16 weeks once source access and data interpretation decisions are closed.

| Milestone | Outcome | Primary owner(s) | Exit criteria |
| --- | --- | --- | --- |
| M0 — Foundations (weeks 1–2) | Source registry, schema decision, UX/provenance contract, sample archive. | Data + product | Sample release is ingested, versioned, and manually traceable end-to-end. |
| M1 — Official data core (weeks 3–5) | Item versions, releases, archive, 2020/2025 mapping, validation harness. | Data engineer | Known source values, item counts, weights, and mappings pass tests. |
| M2 — MVP API and explorer (weeks 5–8) | Search, item APIs/pages, downloads, base-choice UX. | Full-stack + frontend | Rice/米/kome search, permanent pages, and provenance exports work. |
| M3 — Overview and analysis (weeks 8–11) | Headline, contributions, breadth, Tokyo comparison, release narrative. | Full-stack + data | Latest release reconciles; every narrative claim has a calculation link. |
| M4 — Release operations (weeks 11–13) | Scheduler, quarantine/review, observability, documentation, launch QA. | Data + full-stack | Two consecutive dry-run releases publish/revert safely. |
| M5 — Phase 2 | Baskets, regions, API/embeds/i18n. | Team | Pilot users can reproduce and export expected outputs. |
| M6 — Phase 3 | Pipeline, nowcasts, models, licensed data integrations. | Data + full-stack | Model cards and historical evaluation are published before live use. |

Suggested workstreams run in parallel after M0:

- **Data and methods:** source adapters, release archive, mapping curation, validation/reconciliation, derived formulas, model cards.
- **Platform/API:** relational schema, job orchestration, cached read models, OpenAPI, exports, observability.
- **Product/UI:** overview, item explorer, chart/table interaction, Japanese/English search, methodology and journalist outputs.

## 12. Risks and open decisions

| Risk / decision | Why it matters | Proposed treatment | Severity |
| --- | --- | --- | --- |
| Exact product boundary in `gsa-platform` | The repository is a publishing platform; a CPI product needs clear isolation. | Create a dedicated app/module and independent schema namespace; decide deployment/domain before M0. | High |
| 2020–2025 mapping quality | False continuity would damage credibility. | Curated mapping table, explicit confidence, no derived continuity across concept/method changes. | High |
| Official table/API access and licensing | Ingestion reliability and redistribution rights are prerequisites. | Source registry with terms/access review; archive raw evidence; do not launch unsupported data. | High |
| Contribution methodology | Item contributions may not be published at every desired cut. | Prefer official values; document estimate formula and reconciliation; label estimates. | High |
| Translation/alias quality | Search failures undermine the item explorer. | Version aliases; editorial review of high-traffic items; record source and reviewer. | Medium |
| Price levels vs CPI | Misleading city rankings are easy to create. | Separate measure types in schema, UI, and API; enforce in chart component. | High |
| Household basket expectations | Users may mistake results for official rates. | Persistent non-official label, visible weights/mapping/formula, privacy-minimising defaults. | High |
| Scheduled release timing/revisions | Premature publication risks errors. | Quarantine and human approval; immutable vintages and rollback to last accepted release. | High |
| Market-data licensing | Consensus and reaction features may be restricted. | Keep in Phase 3; obtain explicit entitlement before storage or display. | Medium |
| API openness and operating cost | Unbounded downloads could degrade release traffic. | Read-only public API with caching, pagination, rate limits, and export jobs. | Medium |

Open decisions to close in M0:

1. Dedicated subdomain/app versus a route within the current web application.
2. NestJS-only API versus a dedicated FastAPI data service; ownership of schema/migrations and jobs.
3. Canonical source tables and retrieval method for each MVP measure; e-Stat application-ID handling.
4. Exact reconciliation formula/tolerance for contributions and breadth exclusions.
5. Target Japanese/English launch level and editorial ownership of translations/aliases.
6. Whether basket inputs are anonymous session-only (recommended) or offer account-backed saved baskets.
7. Geography scope after Tokyo: cities only, prefectures, or both; which retail-price comparisons are valid enough to publish.

## 13. Acceptance criteria

### MVP product acceptance

- A visitor can understand headline, core, goods, services, food, energy, latest Tokyo, drivers, breadth, and release status from the overview without reading raw index levels.
- Each displayed metric identifies its trust label, release/vintage, source, and—if derived—formula and inputs.
- Search returns relevant 2020 and 2025 items for Japanese, English, code, and approved romanized aliases; results can be filtered and downloaded.
- Every item page has a stable base-qualified URL, identity/metadata, transformation choices, provenance, and base-transition treatment.
- Contributions and breadth default to expenditure weighting; alternative item-count presentation is visibly differentiated.
- The 2020/2025 UI never silently computes a published historical rate from a linked index. Discontinuous/low-confidence mappings are disclosed.
- Tokyo/national comparisons and price-level views state their geography, measure type, and coverage; the UI cannot mix index changes and yen prices in one rank.
- CSV/XLSX exports contain data dictionary fields, source/release identifiers, base, trust label, and retrieval date.
- Overview, item, release, and methodology pages render meaningful server-side content, and every value keeps its trust label and provenance visible at the point of use.
- UI verification passes at 390px, 768px, 1280px, and 1440px without page-level horizontal overflow, hidden sticky content, or inaccessible chart/table states.
- Keyboard navigation, focus visibility, semantic headings/labels, contrast, reduced-motion behavior, and an equivalent non-visual chart representation meet the project's WCAG 2.2 AA target.

### Data and operational acceptance

- A release can run from source artefact to publish candidate idempotently; re-running does not mutate prior vintage data.
- Validation blocks publication for source-schema drift, unreconciled headline/weights, unrecognized item codes, invalid hierarchy, duplicate observations, or undeclared mapping changes.
- Two consecutive dry runs against a current release and a revised/historical release pass reconciliation and show a human-reviewable diff.
- Published overview data has a recoverable prior public snapshot; release approver and validation result are retained.
- API is documented in OpenAPI, paginated/cached, and returns provenance consistently across endpoint families.

## 14. Prioritized backlog

| Priority | Backlog item | Dependency / note |
| --- | --- | --- |
| P0 | Confirm product boundary, deployment domain, owner, and source rights. | M0 decision; blocks build. |
| P0 | Create source registry and immutable artefact archive with checksums. | Foundation for credibility/reproducibility. |
| P0 | Implement versioned CPI item, observation, release, weight, geography, and mapping schema. | Keep separate from publishing tables. |
| P0 | Build 2020/2025 catalogue import and human-review mapping workflow. | Must precede UI continuity features. |
| P0 | Implement release ingestion, quarantine, reconciliation tests, and audit trail. | Do before public display. |
| P0 | Deliver read-only MVP API with provenance envelope and exports. | Enables UI and Data Lab. |
| P0 | Build Item Explorer search, filters, item pages, and permanent URLs. | Core user differentiator. |
| P0 | Build overview, official/derived labels, release status, and calculation reveal. | Public landing experience. |
| P0 | Build official contribution and weighted-breadth views with reconciliation. | Clearly label estimates. |
| P0 | Establish shared UI/UX tokens, trust-label components, responsive layout primitives, and visual/accessibility QA gates. | Must precede workspace implementation; use the GSA-style design standard. |
| P1 | Tokyo comparison and measure-type safeguards. | Complete MVP if source ready; otherwise staged. |
| P1 | Journalist story cards, neutral headlines, citation/embed/image exports. | Uses MVP analysis/read models. |
| P1 | Public API keys/rate limits, Parquet/JSON, Python/R snippets, BibTeX. | Data Lab expansion. |
| P1 | Household basket calculator and presets. | Requires CPI-to-expenditure mapping and privacy decisions. |
| P1 | Regional retail price/city comparison workspace. | Requires coverage and comparability review. |
| P1 | Japanese UI and saved watchlists/release emails. | Ship after core terminology is stable. |
| P2 | BOJ pipeline ingestion and pass-through explorer. | Phase 3 data/model work. |
| P2 | Tokyo-to-national nowcasts and regime matrix. | Publish validation/model card first. |
| P2 | Licensed consensus, surprise, and market-reaction features. | Entitlement and legal approval required. |

## 15. Definition of ready to build

Engineering starts only when M0 has recorded: the deployment boundary; named owners; source table and redistribution terms for each MVP metric; e-Stat credential/operator process; initial 2020/2025 mapping rules; contribution formulas/tolerances; and a reviewed wireframe showing trust labels and base choices. The first implementation slice should be one fully traceable release, 10 representative items (including a renamed or discontinued item), and a minimal overview—then expand catalogue coverage only after the provenance and validation contract holds.
