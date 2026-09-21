# -*- coding: utf-8 -*-
u"""Equity product API — earnings releases (決算短信, TDnet timely disclosure).

The fast half of the financial record. A company publishes its 決算短信 on the
exchange's wire roughly six weeks before the statutory report reaches EDINET,
and since April 2024 — when the statutory first- and third-quarter reports were
abolished — it is the ONLY source for those two quarters. It also carries what
EDINET never does: management's own forecast for the year.

WHAT A CONSUMER MUST NOT ASSUME, carried in the data rather than in prose:

  1. **RESULTS ARE CUMULATIVE.** A second-quarter release reports April to
     September, not July to September. Every result row says which span it
     covers; a single quarter is never derived here, because the difference of
     two rounded cumulative figures is not a published number.

  2. **A RESULT AND A FORECAST ARE THE SAME ELEMENT.** Operating income as it
     happened and operating income as promised share a name and a unit. They
     are kept in separate tables in every response and never mixed in a
     ranking.

  3. **A FORECAST MAY BE A RANGE, OR ABSENT.** Some companies guide to an upper
     and a lower bound; some give no forecast at all. An absent forecast is
     missing, never zero, and progress against it is not calculated.

  4. **ONE PERIOD CAN HAVE SEVERAL RELEASES.** A company re-issues its release
     when the auditor's review completes, and again when it corrects a number.
     Every release is kept as disclosed; the newest for a period is marked
     current and the others say which release replaced them.

  5. **THE RECORD STARTS WHEN CAPTURE STARTED.** TDnet keeps a disclosure public
     for about a month and then deletes it. Nothing before 10 July 2026 can be
     recovered from the wire.

  6. **ACCOUNTING STANDARDS ARE NOT INTERCHANGEABLE.** A Japanese-GAAP filer
     reports ordinary income, an IFRS filer profit before tax; the headline
     lines map each to the nearest published element and always name the
     element used, so nothing is silently equated.
"""
import datetime
import unicodedata

from fastapi import APIRouter, HTTPException, Query

from . import aliases, asof
from .equity_api import NAME_CTES, NAMES_NOTE, _cur, _rows

router = APIRouter(prefix="/api/v1/equity/earnings", tags=["Earnings releases"])

# Headline lines, each an ordered list of published elements: the first one a
# release carries is used, and its name travels with the value. The order puts
# the general-company element first and the sector-specific ones (banks,
# insurers, securities firms, REITs, US GAAP) after it.
LINES = (
    ("revenue", "Revenue", (
        "NetSales", "NetSalesIFRS", "SalesIFRS", "RevenueIFRS",
        "OperatingRevenuesIFRS", "OperatingRevenues", "OrdinaryRevenuesBK",
        "OrdinaryRevenuesIN", "OperatingRevenuesSE", "OperatingRevenuesREIT",
        "NetSalesUS", "TotalRevenuesUS", "OperatingRevenuesUS", "Revenue",
        "Revenue2", "GrossOperatingRevenues", "OperatingRevenuesSpecific",
        "NetSalesOfCompletedConstructionContracts",
        "TotalRevenuesAfterDeductingFinancialExpenseUS")),
    ("operating_income", "Operating income", (
        "OperatingIncome", "OperatingIncomeIFRS", "OperatingIncomeUS")),
    ("ordinary_income", "Ordinary income / profit before tax", (
        "OrdinaryIncome", "ProfitBeforeTaxIFRS", "IncomeBeforeIncomeTaxesUS")),
    ("profit", "Profit attributable to owners", (
        "ProfitAttributableToOwnersOfParent",
        "ProfitAttributableToOwnersOfParentIFRS", "NetIncomeUS", "NetIncome")),
    ("eps", "Earnings per share", (
        "NetIncomePerShare", "BasicEarningsPerShareIFRS", "NetIncomePerShareUS",
        "BasicNetIncomePerShareUS", "NetIncomePerUnitREIT")),
)
LINE_IDS = tuple(l[0] for l in LINES)
LINE_LABELS = dict((l[0], l[1]) for l in LINES)
LINE_OF = dict((el, l[0]) for l in LINES for el in l[2])
PROGRESS_LINES = ("revenue", "operating_income", "ordinary_income", "profit")

