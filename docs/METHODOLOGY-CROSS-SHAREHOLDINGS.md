# Methodology — Japanese Cross-Shareholdings Database

**Dataset:** policy shareholdings (政策保有株式) disclosed in Japanese annual
securities reports.
**Coverage as built:** 21,099 filings parsed (21,076 published) · 204,465
disclosed positions · 4,227 filers · published fiscal periods ending
**2021-02-28 → 2026-05-31**.
**Parser version:** `m6-0`. **Status:** published database is `m5-2`;
`m6-0` pending re-extraction.

> **Pending re-extraction.** `m6-0` adds the filing's own policy-bucket totals
> and the balance-sheet denominators (§4.8–4.9, §8.7). The parser and the API
> serve them, and they are verified against the FY2026 filings held locally,
> but the published database is still `m5-2` until the full archive is
> re-extracted from the cloud bucket. Until that run, `eq_filing_totals` is
> empty and every balance-sheet ratio is null — shown as `—`, never as zero,
> and the strip that carries them is absent rather than blank. Everything
> `m5-2` produces is unaffected.

This document states exactly how the numbers are produced, what they mean, and
where they are wrong. It is written so that a figure taken from this database
can be defended in a client note or a referee report. If something here is
unclear or appears contradicted by the data, treat that as a defect and report
it — the credibility of the dataset is the product.

---

## 1. Scope and source

| | |
| --- | --- |
| Source | EDINET (電子開示システム), Financial Services Agency of Japan |
| Document type | **120** — 有価証券報告書 (annual securities report), the XBRL/CSV package |
| Section extracted | 株式の保有状況 — specified investment equity securities (特定投資株式) |
| Filers | every filer with an archived annual report; no sector restriction |
| Frequency | annual, per filer, on that filer's own fiscal year-end |

**Not included, deliberately:**

- **Correction filings (訂正有価証券報告書, type 130).** Only the original annual
  report is parsed. A correction is a *later* document, not an amendment to the
  stored one, and folding it in silently would violate the immutability rule in
  §3. Corrections are captured in the raw archive and are a planned addition as
  a separate vintage, not a rewrite.
- **Semi-annual and quarterly reports.** Policy holdings are an annual
  disclosure.
- **みなし保有株式 (deemed holdings)** — shares over which the filer holds voting
  or disposal instruction rights, typically through a retirement benefit trust.
  They are disclosed in a separate table and are **excluded** (see §4.3). They
  are economically distinct from owned shares and mixing them double-counts.
- **Non-specified investment shares (純投資目的)** — held for pure investment
  return, disclosed only in aggregate, not named. **Holdings the filer *moved*
  into this category are the exception: those are named, and are captured — see
  §4.5.**

---

## 2. Definitions

- **政策保有株式 / policy shareholding** — equity held for reasons other than
  pure investment return: to support a business relationship, a financing
  relationship, or a group tie. Japan's Corporate Governance Code requires the
  filer to disclose these holdings individually, state the purpose of each, and
  have its board verify annually that each earns its cost of capital.
- **Named position** — one disclosed line: an issuer name, a share count, a
  book value, a stated purpose, and a reciprocity flag. The unit of this
  database is the position, not the company.
- **Holder table** — filings present the disclosure in up to three tables
  depending on group structure. All three are extracted and tagged in
  `holder_table`:

  | `holder_table` | Meaning | Positions |
  | --- | --- | ---: |
  | `reporting` | the reporting company itself | 182,441 |
  | `largest` | the largest share-holding subsidiary | 19,003 |
  | `second_largest` | the second-largest such subsidiary | 2,958 |

  They are **not** aggregated automatically: the same issuer may appear in more
  than one table for one filer, and summing across tables without intent
  double-counts a relationship.
- **Reciprocity (`reciprocal`)** — the filer's own as-filed answer to whether
  the issuer also holds the filer's shares: `有` (yes) or `無` (no), stored
  verbatim including any footnote marker the filer appended (e.g. `無(注)２`).
  Consumers must match on prefix, not equality.
- **Vintage** — one accepted capture of one source file. A stored vintage is
  never edited; a revision becomes a new vintage.

---

## 3. Capture — the raw archive

Extraction is deliberately separated from capture. **Capture ≠ parse.**

1. Every filing is downloaded from the EDINET API and **archived before it is
   parsed**, so evidence is retained even for files that fail extraction.
2. Each archived object is stored with its **SHA-256**, its byte length, and the
   date it was published.
3. The archive is **append-only and immutable**. Nothing is back-filled,
   corrected, or overwritten. This is a commercial property, not housekeeping:
   EDINET's list API reaches back roughly five years and deletes filings ten
   years after filing, so an archive that starts today can never be extended
   backwards.
4. Extraction can therefore be improved and re-run against filings already
   captured, without re-fetching and without any dependence on the source
   still being available.

**Provenance guarantee.** The `sha256` recorded against each filing is computed
from **the bytes the parser actually read**, not copied from a manifest entry.
Any published figure can be traced to a specific archived file and that file
re-hashed to confirm it is the one parsed.

---

## 4. Extraction

### 4.1 Input format

The CSV package (EDINET `type=5`) is a UTF-16, tab-separated export of the
filing's XBRL. Each row carries an element ID, a context reference, a period
label, a unit and a value. Extraction targets the element families for
specified investment equity securities and reads the value out of the tagged
data — **no text parsing, no PDF scraping, no heuristics on layout.**

### 4.2 Fields read

