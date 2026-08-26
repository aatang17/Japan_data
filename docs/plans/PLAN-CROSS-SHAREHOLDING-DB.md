# PLAN — Cross-Shareholding Database (政策保有株式)

> **Status:** PROPOSAL v1 — awaiting approval
>
> **One-liner:** Every policy shareholding disclosed by every listed Japanese company —
> who holds what, at what value, for what stated reason, and how fast it is unwinding —
> extracted from the primary filings, in English, integrated into the Observatory site.
>
> **Position:** This is **product #2**. It shares the site, the brand, the trust contract
> and the customers with the Japan Macro Observatory, but **not** the core schema — it is
> documents-and-events data, not time series, and lives in its own schema namespace and
> its own module. The macro golden rule ("datasets are adapters") explicitly does not
> apply here; forcing it would deform both products.
>
> **Companion docs:** [PLAN-JAPAN-MACRO-OBSERVATORY.md](PLAN-JAPAN-MACRO-OBSERVATORY.md)
> (product #1) · [../SYLLABUS-JAPAN-EQUITIES.md](../SYLLABUS-JAPAN-EQUITIES.md) (Module 2
> is the domain background for this plan)

---

## 1. What the data is

Since the 2019 reporting year, every annual report (有価証券報告書) must disclose the
company's policy shareholdings (政策保有株式) in the governance section (株式の保有状況):

- each significant holding **named individually** (issuer, number of shares, balance-sheet
  value, typically the top 60 plus a threshold rule),
- year-on-year change in the holding,
- and — unique to Japan — **the stated reason for holding each one**, as free text.

Nobody publishes this aggregated, structured, and in English at investor-grade quality.
Toyo Keizai sells a Japanese-language commercial database of it (directory-shaped,
corporate/IR-oriented). The gap is the **investor-facing view**: ranked unwind screens,
holder/held-by networks, pace-versus-promise tracking, overlap with activist positions.

## 2. Verified source facts (2026-08-06)

- **EDINET API v2** ([spec, FSA, June 2026](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf)):
  free; requires registering for an **API key** (user action — see §9 blockers). Serves
  the document list by date and the documents themselves (XBRL/HTML/PDF).
- **Retention is limited: the date-list API reaches back ~5 years, and files are deleted
  10 years after filing.** Consequence: a capture archive compounds exactly like the macro
  vintages — a competitor starting later cannot rebuild what EDINET has deleted. Same moat
  logic, and the reason to start capture early even before the product ships.
- **Entity resolution is mostly a solved problem**: EDINET publishes an official code list
  (`EdinetcodeDlInfo.csv`, fixed URL in the API spec) mapping **EDINET code ↔ securities
  code (5-digit, first 4 are the familiar ticker) ↔ corporate number (法人番号) ↔ filer
  name**. This removes the scariest unknown; what remains is matching the *named holdings*
  (free-text company names inside the tables) to the same code list.
