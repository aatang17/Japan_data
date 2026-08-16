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
    return {"companies": _rows(cur, LATEST_FILINGS + """,
        filers AS (
            SELECT f.sec_code, max(f.filer_name) AS name,
                   count(h.doc_id) AS holdings, 0 AS held_by
            FROM current_filings f LEFT JOIN eq_holdings h USING (doc_id)
            WHERE f.sec_code IS NOT NULL GROUP BY 1),
        held AS (
            SELECT h.held_sec_code AS sec_code, max(h.held_name_raw) AS name,
                   0 AS holdings, count(*) AS held_by
            FROM eq_holdings h JOIN current_filings f USING (doc_id)
            WHERE h.held_sec_code IS NOT NULL GROUP BY 1)
        SELECT sec_code, max(name) AS name,
               sum(holdings) AS holdings_count, sum(held_by) AS held_by_count
        FROM (SELECT * FROM filers UNION ALL SELECT * FROM held)
        WHERE sec_code LIKE ? OR name LIKE ?
        GROUP BY sec_code ORDER BY sum(holdings)+sum(held_by) DESC LIMIT 25
    """, _year_params("") + [like, like])}


@router.get("/company/{sec_code}")
def company(sec_code: str):
    """Both directions for one company: what it holds, and who holds it."""
    cur = _cur()
    ent = _rows(cur, """
        SELECT edinet_code, sec_code, name_ja, name_en, industry
        FROM eq_entities WHERE sec_code = ? LIMIT 1""", [sec_code])
    filing = _rows(cur, """
        SELECT doc_id, filer_name, period_end, filed_date, sha256, status
        FROM eq_filings WHERE sec_code = ?
        ORDER BY period_end DESC LIMIT 1""", [sec_code])
    holdings = []
    if filing:
        holdings = _rows(cur, """
            SELECT holder_table, held_name_raw, held_sec_code, match_status,
                   shares, book_value_yen, prior_shares, prior_book_value_yen,
                   purpose_ja, reciprocal
            FROM eq_holdings WHERE doc_id = ?
            ORDER BY book_value_yen DESC NULLS LAST""", [filing[0]["doc_id"]])
    # one row per holder — its latest filing — not one row per holder per year
    holders = _rows(cur, LATEST_FILINGS + """
        SELECT f.filer_name AS holder_name, f.sec_code AS holder_sec_code,
               f.doc_id, f.period_end, h.holder_table,
               h.shares, h.book_value_yen, h.prior_shares, h.prior_book_value_yen,
               h.purpose_ja, h.reciprocal
        FROM eq_holdings h JOIN current_filings f USING (doc_id)
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
        WITH per_year AS (
            SELECT f.sec_code, CAST(year(f.period_end) AS VARCHAR) AS year,
                   max(f.filer_name) AS name, max(f.period_end) AS period_end,
                   count(*) AS named_holdings,
                   sum(h.book_value_yen) AS book_value_yen
            FROM eq_holdings h JOIN eq_filings f USING (doc_id)
            WHERE f.status IN ('clean','partial') AND f.sec_code IS NOT NULL
            GROUP BY 1, 2),
        ranked AS (
            SELECT sec_code, max(book_value_yen) AS peak FROM per_year GROUP BY 1
            ORDER BY peak DESC NULLS LAST LIMIT ?)
        SELECT p.* FROM per_year p JOIN ranked r USING (sec_code)
        ORDER BY r.peak DESC NULLS LAST, p.sec_code, p.year
    """, [limit]),
        "provenance": PROVENANCE,
        "derived_note": ("Each point is the sum of named policy holdings as filed "
                         "for that fiscal year. Book values are fair-valued at "
                         "period end, so a fall reflects both selling and market "
                         "moves — position counts separate the two.")}


@router.get("/unwind")
def unwind(year: str = Query("", description="fiscal year, e.g. 2025; default latest")):
    """Sector unwind ranking: named policy-holding value change, per filer."""
    cur = _cur()
    return {"filers": _rows(cur, LATEST_FILINGS + """
        SELECT f.sec_code, max(f.filer_name) AS name, max(f.period_end) AS period_end,
               count(*) AS named_holdings,
               sum(h.book_value_yen)        AS book_value_yen,
               sum(h.prior_book_value_yen)  AS prior_book_value_yen,
               sum(CASE WHEN h.shares < h.prior_shares THEN 1 ELSE 0 END) AS reduced,
               sum(CASE WHEN h.shares > h.prior_shares THEN 1 ELSE 0 END) AS increased
        FROM eq_holdings h JOIN current_filings f USING (doc_id)
        GROUP BY f.sec_code ORDER BY book_value_yen DESC NULLS LAST
    """, _year_params(year)), "provenance": PROVENANCE,
        "derived_note": ("Value change and reduced/increased counts compare the "
                         "current and prior-year columns of the same filing — "
                         "derived; formula shown on the page.")}
