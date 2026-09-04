# -*- coding: utf-8 -*-
"""Measurement basis for every yen figure in the cross-shareholding data.

Every holdings figure this product serves is on one convention: balance-sheet
carrying amount, at fiscal year end, from an annual securities report. That was
always true and was never said, which is fine until someone compares our number
with a published one. A Nikkei Asia piece put the three megabanks' cross-
shareholdings at ¥2.56tn at 30 September 2025; we return ¥11.5085tn at
31 March 2026. Both are right. They differ on measurement (acquisition cost vs
carrying amount) and on date (interim vs annual), and a 4.5x gap with no
explanation is worse than no answer.

WHY THIS MODULE STORES NOTHING
------------------------------
The obvious implementation is six columns on every fact row, backfilled. It is
also wrong, because two of the six are already in the schema and are NOT
constant:

  * entity_scope  <- eq_*.holder_table ('reporting' | 'largest' |
    'second_largest'). SMFG discloses ¥3.458tn of listed policy shares under
    SMBC and ¥153.8bn at the holding company itself. Backfilling every row as
    "holdco consolidated" would write a falsehood into the one field that
    exists to prevent falsehoods — and this is exactly the axis banks use when
    they report reduction progress at bank level only.
  * share_scope   <- eq_filing_totals.share_class / eq_filing_flows.share_class
    ('listed' | 'unlisted'). Only a figure summed across both is 'both'.

So the tuple is DERIVED at serialization from fields that already exist plus
three constants. No ALTER, no backfill, no rewrite of the INSERT sites, and no
question about vintage immutability: nothing stored is touched.

The labels below are also written to `eq_basis_labels` by equity/extract.py so
the vocabulary is queryable in SQL. That table is registry data (definitions,
not figures) and is rewritten wholesale, like eq_entities. Nothing here reads
it: the API must keep serving when an extract has not run, so this module is
the source of truth and the table is a projection of it.
"""

# --- the vocabulary --------------------------------------------------------

MEASUREMENT = {
    "carrying_amount":
        "Balance-sheet carrying amount. Under Japanese GAAP listed equities "
        "are carried at market with the valuation difference in other "
        "comprehensive income, so carrying amount and acquisition cost "
        "diverge enormously on positions bought decades ago.",
    "acquisition_cost":
        "Original acquisition cost (取得原価). Reduction targets and progress "
        "statements are almost always quoted on this basis, which is why a "
        "cost-based figure can be a small fraction of the carrying amount.",
}

ENTITY_SCOPE = {
    "parent_only":
        "The reporting company itself (提出会社) — the holding company, "
        "excluding the group holders it names separately.",
    "largest_holding_company":
        "The group's largest holder of policy shares (最大保有会社) — at a "
        "bank group this is the commercial bank, which excludes trust-bank "
        "and securities-subsidiary holdings.",
    "second_largest_holding_company":
        "The group's second largest holder of policy shares, where the filing "
        "discloses one.",
    "holdco_consolidated":
        "Every disclosing entity in the filing, summed — the reporting "
        "company plus each group holder it names.",
}

SHARE_SCOPE = {
    "listed": "Listed shares only (上場株式).",
    "unlisted": "Unlisted shares only (非上場株式).",
    "both": "Listed and unlisted shares together.",
}

TRUST_INCLUDED = {
    "true": "Retirement-benefit-trust shares (退職給付信託) are included.",
    "false": "Retirement-benefit-trust shares are excluded.",
    "unknown":
        "The filing does not state whether retirement-benefit-trust shares "
        "are included. Never guessed — shares contributed to such a trust "
        "leave the holder's balance sheet while the settlor normally keeps "
        "the right to instruct the vote.",
}

PERIOD_TYPE = {
    "annual":
        "From an annual securities report (有価証券報告書). The policy "
        "shareholding table appears only in the annual report.",
    "interim":
        "An interim figure. These come from IR materials, not filings, and "
        "are not held by this product.",
}

# --- constants for everything EDINET-derived --------------------------------
# The two that are NOT constant (entity_scope, share_scope) are read per row.

EDINET_MEASUREMENT = "carrying_amount"
EDINET_TRUST_INCLUDED = "unknown"
EDINET_PERIOD_TYPE = "annual"

