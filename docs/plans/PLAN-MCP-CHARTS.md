# PLAN — Charts Through MCP: From Answer to Deliverable

> **Status:** PROPOSAL v1 — awaiting approval. No code written, no schema touched.
>
> **Scope decision:** Make the MCP conversation a full product experience: a user asks in
> plain language ("compare tourist growth, China vs South Korea, 2019–2023"), and gets a
> finished chart plus the data — first in our house style via permanent chart links, later
> honouring preferences and firm branding they have saved with us.
>
> **Product decision:** Three layers, strictly ordered by what they require. **C1** needs no
> login and no core change — chart links and CSV on the free anonymous MCP. **C2** (personal
> defaults) and **C3** (organization themes, branded exports) both require accounts, which is
> the same plumbing a paid Pro tier needs anyway — so preferences and branding are framed as
> features of the authenticated tier, never bolted onto the anonymous endpoint.
>
> **One-liner:** Every chart a user's AI assistant produces from our data is one click from
> a permanent, citable page on our platform — and for paying firms, one click from an export
> in their own template with the provenance intact.
>
> **Companion docs:** [PLAN-PLATFORM-VISION.md](PLAN-PLATFORM-VISION.md) (umbrella) ·
> [PLAN-JAPAN-MACRO-OBSERVATORY.md](PLAN-JAPAN-MACRO-OBSERVATORY.md) (tiers, customers) ·
> [../../CLAUDE.md](../../CLAUDE.md) (golden rule, trust contract, design rules)

---

## 1. The experience we are selling

A sell-side economist connects our MCP server to Claude (paste one URL, no install — that
already works) and types:

> *"Draw me a comparison of tourist growth between China and South Korea, 2019 to 2023."*

What should happen, in order of ambition:

1. **The assistant draws a sensible chart immediately** from our data — and when the user
   asks *"what kind of chart should this be?"*, the advice it gives matches our house
   methodology (growth comparisons → indexed lines; never mix levels with growth; missing
   is a gap, never zero). We control this through the server instructions the assistant
   reads at connect time.
2. **The reply carries two links from us:** the same view as a permanent chart page on our
   platform, and the data as CSV with the metadata header. The chart link is the Substack
   rule applied to MCP — every chart that circulates in a chat is a citable URL that leads
   back to us.
3. **The chart respects the user's saved defaults** — preferred palette slot, chart size,
   date-range habits — stored against their account.
4. **The export carries their firm's brand** — font, palette, logo, footer template —
   because a bank economist does not put someone else's house style in a client note.
   White-label output is a standard premium feature at data vendors; it is what an
   institutional price is charged for.

Layers 1–2 are distribution (free tier, funnel). Layers 3–4 are monetisation (Pro tier).

## 2. What already exists (verified against the code, 2026-09-01)

| Piece | State today | Gap |
| --- | --- | --- |
| MCP server | Live: stateless JSON-RPC at `/mcp`, 15 tools, anonymous, rate-limited ([app/mcp.py](../../observatory/app/mcp.py)) | No auth, no notion of a user — by design, and C1 keeps it that way |
| `cite` URLs | Every tool response already carries one ([app/tools.py](../../observatory/app/tools.py)); server instructions tell the assistant to link it | Cite links point at a page, not always at the *exact requested view* (series selection, range, comparison mode) |
| URL encodes view state | Standing design rule; the chart pages restore state from the URL | The tools do not yet *construct* deep view-state URLs on request |
| CSV export | Every chart page has Download CSV with the metadata header block — **generated in the browser**, not by the API | No server-side CSV: an MCP reply cannot link a file, only a page with a download button |
| Chart-type advice | Nothing — assistants improvise | Add a house-methodology section to the MCP `INSTRUCTIONS` |
| Accounts / API keys | None anywhere on the platform | Prerequisite for C2 and C3; same prerequisite as the Pro tier |
| Themes / branding | Six `--obs-*` palette slots in `tokens.css`, house style only | No per-user or per-firm theming, and the public pages should stay that way (§4) |

**Honest position:** C1 is small — the platform was built with citable URLs and formula
disclosure from day one, so "charts through MCP" is mostly *finishing plumbing that already
exists*. C2/C3 are a real project because identity is, not because theming is.

## 3. Waves

| Wave | Content | Requires | Why here |
| --- | --- | --- | --- |
| **C1** | **Chart links + CSV + advice on the free MCP.** (a) A `get_chart_link` tool (or a `chart` URL added to existing tool responses) that builds a permanent deep-link encoding series, range, and comparison mode. (b) Server-side CSV — either `?format=csv` on the values endpoints or a small `/api/v1/{dataset}/csv` route — so a reply can link the file itself, with the same metadata header the pages produce. (c) A chart-methodology paragraph in the MCP `INSTRUCTIONS`. | Nothing new — no auth, no schema change | The distribution hook. Every MCP chat becomes a funnel of citable links back to the platform |
| **C2** | **Accounts + personal defaults.** API keys, a preferences record (palette slot, size, default ranges), authenticated MCP passes the key, chart links and exports honour the stored defaults. | Identity — the Pro-tier plumbing | First paid-tier feature that MCP users feel directly |
| **C3** | **Organization themes — branded exports.** A firm-level theme (palette, licensed fonts they supply, logo, footer template) applied to *exports only*: PNG, PowerPoint-ready images, embeds. Every user at the firm exports in it automatically. | C2, plus an org concept | The premium feature that justifies an institutional price; compliance and marketing at the customer like it, not just the economist |