| Field | Element family (local name prefix) |
| --- | --- |
| issuer name | `NameOfSecurities…` |
| share count | `NumberOfSharesHeld…` |
| book value (¥) | `BookValue…` |
| stated purpose | `PurposeOfShareholding…` |
| reciprocity | `WhetherIssuer…` |

Holder-table variant is determined from the element name
(`ReportingCompany` / `LargestHoldingCompany` / `SecondLargestHoldingCompany`).

### 4.3 Current versus prior year, and the deemed-table trap

Each disclosed position appears twice in the XBRL: once in a
`CurrentYearInstant…` context and once in a `Prior1YearInstant…` context, both
keyed to the same `Row<N>Member`. The current-year row is the position; the
prior-year row supplies `prior_shares` and `prior_book_value_yen`.

**The deemed-holdings table reuses the same `Row<N>Member` context references.**
Read naively, its values silently overwrite the owned-share values for the same
row number. Extraction therefore excludes any element whose local name contains
`Deemed`. This defect produced wrong values that looked entirely plausible and
was caught only by the reconciliation gate in §6 — it is the single most
important trap in this dataset.

### 4.4 Missing values

A blank cell is **missing, never zero**. Missing values are stored as `NULL`,
exported as empty, and rendered as `—`. A position with no prior-year column
(a newly disclosed holding) is not treated as an increase from zero.

---

### 4.5 Purpose changes — the reclassification table

A filer may keep a holding but stop calling it a policy shareholding, moving it
to 純投資目的 (pure investment). **The position then disappears from the named
table with no transaction behind it.** Measured on named holdings alone, that is
indistinguishable from a sale, and it is not one: the shares are still owned.

Filings disclose the move in a table of their own —
保有目的を変更した投資株式 — and it is fully tagged. Extraction reads it into
`eq_reclassified`, in both directions:

| `direction` | Meaning |
| --- | --- |
| `to_pure` | policy shareholding → 純投資目的; the holding leaves the named table |
| `to_policy` | 純投資目的 → policy shareholding; the reverse |

Each row carries the issuer name, the share count and book value the filer
reports for it, **the fiscal year the filer states the change took effect**
(`fy_of_change_ja`, verbatim — some filers list more than one), and the filer's
own stated reason (`reason_ja`).

Three properties matter when using this table:

1. **It is a standing disclosure, not a one-year flow.** A filing repeats these
   rows for several years after the change, so an `fy_of_change_ja` earlier than
   the filing's own period end is normal and expected. Summing across filings of
   different years double counts.
2. **These row contexts collide with the named table's.** The reclassification
   table reuses the same `Row<N>Member` context references as the holdings
   table — the same trap as deemed holdings in §4.3. It is keyed and stored
   separately and is never merged into the named positions.
3. **It is not the same measure as a sale.** The filing separately tags how many
   issues increased and decreased during the year and the yen involved —
   acquisition cost for increases, **sale proceeds** for decreases. Extraction
   stores these in `eq_filing_flows`. Read against the reclassification table
   they separate what was actually sold from what merely changed category.

On the archive as extracted for FY2026, 195 filers disclose 976 holdings moved
to pure investment. Reported alongside the same filings' sale proceeds, the two
are frequently an order of magnitude apart.

### 4.6 Table footnotes

The named table's own numbered footnotes (`FootnotesSpecifiedInvestmentShares…`)
are captured verbatim into `eq_filing_notes`. This is where filers explain a
share count that moved without a trade — a split, a consolidation, a merger.

**The `Row<N>Member` number here numbers the footnote, not the holding**: these
are (注)1, (注)2, … and the XBRL carries no link back to a row. A note is
therefore tied to a position only where it names that issuer, and that link is
derived, not filed. `FootnotesDeemedHoldings…` is a different table and is
excluded.

### 4.7 Issued and treasury shares

Each filing's own issued share count at its fiscal year end
(`NumberOfIssuedSharesAsOfFiscalYearEnd…`, ordinary-share context preferred over
the all-classes total) and treasury share count are stored on `eq_filings`.
They are not needed to describe the filer — they are needed because most issuers
of policy holdings are themselves filers, which makes this archive its own
source of denominators (§8.5). `share_classes` records how many share-class
contexts the filing tagged.

### 4.8 The filing's own policy total

The named table lists only a filer's largest holdings, so the sum of the named
rows is **not** the filer's policy total. Every filing also tags the total
carrying amount and the number of issues for the *whole* policy bucket, listed
and unlisted, and those totals are stored in `eq_filing_totals` at the finest
grain the filing carries: one row per **disclosing entity × share class**.

How far the named rows fall short varies by filer. Measured against the tagged
totals for seven large financial groups:

| Filer | Named rows | Tagged total | Named share |
| --- | ---: | ---: | ---: |
| Dai-ichi Life | ¥286.2bn | ¥290.4bn | 98.5% |
| MS&AD | ¥2,987.6bn | ¥3,183.5bn | 93.8% |
| Sompo | ¥1,434.4bn | ¥1,545.5bn | 92.8% |
| Tokio Marine | ¥1,795.6bn | ¥1,964.3bn | 91.4% |
| SMFG | ¥2,724.1bn | ¥4,021.6bn | 67.7% |
| MUFG | ¥2,671.4bn | ¥4,111.3bn | 65.0% |
| Mizuho | ¥1,873.3bn | ¥3,375.6bn | 55.5% |
| **All seven** | **¥13,772.6bn** | **¥18,492.2bn** | **74.5%** |

Anything expressed as a share of the filer's own balance sheet therefore uses
the tagged total, never the named sum.

