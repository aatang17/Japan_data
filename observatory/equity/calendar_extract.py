# -*- coding: utf-8 -*-
u"""Earnings calendar — JPX's 決算発表予定日 lists, parser `kessan-1`.

WHAT JPX PUBLISHES
------------------
One workbook per period-end month: every listed company whose quarter or
fiscal year ended in that month, with the day it has told the exchange it
will announce results. The list for a month goes up early the following
month and is re-issued as companies notify changes, under a new filename
(kessan08_0918.xlsx is the August list as it stood on 17 September). The
March and September lists carry about 3,100 companies each, since most of
the market closes its books in those months; the others carry a few hundred.

During the March and September seasons the page may also link a short
next-business-day file (kessan.xlsx), same layout, updated each evening.

WHAT THIS MEANS FOR A READER
----------------------------
  * A month's dates are known only after that month ends. On 24 September
    the July and August lists exist; the September list — the big one —
    does not until early October. So "no earnings on 5 November" can mean
    "not published yet". The API states how far ahead the lists reach.
  * A date is what the company told the exchange, not a promise. JPX says so
    itself, and a company can move it. Every re-issued list is stored whole
    beside the one before, so a moved date is visible, never overwritten.
  * 未定 (undecided) is stored as a missing date, never guessed.

STORAGE
-------
  eq_cal_files  one row per published workbook (its bytes' SHA-256 is the
                vintage). A workbook read twice stores nothing the second time.
  eq_cal_rows   every row of every workbook, exactly as published.
The current calendar is derived at serve time (app/calendar_api.py): for each
period-end month, the newest list; within that, next-day files where newer.

GATES (a workbook that fails one is not stored at all)
  G1  the header row is the one this parser was written against.
  G2  the title names a period-end month, and for a monthly list it agrees
      with the month in the filename; the as-of date parses and is not in
      the future.
  G3  a monthly list carries at least 20 companies.
  G4  every row has a code, a company name, a fiscal year-end and a
      recognised period type; a date cell is a date or 未定.
  G5  every announcement date falls between the start of the period-end month
      and 150 days after its end.
  G6  no company appears twice for the same fiscal year-end and period type.

Usage (from observatory/equity/):
    ../.venv/bin/python calendar_extract.py
    ../.venv/bin/python calendar_extract.py --db path.duckdb

Python 3.9.
"""
import argparse
import calendar as _calendar
import datetime
import hashlib
import os
import re
import sys

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from app.adapters import xlsx                                    # noqa: E402

DB_PATH = os.environ.get(
    "EQUITY_DB_PATH", os.path.join(HERE, "..", "data", "equity.duckdb"))
RAW_DIR = os.path.join(HERE, "..", "data", "raw")

PARSER_VERSION = "kessan-1"
EXTRACTOR = "earnings-calendar"

INDEX_URL = ("https://www.jpx.co.jp/listing/event-schedules/"
             "financial-announcement/index.html")
BASE = "https://www.jpx.co.jp"

# Same CDN as the short-selling files: a bare urllib request gets a 403.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

EPOCH = datetime.date(1899, 12, 30)
JST = datetime.timezone(datetime.timedelta(hours=9))

# kessan08_0918.xlsx (a monthly list) or kessan.xlsx (the next-day file).
LINK = re.compile(r'href="([^"]*?/(kessan(?:(\d{2})_(\d{4}))?)\.xlsx)"', re.I)

HEADER_ROW = 5
HEADER = {
    "A": u"決算発表予定日",
    "B": u"コード",
    "C": u"会社名",
    "D": u"Issue Name",
    "E": u"決算期末",
    "H": u"種別",
    "J": u"市場区分",
}
TITLE = re.compile(u"([0-9０-９]{1,2})月に四半期末又は期末を迎えた")
AS_OF = re.compile(r"As of (\d{4})/(\d{1,2})/(\d{1,2})")
UNDECIDED = u"未定"

# 種別 as printed -> the short form the API serves. REITs print "-": their
# fiscal period is not a quarter of anything, and it stays unlabelled.
PERIOD_TYPES = {
    u"本決算": "FY",
    u"第１四半期": "Q1",
    u"第２四半期": "Q2",
    u"第３四半期": "Q3",
    u"第４四半期": "Q4",
    u"-": None,
}

MIN_MONTHLY_ROWS = 20
DAYS_BEFORE_PERIOD = 31
DAYS_AFTER_PERIOD = 150


