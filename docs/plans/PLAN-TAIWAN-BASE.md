# PLAN — Taiwan Base: Visa Route, HK Structure, and the Scale-Up Map

> **Status:** PROPOSAL v1 — research + options, no decision taken. Sits beside
> [PLAN-PLATFORM-VISION.md](PLAN-PLATFORM-VISION.md); it changes no schema and no code.
>
> **One-liner:** Taiwan is the residency and engineering base, Hong Kong is the
> commercial base. The visa is not a reward for building a good product — it is a
> checklist. This document maps the checklist onto the product roadmap we already have,
> so that shipping the roadmap *is* the visa application.
>
> **Currency:** NTD figures are the legal thresholds. USD equivalents are approximate at
> ~NT$32/US$ and are indicative only.

---

## 1. The honest answer on qualification

**Can the product qualify?** Yes — but not by being good. Taiwan's Entrepreneur Visa
qualifies you on **one of eight enumerated boxes**, none of which is "I built a valuable
dataset." Three are reachable for us; the rest are not (patents, plant variety rights,
design/film awards, large government innovation grants).

| Path | What it actually requires | Our realistic read |
| --- | --- | --- |
| **A — Capital raised** | ≥ NT$2m (~US$62k) from a domestic/overseas VC, or from a government-approved fundraising platform | Available only if we take outside money. Cleanest proof, worst dilution-per-dollar at this stage. |
| **B — Incubator / startup park** | Stationed within one year at an approved park or incubator, with their recommendation letter | **Lowest-friction path.** Costs desk fees and a review, not equity. Also supplies the "innovation" endorsement the reviewer wants. |
| **C — Own enterprise** | Set up a Taiwan enterprise recognised as having *innovation capability*, invest ≥ NT$1m (~US$31k), and serve as its legal representative, manager or director | **Most controllable path.** NT$1m is a real but small cheque. The risk is entirely in the discretionary "innovation capability" judgement. |

**Initial validity is 2 years**, extendable in blocks of up to 2 years without leaving
Taiwan; since 1 July 2023 the application is filed online. Teams of fewer than three may
apply as a group (under path C, members invest ≥ NT$1m collectively).

### The renewal gate is the real bar — and it is low

At extension the *enterprise* must meet **at least one** of:

- **Sales revenue ≥ NT$3m** (most recent year, or 3-year average) — ≈ **US$92k ARR**
- **Operating expenses ≥ NT$1m** (most recent year, or 3-year average) — ≈ **US$31k/yr**
- **≥ 3 full-time employees of Taiwanese nationality**
- Other economic contribution recognised by the industry authority

This is the number that should anchor planning. **NT$3m of revenue is two Institutional
contracts** at the $10–50k/yr price shape already set in the vision plan — or roughly 50
Pro seats. **NT$1m of operating expense is one part-time Taiwan engineer plus a desk**,
which we would spend anyway. In other words: *the extension is nearly free if we execute
Phase 1–2 at all*; the hard part is the initial grant, which turns on the discretionary
innovation review.

### The alternative that is probably faster: the Employment Gold Card

Given a sell-side equities background, the **Gold Card (Field of Finance)** deserves a
serious look before the Entrepreneur Visa. Six qualifying paths exist; three are
plausible for us:

- Monthly salary **≥ NT$160,000** in a recent role (evidenced by tax statement or
  employment certificate) — the cleanest if the pay history supports it;
- **3 years in a managerial position** at a domestic or foreign financial institution
  **plus** CFA / CFP / FRM / CIA;
- **3 years** of financial-professional experience in a government-promoted sector
  (**fintech, digital economy, asset management** are named) with concrete achievements
  — the Observatory is squarely fintech/digital-economy evidence.

Why it may be the better first move: it is a **1–3 year open work permit** granted on
*your* record rather than the company's; it carries a **5-year tax break** (half of salary
income above NT$3m excluded, and overseas income exempt, in years you are resident 183+
days); and it runs a **3-year path to permanent residency**. It does not stop you
incorporating and running a Taiwan company.

**Recommended sequencing:** Gold Card for the person → incorporate the Taiwan entity when
there is revenue or a hire to justify it → keep the Entrepreneur Visa as the fallback if
the Gold Card evidence does not stand up. Do not run both applications simultaneously.

---