# The span a release's results cover, keyed by the release's own period.
RESULT_PERIOD = {"q1": "q1-ytd", "q2": "q2-ytd", "q3": "q3-ytd", "full-year": "year"}
PRIOR_PERIOD = {"q1": "prior-q1-ytd", "q2": "prior-q2-ytd", "q3": "prior-q3-ytd",
                "full-year": "prior-year"}
# A full-year release guides to the year that has just begun; an interim one to
# the year it is part of.
FORECAST_PERIOD = {"q1": "year", "q2": "year", "q3": "year", "full-year": "next-year"}
MONTHS_COVERED = {"q1": 3, "q2": 6, "q3": 9, "full-year": 12}
PERIOD_LABELS = {"q1": "First quarter (3 months)", "q2": "Second quarter (6 months, cumulative)",
                 "q3": "Third quarter (9 months, cumulative)", "full-year": "Full year"}

CALC = {
    "progress_pct": (
        "cumulative result ÷ full-year company forecast × 100, for the same "
        "line and basis, both as published in the same release; not calculated "
        "when the forecast is absent, a range, or zero or negative"),
    "is_current": (
        "the newest release by disclosure date and time for one company, "
        "fiscal period and quarter"),
    "fiscal_period": (
        "the fiscal year-end month printed in the release's own headline "
        "(2027年3月期 → 2027-03); era years are converted (令和9年 → 2027)"),
    "days_covered": "number of distinct disclosure days held in the archive",
}

PROVENANCE = {
    "trust": "official",
    "note": ("Figures exactly as each company tagged them in the Summary of "
             "its 決算短信 on TDnet, the Tokyo Stock Exchange's timely "
             "disclosure network. Each package is archived with its SHA-256 "
             "before parsing. Year-on-year changes are the company's own "
             "published percentages, not recalculated."),
}

CUMULATIVE_NOTE = (
    "Interim results are cumulative from the start of the fiscal year: a "
    "second-quarter release covers six months, a third-quarter release nine. "
    "A stand-alone quarter is not derived here.")

FORECAST_NOTE = (
    "Forecasts are the company's own, published in the same release as the "
    "results. They are kept apart from results in every response. A company "
    "that guides to a range has forecast_upper and forecast_lower and no "
    "single forecast; a company that gives no forecast has none, and nothing "
    "is filled in.")

REISSUE_NOTE = (
    "A company can publish more than one release for the same period: a "
    "re-issue when the auditor's interim review completes, or a correction. "
    "Every release is kept as disclosed. is_current marks the newest for its "
    "period; an earlier one names the release that replaced it.")

COVERAGE_NOTE = (
    "TDnet keeps each disclosure public for about a month and then deletes "
    "it. There is no archive, no API and no second source, so this record "
    "begins on 10 July 2026, the day capture began, and can never be "
    "back-filled.")

STANDARD_NOTE = (
    "Headline lines map each accounting standard's element to the nearest "
    "common line and always return the element used. Ordinary income "
    "(Japanese GAAP) and profit before tax (IFRS, US GAAP) share a line "
    "because they sit in the same place in the summary; they are not the same "
    "measure and are not compared across standards here.")

PROGRESS_NOTE = (
    "Progress is how much of the company's own full-year forecast the "
    "cumulative result has reached. It is a calculated figure and carries its "
    "formula. Seasonal businesses do not earn evenly through the year, so a "
    "first-quarter figure far from 25% is not in itself a surprise.")

WIRE_NOTE = (
    "The wire lists every disclosure on TDnet, not only earnings: title, "
    "time, company and a coarse kind read from the headline. The kind is for "
    "filtering, never for counting events — a company that words a headline "
    "unusually is simply 'other', and the title is always returned.")


def _require():
    cur = _cur()
    try:
        cur.execute("SELECT 1 FROM eq_tdnet_filings LIMIT 1")
    except Exception:                                            # noqa: BLE001
        raise HTTPException(503, "earnings releases dataset not published yet")
    return cur


def _vintage():
    v = asof.vintage("release")
    v["basis"] = "filed_date"
    v["note"] = (
        "as_of selects the releases disclosed on TDnet by the end of that day — "
        "what the market could read then." if v["as_of"] else
        "The newest release per company and period. Pass ?as_of=YYYY-MM-DD for "
        "the releases disclosed on TDnet by that date.")
    return v


