# PLAN — Boards & Pay (役員の状況・役員の報酬等)

> **Status:** PROPOSAL v1 — awaiting approval. M0 (feasibility) and M1 (extraction
> prototype) are **done and passed**; see [`equity/board_m1/README.md`](../../equity/board_m1/README.md).
>
> **One-liner:** Every director of every listed Japanese company — name, age, role, board
> seat, shares owned — and what the company pays its officers, including every individual
> earning ¥100m or more, extracted from the same annual reports we already archive.
>
> **Position:** a **third surface — "Governance"** — alongside Holdings (cross-shareholdings)
> on the equity side of the platform. It is the same product family, the same customers, the
> same trust contract, and the **same source file**: `jpcrp030000-asr` in the EDINET `type=5`
> package we already download and parse for policy shareholdings. Marginal capture cost is
> zero.
>
> **Companion docs:** [PLAN-CROSS-SHAREHOLDING-DB.md](PLAN-CROSS-SHAREHOLDING-DB.md) ·
> [../SYLLABUS-JAPAN-EQUITIES.md](../SYLLABUS-JAPAN-EQUITIES.md) (Module 6, governance plumbing)

---

## 1. Why this, and why now

Cross-shareholdings answer *who owns whom*. Boards and pay answer *who runs it and what
they are paid for it* — the other half of every governance conversation in Japan, and the
half that moves on a calendar we can publish against: every June, ~2,300 annual reports
land inside three weeks.

Nobody serves this in English at investor grade. The individual ¥100m disclosure is
reported one company at a time by the Japanese press each summer and never assembled;
board age, tenure and gender data sit in Japanese-only commercial governance databases.
The pairing with the holdings dataset is the differentiator neither has alone: *does a
board with entrenched cross-shareholders pay differently, age faster, and unwind slower?*

## 2. Verified source facts (M0, 2026-08-23 — measured, not assumed)

Scanned 800 archived annual reports for coverage, then extracted all 2,766:

| Fact | Tagged? | Coverage |
| --- | --- | --- |
| Director name, title, date of birth, shares held | ✅ per person | 96.9% of all filers; **99.7% of listed filers** |
| Officer pay by category (total + headcount) | ✅ | 96.4% / 94.9% |
| Pay components (fixed, base, performance, bonus, non-monetary, retirement, share awards) | ✅ open family | 54–65% each — filers break out different ones |
| **Individual pay ≥¥100m (連結報酬等)** | ✅ per person | 455 of 2,721 filings; 1,122 people |
| Male/female officer counts and ratio | ✅ | 96.8% |
| Employees, average age, tenure, **average annual salary** | ✅ | 96.4% |
| Human capital: gender wage gap, female managers, male childcare leave | ✅ | ~70%, filer and consolidated-subsidiary variants |

Two structural gifts: the per-person context member carries a **romanised name**
(`…_ShinyaAkitoMember`, 100% of 8,410 contexts), so English names need no translation; and
the ¥100m pay fact sits on **that same member context**, so named pay joins to the board
seat with zero name matching. Full findings and traps: `equity/board_m1/README.md`.

## 3. What the site shows

A new **Governance** section, three surfaces, in build order:

1. **Company page** (`/equity/governance/{ticker}`) — the board as a table (name JA/EN,
   role, age, tenure where derivable, shares held, representative flag), the pay table as
   filed, named individuals ≥¥100m, and the company's human-capital metrics. Cross-linked
   both ways with the company's Holdings page.
2. **Screens** — oldest and youngest boards · boards with no women · highest paid
   individuals in Japan · pay per director vs company size · biggest movers in pay ·
   directors who own nothing of the company they run.
3. **Pairings with Holdings** (the thing only this platform can do) — board age vs unwind
   pace · pay growth vs cross-shareholding stock · zero-women boards among the biggest
   remaining cross-holders.

**API:** `/api/v1/equity/governance/...`, versioned from day one, same namespace rules as
`/api/v1/equity/holdings/...`.

## 4. Trust contract adaptation

- Director names, titles, dates of birth, share counts, pay figures → **as filed**,
  `Official Statistic`, with filing ID, EDINET link, filing date and artifact SHA-256.
- English director names are **transliterations taken from the filer's own XBRL context**,
  not our translation — label them as such; the Japanese name is always shown.
- Age, average pay per head, board averages, gender ratios we recompute → **derived**, carry
  the formula.
