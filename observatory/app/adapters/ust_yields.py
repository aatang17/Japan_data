# -*- coding: utf-8 -*-
"""US Treasury par yield curve — daily constant-maturity yields.

The US counterpart of `mof_jgb`, and the same shape: one series per maturity,
one observation per business day, yields in percent. Published by the Treasury
every business day since 2 January 1990.

Two things about the source shape the code here.

**The tenor set grows over time.** 1990 files carry nine maturities; by 2010
there are eleven; today there are fourteen. The 1-month began in 2001, the
2-month in 2018, the 4-month in 2022 and the 1.5-month in 2025, while the
30-year was discontinued in 2002 and reintroduced in 2006. So a maturity is
absent from a date because the tenor did not exist then, not because the value
is zero: the gap stays a gap (P0 — missing is never zero).

**There is no single history file.** The Treasury serves one CSV per year and
refuses the all-years form with a 403; each request also takes about 19
seconds regardless of size, which is server-side and cannot be hurried. A
cold fetch is therefore ~37 requests and ~12 minutes.

Closed years are immutable — the Treasury does not revise 1995 — so re-reading
them daily would mean 37 requests a day forever to re-download bytes that
cannot have changed. Instead each year is cached under
`data/raw/ust-yields-years/`, and a normal run re-fetches only the current year
and the one before it (the pair covers a January rollover). That is two
requests and about forty seconds. The cache is pure derived state: delete it
and the next run rebuilds it, which is also how a year gets repaired if the
Treasury ever does restate one.

Source: https://home.treasury.gov/resource-center/data-chart-center/interest-rates/
Public domain (US Government work).
"""
import base64
import datetime
import json
import os
import time

from . import boj_ts  # shared fetch_bytes; nothing BOJ-specific is used


class ValidationError(Exception):
    pass


URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
       "interest-rates/daily-treasury-rates.csv/{year}/all"
       "?type=daily_treasury_yield_curve&field_tdr_date_value={year}"
       "&page&_format=csv")

FIRST_YEAR = 1990

# (code, years, name_en). Order is the curve order and the sort order.
# `years` is what the curve chart plots on its x-axis.
MATURITIES = [
    ("1M",   1 / 12.0,  "1-month Treasury constant-maturity yield"),
    ("1_5M", 1.5 / 12.0, "1.5-month Treasury constant-maturity yield"),
    ("2M",   2 / 12.0,  "2-month Treasury constant-maturity yield"),
    ("3M",   0.25,      "3-month Treasury constant-maturity yield"),
    ("4M",   4 / 12.0,  "4-month Treasury constant-maturity yield"),
    ("6M",   0.5,       "6-month Treasury constant-maturity yield"),
    ("1Y",   1,         "1-year Treasury constant-maturity yield"),
    ("2Y",   2,         "2-year Treasury constant-maturity yield"),
    ("3Y",   3,         "3-year Treasury constant-maturity yield"),
    ("5Y",   5,         "5-year Treasury constant-maturity yield"),
    ("7Y",   7,         "7-year Treasury constant-maturity yield"),
    ("10Y",  10,        "10-year Treasury constant-maturity yield"),
    ("20Y",  20,        "20-year Treasury constant-maturity yield"),
    ("30Y",  30,        "30-year Treasury constant-maturity yield"),
]

# The Treasury's column labels are not stable across years or between the
# nominal and real files: "1 Mo", "1.5 Month", "5 Yr" and "5 YR" all occur.
# Normalising by squashing case and spaces keeps one entry per real tenor
# instead of one per spelling.
def _norm(label):
    return "".join(label.split()).upper().strip('"')


HEADER_TO_CODE = {}
for _code, _years, _name in MATURITIES:
    n = _code.replace("_", ".")
    if _code.endswith("M"):
        months = n[:-1]
        for spelling in ("%sMO" % months, "%sMONTH" % months, "%sMONTHS" % months):
            HEADER_TO_CODE[_norm(spelling)] = _code
    else:
        years = n[:-1]
        for spelling in ("%sYR" % years, "%sYEAR" % years, "%sYEARS" % years):
            HEADER_TO_CODE[_norm(spelling)] = _code

