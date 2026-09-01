# Methodology — Shareholder Register (大株主の状況・所有者別状況)

Who owns each listed Japanese company, from the ownership section of its annual
securities report (有価証券報告書, EDINET): the named holders at the top of the
register, and the whole register split by investor category. Extractor:
[`equity/ownership_extract.py`](../equity/ownership_extract.py) (parser `own-1`).
API: `/api/v1/equity/ownership/…`. Page: `ownership.html`.

This is the reverse of [cross-shareholdings](METHODOLOGY-CROSS-SHAREHOLDINGS.md):
that dataset says what a company **holds**, this says who holds **it**.

## Source

The same EDINET `type=5` CSV package the holdings and boards extractors already
read — no new capture, no new document. Both tables are fully XBRL-tagged:

- **大株主の状況** — one context per row (`No1MajorShareholdersMember` …), each
  carrying name, address, share count and percentage, plus the filer's own 計
  row in the bare context. Past row 15 filers switch to a context id prefixed
  with their own extension namespace; the row number is read after stripping it.
- **所有者別状況** — the category is in the *element name*, not a dimension, and
  the three families do not agree on their suffixes (a foreign institution is
  `ForeignInvestorsOtherThanIndividuals` in the count and unit elements,
  `ForeignersOtherThanIndividuals` in the percentage one). The table is
  dimensioned by share class, so a company with preferred shares has one
  register per class and they are never merged.

Every filing row stores the SHA-256 of the bytes actually parsed.

## The two things that make this data misleading if unlabelled

### 1. The register is not beneficial ownership

Two nominee trust banks — 日本マスタートラスト信託銀行 and 株式会社日本カストディ
銀行 — sit at the top of almost every register in Japan, holding for index funds
and pension money they do not own. Ranked naively they are the largest
shareholder in the market, which is true of custody and false of ownership. In
this dataset **5,294 of 24,353 named rows are custody accounts** — a fifth of
every top-ten in Japan.

Every row therefore carries `holder_kind`, and it is **ours, not filed** —
derived from the name by fixed rules, with the name always shown so the reading
can be checked:

| holder_kind | Rule |
| --- | --- |
| `trust_bank_nominee` | One of the four custody banks (Master Trust, Custody Bank of Japan, and the two pre-2020 names that merged into it), or any other 信託銀行 holding through a bracketed account |
| `foreign_nominee` | A global custodian or street-name account, matched on a fixed list in both Latin and katakana spellings |
| `retirement_benefit_trust` | 退職給付信託 — the settlor company is named inside the account and is returned as `beneficiary` |
| `employee_association` | 持株会 in any of its forms |
| `individual` | Japanese characters only, short, and spaced — deliberately conservative |
| `foreign_entity` | No Japanese characters in the name |
| `entity` | Everything else |

Two rules exist because getting them wrong is a factual claim about someone:

- **The custodian test runs on the name with its bracketed qualifier removed.**
  That bracket usually names the holder's 常任代理人 (standing proxy in Japan),
  and the proxy is not the holder — GOVERNMENT OF NORWAY（常任代理人 シティバンク）
  is Norway's sovereign fund holding its own money, not a Citibank account.
- **A natural person is never entity-matched.** EDINET issues codes to
  individuals who file large-holding reports, so a name lookup *would* return a
  hit — and a name collision would attribute one person's holdings to another.

### 2. The two percentage columns have different denominators

- 大株主の状況 percentages are of shares in issue **excluding treasury**
  (発行済株式（自己株式を除く。）の総数) — the filing's own denominator.
- 所有者別状況 percentages are of **all issued shares**.

They are close, they are not the same measure, and nothing on this platform
nets or compares them row for row.

## Units and precision

Percentages are stored **as percent**. The XBRL carries them as pure fractions
(`0.0918`) while the filing prints `9.18` under a （％） header; ×100 is a unit
conversion of the filed figure, not a recomputation, and the filing's own
precision is preserved.

## Validation gates

Each gate recomputes a number the filer published. A filing that fails one is
published anyway, marked `partial`, with the failure in `detail` — never
corrected, never dropped.

| Gate | Test |
| --- | --- |
| **G1** | Category unit counts sum to the filer's own 計 row — exact integers |
| **G2** | Category percentages sum to 100 |
| **G3** | Named holders' percentages sum to the filer's own 計 ratio |
| **G4** | No holder's share count exceeds shares in issue |

**How the tolerance for G2 and G3 was set.** Filers do not agree on how to
round, and their own share counts prove both habits: Ono Pharmaceutical prints
1.80 for an exact 1.8064 and its 計 row is the truncated sum, while Toyota's ten
rows sum two hundredths *above* its 計. So the window is asymmetric — a full
last printed digit per row below the filed total, half a digit above it. The
last digit is the coarsest the filing states, because XBRL drops trailing zeros
(a printed 96.30 arrives as 0.963 and claims only one decimal), floored at the
two decimals the form prints.

**G4's denominator is all share classes.** TEPCO's rescue fund and Mitsubishi
Corporation's stake in Chiyoda are held largely in preferred shares; measuring
them against the ordinary count alone reports a holder owning more of a company
than exists.

## Coverage (local archive, parser `own-1`)

2,503 archived annual reports → **2,445 clean · 13 partial · 45 unsupported
form** (foreign-issuer and 特定 forms tag no ownership section at all).
24,353 named holders and 16,321 category rows. The 13 partials are filer-side
arithmetic, not parse failures — Ryukyu Bank's unit counts miss its own total by
three, Loginet Japan's register is stated a thousandfold larger than its share
count, and Jiban Net's 計 row does not match its own rows.

The five-year S3 run is the next step; the extractor takes `--source s3`
unchanged.

## Known limitations

- **A register discloses only its largest holders**, ten rows in most filings.
  A position below a company's tenth holder is invisible here by construction,
  and the reverse view ("where does this holder appear") means *in a top ten*.
- **The register is dated at the fiscal year end**, once a year. For a position
  that moves inside the year, the [5% filings](METHODOLOGY-5PCT-FILINGS.md) are
  the faster tape.
- **A nominee's beneficial owners are not disclosed anywhere** in Japanese
  public filings. The platform states the custody share; it does not estimate
  behind it.
- Entity matching resolves 7,748 of 24,353 rows. Most of the rest are private
  companies with no EDINET registration — genuinely unmatchable, not a failure.