def _notes(head):
    head["cumulative_note"] = CUMULATIVE_NOTE
    head["forecast_note"] = FORECAST_NOTE
    head["reissue_note"] = REISSUE_NOTE
    head["coverage_note"] = COVERAGE_NOTE
    head["standard_note"] = STANDARD_NOTE
    head["progress_note"] = PROGRESS_NOTE
    head["calc"] = CALC
    head["provenance"] = PROVENANCE
    head["vintage"] = _vintage()
    return head


# Every accepted release with its place in the re-issue chain. `filed_date` is
# the day TDnet published it: the name the other filing datasets use for the
# same idea, and the date the point-in-time ceiling applies to.
_RELEASES = """
    WITH rel AS (
        SELECT f.doc_key, f.disclosed_on AS filed_date, f.disclosed_at AS filed_time,
               f.sec_code, f.company_name AS name, f.title, f.period,
               f.fiscal_period, f.sha256, f.parser_version, f.status, f.facts,
               row_number() OVER (
                   PARTITION BY f.sec_code, f.fiscal_period, f.period
                   ORDER BY f.disclosed_on DESC, f.disclosed_at DESC, f.doc_key DESC) AS rn,
               first_value(f.doc_key) OVER (
                   PARTITION BY f.sec_code, f.fiscal_period, f.period
                   ORDER BY f.disclosed_on DESC, f.disclosed_at DESC, f.doc_key DESC) AS newest
        FROM eq_tdnet_filings f
        WHERE f.status IN ('clean', 'partial') AND f.sec_code IS NOT NULL/*ASOF*/
    )
"""


def releases_cte():
    return _RELEASES.replace("/*ASOF*/", asof.clause("disclosed_on", "f"))


def _nfkc(s):
    return unicodedata.normalize("NFKC", s or "")


def _flags(title):
    t = _nfkc(title)
    return {"is_correction": u"訂正" in t,
            "review_completed": u"レビューの完了" in t}


def _release_row(r):
    out = {
        "doc_key": r["doc_key"], "filed_date": r["filed_date"],
        "filed_time": r["filed_time"], "title": r["title"],
        "period": r["period"], "period_label": PERIOD_LABELS.get(r["period"]),
        "months_covered": MONTHS_COVERED.get(r["period"]),
        "fiscal_period": r["fiscal_period"],
        "is_current": r["rn"] == 1,
        "replaced_by": None if r["rn"] == 1 else r["newest"],
        "status": r["status"], "sha256": r["sha256"],
        "parser_version": r["parser_version"],
    }
    out.update(_flags(r["title"]))
    return out


def _pct(value):
    u"""A published change, stored as a fraction, as the percentage printed."""
    return None if value is None else round(value * 100.0, 1)


def _basis_of(facts):
    u"""Consolidated when the release has it; a parent-only filer's own basis."""
    bases = set(f["basis"] for f in facts if f["nature"] == "result" and f["basis"])
    if "consolidated" in bases:
        return "consolidated"
    return "parent" if "parent" in bases else None


def _pick(facts, period, nature, basis):
    u"""{element: value} for one span, nature and basis."""
    return dict((f["element"], f["value"]) for f in facts
                if f["period"] == period and f["nature"] == nature
                and f["basis"] == basis and f["sub_period"] is None)


def _change(values, element):
    for prefix in ("ChangeIn", "ChangesIn"):
        if prefix + element in values:
            return _pct(values[prefix + element])
    return None