DATASET = {
    "slug": "ust-yields",
    "title": "US Treasury Yield Curve — Constant-Maturity Yields",
    "country": "United States",
    "agency": "U.S. Department of the Treasury",
    "agency_ja": None,
    "base": None,
    "frequency": "daily",
    "description": (
        "Daily par yields on US Treasury securities at constant maturities "
        "from 1 month to 30 years, in percent per year, published by the "
        "Treasury every business day since January 1990. Derived by the "
        "Treasury from end-of-day bid yields on the most recently auctioned "
        "securities. A maturity is null before that tenor existed; the "
        "30-year was discontinued in February 2002 and reintroduced in "
        "February 2006."
    ),
}

SOURCE = {
    "source_id": "ust:daily_treasury_yield_curve",
    "name": "U.S. Department of the Treasury — Daily Treasury Par Yield Curve Rates",
    "name_ja": None,
    "url": ("https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/TextView?type=daily_treasury_yield_curve"),
    "license_note": (
        "Work of the United States Government, in the public domain "
        "(17 U.S.C. §105). Yields are Treasury's own par-yield estimates, "
        "interpolated from end-of-day bid-side market quotations."
    ),
}

DOWNLOAD_URL = URL.format(year=datetime.date.today().year)

RAW_SUFFIX = ".json"


def _years_wanted():
    return list(range(FIRST_YEAR, datetime.date.today().year + 1))


def _cache_dir():
    """Where closed years are kept. Under the data directory, because on
    Railway that is the mounted volume and the only disk that survives a
    redeploy; anywhere else the cache would evaporate every deploy and every
    boot would pay the full 12 minutes."""
    root = os.environ.get("OBSERVATORY_DATA_DIR")
    if not root:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.join(here, "..", "..", "data")
    return os.path.join(root, "ust-yields-years")


def fetch_year_csv(url, label):
    """One year CSV with retries.

    The Treasury endpoint takes ~19s to answer and occasionally just stops
    answering — a cold 24-file run timed out mid-way on 15 September 2026 and
    the same URL served fine a minute later. A daily job that gives up on one
    slow response would leave the dataset unpublished for the day, so this
    retries with a widening pause before it admits defeat.
    """
    last = None
    for attempt in range(4):
        try:
            raw = boj_ts.fetch_bytes(url)
        except Exception as e:
            last = e
            time.sleep(5 * (attempt + 1))
            continue
        if not raw.lstrip()[:4].upper().startswith(b"DATE"):
            raise ValidationError("%s: not a rates CSV (got %r)" % (label, raw[:60]))
        return raw
    raise ValidationError("%s: fetch failed after 4 attempts (%s)" % (label, last))