**Entities are summed, not maxed.** A filing discloses for the filer itself
(`reporting`) and, where the group's biggest holder is a different company, for
that company (`largest`) and sometimes a second (`second_largest`). These are
separate legal entities inside the same consolidated balance sheet, so their
totals add. For 94% of filers only one entity is disclosed and the distinction
is moot; for the rest it is large — MS&AD reads 42% of equity on the largest
entity alone and 66% on the sum.

The result is a **floor**. A filing names at most those entities, so holdings
at other group companies are disclosed nowhere and are not counted.

The issue-count elements also exist for the 純投資目的 bucket, so the purpose
guard is load-bearing when reading them; the carrying-amount elements do not
(checked: no pure-investment carrying amounts in 523 annual reports), which is
why the §6 reconciliation gate is unaffected by it.

### 4.9 Shareholders' equity and total assets

Both are read from the filing's own 主要な経営指標等の推移 table and stored on
`eq_filings` as `equity_yen` / `total_assets_yen`, each with the basis actually
used. They are present in every annual report: over 2,460 filings, coverage is
100%, and every filer that discloses a policy total also discloses both.

Filers report under Japanese, IFRS or US accounting standards, and each tags
equity under a different element name. **The trap is that an IFRS or US-GAAP
adopter stops tagging the Japanese consolidated figure for the current year but
leaves the prior years in place** — the element is present and merely stale. A
naive read falls through to the parent-only figure, which for a holding company
is a near-empty shell: read that way, Sompo shows 90% of equity in policy
shares against a true 30%, because the shareholdings sit in the operating
subsidiary while the equity read was the holding company's own.

Resolution is therefore ordered, and the rung used is recorded in
`equity_basis` and displayed:

| Order | Element | `equity_basis` | Share of filings |
| --- | --- | --- | ---: |
| 1 | `NetAssetsSummaryOfBusinessResults` @ `CurrentYearInstant` | `jgaap_consolidated` | 100% tag it |
| 2 | `TotalEquityIFRS…` | `ifrs_consolidated` | 0.2% |
| 3 | `EquityAttributableToOwnersOfParentIFRS…` | `ifrs_consolidated_excl_nci` | 7.8% |
| 4 | `EquityIncludingPortionAttributableToNonControllingInterestUSGAAP…` | `usgaap_consolidated` | 0.1% |
| 5 | `EquityAttributableToOwnersOfParentUSGAAP…` | `usgaap_consolidated_excl_nci` | 0.3% |
| 6 | `NetAssetsSummaryOfBusinessResults` @ `CurrentYearInstant_NonConsolidatedMember` | `parent_only` | fallback |

Total assets follow the same ladder (`assets_basis`). A parent-only denominator
is a different measure from a group one and is labelled as such — the two are
never silently mixed.

**Element names are matched without their namespace, and this is load-bearing.**
Ajinomoto tags `TotalEquityIFRS…` in a filer-specific extension namespace
(`jpcrp030000-asr_E00436-000`) rather than a standard taxonomy prefix. Matching
on the qualified name would have missed it and dropped that filing to the
parent-only rung — ¥332bn instead of ¥844bn, a ratio overstated 2.5×.

## 5. Entity resolution

Issuer names are written free-form by the filer and must be matched to the
EDINET code list to make the data joinable.

Normalisation applied before matching:

1. HTML entity unescaping (filings carry `&amp;` and similar).
2. Unicode NFKC normalisation; removal of ASCII and ideographic spaces.
3. Removal of footnote markers filers append to names — `（注）３`, `(※5)`,
   `（注４）` and similar.
4. Kyūjitai → shinjitai character folding (會→会, 國→国, 髙→高, …).
5. A small hand-curated alias map for companies that renamed between the filing
   date and the current registry (a filer's name is frozen at its fiscal
   year-end; the registry is current).

The normalised name is then matched against the registry in **three tiers,
strongest first**, and a tier is used only where it resolves to exactly one
company:

| Tier | Key | Purpose |
| --- | --- | --- |
| 1 | the full normalised name | exact identity |
| 2 | the name less its legal form (株式会社, ㈱) | filers write the form in any position, and it never distinguishes two companies |
| 3 | the name less ホールディングス and グループ本社 as well | catches a filer naming the operating company where the registry lists the holding company, and vice versa |

**Tier 3 is a last resort, and that ordering matters.** ホールディングス does
distinguish companies: ヤマトホールディングス (9064, ~360mn shares, logistics)
and 株式会社ヤマト (1967, ~27mn shares, construction) are unrelated, and
collapsing both to ヤマト let registry order decide which one a holding pointed
at. Because the ownership percentage divides by *the matched company's* share
count (§8.5), a wrong match published a wrong stake — Toyota's holding in Yamato
Holdings read 25.7% instead of 1.8%. Matching now prefers the stronger key, so
ヤマトホールディングス resolves at tier 2 and never reaches tier 3.

Where a tier's key still names more than one registry row:

- A company that re-registers leaves behind a bare row with no listing status
  that never files; those are dropped.
- Where two registrations are the same company covering different years —
  ＪＳＲ株式会社 filed under E01003 through FY2024 and E39283 after — the one
  that actually filed over the holding's period is chosen.
- Where two **different** listed companies share a name — 株式会社アルファ is
  both 3434 (metal products) and 4760 (services); 株式会社バッファロー is both
  6676 and 3352 — no name-based rule can choose, and the position is left
  `unmatched` rather than assigned by registry order. This affects 47 positions.

**Match status is recorded on every row and never guessed:**

| `match_status` | Meaning | Rows | Share |
| --- | --- | ---: | ---: |
| `matched` | resolved to an EDINET code, and a securities code where listed | 191,882 | 93.8% |
| `unmatched` | domestic name that did not resolve | 10,197 | 5.0% |
| `foreign` | non-Japanese issuer, outside the domestic registry | 2,386 | 1.2% |

