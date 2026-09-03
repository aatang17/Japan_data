# Methodology — 5% Filings (大量保有報告書・変更報告書)

Every large-shareholding report filed on a Japanese listed company: who crossed
5%, in whom, how the stake moved, what they say it is for, and whether they
state that they may make important proposals to the board. Extractor:
[`observatory/equity/lvh_extract.py`](../observatory/equity/lvh_extract.py) (parser `lvh-1`). API:
`/api/v1/equity/stakes/…`. Page: `stakes.html`.

Anyone crossing 5% of a listed company's voting shares must file within five
business days, and file again on every one-point move — so this is the only
public dataset in Japan that names an accumulating holder *before* the annual
report does.

## Source, and why it is parsed differently

EDINET document types **350** (報告書) and **360** (訂正報告書), captured daily
since 2021. Unlike every other dataset here the source is the **t1 inline-XBRL
package**: EDINET publishes no CSV rendition of this form. The facts are tagged
all the same (`jplvh_cor:*`) and are spread across the header, body and
per-holder documents of the package, which are read together.

**The scan cannot be a regular expression.** Inline XBRL nests: a text-block
fact wraps the tagged facts inside it, and a non-greedy regex closes the outer
element on the inner element's end tag and then resumes past it — truncating the
outer value and swallowing the inner facts whole. Measured on the archive, that
lost the holding ratio outright in 36% of filings. The extractor keeps a stack.

Three forms appear: `jplvh010000` (第一号様式, the general form), `jplvh020000`
(第二号様式, the special form for institutions), `jplvh030000` (第三号様式, the
change report). The cover-page title, not the form code, says whether a document
is an initial report, a change report or a correction.

## What is official and what is derived

- **Official, as filed:** issuer, holder names and addresses, share counts,
  holding ratios, the stated purpose, the reason for filing, funding amounts,
  the important-proposal answer, and each holder's stated business (`business_ja`,
  事業内容) and occupation (`occupation_ja`, 職業).
- **Derived:** `ratio_change_pp` (current ratio − prior ratio, both as filed),
  every count and aggregate, `is_current`, and the two labels below —
  `filer_type` and `group`.
- **From EDINET's own record, not the document:** `filed_date` is EDINET's
  submission timestamp. The date printed on the cover page is typed by the
  filer and is occasionally impossible — a Trusco corrector dated a 2026 filing
  2028 — so the printed one is kept separately as `cover_date`.

Money is stated in 千円 on this form and stored in yen, using the filing's own
`scale` attribute where it states one.

## Five things a consumer must not assume

1. **A report is an event, not a position.** Every filing is a snapshot at its
   own trigger date. "Who holds 5% of X today" is the latest report per
   (issuer, filing group); a group that has fallen below 5% files a final
   report and then stops, so a stale-looking row may be an exit.
2. **The group is the unit, and it is not the sum of its members.** The form
   deducts claims between joint holders, and a member that has just left is
   still described in the document with last-report figures only — Nomura's
   report on Nissui details three holders and its group total of 33,338,274
   shares is the sum of two of them. A holder counts toward the group only
   where the filing gives it a current figure (`in_group_total`).
3. **重要提案行為 is not asked on every form.** Only the general first-schedule
   form carries the field. The change report and the special form (whose whole
   basis is an undertaking not to make such proposals) do not, and
   `proposal_asked` is false there. **A null answer never means "no."** Where
   the field exists and the filer left it blank, `proposal_asked` is true and
   the answer stays null.
4. **The ratio is the statutory one.** Its denominator is 発行済株式等総数 plus
   the holder's own potential shares and its numerator excludes underwritten
   shares, so it does not equal `shares_held / shares_outstanding`, and the
   difference is not an error.
5. **A change report often restates the original obligation date.** 提出義務発生日
   on a 変更報告書 is frequently the date the holder first crossed 5%, years
   earlier — 14% of change reports state a date more than 40 days before
   filing, the oldest reaching back to 1990. The tape is therefore ordered by
   filing date, and the gap between the two dates is not a lateness measure.

## Filer type and filer groups

Two labels sit on top of the filings, both **derived**, both applied at serve
time in [`observatory/app/filer_labels.py`](../observatory/app/filer_labels.py).
The extractor stores only what the filing states, so changing a rule costs a
redeploy and never rewrites a stored row.

**filer_type** is read from the filer's own 事業内容 (business description),
which 87.9% of holder rows state, plus the filed 法人/個人 flag. Across 1,340
filing entities that types **99.3%** from a filed field: individual 483, asset
manager 162, investment vehicle 273, broker-dealer 36, insurer 19, bank 16,
trust bank 4, operating company 337, not stated 10.

