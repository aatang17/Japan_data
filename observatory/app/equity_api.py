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


# English names are NOT in the filings — a Japanese annual report names its
# holdings in Japanese. They come from EDINET's own filer registry
# (EdinetcodeDlInfo), joined on the filer's EDINET code, falling back to the
# securities code. The registry leaves the English field blank for roughly one
# listed filer in ten, and a company that has restructured may no longer carry
# its old securities code, so name_en is null for some rows. The as-filed
# Japanese name is always returned alongside it and is never replaced by it.
NAME_CTES = """,
    en_ecode AS (SELECT edinet_code, name_en FROM eq_entities
                 WHERE name_en IS NOT NULL),
    en_scode AS (SELECT sec_code, max(name_en) AS name_en FROM eq_entities
                 WHERE sec_code IS NOT NULL AND name_en IS NOT NULL GROUP BY 1)
"""

NAMES_NOTE = ("English names are a lookup from EDINET's filer registry, not part "
              "of the filing; name_en is null where the registry has no English "
              "name. The as-filed Japanese name is the primary record.")

PROVENANCE = {
    "trust": "official",
    "note": ("Figures exactly as filed in each company's 有価証券報告書 "
             "(annual securities report), EDINET. Raw filings archived with "
             "SHA-256; doc_id links to the source filing."),
}


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
        SELECT edinet_code, sec_code, name_ja, name_en, industry
        FROM eq_entities WHERE sec_code = ? LIMIT 1""", [sec_code])
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
            WITH x AS (SELECT 1)""" + NAME_CTES + """
            SELECT h.holder_table, h.held_name_raw,
                   coalesce(n.name_en, s.name_en) AS held_name_en,
                   h.held_sec_code, h.match_status,
                   h.shares, h.book_value_yen, h.prior_shares, h.prior_book_value_yen,
                   h.purpose_ja, h.reciprocal
            FROM eq_holdings h
            LEFT JOIN en_ecode n ON n.edinet_code = h.held_edinet_code
            LEFT JOIN en_scode s ON s.sec_code = h.held_sec_code
            WHERE h.doc_id = ?
            ORDER BY h.book_value_yen DESC NULLS LAST""", [filing[0]["doc_id"]])
    # one row per holder — its latest filing — not one row per holder per year
    holders = _rows(cur, LATEST_FILINGS + NAME_CTES + """
        SELECT f.filer_name AS holder_name,
               coalesce(n.name_en, s.name_en) AS holder_name_en,
               f.sec_code AS holder_sec_code,
               f.doc_id, f.period_end, h.holder_table,
               h.shares, h.book_value_yen, h.prior_shares, h.prior_book_value_yen,
               h.purpose_ja, h.reciprocal
        FROM eq_holdings h JOIN current_filings f USING (doc_id)
        LEFT JOIN en_ecode n ON n.edinet_code = f.edinet_code
        LEFT JOIN en_scode s ON s.sec_code = f.sec_code
        WHERE h.held_sec_code = ?
        ORDER BY h.book_value_yen DESC NULLS LAST""", _year_params("") + [sec_code])
    history = _rows(cur, """
        SELECT CAST(year(f.period_end) AS VARCHAR) AS year, f.period_end,
               count(*) AS named_holdings, sum(h.book_value_yen) AS book_value_yen
        FROM eq_holdings h JOIN eq_filings f USING (doc_id)
        WHERE f.sec_code = ? AND f.status IN ('clean','partial')
        GROUP BY 1, 2 ORDER BY 1""", [sec_code])
    if not ent and not filing and not holders:
        raise HTTPException(404, "no data for securities code %s" % sec_code)
    return {"entity": ent[0] if ent else None,
            "names_note": NAMES_NOTE,
            "filing": filing[0] if filing else None,
            "holdings": holdings,
            "holders": holders,
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