def _headline(facts, period):
    u"""Results, forecast and progress for one release, line by line."""
    basis = _basis_of(facts)
    now = _pick(facts, RESULT_PERIOD.get(period), "result", basis)
    prior = _pick(facts, PRIOR_PERIOD.get(period), "result", basis)
    fperiod = FORECAST_PERIOD.get(period)
    point = _pick(facts, fperiod, "forecast", basis)
    upper = _pick(facts, fperiod, "forecast-upper", basis)
    lower = _pick(facts, fperiod, "forecast-lower", basis)

    results, forecast = [], []
    for line, label, elements in LINES:
        el = next((e for e in elements if e in now), None)
        if el is not None:
            results.append({
                "line": line, "label": label, "element": el,
                "value": now[el], "prior_value": prior.get(el),
                "yoy_pct_published": _change(now, el),
                "unit": "JPY_per_share" if line == "eps" else "JPY"})
        fel = next((e for e in elements
                    if e in point or e in upper or e in lower), None)
        if fel is not None:
            row = {"line": line, "label": label, "element": fel,
                   "forecast": point.get(fel),
                   "forecast_upper": upper.get(fel), "forecast_lower": lower.get(fel),
                   "yoy_pct_published": _change(point, fel),
                   "unit": "JPY_per_share" if line == "eps" else "JPY",
                   "progress_pct": None}
            # Against a point forecast only, and only a positive one: a ratio
            # to a range is two numbers, and a ratio to a loss means nothing.
            if (period != "full-year" and line in PROGRESS_LINES
                    and el == fel and now.get(el) is not None
                    and point.get(fel) is not None and point[fel] > 0):
                row["progress_pct"] = round(100.0 * now[el] / point[fel], 1)
            forecast.append(row)

    position = {}
    for key, elements in (
            ("total_assets", ("TotalAssets", "TotalAssetsIFRS", "TotalAssetsUS")),
            ("net_assets", ("NetAssets", "TotalEquityIFRS", "NetAssetsUS")),
            ("owners_equity", ("OwnersEquity", "EquityAttributableToOwnersOfParentIFRS",
                               "ShareholdersEquityUS"))):
        el = next((e for e in elements if e in now), None)
        if el is not None:
            position[key] = {"element": el, "value": now[el]}
    for el in ("CapitalAdequacyRatio",
               "EquityAttributableToOwnersOfParentToTotalAssetsRatioIFRS",
               "ShareholdersEquityRatioUS"):
        if el in now:
            position["equity_ratio_pct"] = {"element": el, "value": _pct(now[el])}
            break

    dividends = [{
        "fiscal_year": {"year": "current", "next-year": "next",
                        "prior-year": "prior"}.get(f["period"], f["period"]),
        "nature": f["nature"], "sub_period": f["sub_period"], "value": f["value"]}
        for f in facts
        if f["element"] == "DividendPerShare" and f["sub_period"]
        and f["nature"] in ("result", "forecast", "forecast-upper", "forecast-lower")]
    return {"basis": basis, "results": results, "forecast": forecast,
            "forecast_for": {"year": "the current fiscal year",
                             "next-year": "the fiscal year that has just begun"}
                            .get(fperiod),
            "position": position, "dividends_per_share": dividends}


def _facts(cur, doc_key):
    return _rows(cur, """
        SELECT ord, element, period, period_kind, nature, basis, sub_period,
               unit, value
        FROM eq_tdnet_facts WHERE doc_key = ? ORDER BY ord""", [doc_key])


def _coverage(cur):
    u"""How much wire we hold. This is the completeness of everything below it."""
    ceiling = asof.clause("disclosed_on", "")
    row = _rows(cur, """
        SELECT count(DISTINCT disclosed_on) AS days_covered,
               min(disclosed_on) AS first_day, max(disclosed_on) AS last_day,
               count(*) AS disclosures
        FROM eq_tdnet_items WHERE TRUE""" + ceiling)[0]
    return row


# The flat cross-section behind /recent and /screen: one row per current
# release with its headline lines pivoted out. Built in SQL so a screen over
# 3,500 companies is one query, with the same element order as LINES.
def _pivot_sql():
    # The element is chosen by the RESULT: the forecast and the published
    # change read the same element, so a progress figure never divides one
    # measure by another.
    def has(e):
        return ("max(CASE WHEN x.element = '%s' AND x.nature = 'result' "
                "AND x.period = r.rp THEN 1 END) = 1" % e)

    def val(elements, nature, period_col):
        return ("max(CASE WHEN x.element IN (%s) AND x.nature = '%s' "
                "AND x.period = r.%s THEN x.value END)"
                % (", ".join("'%s'" % e for e in elements), nature, period_col))

    cols = []
    for line, _, elements in LINES:
        for suffix, fn in (
                ("", lambda e: val((e,), "result", "rp")),
                ("_forecast", lambda e: val((e,), "forecast", "fp")),
                ("_yoy_pct_published", lambda e: "round(100 * %s, 1)" % val(
                    ("ChangeIn" + e, "ChangesIn" + e), "result", "rp"))):
            cols.append("CASE %s END AS %s%s" % (
                " ".join("WHEN %s THEN %s" % (has(e), fn(e)) for e in elements),
                line, suffix))
        cols.append("CASE %s END AS %s_element" % (
            " ".join("WHEN %s THEN '%s'" % (has(e), e) for e in elements), line))
    return ",\n               ".join(cols)