**Domestic match rate: 191,882 / 202,079 = 95.0%.**

Unmatched rows retain their full as-filed name, share count and book value —
they are complete for aggregate purposes and merely not joinable by code.
Aggregates over *positions* and *yen* include them; network and
"who-holds-whom" views necessarily do not, and any such view should state that.
The alias map is hand-curated and does not scale; a systematic rename feed
keyed on securities codes is the known fix.

### 5.1 English company names

A filing names its *holdings* in Japanese only, but every 有価証券報告書 states
the **filer's own English name on its cover page** (`jpcrp_cor:CompanyNameInEnglishCoverPage`,
【英訳名】). That is the English name used throughout: **as filed**, from the
same archived package under the same SHA-256 as every figure beside it — not a
translation, and not machine-generated.

EDINET's filer registry also carries an English name (`EdinetcodeDlInfo`, field
提出者名（英字）), but leaves it blank for roughly one listed filer in ten —
Murata Manufacturing (E01914) among them, which is why an English search for
"Murata" once returned nothing while 232 filings named it as a holding. The
registry is therefore only the fallback, for a company that files no annual
report of its own.

Coverage, on the archive as extracted:

| Population | With an English name | Share |
| --- | ---: | ---: |
| Filers with a securities code | 4,226 / 4,226 | 100% |
| Named positions resolved to an EDINET code | 191,331 / 191,869 | 99.7% |
| Named positions (all rows) | 191,331 / 204,402 | 93.6% |
| Filers whose own filing states one | 4,567 / 4,575 | 99.8% |

The gap in the all-rows figure is the `unmatched` and `foreign` positions
(§5) — names that resolve to no company, so there is nothing to look up. Most
foreign names are already written in Latin script in the filing.

The stated value needs three corrections, all applied identically by the
extractor and the backfill so a re-extracted row can never disagree with a
backfilled one:

1. **HTML entities** are unescaped — filings carry `ISEKI&amp;CO., LTD.`
2. **Japanese annotation is cut** — filers append a former English name or a
   rename note to the field (`NANKAI Co.,Ltd.（旧英訳名　Nankai Electric Railway
   Co.,Ltd.）（注）…`). Everything from the first kana or ideograph is dropped.
   Two characters are deliberately *not* treated as Japanese, because filers
   write them inside the name itself: the full-width space
   (`ＴＨＥ　ＳＨＩＧＡ　ＢＡＮＫ，ＬＴＤ．`) and the middle dot
   (`ＧＯＬＦ・ＤＯ`, `Ａｉ・Ｐａｒｔｎｅｒｓ`). Cutting on those truncated
   names to `ＴＨＥ` and `ＧＯＬＦ`.
3. **Dash placeholders are missing, not names** — a filer that states no
   English name sometimes writes `――――` rather than leaving the field empty.

Full-width Latin is preserved exactly as the filer wrote it; it is the name as
filed. Where no English name exists anywhere, the as-filed Japanese name is
shown alone — never a blank, never a guess — and the Japanese name is always
carried alongside the English one, on screen and in every export.

Sectors are recorded by EDINET in Japanese only. The site shows the standard
English name of the TSE sector (JPX's own English labels for the 33-sector
classification), with the recorded Japanese available on hover; a value outside
that fixed list is shown in Japanese as recorded. That is a lookup against a
closed enumeration, never a translation of free text — and the *stated purpose*
of each holding, which is free-form Japanese, is published exactly as filed and
never translated.

Search matches the securities code, the as-filed Japanese name and the English
name; English matching is case-insensitive.

---

## 6. Validation and per-filing status

Every filing carries an extraction status, disclosed per filing and surfaced in
the API. Gaps are disclosed, never filled.

**The reconciliation gate.** Filings tag their own total carrying amount of
listed policy holdings for the current period (`当期末`). For each holder table,
the sum of the named positions extracted must not exceed that filing's own
tagged total. A breach means extraction has picked up rows it should not have
— for example the deemed-holdings collision in §4.3.

| Status | Meaning | Filings |
| --- | --- | ---: |
| `clean` | parsed; named sums reconcile against the filing's own totals | 20,765 |
| `partial` | parsed, but a named sum exceeds the filing's tagged total; figures published with the status disclosed | 296 |
| `failed` | the expected XBRL statement was not present in the package; nothing published for that filing | 23 |

**Known asymmetry — read this before using a single-company series.** The gate
detects *over*-extraction. It cannot detect *under*-extraction: a filing whose
table was only partly read still reconciles, because a smaller sum is still
less than the tagged total. Two filings are known to be affected —
**SMFG FY2025** (`S100W0S7`, 59 → 10 → 60 positions across adjacent years) and
**Retail Partners FY2024** (`S100THMG`, 12 → 2 → 12). Detected by screening for
a position count below half of both adjacent years: **2 of 21,061** parsed
filings, 0.01%. Market-wide aggregates are unaffected; a single-company series
should be eyeballed for an implausible one-year dip before it is published.

---

## 7. Trust labels

| Class | What it covers | Label |
| --- | --- | --- |
| **Official** | share counts, book values, stated purposes, reciprocity flags, issuer names, fiscal period, filing date; reclassified holdings with their fiscal year of change and stated reason; table footnotes; the filing's own increased/decreased issue counts, acquisition costs and sale proceeds; issued and treasury share counts | exactly as filed; never recomputed |
| **Derived** | year-on-year deltas, cut/added counts, sector and market aggregates, matched-panel indices, ownership percentages (§8.5), corporate-action flags and share ratios (§8.6), the note-to-position link (§4.6) | carries its formula, not a badge |
| **Official** | English company names (§5.1) | as stated on the filer's own cover page |
| **Registry lookup** | English name of a company that files no annual report; sector (§5.1) | attached from the EDINET filer registry / the fixed TSE sector list, not from the filing |