class SourceError(Exception):
    u"""The file could not be read, or read as something we don't recognise."""


# ------------------------------------------------------------- fetching ------

def fetch(url, timeout=30):
    from urllib.request import Request, urlopen
    req = Request(url, headers={"User-Agent": UA,
                                "Accept-Language": "ja,en;q=0.8"})
    return urlopen(req, timeout=timeout).read()


def listing(html):
    u"""[(name, url, month or None)] for every workbook linked from the page.

    `month` is the period-end month a monthly list names in its filename;
    None for the next-day file.
    """
    out, seen = [], set()
    for href, name, month, _stamp in LINK.findall(html):
        if name in seen:
            continue
        seen.add(name)
        url = href if href.startswith("http") else BASE + href
        out.append((name, url, int(month) if month else None))
    return out


def archive(name, data):
    sha = hashlib.sha256(data).hexdigest()
    if not os.path.isdir(RAW_DIR):
        os.makedirs(RAW_DIR)
    path = os.path.join(RAW_DIR, "jpx-%s-%s.xlsx" % (name, sha[:12]))
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(data)
    return sha, path


# -------------------------------------------------------------- parsing ------

def _squash(text):
    return re.sub(r"\s+", "", text or "")


def _clean(text):
    text = re.sub(r"\s+", " ", (text or "").replace(u"　", " ")).strip()
    return text or None


def _serial(text, field, where):
    text = (text or "").strip()
    try:
        return EPOCH + datetime.timedelta(days=int(float(text)))
    except (ValueError, OverflowError):
        raise SourceError("%s: %s is not a date: %r" % (where, field, text))


def _halfwidth(s):
    return s.translate(dict((0xFF10 + i, 0x30 + i) for i in range(10)))


def period_month(month, as_of):
    u"""The period-end month a list names, as the first day of that month.

    The title gives only the month. A list is published after its month ends,
    so the year is the latest one that puts the month before the as-of date.
    """
    year = as_of.year if month < as_of.month else as_of.year - 1
    return datetime.date(year, month, 1)


def month_end(first):
    return first.replace(day=_calendar.monthrange(first.year, first.month)[1])


def parse(raw, name, file_month, fetched_on):
    u"""One workbook -> (meta, [row dicts]). Raises SourceError on anything odd.

    `fetched_on` is the JST date we read it: the as-of date for the next-day
    file, which states none of its own.
    """
    try:
        book = xlsx.sheets(raw)
    except Exception as exc:                                     # noqa: BLE001
        raise SourceError("not a readable workbook: %s" % exc)
    if not book:
        raise SourceError("workbook has no sheets")
    grid = book[list(book.keys())[0]]

    def text(row, col):
        return xlsx.cell_text(grid.get(row, {}).get(col))

    # G1 — the header is the one we were written against. Each header cell
    # holds the Japanese label, a newline and the English one; the Japanese
    # label must lead.
    for col, label in sorted(HEADER.items()):
        got = _squash(text(HEADER_ROW, col))
        if not got.startswith(_squash(label)):
            raise SourceError("column %s is %r, expected %r — JPX changed "
                              "the layout" % (col, got, label))

    # G2 — the title's month, the filename's month and the as-of date.
    m = TITLE.search(_halfwidth(text(1, "A")))
    if not m:
        raise SourceError("no period-end month in the title %r" % text(1, "A"))
    title_month = int(m.group(1))
    if not 1 <= title_month <= 12:
        raise SourceError("title names month %d" % title_month)
    if file_month is not None and file_month != title_month:
        raise SourceError("%s is named for month %d but its title says %d"
                          % (name, file_month, title_month))
    stated = None
    for r in (3, 4):
        a = AS_OF.search(text(r, "A"))
        if a:
            stated = datetime.date(int(a.group(1)), int(a.group(2)),
                                   int(a.group(3)))
    if file_month is not None and stated is None:
        raise SourceError("%s states no as-of date" % name)
    as_of = stated or fetched_on
    if as_of > fetched_on + datetime.timedelta(days=1):
        raise SourceError("%s is dated %s, after the day it was read"
                          % (name, as_of))
    first = period_month(title_month, as_of)

    rows = []
    for number in sorted(grid):
        if number <= HEADER_ROW:
            continue
        code = _clean(text(number, "B"))
        cell = (text(number, "A") or "").strip()
        if not code:
            continue                         # the footnotes under the table
        where = "row %d (%s)" % (number, code)
        if cell.startswith(UNDECIDED):
            announce = None
        else:
            announce = _serial(cell, u"決算発表予定日", where)
        fy_end = _serial(text(number, "E"), u"決算期末", where)
        raw_type = _clean(text(number, "H")) or ""
        if raw_type not in PERIOD_TYPES:
            raise SourceError("%s: unknown period type %r" % (where, raw_type))
        name_ja = _clean(text(number, "C"))
        if not name_ja:
            raise SourceError("%s names no company" % where)
        rows.append({
            "announce_date": announce,
            "sec_code": code,
            "name_ja": name_ja,
            "name_en": _clean(text(number, "D")),
            "fy_end": fy_end,
            "period_type": PERIOD_TYPES[raw_type],
            "period_type_raw": raw_type,
            "industry_ja": _clean(text(number, "F")),
            "industry_en": _clean(text(number, "G")),
            "market_ja": _clean(text(number, "J")),
            "market_en": _clean(text(number, "K")),
        })
    meta = {
        "name": name,
        "kind": "monthly" if file_month is not None else "next-day",
        "period_month": first,
        "as_of_date": as_of,
        "as_of_basis": "stated" if stated else "fetched",
    }
    return meta, rows


