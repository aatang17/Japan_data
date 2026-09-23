# -*- coding: utf-8 -*-
u"""Equity product API — earnings calendar (決算発表予定日, JPX).

The day each listed company has told the exchange it will announce results,
from JPX's per-month lists (equity/calendar_extract.py stores every list it
has ever read, whole).

WHAT A CONSUMER MUST NOT ASSUME, carried in every response:

  1. **AN EMPTY DAY MAY ONLY BE UNPUBLISHED.** JPX lists a month's companies
     after that month ends. Until the list for a period-end month exists, the
     companies closing that month have no date here. `horizon` says which
     months are covered and how far ahead their dates reach.

  2. **A DATE IS A NOTIFIED PLAN.** It is what the company told the exchange,
     and it can move. When a later list moved it, the row carries
     `previous_date`; the full trail is in /company/{code}.

  3. **UNDECIDED IS MISSING, NOT A DATE.** JPX prints 未定 for companies that
     have not set a day. They are listed apart, with no date.
"""
import datetime
import re

from fastapi import APIRouter, HTTPException, Query

from . import asof
from .equity_api import _cur, _rows

router = APIRouter(prefix="/api/v1/equity/calendar", tags=["Earnings calendar"])

JST = datetime.timezone(datetime.timedelta(hours=9))
MAX_RANGE_DAYS = 120
DEFAULT_RANGE_DAYS = 14
MAX_CODES = 500
CODE = re.compile(r"^[0-9A-Z]{4}$")

# Market filter values -> the Japanese segment names JPX prints. Foreign
# listings carry "（外国）" after the segment, so the match is a prefix.
MARKETS = {"prime": u"プライム", "standard": u"スタンダード",
           "growth": u"グロース", "reit": u"REIT"}

PROVENANCE = {
    "trust": "official",
    "note": ("Dates exactly as published by Japan Exchange Group in its "
             "決算発表予定日 lists, compiled from what listed companies notified "
             "the Tokyo Stock Exchange. Each list is archived with its SHA-256 "
             "before parsing, and every re-issued list is kept beside the one "
             "before it."),
}

CALC = {
    "current_date": (
        "for each company, fiscal year-end and period type: the date in the "
        "newest JPX list for that period-end month, or in a newer next-day "
        "list where one exists"),
    "previous_date": (
        "the date the same company, fiscal year-end and period type carried in "
        "the list before the one shown, where it differs"),
}

HORIZON_NOTE = (
    "JPX lists a month's companies only after that month ends, usually within "
    "the first ten days of the next month, then re-issues the list as dates "
    "change. Companies whose quarter or year ends in a month with no list yet "
    "have no date here, so a quiet day beyond `known_through` may simply be "
    "unpublished.")

PLAN_NOTE = (
    "A date is what the company notified the exchange, not a commitment: JPX "
    "notes that companies may announce on another day, and that companies not "
    "on its lists may announce too. Where a later list moved a date, "
    "previous_date shows the one it replaced.")

UNDECIDED_NOTE = (
    u"JPX prints 未定 (undecided) for companies that have not set a day. They "
    u"are listed under `undecided` with no date, never with a guessed one.")


def _require():
    cur = _cur()
    try:
        cur.execute("SELECT 1 FROM eq_cal_files LIMIT 1")
    except Exception:                                            # noqa: BLE001
        raise HTTPException(503, "earnings calendar not published yet")
    return cur


def _ceiling(as_of):
    u"""SQL fragment limiting to the lists that existed by `as_of`."""
    day = asof.parse(as_of)
    return day, ("" if day is None else " AND f.as_of_date <= %s" % asof.literal(day))


def _vintage(day):
    return {
        "unit": "list",
        "basis": "as_of_date",
        "as_of": day.isoformat() if day else None,
        "note": ("as_of selects the JPX lists dated on or before that day, by "
                 "the date each list states (the day it was read, for a "
                 "next-day list, which states none)." if day else
                 "The newest list per period-end month. Pass "
                 "?as_of=YYYY-MM-DD for the calendar as it was known then."),
    }


