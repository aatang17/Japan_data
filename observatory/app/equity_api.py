# -*- coding: utf-8 -*-
"""Equity product API — cross-shareholdings (政策保有株式).

Product #2's namespace. Reads its own DuckDB file (data/equity.duckdb, written
offline by equity/extract.py — one writer at a time, same discipline as the
macro DB). Deliberately outside the macro core: none of the /{dataset}/ shapes
apply here, and this router must be registered BEFORE the core router so its
literal /equity/ paths win over the core's /{dataset}/ catch-alls.

Trust contract: share counts, book values, purposes and reciprocity are
Official (as filed) — every row carries its filing doc_id, filed date and the
archived file's SHA-256. Year-on-year changes are derived client-side and carry
their formula there.
"""
import datetime
import pathlib
import threading

import duckdb
from fastapi import APIRouter, HTTPException, Query

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "equity.duckdb"

router = APIRouter(prefix="/api/v1/equity")

_READER = None
_READER_VERSION = None
_LOCK = threading.Lock()


def _version():
    try:
        st = DB_PATH.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _cur():
    global _READER, _READER_VERSION
    if not DB_PATH.exists():
        raise HTTPException(503, "equity database not built yet")
    version = _version()
    with _LOCK:
        if _READER is None or _READER_VERSION != version:
            if _READER is not None:
                _READER.close()
            _READER = duckdb.connect(str(DB_PATH), read_only=True)
            _READER_VERSION = version
        return _READER.cursor()


def _rows(cur, sql, params=()):
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# How far each extractor has read the EDINET archive. This is the equity
# equivalent of the ingest health report, and it exists because nothing like
# it did: when the 5% filings stopped advancing on 2026-08-06 every dashboard
# still rendered, every endpoint still answered 200, and the only way to see
# the problem was to notice that the newest filing was a month old.
#
# EDINET publishes on business days, and Japan's longest normal closure (the
# New Year period, plus the weekends either side) runs to about six days, so
# seven is the shortest threshold that never cries wolf.
EXTRACT_STALE_AFTER_DAYS = 7


def coverage():
    """[(extractor, through_date, ran_at)] — empty if never recorded."""
    if not DB_PATH.exists():
        return []
    cur = _cur()
    names = {r[0] for r in cur.execute(
        "SELECT table_name FROM duckdb_tables()").fetchall()}
    if "eq_extract_runs" not in names:
        return []
    cur.execute("SELECT extractor, through_date, ran_at FROM eq_extract_runs "
                "ORDER BY extractor")
    return cur.fetchall()


def health():
    """Per-extractor freshness, in the shape /catalog/health uses."""
    today = datetime.date.today()
    out = []
    for extractor, through, ran in coverage():
        days = (today - through).days if through else None
        stale = days is None or days > EXTRACT_STALE_AFTER_DAYS
        out.append({
            "dataset": extractor,
            "status": "attention" if stale else "ok",
            "archive_read_through": through.isoformat() if through else None,
            "days_behind": days,
            "stale_after_days": EXTRACT_STALE_AFTER_DAYS,
            "stale": stale,
            "last_extracted_at": ran.isoformat() + "Z" if ran else None,
        })
    return out


# The archive holds five fiscal years, so "one row per filing" is never the
# right population for a cross-section: summing book value over every filing a
# company ever made would overstate the total several times over, and the same
# holder would appear once per year in a holder list. Every cross-sectional
# surface therefore runs against ONE filing per company — its latest, or the
# one covering ?year= — while the year-on-year series lives in /history.
LATEST_FILINGS = """
    WITH scoped AS (
        SELECT *, coalesce(sec_code, edinet_code, doc_id) AS filer_key
        FROM eq_filings
        WHERE status IN ('clean','partial')
          AND (CAST(? AS VARCHAR) IS NULL
               OR CAST(year(period_end) AS VARCHAR) = CAST(? AS VARCHAR))
    ),
    current_filings AS (
        SELECT * FROM (
            SELECT *, row_number() OVER (PARTITION BY filer_key
                                         ORDER BY period_end DESC, filed_date DESC) AS rn
            FROM scoped
        ) WHERE rn = 1
    )
"""


def _year_params(year):
    y = (year or "").strip() or None
    return [y, y]


# A filing names its holdings in Japanese, but every annual report states the
# FILER's own English name on its cover page (【英訳名】) — and that is the name
# used here: as filed, and complete, since all 4,226 filers with a securities
# code state one. EDINET's filer registry is only the fallback, for the few held
# companies that file no annual report of their own; the registry alone missed
# roughly one listed filer in ten, Murata Manufacturing among them. Dating the
# registry rows to 1900 makes the filing win wherever both exist.
NAME_CTES = """,
    en_ecode AS (
        SELECT edinet_code, max_by(name_en, ord) AS name_en FROM (
            SELECT edinet_code, filer_name_en AS name_en, period_end AS ord
            FROM eq_filings WHERE filer_name_en IS NOT NULL
            UNION ALL
            SELECT edinet_code, name_en, DATE '1900-01-01'
            FROM eq_entities WHERE name_en IS NOT NULL)
        WHERE edinet_code IS NOT NULL GROUP BY 1),
    en_scode AS (
        SELECT sec_code, max_by(name_en, ord) AS name_en FROM (
            SELECT sec_code, filer_name_en AS name_en, period_end AS ord
            FROM eq_filings WHERE filer_name_en IS NOT NULL AND sec_code IS NOT NULL
            UNION ALL
            SELECT sec_code, name_en, DATE '1900-01-01'
            FROM eq_entities WHERE name_en IS NOT NULL AND sec_code IS NOT NULL)
        GROUP BY 1)
"""

