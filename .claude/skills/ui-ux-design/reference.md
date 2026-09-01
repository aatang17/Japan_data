# UI/UX Design — Detailed Reference

> Exhaustive specs behind the `ui-ux-design` skill procedure ([SKILL.md](SKILL.md)). Canonical home for
> the Observatory's visual rules. Read the matching section before building that surface. Once code
> exists, the token file and shared components named here are the source of truth for values; this doc
> mirrors them.

## General principle — density is the product

Professional data UI: precise, dense, credible. "Dense" means **high signal per screen**, _not_ tiny
text in packed grids. Density helps when **scanning and comparing many series**; it hurts when
**reading** methodology or explanation. Never sacrifice legibility for compactness.

Our users are pattern-matching against numbers they already half-know. They need more data per screen
than a consumer product would give them, laid out predictably enough that their eye lands in the same
place every release. Consistency of position beats novelty of layout, always.

## Reference products — what to take, what to leave

| Product | Take | Don't copy |
| --- | --- | --- |
| **FRED / ALFRED** | Series-page structure, permanent citable URLs, transformation dropdown (YoY / MoM / index / log), vintage-aware history, source line on every chart, one-click export and embed | Dated typography, cramped chrome |
| **Bloomberg Terminal** | Information density, tabular monospace numerics, keyboard-first navigation, consistent field positions | 1990s chrome, black+amber+rainbow palette, all-caps everything, jargon labels |
| **Koyfin** | Modern macro-dashboard layout, watchlists, chart interaction, comparison workflows | Occasional filled-pill overuse, cluttered defaults |
| **Stripe Dashboard** | Restraint, table craft, loading/empty/error states, stat-tile discipline, plain-language operator copy | Payments-specific nav patterns |
| **Trading Economics** | Indicator and country page structure, release calendar, clear forecast-vs-actual labelling | Ad density, page clutter |
| **Macrobond** | Chart annotation, recession/event shading, rich series metadata display | Desktop-only complexity |
| **Datadog / Grafana** | Time-series interaction, synced crosshairs, dashboard composition | Ops-specific density, dark-only assumptions |
| **Our World in Data / Datawrapper** | Public-facing chart clarity, source attribution, embed and download affordances | Not dense enough for professional users |

House style sits between FRED's rigour and Stripe's polish. When a rule is ambiguous, ask: _would a PM
put a screenshot of this in front of a client?_

## Colour system

Never hard-code a hex. All values below are tokens.

### Interface

| Token | Light | Use |
| --- | --- | --- |
| `--obs-primary` | `#1a4d8f` | Buttons, links, primary series |
| `--obs-primary-dark` | `#123a6d` | Hover |
| `--obs-ink` | `#0f172a` | Primary text, key figures |
| `--obs-text` | `#334155` | Body text |
| `--obs-text-muted` | `#64748b` | Labels, axis text, secondary |
| `--obs-border` | `#e2e8f0` | Borders, dividers |
| `--obs-grid` | `#eef2f7` | Chart gridlines |
| `--obs-surface` | `#ffffff` | Panels |
| `--obs-surface-subtle` | `#f8fafc` | Row hover, table header |

Three greys plus brand. Adding a fourth grey is a design smell.

### Filled navy chrome

The two surfaces that are filled navy with light text. Their foregrounds cannot be derived from the
body text tokens (those are dark-on-light), so each carries its own `ink` / `muted` pair.

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--obs-header-bg` | `#1a4d8f` | `#16406f` | Site header bar |
| `--obs-header-ink` | `#ffffff` | `#f1f5f9` | Brand, active nav item |
| `--obs-header-text` | `#c5d7ec` | `#aac3de` | Inactive nav items |
| `--obs-header-muted` | `#aec6e1` | `#a9c2dd` | As-of, secondary header text |
| `--obs-header-accent` | `#8fbde8` | `#7fb3e3` | Active-nav underline |
| `--obs-header-border` | `rgba(255,255,255,.28)` | `rgba(255,255,255,.16)` | Header base rule, toggle outline |
| `--obs-band-bg` | `#1a4d8f` | `#16406f` | Section header band |
| `--obs-band-ink` | `#ffffff` | `#f1f5f9` | Section title text |
| `--obs-band-muted` | `#c5d7ec` | `#a9c2dd` | Right-side note inside a band |

