# -*- coding: utf-8 -*-
u"""Cohorts — the TOPIX classification from JPX, the Nikkei 225 from Nikkei.

Why this exists
---------------
Every cross-company surface in this product ranks companies against the whole
listed market, and that is the wrong denominator for almost every question
anyone actually asks. A 3% female board is unremarkable among 3,700 listed
issues and conspicuous inside TOPIX Core30; a 40% cross-shareholding ratio
means one thing for a regional bank and another for a Prime-listed machinery
maker. The comparison only carries information once it is made against the
cohort the company actually trades in.

We do not license TOPIX or the Nikkei 225, and this does not pretend to
reconstruct either index. Both publishers put their constituent lists in the
open; this reads them, joins them to the EDINET registry we already keep, and
stores the membership so a screen can be scoped to it.

    - JPX 東証上場銘柄一覧 (``data_j.xlsx``) — every listed issue with its
      market segment, the 33- and 17-industry codes, and the TOPIX scale
      band (Core30 / Large70 / Mid400 / Small 1 / Small 2). Free, updated
      monthly, no key. The issues carrying a scale band ARE the TOPIX
      constituents — 1,636 of them at 2026-08-31.
    - Nikkei 225 constituent weights CSV — the 225, with Nikkei's own
      36-industry and 6-sector groupings and each issue's index weight.

Redistribution
--------------
The Nikkei file carries an explicit notice: it is Nikkei's copyrighted work
and may not be copied, reproduced, republished or distributed without
permission. So its rows are stored with ``public = FALSE`` and the serving
layer refuses to emit them without the admin credential (see
``app/cohorts.py``). This is enforced in the query layer, not by convention:
a cohort resolves to a set of security codes, and a non-public cohort resolves
to nothing at all unless the caller is authorised. The JPX file is published
for public reference and its rows are ``public = TRUE``.

Vintages
--------
Membership is a moving target — index reviews, segment migrations, listings
and delistings — and the whole point of holding it is being able to ask what a
cohort looked like at the time. A vintage is one accepted read of one source
file, identified by the SHA-256 of the bytes; the raw file is archived under
``data/raw/`` before anything is parsed. **A stored vintage is never rewritten.**
Re-running against an unchanged file is a no-op; a revised file at the same
effective date lands as a separate vintage and the newer one wins on read.
Back-history is not available from either publisher, so this accumulates
forward from the first run, like every other vintage in the product.

Usage:
    python class_extract.py                    # fetch both, store new vintages
    python class_extract.py --skip-nikkei      # JPX only
    python class_extract.py --db path.duckdb

Python 3.9.
"""
import argparse
import csv
import datetime
import hashlib
import io
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

PARSER_VERSION = "class-1"

JPX_URL = ("https://www.jpx.co.jp/markets/statistics-equities/misc/"
           "tvdivq0000001vg2-att/data_j.xlsx")
NIKKEI_URL = ("https://indexes.nikkei.co.jp/nkave/archives/file/"
              "nikkei_stock_average_weight_jp.csv")

# Both publishers serve these from a CDN that answers a bare urllib request
# with 403. A browser user-agent is the whole difference.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


class SourceError(Exception):
    u"""The source could not be read, or read as something we don't recognise."""


def fetch(url, timeout=120):
    try:                                    # py3
        from urllib.request import Request, urlopen
    except ImportError:                     # pragma: no cover
        raise SourceError("no urllib")
    req = Request(url, headers={"User-Agent": UA,
                                "Accept-Language": "ja,en;q=0.8"})
    return urlopen(req, timeout=timeout).read()


def archive(name, data, ext):
    u"""Write the bytes to data/raw/ under their own hash, and return it.

    Same convention as the macro ingests: stamped with the fetch time and the
    first 12 of the SHA-256, so an archived file can always be tied back to
    the vintage row that quotes it.
    """
    sha = hashlib.sha256(data).hexdigest()
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    if not os.path.isdir(RAW_DIR):
        os.makedirs(RAW_DIR)
    path = os.path.join(RAW_DIR, "%s-%s-%s.%s" % (name, stamp, sha[:12], ext))
    with open(path, "wb") as fh:
        fh.write(data)
    return sha, path