# Ownership percentage. There is no price feed in this product and there does
# not need to be one: for a single-class listed stock, a stake's share of market
# capitalisation IS its share of shares outstanding. The denominator therefore
# comes from the issuer's OWN annual report — issued shares at its fiscal year
# end, less treasury — which we already hold, because most issuers of policy
# holdings are themselves filers.
#
# Two dates never line up. The holder reports its stake at its own fiscal year
# end; the issuer reports its share count at the issuer's. We take the issuer
# filing NEAREST that date, either side, because nearest-in-time is the best
# estimate of the share base the stake was measured against — an issuer report
# three months later describes it better than one nine months earlier. Ties go
# to the earlier filing, and the date used is always returned.
#
# The failure this guards against is a stock split inside that window. The
# holder's share count is post-split and the issuer's pre-split, so the stake
# reads high by the split ratio — Hulic's stake in Fuyo General Lease read
# 41.8% against a pre-split denominator where the real figure is ~13.9%, and
# the 3-for-1 and 5-for-1 splits of the last two years put 2,502 positions in
# that state. Where the issuer's share count moves by BASIS_MOVE_LIMIT or more
# across the window, the share base is indeterminate and no percentage is
# published. Detect, disclose, never fill — the same rule the yen totals follow.
BASIS_WINDOW_DAYS = 550          # an annual filer, plus room for one missed year
BASIS_MOVE_LIMIT = 1.5           # split or major issuance inside the window

OWNERSHIP_CTE = (""",
    issuer_shares AS (
        SELECT edinet_code, period_end, outstanding, share_classes,
               lag(outstanding) OVER (PARTITION BY edinet_code
                                      ORDER BY period_end) AS prev_outstanding
        FROM (SELECT edinet_code, period_end, share_classes,
                     issued_shares - coalesce(treasury_shares, 0) AS outstanding
              FROM eq_filings
              WHERE status IN ('clean','partial')
                AND issued_shares IS NOT NULL
                AND issued_shares - coalesce(treasury_shares, 0) > 0)
    ),
    basis_candidates AS (
        SELECT h.doc_id, h.held_edinet_code AS edinet_code,
               i.period_end, i.outstanding, i.share_classes, i.prev_outstanding,
               i.period_end <= f.period_end AS at_or_before,
               abs(date_diff('day', i.period_end, f.period_end)) AS gap,
               -- nearest wins; a tie goes to the filing at or before the
               -- holding's date, which is the as-filed reading.
               2 * abs(date_diff('day', i.period_end, f.period_end))
                 + CASE WHEN i.period_end <= f.period_end THEN 0 ELSE 1 END AS rank_key
        FROM eq_holdings h
        JOIN eq_filings f ON f.doc_id = h.doc_id
        JOIN issuer_shares i ON i.edinet_code = h.held_edinet_code
        WHERE abs(date_diff('day', i.period_end, f.period_end)) <= %d
    ),
    basis_agg AS (
        SELECT doc_id, edinet_code,
               arg_min(outstanding, rank_key) AS outstanding,
               arg_min(period_end, rank_key) AS basis_period_end,
               arg_min(share_classes, rank_key) AS share_classes,
               arg_min(gap, rank_key) AS basis_gap,
               arg_min(prev_outstanding, rank_key) AS prev_outstanding,
               arg_min(outstanding, rank_key) FILTER (WHERE at_or_before) AS before_out,
               arg_min(outstanding, rank_key) FILTER (WHERE NOT at_or_before) AS after_out
        FROM basis_candidates GROUP BY 1, 2
    ),
    issuer_basis AS (
        SELECT doc_id, edinet_code, outstanding, basis_period_end, share_classes,
               prev_outstanding,
               -- Only a denominator measured on a DIFFERENT date can straddle a
               -- split. Where the issuer's year end is the holding's year end —
               -- the common case, both being 31 March — the count is exact and
               -- a change in the following year says nothing about it.
               basis_gap > 0
                 AND before_out IS NOT NULL AND after_out IS NOT NULL
                 AND greatest(before_out, after_out)
                     >= %s * least(before_out, after_out) AS basis_ambiguous
        FROM basis_agg
    )
""") % (BASIS_WINDOW_DAYS, BASIS_MOVE_LIMIT)

# One expression, both directions of the page, so the two can never disagree.
#
# Three things stop a percentage being published, and each one has a reason the
# page can show instead of a bare dash:
#
# 1. The issuer's share count moved across the window and nothing places the
#    holding on one side of the move (see basis_ambiguous above).
# 2. The POSITION's own share count multiplied while the issuer's did not. That
#    is a split the issuer has not filed for yet: the holder restates its
#    holding onto the new share base a year before the issuer's next annual
#    report reaches us. Mitsubishi's Ise Chemicals holding went 577,604 to
#    3,726,040 shares against a share count that never moved, and read 73% of a
#    company it holds about a seventh of. Where the issuer's count moved WITH
#    the position, the opposite is true — the two agree, and that agreement
#    resolves case 1, which is why Hulic's post-split Fuyo General Lease stake
#    still publishes.
# 3. The result exceeds 100%, which cannot be a stake in any company. It means
#    the denominator belongs to the wrong share base, and it is a fault to
#    report rather than a number to print.
POSITION_RESTATED = "h.prior_shares > 0 AND h.shares >= %s * h.prior_shares" % BASIS_MOVE_LIMIT
ISSUER_RESTATED = ("i.prev_outstanding > 0 AND i.outstanding >= %s * i.prev_outstanding"
                   % BASIS_MOVE_LIMIT)

PCT_UNAVAILABLE = """
       CASE WHEN h.shares IS NULL OR i.outstanding IS NULL THEN NULL
            WHEN ({restated}) AND NOT ({issuer_restated})
                 THEN 'holding restated onto a share base the issuer has not filed yet'
            WHEN i.basis_ambiguous AND NOT (({restated}) AND ({issuer_restated}))
                 THEN 'issuer share count changed over this window'
            WHEN 100.0 * h.shares / i.outstanding > 100
                 THEN 'stake exceeds the shares outstanding we hold'
            END""".format(restated=POSITION_RESTATED, issuer_restated=ISSUER_RESTATED)

# Filers occasionally tag a figure at the wrong scale — a book value entered in
# 百万円 into a 円 field, or a share count in thousands. The two filed numbers
# are then mutually impossible: no listed Japanese share carries a book value of
# ¥1,000,000 per share. The row is kept exactly as filed (both numbers stay), is
# flagged, and is left OUT of aggregate yen, with the exclusion disclosed —
# the same discipline as the reconciliation gate: detect, disclose, never fill.
# Five reclassified rows breach it, and they would otherwise carry ¥319trn of a
# ¥328trn total.
IMPLAUSIBLE_YEN_PER_SHARE = 1000000

PLAUSIBLE_SQL = ("(r.shares IS NULL OR r.shares <= 0 OR r.book_value_yen IS NULL "
                 "OR r.book_value_yen * 1.0 / r.shares < %d)" % IMPLAUSIBLE_YEN_PER_SHARE)

