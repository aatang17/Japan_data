# Plan — Global signal datasets and a backtest for component-cycle inflection points

> Status: **proposal, September 2026 — nothing built.** Follows the September 2026
> investigation into whether the platform could have seen the 2026 MLCC tightening.
> Companion to `PLAN-JAPAN-MACRO-OBSERVATORY.md`; see the scope note below on how this
> squares with "Japan, deep — not Asia, wide".

---

## 1. What we are trying to do

Find, ahead of consensus, the turning points in electronic-component cycles — MLCCs
and other passives, memory, and the semiconductor complex around them — and prove,
with a backtest, which datasets actually carry that information and how early.

**What the first backtest established** (Japan export unit values, 254 lines, 2001–2026):

- A magnitude rule (z-score) has **no edge** over the base rate and misses the 2026
  capacitor move — the line's own history is too volatile for "big" to mean anything.
- A **persistence** rule (price yoy improving 8 months running, volumes growing),
  parameter fixed on 2001–2015 and tested untouched on 2016–2026, fires 55 times in
  eleven years; **73% of fires are still elevated six months later against a 59% base
  rate**, and it fires on capacitors in **September 2017** — the last MLCC shortage.
- Effective sample is ~6 supply cycles, not 55 independent trials. Suggestive, not proven.

That is one country and one mechanism. This plan widens both.

### Scope note

`CLAUDE.md` says Japan, deep — not Asia, wide. That rule is about what we **sell**.
This plan does not propose selling Korean or Taiwanese data; it proposes ingesting
foreign series as **inputs** to a Japan-centred signal — the customers of Murata and
Taiyo Yuden are in Taiwan, the price of memory is set in Korea, and the demand is
booked in US M3 orders. The product surface stays Japan; the signal reads the world.
If a foreign series ever becomes a product in its own right, that is a separate decision.

---

## 2. Dataset inventory — verified 7 September 2026

Every row below was checked this session unless marked otherwise. "PIT" = whether true
point-in-time history exists (what the data said *at the time*, before revision) — the
single most important property for an honest backtest.

### Tier 1 — build these first (free, monthly or faster, directly on the mechanism)