Nothing in this database is modelled, imputed, estimated or interpolated. There
are no nowcasts and no gap-filling.

---

## 8. How to query it correctly

Two properties of Japanese annual reporting make naive queries wrong. Both are
handled in the API; anyone querying the tables directly must handle them.

### 8.1 A cross-section must use ONE filing per company

The database holds five fiscal years. Summing book value across all filings a
company has ever made overstates the total several-fold, and a "who holds this
company" list would repeat each holder once per year.

Every cross-sectional surface therefore runs against **one filing per company**
— its latest, or the one covering a requested fiscal year.

Because Japanese fiscal year-ends are staggered, and because a company that
delists or merges simply stops filing, a "latest filing" cross-section mixes
reference periods. That composition is published alongside the figures rather
than hidden behind a single as-of date.

### 8.2 A trend must use a matched panel

Coverage is not uniform across fiscal years:

| Fiscal year | Filings |
| --- | ---: |
| FY2021 | 1,277 *(partial — archive window opens)* |
| FY2022 | 4,253 |
| FY2023 | 4,281 |
| FY2024 | 4,270 |
| FY2025 | 4,228 |
| FY2026 | 2,752 *(partial — archive window closes; later year-ends not yet filed)* |

A raw year-on-year comparison across the endpoints measures the archive window,
not corporate behaviour. **Restrict to filers present in both endpoint years**
and the comparison is of the same companies to themselves.

### 8.3 Count positions, not yen, to measure behaviour

Book values are **fair-valued at fiscal year-end**. A company that sells nothing
shows a rising book value in a rising market. Position counts measure decisions;
yen measures the market. Both are published; they answer different questions.

### 8.4 Share-count increases are usually not purchases

A stock split multiplies the share count with no transaction. Verified examples
carry ratios of exactly **3.00** and **5.00**, on rows the filers themselves
footnote. Consequently:

- an "increased" count over-states buying;
- **most positions do not move at all** — 25,587 of 33,149 comparable positions
  in the current cross-section are unchanged;
- surfaces publish unchanged and not-comparable counts alongside cut and added,
  because cut-versus-added alone reads as market-wide accumulation, which is the
  opposite of what the filings say.

---

### 8.5 Ownership percentage — the denominator comes from the issuer

There is no price feed in this product and there does not need to be one: **for
a single-class listed stock, a stake's share of market capitalisation is its
share of shares outstanding.** Both would be the same ratio, because the book
value in the filing is itself fair value at the same date.

The denominator therefore comes from the issuer's own annual report:

```
pct_outstanding = shares held ÷ (issuer's issued shares − treasury shares) × 100
```

Both inputs are as filed (§4.7); the percentage is derived and carries this
formula wherever it appears.

**Choosing the denominator's date.** The holder reports its stake at its own
fiscal year end; the issuer reports its share count at the issuer's. The two
rarely coincide, so we take the issuer report **nearest** the holding's fiscal
year end, on either side of it, because nearest-in-time is the best estimate of
the share base the stake was measured against — an issuer report three months
later describes it better than one nine months earlier. A tie goes to the
earlier report. The date used is always published as `pct_basis_period_end`,
and it may fall *after* the holding's own year end.

**Where the share base cannot be pinned down, no percentage is published.**
This is the important guarantee, and it exists because the failure is silent:
after a stock split the holder's share count is post-split while an older
issuer report is pre-split, and the stake reads high by the whole split ratio.
Hulic's stake in Fuyo General Lease is 13.9%; measured against a pre-split
denominator it reads 41.8%. Two tests suppress the number rather than publish a
distorted one, and `pct_unavailable` says which fired:

| Test | What it catches |
| --- | --- |
| The issuer's share count moves by ≥1.5× between the reports bracketing the holding's date, and the denominator is not measured on that exact date | A split or large issue somewhere inside the window, with nothing to place the holding on one side of it |
| The **position's** own share count multiplies by ≥1.5× year on year while the issuer's does not | A split the issuer has not filed for yet — the holder restates onto the new share base a year before the issuer's next annual report reaches us |

Where the position and the issuer's share count move **together**, they agree,
and the percentage publishes normally — that agreement is what lets a post-split
stake like Hulic's be reported rather than withheld.

Four further things to know before quoting it:

- It is **null where the issuer files no annual report in this archive**, never
  zero.
- **A result above 100% is never published.** It cannot be a stake in any
  company; it means the denominator belongs to a different share base, and it is
  a fault to report rather than a number to print.
- Where the issuer has more than one share class (`pct_share_classes > 1`) it is
  less exact, because treasury shares are reported across all classes while the
  numerator and the issued-share count are ordinary shares.
- **Do not total the column.** Holders are not aggregated: the same group may
  file more than one holder table (§2), and summing double counts.

> **Correction, August 2026.** Before this revision the denominator was the
> issuer's most recent report *at or before* the holding's date, with no test on
> the share base. Percentages distorted by splits were published as if sound,
> and results above 100% were published at all. Separately, the issuer a
> position resolved to was matched on a key that stripped ホールディングス, so
> ヤマトホールディングス (9064) and 株式会社ヤマト (1967) — unrelated companies —
> shared one key: Toyota's 5,748,133-share holding in Yamato Holdings was
> measured against the smaller company's share count and published as 25.7%
> rather than 1.8%. Both are fixed; see §5 for the matcher and the note there on
> names that remain genuinely undecidable.

