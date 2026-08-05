# PLAN — Japan Inflation Observatory

> **Status:** PROPOSAL v2 (commercial reframe)
>
> **One-liner:** Subscription-grade Japanese inflation intelligence — faster and clearer than official portals, cheaper and more transparent than terminals, with every number reproducible to its official source.
>
> **Platform framing:** Japan CPI is the first vertical on a dataset-agnostic "Observatory" data platform. The core (sources, releases, vintages, series, provenance, trust labels) must carry future datasets — Japan wages/PPI, then other countries — without schema rework.
>
> **Companion doc:** [IMPL-JAPAN-INFLATION-OBSERVATORY.md](IMPL-JAPAN-INFLATION-OBSERVATORY.md) covers architecture, data model, milestones, and acceptance criteria.

## 1. Why now

- The **2025 CPI base transition** breaks every casual consumer of Japanese price data; whoever handles it correctly and visibly earns durable trust.
- Japan's exit from the deflation era and BOJ policy normalization have made Japanese inflation a **first-order global macro trade**; demand for release-day analysis is high.
- The official record (e-Stat, Statistics Bureau tables) is authoritative but hard to use, poorly searchable in English, and offers no analytics. Terminals are expensive and shallow on Japanese CPI detail.

## 2. Customers and commercial model

**Primary paying customer: professional investors** — macro/rates/FX PMs, hedge fund and sell-side economists, strategists, and their data teams. They pay for release-day speed, contribution/breadth analytics, vintage-correct history, and a licensed API.

**Free tier is the acquisition funnel**, not a separate mission: public users, journalists, and academics get the overview and limited explorer; journalist story cards and citable permanent URLs are the distribution/SEO engine that builds the brand investors trust.

| Tier | Who | Gets | Converts via |
| --- | --- | --- | --- |
| **Free** | Public, journalists, academics | Overview, limited explorer, exports with attribution, methodology | SEO, citations, release-day traffic |
| **Pro** (individual subscription) | Analysts, economists, journalists on deadline | Full explorer, watchlists, release-day alerts, full contribution/breadth analytics, bulk downloads | Release-day paywall on depth |
| **API / Data** (team) | Quant and data teams | Versioned REST API, Parquet bulk, vintage history, SLA | Rate-limited free keys → paid |
| **Enterprise** | Funds, research shops | Licensing, custom feeds, nowcasts, support | Direct sales |

Pricing points are an open decision (Section 6); the tier structure is not.

**Success metrics:** release-day unique visitors and return rate across release cycles; free→Pro conversion; active API keys and paid seats; citation/backlink growth. Instrument these from MVP.

**Positioning:** vs e-Stat — usability, English, analytics; vs terminals — price, CPI depth, provenance; vs nowcasters (Truflation/PriceStats) — official-first trust, not alternative data. Provenance is the moat: no competitor shows the formula and source artefact behind every number.

## 3. Trust contract

Every metric, chart, API response, and export carries exactly one label:

| Label | Meaning | Must show |
| --- | --- | --- |
| **Official statistic** | Published by an authority | Agency, series ID, release, vintage, source link |
| **Platform-derived** | Deterministic calc from official inputs | Formula, inputs, calc version, retrieval time |
| **Platform model/estimate** | Nowcast, pass-through, forecast | Method, sample window, uncertainty, non-official status |

Non-negotiable principles:

- Never silently replace an official published rate with one recomputed from a rebased series; release vintages are immutable and revisions inspectable.
- Separate **price change** (index movement) from **price level** (yen prices); never rank mixed measure types together.
- Default to expenditure-weighted analysis; item-count views are an explicit alternative.
- Descriptive language only ("coincides with", "contributed mechanically") unless a documented research design supports a causal claim.
- Japanese and English names, aliases, and official metadata are first-class and searchable.

This contract is a commercial asset: it is what lets a PM put our number in front of a client.

## 4. Product scope by phase