| # | Dataset | What it measures | Freq / lag | History | PIT? | Access | Verified |
|---|---|---|---|---|---|---|---|
| 1 | **MOF Trade Statistics — 概況品別国別表** (Japan exports & imports by commodity × partner) | Value **and quantity** → unit value (price) for 404 export / 427 import lines | Monthly, ~25 days | 1988– | Partial: MOF publishes 4 revision stages; e-Stat serves only the current one for closed years. Our own vintages accrue from ingest. | e-Stat API (have key). Already ingested: 6 of 404 export lines. | ✓ |
| 2 | **MOF 航空貨物品別国別表** (Japan **air-freight** exports by commodity × partner) | The share of a commodity shipped by air — parts get flown when they are scarce | Monthly | 1988– (tables 0003258355… 0004049331) | As #1 | e-Stat API, same parser as #1 | ✓ table IDs |
| 3 | **METI IIP — 業種別 在庫率** (inventory ratio by industry) | Electronic parts & devices inventory-to-shipment ratio, the classic Japanese cycle indicator | Monthly, ~30 days | 2018– (2020 base), 2013– (2015 base), 2008– (2010 base) — spliceable | No (revised; seasonal factors re-estimated) | e-Stat API; table 0004052184 carries 電子部品・デバイス工業 / 電子部品 / 電子デバイス | ✓ |
| 4 | **TWSE OpenAPI `t187ap05_L`** — monthly revenue of every Taiwan-listed company | **Yageo (2327), Walsin (2492)** = MLCC; Nanya, Winbond, Macronix = memory; TSMC, ASE. Companies must report by the 10th | Monthly, **~10 days** — the fastest hard company data in the world | API serves current month only; history via MOPS pages (URL pattern not yet cracked) or accumulate from now | **Yes** — self-reported, almost never revised | Free JSON, no key. Yageo July 2026: TWD 16.13bn, **+51.5% yoy** | ✓ current month |
| 5 | **Korea MOTIE monthly export release** | Exports by item incl. **semiconductors** (July 2026: $41.0bn, +178.8%), computers/SSDs, displays | Monthly, **1st business day** after month end | Press-release archive (English), PDF attached | **Yes** by construction if we archive each release | Scrape `english.motir.go.kr` press releases | ✓ |
| 6 | **Korea Customs — first-20-days exports** | Same items, 10 days earlier still | ~21st of the same month | Press releases | Yes if archived | Scrape; official page not yet located (existence confirmed via secondary coverage) | ◐ |
| 7 | **US Census M3 via FRED/ALFRED** — `A34SNO` new orders, plus shipments, inventories, unfilled orders for computers & electronic products | Demand-side orders and the inventory/unfilled-orders cycle | Monthly, ~35 days | 1992– | **Yes — ALFRED vintages** (the only fully honest PIT source in this list) | FRED API, free key | ✓ |
| 8 | **BLS PPI capacitors via FRED/ALFRED** — `WPU117811` (1968–Dec 2022, discontinued) spliced to `WPU117854` (Dec 2022–); industry series `PCU33441K33441K4` (1981–) | US producer prices for electronic-circuit capacitors — the closest thing to a public MLCC price index | Monthly, ~15 days | 1968– | **Yes — ALFRED** | FRED API | ✓ (splice needed) |
| 9 | **WSTS monthly semiconductor billings** (Blue Book historical, free Excel) | Global chip sales by region, monthly + 3mma | Monthly, ~35 days | 1976– | No | Free download, no login; SIA press releases mirror it | ✓ |
| 10 | **JEITA 電子部品グローバル出荷統計** | Japanese-affiliated component makers' **global** shipments by product incl. **積層セラミックコンデンサ** (MLCC) as its own line | Monthly | Excel on JEITA site; start year and release timing not yet checked | Unknown | Free Excel | ◐ classification confirmed |

### Tier 2 — useful, but slower, coarser or harder to reach

| # | Dataset | Notes | Verified |
|---|---|---|---|
| 11 | **Taiwan MOEA export orders** by product (electronics, ICT) | Orders lead shipments by design; monthly ~20th; page blocks automated fetch (403) — manual download or headless browser | ◐ |
| 12 | **Taiwan customs** (portal.sw.nat.gov.tw) exports by HS code | Web query, monthly, downloadable; no API | ◐ |
| 13 | **US Census international trade API** — HS-10 imports by origin, e.g. `853224` MLCCs from JP/CN/KR/TW | Monthly value & quantity; free key required | ✓ (key gate) |
| 14 | **UN Comtrade** public preview endpoint | Works without a key (Japan 853224 Jan-2026 returned); heavily rate-limited; lagged and revised | ✓ |
| 15 | **BLS import price index** — `COJPNZ334` Japan computers & electronics | Monthly from 2012 only | ✓ |
| 16 | **JMTBA machine tool orders** | Monthly, ~10 days; capex cycle, not components | ✓ |
| 17 | **METI 生産動態統計 — 固定コンデンサ** production/shipments/inventory | On e-Stat only through 2013 (table 0003040032, quantity & value). Current years may be on METI's own site — **not yet found**; if it exists with inventory it is the best Japanese MLCC series there is | ✗ needs work |
| 18 | **China GACC** exports/imports by HS | Web query only, scrape-hostile; the largest MLCC importer. Defer | ✗ |
| 19 | **KOSIS** (Statistics Korea) semiconductor production & inventory indices | API key requires Korean identity verification — **we cannot get one**; use MOTIE releases instead | ✗ blocked |
| 20 | **SEC EDGAR XBRL API** — Vishay, KEMET (pre-2020), Micron, hyperscaler capex | Quarterly; standard, not re-verified this session | — |
| 21 | **EDINET archive we already hold** — ~21,000 annual reports FY2021–FY2026 in the S3 bucket | Re-running `fin_extract.py` yields five cross-sections of capex/inventory intensity with no new downloads | ✓ internal |

