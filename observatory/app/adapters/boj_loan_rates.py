"""Adapter: Bank of Japan — average contract interest rates on loans (IR04).

Source: BOJ Time-Series Data Search API, database IR04 — the average
contracted interest rate on loans and discounts, in percent per year, by
type of lender: domestically licensed banks as a whole, city banks, regional
banks, second-tier regional banks (regional banks II) and shinkin banks.

Three families, each by lender:
- **new loans** — the rate on loans made during the month, total and split
  short-term / long-term, monthly from October 1993 (shinkin from September
  1997). This is the line that moves first when policy rates move;
- **outstanding loans** — the average rate on the whole loan book at
  month-end, total and split short / long / overdrafts, from 1976 for the
  bank groups;
- **outstanding by instrument** — loans-on-deeds versus discounted bills.

The BOJ re-based the lender groups at March 2002: the trust-bank and
long-term-credit-bank lines and the "sub-total" lines stop there and are
kept as their own series, never spliced onto the domestically-licensed-banks
line that continues. A rate is a level in percent; changes are in
percentage points and the ratio measures (yoy, mom, ann3m) are meaningless
on it and refused by the API's rate handling.

Curated series only, never the whole database. Every code and name below
was checked against getMetadata on 2026-09-23.
"""
import datetime

from . import boj_ts
from .boj_ts import ValidationError  # noqa: F401 — part of the adapter contract
from .boj_ts import canonical_bytes  # noqa: F401 — idempotency: response embeds a timestamp

DB = "IR04"

LENDERS = [
    ("DB", "Domestically licensed banks"),
    ("CB", "City banks"),
    ("RB", "Regional banks"),
    ("RB2", "Regional banks II"),
    ("SK", "Shinkin banks"),
    ("TB", "Trust banks (through March 2002)"),
    ("LTCB", "Long-term credit banks (through March 2002)"),
    ("SUB", "Sub-total (through March 2002)"),
]
LENDER_NAME = dict(LENDERS)
LENDER_ORDER = dict((k, i) for i, (k, _n) in enumerate(LENDERS))

# (code, family, term, lender). family: 'new' = loans made in the month,
# 'outstanding' = the book at month-end, 'instrument' = the book by type.
SERIES = [
    ("DLLR2CIDBNL1", "new", "total", "DB"),
    ("DLLR2CICBNL1", "new", "total", "CB"),
    ("DLLR2CIRBNL1", "new", "total", "RB"),
    ("DLLR2CIMBNL1", "new", "total", "RB2"),
    ("DLLR2CICR35", "new", "total", "SK"),
    ("DLLR2CIDBNL2", "new", "short", "DB"),
    ("DLLR2CICBNL2", "new", "short", "CB"),
    ("DLLR2CIRBNL2", "new", "short", "RB"),
    ("DLLR2CIMBNL2", "new", "short", "RB2"),
    ("DLLR2CICR33", "new", "short", "SK"),
    ("DLLR2CIDBNL3", "new", "long", "DB"),
    ("DLLR2CICBNL3", "new", "long", "CB"),
    ("DLLR2CIRBNL3", "new", "long", "RB"),
    ("DLLR2CIMBNL3", "new", "long", "RB2"),
    ("DLLR2CICR34", "new", "long", "SK"),
    ("DLLR2CIDBST1", "outstanding", "total", "DB"),
    ("DLLR2CIST29", "outstanding", "total", "SUB"),
    ("DLLI2CI@01", "outstanding", "total", "CB"),
    ("DLLI2CI@02", "outstanding", "total", "RB"),
    ("DLLI2CI@03", "outstanding", "total", "RB2"),
    ("DLLR2CIDT29", "outstanding", "total", "TB"),
    ("DLLR2CILB29", "outstanding", "total", "LTCB"),
    ("DLLR2CICR29", "outstanding", "total", "SK"),
    ("DLLR2CIDBST2", "outstanding", "short", "DB"),
    ("DLLR2CIST07", "outstanding", "short", "SUB"),
    ("DLLI2CI@04", "outstanding", "short", "CB"),
    ("DLLI2CI@05", "outstanding", "short", "RB"),
    ("DLLI2CI@06", "outstanding", "short", "RB2"),
    ("DLLR2CIDT07", "outstanding", "short", "TB"),
    ("DLLR2CILB07", "outstanding", "short", "LTCB"),
    ("DLLR2CICR31", "outstanding", "short", "SK"),
    ("DLLR2CIDBST3", "outstanding", "long", "DB"),
    ("DLLR2CIST03", "outstanding", "long", "SUB"),
    ("DLLI2CI@07", "outstanding", "long", "CB"),
    ("DLLI2CI@08", "outstanding", "long", "RB"),
    ("DLLI2CI@09", "outstanding", "long", "RB2"),
    ("DLLR2CIDT03", "outstanding", "long", "TB"),
    ("DLLR2CILB03", "outstanding", "long", "LTCB"),
    ("DLLR2CICR32", "outstanding", "long", "SK"),
    ("DLLR2CIDBST4", "outstanding", "overdraft", "DB"),
    ("DLLR2CIST30", "outstanding", "overdraft", "SUB"),
    ("DLLI2CI@10", "outstanding", "overdraft", "CB"),
    ("DLLI2CI@11", "outstanding", "overdraft", "RB"),
    ("DLLI2CI@12", "outstanding", "overdraft", "RB2"),
    ("DLLR2CIDT30", "outstanding", "overdraft", "TB"),
    ("DLLR2CILB30", "outstanding", "overdraft", "LTCB"),
    ("DLLR2CICR30", "outstanding", "overdraft", "SK"),
    ("DLLR2CIDBLO1", "instrument", "loans", "DB"),
    ("DLLR2CIST02", "instrument", "loans", "SUB"),
    ("DLLI2CI@13", "instrument", "loans", "CB"),
    ("DLLI2CI@14", "instrument", "loans", "RB"),
    ("DLLI2CI@15", "instrument", "loans", "RB2"),
    ("DLLR2CIDT02", "instrument", "loans", "TB"),
    ("DLLR2CILB02", "instrument", "loans", "LTCB"),
    ("DLLR2CICR02", "instrument", "loans", "SK"),
    ("DLLR2CIDBBD1", "instrument", "discounts", "DB"),
    ("DLLR2CIST05", "instrument", "discounts", "SUB"),
    ("DLLI2CI@16", "instrument", "discounts", "CB"),
    ("DLLI2CI@17", "instrument", "discounts", "RB"),
    ("DLLI2CI@18", "instrument", "discounts", "RB2"),
    ("DLLR2CIDT05", "instrument", "discounts", "TB"),
    ("DLLR2CILB05", "instrument", "discounts", "LTCB"),
    ("DLLR2CICR05", "instrument", "discounts", "SK"),
]

