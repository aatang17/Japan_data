# PLAN — Japan Inbound: Arrivals, Outbound and the Travel Balance

> **Status:** PROPOSAL v1 — awaiting approval. No code written, no schema touched.
>
> **Scope decision:** Add **JNTO visitor arrivals** (dataset #5) as a normal adapter, then
> the outbound and yen-value layers behind it. This is Japan depth, not Asia breadth — it
> stays inside the standing scope decision.
>
> **Product decision:** Justified on the **join**, not on the archive. The headline arrivals
> number is commoditised; what is not available anywhere is arrivals sitting in the same
> database as our CPI item detail, and later the travel balance and spend per head.
>
> **One-liner:** The only place where Japanese inbound arrivals, hotel prices and the travel
> surplus are one queryable dataset in English — so a fund with no Tokyo office can tell the
> difference between "Japan inbound is rolling over" and "China is rolling over."
>
> **Companion docs:** [PLAN-PLATFORM-VISION.md](PLAN-PLATFORM-VISION.md) (umbrella) ·
> [PLAN-JAPAN-MACRO-OBSERVATORY.md](PLAN-JAPAN-MACRO-OBSERVATORY.md) (macro product, the
> waves this slots beside) · [../../CLAUDE.md](../../CLAUDE.md) (golden rule, trust contract)

---

## 1. Why an investor cares

Inbound is one of the two or three largest domestic demand stories in Japan, and it is the
one a foreign fund is least equipped to track. It reaches a portfolio through four channels
at once:

| Channel | What inbound does to it |
| --- | --- |
| **Domestic consumption equities** | Department stores, drugstores, cosmetics, duty-free retail, restaurants — revenue tied to arrivals *by market*, because spend per head differs several-fold between markets |
| **Hotels, REITs, airports, airlines, rail** | Volume and pricing power straight off arrivals; hotel RevPAR is the transmission mechanism |
| **Services inflation, and therefore the BOJ** | Hotel charges are a visible, volatile contributor to Japanese services CPI — the exact component BOJ normalisation is being judged on. We already hold the CPI item detail and the BOJ balance sheet |
| **The yen** | The travel surplus is a persistent, growing credit in the current account; outbound travel has *not* recovered, so the gap is structural, not seasonal |

Sizing: the Japan Tourism Agency put 2025 inbound travel spending at **¥9.46tn, +16.4%**
(¥229k per visitor) — figures published by JTA, not derived by us. Against arrivals of
42.68m, which our own read of the JNTO file reproduces exactly.

**The live mispricing this dataset surfaces.** Headline arrivals for January–May 2026 are
**−1.1%** year on year. Read as published, that says the inbound trade is over. It is not:
China is **−56.2%**, and **ex-China arrivals are +14.1%**, with Korea +20.6%, Taiwan +22.3%,
the US +8.2%, Europe +8.8%. A PM who trades the headline is wrong about every name whose
customers are not Chinese — and right about the cosmetics and department-store names whose
customers are. **That decomposition is the product.** It takes about ten lines of code and
nobody publishes it.

This is the same argument that makes the equity side defensible in
[PLAN-PLATFORM-VISION.md](PLAN-PLATFORM-VISION.md) §4: the value is not in the source file,
it is in the assembled database and the views that only exist once things are joined.

## 2. What already exists — and where we are actually different

Verified 2026-08-29 by hitting each one, not assumed.

| Who | What they give | Gap we exploit |
| --- | --- | --- |
| **JNTO itself** (`jnto.go.jp`) | The source Excel (2003–2026, by market, monthly) and monthly press PDFs. Free, direct download | Excel-and-PDF only, Japanese-first, no API, no derived series, URL rotates every month |
| **JNTO's own dashboard** (`statistics.jnto.go.jp`) | Good charts, prefecture and spending views | **Downloads sit behind a use-application form; there is no API.** A quant team cannot automate against it, and no chart is a citable permanent URL |
| **CEIC** | Arrivals by country back to 1992 | Paid, no vintages, no formula disclosure, no CPI join, and it is a terminal your reader cannot open from a Substack post |
| **Trading Economics** | Headline arrivals only, free chart, paid API | Headline only — the entire China-vs-rest story is invisible |
| **JTB tourism.jp** | Free summary tables, JP/EN | Static tables, no API, nothing derived |
| **nara-data and similar republishers** | The identical JNTO files, re-hosted, free | A mirror. No API, no derived series, no revision marking |
| **e-Stat / MOJ / JTA** | The upstream silos: immigration counts, spending survey, accommodation survey | Three separate Japanese-language silos that nobody joins to each other, let alone to CPI |

**So the honest competitive position:** the headline number is fully commoditised and we
should never pretend otherwise. Four things below the headline are not.

1. **The join.** Arrivals × hotel CPI today; × spend per head and × the travel balance in
   later waves. Every source above owns exactly one silo. We already own the CPI item
   detail (582 leaf items, including hotel charges and foreign package tours) — a
   competitor would have to build our CPI product first to copy this one chart.
2. **Derived series nobody publishes:** recovery versus the same month of 2019 by market,
   ex-China arrivals, market-mix shares, concentration, and a YoY contribution
   decomposition with the residual disclosed. All computed, all carrying their formula per
   the trust contract — never badged as official.
3. **English, citable, machine-readable.** Permanent URLs for the Substack, CSV with a
   metadata header, an API, and MCP so a customer's own agent can query it. That is the
   layer-5 pitch in the vision doc applied to macro.
4. **The revision ladder made explicit.** JNTO publishes an estimate, then a provisional
   figure, then a final one — and no republisher marks which is which. We will.

**Not defensible, and worth writing down:** the ingest itself. It is one spreadsheet; a
funded competitor could copy it in a day. What they cannot copy quickly is the CPI dataset
it joins to, the readership, and the discipline of showing the formula.

## 3. The vintage moat does not apply to this dataset

This is a deliberate exception to the standing framing in
[PLAN-JAPAN-MACRO-OBSERVATORY.md](PLAN-JAPAN-MACRO-OBSERVATORY.md) §2, and it is better to
say so here than to be caught by it in an institutional meeting.

**The test I ran.** Old JNTO file URLs stay live, so three vintages of the same workbook
were pulled — December 2024, June 2025, and the current August 2026 release — and diffed
cell by cell:

- the **2019 and 2023 sheets are bit-identical across all three vintages**;
- the **2024 sheet is identical** between the June 2025 and August 2026 vintages;
- the only changes anywhere are the estimate→final transition, and they are rounding:
  October 2024 went from 3,312,000 to 3,312,193 — **+0.006%**.

**Conclusion:** JNTO finalises and then never revises. Point-in-time history on this
dataset is worth close to nothing commercially, and we should not sell it. Two consequences:

- **We still store vintages** — the guardrail is unconditional and costs nothing — but the
  business case for this dataset rests on §2, not on the archive.
- **Because old URLs stay live, prior vintages could be backfilled.** Cheap, and a nice
  proof point for the pipeline. It buys little else. Low priority.

## 4. Source facts (verified 2026-08-29)

Confirmed by downloading and parsing the real files.

**The file.** `国籍/月別 訪日外客数` — one XLSX, one sheet per year, **2003 to 2026**,
~54 rows per recent year (markets plus regional totals), 12 monthly value columns plus
growth columns and a cumulative column. Roughly 14,000 observations. Reproduces the
published totals exactly (2025: 42,683,301).

**Five parsing facts the adapter must handle:**

1. **The download URL rotates every month** — it is stamped with the release date and time
   (`20241218_…` → `20250618_…` → `20260819_1615-5.xlsx`). `fetch()` must discover the link
   from the statistics page rather than hard-coding it, unlike the MOF and BOJ adapters.
2. **The layout shifts in 2020.** Sheets for 2019 and earlier start data one column to the
   left; from 2020 a sub-market label column is inserted. Parse from the header row, never
   from fixed column letters.
3. **Japanese labels carry embedded furigana.** Read naively, `韓国` comes back as
   `韓国カンコク`. The phonetic runs must be stripped when reading shared strings.
4. **The two newest months are deliberately incomplete.** At the estimate stage JNTO
   publishes only **31 of 54 series**, rounded to the nearest 100, and **the regional
   totals are absent**. Named markets will not sum to the headline for those months — the
   residual must be shown, per the reconciliation rule, never hidden.
5. **Estimate status is encoded as italic styling** in the workbook, so it can be read
   exactly rather than guessed.

**Parse it with the standard library.** ~40 lines of `zipfile` + `ElementTree` reads the
XLSX. No new dependency; `openpyxl` is not installed and does not need to be.

**Outbound.** Japanese departures (`出国日本人数`) are published by MOJ and reprinted by
JNTO. Annual **1964–2025** comes from a JNTO PDF that extracts cleanly; monthly appears in
the press PDF for the current and prior year only. Longer monthly history needs MOJ
immigration statistics on e-Stat.

**The outbound fact worth a chart on its own:** Japan crossed over in 2015 — 19.74m in
against 16.21m out. In 2025 inbound is **+33.9% above 2019** while outbound is still
**−26.6% below** it. Japanese travellers have not come back, and that gap is the travel
surplus.

**Licensing.** JNTO requires the credit line 「日本政府観光局(JNTO)」 on any reproduction —
the same shape as the BOJ obligation we already discharge. Encode it in the source registry
and render it on the page and in every CSV, not in someone's memory.

## 5. The join, measured

Against our own `cpi-jp-items` series `0139` (hotel charges, 0.81% of the CPI basket):

- arrivals YoY and hotel-CPI YoY correlate **0.60** across 102 non-COVID months
  (January 2014 – June 2026, excluding 2020–2022);
- slope ≈ **0.18pp** of hotel inflation per 1pp of arrivals growth;
- and the two have visibly decoupled: June 2026 arrivals are +9.3% on June 2019 while hotel
  charges are **+36.1%**.

That decoupling is a research question worth publishing — capacity, staffing, or two-tier
pricing — and it is only visible because both series sit in one database. It is also the
chain that connects this dataset to the rest of the platform: **arrivals → hotel CPI →
services inflation → BOJ → JGB yields**, all four of which we already hold.

## 6. Waves

| Wave | Content | Core change? | Why here |
| --- | --- | --- | --- |
| **T1** | **`jnto-visitors`** — arrivals by market, monthly, 2003– . Adapter + two registry lines + an Inbound page | **None** | The whole asset for one file. Proves the adapter pattern on a fourth measure type |
| **T2** | **Outbound**: annual arrivals/departures 1964–2025, then monthly departures from MOJ | None expected | Completes the flow picture and the crossover chart; the yen story starts here |
| **T3** | **Travel balance** via the BOJ API we already talk to (monthly, long history) | Reuses the BOJ adapter | Turns people into yen and links inbound to the current account |
| **T4** | **Spend per head** — JTA inbound consumption survey on e-Stat, quarterly, by market and expenditure category | Frequency handling | The equity layer: arrivals × spend per head by market is what actually drives retail revenue |

T1 is worth shipping alone. Nothing after it is a prerequisite for anything before it.

## 7. Golden-rule check

**T1 requires no core change.** Arrivals are a count of people: `unit = 'persons'`,
`weight_per_10000` NULL, values positive, monthly periods — the existing schema and the
existing `/api/v1/{dataset}/…` contract carry it unmodified. A fourth measure type
(*people*) joins price change, price level, stock and flow, and never mixes with them.

**The one design question that needs an answer before code**, because it looks like a
schema change and is not: how to mark 推計値 / 暫定値 / 確定値. This is a *revision status*,
not a trust level — the figures are official either way, so it must not become a third
badge, and `TRUST_LABELS` stays at `official` and `model`. Proposal: the adapter reads the
italic flag, records the provisional periods in the release's existing free-form
`validation` JSON, and the API exposes them; the chart marks those points and the CSV header
lists them. **Zero schema change.** Your call if you would rather see a badge.

## 8. What we deliberately do not build

- **No forecasts of arrivals.** The `Model Estimate` badge stays reserved and unused.
- **No prefecture-level tourism** in T1 — the accommodation survey is a separate dataset
  with its own reliability profile; revisit only if a customer asks.
- **No recommendations.** The page ranks markets and shows contributions; the reader
  concludes. Same permanent line as the equity surfaces.
- **No scraping of `statistics.jnto.go.jp`.** Its downloads are behind a use-application
  form; we take the openly published files only, and honour the credit line.

## 9. Risks and open decisions

| Risk / decision | Treatment | Severity |
| --- | --- | --- |
| The rotating URL changes shape and the monthly ingest silently stops | Discover the link from the page; fail loudly on no-match; staleness gate on `stale_after_days`. Ingest stays fail-safe — last good release keeps serving | **High** |
| Named markets do not sum to the headline in estimate months, and someone reads it as a data error | Residual disclosed and labelled on the page and in exports; provisional points marked | **High** |
| We oversell the vintage story out of habit (§3) | Written down here; the pitch is the join, not the archive | Medium |
| XLSX layout changes at a future rebase | Header-driven parsing, plus a validation gate on the expected market list; a failed gate publishes nothing | Medium |
| JNTO credit line forgotten in an export or a Substack chart | Encode in the source registry and the PNG/CSV templates | Medium |
| Dataset #5 dilutes focus from the equity roadmap | T1 is roughly one adapter and one page; T2–T4 only if T1 gets read | Medium |

**Open decisions, needing your call rather than code:**

1. **Revision status** — validation-JSON approach as proposed in §7, or a visible badge?
2. **Page identity** — a standalone Inbound page, or a section on a broader "Japan demand"
   page that later absorbs the travel balance?
3. **Whether T4 (spend per head) is the real product** and arrivals are merely the entry
   layer. If the equity audience is the target, spend-by-market may matter more than counts.
4. **Backfilling old vintages** (§3) — worth a couple of hours as a pipeline proof point, or
   skip given no revisions exist?

## 10. Definition of ready

Build starts when: (a) the revision-status decision in §7 is made; (b) the market list is
frozen as a validation gate, including the pre-2020 and pre-2016 shorter lists; (c) the
credit-line text is drafted for page, PNG and CSV.

**First slice (T1):** arrivals end to end — link discovery, raw archive with SHA-256,
validation, our API, and a rendered page showing monthly arrivals, recovery versus 2019, and
the YoY contribution decomposition with China separated and the residual disclosed, every
derived figure carrying its formula and the JNTO credit line visible. The hotel-CPI overlay
ships in the same slice, because it is the reason the dataset is here. Expand only after
that round-trips.
