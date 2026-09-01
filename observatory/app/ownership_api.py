# -*- coding: utf-8 -*-
u"""Equity product API — the shareholder register (大株主の状況・所有者別状況).

The other side of the cross-shareholding graph: equity_api.py answers "what
does this company hold", this answers "who holds it". Same DuckDB file, same
reader, same English names, and registered before the core router for the same
reason — its literal /equity/ paths must beat the core's /{dataset}/ catch-alls.

TWO DISCLOSURES TRAVEL WITH EVERY NUMBER HERE, because without them the data
is actively misleading (see METHODOLOGY-OWNERSHIP.md):

  1. THE REGISTER IS NOT BENEFICIAL OWNERSHIP. Two nominee trust banks —
     日本マスタートラスト信託銀行 and 日本カストディ銀行 — sit at the top of
     almost every register in Japan holding for index funds and pension money
     they do not own. Rank the register naively and they are the largest
     shareholder in the market; that is a fact about custody, not ownership.
     Every holder row carries `holder_kind`, every holder ranking states
     whether nominees are in it, and the nominee-excluded ranking is the
     default because it is the one that means something.
  2. THE TWO PERCENTAGE COLUMNS HAVE DIFFERENT DENOMINATORS. A register row's
     ratio is of shares in issue EXCLUDING treasury (the filing's own
     definition); the investor-category percentages are of ALL issued shares.
     They are close, they are not the same measure, and they are never netted.

holder_kind, the retirement-trust settlor, and every aggregate computed here
are DERIVED — they carry their formula, not an Official Statistic badge. The
names, addresses, share counts and ratios are as filed.
"""
from fastapi import APIRouter, HTTPException, Query

from .equity_api import NAMES_NOTE, NAME_CTES, PROVENANCE, _cur, _rows

router = APIRouter(prefix="/api/v1/equity/ownership")

NOMINEE_KINDS = ("trust_bank_nominee", "foreign_nominee")
NOMINEE_SQL = "('trust_bank_nominee','foreign_nominee')"

HOLDER_KINDS = {
    "entity": "Company or institution holding in its own name",
    "individual": "Natural person",
    "trust_bank_nominee": "Nominee trust-bank account (holds for others)",
    "foreign_nominee": "Global custodian or street-name account (holds for others)",
    "retirement_benefit_trust": "Retirement-benefit trust — the settlor company is the economic holder",
    "employee_association": "Employee or business-partner shareholding association",
    "foreign_entity": "Overseas company or fund holding in its own name",
    "treasury": "The company's own shares",
}

KIND_NOTE = (
    "holder_kind is OUR classification of each register row, not a filed field. "
    "It is derived from the holder's name: the four custody banks that exist "
    "only as nominees, any other trust bank holding through a bracketed trust "
    "account, the global custodians, employee shareholding associations, "
    "retirement-benefit trusts (whose settlor is named inside the account and "
    "is returned as beneficiary), and natural persons. Everything else is "
    "'entity'. Rows are always returned with the name exactly as filed so the "
    "classification can be checked.")

DENOMINATOR_NOTE = (
    "Register ratios (ratio_pct) are of shares in issue EXCLUDING treasury — "
    "the filing's own denominator, 発行済株式（自己株式を除く）の総数. Investor-"
    "category percentages (eq_own_category.pct) are of ALL issued shares. The "
    "two are different measures and must not be netted or compared row for row.")

PERCENT_NOTE = (
    "Percentages are as filed, converted from the XBRL fraction to percent "
    "(0.0918 → 9.18) at the precision the filing states. Filers round or "
    "truncate each row themselves, so a column of rows need not sum exactly to "
    "the filed total; where it falls outside what that printing precision "
    "allows, the filing is marked partial and says so in `detail`.")

CALC = {
    "nominee_ratio_pct": "sum of ratio_pct over rows whose holder_kind is a nominee kind",
    "top_holder_ratio_pct": "ratio_pct of rank 1, as filed",
    "register_concentration_pct": "majors_ratio_filed_pct — the filer's own 計 row, not our sum",
    "foreign_pct": "所有株式数の割合 for 外国法人等 (institutions + individuals), as filed",
    "avg_foreign_pct": "unweighted mean of foreign_pct across the companies in scope",
}

