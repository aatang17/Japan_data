# Divergence detector — pre-registered spec

Written BEFORE looking at any backtest output. Any change made after seeing
results is recorded in a "post-hoc changes" section at the bottom, with why.

## Data

- Source: MOF Trade Statistics, 概況品別国別表 輸出 (exports), via e-Stat.
- Universe: level-3 and level-4 commodity lines with (a) a published quantity
  series and (b) >= JPY 20bn of exports in the last 12 months. Frozen once,
  from the latest 12 months, and applied to all history (survivorship bias
  acknowledged; see limitations).
- World value V(c,t) and quantity Q(c,t) = sum over every published partner,
  including the non-country entries. The Ministry publishes no world row.
- Period: 2001-01 to 2026-07.
- Unit value P(c,t) = V(c,t) * 1000 / Q(c,t), yen per published unit.
  Undefined where Q = 0; never zero-filled.

## Signal

For line c at month t:

    P3(c,t)  = sum V over [t-2, t] * 1000 / sum Q over [t-2, t]
    r3(c,t)  = P3(c,t) / P3(c,t-12) - 1
    v3(c,t)  = sum V over [t-2, t]   /  sum V over [t-14, t-12]   - 1
    q3(c,t)  = sum Q over [t-2, t]   /  sum Q over [t-14, t-12]   - 1

Robust score against the line's OWN history, trailing 10 years, ending 13
months before t (so the comparison window never overlaps the signal window):

    med   = median of r3(c, s) for s in [t-132, t-13]
    mad   = median(|r3(c,s) - med|) * 1.4826
    z(c,t) = (r3(c,t) - med) / max(mad, 0.02)

Variant B (FX/inflation-neutral), computed in parallel:

    x3(c,t) = r3(c,t) - median of r3(*, t) across the whole universe that month
    zx(c,t) = same robust score applied to x3

Yen unit values move with the exchange rate and with global input inflation.
Variant B asks whether a line is repricing MORE than everything else is.

## Fire rule

Fire at (c,t) when ALL hold:

1. z >= 3.0                      (break from the line's own pattern)
2. r3 >= +8%                     (economically meaningful, not just quiet)
3. v3 > 0                        (value is rising: not a volume collapse)
4. q3 >= -15%                    (volumes not cratering: rules out mix/lumpiness)
5. at least 60 months of history for the line
6. no fire for the same line in the preceding 5 months (one episode = one fire)

Variant B substitutes zx for z in (1) and x3 for r3 in (2).

## Success criteria — decided in advance

The detector is worth building if it clears ALL of:

- **Continuation.** Median unit value over [t+1, t+6] after a fire is higher
  than P(t), and the hit rate (share of fires with a higher forward path) is
  >= 60%. A detector that fires at the top is worse than nothing.
- **Alert load.** Median fires per month across the universe <= 5. More than
  that is a newsletter nobody reads.
- **Not-a-blip.** >= 50% of fires are followed by the line staying above its
  pre-fire unit value 6 months later.
- **Recall.** It fires on episodes named independently below, with a lead
  time (fire month vs the month the episode's unit value peaked) of >= 3
  months. Missing one is a finding, not a failure; missing most kills it.

## Episodes named in advance (from industry knowledge, not from the data)

| Episode | Expected line(s) | Rough window |
|---|---|---|
| MLCC / passive component shortage | 70329 capacitors | 2017 H2 – 2018 H2 |
| DRAM / NAND price super-cycle | 7032305 ICs | 2017 – mid 2018 |
| Tohoku earthquake supply shock | broad, autos/electronics | 2011 Q2 – Q4 |
| Global semiconductor shortage | ICs, discretes | 2021 – mid 2022 |
| Resin / chemicals squeeze | polyethylene, PVC, styrene | 2021 H2 – 2022 |
| Current AI buildout | ICs, capacitors, test gear, generators | 2025 H2 – |

The 2017-18 MLCC episode is the key out-of-sample test: same line, same
mechanism, a full cycle before the one that prompted this work.

## Known limitations, stated up front

- **Not point-in-time.** History is served at 確定 (final) revision. A true
  point-in-time backtest is impossible for the past — MOF publishes revision
  stages but e-Stat serves only the current one for closed blocks. Our own
  vintages start accruing the day we ingest a line. Value revisions are small;
  quantity revisions are larger, so measured lead times are optimistic by an
  unknown but probably small amount.
- **Publication lag is real and is modelled.** A month t signal is actionable
  around t + 25 days. Lead times are reported in months from the actionable
  date, not from t.
- **Survivorship.** The universe is chosen on today's export value.
- **Unit values are averages, not prices.** Mix moves them. That is what
  criteria 3, 4 and Variant B exist to control, and the residual is a
  limitation, not a bug to be fixed away.

## Deviations from spec, recorded before running

- P3 is computed as an aggregate (sum of value over the window / sum of
  quantity over the window) rather than a mean of monthly unit values. It is
  the same quantity the /trade page already shows for a 12-month window, and it
  makes r3, v3 and q3 arithmetically consistent: (1+v3)/(1+q3) = 1+r3 exactly.
  Decided before seeing any output.