def check(meta, rows):
    u"""Gates G3, G5 and G6."""
    if meta["kind"] == "monthly" and len(rows) < MIN_MONTHLY_ROWS:
        raise SourceError("only %d companies in a monthly list" % len(rows))
    lo = meta["period_month"] - datetime.timedelta(days=DAYS_BEFORE_PERIOD)
    hi = month_end(meta["period_month"]) + datetime.timedelta(days=DAYS_AFTER_PERIOD)
    seen = set()
    for r in rows:
        d = r["announce_date"]
        if d is not None and not lo <= d <= hi:
            raise SourceError("%s announces on %s, outside %s to %s for the "
                              "%s list" % (r["sec_code"], d, lo, hi,
                                           meta["period_month"].strftime("%Y-%m")))
        key = (r["sec_code"], r["fy_end"], r["period_type_raw"])
        if key in seen:
            raise SourceError("%s appears twice for %s %s"
                              % (r["sec_code"], r["fy_end"], r["period_type_raw"]))
        seen.add(key)
    dated = [r["announce_date"] for r in rows if r["announce_date"]]
    return {
        "companies": len(rows),
        "undecided": sum(1 for r in rows if r["announce_date"] is None),
        "first_date": min(dated) if dated else None,
        "last_date": max(dated) if dated else None,
    }


# -------------------------------------------------------------- storage ------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS eq_cal_files (
    vintage_id    VARCHAR PRIMARY KEY,  -- file name + content hash
    file_name     VARCHAR,              -- kessan08_0918, or kessan
    kind          VARCHAR,              -- 'monthly' or 'next-day'
    period_month  DATE,                 -- first day of the period-end month
    as_of_date    DATE,                 -- the list's own date, else the day read
    as_of_basis   VARCHAR,              -- 'stated' or 'fetched'
    sha256        VARCHAR,
    companies     INTEGER,
    undecided     INTEGER,
    first_date    DATE,
    last_date     DATE,
    url           VARCHAR,
    raw_path      VARCHAR,
    fetched_at    TIMESTAMP,
    parser_version VARCHAR
);

CREATE TABLE IF NOT EXISTS eq_cal_rows (
    vintage_id      VARCHAR,
    announce_date   DATE,       -- 決算発表予定日; NULL where JPX prints 未定
    sec_code        VARCHAR,    -- JPX 4-character code, as printed
    name_ja         VARCHAR,
    name_en         VARCHAR,
    fy_end          DATE,       -- 決算期末: the fiscal year the result belongs to
    period_type     VARCHAR,    -- FY / Q1-Q4; NULL for a REIT's period
    period_type_raw VARCHAR,    -- 種別, verbatim
    industry_ja     VARCHAR,
    industry_en     VARCHAR,
    market_ja       VARCHAR,
    market_en       VARCHAR
);