def _cross_section():
    return releases_cte() + """,
    cur_rel AS (
        SELECT *, CASE period WHEN 'q1' THEN 'q1-ytd' WHEN 'q2' THEN 'q2-ytd'
                              WHEN 'q3' THEN 'q3-ytd' ELSE 'year' END AS rp,
                  CASE period WHEN 'full-year' THEN 'next-year' ELSE 'year' END AS fp
        FROM rel WHERE rn = 1
    ),
    basis AS (
        SELECT doc_key,
               CASE WHEN bool_or(basis = 'consolidated') THEN 'consolidated'
                    ELSE 'parent' END AS basis
        FROM eq_tdnet_facts WHERE nature = 'result' AND basis IS NOT NULL
        GROUP BY 1
    ),
    flat AS (
        SELECT r.doc_key, r.sec_code, r.name, r.title, r.filed_date, r.filed_time,
               r.period, r.fiscal_period, b.basis,
               """ + _pivot_sql() + """
        FROM cur_rel r
        JOIN basis b USING (doc_key)
        JOIN eq_tdnet_facts x ON x.doc_key = r.doc_key AND x.basis = b.basis
                              AND x.sub_period IS NULL
        GROUP BY ALL
    )""" + NAME_CTES


def _with_progress(rows):
    for r in rows:
        for line in PROGRESS_LINES:
            res, fc = r.get(line), r.get(line + "_forecast")
            r[line + "_progress_pct"] = (
                round(100.0 * res / fc, 1)
                if r["period"] != "full-year" and res is not None
                and fc is not None and fc > 0 else None)
    return rows


@router.get("/summary")
def summary():
    u"""Coverage first — it is the honest ceiling on everything after it."""
    cur = _require()
    head = {"coverage": _coverage(cur)}
    head["releases"] = _rows(cur, releases_cte() + """
        SELECT count(*) AS releases,
               count(*) FILTER (WHERE rn = 1) AS current_releases,
               count(DISTINCT sec_code) AS companies,
               min(filed_date) AS first_filed_date,
               max(filed_date) AS last_filed_date
        FROM rel""")[0]
    head["by_period"] = _rows(cur, releases_cte() + """
        SELECT fiscal_period, period, count(*) AS current_releases
        FROM rel WHERE rn = 1 GROUP BY 1, 2
        ORDER BY current_releases DESC LIMIT 24""")
    head["by_day"] = _rows(cur, releases_cte() + """
        SELECT filed_date, count(*) AS releases
        FROM rel GROUP BY 1 ORDER BY 1 DESC LIMIT 60""")
    head["wire_kinds"] = _rows(cur, """
        SELECT kind, count(*) AS disclosures FROM eq_tdnet_items
        WHERE TRUE""" + asof.clause("disclosed_on", "") + """
        GROUP BY 1 ORDER BY 2 DESC""")
    head["wire_note"] = WIRE_NOTE
    return _notes(head)


@router.get("/recent")
def recent(limit: int = Query(50, ge=1, le=500),
           period: str = Query("", description="q1 | q2 | q3 | full-year"),
           fiscal_period: str = Query("", description="fiscal year-end month, e.g. 2027-03")):
    u"""The newest current releases, with their headline lines."""
    cur = _require()
    where, params = ["TRUE"], []
    if period.strip():
        where.append("f.period = ?")
        params.append(period.strip())
    if fiscal_period.strip():
        where.append("f.fiscal_period = ?")
        params.append(fiscal_period.strip())
    rows = _rows(cur, _cross_section() + """
        SELECT f.*, en.name_en FROM flat f
        LEFT JOIN en_scode en ON en.sec_code = f.sec_code
        WHERE """ + " AND ".join(where) + """
        ORDER BY f.filed_date DESC, f.filed_time DESC, f.sec_code
        LIMIT ?""", params + [limit])
    return _notes({"releases": _with_progress(rows),
                   "filters": {"period": period.strip() or None,
                               "fiscal_period": fiscal_period.strip() or None},
                   "names_note": NAMES_NOTE})