# One filing per company: the archive holds several fiscal years and a
# cross-section that counted every filing would count a company once per year.
LATEST_OWN = """
    WITH scoped AS (
        SELECT o.*, coalesce(o.sec_code, o.edinet_code, o.doc_id) AS filer_key
        FROM eq_own_filings o
        LEFT JOIN eq_entities ent ON ent.edinet_code = o.edinet_code
        WHERE o.status IN ('clean','partial')
          AND (CAST(? AS VARCHAR) IS NULL
               OR CAST(year(o.period_end) AS VARCHAR) = CAST(? AS VARCHAR))
          AND (CAST(? AS VARCHAR) IS NULL
               OR coalesce(ent.listed, FALSE) = (CAST(? AS VARCHAR) = 'true'))
    ),
    current_own AS (
        SELECT * FROM (
            SELECT *, row_number() OVER (PARTITION BY filer_key
                                         ORDER BY period_end DESC, filed_date DESC) AS rn
            FROM scoped
        ) WHERE rn = 1
    )
"""


def _params(year="", listed=""):
    y = (year or "").strip() or None
    l = (listed or "").strip().lower()
    return [y, y, l if l in ("true", "false") else None,
            l if l in ("true", "false") else None]


def _require():
    cur = _cur()
    try:
        cur.execute("SELECT 1 FROM eq_own_filings LIMIT 1")
    except Exception:                                            # noqa: BLE001
        raise HTTPException(503, "ownership dataset not published yet")
    return cur


def _notes(head):
    head["kind_note"] = KIND_NOTE
    head["denominator_note"] = DENOMINATOR_NOTE
    head["percent_note"] = PERCENT_NOTE
    head["names_note"] = NAMES_NOTE
    head["calc"] = CALC
    head["provenance"] = PROVENANCE
    return head


@router.get("/years")
def years():
    u"""Fiscal years available, newest first — the feed for a year picker."""
    return {"years": _rows(_require(), """
        SELECT CAST(year(period_end) AS VARCHAR) AS year, count(*) AS filings,
               min(period_end) AS first_period_end, max(period_end) AS last_period_end
        FROM eq_own_filings
        WHERE status IN ('clean','partial') AND period_end IS NOT NULL
        GROUP BY 1 ORDER BY 1 DESC""")}


@router.get("/summary")
def summary(year: str = Query("", description="fiscal year, e.g. 2026; default latest"),
            listed: str = Query("", description="'true' for listed filers only")):
    u"""Coverage first, then what the registers say in aggregate."""
    cur = _require()
    p = _params(year, listed)
    head = _rows(cur, LATEST_OWN + """
        SELECT count(*)                          AS companies,
               sum(majors_rows)                  AS register_rows,
               avg(majors_ratio_filed_pct)       AS avg_top_holders_pct,
               avg(nominee_ratio_pct)            AS avg_nominee_pct,
               avg(foreign_pct)                  AS avg_foreign_pct,
               avg(individuals_pct)              AS avg_individuals_pct,
               avg(financial_institutions_pct)   AS avg_financial_institutions_pct,
               avg(other_corporations_pct)       AS avg_other_corporations_pct,
               sum(shareholders_total)           AS shareholders_counted,
               min(period_end) AS earliest_period_end, max(period_end) AS latest_period_end
        FROM current_own""", p)[0]
    head["holders_by_kind"] = _rows(cur, LATEST_OWN + """
        SELECT h.holder_kind, count(*) AS rows,
               count(DISTINCT c.doc_id) AS companies,
               avg(h.ratio_pct) AS avg_ratio_pct
        FROM current_own c JOIN eq_major_shareholders h USING (doc_id)
        GROUP BY 1 ORDER BY 2 DESC""", p)
    status = _rows(cur, "SELECT status, count(*) AS n FROM eq_own_filings GROUP BY 1")
    head["extraction_status"] = {r["status"]: r["n"] for r in status}
    head["filings_total_all_years"] = sum(r["n"] for r in status)
    head["scope"] = ("fiscal year %s" % year.strip()) if year.strip() else \
        "each company's latest filing"
    head["holder_kinds"] = HOLDER_KINDS
    head["coverage_note"] = (
        "Every archived annual report is parsed. A filing on a form that tags "
        "no 株式等の状況 section at all (unsupported_form — foreign-issuer "
        "and 特定 forms) contributes nothing; clean and partial filings are "
        "used, one per company, and partial filings publish the gate that "
        "failed in `detail`.")
    return _notes(head)