def _current(ceiling):
    u"""The current calendar as a CTE named `cur`, with previous_date.

    Newest monthly list per period-end month; next-day lists add or replace
    rows where they are newer. `apps` is every appearance of a row, used for
    the date it carried in the list before.
    """
    return """
    WITH f AS (SELECT * FROM eq_cal_files f WHERE TRUE%(c)s),
    latest AS (
        SELECT vintage_id FROM (
            SELECT vintage_id, row_number() OVER (
                PARTITION BY period_month ORDER BY as_of_date DESC, fetched_at DESC) AS rn
            FROM f WHERE kind = 'monthly') WHERE rn = 1),
    apps AS (
        SELECT r.*, f.as_of_date, f.fetched_at, f.kind, f.period_month,
               lag(r.announce_date) OVER (
                   PARTITION BY r.sec_code, r.fy_end, r.period_type_raw
                   ORDER BY f.as_of_date, f.fetched_at) AS prior_date,
               lag(f.as_of_date) OVER (
                   PARTITION BY r.sec_code, r.fy_end, r.period_type_raw
                   ORDER BY f.as_of_date, f.fetched_at) AS prior_as_of
        FROM eq_cal_rows r JOIN f USING (vintage_id)),
    cands AS (
        SELECT * FROM apps
        WHERE vintage_id IN (SELECT vintage_id FROM latest) OR kind = 'next-day'),
    cur AS (
        SELECT * FROM (
            SELECT *, row_number() OVER (
                PARTITION BY sec_code, fy_end, period_type_raw
                ORDER BY as_of_date DESC, fetched_at DESC) AS rn
            FROM cands) WHERE rn = 1)
    """ % {"c": ceiling}


ROW_COLS = """
    announce_date, sec_code, name_ja, name_en, fy_end, period_type,
    period_type_raw, industry_ja, industry_en, market_ja, market_en,
    CASE WHEN prior_as_of IS NOT NULL AND prior_date IS DISTINCT FROM announce_date
         THEN prior_date END AS previous_date,
    CASE WHEN prior_as_of IS NOT NULL AND prior_date IS DISTINCT FROM announce_date
         THEN prior_as_of END AS previous_list_as_of,
    vintage_id, as_of_date AS list_as_of
"""


def _codes(codes):
    out = []
    for c in (codes or "").replace(" ", "").split(","):
        if not c:
            continue
        c = c.upper()
        if len(c) == 5 and c.endswith("0"):
            c = c[:4]                  # TDnet's five-character form
        if not CODE.match(c):
            raise HTTPException(400, "not a securities code: %r" % c)
        out.append(c)
    if len(out) > MAX_CODES:
        raise HTTPException(400, "at most %d codes" % MAX_CODES)
    return out


def _filters(codes, market):
    where, params = [], []
    if codes:
        where.append("sec_code IN (%s)" % ", ".join(["?"] * len(codes)))
        params.extend(codes)
    if market:
        m = MARKETS.get(market.strip().lower())
        if m is None:
            raise HTTPException(400, "market must be one of %s" % ", ".join(sorted(MARKETS)))
        where.append("starts_with(market_ja, ?)")
        params.append(m)
    return "".join(" AND " + w for w in where), params


def _day(value, field):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(400, "%s must be a date, YYYY-MM-DD (got %r)" % (field, value))


def _horizon(cur, ceiling):
    lists = _rows(cur, _current(ceiling) + """
        SELECT f.period_month, f.as_of_date, f.file_name, f.companies,
               f.undecided, f.last_date
        FROM f WHERE f.vintage_id IN (SELECT vintage_id FROM latest)
        ORDER BY f.period_month DESC LIMIT 6""")
    newest = lists[0]["period_month"] if lists else None
    through = max((l["last_date"] for l in lists if l["last_date"]), default=None)
    out = {"lists": lists, "known_through": through, "note": HORIZON_NOTE}
    if newest:
        d = datetime.date.fromisoformat(str(newest)[:10])
        nxt = datetime.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        out["next_list_pending"] = nxt.strftime("%Y-%m")
        out["pending_note"] = (
            "Companies whose quarter or fiscal year ends in %s have no date yet; "
            "JPX publishes that list early the following month."
            % nxt.strftime("%B %Y"))
    return out


