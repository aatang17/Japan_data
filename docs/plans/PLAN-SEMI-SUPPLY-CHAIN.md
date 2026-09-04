# PLAN — Semiconductor Supply Chain: from customs data to company models

> **Status:** APPROVED 2026-09-04. **M0–M4 done and gated** (§9); M5 spike recorded in §10.
> Every fact in §2 was measured against the archive and the live APIs, not assumed.
>
> **One-liner:** Put Japan's semiconductor trade — wafers in, chips out, machines installed —
> next to what the listed companies that make those things actually report: revenue by
> region, named customers, and (later) orders and backlog. Roll everything up to each
> company's own fiscal calendar so an investor can paste it straight into a model.
>
> **Position:** the first surface that joins the two halves of the platform. The macro side
> supplies `trade-semis` (live since 2026-09-03) and the HS-level wafer layer proposed here;
> the equity side supplies the annual-report financials already extracted for 2,243 filers.
> The join is **editorial** — customs data carries no company identity — and the product is
> honest about that on every screen.
>
> **Companion docs:** [PLAN-JAPAN-MACRO-OBSERVATORY.md](PLAN-JAPAN-MACRO-OBSERVATORY.md) ·
> [PLAN-EQUITY-PROTOTYPE.md](PLAN-EQUITY-PROTOTYPE.md) (§5.0 rules bind here) ·
> `observatory/app/adapters/mof_trade.py` (the trade adapter this builds on)

---

## 1. Why this, and why now

`trade-semis` answers *where Japan's chips and chipmaking equipment go*. On its own that is
a macro chart. The question an investor is paying for is one step further: *what does that
mean for Tokyo Electron's next quarter, and how much of Japan's equipment exports to China
is TEL?* Today nobody serves that join in English, at investor grade, with point-in-time
history. Sell-side desks assemble it by hand, one company at a time, every quarter.

Three things make it buildable now rather than later:

- **The company side already exists.** Twelve of the sixteen companies that matter have
  clean FY2026 annual-report financials in `eq_fin_facts` (§2). The remaining work on that
  side is one extractor, not a new pipeline.
- **The regional revenue is in the filings we already archive** — in the segment note, by
  customer location, for the current and prior year, with the largest customers named. It
  is not tagged as numbers (§2, fact 3), which is why nobody has it in a database.
- **Customs is monthly and arrives first.** Company results are quarterly and arrive after
  the quarter closes. The historical relationship between the two, measured and published,
  is the nowcast an analyst currently carries in their head.

## 2. Verified source facts (M0, 2026-09-04 — measured, not assumed)

