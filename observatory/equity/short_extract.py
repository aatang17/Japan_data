# -*- coding: utf-8 -*-
u"""Short positions — the JPX daily disclosure of 空売り残高, parser `short-1`.

WHY THIS ONE CANNOT WAIT
------------------------
Every holder of a short position worth 0.5% or more of an issuer's shares must
report it, and the exchange publishes every such report the next business day.
It is the exact mirror of the 5% long filings this platform already carries:
name, address, issuer, size, and the day the position was measured.

JPX keeps about **twelve business days** of those files on its site and then
deletes them. There is no archive, no API, no back-file and no second source.
So the history of who was short what, in Japan, exists only for as long as
somebody is copying it down each day — which is the same position TDnet is in
(see ``tdnet_extract.py``), and the reason both run nightly.

WHAT A DAILY FILE ACTUALLY CONTAINS
-----------------------------------
Not the outstanding book. Each file is the set of reports RECEIVED that day,
and a report is dated by its own 計算年月日 (calculation date), typically two
business days before publication. Consecutive files therefore overlap only
partly — 429 of 961 rows between 15 and 16 September 2026 — because a holder
files again only when the position moves.

That makes this a TAPE, like the 5% filings, not a snapshot:

  * ``eq_short_reports`` is the tape — one row per report per published file,
    exactly as published.
  * The outstanding book is DERIVED from it at serve time: for each
    (issuer, holder, fund), the newest report by calculation date. That
    derivation carries its formula, never a badge (``app/short_api.py``).

A position that closes is reported too: the row carries the note "Below the
threshold" (or its Japanese equivalent) and a ratio at or near zero. **That
zero is a real zero** — the position went away — and must never be confused
with a missing value.

A CONSEQUENCE WORTH SAYING OUT LOUD
-----------------------------------
A book assembled from a tape is only as complete as the tape is long. A
position opened before our first captured day and not moved since has never
been published into our archive, so it is not in ours either. The gap closes
as the archive lengthens; until it has, every surface says so.

GATES
-----
  G1  the Japanese header row is the one this parser was written against —
      a renamed or reordered column stops the file rather than silently
      mapping the wrong field.
  G2  the publication date inside the file equals the date in its filename.
  G3  at least 50 reports; a normal day carries roughly a thousand, and JPX
      publishes no file at all on a day with nothing to report.
  G4  every row states an issuer code, a holder and a share count.
  G5  ratios sit in [0, 50]% and share counts are never negative.
  G6  a calculation date is on or before the publication date, and within 30
      days of it.

Usage (from observatory/equity/):
    ../.venv/bin/python short_extract.py                 # every day still on the site
    ../.venv/bin/python short_extract.py --limit 1       # newest day only
    ../.venv/bin/python short_extract.py --db path.duckdb

Python 3.9.
"""
import argparse
import datetime
import hashlib
import os
import re
import sys

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from app.adapters import xls                                     # noqa: E402

DB_PATH = os.environ.get(
    "EQUITY_DB_PATH", os.path.join(HERE, "..", "data", "equity.duckdb"))
RAW_DIR = os.path.join(HERE, "..", "data", "raw")

PARSER_VERSION = "short-1"
EXTRACTOR = "short-positions"

INDEX_URL = "https://www.jpx.co.jp/markets/public/short-selling/index.html"
BASE = "https://www.jpx.co.jp"

# JPX serves these from a CDN that answers a bare urllib request with 403.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# Excel's day zero. The workbook stores every date as a serial number and this
# module converts once, here, rather than leaving serials in the database.
EPOCH = datetime.date(1899, 12, 30)

LINK = re.compile(r'href="([^"]*?(\d{8})_Short_Positions\.xls)"', re.I)

# The header this parser was written against, row 7 of the sheet. Compared
# after whitespace is stripped out, because JPX pads these cells irregularly.
HEADER = {
    "B": u"計算年月日",
    "C": u"銘柄コード",
    "F": u"商号・名称・氏名",
    "G": u"住所・所在地",
    "K": u"空売り残高割合",
    "L": u"空売り残高数量",
    "M": u"空売り残高売買単位数",
    "N": u"直近計算年月日",
    "O": u"直近空売り残高割合",
}
HEADER_ROW = 7
FIRST_DATA_ROW = 9
PUBLISH_CELL = ("C", 5)          # 公表年月日, as a serial

