# -*- coding: utf-8 -*-
"""Backfill the real-time history of Japan's quarterly GDP estimates.

`gdp-jp` accumulates a vintage every time we ingest it, which started on
13 September 2026. This module loads what came before: the 134 estimates the
Cabinet Office published between August 2002 and March 2019, each one as the
numbers stood on the morning it was released.

Usage:  python -m app.gdp_vintages plan     # what would be loaded, and from where
        python -m app.gdp_vintages load     # fetch, archive and record it
        python -m app.gdp_vintages load --limit 4

Why this is not an adapter
--------------------------
An adapter publishes a dataset's *live* release: it replaces `observations`
and marks the previous release superseded. Loading a 2011 estimate through
that path would overwrite today's numbers with fifteen-year-old ones. So
this module writes to `releases`, `source_artifacts` and the append-only
`observation_vintages` and **never touches `observations`**. Its releases
carry `status='archived'`: they are history, never the live answer.

Where the dates come from, and why they can be trusted
------------------------------------------------------
A vintage is worthless unless its date is right, and e-Stat does not carry
one: every archived GDP table reports `OPEN_DATE` 2020-04-01, the day the
Cabinet Office loaded the lot. Dating them by the usual rule of thumb —
first estimate about six weeks after the quarter, second about ten — would
have put releases on the wrong side of a month end and quietly corrupted
every `?as_of=` answer in the archive's span.

Two independent sources are used instead, and they check each other:

1. **The Cabinet Office's own release calendar**, published as XML at
   `https://www.esri.cao.go.jp/jp/sna/e-stat_sna.xml`, which gives the date
   and time (08:50 JST) of each estimate from 2009 Q3 onward.
2. **The statistics-list page of each individual release**, which prints its
   own publication date and reaches back to 2002.

On the 24 releases where both were checked, they agreed 24 times and
disagreed none. That is what justifies using the page date for the earlier
releases the calendar does not reach: the method was verified against the
agency's own record before being relied on. Where both exist they must still
agree at load time — a disagreement fails the release rather than picking
one.

What a loaded vintage contains
------------------------------
The three seasonally adjusted expenditure tables of that release — real
levels, nominal levels and the deflator — the same three the live adapter
carries, matched to the same series by the Japanese line name the Cabinet
Office publishes. Two lines were renamed at the 2016 changeover to the 2008
SNA (民間在庫品増加 -> 民間在庫変動 and its public twin); both names map to
the one series, so a stock-building series is continuous across the break
rather than splitting in two.

**Levels are not comparable across vintages, and that is the point.** Each
release is on the price base and the SNA vintage in force when it was
published: real GDP appears in 1995, 2000, 2005, 2011 and 2020 chained
prices at different dates, and nominal GDP jumps about ¥30tn at the
December 2016 changeover. A difference between two vintages is therefore a
rebasing, a benchmark revision or a data revision, and reading it as one
kind when it is another is the mistake this history exists to make
visible. Each release records its own base in `validation`, and the API
serves it.
"""
import argparse
import datetime
import hashlib
import io
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

from . import db, env

env.load()

from .adapters import estat_api, estat_gdp                      # noqa: E402

DATASET = "gdp-jp"

# The archive is its own source: a different set of e-Stat tables from the
# live one, retrieved differently, and a reader looking at a 2011 vintage
# should see where it actually came from.
SOURCE = {
    "source_id": "e-stat:qe-gdp-archive",
    "name": ("Quarterly Estimates of GDP — archived releases "
             "(first and second preliminary, as published)"),
    "name_ja": "四半期別ＧＤＰ速報 過去の値（1次速報値・2次速報値）",
    "url": "https://www.e-stat.go.jp/stat-search?page=1&toukei=00100409",
    "license_note": (
        "e-Stat terms of use: reuse permitted with attribution to the Cabinet "
        "Office. Retrieved through the e-Stat API, which requires a free "
        "application ID. Publication dates are from the Cabinet Office's own "
        "release calendar and release pages."
    ),
}