## 2. The Hong Kong office: a structuring decision, not an afterthought

Hong Kong is the right commercial base — the buy-side clients in §1 of the vision plan
are physically there, and the Substack audience skews there. But **how the HK entity
relates to the Taiwan entity is a regulatory choice with real consequences.**

- Inbound investment into Taiwan needs prior approval from the **Department of Investment
  Review (DIR), MOEA**, assessed case by case.
- The decisive test for anything routed through Hong Kong: a company in which PRC
  individuals or entities hold, **directly or indirectly, more than 30%** of the shares —
  or exercise **effective control** — is classified as **PRC-funded**, whatever
  jurisdiction it is incorporated in. The 30% test is applied at *each* upper-level
  shareholder.
- PRC-funded status would be close to fatal for us specifically: we are an information
  and data-services business, exactly the category that draws scrutiny.

**Design rules that follow:**

1. Keep the **HK entity's cap table free of PRC-domiciled shareholders**, and keep the
   evidence to prove it. If you ever take outside money, this constraint prices into the
   term sheet before the cheque, not after.
2. **Prefer holding the Taiwan entity personally** (or via a clean non-HK holdco) rather
   than under the HK company, unless there is a tax or contracting reason not to. It
   sidesteps the HK/Macau investment-approval track entirely and removes a discretionary
   step from the visa timeline.
3. Decide **where revenue is contracted** before the first institutional invoice.
   Contracting from HK and paying a Taiwan service entity on cost-plus is conventional and
   clean — but note it puts revenue in HK while the *Taiwan* renewal test looks at the
   Taiwan entity. If you plan to renew on revenue rather than opex or headcount, the
   Taiwan entity must book real revenue. **Choose the renewal test first, then structure.**

---

## 3. Division of labour

| | Taiwan | Hong Kong |
| --- | --- | --- |
| **Purpose** | Residency, engineering, data ops | Clients, contracts, brand |
| **Holds** | Ingest and extraction pipelines, dev, the archive's operational home | Sales, the Substack, institutional agreements |
| **Why there** | Cost, engineering talent, Gold Card tax treatment, 3-year PR path | Buy-side density, English contracting, time zone with Tokyo |
| **Headcount first hires** | Data engineer; Japanese-capable extraction analyst | None until revenue; founder-sold |

The uncomfortable truth to keep in view: **neither office is in Tokyo**, and the product
is Japanese primary documents. That is survivable because the sources are all remote and
digital, but it is a real gap for the "management meetings and channel checks" half of
the market. The vision plan already concedes that half ("first analyst, not the last") —
this is the same line, restated geographically.

---

## 4. The scale-up map: milestones that are simultaneously visa evidence

Each phase maps to the vision plan's existing phases. Nothing here adds product scope —
it re-labels what we were doing anyway with the evidence it generates.

**M0 — Pre-application (0–6 months). *Make the record legible.***
Ship Phase 1 (unified company dossier, coverage and methodology pages public), keep the
capture jobs running unattended, keep the Substack cadence. Produce, as a by-product:
public URLs with a citation trail, an uptime record for the daily capture, an audience
number, and a written architecture note. *Visa value:* this is the entire evidentiary
basis for "innovation capability" (path C) or "concrete achievements in fintech/digital
economy" (Gold Card path 5). **Exit test:** a reviewer with no finance background can
open three links and see a working, original, running system.

**M1 — Entry (6–12 months). *Get the person in.***
File the Gold Card on the strongest single path. In parallel, price the incubator/park
option (path B) as the fallback and for the local network it brings. Incorporate the
Taiwan entity only when M2 revenue or a first hire makes it necessary. *Do not incorporate
early "to look serious" — an idle entity has filing obligations and proves nothing.*

**M2 — First revenue (12–24 months). *Clear NT$3m or don't need to.***
Execute vision Phase 2: prices, then 5% filings / tender offers / AGM results, then
watchlists, alerts and the weekly digest. Sell in the stated order — sell-side economists
first, then buy-side data teams. Two institutional contracts clears the revenue test; one
Taiwan engineer clears the expense test; either alone satisfies the extension.
**Exit test:** a fund runs a 20-name Japan book for a quarter through us and misses no
disclosed event.