### 8.6 A share count that moved is not necessarily a trade

Two derived flags travel with each named position, both of them pointers to what
the filing itself says rather than claims of their own:

- **`corporate_actions`** — keyword match over the row's stated purpose and the
  table's footnotes for 株式分割、株式併合、株式交換、株式移転、会社分割、合併、
  持株会社、商号変更、公開買付、上場廃止. The filed text is always carried with
  the flag so it can be checked.
- **`share_ratio`** — current shares ÷ prior shares where that ratio is an exact
  whole number, or its exact reciprocal. Verified examples carry ratios of
  exactly 2.00, 3.00 and 5.00 on rows the filers themselves footnote (§8.4).

Neither is a substitute for reading the footnote; both exist so that a reader
scanning a column of share counts is not misled by one.

### 8.7 Sizing a policy book against the filer's own balance sheet

Two different questions get confused here, and they use different denominators.

**Relative to the issuer** — "how much of Toyota does this bank own?" — is
§8.5: shares held ÷ issuer's shares outstanding. For a single-class listed
stock that *is* the stake's share of market capitalisation.

**Relative to the holder** — "how much of this bank's own balance sheet is
tied up in policy holdings?" — is this section:

```
pct_of_equity = total policy shareholdings ÷ shareholders' equity × 100
pct_of_assets = total policy shareholdings ÷ total assets × 100
```

Both figures are as filed in the same annual report; the ratio is calculated
and carries its formula. Use `eq_filing_totals` for the numerator (§4.8), never
the sum of `eq_holdings` — and sum across `holder_table`, do not take the
largest. Guard the denominator on `> 0`: equity can be filed negative, and a
percentage of negative equity is not a reading.

Read `equity_basis` before comparing two filers. A `parent_only` denominator is
not comparable with a consolidated one, and the two `_excl_nci` bases exclude
non-controlling interests where the Japanese standard includes them, so a
group with large minority stakes reads slightly high against them.

Why this ratio matters commercially: ISS's Japan proxy voting guidelines
recommend a vote against the top executive at a company that allocates 20% or
more of its net assets to cross-shareholdings, a policy effective February
2022, and ISS counts unilateral as well as mutual holdings. The database states
the level; it does not render a verdict on a company.

There is no equivalent ratio against the *holder's own market capitalisation*.
That needs a price feed, which this product does not have.

**The same reading for a single position.** `pct_of_holder_equity` and
`pct_of_holder_assets` on each row of `/company` apply the identical
denominators to one holding rather than the whole book — how much of a
company's own capital sits in one name:

```
pct_of_holder_equity = that position's book value ÷ the holder's equity × 100
```

It is the mirror of the ownership percentage in §8.5, and the pair answers the
two different questions people conflate: *how much of the issuer do they own*
(§8.5) versus *how much of themselves have they committed to it* (here). In the
reverse "who holds it" direction each row uses **that holder's** own balance
sheet, so the denominator changes down the column and `holder_equity_basis` must
be read before comparing two rows.

Distribution across 188,896 positions with both figures: median **0.11%** of the
holder's equity, 90th percentile 1.21%, 99th 7.43%, 99.9th 25.9%.

**No ceiling is applied, deliberately.** A position can exceed 100% of its
holder's book equity, and the cases that do are among the most interesting in
the dataset — Megachips' SiTime stake is 102% of its equity, Iwatsuka Seika's
Want Want China holding 82%. Clamping or suppressing those would hide the
signal. Sixteen positions exceed 100%; some are genuine and some are filer
scale errors, and the `implausible` flag (§6) catches only those whose per-share
book value is impossible, so it does not separate the two completely. The share
count and book value are returned alongside so an extreme value can be checked
against the filing.

### 8.8 Measurement basis — why our figure and a published one differ

Every yen figure in this dataset is on one convention, and until it was stated
it was invisible:

| Field | Value here | Read from |
| --- | --- | --- |
| `measurement` | `carrying_amount` | constant — balance-sheet carrying amount |
| `entity_scope` | varies | **`holder_table`** |
| `share_scope` | varies | **`share_class`** |
| `trust_included` | `unknown` | never guessed |
| `as_of` | fiscal year end | `eq_filings.period_end` |
| `period_type` | `annual` | the table exists only in the annual report |

The basis is **derived at serialization, not stored.** Two of the six fields
were already in the schema and are not constant, which is why they must be read
rather than assumed:

- `entity_scope` comes from `holder_table` — `reporting` → `parent_only`,
  `largest` → `largest_holding_company`, `second_largest` →
  `second_largest_holding_company`. A figure spanning more than one is
  `holdco_consolidated`. **SMFG discloses ¥3.458tn of listed policy shares
  under SMBC and ¥153.8bn at the holding company itself** (2026-03-31): a
  figure quoted for one entity is not the group figure, and this is precisely
  the axis a bank group uses when it reports reduction progress at commercial-
  bank level. Backfilling every row as `holdco_consolidated` would have written
  a falsehood into the field that exists to prevent them.
- `share_scope` comes from `share_class`. Only a figure summed across both is
  `both`, and reduction targets are usually listed-only.

Because nothing is stored, there is no backfill and no stored release is
written to — the vintage rule (§11) is untouched. `app/basis.py` is the source
of truth; `eq_basis_labels` and the view `v_holdings_basis` are projections of
it for SQL, and the API reads neither, so a database an extract has not yet
touched still serves a correct basis.