FAMILY_NAME = {
    "new": "New loans",
    "outstanding": "Outstanding loans",
    "instrument": "Outstanding loans by instrument",
}
TERM_NAME = {
    "total": "total", "short": "short-term", "long": "long-term",
    "overdraft": "overdrafts", "loans": "loans on deeds", "discounts": "discounted bills",
}
FAMILY_ORDER = {"new": 0, "outstanding": 1, "instrument": 2}
TERM_ORDER = {"total": 0, "short": 1, "long": 2, "overdraft": 3, "loans": 4, "discounts": 5}

# Every rate series is a level in percent — one kind, so the API's kind
# guard has nothing to separate, but the label is what the explorer shows.
KIND = dict((code, "rate") for code, _f, _t, _l in SERIES)

# The lines this dataset is for: what a lender charges on the loans it wrote
# this month. Regional banks are the headline because that is the group the
# Banks page follows.
HEADLINE = "DLLR2CIRBNL1"

DATASET = {
    "slug": "boj-loan-rates",
    "title": "Bank of Japan — Average Contract Interest Rates on Loans",
    "country": "Japan",
    "agency": "Bank of Japan",
    "agency_ja": "日本銀行",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Average contracted interest rates on loans and discounts, in percent "
        "per year, by type of lender — domestically licensed banks, city banks, "
        "regional banks, second-tier regional banks and shinkin banks. Rates on "
        "new loans made in the month (total, short-term, long-term) from October "
        "1993, and on the outstanding loan book at month-end (total, short, long, "
        "overdrafts; loans on deeds and discounted bills) from 1976. Source "
        "database IR04, 'Average Contract Interest Rates on Loans and Discounts'."
    ),
}

SOURCE = {
    "source_id": "boj:IR04",
    "name": ("BOJ Time-Series Data Search — IR04: Average Contract Interest "
             "Rates on Loans and Discounts"),
    "name_ja": "日本銀行 時系列統計データ検索サイト 貸出約定平均金利",
    "url": "https://www.stat-search.boj.or.jp/",
    "license_note": (
        "BOJ Time-Series Data Search API terms: no redistribution "
        "restriction. Two mandatory obligations — display the credit line "
        "(\"%s\") wherever the data appears, including exports, and notify "
        "the BOJ Research and Statistics Department by email when a service "
        "using the API is released." % boj_ts.CREDIT_LINE
    ),
}

DOWNLOAD_URL = boj_ts.data_code_url(DB, [code for code, _f, _t, _l in SERIES])

RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": boj_ts.CREDIT_LINE,
    "main_series": [
        {"role": "headline", "code": HEADLINE,
         "label": "New loans, regional banks", "slot": 1},
        {"role": "city", "code": "DLLR2CICBNL1",
         "label": "New loans, city banks", "slot": 2},
        {"role": "regional2", "code": "DLLR2CIMBNL1",
         "label": "New loans, regional banks II", "slot": 3},
        {"role": "shinkin", "code": "DLLR2CICR35",
         "label": "New loans, shinkin banks", "slot": 4},
    ],
    "overview_tiles": [
        {"key": "new_regional", "type": "level", "code": HEADLINE,
         "label": "New Loans, Regional"},
        {"key": "book_regional", "type": "level", "code": "DLLI2CI@02",
         "label": "Loan Book, Regional"},
        {"key": "new_city", "type": "level", "code": "DLLR2CICBNL1",
         "label": "New Loans, City"},
        {"key": "new_shinkin", "type": "level", "code": "DLLR2CICR35",
         "label": "New Loans, Shinkin"},
    ],
    "kinds": KIND,
    # The month's rates are published about five weeks after month-end
    # (July 2026 landed on 1 September). Allows two missed releases.
    "stale_after_days": 120,
}