CREATE TABLE IF NOT EXISTS eq_extract_runs (
    extractor VARCHAR PRIMARY KEY,
    through_date DATE,
    docs_seen BIGINT,
    parser_version VARCHAR,
    ran_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS eq_cal_code ON eq_cal_rows (sec_code);
CREATE INDEX IF NOT EXISTS eq_cal_date ON eq_cal_rows (announce_date);
CREATE INDEX IF NOT EXISTS eq_cal_vintage ON eq_cal_rows (vintage_id);
"""

COLUMNS = ("announce_date", "sec_code", "name_ja", "name_en", "fy_end",
           "period_type", "period_type_raw", "industry_ja", "industry_en",
           "market_ja", "market_en")

INSERT = "INSERT INTO eq_cal_rows (vintage_id, %s) VALUES (?, %s)" % (
    ", ".join(COLUMNS), ", ".join(["?"] * len(COLUMNS)))


def vintage_id(name, sha):
    return "jpx-%s-%s" % (name, sha[:12])


def store(con, meta, sha, rows, stats, url, raw_path):
    u"""Insert one workbook whole, or nothing. Never touches a stored one."""
    vid = vintage_id(meta["name"], sha)
    if con.execute("SELECT 1 FROM eq_cal_files WHERE vintage_id = ?",
                   [vid]).fetchone():
        return vid, 0
    con.execute("BEGIN")
    try:
        if rows:
            con.executemany(
                INSERT, [[vid] + [r.get(c) for c in COLUMNS] for r in rows])
        con.execute(
            "INSERT INTO eq_cal_files (vintage_id, file_name, kind, period_month,"
            " as_of_date, as_of_basis, sha256, companies, undecided, first_date,"
            " last_date, url, raw_path, fetched_at, parser_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [vid, meta["name"], meta["kind"], meta["period_month"],
             meta["as_of_date"], meta["as_of_basis"], sha, stats["companies"],
             stats["undecided"], stats["first_date"], stats["last_date"], url,
             os.path.basename(raw_path), datetime.datetime.utcnow(),
             PARSER_VERSION])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return vid, len(rows)


# ----------------------------------------------------------------- main ------

def run(con):
    html = fetch(INDEX_URL).decode("utf-8", "replace")
    files = listing(html)
    monthly = [f for f in files if f[2] is not None]
    if not monthly:
        raise SourceError("no monthly lists linked from %s — the page layout "
                          "changed" % INDEX_URL)
    today = datetime.datetime.now(JST).date()
    print("%d workbooks on the page: %s" % (len(files), ", ".join(f[0] for f in files)))

    failed = 0
    for name, url, month in files:
        try:
            raw = fetch(url)
            meta, rows = parse(raw, name, month, today)
            stats = check(meta, rows)
            sha, path = archive(name, raw)
            vid, n = store(con, meta, sha, rows, stats, url, path)
            print("%s  %s  %s  (%s list as of %s; %d undecided; %s to %s)"
                  % (name, vid, "stored %d rows" % n if n else "unchanged",
                     meta["period_month"].strftime("%Y-%m"), meta["as_of_date"],
                     stats["undecided"], stats["first_date"], stats["last_date"]))
        except SourceError as exc:
            failed += 1
            print("%s  REJECTED: %s" % (name, exc))
        except Exception as exc:                                 # noqa: BLE001
            failed += 1
            print("%s  FAILED: %s: %s" % (name, type(exc).__name__, str(exc)[:200]))

    # The watermark is the newest list we hold, by its own date. JPX re-issues
    # a list every week or two, and a new month's list at least monthly, so a
    # watermark that stops moving means the page stopped being read.
    newest = con.execute(
        "SELECT max(as_of_date) FROM eq_cal_files").fetchone()[0]
    if newest:
        con.execute(
            "INSERT OR REPLACE INTO eq_extract_runs (extractor, through_date,"
            " docs_seen, parser_version, ran_at) VALUES (?, ?, ?, ?, ?)",
            [EXTRACTOR, newest,
             con.execute("SELECT count(*) FROM eq_cal_files").fetchone()[0],
             PARSER_VERSION, datetime.datetime.utcnow()])
    return failed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB_PATH)
    # Passed by the nightly refresh to every extractor; meaningless here.
    ap.add_argument("--source", default="local")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--new-only", action="store_true")
    ap.add_argument("--no-compact", action="store_true")
    args = ap.parse_args()

    con = duckdb.connect(args.db)
    con.execute(SCHEMA_SQL)
    try:
        failed = run(con)
    except SourceError as exc:
        print("REJECTED: %s" % exc)
        return 1
    except Exception as exc:                                     # noqa: BLE001
        print("FAILED: %s: %s" % (type(exc).__name__, str(exc)[:300]))
        return 1
    finally:
        con.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
