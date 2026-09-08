# Backtest results — component-cycle signals, round two (7 September 2026)

> Executes `PLAN-SIGNAL-BACKTEST.md`. Research only: nothing here touched the product,
> the volume, or the serving process. All inputs were pulled into a session scratch
> directory; the rules and success criteria were written to a spec file **before** any
> result was computed, and every post-hoc change is listed in §7 with its reason.

---

## 1. Bottom line

Eight of the ten signals in the plan were acquired and tested on 2016–2026 with
parameters chosen on 2005–2015. Three things survive contact with the data:

1. **Taiwan's monthly MLCC revenue (Yageo + Walsin + Holy Stone) is the earliest and
   strongest single MLCC signal.** Nine fires in eleven years; the capacitor price was
   still higher six months later after **78%** of them (base rate 63%), and the MLCC
   equity basket's median six-month excess return after a fire was **+10.5%** against a
   base of +3.2%. It fired on **September 2017** — the last MLCC shortage — and on
   **November 2025**, published in December 2025, three months before Japanese capacitor
   prices broke out and four months before the MLCC names went vertical.
2. **Agreement beats any one signal.** When three or more independent signals fired
   within three months (13 times in eleven years), the capacitor price was higher six
   months later **83%** of the time and the MLCC basket's median six-month excess return
   was **+16.9%** (hit rate 67%). Every named episode — 2017-18, 2021-22, 2025-26 — was
   flagged by a three-signal cluster, at publication dates of May 2017, November 2020
   and December 2025.
3. **The US series are honestly point-in-time and revisions matter:** on the data as it
   actually stood at publication, 8 of 10 orders-minus-inventories fires and 7 of 11 PPI
   fires would still have fired. Roughly one fire in five on a revised series is an
   artefact of revision. Nobody else in this list can be checked this way.

What did **not** work: the US capacitor PPI and Japan's inventory ratio add nothing for
equities (median excess ≈ 0) even though they score on the physical target; the
air-freight share of MLCC exports is structurally useless because 97% of Japanese MLCCs
already fly; and Korea's monthly IC exports could not be trained at all (the free
Comtrade feed starts in 2013).

The effective sample remains about six cycles. Nothing here is proven. What it earns is
a ranked shortlist worth running forward, and a clear first pick.

---

## 2. What was acquired

| Signal | Series | Source | Coverage | PIT | Status |
|---|---|---|---|---|---|
| S1 | Japan export unit value, 254 lines | MOF via e-Stat | 2001-01 – 2026-07 | revised | ✓ (round one) |
| S2 | Air-freight share of Japan exports: HS 8532.24 (MLCC), 8532.* (capacitors), 8542.* (ICs) | MOF 航空貨物品別国別表 + 品別国別表, 12 tables | 2001-01 – 2026-07 | revised | ✓ |
| S3 | Taiwan monthly revenue, MLCC trio (2327, 2492, 3026); memory trio (2408, 2344, 2337) | MOPS filings via FinMind mirror (MOPS itself refuses automated access) | 2005-01 – 2026-08 | effectively PIT | ✓ |
| S4 | Korea exports HS 8542 (ICs), monthly | UN Comtrade public preview, 163 calls | **2013-01** – 2025-12 | revised | ✓ but untrainable |
| S5 | US M3 computers & electronics: new orders, shipments, inv/ship ratio, unfilled | FRED + **ALFRED vintages** at each fire | 1992-01 – 2026-07 | **true PIT** | ✓ |
| S6 | US PPI capacitors: WPU117811 (1968–2022-12) spliced to WPU117854 | FRED + ALFRED | 1968 – 2026-07 | **true PIT** | ✓ |
| S7 | Japan IIP inventory ratio, 電子部品・デバイス工業, three bases spliced | METI via e-Stat | 2008-01 – **2026-03** (IIP tables on e-Stat stop there) | revised | ✓ |
| S8 | WSTS worldwide semiconductor billings | WSTS Blue Book xlsx | 1986-01 – 2026-06 | revised | ✓ |
| S9 | JEITA MLCC shipments | — | — | — | ✗ site refuses automated fetch |
| S10 | Filings capex intensity, five cross-sections | — | — | — | ✗ needs the S3 filing archive; no credentials on this machine |
| Prices | Month-end adjusted closes: 6981.T 6976.T 6762.T 2327.TW 2492.TW 009150.KS / MU 000660.KS 005930.KS; benchmarks 1321.T (Nikkei ETF), SOXX | Yahoo chart endpoint, daily bars | 2000 – 2026-09 | research-grade | ✓ |

