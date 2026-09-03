# Methodology — AGM Votes (臨時報告書, 株主総会決議)

How every resolution at a Japanese shareholder meeting was voted, and — for
board elections — how much support each named director received. Extractor:
[`observatory/equity/agm_extract.py`](../observatory/equity/agm_extract.py)
(parser `agm-1`). API: `/api/v1/equity/agm/…`. Page: `agm.html`.

A listed company must file an 臨時報告書 within days of a general meeting
stating, proposal by proposal, the voting rights cast for, against and
abstaining, and the resolution's outcome. For elections it must do so for
*every individual candidate*. That per-director figure is the point of the
dataset: it is the only free, public, structured measure of a named director's
mandate in Japan.

## Source, and why it is parsed differently

EDINET document type **180** (臨時報告書) and **190** (訂正臨時報告書).

Every other extractor in this repo reads tagged facts. This one cannot. Type
180 is 98% "XBRL" by EDINET's own flag, but the tagged facts are cover-page
boilerplate — filer name, fiscal year, EDINET code — plus a single
`ReasonForFilingTextBlock`. **All of the substance is an HTML table inside the
t1 honbun document**, so this parses the honbun and reuses the rowspan/colspan
grid machinery written for `facility_extract.py`.

**臨時報告書 is a grab-bag.** The same document type carries mergers, share
exchanges, specified-subsidiary changes and officer changes. Only about 42% of
all type-180 filings report a general meeting (88% in the late-June AGM week).
The rest are recorded with status `not_agm` and no proposals rather than
silently dropped, so the table reconciles against the archive.

## Column typing, not column position

Filers word the header differently — 賛成 / 賛成数, with and without 個, six
spellings of the result column — but the columns and their order do not vary.
Columns are therefore typed by keyword.

One family of filers needs more than that. A minority publish a dedicated
`賛成率` column, then the result, then a trailing `(参考) 反対率`. A scanner
that took the first percentage after the result column read the **against**
rate as the approval rate, turning Omron's 99.1% into 0.1%. The approval-rate
column is typed in its own right, and any column naming 反対 is recorded as a
rate to be ignored rather than left for a positional guess to find.

Percentages are written four ways — `99.4%`, `（98.1%）`, `99.76`, and
`可決93.51%` — and about a third omit the sign, so a bare decimal standing
alone in the result column is read as the percentage, bounded at 100.

## What is official and what is derived

| Field | Trust |
| --- | --- |
| `for_votes`, `against_votes`, `abstain_votes` | **Official** — exactly as filed, in voting rights (個) |
| `approval_pct` (賛成割合) | **Official** — exactly as filed, never recomputed |
| `result` (可決 / 否決) | **Official** — as filed |
| `partial_tally` | **Official** — the filer's own disclosure that it stopped counting |
| `approval_pct_of_counted` | Derived: `100 × For ÷ (For + Against + Abstain)` |
| `category`, `shareholder_proposal` | Derived: keyword classification of the filed label |
| `pct_consistent` | Derived: whether the two percentages agree within 15pp |

### Why the percentage is not recomputed

**95% of these filings state that the company did not count every vote.** The
section is headed 出席した株主の議決権の数の一部を加算しなかった理由 — "reason
part of the attending shareholders' voting rights were not counted". Japanese
issuers tally advance votes plus enough of the votes in the room to settle the
outcome, then stop, and say so.

The consequence is that **the denominator behind the published 賛成割合 is never
disclosed.** Measured over 371 sampled proposal rows, recomputing
`For ÷ (For + Against + Abstain)` misses the filed figure by a median of
0.24pp, and sometimes by far more.

So the filed percentage is stored and displayed exactly as filed and carries
the official badge. Our arithmetic is served separately as
`approval_pct_of_counted`, with its formula, and is never shown beside the
filed figure on the page — presenting the two in one column would invite them
to be read as the same measure.

### Why a board election has no proposal-level vote

The filing publishes one result per candidate and **no total for the
proposal**. Summing the candidates would invent a figure nobody filed, so
proposal-level vote columns are null for elections and `candidates` says how
many rows sit underneath. The per-candidate rows live in `eq_agm_votes`.

## Validation gates

None of these judges the company. They judge the parser, by recomputing what
the filing already publishes and asking whether our reading reproduces it.
Measured over 1,137 sampled rows: median gap 0.14pp, p90 2.3pp, p99 7.3pp.

