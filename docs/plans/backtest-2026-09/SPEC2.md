# Multi-source signal backtest — pre-registered spec (round two)

Written BEFORE any of S2–S8 or any equity result is computed. Post-hoc changes are
recorded at the bottom, dated, with the reason.

## Data actually acquired (7 Sep 2026)

| Signal | Series | Source | Coverage | PIT |
|---|---|---|---|---|
| S1 | Japan export unit value, 254 lines | MOF via e-Stat | 2001-01 – 2026-07 | revised |
| S2 | Air-freight share of Japan exports, HS 8532.24 (MLCC), 8532.* (all capacitors), 8542.* (ICs) | MOF 航空貨物品別国別表 + 品別国別表 | 2001-01 – 2026-07 | revised |
| S3 | Taiwan monthly revenue: Yageo 2327 + Walsin 2492 + Holy Stone 3026 (MLCC); Nanya 2408 + Winbond 2344 + Macronix 2337 (memory) | MOPS via FinMind mirror | 2005-01 – 2026-08 | effectively PIT |
| S4 | Korea exports of HS 8542 (ICs), monthly | UN Comtrade public preview | 2010-01 – 2026-07 | revised |
| S5 | US M3 computers & electronic products: new orders A34SNO, shipments A34SVS, inv/ship ratio A34SIS, unfilled A34SUO | FRED (current vintage; ALFRED vintages if reachable) | 1992-01 – 2026-07 | current vintage unless ALFRED works |
| S6 | US PPI capacitors for electronic circuitry: WPU117811 (1968–2022-12) spliced to WPU117854 (2022-12–) | FRED | 1968 – 2026-07 | current vintage |
| S7 | Japan IIP inventory ratio, 電子部品・デバイス工業, 2010/2015/2020 bases spliced | METI via e-Stat | 2008-01 – 2026-03 | revised |
| S8 | WSTS worldwide semiconductor billings, monthly | WSTS Blue Book xlsx | 1986-01 – 2026-06 | revised |
| S9 | JEITA MLCC shipments | — | **not acquired**: JEITA site refuses automated fetch | — |
| S10 | Filings capex intensity | — | **not acquired**: back-extraction needs the S3 archive, no credentials on this machine | — |
| Prices | Monthly closes: 6981.T 6976.T 6762.T 6971.T 2327.TW 2492.TW 009150.KS MU 000660.KS 005930.KS 285A.T 1306.T (TOPIX ETF) SOXX | Yahoo chart endpoint | 2000 – 2026-09 | research-grade |

## Common definitions

- For a monthly level series x: `y3(t) = sum(x[t-2..t]) / sum(x[t-14..t-12]) − 1`.
- "Improving k months" at t: `y3(t) > y3(t-1) > … > y3(t-k)`.
- Cooldown: no second fire on the same signal within 5 months of a fire.
- k is chosen on the TRAIN window only, from {2, 3, 4, 6, 8}, by the objective below.

## Signal rules

