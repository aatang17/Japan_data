"""Adapter: JGB yield curve — Ministry of Finance constant-maturity yields.

Source: the MOF "Interest Rate" files — daily par yields for 15
maturities (1–10, 15, 20, 25, 30, 40 years), computed by the Ministry
from JSDA reference prices, published every business day since
24 September 1974. This is the platform's first MOF source: the data
obligations are the Government of Japan standard terms (attribution),
not the BOJ API credit line.

Two files make one complete picture, so one ingest fetches both and
archives them together as a single JSON envelope (each file's bytes
base64'd verbatim, so the artifact is still the pristine downloads):
- jgbcme_all.csv  — full history through the end of the prior month;
- jgbcme.csv      — the current month, updated each business day.

Data facts the parser and gates rely on:
- CRLF endings; row 1 is a title, row 2 the header, data from row 3;
- the current-month file carries a footer (an all-empty row and a
  quoted browser-cache note) that must be skipped, and stray text is
  cp932, not UTF-8;
- missing is "-" and stays missing, never zero. Two kinds of gap are
  real: maturities that start late (10Y 1986-07, 20Y 1986-12, 15Y
  1991-08, 30Y 1999-09, 25Y 2004-03, 40Y 2007-11) and mid-series
  holes in 1Y/2Y/3Y (648/361/76 dates) where short tenors were not
  quoted. Only 4Y–9Y run complete from 1974; 5Y anchors the
  every-date gate;
- yields go negative (NIRP era: 1Y touched about −0.37%) — there is
  no positivity gate, only a sanity band;
- the largest calendar gap between business days on record is 11 days
  (Golden Week 2019), so a wider gap means a file went missing.

Unlike CPI indices these are rates in percent: `weight_per_10000` is
meaningless and stays NULL, and the curve is served by the /curve
surface rather than the index-shaped overview.
"""
import base64
import datetime
import json

from . import boj_ts  # shared fetch_bytes; nothing BOJ-specific is used


class ValidationError(Exception):
    pass


URL_HISTORICAL = ("https://www.mof.go.jp/english/policy/jgbs/reference/"
                  "interest_rate/historical/jgbcme_all.csv")
URL_CURRENT = ("https://www.mof.go.jp/english/policy/jgbs/reference/"
               "interest_rate/jgbcme.csv")

# (code, years, name_en); order is the curve order and the sort order.
MATURITIES = [
    ("1Y", 1, "1-year JGB yield"),
    ("2Y", 2, "2-year JGB yield"),
    ("3Y", 3, "3-year JGB yield"),
    ("4Y", 4, "4-year JGB yield"),
    ("5Y", 5, "5-year JGB yield"),
    ("6Y", 6, "6-year JGB yield"),
    ("7Y", 7, "7-year JGB yield"),
    ("8Y", 8, "8-year JGB yield"),
    ("9Y", 9, "9-year JGB yield"),
    ("10Y", 10, "10-year JGB yield"),
    ("15Y", 15, "15-year JGB yield"),
    ("20Y", 20, "20-year JGB yield"),
    ("25Y", 25, "25-year JGB yield"),
    ("30Y", 30, "30-year JGB yield"),
    ("40Y", 40, "40-year JGB yield"),
]

EXPECTED_HEADER = ["Date"] + [code for code, _y, _n in MATURITIES]

DATASET = {
    "slug": "jgb-yields",
    "title": "JGB Yield Curve — Constant-Maturity Yields",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "daily",
    "description": (
        "Daily constant-maturity yields on Japanese government bonds for "
        "15 maturities from 1 to 40 years, in percent, computed by the "
        "Ministry of Finance from JSDA reference prices and published "
        "every business day since September 1974. Longer maturities "
        "begin when the tenor was first issued (40-year in 2007). "
        "Yields can be negative."
    ),
}