**One navy, used at both levels** — the header bar and the section band are the same fill. Never a
second blue for chrome. In dark mode the navy goes *deeper*, never lighter: the dark-mode
`--obs-primary` is a light blue, and a light-blue bar on a dark page glows and fails white-text
contrast. Foreground tokens are per-surface even though the fill is shared, because they are tuned
against that fill — see the seam and contrast rules below.

**Two filled navies that touch must show a seam.** With one shared fill, a section band scrolling under
the sticky header merges into a single navy slab. Give the header
`border-bottom: 1px solid var(--obs-header-border)`: a translucent-white rule is invisible against the
white page and only resolves into a hairline where the two navies meet. Do not reach for a `box-shadow`
here — it is an anti-AI-tell reject. The band's side inset against the full-bleed header helps, but it
does not separate the top edge on its own.

**Re-check contrast whenever a filled surface changes value.** Lightening the header from `#123a6d` to
`#1a4d8f` pushed the old muted foreground to 4.07:1 and had to be lifted to `#aec6e1` (4.8:1). A fill
change is a foreground change; verify every `-text` / `-muted` token on it clears 4.5:1.

### Categorical series palette (max 6, in this order)

| Slot | Token | Value |
| --- | --- | --- |
| 1 | `--obs-series-1` | `#1a4d8f` (blue) |
| 2 | `--obs-series-2` | `#c2410c` (burnt orange) |
| 3 | `--obs-series-3` | `#0f766e` (teal) |
| 4 | `--obs-series-4` | `#a16207` (amber-brown) |
| 5 | `--obs-series-5` | `#475569` (slate) |
| 6 | `--obs-series-6` | `#9d174d` (maroon) |

Assign by **stable series identity, not draw order** — headline CPI is always slot 1 everywhere on the
platform, so a user reading two charts side by side doesn't have to re-learn the legend. Beyond 6
series, stop adding colours: switch container (Step 1) or grey out the non-focused series and colour
only the selection.

### Diverging scale (contributions, surprises, changes)

Cool → warm, never red/green: `#1a4d8f` → `#7ba7d4` → `#f1f5f9` → `#e8a87c` → `#c2410c`.
Always print the sign alongside; colour is reinforcement, never the sole encoding.

### Sequential scale (heatmaps, intensity)

Single-hue blue ramp from `--obs-surface-subtle` to `--obs-primary-dark`. No rainbow, no viridis-style
multi-hue ramp in product surfaces.

### Direction and status colour

- **Macro indicators: no P&L colour.** Rising inflation is not "bad red". Use `--obs-ink` for the value
  plus an explicit sign and a small arrow glyph. Colour communicates *series identity*, not *sentiment*.
- **Genuine gain/loss surfaces only** (portfolio, P&L, market reaction) may use directional colour. Note
  the inverted East-Asian convention (red = up, blue/green = down); make the convention a user setting
  and never let colour alone carry direction — always pair with sign and arrow.
- Colourblind safety: every direction, status, and series is distinguishable without colour — via sign,
  arrow, label, position, or dash pattern.

### Trust-label colours (outline-only)

| Label | Border + text |
| --- | --- |
| Official statistic | `#15803d` (green) |
| Platform-derived | `#1a4d8f` (blue) |
| Platform model / estimate | `#b45309` (amber) |
| Provisional | `#b45309` (amber) |
| Revised | `#7c2d12` (dark rust) |
| Quarantined / stale | `#b91c1c` (red) |

## Numeric formatting

The most-violated rules in any data product. Centralise these in one formatter module; never format a
number inline in a component.

- **Tabular numerals** on every numeric: `font-variant-numeric: tabular-nums`, or a mono face in dense
  grids. Non-tabular digits make a column visibly ragged and are an instant credibility loss.