def fetch():
    return boj_ts.fetch_bytes(DOWNLOAD_URL)


def _name(family, term, lender):
    return "%s — %s — %s" % (FAMILY_NAME[family], TERM_NAME[term], LENDER_NAME[lender])


def parse(raw_bytes):
    data = boj_ts.parse_getdatacode(raw_bytes)
    series, observations = [], []
    for code, family, term, lender in SERIES:
        if code not in data:
            continue  # validate() reports the complete missing set
        series.append({
            "code": code,
            "name_en": _name(family, term, lender),
            "name_ja": None,
            "unit": "percent",
            "weight_per_10000": None,
            "sort_order": (FAMILY_ORDER[family] * 100 + TERM_ORDER[term] * 10
                           + LENDER_ORDER[lender]),
        })
        for period, value in data[code]["observations"]:
            observations.append({"code": code, "period": period, "value": value})
    return series, observations


def _month_index(d):
    return d.year * 12 + d.month


# The 1976–1978 shinkin book has 32 unpublished months; the modern era
# (October 1993 on, when the domestically-licensed-banks lines begin) is
# gap-free for every live series and is what the coverage gate enforces.
COVERAGE_FROM = datetime.date(1993, 10, 1)
DISCONTINUED = datetime.date(2002, 3, 1)
RATE_FLOOR, RATE_CEILING = 0.0, 15.0


def validate(series, observations):
    expected = set(code for code, _f, _t, _l in SERIES)
    got = set(s["code"] for s in series)
    missing = sorted(expected - got)
    if missing:
        raise ValidationError("series missing from response: %s" % ", ".join(missing))
    if len(observations) < 20000:
        raise ValidationError("only %d observations parsed" % len(observations))

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    latest = max(o["period"] for o in observations)
    for code, _family, _term, lender in SERIES:
        obs = by_code[code]
        lo, hi = min(obs.values()), max(obs.values())
        if lo < RATE_FLOOR or hi > RATE_CEILING:
            raise ValidationError(
                "%s: rate outside %s–%s%% (min %s, max %s)"
                % (code, RATE_FLOOR, RATE_CEILING, lo, hi))
        last = max(obs)
        if lender in ("TB", "LTCB", "SUB"):
            if last != DISCONTINUED:
                raise ValidationError(
                    "%s: a discontinued line now ends %s, not %s" % (code, last, DISCONTINUED))
            continue
        if last != latest:
            raise ValidationError(
                "%s: ends %s while the newest month in the file is %s" % (code, last, latest))
        recent = sorted(p for p in obs if p >= COVERAGE_FROM)
        span = _month_index(recent[-1]) - _month_index(recent[0]) + 1
        if span != len(recent):
            raise ValidationError(
                "%s: gap in monthly coverage since %s (%d months span, %d present)"
                % (code, COVERAGE_FROM, span, len(recent)))

    today = datetime.date.today()
    if (today - latest).days > 120:
        raise ValidationError(
            "latest period %s is implausibly old for a changed file" % latest)

    headline = by_code[HEADLINE]
    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "new_loan_rate_regional_latest_pct": headline[max(headline)],
        "new_loan_rate_city_latest_pct": by_code["DLLR2CICBNL1"][latest],
        "new_loan_rate_shinkin_latest_pct": by_code["DLLR2CICR35"][latest],
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "banking",
    "name": {"en": "Bank of Japan — average contract interest rates on loans",
             "ja": "日本銀行 貸出約定平均金利（業態別）"},
    "shape": "series",
    "summary": ("Average contracted interest rates on loans, in percent per "
                "year, by lender — city, regional, second-tier regional and "
                "shinkin banks — on new loans made in the month (from October "
                "1993) and on the outstanding loan book (from 1976), split "
                "short-term and long-term."),
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
        "as_of_supported": True, "history_from": "1976-01",
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
    "cite": "/banks.html?dataset=boj-loan-rates",
    "page": "/banks.html",
    "notes": [
        "A rate is a level in percent per year. A change in a rate is in "
        "percentage points; the ratio measures (yoy, mom, ann3m) are not "
        "meaningful on a rate and are not offered.",
        "'New loans' is the average rate on loans made during the month; "
        "'outstanding' is the average rate on the whole loan book at month-end. "
        "The new-loan rate moves first when policy rates move; the book follows "
        "as old loans reprice or mature.",
        "The lender groups were re-based at March 2002: the trust-bank, "
        "long-term-credit-bank and sub-total lines end there and are kept as "
        "their own series, never spliced onto the domestically-licensed-banks line.",
        "Shinkin banks' outstanding-rate series have 32 unpublished months in "
        "1976–1978; those gaps are the BOJ's, not this dataset's.",
        "The BOJ's credit line must be displayed wherever the data appears, "
        "including exports.",
    ],
}