@router.get("/companies")
def companies(q: str = Query("", description="name or code substring")):
    u"""Search feed for this dataset — a company is here if a register was
    extracted from its annual report."""
    cur = _require()
    like = "%" + q.strip() + "%"
    return {"companies": _rows(cur, LATEST_OWN + NAME_CTES + """
        SELECT c.sec_code, c.filer_name AS name,
               coalesce(n.name_en, s.name_en) AS name_en, e.industry,
               CAST(year(c.period_end) AS VARCHAR) AS year, c.majors_rows,
               c.majors_ratio_filed_pct, c.foreign_pct, c.nominee_ratio_pct
        FROM current_own c
        LEFT JOIN eq_entities e ON e.edinet_code = c.edinet_code
        LEFT JOIN en_ecode n ON n.edinet_code = c.edinet_code
        LEFT JOIN en_scode s ON s.sec_code = c.sec_code
        WHERE c.sec_code IS NOT NULL
          AND (c.sec_code LIKE ? OR c.filer_name LIKE ?
               OR lower(coalesce(n.name_en, s.name_en, '')) LIKE lower(?))
        ORDER BY c.shareholders_total DESC NULLS LAST LIMIT 25""",
        _params("", "") + [like, like, like]),
        "names_note": NAMES_NOTE}


@router.get("/company/{sec_code}")
def company(sec_code: str,
            year: str = Query("", description="fiscal year; default the latest filing")):
    u"""One company's register: the named holders and the whole-book split."""
    cur = _require()
    code = (sec_code or "").strip()
    rows = _rows(cur, LATEST_OWN + NAME_CTES + """
        SELECT c.*, coalesce(es.name_en, ee.name_en) AS filer_name_en
        FROM current_own c
        LEFT JOIN en_scode es ON es.sec_code = c.sec_code
        LEFT JOIN en_ecode ee ON ee.edinet_code = c.edinet_code
        WHERE c.sec_code = ? OR c.edinet_code = ?
        LIMIT 1""", _params(year) + [code, code])
    if not rows:
        raise HTTPException(404, "no register filing for %s" % code)
    head = rows[0]
    head.pop("rn", None)
    head.pop("filer_key", None)
    doc = head["doc_id"]
    head["holders"] = _rows(cur, "WITH x AS (SELECT 1)" + NAME_CTES + """
        SELECT h.rank, h.name_raw, h.account_raw, h.address_raw, h.shares,
               h.ratio_pct, h.holder_kind, h.beneficiary_raw,
               h.holder_edinet_code, h.holder_sec_code, h.match_status,
               h.beneficiary_sec_code,
               coalesce(es.name_en, ee.name_en) AS holder_name_en
        FROM eq_major_shareholders h
        LEFT JOIN en_scode es ON es.sec_code = h.holder_sec_code
        LEFT JOIN en_ecode ee ON ee.edinet_code = h.holder_edinet_code
        WHERE h.doc_id = ? ORDER BY h.rank""", [doc])
    head["categories"] = _rows(cur, """
        SELECT share_class, category, category_en, shareholders, units, pct
        FROM eq_own_category WHERE doc_id = ?
        ORDER BY share_class, pct DESC NULLS LAST""", [doc])
    head["history"] = _rows(cur, """
        SELECT CAST(year(period_end) AS VARCHAR) AS year, period_end, doc_id,
               majors_ratio_filed_pct, nominee_ratio_pct, foreign_pct,
               individuals_pct, financial_institutions_pct,
               other_corporations_pct, shareholders_total, status
        FROM eq_own_filings
        WHERE (sec_code = ? OR edinet_code = ?) AND status IN ('clean','partial')
        ORDER BY period_end DESC""", [code, head.get("edinet_code")])
    return _notes(head)