Dead ends worth recording so nobody repeats them: KOSIS needs a Korean identity; MOPS
and the MOEA export-orders page block scripted access; JEITA likewise; Yahoo's data for
1306.T (TOPIX ETF) is corrupt (an unadjusted 10:1 split and a bad tick), hence 1321.T.

## 3. Method

Identical discipline to round one. Rule per signal frozen in advance; base rate reported
next to every score; parameter k (months of consecutive improvement) chosen on
**2005–2015** only, evaluated untouched on **2016–2026**; episodes named from industry
knowledge, not from the data; publication lag modelled per source (Japan trade 1 month,
Taiwan 1, Korea 1, US M3 2, PPI 1, IIP 1, WSTS 2); equity entry at the month-end
**after** publication.

Targets. Physical: is the Japan capacitor export unit value (T1) or Korea's IC exports
(T2) still higher six months after the fire? Equity: equal-weight local-currency return
of the MLCC basket minus the Nikkei ETF (T3), or the memory basket minus SOXX (T4), over
3/6/12 months. **Medians are the honest equity statistic here** — the MLCC basket rose
several-fold in April–June 2026, so any mean that includes a 2025–26 fire is dominated by
one episode. Base rates on the test window: T1 62.8%, T2 70.2%; MLCC basket six-month
excess mean +15.2% / **median +3.2%** / hit 55%; memory basket mean +10.8% / median +3.0% / hit 56%.

## 4. Results — single signals, test window 2016-01 to 2026-07

| Signal | k | Fires | Physical hit vs base | Equity 6m excess: median · mean · hit | Verdict |
|---|---:|---:|---|---|---|
| **S3 Taiwan MLCC revenue** | 4 | 9 | **78% vs 63%** (T1, n=9, ±14pp) | **+10.5%** · +49.4% · 78% | **Keep — first pick** |
| **S5 US orders − inventories** | 2 | 10 | **100% vs 70%** (T2, n=8) | **+7.9%** · +19.8% · 80% | Keep — 8/10 fires confirmed point-in-time |
| S8 WSTS billings | 4 | 8 | 100% vs 70% (T2, n=6) | +9.1% · +20.2% · 71% | Keep, coarse |
| S7 Japan parts inventory ratio | 4 | 6 | 83% vs 63% (T1, n=6, ±15pp) | −2.5% · +0.5% · 33% | Physical only; no equity content |
| S6 US PPI capacitors | 2 | 11 | 64% vs 63% (T1, n=11) | −3.0% · 0.0% · 45% | **Drop** — no edge either way |
| S2 air share, ICs | 3 | 9 | 71% vs 70% (T2, n=7) | +6.8% · +22.0% · 63% | Weak |
| S2 air share, MLCC | 4 | 4 | 100% (n=3) | +31.2% · +42.3% · 75% | Too few fires; 97% of MLCCs already fly |
| S4 Korea IC exports | (4, borrowed) | 6 | 100% vs 70% (T2, n=6) | +9.1% · +2.5% · 67% | Untrained — series starts 2013 |
| S1 Japan export price persistence | 8 (fixed) | 55 | 73% vs 59% on each line's own price (round one) | — | Keep, universe-wide attention tool |

Alert load across all eight signals: **112 fires in 127 months, 0.88 per month**, 55 of
them from S1's 254-line universe. Criterion (≤ 5/month) passes easily.

The fire dates matter more than the percentages. S3 fired 2016-01, 2016-08, **2017-09**,
2018-03, 2018-09, 2020-04, 2020-10, 2024-01, **2025-11**. S5 fired 2016-02, 2017-09,
2018-05, 2019-04, 2020-10, 2023-12, 2024-06, 2025-01, 2025-07, 2026-01.

## 5. Results — combinations

"C3" = at least three of the eight signals fired within a three-month window; entry two
months after the window closes.

| | Fires | T1 hit vs base | T2 hit vs base | MLCC basket 6m excess (median · mean · hit) | Memory basket 6m excess |
|---|---:|---|---|---|---|
| C2 (≥2 agree) | 16 | 73% vs 63% | 85% vs 70% | +0.3% · +10.7% · 53% | +3.9% · +7.6% · 53% |
| **C3 (≥3 agree)** | **13** | **83% vs 63%** (n=12, ~1.9 SE) | 82% vs 70% | **+16.9% · +22.4% · 67%** | +5.5% · +1.9% · 58% |