- **Right-align numerics and their headers.** Left-align text. Decimal points line up.
- **Fixed precision per column**, never per value: rates `2.7%`, index `108.3`, contributions `0.24 pp`,
  weights `1,000`, yen `¥487`, ratios `0.83`. Trailing zeros are kept (`2.0`, not `2`).
- **Units in the column header**, not repeated per cell. A column must not mix units.
- `pp` for a difference between two percentages. Writing `%` there is a factual error, not a style one.
- **Thousands separators** always (`1,653`). Abbreviation (`1.7K`, `¥1.2bn`) only in a space-constrained
  stat tile, with full precision in the tooltip. Never in a table or an export.
- **True minus** `−` (U+2212) for negative numbers, not a hyphen. Explicit `+` on signed deltas.
- **Zero vs missing vs suppressed are three different renderings**: `0.0` / `—` (tooltip: why) /
  `·` with a suppression note. Never coerce one to another. This must hold in exports too.
- **Percent change vs percentage-point change vs index level** are separate measures — separate columns,
  separate axes, never one ranking.
- **Dates**: `2026-06` for reference months in tables (sortable, unambiguous), `June 2026` in prose,
  ISO-8601 with timezone for publication timestamps (`2026-07-18 08:30 JST`). Never `06/07/2026`.
- Locale-aware Japanese formatting where the Japanese UI is active, but the underlying export stays
  machine-parseable.

## Chart chrome

- **Plot height**: primary chart ≥ 320px desktop / ≥ 240px mobile. Sparklines 24–32px, no axes.
- **Axes**: y-axis labelled with unit; x-axis with year ticks (month ticks only when the range is < 3
  years). Axis text `--obs-text-muted`, 11–12px. Never rotate labels past 45° — drop ticks instead.
- **Gridlines**: horizontal only, 1px `--obs-grid`. No vertical gridlines. No plot border, no background.
- **Zero line**: when data crosses zero, draw a 1px `--obs-text-muted` line at zero, heavier than a
  gridline. Bars always start at zero; lines need not.
- **Line weight** 2px; series markers only when points are sparse (< ~30). No shadows, no glow, no
  gradient fill; an area tint at ≤12% opacity is allowed for a single-series chart.
- **Legend** above or right of the plot, never overlapping it. Direct-labelling the line end beats a
  legend when there are ≤4 series. Legend order matches the series' latest value, descending.
- **Tooltip / crosshair**: vertical crosshair, all series at that x-position, full precision, unit, date,
  and trust label. Synced across charts on the same page. Must remain fully on-screen at the right edge.
- **Annotations**: 1px vertical rule + short label for base changes, methodology breaks, and policy
  dates. A methodology break also breaks the line — do not draw continuity across it.
- **Shading**: recession/event bands in `--obs-surface-subtle`, behind gridlines, labelled once.
- **Source line** under every chart: agency · series ID · vintage · as-of · trust label. Required, small
  (11px, `--obs-text-muted`), and included in any PNG/SVG export.
- **Rebasing and transformation controls** sit above the chart, not buried in a settings menu: index/YoY/
  MoM/annualised, date range, base vintage, and comparison series.
- **Export** on every chart: PNG, SVG, CSV of the plotted data, and a permalink that reproduces the exact
  view (series, range, transformation, vintage) in the URL.

## Stat tiles

The headline row. One tile = one number a user came for.

- Structure, top to bottom: **label** (13px muted, Title Case, with unit) → **value** (28–32px,
  `--obs-ink`, tabular) → **delta** (13px, signed, with the comparison named: "vs prior month") →
  **as-of + trust label** (11px muted).
- A tile without a unit, an as-of, and a comparison basis is incomplete — that combination is an
  anti-AI-tell (Step 7, item 13).
- Max 4–6 tiles in a row; they wrap to 2 columns at 768px and 1 at 390px. Equal heights, equal widths,
  aligned baselines across the row — a tile with a longer label must not shift its value's baseline.
- Optional 24–32px sparkline at the tile's foot. No axis, no fill, one colour.
- Never put a gauge, dial, progress ring, or "score out of 100" in a tile.

## Data tables

The workhorse surface. Most professional users live here, not in the charts.