**The reconciliation that motivated this.** Nikkei Asia reported the three
megabanks holding **¥2.56tn** of cross-shareholdings at 2025-09-30, "down 60%
from a decade earlier by book value". This dataset returns **¥11.5085tn** for
the same three at 2026-03-31 (MUFG ¥4.111tn, SMFG ¥4.022tn, Mizuho ¥3.376tn;
documents `S100YJQO`, `S100YERK`, `S100YF8Y`). Both are correct. They differ on
measurement (acquisition cost vs carrying amount — under JGAAP listed equities
are carried at market with the valuation difference in OCI, so the two diverge
enormously on positions bought decades ago) and on date (interim vs annual).
A 4.5× discrepancy with no explanation is worse than no answer.

The same trap on flows: that article cites ¥160bn of book-value reduction at
end-September, while `flows` reports ¥1.48tn of listed sale proceeds for the
full year to March 2026. **This product holds no book-value-reduction measure
at all.** Sale proceeds are cash received on disposals over a fiscal year, as
filed. The two are different measures and are never presented as equivalent.

**`/api/v1/equity/claim-check`** (MCP tool `check_claim`) does this
reconciliation. Its one design rule: it **never infers the claim's basis from
the claim's wording.** The caller states the basis in `claimed_*` arguments, or
the answer says the gap cannot be classified — `context` is echoed for the
record and never parsed. A match is tested at the claim's own precision (¥2.56tn
is three significant figures), not against an arbitrary tolerance. Verdicts
(`consistent`, `cannot_verify`, with reasons `date_mismatch`, `basis_mismatch`,
`scope_mismatch`, `measure_not_held`, `basis_not_supplied`, `coverage_gap`)
describe what this dataset can corroborate. **No verdict asserts that a
published figure is wrong**, and none may be reported as if it did.

## 9. Known limitations

1. **Correction filings are not folded in** (§1).
2. **Under-extraction is not detectable by the gate** (§6); 2 known filings.
3. **Entity matching is 95%** of domestic names; the alias map is hand-curated
   and does not scale (§5).
4. **Deemed holdings are excluded**, so this is not a measure of total voting
   influence (§1).
5. **Only named positions are captured *individually*.** Filers disclose
   issue by issue only their significant holdings; the tail is disclosed in
   aggregate. The aggregate *is* captured, in `eq_filing_totals` (§4.8), so a
   filer's policy total is known — but the tail cannot be attributed to
   issuers, so every per-issuer view is of named holdings only, and the
   disclosure threshold varies by filer.
6. **Coverage is partial at both ends of the window** (§8.2).
7. **Book values are fair-valued, not cost** (§8.3).
8. **This is not a shareholder register.** It shows only holders that file an
   annual report and disclose the position as a policy holding.
9. **Reclassifications are only as complete as the disclosure.** The table
   captures what filers report under 保有目的を変更した投資株式. A filer that
   moved a holding and did not disclose it is invisible here, and the table says
   nothing about whether the shares were subsequently sold.
10. **The filing's own issue counts are not corrected.** `eq_filing_flows` is
    stored exactly as tagged, and at least one filer in the FY2026 archive tags
    an impossible value (1,000,000 issues decreased against 9 listed issues
    held). Per-filer figures are shown as filed; no market-wide sum of issue
    counts is published for this reason. Yen figures are unaffected.
11. **Ownership percentages depend on issuer coverage** and on no share split
    falling between the two fiscal year ends (§8.5).
12. **A policy total is a floor, not a group total** (§4.8). A filing discloses
    for the filer and at most two named group holders; holdings at other group
    companies are disclosed nowhere and are not counted. Balance-sheet ratios
    therefore understate for complex groups, and by an unknown amount.
13. **Equity is not defined identically across accounting standards** (§4.9).
    Japanese 純資産 includes non-controlling interests. Where a filer tags only
    the parent-share IFRS or US-GAAP figure — 8.1% of filings — the
    denominator excludes them, and the ratio reads slightly high. There is no
    including-minorities element available for those filings, so the
    difference is disclosed through `equity_basis` rather than adjusted away.

---

## 10. Field dictionary

**`eq_filings`** — one row per annual report parsed.

| Field | Description |
| --- | --- |
| `doc_id` | EDINET document ID; the key back to the source filing |
| `edinet_code`, `sec_code` | filer identifiers (`sec_code` = 4-digit securities code) |
| `filer_name` | filer name as at the filing |
| `period_end`, `filed_date` | fiscal period covered; date published |
| `sha256` | hash of the archived package as parsed (§3) |
| `parser_version` | code version that produced the rows |
| `status`, `detail` | `clean` / `partial` / `failed`, with the reason (§6) |
| `issued_shares`, `treasury_shares` | the filer's own counts at its fiscal year end; the denominator when this company is someone else's issuer (§4.7, §8.5) |
| `share_classes` | number of share-class contexts the filing tagged |
| `equity_yen`, `equity_basis` | shareholders' equity as filed, and which accounting basis it is (§4.9) |
| `total_assets_yen`, `assets_basis` | total assets as filed, and its basis (§4.9) |

**`eq_filing_totals`** — the filing's own total for the whole policy bucket:
one row per disclosing entity × share class (§4.8). Sum across rows for a
filer's policy total; never substitute the sum of `eq_holdings`.

| Field | Description |
| --- | --- |
| `doc_id` | the filing |
| `holder_table` | `reporting` (the filer), `largest`, `second_largest` — separate legal entities in one consolidated group; their totals add |
| `share_class` | `listed` or `unlisted` |
| `book_value_yen` | total carrying amount for that entity and class, as filed |
| `issue_count` | number of issues held, as filed |