### Outcome data (needed to score anything)

| Dataset | Notes | Verified |
|---|---|---|
| **Equity prices** — Murata 6981, Taiyo Yuden 6976, TDK 6762, Kyocera 6971, Yageo 2327, Walsin 2492, Samsung Electro-Mechanics 009150, Micron, SK Hynix, Kioxia 285A, TOPIX | Yahoo Finance chart endpoint returns daily JPY prices for `6981.T` (23 sessions, last close ¥7,191). **Unofficial; fine for research, not for a product.** Stooq is behind a JavaScript challenge. A licensed feed is a separate decision. | ✓ research-grade |
| **Physical outcomes** — Japan capacitor export unit value (#1), US PPI capacitors (#8), JEITA MLCC shipments (#10) | Already in Tier 1 | ✓ |

---

## 3. The backtest

### 3.1 Hypothesis

> A small set of monthly, public series can flag the start of a component-cycle upturn
> 2–6 months before it is priced, and agreement between independent series is more
> informative than any one of them.

### 3.2 Targets — what "right" means

Two families, scored separately. Physical first, because it is cleaner.

**Physical:** for a fire at month *t*, is the target still elevated at *t+6*?
- MLCC price proxy: Japan capacitor export unit value (3-month aggregate), US PPI capacitors.
- Memory: Korea semiconductor exports, US M3 computers & electronics shipments.

**Financial (event study):** cumulative excess return of a basket over 3, 6 and 12 months
from the first tradeable day after the signal is *published* (not the data month).
- MLCC basket: 6981, 6976, 6762, 2327, 2492, 009150 — equal weight, vs TOPIX.
- Memory basket: Micron, Samsung, SK Hynix, 285A — vs a world semis index.
- Base rate: same statistic on every non-fire month. A signal earns its place only by
  beating that, and the effective sample will be a handful of cycles — say so in every table.

### 3.3 Signals — each pre-registered before it is run

| Signal | Series | Rule (to be frozen before running) | Point-in-time honesty |
|---|---|---|---|
| S1 Japan export price persistence | #1 | Already validated: r3 improving 8 months, ≥ +8%, volume > 0 | revised data; MOF revisions small |
| S2 Air-freight share | #2 | 3m air share of a commodity's export value vs its own 5y range | revised data |
| S3 Taiwan MLCC revenue acceleration | #4 | Yageo + Walsin combined revenue yoy, 3m, improving *k* months | **true PIT** |
| S4 Korea semis export momentum | #5, #6 | Semis export yoy improving *k* months; 20-day print confirms | **true PIT** (archived releases) |
| S5 US orders-inventory cycle | #7 | M3 new orders yoy minus inventories yoy, turning up from below zero | **true PIT via ALFRED** |
| S6 US PPI capacitors momentum | #8 | 3m price change turning positive after ≥ 12 months negative | **true PIT via ALFRED** |
| S7 Japan inventory ratio | #3 | Electronic-parts 在庫率 falling *k* months from above its 3y mean | revised |
| S8 Global chip billings | #9 | 3mma yoy improving *k* months | revised |
| S9 JEITA MLCC shipments | #10 | Shipments yoy improving *k* months | unknown |
| S10 Filings — capex intensity | #21 | Capex/revenue Δpp in the top decile, revenue growing | annual; corroboration only |

Then the combination: **confirmation count** = number of S1–S9 firing within a
3-month window. Test whether count ≥ 2 and ≥ 3 improve precision over the best single
signal. This is the actual product hypothesis — that agreement is the edge.

### 3.4 Method — the same discipline as round one

1. **Pre-register** every rule, threshold and success criterion in a file before any
   result is looked at. Post-hoc changes go in a dated appendix with the reason.
2. **Base rate first.** Every score is reported next to the unconditional rate.
3. **Split by time**: parameters chosen on 2005–2015 only; 2016–2026 untouched.
4. **Episode recall**, named in advance from industry knowledge, not from the data:
   2010 post-crisis restock · 2017–18 MLCC/passives shortage · 2017–18 DRAM super-cycle ·
   2021–22 semiconductor shortage · 2025–26 AI buildout. Report lead time from the
   **publication date** of the firing data to the target's peak.
5. **Alert load** — fires per month across the universe. Above ~5 nobody reads it.
6. **Publication lag modelled explicitly** per source (Korea 1 day, Taiwan 10 days,
   Japan trade 25, US M3 35).
7. **PIT honesty flag** on every result: true-PIT sources vs revised-data sources,
   never blended in one number.
8. **Costs**: for the equity event study, assume 30bp round trip; report gross and net.

### 3.5 Phases and effort

| Phase | Work | Effort |
|---|---|---|
| **A. Acquire** | Adapters/scrapers: FRED+ALFRED (S5, S6), TWSE OpenAPI + MOPS history (S3), MOTIE release archive (S4), WSTS Excel (S8), JEITA Excel (S9), METI IIP (S7), air-freight tables (S2). Yahoo daily prices for the two baskets. Back-extract FY2021–25 financials from S3 (S10). | 5–7 days |
| **B. Pre-register** | Rules, thresholds, criteria, episode list — written and frozen | 1 day |
| **C. Run** | Single-signal backtests, then the confirmation-count test; physical targets first, then event study | 3–4 days |
| **D. Report** | One page per signal with base rate, split results, recall table, alert load, PIT flag; one page on combination | 1–2 days |

Roughly **two to three weeks** end to end, all read-only against the live product.
Nothing here touches `data/` on the volume or the serving process.

### 3.6 What would make us stop

- No single signal beats its base rate by more than one standard error on the test
  period → the mechanism is weaker than the MLCC case suggested; keep the coverage
  widening (independently justified), drop the detector.
- Confirmation count does not improve precision over the best single signal → ship
  the single best signal as an attention tool and nothing more.

---

## 4. Risks and limitations

- **Point-in-time is only real for US series and self-reported company data.** Every
  Japanese and Korean official series is served as revised. Lead times measured on
  revised data are optimistic by an unknown amount; we will quote them as such.
- **Survivorship and look-ahead in universe choice.** The basket and the commodity
  universe are chosen today. State it; do not pretend otherwise.
- **Few cycles.** Six episodes in 25 years. No statistic from this will be conclusive;
  the deliverable is a ranked shortlist of signals worth running forward, not proof.
- **Scraping fragility.** MOTIE, MOPS history and MOEA are HTML with no contract. Archive
  every page with its SHA-256 on capture, exactly as we do for EDINET filings, so the
  PIT record survives site redesigns.
- **e-Stat truncation.** The API dropped a connection mid-response during this
  investigation; `estat_api.call()` has no retry. Fix before any widened ingest.
- **Equity prices are research-grade only.** Anything shown to a customer needs a
  licensed feed; that is a commercial decision outside this plan.
- **Scope drift.** Foreign series are inputs. The moment one becomes a page, revisit the
  Japan-deep rule explicitly rather than by accretion.

---

## 5. Decisions needed before Phase A

1. **Go/no-go on the two-to-three-week research spend.** This produces knowledge, not a
   feature.
2. **Which target matters more** — physical prices (cleaner, defensible in the
   Methodology page) or equity returns (what a PM actually wants)? Both are planned;
   the order and the emphasis are the call.
3. **Baskets.** Confirm the MLCC and memory constituents above, or replace.
4. **Do we archive Korean and Taiwanese releases from now on regardless?** Cheap, and
   every month we don't is a month of point-in-time history nobody can recover later —
   the same logic as our vintage moat.
5. **Prices.** Accept Yahoo for research, or hold the event study until a licensed feed
   is decided.