SOURCE = {
    "source_id": "mof:jgbcm",
    "name": "Ministry of Finance — Interest Rate (JGB constant-maturity yields)",
    "name_ja": "財務省 国債金利情報",
    "url": "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm",
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with "
        "CC BY 4.0): free to use with attribution to the Ministry of "
        "Finance. Yields are reference values computed by the Ministry "
        "from JSDA over-the-counter reference prices."
    ),
}

DOWNLOAD_URL = URL_HISTORICAL  # shown as the origin; fetch() also gets URL_CURRENT

RAW_SUFFIX = ".json"


def fetch():
    """Both files, verbatim, in one archived artifact.

    The envelope is deterministic (no timestamps), so the ingest
    runner's plain SHA-256 comparison gives idempotency: the artifact
    changes exactly when either published file changes.
    """
    envelope = {
        "historical": {"url": URL_HISTORICAL,
                       "b64": base64.b64encode(
                           boj_ts.fetch_bytes(URL_HISTORICAL)).decode("ascii")},
        "current": {"url": URL_CURRENT,
                    "b64": base64.b64encode(
                        boj_ts.fetch_bytes(URL_CURRENT)).decode("ascii")},
    }
    return json.dumps(envelope, sort_keys=True).encode("utf-8")


def _parse_file(raw_bytes, origin):
    """One MOF CSV -> {date: {code: value}}. Missing cells are absent."""
    text = raw_bytes.decode("cp932")  # ASCII-superset; footer notes are cp932
    lines = text.split("\n")
    if len(lines) < 3:
        raise ValidationError("%s: fewer than 3 lines" % origin)
    header = [c.strip() for c in lines[1].strip("\r").split(",")]
    if header != EXPECTED_HEADER:
        raise ValidationError("%s: unexpected header %r" % (origin, header))

    out = {}
    for lineno, line in enumerate(lines[2:], start=3):
        line = line.strip("\r")
        if not line:
            continue
        cells = line.split(",")
        date_cell = cells[0].strip()
        # Footer rows: an all-empty row, or a quoted note. Skip only what
        # is recognisably a footer; anything else unexpected must fail.
        if not date_cell:
            if any(c.strip() and not c.strip().startswith('"') for c in cells):
                raise ValidationError(
                    "%s line %d: dateless row with data" % (origin, lineno))
            continue
        if date_cell.startswith('"'):
            continue
        if len(cells) != len(EXPECTED_HEADER):
            raise ValidationError(
                "%s line %d: %d fields, expected %d"
                % (origin, lineno, len(cells), len(EXPECTED_HEADER)))
        try:
            y, m, d = date_cell.split("/")
            period = datetime.date(int(y), int(m), int(d))
        except ValueError:
            raise ValidationError(
                "%s line %d: bad date %r" % (origin, lineno, date_cell))
        row = {}
        for (code, _years, _name), cell in zip(MATURITIES, cells[1:]):
            cell = cell.strip()
            if cell in ("", "-"):
                continue  # missing stays missing, never zero
            try:
                row[code] = float(cell)
            except ValueError:
                raise ValidationError(
                    "%s line %d: bad value %r for %s"
                    % (origin, lineno, cell, code))
        out[period] = row
    return out


def parse(raw_bytes):
    envelope = json.loads(raw_bytes.decode("utf-8"))
    historical = _parse_file(
        base64.b64decode(envelope["historical"]["b64"]), "historical file")
    current = _parse_file(
        base64.b64decode(envelope["current"]["b64"]), "current-month file")

    # The current-month file is the fresher publication wherever both
    # cover a date (at month rollover they can briefly overlap).
    merged = dict(historical)
    merged.update(current)

    series = []
    for order, (code, years, name_en) in enumerate(MATURITIES):
        series.append({
            "code": code,
            "name_en": name_en,
            "name_ja": None,
            "unit": "pct",
            "weight_per_10000": None,   # meaningless for a yield
            "sort_order": order,
        })

    observations = []
    for period in sorted(merged):
        for code, value in merged[period].items():
            observations.append(
                {"code": code, "period": period, "value": value})
    return series, observations


