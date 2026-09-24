"""Adapter: US average hourly and weekly earnings (BLS Current Employment
Statistics), nominal and real.

Source: U.S. Bureau of Labor Statistics, Current Employment Statistics (the
payroll survey behind the monthly jobs report) — flat files at
download.bls.gov/pub/time.series/ce/ (see bls_flat.py). For total private,
goods-producing and private service-providing industries:

    average hourly earnings, all employees                (from March 2006)
    average weekly earnings, all employees                (from March 2006)
    average hourly earnings, production and nonsupervisory (from 1964)
    average weekly earnings, production and nonsupervisory (from 1964)

each in current dollars and in constant 1982-84 dollars ("real earnings",
which the BLS deflates by the CPI-U for all employees and the CPI-W for
production and nonsupervisory employees), seasonally adjusted and not.
Codes are the BLS series ids — CES0500000003 is average hourly earnings of
all private employees, seasonally adjusted, the headline wage figure.

The real series are the BLS's own. This platform does not deflate anything:
a real-wage figure here is exactly the one the BLS publishes.

**Revised, twice.** Each month's estimate is revised in each of the next two
releases as more payroll reports arrive, and every February the whole series
is re-benchmarked to unemployment-insurance tax records. Each revision is a
new vintage here, so the first-print figure stays retrievable with as_of.
"""
import datetime

from . import bls_flat


class ValidationError(Exception):
    pass


DATASET = {
    "slug": "us-wages",
    "title": "US Average Hourly and Weekly Earnings (BLS Current Employment Statistics)",
    "country": "United States",
    "agency": "U.S. Bureau of Labor Statistics",
    "agency_ja": None,
    "base": None,
    "frequency": "monthly",
    "description": (
        "Average hourly and weekly earnings of private-sector employees from "
        "the BLS payroll survey — all employees from 2006, production and "
        "nonsupervisory employees from 1964 — for total private, "
        "goods-producing and service-providing industries, in current dollars "
        "and in 1982-84 dollars (the BLS's real earnings), seasonally adjusted "
        "and not. Revised for two months after release and re-benchmarked "
        "every February; each revision is a new vintage."
    ),
}

SOURCE = {
    "source_id": "bls:ce:earnings",
    "name": "BLS Current Employment Statistics — hours and earnings, private industries",
    "name_ja": None,
    "url": "https://www.bls.gov/ces/",
    "license_note": ("Work of the United States Government, in the public domain "
                     "(17 U.S.C. §105). Cite the Bureau of Labor Statistics as the source."),
}

DOWNLOAD_URL = bls_flat.BASE + "ce/"
RAW_SUFFIX = ".zip"

META_FILES = ["ce.series"]
DATA_FILES = ["ce.data.05b.TotalPrivate.AllEmployeeHoursAndEarnings",
              "ce.data.05c.TotalPrivate.ProductionEmployeeHoursAndEarnings"]

# total private, goods-producing, private service-providing
INDUSTRIES = ("05000000", "06000000", "08000000")
# data type -> unit. 03/11 all-employee hourly/weekly, 08/30 production and
# nonsupervisory; 13/12 and 32/31 the same in 1982-84 dollars.
DATA_TYPES = {"03": "usd", "11": "usd", "08": "usd", "30": "usd",
              "13": "usd_1982_84", "12": "usd_1982_84",
              "32": "usd_1982_84", "31": "usd_1982_84"}

TILES = [
    ("ahe", "CES0500000003", "Hourly, all employees"),
    ("ahe_real", "CES0500000013", "Hourly, real (1982-84 $)"),
    ("ahe_pne", "CES0500000008", "Hourly, production workers"),
    ("awe", "CES0500000011", "Weekly, all employees"),
]

PRESENTATION = {
    "credit_line": "Source: U.S. Bureau of Labor Statistics.",
    "stale_after_days": 70,        # the jobs report lands in the first week
    "overview_tiles": [{"key": k, "code": c, "label": l, "type": "level"}
                       for k, c, l in TILES],
    "main_series": [{"role": k, "code": c, "label": l, "slot": i + 1}
                    for i, (k, c, l) in enumerate(TILES)],
}


def fetch():
    files = {}
    for name in META_FILES + DATA_FILES:
        files[name] = bls_flat.fetch_file("ce", name)
    return bls_flat.bundle(files)


def _wanted(row):
    sid = row.get("series_id", "")
    return (len(sid) == 13 and sid[2] in "SU"
            and row.get("industry_code") in INDUSTRIES
            and row.get("data_type_code") in DATA_TYPES)


