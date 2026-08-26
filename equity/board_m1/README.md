# M1 — Board composition and executive pay extraction prototype

Prototype for [PLAN-BOARD-AND-PAY.md](../../docs/plans/PLAN-BOARD-AND-PAY.md), milestone M1.
Run 2026-08-23 against the **whole local EDINET archive** (2,766 annual-report `type=5`
packages, filing dates 2026-06-01 … 2026-07-17).

Same input file as the cross-shareholding extractor — nothing new is downloaded.

## Run

```bash
../../observatory/.venv/bin/python extract.py            # whole local archive
../../observatory/.venv/bin/python extract.py --limit 300
```

Outputs to `out/`: `company.csv` · `directors.csv` · `pay_by_category.csv` · `pay_named.csv`.

## Results

| | |
| --- | --- |
| Filings parsed | 2,721 (2,499 listed, 2,277 distinct tickers) |
| **Clean among listed filers** | **2,484 / 2,499 = 99.4%** |
| Listed filings with no tagged board | 7 (0.3%) — the other 206 untagged are unlisted filers |
| Directors extracted | 25,869 (17,122 directors · 4,635 statutory auditors · 3,900 audit-committee directors) |
| Pay rows by officer category | 7,990 |
| Named individuals (連結報酬等) | 1,122 people at 455 filers |
| Filings flagged `partial` | 9 |

Sanity numbers the data produces (FY2025 filings, listed only):

- Median board 10; director mean age **62.2**, and **18.4% of directors are 70 or older**.
- Female officer ratio mean 16.9%, median 15.4%; **4.9% of boards still have no women**.
- Median pay **¥29.4m per inside director** vs **¥5.2m per outside officer**.
- Median employee average salary ¥6.85m; median gender wage gap 0.701 (women earn 70% of men).
- Top named pay: Rene Haas ¥6,139m · Stacy J Smith ¥3,808m · Christopher Willcox ¥2,560m ·
  Christophe Weber ¥2,315m · Toyoda Akio ¥2,113m. (The first three are group officers
  disclosed on a **consolidated** basis — 連結報酬等 includes pay from subsidiaries.)

## Gates

| | Gate | Result |
| --- | --- | --- |
| G1 | counted board rows ≤ filer's own 役員 headcount | 4 filings breach |
| G2 | recomputed female ratio reproduces the filed ratio | 2 filings breach |
| G3 | pay components sum to the filed category total | **disclosure flag, not a gate** — 94.1% of 7,439 rows reconcile |
| G4 | named pay ≥ ¥100m | **flag, not a gate** — 40 rows are voluntary sub-threshold disclosure |
| G5 | date of birth implies an age of 20–100 | no breaches |

## What the prototype taught us (feed into M3 design)

1. **Directors are tagged one context per person**, and the context member carries a
   **romanised name** (`…_ShinyaAkitoMember`) — 100% of 8,410 sampled contexts. English
   director names come free; no translation layer. Treat it as a display name and a
   *weak* person key: it is filer-authored, so it joins a pay row to a board row inside
   one filing but must not be used to assert two companies share a director.
2. **The ≥¥100m individual pay disclosure is tagged**, on the *same member context* as
   the director row, so named pay joins to the board seat with no name matching at all.
   188 of 1,122 named people are **not** on the board at the filing date — retired or
   subsidiary officers. That is correct, not an error.
3. **The filer's 役員 gender tally is a different population from the tagged board.** In a
   指名委員会等設置会社 the tally includes 執行役 who are not individually tagged (JPX:
   12 board rows vs 17 officers; HOYA 7 vs 8). So the invariant is board ≤ officers, and
   the female ratio can only be recomputed when the two coincide. Getting this wrong made
   10% of filings look broken.
4. **A member context with no name is a totals row**, not a person — counting contexts
   instead of names over-counted boards by one.
5. **Pay components are an open family and can be negative.** Beyond fixed/base/
   performance/bonus/non-monetary/retirement, filers invent components
   (`RestrictedShareAwards…`, `ShareAwards…`, `PerformanceLinkedShareAwards…`,
   `MonthlyRemuneration…`); ZOZO's restricted-share award is **−¥141m**, a forfeiture
   reversal, and only including it makes the row add up. Match the family by pattern, never
   a fixed list.
6. **Components do not reliably add to the total, and that is the filer's doing.** 非金銭報酬等
   is additive for some filers and an "of which" memo for others (tested both ways: 88.5%
   vs 87.2% reconcile — inconsistent either way), and components are printed rounded to
   ¥mn. The **filed category total is the published number**; components ship as filed with
   a per-row `components_reconcile` flag. Do not "fix" this by choosing a convention.
7. **Outside-director status is not derivable per person** — only 3.5% of 役職名 strings say
   社外. Inside/outside counts come from the pay table's categories instead.
8. **¥100m is a trigger, not a floor.** Takeda, Recruit, SMTG and others disclose directors
   voluntarily below it; treating that as an error flagged five blue chips as broken.