- **Three disclosures that must be on the page, not buried:**
  1. The tagged board is 取締役会 members; the filer's 役員 gender tally may include 執行役
     who are not individually disclosed. Where they differ, say so (`officers_untagged`).
  2. Pay components need not sum to the filed total — 非金銭報酬等 is additive for some
     filers and an "of which" memo for others, and components are rounded to ¥mn. The
     **filed total is the published number**; components carry a reconciliation flag.
  3. 連結報酬等 is *consolidated* — it includes pay from subsidiaries, which is why an Arm
     executive appears in SoftBank's filing. Never present it as parent-company pay.
- Extraction status per filing (`clean` / `partial` / `no_tagged_board`) is public, and
  every aggregate states its coverage.

## 5. Data model (same equity namespace, reusing the vintage layer)

Reuses `eq_entities` and `eq_filings` unchanged — the filing row and its SHA-256 already
exist because the holdings extractor archived it. Four new tables:

- **`eq_board`** — one row per (filing, person): member key, name JA, name EN, title JA,
  role, representative flag, date of birth, age at period end, shares held.
- **`eq_pay_category`** — one row per (filing, officer category): total, headcount,
  per-head, each component, unknown-component sum, `components_reconcile`.
- **`eq_pay_named`** — one row per (filing, named individual): member key, name EN,
  consolidated pay, voluntary-below-threshold flag, on-board-at-filing flag.
- **`eq_company_year`** — one row per filing: board size, officer tally, gender split,
  employees, average age/tenure/salary, human-capital metrics, extraction status.

No core-schema change; no change to the holdings tables.

## 6. Milestones

| | | Status |
| --- | --- | --- |
| M0 | Verify what is tagged, at what coverage, across many filers | **done** — §2 |
| M1 | Extraction prototype with gates, whole local archive | **done** — 99.4% clean |
| M2 | Full five-year extraction from the S3 archive; load the four tables | **done** — §8 |
| M3 | API endpoints + MCP tools | **done** — §9 |
| M4 | Governance pages and screens (`ui-ux-design` gate applies) | **done** — §10 |
| M5 | Pairings with Holdings; first Substack post off the data | next |

## 8. M2 result (2026-08-23)

`equity/board_extract.py --all --source s3` over the cloud archive: **21,099 filings,
fiscal periods ending 2020-12-31 → 2026-05-31**, loaded into the served equity DuckDB as
`eq_board` (195,097 seats), `eq_pay_category` (61,968 rows), `eq_pay_named` (5,605 people)
and `eq_company_year` (21,099). **99.4% clean among listed filers**; 85 filings `partial`,
23 on forms that carry no governance section. Provenance per filing: SHA-256 of the bytes
parsed, parser version `board-m2-2`.

The dataset immediately produces a **matched five-year panel of 2,360 listed companies**
(clean in all of FY2022–FY2026) — the thing no one publishes:

| | FY2022 | FY2026 |
| --- | --- | --- |
| Average board size | 10.60 | 10.20 |
| Average director age | 60.78 | 61.84 |
| Directors aged 70+ | 15.7% | 17.9% |
| Female officer ratio | 12.1% | 17.0% |
| Median pay per inside director | ¥24.19m | ¥29.00m |

Boards are getting smaller, older and more female at once, and inside-director pay is up
**19.9% in four years on a like-for-like panel** — against a CPI the macro product already
serves, which is the first natural cross-product post.

Two operational notes for M3: the shared `compact()` in `extract.py` now copies every table
from its own stored DDL (a hardcoded list would have dropped these four on the next
holdings run), and `board_extract.py` deliberately does not write `eq_filings` — that row
belongs to the holdings extractor, and `eq_company_year` carries this dataset's own status
and hash.

## 7. Risks

- **Person identity across companies and years is not solved.** The romaji member key is
  filer-authored: fine within a filing, unsafe for asserting interlocks. Any
  "directors in common" feature needs a curated person map (`eq_person_map`), the same
  pattern as `eq_name_map` — do not ship interlocks on the weak key.
- **Committee-system companies under-disclose executives.** 執行役 are only in a TextBlock.
  We publish the board, and say so; parsing that table is optional later work.
- **Reputational sensitivity.** Named individual pay is public disclosure, but this is
  personal data about identifiable people. Publish exactly what was filed, no inference,
  no scraping of anything not in the filing, and no derived "worth it?" scoring.
- **Nine filings breach a gate today** because the filer's own numbers disagree with each
  other. Those must render as `partial` with the discrepancy shown, never be quietly fixed.

