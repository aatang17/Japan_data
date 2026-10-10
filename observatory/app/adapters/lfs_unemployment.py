"""Adapter: Labour Force Survey — unemployment and employment, Japan.

Source: 総務省統計局 労働力調査 基本集計, long-run table 1 a-1 「主要項目
（労働力人口・就業者・雇用者・完全失業者・非労働力人口・完全失業率）」 — the
whole-Japan monthly results, seasonally adjusted from January 1953 and
original (not adjusted) from July 1972, read from the Excel file e-Stat
serves under the fixed statInfId 000031831358. The Bureau replaces that file
in place on every release (the last Friday or so of the following month), so
the id does not move; the API's file catalog confirms it is the current one.

This is the unemployment rate the press quotes — 完全失業率, seasonally
adjusted — and the five headcounts it is built from, for both sexes, men and
women.

Facts the parser and the gates rely on:

- Headcounts are in 万人 (ten thousand persons) exactly as published and are
  stored in that unit (``persons_10k``). Nothing is rescaled: 177 means
  1.77 million people.
- The rate is published to one decimal; Excel stores some as binary noise
  (1.1000000000000001), so every value is rounded to the one decimal the
  Bureau prints.
- The seasonally adjusted sheet runs from 1953; months marked ``*`` in it
  (1953–1973) exclude Okinawa, which the survey covered from July 1972. The
  original-series sheet starts in July 1972 — the months before are ``…``,
  which is missing, never zero. A third sheet of pre-1974 figures without
  Okinawa and the seasonal-factor sheet are not taken.
- March–August 2011 are the Bureau's supplementary estimates for the whole
  country (the survey could not be run in the three prefectures the
  earthquake hit); the Bureau publishes them in the series and so do we.
- Seasonal adjustment is re-estimated each January and the last ten years of
  adjusted values are revised then: each revision is a new vintage here.
- The year column alternates an era label (「令和 8年」) on January with a
  Western year (「2026」) on February. Years are assigned by counting months
  and gated against every Western year the sheet prints.

Levels and rates, not indices: ``weight_per_10000`` stays NULL.
"""
import datetime

from . import estat_csv, xlsx


class ValidationError(Exception):
    pass


STAT_INF_ID = "000031831358"

DATASET = {
    "slug": "unemployment-jp",
    "title": "Labour Force Survey — Unemployment and Employment, Japan (Statistics Bureau)",
    "country": "Japan",
    "agency": "Statistics Bureau of Japan",
    "agency_ja": "総務省統計局",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Japan's unemployment rate and the headcounts behind it — labour force, "
        "employed, employees, unemployed and people outside the labour force — "
        "for both sexes, men and women, from the Statistics Bureau's Labour Force "
        "Survey. Seasonally adjusted monthly from 1953, original series from July "
        "1972. Headcounts in units of ten thousand persons, exactly as published."
    ),
}

SOURCE = {
    "source_id": "e-stat:" + STAT_INF_ID,
    "name": ("Labour Force Survey, Basic Tabulation — historical data 1 a-1, "
             "major items, whole Japan, monthly"),
    "name_ja": "労働力調査 基本集計 長期時系列表１ ａ－１ 主要項目（全国、月別結果）",
    "url": "https://www.stat.go.jp/data/roudou/longtime/03roudou.html",
    "license_note": (
        "e-Stat / Statistics Bureau terms of use: reuse permitted with attribution "
        "to the Statistics Bureau of Japan."
    ),
}

DOWNLOAD_URL = ("https://www.e-stat.go.jp/stat-search/file-download?statInfId="
                + STAT_INF_ID + "&fileKind=0")
RAW_SUFFIX = ".xlsx"

# (column of the both-sexes cell, key, English, Japanese header, unit, kind).
# Each measure spans three columns: both sexes, men, women.
MEASURES = [
    ("E", "labour_force", "Labour force", "労働力人口", "persons_10k", "stock"),
    ("H", "employed", "Employed persons", "就業者", "persons_10k", "stock"),
    ("K", "employees", "Employees", "雇用者", "persons_10k", "stock"),
    ("N", "unemployed", "Unemployed persons", "完全失業者", "persons_10k", "stock"),
    ("Q", "not_in_labour_force", "Not in labour force", "非労働力人口", "persons_10k", "stock"),
    ("T", "unemployment_rate", "Unemployment rate", "完全失業率（％）", "percent", "rate"),
]
SEXES = [("total", "both sexes", "男女計"), ("male", "men", "男"), ("female", "women", "女")]
# (sheet, key, English, the header it must carry)
SHEETS = [
    ("季節調整値", "sa", "seasonally adjusted", "季節調整値"),
    ("原数値", "nsa", "original series", "原数値"),
]


