# Ceres Analytics pitch deck — what to fill in, and where the numbers come from

`Ceres-Analytics-Pitch.pptx` · 19 slides · 16:9. Rebuild with
`python build_ceres_deck.py` (needs `python-pptx`; keep `arch-diagram.png` and
`site-holdings.png` next to it, and set `SCR` at the top of the script to this folder).

The build **fails rather than saves** if any text collides with other text, spills out of
its card, or runs into the footer, or if a screenshot runs into the footer. It also writes `preview.html`, a browser mirror of the
same coordinates, for eyeballing before you present. Keep the five `ui-*.png` dashboard
renders next to it as well.

## Positioning

**Ceres Analytics** is the company and the platform. **Plover Analytics** is the
first deployment, which is why the live screenshots carry that name. Japan is market one,
not the thesis: the core stores series, observations and provenance and knows nothing about
any country, so a new market is an adapter set.

Three surfaces carry the whole pitch: the **database**, the **MCP server**, and the
**assistant**. The assistant is what widens the market past people who can write a query.

## Running order

Headings are two or three words. The line under each one carries the argument.

| # | Heading | # | Heading |
| --- | --- | --- | --- |
| 1 | Ceres Analytics | 11 | One up close |
| 2 | Unusable public data | 12 | Approval and audit |
| 3 | Ingest, store, serve | 13 | Under the hood |
| 4 | What we cover | 14 | Users and tiers |
| 5 | Fix difficult formats | 15 | Why it holds |
| 6 | Point-in-time history | 16 | Where we are |
| 7 | Agent access | 17 | What happens next |
| 8 | Our way in | 18 | The team |
| 9 | The desk | 19 | The ask |
| 10 | Add specialists | | |

Product first, with the engineering explained inside each product slide. No section
dividers.

Three deliberate omissions:

- **No counts of our own datasets, tools or companies.** They go stale a week after the
  deck is written. The one number kept is ¥59tn of cross-holdings, a fact about the market.
- **No prices.** Slide 14 names three tiers and what each gets, and says prices come after
  the first customers have told us what they will pay.
- **No market-size table.** It was built on the prices.

Specialist names are the vendor kind a fund expects: Coverage Monitor, Cross-Shareholding
Monitor, Buyback Monitor, Governance Monitor, Filing Review, Macro Release Brief,
Disclosure Verification, Financials Extract, Research Draft. The example on slide 11 is the
Cross-Shareholding Monitor.

The dashboard screens are **designed, not built**. Slide 16 says so under "Being built".
Say it out loud rather than letting someone find it in diligence.

## Slide 5 uses a real file

The Bank of Japan publishes `mei260831.xlsx` every ten days, listing every government bond
it owns. A copy is in this folder as `example-hard-format-mei260831.xlsx`; the original is
at boj.or.jp/statistics/boj/other/mei/. Everything on the slide was read out of it:

- 339 issues, 9 bond types, ¥517.7tn
- 15 rows of titles, a department and a phone number before the data starts
- 257 columns declared, 6 with anything in them
- The bond type written on two rows, Japanese then English, then blank for the next
  twenty-one issues that still belong to it
- The unit in a floating cell, so every figure needs multiplying by a hundred million

If someone doubts it, open the file. That is why it is a real one.

## The live demo

`ceres-mcp-demo.html` in this folder is an animated version of slide 7, with three worked
examples: the cross-shareholding chart, the Bank of Japan bond book as a table, and a
broker-note claim being checked. It plays on its own and loops; arrow keys step through it.
Open it full screen when you have a screen, and let slide 7 cover the same ground on paper.

Published copy: https://claude.ai/code/artifact/d0dec09b-18d1-46d9-9177-0526be50bc74

## Fill these in before you present

| Slide | Placeholder | What it needs |
| --- | --- | --- |
| 1 · Title | `[FOUNDER 1] · [FOUNDER 2]`, `[EMAIL]`, `ceresanalytics.[tld]` | Both names, contact, the domain once you own it |
| 18 · Team | `[Years]`, the whole `[FOUNDER 2]` block | Your years in equities sales; your co-founder's name, role, and one concrete thing they have built at scale |
| 19 · Ask | `[AMOUNT]`, three `[%]` | The raise and the split |

Everything else on the deck is a real, checkable figure.

## The figures that remain

| Figure | Source |
| --- | --- |
| ¥59tn of cross-holdings, 2,778 filers | `eq_holdings` and the live Cross-Shareholdings page, 11 Sep 2026 |
| The chart on slide 7: MS&AD 52, Mizuho 15, SMFG 13, MUFG 9 | positions reduced, FY2026 annual reports, from `/api/v1/equity/company/{code}` |
| Slide 5, all of it | `mei260831.xlsx`, parsed directly; see the copy in this folder |
| Demo scenario 2: JGB book by maturity | the same BOJ file: 10Y ¥227.0tn/39 issues, 20Y ¥126.4tn/106, 5Y ¥80.8tn/38, 30Y ¥52.7tn/90 |
| Demo scenario 3: Toyota and KDDI | EDINET S100Y8NY: 203,294,600 → 363,365,900 shares, ¥989.6bn, 9.54% of KDDI |
| MS&AD cut 52 holdings, added 23 | EDINET S100YNCJ, period end 2026-03-31 |
| 1.9% then 2.0% on the point-in-time slide | illustrative pair, not a specific release; swap in a real revision when you have one |
| "Since August 2026" | first commit 2026-08-05 |

## Two questions you will definitely get

- **"Isn't this just free government data?"** Slide 15, "Why it holds". Lead with
  point-in-time history: versions of revised numbers that nobody can reconstruct later.
- **"Who is the technical founder?"** Slide 18 is the weakest slide until that block is
  filled in properly. Write it before you present.

## Presenting

Nineteen slides, about twenty minutes. Cut to twelve by dropping 3, 13, 15 and 17. Never
cut 5, 8 or 12. If you have a screen, run the live demo instead of talking through slide 7.