def parse(raw_bytes):
    try:
        files = bls_flat.unbundle(raw_bytes)
    except Exception as exc:
        raise ValidationError("not a BLS bundle: %s" % exc)
    if "ce.series" not in files:
        raise ValidationError("bundle is missing ce.series")
    chosen = dict((r["series_id"], r) for r in bls_flat.read_table(files["ce.series"])
                  if _wanted(r))
    values = {}
    for name in DATA_FILES:
        if name not in files:
            raise ValidationError("bundle is missing %s" % name)
        bls_flat.read_values(files[name], chosen, name, ValidationError, into=values)

    order = list(DATA_TYPES)

    def key(sid):
        r = chosen[sid]
        # industry, then SA before NSA, then the data type order above
        return (INDUSTRIES.index(r["industry_code"]), sid[2] != "S",
                order.index(r["data_type_code"]))

    series, observations = [], []
    for sid in sorted(chosen, key=key):
        vals = values.get(sid)
        if not vals:
            continue
        r = chosen[sid]
        title = r["series_title"]
        series.append({
            "code": sid, "name_en": title[:1].upper() + title[1:], "name_ja": None,
            "unit": DATA_TYPES[r["data_type_code"]], "weight_per_10000": None,
            "sort_order": len(series),
        })
        for period in sorted(vals):
            observations.append({"code": sid, "period": period, "value": vals[period]})
    return series, observations


def validate(series, observations):
    if len(series) < 40:
        raise ValidationError("only %d series parsed" % len(series))
    codes = set(s["code"] for s in series)
    missing = [c for _k, c, _l in TILES if c not in codes]
    if missing:
        raise ValidationError("headline series missing: %s" % ", ".join(missing))
    latest, first = None, None
    last_by = {}
    for o in observations:
        v, code = o["value"], o["code"]
        weekly = code[-2:] in ("11", "12", "30", "31")
        # Hourly earnings run from ~$2 (1964) to the $30s; weekly to ~$1,500.
        hi = 5000.0 if weekly else 200.0
        if not (0.5 < v < hi):
            raise ValidationError("%s %s: %r out of range" % (code, o["period"], v))
        p = o["period"]
        latest = p if latest is None or p > latest else latest
        first = p if first is None or p < first else first
        if p > last_by.get(code, datetime.date.min):
            last_by[code] = p
    if first > datetime.date(1964, 1, 1):
        raise ValidationError("history starts %s, expected 1964" % first)
    for _k, c, _l in TILES:
        if last_by.get(c) != latest:
            raise ValidationError("%s ends %s but the release runs to %s"
                                  % (c, last_by.get(c), latest))
    last = dict((o["code"], o["value"]) for o in observations if o["period"] == latest)
    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "ahe_all_employees_sa": last.get("CES0500000003"),
        "real_ahe_sa": last.get("CES0500000013"),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "prices",
    "name": {"en": "US average hourly and weekly earnings", "ja": "米国平均時給・週給"},
    "shape": "series",
    "summary": ("What US private-sector workers earn per hour and per week, in "
                "current and 1982-84 dollars — all employees from 2006, "
                "production and nonsupervisory from 1964 — from the BLS payroll "
                "survey, monthly."),
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
        "as_of_supported": True, "history_from": "1964-01",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Earnings, US dollars (current or 1982-84, per the series)",
         "unit": "USD", "trust": "official"},
        {"id": "yoy", "label": "Year over year", "unit": "%", "trust": "derived",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
        {"id": "mom", "label": "Month over month", "unit": "%", "trust": "derived",
         "calc": "(value[t] / value[t−1 month] − 1) × 100, from published values."},
        {"id": "ann3m", "label": "3-month annualized", "unit": "%", "trust": "derived",
         "calc": "((value[t] / value[t−3 months]) ^ 4 − 1) × 100, from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "summary": "/api/v1/%s/overview" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search", "summary"],
    "cite": "/us-wages.html",
    "page": "/us-wages.html",
    "notes": [
        "Real earnings (1982-84 dollars) are the BLS's own series, deflated by "
        "the BLS with the CPI-U (all employees) or CPI-W (production and "
        "nonsupervisory). Nothing is deflated by this platform.",
        "Codes are BLS series ids: CES = seasonally adjusted, CEU = not; "
        "05 total private, 06 goods-producing, 08 private service-providing.",
        "All-employee series begin in March 2006; production and "
        "nonsupervisory series in January 1964.",
        "Each month is revised in the next two releases and the whole series "
        "is re-benchmarked every February; each revision is a new vintage and "
        "the first print stays retrievable with as_of.",
    ],
}