## 9. M3 result (2026-08-24)

`app/governance_api.py` serves six endpoints under `/api/v1/equity/governance/`
(summary · company · history · screen · screen/metrics · named), reusing the holdings
API's reader, English-name resolution and industry lookup — one connection, one set of
company names. Five MCP tools are registered alongside the holdings ones and advertised
only when the tables exist: `get_governance_summary`, `get_company_board`,
`get_board_history`, `get_governance_screen`, `get_top_paid_officers`. Every pay tool's
description repeats the consolidated-basis and components warnings, because an assistant
that misses them states something false with confidence.

Three things the API layer had to solve that the extraction did not:

- **Filer-defined pay categories.** Roughly one row in twelve uses a category tag no fixed
  map covers (Toyota's are all bespoke), so an unmapped tag is de-camel-cased from the
  filer's own label and marked `derived_from_filer_tag` — never passed off as a published
  label. The comparable inside-director metric is only computed from the two standard tags
  (92.4% of pay tables) and is null elsewhere, with `pay_per_officer_yen` as the
  always-defined alternative.
- **"Of which" sub-rows.** 106 filings tag うち社外役員 rows that are a subset of the row
  above; summing the table without excluding them double-counts those officers.
- **Filer scale errors.** GALA's filing tags ¥71.4bn for five directors. Nothing is
  corrected, but a legally grounded cross-check flags it: anyone paid ¥100m or more must
  be named individually, so a filing implying such a person while naming nobody
  contradicts itself. Six filings market-wide carry `pay_consistency_flag`.

Fixed in passing: `get_holdings_summary` and `get_unwind_ranking` called their endpoints
with no arguments, so FastAPI's `Query` defaults leaked through as objects and both tools
failed at the first `.strip()` — a pre-existing break in the MCP surface, not visible from
the HTTP API.

## 10. M4 result (2026-08-24)

`web/governance.html` + `web/assets/governance.js`, listed under **Equities → Boards & Pay**
and on the landing page. Two views on one URL, same shape as the holdings page: a market
view (coverage strip · matched-panel trend chart with a measure picker · ten screens with a
listed/all toggle) and a company view (`?c=7203`: headline facts · the board · the pay table ·
the individuals disclosed · a five-year record). Every table exports CSV with a metadata
header; the chart exports a light-theme PNG carrying its source line; the URL encodes the
measure, the screen and the scope, so any view is citable.

Two API endpoints were added for it: `/governance/companies` (a search scoped to this
dataset — a company can have a board here and no policy holdings next door) and
`/governance/trend`, the matched panel of **3,459 listed companies clean in every year of
FY2022–FY2025**, one filing per company per year. That panel is the chart, and it is the
finding: average director age 59.66 → 60.50, directors aged 70+ 15.4% → 16.8%, female
officers 12.7% → 16.1%, median pay per officer ¥14.31m → ¥15.25m against a median employee
salary of ¥6.03m → ¥6.51m.

What the look-at-it gate caught, none of which was visible in the API responses:

- **The headline "filed total" double-counted.** `eq_company_year.pay_category_total_yen`
  sums every category row a filing tags, including うち社外役員 "of which" sub-rows, which are
  a subset of the row above. Toyota read ¥4,638m against a true ¥4,433m. Fixed in the
  extractor for future runs and computed from the rows at query time now, so the served
  figure is right today and the two definitions agree after the next extraction.
- **Screens repeated their own ranked column.** Every screen now shows the same columns and
  only changes what it sorts by, with the ranked column marked — a company reads the same
  way whichever screen surfaced it.
- **`¥— m`.** A missing value wrapped in a currency symbol and a unit reads as a number that
  failed to load. Missing is now a bare em dash (Sony files no category totals at all).
- **Raw field names in prose.** The API's notes name their own fields, which is right for a
  machine consumer and wrong on a page; the page carries the same facts in a reader's words,
  and the CSV headers keep the precise field-level wording.
- **A squeezed board table** broke Japanese titles into one character per line at 390px; the
  table now scrolls inside its own container instead of compressing.

Shared-file changes, both additive: `charts.js` gained a category x-axis (annual data on a
time axis would be labelled by month and imply readings we do not have) and a little more
top padding when a single-series chart's y-axis name is the only place its unit appears;
`tokens.css` gained `--obs-warn` for a filing whose own figures contradict each other —
deliberately not a trust colour, since it marks a problem in the source document, not the
standing of a number we publish.