C3 improves on the best single signal on the physical MLCC target (83% vs 78%) and on the
equity median (+16.9% vs +10.5%). The agreement hypothesis has support — weakly, on a
dozen events. The per-fire MLCC-basket record for C3, six-month excess over the Nikkei ETF:

| Cluster (data month) | Signals agreeing | Entry | 6m excess | 12m excess |
|---|---|---|---:|---:|
| 2016-09 | S2 ICs, S3, S8 | 2016-11 | +26% | +89% |
| 2017-03 | S1, S2 ICs, S6, S8 | 2017-05 | +38% | +215% |
| **2017-09** | S1, S2 ICs, S2 MLCC, **S3**, S5 | 2017-11 | **+87%** | +26% |
| 2018-05 | S3, S5, S6 | 2018-07 | −31% | −37% |
| 2018-11 | S1, S3, S6 | 2019-01 | −8% | +26% |
| 2020-04 | S3, S6, S8 | 2020-06 | +17% | +10% |
| 2020-10 | S3, S5, S7, S8 | 2020-12 | −6% | −5% |
| 2021-04 | S1, S7, S8 | 2021-06 | +0% | −20% |
| 2022-07 | S1, S2 ICs, S6 | 2022-09 | +20% | +6% |
| 2023-11 | S2 ICs, S7, S8 | 2024-01 | +17% | −14% |
| 2024-06 | S1, S5, S7 | 2024-08 | −13% | −21% |
| **2025-11** | S2 ICs, **S3**, S8 | 2026-01 | **+122%** | — |
| 2026-06 | S1, S2 ICs, S8 | 2026-08 | — | — |

Read that honestly: it caught both MLCC shortages and the 2016–17 run, and it was wrong
in 2018 (late-cycle) and 2024. It is a cycle-*start* detector; it has no idea when to
leave.

## 6. Episode recall and lead time

| Episode | First three-signal cluster published | First S3 (Taiwan) fire published | Capacitor price peak | Notes |
|---|---|---|---|---|
| 2017-18 MLCC / DRAM | **May 2017** | Oct 2017 | 2019-05 | S1's own capacitor line fired Sep 2017 (round one) |
| 2021-22 semis shortage | **Nov 2020** | Nov 2020 | 2023-02 | led by Taiwan revenue, US orders, Japan inventory ratio, WSTS together |
| 2025-26 AI buildout | **Dec 2025** | Dec 2025 | ≥ 2026-07 (data ends; censored) | Japan capacitor price broke out Mar 2026; MLCC equities Apr–Jun 2026 |

Lead to the physical peak is 11–30 months in the two completed episodes; lead to the
*equity* move in 2025-26 was three to four months from the December 2025 publication.

## 7. Point-in-time check (ALFRED)

For every S5 and S6 fire, the rule was recomputed on the vintage of the US data that
existed at the end of the publication month.

- **S5 orders − inventories:** 8 of 10 fires stand. 2016-02 and 2019-04 exist only in
  revised data — they would not have fired at the time.
- **S6 PPI capacitors:** 7 of 11 stand. 2021-01 is a revision artefact; 2023-01, 2023-07
  and 2024-02 were **unobservable** — the old index was discontinued in December 2022 and
  its successor was not yet in ALFRED at those dates. A practitioner would have had a
  fifteen-month hole.

Implication for every revised series in this study (Japan, Korea, WSTS): expect
roughly one fire in five to be a revision artefact, and treat all lead times on those
sources as optimistic.

## 8. Verdict against the pre-registered criteria

| Criterion | Result |
|---|---|
| 1. Physical hit rate beats base by > 1 SE on TEST | **Pass** for S3, S5, S7, S8 and C3; fail for S6 and S2-ICs |
| 2. Alert load ≤ 5/month | **Pass** (0.88) |
| 3. Recall of named episodes | **Pass** — all three test-window episodes flagged by C3 with lead |
| 4. Combination beats best single signal | **Pass, weakly** — C3 > S3 on both physical (83 vs 78) and equity median (+16.9 vs +10.5) |

## 9. What this means for the product