# Words a closing report carries in the 備考 column. A holder whose position
# drops under the 0.5% disclosure threshold files one last report saying so.
BELOW_THRESHOLD = (u"below the threshold", u"0.5%を下回", u"０．５％を下回")

# Placeholders the file uses for "this field does not apply". They are missing,
# never a value.
BLANKS = ("", "-", u"－", u"ー", "n/a", "N/A", u"該当なし")

# Legal-form tokens folded out of a holder name to give it a stable key.
# Deliberately short: it removes what a registrar appends, never anything that
# distinguishes one arm of a group from another. "Morgan Stanley & Co.
# International plc" folds to "morgan stanley co international", which is still
# not "Morgan Stanley MUFG Securities".
SUFFIXES = ("plc", "llc", "ltd", "limited", "inc", "incorporated", "llp", "lp",
            "gmbh", "ag", "sa", "snc", "nv", "bv", "pte", "co", "corp",
            "corporation", "partnership", "sc", "spc")

MAX_RATIO_PCT = 50.0
MIN_ROWS = 50
MAX_REPORT_LAG_DAYS = 30


class SourceError(Exception):
    u"""The file could not be read, or read as something we don't recognise."""


# ------------------------------------------------------------- fetching ------

def fetch(url, timeout=120):
    from urllib.request import Request, urlopen
    req = Request(url, headers={"User-Agent": UA,
                                "Accept-Language": "ja,en;q=0.8"})
    return urlopen(req, timeout=timeout).read()


def listing(html):
    u"""{publication date: absolute url} for every daily file still on the page.

    JPX keeps roughly the current month. A date that has fallen off the page is
    gone from the internet; whether we hold it depends entirely on whether this
    ran while it was up.
    """
    out = {}
    for href, stamp in LINK.findall(html):
        try:
            day = datetime.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
        except ValueError:
            continue
        out[day] = href if href.startswith("http") else BASE + href
    return out


def archive(day, data):
    u"""Write the bytes under their own hash, and return (sha256, path).

    Same convention as the macro ingests and `class_extract.py`: the archived
    file can always be tied back to the vintage row that quotes it.
    """
    sha = hashlib.sha256(data).hexdigest()
    if not os.path.isdir(RAW_DIR):
        os.makedirs(RAW_DIR)
    path = os.path.join(
        RAW_DIR, "jpx-short-%s-%s.xls" % (day.strftime("%Y%m%d"), sha[:12]))
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(data)
    return sha, path


# -------------------------------------------------------------- parsing ------

def _squash(text):
    return re.sub(r"\s+", "", text or "")