def _shift(col, n):
    """'E' shifted n columns to the right; single letters only here."""
    return chr(ord(col) + n)


def _code(adj, measure, sex):
    return "%s.%s.%s" % (adj, measure, sex)


# --- fetch ------------------------------------------------------------------

def fetch():
    raw = estat_csv.fetch_bytes(DOWNLOAD_URL)
    if raw[:2] != b"PK":
        raise ValidationError("the e-Stat file is not an .xlsx workbook "
                              "(got %r…)" % raw[:16])
    return raw


# --- parse ------------------------------------------------------------------

def _text(row, col):
    cell = row.get(col)
    return xlsx.cell_text(cell) if cell else ""


def _month(text):
    """'1月' / '１２月' -> 1..12, else None."""
    t = text.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if t.endswith("月") and t[:-1].isdigit() and 1 <= int(t[:-1]) <= 12:
        return int(t[:-1])
    return None


def _value(text):
    t = text.strip()
    if not t or t.startswith("…") or t in ("-", "－", "***"):
        return None
    # The 1953 Jan–Mar figures are bracketed and 2011's supplementary
    # estimates angle-bracketed in print; a cell holding the brackets as
    # text keeps the number.
    t = t.strip("()（）<>＜＞ ")
    try:
        return round(float(t.replace(",", "")), 1)
    except ValueError:
        raise ValidationError("unreadable value %r" % text)


def _check_header(name, rows, label):
    head = _text(rows.get(5, {}), "E")
    if label not in head:
        raise ValidationError("sheet %s: header %r does not say %s" % (name, head, label))
    if "万人" not in _text(rows.get(4, {}), "E"):
        raise ValidationError("sheet %s: headcounts are no longer in 万人" % name)
    for col, key, _en, ja, _u, _k in MEASURES:
        got = _text(rows.get(6, {}), col)
        if got != ja:
            raise ValidationError("sheet %s column %s: expected %r, found %r"
                                  % (name, col, ja, got))
        for i, (_s, _e, sex_ja) in enumerate(SEXES):
            got = _text(rows.get(8, {}), _shift(col, i))
            if got != sex_ja:
                raise ValidationError("sheet %s column %s: expected %r, found %r"
                                      % (name, _shift(col, i), sex_ja, got))


def _dated_rows(name, rows):
    """[(row, date)] for every month row, years counted from the first
    Western year printed and checked against every later one."""
    months = [(r, _month(_text(rows[r], "B"))) for r in sorted(rows) if r > 9]
    months = [(r, m) for r, m in months if m is not None]
    if not months or months[0][1] != 1:
        raise ValidationError("sheet %s does not start in January" % name)
    anchor = None
    for i, (r, m) in enumerate(months):
        a = _text(rows[r], "A").strip()
        if a.isdigit() and len(a) == 4:
            anchor = (i, int(a))
            break
    if anchor is None:
        raise ValidationError("sheet %s prints no Western year" % name)
    # Every row before the anchor is in the anchor's year (the anchor is the
    # February row of the first year).
    year = anchor[1]
    out = []
    prev = None
    for i, (r, m) in enumerate(months):
        if prev is not None:
            if m == 1 and prev == 12:
                year += 1
            elif m != prev + 1:
                raise ValidationError("sheet %s row %d: month %d follows %d"
                                      % (name, r, m, prev))
        prev = m
        a = _text(rows[r], "A").strip()
        if a.isdigit() and len(a) == 4 and int(a) != year:
            raise ValidationError("sheet %s row %d prints %s but counts as %d"
                                  % (name, r, a, year))
        out.append((r, datetime.date(year, m, 1)))
    return out


def parse(raw_bytes):
    try:
        sheets = xlsx.sheets(raw_bytes)
    except Exception as exc:
        raise ValidationError("not a readable workbook: %s" % exc)
    series, observations = [], []
    order = 0
    for sheet, adj, adj_en, label in SHEETS:
        if sheet not in sheets:
            raise ValidationError("workbook has no sheet %r (sheets: %s)"
                                  % (sheet, ", ".join(sheets)))
        rows = sheets[sheet]
        _check_header(sheet, rows, label)
        dated = _dated_rows(sheet, rows)
        for col, key, en, ja, unit, _kind in MEASURES:
            for i, (sex, sex_en, sex_ja) in enumerate(SEXES):
                code = _code(adj, key, sex)
                c = _shift(col, i)
                n = 0
                for r, period in dated:
                    v = _value(_text(rows[r], c))
                    if v is None:
                        continue
                    observations.append({"code": code, "period": period, "value": v})
                    n += 1
                if n:
                    series.append({
                        "code": code,
                        "name_en": "%s, %s, %s" % (en, sex_en, adj_en),
                        "name_ja": "%s %s %s" % (ja.replace("（％）", ""), sex_ja, label),
                        "unit": unit,
                        "weight_per_10000": None,
                        "sort_order": order,
                    })
                order += 1
    if not observations:
        raise ValidationError("no values parsed")
    return series, observations