SCREEN_SORTS = {
    "progress": "progress",
    "revenue_yoy": "revenue_yoy_pct_published",
    "operating_income_yoy": "operating_income_yoy_pct_published",
    "profit_yoy": "profit_yoy_pct_published",
}


@router.get("/screen")
def screen(sort: str = Query("progress", description="progress | revenue_yoy | "
                                                     "operating_income_yoy | profit_yoy"),
           line: str = Query("operating_income",
                             description="for sort=progress: revenue | operating_income | "
                                         "ordinary_income | profit"),
           period: str = Query("q1", description="q1 | q2 | q3 | full-year — one at a "
                                                 "time, because progress after three "
                                                 "months and after nine do not compare"),
           fiscal_period: str = Query("", description="fiscal year-end month, e.g. 2027-03"),
           order: str = Query("desc", description="desc | asc"),
           limit: int = Query(50, ge=1, le=500)):
    u"""Companies ranked within ONE reporting period — never across periods."""
    cur = _require()
    if sort not in SCREEN_SORTS:
        raise HTTPException(400, "sort must be one of %s" % ", ".join(sorted(SCREEN_SORTS)))
    if line not in PROGRESS_LINES:
        raise HTTPException(400, "line must be one of %s" % ", ".join(PROGRESS_LINES))
    p = period.strip() or "q1"
    if p not in RESULT_PERIOD:
        raise HTTPException(400, "period must be one of q1, q2, q3, full-year")
    if sort == "progress" and p == "full-year":
        raise HTTPException(400, "progress is not defined for a full-year release")
    where, params = ["f.period = ?"], [p]
    if fiscal_period.strip():
        where.append("f.fiscal_period = ?")
        params.append(fiscal_period.strip())
    if sort == "progress":
        key = ("CASE WHEN f.%s IS NOT NULL AND f.%s_forecast > 0 "
               "THEN round(100.0 * f.%s / f.%s_forecast, 1) END" % (line, line, line, line))
    else:
        key = "f." + SCREEN_SORTS[sort]
    direction = "ASC" if order.strip().lower() == "asc" else "DESC"
    rows = _rows(cur, _cross_section() + """
        SELECT f.*, en.name_en, """ + key + """ AS sort_value
        FROM flat f LEFT JOIN en_scode en ON en.sec_code = f.sec_code
        WHERE """ + " AND ".join(where) + " AND " + key + """ IS NOT NULL
        ORDER BY sort_value """ + direction + """, f.sec_code
        LIMIT ?""", params + [limit])
    return _notes({"companies": _with_progress(rows), "sort": sort, "line": line,
                   "period": p, "order": direction.lower(),
                   "fiscal_period": fiscal_period.strip() or None,
                   "names_note": NAMES_NOTE})


@router.get("/companies")
def companies(q: str = Query("", description="company name or code substring"),
              limit: int = Query(50, ge=1, le=500)):
    u"""Companies with a release in the archive. Also the search feed."""
    cur = _require()
    term = (q or "").strip()
    like = "%" + term + "%"
    alias_sql, alias_params = aliases.clause(cur, "r.sec_code", term)
    rows = _rows(cur, releases_cte() + NAME_CTES + """
        SELECT r.sec_code, max_by(r.name, r.filed_date) AS name,
               any_value(en.name_en) AS name_en,
               count(*) AS releases,
               max(r.filed_date) AS last_filed_date,
               max_by(r.period, r.filed_date) AS latest_period,
               max_by(r.fiscal_period, r.filed_date) AS latest_fiscal_period
        FROM rel r LEFT JOIN en_scode en ON en.sec_code = r.sec_code
        WHERE (? = '' OR r.sec_code LIKE ? OR r.name LIKE ?
               OR lower(coalesce(en.name_en, '')) LIKE lower(?)""" + alias_sql + """)
        GROUP BY 1
        ORDER BY last_filed_date DESC, r.sec_code
        LIMIT ?""", [term, like, like, like] + alias_params + [limit])
    return _notes({"companies": rows, "names_note": NAMES_NOTE})