PCT_SELECT = """
       CASE WHEN h.shares IS NOT NULL AND i.outstanding > 0
                 AND ({unavailable}) IS NULL
            THEN 100.0 * h.shares / i.outstanding END AS pct_outstanding,
       ({unavailable}) AS pct_unavailable,
       i.basis_period_end AS pct_basis_period_end,
       i.share_classes AS pct_share_classes,
       -- The mirror of pct_outstanding. That one sizes a stake against the
       -- ISSUER; these size the SAME position against the HOLDER's own balance
       -- sheet, both figures off the holder's filing (`f` is the holder's
       -- filing in both queries that use this block). Guarded on > 0: a
       -- percentage of negative or absent equity is not a reading.
       CASE WHEN h.book_value_yen IS NOT NULL AND f.equity_yen > 0
            THEN 100.0 * h.book_value_yen / f.equity_yen END AS pct_of_holder_equity,
       CASE WHEN h.book_value_yen IS NOT NULL AND f.total_assets_yen > 0
            THEN 100.0 * h.book_value_yen / f.total_assets_yen END AS pct_of_holder_assets,
       f.equity_basis AS holder_equity_basis,
       f.equity_yen AS holder_equity_yen,
       f.total_assets_yen AS holder_total_assets_yen,
       NOT ({plausible}) AS implausible
""".format(unavailable=PCT_UNAVAILABLE.strip(),
           plausible=PLAUSIBLE_SQL.replace("r.", "h."))

PCT_JOIN = """
        LEFT JOIN issuer_basis i ON i.doc_id = h.doc_id
             AND i.edinet_code = h.held_edinet_code
"""

OWNERSHIP_CALC = ("shares held ÷ (issuer's issued shares − treasury shares) × 100, "
                  "both as filed, the denominator taken from the issuer's own "
                  "annual securities report nearest the holding's fiscal year end")

OWNERSHIP_NOTE = ("Derived, not filed. The denominator is the issuer's own "
                  "reported issued shares less treasury shares, from its annual "
                  "report nearest this holding's fiscal year end on either side "
                  "— pct_basis_period_end gives that date, and it can fall after "
                  "the holding's date where that report is the closer one. For a "
                  "single-class listed stock this equals the stake's share of "
                  "market capitalisation. It is null where the issuer files no "
                  "annual report we hold; where the issuer's share count moves "
                  "by half or more across the window, because a split or issue "
                  "makes the share base indeterminate; and where the result "
                  "would exceed 100%, which is a data fault rather than a "
                  "stake. It is less exact where the issuer has more than one "
                  "share class (pct_share_classes > 1), because treasury shares "
                  "are reported across all classes.")


IMPLAUSIBLE_NOTE = (
    "A row is flagged implausible when its two filed numbers are mutually "
    "impossible — book value ÷ shares of ¥%s or more, which no listed Japanese "
    "share reaches. It is a filer tagging error (a value entered at the wrong "
    "scale, or a share count in thousands), not an extraction error: the values "
    "match the filing's XBRL exactly. Flagged rows are still returned, exactly "
    "as filed, but are excluded from the yen aggregates here and counted in "
    "excluded_positions / excluded_yen so the exclusion is visible."
    % "{:,}".format(IMPLAUSIBLE_YEN_PER_SHARE))

HOLDER_SHARE_CALC = ("this position's book value ÷ the holder's shareholders' "
                     "equity (or total assets) × 100, both as filed in the "
                     "holder's own annual securities report")

HOLDER_SHARE_NOTE = (
    "The mirror of pct_outstanding. That sizes a stake against the ISSUER — how "
    "much of the issuer this holder owns. pct_of_holder_equity and "
    "pct_of_holder_assets size the same position against the HOLDER: how much "
    "of its own capital is committed to this one name. Calculated, not filed. "
    "Null where the holder's filing gives no usable denominator, never zero. "
    "holder_equity_basis says which accounting figure the denominator is, and a "
    "parent_only basis is not comparable with a consolidated one. "
    "A position CAN legitimately exceed 100% of equity — a holder whose book "
    "equity is smaller than one long-held stake is a real and commercially "
    "interesting case, not an error — so no ceiling is imposed. Extreme values "
    "are worth checking against the filing: where the position's own two filed "
    "numbers are mutually impossible the row is marked `implausible`, but that "
    "test catches only scale errors visible per share, so it does not catch "
    "every bad figure. The book value and share count are returned alongside "
    "so the reader can check.")

RECLASSIFIED_NOTE = (
    "As filed, from the annual report's 保有目的を変更した投資株式 table. "
    "direction=to_pure means the filer moved the holding from a policy "
    "shareholding to 純投資目的 (pure investment); the shares are not "
    "necessarily sold, and the position leaves the named policy table in the "
    "year of the change. direction=to_policy is the reverse. fy_of_change_ja is "
    "the fiscal year the filer states the change took effect, verbatim — some "
    "filers list more than one. A filing repeats these rows for several years "
    "after the change, so this is a standing disclosure, not a one-year event.")

FILING_NOTES_NOTE = (
    "The filing's own numbered footnotes to the named policy table, verbatim. "
    "The XBRL numbers them (注)1, (注)2 … and gives no link back to a row, so "
    "a note is tied to a position only where it names that issuer.")

FLOWS_NOTE = (
    "The filer's own tally, as filed, of how many issues increased or decreased "
    "during the year and the yen involved — acquisition cost for increases, "
    "sale proceeds for decreases. Read against the reclassification table this "
    "separates what was actually sold from what merely changed category. "
    "Counts are as filed and are not corrected for filer tagging errors.")

# How big the policy book is relative to the filer's own balance sheet.
#
# The numerator is the filing's OWN total for the whole policy bucket, not our
# sum of the named rows: the named table lists only the largest issues, and
# over seven large financials those rows carry 74.5% of the tagged total —
# 55.5% at Mizuho. Totals are summed across the entities a filing discloses
# (the filer itself, and where different the group's largest and second largest
# holders), because those are separate legal entities inside the same
# consolidated balance sheet. That summing is what separates 42% from 66% at
# MS&AD; for 94% of filers only one entity is disclosed and it changes nothing.
#
# It is a FLOOR, not the group total: a filing names at most those entities, so
# holdings elsewhere in the group are disclosed nowhere and are not counted.
SCALE_ENTITY_LABEL = {"reporting": "The filer itself",
                      "largest": "Largest holder in the group",
                      "second_largest": "Second largest holder in the group"}

