# Methodology — Japanese Boards and Executive Pay

**Dataset:** board composition (役員の状況) and officer remuneration (役員の報酬等)
disclosed in Japanese annual securities reports.
**Coverage as built:** 21,099 filings parsed · 195,097 board seats · 61,968 officer-category
pay rows · 5,605 named individuals · 4,238 filers · fiscal periods ending
**2020-12-31 → 2026-05-31**.
**Parser version:** `board-m2-2`. **Status:** production — extracted, loaded, served at `/api/v1/equity/governance/` and published at `/governance.html`.

| Extraction status | All filers | Listed filers |
| --- | --- | --- |
| `clean` | 19,423 (92.1%) | 18,165 (**99.4%**) |
| `partial` (a gate breached, rows kept and the discrepancy published) | 85 | 74 |
| `no_tagged_board` (officers table exists only as a text block) | 1,568 | 35 |
| `unsupported_form` (annual report on a form with no governance section) | 23 | 5 |

The 1,568 untagged filings are overwhelmingly **unlisted** filers — bond issuers and
wholly-owned subsidiaries whose agents tag less. Among listed filers the board is tagged in
99.8% of filings.

This document states exactly how the numbers are produced, what they mean, and where
they are wrong. A figure taken from this database should be defensible in a client note
or a referee report. If something here is unclear or appears contradicted by the data,
treat that as a defect and report it.

Sibling document: [METHODOLOGY-CROSS-SHAREHOLDINGS.md](METHODOLOGY-CROSS-SHAREHOLDINGS.md).
Same source file, same archive, same trust contract.

---

## 1. Scope and source

| | |
| --- | --- |
| Source | EDINET (電子開示システム), Financial Services Agency of Japan |
| Document type | **120** — 有価証券報告書 (annual securities report), XBRL-to-CSV package (`type=5`) |
| Sections extracted | 役員の状況 · 役員の報酬等 · 従業員の状況 · 従業員の状況（多様性指標） |
| Filers | every filer with an archived annual report; no sector restriction |
| Frequency | annual, per filer, on that filer's own fiscal year-end |

Everything below comes from XBRL facts the filer tagged. **No HTML table is parsed**, so
there is no row-alignment failure mode. What is not tagged is not extracted, and its
absence is recorded rather than guessed.

Correction filings (訂正有価証券報告書, type 130) are archived but not extracted: as in the
holdings dataset, a revision is a new vintage, never an overwrite of a stored one.

## 2. The two reconciliations that must be shown, not buried

These are the two places where an intelligent reader will otherwise reach a wrong
conclusion. Both are carried as columns in the data, so any surface that shows the
figures can show the caveat next to them.

### 2.1 Named individual pay is CONSOLIDATED (連結報酬等) — a different basis from the pay table

The individual disclosure required of anyone paid ¥100m or more is *連結報酬等の総額*:
total remuneration from the **whole group**, including subsidiaries. The officer-category
table (§4.2) is the filer's own 役員区分ごとの報酬等 and is generally the parent company's.

Consequences, all of which are correct behaviour and not extraction errors:

- **People appear who do not sit on the filer's board.** An executive of a subsidiary is
  named in the parent's filing — Arm's chief executive appears in SoftBank Group's report.
  `eq_pay_named.on_board_at_filing` is false for these rows.
- **The named individuals' pay can exceed the entire officer-category total.** A handful
  of people paid on a group basis out-totalling the parent's whole officer table is
  arithmetically possible and happens. `eq_company_year.named_exceeds_category` marks
  every filing where it does — that flag is the proof in the data that the two figures are
  different bases.
- **Therefore: never subtract, net, or divide one by the other.** Named pay is not "part
  of" the category total, and "pay for everyone else" cannot be derived by subtraction.

Every row of `eq_pay_named` carries `pay_basis = 'consolidated'` so the basis travels with
the number into any export, chart or API response.

### 2.2 Pay components need not sum to the filed total

The category table's **total (報酬等の総額) is the filed, published figure**. The
components beside it — 固定報酬 / 基本報酬 / 業績連動報酬 / 賞与 / 非金銭報酬等 /
退職慰労金, plus filer-invented ones such as 譲渡制限付株式報酬 — are also as filed, and
they frequently do not add up to it. Two reasons, both the filer's:

1. **非金銭報酬等 is additive for some filers and an "of which" memo for others.** Tested
   both ways across the sample, neither convention reconciles more than the other by any
   meaningful margin, so there is no rule to apply — only the filer's own intent, which is
   not tagged.
2. **Components are printed rounded to ¥mn**, so several of them accumulate rounding error
   against a total that was rounded independently.