CALENDAR_URL = "https://www.esri.cao.go.jp/jp/sna/e-stat_sna.xml"
RELEASE_PAGE = ("https://www.esri.cao.go.jp/jp/sna/data/data_list/sokuhou/"
                "files/%(year)d/qe%(yy)02d%(q)d%(suffix)s/gdemenuja.html")
USER_AGENT = "ObservatoryIngest/0.1 (data pipeline; contact: repo owner)"

# The two estimates of every quarter. The Cabinet Office's own names, because
# they are what the calendar and the e-Stat listing both use.
ROUNDS = [("1次速報", "1次速報値", ""), ("2次速報", "2次速報値", "_2")]

# The tables to take from each release, by the prefix of the title the Cabinet
# Office gives them. Note the DASH: the archived deflator tables are titled
# デフレータ― with U+2015, not デフレーター — searching for the modern spelling
# finds nothing at all.
#
# The two level tables are required. **The seasonally adjusted deflator is
# not, because before 2009 it did not exist**: those releases published a
# quarterly deflator on the original series only, and no amount of fetching
# will produce one that was never issued. A release is loaded with the bases
# it actually carried and records which those were, rather than being dropped
# because a later convention is missing from it.
REQUIRED = [
    ("real_sa", "国内総生産（支出側）及び各需要項目 実質季節調整系列　実額"),
    ("nominal_sa", "国内総生産（支出側）及び各需要項目 名目季節調整系列　実額"),
]
OPTIONAL = [
    ("deflator_sa", "国内総生産（支出側）及び各需要項目 四半期デフレータ―季節調整系列　実数"),
]
WANTED = REQUIRED + OPTIONAL

# Line names that changed without the meaning changing, so each maps onto the
# series the live table uses. Every one was checked against the release it
# appears in — a rename is assumed for none of them:
#
#   国内総支出        "gross domestic expenditure", the headline's name until
#                     the 2004 tables began calling the same total 国内総生産
#                     (支出側), "GDP, expenditure side".
#   家計最終消費      the household line's wording before 2005, and the
#                     imputed-rent line beneath it, which reached its present
#                     wording in two steps. Every name every archived release
#                     uses was enumerated before this list was written: a
#                     sweep of all 342 tables found exactly these and nothing
#                     else, so no release is loaded on a guess.
#   民間/公的在庫品増加 stock-building, renamed 在庫変動 at the December 2016
#                     move to the 2008 SNA.
#
# Anything NOT listed here and not in the live table fails the release. A GDP
# line served under a guessed English name would be worse than a gap.
ALIASES = {
    "国内総支出": "国内総生産(支出側)",
    "民間最終消費支出_家計最終消費": "民間最終消費支出_家計最終消費支出",
    "民間最終消費支出_家計最終消費_除く帰属家賃":
        "民間最終消費支出_家計最終消費支出_除く持ち家の帰属家賃",
    "民間最終消費支出_家計最終消費支出_除く帰属家賃":
        "民間最終消費支出_家計最終消費支出_除く持ち家の帰属家賃",
    "民間在庫品増加": "民間在庫変動",
    "公的在庫品増加": "公的在庫変動",
}

# Lines that exist ONLY in old vintages and are NOT renames of anything the
# live table carries. FISIM is the value of the banking services a customer
# gets without paying a fee for them, which the 2008 SNA brought inside GDP;
# through the 2016 changeover the Cabinet Office published "excluding FISIM"
# versions of four lines beside the new ones, so a reader could see the size
# of the change. They are separate measures — aliasing them onto the main
# lines would file two different numbers under one series — so they get
# series of their own, created inactive because nothing publishes them now.
#
#   (published name, series key, English, Japanese for the series row)
ARCHIVE_CONCEPTS = [
    ("<参考>国内総生産(支出側)(除FISIM)", "gdp_ex_fisim",
     "Gross domestic product (expenditure side), excluding FISIM",
     "国内総生産(支出側)(除FISIM)"),
    ("<参考>家計最終消費支出(除FISIM)", "household_consumption_ex_fisim",
     "Household final consumption expenditure, excluding FISIM",
     "家計最終消費支出(除FISIM)"),
    ("<参考>財貨・サービス_輸出(除FISIM)", "exports_ex_fisim",
     "Exports of goods and services, excluding FISIM",
     "財貨・サービス_輸出(除FISIM)"),
    ("<参考>財貨・サービス_輸入(除FISIM)", "imports_ex_fisim",
     "Imports of goods and services, excluding FISIM",
     "財貨・サービス_輸入(除FISIM)"),
]
ARCHIVE_BY_NAME = dict((c[0], c) for c in ARCHIVE_CONCEPTS)
ARCHIVE_BY_KEY = dict((c[1], c) for c in ARCHIVE_CONCEPTS)


