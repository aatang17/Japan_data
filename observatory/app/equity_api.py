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


PROVENANCE = {
    "trust": "official",
    "note": ("Figures exactly as filed in each company's 有価証券報告書 "
             "(annual securities report), EDINET. Raw filings archived with "
             "SHA-256; doc_id links to the source filing."),
}


@router.get("/summary")
def summary():
    cur = _cur()
    head = _rows(cur, """
        SELECT count(DISTINCT f.doc_id)                          AS filers,
               count(*)                                          AS named_holdings,
               sum(h.book_value_yen)                             AS total_book_value_yen,
               sum(CASE WHEN h.shares < h.prior_shares THEN 1 ELSE 0 END) AS positions_reduced,
               sum(CASE WHEN h.shares > h.prior_shares THEN 1 ELSE 0 END) AS positions_increased,
               sum(CASE WHEN h.reciprocal LIKE '有%' THEN 1 ELSE 0 END)   AS reciprocal_pairs
        FROM eq_holdings h JOIN eq_filings f USING (doc_id)
        WHERE f.status IN ('clean','partial')
    """)[0]
    status = _rows(cur, "SELECT status, count(*) AS n FROM eq_filings GROUP BY 1")
    head["extraction_status"] = {r["status"]: r["n"] for r in status}
    head["provenance"] = PROVENANCE
    return head


@router.get("/companies")
def companies(q: str = Query("", description="name or code substring")):
    """Search box feed: filers with extracted tables and/or companies that are held."""
    cur = _cur()
    like = "%" + q.strip() + "%"
    return {"companies": _rows(cur, """
        WITH filers AS (
            SELECT f.sec_code, max(f.filer_name) AS name,
                   count(h.doc_id) AS holdings, 0 AS held_by
            FROM eq_filings f LEFT JOIN eq_holdings h USING (doc_id)
            WHERE f.sec_code IS NOT NULL GROUP BY 1),
        held AS (
            SELECT held_sec_code AS sec_code, max(held_name_raw) AS name,
                   0 AS holdings, count(*) AS held_by
            FROM eq_holdings WHERE held_sec_code IS NOT NULL GROUP BY 1)
        SELECT sec_code, max(name) AS name,
               sum(holdings) AS holdings_count, sum(held_by) AS held_by_count
        FROM (SELECT * FROM filers UNION ALL SELECT * FROM held)
        WHERE sec_code LIKE ? OR name LIKE ?
        GROUP BY sec_code ORDER BY sum(holdings)+sum(held_by) DESC LIMIT 25
    """, [like, like])}


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
    holders = _rows(cur, """
        SELECT f.filer_name AS holder_name, f.sec_code AS holder_sec_code,
               f.doc_id, f.period_end, h.holder_table,
               h.shares, h.book_value_yen, h.prior_shares, h.prior_book_value_yen,
               h.purpose_ja, h.reciprocal
        FROM eq_holdings h JOIN eq_filings f USING (doc_id)
        WHERE h.held_sec_code = ? AND f.status IN ('clean','partial')
        ORDER BY h.book_value_yen DESC NULLS LAST""", [sec_code])
    if not ent and not filing and not holders:
        raise HTTPException(404, "no data for securities code %s" % sec_code)
    return {"entity": ent[0] if ent else None,
            "filing": filing[0] if filing else None,
            "holdings": holdings,
            "holders": holders,
            "provenance": PROVENANCE}


@router.get("/unwind")
def unwind():
    """Sector unwind ranking: named policy-holding value change, per filer."""
    cur = _cur()
    return {"filers": _rows(cur, """
        SELECT f.sec_code, max(f.filer_name) AS name, max(f.period_end) AS period_end,
               count(*) AS named_holdings,
               sum(h.book_value_yen)        AS book_value_yen,
               sum(h.prior_book_value_yen)  AS prior_book_value_yen,
               sum(CASE WHEN h.shares < h.prior_shares THEN 1 ELSE 0 END) AS reduced,
               sum(CASE WHEN h.shares > h.prior_shares THEN 1 ELSE 0 END) AS increased
        FROM eq_holdings h JOIN eq_filings f USING (doc_id)
        WHERE f.status IN ('clean','partial')
        GROUP BY f.sec_code ORDER BY book_value_yen DESC NULLS LAST
    """), "provenance": PROVENANCE,
        "derived_note": ("Value change and reduced/increased counts compare the "
                         "current and prior-year columns of the same filing — "
                         "derived; formula shown on the page.")}
