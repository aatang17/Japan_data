# Round three — pre-registered, written before running

## What went wrong before, and the rule that fixes each

| Problem found | Fix in this round |
|---|---|
| Index contained the target price series | **No signal may be built from Japan's HS 8532.24 export value or quantity.** The target is computed from it; nothing else is. |
| "Warned 7 of 9" with an indicator on 60% of the time | **Every row reports its base rate AND a permutation p-value**: 2,000 random re-drawings of the same number of fires at the same spacing. A signal is only "reliable" if random timing rarely matches it. |
| Components chosen after seeing 2016–2026 | **Candidates listed here, before any result.** Every candidate is reported, including the failures. Nothing is dropped after the fact. |
| Episodes defined by the target, scored coincidentally | Target is **forward-looking only**: what the price does in the six months AFTER the fire. A fire in the same month as a spike start scores zero lead. |
| Fires cluster within episodes | **Six-month cooldown** per signal; each surviving fire is one observation. n is the fire count, not the month count. |
| Threshold picked after looking | Fire rule, k, thresholds and success criterion fixed in this file. k is chosen on the earliest available window and evaluated on the rest; series too short to split use k=4 (the validated value for revenue-type series) and are labelled UNTUNED. |

## Target (outcome), fixed

P3(t) = Japan MLCC export unit value, 3-month aggregate, HS 8532.24.

**Primary — "a spike starts":** at month t the price is NOT already spiking
(P3 yoy < +8%), and within t+1..t+6 the P3 yoy crosses ≥ +8%. Fires that land
while a spike is already running are not scorable for this target and are
counted separately as "fired mid-spike".

**Secondary — "price rises":** P3(t+6) / P3(t) − 1 ≥ +5%, scored for every fire.

Base rate for each = the unconditional share of eligible months where the
outcome occurs.

## Fire rule, fixed

For a monthly series x: y3(t) = 3m sum / 3m sum a year earlier − 1.
Fire when y3 has improved k consecutive months AND y3(t) ≥ 0. Six-month cooldown.
For an inventory-type series the rule is inverted (falling k months, below 12m mean).
For a price-gap series (HK markup, US orders−inventories) the rule is: gap > 0
and improving k months.

## Candidates, all of them, with source and independence from the target

| # | Signal | Source | From | Independent of target? | k |
|---|---|---|---|---|---|
| 1 | Taiwan MLCC revenue (2327+2492+3026) | MOPS via FinMind | 2005 | yes | train 2005–15, test 2016– |
| 2 | Taiwan server ODM revenue (2382+2356+6669) | same | 2005 | yes | same |
| 3 | Taiwan memory revenue (2408+2344+2337) | same | 2005 | yes | same |
| 4 | HK MLCC import price, all origins, HK$/unit | HK C&SD IDDS | 2018 | partial (29% Japanese product) | 4, UNTUNED |
| 5 | HK MLCC re-exports to China, units | same | 2018 | yes | 4, UNTUNED |
| 6 | HK channel gap (imports − re-exports, units), inverted | same | 2018 | yes | 4, UNTUNED |
| 7 | HK re-export markup (out price / in price) | same | 2018 | yes | 4, UNTUNED |
| 8 | US M3 computers & electronics: orders − inventories | FRED | 1992 | yes | train/test |
| 9 | US PPI capacitors for electronic circuitry | FRED | 1968 | yes | train/test |
| 10 | Barium carbonate import price (HS 2836.60) | MOF | 2001 | yes | train/test |
| 11 | Nickel powder export value (HS 7504) | MOF | 2001 | yes | train/test |
| 12 | Japan IIP electronic-parts inventory ratio, inverted | METI | 2008 | yes | train/test |
| 13 | WSTS worldwide billings | WSTS | 1986 | yes | train/test |
| 14 | Korea IC exports (HS 8542) | Comtrade | 2013 | yes | 4, UNTUNED |

Not a candidate: anything from Japan's capacitor or MLCC export lines
(target family), the corridor spread (built from the target line by
destination), the Japanese blended capacitor line.

## Success criterion, fixed

A signal is reported as **reliable** only if, on its test window:
- primary hit rate exceeds base rate, AND
- permutation p ≤ 0.10, AND
- at least 5 scorable fires.

"Suggestive" = beats base rate with p ≤ 0.25. Otherwise "no evidence".

## Limitations accepted in advance

- HK series have 8 years — no split possible; results are untuned and thin.
- Japan trade values are as-revised; only US series are point-in-time.
- The target is one country's export price. A spike in Korean or Taiwanese
  MLCC prices that Japan's exporters did not follow is invisible to it.
- 2,000 permutations is enough to place p to about ±0.01.
