# Templates — research-report

## plan.md

```markdown
# <Title> — research plan

- **Question:** <one sentence>
- **Audience:** <who> · **Format:** <md / docx / pptx> · **Length:** <pages / slides>
- **As-of date for Plover numbers:** <YYYY-MM-DD>
- **Status:** draft | approved <date>

## Hypotheses (each must be disprovable)
1. <hypothesis> — disproven if <what the data would show>
2. …

## Outline
| # | Section | Claim it will make | Evidence | Chart / table |
|---|---|---|---|---|

## Data inventory
| Evidence | Source | Held? (dataset · series/screen) | Gap decision (fetch URL / cite / drop) |
|---|---|---|---|

## Out of scope
- …
```

## log.md

```markdown
| # | When | Tool / URL | Arguments | Returned (one line) | Cite URL (with as_of) | Release / vintage |
|---|---|---|---|---|---|---|
```

## findings.md

```markdown
## <Section>
- **Finding:** <one sentence>
- **Numbers:** <value — source (log #)>
- **Hypothesis:** supports / breaks H<n> because …
```

## verify.md

```markdown
| Number in draft | Where in draft | Log # | Matches? | check_claim |
|---|---|---|---|---|

Result: <n> numbers traced, <n> unresolved.
```

---

## Worked plan (skeleton) — "Write a research piece on Japan regional banks"

**Step 0 — candidate questions to offer:**
1. Which regional banks gain most from rising rates, and which get hurt?
2. Is consolidation among regional banks about to accelerate — and who is a target?
3. Are regional banks finally returning capital (buybacks, cross-holding sales)?

**Data inventory for question 1** (datasets confirmed on the platform, Sept 2026;
re-check coverage with `describe_dataset` when running):

| Evidence | Source | Held? |
|---|---|---|
| Each bank's balance sheet and P&L, half-yearly from 2002 | `jba-banks` | Yes |
| Regional-bank group results from 2005 (core profit, credit costs, capital ratios) | `fsa-bank-results` | Yes |
| Bad-loan ratios by bank type from 1999 | `fsa-npl` | Yes |
| Yield curve, BOJ JGB holdings | `jgb-yields`, `boj-assets` | Yes |
| Listed banks: financials, holders, cross-holdings, buybacks, earnings, AGM votes | `financials`, `shareholder-register`, `cross-shareholdings`, `buybacks`, `earnings-releases`, `agm-votes`; peer group `ind33:7050` (79 names incl. megabanks — curate) | Yes |
| Home-region demographics (deposit base) | `population-jp-municipal`, `population-jp-history` | Yes |
| Unrealised losses on bond portfolios | check `financials` statements for the securities valuation difference | To check |
| Monthly deposits and loans by bank type | BOJ Time-Series Data Search (not ingested) | Gap → fetch |
| Share prices, market PBR | not held | Gap → user's data, or drop valuation |
| Merger history, FSA policy (e.g. consolidation subsidies) | FSA / press | Gap → cite |