# holder_table is the filing's own structure, not our classification.
ENTITY_SCOPE_BY_HOLDER_TABLE = {
    "reporting": "parent_only",
    "largest": "largest_holding_company",
    "second_largest": "second_largest_holding_company",
}

SHARE_SCOPE_BY_SHARE_CLASS = {"listed": "listed", "unlisted": "unlisted"}

NOT_COMPARABLE = (
    "Figures are balance-sheet CARRYING AMOUNT at fiscal year end, from the "
    "annual securities report. They are NOT comparable with the acquisition-"
    "cost or book-value-reduction figures quoted in press coverage and IR "
    "presentations, and NOT comparable with interim (half-year) figures, "
    "which this product does not hold. Always state the basis with the "
    "number, and use check_claim before setting one of our figures against a "
    "published one."
)

# There is no book-value-reduction measure in this product. `sale_proceeds_yen`
# is cash received on disposals over one fiscal year, as filed; a reduction in
# book value over the same period is a different measure and is not held. The
# two are never presented as equivalent.
NO_REDUCTION_MEASURE = (
    "This product holds sale proceeds (売却価額), as filed, for one fiscal "
    "year. It does NOT hold a book-value-reduction measure. The two are "
    "different measures and must never be presented as equivalent."
)


def entity_scope_for(holder_tables):
    """One scope for a figure spanning these holder_table values.

    A single disclosing entity keeps its own scope; more than one means the
    figure sums the group, which is holdco_consolidated. An unrecognised value
    degrades to holdco_consolidated rather than inventing a scope name.
    """
    seen = set()
    for h in holder_tables or ():
        if h is None:
            continue
        scope = ENTITY_SCOPE_BY_HOLDER_TABLE.get(h)
        if scope is None:
            return "holdco_consolidated"
        seen.add(scope)
    if len(seen) == 1:
        return seen.pop()
    return "holdco_consolidated"


def share_scope_for(share_classes):
    """One scope for a figure spanning these share_class values."""
    seen = set()
    for s in share_classes or ():
        if s is None:
            continue
        scope = SHARE_SCOPE_BY_SHARE_CLASS.get(s)
        if scope is None:
            return "both"
        seen.add(scope)
    if len(seen) == 1:
        return seen.pop()
    return "both"


def basis(as_of=None, entity_scope="holdco_consolidated", share_scope="both",
          measurement=EDINET_MEASUREMENT, trust_included=EDINET_TRUST_INCLUDED,
          period_type=EDINET_PERIOD_TYPE):
    """The typed basis tuple, with the label for each value alongside."""
    return {
        "measurement": measurement,
        "entity_scope": entity_scope,
        "share_scope": share_scope,
        "trust_included": trust_included,
        "as_of": as_of.isoformat() if hasattr(as_of, "isoformat") else as_of,
        "period_type": period_type,
        "labels": {
            "measurement": MEASUREMENT.get(measurement),
            "entity_scope": ENTITY_SCOPE.get(entity_scope),
            "share_scope": SHARE_SCOPE.get(share_scope),
            "trust_included": TRUST_INCLUDED.get(trust_included),
            "period_type": PERIOD_TYPE.get(period_type),
        },
        "not_comparable": NOT_COMPARABLE,
    }


def basis_for_rows(rows, as_of=None, holder_key="holder_table",
                   class_key="share_class"):
    """Basis for a figure aggregated over `rows` — scopes read off the rows."""
    rows = rows or ()
    return basis(as_of=as_of,
                 entity_scope=entity_scope_for([r.get(holder_key) for r in rows]),
                 share_scope=share_scope_for([r.get(class_key) for r in rows]))


# Cross-sectional surfaces span many filers with different fiscal year ends, so
# there is no single as_of; the scope is the whole group and both share classes
# because every filer's named rows are summed.
def market_basis(as_of=None):
    return basis(as_of=as_of, entity_scope="holdco_consolidated",
                 share_scope="both")


def label_rows():
    """The vocabulary as rows, for eq_basis_labels. Registry data."""
    out = []
    for field, table in (("measurement", MEASUREMENT),
                         ("entity_scope", ENTITY_SCOPE),
                         ("share_scope", SHARE_SCOPE),
                         ("trust_included", TRUST_INCLUDED),
                         ("period_type", PERIOD_TYPE)):
        for value, note in sorted(table.items()):
            out.append((field, value, note))
    return out
