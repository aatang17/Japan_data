"""Adapter: Bank of Japan — average interest rates posted on deposits (IR02).

Source: BOJ Time-Series Data Search API, database IR02 — the average of
the interest rates that financial institutions post on ordinary deposits
and on time deposits by term (1 month to 10 years) and by size of deposit
(under ¥3 million, ¥3–10 million, ¥10 million and over), in percent per
year, monthly from April 2022.

Only the monthly series are taken. The same database carries the earlier
regimes of the survey (October 2007 – March 2022, weekly on Mondays; 1991 –
2007, weekly on Thursdays) under different codes; those are weekly series
in a monthly store and are not ingested. The monthly series begin exactly
where the BOJ moved the survey to a monthly basis, so nothing is spliced.

A posted deposit rate is a level in percent; changes are in percentage
points. Values are tiny for most of the sample (0.002% on ordinary
deposits in 2022) and the gates allow that — a floor of zero, not of some
"plausible" positive number.

Curated series only. Every code and name below was checked against
getMetadata on 2026-09-23.
"""
import datetime

from . import boj_ts
from .boj_ts import ValidationError  # noqa: F401 — part of the adapter contract
from .boj_ts import canonical_bytes  # noqa: F401 — idempotency: response embeds a timestamp

DB = "IR02"

SIZES = [
    ("L", "¥10 million or more"),
    ("M", "¥3 million to under ¥10 million"),
    ("S", "under ¥3 million"),
]
SIZE_NAME = dict(SIZES)
SIZE_ORDER = dict((k, i) for i, (k, _n) in enumerate(SIZES))
TERMS = [
    ("1M", "1 month"), ("3M", "3 months"), ("6M", "6 months"),
    ("1Y", "1 year"), ("2Y", "2 years"), ("3Y", "3 years"), ("4Y", "4 years"),
    ("5Y", "5 years"), ("7Y", "7 years"), ("10Y", "10 years"),
]
TERM_NAME = dict(TERMS)
TERM_ORDER = dict((k, i) for i, (k, _n) in enumerate(TERMS))

# (code, size, term). The ordinary-deposit line has neither.
SERIES = [("DLDR121N", None, None)]
for _size_code, _size_key in (("4", "L"), ("5", "M"), ("6", "S")):
    for _term_key, _n in TERMS:
        SERIES.append(("DLDR43TL%s%sN" % (_size_code, _term_key), _size_key, _term_key))

KIND = dict((code, "rate") for code, _s, _t in SERIES)
HEADLINE = "DLDR121N"

DATASET = {
    "slug": "boj-deposit-rates",
    "title": "Bank of Japan — Average Interest Rates Posted on Deposits",
    "country": "Japan",
    "agency": "Bank of Japan",
    "agency_ja": "日本銀行",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Average interest rates posted at financial institutions on ordinary "
        "deposits and on time deposits by term (1 month to 10 years) and by "
        "size of deposit (under ¥3 million, ¥3–10 million, ¥10 million and "
        "over), in percent per year, monthly from April 2022. Source database "
        "IR02, 'Average Interest Rates Posted at Financial Institutions by "
        "Type of Deposit'."
    ),
}

SOURCE = {
    "source_id": "boj:IR02",
    "name": ("BOJ Time-Series Data Search — IR02: Average Interest Rates "
             "Posted at Financial Institutions by Type of Deposit"),
    "name_ja": "日本銀行 時系列統計データ検索サイト 預金種類別店頭表示金利の平均年利率等",
    "url": "https://www.stat-search.boj.or.jp/",
    "license_note": (
        "BOJ Time-Series Data Search API terms: no redistribution "
        "restriction. Two mandatory obligations — display the credit line "
        "(\"%s\") wherever the data appears, including exports, and notify "
        "the BOJ Research and Statistics Department by email when a service "
        "using the API is released." % boj_ts.CREDIT_LINE
    ),
}

DOWNLOAD_URL = boj_ts.data_code_url(DB, [code for code, _s, _t in SERIES])

RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": boj_ts.CREDIT_LINE,
    "main_series": [
        {"role": "headline", "code": HEADLINE,
         "label": "Ordinary deposits", "slot": 1},
        {"role": "time_1y", "code": "DLDR43TL61YN",
         "label": "Time deposits, 1 year, under ¥3mn", "slot": 2},
        {"role": "time_5y", "code": "DLDR43TL65YN",
         "label": "Time deposits, 5 years, under ¥3mn", "slot": 3},
        {"role": "time_10y", "code": "DLDR43TL610YN",
         "label": "Time deposits, 10 years, under ¥3mn", "slot": 4},
    ],
    "overview_tiles": [
        {"key": "ordinary", "type": "level", "code": HEADLINE,
         "label": "Ordinary Deposits"},
        {"key": "time_1y", "type": "level", "code": "DLDR43TL61YN",
         "label": "1-Year Time, <¥3mn"},
        {"key": "time_5y", "type": "level", "code": "DLDR43TL65YN",
         "label": "5-Year Time, <¥3mn"},
        {"key": "time_10y", "type": "level", "code": "DLDR43TL610YN",
         "label": "10-Year Time, <¥3mn"},
    ],
    "kinds": KIND,
    # Published mid-month for the current month (September 2026 was up by
    # the 17th), so the newest point is never older than a few weeks.
    "stale_after_days": 75,
}