| # | Fact | Evidence |
| --- | --- | --- |
| 1 | **12 of 16 target companies** have a clean FY2026-03 filing in `eq_fin_filings`: Shin-Etsu 4063, TEL 8035, Advantest 6857, SCREEN 7735, Disco 6146, Kokusai 6525, Sony 6758, Rohm 6963, Fujifilm 4901, Tokyo Seimitsu 7729, Socionext 6526, Kioxia 285A. | DuckDB query, `data/equity.duckdb` |
| 2 | **The 4 missing all have non-March year-ends**: SUMCO 3436 (Dec), Lasertec 6920 (Jun), Renesas 6723 (Dec), Tokyo Ohka 4186 (Dec). The financials extractor's watermark is 2026-08-06 over 2,503 documents (vs 34,768 for the older extractors) — whether these are outside its processed range or genuinely absent must be settled in M1. | `eq_extract_runs` |
| 3 | **Segment information is a text block, not tagged numbers.** TEL's XBRL instance has **zero** segment- or region-dimensioned contexts. The whole note is one element, `jpcrp_cor:NotesSegmentInformationEtcConsolidatedFinancialStatementsTextBlock` — 31,394 characters, **12 HTML tables**. The financials extractor's docstring ("adding segment breakdowns later is a filter change") is therefore **wrong** for this data; it is a text-block table parse, the same job `equity/facility_m1/extract.py` already does for facilities. | `S100YEOO_t1.zip`, grep of the `.xbrl` |
| 4 | **Inside that block, TEL discloses revenue by customer location for seven regions, both years.** FY to Mar 2026 (¥m): Japan 239,427 · North America 166,446 (of which US 166,235) · Europe 67,407 · Korea 543,858 · Taiwan 499,853 · **China 832,555** · Other 93,985 · Total 2,443,533. Prior year China was 1,015,060. The note states the basis: 「売上高は顧客の所在地を基礎とし」. | text block §2 地域ごとの情報 |
| 5 | **The block also names the largest customers with revenue**: Samsung Electronics ¥286,800m, TSMC ¥280,618m (FY to Mar 2025 shown; current year alongside). This is the direct company-to-company link the customs data can never give. | text block §3 主要な顧客ごとの情報 |
| 6 | TEL is a **single-segment filer** (「半導体製造装置」の単一セグメント), so its product split is empty by construction; the regional and customer tables are what it carries. Multi-segment filers (Sony, Fujifilm, Shin-Etsu) will carry a product table in the same block. | `DescriptionOfFactThatCompanysBusinessComprisesSingleSegment` |
| 7 | **Customs, same commodity, overlapping window**: Japan's exports of semiconductor machinery & equipment (概況品 70131000) to China were **¥1,820.5bn** in the 12 months to July 2026. Against TEL's ¥832.6bn (Apr 2025–Mar 2026, a different window) that is an *indicative* TEL share of ~45%. The point is not the number; it is that the two can now be put on one axis and the ratio tracked. | `trade-semis`, raw cache recomputation |
| 8 | **Wafers are not in `trade-semis`** (no wafer line in the 概況品 classification) but **are in the HS-detail tables** (`品別国別表`, e-Stat `0004049306` for 2026 exports): **HS 3818.00-100**, monthly, by country, value and quantity in kg. Jan–Jul 2026: ¥388.8bn — Taiwan ¥149.6bn · Korea ¥64.3bn · China ¥59.9bn · US ¥42.1bn · Singapore ¥23.6bn. `-900` is a ¥33.6bn residual and stays separate. | e-Stat `getStatsData`, `cdCat01=381800100,381800900` |
| 9 | Two HS-table traps, both measured: the commodity axis **carries no names** (e-Stat returns the code as the label — labels must come from the Customs tariff schedule), and **quantity sits in 数量2**, not 数量1 (数量1 is all zeros for these lines). A parser reading the first quantity column silently produces zeros. | `cat02` axis, 41 fields = 2 units + 3 per month |
| 10 | **Japanese wafer *production* is confidentiality-suppressed.** IIP item `1105005010 シリコンウエハ`: 12 numeric months (all of 2018), then `X` for 87 months continuously from Jan 2019; no inventory series at all. Not usable. | e-Stat `0004052197/98/99` |
| 11 | **Wafer and chip price indices exist on the BOJ API**, keyless, monthly to Jul 2026: silicon wafers — domestic PPI `PRCG20_2201550017` from 1985-01, export price yen-basis `PRCG20_2400550016` / contract-currency `PRCG20_2300550016` from 1990-01, import price `PRCG20_2600850015`. ICs: export price `PRCG20_2400540002` / `PRCG20_2300540002`; MOS memory `PRCG20_2400550006`. | `getMetadata db=PR01`, 659 export-price series on the 2020 base |
| 12 | **The BOJ IC price index is not a deflator for customs IC value.** Jul 2025→Jul 2026: customs value +52.0%, customs quantity **+7.5%**, BOJ IC export price (yen) **+152.6%** (MOS memory alone 96.4→432.1). Deflating value by the index implies volume −39.8% against a measured +7.5%: the baskets differ (BOJ weight-dominated by memory; customs is 6.75bn units/month at ¥98 average). Use side by side as triangulation, never as a deflator. | recomputed from raw cache + BOJ series |
| 13 | **Quarterly securities reports were abolished from April 2024.** Q1/Q3 exist only as 決算短信 on TDnet; the regional and order detail lives in per-company supplementary PDFs/Excel. Half-year reports remain on EDINET. This is the reason the quarterly layer is the hard milestone, not a data gap in EDINET. | statutory; not re-verified here |