- **One idea per cell.** No paragraphs, sentences, nested lists, or raw messages.
- **Sticky header row and sticky first column** whenever the table scrolls. Column headers never wrap
  (`whitespace-nowrap`); truncate with a `title` if needed.
- **Condensed padding** `0.45rem 0.6rem`, 13px text, uppercase 11px column headers in `--obs-text-muted`.
- **Row hover** `--obs-surface-subtle`. Zebra striping only above ~15 rows, and then at ≤3% tint.
- Beyond ~7 columns, wrap in `overflow-x: auto` with the identity column pinned. Offer a column picker
  rather than silently truncating what the user can see.
- **Sort** on every numeric column; show the active sort direction; sorting must be stable and must place
  missing values last in both directions (never treat `—` as zero or as `-Infinity`).
- **Sort and filter are the platform default, applied automatically — do not hand-roll either.**
  `assets/sortable.js` watches the DOM and, as soon as a table with a header row and at least six body
  rows appears (or is re-rendered), gives it click-to-sort on every orderable column plus a filter box
  and an "N of M rows" count above it. A page only has to load the script. Consequences to design for:
  - A column is treated as numeric only when every cell carrying a value parses as a number, so a name
    column is never ranked as though `3M` were three. Where the eye and the machine read a cell
    differently — a date, a yen figure with a unit suffix, a value with a footnote marker — put the
    orderable value in `data-sort` on the `<td>`.
  - A column with nothing orderable in it (a sparkline, an actions cell) is skipped, so it never offers
    a sort that silently does nothing.
  - Opt a table out entirely with `data-no-enhance`; set its filter placeholder with
    `data-filter-placeholder`. Below six rows nothing is added — a filter box over four rows is clutter.
  - A table whose page sorts its own rows — any header carrying `data-key`, which both `sortableHead()`
    and the Item Explorer emit — keeps that sort and its own arrow, and gets only the filter. Two sort
    handlers on one click is the failure this avoids; force it with `data-no-enhance-sort` if a page
    sorts without using `data-key`.
  - The toolbar is inserted as a sibling *outside* the table's `.table-wrap`, so re-rendering the table's
    `innerHTML` — which nearly every page here does — cannot destroy it, and the reader's query is
    re-applied to the new rows.
- **Inline sparklines** are preferred over a wide grid of period columns when comparing many series.
- Long identifiers or names: truncate with the full value in `title`, or link to the detail page. Never
  let one long name reflow the numeric columns.
- **Row count and applied filters are always visible** above the table ("1,653 items · 3 filters"), and
  the export button exports *what is filtered*, not the whole table — state which in the button's tooltip.
- Pagination or virtualisation past ~200 rows. A table that renders 10,000 DOM rows is a bug.

## Filters and controls

- Controls sit **above** the data they filter, in one row, left-aligned, in a fixed order across the
  platform: geography → vintage/base → date range → transformation → series filters.
- **Active filters are visible as removable chips** (outline-only) with a single "Clear all". A filter
  buried in a closed drawer, silently affecting the data, is a trust bug.
- **Every control's state lives in the URL** so a view is shareable and citable. This is a P0 for a data
  product — a colleague pasted a link must see exactly the same numbers.
- Date-range presets (1Y / 3Y / 5Y / 10Y / Max / custom) plus explicit start–end inputs.
- Defaults must be defensible and stated: the default range, default vintage, and default weighting
  appear as selected values, never as an implicit blank.

## States — loading, empty, error, stale

Every data surface implements all four. A screen that only handles the happy path is not done.

- **Loading**: skeleton blocks matching the final layout's dimensions — never a spinner, never a layout
  shift when data lands. Charts show a skeleton plot area of the final height.
- **Empty (no matching data)**: one plain sentence saying what's missing and how to widen the query
  ("No items match these filters. Clear the vintage filter to include 2020-base items."). No illustration.
- **Empty (genuinely no data exists)**: say so and say why — not yet published, not collected for this
  geography, series discontinued at this date — with a link to the methodology note.
- **Error**: what happened · why · what to do next, in plain language, with a retry. Raw text behind a
  collapsed "See details". Never a bare status code.