def _year_bytes(year, force):
    """One year's CSV, from cache when it is a closed year we already hold."""
    path = os.path.join(_cache_dir(), "%d.csv" % year)
    if not force and os.path.exists(path):
        with open(path, "rb") as f:
            raw = f.read()
        if raw.lstrip()[:4].upper().startswith(b"DATE"):
            return raw
        # a truncated or garbled cache file is not worth reasoning about
        os.remove(path)
    raw = fetch_year_csv(URL.format(year=year), str(year))
    os.makedirs(_cache_dir(), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:      # written whole then renamed: a crash must
        f.write(raw)                # never leave a half file to be cached
    os.replace(tmp, path)
    return raw


def fetch():
    """Every year file, verbatim, in one archived artifact.

    The envelope is deterministic (sorted keys, no timestamps), so the ingest
    runner's SHA-256 comparison gives idempotency: the artifact changes exactly
    when the Treasury changes a published file.

    Only the current year and the one before it are re-fetched; earlier years
    come from the cache described in the module docstring. Set
    UST_YEARS_REFRESH_ALL=1 to force a full re-download.
    """
    force_all = os.environ.get("UST_YEARS_REFRESH_ALL", "").strip().lower() in (
        "1", "true", "yes", "on")
    this_year = datetime.date.today().year
    files = {}
    for year in _years_wanted():
        force = force_all or year >= this_year - 1
        raw = _year_bytes(year, force)
        files[str(year)] = {"url": URL.format(year=year),
                            "b64": base64.b64encode(raw).decode("ascii")}
    return json.dumps({"files": files}, sort_keys=True).encode("utf-8")


def _split_csv_line(line):
    """The Treasury quotes its header labels but never its values, and no field
    contains a comma, so a small hand-rolled split beats pulling in csv for a
    file this regular."""
    out, cur, inq = [], [], False
    for ch in line:
        if ch == '"':
            inq = not inq
        elif ch == "," and not inq:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [f.strip() for f in out]


def _parse_file(raw_bytes, origin):
    """One Treasury year CSV -> {date: {code: value}}. Blank cells are absent."""
    text = raw_bytes.decode("utf-8-sig", "replace")
    lines = [l for l in text.replace("\r\n", "\n").split("\n") if l.strip()]
    if not lines:
        raise ValidationError("%s: empty file" % origin)
    header = _split_csv_line(lines[0])
    if not header or header[0].strip('"').upper() != "DATE":
        raise ValidationError("%s: unexpected header %r" % (origin, header[:3]))
    codes = []
    for label in header[1:]:
        code = HEADER_TO_CODE.get(_norm(label))
        if code is None:
            # A new tenor appearing unannounced is a real event (the 4-month
            # arrived in 2022). Refusing to guess is the point: publish nothing
            # and let a human add it, rather than silently dropping a column.
            raise ValidationError(
                "%s: unknown maturity column %r — add it to MATURITIES"
                % (origin, label))
        codes.append(code)

    out = {}
    for line in lines[1:]:
        fields = _split_csv_line(line)
        if len(fields) != len(header):
            raise ValidationError(
                "%s: row has %d fields, header has %d: %r"
                % (origin, len(fields), len(header), line[:80]))
        try:
            month, day, year = fields[0].split("/")
            period = "%04d-%02d-%02d" % (int(year), int(month), int(day))
        except Exception:
            raise ValidationError("%s: bad date %r" % (origin, fields[0]))
        row = {}
        for code, cell in zip(codes, fields[1:]):
            if cell in ("", "N/A", "-"):
                continue          # tenor not published that day; a gap, never zero
            try:
                row[code] = float(cell)
            except ValueError:
                raise ValidationError(
                    "%s %s %s: non-numeric %r" % (origin, period, code, cell))
        if row:
            out[period] = row
    return out


def parse(raw_bytes):
    envelope = json.loads(raw_bytes.decode("utf-8"))
    merged = {}
    for year in sorted(envelope["files"]):
        merged.update(_parse_file(
            base64.b64decode(envelope["files"][year]["b64"]), "%s file" % year))

    series = []
    for order, (code, years, name_en) in enumerate(MATURITIES):
        series.append({
            "code": code,
            "name_en": name_en,
            "name_ja": None,
            "unit": "percent",
            "weight_per_10000": None,   # meaningless for a yield
            "sort_order": order,
        })

    observations = []
    for period in sorted(merged):
        for code, value in merged[period].items():
            observations.append(
                {"code": code, "period": period, "value": value})
    return series, observations


# Sanity band for a US par yield in percent. The history spans roughly 0.00
# (bills at the 2020 and 2011 lows) to 9.09 (the 30-year in 1990). Anything
# outside this band is a parsing or publication fault, not a market move.
YIELD_MIN = -1.0
YIELD_MAX = 25.0

# Wider than the longest run of US market holidays plus a weekend. A gap
# beyond this means a whole year file failed to parse or was served empty.
MAX_GAP_DAYS = 12

FIRST_DATE = datetime.date(1990, 1, 2)


def validate(series, observations):
    expected = set(code for code, _y, _n in MATURITIES)
    got = set(s["code"] for s in series)
    if got != expected:
        raise ValidationError("maturity set mismatch: %s" % sorted(
            got.symmetric_difference(expected)))

    # ~9,000 business days since 1990 at 9–14 maturities each.
    if len(observations) < 80000:
        raise ValidationError("only %d observations parsed" % len(observations))

    dates = set()
    seen = set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        dates.add(o["period"])
        v = o["value"]
        if not (YIELD_MIN <= v <= YIELD_MAX):
            raise ValidationError(
                "%s %s: yield %.3f outside [%.1f, %.1f]"
                % (o["code"], o["period"], v, YIELD_MIN, YIELD_MAX))

    ordered = sorted(dates)
    first = datetime.date.fromisoformat(ordered[0])
    if first > FIRST_DATE + datetime.timedelta(days=7):
        raise ValidationError("history starts %s, expected %s" % (first, FIRST_DATE))

    for a, b in zip(ordered, ordered[1:]):
        gap = (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
        if gap > MAX_GAP_DAYS:
            raise ValidationError("gap of %d days between %s and %s" % (gap, a, b))

    # The 10-year is published every business day the curve exists; if it is
    # thin, a year file parsed into near-nothing and the rest would still pass.
    ten = sum(1 for o in observations if o["code"] == "10Y")
    if ten < len(dates) * 0.95:
        raise ValidationError(
            "10Y present on only %d of %d dates" % (ten, len(dates)))

    latest = ordered[-1]
    latest_curve = dict(
        (o["code"], o["value"]) for o in observations if o["period"] == latest)
    # Unlike the JGB curve, not every tenor is expected on every date — the
    # set has grown over time and the Treasury occasionally omits one — so
    # this checks the curve is substantially there rather than complete.
    if len(latest_curve) < 8:
        raise ValidationError(
            "latest date %s has only %d maturities" % (latest, len(latest_curve)))
    if "10Y" not in latest_curve:
        raise ValidationError("latest date %s has no 10Y yield" % latest)

    return {
        "series": len(series),
        "observations": len(observations),
        "dates": len(ordered),
        "latest_period": latest,
        "latest_10y_pct": latest_curve.get("10Y"),
        "latest_2y_pct": latest_curve.get("2Y"),
        "latest_3m_pct": latest_curve.get("3M"),
    }


PRESENTATION = {
    "credit_line": "Source: U.S. Department of the Treasury.",
    "stale_after_days": 7,   # daily series; allows weekends and holidays
    "curve": {
        "maturities": [
            {"code": code, "years": years} for code, years, _n in MATURITIES],
        "spreads": [
            {"key": "s2s10", "label": "2s10s Spread",
             "long": "10Y", "short": "2Y"},
            {"key": "s3m10y", "label": "3m10y Spread",
             "long": "10Y", "short": "3M"},
        ],
        "history_series": ["2Y", "10Y", "30Y"],
    },
}


# The dataset's card. Daily yields in percent; spreads and changes are computed
# at serve time and their formulas are recorded here, never badged as official.
MANIFEST = {
    "id": DATASET["slug"],
    "section": "rates",
    "name": {"en": "US Treasury yield curve — constant-maturity yields",
             "ja": "米国債イールドカーブ（残存期間別）"},
    "shape": "series",
    "summary": ("Daily par yields on US Treasury securities at constant "
                "maturities from 1 month to 30 years, in percent per year, "
                "every business day since January 1990."),
    "source": {
        "publisher": DATASET["agency"],
        "publisher_ja": None,
        "document": SOURCE["name"],
        "url": SOURCE["url"],
        "credit": PRESENTATION["credit_line"],
        "license_note": SOURCE["license_note"],
    },
    "keys": ["series_code", "period"],
    "frequency": DATASET["frequency"],
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "1990-01-02",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Par yield, % per year", "unit": "%",
         "trust": "official"},
        {"id": "s2s10", "label": "2s10s spread", "unit": "pp", "trust": "derived",
         "calc": ("2s10s spread[t] = 10Y yield[t] − 2Y yield[t], in percentage "
                  "points, from published yields.")},
        {"id": "s3m10y", "label": "3m10y spread", "unit": "pp", "trust": "derived",
         "calc": ("3m10y spread[t] = 10Y yield[t] − 3M yield[t], in percentage "
                  "points, from published yields.")},
        {"id": "delta", "label": "Change over 1 month / 1 year", "unit": "pp",
         "trust": "derived",
         "calc": ("change[t] = value[t] − value[b], where b is the latest "
                  "business day on or before the same date 1 month (or 1 year) "
                  "earlier.")},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "curve": "/api/v1/%s/curve" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search"],
    "cite": "/rates.html",
    "page": "/rates.html",
    "notes": [
        "Daily series: the monthly rate measures (yoy, mom, ann3m) do not "
        "apply and are refused; request measure=index for published yields.",
        "A maturity not yet introduced on a date is null, never zero. The "
        "1-month begins in 2001, the 2-month in 2018, the 4-month in 2022 "
        "and the 1.5-month in 2025.",
        "The 30-year was discontinued in February 2002 and reintroduced in "
        "February 2006; that gap is in the published data, not a fault here.",
    ],
}