## 3. What the product shows

Three layers, each labelled with what it is.

**Layer 1 — what the companies report (truth).** Per company: consolidated revenue,
revenue by region on the filer's own basis (customer location), named major customers,
product segments where multi-segment, capex — annual from EDINET now; half-year from EDINET
and quarterly from TDnet in the later milestones. Every figure *as filed*, `Official
Statistic`-equivalent badge for the equity namespace ("As filed").

**Layer 2 — what customs says (the early read).** The `trade-semis` series and the HS wafer
layer, rolled up to *that company's* fiscal quarters and years. Monthly, by destination,
published ~2 months after the month — before the company's quarter is printed.

**Layer 3 — the relationship (derived, formula shown).** For each company × commodity ×
region pair the platform has mapped: the ratio of filed revenue to customs exports over
matching windows, its history, and the measured lead of customs over the company print.
Never a badge; always a formula; always the caveat in §4.

### Surfaces

1. **Company Lens** (`web/company.html?code=8035`) — the modeller's page. Left: filed
   figures in fiscal periods. Right: the mapped customs drivers in the same fiscal periods.
   Below: the ratio and its history. One **wide CSV**: one row per fiscal quarter, one column
   per series, both sides, with the data dictionary, source, vintage and trust in the header.
2. **Supply-chain view** on `semis.html` — wafers → chips → equipment by destination, one
   screen, Taiwan / Korea / China / US selectable. The Substack chart.
3. **Customer graph** — from fact 5: the named-customer tables give a real edge list
   (TEL → Samsung ¥286.8bn; TEL → TSMC ¥280.6bn). Rendered as a table first; a graph only if
   it earns it.

## 4. Trust contract adaptation

- **The commodity → company mapping is editorial.** It is a versioned file in the repo,
  reviewed in git, labelled on every surface as "Companies whose disclosed business
  produces this commodity — platform curation, not a source classification." It is never
  presented as a join.
- **Customs is not revenue, and the page says so in plain words** wherever the two meet:
  companies ship from overseas plants, sell domestically, recognise revenue on acceptance
  not shipment, and customs includes competitors and trading houses. The ratio in Layer 3
  is an indicator of direction and share, never an accounting identity.
- **Regions do not correspond.** A company's "China" (customer location, its own
  definition) and customs' "China" (declared destination) are different concepts that
  happen to share a name. The Company Lens shows the filer's basis text (fact 4) next to
  the customs definition. No region is silently re-mapped to another.
- **Fiscal roll-ups are derived.** `Σ monthly customs value over the company's fiscal
  quarter` carries its formula and the company's fiscal calendar as an input.
- **Price indices are triangulation, not deflators** (fact 12). If a volume estimate is
  ever shown it is the customs quantity, which is measured, never value ÷ index.
- **Point-in-time by default in exports.** Every wide CSV states the `as_of`; the macro side
  already serves it, and the equity side keeps restatements as separate rows (§5.0 rules).

## 5. Data model

Equity namespace (own schema; the macro golden rule does not apply):

```
eq_seg_filings   (doc_id, edinet_code, sec_code, period_end, filed_date, sha256,
                  parser_version, status, detail, single_segment, tables_found)
eq_seg_regions   (doc_id, year_offset, basis_text, region_label_ja, region_label_en,
                  revenue_yen, ppe_yen, ord)            -- 地域ごとの情報, both years
eq_seg_customers (doc_id, year_offset, customer_name, revenue_yen, segment_label, ord)
eq_seg_products  (doc_id, year_offset, segment_label_ja, segment_label_en,
                  revenue_yen, profit_yen, assets_yen, ord)   -- multi-segment filers only
```

Repo data, editorial:

```
observatory/app/curation/semi_supply_chain.json
  { "70131000": { "label": "...", "companies": [{"sec_code": "8035", "role": "maker", ...}] },
    "381800100": { ... "companies": [{"sec_code": "3436"}, {"sec_code": "4063"}] } }
```

Macro API, no schema change:

```
GET /api/v1/{dataset}/observations?...&period=fiscal&fy_end=03   -- fiscal-quarter roll-up
GET /api/v1/equity/company/{sec_code}/lens                         -- both sides, one payload
GET /api/v1/equity/company/{sec_code}/lens.csv?as_of=              -- the wide export
```

Reads use the same functions that serve the pages; the MCP tools wrap those.

## 6. Milestones

| M | Deliverable | Acceptance gate |
| --- | --- | --- |
| **M1 — Segment-note extractor** | Parse `NotesSegmentInformationEtc…TextBlock` from the t1 package for **every** annual-report filer (not only semis — the extractor is generic): regional revenue with basis text, named customers, product segments. Reuse the facilities extractor's table-parsing approach. Settle fact 2 (the four non-March filers). | Regional totals reconcile to consolidated revenue in `eq_fin_facts` within ¥1m rounding for ≥95% of filings that carry the table; TEL's seven regions match fact 4 exactly; every parse failure is `partial` with a reason, never a silent zero. Freshness reported in `/catalog/health`. |
| **M2 — Mapping + fiscal roll-ups** | `semi_supply_chain.json` for the 16 companies × the 11 `trade-semis` commodity-flows; `period=fiscal` on `/observations` and `/trade`. | Roll-up of any series over a fiscal year equals the sum of its months (exact); mapping file has an owner and a review date in its header. |
| **M3 — Company Lens + wide CSV** | The page and the export; Layer 3 ratio with formula; `as_of` in every CSV header. | Look-at-it gate at 390/768/1280/1440, light and dark; a modeller can paste the CSV into Excel and rebuild the page's ratio from it. |
| **M4 — HS wafer layer** | Adapter for `品別国別表` with a curated HS list (3818.00-100 first; photoresist, targets, quartz next), labels from the Customs tariff schedule, quantity from 数量2. Supply-chain view on `semis.html`. | Jan–Jul 2026 wafer world total = ¥388.8bn (fact 8); Taiwan ¥149.6bn; quantity non-zero for every month Taiwan has value. |
| **M5 — Quarterly layer (spike first)** | One-week spike on TDnet 決算短信 for TEL, Advantest, SCREEN: can orders, backlog and regional sales be extracted reliably from the supplementary materials? Go/no-go before any build. | A written result with per-company extraction cost; no code merged. |
| Later | BOJ wafer/IC price indices as a triangulation panel (fact 11), never a deflator (fact 12). | — |

M1 is the highest-value single step and unblocks everything else; M4 is independent of
M1–M3 and can run in parallel.

## 7. Risks

- **Text-block tables vary by filer.** The facilities extractor already absorbed this class
  of variance; budget for it again. Gate: every failure is visible as `partial`, never a
  zero.
- **The mapping rots.** Companies delist (JSR went private in 2024), merge, change what
  they make. Mitigation: owner + review date in the file; a health line when a mapped
  `sec_code` stops filing.
- **Window mismatch is misread as a share change.** Customs 12-month windows and company
  fiscal years differ by up to 11 months; only same-window ratios are shown, and the
  window is printed beside every ratio.
- **The quarterly layer may not be extractable at acceptable cost.** That is what the M5
  spike decides; nothing else depends on it.
- **Scope creep into a graph product.** The customer edge list is a table until a graph
  demonstrably earns its place.

## 8. Open decisions (need the owner's call)

1. **Approve M1 as the first build**, generic across all annual-report filers (recommended
   — same cost, far more value than semis-only).
2. Whether the four non-March filers (fact 2) are worth a targeted backfill before M1, or
   are picked up by the extractor's normal watermark advance.
3. Whether the Company Lens is a **Pro** surface or free with attribution (the academic
   plan's tiering applies; a modeller's CSV is the most obviously paid artefact on the
   platform).
4. Update `equity/fin_extract.py`'s docstring, which currently describes segment data as
   "a filter change" (fact 3). One line; not done in this proposal.

## 9. Results (2026-09-04)

### M1 — segment-note extractor: **passed**