def fetch():
    return boj_ts.fetch_bytes(DOWNLOAD_URL)


def _name(size, term):
    if size is None:
        return "Ordinary deposits"
    return "Time deposits — %s — %s" % (TERM_NAME[term], SIZE_NAME[size])


def parse(raw_bytes):
    data = boj_ts.parse_getdatacode(raw_bytes)
    series, observations = [], []
    for code, size, term in SERIES:
        if code not in data:
            continue
        series.append({
            "code": code,
            "name_en": _name(size, term),
            "name_ja": None,
            "unit": "percent",
            "weight_per_10000": None,
            "sort_order": (0 if size is None
                           else 10 + SIZE_ORDER[size] * 20 + TERM_ORDER[term]),
        })
        for period, value in data[code]["observations"]:
            observations.append({"code": code, "period": period, "value": value})
    return series, observations


def _month_index(d):
    return d.year * 12 + d.month


FIRST = datetime.date(2022, 4, 1)
RATE_FLOOR, RATE_CEILING = 0.0, 10.0


def validate(series, observations):
    expected = set(code for code, _s, _t in SERIES)
    got = set(s["code"] for s in series)
    missing = sorted(expected - got)
    if missing:
        raise ValidationError("series missing from response: %s" % ", ".join(missing))
    if len(observations) < 31 * 40:
        raise ValidationError("only %d observations parsed" % len(observations))

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    latest = max(o["period"] for o in observations)
    for code in expected:
        obs = by_code[code]
        periods = sorted(obs)
        if periods[0] != FIRST:
            raise ValidationError("%s: starts %s; the monthly survey began %s"
                                  % (code, periods[0], FIRST))
        if periods[-1] != latest:
            raise ValidationError("%s: ends %s while the newest month is %s"
                                  % (code, periods[-1], latest))
        span = _month_index(periods[-1]) - _month_index(periods[0]) + 1
        if span != len(periods):
            raise ValidationError("%s: gap in monthly coverage (%d months span, %d present)"
                                  % (code, span, len(periods)))
        lo, hi = min(obs.values()), max(obs.values())
        if lo < RATE_FLOOR or hi > RATE_CEILING:
            raise ValidationError("%s: rate outside %s–%s%% (min %s, max %s)"
                                  % (code, RATE_FLOOR, RATE_CEILING, lo, hi))

    # A longer term never pays less than a shorter one at the same size?
    # Not enforced — the posted curve inverted at the short end in 2024 —
    # but a 10-year rate below the ordinary-deposit rate would mean a
    # column shift, and that is checked.
    ordinary = by_code[HEADLINE][latest]
    for size_code in ("4", "5", "6"):
        ten = by_code["DLDR43TL%s10YN" % size_code][latest]
        if ten < ordinary:
            raise ValidationError(
                "10-year time deposit %s%% below ordinary deposits %s%% in %s: "
                "columns have shifted" % (ten, ordinary, latest))

    today = datetime.date.today()
    if (today - latest).days > 75:
        raise ValidationError(
            "latest period %s is implausibly old for a changed file" % latest)

    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "ordinary_deposit_rate_latest_pct": ordinary,
        "time_1y_small_latest_pct": by_code["DLDR43TL61YN"][latest],
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "banking",
    "name": {"en": "Bank of Japan — average interest rates posted on deposits",
             "ja": "日本銀行 預金種類別店頭表示金利の平均年利率"},
    "shape": "series",
    "summary": ("Average rates posted at financial institutions on ordinary "
                "deposits and on time deposits by term (1 month to 10 years) "
                "and deposit size, in percent per year, monthly from April 2022."),
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
        "as_of_supported": True, "history_from": "2022-04",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published rate, % per year", "unit": "%",
         "trust": "official"},
        {"id": "delta_1m", "label": "Change on the month", "unit": "pp",
         "trust": "derived",
         "calc": "value[t] − value[t−1 month], from published values."},
        {"id": "delta_12m", "label": "Change on the year", "unit": "pp",
         "trust": "derived",
         "calc": "value[t] − value[t−12 months], from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "summary": "/api/v1/%s/overview" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search", "summary"],
    "cite": "/banks.html?dataset=boj-deposit-rates",
    "page": "/banks.html",
    "notes": [
        "Posted (店頭表示) rates averaged across institutions — what a depositor "
        "is offered, not the average rate banks actually pay on their deposit "
        "books. A rate is a level in percent; changes are in percentage points.",
        "Monthly from April 2022 only. The BOJ's earlier weekly regimes of the "
        "same survey (1991–2007 and 2007–2022) carry different codes and are "
        "not ingested into this monthly store, and nothing is spliced.",
        "The BOJ's credit line must be displayed wherever the data appears, "
        "including exports.",
    ],
}