- **Widen the trade adapter (unchanged from the plan).** S1 is the only universe-wide
  signal and everything else is one series each.
- **Add Taiwan monthly revenue as an input.** It is the first pick by every measure, it
  is effectively point-in-time, and it costs one JSON call a month. The history has to
  come from a mirror or be accumulated from now on — MOPS blocks scripts.
- **Add US M3 and archive the vintage each month** — the only source where "what did we
  know and when" can be answered from the publisher's own record.
- **Ship the cluster count, not a forecast.** "Three of eight independent series turned
  up within a quarter" is a defensible, citable statement; "buy Murata" is not.
- **Drop the PPI and the air-freight MLCC share.** Keep the inventory ratio as a physical
  corroborator only.

## 10. Post-hoc changes to the spec, with reasons

1. Prices: Yahoo's monthly bars carried impossible values; replaced with month-end closes
   built from daily bars. Data quality.
2. Benchmark: 1306.T corrupt (unadjusted split, bad tick); replaced by 1321.T. Data quality.
3. Training fallback: signals whose natural target (Korea) begins in 2013 are trained on
   the Japan capacitor target; test evaluation unchanged. Data availability.
4. S4 untrainable; reported at k=4 borrowed from S8 and labelled as such. Data availability.
5. Air-freight MLCC share run as registered despite ~97% saturation. Reported, not tuned.
6. 2025-26 peaks are censored at the end of the data; leads there are lower bounds.

## 11. Limitations that do not go away

- ~6 cycles. Standard errors of 10–15pp on every hit rate; effective n far below the
  fire count because fires cluster within episodes.
- Survivorship: universe and baskets chosen in 2026.
- Equity results are dominated by 2025-26. Medians are reported for that reason; even
  they rest on a dozen events.
- Only the US series were verified point-in-time. Everything else is as-revised.
- Equity prices are research-grade; the event study is for judgement, not for a page.
- JEITA (S9) and the filings screen (S10) were not tested at all.

## 12. Where the artefacts are

`docs/plans/backtest-2026-09/` holds the spec files, engine, full output and the round-one scripts. Raw pulls stay in session scratch: `SPEC2.md` (pre-registration and post-hoc log),
`bt2.py` (engine), `bt2_out.txt` (full output), `pit.py` (ALFRED check), raw pulls
(`hist.json`, `scan.json`, `air_hs.json`, `finmind_*.json`, `comtrade_kr_8542.json`,
`fred/`, `alf/`, `wsts.json`, `iip_invratio.json`, `pxd/`). Nothing was written to
`observatory/data/` and nothing was committed.

---

## 13. Addendum — the same machinery beyond MLCCs (7 September 2026)

The rules are product-agnostic. Re-run with **no parameter changes** (S1 k=8, S3 k=4,
S5 k=2, S7 k=4) across every cell each source offers. Script and full output:
`backtest-2026-09/families.py`, `families_out.txt`.

**Family A — Japan export prices, 254 product lines** (monthly, 25-day lag). Firing now:
copper sheet & strip (11-month run, price +36%, volume +14%), brass (10 months, +37%).
One to four months short: bare copper wire (+78%), **capacitors (+18%)**, insulated wire
& cable (+17%), hand tools, passenger cars (+18% on ¥16.6tn of exports), roller bearings,
ICs (+53%), discrete semis (+22%), aluminium sheet, photographic film.

**Family B — Japan inventory ratios, 124 industries** (monthly, 30-day lag, data to
2026-03). Firing: powder metallurgy (−26% vs its own 12-month mean), heating/cooking
equipment, **batteries (−38%)**, **electrical machinery (−13%)**, **electrical measuring
instruments (−26%)**, paper, textiles, stationery. Below mean but no run: analytical and
testing instruments, wireless communications equipment.

**Family C — Taiwan revenue baskets** (monthly, 10-day lag, 1,085 listed companies
available). Firing: **memory (18-month run, 3m revenue +361% yoy)**, CCL/PCB materials
(8 months, +122%), ASIC & analog design (5 months), server ODM (4 months, +78%). One
month short: power & thermal (+51%), foundry (+45%), passives/MLCC (+41%), ABF substrates
(+38%), OSAT (+34%). Fab tools & build-out +76% yoy but no run.