`observatory/equity/seg_extract.py` (parser `seg-1`), registered in `refresh_equity.py`
but withheld from the boot path until the shipped seed carries a `segments` watermark —
the same rule as financials and AGM votes. Reads the XBRL instance in the t1 package
(the inline-XBRL .htm splits the note across `ix:continuation` fragments), parses the
region, customer and reportable-segment tables from the text block, and reconciles
current-year region revenue to `eq_fin_facts`.

Full local archive (June–August 2026 filing season, 2,503 annual reports, 43 seconds):

| Gate | Target | Result |
| --- | --- | --- |
| Region tables reconciling to consolidated revenue within 0.5% | ≥ 95% | **95.9%** (883 of 921) |
| TEL's seven regions match §2 fact 4 exactly | exact | **exact** |
| Filings `clean` | — | 2,275 of 2,503 (91%) |
| Filers stating an omission (no overseas revenue / >90% domestic) | — | 1,393 |
| Named-customer rows / filings naming one | — | 2,786 / 897 |
| Reportable-segment rows / multi-segment filings | — | 12,139 / 1,777 |
| `partial`, by reason | — | 139 no table and no omission wording · 50 no tagged note (5 US-GAAP filers, 45 unlisted asset managers) · 37 reconciliation off · 2 year marker missing |

Every `partial` carries its reason; no value was adjusted to pass a gate. **§2 fact 2 is
settled**: the four non-March filers are absent because the local archive holds only
2026-06-01 → 2026-08-06; they will arrive with the S3 archive, not with a parser change.

What the parser had to learn, in order of how much each cost the gate: (1) the commonest
omission wording is 「本邦以外の外部顧客への売上高がないため、該当事項はありません」, not the
90% form; (2) a filer whose *reportable segments* are named 日本 and 中国 must be read as
segments in the segment section, or its table is counted twice against the region table;
(3) two-level headers — 「北米・南米」 above 「内、ブラジル」 — and colspan'd cells, which
`grid_of` expands into every column they cover, so values are read only at a cell's origin;
(4) 「海外」 printed beside 北米/欧州/アジア is their subtotal, not another region.

The customer table is already a real edge list: TSMC is a named ≥10% customer of seven
Japanese filers (TEL, Advantest, SCREEN, Disco, Shibaura Machine, Fujimi, Rasa).

### M2 — mapping and fiscal roll-ups: **done**

- `observatory/app/curation/semi_supply_chain.json` — 9 commodity keys, 16 companies,
  roles, the reason each is listed, an owner and a review date. Editorial, labelled so.
- `observatory/app/fiscal.py` + `period=fiscal_quarter|fiscal_year&fy_end=MM` on
  `/api/v1/{dataset}/observations`. Sums only units known to be monthly flows (customs
  value and quantity, persons) and refuses an index, a stock or a rate; emits only complete
  periods and lists the months left out. Verified live: TEL's fiscal quarters of Japan's
  equipment exports to China; a December year-end; the index refusal.

### M3 — Company Lens: **done**

`observatory/app/segments_api.py` (MANIFEST validated, registered in the dataset
registry) and `web/company.html`. Endpoints: `company/{sec_code}`, `supply-chain`,
`customers`, `lens/{sec_code}`, `lens/{sec_code}.csv`, `coverage`. Look-at-it gate passed
at 390 / 768 / 1280 / 1440, light and dark; interaction pass (company switch, view, commodity,
range) with no console errors.

The lens already shows why the ratio is an indicator and not an identity — TEL, FY2025,
narrow equipment line: China 66%, Taiwan 65%, Korea **102%**, North America **101%**,
Europe 96% — and the page prints the caveat next to the number.

### Decisions taken along the way

- Real-database loads happen in a short write window with every dev server stopped and
  restarted; the extractor itself never runs beside the serving process.
- The Europe key maps to every partner in the Ministry's region 2 (46 countries); "Asia"
  is never mapped, per §4.
- `equity/fin_extract.py`'s docstring still says segment data is "a filter change"; it is
  not (§2 fact 3). Left for its owner — the file is under active change in another session.

### M4 — HS wafer layer: **passed**