# ---------------------------------------------------------------- JPX --------

JPX_HEADER = [u"日付", u"コード", u"銘柄名", u"市場・商品区分",
              u"33業種コード", u"33業種区分", u"17業種コード", u"17業種区分",
              u"規模コード", u"規模区分"]

# The segment label carries two facts in one string — which market, and
# whether the issue is a domestic or a foreign share — and the funds and the
# professional market are not operating companies at all. Splitting it here
# means no downstream query ever pattern-matches on Japanese text.
SEGMENTS = {
    u"プライム（内国株式）":   ("prime",    True),
    u"プライム（外国株式）":   ("prime",    False),
    u"スタンダード（内国株式）": ("standard", True),
    u"スタンダード（外国株式）": ("standard", False),
    u"グロース（内国株式）":   ("growth",   True),
    u"グロース（外国株式）":   ("growth",   False),
    u"ETF・ETN":              ("etf",      False),
    u"REIT・ベンチャーファンド・カントリーファンド・インフラファンド":
                              ("reit",     False),
    u"PRO Market":            ("pro",      True),
    u"出資証券":              ("shinkin",  True),
}

SIZES = {
    u"TOPIX Core30":  ("core30",  u"TOPIX Core30"),
    u"TOPIX Large70": ("large70", u"TOPIX Large70"),
    u"TOPIX Mid400":  ("mid400",  u"TOPIX Mid400"),
    u"TOPIX Small 1": ("small1",  u"TOPIX Small 1"),
    u"TOPIX Small 2": ("small2",  u"TOPIX Small 2"),
}


def _blank(v):
    u"""JPX writes a hyphen where a field does not apply. That is missing."""
    v = (v or "").strip()
    return None if v in ("", "-", u"－", u"ー") else v