**Family D — US manufacturing orders, 7 industry cells** (monthly, 35-day lag, true
ALFRED vintages). Firing: metals & machinery (6-month run, orders−inventories gap
+12.6pp), food & textiles. Two months short: chemicals/paper/plastics, computers &
electronics, total manufacturing. Negative: transport equipment, **core capex ex-aircraft
(−18pp)**.

### What the four families say together

Three distinct clusters, only one of which is the AI story:

1. **AI compute** — memory, ICs, ABF substrates, CCL, server ODM, OSAT, fab tools.
2. **Electrification and power** — copper sheet, brass, bare copper wire, insulated
   cable, Japanese battery and electrical-machinery inventories drawn down hard, Delta
   and AVC accelerating, electrical measuring instruments destocked. Four independent
   sources, one story, and it is not the MLCC story.
3. **Traditional capital goods are weak** — US core capex −18pp and transport equipment
   negative while everything above accelerates.

### Not yet exploited, same plumbing

Air-freight share on any of Japan's 4,713 HS export lines (mechanism proven; MLCC was a
dud only because 97% of them already fly); Comtrade for any reporter × HS code (keyless);
US PPI for thousands of product cells with vintages; Japan's 427 **import** unit-value
lines (the input side — we carry five today); company capex/inventory intensity across
2,243 filings.

### Caveats specific to this addendum

Only the MLCC- and memory-adjacent signals were backtested. Family B had no equity
content in the test (median excess −2.5%). Family D's non-electronics cells were never
scored against any target — there is no defined outcome series for "copper" or "food"
in this work. These are current readings from validated rules, not validated signals.

---

## 14. Round three — the leak-free test, and what it retracts (8 September 2026)

Spec, engine and full output: `backtest-2026-09/SPEC3.md`, `bt3.py`, `bt3_out.txt`.

**Why a third round.** Sections 1–13 contain two errors that flatter every
MLCC-specific result: the tightness index included the Japanese MLCC price it
was meant to predict, and fires that landed in the same month a spike began were
scored as hits. Round three fixes both and adds a random-timing null.

**Design.** Target defined first and forward-only: *the price is not spiking now
(< +8% yoy) and a spike (≥ +8%) begins within six months.* No candidate may be
built from Japan's HS 8532.24 export value or quantity. Fourteen candidates
listed before running, all reported. Six-month cooldown so each fire is one
observation. Every row carries its base rate **and** a permutation p-value from
2,000 random re-drawings of the same number of fires at the same spacing.

**Result: none of the fourteen is reliable, and none is even suggestive.**

| Candidate | Fires | Scorable | Hit vs base | p |
|---|---:|---:|---|---:|
| Taiwan memory revenue | 11 | 7 | 57% vs 40% | 0.29 |
| Taiwan MLCC revenue | 14 | 7 | 43% vs 40% | 0.74 |
| HK MLCC import price | 4 | 3 | 67% vs 43% | 0.40 |
| US orders − inventories | 10 | 5 | 40% vs 40% | 0.74 |
| US PPI capacitors | 11 | 6 | 17% vs 40% | 0.99 |
| Korea IC exports | 7 | 5 | 40% vs 45% | 0.76 |
| Combination, ≥3 agree | 8 | 5 | 60% vs 43% | — |

(Full table in `bt3_out.txt`; the untuned fixed-k=4 full-history variant gives the same picture.)

**The reason is sample size, not the signals.** The base rate is ~40%: MLCC
price spikes are frequent — nine in 25 years, the price above +8% in half of
all months. Against that base, a signal with seven scorable fires must hit
**71%** to reach p ≤ 0.10; with thirty fires, 53%. No MLCC-specific series has
thirty independent fires in its history. The test is not rejecting the signals;
it cannot pass anything at this n.

**What this retracts.** The 0–100 index (§ "MLCC Tightness Index",
`equity/mlcc_index.py`) and any claim that it "caught 2017". The index rose
*with* the 2017 spike, not before it, because it contained the price. Its
leading components alone sit above 45 in 60% of months, so "warned 7 of 9" is
what always-on would score.

**What stands.**
- The round-one result on the *pooled* 254-line Japanese export universe
  (73% vs 59% base, ~50 fires, out of sample) — pooling across products is the
  only way to reach a usable n. It was not permutation-tested; that is the next step.
- The descriptive record of 2025–26: Taiwan revenue fired on November 2025 data,
  Japan's MLCC price crossed +8% on April 2026 data. One episode; a story, not evidence.