@router.get("/holder/{key}")
def holder(key: str,
           year: str = Query("", description="fiscal year; default latest filings"),
           limit: int = Query(200, ge=1, le=1000)):
    u"""The reverse view: every register this holder appears in.

    `key` is an EDINET code (E01234) where the holder resolved to one, else the
    holder's name exactly as some filing writes it. A register names holders in
    free text, so a holder that never resolved is only as findable as its name
    is consistent — which is why the resolved code is preferred.
    """
    cur = _require()
    k = (key or "").strip()
    by_code = k.upper().startswith("E") and k[1:].isdigit()
    where = "h.holder_edinet_code = ?" if by_code else "h.name_base = ? OR h.name_raw = ?"
    params = _params(year) + ([k] if by_code else [k, k])
    positions = _rows(cur, LATEST_OWN + NAME_CTES + """
        SELECT c.sec_code, c.edinet_code, c.filer_name,
               coalesce(es.name_en, ee.name_en) AS company_name_en,
               c.period_end, c.doc_id, h.rank, h.name_raw AS held_as,
               h.holder_kind, h.shares, h.ratio_pct
        FROM current_own c JOIN eq_major_shareholders h USING (doc_id)
        LEFT JOIN en_scode es ON es.sec_code = c.sec_code
        LEFT JOIN en_ecode ee ON ee.edinet_code = c.edinet_code
        WHERE """ + where + """
        ORDER BY h.ratio_pct DESC NULLS LAST LIMIT ?""", params + [limit])
    # Counted over EVERY position, not the page of them returned: a holder that
    # appears in more registers than `limit` would otherwise report its own
    # page size as its number of companies.
    totals = _rows(cur, LATEST_OWN + """
        SELECT count(*) AS top_ten_seats, avg(h.ratio_pct) AS avg_ratio_pct,
               max(h.name_base) AS name_ja
        FROM current_own c JOIN eq_major_shareholders h USING (doc_id)
        WHERE """ + where, params)[0]
    name_en = _rows(cur, "WITH x AS (SELECT 1)" + NAME_CTES + """
        SELECT coalesce(ee.name_en, es.name_en) AS name_en
        FROM en_ecode ee FULL JOIN en_scode es ON FALSE
        WHERE ee.edinet_code = ?""", [k])if by_code else []
    head = {"key": k, "resolved_by": "edinet_code" if by_code else "name",
            "name": totals.get("name_ja"),
            "name_en": (name_en[0]["name_en"] if name_en else None),
            "positions": positions, "returned": len(positions),
            "companies": totals["top_ten_seats"],
            "top_ten_seats": totals["top_ten_seats"],
            "avg_ratio_pct": totals["avg_ratio_pct"],
            "scope": ("fiscal year %s" % year.strip()) if year.strip()
                     else "each company's latest filing"}
    head["reverse_note"] = (
        "A register discloses only its largest holders — the top ten in most "
        "filings — so this is where the holder appears in a TOP-TEN, not "
        "everything it owns. A position below a company's tenth holder is "
        "invisible to this dataset by construction.")
    return _notes(head)