def _clean(text):
    u"""A cell's text, or None where the file means 'does not apply'."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return None if text in BLANKS else text


def _serial_date(text, field):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return EPOCH + datetime.timedelta(days=int(float(text)))
    except (ValueError, OverflowError):
        raise SourceError("%s is not a date serial: %r" % (field, text))


def _number(text):
    text = (text or "").strip().replace(",", "")
    if text in ("", "-", u"－", u"ー"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def holder_key(name):
    u"""A stable identity for a holder, folded the way a ranking needs it.

    Case, punctuation, spacing and the legal-form tail are what vary between
    one filing of a name and the next; nothing else is touched. A Japanese
    name folds to itself with spaces removed, which is what the rest of the
    platform does with 商号 too.
    """
    if not name:
        return None
    text = name.strip().lower()
    text = text.replace(u"　", " ")
    text = re.sub(r"[.,()、。&'’\"/]", " ", text)
    tokens = [t for t in text.split() if t]
    while tokens and tokens[-1] in SUFFIXES:
        tokens.pop()
    return " ".join(tokens) if tokens else name.strip().lower()


def parse(raw, expected_day):
    u"""One daily workbook -> (publication date, [report dicts]).

    Raises SourceError on anything this parser does not recognise. The caller
    stores nothing when that happens, and the days already held stay live.
    """
    try:
        book = xls.sheets(raw)
    except Exception as exc:                                     # noqa: BLE001
        raise SourceError("not a readable workbook: %s" % exc)
    if not book:
        raise SourceError("workbook has no sheets")
    grid = book[list(book.keys())[0]]
    if not grid:
        raise SourceError("first sheet is empty")

    # G1 — the header is the one we were written against.
    head = grid.get(HEADER_ROW, {})
    for col, label in sorted(HEADER.items()):
        got = _squash(xls.cell_text(head.get(col)))
        if got != _squash(label):
            raise SourceError(
                "column %s is %r, expected %r — JPX changed the layout"
                % (col, got, label))

    # G2 — the file's own publication date agrees with its filename.
    col, row = PUBLISH_CELL
    published = _serial_date(xls.cell_text(grid.get(row, {}).get(col)),
                             u"公表年月日")
    if published is None:
        raise SourceError("no publication date in cell %s%d" % (col, row))
    if published != expected_day:
        raise SourceError("file named %s carries publication date %s"
                          % (expected_day, published))

    reports = []
    for number in sorted(grid):
        if number < FIRST_DATA_ROW:
            continue
        cells = grid[number]

        def text(letter):
            return xls.cell_text(cells.get(letter)) if letter in cells else ""

        sec_code = _clean(text("C"))
        if not sec_code:
            continue                       # trailing notes and blank rows

        calc_date = _serial_date(text("B"), u"計算年月日")
        holder = _clean(text("F"))
        shares = _number(text("L"))
        ratio = _number(text("K"))

        # G4 — a row without these three is not a report.
        if not holder or shares is None or ratio is None:
            raise SourceError(
                "row %d (%s) states no %s" % (
                    number, sec_code,
                    "holder" if not holder else
                    "share count" if shares is None else "ratio"))
        if calc_date is None:
            raise SourceError("row %d (%s) has no calculation date"
                              % (number, sec_code))

        # JPX publishes the ratio as a decimal fraction (0.0055). It is stored
        # as the percentage its own PDF prints, which is the same number in the
        # unit every other holding ratio on this platform uses.
        ratio_pct = ratio * 100.0
        prev_ratio = _number(text("O"))
        note = _clean(text("P"))
        low = (note or "").lower()

        reports.append({
            "publish_date": published,
            "calc_date": calc_date,
            "sec_code": sec_code,
            "name_ja": _clean(text("D")),
            "name_en": _clean(text("E")),
            "holder_name": holder,
            "holder_address": _clean(text("G")),
            "holder_key": holder_key(holder),
            "manager_name": _clean(text("H")),
            "manager_address": _clean(text("I")),
            "fund_name": _clean(text("J")),
            "ratio_pct": ratio_pct,
            "shares": int(shares),
            "units": int(_number(text("M")) or 0) if text("M") else None,
            "prev_calc_date": _serial_date(text("N"), u"直近計算年月日"),
            "prev_ratio_pct": None if prev_ratio is None else prev_ratio * 100.0,
            "note_raw": note,
            "below_threshold": any(w in low for w in BELOW_THRESHOLD),
        })

    for r in reports:
        r["report_key"] = report_key(r)
    return published, reports


def report_key(r):
    u"""What makes two rows the same report.

    A calculation date, an issuer, a holder and — where the holder reports per
    fund — the fund. The same report appears in more than one daily file, so
    this is what a reader groups on when asking what the book looks like; it is
    NOT a primary key here, because every published file is stored whole.
    """
    parts = [r["calc_date"].isoformat(), r["sec_code"], r["holder_key"] or "",
             (r["fund_name"] or "").lower(), (r["manager_name"] or "").lower()]
    return hashlib.sha1(u"|".join(parts).encode("utf-8")).hexdigest()[:20]


def check(published, reports):
    u"""Gates G3, G5 and G6. A file that fails one is not stored at all."""
    if len(reports) < MIN_ROWS:
        raise SourceError("only %d reports; a normal day carries about a "
                          "thousand" % len(reports))
    for r in reports:
        where = "%s %s" % (r["sec_code"], r["holder_name"])
        if r["shares"] < 0:
            raise SourceError("%s: a short position of %s shares is negative"
                              % (where, r["shares"]))
        if not 0.0 <= r["ratio_pct"] <= MAX_RATIO_PCT:
            raise SourceError("%s: %.4f%% is outside the plausible range"
                              % (where, r["ratio_pct"]))
        lag = (published - r["calc_date"]).days
        if lag < 0:
            raise SourceError("%s: calculated %s, after the %s publication"
                              % (where, r["calc_date"], published))
        if lag > MAX_REPORT_LAG_DAYS:
            raise SourceError("%s: calculated %s, %d days before publication"
                              % (where, r["calc_date"], lag))
    calc = [r["calc_date"] for r in reports]
    return {
        "reports": len(reports),
        "issuers": len(set(r["sec_code"] for r in reports)),
        "holders": len(set(r["holder_key"] for r in reports)),
        "calc_date_min": min(calc),
        "calc_date_max": max(calc),
        "closing": sum(1 for r in reports if r["below_threshold"]),
    }


# -------------------------------------------------------------- storage ------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS eq_short_files (
    vintage_id   VARCHAR PRIMARY KEY,   -- publication date + content hash
    publish_date DATE,
    sha256       VARCHAR,
    row_count    INTEGER,
    issuers      INTEGER,
    holders      INTEGER,
    calc_date_min DATE,
    calc_date_max DATE,
    url          VARCHAR,
    raw_path     VARCHAR,
    fetched_at   TIMESTAMP,
    parser_version VARCHAR
);

CREATE TABLE IF NOT EXISTS eq_short_reports (
    vintage_id      VARCHAR,
    publish_date    DATE,        -- the day JPX published this file
    calc_date       DATE,        -- 計算年月日, the day the position is measured
    sec_code        VARCHAR,     -- JPX 4-character code, as printed
    name_ja         VARCHAR,
    name_en         VARCHAR,
    holder_name     VARCHAR,     -- 商号・名称・氏名, as published
    holder_address  VARCHAR,
    holder_key      VARCHAR,     -- folded name; what a ranking groups on
    manager_name    VARCHAR,     -- 委託者・投資一任契約の相手方
    manager_address VARCHAR,
    fund_name       VARCHAR,     -- 信託財産・運用財産の名称
    ratio_pct       DOUBLE,      -- 空売り残高割合, as a percentage
    shares          BIGINT,      -- 空売り残高数量
    units           BIGINT,      -- 空売り残高売買単位数
    prev_calc_date  DATE,
    prev_ratio_pct  DOUBLE,
    note_raw        VARCHAR,     -- 備考, verbatim
    below_threshold BOOLEAN,     -- the note says the position fell under 0.5%
    report_key      VARCHAR      -- same report, however many files carry it
);

CREATE TABLE IF NOT EXISTS eq_extract_runs (
    extractor VARCHAR PRIMARY KEY,
    through_date DATE,
    docs_seen BIGINT,
    parser_version VARCHAR,
    ran_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS eq_short_code ON eq_short_reports (sec_code);
CREATE INDEX IF NOT EXISTS eq_short_pub ON eq_short_reports (publish_date);
CREATE INDEX IF NOT EXISTS eq_short_calc ON eq_short_reports (calc_date);
CREATE INDEX IF NOT EXISTS eq_short_holder ON eq_short_reports (holder_key);
CREATE INDEX IF NOT EXISTS eq_short_report ON eq_short_reports (report_key);
"""