**`eq_holdings`** — one row per named position.

| Field | Description |
| --- | --- |
| `doc_id` | the filing this position came from |
| `holder_table`, `row_no` | which table, and the row within it (§2) |
| `held_name_raw` | issuer name exactly as filed |
| `held_edinet_code`, `held_sec_code`, `match_status` | entity resolution (§5) |
| `shares`, `book_value_yen` | current period, as filed |
| `prior_shares`, `prior_book_value_yen` | prior period, from the same filing |
| `purpose_ja` | stated purpose, verbatim |
| `reciprocal` | `有` / `無` as filed, footnote markers retained (§2) |

**`eq_reclassified`** — one row per holding whose stated purpose changed (§4.5).

| Field | Description |
| --- | --- |
| `doc_id`, `holder_table`, `row_no` | the filing, which table, and the row within it |
| `direction` | `to_pure` (out of the policy bucket) or `to_policy` (the reverse) |
| `held_name_raw`, `held_edinet_code`, `held_sec_code`, `match_status` | issuer, resolved as in §5 |
| `shares`, `book_value_yen` | as the filer reports them for the reclassified holding |
| `fy_of_change_ja` | fiscal year of the change, verbatim; some filers list more than one |
| `reason_ja` | the filer's stated reason, verbatim |

**`eq_filing_notes`** — the named table's own numbered footnotes (§4.6).

| Field | Description |
| --- | --- |
| `doc_id`, `holder_table` | the filing and which table the notes belong to |
| `note_no` | the footnote's own number — (注)1, (注)2 …, **not** a holding row |
| `text_ja` | the footnote, verbatim |

**`eq_filing_flows`** — the filing's own tally of what moved (§4.5).

| Field | Description |
| --- | --- |
| `doc_id`, `holder_table` | the filing and which table |
| `share_class` | `listed` (非上場株式以外の株式) or `unlisted` (非上場株式) |
| `issues_increased`, `acquisition_cost_yen` | issues whose share count rose, and the cost |
| `issues_decreased`, `sale_proceeds_yen` | issues whose share count fell, and the proceeds |

**`eq_entities`** — the EDINET registry: codes, names (JA/EN), industry,
listing status. Refreshed wholesale each run; registry data, not vintage data.
`name_en` is the registry's English name, null for roughly one listed filer
in ten (§5.1).

`eq_filings.filer_name_en` holds the filer's own cover-page English name, and
is the source of every English name on the site and in the API; `eq_entities.name_en`
is the registry fallback (§5.1).

API responses that carry names return the as-filed Japanese name (`name`,
`filer_name`, `held_name_raw`, `holder_name`) and, alongside it, the English
name (`name_en`, `filer_name_en`, `held_name_en`, `holder_name_en`), plus a
`names_note` stating where each came from. `/company` also returns
`industry_en`.

---

### 10.1 The `basis` object

Returned on every response carrying a yen figure. Derived, never stored (§8.8).

| Field | Values | Meaning |
| --- | --- | --- |
| `measurement` | `carrying_amount`, `acquisition_cost` | Only `carrying_amount` is held here. |
| `entity_scope` | `parent_only`, `largest_holding_company`, `second_largest_holding_company`, `holdco_consolidated` | Which disclosing entity of the group the figure covers. Read from `holder_table`. |
| `share_scope` | `listed`, `unlisted`, `both` | Read from `share_class`. |
| `trust_included` | `true`, `false`, `unknown` | Whether 退職給付信託 shares are in the tally. Always `unknown` here — the filings do not state it and it is never guessed. |
| `as_of` | date | The fiscal year end the figure is measured at. |
| `period_type` | `annual`, `interim` | Only `annual` is held here. |
| `labels` | object | One sentence of definition per value above. |
| `not_comparable` | text | The standing warning against setting these figures beside press or IR figures without `check_claim`. |

On `/api/v1/equity/company/{sec_code}`, `scale_entities` and `flows` each carry
their own `entity_scope` and `share_scope`, so the group split is visible row by
row rather than collapsed into the filing-level tuple.

## 11. Reproducibility

- Every figure traces to a `doc_id`, and every `doc_id` to an archived file with
  a recorded SHA-256.
- The API serves the same numbers the pages render; CSV exports carry their
  source, units and formulas in a metadata header.
- Extraction is re-runnable against the archive: same inputs and same parser
  version produce the same output, independent of whether the source is still
  published.
- Derived figures carry their formula, not a label.

---

## 12. Version history

| Version | Scope |
| --- | --- |
| `m1` | prototype: 7 financial filers, 817 positions; established the deemed-table and rename traps |
| `m3-1` | financial sector, one fiscal year: 151 filings, 4,684 positions |
| `m4-1` | full universe, five fiscal years: 21,084 filings, 204,402 positions; SHA-256 computed from parsed bytes; multi-year query rules (§8) |
| `m5-2` | purpose-change (reclassification) tables in both directions, table footnotes, the filing's own increased/decreased issue counts and yen, and issuer issued/treasury share counts, which make ownership percentages computable from the archive itself (§4.5–4.7, §8.5); filer English names read from the filing cover page |
| `m6-0` | **current** — the filing's own policy-bucket totals per disclosing entity and share class, and shareholders' equity and total assets with the accounting basis actually used, which make a policy book sizeable against the filer's own balance sheet (§4.8–4.9, §8.7) |

---

*Source: 有価証券報告書 (annual securities reports) filed on EDINET, Financial
Services Agency of Japan. Figures are as filed. This database is derived from
public disclosures and is not affiliated with or endorsed by the FSA.*