def concept_key(published_name):
    """The series key for a published line name, or None if unrecognised."""
    name = ALIASES.get(published_name, published_name)
    concept = estat_gdp.CONCEPT_BY_NAME.get(name)
    if concept is not None:
        return concept[1]
    archived = ARCHIVE_BY_NAME.get(name)
    return archived[1] if archived else None

# The price or index base, as the Cabinet Office writes it in the title:
# "（単位:2011暦年連鎖価格、10億円）", "（2011暦年＝100）", "（単位:1995暦年価格、10億円）".
BASE_RE = re.compile(r"[（(]\s*(?:単位[:：])?\s*([0-9]{4}暦年[^、）)]*)")
DATE_RE = re.compile(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日")
QUARTERS = {"1-3月期": 1, "4-6月期": 2, "7-9月期": 3, "10-12月期": 4}
ERA = {"平成": 1988, "令和": 2018}

# The Cabinet Office releases GDP at 08:50 Japan time, and the stamp is stored
# as that WALL CLOCK, not converted to UTC.
#
# Converting looks tidier and is wrong here. `as_of=D` means "what was public
# by the end of D", and a date is compared against the stored stamp. In UTC,
# 08:50 JST on the 12th is 23:50 on the 11th — so `as_of=2009-03-11` would
# return an estimate that nobody in Japan could read until the following
# morning. A nine-hour look-ahead is small enough to go unnoticed and fatal to
# the one job this history has. Japan is the market, so Japan time is the
# clock, and the API says so.
RELEASE_HOUR_JST = 8
RELEASE_MINUTE_JST = 50


class LoadError(Exception):
    pass


# --- dates -------------------------------------------------------------------

def _get(url, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _jp_year(name):
    m = re.match(r"(平成|令和)(\d+|元)年", name)
    if m:
        n = 1 if m.group(2) == "元" else int(m.group(2))
        return ERA[m.group(1)] + n
    m = re.match(r"(\d{4})年", name)
    if not m:
        raise LoadError("cannot read a year from %r" % name)
    return int(m.group(1))


def _quarter_of(name):
    for suffix, q in QUARTERS.items():
        if name.endswith(suffix):
            return _jp_year(name), q
    return None


def calendar():
    """{(year, quarter, round): date} from the Cabinet Office's XML calendar.

    Authoritative but partial: it starts at 2009 Q3. Missing entries are not
    an error — the release page carries the date for the earlier ones.
    """
    root = ET.fromstring(_get(CALENDAR_URL))
    out = {}
    for c1 in root.iter("class_1"):
        if c1.get("name") != "四半期別ＧＤＰ速報":
            continue
        for c2 in c1.iter("class_2"):
            quarter = _quarter_of(c2.get("name") or "")
            if not quarter:
                continue
            for c3 in c2.iter("class_3"):
                if c3.get("name") not in (r[0] for r in ROUNDS):
                    continue
                for c5 in c3.iter("class_5"):
                    out[(quarter[0], quarter[1], c3.get("name"))] = datetime.date(
                        int(c5.findtext("release_year")),
                        int(c5.findtext("release_month")),
                        int(c5.findtext("release_day")))
    if len(out) < 100:
        raise LoadError("the release calendar returned only %d entries" % len(out))
    return out


def page_date(year, quarter, suffix):
    """The publication date printed on that release's own statistics-list page."""
    url = RELEASE_PAGE % {"year": year, "yy": year % 100, "q": quarter, "suffix": suffix}
    try:
        html = _get(url).decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001 - reported, not raised
        return None, url, "unreachable: %s" % exc.__class__.__name__
    m = DATE_RE.search(html)
    if not m:
        return None, url, "no date printed on the page"
    return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), url, None


def published_at(year, quarter, round_name, suffix, cal):
    """The verified publication timestamp, or an explanation of why there is none.

    Both sources are consulted wherever both exist and must agree. A release
    with one source is accepted on it; a release with none is refused. The
    stamp is 08:50 on that day in Japan, the hour the Cabinet Office releases
    GDP, kept in Japan time — see RELEASE_HOUR_JST.
    """
    from_cal = cal.get((year, quarter, round_name))
    from_page, url, why = page_date(year, quarter, suffix)
    if from_cal and from_page and from_cal != from_page:
        raise LoadError(
            "%d Q%d %s: the release calendar says %s and the release page says "
            "%s — refusing to guess which" % (year, quarter, round_name, from_cal, from_page))
    date = from_cal or from_page
    if date is None:
        return None, None, (why or "not in the release calendar")
    sources = [s for s, present in (("calendar", from_cal), ("release page", from_page)) if present]
    stamp = datetime.datetime(date.year, date.month, date.day,
                              RELEASE_HOUR_JST, RELEASE_MINUTE_JST)
    return stamp, {"date": date.isoformat(), "sources": sources, "page": url}, None


# --- which tables ------------------------------------------------------------

def _title(table):
    title = table.get("TITLE")
    return title.get("$") if isinstance(title, dict) else (title or "")


def archived_tables():
    """{(year, quarter, round): {basis: (statsDataId, title)}} from e-Stat.

    One listing call, walked once. A release missing any of the three tables
    is reported by plan() and skipped by load() rather than half-loaded.
    """
    pages = []
    start = None
    while True:
        params = {"statsCode": "00100409", "searchWord": "四半期別ＧＤＰ速報",
                  "limit": estat_api.PAGE_LIMIT}
        if start is not None:
            params["startPosition"] = start
        payload = estat_api.call("getStatsList", **params)
        info = payload["GET_STATS_LIST"]["DATALIST_INF"]
        tables = info.get("TABLE_INF", [])
        pages.extend(tables if isinstance(tables, list) else [tables])
        nxt = payload["GET_STATS_LIST"].get("RESULT_INF", {}).get("NEXT_KEY")
        if not nxt:
            break
        start = nxt

    out = {}
    for table in pages:
        name = table.get("STATISTICS_NAME") or ""
        if "過去の値" not in name:
            continue
        round_name = None
        for short, listed, _suffix in ROUNDS:
            if listed in name:
                round_name = short
        if round_name is None:
            continue
        survey = str(table.get("SURVEY_DATE") or "")
        if len(survey) != 13:                       # "201810-201812"
            continue
        year, month = int(survey[:4]), int(survey[4:6])
        quarter = (month - 1) // 3 + 1
        title = _title(table)
        for basis, prefix in WANTED:
            if title.startswith(prefix):
                out.setdefault((year, quarter, round_name), {})[basis] = (
                    table["@id"], title)
    return out


def _base_of(title):
    m = BASE_RE.search(title)
    return m.group(1).strip() if m else None


# --- parsing -----------------------------------------------------------------

def parse_release(doc):
    """[(series_code, period, value)] from one release's three tables.

    Lines are matched by the Japanese name the Cabinet Office publishes, the
    same rule the live adapter uses, because the numeric codes are renumbered
    between tables and between eras. A name this module does not recognise
    fails the release: a GDP line served under a guessed English name is
    worse than a gap.
    """
    rows = []
    bases = {}
    for basis, entry in sorted(doc.items()):
        if basis not in ("real_sa", "nominal_sa", "deflator_sa"):
            continue
        bases[basis] = entry.get("base")
        seen = set()
        for page in entry["pages"]:
            data = page["GET_STATS_DATA"]["STATISTICAL_DATA"]
            names = estat_api.class_values(data, "cat01")
            times = estat_api.class_values(data, "time")
            values = data["DATA_INF"]["VALUE"]
            if isinstance(values, dict):
                values = [values]
            for v in values:
                raw_name = names.get(v["@cat01"], "")
                key = concept_key(raw_name)
                if key is None:
                    raise LoadError(
                        "%s table carries a line named %r, which this loader "
                        "does not know" % (basis, raw_name))
                value = estat_gdp._value(v.get("$"))
                if value is None:
                    continue
                period = estat_gdp._quarter_start(v["@time"], times[v["@time"]])
                seen.add(key)
                rows.append(("%s.%s" % (key, basis), period, value))
        if "gdp" not in seen:
            raise LoadError("%s table carries no GDP line" % basis)
    return rows, bases


# --- loading -----------------------------------------------------------------

def _source_row(con):
    if con.execute("SELECT 1 FROM sources WHERE source_id=?",
                   [SOURCE["source_id"]]).fetchone():
        return
    con.execute("INSERT INTO sources VALUES (?,?,?,?,?,?)",
                [SOURCE["source_id"], DATASET, SOURCE["name"], SOURCE["name_ja"],
                 SOURCE["url"], SOURCE["license_note"]])


def _series_ids(con, codes):
    """{code: series_id}, creating any series that only old vintages carry.

    A line the Cabinet Office has stopped publishing still belongs in the
    history that recorded it. Such a series is created inactive — it has no
    live observation and must never appear in a current listing — rather than
    dropped, which would lose the only copy of it we will ever have.
    """
    known = dict(con.execute(
        "SELECT code, series_id FROM series WHERE dataset=?", [DATASET]).fetchall())
    created = []
    for code in sorted(set(codes) - set(known)):
        key, basis = code.rsplit(".", 1)
        concept = estat_gdp.CONCEPT_BY_KEY.get(key)
        if concept is not None:
            name_en, name_ja = concept[2], concept[3].replace("<参考>", "")
            order = estat_gdp.CONCEPT_ORDER[key] * 10
        elif key in ARCHIVE_BY_KEY:
            archived = ARCHIVE_BY_KEY[key]
            name_en, name_ja = archived[2], archived[3]
            # After every live concept, so an archive-only line never sorts
            # into the middle of the expenditure account.
            order = 1000 + list(ARCHIVE_BY_KEY).index(key) * 10
        else:
            raise LoadError("no concept for series code %r" % code)
        series_id = con.execute(
            "INSERT INTO series (dataset, code, name_en, name_ja, unit, "
            "weight_per_10000, sort_order, active) VALUES (?,?,?,?,?,?,?,FALSE) "
            "RETURNING series_id",
            [DATASET, code,
             "%s — %s" % (name_en, estat_gdp.BASIS_LABEL[basis]),
             "%s %s" % (name_ja, estat_gdp._basis_ja(basis)),
             estat_gdp.BASIS_UNIT[basis], None, order]).fetchone()[0]
        known[code] = series_id
        created.append(code)
    return known, created


def _loaded(con):
    """The (year, quarter, round) already recorded, so a run can be resumed."""
    rows = con.execute(
        "SELECT label FROM releases WHERE dataset=? AND status='archived'",
        [DATASET]).fetchall()
    out = set()
    for (label,) in rows:
        m = re.match(r"(\d{4}) Q(\d) (\S+)", label or "")
        if m:
            out.add((int(m.group(1)), int(m.group(2)), m.group(3)))
    return out


def plan(limit=None, skip=()):
    """What could be loaded, and on whose authority each date rests.

    `skip` is the set already recorded. Releases in it are passed over before
    their date is looked up, which is what makes a second run cheap: verifying
    134 dates means 134 page fetches, and a re-run that has nothing to do
    should not pay for them.
    """
    cal = calendar()
    tables = archived_tables()
    print("release calendar: %d entries; archived releases on e-Stat: %d"
          % (len(cal), len(tables)))
    ready, skipped, partial, already = [], [], 0, 0
    for key in sorted(tables):
        year, quarter, round_name = key
        if key in skip:
            already += 1
            continue
        suffix = dict((r[0], r[2]) for r in ROUNDS)[round_name]
        found = tables[key]
        missing = [b for b, _p in REQUIRED if b not in found]
        if missing:
            skipped.append((key, "missing tables: %s" % ", ".join(missing)))
            continue
        stamp, evidence, why = published_at(year, quarter, round_name, suffix, cal)
        if stamp is None:
            skipped.append((key, "no verified publication date (%s)" % why))
            continue
        if any(b not in found for b, _p in OPTIONAL):
            partial += 1
        ready.append((key, stamp, evidence, found))
        if limit and len(ready) >= limit:
            break
    print("loadable: %d   already recorded: %d   skipped: %d   (of the loadable, "
          "%d published no seasonally adjusted deflator)"
          % (len(ready), already, len(skipped), partial))
    for key, why in skipped[:10]:
        print("   skip %d Q%d %s — %s" % (key[0], key[1], key[2], why))
    if ready:
        first, last = ready[0], ready[-1]
        print("   first: %d Q%d %s published %s (%s)"
              % (first[0][0], first[0][1], first[0][2], first[2]["date"],
                 " + ".join(first[2]["sources"])))
        print("   last:  %d Q%d %s published %s (%s)"
              % (last[0][0], last[0][1], last[0][2], last[2]["date"],
                 " + ".join(last[2]["sources"])))
    return ready


def load(limit=None, pause=0.4):
    # What is already recorded is read first, so a re-run skips those releases
    # before looking their dates up again. Safe to run repeatedly.
    con = db.connect()
    try:
        done = _loaded(con)
    finally:
        con.close()
    ready = plan(limit, skip=done)
    if not ready:
        print("nothing to load")
        return 0
    con = db.connect()
    try:
        _source_row(con)
        db.RAW_DIR.mkdir(parents=True, exist_ok=True)
        loaded = 0
        for key, stamp, evidence, found in ready:
            year, quarter, round_name = key
            label = "%d Q%d %s" % (year, quarter, round_name)

            doc = {}
            for basis, _prefix in WANTED:
                if basis not in found:
                    continue                      # a basis this release never published
                stats_id, title = found[basis]
                doc[basis] = {
                    "statsDataId": stats_id,
                    "title": title,
                    "base": _base_of(title),
                    "pages": estat_api.get_stats_data(stats_id),
                }
                time.sleep(pause)
            raw = json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
            sha = hashlib.sha256(raw).hexdigest()
            rows, bases = parse_release(doc)
            if not rows:
                raise LoadError("%s parsed to nothing" % label)

            path = db.RAW_DIR / ("gdp-jp-archive-%d-Q%d-%s-%s.json"
                                 % (year, quarter, round_name, sha[:12]))
            path.write_bytes(raw)

            con.execute("BEGIN")
            artifact_id = con.execute(
                "INSERT INTO source_artifacts (source_id, url, retrieved_at, sha256, "
                "path, bytes) VALUES (?,?,?,?,?,?) RETURNING artifact_id",
                [SOURCE["source_id"],
                 "https://www.e-stat.go.jp/dbview?sid=%s" % found["real_sa"][0],
                 datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
                 sha, str(path), len(raw)]).fetchone()[0]

            ids, created = _series_ids(con, [r[0] for r in rows])
            latest = max(r[1] for r in rows)
            summary = {
                "series": len(set(r[0] for r in rows)),
                "observations": len(rows),
                "latest_period": latest.isoformat(),
                "published_at": evidence["date"],
                "date_sources": evidence["sources"],
                "date_evidence_url": evidence["page"],
                "bases": bases,
                "series_created": created,
            }
            release_id = con.execute(
                "INSERT INTO releases (dataset, artifact_id, label, latest_period, "
                "ingested_at, published_at, status, validation) "
                "VALUES (?,?,?,?,?,?,?,?) RETURNING release_id",
                [DATASET, artifact_id, label, latest,
                 datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
                 stamp, "archived", json.dumps(summary, ensure_ascii=False)]).fetchone()[0]

            # Change-only, exactly as ingest writes it: a row is recorded for a
            # (series, period) this release introduces or changes, never for one
            # it merely restates. "In force" means the newest recorded value at
            # or before this release's own publication date, so a resumed run
            # and a run in one pass record the same history.
            prior = con.execute(
                "SELECT series_id, period, value FROM ("
                "  SELECT v.series_id, v.period, v.value,"
                "         row_number() OVER (PARTITION BY v.series_id, v.period"
                "                            ORDER BY COALESCE(r.published_at, r.ingested_at) DESC,"
                "                                     v.release_id DESC) AS rn"
                "  FROM observation_vintages v JOIN series s USING(series_id)"
                "  JOIN releases r USING(release_id)"
                "  WHERE s.dataset = ? AND COALESCE(r.published_at, r.ingested_at) <= ?"
                ") WHERE rn = 1", [DATASET, stamp]).fetchall()
            in_force = dict(((sid, period), value) for sid, period, value in prior)

            changed = []
            for code, period, value in rows:
                sid = ids[code]
                if in_force.get((sid, period)) != value:
                    changed.append((sid, period, value, release_id))
            con.executemany(
                "INSERT INTO observation_vintages (series_id, period, value, release_id) "
                "VALUES (?,?,?,?) ON CONFLICT DO NOTHING", changed)
            con.execute("COMMIT")
            loaded += 1
            print("%s  published %s  %5d values, %5d recorded as new or revised%s"
                  % (label, evidence["date"], len(rows), len(changed),
                     ("  [+%d series]" % len(created)) if created else ""))
        print("loaded %d archived release(s)" % loaded)
    finally:
        con.close()
    return 0


def reindex():
    """Rebuild the archived releases' vintage rows from the archived files.

    The releases, their dates and their artifacts are untouched; only the
    change-only rows in `observation_vintages` are recomputed, in publication
    order, from the JSON already on disk. No network call is made — the
    artifacts ARE the evidence, which is why they are kept.

    This exists because a bad predicate can delete rows that carry
    information, and when that happens the archive has to be reconstructible
    without asking e-Stat for seventeen years of tables a second time.
    """
    con = db.connect()
    try:
        releases = con.execute(
            "SELECT r.release_id, r.label, r.published_at, a.path "
            "FROM releases r JOIN source_artifacts a USING(artifact_id) "
            "WHERE r.dataset=? AND r.status='archived' "
            "ORDER BY r.published_at, r.release_id", [DATASET]).fetchall()
        if not releases:
            print("no archived releases to rebuild")
            return 0
        ids = dict(con.execute(
            "SELECT code, series_id FROM series WHERE dataset=?", [DATASET]).fetchall())
        con.execute("BEGIN")
        removed = con.execute(
            "DELETE FROM observation_vintages WHERE release_id IN ("
            "  SELECT release_id FROM releases WHERE dataset=? AND status='archived')"
            " RETURNING 1", [DATASET]).fetchall()
        print("cleared %d archived vintage rows; rebuilding %d releases"
              % (len(removed), len(releases)))
        # The value in force from releases that are NOT archived — today's
        # live release — keyed the same way, so the rebuild sees exactly what
        # a fresh load would have seen.
        in_force = {}
        total = 0
        for release_id, label, stamp, path in releases:
            doc = json.loads(io.open(path, encoding="utf-8").read())
            rows, _bases = parse_release(doc)
            changed = []
            for code, period, value in rows:
                sid = ids.get(code)
                if sid is None:
                    raise LoadError("series %r vanished; rebuild needs it" % code)
                if in_force.get((sid, period)) != value:
                    changed.append((sid, period, value, release_id))
                    in_force[(sid, period)] = value
            con.executemany(
                "INSERT INTO observation_vintages (series_id, period, value, release_id) "
                "VALUES (?,?,?,?) ON CONFLICT DO NOTHING", changed)
            total += len(changed)
        con.execute("COMMIT")
        print("rebuilt %d vintage rows across %d archived releases" % (total, len(releases)))
    finally:
        con.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("plan", "load", "reindex"))
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after this many releases (for a trial run)")
    args = ap.parse_args()
    try:
        if args.command == "plan":
            plan(args.limit)
            return 0
        if args.command == "reindex":
            return reindex()
        return load(args.limit)
    except LoadError as exc:
        print("FAILED: %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
