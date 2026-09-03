# Methodology — Facilities & Land (主要な設備の状況)

One row per facility a listed company discloses in the major-facilities section
of its annual securities report (有価証券報告書, EDINET): site name, city-level
location, per-asset-class book values, land area, employees. Extractor:
[`observatory/equity/facility_extract.py`](../observatory/equity/facility_extract.py) (parser `fac-6`);
prototype and trap catalogue: [`equity/facility_m1/`](../equity/facility_m1/).

## Source and why it is the t1 package

The section is a text block in the filing, not individually XBRL-tagged. The
CSV package (EDINET `type=5`) **flattens text blocks to plain text and destroys
the table**, so the extractor reads the t1 (full XBRL) honbun HTML — the same
documents, already archived. Balance-sheet land is a tagged numeric fact and
still comes from the t5 CSV. Every filing row stores the SHA-256 of both
packages as parsed.

## What is official and what is derived

- **Official, as filed:** every book value (normalised to yen from the table's
  stated unit), every land area (normalised to ㎡), employee counts, site
  names, addresses, the filer's own 合計 rows.
- **Derived, formula shown wherever displayed:**
  - *Book ¥ per ㎡* = land book value ÷ disclosed land area, both as filed.
  - *Map positions*: the filed city-level address is matched to its
    municipality and plotted at the municipality centroid
    ([`equity/gazetteer_municipalities.csv`](../equity/gazetteer_municipalities.csv),
    median of Geolonia Japanese-addresses points, CC BY 4.0). A position is a
    national-map location, never a parcel. An address that names no prefecture
    geocodes only if its municipality name is nationally unique — 府中市
    exists in Tokyo and Hiroshima and stays unmapped rather than coin-flipped.
- **Book value is historical cost**, not market value. No market estimate is
  made anywhere. That gap is the analytical point of the dataset, and every
  surface says so.
  - *English locations* (`location_en`): the geocoded municipality's official
    Hepburn romanization, joined on municipality code from Japan Post's
    romanized address data ([`observatory/app/gazetteer_en.csv`](../observatory/app/gazetteer_en.csv),
    KEN_ALL_ROME snapshot 2026-08-28; Hamamatsu's pre-2024 wards romanized
    manually). An English location exists exactly where a geocode exists;
    the filed Japanese address always renders alongside it.
  - *Use category* (`use`): a coarse category (production, offices, stores,
    logistics, rental real estate, R&D, rail & transport, hotels & leisure,
    housing & welfare, energy, idle) classified from the filer's own text —
    site name, 設備の内容, segment — by fixed keyword rules in
    [`observatory/app/facility_labels.py`](../observatory/app/facility_labels.py),
    first match wins. Ditto marks (〃 / 同上) inherit from the row above for
    classification only; the filed cell is returned untouched. A row matching
    no rule is unclassified (about 16% of rows) and renders `—`, never a
    guess. Categories *rental real estate*, *housing & welfare* and *idle*
    are flagged **non-core**; the flag describes the use, not a judgment on
    strategy — for a real-estate filer, rental property is core.

## Validation gates (never weakened to pass)

1. **Row gate** — where a table publishes a 合計 column, the asset-class cells
   must recompute it (tolerance one rounded unit per summed column, scaled by
   the number of physical rows merged into the record — each merged cell
   carries its own rounding). Elimination rows print negatives in
   parentheses — per-cell indistinguishable from the (annotation)
   convention — so negative-total rows are recorded, not gated.
2. **Balance-sheet gate** — land across the tables (summary 総括表 preferred
   per scope; the filer's own 合計 row preferred over re-summing) must not
   exceed consolidated balance-sheet land: `jppfs_cor:Land` plus
   filer-extension `LandInTrust` elements. "Major facilities" is a subset, so
   the test is ≤, never ==. IFRS adopters tag no consolidated JGAAP land and
   are recorded `parent_only_bs`, not failed.

Cross-company surfaces (map, screen, aggregates) use **only `clean` filings —
one per company, the latest**. `partial` filings are stored, inspectable on
the company page with a warning, and excluded from every aggregate.

## Foreign-currency tables

A filer can denominate a facilities table in a foreign currency (Tokyo Gas's
US subsidiaries file in 百万米ドル). The figures are stored and displayed
**exactly as filed, in the filed currency** — a `currency` column marks the
row, the UI shows the currency's own symbol (US$…), and no exchange rate is
ever invented. Foreign-currency amounts never join a yen total, ranking, or
gate; land areas (㎡ is ㎡ everywhere) still count. The unit gate fails only a
yen table with no detectable unit. The row-sum gate still applies within a
foreign table, in its own currency.

## Rental property at market (賃貸等不動産)

Extractor: [`observatory/equity/rental_extract.py`](../observatory/equity/rental_extract.py) (parser
`rent-1`), reading the 賃貸等不動産 note from the same t1 filings — the one
disclosure that puts a **market value** on a company's real estate. Stored
exactly as disclosed: the balance-sheet carrying amount and the year-end fair
value (時価, mostly appraisal-based; some filers self-assess from property-tax
values and say so in the note).

- **Official:** carrying amount, fair value, prior-year values, per category
  (賃貸等不動産 proper / dual-use property / a combined disclosure). Dual-use
  property (an HQ partly let out) is disclosed at the **whole property's**
  amounts — the note's convention, not ours.
- **Derived, formula shown:** unrealized gain = fair value − carrying amount;
  fair ÷ book. Negative unrealized gains (impaired property below book) are
  real and rendered with a true minus.
- **Gate:** where the note shows opening balance, movement and closing
  balance, they must roll (期首 + 増減 = 期末, tolerance 2 rounding units).
  Non-rolling or unit-less filings are `partial` and excluded from every
  cross-company surface. A note stating the disclosure is omitted for
  immateriality is `immaterial`, not a failure.
- **Coverage caveat:** IFRS adopters disclose investment property in IFRS
  notes this extractor does not read — they are absent, not zero. `no_note`
  mixes them with companies that simply have no material rental property.

## Known limitations

- "Major" is the filer's judgment; totals are a floor, not a register.
- ~11% of filings are `partial` under parser `fac-6`; ~2% have a facilities
  section that yields no parseable asset table. The large real-estate filers
  (Mitsui Fudosan, Mitsubishi Estate, Sumitomo Realty) reconcile as of
  `fac-6`. Some remaining partials are filer-side anomalies the row gate
  catches honestly (a printed 合計 that does not equal its own parts).
- Overseas facilities are disclosed at country level and are not on the Japan
  map.
- Municipality centroids move only if the gazetteer snapshot is rebuilt; the
  snapshot date is recorded in the file header.

## Attribution

Company filings via EDINET (Financial Services Agency). Coordinates derived
from [Geolonia Japanese-addresses](https://github.com/geolonia/japanese-addresses)
(CC BY 4.0) — credit required wherever the coordinates are displayed. English
municipality names from Japan Post's romanized zipcode data (free to use, no
attribution required; credited in the file header regardless).