- Everything about *seeing* the cycle: units, destinations, dielectric split,
  Hong Kong channel stock. The data describes the MLCC market in real time with
  more granularity than anything published. It cannot be shown to predict it.

**Product implication.** Sell "see it as it happens, everywhere, with
provenance". Do not sell "see it before it happens" for any single product.

---

## 15. Round four — pooled across products, replicated in Hong Kong: one signal survives (8 September 2026)

Spec, engine, output and the Hong Kong fetcher: `backtest-2026-09/SPEC4.md`,
`bt4.py`, `bt4_out.txt`, `hk_universe.py`. The Hong Kong panel itself
(990 HS-6 import lines, monthly 2015–2026, value and units, from the C&SD
IDDS API) lives in session scratch as `hk_universe.json`; it is re-fetchable
in about eight minutes.

**Why this round works where round three could not.** A single product has
nine episodes in 25 years. Pooling 138 Japanese export lines under one fixed
rule gives 117 scorable fires; pooling 990 Hong Kong import lines gives 215.
That is enough to test against a random-timing null.

**Design.** Five candidate rules listed before running, identical on every
line. Target forward-only: *price yoy < +8% now; crosses ≥ +8% within six
months.* k chosen on Japan 2005–2015 only. Hong Kong receives Japan's k
unchanged — no parameter touched it. Six-month cooldown per line.
Permutation null: per line, the same number of fires re-drawn at random
eligible months, 300–1,000 draws. Leave-one-year-out on every result.

**Result.**

| Rule | Japan: hit vs base (n) · p | Hong Kong: hit vs base (n) · p | Verdict |
|---|---|---|---|
| **BOTH** — price and volume yoy both improving ≥2 months, both ≥ 0 | **57.3% vs 38.5%** (117) · 0.000 | **73.0% vs 58.6%** (215) · 0.000 | **RELIABLE, replicates** |
| VALUE — export value improving ≥8 months | 51.2% vs 38.5% (80) · 0.000 | 54.5% vs 58.6% (99) · 0.11 | Japan only — does not replicate |
| PRICE — price yoy improving ≥8 months | 57.6% vs 38.5% (33) · 0.00 | 76.2% vs 58.6% (21) · 0.00 | suggestive; fires mostly mid-spike |
| VOLUME alone | 40.3% vs 38.5% · 0.99 | 58.3% vs 58.6% · 1.00 | nothing |
| VOL-LEADS — volume up, price flat | 45.5% vs 38.5% · 0.95 | 58.2% vs 58.6% · 1.00 | nothing |

**BOTH, in detail.**
- Not a few lines: 117 fires across 68 Japanese lines, no line contributing
  more than 2 hits; Hong Kong hits spread across every year 2016–2026.
- Leave-one-year-out: worst case 48.8% (dropping 2021) on Japan, still 10pp
  over base; Hong Kong 74.0% with 2021–22 removed.
- **Stricter null**: random months on the same lines *within the same 0–8%
  yoy band* — i.e. "price already positive, random timing" — score 41.1%
  (Japan) and 62.6% (Hong Kong). The momentum run itself adds 10–16pp.
- Lead time: median **2 months** from fire to crossing +8% (distribution
  1:22, 2:12, 3:7, 4:11, 5:10, 6:5). Short. It is trend *continuation*, seen
  early, not a distant forecast.
- **It does not predict magnitude.** Median forward six-month price change
  after a fire is +3.5% against +2.2% for all eligible months; means are
  identical. It predicts that a rising rate keeps rising past a threshold,
  not that the move will be large.

**What it is, in plain words.** When a product's price *and* its volume have
both been accelerating for two months, and the price is not yet 8% above last
year, the odds that it gets there within six months rise from roughly 2-in-5
to roughly 3-in-5 in Japan, and from 3-in-5 to 3-in-4 in Hong Kong. That holds
across 1,128 product lines in two customs systems, and against random timing
on the same lines in the same price band.

**Current fires (Japan, June 2026 data, pre-spike):** semiconductor
manufacturing equipment (¥4.66tn/yr, price +7.0%, volume +4.2%), plated steel
sheet, paper & paperboard, packaging paper (+17.6% volume), printing paper.
July's fires — cars, brass, bare copper wire — are already past +8%.

**Retractions carried forward.** The single-product tightness index remains
retracted. VALUE is dropped: it was a Japan-only artefact.

