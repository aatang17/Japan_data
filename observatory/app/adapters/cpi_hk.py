"""Adapter: Consumer Price Indices — Hong Kong (C&SD).

Source: the Census and Statistics Department's web tables, read through its
keyless API (censtatd.py):

- 510-60001  the Composite CPI (monthly from October 1980) and CPI(A),
             CPI(B), CPI(C) (from July 1974);
- 510-60002  the underlying indices — the same four, netting out the effects
             of the government's one-off relief measures — monthly from 2007;
- 510-60003  the four indices by COICOP division (thirteen divisions) —
             monthly from 2005. Its "Total" repeats 510-60001 and is checked
             against it, not loaded twice.

CPI(A), (B) and (C) cover households in the lowest, middle and highest
expenditure ranges (some 50%, 30% and 10% of households, by the C&SD's
table note); the Composite aggregates them, and its year-on-year change is,
in the C&SD's words, "generally taken to reflect overall consumer price
inflation". Every index is on the October 2019 – September 2020 = 100
base, as published, to one decimal.

The underlying indices remove a swing that is policy, not prices: a one-off
rates waiver or electricity subsidy lowers what households pay in the month
it applies and raises it again when it lapses. Both are stored as published.

The official year-on-year rates and the seasonally adjusted series are
cpi-hk-rates: across each rebasing year the C&SD computed its rate on the old
basket, so a rate calculated from these linked levels can differ from the
official one by up to 0.8 pp (see cpi-hk-rates).
"""
import datetime

from . import bls_cpi, censtatd
from .censtatd import ValidationError  # noqa: F401 — part of the adapter contract

ORDER = ["CC_CM_1920", "A_CM_1920", "B_CM_1920", "C_CM_1920"]
TABLES = [
    {"id": "510-60001", "freq": "M", "sv_order": ORDER},
    {"id": "510-60002", "freq": "M", "sv_order": ["U" + c for c in ORDER]},
    {"id": "510-60003", "freq": "M", "drop_total": True, "sv_order": ORDER},
]

DATASET = {
    "slug": "cpi-hk",
    "title": "Consumer Price Indices — Hong Kong (composite, A/B/C, underlying, by division)",
    "country": "Hong Kong",
    "agency": censtatd.AGENCY,
    "agency_ja": None,
    "base": "Oct 2019–Sep 2020=100",
    "frequency": "monthly",
    "description": (
        "Hong Kong's Consumer Price Indices from the Census and Statistics "
        "Department: CPI(A), (B), (C) monthly from 1974 and the Composite from 1980, "
        "the underlying indices (net of one-off government relief) from 2007, "
        "and all four by the thirteen COICOP divisions from 2005. Index levels "
        "as published, October 2019 – September 2020 = 100."
    ),
}

SOURCE = {
    "source_id": "censtatd:510-6000x",
    "name": "C&SD tables 510-60001, 510-60002 and 510-60003 — Consumer Price Indices",
    "name_ja": None,
    "url": censtatd.WEB_TABLE % "510-60001",
    "license_note": censtatd.LICENSE_NOTE,
}

DOWNLOAD_URL = censtatd.table_url("510-60001")
RAW_SUFFIX = ".json"

HEADLINE = "CC_CM_1920"
UNDERLYING = "UCC_CM_1920"
DIVISIONS = [str(i) for i in range(1, 14)]

PRESENTATION = {
    "measure_type": "index",
    "main_series": [
        {"role": "headline", "code": HEADLINE, "label": "Composite CPI", "slot": 1},
        {"role": "underlying", "code": UNDERLYING, "label": "Underlying Composite CPI", "slot": 2},
        {"role": "food", "code": "CC_CM_1920.1", "label": "Food", "slot": 3},
        {"role": "housing", "code": "CC_CM_1920.4", "label": "Housing", "slot": 4},
    ],
    "group_codes": ["CC_CM_1920." + d for d in DIVISIONS],
    "credit_line": censtatd.CREDIT,
    # A month is dated by its first day and released about three weeks after
    # it ends: the newest month is ~80 days old the day before the next one.
    "stale_after_days": 95,
}


def fetch():
    return censtatd.fetch([t["id"] for t in TABLES])


canonical_bytes = censtatd.canonical_bytes


def _name(spec, sv, stat, part, desc):
    return censtatd.cpi_short(stat) + (" — " + part if part else "")


def parse(raw_bytes):
    return censtatd.parse(raw_bytes, TABLES, name_fn=_name)


def validate(series, observations):
    required = ([m["code"] for m in PRESENTATION["main_series"]] + PRESENTATION["group_codes"]
                + ["A_CM_1920", "B_CM_1920", "C_CM_1920",
                   "UA_CM_1920", "UB_CM_1920", "UC_CM_1920"])
    if len(series) != 60:
        raise ValidationError("%d series parsed, expected 60 (4 headline, 4 underlying, "
                              "4 × 13 divisions)" % len(series))
    latest = censtatd.check(series, observations, required,
                            first_period=datetime.date(1974, 7, 1), max_age_days=150,
                            ranges={"index": (0.5, 1000.0)})
    head = dict((o["period"], o["value"]) for o in observations if o["code"] == HEADLINE)
    under = dict((o["period"], o["value"]) for o in observations if o["code"] == UNDERLYING)
    return {"series": len(series), "observations": len(observations),
            "latest_period": latest.isoformat(),
            "composite_index": head.get(latest), "underlying_composite_index": under.get(latest)}


MANIFEST = censtatd.manifest(
    DATASET, SOURCE, PRESENTATION, section="prices",
    name={"en": "Hong Kong Consumer Price Indices", "ja": "香港消費者物価指数"},
    summary=("Hong Kong's CPI(A), (B), (C) from 1974 and Composite CPI from 1980, the "
             "underlying indices net of one-off government relief from 2007, and "
             "all four by the thirteen COICOP divisions from 2005 — monthly index "
             "levels as the Census and Statistics Department publishes them."),
    page="/hk-prices.html", history_from="1974-07",
    measures=[
        {"id": "index", "label": "Index level (October 2019 – September 2020 = 100)",
         "unit": "index", "trust": "official"},
        {"id": "yoy", "label": "Year over year", "unit": "%", "trust": "derived",
         "calc": bls_cpi.CALC_YOY},
        {"id": "mom", "label": "Month over month", "unit": "%", "trust": "derived",
         "calc": bls_cpi.CALC_MOM},
        {"id": "ann3m", "label": "3-month annualized", "unit": "%", "trust": "derived",
         "calc": bls_cpi.CALC_ANN3M},
    ],
    notes=[
        "The Composite CPI's year-on-year change is, in the C&SD's words, "
        "'generally taken to reflect overall consumer price inflation'. The "
        "underlying indices net out the effects of the government's one-off "
        "relief measures.",
        "CPI(A), (B) and (C) cover households in the relatively low, medium and "
        "relatively high expenditure ranges — some 50%, 30% and 10% of "
        "households; the Composite aggregates them.",
        "Not seasonally adjusted. The C&SD's seasonally adjusted series are rates "
        "of change only: see cpi-hk-rates.",
        "A year-on-year rate calculated from these levels can differ from the "
        "C&SD's official rate by up to 0.8 pp across the rebasing years (Oct 2009 – "
        "Sep 2010, Oct 2014 – Sep 2015, Oct 2019 – Sep 2020), and by more than "
        "0.1 pp in some 1980s months, when the index stood near 20 and one "
        "decimal is a coarse step. The official rates are in cpi-hk-rates.",
    ])