**M3 — Become infrastructure (24–48 months). *The agent's data layer.***
Vision Phase 3: hardened API and MCP, point-in-time everywhere, bulk export, docs an
agent can self-serve on. This is where "big" actually lives — not more pages, but
**being the substrate other people's products sit on**: fund AI stacks, screeners,
terminals, academic citations. Three full-time Taiwanese employees by here would satisfy
the headcount test permanently and put PR/APRC in reach on the residency clock.

**M4 — Second market (optional, deliberately closed).**
Vision Phase 4 names **Korea** as the analog (chaebol governance, Value-up). Taiwan is
the tempting alternative *because it flatters the visa* — a Taiwan dataset makes the
"contribution to Taiwan" case trivially. **Resist letting the visa choose the roadmap.**
Korea is the better product decision; a small Taiwan surface (TWSE governance or CBC/DGBAS
price data) is defensible only if it is cheap, additive, and explicitly framed as
regulatory goodwill rather than strategy. Either way, the trigger stays what the vision
plan says it is: a paying customer, or a board-level decision — never drift.

---

## 5. What "big" means here, stated plainly

Three honest ceilings, in ascending order:

1. **Lifestyle data business (very likely reachable).** ~US$150–400k/yr from a handful of
   institutional seats plus Pro. One or two staff. Clears every visa test forever. This is
   the base case and it is a good outcome.
2. **Category owner for Japan governance data (plausible, 3–5 years).** Low seven figures
   of ARR, 5–15 staff, the reference source cited in fund letters and academic papers. The
   moat is the one the plans already name: the archive, the resolved entity graph, the
   reverse views, and workflow lock-in from watchlists.
3. **Asia's primary-source data layer (the option, not the plan).** Japan + Korea +
   selectively others, sold mainly through API/MCP to funds and to other vendors. This is
   an acquisition-shaped outcome (a terminal, a screener, or an index provider buys the
   archive). It requires outside capital, which reopens the HK cap-table constraint in §2.

The binding constraint is not the visa and not the market — it is **one person, five
layers** (vision plan §8.2). The first hire in Taiwan buys down that risk more than any
feature does.

---

## 6. Open decisions (need a call, not code)

1. **Gold Card or Entrepreneur Visa first?** Recommendation: Gold Card, on the strongest
   Finance path — faster, personal, tax-advantaged, and does not depend on a discretionary
   innovation review.
2. **Which renewal test do we intend to pass** — revenue, opex, or headcount? This
   determines whether Taiwan books revenue (§2.3), and should be decided *before* the
   first institutional contract is drafted.
3. **Where the IP sits.** The archive is the asset. Whichever entity owns it should be the
   one that survives a restructuring, and it should be documented before the first hire.
4. **Do we ever take outside money?** If yes, the PRC-ownership constraint (§2.1) is a
   term-sheet clause, not a diligence surprise.
5. **Professional advice.** Everything above is desk research from official sources. The
   innovation review, the DIR track, and the tax treatment each turn on facts a Taiwan
   immigration/corporate lawyer and a cross-border tax adviser should confirm before
   money moves.

---

## 7. Sources

- SMEA/MOEA, *Taiwan Entrepreneur Visa* — criteria, 2-year validity, extension thresholds:
  <https://www.sme.gov.tw/article-en-2618-7911>
- Startup Portal Taiwan, *Visa and Work Permit*: <https://startup.sme.gov.tw/en/permit>
- Taiwan Employment Gold Card, *Field of Finance*:
  <https://goldcard.nat.gov.tw/en/qualification/field-of-finance/>
- Taiwan Employment Gold Card, *Tax* (5-year benefit, NT$3m threshold, 183 days):
  <https://goldcard.nat.gov.tw/en/tags/tax/>
- MOEA Department of Investment Review, FAQ:
  <https://www.moea.gov.tw/Mns/dir_e/Investment/DirQuestionsAnswers_En.aspx?menu_id=42942>
- White & Case, *Foreign direct investment reviews: Taiwan* (30% PRC ownership test):
  <https://www.whitecase.com/insight-our-thinking/foreign-direct-investment-reviews-2024-taiwan>

**Verification status:** thresholds and criteria above are quoted from the official pages
listed. The definition of "innovation capability" under the Entrepreneur Visa is set in
the MOEA review principles and is **not** reproduced in the English pages — treat it as
the one genuinely unverified element of this plan.