# Which rung of the equity ladder the filing actually tagged. JGAAP 純資産 and
# the including-minorities IFRS/US-GAAP totals are comparable; the parent-share
# figures exclude non-controlling interests and so read slightly high as a
# denominator; parent-only is a different measure altogether and says so.
EQUITY_BASIS_LABEL = {
    "jgaap_consolidated": "Consolidated net assets (Japanese GAAP)",
    "ifrs_consolidated": "Consolidated total equity (IFRS)",
    "ifrs_consolidated_excl_nci":
        "Consolidated equity attributable to owners of the parent (IFRS)",
    "usgaap_consolidated": "Consolidated total equity (US GAAP)",
    "usgaap_consolidated_excl_nci":
        "Consolidated equity attributable to owners of the parent (US GAAP)",
    "parent_only": "Parent company only — not consolidated",
}

SCALE_EQUITY_CALC = ("total policy shareholdings ÷ shareholders' equity × 100, "
                     "both as filed in this annual securities report")

SCALE_ASSETS_CALC = ("total policy shareholdings ÷ total assets × 100, "
                     "both as filed in this annual securities report")

SCALE_NOTE = (
    "The policy total is Official (as filed) — the filing's own total carrying "
    "amount for the whole policy bucket, listed and unlisted, summed across the "
    "entities the filing discloses. It is a floor: holdings at group companies "
    "the filing does not name are disclosed nowhere and are not included. The "
    "percentages are calculated, not filed, and carry their formula. "
    "equity_basis names which figure the denominator is, because filers report "
    "under Japanese, IFRS or US accounting standards and an adopter of the "
    "latter two stops tagging the Japanese consolidated figure — a parent-only "
    "denominator is a different measure and is labelled as one, never silently "
    "mixed with a group figure. Percentages are null where equity or total "
    "assets is missing or not positive; missing is never shown as zero.")

# Stated because it is the published threshold professional readers apply, and
# it is a fact about a third party's policy, not our judgement of a company.
SCALE_REFERENCE = (
    "ISS's Japan proxy voting guidelines recommend a vote against the top "
    "executive at a company that allocates 20 percent or more of its net "
    "assets to cross-shareholdings, a policy effective from February 2022. "
    "ISS counts unilateral holdings, not only mutual ones.")

NAMES_NOTE = ("English company names are as filed: each company's own annual "
              "report states its English name on the cover page. For a company "
              "that files no annual report, EDINET's filer registry is used "
              "instead. The as-filed Japanese name is always returned alongside.")

# EDINET records a filer's sector in Japanese only. These are the standard TSE
# 33 sectors, whose English names JPX publishes, plus the filer types EDINET
# puts in the same field for entities that are not listed companies. A fixed
# lookup, never a translation: an unknown value returns None and the page shows
# the Japanese as recorded.
INDUSTRY_EN = {
    u"水産・農林業": "Fishery, Agriculture & Forestry",
    u"鉱業": "Mining",
    u"建設業": "Construction",
    u"食料品": "Foods",
    u"繊維製品": "Textiles & Apparels",
    u"パルプ・紙": "Pulp & Paper",
    u"化学": "Chemicals",
    u"医薬品": "Pharmaceutical",
    u"石油・石炭製品": "Oil & Coal Products",
    u"ゴム製品": "Rubber Products",
    u"ガラス・土石製品": "Glass & Ceramics Products",
    u"鉄鋼": "Iron & Steel",
    u"非鉄金属": "Nonferrous Metals",
    u"金属製品": "Metal Products",
    u"機械": "Machinery",
    u"電気機器": "Electric Appliances",
    u"輸送用機器": "Transportation Equipment",
    u"精密機器": "Precision Instruments",
    u"その他製品": "Other Products",
    u"電気・ガス業": "Electric Power & Gas",
    u"陸運業": "Land Transportation",
    u"海運業": "Marine Transportation",
    u"空運業": "Air Transportation",
    u"倉庫・運輸関連": "Warehousing & Harbor Transportation Services",
    u"情報・通信業": "Information & Communication",
    u"卸売業": "Wholesale Trade",
    u"小売業": "Retail Trade",
    u"銀行業": "Banks",
    u"証券、商品先物取引業": "Securities & Commodities Futures",
    u"保険業": "Insurance",
    u"その他金融業": "Other Financing Business",
    u"不動産業": "Real Estate",
    u"サービス業": "Services",
    u"その他": "Others",
    u"個人（組合発行者を除く）": "Individual (excluding partnership issuers)",
    u"個人（非居住者）（組合発行者を除く）":
        "Individual, non-resident (excluding partnership issuers)",
    u"内国法人・組合（有価証券報告書等の提出義務者以外）":
        "Domestic corporation or partnership (not an annual-report filer)",
    u"外国法人・組合（有価証券報告書等の提出義務者以外）":
        "Foreign corporation or partnership (not an annual-report filer)",
    u"外国法人・組合": "Foreign corporation or partnership",
    u"外国政府等": "Foreign government or equivalent",
}

PROVENANCE = {
    "trust": "official",
    "note": ("Figures exactly as filed in each company's 有価証券報告書 "
             "(annual securities report), EDINET. Raw filings archived with "
             "SHA-256; doc_id links to the source filing."),
}


# A share count that jumps without a purchase is the second-most common way to
# misread this data (the first is a reclassification). Filers say so themselves,
# in the row's stated purpose or in the table's footnotes, and the events are a
# closed vocabulary. Detection is keyword matching on the filed text — derived,
# so it carries this rule rather than a badge, and the filed text always travels
# with the flag so a reader can check it.
CORPORATE_ACTIONS = [
    ("株式分割", "share split"),
    ("株式併合", "share consolidation"),
    ("株式交換", "share exchange"),
    ("株式移転", "share transfer"),
    ("会社分割", "company split"),
    ("合併", "merger"),
    ("持株会社", "holding-company reorganisation"),
    ("商号変更", "name change"),
    ("公開買付", "tender offer"),
    ("上場廃止", "delisting"),
]

ACTION_CALC = ("keyword match over the filing's own stated purpose and table "
               "footnotes: " + "、".join(ja for ja, _ in CORPORATE_ACTIONS))

