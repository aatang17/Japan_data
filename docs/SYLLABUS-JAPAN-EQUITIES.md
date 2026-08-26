# Syllabus — Japanese Equities: Governance, Activism, M&A, Cross-Shareholdings

> **Purpose:** get from "informed generalist" to "can read a Japanese filing and form an
> independent view" on the governance-reform trade. Written for a non-engineer.
>
> **Shape:** 10 modules. Each has *the question it answers*, *core concepts* (with the
> Japanese terms, because the primary sources are in Japanese), *primary sources*, and
> *an exercise*. A suggested 12-week pacing is at the end.
>
> **Method:** every module ends with you reading an actual filing. Reading commentary about
> Japanese governance is not the same as reading a 有価証券報告書. The gap between people
> who have done the latter and people who have not is the entire edge.

---

## Module 0 — Why this is happening now

**The question:** Why did a 30-year-dormant market become the most active governance
situation in the developed world?

**Core concepts.** Post-war *keiretsu* (系列) and the main-bank system · cross-shareholdings
(持ち合い / 政策保有株式) as an anti-takeover device and relationship glue · the ROE problem
and chronic sub-book valuations · the reform sequence that changed the incentives:

| Year | Event | Why it mattered |
| --- | --- | --- |
| 2014 | **Ito Review** (伊藤レポート) | Put a number on it: 8% ROE as a minimum. Made underperformance quantifiable and therefore arguable |
| 2014 | **Stewardship Code** | Obliged domestic institutions to engage rather than rubber-stamp |
| 2015 | **Corporate Governance Code** (revised 2018, 2021) | Independent directors, disclosure of policy shareholdings and the rationale for each |
| 2022 | **TSE market restructure** — Prime / Standard / Growth | Created an explicit quality tier and a public list of companies failing to meet it |
| 2023 | **TSE request on "management conscious of cost of capital and share price"** | The PBR<1 campaign. Naming, listing, and pressure — the single biggest catalyst |
| 2023 | **METI Guidelines for Corporate Takeovers** | Made unsolicited bids respectable; boards can no longer reflexively refuse to engage |

**Exercise.** Pick any TSE Prime company trading below book. Write one page on why, without
using the words "cheap" or "undervalued." Force yourself to name the *mechanism* — excess
cash, cross-holdings, a parent, a dead segment, entrenchment.

---

## Module 1 — The disclosure system (do this before anything else)

**The question:** Where does the raw truth live, and how do I get it myself?

This module is load-bearing. Everything later depends on being able to pull primary
documents rather than reading someone's summary.

**Core concepts.**

- **EDINET** (金融庁) — Japan's EDGAR. Statutory filings under the Financial Instruments and
  Exchange Act.
  - 有価証券報告書 (yūkashōken hōkokusho) — annual report. Contains the cross-shareholding
    disclosures, board detail, major shareholders.
  - 大量保有報告書 (**5% rule filing**) — *this is the activist-tracking dataset.* Anyone
    crossing 5% of a listed company's voting rights files, with amendments on ~1% changes.
    Note the **特例報告** (special reporting) regime: passive institutional holders file on a
    relaxed schedule, which is why a "passive" filer switching to general reporting is
    itself a signal.
  - 公開買付届出書 — tender offer statement. The M&A primary document.
- **TDnet** (適時開示情報閲覧サービス, JPX) — timely disclosure. Corporate actions, results,
  board resolutions. Faster than EDINET, different legal basis.
- **Identifiers.** Securities code (証券コード) · EDINET code · corporate number (法人番号,
  National Tax Agency). None of them map cleanly to each other. **Entity resolution is the
  single hardest data problem in this domain** — start noticing it now.

**Primary sources.** [EDINET API specification v2 (FSA, June 2026)](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf)
— free, but requires registering for an API key.

**Exercise.** Register for an EDINET API key. Pull every 大量保有報告書 filed in the last
30 days. Sort by filer. You have just built the activist watchlist that people pay for.

---

## Module 2 — Cross-shareholdings (政策保有株式)

**The question:** How much of the Japanese market is still owned for reasons other than
return, and how fast is that unwinding?

