# facility_m1 — facilities extraction prototype (主要な設備の状況)

Answers one question: **can the major-facilities table in the annual report be
parsed reliably enough to power a company-facilities map** — site name,
city-level location, per-asset-class book values, and land area (㎡)?

Verdict: **yes.** 18 filings chosen for maximum layout variance parse with
**zero row-gate failures** (208 rows verified against the filers' own 合計
columns, 0 bad) and the land totals reconcile against each filer's own balance
sheet — JR East 99%, Tobu / Keisei / SG Holdings exactly 100%, Idemitsu 98%,
Keihanshin Building 98% (after adding trust land).

```bash
../../observatory/.venv/bin/python extract.py     # writes out/facilities.json
```

## The one discovery that changes M2 planning

**The t5 CSV package is unusable for this dataset.** It flattens every text
block to plain text — `<table>` markup stripped, cell boundaries lost — so the
facilities table arrives as one unparseable run of digits. The holdings and
board extractors never hit this because their data is individually XBRL-tagged.
Anything **table-shaped inside a text block** — facilities, and equally the
planned major-customers (主要な相手先別の販売実績) and geographic-segment
(地域ごとの情報) datasets — must be read from the **t1 (full XBRL) honbun
HTML** instead. Both packages are already archived for every annual report, so
nothing new needs capturing — but M2's reader targets t1, and so should the
customer/geography extractors when they come.

## What the sample yielded

369 facility rows across 18 filings: 94% carry a location, 77% match a
prefecture/city pattern (most of the rest are overseas sites, disclosed at
country level), 301 carry a land book value and 290 a land area. Every filing
parsed; none was 該当なし.

The data is exactly the hidden-land story the map is for:

| Site | Area | Book value |
| --- | --- | --- |
| Idemitsu Australia (coal) | 202 km² | ¥3.5bn (¥17/m²) |
| Sojitz Development (Gregory, Australia) | 164 km² | ¥0.7bn (¥4/m²) |
| JR East, whole network land | 166 km² | ¥1,597bn |
| Kobe Steel, Kakogawa works | 5.0 km² | ¥18.5bn |
| JR East, Akita rolling-stock centre | 171k m² | ¥374/m² book |

## Gates

1. **Row gate** — where a table publishes a 合計 column, the asset-class cells
   must sum back to it (tolerance one rounded unit per summed column).
   Result: 208 ok / 0 bad / 170 rows in tables with no 合計 column
   (recorded, legitimately unverifiable).
2. **Balance-sheet gate** — facilities land (a "major" subset) must not exceed
   the balance sheet's tagged land (`jppfs_cor:Land` **plus** filer-extension
   `…LandInTrust…` elements), consolidated basis. 11 clean / 0 exceeds.
   6 filers are IFRS adopters that tag no consolidated JGAAP land
   (`parent_only_bs` — recorded, not comparable); ZOZO owns no land at all.

## Traps M2 must inherit

The full list lives in `extract.py`'s docstring; the load-bearing ones:

- **One facility spans several physical rows** (Toyota Boshoku: land area on a
  continuation row). Merge by where the anchor cell *originates*, or every
  such site is duplicated and its area lost.
- **面積 subcolumns**: banks/railways put land area in its own column;
  positional reading sums ㎡ into yen.
- **The same header words mean opposite things by layout** — Sojitz's
  `土地 面積(千m2)` column is areas (the sibling `土地/帳簿価額` is money);
  Toyota Boshoku's single `土地(面積m2)` column is money with area in
  parentheses. Only the sibling-column context disambiguates.
- **The land cell is a grammar** — Kobe Steel: `(13,035m2) 5,036,909m2 18,498`
  = leased-in area, owned area, book value in one cell.
- **Summary vs detail double-counting** (JR East 総括表 + per-station detail;
  SG/Keisei group summaries): per-scope, a summary table trumps detail tables;
  a summary's own 合計 row (after 消去又は全社) trumps re-summing its rows.
- **当社グループ means the group; 当社 alone means the parent.**
- **Trust assets are separate columns** (信託建物/信託土地, Keihanshin) and a
  separate balance-sheet element.
- Negative subtotal rows print negatives in parentheses — per-cell
  indistinguishable from the (annotation) convention; record, don't gate.

## Known limits (accepted for M1, to resolve in M2)

- **Scope headings are heuristic.** A filer whose only summary has no heading
  is treated as group-wide; a parent-only unlabelled summary would undercount
  the group total (conservative for the ≤ gate, wrong for display totals).
- Tobu's group land **area** is not totalled (its 総括表 合計 row carries book
  value only); detail-row areas exist but are a subset.
- Overseas locations are country/region strings — the map needs a separate
  country gazetteer for the ~23% of rows that aren't Japan-geocodable.
- Employees, building areas (総面積/賃貸面積) and the 摘要 column are parsed
  past but not yet stored.

## What M2 needs beyond this

1. Municipality gazetteer: 所在地 → standard municipal code → centroid
   (static table, ~1,900 rows; no external API).
2. DuckDB tables (`eq_facility_filings`, `eq_facilities`) in the equity DB,
   same vintage discipline as holdings.
3. ECharts geo scatter with a vendored Japan geoJSON; every dot carries book
   value vs area — the ¥/m² story — with the book-value-not-market-value
   caveat on the page.