RATIO_CALC = ("current shares ÷ prior shares where that ratio is an exact whole "
              "number (or its exact reciprocal) — the signature of a split or a "
              "consolidation rather than a trade")

_LEGAL = ("株式会社", "㈱", "（株）", "(株)", "ホールディングス", "グループ本社",
          "有限会社", "合同会社")


def _base_name(s):
    """Issuer name reduced to its core, for finding it inside a footnote."""
    s = (s or "").strip()
    for token in _LEGAL:
        s = s.replace(token, "")
    return s.replace(" ", "").replace("\u3000", "")


def _actions_in(text):
    return [en for ja, en in CORPORATE_ACTIONS if ja in (text or "")]


def _share_ratio(shares, prior):
    """Exact whole-number ratios only. 2,723,220 / 544,644 = 5.00 is a split;
    1,224,000 / 612,000 = 2.00 is a split; anything inexact is a trade."""
    if not shares or not prior or shares <= 0 or prior <= 0:
        return None
    if shares > prior and shares % prior == 0:
        return float(shares // prior)
    if prior > shares and prior % shares == 0:
        return round(1.0 / (prior // shares), 6)
    return None


def _annotate(holdings, notes, reclassified=()):
    """Attach corporate-action flags to each position, in place.

    A footnote is tied to a position when it names that issuer; the footnote
    numbers in the XBRL are the notes' own (注)1, (注)2 … and carry no link
    back to a row, so the name is the only join the filing gives us.

    The same name match carries the reclassification flag back onto the named
    table, which is where it answers the question a reader actually has: a row
    whose current column is blank did not necessarily go anywhere.
    """
    indexed = [(n, _base_name(n.get("text_ja"))) for n in notes]
    moved = set()
    for r in reclassified:
        if r.get("direction") == "to_pure":
            base = _base_name(r.get("held_name_raw"))
            if base:
                moved.add(base)
    for h in holdings:
        name = _base_name(h.get("held_name_raw"))
        hit = [n for n, base in indexed if name and len(name) >= 2 and name in base]
        found = _actions_in(h.get("purpose_ja"))
        for n in hit:
            for a in _actions_in(n["text_ja"]):
                if a not in found:
                    found.append(a)
        h["corporate_actions"] = found
        h["note_refs"] = [n["note_no"] for n in hit]
        h["share_ratio"] = _share_ratio(h.get("shares"), h.get("prior_shares"))
        h["reclassified_to_pure"] = bool(name) and name in moved
    return holdings


@router.get("/years")
def years():
    """Fiscal years available, newest first — the feed for a year picker."""
    cur = _cur()
    return {"years": _rows(cur, """
        SELECT CAST(year(period_end) AS VARCHAR) AS year,
               count(*) AS filings, min(period_end) AS first_period_end,
               max(period_end) AS last_period_end
        FROM eq_filings WHERE status IN ('clean','partial') AND period_end IS NOT NULL
        GROUP BY 1 ORDER BY 1 DESC""")}


@router.get("/summary")
def summary(year: str = Query("", description="fiscal year, e.g. 2025; default latest")):
    cur = _cur()
    head = _rows(cur, LATEST_FILINGS + """
        SELECT count(DISTINCT f.filer_key)                        AS filers,
               count(*)                                          AS named_holdings,
               sum(h.book_value_yen)                             AS total_book_value_yen,
               sum(CASE WHEN h.shares < h.prior_shares THEN 1 ELSE 0 END) AS positions_reduced,
               sum(CASE WHEN h.shares > h.prior_shares THEN 1 ELSE 0 END) AS positions_increased,
               sum(CASE WHEN h.shares = h.prior_shares THEN 1 ELSE 0 END) AS positions_unchanged,
               sum(CASE WHEN h.shares IS NULL OR h.prior_shares IS NULL
                        THEN 1 ELSE 0 END)                        AS positions_not_comparable,
               sum(CASE WHEN h.reciprocal LIKE '有%' THEN 1 ELSE 0 END)   AS reciprocal_pairs,
               min(f.period_end)                                 AS earliest_period_end,
               max(f.period_end)                                 AS latest_period_end
        FROM eq_holdings h JOIN current_filings f USING (doc_id)
    """, _year_params(year))[0]
    status = _rows(cur, "SELECT status, count(*) AS n FROM eq_filings GROUP BY 1")
    head["extraction_status"] = {r["status"]: r["n"] for r in status}
    head["filings_total_all_years"] = sum(r["n"] for r in status)
    head["scope"] = ("fiscal year %s" % year.strip()) if year.strip() else \
        "each company's latest filing"
    # Japanese year-ends are staggered and a company that has delisted or merged
    # stops filing, so a "latest filing" cross-section mixes reference periods.
    # Publish that spread rather than a single max date, which would read as an
    # as-of it isn't.
    head["as_of_composition"] = _rows(cur, LATEST_FILINGS + """
        SELECT CAST(f.period_end AS VARCHAR)[1:4] AS year,
               count(DISTINCT f.filer_key) AS filers
        FROM current_filings f JOIN eq_holdings h USING (doc_id)
        GROUP BY 1 ORDER BY 1 DESC""", _year_params(year))
    head["as_of_note"] = ("Each company's most recent annual report, counting only "
                          "filers that disclosed named holdings. Japanese fiscal "
                          "year-ends are staggered, and a company that has delisted "
                          "or merged stops filing, so reference periods differ by "
                          "company — see as_of_composition. Request ?year= for a "
                          "single fiscal year.")
    # Most positions simply do not move, and a share count can rise without a
    # purchase when the issuer splits its stock. Publishing cut-vs-added alone
    # would read as accumulation across the market, which is not what the
    # filings say — the unchanged and not-comparable counts are the context.
    head["position_change_note"] = ("Share-count comparison against the same "
                                    "filing's prior-year column. A stock split "
                                    "raises the count without a purchase, so "
                                    "'increased' overstates buying; most positions "
                                    "are unchanged.")
    head["provenance"] = PROVENANCE
    return head


@router.get("/companies")
def companies(q: str = Query("", description="name or code substring")):
    """Search box feed: filers with extracted tables and/or companies that are held."""
    cur = _cur()
    like = "%" + q.strip() + "%"
    # Match the code, the as-filed Japanese name and the registry English name.
    # The match runs AFTER the filer and held rows are grouped into one row per
    # company: filtering the two branches separately would drop a company's
    # held-by count whenever only its filer name matched the query.
    return {"companies": _rows(cur, LATEST_FILINGS + NAME_CTES + """,
        filers AS (
            SELECT f.sec_code, max(f.filer_name) AS name, max(n.name_en) AS name_en,
                   count(h.doc_id) AS holdings, 0 AS held_by
            FROM current_filings f LEFT JOIN eq_holdings h USING (doc_id)
            LEFT JOIN en_ecode n ON n.edinet_code = f.edinet_code
            WHERE f.sec_code IS NOT NULL GROUP BY 1),
        held AS (
            SELECT h.held_sec_code AS sec_code, max(h.held_name_raw) AS name,
                   max(n.name_en) AS name_en, 0 AS holdings, count(*) AS held_by
            FROM eq_holdings h JOIN current_filings f USING (doc_id)
            LEFT JOIN en_ecode n ON n.edinet_code = h.held_edinet_code
            WHERE h.held_sec_code IS NOT NULL GROUP BY 1),
        combined AS (
            SELECT u.sec_code, max(u.name) AS name,
                   coalesce(max(u.name_en), max(s.name_en)) AS name_en,
                   sum(u.holdings) AS holdings_count, sum(u.held_by) AS held_by_count
            FROM (SELECT * FROM filers UNION ALL SELECT * FROM held) u
            LEFT JOIN en_scode s ON s.sec_code = u.sec_code
            GROUP BY u.sec_code)
        SELECT * FROM combined
        WHERE sec_code LIKE ? OR name LIKE ?
           OR lower(coalesce(name_en, '')) LIKE lower(?)
        ORDER BY holdings_count + held_by_count DESC LIMIT 25
    """, _year_params("") + [like, like, like]),
        "names_note": NAMES_NOTE}


@router.get("/company/{sec_code}")
def company(sec_code: str):
    """Both directions for one company: what it holds, and who holds it."""
    cur = _cur()
    ent = _rows(cur, """
        WITH x AS (SELECT 1)""" + NAME_CTES + """
        SELECT e.edinet_code, e.sec_code, e.name_ja,
               coalesce(n.name_en, s.name_en) AS name_en, e.industry
        FROM eq_entities e
        LEFT JOIN en_ecode n ON n.edinet_code = e.edinet_code
        LEFT JOIN en_scode s ON s.sec_code = e.sec_code
        WHERE e.sec_code = ? LIMIT 1""", [sec_code])
    if ent:
        ent[0]["industry_en"] = INDUSTRY_EN.get(ent[0]["industry"])
    filing = _rows(cur, """
        WITH x AS (SELECT 1)""" + NAME_CTES + """
        SELECT f.doc_id, f.filer_name, coalesce(n.name_en, s.name_en) AS filer_name_en,
               f.period_end, f.filed_date, f.sha256, f.status
        FROM eq_filings f
        LEFT JOIN en_ecode n ON n.edinet_code = f.edinet_code
        LEFT JOIN en_scode s ON s.sec_code = f.sec_code
        WHERE f.sec_code = ?
        ORDER BY f.period_end DESC LIMIT 1""", [sec_code])
    holdings = []
    if filing:
        holdings = _rows(cur, """
            WITH x AS (SELECT 1)""" + NAME_CTES + OWNERSHIP_CTE + """
            SELECT h.holder_table, h.held_name_raw,
                   coalesce(n.name_en, s.name_en) AS held_name_en,
                   h.held_sec_code, h.match_status,
                   h.shares, h.book_value_yen, h.prior_shares, h.prior_book_value_yen,
                   h.purpose_ja, h.reciprocal,
""" + PCT_SELECT + """
            FROM eq_holdings h
            JOIN eq_filings f ON f.doc_id = h.doc_id
            LEFT JOIN en_ecode n ON n.edinet_code = h.held_edinet_code
            LEFT JOIN en_scode s ON s.sec_code = h.held_sec_code
""" + PCT_JOIN + """
            WHERE h.doc_id = ?
            ORDER BY h.book_value_yen DESC NULLS LAST""", [filing[0]["doc_id"]])
    # one row per holder — its latest filing — not one row per holder per year
    holders = _rows(cur, LATEST_FILINGS + NAME_CTES + OWNERSHIP_CTE + """
        SELECT f.filer_name AS holder_name,
               coalesce(n.name_en, s.name_en) AS holder_name_en,
               f.sec_code AS holder_sec_code,
               f.doc_id, f.period_end, h.holder_table,
               h.shares, h.book_value_yen, h.prior_shares, h.prior_book_value_yen,
               h.purpose_ja, h.reciprocal,
""" + PCT_SELECT + """
        FROM eq_holdings h JOIN current_filings f USING (doc_id)
        LEFT JOIN en_ecode n ON n.edinet_code = f.edinet_code
        LEFT JOIN en_scode s ON s.sec_code = f.sec_code
""" + PCT_JOIN + """
        WHERE h.held_sec_code = ?
        ORDER BY h.book_value_yen DESC NULLS LAST""", _year_params("") + [sec_code])
    history = _rows(cur, """
        SELECT CAST(year(f.period_end) AS VARCHAR) AS year, f.period_end,
               count(*) AS named_holdings, sum(h.book_value_yen) AS book_value_yen
        FROM eq_holdings h JOIN eq_filings f USING (doc_id)
        WHERE f.sec_code = ? AND f.status IN ('clean','partial')
        GROUP BY 1, 2 ORDER BY 1""", [sec_code])
    # The same reading, one point per annual report. Filed totals against filed
    # balance sheets, so the series is comparable year to year even though the
    # named table's composition changes.
    scale_history = _rows(cur, """
        WITH tot AS (
            SELECT doc_id, sum(book_value_yen) AS policy_total_yen
            FROM eq_filing_totals GROUP BY 1)
        SELECT CAST(year(f.period_end) AS VARCHAR) AS year, f.period_end,
               t.policy_total_yen, f.equity_yen, f.equity_basis,
               CASE WHEN f.equity_yen > 0
                    THEN 100.0 * t.policy_total_yen / f.equity_yen END
                    AS pct_of_equity,
               CASE WHEN f.total_assets_yen > 0
                    THEN 100.0 * t.policy_total_yen / f.total_assets_yen END
                    AS pct_of_assets
        FROM eq_filings f JOIN tot t USING (doc_id)
        WHERE f.sec_code = ? AND f.status IN ('clean','partial')
        ORDER BY 1""", [sec_code])
    reclassified, notes, flows = [], [], []
    scale, scale_entities = None, []
    if filing:
        doc = filing[0]["doc_id"]
        # Summed across the entities the filing discloses — see SCALE_ENTITY_
        # LABEL. Guarded on > 0 rather than IS NOT NULL: equity can be filed
        # negative, and a percentage of negative equity is not a reading.
        got = _rows(cur, """
            WITH tot AS (
                SELECT doc_id,
                       sum(book_value_yen) AS policy_total_yen,
                       sum(CASE WHEN share_class = 'listed'
                                THEN book_value_yen END) AS listed_yen,
                       sum(CASE WHEN share_class = 'unlisted'
                                THEN book_value_yen END) AS unlisted_yen,
                       sum(CASE WHEN share_class = 'listed'
                                THEN issue_count END) AS listed_issues,
                       sum(CASE WHEN share_class = 'unlisted'
                                THEN issue_count END) AS unlisted_issues
                FROM eq_filing_totals GROUP BY 1)
            SELECT t.policy_total_yen, t.listed_yen, t.unlisted_yen,
                   t.listed_issues, t.unlisted_issues,
                   f.equity_yen, f.equity_basis,
                   f.total_assets_yen, f.assets_basis,
                   CASE WHEN f.equity_yen > 0
                        THEN 100.0 * t.policy_total_yen / f.equity_yen END
                        AS pct_of_equity,
                   CASE WHEN f.total_assets_yen > 0
                        THEN 100.0 * t.policy_total_yen / f.total_assets_yen END
                        AS pct_of_assets
            FROM eq_filings f JOIN tot t USING (doc_id)
            WHERE f.doc_id = ?""", [doc])
        if got:
            scale = got[0]
            scale["equity_basis_label"] = EQUITY_BASIS_LABEL.get(
                scale["equity_basis"])
            scale["assets_basis_label"] = EQUITY_BASIS_LABEL.get(
                scale["assets_basis"])
            scale["equity_calc"] = SCALE_EQUITY_CALC
            scale["assets_calc"] = SCALE_ASSETS_CALC
            # Disclosure order, not alphabetical: the filer first, then the
            # group holders it names, which is how the filing itself reads.
            scale_entities = _rows(cur, """
                SELECT holder_table, share_class, book_value_yen, issue_count
                FROM eq_filing_totals WHERE doc_id = ?
                ORDER BY CASE holder_table WHEN 'reporting' THEN 0
                                           WHEN 'largest' THEN 1
                                           WHEN 'second_largest' THEN 2
                                           ELSE 3 END,
                         share_class""", [doc])
            for e in scale_entities:
                e["holder_table_label"] = SCALE_ENTITY_LABEL.get(
                    e["holder_table"])
        # Positions the filer moved OUT of the policy bucket into 純投資目的.
        # The shares are usually still held: the row leaves the named table
        # without a sale, so an unwind measured on the named table alone counts
        # this as a disposal. Ordered by the size of what left.
        reclassified = _rows(cur, """
            WITH x AS (SELECT 1)""" + NAME_CTES + """
            SELECT r.holder_table, r.direction, r.held_name_raw,
                   coalesce(n.name_en, s.name_en) AS held_name_en,
                   r.held_sec_code, r.match_status,
                   r.shares, r.book_value_yen, r.fy_of_change_ja, r.reason_ja,
                   NOT (""" + PLAUSIBLE_SQL + """) AS implausible
            FROM eq_reclassified r
            LEFT JOIN en_ecode n ON n.edinet_code = r.held_edinet_code
            LEFT JOIN en_scode s ON s.sec_code = r.held_sec_code
            WHERE r.doc_id = ?
            -- to_pure first: it is the direction that removes a holding from
            -- the named table, and the reason this section exists.
            ORDER BY r.direction DESC, r.book_value_yen DESC NULLS LAST""", [doc])
        notes = _rows(cur, """
            SELECT holder_table, note_no, text_ja FROM eq_filing_notes
            WHERE doc_id = ?
            ORDER BY holder_table, CAST(note_no AS INTEGER)""", [doc])
        flows = _rows(cur, """
            SELECT holder_table, share_class, issues_increased,
                   acquisition_cost_yen, issues_decreased, sale_proceeds_yen
            FROM eq_filing_flows WHERE doc_id = ?
            ORDER BY holder_table, share_class""", [doc])
        _annotate(holdings, notes, reclassified)

    if not ent and not filing and not holders:
        raise HTTPException(404, "no data for securities code %s" % sec_code)
    return {"entity": ent[0] if ent else None,
            "names_note": NAMES_NOTE,
            "filing": filing[0] if filing else None,
            "holdings": holdings,
            "holders": holders,
            "reclassified": reclassified,
            "reclassified_note": RECLASSIFIED_NOTE,
            "implausible_note": IMPLAUSIBLE_NOTE,
            "notes": notes,
            "notes_note": FILING_NOTES_NOTE,
            "flows": flows,
            "flows_note": FLOWS_NOTE,
            "scale": scale,
            "scale_entities": scale_entities,
            "scale_history": scale_history,
            "scale_note": SCALE_NOTE,
            "scale_reference": SCALE_REFERENCE,
            "ownership_calc": OWNERSHIP_CALC,
            "ownership_note": OWNERSHIP_NOTE,
            "holder_share_calc": HOLDER_SHARE_CALC,
            "holder_share_note": HOLDER_SHARE_NOTE,
            "action_calc": ACTION_CALC,
            "ratio_calc": RATIO_CALC,
            "history": history,
            "history_note": ("One point per annual report filed. Each year's book "
                             "value is as filed; book values are fair-valued at "
                             "period end, so a change reflects both trading and "
                             "market moves."),
            "provenance": PROVENANCE}


@router.get("/history")
def history(limit: int = Query(40, ge=1, le=500)):
    """Multi-year unwind: named policy-holding value per filer, per fiscal year.

    The series the five-year archive exists for. One row per filer-year, so a
    caller can chart a company's path; the cross-sectional surfaces stay on a
    single year.
    """
    cur = _cur()
    return {"rows": _rows(cur, """
        WITH x AS (SELECT 1)""" + NAME_CTES + """,
        per_year AS (
            SELECT f.sec_code, CAST(year(f.period_end) AS VARCHAR) AS year,
                   max(f.filer_name) AS name,
                   coalesce(max(n.name_en), max(s.name_en)) AS name_en,
                   max(f.period_end) AS period_end,
                   count(*) AS named_holdings,
                   sum(h.book_value_yen) AS book_value_yen
            FROM eq_holdings h JOIN eq_filings f USING (doc_id)
            LEFT JOIN en_ecode n ON n.edinet_code = f.edinet_code
            LEFT JOIN en_scode s ON s.sec_code = f.sec_code
            WHERE f.status IN ('clean','partial') AND f.sec_code IS NOT NULL
            GROUP BY 1, 2),
        ranked AS (
            SELECT sec_code, max(book_value_yen) AS peak FROM per_year GROUP BY 1
            ORDER BY peak DESC NULLS LAST LIMIT ?)
        SELECT p.* FROM per_year p JOIN ranked r USING (sec_code)
        ORDER BY r.peak DESC NULLS LAST, p.sec_code, p.year
    """, [limit]),
        "provenance": PROVENANCE,
        "names_note": NAMES_NOTE,
        "derived_note": ("Each point is the sum of named policy holdings as filed "
                         "for that fiscal year. Book values are fair-valued at "
                         "period end, so a fall reflects both selling and market "
                         "moves — position counts separate the two.")}


@router.get("/unwind")
def unwind(year: str = Query("", description="fiscal year, e.g. 2025; default latest")):
    """Sector unwind ranking: named policy-holding value change, per filer."""
    cur = _cur()
    return {"filers": _rows(cur, LATEST_FILINGS + NAME_CTES + """
        SELECT f.sec_code, max(f.filer_name) AS name,
               coalesce(max(n.name_en), max(s.name_en)) AS name_en,
               max(f.period_end) AS period_end,
               count(*) AS named_holdings,
               sum(h.book_value_yen)        AS book_value_yen,
               sum(h.prior_book_value_yen)  AS prior_book_value_yen,
               sum(CASE WHEN h.shares < h.prior_shares THEN 1 ELSE 0 END) AS reduced,
               sum(CASE WHEN h.shares > h.prior_shares THEN 1 ELSE 0 END) AS increased
        FROM eq_holdings h JOIN current_filings f USING (doc_id)
        LEFT JOIN en_ecode n ON n.edinet_code = f.edinet_code
        LEFT JOIN en_scode s ON s.sec_code = f.sec_code
        GROUP BY f.sec_code ORDER BY book_value_yen DESC NULLS LAST
    """, _year_params(year)), "provenance": PROVENANCE,
        "names_note": NAMES_NOTE,
        "derived_note": ("Value change and reduced/increased counts compare the "
                         "current and prior-year columns of the same filing — "
                         "derived; formula shown on the page.")}


@router.get("/reclassified")
def reclassified(year: str = Query("", description="fiscal year, e.g. 2025; default latest"),
                 limit: int = Query(100, ge=1, le=1000)):
    """Filers ranked by policy holdings moved to 純投資目的, not sold.

    The gap this closes: a position reclassified as pure investment vanishes
    from the named policy table without a transaction, so an unwind measured on
    that table alone books it as a disposal. Filings disclose the move
    explicitly, with the fiscal year and the filer's own reason; this ranks
    what left the bucket against what the same filing says was actually sold.
    """
    cur = _cur()
    filers = _rows(cur, LATEST_FILINGS + NAME_CTES + """,
        sold AS (
            SELECT doc_id, sum(sale_proceeds_yen) AS sale_proceeds_yen
            FROM eq_filing_flows WHERE share_class = 'listed' GROUP BY 1
        )
        SELECT f.sec_code, f.filer_name AS name,
               coalesce(n.name_en, s.name_en) AS name_en,
               f.period_end, f.doc_id,
               count(*)                    AS reclassified_positions,
               sum(CASE WHEN """ + PLAUSIBLE_SQL + """ THEN r.book_value_yen END)
                                           AS reclassified_yen,
               count(*) FILTER (WHERE NOT (""" + PLAUSIBLE_SQL + """))
                                           AS excluded_positions,
               sum(CASE WHEN NOT (""" + PLAUSIBLE_SQL + """) THEN r.book_value_yen END)
                                           AS excluded_yen,
               max(sold.sale_proceeds_yen) AS sale_proceeds_yen
        FROM eq_reclassified r
        JOIN current_filings f USING (doc_id)
        LEFT JOIN en_ecode n ON n.edinet_code = f.edinet_code
        LEFT JOIN en_scode s ON s.sec_code = f.sec_code
        LEFT JOIN sold ON sold.doc_id = f.doc_id
        WHERE r.direction = 'to_pure'
        GROUP BY f.sec_code, f.filer_name, n.name_en, s.name_en, f.period_end, f.doc_id
        ORDER BY reclassified_yen DESC NULLS LAST
        LIMIT ?
    """, _year_params(year) + [limit])
    totals = _rows(cur, LATEST_FILINGS + """
        SELECT count(DISTINCT r.doc_id)  AS filers,
               count(*)                  AS positions,
               sum(CASE WHEN """ + PLAUSIBLE_SQL + """ THEN r.book_value_yen END)
                                         AS book_value_yen,
               count(*) FILTER (WHERE NOT (""" + PLAUSIBLE_SQL + """))
                                         AS excluded_positions,
               sum(CASE WHEN NOT (""" + PLAUSIBLE_SQL + """) THEN r.book_value_yen END)
                                         AS excluded_yen
        FROM eq_reclassified r JOIN current_filings f USING (doc_id)
        WHERE r.direction = 'to_pure'
    """, _year_params(year))
    return {"filers": filers,
            "totals": totals[0] if totals else None,
            "provenance": PROVENANCE,
            "names_note": NAMES_NOTE,
            "reclassified_note": RECLASSIFIED_NOTE,
            "flows_note": FLOWS_NOTE,
            "implausible_note": IMPLAUSIBLE_NOTE,
            "coverage_note": ("One filing per filer — its latest, or the one "
                              "covering ?year=. A filing repeats a "
                              "reclassification for several years after the "
                              "change, so this is the standing disclosed stock "
                              "of reclassified holdings, not one year's flow.")}