`observatory/app/adapters/mof_trade_hs.py`, dataset `trade-inputs`, live in the database
(release 16: 514 series, 82,158 observations, 103 partners, 2001-01 → 2026-07) and in
`/catalog/health`. Shares the year-block cache, partner table, coverage rule and series-code
shape with `mof_trade`, so `/api/v1/trade-inputs/trade` is served by the same endpoint
unchanged. Registered in `start.sh`, `ingest.py`, `api.py`; MANIFEST validated.

| Gate | Target | Result |
| --- | --- | --- |
| Jan–Jul 2026 wafer exports, world | ¥388.8bn (§2 fact 8) | **¥388.8bn** |
| Taiwan | ¥149.6bn | **¥149.6bn** |
| Quantity non-zero in every month Taiwan has value | all | **7 of 7** |

Two things the build measured that §2 did not know:

- **The import schedule splits HS 3818.00 differently** — `-010`/`-020` against the
  export schedule's `-100`/`-900`. The lines are therefore direction-specific, as the
  concept codes are. The import silicon line was confirmed by its signature (¥48k/kg over
  1.8m kg from China, the US, Taiwan and Korea) against the residual's (¥709k/kg over
  48 t — compound substrates). The adapter records this in its notes.
- **Which quantity slot carries the figure is measured per line**, not assumed: the
  parser takes the slot with any non-zero value, so a future line that uses 数量1 parses
  without a code change, and the gate refuses a release whose quantity column is all zero.

The semis page gained **The Supply Chain by Destination**: wafers → integrated circuits →
chipmaking equipment for Taiwan / Korea / China / US / World, twelve-month totals, indexed
to a common base or in ¥bn. To Taiwan since August 2016: wafers ×3.4, ICs ×3.0, equipment
×2.4, with the equipment cycle's 2023–24 trough visible against a wafer line that never
turned down. The Company Lens reads `hs.` mapping keys from the new dataset (Shin-Etsu:
wafer exports to the US beside its filed US revenue), and marks the ratio as an **upper
bound** for any multi-segment filer, since regional revenue spans every segment.

## 10. M5 spike result (2026-09-04) — quarterly layer: **go for regional sales, no-go for orders**

Bounded to what could be measured in one session; no code merged.

| Question | Finding | Evidence |
| --- | --- | --- |
| Is TDnet reachable by a pipeline? | **Yes, with a browser user-agent.** The bare fetch is refused (403); with a normal UA the daily lists (`I_list_001_YYYYMMDD.html`) return 200 and each 決算短信 row links a PDF and an XBRL zip. Lists are paginated per day. | curl, 2026-07-17 → 08-11 |
| Does the 決算短信 XBRL carry regional sales or orders? | **No.** TEL's Q1 FY2027 package (56 KB) holds the summary cover (`tse-qcedjpsm`), BS/PL/CI as inline XBRL, a `qualitative.htm` with 10 tables, and one segment-note text block — 地域 0 mentions, 受注 0 mentions. The structured file is the wrong place to look. | `081220260630584086.zip` |
| Where are quarterly regional sales? | **In the IR presentation PDF, as machine text in a stable template.** TEL slide 6, "Composition of Net Sales by Region (Quarterly)": a table of nine quarters × seven regions in ¥bn (FY2027 Q1: Japan 64.6 · North America 59.0 · Europe 24.2 · South Korea 152.4 · Taiwan 186.1 · SE Asia/Others 22.9 · China 222.9; total 732.3). Also new-equipment sales by application (DRAM / NVM / non-memory) and Field Solutions. | `fy27q1presentations-e.pdf` pp. 4–8 |
| Advantest? | Regional sales are a **chart with data labels**, not a table ("Quarterly Sales by Region (Ship to Region)", nine quarters × seven regions), plus sales by segment and sub-segment. Extractable, but from label positions rather than a table grid — a per-company parser. No Excel or data file is offered (checked FY2008–FY2026). | `JE_BIZ_260729_slide.pdf` pp. 5–7 |
| Orders and backlog? | **Not disclosed by TEL or Advantest** in their current quarterly decks. TEL discontinued order disclosure years ago; Advantest's deck carries TAM outlook instead. SCREEN was not checked in this spike. | same decks |
| Structured data anywhere? | **No.** Neither company offers xlsx/csv; the only structured quarterly numbers are the consolidated totals in the 短信 summary XBRL. | IR library pages |