| | Rule at month t (data month) | Publication lag L (months) |
|---|---|---|
| S1 | validated in round one: r3 improving 8 months, r3 ≥ +8%, q3 > 0, v3 > 0 — **fixed, not re-tuned** | 1 |
| S2 | air share a3(t) = 3m air value / 3m all-mode value for the HS group; fire when a3 improving k months AND a3(t) > median of a3 over [t-36, t-13] | 1 |
| S3 | MLCC trio revenue: y3 improving k months AND y3(t) ≥ 0 | 1 (published by the 10th; entry end of t+1 is conservative) |
| S4 | Korea HS 8542 exports: y3 improving k months AND y3(t) ≥ 0 | 1 |
| S5 | d(t) = y3(new orders) − y3(inventories), inventories = A34SIS × A34SVS; fire when d improving k months AND d(t) > 0 | 2 |
| S6 | p3(t) = 3m mean of the spliced PPI, yoy; fire when p3 improving k months AND p3(t) ≥ 0 | 1 |
| S7 | inventory ratio r3(t) = 3m mean; fire when r3 FALLING k months AND r3(t) < mean of r3 over [t-12, t-1] | 1 |
| S8 | WSTS worldwide: y3 improving k months AND y3(t) ≥ 0 | 2 |
| C2 / C3 | at least 2 / 3 of S1–S8 have fired within [t-2, t] (each signal's own data month) | max L of the contributing signals |

## Targets

- **T1 (MLCC, physical):** Japan capacitor export unit value P3 (3m aggregate, line
  70329000): hit if P3(t+6) ≥ P3(t). Base rate = same statistic over all months.
- **T2 (memory, physical):** Korea HS 8542 exports 3m sum: hit if X3(t+6) ≥ X3(t).
- **T3 (MLCC, equity):** equal-weight local-currency total return of {6981.T, 6976.T,
  6762.T, 2327.TW, 2492.TW, 009150.KS} over 3, 6, 12 months from the close of month
  t+L, minus 1306.T over the same window. Reported gross and net of 30bp round trip.
- **T4 (memory, equity):** {MU, 000660.KS, 005930.KS} minus SOXX, same construction.

Natural target per signal: S1, S2, S3, S6, S7 → T1/T3. S4, S5, S8 → T2/T4. Combinations → both.

## Windows and objective

- TRAIN 2005-01 – 2015-12 (S4 from 2010; S7 from 2008). Choose k per signal to maximise
  the physical-target hit rate subject to alert load ≤ 3 fires/month across the whole
  set. Ties → smaller k.
- TEST 2016-01 – 2026-07, untouched.
- Fires in the last 6 months of the test window cannot be scored and are listed, not counted.

## Success criteria (unchanged from round one)

1. Physical hit rate on TEST exceeds the base rate by more than one standard error.
2. Alert load ≤ 5/month on the combined set.
3. Recall of the named episodes: 2010 restock · 2017-18 MLCC/passives · 2017-18 DRAM ·
   2021-22 semiconductor shortage · 2025-26 AI buildout. Lead time = months from the
   publication month of the firing data to the target's local peak.
4. Combination test: C2 and C3 precision vs the best single signal.

## Limitations stated in advance

- Effective sample is ~6 cycles. Every number is suggestive.
- Only the US series can be point-in-time, and only if ALFRED is reachable without a key.
- Universe and baskets are chosen today (survivorship, look-ahead in selection).
- Equity prices are monthly closes from an unofficial endpoint; entry timing is
  end-of-month after publication, which is conservative for fast sources (Korea, Taiwan).
- S3 uses a third-party mirror of MOPS (FinMind); values are the companies' own filings
  but the mirror is not an official source. For research only.

## Post-hoc changes (dated 2026-09-07, before any test result was inspected for these items)

1. **Prices:** the first Yahoo pull returned monthly bars with impossible values (a +961%
   month on the TOPIX ETF, a −158% month on SK Hynix). Replaced with month-end closes
   derived from daily bars. Reason: data quality, not results.
2. **Train objective for T2-targeted signals:** Korea HS 8542 monthly data on Comtrade
   begins 2013-01, so S4 and S8 had no scorable train fires on T2. Where T2 has fewer
   than 3 scorable train fires, k is chosen on T1 instead; the TEST evaluation still
   uses the natural target. S4 is evaluated only on 2016–2026 as a result.
3. **Air share, MLCC:** on inspection ~97% of Japanese MLCC exports already travel by
   air, so the S2 MLCC rule has almost no headroom. It is run as registered and
   reported as such.
4. **Benchmark for T3:** Yahoo's series for 1306.T (TOPIX ETF) is corrupt in the daily
   data as well (+961% and −91% months in 2026, −90% in 2015-01). Replaced by 1321.T
   (Nikkei 225 ETF), whose largest monthly move is 17%. Reason: data quality.
5. **S4 (Korea) cannot be trained** — fewer than three scorable train fires on either
   target because the series starts 2013. Reported at k=4, borrowed from S8 (same rule
   family), and labelled untrained. Reason: data availability.
6. **Peaks in the 2025-26 window are censored** — the data ends 2026-07 (Japan) and
   2025-12 (Korea/Comtrade), so "lead to peak" there is a lower bound, not a lead.
