# -*- coding: utf-8 -*-
"""US Treasury real yield curve — TIPS constant-maturity yields.

The inflation-protected twin of `ust_yields`, and the reason both are worth
having: nominal minus real at the same maturity is the breakeven inflation
rate, which is the market's own forecast of average CPI over that horizon. It
is the single most useful number the Treasury publishes for anyone studying
how inflation expectations move, and it exists for no other major market in
this platform.

Everything mechanical is shared with the nominal curve — the same per-year
CSVs behind the same slow endpoint, the same year cache, the same header
quirks (this file writes "5 YR" where the nominal one writes "5 Yr", which is
why label matching squashes case and spaces). Only the tenor set and the
history differ: five maturities, from January 2003, because that is when the
Treasury began publishing the series.

Real yields are routinely negative — every maturity was below zero for much of
2020-2021 — so the sanity band must allow it. A validator that rejected
negative values here would reject the most interesting period in the data.
"""
import base64
import datetime
import json

from . import ust_yields as _n


class ValidationError(Exception):
    pass


URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
       "interest-rates/daily-treasury-rates.csv/{year}/all"
       "?type=daily_treasury_real_yield_curve&field_tdr_date_value={year}"
       "&page&_format=csv")

FIRST_YEAR = 2003

MATURITIES = [
    ("5Y",  5,  "5-year TIPS constant-maturity real yield"),
    ("7Y",  7,  "7-year TIPS constant-maturity real yield"),
    ("10Y", 10, "10-year TIPS constant-maturity real yield"),
    ("20Y", 20, "20-year TIPS constant-maturity real yield"),
    ("30Y", 30, "30-year TIPS constant-maturity real yield"),
]

HEADER_TO_CODE = {}
for _code, _years, _name in MATURITIES:
    y = _code[:-1]
    for spelling in ("%sYR" % y, "%sYEAR" % y, "%sYEARS" % y):
        HEADER_TO_CODE[_n._norm(spelling)] = _code

DATASET = {
    "slug": "ust-real-yields",
    "title": "US Treasury Real Yield Curve — TIPS Constant-Maturity Yields",
    "country": "United States",
    "agency": "U.S. Department of the Treasury",
    "agency_ja": None,
    "base": None,
    "frequency": "daily",
    "description": (
        "Daily real yields on Treasury Inflation-Protected Securities at "
        "constant maturities of 5, 7, 10, 20 and 30 years, in percent per "
        "year, published every business day since January 2003. Subtracting "
        "a real yield from the nominal yield of the same maturity gives the "
        "breakeven inflation rate for that horizon. Real yields are often "
        "negative."
    ),
}

SOURCE = {
    "source_id": "ust:daily_treasury_real_yield_curve",
    "name": "U.S. Department of the Treasury — Daily Treasury Par Real Yield Curve Rates",
    "name_ja": None,
    "url": ("https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/TextView?type=daily_treasury_real_yield_curve"),
    "license_note": (
        "Work of the United States Government, in the public domain "
        "(17 U.S.C. §105). Real yields are Treasury's own estimates, derived "
        "from end-of-day bid-side quotations on outstanding TIPS."
    ),
}

DOWNLOAD_URL = URL.format(year=datetime.date.today().year)
RAW_SUFFIX = ".json"


def _cache_dir():
    import os
    root = os.environ.get("OBSERVATORY_DATA_DIR")
    if not root:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.join(here, "..", "..", "data")
    return os.path.join(root, "ust-real-yields-years")


def _year_bytes(year, force):
    import os
    path = os.path.join(_cache_dir(), "%d.csv" % year)
    if not force and os.path.exists(path):
        with open(path, "rb") as f:
            raw = f.read()
        if raw.lstrip()[:4].upper().startswith(b"DATE"):
            return raw
        os.remove(path)
    raw = _n.fetch_year_csv(URL.format(year=year), str(year))
    os.makedirs(_cache_dir(), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, path)
    return raw


def fetch():
    """As `ust_yields.fetch`: closed years from cache, the last two live."""
    import os
    force_all = os.environ.get("UST_YEARS_REFRESH_ALL", "").strip().lower() in (
        "1", "true", "yes", "on")
    this_year = datetime.date.today().year
    files = {}
    for year in range(FIRST_YEAR, this_year + 1):
        raw = _year_bytes(year, force_all or year >= this_year - 1)
        files[str(year)] = {"url": URL.format(year=year),
                            "b64": base64.b64encode(raw).decode("ascii")}
    return json.dumps({"files": files}, sort_keys=True).encode("utf-8")


