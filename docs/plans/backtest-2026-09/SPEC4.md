# Round four — pooled across products, written before running

## Why pooling

Round three showed a single product cannot be validated: nine episodes in 25
years, seven scorable fires per signal, a test that needs 71% to pass. Pooling
across hundreds of product lines under ONE fixed rule turns seven fires into
several hundred. That is the only route to a signal that can be shown to work.

## Universe A (Japan) — already held

138 Japanese export lines (概況品, level 3–4) with a published quantity and
≥ ¥20bn/yr, monthly 2001-01 → 2026-07. Unit value = value ÷ quantity.

## Universe B (Hong Kong) — to be fetched, used only as replication

Hong Kong imports by HS-6 subheading, electronics chapters, monthly 2015 →
2026-07, value (HK$) and quantity, from the C&SD IDDS API. A different
reporter, currency, customs system and product mix. **No parameter is tuned on
it.** Whatever k Universe A's training window picks is applied unchanged.

## Signals (pooled, identical rule on every line)

For each line: P = 3m unit value, Q = 3m quantity, V = 3m value; yoy of each.
"Improving k months" = the yoy statistic rose each of the last k months.

| id | rule at month t |
|---|---|
| PRICE | price yoy improving k months AND ≥ 0 (round one's rule) |
| VOLUME | quantity yoy improving k months AND ≥ 0 |
| BOTH | price AND quantity yoy both improving k months, both ≥ 0 |
| VALUE | value yoy improving k months AND ≥ 0 |
| VOL-LEADS | quantity yoy improving k months AND ≥ +10%, price yoy still ≤ +3% |

VOL-LEADS is the new hypothesis: demand pulls before price moves. Six-month
cooldown per line per signal.

## Target (own line, forward only)

Primary — spike start: price yoy < +8% at t; crosses ≥ +8% within t+1..t+6.
Secondary — P(t+6)/P(t) − 1 ≥ +5%.
Fires landing mid-spike are not scorable for the primary and are counted.

## Method

- k chosen on TRAIN 2005–2015 (pooled), from {2,3,4,6,8}, maximising primary
  hit rate subject to ≥ 30 pooled fires; ties → smaller k.
- TEST 2016–2026, untouched. Universe B: k from A's train, no tuning.
- Base rate: pooled share of eligible line-months where the outcome occurs.
- Permutation null: per line, redraw the same number of fires at random
  eligible months with the same spacing; pool; 300 draws; p = share ≥ observed.
- Cluster check: hit rate by calendar year of fire, and excluding 2021–2022
  (the one shock that hit everything at once).
- Reliable = beats base, p ≤ 0.05, ≥ 50 scorable fires, AND still beats base
  with 2021–22 removed. Suggestive = p ≤ 0.20.

## Accepted limits

- Universe A lines share a country, currency and customs system; a yen move
  lifts all unit values together. The by-year table and Universe B exist to
  catch that.
- Survivorship: A's 138 lines were chosen on 2026 export value.
- As-revised data throughout.