COLUMNS = ("publish_date", "calc_date", "sec_code", "name_ja", "name_en",
           "holder_name", "holder_address", "holder_key", "manager_name",
           "manager_address", "fund_name", "ratio_pct", "shares", "units",
           "prev_calc_date", "prev_ratio_pct", "note_raw", "below_threshold",
           "report_key")

INSERT = "INSERT INTO eq_short_reports (vintage_id, %s) VALUES (?, %s)" % (
    ", ".join(COLUMNS), ", ".join(["?"] * len(COLUMNS)))


def vintage_id(day, sha):
    return "jpx-short-%s-%s" % (day.strftime("%Y%m%d"), sha[:12])


def stored_days(con):
    return {r[0] for r in con.execute(
        "SELECT DISTINCT publish_date FROM eq_short_files").fetchall()}


def store(con, day, sha, reports, stats, url, raw_path):
    u"""Insert one published file, or refuse.

    A vintage is its bytes: reading the same file twice stores nothing the
    second time. A revised file for the same day hashes differently and lands
    BESIDE the first — what JPX published on the day it published it stays
    recoverable, which is the whole reason for keeping this.
    """
    vid = vintage_id(day, sha)
    if con.execute("SELECT 1 FROM eq_short_files WHERE vintage_id = ?",
                   [vid]).fetchone():
        return vid, 0
    con.execute("BEGIN")
    try:
        con.executemany(
            INSERT, [[vid] + [r.get(c) for c in COLUMNS] for r in reports])
        con.execute(
            "INSERT INTO eq_short_files (vintage_id, publish_date, sha256,"
            " row_count, issuers, holders, calc_date_min, calc_date_max, url,"
            " raw_path, fetched_at, parser_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [vid, day, sha, len(reports), stats["issuers"], stats["holders"],
             stats["calc_date_min"], stats["calc_date_max"], url,
             os.path.basename(raw_path), datetime.datetime.utcnow(),
             PARSER_VERSION])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return vid, len(reports)