@router.get("/upcoming")
def upcoming(
        start: str = Query("", description="first day, YYYY-MM-DD; default today in Tokyo"),
        end: str = Query("", description="last day, YYYY-MM-DD; default start + 13 days"),
        codes: str = Query("", description="comma-separated securities codes; empty = every company"),
        market: str = Query("", description="prime, standard, growth or reit"),
        as_of: str = Query("", description="the calendar as known on this date")):
    u"""Scheduled earnings announcements between two dates."""
    cur = _require()
    day, ceiling = _ceiling(as_of)
    s = _day(start, "start") or datetime.datetime.now(JST).date()
    e = _day(end, "end") or (s + datetime.timedelta(days=DEFAULT_RANGE_DAYS - 1))
    if e < s:
        raise HTTPException(400, "end is before start")
    if (e - s).days >= MAX_RANGE_DAYS:
        raise HTTPException(400, "at most %d days per request" % MAX_RANGE_DAYS)
    code_list = _codes(codes)
    where, params = _filters(code_list, market)

    events = _rows(cur, _current(ceiling) + "SELECT " + ROW_COLS + """
        FROM cur WHERE announce_date BETWEEN ? AND ?""" + where + """
        ORDER BY announce_date, sec_code""", [s, e] + params)
    undecided = _rows(cur, _current(ceiling) + "SELECT " + ROW_COLS + """
        FROM cur WHERE announce_date IS NULL""" + where + """
        ORDER BY sec_code""", params)
    days = {}
    for ev in events:
        k = str(ev["announce_date"])[:10]
        days[k] = days.get(k, 0) + 1
    return {
        "range": {"start": s.isoformat(), "end": e.isoformat()},
        "filter": {"codes": code_list or None, "market": market or None},
        "horizon": _horizon(cur, ceiling),
        "days": [{"date": k, "companies": v} for k, v in sorted(days.items())],
        "events": events,
        "undecided": undecided,
        "notes": {"plan": PLAN_NOTE, "undecided": UNDECIDED_NOTE},
        "calc": CALC,
        "provenance": PROVENANCE,
        "vintage": _vintage(day),
    }


@router.get("/company/{sec_code}")
def company(sec_code: str, as_of: str = Query("", description="lists dated on or before")):
    u"""Every date a company has carried, list by list — how its plan moved."""
    cur = _require()
    code = _codes(sec_code)
    if len(code) != 1:
        raise HTTPException(400, "one securities code")
    day, ceiling = _ceiling(as_of)
    trail = _rows(cur, """
        SELECT r.fy_end, r.period_type, r.period_type_raw, r.announce_date,
               r.name_ja, r.name_en, f.file_name, f.kind, f.as_of_date AS list_as_of,
               f.vintage_id
        FROM eq_cal_rows r JOIN eq_cal_files f USING (vintage_id)
        WHERE r.sec_code = ?""" + ceiling + """
        ORDER BY r.fy_end DESC, r.period_type_raw, f.as_of_date DESC""", code)
    current = _rows(cur, _current(ceiling) + "SELECT " + ROW_COLS + """
        FROM cur WHERE sec_code = ? ORDER BY fy_end DESC, period_type_raw""", code)
    return {"sec_code": code[0], "current": current, "trail": trail,
            "notes": {"plan": PLAN_NOTE, "undecided": UNDECIDED_NOTE},
            "calc": CALC, "provenance": PROVENANCE, "vintage": _vintage(day)}


@router.get("/files")
def files(limit: int = Query(50, ge=1, le=500)):
    u"""Every JPX list held, newest first, with its hash and archive file."""
    cur = _require()
    return {"files": _rows(cur, """
        SELECT vintage_id, file_name, kind, period_month, as_of_date, as_of_basis,
               companies, undecided, first_date, last_date, sha256, url, raw_path,
               fetched_at, parser_version
        FROM eq_cal_files ORDER BY as_of_date DESC, fetched_at DESC LIMIT ?""", [limit]),
        "provenance": PROVENANCE}