C1 is worth shipping alone. C2 should not be built for preferences on its own — it ships
when the Pro tier ships, and preferences ride along.

## 4. Trust-contract and design-rule check

- **Our pages stay ours.** The permanent citable URLs keep the house style, always — the
  six-token palette, both themes, the whole design system. Nobody reskins the public site;
  that consistency *is* the brand. Custom styling applies to **exports only**.
- **Branding never strips provenance.** Whatever the theme: the source line, the
  official-vs-calculated distinction with its formula, and mandatory credit lines (the BOJ
  line is a legal obligation, JNTO's is a licence condition) appear on every export. A theme
  may restyle them, never remove them. This is non-negotiable — and a selling point: the
  customer's compliance desk gets provenance that cannot be stripped off.
- **Personal "colors" are palette slots, not arbitrary hex.** Free-choice colors would
  fight the readability and light/dark discipline the token rule exists for. Defaults mean:
  which slots, what size, what ranges. Arbitrary brand colors arrive only via C3 org
  themes, applied to exports, where the firm owns the output medium.
- **Fonts are licensed property.** We never ship a firm's proprietary typeface; the firm
  supplies font files under its own licence, and we apply them only to that firm's exports.
  Part of onboarding, not a surprise later.
- **Golden rule:** C1 touches no dataset schema and no `/api/v1/{dataset}/...` contract
  shape — a CSV *format* of an existing endpoint is an addition, not a change. C2/C3 add
  accounts and themes, which live beside the datasets, not inside them. If theming ever
  seems to need a column on the core tables, stop — it belongs in its own store.
- **MCP stays read-only and stateless in C1.** No sessions, no server-initiated streams.
  Authenticated MCP in C2 is the first departure and gets its own design pass.

## 5. What we deliberately do not build

- **No server-side chart rendering, no image blocks in MCP replies.** A rendering engine on
  the server buys static pictures at high cost; the assistant draws interactive charts fine,
  and our links carry the branded/citable version. Revisit only if MCP Apps (interactive
  embedded UI, the Anthropic/OpenAI extension) matures in the clients our customers use.
- **No reskinning of public pages, ever** — see §4.
- **No preferences on the anonymous endpoint** (cookies, fingerprinting, "remember me"
  hacks). Identity comes from an account or not at all.
- **No LLM of our own.** The assistant belongs to the user; `ASK_ENABLED` stays off. We
  supply data, links, and instructions — never generated prose.

## 6. Risks and open decisions

| Risk / decision | Treatment | Severity |
| --- | --- | --- |
| Deep-link URLs drift from what pages actually restore, and cite links land on wrong views | The URL-state contract becomes tested surface: a round-trip test per page (build URL → load → assert view) before `get_chart_link` ships | **High** |
| Assistants ignore instructions and misquote or badly chart the data | Instructions help but cannot compel; keep formulas and `calc` fields in every response so errors are traceable to the assistant, not to us | Medium |
| Server-side CSV diverges from the browser-generated CSV | One shared definition of the metadata header; the browser path eventually calls the same endpoint | Medium |
| C2 auth built ad hoc for preferences, then rebuilt for billing | C2 explicitly waits for the Pro-tier decision; this plan does not green-light account plumbing on its own | Medium |
| A firm's theme makes an export unreadable (contrast, tiny fonts) | Validation gates on themes at upload: contrast minimums, provenance block untouched | Low |
| Brand exports leak between firms | Themes scoped to org accounts; exports watermarked with the requesting account in logs | Low |

**Open decisions, needing your call rather than code:**

1. **C1 shape** — a new `get_chart_link` tool, or enrich every existing tool response with
   a ready-made `chart` deep link next to `cite`? (Fewer tools is simpler for assistants;
   a dedicated tool handles "chart X vs Y" requests more precisely.)
2. **Server-side CSV route** — `?format=csv` on existing endpoints or a parallel `/csv`
   path? Cosmetic, but it becomes public API contract either way.
3. **Whether C3 exports include PowerPoint-ready output** (sized PNG at deck resolution) in
   the first cut, or PNG/embed only. Sell-side workflow suggests PPT matters.
4. **Pricing posture for C3** — bundled in the institutional tier or priced as an add-on.
   Not needed until C2 is real; recorded so it is not decided by accident.

## 7. Definition of ready

**C1 build starts when:** (a) the C1-shape decision (§6.1) is made; (b) the CSV route
decision (§6.2) is made; (c) the URL-state round-trip test list is agreed (which pages,
which parameters).

**First slice (C1):** one dataset end to end — the user's own example. "China vs South
Korea arrivals, 2019–2023" asked through Claude returns the assistant's chart *plus* our
permanent chart link restoring exactly that view *plus* a CSV link whose header matches the
page download, with the JNTO credit line in all three places. Expand to the other datasets
only after that round-trips.

**C2/C3 start only with the Pro-tier decision** — they are recorded here so the account
design is built once, with themes in mind.