Investor-facing analytics move earlier than in v1; monetization infrastructure lands in Phase 2, not "someday".

### MVP — the credible release-day product (free + Pro preview)

- **Overview:** headline/core/core-core, goods/services/food/energy, MoM and 3m-annualized, Tokyo comparison, release status, and a deterministic release summary where every sentence exposes its calculation.
- **Contributions & breadth:** driver rankings (official values preferred, estimates labelled), weighted breadth metrics (shares above 2%/4%, weighted median, trimmed mean, diffusion), release-to-release change.
- **Item Explorer:** all 2020- and 2025-base items with bilingual search ("rice" / 米 / kome), permanent versioned URLs, dense filterable table, provenance on every cell.
- **Data Lab:** CSV/Excel exports with data dictionary, source and vintage identifiers; methodology and release pages.
- **Operations:** automated ingestion, immutable source archive, validation gates, manual publish approval.

### Phase 2 — monetize and retain

- Accounts, **Pro subscription**, watchlists, release-day email/alerts.
- **Public API** with keys, rate limits, and paid tiers; Parquet/JSON, Python/R snippets, citations/BibTeX.
- Household basket calculator (labelled platform-calculated, never official) and regional/retail-price workspace — engagement and press features that feed the funnel.
- Japanese-language UI; embeds and image exports.

### Phase 3 — deepen the paid product and prove the platform

- **Inflation pipeline:** import prices, CGPI, SPPI, wages, expectations — upstream pass-through views for investors.
- **Documented nowcasts** (Tokyo-to-national) with published model cards and historical error before live use.
- Licensed consensus/surprise and market-reaction views, only after data-rights review.
- **Second dataset onboarded on the same core** (e.g. Japan wages or PPI) as the platform-generality proof, gating any multi-country ambition.

Out of scope until explicitly approved: a proprietary "official-sounding" household CPI, causal claims from correlation, and redistribution of licensed market data.

## 5. Platform generality rule

Nothing Japan- or CPI-specific may live in core tables, core API shapes, or core pipeline code. Country, dataset, base-vintage semantics, classifications, and mappings are versioned data plus per-dataset adapter config. The test: onboarding a second dataset (Phase 3) must require a new adapter and new classification records — not a migration of core schema. Details in the implementation doc.

## 6. Risks and open decisions

| Risk / decision | Treatment | Severity |
| --- | --- | --- |
| 2020→2025 mapping quality; false continuity destroys credibility | Curated mapping table with confidence levels; no derived continuity across concept/method changes | High |
| Source access, licensing, and redistribution rights | Source registry with terms review before ingestion; archive raw evidence; don't launch unlicensed data | High |
| Contribution methodology where official values are missing | Prefer official; document estimate formula and reconciliation tolerance; label estimates | High |
| Premature publication on release day | Quarantine + human approval; immutable vintages; rollback to last accepted release | High |
| Paywall placement hurting the acquisition funnel | Keep overview and citations free; paywall depth and speed, not headline facts | Medium |
| Product boundary within the existing platform repo | Dedicated app/module, independent schema namespace; decide deployment/domain before M0 | Medium |
| Market-data licensing for consensus/surprise | Phase 3 only; explicit entitlement before storage or display | Medium |

Open decisions to close in M0: deployment boundary (subdomain/app vs route); API ownership (NestJS vs dedicated FastAPI service); canonical source table and retrieval method per MVP metric; contribution formulas and tolerances; Pro/API price points and paywall line; Japanese-launch level and translation ownership.

## 7. Definition of ready to build

Engineering starts when M0 has recorded: deployment boundary and named owners; source table and redistribution terms for each MVP metric; e-Stat credential process; initial 2020/2025 mapping rules; contribution formulas/tolerances; the paywall line for MVP; and a reviewed wireframe showing trust labels and base choices. First slice: one fully traceable release, ~10 representative items (including a renamed or discontinued one), a minimal overview — expand coverage only after the provenance and validation contract holds end-to-end.
