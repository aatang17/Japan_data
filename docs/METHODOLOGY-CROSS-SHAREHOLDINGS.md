# Methodology — Japanese Cross-Shareholdings Database

**Dataset:** policy shareholdings (政策保有株式) disclosed in Japanese annual
securities reports.
**Coverage as built:** 21,084 filings parsed (21,061 published) · 204,402
disclosed positions · 4,227 filers · published fiscal periods ending
**2021-02-28 → 2026-05-31**.
**Parser version:** `m4-1`. **Status:** production.

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
  return, disclosed only in aggregate, not named.

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

## 5. Entity resolution

Issuer names are written free-form by the filer and must be matched to the
EDINET code list to make the data joinable.

Normalisation applied before matching:

1. HTML entity unescaping (filings carry `&amp;` and similar).
2. Unicode NFKC normalisation; removal of ASCII and ideographic spaces.
3. Removal of footnote markers filers append to names — `（注）３`, `(※5)`,
   `（注４）` and similar.
4. Kyūjitai → shinjitai character folding (會→会, 國→国, 髙→高, …).
5. Removal of legal-form suffixes (株式会社, （株）, ホールディングス, グループ本社)
   to derive a base name, matched after the full-string match fails.
6. A small hand-curated alias map for companies that renamed between the filing
   date and the current registry (a filer's name is frozen at its fiscal
   year-end; the registry is current).

**Match status is recorded on every row and never guessed:**

| `match_status` | Meaning | Rows | Share |
| --- | --- | ---: | ---: |
| `matched` | resolved to an EDINET code, and a securities code where listed | 191,869 | 93.9% |
| `unmatched` | domestic name that did not resolve | 10,147 | 5.0% |
| `foreign` | non-Japanese issuer, outside the domestic registry | 2,386 | 1.2% |

**Domestic match rate: 191,869 / 202,016 = 95.0%.**

Unmatched rows retain their full as-filed name, share count and book value —
they are complete for aggregate purposes and merely not joinable by code.
Aggregates over *positions* and *yen* include them; network and
"who-holds-whom" views necessarily do not, and any such view should state that.
The alias map is hand-curated and does not scale; a systematic rename feed
keyed on securities codes is the known fix.

### 5.1 English company names

A Japanese annual securities report names its holdings in Japanese only. The
English name shown on every surface is therefore **not part of the filing**: it
is a lookup into EDINET's own filer registry (`EdinetcodeDlInfo`, field
提出者名（英字）), joined on the EDINET code, falling back to the securities
code. It is a registry label attached to a company, never a translation of the
filed text and never machine-translated.

Coverage, on the archive as extracted:

| Population | With an English name | Share |
| --- | ---: | ---: |
| Named positions (all rows) | 182,874 / 204,402 | 89.5% |
| Named positions resolved to an EDINET code | 182,874 / 191,869 | 95.3% |
| Filers with a securities code | 3,778 / 4,226 | 89.4% |
| Registry entries with a securities code | 3,428 / 3,830 | 89.5% |

Two causes of a missing English name, both left visible rather than filled:
EDINET holds no English name for that filer, and a company that renamed or
restructured no longer carries the securities code the filing used. Where there
is no English name the as-filed Japanese name is shown alone — never a blank,
never a guess. The as-filed Japanese name is always carried alongside the
English one, on screen and in every export.

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
| **Official** | share counts, book values, stated purposes, reciprocity flags, issuer names, fiscal period, filing date | exactly as filed; never recomputed |
| **Derived** | year-on-year deltas, cut/added counts, sector and market aggregates, matched-panel indices | carries its formula, not a badge |
| **Registry lookup** | English company names (§5.1) | attached from the EDINET filer registry, not from the filing; blank where the registry has none |

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

## 9. Known limitations

1. **Correction filings are not folded in** (§1).
2. **Under-extraction is not detectable by the gate** (§6); 2 known filings.
3. **Entity matching is 95%** of domestic names; the alias map is hand-curated
   and does not scale (§5).
4. **Deemed holdings are excluded**, so this is not a measure of total voting
   influence (§1).
5. **Only named positions are captured.** Filers disclose individually only
   their significant holdings; the tail is disclosed in aggregate and is not in
   this database. Totals are therefore of *named* holdings, and the disclosure
   threshold varies by filer.
6. **Coverage is partial at both ends of the window** (§8.2).
7. **Book values are fair-valued, not cost** (§8.3).
8. **This is not a shareholder register.** It shows only holders that file an
   annual report and disclose the position as a policy holding.

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

**`eq_entities`** — the EDINET registry: codes, names (JA/EN), industry,
listing status. Refreshed wholesale each run; registry data, not vintage data.
`name_en` is the source of every English name on the site and in the API
(§5.1); it is null where EDINET publishes none.

API responses that carry names return the as-filed Japanese name (`name`,
`filer_name`, `held_name_raw`, `holder_name`) and, alongside it, the registry
English name (`name_en`, `filer_name_en`, `held_name_en`, `holder_name_en`),
plus a `names_note` stating that distinction.

---

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
| `m4-1` | **current** — full universe, five fiscal years: 21,084 filings, 204,402 positions; SHA-256 computed from parsed bytes; multi-year query rules (§8) |

---

*Source: 有価証券報告書 (annual securities reports) filed on EDINET, Financial
Services Agency of Japan. Figures are as filed. This database is derived from
public disclosures and is not affiliated with or endorsed by the FSA.*
