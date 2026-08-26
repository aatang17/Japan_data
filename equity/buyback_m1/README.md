# M1 — buyback execution extractor (prototype)

Parses EDINET **自己株券買付状況報告書** (document type 220), the monthly report a
company files while a share buyback is running. Prototype only: reads from the
cloud archive, validates, and writes CSV. No database, no API.

```bash
set -a; . /path/to/s3.env; set +a          # EDINET_S3_* — same vars as capture
../../observatory/.venv/bin/python extract.py --limit 300 --csv out/sample.csv
```

## Result

**300 filings sampled across 13 months · 232 companies · gate pass 298/298 = 100%**
(2 further filings correctly identified as "no table": the filing exists but
states 該当事項なし.)

## What the source actually is — and why this was not a repeat of M1-holdings

The cross-shareholding tables are fully XBRL-tagged, element by element. **These
filings are not.** The body carries only ~5 inline facts, all `TextBlock`s, and
every number sits in an HTML table inside them. This is table parsing, which is
structurally more fragile than element lookup.

Two things make it safe enough to build on:

1. **The form is regulator-prescribed**, so row labels (決議状況 / 計 / 累計 /
   進捗状況) are stable across filers even though cell padding and merging are not.
2. **The filing publishes its own arithmetic.** 自己株式取得の進捗状況（％） is the
   filer's cumulative ÷ authorised. Recomputing it from the rows we extracted
   and requiring the filer's own figure back is a genuine end-to-end gate: a row
   read from the wrong line fails it immediately.

**Never key on cell position.** Daily acquisition rows carry (label, date,
shares, yen) while summary rows carry (label, shares, yen), and filers merge the
label cell across days. The parser reads the *trailing numeric pair* of each
row and identifies the row by a substring of its label.

## Traps found (all three produced wrong or missing numbers)

- **Filers disagree about rounding.** Dai-ichi Life prints `21.8` for a true
  21.893% (truncation); Yoshicon prints `59.7` for 59.65 (rounding). A fixed
  ±0.05pp tolerance fails perfectly good extractions. The gate now allows one
  unit in the last decimal place the filer actually printed — the tightest
  bound admitting both conventions.
- **Units inside the value cell.** Some filers write `55.17%`, others `55.17`;
  share cells occasionally carry 株/円. Rejecting the cell as non-numeric does
  not fail loudly — it silently shifts the trailing-pair read onto the wrong
  column, which is how 雪印メグミルク came out with the yen percentage in the
  shares field. Strip the unit; never discard the cell.
- **"Not applicable" has several spellings** — 該当事項はありません, 該当事項なし,
  該当なし — and may be wrapped in a one-row table rather than a paragraph, so
  the test must run on stripped text, not on the presence of markup.

## What it extracts

Per filing, per resolution table (board or AGM): resolution date, authorised
shares and yen, shares and yen acquired in the reporting month, the count of
daily execution rows, cumulative shares and yen against the authorisation, the
filer's stated progress percentages, and the as-of date. Disposal (処理状況) and
treasury-holding (保有状況) blocks are captured as text for now.

## Known limitations before M2

- **The AGM path is untested.** No filing in the 300-filing sample carried an
  actual 株主総会決議 acquisition table — every one was a board resolution. The
  code path exists but has never parsed a populated table; find one before
  trusting it.
- **History is capped at roughly one year, permanently.** EDINET purges these
  filings after about 12 months: the earliest still retrievable is **2025-08-12**,
  and purged documents return as stub rows with `legalStatus: 0` and every field
  null. Across the whole archive, 44.7% of 2021 documents, 40.5% of 2022 and
  31.2% of 2023 are already gone. **The pre-2025 buyback record cannot be
  rebuilt by anyone.** Coverage compounds only from here, which is precisely the
  argument for the capture job.
- **Multiple concurrent programmes** in one filing are not handled — the parser
  assumes one acquisition table per resolution type.
- Disposal and holding blocks are stored as raw text, not parsed.
- HTML layout is not a contract. If EDINET restyles the form the parser must
  fail loudly rather than return partial rows; the progress gate is what makes
  that possible.

## Preview of the product (from the 300-filing sample)

Completion against authorisation, by yen, across 276 filing-months: median
**71.9%**, p25 **31.6%**, p75 **100%**; 78 filing-months at or above 99% and 62
below 25%. ¥999bn of actual buying in the sampled months. Announced-versus-
executed is the question this dataset answers and no free source does.

---

## M2 outcome (production run, `buyback.py`, parser `bb-1`)

> **Superseded by `bb-2` (2026-08-24).** The numbers below stand as the bb-1 record,
> but bb-1 dropped every resolution table but the last in the 209 filings that carry
> more than one — see the lifecycle section at the end of this file. Current figures:
> [../README.md](../README.md).

**6,221 filings · 6,193 programme rows · 1,237 companies · months 2025-02 → 2026-08**

| Status | Rows | Meaning |
| --- | ---: | --- |
| `clean` | 5,681 | gate ran and passed |
| `partial` | 119 | gate ran and **failed** — published with the discrepancy recorded |
| `unverified` | 393 | filer published no 進捗状況, so there was nothing to reconcile |
| `no_table` | 28 filings | section absent or explicitly not applicable |

**Gate pass, of rows the gate could actually check: 5,681/5,800 = 97.9%.**