**Verdict.** Quarterly regional sales are extractable for TEL today with a small PDF table
parser against a template that has not changed shape across the nine quarters on the slide,
and for Advantest with more work. Orders and backlog — the thing "wafer orders" really
asked for — are not published by the two largest equipment makers, so that layer cannot be
built from public disclosure for them. The M5 build, if approved, is **"quarterly regional
sales from IR decks, per company, TEL first"**, with the same status/partial discipline as
M1, and an explicit note on every surface that the figures are read from a presentation,
not a statutory filing. Cost: one parser per company template; a template change breaks it
loudly, never silently.

## 11. Customer concentration surface (2026-09-04)

Built on the M1 customer table, after the memory work showed what it was worth:
`/api/v1/equity/segments/concentration` and `web/customers.html` — buyer lookup, buyers ranked
by Japanese suppliers, and suppliers ranked by dependence, each with a complete CSV.

**841 companies disclose 1,385 customer relationships under 1,010 distinct names as filed.**
98 of them draw more than half their revenue from customers they were required to name.

Building it exposed three parser faults in M1, all now fixed and gated — this is the value of
putting data on a screen:

1. **Unit stated inside the customer table's header** (「売上高(千円)」) rather than in a caption
   above it. 251 of 2,786 rows were read a thousandfold too large. Fixed; gate added — a named
   customer larger than the filer's whole revenue is `partial`.
2. **One customer relating to several segments** was duplicated once per segment by the
   rowspan expansion, putting MIRAIT ONE at 147.9% of its own revenue. Collapsed to one row
   carrying every segment the filer listed.
3. **Two customer tables (prior and current year) both landing on the current year** where the
   年度 heading between them was missed, doubling gumi's disclosed total. Now assigned by
   document order, and a combined-share gate refuses anything above 100%.

After the fixes: **zero filers above 100%**, `clean` 2,249 of 2,503.

**Design decision worth keeping:** customer names are never merged. Toyota appears twice and
Samsung three times because the filers wrote them that way; the page says so on every surface
and searches text rather than guessing. Merging would state a total nobody disclosed.

## 12. The hand-edited company list (2026-09-04)

`observatory/app/company_labels.py` — the issuer-side counterpart to `filer_labels.py`, and now
the single place a person edits company reference data. It replaces the two JSON curation files
the earlier milestones created (`customer_names_en.json` is deleted; the supply-chain mapping
stays, since it maps commodities rather than names).

Per company: English name, canonical Japanese name, securities code, **the alternative spellings
filers actually use**, corporate family, and theme tags. 71 companies, 75 aliases, 9 themes.

Why it has to exist, measured rather than assumed: **70 buyers in the current filings are written
more than one way** — Toyota two, Honda three, Denso three, Nissan three — and no document states
that any two are the same company. Half of the 1,010 distinct customer names have no English name
anywhere in the machine-readable record.

Effect on the Customers page: English coverage 495 → **508 of 1,010**, and the theme tags became a
live filter. Choosing "Memory makers" now returns 9 supplier relationships across 6 buyers —
Wacom at 41.5% of revenue to Samsung, Kanto Denka at 22.0% and 18.9% to Samsung and Kioxia,
Tokyo Electron at 15.1% — the memory-exposure screen, driven by an editable file rather than a
one-off query.

Rules the file states and the code enforces: the as-filed name is never replaced; nothing is
translated; a subsidiary keeps its own identity (Amazon Japan G.K. is not Amazon.com, Toyota
Boshoku is not Toyota Motor); a group is public record or absent; an alias is a spelling actually
seen in a filing, so every entry can be checked against a document.

`python -m app.company_labels --check` reports what has gone stale and what is missing. It
currently flags 4 aliases no longer filed and **914 filed names not in the list** — the long tail
of small private buyers, which is expected and is the queue for whoever curates it next.