- **Stale / pending release**: a banner at the top of the surface with the last-good as-of and the next
  expected release time. Data stays visible but is explicitly marked; never show stale data unmarked, and
  never blank the screen because a refresh failed.

## Provenance surfaces

- **Every displayed value reaches its source in ≤2 clicks**: value → "show calculation" or "source" →
  the release record and archived artefact.
- "Show calculation" is a collapsed inline disclosure listing formula, named inputs with their values,
  calc version, and the release IDs used. Not a modal, not a separate page.
- **Vintage selector** on any series with more than one vintage; the current selection is always visible,
  and appears in the URL and in every export's metadata.
- **Revision markers**: a superscript or small glyph next to a revised value, linking to a diff of prior
  vs current vintage.
- Exports carry a header block: data dictionary, agency, series IDs, vintage, trust label, retrieval
  timestamp, and the permalink to the live view.

## Dark mode

First-class, not a filter. Financial users work in dark environments and will expect it.

- Implement via tokens with `@media (prefers-color-scheme: dark)` plus an explicit user toggle that wins
  over the media query in both directions.
- Never pure black. Surface `#0f172a`, panel `#1a2436`, border `#2b3a52`, grid `#22304a`, ink `#e2e8f0`,
  muted `#94a3b8`, primary lightened to `#5b9bd8`.
- **Series colours need light-mode and dark-mode variants** — `#1a4d8f` is unreadable on a dark panel.
  Define both per slot; never programmatically lighten at render time.
- Re-check every contrast ratio in dark mode; a palette that passes in light routinely fails in dark.
- Chart exports (PNG/SVG) default to the **light** variant regardless of the viewer's theme, since they
  end up in decks and documents. Offer a dark export explicitly.

## Accessibility

- Text contrast ≥ 4.5:1; large text and UI borders ≥ 3:1. Axis text and muted labels are the usual
  failures — check them, not just body copy.
- **Never colour-only encoding** for series, direction, or status: pair with label, sign, dash pattern,
  or position.
- Full keyboard operation: tab order follows visual order; charts expose a data-table equivalent; the
  focus ring is visible (`box-shadow: 0 0 0 2px rgba(26,77,143,0.35)`) and never removed.
- Tables use real `<th>` with `scope`; sortable headers announce their state with `aria-sort`.
- Respect `prefers-reduced-motion` — chart transitions and skeleton shimmer stop.

## Copy

- **Instruct, don't sell.** Shortest sentence that says what to do or what the value is. No hype, no
  slogans, no time-saving promises, no "unlock/supercharge/seamlessly/effortlessly".
- **Never render a raw enum, slug, or code identifier.** Map every stored value to a Title-Case display
  label through one `Record<value, label>` per surface. Applies to badges, cells, filters, dropdown
  options, toasts, and email subjects.
- **Capitalisation**: badges, headings, buttons, column headers → Title Case. Sentences, hints, empty
  states → sentence case.
- **Descriptive, never causal.** "Electricity contributed 0.2 pp of the 0.3 pp slowdown" is a mechanical
  statement and is fine. "Electricity drove inflation down" is a causal claim and is not, absent a
  documented research design. Banned in generated summaries: caused, drove, because, due to, led to.
- **Never name the technology.** "Estimated from Tokyo series with a published error history", not
  "AI-powered nowcast". If a value was generated by a model, say "estimate" and link the model card.
- **Never overstate certainty.** A model output says "estimate"; a provisional official figure says
  "provisional". Hedging that is *accurate* is not weakness.
- **Operator copy** (internal ops screens): operators are not engineers. Translate machine errors to
  _what happened · why · what to do next_; keep raw text behind "See details"; buttons say what they do
  ("Re-run ingestion", "Approve release"), never internal jargon ("flush", "upsert", "backfill").

## Layout, spacing, and framing

- **Spacing scale**: 4 / 8 / 12 / 16 / 24 / 32 / 48px. Nothing else. Min 8px between unrelated elements,
  4px between closely related ones. No two elements touch.