Additionally, a component can be **negative**: a forfeited restricted-share award is a
reversal (ZOZO's is −¥141m, and only including it makes that row add up).

How this is handled:

- `total_yen` is the published number. Never recomputed, never replaced by the sum.
- `components_sum_yen` is stored so the arithmetic is visible, and
  `components_reconcile` is true when the sum matches the total within
  max(¥1m × number of components, 0.5%).
- Per filing, `pay_rows_reconciled` / `pay_rows_with_components` state how much of that
  filing's pay table adds up.
- This is disclosed, **never fixed**. Choosing a convention would replace the filer's
  numbers with ours.

## 3. Capture

Identical to the holdings dataset: the daily EDINET capture job archives the `type=5`
package with its SHA-256 before anything is parsed, and extraction reads only the
archive. The SHA-256 stored on each filing row is computed from **the bytes actually
parsed**, so provenance is verifiable rather than copied from a manifest.

## 4. Extraction

### 4.1 The board (`eq_board`)

One row per person tagged in 役員の状況, in filing order (`seat_no`).

Each person is one XBRL context whose member is the filer's own label for them —
`…_ShinyaAkitoMember`. Fields read: 氏名, 役職名, 生年月日, 所有株式数.

- **`name_en` is the filer's own romanisation**, taken from that context member. It is
  *not* our translation. Split on camel-case boundaries; Japanese order (surname first)
  is preserved because that is how filers write it.
- **`person_key` is a weak key.** It is filer-authored and unverified: good enough to join
  a pay row to a board row inside one filing, **not** evidence that two companies share a
  director. Interlock analysis requires a curated person map that does not yet exist.
- **A member context with no 氏名 is a totals row, not a person**, and is dropped.
- `age_at_period_end` is derived from 生年月日 against the filing's fiscal period end —
  derived, not filed.
- `role` is classified from 役職名: 監査等委員 → audit-committee director; 監査役 →
  statutory auditor; 取締役/執行役 → director. **Outside status is not derivable per
  person** — only ~3.5% of 役職名 strings contain 社外 — so inside/outside counts come
  from the pay categories instead (§4.2), never from this column.

### 4.2 Pay by officer category (`eq_pay_category`)

One row per 役員区分: the filed total, the headcount it covers, and every component in the
XBRL family (matched by pattern, so filer-invented components are captured rather than
dropped). See §2.2 for why the components need not sum.

`headcount` counts officers **paid during the year**, which includes people who retired
mid-year. It is therefore not the board size and the two legitimately differ.

### 4.3 Named individuals (`eq_pay_named`)

One row per person whose 連結報酬等 is disclosed. See §2.1 for the basis.

**¥100m is a mandatory trigger, not a floor.** Takeda, Recruit, Sumitomo Mitsui Trust and
others disclose officers voluntarily below it; `voluntary_below_100m` marks those rows.
Treating them as errors would flag several blue chips as broken filings.

### 4.4 Company-level facts (`eq_company_year`)

Employees (consolidated and reporting-company), average age, average length of service,
**average annual salary**, and the human-capital metrics mandatory since FY2023 —
gender wage gap, female managers ratio, male childcare-leave uptake — all as filed.

## 5. Validation and per-filing status

| Gate | Rule | Why it is shaped this way |
| --- | --- | --- |
| **G1** | tagged board rows ≤ the filer's own 役員 headcount | In a 指名委員会等設置会社 the 役員 tally includes 執行役 who are disclosed only in a text block (JPX: 12 board rows vs 17 officers). Board ≤ officers is the invariant; the gap is published as `officers_untagged`. The reverse — more board rows than the filer's own tally — is a genuine defect. |
| **G2** | recomputed female ratio reproduces the filed ratio, to the decimal place the filer used | Only meaningful when the two populations coincide (board == officers); skipped otherwise, because the filed ratio then covers a wider population than the tagged table. |
| **G5** | 生年月日 implies an age of 20–100 | Catches a malformed or mis-scoped date. |

G3 (components sum, §2.2) and G4 (the ¥100m threshold, §4.3) are **disclosure flags, not
gates**: both describe the filing, not our reading of it.

Status per filing: `clean` · `partial` (a gate breached — the discrepancy is published,
the rows are kept) · `no_tagged_board` (the officers table exists only as a text block) ·
`failed` (the package could not be read).

## 6. Trust labels

- Names, titles, dates of birth, share counts, headcounts, pay figures, employee metrics →
  **as filed** (`Official Statistic`), with filing ID, EDINET link, filing date and the
  SHA-256 of the parsed bytes.
- English names → the **filer's own romanisation**, labelled as such. Not a translation.
- Age, averages, ratios, per-head pay, board aggregates → **derived**; they carry their
  formula, never a badge.
- Missing is missing. A director with no tagged shareholding is `—`, never 0.

## 7. How to query it correctly

1. **One filing per company for a cross-section.** Five fiscal years are five filings per
   filer; summing pay across them overstates it several-fold. Pin a fiscal year.
2. **Do not mix `eq_pay_named` with `eq_pay_category`** — different bases (§2.1).
3. **Do not compare `headcount` with `board_size`** — different populations (§4.2).
4. **Do not treat `person_key` as a person across companies** (§4.1).
5. **Filter on extraction status** when quoting an aggregate, and state coverage.

## 8. Known limitations

- **執行役 of committee-system companies are not individually disclosed** in XBRL; the
  board is complete, the wider officer group is not.
- **Tenure is not derivable.** 任期 is tagged but almost always as a footnote reference
  ("（注）３"), not a date, so board tenure is not in this dataset.
- **No person identity across companies or years.** See §4.1.
- **Committee memberships, independence designations and attendance rates are not in the
  annual report** — they are in the corporate governance report, a separate TSE filing not
  yet captured.
- **Two annual-report forms carry no governance tagging at all** — `jpcrp080000-asr`
  (foreign issuers) and `jpcrp030200-asr`. Verified by inspection, not assumed: those
  packages contain zero director and zero remuneration facts. 23 filings, status
  `unsupported_form`.
- **Filings where the filer's own numbers disagree** stay `partial` and are shown with the
  discrepancy. They are never silently corrected.
