# PLAN — Japan Macro Observatory

> **Status:** PROPOSAL v2 — awaiting approval. Supersedes the Asia-breadth plan (v1, this
> file when it was named `PLAN-ASIA-EXPANSION.md`).
>
> **Scope decision:** **Go deeper on Japan, not wider across Asia.** Japan price statistics
> *plus* Bank of Japan monetary and balance-sheet data, in one platform. Hong Kong is
> demoted to an option, taken only if a paying customer asks for it.
>
> **Product decision:** This is an **institutional data product** — sold to sell-side and
> buy-side research and data teams — not a consumer dashboard. The Substack is the
> acquisition channel, not a separate business.
>
> **One-liner:** The complete, reproducible, point-in-time record of Japanese macro data —
> deeper than any terminal on Japan, with the formula and the archived source file behind
> every number.
>
> **Companion docs:** [PLAN-JAPAN-INFLATION-OBSERVATORY.md](PLAN-JAPAN-INFLATION-OBSERVATORY.md)
> (v1 product strategy — **partly superseded**, see §8) ·
> [IMPL-JAPAN-INFLATION-OBSERVATORY.md](IMPL-JAPAN-INFLATION-OBSERVATORY.md) (architecture)

---

## 1. Strategy on one page

**Why depth beats breadth.** Selling broad Asian coverage means competing with CEIC, Haver
and Macrobond, who already sit on every macro desk, have decades of licensing relationships
and staff coverage teams. Breadth has no moat — anyone can scrape a statistics agency. Depth
on one market, with provenance and vintage history, does.

**Everything we ingest is free and public.** e-Stat, the BOJ API, and any future source. We
are not selling access; we are selling *reproducibility, depth, and history*. That must be
true enough to survive the first question in every institutional meeting: "why not use what
we already pay for?"

**Three answers that survive that question:**

1. **Point-in-time vintages** — what the number looked like *before* revision (§2). The only
   one of the three that gets stronger with time.
2. **Depth the terminals don't carry** — 582 individually priced CPI items, BOJ JGB holdings
   by individual issue, the 2020→2025 base mapping.
3. **Reproducibility** — every number traceable to an archived source artefact and its hash.

**Customers, in the order we pursue them:**

| # | Segment | Why this order |
| --- | --- | --- |
| 1 | **Sell-side economists / strategists** | Publish constantly, cite sources, clear a few hundred dollars a month without procurement — and their notes are read by the buy-side. Every sell-side user is a free referral. |
| 2 | **Buy-side data and quant teams** | Evaluate on the API and vintage history, not the UI. Longest cycle, best revenue. Approach second, with references. |
| 3 | **Academics** | Near-zero revenue; citations make us the canonical source. Free tier, trivial BibTeX export, low support burden. Treat as marketing. |
| 4 | **Discretionary macro PMs** | Highest willingness to pay, hardest to reach cold. This is who the Substack is for. |

**Distribution.** Institutions do not buy from unknown vendors via cold outreach; they buy
from people whose work they already read. The *Asia Economics Observations* Substack is the
top of the funnel: every chart in a post is a permanent, clickable, reproducible URL on the
platform. The existing design rule — *URL encodes the full view state so any view is
citable* — is that integration, already specified.

## 2. The vintage moat (P0)

Backtesting any macro strategy requires knowing what the data looked like **at the time**,
before revisions. Almost every free source publishes only the latest revised series. Our
schema already stores immutable releases with the raw file and its SHA-256.

The property that matters: **vintage history can only be accumulated going forward.** Every
month the pipeline runs, the asset compounds, and a competitor starting in 2028 can never
buy back the 2026 vintages. This is the only moat on the list that time strengthens.

Three consequences, all binding:

- **Run the ingest reliably starting now**, before anyone is paying. Uptime is the product.
- **A vintage is immutable.** A bug that silently overwrites a stored release destroys the
  exact thing we sell. This needs its own validation gate, not just the existing ones.
- **Expose it.** The schema stores vintages; nothing in `/api/v1` surfaces them. Until it
  does, the moat is invisible and unsellable.

## 3. Coverage ladder — Japan

Publish this on the site. Being explicit about what is and is not covered is itself a
selling point, because terminals never tell you.

- **L1** headline + core CPI, full history · **L2** major groups with weights ·
  **L3** full item detail · **L4** regional / sub-national · **L5** adjacent price
  statistics (PPI, services, import prices) · **L6** monetary, balance-sheet and
  flow-of-funds

