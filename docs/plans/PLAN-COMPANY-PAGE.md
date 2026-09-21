# Company Profile — one company, nine datasets

> Status: **built 16 September 2026**. Design mockup:
> https://claude.ai/code/artifact/b90d54f9-931a-4b12-901d-7808dad32077
> Files: `observatory/web/company.html`, `web/assets/company.js`, company styles
> appended to `app.css`.

## What it is

Everything the platform holds on one company, on one page, read from two endpoints that
already existed: `/api/v1/company/{code}` (every dataset's view, composed) and
`/api/v1/equity/financials/statements/{code}` (the three statements, fetched per tab).
No new API, no adapter, no schema change.

Order: identity and freshness → what we hold, grouped by section → **Filings** → Financials
→ Ownership → Governance → Capital returns + Assets side by side → provenance.

- **Filings first.** Every archived document tagged to the issuer, newest first, including
  the ones somebody else filed *about* it — 5% reports and AGM results. A record belongs to
  a company by the issuer's code, not the filer's.
- **Financials second**, with tabs for income statement, balance sheet, cash flow, ratios
  and segments. The ratios tab prints ours beside the company's own filed figure.
- Sections whose dataset has no rows for this company are hidden, never shown empty.

## Rules it keeps

- Nothing computed carries a badge; the change column, the unspent buyback balance, shares
  of a total and every ratio carry a formula under "Show calculation".
- A dash is missing, never zero — including a statement line the filing does not state.
- One precision and one unit per column: statements in ¥ million, per-share lines in yen
  (they carry `JPYPerShares` and must not be divided), director pay in ¥ million.
- Contradictions are printed, not reconciled: land at group vs parent basis, our sum of
  filed top-ten ratios against the company's stated total.
- Tables get sort, filter and CSV from `sortable.js`; the section navigation is the
  platform's own page TOC, not a second bar.
- URL encodes the view: `?code=7203&fin=ratios&own=five`. `?c=` still resolves, since pages
  printed before this rebuild link that way; `?code=` is canonical because the prerenderer
  titles the page from it.

## Universe

Companies that have filed an annual securities report — 4,586, of which 3,813 carry a
ticker. Search is `/api/v1/equity/financials/companies?q=`, which is scoped to filers with
statements. See [[company-universe-report-filers]] in memory.

## What moved

The old company.html — the segment-vs-customs lens — is now `customs-lens.html` +
`assets/customs-lens.js`, reachable as the second tab under Company Profile and from the
new page's provenance line. Nothing was deleted.

## Open

- Unlisted report-filers (773) have no ticker and no page yet: `/company/E02144` is the
  proposed address, and the statements extractor is scoped to filings carrying a securities
  code, so their Financials section would be empty until it is widened.
- Statements show two years; five are held. A period selector is a display choice.
- Follow on this page should become the coverage-list control when accounts ship
  (PLAN-COVERAGE-AND-SIGNIN.md).
