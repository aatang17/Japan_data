# PLAN — Platform Vision: Japan Without a Japan Analyst

> **Status:** PROPOSAL v1 — awaiting approval. This is the umbrella document: it sits
> *above* the three product plans and gives them one destination. It changes no schema
> and no code by itself.
>
> **One-liner:** The platform that lets a foreign investor or hedge fund run Japanese
> exposure — starting with the governance-reform trade — without hiring a Japan analyst:
> every primary source read, extracted, translated, screened, and monitored in English,
> with the filing behind every number.
>
> **Companion docs:** [PLAN-JAPAN-MACRO-OBSERVATORY.md](PLAN-JAPAN-MACRO-OBSERVATORY.md)
> (macro, product #1) · [PLAN-CROSS-SHAREHOLDING-DB.md](PLAN-CROSS-SHAREHOLDING-DB.md)
> (holdings, product #2) · [PLAN-BOARD-AND-PAY.md](PLAN-BOARD-AND-PAY.md) (governance,
> surface #3) · [../SYLLABUS-JAPAN-EQUITIES.md](../SYLLABUS-JAPAN-EQUITIES.md) (the
> domain map this vision is built on)

---

## 1. The customer and the job

**Who.** A fund that wants Japan exposure but has no Tokyo office and no Japanese
speaker: US/European event-driven and value funds, family offices, smaller hedge funds,
and increasingly the "generalist PM plus AI tools" shop. Today their choices are
(a) hire a Japan analyst at $300–500k fully loaded, (b) rent sell-side coverage and
accept its conflicts and gaps, or (c) skip the market. Japan is the most active
governance situation in the developed world and most of these funds are choosing (c)
because of language and plumbing, not conviction.

**The job we do.** A Japan analyst's week is mostly mechanical: read filings in
Japanese, extract the numbers, screen for names, monitor the portfolio for events,
explain the local context. That mechanical 70% is exactly what a database with an
extraction pipeline does better than a person — completely, every filer, every day,
with a citation. So the honest framing is:

> **We replace the *first* analyst you would hire, not the last.**

What we do **not** replace, and never claim to: judgment, valuation calls, management
meetings, channel checks, taste in ideas. We are a data and publishing product, not an
adviser — this line also keeps us out of investment-advice regulation (§7).

**Why the governance trade first.** "Invest in Japan" is too broad to own. "The
governance-reform trade — unwinds, buybacks, boards, activism, M&A — investable from
abroad" is ownable, because it runs on Japanese-only primary documents nobody else
structures in English, and it is the trade foreign money actually wants on.

## 2. Scope: Japan is the product, Asia is the brand

Standing decision (unchanged): **Japan deep, not Asia wide.** The Substack brand is
*Asia* Economics Observations and the long-term ambition is "invest in Asia without a
local analyst" — but Asia is the **option**, not the roadmap. The trigger to open a
second market is a paying customer asking for it, or Japan revenue proving the playbook
repeats. (When that day comes, Korea is the natural analog — chaebol governance and the
Value-up programme mirror the TSE reform story — but that is a future decision, made
explicitly, not drift.) Until then, every hour goes into Japan depth, because depth is
the moat and breadth is CEIC's business.

## 3. The product: five layers

The vision is one stack. Each layer makes the one below it sellable.

| Layer | What it is | State today |
| --- | --- | --- |
| **1. Data** | Primary-source datasets, extracted and archived: CPI (822 series), BOJ balance sheet, cross-shareholdings (~204k named holdings), boards & pay (~49k directors, ¥100m individuals), buybacks (~6.4k programmes) | **Live locally; the core asset** |
| **2. Dossier** | One page per company that assembles everything: who it holds, who holds it, the board, pay, buyback record, unwind pace vs stated intent. The analyst's briefing book, generated | Partial — holdings/governance/buyback pages exist as separate surfaces; the unified dossier does not |
| **3. Screens** | Idea generation: biggest remaining cross-holders, fastest/slowest unwinds, sub-book laggards, entrenched boards, cash-rich under-buyers, pay outliers | Partial (unwind ranking exists); blocked on prices for anything ratio-based |
| **4. Watch** | The retention product: watchlists + event alerts + a weekly English digest ("your names this week: 2 buyback resolutions, 1 new 5% filer, 1 AGM result"). This is the analyst function funds *feel* the absence of daily | **Missing.** Raw material already being captured daily (EDINET extraordinary reports, 5% filings, tender offers, AGM voting results; TDnet fast tape) but none of it parsed or surfaced |
| **5. Access** | How the customer consumes it: web for humans, CSV for analysts, API for quants, **MCP for the customer's own AI agent** | Web + API + MCP live for existing datasets |

**The 2026 point about layer 5.** "Without a Japan analyst" increasingly means "my AI
does the analyst work." An LLM alone cannot be trusted on Japan — it hallucinates
numbers and cannot read what was never digitised in English. Our MCP server makes the
customer's *own* agent a competent Japan analyst, because every answer is grounded in
tool calls against filed data with citations. This is fully consistent with keeping our
own Ask box off: we do not run the LLM or bear its liability — the customer runs
theirs; we sell the ground truth it stands on. "The data layer for your Japan agent"
may end up the strongest institutional pitch we have.

## 4. What makes this defensible

1. **The archive compounds** (unchanged from the product plans): EDINET deletes,
   TDnet retains ~31 days, vintages accumulate only forward. Every day the capture
   runs, the platform gets harder to replicate.
2. **The entity graph.** 94% of free-text holding names resolved to entity codes, and
   climbing. Joins nobody else can run (board age × unwind pace, buybacks × who owns
   you) exist only because one database holds all of it, resolved.
3. **The reverse views.** "Who holds this company" and "who filed 5% on this company"
   appear in no single filing — they exist only in the assembled database.
4. **Workflow lock-in.** Watchlists and alerts (layer 4) create switching costs the
   raw data never will. A fund that has monitored its book through us for a year
   doesn't leave over price.
5. **Audience first.** The Substack means we arrive with readers, not cold emails.

Not defensible, and worth saying plainly: the extraction itself. The tables are tagged
XBRL; a funded incumbent could rebuild the pipeline in a quarter. They cannot rebuild
the archive, the resolved graph, the vintage history, or the readership.

## 5. Roadmap

Phases, not dates — each phase is sellable on its own and none requires the next.

- **Phase 1 — Finish the record (now).** Ship the three equity surfaces plus the
  unified company dossier; publish coverage and methodology; keep macro waves J1–J2
  moving. Substack cadence against every release. *Exit test: a PM can read one page
  on any of ~4,000 companies and know its governance posture without asking anyone.*
- **Phase 2 — Make it a workflow (the "no analyst" phase).** (a) **Prices** — EOD
  closes and market caps, the single biggest unlock: turns levels into ratios
  (cross-holdings as % of market cap, buyback yield, PBR screens). (b) **Parse what we
  already capture**: 5% filings (activist stakes), tender offers, AGM voting results.
  (c) **Watchlists, alerts, weekly digest.** *Exit test: a fund runs a 20-name Japan
  book for a quarter with no local analyst and misses no disclosed event.*
- **Phase 3 — Be the agent's data layer.** Harden the API and MCP surface as the
  product for quant teams and internal AI: point-in-time everywhere, bulk export,
  documentation good enough that an agent can self-serve. Licensing conversations
  (screeners, terminals) become possible here.
- **Phase 4 — Second market (option, closed by default).** Opens only on a paying
  customer or a board-level decision. The playbook by then is written: capture →
  extract → resolve → dossier → screens → watch.

## 6. Business model

| Tier | Who | Gets | Price shape |
| --- | --- | --- | --- |
| Free | Academics, Substack readers | Charts, citable URLs, single-company pages, BibTeX | ¥0 — this is marketing and the citation moat |
| Pro | Individual professionals | Screens, CSV exports, watchlists + alerts | ~$50–150/mo, self-serve |
| Institutional | Sell-side, buy-side, quant | API + MCP, bulk/point-in-time, redistribution rights in notes | $10–50k/yr, sold in the order the macro plan already set |

The anchor in every institutional conversation: the alternative is a $300k+ hire or a
Japanese-language database they cannot read. We are priced as a rounding error against
either.

## 7. What we deliberately do not do

- **No recommendations, no ratings, no "buy" lists.** Screens rank facts; the reader
  concludes. This is the regulatory line (data/publishing, not investment advice) and
  the credibility line, and it is permanent.
- **No financials/estimates/news terminal.** Vendors do that well; we integrate the
  minimum (prices) needed to make our own data ratio-ready, and stop.
- **No execution, no brokerage, nothing that touches orders.**
- **No LLM answering on our own site** (ASK_ENABLED stays off, settled decision) — the
  customer's agent consumes our MCP; we never speak for the data in prose we can't
  stand behind.
- **No second market by drift** (§2).

## 8. Honest risks

1. **The tagline oversells.** "Without a Japan analyst" is a sharp pitch and a wrong
   literal claim — funds still need judgment and meetings. Mitigation: the "first
   analyst, not the last" framing in every serious document; the marketing may be
   sharper than the contract, never the reverse.
2. **One person, five layers.** The roadmap survives only if phases ship sequentially
   and capture keeps running unattended. Uptime of the boring jobs *is* the product.
3. **Prices introduce a new dependency class.** Everything so far is free public
   filings; a price feed has licensing terms. Choose a source whose redistribution
   terms fit the API tier *before* building screens on it.
4. **Translation liability.** English renderings of free-text purposes must always be
   labelled as our translation with the Japanese alongside — one mistranslation quoted
   in a fund letter is a credibility event.
5. **The trade could cool.** If governance reform loses steam, the *urgency* fades but
   the dataset doesn't — boards, pay, ownership and buybacks are permanent furniture of
   the market. The macro platform is the hedge on the equity story and vice versa.

## 9. Open decisions (need your call, not code)

1. **Price source** for Phase 2 — which EOD feed, and confirm its redistribution terms
   fit the institutional tier.
2. **Digest identity** — does the weekly English digest live inside the Substack (one
   audience, one brand) or as a product feature behind Pro (revenue, lock-in)? This
   shapes Phase 2 significantly.
3. **Naming** — whether the equity side keeps living under "Japan Data Observatory" or
   gets its own product name for the fund audience.
4. **Korea research budget** — zero for now, or a fixed few hours to verify DART (the
   Korean EDINET) feasibility so Phase 4 has a priced option on the shelf?