@router.get("/holders")
def holders(year: str = Query("", description="fiscal year; default latest filings"),
            include_nominees: str = Query("false", description="'true' to include "
                                          "nominee and custodian accounts"),
            kind: str = Query("", description="one holder_kind to filter to"),
            limit: int = Query(50, ge=1, le=500)):
    u"""Who appears in the most registers — nominees excluded by default."""
    cur = _require()
    p = _params(year)
    clauses = []
    if (include_nominees or "").strip().lower() != "true" and not kind.strip():
        clauses.append("h.holder_kind NOT IN " + NOMINEE_SQL)
    if kind.strip():
        clauses.append("h.holder_kind = ?")
        p = p + [kind.strip()]
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = _rows(cur, LATEST_OWN + NAME_CTES + """
        SELECT coalesce(h.holder_edinet_code, h.name_key, h.name_base) AS holder_key,
               -- Filers spell one name half-width and full-width; the rows
               -- merge on name_key, and min() then shows the ASCII spelling
               -- rather than whichever variant the engine reached first.
               min(h.name_base) AS name_ja,
               any_value(coalesce(es.name_en, ee.name_en)) AS name_en,
               any_value(h.holder_kind) AS holder_kind,
               any_value(h.holder_sec_code) AS holder_sec_code,
               any_value(h.holder_edinet_code) AS holder_edinet_code,
               count(*) AS top_ten_seats,
               avg(h.ratio_pct) AS avg_ratio_pct,
               max(h.ratio_pct) AS max_ratio_pct,
               sum(CASE WHEN h.rank = 1 THEN 1 ELSE 0 END) AS largest_holder_seats
        FROM current_own c JOIN eq_major_shareholders h USING (doc_id)
        LEFT JOIN en_scode es ON es.sec_code = h.holder_sec_code
        LEFT JOIN en_ecode ee ON ee.edinet_code = h.holder_edinet_code""" + where + """
        GROUP BY 1 ORDER BY top_ten_seats DESC, avg_ratio_pct DESC
        LIMIT ?""", p + [limit])
    head = {"holders": rows,
            "nominees_included": (include_nominees or "").strip().lower() == "true",
            "kind": kind.strip() or None,
            "scope": ("fiscal year %s" % year.strip()) if year.strip()
                     else "each company's latest filing"}
    head["ranking_note"] = (
        "Ranked by how many top-ten registers the holder appears in. Nominee "
        "and custodian accounts are excluded unless asked for, because they "
        "hold for others: included, the two Japanese custody banks are the "
        "largest shareholder of most of the market and the ranking says "
        "nothing about ownership.")
    return _notes(head)


SCREEN_METRICS = {
    "foreign_pct": "foreign_pct",
    "individuals_pct": "individuals_pct",
    "financial_institutions_pct": "financial_institutions_pct",
    "other_corporations_pct": "other_corporations_pct",
    "securities_firms_pct": "securities_firms_pct",
    "nominee_ratio_pct": "nominee_ratio_pct",
    "top_holders_pct": "majors_ratio_filed_pct",
    "shareholders_total": "shareholders_total",
}


@router.get("/screen")
def screen(metric: str = Query("foreign_pct", description="one of /screen/metrics"),
           order: str = Query("desc", description="'desc' or 'asc'"),
           year: str = Query("", description="fiscal year; default latest filings"),
           listed: str = Query("true", description="'true' for listed filers only"),
           min_shareholders: int = Query(0, ge=0,
                                         description="drop companies with fewer "
                                                     "shareholders than this"),
           limit: int = Query(50, ge=1, le=500)):
    u"""Companies ranked on one register metric."""
    cur = _require()
    col = SCREEN_METRICS.get((metric or "").strip())
    if not col:
        raise HTTPException(400, "unknown metric; see /screen/metrics")
    direction = "ASC" if (order or "").lower() == "asc" else "DESC"
    rows = _rows(cur, LATEST_OWN + NAME_CTES + """
        SELECT c.sec_code, c.edinet_code, c.filer_name,
               coalesce(es.name_en, ee.name_en) AS filer_name_en,
               c.period_end, c.doc_id, c.status,
               c.foreign_pct, c.individuals_pct, c.financial_institutions_pct,
               c.other_corporations_pct, c.securities_firms_pct,
               c.nominee_ratio_pct, c.majors_ratio_filed_pct AS top_holders_pct,
               c.shareholders_total, {COL} AS metric_value
        FROM current_own c
        LEFT JOIN en_scode es ON es.sec_code = c.sec_code
        LEFT JOIN en_ecode ee ON ee.edinet_code = c.edinet_code
        WHERE {COL} IS NOT NULL
          AND coalesce(c.shareholders_total, 0) >= ?
        ORDER BY metric_value {DIR} LIMIT ?"""
        .replace("{COL}", "c." + col).replace("{DIR}", direction),
        _params(year, listed) + [min_shareholders, limit])
    return _notes({"metric": metric, "order": direction.lower(), "companies": rows,
                   "scope": ("fiscal year %s" % year.strip()) if year.strip()
                            else "each company's latest filing"})


@router.get("/screen/metrics")
def screen_metrics():
    return {"metrics": sorted(SCREEN_METRICS), "calc": CALC}