@router.get("/company/{sec_code}")
def company(sec_code: str,
            doc_key: str = Query("", description="one release to read; default the newest"),
            wire: int = Query(40, ge=0, le=300,
                              description="how many of the company's other disclosures to list")):
    u"""One company's releases: results, the company's forecast, progress against it."""
    cur = _require()
    code = (sec_code or "").strip()
    rels = _rows(cur, releases_cte() + """
        SELECT * FROM rel WHERE sec_code = ?
        ORDER BY filed_date DESC, filed_time DESC, doc_key DESC""", [code])
    if not rels:
        raise HTTPException(404, "no earnings release archived for %s" % code)
    chosen = next((r for r in rels if r["doc_key"] == doc_key.strip()), None) \
        if doc_key.strip() else rels[0]
    if chosen is None:
        raise HTTPException(404, "no release %s for %s" % (doc_key, code))
    name_en = _rows(cur, "WITH x AS (SELECT 1)" + NAME_CTES + """
        SELECT name_en FROM en_scode WHERE sec_code = ?""", [code])
    facts = _facts(cur, chosen["doc_key"])
    head = {
        "sec_code": code, "name": chosen["name"],
        "name_en": name_en[0]["name_en"] if name_en else None,
        "release": _release_row(chosen),
        "releases": [_release_row(r) for r in rels],
    }
    head.update(_headline(facts, chosen["period"]))
    # Everything the Summary tagged, as tagged: the headline above is a reading
    # of this table and never replaces it.
    head["facts"] = facts
    if wire:
        head["wire"] = _rows(cur, """
            SELECT disclosed_on AS filed_date, disclosed_at AS filed_time, title,
                   kind, pdf_name, (xbrl_name IS NOT NULL) AS has_xbrl
            FROM eq_tdnet_items WHERE sec_code = ?""" +
            asof.clause("disclosed_on", "") + """
            ORDER BY disclosed_on DESC, disclosed_at DESC, ord LIMIT ?""", [code, wire])
        head["wire_note"] = WIRE_NOTE
    head["coverage"] = _coverage(cur)
    head["names_note"] = NAMES_NOTE
    return _notes(head)


@router.get("/wire")
def wire(kind: str = Query("", description="earnings | forecast-revision | dividend-forecast | "
                                           "buyback | tender-offer | share-split | … ; "
                                           "empty for everything"),
         q: str = Query("", description="company name, code or headline substring"),
         day: str = Query("", description="one disclosure day, YYYY-MM-DD"),
         limit: int = Query(100, ge=1, le=1000)):
    u"""Every disclosure on the wire, newest first — the index, not the documents."""
    cur = _require()
    where, params = ["TRUE" + asof.clause("disclosed_on", "i")], []
    if kind.strip():
        where.append("i.kind = ?")
        params.append(kind.strip())
    if q.strip():
        where.append("(i.sec_code LIKE ? OR i.company_name LIKE ? OR i.title LIKE ?)")
        params += ["%" + q.strip() + "%"] * 3
    if day.strip():
        try:
            params.append(datetime.date.fromisoformat(day.strip()))
        except ValueError:
            raise HTTPException(400, "day must be a date, YYYY-MM-DD")
        where.append("i.disclosed_on = ?")
    rows = _rows(cur, """
        SELECT i.disclosed_on AS filed_date, i.disclosed_at AS filed_time,
               i.sec_code, i.company_name AS name, i.exchange, i.title, i.kind,
               i.pdf_name, (i.xbrl_name IS NOT NULL) AS has_xbrl
        FROM eq_tdnet_items i WHERE """ + " AND ".join(where) + """
        ORDER BY i.disclosed_on DESC, i.disclosed_at DESC, i.ord LIMIT ?""",
        params + [limit])
    return _notes({"disclosures": rows, "wire_note": WIRE_NOTE,
                   "coverage": _coverage(cur),
                   "filters": {"kind": kind.strip() or None, "q": q.strip() or None,
                               "day": day.strip() or None}})