Three classification lessons from the full run, none visible at prototype scale:

- **A table-less block is not a failed parse.** Some filers write the section as
  prose. Grading that as a defect put 109 rows in the same bucket as real
  failures and hid them.
- **`clean` must mean the gate ran.** 393 rows (6.5% of what was previously
  called clean) omit 進捗状況 entirely — Daikin's completed ¥350bn programme
  among them. They now carry `unverified`: the figures are extracted and
  usable, but nothing reconciled them, and saying otherwise would claim a
  verification that never happened.
- **Roughly 2% of filings do not reconcile against their own published
  percentage.** S100WIKI states 12.26% while its resolution row repeats the
  cumulative figure exactly, with the real authorisation appearing nowhere in
  the table. Raw cells were re-read to confirm the parser is faithful. The gate
  cannot distinguish a mis-read row from a mis-printed filing, and should not
  try — either way the row is not clean.

**Aggregate sanity checks.** Duplicate company-months are negligible (¥21.88tn
summed as-is versus ¥21.86tn taking one row per company-month), and every
filing carries a SHA-256 computed from the parsed bytes (0 nulls).

---

## Lifecycle probe (`lifecycle_probe.py`) — announcement → execution → cancellation

Asked whether the three-leg lifecycle can be built. Answer from the source, not
from theory: **two of the three legs are already inside the filings `buyback.py`
downloads and parser `bb-1` throws away.** Probe reads the local EDINET archive
(1,206 type-220 filings submitted 2026-06-01 → 2026-08-06, 609 companies,
reporting months 2025-06 → 2026-08), writes CSV, touches no DB. Every row is a
board resolution — the AGM path is still untested, as at M1.

| Leg | Where it lives | Probe result |
| --- | --- | --- |
| **Announcement** | the 決議状況 row label carries the acquisition **window** — `(取得期間 2026年5月27日~2026年12月31日)` — alongside the resolution date and authorised shares/yen | window parsed on **1,198/1,200** programme rows |
| **Execution** | already in production (`bb-1`) | unchanged: 1,063 clean / 30 partial / 107 unverified |
| **Cancellation** | 【株式の処理状況及び保有状況】 — a prescribed 消却 row (retirement date, shares, yen) plus 発行済株式総数 and 保有自己株式数 at month end. `bb-1` ignores both blocks | disposal gate **157/157** clean where it could run; 1,031 filings correctly read as "nothing disposed"; holding block parsed on 1,202/1,206 |

**The disposal block publishes its own 合計**, so it gets the same end-to-end
gate as the acquisition block: recompute the total from the four category rows
and require the filer's figure back.

**Programme rollup.** Grouping filing-months by (edinet_code, resolution type,
resolution date) gives one row per authorisation. Production `bb-2` now does
this as the view `eq_buyback_lifecycle`; on the local archive: **162 completed ·
84 window closed with the authorisation unspent · 28 window closed but the final
report not yet in the archive · 259 running · 123 unclassifiable** (no
authorisation or no cumulative). The unspent ones are the commercially
interesting leg — Marui 18.5% of ¥20bn, Hirose Electric 35.5% of ¥15bn, SMFG
60.3% of ¥180bn.

### Defects found (four of the five were live in production `bb-1`)

- **A filing can report more than one live authorisation, and `bb-1` published
  only the last.** TOPPAN's May 2026 filing carries two tables — a ¥30bn
  programme closing at 100% and a ¥50bn one four days old. bb-1 read the block
  as a single record, so last-row-wins kept the new programme and silently
  dropped the completed one. **The figures it published were internally
  consistent and passed the progress gate**, which is why it survived a
  6,221-filing run — and why the first draft of this note wrongly read TOPPAN as
  having spent 2.9% of ¥50bn. 40 of 1,206 local filings (3.3%) are affected.
  `bb-2` parses one record per resolution table.

- **`その他` is not one row.** Filers open a separate その他(…) block per reason —
  Sony files three. Keying the category by name overwrites all but the last and
  fails the sum gate on a perfectly good filing; the categories must accumulate.
- **Reiwa-era dates.** ~1% of filers write 令和8年5月13日. `bb-1`'s `jdate()`
  matches only 西暦, so **`resolution_date` is null for those filings in
  production** — and the programme rollup keys on it.
- **取得期間 is not always in the label.** Idemitsu puts it in a row of its own,
  so the window must be read from the block text, not the 決議状況 cell.
- **Never substitute a nearby date.** MonotaRO filed the form with the resolution
  date left blank; a fallback that picks up the as-of date invents a fact. One
  row, correctly null.

Two filer-side inconsistencies the gates caught, both published as filed:
TalentX states 発行済株式総数 49,800 against 保有自己株式数 20,344,700 (impossible),
and 8 filings publish disposal rows with no 合計 to reconcile against.

### What is *not* in EDINET, and cannot be

The announcement **press release** — stated rationale, % of shares outstanding,
ToSTNeT-3 mechanics, and any *abandonment* of a live programme (取得中止) — is
TDnet only: **PDF, no XBRL** (107 announcement and 71 消却 disclosures in the 22
captured days, zero with XBRL). TDnet retention is ~31 days, so that history
starts at our capture (2026-07-13) and can never be backfilled. EDINET's 220
horizon is 2025-08-12 for the same reason.