# --- validate ---------------------------------------------------------------

STALE_AFTER_DAYS = 100    # a month is published ~4 weeks after it ends
SA_FROM = datetime.date(1953, 1, 1)
NSA_FROM = datetime.date(1972, 7, 1)
# The original series is published in whole 万人 from components that are
# themselves rounded, so an identity can miss by a unit or two.
IDENTITY_TOLERANCE = 2.0
# Except where the Bureau replaced the published figures with re-benchmarked
# "comparable time-series" values (its note 4: October 2005 to December 2021,
# after each census re-basing). Each cell there was re-estimated on its own,
# and the file misses by 3 to 5 in a dozen months of that window — never
# outside it. Measured on the 2026-10-02 file, not guessed.
REBENCHMARKED = (datetime.date(2005, 10, 1), datetime.date(2021, 12, 1))
REBENCHMARKED_TOLERANCE = 5.0


def _tolerance(period):
    if REBENCHMARKED[0] <= period <= REBENCHMARKED[1]:
        return REBENCHMARKED_TOLERANCE
    return IDENTITY_TOLERANCE
# The rate is computed by the Bureau from unrounded counts and printed to one
# decimal; recomputing it from rounded counts lands within this.
RATE_TOLERANCE = 0.15


def validate(series, observations):
    by = {}
    for o in observations:
        key = (o["code"], o["period"])
        if key in by:
            raise ValidationError("duplicate observation %s %s" % key)
        by[key] = o["value"]
    col = {}
    for (c, p), v in by.items():
        col.setdefault(c, {})[p] = v
    expected = set(_code(a, m[1], s[0]) for _sh, a, _e, _l in SHEETS
                   for m in MEASURES for s in SEXES)
    missing = expected - set(col)
    if missing:
        raise ValidationError("series missing: %s" % ", ".join(sorted(missing)))

    # 1. The headline runs unbroken from 1953, the original series from July
    #    1972, and both end in the same, recent month.
    def months_between(a, b):
        return (b.year - a.year) * 12 + b.month - a.month + 1

    latest = None
    for code, start in (("sa.unemployment_rate.total", SA_FROM),
                        ("nsa.unemployment_rate.total", NSA_FROM)):
        ps = sorted(col[code])
        if ps[0] != start:
            raise ValidationError("%s starts %s, expected %s" % (code, ps[0], start))
        if len(ps) != months_between(ps[0], ps[-1]):
            raise ValidationError("%s has a gap: %d months over %d"
                                  % (code, len(ps), months_between(ps[0], ps[-1])))
        if latest is None:
            latest = ps[-1]
        elif ps[-1] != latest:
            raise ValidationError("adjusted series ends %s, original %s" % (latest, ps[-1]))
    if (datetime.date.today() - latest).days > 400:
        raise ValidationError("newest month %s is implausibly old" % latest)
    for code in expected:
        if max(col[code]) != latest:
            raise ValidationError("%s ends %s, the release runs to %s"
                                  % (code, max(col[code]), latest))

    # 2. Ranges: the rate has stayed between 1% and 6% since 1953; headcounts
    #    are millions, not people and not thousands.
    for (code, p), v in by.items():
        if code.split(".")[1] == "unemployment_rate":
            if not (0.5 <= v <= 8.0):
                raise ValidationError("%s %s: rate %.1f%% out of range" % (code, p, v))
        elif not (0 <= v <= 12000):
            raise ValidationError("%s %s: %.0f (万人) out of range" % (code, p, v))

    # 3. Identities on the original series: labour force = employed +
    #    unemployed; both sexes = men + women; the rate = unemployed / labour
    #    force. (Each adjusted series is adjusted on its own, so the
    #    identities hold only approximately there and are not gated.)
    checked = 0
    for p in col["nsa.labour_force.total"]:
        for sex, _e, _j in SEXES:
            lf = col["nsa.labour_force." + sex].get(p)
            emp = col["nsa.employed." + sex].get(p)
            un = col["nsa.unemployed." + sex].get(p)
            rate = col["nsa.unemployment_rate." + sex].get(p)
            if None in (lf, emp, un, rate):
                continue
            if abs(lf - (emp + un)) > _tolerance(p):
                raise ValidationError("%s %s: labour force %.0f ≠ employed %.0f + "
                                      "unemployed %.0f" % (sex, p, lf, emp, un))
            if abs(rate - un / lf * 100) > RATE_TOLERANCE:
                raise ValidationError("%s %s: rate %.1f%% but unemployed / labour "
                                      "force = %.2f%%" % (sex, p, rate, un / lf * 100))
            checked += 1
        for m in MEASURES[:5]:
            t = col["nsa.%s.total" % m[1]].get(p)
            a = col["nsa.%s.male" % m[1]].get(p)
            b = col["nsa.%s.female" % m[1]].get(p)
            if None not in (t, a, b) and abs(t - (a + b)) > _tolerance(p):
                raise ValidationError("%s %s: both sexes %.0f ≠ men %.0f + women %.0f"
                                      % (m[1], p, t, a, b))
    if checked < 1500:
        raise ValidationError("only %d identities checked" % checked)

    last = dict((c, col[c][latest]) for c in col)
    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "identities_checked": checked,
        "unemployment_rate_sa": last["sa.unemployment_rate.total"],
        "unemployed_sa_10k": last["sa.unemployed.total"],
    }