**Limits.** Base rates differ by country (Hong Kong's unit values are noisier,
so spikes are more frequent there); the edge is similar in both. Two months of
lead is what the data supports — not four, not six. As-revised data throughout.

---

## 16. Round five — what else moves these prices: common factor, co-movement, chain direction, final customer (8 September 2026)

Scripts and full output: `backtest-2026-09/chain.py`, `chain2.py`, `chain3.py`, `chain_out.txt`.
Panel: Hong Kong imports, 990 HS-6 lines, 2016-01 → 2026-07; Japan 138 lines for Test 1.
Chain pairs were written into `chain.py` before any result was computed.

**Test 1 — how much is "the market"?** Regress each line's price yoy on the
cross-line median. Hong Kong: median R² **0.03**, only 4 of 920 lines above
0.5. Japan: median R² 0.29 — the yen moves every yen unit value together.
BOTH re-run on the *residual* (line minus market) still passes: Hong Kong
74.2% vs 56.0% base, Japan 40.8% vs 29.4%, both p = 0.000. The signal is about
the product, not the tide.

**Test 2 — what co-moves.** Average pairwise correlation of price yoy is
≈ +0.04 within components, within devices, within materials, and across all
three. Unit-value moves are idiosyncratic. The exceptions are specific
material → component pairs, and they read like cost pass-through:
aluminium wire (7605.29) ~ wirewound resistors (8533.31) r = +0.92; acrylic
sheet (3920.63) ~ wirewound resistors +0.86; PVC (3914) ~ coaxial cable
(8544.20) +0.78; aluminium ingot (7601.10) ~ copper winding wire (8544.11)
+0.77; polyester (3907.61) ~ other conductors (8544.70) +0.75. About 490,000
pairs were scanned; r > 0.7 on ~110 observations is not chance, but these
are candidates for a cost-pass-through map, not proven links.

**Test 3 — which way does the chain lead?** Ten pre-specified
upstream → downstream chains. A BOTH fire on the *upstream* line raises the
odds of a spike starting *downstream* within six months: pooled **68.6% vs
50.4%** (n = 86, permutation p = 0.004). The reverse direction —
downstream fire → upstream spike — is nothing: 52.1% vs 49.5%. The result is
carried by one chain: **copper → cables, connectors, transformers, 73.5% vs
48.2%, n = 49, p < 0.001**. The other chains point the same way but thin
out — 62.2% on 37, p = 0.21. Several chains (wafers → ICs, Li-ion → EVs,
steel → cars) produced no fires because their HS-6 lines lack usable units in
Hong Kong.

**Test 4 — the final customer.** Three demand-side series, all tested as
leaders of Hong Kong component import prices:
- China-bound re-exports of finished goods (computers, servers, phones,
  monitors, batteries, power supplies; 11 HS-6 lines, units): **51.9% vs
  51.9%**. Nothing. Reverse direction also nothing (48.4% vs 47.5%).
- Taiwan server-ODM revenue (Quanta, Inventec, Wiwynn), four-month run:
  **28.6% vs 51.9%, p = 1.00** — *inverse*. Foundry revenue → IC prices:
  20.0% vs 50.3%. MLCC makers' revenue → capacitor prices: 43.5% vs 48.3%.
- Coincidence check: in the months Taiwan revenue fires, *fewer* component
  lines are already spiking than in an average month (28–38% vs 42–45%).
  Taiwan's customers accelerate when component prices are quiet, and prices
  do not follow within six months.
- The reverse — component price fire → Taiwan customer revenue accelerating
  within six months — is the only demand-side result with a pulse: server
  ODMs 60.0% vs 46.7%, n = 15, p = 0.17. Suggestive at best.

**What this retracts.** The narrative that Taiwan MLCC revenue "led" the 2026
Japanese price move. It did in that one episode (November 2025 → April 2026).
Pooled across 23 fires against Hong Kong capacitor prices, and across 14
against Japan's in round three, it does not. One episode was a story.

**What it establishes.**
1. Component and material prices are overwhelmingly product-specific; a
   common factor explains ~3% of the variance in Hong Kong.
2. Costs push forward, demand does not pull back: material price momentum
   precedes component price spikes; customer revenue does not.
3. The one chain with enough events to be sure is copper → the copper-bearing
   components. Everything else is a direction, not a finding.