def parse_jpx(raw):
    u"""data_j.xlsx -> (as_of, [row dicts]). Raises SourceError on any surprise."""
    try:
        book = xlsx.sheets(raw)
    except Exception as e:                                        # noqa: BLE001
        raise SourceError("not a readable workbook: %s" % e)
    if not book:
        raise SourceError("workbook has no sheets")
    grid = book[list(book.keys())[0]]
    if not grid:
        raise SourceError("first sheet is empty")

    numbers = sorted(grid)
    head = [xlsx.cell_text(grid[numbers[0]].get(c))
            for c in ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J")]
    if head != JPX_HEADER:
        raise SourceError("unexpected columns: %r" % (head,))

    as_of, rows, seen = None, [], set()
    for n in numbers[1:]:
        cells = grid[n]
        get = lambda c: _blank(xlsx.cell_text(cells.get(c)))       # noqa: E731
        code = get("B")
        if not code:
            continue
        day = get("A")
        if day and len(day) == 8 and day.isdigit():
            stamped = datetime.date(int(day[:4]), int(day[4:6]), int(day[6:]))
            if as_of and stamped != as_of:
                raise SourceError("two effective dates in one file: %s and %s"
                                  % (as_of, stamped))
            as_of = stamped
        if code in seen:
            raise SourceError("duplicate security code %s" % code)
        seen.add(code)
        segment_ja = get("D")
        segment, domestic = SEGMENTS.get(segment_ja or "", (None, None))
        size_key, size_name = SIZES.get(get("J") or "", (None, None))
        rows.append({
            "sec_code": code,
            "name_ja": get("C"),
            "segment_ja": segment_ja,
            "segment": segment,
            "domestic": domestic,
            "ind33_code": get("E"),
            "ind33_name": get("F"),
            "ind17_code": get("G"),
            "ind17_name": get("H"),
            "size_code": size_key,
            "size_name": size_name,
        })
    if as_of is None:
        raise SourceError("no effective date in the file")
    return as_of, rows


def check_jpx(rows):
    u"""Gates. A file that fails one of these is not stored, and the previous
    vintage stays live — the classification is never half-updated."""
    if len(rows) < 3000:
        raise SourceError("only %d issues; the market has ~4,400" % len(rows))
    unknown = sorted({r["segment_ja"] for r in rows if r["segment"] is None})
    if unknown:
        raise SourceError("unmapped market segments: %r" % unknown)
    bands = {}
    for r in rows:
        if r["size_code"]:
            bands[r["size_code"]] = bands.get(r["size_code"], 0) + 1
    missing = [k for k in ("core30", "large70", "mid400", "small1", "small2")
               if k not in bands]
    if missing:
        raise SourceError("TOPIX bands absent from the file: %r" % missing)
    # The two headline bands are near-fixed by construction — they run a
    # little over their nominal count between periodic reviews (Core30 held
    # 31 at 2026-08-31) — so they are bounded rather than asserted exactly.
    if not 28 <= bands["core30"] <= 34:
        raise SourceError("Core30 holds %d issues" % bands["core30"])
    if not 65 <= bands["large70"] <= 76:
        raise SourceError("Large70 holds %d issues" % bands["large70"])
    total = sum(bands.values())
    if not 1200 <= total <= 2600:
        raise SourceError("%d TOPIX constituents; expected ~1,600" % total)
    industries = {r["ind33_code"] for r in rows if r["ind33_code"]}
    if len(industries) != 33:
        raise SourceError("%d industry codes, expected 33" % len(industries))
    return bands


# ------------------------------------------------------------- Nikkei --------

NK_HEADER = [u"日付", u"コード", u"社名", u"業種", u"セクター", u"ウエート"]

NK_COPYRIGHT = u"著作物"


def parse_nikkei(raw):
    u"""The 225 weights CSV -> (as_of, [row dicts]).

    cp932, quoted, with a copyright line appended after the last constituent —
    that trailing line is the notice this data is stored under, so its absence
    means we are not reading the file we think we are.
    """
    try:
        text = raw.decode("cp932")
    except UnicodeDecodeError:
        raise SourceError("not cp932; Nikkei changed the encoding")
    lines = list(csv.reader(io.StringIO(text)))
    if not lines or [c.strip() for c in lines[0]] != NK_HEADER:
        raise SourceError("unexpected columns: %r" % (lines[0] if lines else None,))
    if not any(NK_COPYRIGHT in "".join(r) for r in lines[-3:]):
        raise SourceError("the copyright notice is gone; check what changed "
                          "before storing this file")

    as_of, rows, seen = None, [], set()
    for r in lines[1:]:
        if len(r) != 6:
            continue
        day, code, name, industry, sector, weight = [c.strip() for c in r]
        if not re.match(r"^\d{4}/\d{2}/\d{2}$", day):
            continue
        stamped = datetime.date(int(day[:4]), int(day[5:7]), int(day[8:]))
        if as_of and stamped != as_of:
            raise SourceError("two effective dates in one file")
        as_of = stamped
        if code in seen:
            raise SourceError("duplicate security code %s" % code)
        seen.add(code)
        pct = None
        if weight.endswith("%"):
            try:
                pct = float(weight[:-1])
            except ValueError:
                pct = None
        rows.append({"sec_code": code, "name_ja": name,
                     "nk_industry": industry, "nk_sector": sector,
                     "weight_pct": pct})
    if as_of is None:
        raise SourceError("no effective date in the file")
    return as_of, rows


def check_nikkei(rows):
    if len(rows) != 225:
        raise SourceError("%d constituents; the Nikkei 225 has 225" % len(rows))
    weights = [r["weight_pct"] for r in rows if r["weight_pct"] is not None]
    if len(weights) != 225:
        raise SourceError("%d issues have no weight" % (225 - len(weights)))
    total = sum(weights)
    # Each weight is published rounded to four decimals, so 225 of them sum to
    # 100 only within rounding — not to the digit.
    if abs(total - 100.0) > 0.5:
        raise SourceError("weights sum to %.4f%%, not 100%%" % total)
    return total


# ------------------------------------------------------------ storage --------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS eq_class_vintages (
    vintage_id  VARCHAR PRIMARY KEY,   -- source + effective date + content hash
    source      VARCHAR,               -- 'jpx-listed' | 'nikkei-225'
    as_of       DATE,                  -- the file's OWN effective date
    sha256      VARCHAR,
    row_count   INTEGER,
    public      BOOLEAN,               -- may these rows be served publicly?
    url         VARCHAR,
    raw_path    VARCHAR,
    fetched_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS eq_classification (
    vintage_id  VARCHAR,
    as_of       DATE,
    sec_code    VARCHAR,
    name_ja     VARCHAR,
    segment_ja  VARCHAR,
    segment     VARCHAR,               -- prime | standard | growth | etf | ...
    domestic    BOOLEAN,
    ind33_code  VARCHAR,
    ind33_name  VARCHAR,
    ind17_code  VARCHAR,
    ind17_name  VARCHAR,
    size_code   VARCHAR,               -- core30 | large70 | mid400 | small1 | small2
    size_name   VARCHAR
);

CREATE TABLE IF NOT EXISTS eq_index_member (
    vintage_id  VARCHAR,
    as_of       DATE,
    index_code  VARCHAR,               -- 'nk225'
    sec_code    VARCHAR,
    name_ja     VARCHAR,
    nk_industry VARCHAR,
    nk_sector   VARCHAR,
    weight_pct  DOUBLE
);

-- The watermark table the other extractors write through extract.record_run().
-- That helper opens its own connection, and DuckDB allows one writer, so this
-- extractor declares the table itself and writes it on the connection it
-- already holds. Same shape, same primary key.
CREATE TABLE IF NOT EXISTS eq_extract_runs (
    extractor VARCHAR PRIMARY KEY,
    through_date DATE,
    docs_seen BIGINT,
    parser_version VARCHAR,
    ran_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS eq_class_code ON eq_classification (sec_code);
CREATE INDEX IF NOT EXISTS eq_class_asof ON eq_classification (as_of);
CREATE INDEX IF NOT EXISTS eq_class_size ON eq_classification (size_code);
CREATE INDEX IF NOT EXISTS eq_index_code ON eq_index_member (sec_code);
CREATE INDEX IF NOT EXISTS eq_index_asof ON eq_index_member (index_code, as_of);
"""


def vintage_id(source, as_of, sha):
    return "%s-%s-%s" % (source, as_of.strftime("%Y%m%d"), sha[:12])


def already_stored(con, vid):
    return con.execute("SELECT 1 FROM eq_class_vintages WHERE vintage_id = ?",
                       [vid]).fetchone() is not None


def store(con, source, as_of, sha, rows, public, url, raw_path, table, columns):
    u"""Insert one vintage, or refuse.

    A vintage is its bytes: the same file read twice is the same vintage and
    the second read stores nothing. A revised file at the same effective date
    hashes differently, so it lands beside the first rather than over it —
    what was served on the day it was served remains recoverable, which is the
    entire reason for keeping this.
    """
    vid = vintage_id(source, as_of, sha)
    if already_stored(con, vid):
        return vid, 0
    con.execute("BEGIN")
    try:
        con.executemany(
            "INSERT INTO %s (vintage_id, as_of, %s) VALUES (?, ?, %s)"
            % (table, ", ".join(columns), ", ".join("?" * len(columns))),
            [[vid, as_of] + [r.get(c) for c in columns] for r in rows])
        con.execute(
            "INSERT INTO eq_class_vintages (vintage_id, source, as_of, sha256,"
            " row_count, public, url, raw_path, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [vid, source, as_of, sha, len(rows), public, url, raw_path,
             datetime.datetime.utcnow()])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return vid, len(rows)


JPX_COLUMNS = ["sec_code", "name_ja", "segment_ja", "segment", "domestic",
               "ind33_code", "ind33_name", "ind17_code", "ind17_name",
               "size_code", "size_name"]
NK_COLUMNS = ["index_code", "sec_code", "name_ja", "nk_industry", "nk_sector",
              "weight_pct"]


# --------------------------------------------------------------- main --------

def do_jpx(con, args):
    raw = fetch(JPX_URL)
    as_of, rows = parse_jpx(raw)
    bands = check_jpx(rows)
    sha, path = archive("jpx-listed", raw, "xlsx")
    vid, n = store(con, "jpx-listed", as_of, sha, rows, True, JPX_URL,
                   os.path.basename(path), "eq_classification", JPX_COLUMNS)
    print("jpx-listed  %s  %s  %s"
          % (as_of, vid, "stored %d issues" % n if n else "unchanged"))
    print("            TOPIX: " + ", ".join(
        "%s %d" % (k, bands[k]) for k in
        ("core30", "large70", "mid400", "small1", "small2")))
    return as_of


def do_nikkei(con, args):
    raw = fetch(NIKKEI_URL)
    as_of, rows = parse_nikkei(raw)
    total = check_nikkei(rows)
    for r in rows:
        r["index_code"] = "nk225"
    sha, path = archive("nikkei-225", raw, "csv")
    vid, n = store(con, "nikkei-225", as_of, sha, rows, False, NIKKEI_URL,
                   os.path.basename(path), "eq_index_member", NK_COLUMNS)
    print("nikkei-225  %s  %s  %s  (weights sum %.4f%%)"
          % (as_of, vid, "stored %d members" % n if n else "unchanged", total))
    return as_of


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--skip-nikkei", action="store_true",
                    help="JPX only; the public half of the classification")
    ap.add_argument("--skip-jpx", action="store_true")
    # The nightly refresh passes these to every extractor. This one reads two
    # small files over HTTP and has no archive to walk, so they mean nothing
    # here — accepted and ignored so the runner stays uniform.
    ap.add_argument("--source", default="local")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--new-only", action="store_true")
    ap.add_argument("--no-compact", action="store_true")
    args = ap.parse_args()

    con = duckdb.connect(args.db)
    con.execute(SCHEMA_SQL)

    # Each source stands alone: Nikkei being unreachable must not cost us the
    # JPX vintage, and neither failure may be fatal to the refresh that calls
    # this (start.sh must always reach uvicorn).
    newest, failed = None, 0
    for name, fn, skip in (("jpx-listed", do_jpx, args.skip_jpx),
                           ("nikkei-225", do_nikkei, args.skip_nikkei)):
        if skip:
            print("%s  skipped" % name)
            continue
        try:
            as_of = fn(con, args)
            newest = max(newest, as_of) if newest else as_of
        except SourceError as e:
            failed += 1
            print("%s  REJECTED: %s" % (name, e))
        except Exception as e:                                    # noqa: BLE001
            failed += 1
            print("%s  FAILED: %s: %s" % (name, type(e).__name__, str(e)[:200]))

    # Only ever stamped after a source was actually read: a run in which both
    # publishers were unreachable must leave the watermark where it was, so
    # /catalog/health reports the classification going stale instead of
    # reporting a fresh run over unchanged data.
    if newest:
        con.execute(
            "INSERT OR REPLACE INTO eq_extract_runs (extractor, through_date,"
            " docs_seen, parser_version, ran_at) VALUES (?, ?, ?, ?, ?)",
            ["classification", newest,
             con.execute("SELECT count(*) FROM eq_classification").fetchone()[0],
             PARSER_VERSION, datetime.datetime.utcnow()])
    con.close()
    return 1 if failed and newest is None else 0


if __name__ == "__main__":
    sys.exit(main())