**Core concepts.** Why they exist — takeover defence, customer/supplier relationships, bank
ties · *stable shareholders* (安定株主) and why they make an AGM vote a formality · the
disclosure regime: since the 2019 reporting year, annual reports must list policy
shareholdings individually above a threshold, with **the stated reason for holding each
one** — an extraordinary disclosure with no US equivalent · the distinction between
政策保有株式 (the holder's disclosure) and the *reciprocal* position · parent-subsidiary
listings (親子上場) as a related governance abuse.

**Why it's the highest-value dataset here:** it is disclosed only as tables inside thousands
of Japanese-language annual reports. It has never been easy to aggregate. Toyo Keizai sells
a commercial database of exactly this, which tells you both that it is valuable and that you
would have a real competitor.

**Primary sources.** [JPX Shareownership Survey](https://www.jpx.co.jp/english/markets/statistics-equities/examination/)
(株式分布状況調査) — annual, Excel and PDF, English, ownership by investor category. This is
the market-level view; the annual reports are the company-level view.

**Exercise.** Take one bank or insurer. Extract its policy-shareholding table for the last
five years. Chart the count and value. Then read the *stated reasons* and judge how many are
real.

---

## Module 3 — Shareholder activism in Japan

**The question:** What actually works here, and why did the 2000s playbook fail?

**Core concepts.**

- **The first wave and why it lost:** the Murakami Fund (村上ファンド); Steel Partners; and
  the decisive **Bull-Dog Sauce** Supreme Court decision (2007), which upheld a discriminatory
  defensive measure and effectively closed the market to hostile approaches for a decade.
- **Why the second wave is different:** it is not fighting the establishment, it is invoking
  the establishment's own codes. The TSE, METI and the FSA have already said the things
  activists want to say. That is the whole shift.
- **Mechanics:** shareholder proposal rights (株主提案権) — broadly, 1% of voting rights or
  300 voting units, held at least six months · the June AGM concentration and what it does
  to campaign timing · proxy advisers (ISS, Glass Lewis) and their Japan-specific policies
  (e.g. voting against top management where ROE or board independence falls short).
- **Who to follow:** Elliott, ValueAct, Oasis Management, Effissimo Capital Management, 3D
  Investment Partners, Strategic Capital, Dalton, Nippon Active Value Fund. Distinguish the
  loud from the effective — they are not the same set.

**Exercise.** Pick one campaign that concluded. Reconstruct it from primary documents only:
the 5% filing, the proposal, the company's response, the AGM vote result. Then read the
press coverage and note what it got wrong.

---

## Module 4 — Takeover and M&A law

**The question:** What can actually be done to a Japanese company against its board's wishes?

**Core concepts.**

- **Structures** under the Companies Act (会社法): merger (合併), share exchange (株式交換),
  share transfer (株式移転), business transfer (事業譲渡).
- **Tender offers** (公開買付, TOB): the **one-third rule** triggering a mandatory tender
  offer; the two-thirds threshold requiring an offer for all shares.
- **Squeeze-out:** the special controlling shareholder's demand at 90% (特別支配株主の株式等
  売渡請求) and the share-consolidation route (株式併合) — and why the choice between them
  has tax and appraisal consequences.
- **Conflicts:** MBOs and controlling-shareholder transactions; the **METI Fair M&A
  Guidelines (2019)** — special committees, market checks, majority-of-minority; and the
  **METI Guidelines for Corporate Takeovers (2023)**, which shifted the norm toward boards
  having to *consider* bona fide offers.
- **Defences:** poison pills (買収防衛策) and their decline; the shrinking legitimacy of
  "corporate value" as a refusal.

**Exercise.** Read one 公開買付届出書 end to end, including the special committee's report
and the valuation annex. Ask whether the minority was actually protected or merely
procedurally processed.

---

## Module 5 — Corporate actions

**The question:** What do companies do with the cash, and what does each action signal?

**Core concepts.** Buybacks (自己株式取得) — announcement vs execution vs **cancellation**
(消却), and why the third is the only one that permanently changes share count · dividend
policy and payout/DOE targets · splits and the TSE's push toward smaller investment units ·
third-party allotments (第三者割当増資) as a dilution and entrenchment tool — a red flag
worth learning to spot · treasury shares as a defensive reserve · delisting and going
private.

**Exercise.** Take 20 buyback announcements from TDnet a year ago. Track how much was
actually executed and how much was cancelled versus held in treasury. The gap between
announcement and cancellation is a real and under-analysed signal.

---

## Module 6 — Governance plumbing

**The question:** Who actually controls the board, and can an outsider change it?

**Core concepts.** The three board structures — 監査役会設置会社 (statutory auditors),
監査等委員会設置会社 (audit & supervisory committee), 指名委員会等設置会社 (three-committee)
— and what each means for how hard it is to change directors · independent outside directors:
the trend, and the gap between formal independence and real independence · the TSE Prime
continued-listing standards and the ending of transitional relief · the Stewardship Code and
what "engagement" means in practice from a Japanese institution.

**Exercise.** For one company, list every director, their tenure, their prior employer, and
whether "independent" survives contact with those facts.

---

## Module 7 — Valuation in a governance market

**The question:** Why do so many Japanese companies trade below book, and when is that a
signal rather than a trap?

**Core concepts.** PBR<1 as a *governance* statement, not only a valuation one · net cash
and cross-holdings as a share of market cap — the "sum of the parts is negative" phenomenon ·
cost-of-capital disclosure under the TSE request, and how to test whether a company's stated
WACC is serious · why cheapness without a catalyst persisted for 30 years, and what
constitutes a catalyst now.

**Exercise.** Build a screen: market cap minus net cash minus listed cross-holdings at
market value. Rank. Then check which names already have a 5% filer. The overlap is the
watchlist.

---

## Module 8 — Reading Japanese filings without fluent Japanese

**The question:** How do I work in the primary sources realistically?

**Core concepts.** The ~200 recurring terms that carry most of the meaning (start the
glossary in Module 1 and never stop adding) · XBRL tagging in EDINET and what is tagged
versus buried in free text — cross-shareholding tables are largely the latter, which is
precisely why the data is valuable · machine translation as a first pass and where it
reliably fails (legal structures, negation, subject-elision) · the 会社四季報 (Toyo Keizai)
as a fast orientation tool.

**Exercise.** Take the same annual report section in Japanese and in the company's English
version. List every place the English is softer. Companies disclose differently by language,
and that gap is itself information.

---

## Module 9 — What this means for the data product

**The question:** If I build this, what am I actually building?

**Core concepts.** This is **not** the macro data model. Macro is a few hundred clean
numeric time series keyed `(series, period, value)`. Equities governance is *documents and
events*: "filer F crossed 5.2% of company C on date D via instrument I." Entity resolution
across ~4,000 companies and thousands of filers is the hard part, and it has no analogue in
the CPI work.

The datasets ranked by value-to-difficulty:

1. **5% filings, structured** — moderate difficulty, high value, direct activist signal.
2. **Cross-shareholding tables, aggregated** — hardest extraction, highest value, an
   established commercial competitor.
3. **Buyback announcement vs execution vs cancellation** — easy, under-analysed.
4. **Tender offer terms and premia** — moderate, small volume, high per-item value.

**Open question worth answering early:** how far back EDINET actually serves documents via
the API. If the retention window is short, then the daily capture archive compounds the same
way macro vintages do — and starting early has real value. Verify before assuming either way.

---

## Suggested pacing (12 weeks)

| Weeks | Modules | Milestone |
| --- | --- | --- |
| 1 | 0, 1 | EDINET API key working; 30 days of 5% filings pulled |
| 2–3 | 2 | One sector's cross-shareholdings extracted and charted |
| 4–5 | 3 | One activist campaign reconstructed from primary documents |
| 6–7 | 4 | One tender offer read end to end, including the valuation annex |
| 8 | 5, 6 | Buyback execution study; one board fully mapped |
| 9–10 | 7 | Working screen, cross-referenced against 5% filers |
| 11 | 8 | Glossary at 200 terms; disclosure-gap comparison done |
| 12 | 9 | Written decision on whether to build, and which dataset first |

## Reading list

**Primary and official** (read these before any book): the Ito Review · Japan's Corporate
Governance Code and Stewardship Code (JPX/FSA, English available) · the TSE March 2023
request on cost of capital and share price · METI Fair M&A Guidelines (2019) and Guidelines
for Corporate Takeovers (2023) · the JPX *White Paper on Corporate Governance* · the JPX
Shareownership Survey.

**Context:** the standard corporate-history accounts of the keiretsu and main-bank system
for Module 0; contemporary Japan-governance commentary for the current wave. Treat all
secondary sources as orientation, never as evidence — the filings are the evidence.

**Ongoing:** a handful of activist funds' own published letters and presentations, which are
often the clearest available writing on specific Japanese companies.
