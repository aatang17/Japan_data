# Methodology — 5% Filings (大量保有報告書・変更報告書)

Every large-shareholding report filed on a Japanese listed company: who crossed
5%, in whom, how the stake moved, what they say it is for, and whether they
state that they may make important proposals to the board. Extractor:
[`equity/lvh_extract.py`](../equity/lvh_extract.py) (parser `lvh-1`). API:
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
  and the important-proposal answer.
- **Derived:** `ratio_change_pp` (current ratio − prior ratio, both as filed),
  every count and aggregate, and `is_current`.
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

## Identity resolution

Both sides resolve without name matching, which is what makes the reverse view
exact rather than fuzzy:

- **The issuer** is filed with its securities code (`SecurityCodeOfIssuer`).
- **Each holder** carries its own EDINET code. Joint holders are coded even when
  they never file themselves, so a holder is identifiable across every report it
  appears in; where EDINET's public filer registry has no row for that code the
  status is `code_not_in_registry` and the code is still the identity.

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