MANIFEST = {
    "id": "earnings-releases",
    "section": "financials",
    "name": {"en": "Earnings releases", "ja": "決算短信"},
    "shape": "events",
    "summary": ("Every earnings release on the Tokyo Stock Exchange's disclosure "
                "wire — quarterly and full-year results as the company tagged "
                "them, the company's own forecast for the year with any range, "
                "and how far the results have progressed against it. The only "
                "source for first- and third-quarter results since the statutory "
                "quarterly reports were abolished, and a record that cannot be "
                "back-filled: the exchange deletes each disclosure after about a "
                "month."),
    "source": {
        "publisher": "Tokyo Stock Exchange (Japan Exchange Group)",
        "publisher_ja": "東京証券取引所",
        "document": "決算短信 (earnings release) Summary, disclosed on TDnet, the "
                    "Timely Disclosure network",
        "url": "https://www.release.tdnet.info/inbs/I_main_00.html",
        "credit": "Source: company disclosures on TDnet, Tokyo Stock Exchange.",
        "license_note": ("Disclosed by each listed company under the exchange's "
                         "timely-disclosure rules. Each package is archived with "
                         "its SHA-256 before parsing; TDnet itself retains about "
                         "a month."),
    },
    "keys": ["sec_code", "fiscal_period", "period", "doc_key"],
    "frequency": "per-event",
    "vintage": {
        "unit": "filing", "as_of_basis": "filed_date", "as_of_supported": True,
        "history_from": "2026-07 (disclosure date; capture began then)",
        "stale_after_days": 7,
    },
    "measures": [
        {"id": "value", "label": "Result, cumulative from the start of the fiscal year",
         "unit": "JPY", "trust": "official"},
        {"id": "prior_value", "label": "Same span of the prior year", "unit": "JPY",
         "trust": "official"},
        {"id": "yoy_pct_published", "label": "Year-on-year change, as the company published it",
         "unit": "%", "trust": "official"},
        {"id": "forecast", "label": "Company forecast", "unit": "JPY", "trust": "official"},
        {"id": "forecast_upper", "label": "Company forecast, upper bound", "unit": "JPY",
         "trust": "official"},
        {"id": "forecast_lower", "label": "Company forecast, lower bound", "unit": "JPY",
         "trust": "official"},
        {"id": "dividends_per_share", "label": "Dividend per share, paid and forecast",
         "unit": "JPY", "trust": "official"},
        {"id": "filed_date", "label": "Date disclosed on TDnet", "unit": "date",
         "trust": "official"},
        {"id": "progress_pct", "label": "Progress against the company's full-year forecast",
         "unit": "%", "trust": "derived", "calc": CALC["progress_pct"]},
        {"id": "is_current", "label": "Newest release for its period", "unit": "boolean",
         "trust": "derived", "calc": CALC["is_current"]},
        {"id": "fiscal_period", "label": "Fiscal year-end month", "unit": "text",
         "trust": "derived", "calc": CALC["fiscal_period"]},
    ],
    "endpoints": {
        "company": "/api/v1/equity/earnings/company/{sec_code}",
        "search": "/api/v1/equity/earnings/companies",
        "summary": "/api/v1/equity/earnings/summary",
        "screen": "/api/v1/equity/earnings/screen",
        "recent": "/api/v1/equity/earnings/recent",
        "wire": "/api/v1/equity/earnings/wire",
    },
    "capabilities": ["company", "search", "summary", "screen"],
    "screens": [
        {"id": "progress", "title": "Progress against the company's own full-year forecast"},
        {"id": "revenue_yoy", "title": "Revenue growth, as published"},
        {"id": "operating_income_yoy", "title": "Operating income growth, as published"},
        {"id": "profit_yoy", "title": "Profit growth, as published"},
    ],
    "cite": "/earnings.html?c={sec_code}",
    "page": "/earnings.html",
    "notes": [CUMULATIVE_NOTE, FORECAST_NOTE, REISSUE_NOTE, COVERAGE_NOTE,
              STANDARD_NOTE, PROGRESS_NOTE, WIRE_NOTE],
}