- **Dividers vs whitespace**: whitespace is the default separator. Add a 1px `--obs-border` rule only
  when two sections would otherwise blur together. Never both a large margin and a rule.
- **Section framing — pick one pattern per page.** Either every section on the page is a bordered panel
  or every section is a header band + bare content. Never mix bare and boxed sections on one page, and
  never put a band on a boxed one.
- **Sibling parity**: peers in a row share treatment — same border weight, same button style, same
  heading size. Scan left-to-right; if your eye catches one sibling as heavier, that's the bug.
- **Heading hierarchy**: page title `h1`, sections `h2`, sub-sections `h3`. Never skip a level. All `h2`
  on a page use one treatment — the section band below — never a mix.

### Section header band

Every top-level `h2` is a **filled navy band spanning the content width**, not underlined text. This is
the house pattern for section structure and the one sanctioned exception to the outline-only rule.

```css
h2 {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 16px; flex-wrap: wrap;
  font-size: 13px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--obs-band-ink);
  background: var(--obs-band-bg);
  border-radius: 3px;
  padding: 10px 16px;
  margin-bottom: 14px;
}
```

- **Uppercase, tracked, and small** — the band carries the emphasis, so the type does not also need to
  be large. A 20px uppercase title inside a filled bar is shouting twice.
- **The band spans its container**, full-bleed to the content column. Never a band that hugs its text.
- **The right slot is for one short qualifier only** — a count, an as-of, a unit (`574 priced items ·
  June 2026`), in `--obs-band-muted`. Not a control, not a button, not a sentence. Interactive controls
  go in the row *below* the band.
- **h3 stays plain text.** Only `h2` gets a band; nesting bands reads as two competing sections.
- **A section that is already a bordered panel does not get a band** — that is a filled box inside a
  box. Panel titles (detail panels, modals, cards) are plain 16px semibold `--obs-ink`. Give the opt-out
  a named selector and reset `background`, `color`, `text-transform`, and `letter-spacing`, not just
  padding — a partial reset leaves uppercase white text on a white panel.
- Prose pages use the same band; it caps at the prose measure with the body text, not the full width.
- **Icons**: wrap icon + text in `display:flex; align-items:center; gap:4px`, explicit `width`/`height`,
  `flex-shrink:0`. Never a bare inline icon sitting on the text baseline.
- **Link style**: brand blue, underline on hover only. Standalone action links have no resting underline;
  prose links may. Never a third link colour on one page.
- **Content width**: dashboards and tables use the full container. Prose (methodology, notes, docs) caps
  at ~1040px with 60–80 characters per line, ≥14px, line-height ~1.55.

## Responsive

- Breakpoints: 390 (mobile) / 768 (tablet) / 1280 (desktop) / 1440 (wide).
- **Charts do not simply shrink** — below 768px, drop to fewer series, fewer x-ticks, and a bottom legend;
  never render a 6-series chart at 390px width.
- **Tables become cards or a pinned-column scroll** below 768px, whichever preserves comparison. Do not
  hide numeric columns silently; if columns are dropped, say which and offer a toggle.
- Stat-tile rows wrap 6 → 2 → 1. Filters collapse to a single "Filters" button showing the active count.
- Test the open state of every menu at 390px — the underpainting and clipping bugs in SKILL.md Step 9
  almost always surface there first.

## Forms

Fewer forms than a transactional product, but the same discipline for basket inputs, alert rules, saved
views, and account settings.

- One field per container. **Label above the input**, 13px, weight 600, 6px below.
- Required: red `*` after the label (`aria-hidden`). Optional: a muted lightweight "optional". Never
  inline "Required" text.
- Hint text below the input, 12px muted; field error below the hint, 12px red, rendered only when present.
- **Focus ring** `border-color: var(--obs-primary)` + `box-shadow: 0 0 0 2px rgba(26,77,143,0.15)`. No
  red border on the input for errors — errors are text.
- Form-level alerts above the submit button, not inline with fields.
- Two-column grid at ≥720px, one column below; full-width fields span both.
- **Numeric inputs** use the same formatter as display: thousands separators on blur, unit shown as a
  suffix inside the field, and validation stating the accepted range in the same units.