**Today: L3.** 822 series live (78 `cpi-jp` + 744 `cpi-jp-items`), monthly, January 1970 to
June 2026.

## 4. Waves

| Wave | Content | Core change? | Why here |
| --- | --- | --- | --- |
| **J1** | Three ready-to-adapt e-Stat sibling tables: goods/services splits (`000032103845`), seasonally adjusted (`000032103846`), 1946– all-items-less-imputed-rent (`000032103843`) | **None** | Cheapest depth available — same CSV layout, same parser. Proves the adapter pattern a third time before we touch the core |
| **J2** | **BOJ monetary and balance-sheet data** via the new API: `BS01` accounts, `MD09` stock **and flow** tables, `MD01` monetary base, `MD06` operations | **Yes — §5** | The QT story (§6). Highest reader interest, and the API launch made it cheap |
| **J3** | **BOJ price statistics** — CGPI (`PR01`, 907 commodities), SPPI (`PR02`, 152), IOPI (`PR03`), FD–ID (`PR04`) | Reuses J2 | Same API, same adapter, ~1,059 more series. Completes the pass-through chain: import → producer → services → consumer prices |
| **J4** | **Tokyo advance CPI** (~2–3 weeks ahead of national) + regional/prefectural indices | Minor | Tokyo advance is a genuine release-day edge and the input to any future nowcast |
| **J5** | **JGB holdings by individual issue** (XLSX) + Flow of Funds (`FF`) ownership by sector | Yes | The two genuinely differentiated datasets — which bonds the BOJ has cornered, and who absorbs supply as it withdraws. Neither is in the terminals in usable form |
| **J6** | Retail Price Survey (yen price *levels*), Monthly Labour Survey (wages) | Yes — measure type | New measure type; enforces the price-level vs price-change separation |

**Vintage capture applies from J1 onward** — every wave stores releases immutably from its
first ingest, not retrofitted later.

J2 and J3 share one BOJ adapter and one set of core changes; keep them adjacent.

## 5. Core changes required

Adding BOJ data breaks assumptions that CPI-only hid. These land once, in J2.

1. **Non-index measure types.** BOJ data is **levels in ¥100 million and flows that go
   negative** (monthly JGB runoff is negative — see §6). Validation gates that assume
   index-like positive values will reject valid data. `series.weight_per_10000` is
   meaningless for these series.
2. **Mixed frequency.** `observations` is keyed `(series_id, period)` with no frequency
   column. BOJ publishes daily (`MD06`), every ten days (BOJ Accounts), monthly, and
   quarterly (`FF`) — so `2005` and `200501` collide on the same series. Store frequency
   explicitly or discard non-primary frequencies at parse time; decide deliberately.
3. **Measure-type separation.** Price *change*, price *level*, *stock* and *flow* must never
   be ranked or aggregated together. Extends the rule the v1 plan already set for prices.
4. **Vintage/point-in-time API surface.** The commercial product of §2. Requires a
   `/api/v1/.../vintages` shape and an as-of query parameter.
5. **Source registry with enforced terms.** `sources.license_note` is advisory today. Make
   redistribution terms required and checked before ingest — the BOJ imposes two obligations
   (§6) that must be discharged in the product, not in someone's memory.

**Deferred until actually needed:** localised-name generalisation (the `name_ja` /
`agency_ja` columns) and any COICOP classification map. Both were driven by Hong Kong; with
Hong Kong demoted they are not on the critical path.

**This is an approved exception to the golden rule**, made once, deliberately, before J2 —
not discovered during it.

## 6. BOJ source facts (verified 2026-08-06)

Confirmed by hitting the live API, not assumed:

- **Endpoint:** `https://www.stat-search.boj.or.jp/api/v1/getDataCode?format=json&lang=en&db={DB}&code={SERIES}`
  — plus `/getMetadata` (series catalogue per DB) and `/getDataLayer` (hierarchy). JSON or
  CSV, gzip supported, **no API key or registration**. Launched 18 February 2026.
