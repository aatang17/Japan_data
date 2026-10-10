"""Adapter: published CPI rates — Hong Kong (C&SD).

The rates of Hong Kong's CPI that the stored index levels (cpi-hk) cannot
reproduce, kept exactly as the Census and Statistics Department publishes
them, in percent (censtatd.py):

- 510-60001 / 510-60002  the year-on-year rate of the Composite CPI, CPI(A),
             (B), (C) and their underlying counterparts. Across each rebasing
             year (Oct 2009 – Sep 2010, Oct 2014 – Sep 2015, Oct 2019 – Sep
             2020) the C&SD computed these on the old basket, so the rate
             calculated from the linked index differs by up to 0.8 pp
             (underlying inflation, June 2020: published 1.2%, calculated
             2.0%). These are the official inflation rates.
- 510-60004  the seasonally adjusted series, published only as the average
             monthly rate of change over the latest three months — no
             seasonally adjusted index level exists — monthly from 1981.

Every value is a rate in percent; its change is read in percentage points.
"""
import datetime

from . import censtatd
from .censtatd import ValidationError  # noqa: F401 — part of the adapter contract

HEADLINE = ["CC_CM_1920", "A_CM_1920", "B_CM_1920", "C_CM_1920"]
YOY = {"Year-on-year % change": "yoy"}
SA = ["SCC_CM", "SA_CM", "SB_CM", "SC_CM"]
TABLES = [
    {"id": "510-60001", "freq": "M", "changes": YOY, "sv_order": HEADLINE},
    {"id": "510-60002", "freq": "M", "changes": YOY, "sv_order": ["U" + c for c in HEADLINE]},
    {"id": "510-60004", "freq": "M", "rates_of_change": True, "sv_order": SA},
]
CODES = ([c + ".yoy" for c in HEADLINE] + ["U" + c + ".yoy" for c in HEADLINE] + SA)

DATASET = {
    "slug": "cpi-hk-rates",
    "title": "Consumer Price Indices, published rates — Hong Kong (year-on-year, seasonally adjusted)",
    "country": "Hong Kong",
    "agency": censtatd.AGENCY,
    "agency_ja": None,
    "base": None,
    "frequency": "monthly",
    "description": (
        "Hong Kong's official CPI inflation rates as the Census and Statistics "
        "Department publishes them: the year-on-year change of the Composite CPI, "
        "CPI(A), (B), (C) and their underlying counterparts, and the seasonally "
        "adjusted average monthly change over the latest three months — in "
        "percent, monthly."
    ),
}

SOURCE = {
    "source_id": "censtatd:510-6000x-rates",
    "name": "C&SD tables 510-60001, 510-60002 and 510-60004 — Consumer Price Indices, rates",
    "name_ja": None,
    "url": censtatd.WEB_TABLE % "510-60001",
    "license_note": censtatd.LICENSE_NOTE,
}

DOWNLOAD_URL = censtatd.table_url("510-60001")
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": censtatd.CREDIT,
    "stale_after_days": 95,   # as cpi-hk: released ~3 weeks after the month
    "overview_tiles": [
        {"key": "composite", "code": "CC_CM_1920.yoy", "label": "Composite CPI, YoY",
         "type": "level"},
        {"key": "underlying", "code": "UCC_CM_1920.yoy", "label": "Underlying Composite CPI, YoY",
         "type": "level"},
        {"key": "a", "code": "A_CM_1920.yoy", "label": "CPI(A), YoY", "type": "level"},
        {"key": "sa", "code": "SCC_CM", "label": "SA Composite CPI, 3-month avg",
         "type": "level"},
    ],
    "main_series": [
        {"role": "composite", "code": "CC_CM_1920.yoy", "label": "Composite CPI, YoY", "slot": 1},
        {"role": "underlying", "code": "UCC_CM_1920.yoy", "label": "Underlying Composite CPI, YoY",
         "slot": 2},
    ],
    # Every value is already a rate in percent; a percentage change of it is refused.
    "kind_default": "rate",
}


def fetch():
    return censtatd.fetch([t["id"] for t in TABLES])


canonical_bytes = censtatd.canonical_bytes


def _name(spec, sv, stat, part, desc):
    if spec["id"] == "510-60004":
        return "%s: average monthly change over the latest 3 months" % censtatd.cpi_short(stat)
    return "%s: year-on-year change (as published)" % censtatd.cpi_short(stat)


def parse(raw_bytes):
    return censtatd.parse(raw_bytes, TABLES, name_fn=_name)


def validate(series, observations):
    if sorted(s["code"] for s in series) != sorted(CODES):
        raise ValidationError("series %s, expected %s" % (sorted(s["code"] for s in series), CODES))
    # Hong Kong's CPI rose 15% a year at its 1980 peak; beyond ±60 is a
    # column read wrongly.
    latest = censtatd.check(series, observations, CODES,
                            first_period=datetime.date(1975, 7, 1), max_age_days=150,
                            ranges={"percent": (-60.0, 60.0)})
    v = dict(((o["code"], o["period"]), o["value"]) for o in observations)
    return {"series": len(series), "observations": len(observations),
            "latest_period": latest.isoformat(),
            "composite_yoy_pct": v.get(("CC_CM_1920.yoy", latest)),
            "underlying_yoy_pct": v.get(("UCC_CM_1920.yoy", latest))}


MANIFEST = censtatd.manifest(
    DATASET, SOURCE, PRESENTATION, section="prices",
    name={"en": "Hong Kong CPI — published rates", "ja": "香港消費者物価指数（公表上昇率）"},
    summary=("Hong Kong's official CPI inflation rates as the C&SD publishes them — "
             "year-on-year for the Composite CPI, CPI(A), (B), (C) and the underlying "
             "indices, and the seasonally adjusted three-month average monthly change "
             "— in percent, monthly."),
    page="/hk-prices.html", cite="/hk-prices.html?dataset=cpi-hk-rates", history_from="1975-07",
    measures=[
        {"id": "index", "label": "Rate in percent, as published", "unit": "%", "trust": "official"},
    ],
    notes=[
        "These are the official rates. A year-on-year rate calculated from the "
        "index levels in cpi-hk can differ by up to 0.8 pp across the rebasing "
        "years (Oct 2009 – Sep 2010, Oct 2014 – Sep 2015, Oct 2019 – Sep 2020), "
        "when the C&SD computed the rate on the old basket.",
        "The seasonally adjusted series exist only as this rate: the C&SD releases "
        "no seasonally adjusted index level.",
        "Every value is a rate in percent; its change is read in percentage points "
        "and a percentage change of it is refused.",
    ])