# Sanity band for a JGB par yield in percent. History spans roughly
# −0.4% (NIRP-era 1Y) to 10.4% (1974 1Y); a value outside this band is
# a parsing or publication fault, not a market move.
YIELD_MIN = -2.0
YIELD_MAX = 20.0

# Wider than the largest business-day gap on record (11 calendar days,
# Golden Week 2019). A gap beyond this means a month of data is missing
# — the month-rollover failure mode where the historical file has been
# rolled forward but the current-month file no longer covers last month.
MAX_GAP_DAYS = 16

FIRST_DATE = datetime.date(1974, 9, 24)   # published start of the series


def validate(series, observations):
    expected = set(code for code, _y, _n in MATURITIES)
    got = set(s["code"] for s in series)
    if got != expected:
        raise ValidationError("maturity set mismatch: %s" % sorted(
            got.symmetric_difference(expected)))

    if len(observations) < 150_000:   # ~13,000 days × 9–15 maturities
        raise ValidationError("only %d observations parsed" % len(observations))

    dates = set()
    seen = set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        dates.add(o["period"])
        if not (YIELD_MIN <= o["value"] <= YIELD_MAX):
            raise ValidationError(
                "%s %s: yield %s%% outside sanity band"
                % (o["code"], o["period"], o["value"]))

    ordered = sorted(dates)
    if ordered[0] != FIRST_DATE:
        raise ValidationError(
            "history starts %s, expected %s — historical file truncated?"
            % (ordered[0], FIRST_DATE))
    for prev, cur in zip(ordered, ordered[1:]):
        if (cur - prev).days > MAX_GAP_DAYS:
            raise ValidationError(
                "gap of %d days between %s and %s — a month of data is "
                "missing (files out of step at month rollover?)"
                % ((cur - prev).days, prev, cur))

    latest = ordered[-1]
    today = datetime.date.today()
    if (today - latest).days > 45:
        raise ValidationError(
            "latest date %s is implausibly old for a changed file" % latest)

    # Every date must carry the curve for its era. 5Y is the anchor: it
    # is the only maturity published on every date since 1974 (10Y only
    # starts 1986-07; 1Y–3Y have real mid-series holes).
    by_date_5y = set(o["period"] for o in observations if o["code"] == "5Y")
    missing_5y = dates - by_date_5y
    if missing_5y:
        raise ValidationError(
            "%d dates lack a 5Y yield, e.g. %s"
            % (len(missing_5y), sorted(missing_5y)[0]))

    latest_curve = dict(
        (o["code"], o["value"]) for o in observations if o["period"] == latest)
    if len(latest_curve) != len(MATURITIES):
        raise ValidationError(
            "latest date %s has %d of %d maturities"
            % (latest, len(latest_curve), len(MATURITIES)))

    return {
        "series": len(series),
        "observations": len(observations),
        "dates": len(ordered),
        "latest_period": latest.isoformat(),
        "latest_10y_pct": latest_curve.get("10Y"),
        "latest_2y_pct": latest_curve.get("2Y"),
    }


# Presentation config for the /curve surface and the rates page.
# Spread definitions are data for the front end: the API serves official
# yields only; spreads are calculated on the page and carry their
# formula there and in every export, per the trust contract.
PRESENTATION = {
    "credit_line": "Source: Ministry of Finance, Japan.",
    "stale_after_days": 7,   # daily series; allows weekends + Golden Week
    "curve": {
        "maturities": [
            {"code": code, "years": years} for code, years, _n in MATURITIES],
        "spreads": [
            {"key": "s2s10", "label": "2s10s Spread",
             "long": "10Y", "short": "2Y"},
            {"key": "s10s30", "label": "10s30s Spread",
             "long": "30Y", "short": "10Y"},
        ],
        "history_series": ["2Y", "10Y", "30Y"],
    },
}