- **Market-level cross-check:** the [JPX Shareownership Survey](https://www.jpx.co.jp/english/markets/statistics-equities/examination/)
  (annual, Excel, English) gives ownership by investor category — a reconciliation
  reference for whether our aggregates are sane, not a source.
- **M0 RESULT (2026-08-06): GO — verified against MUFG's live filing (S100YJQO).** The
  plan's worst-case assumption was wrong in our favour: the cross-shareholding table is
  **fully tagged XBRL, delivered as clean CSV** via the API's `type=5` package
  (`XBRL_TO_CSV/jpcrp030000-asr-…csv`, UTF-16 TSV). Per named holding, tagged fields
  include: issuer name (`NameOfSecuritiesDetailsOfSpecifiedInvestmentEquitySecurities…`),
  share count, balance-sheet value, the **purpose free text**, and — unexpected upside —
  **`WhetherIssuerOfAforementionedSharesHolds…` (有/無), the reciprocity flag**, meaning
  the "cross" in cross-shareholding is disclosed per row, not inferred. Aggregate fields
  (issue counts, totals, increases/decreases with acquisition/sale amounts) are tagged
  too. MUFG FY2025: 773 listed policy issues worth ¥3.77tn; 66 named current-year rows
  summing to ¥2.67tn (top: Toyota ¥496bn, U.S. Bancorp ¥369bn); sold down 282 issues for
  ¥531.6bn against **1** increase — the unwind in one row. No HTML parsing needed for the
  main table; extraction risk in §8 downgrades from High to Medium. One real M1 finding:
  element-name suffixes vary by filer structure (`…LargestHoldingCompany` vs
  `…ReportingCompanyOrLargestHoldingCompany`) — the parser must handle variants.

## 3. What the website shows (the product)

Four surfaces, in build order:

1. **Company page** (`/equity/holdings/{ticker}`): the company's policy holdings — names,
   values, share counts, YoY change, stated reasons (Japanese + English translation,
   clearly labelled as our translation) — and the reverse view: **who holds this company**.
   The reverse view is the differentiator; no filing shows it, because it only exists once
   every filer's table is in one database.
2. **Unwind tracker**: by company and by sector — holdings count and value over time,
   pace of decline, "announced intent vs actual pace" once ≥2 years of history per filer.
3. **Screens** (the sell-side product): largest remaining holders · fastest unwinds ·
   stalled unwinds (stated intent to reduce, no reduction) · holdings as % of holder's
   market cap · overlap with sub-book valuation.
4. **Exports and citable URLs**: same rules as macro — CSV with metadata header, PNG with
   source line, URL encodes full view state. Every chart is a Substack-ready asset.

**API:** `/api/v1/equity/holdings/...` — a new namespace, versioned from day one, because
API users are the paying customers.

## 4. Trust contract adaptation

Same philosophy, new wrinkles:

- Holding names, share counts, values, and reasons are **as filed** → `Official Statistic`
  (source: filing ID, EDINET link, filing date, archived artifact SHA-256).
- **Translations of the stated reasons are ours** → labelled as platform translation,
  original Japanese always available on click. Never present a translation as the filing.
- Aggregates (sector totals, unwind pace, % of market cap) → derived; carry their formula.
- **Extraction confidence is disclosed.** Parsing thousands of differently-formatted HTML
  tables will not be 100% accurate. Each filer-year carries an extraction status
  (`clean` / `partial` / `failed`), the failure list is public, and coverage is stated on
  every aggregate ("aggregated from N of M Prime-market filers"). Silent gaps would
  destroy exactly the credibility the macro product is built on.

## 5. Data model (new schema namespace, own DuckDB tables)

Five tables, deliberately simple:

- **`eq_entities`** — one row per legal entity: EDINET code, securities code, corporate
  number, names (JA/EN), listing status. Seeded from `EdinetcodeDlInfo.csv`; refreshed on
  ingest.
- **`eq_filings`** — one row per captured document: filing ID, filer entity, doc type,
  fiscal year, filing date, raw artifact path + SHA-256, extraction status. **Immutable —
  this is the vintage layer.** An amended filing (訂正報告書) is a new row linked to the
  original, never an overwrite.
- **`eq_holdings`** — one row per (filing, named holding): holder entity → held entity
  (nullable until name-matched, raw name always kept), share count, balance-sheet value,
  purpose text (JA), purpose translation (EN), match confidence.
- **`eq_name_map`** — curated free-text-name → entity matches with confidence, so manual
  corrections persist across re-ingests instead of being re-derived.
- **`eq_extraction_log`** — per filing: parser version, status, error detail. Re-running a
  newer parser version creates new extraction rows; old extractions are kept (same
  immutability discipline as macro vintages).

Ingest follows the macro guardrails verbatim: idempotent, fail-safe, archive-before-parse,
one writer, never fatal to boot.

## 6. Milestones

> **Status 2026-08-06:** M0 ✅ (GO recorded, §2) · M1 ✅ (`equity/m1/` — 817 named
> holdings from 7 financials, 100% domestic entity match, all reconciliation gates pass)
> · M2 ✅ built and live-tested (`equity/capture.py` + launchd plist; corporate-only
> filter — fund filings excluded by `fundCode`; buyback reports (type 220) captured as
> a bonus). The 14-day unattended acceptance run starts when the launchd agent is
> installed. M3 next.

| M | Deliverable | Acceptance criteria | Effort (est.) |
| --- | --- | --- | --- |
| **M0 — Feasibility probe** | API key working; pull the latest 有価証券報告書 for **7 financials** (3 megabanks, 4 insurers); locate the 株式の保有状況 block; hand-inspect structure | We can state, from evidence: the exact XBRL/HTML location, tagged-vs-text ratio, and per-filing parse effort. **Go/no-go decision recorded** | 1–2 days |
| **M1 — Prototype extractor** | Parse those 7 filers into `eq_holdings`; entity match against the code list; manual QA of every row | 100% of the 7 filers' named holdings extracted and hand-verified; ≥90% of held-company names auto-matched | ~1 week |
| **M2 — Daily capture (the moat)** | Scheduled job: pull the daily document list, archive every 有価証券報告書 + 訂正 (and 大量保有報告書 while we're there — cheap, feeds the future activist overlap) raw into `data/raw/edinet/` with SHA-256. **Capture ≠ parse**: archive everything, extract at leisure | Runs unattended for 14 consecutive days; misses nothing filed; survives EDINET downtime without data loss | ~1 week, then passive |
| **M3 — Sector slice on the site** | Financials sector (~150 filers, largest holders of everything): company pages + reverse view + one unwind chart, live on the site behind the trust rules of §4 | Round-trip proven: filing → archive → extraction → API → rendered page → CSV/PNG export. First Substack post published from it | 2–3 weeks |
| **M4 — Full coverage** | All ~3,800 filers, latest year + available history (≤5 years back via the list API); extraction status public | ≥90% of Prime filers `clean`; failure list published; JPX survey reconciliation sane | 3–4 weeks |
| **M5 — Screens + API keys** | The §3 screens; `/api/v1/equity/` with keys and rate limits; pricing decision | First external user (even free-tier sell-side) pulling via API | 2 weeks |

Effort estimates assume solo pace alongside the macro product; the real constraint is your
time. **M2 is deliberately early and deliberately separated from parsing** — the archive is
the compounding asset and costs almost nothing to run; the extractor can improve for months
afterward against already-captured files.

## 7. Validation gates

1. **Reconciliation:** sum of a filer's disclosed values must be within tolerance of the
   filer's own stated total (the filings state totals); deviations → `partial`, never
   silently published.
2. **Entity match audit:** any auto-match below confidence threshold is queued for manual
   review, not published as matched.
3. **Amendment handling:** a 訂正報告書 supersedes on the surface, but both vintages remain
   queryable — same rule as macro releases.
4. **Coverage honesty:** every aggregate states its denominator. "Financials sector,
   142 of 148 filers extracted clean" — always.

## 8. Risks

| Risk | Treatment | Severity |
| --- | --- | --- |
| Extraction variance across thousands of hand-authored HTML tables | M0 probe before commitment; per-filing status; sector-by-sector rollout; publish failures | **High** |
| Toyo Keizai (incumbent) reacts, or a fund's data team self-builds | Ship the investor-facing views they don't have; English; API; activist overlap. Speed matters — this window is open because the TSE campaign made the data topical | **High** |
| Two products, one person: equities work stalls the macro roadmap | M2 (capture) is the only time-critical piece — it runs passively. Everything else can pause without losing the moat | **High** |
| Translation of purpose text misrepresents a filing | Label as platform translation; original always shown; never translate into stronger language than the Japanese | Medium |
| Historical depth capped at ~5 years by the list API | Accept at launch; the capture archive fixes it going forward; commercial back-history is a later buy-vs-build decision | Medium |
| EDINET key terms / rate limits stricter than expected | Confirmed free; probe actual limits in M0 before designing the daily job | Low |

## 9. Blockers and decisions

- **Blocker (user action): register for the EDINET API key.** Nothing in M0 moves without
  it. ~15 minutes on the EDINET site.
- **Decision: translation approach** for purpose text (machine translation with disclosure
  vs curated glossary-driven) — decide at M1 when we see the actual text variety.
- **Decision at M3: pricing surface** — free during the Substack-building phase vs paid
  screens from day one. Recommendation: free company pages, paid screens and API, decided
  properly at M5.

## 10. Definition of ready / first slice

Build starts when the API key exists and M0's go/no-go is recorded. **First slice = M1's
seven financials**, hand-verified, because financials are the largest policy holders and
the unwind story's centre of gravity — and because seven hand-checked filers are exactly
enough to write the first credible Substack post: *"Who's actually unwinding: what seven
financials' filings show."*