- **Databases of interest:** `BS01` BOJ Accounts · `MD01` Monetary Base · `MD06` Market
  Operations · `MD09` Monetary Base and the BOJ's Transactions (stock **and** flow) ·
  `FF` Flow of Funds (~34,700 series — ingest against a named list, never wholesale) ·
  `FM05`/`FM06` bond issuance and trading by purchaser · `PF02` National Government Debt ·
  `OB01`/`OB02` government transactions and collateral · `PR01`–`PR04` price statistics.
- **Two obligations, both mandatory:** notify the Research and Statistics Department by
  email on release, and display the credit line *"This service uses the API provided by the
  'Bank of Japan Time-Series Data Search.' The Bank of Japan does not guarantee the content
  of the service."* No redistribution restriction; prohibited acts are limited to
  interfering with the API and excessive request frequency.
- **Stricter terms elsewhere:** the *Measures of Underlying Inflation* research data
  (trimmed mean, weighted median, mode, diffusion index) is published as XLSX **outside**
  the API and directs users to seek permission for commercial reproduction. Clear that
  before building on it — it is otherwise ideal, being the official version of the breadth
  statistics we compute ourselves, and a free validation mirror for them.

**Verified round-trip, `MD09`:** BOJ JGB holdings peaked at **¥597.5tn in November 2023**
and stood at **¥518.3tn in June 2026**. Monthly net flow moved from **+¥2.66tn/mo (2023)**
to **−¥0.67tn (2024)**, **−¥3.00tn (2025)**, **−¥4.34tn (2026 H1)**. Levels are official BOJ
figures; the peak-to-date decline (−¥79.2tn, −13.3%) and the monthly averages are derived
and must carry their formula, not an official badge.

## 7. What we are explicitly not building

- **The Ask / LLM feature stays off — permanently for this product.** Institutional users
  will not trust an LLM over the numbers, and it is a support and credibility liability.
- **Broad Asia coverage.** Hong Kong sources were verified and are cleanly licensed for
  commercial redistribution (`censtatd.gov.hk` JSON API; tables `510-60001`–`510-60004`;
  max depth 13 COICOP divisions, headline monthly back to July 1974) — on hold until a
  paying customer asks.
- **Consumer dashboard polish** beyond what makes a chart publishable in the newsletter.

## 8. Tension with the v1 product plan

[PLAN-JAPAN-INFLATION-OBSERVATORY.md](PLAN-JAPAN-INFLATION-OBSERVATORY.md) remains correct
on the trust contract, the platform-generality rule and the risk register. It is **out of
date** on: the free/Pro/API/Enterprise tier ladder (the funnel now runs through the
Substack, and the paid tier should be tested there before any accounts system is built), the
"journalists and public as acquisition funnel" framing, and the inflation-only scope.
Resolve by editing that doc once this plan is approved — not by keeping two contradictory
strategies.

## 9. Risks and open decisions

| Risk / decision | Treatment | Severity |
| --- | --- | --- |
| A bug overwrites a stored vintage, destroying the moat | Dedicated immutability validation gate before J2; vintages never updated in place | **High** |
| No institutional track record — the binding constraint, not the data or the code | Substack first; sell-side before buy-side; academics for citations | **High** |
| Uptime: a data vendor that goes dark is finished | Monitoring and alerting before the first paying customer, not after | **High** |
| Five core changes land at once in J2 | Own milestone, Japan CPI live and re-validating green throughout, rollback path | **High** |
| `FF` is ~34,700 series — an order of magnitude more than everything live today | Named-series allowlist; never ingest wholesale | Medium |
| BOJ obligations (notify + credit) forgotten at launch | Encode in the source registry and the site footer, not in memory | Medium |
| Scope creep back toward breadth | Market #2 requires a written case that the Japan product has paying users | Medium |

**Open decisions:** whether to store or discard non-primary frequencies; the shape of the
vintage/as-of API; the Substack paid-tier price point; whether *Measures of Underlying
Inflation* is worth the permission request; which `FF` series make the allowlist.

## 10. Definition of ready

Build starts when: (a) J1 has shipped and re-validated green; (b) core changes 1–5 are
specified as a single migration with a rollback path; (c) the vintage immutability gate is
written; (d) the BOJ credit line and notification are drafted.

**First slice (J2):** BOJ JGB holdings and monthly flow end-to-end — API fetch, raw archive
with SHA-256, validation, our API, rendered chart — showing holdings against the November
2023 peak with the runoff pace, the derived figures carrying their formula, and the BOJ
credit line visible on the page and in the CSV export. Expand only after that round-trips.