def _parse_file(raw_bytes, origin):
    """Same CSV shape as the nominal file, against this file's tenor set."""
    text = raw_bytes.decode("utf-8-sig", "replace")
    lines = [l for l in text.replace("\r\n", "\n").split("\n") if l.strip()]
    if not lines:
        raise ValidationError("%s: empty file" % origin)
    header = _n._split_csv_line(lines[0])
    if not header or header[0].strip('"').upper() != "DATE":
        raise ValidationError("%s: unexpected header %r" % (origin, header[:3]))
    codes = []
    for label in header[1:]:
        code = HEADER_TO_CODE.get(_n._norm(label))
        if code is None:
            raise ValidationError(
                "%s: unknown maturity column %r — add it to MATURITIES"
                % (origin, label))
        codes.append(code)
    out = {}
    for line in lines[1:]:
        fields = _n._split_csv_line(line)
        if len(fields) != len(header):
            raise ValidationError(
                "%s: row has %d fields, header has %d" % (origin, len(fields), len(header)))
        try:
            month, day, year = fields[0].split("/")
            period = "%04d-%02d-%02d" % (int(year), int(month), int(day))
        except Exception:
            raise ValidationError("%s: bad date %r" % (origin, fields[0]))
        row = {}
        for code, cell in zip(codes, fields[1:]):
            if cell in ("", "N/A", "-"):
                continue           # tenor not published that day; a gap, never zero
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
    series = [{
        "code": code, "name_en": name, "name_ja": None, "unit": "percent",
        "weight_per_10000": None, "sort_order": order,
    } for order, (code, _y, name) in enumerate(MATURITIES)]
    observations = []
    for period in sorted(merged):
        for code, value in merged[period].items():
            observations.append({"code": code, "period": period, "value": value})
    return series, observations


# Real yields spent 2020-2021 deeply negative (the 5-year touched about −2%)
# and peaked near 3.5%. The band has to admit negatives or it would reject the
# most interesting stretch of the history.
YIELD_MIN = -5.0
YIELD_MAX = 10.0
MAX_GAP_DAYS = 12
FIRST_DATE = datetime.date(2003, 1, 2)


def validate(series, observations):
    expected = set(code for code, _y, _n2 in MATURITIES)
    got = set(s["code"] for s in series)
    if got != expected:
        raise ValidationError("maturity set mismatch: %s" % sorted(
            got.symmetric_difference(expected)))
    if len(observations) < 20000:      # ~5,900 business days × up to 5 tenors
        raise ValidationError("only %d observations parsed" % len(observations))

    dates, seen = set(), set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        dates.add(o["period"])
        if not (YIELD_MIN <= o["value"] <= YIELD_MAX):
            raise ValidationError(
                "%s %s: real yield %.3f outside [%.1f, %.1f]"
                % (o["code"], o["period"], o["value"], YIELD_MIN, YIELD_MAX))

    ordered = sorted(dates)
    first = datetime.date.fromisoformat(ordered[0])
    if first > FIRST_DATE + datetime.timedelta(days=7):
        raise ValidationError("history starts %s, expected %s" % (first, FIRST_DATE))
    for a, b in zip(ordered, ordered[1:]):
        gap = (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
        if gap > MAX_GAP_DAYS:
            raise ValidationError("gap of %d days between %s and %s" % (gap, a, b))

    ten = sum(1 for o in observations if o["code"] == "10Y")
    if ten < len(dates) * 0.95:
        raise ValidationError("10Y present on only %d of %d dates" % (ten, len(dates)))

    latest = ordered[-1]
    curve = dict((o["code"], o["value"]) for o in observations if o["period"] == latest)
    if "10Y" not in curve:
        raise ValidationError("latest date %s has no 10Y real yield" % latest)
    return {
        "series": len(series),
        "observations": len(observations),
        "dates": len(ordered),
        "latest_period": latest,
        "latest_10y_real_pct": curve.get("10Y"),
        "latest_5y_real_pct": curve.get("5Y"),
    }


PRESENTATION = {
    "credit_line": "Source: U.S. Department of the Treasury.",
    "stale_after_days": 7,
    "curve": {
        "maturities": [{"code": c, "years": y} for c, y, _ in MATURITIES],
        "spreads": [
            {"key": "s5s30", "label": "5s30s Real Spread",
             "long": "30Y", "short": "5Y"},
        ],
        "history_series": ["5Y", "10Y", "30Y"],
    },
}

MANIFEST = {
    "id": DATASET["slug"],
    "section": "rates",
    "name": {"en": "US Treasury real yield curve — TIPS constant-maturity yields",
             "ja": "米国物価連動国債（TIPS）実質利回りカーブ"},
    "shape": "series",
    "summary": ("Daily real yields on Treasury Inflation-Protected Securities "
                "at 5, 7, 10, 20 and 30 years, in percent per year, every "
                "business day since January 2003. Often negative."),
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
        "as_of_supported": True, "history_from": "2003-01-02",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Real yield, % per year", "unit": "%",
         "trust": "official"},
        {"id": "s5s30", "label": "5s30s real spread", "unit": "pp",
         "trust": "derived",
         "calc": ("5s30s real spread[t] = 30Y real yield[t] − 5Y real yield[t], "
                  "in percentage points, from published yields.")},
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
        "Real yields are frequently negative; that is the published value, "
        "not an error.",
        "Breakeven inflation is not served here. It is nominal minus real at "
        "the same maturity, a derived figure, and would carry its formula "
        "rather than an official badge.",
    ],
}