| Gate | Asserts |
| --- | --- |
| **G1** | A row's filed percentage is within 15pp of our share of counted votes. Deliberately loose — the gap is dominated by the disclosure artefact above, not by error; 99.7% of rows sit inside it. |
| **G1b** | *Consistency within a filing.* Filers differ in what they put in the denominator, but no filer changes convention between two rows of one table. A filing where some rows land inside 2pp and others fall outside 5pp has a misaligned row. In the sample this isolated 2 filings against 11 where every row shifts together and the parse is fine. |
| **G2** | Candidates under one election proposal cast near-identical totals — same meeting, same votes. Divergence beyond 2% means a rowspan the grid did not expand. |
| **G3** | A proposal recorded 可決 has 賛成 > 反対. |

A filing failing any gate is stored with status `partial` and the specific
problem in `detail`. **Nothing is dropped**; the filing says what it says.

## Who proposed it

The table label almost never says 株主提案. The filing marks it in the
narrative instead, as an explicit range:

```
<会社提案(第1号議案から第2号議案まで)>
<株主提案(第3号議案から第9号議案まで)>
```

That range is the authoritative marker and is what sets `shareholder_proposal`.
Reading only the table label missed it entirely — MUFG's shareholder-nominated
directors came back indistinguishable from board nominees, which is the single
most interesting distinction in the dataset.

## Rankings show only corroborated rows

`/directors` and `/proposals` rank only rows where `pct_consistent` is true.
Without that, a single misread cell puts a fictitious 0.1% at the top of
"lowest support", above every genuine result — which is exactly what the
against-rate bug produced before it was found. `include_unverified=true`
returns the excluded rows, flagged.

## Five things a consumer must not assume

1. **The percentage is the company's, not ours,** and cannot be rebuilt from
   the counts printed beside it. See above.
2. **A board election has no single vote count.** Null there is structural,
   not missing data.
3. **Voting rights are not shares.** Counts are in 個, one per trading unit.
   They are not comparable with the share counts in the 5% filings, the
   shareholder register, or the cross-shareholding tables.
4. **Absence is not dissent.** A shareholder who did not vote appears nowhere.
   A low approval percentage means votes actively cast *against*, which makes
   it a much sharper signal than a low turnout would be.
5. **A low figure is not automatically a governance story**, for two separate
   reasons, both of which produced wrong-looking rankings before they were
   handled.

   **A dismissal vote reads backwards.** 取締役の解任の件 asks shareholders to
   *remove* a named director, so 0.5% approval means the attempt was crushed
   and the director kept the seat. Ranked beside elections it put retained
   directors at the top of "lowest support" — a wrong number, not a
   presentational quibble. `/directors` serves elections by default;
   `kind=dismissal` serves removal votes, where a *high* percentage is the
   adverse signal.

   **A shareholder-nominated candidate is not a sitting director.** They are
   routinely opposed by the board and routinely lose, so 1–3% is the proposal
   failing, not a mandate collapsing. MUFG's 2025 meeting carried three such
   candidacies at about 1.4%.

## Coverage

**The archive starts in April 2024, and nothing earlier can be recovered.**
臨時報告書 leave EDINET's public inspection window far sooner than annual
reports do: measured against our own daily lists, the earliest type-180 still
carrying metadata is 2024-04-01, while type 120 and type 350 reach back to
2021-08. Filings older than that had already been withdrawn before capture
began, and no back-fill can reach them. Coverage grows forward from here — one
more reason the daily capture is the asset.

## Known limitations

- **Multi-group header tables are not parsed.** A minority of filers split the
  vote into 事前行使 / 当日行使 / 総行使 column groups under a stacked header.
  Column typing picks the advance-exercise group, and the gates flag the
  filing as `partial` when the percentages then disagree. These are stored but
  excluded from rankings.
- **The meeting date is read from the narrative,** not a tagged fact, and is
  bounded to the year before the filing date — the same paragraph often quotes
  a dividend record date and a prior meeting. Where no date survives that
  bound it is null, never guessed.
- **`category` is keyword classification of the filed label,** not a taxonomy
  the filer supplied. About 1.4% of proposals fall to `other`. Some filers
  print only `第9号議案` in the table and set out the subject in the narrative;
  the agenda text is read to fill that in, but where the narrative is also
  terse the proposal stays `other`.
- **The candidate name is as printed,** including the wide spacing some filers
  use inside a name (`成 島 啓`). Names are not yet resolved to the directors
  in the boards-and-pay dataset, so the same person is not yet queryable
  across companies.