# --- presentation -----------------------------------------------------------

KINDS = dict((_code(a, m[1], s[0]), m[5])
             for _sh, a, _e, _l in SHEETS for m in MEASURES for s in SEXES)

PRESENTATION = {
    "credit_line": "Source: Statistics Bureau of Japan, Labour Force Survey.",
    "stale_after_days": STALE_AFTER_DAYS,
    "overview_tiles": [
        {"key": "rate", "code": "sa.unemployment_rate.total",
         "label": "Unemployment rate", "type": "level"},
        {"key": "unemployed", "code": "sa.unemployed.total",
         "label": "Unemployed", "type": "level"},
        {"key": "employed", "code": "sa.employed.total",
         "label": "Employed", "type": "level"},
        {"key": "labour_force", "code": "sa.labour_force.total",
         "label": "Labour force", "type": "level"},
    ],
    "main_series": [
        {"role": "headline", "code": "sa.unemployment_rate.total",
         "label": "Unemployment rate, both sexes", "slot": 1},
        {"role": "men", "code": "sa.unemployment_rate.male",
         "label": "Unemployment rate, men", "slot": 2},
        {"role": "women", "code": "sa.unemployment_rate.female",
         "label": "Unemployment rate, women", "slot": 3},
    ],
    "kinds": KINDS,
}


MANIFEST = {
    "id": DATASET["slug"],
    "section": "labour",
    "name": {"en": "Unemployment and employment — Labour Force Survey",
             "ja": "労働力調査 完全失業率・就業者数"},
    "shape": "series",
    "summary": DATASET["description"],
    "source": {
        "publisher": DATASET["agency"],
        "publisher_ja": DATASET["agency_ja"],
        "document": SOURCE["name"],
        "url": SOURCE["url"],
        "credit": PRESENTATION["credit_line"],
        "license_note": SOURCE["license_note"],
    },
    "keys": ["series_code", "period"],
    "frequency": DATASET["frequency"],
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "1953-01",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published value (headcounts in ten thousand persons; "
                                 "the rate in %)",
         "unit": "persons_10k", "trust": "official"},
        {"id": "yoy", "label": "Change on a year earlier", "unit": "%", "trust": "derived",
         "where": "headcounts only; the unemployment rate is already a percentage and "
                  "its change is read in points",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
        {"id": "mom", "label": "Change on the month before", "unit": "%", "trust": "derived",
         "where": "headcounts only, seasonally adjusted series",
         "calc": "(value[t] / value[t−1 month] − 1) × 100, from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "summary": "/api/v1/%s/overview" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search", "summary"],
    "cite": "/labour.html?dataset=unemployment-jp",
    "page": "/labour.html",
    "notes": [
        "Headcounts are in ten thousand persons (万人), as published: 177 is "
        "1.77 million people.",
        "Codes are adjustment.measure.sex — sa = seasonally adjusted (from 1953), "
        "nsa = original series (from July 1972).",
        "Figures before 1974 marked * by the Bureau exclude Okinawa.",
        "March–August 2011 are the Bureau's supplementary estimates for the "
        "whole country after the Great East Japan Earthquake.",
        "Seasonally adjusted values for the last ten years are revised every "
        "January; each revision is a new vintage and the earlier figure stays "
        "retrievable with as_of.",
    ],
}