- **No filing states a category such as "hedge fund"**, and none is invented
  here. The closest filed signal is 重要提案行為, which is a declaration of
  intent, not a description of the firm.
- **Own-account before third-party**, and the ordering is load-bearing. Hikari
  Tsushin's securities arm files 有価証券の保有管理及び投資運用: reading the
  投資運用 at the end of that sentence as "asset manager" would file a corporate
  holding vehicle among the fund houses. Managing your own money is not
  managing anyone else's.
- **Operating company is a finding, not a failure.** On a 5% filing it means a
  strategic holder.

**group** consolidates a family's filing entities. This one cannot be derived:
BlackRock files under 16 EDINET codes, Fidelity 13, J.P. Morgan 10, Nomura 8,
and no document names the parent. It is therefore a curated map, kept small,
with every entry carrying the name as the filings write it. An entity not in
the map is its own group — never inferred from a shared word, because Sumitomo
Corporation and Sumitomo Mitsui Banking are different companies and 48
unrelated firms have "Capital" in their name. **A joint venture is its own
group** (三菱UFJモルガン・スタンレー証券) rather than being counted inside either
parent. A group's issuer count is the distinct companies its entities cover
between them, never the sum of theirs — they file on largely the same names.

## Identity resolution

Both sides resolve without name matching, which is what makes the reverse view
exact rather than fuzzy:

- **The issuer** is filed with its securities code (`SecurityCodeOfIssuer`).
- **Each holder** carries its own EDINET code. Joint holders are coded even when
  they never file themselves, so a holder is identifiable across every report it
  appears in; where EDINET's public filer registry has no row for that code the
  status is `code_not_in_registry` and the code is still the identity.
- **A holder's code is not the issuer's.** A holder with no EDINET registration
  of its own is sometimes given the target company's code by the filer's own
  XBRL tool: Be Brave, an activist vehicle, filed on three companies and carried
  a different target's code each time, splitting its stakes three ways and
  landing each on the code of the company it was challenging. Where a holder's
  code equals the issuer's and the names differ, the code is rejected, the
  holder is identified by name, and the filing says so. 9 holder rows in 8,287.
- **A holder with no usable code** is identified by `name_key`, the same width-,
  spacing- and character-form folding the entity resolver uses, so one holder is
  one row of a ranking however the filer spelled it.

## Validation gates

Every gate is one-sided, and each side is the form's own arithmetic.

| Gate | Test | Why one-sided |
| --- | --- | --- |
| **G1** | Holders' share counts cover the filed group total | The group line deducts claims between joint holders, so members can legitimately sum to more |
| **G2** | Holders' ratios cover the filed group ratio | Same deduction, plus two-decimal printing per holder |
| **G3** | The filed ratio does not exceed held ÷ outstanding | The statutory denominator adds the holder's potential shares, so the filed ratio sits at or below that identity by construction — an equality test failed one filing in six on the statute, not on the data |
| **G4** | The ratio is between 0 and 100 | |
| **G5** | The obligation date is not after EDINET received the document | |
| **G6** | The cover page is not dated after EDINET received the document | A cover dated *before* submission is ordinary; only the impossible direction is a defect |

**Numeric facts are taken only when the tagged text is itself a number.** Filers
routinely leave a tag open over a whole table, and the one number inside it is
often a different line of the form — Nomura's borrowings tag contains its total
funding. A plausible-looking number in the wrong column is worse than a gap, so
anything else is missing and counted in `messy_facts`.

**Funding amounts carry a plausibility flag.** 取得資金 is printed in 千円 and a
few filers type yen into that box while still tagging `scale="3"`: Kobe Bussan's
¥1,677,200,000 of own funds becomes ¥1.68tn for 1.4m shares. The amounts stay
exactly as filed; `funding_implausible` marks where the implied cost per share
is impossible (5 filings in 3,893), so a page can decline to print a number
rather than print a wrong one.

## Coverage (local archive, parser `lvh-1`)

3,893 reports filed 2026-05-29 → 2026-08-06 → **3,850 clean · 43 partial**;
1,276 issuers, 817 filing groups, 8,287 holder rows, **150 reports stating an
important-proposal act**. Median gap from trigger date to filing: 7 days.

The archive itself reaches back to 2021 in the cloud bucket; the extractor takes
`--source s3` unchanged and that run is the next step.

## Known limitations

- **The window opens where the capture does.** EDINET's list API reaches about
  five years, so an accumulation that began earlier is visible from its first
  captured report onward, not from its start.
- **The 60-day trade table is not extracted.** The form's
  最近60日間の取得又は処分の状況 — dates, sizes and venues of the trades behind a
  move — is a text-block table and is left for a later parser.
- **No price data**, so a stake's yen value is not computed anywhere; the
  filing's own funding figures are the only monetary amounts here.