# ----------------------------------------------------------------- main ------

def run(con, args):
    html = fetch(INDEX_URL).decode("utf-8", "replace")
    days = listing(html)
    if not days:
        raise SourceError("no daily files linked from %s — the page layout "
                          "changed" % INDEX_URL)

    have = stored_days(con)
    wanted = sorted(days, reverse=True)
    if args.limit:
        wanted = wanted[:args.limit]
    if not args.refetch:
        wanted = [d for d in wanted if d not in have]

    print("%d files on the page (%s to %s); %d to read"
          % (len(days), min(days), max(days), len(wanted)))

    newest, failed = None, 0
    for day in sorted(wanted):
        url = days[day]
        try:
            raw = fetch(url)
            published, reports = parse(raw, day)
            stats = check(published, reports)
            sha, path = archive(day, raw)
            vid, n = store(con, day, sha, reports, stats, url, path)
            print("%s  %s  %s  (%d issuers, %d holders, %d closing)"
                  % (day, vid, "stored %d reports" % n if n else "unchanged",
                     stats["issuers"], stats["holders"], stats["closing"]))
            newest = max(newest, day) if newest else day
        except SourceError as exc:
            failed += 1
            print("%s  REJECTED: %s" % (day, exc))
        except Exception as exc:                                 # noqa: BLE001
            failed += 1
            print("%s  FAILED: %s: %s" % (day, type(exc).__name__, str(exc)[:200]))

    # The watermark moves only when a file was actually read and accepted. A
    # run in which JPX was unreachable leaves it where it was, so
    # /catalog/health reports the dataset going stale rather than reporting a
    # healthy run over nothing.
    if newest is None:
        held = con.execute(
            "SELECT max(publish_date) FROM eq_short_files").fetchone()[0]
        newest = held
    if newest:
        con.execute(
            "INSERT OR REPLACE INTO eq_extract_runs (extractor, through_date,"
            " docs_seen, parser_version, ran_at) VALUES (?, ?, ?, ?, ?)",
            [EXTRACTOR, newest,
             con.execute("SELECT count(*) FROM eq_short_reports").fetchone()[0],
             PARSER_VERSION, datetime.datetime.utcnow()])
    return failed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--limit", type=int, default=0,
                    help="read only the N newest days still on the page")
    ap.add_argument("--refetch", action="store_true",
                    help="re-read days already held; a revision lands as a "
                         "new vintage beside the one we hold, never over it")
    # The nightly refresh passes these to every extractor. This one reads a
    # web page, not the EDINET archive, so they mean nothing here; accepted
    # and ignored so the runner stays uniform.
    ap.add_argument("--source", default="local")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--new-only", action="store_true")
    ap.add_argument("--no-compact", action="store_true")
    args = ap.parse_args()

    con = duckdb.connect(args.db)
    con.execute(SCHEMA_SQL)
    try:
        failed = run(con, args)
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
