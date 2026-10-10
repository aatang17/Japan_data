"""Adapter: labour force, employment and unemployment — Hong Kong (C&SD).

Source: C&SD web table 210-06101 (censtatd.py), from the General Household
Survey: the labour force, employed, unemployed and underemployed persons in
thousands, the participation, unemployment and underemployment rates, each
for both sexes, men and women, and the seasonally adjusted unemployment rate
— monthly from the period ending March 1985.

Every figure is for a ROLLING THREE-MONTH period, which the C&SD labels by
its last month and the platform dates the same way: 2026-08 is June–August
2026. Consecutive months share two of their three months, so a one-month
change is mostly overlap; compare with the period three months earlier, or a
year earlier.
"""
import datetime

from . import censtatd
from .censtatd import ValidationError  # noqa: F401 — part of the adapter contract

ORDER = ["SAUR", "UR", "UDR", "LFPR", "LF", "EM", "UE", "UDE"]
TABLES = [{"id": "210-06101", "freq": "M3M", "sv_order": ORDER}]

DATASET = {
    "slug": "labour-hk",
    "title": "Labour force and unemployment — Hong Kong (rolling 3-month periods)",
    "country": "Hong Kong",
    "agency": censtatd.AGENCY,
    "agency_ja": None,
    "base": None,
    "frequency": "monthly",
    "description": (
        "Hong Kong's labour force, employment, unemployment and underemployment "
        "from the Census and Statistics Department's General Household Survey: "
        "counts in thousands and rates in percent, by sex, plus the seasonally "
        "adjusted unemployment rate — for rolling three-month periods, monthly "
        "from 1985."
    ),
}

SOURCE = {
    "source_id": "censtatd:210-06101",
    "name": "C&SD table 210-06101 — Labour force, employment, unemployment and underemployment",
    "name_ja": None,
    "url": censtatd.WEB_TABLE % "210-06101",
    "license_note": censtatd.LICENSE_NOTE,
}

DOWNLOAD_URL = censtatd.table_url("210-06101")
RAW_SUFFIX = ".json"

RATES = ["SAUR", "UR", "UR.M", "UR.F", "UDR", "UDR.M", "UDR.F", "LFPR", "LFPR.M", "LFPR.F"]
KINDS = dict((c, "rate") for c in RATES)

PRESENTATION = {
    "credit_line": censtatd.CREDIT,
    "stale_after_days": 95,   # released ~3 weeks after the period's last month
    "overview_tiles": [
        {"key": "saur", "code": "SAUR", "label": "Unemployment rate (seasonally adjusted)",
         "type": "level", "compare_months": 3},
        {"key": "udr", "code": "UDR", "label": "Underemployment rate", "type": "level",
         "compare_months": 12},
        {"key": "lfpr", "code": "LFPR", "label": "Participation rate", "type": "level",
         "compare_months": 12},
        {"key": "em", "code": "EM", "label": "Employed persons", "type": "level",
         "compare_months": 12},
    ],
    "main_series": [
        {"role": "saur", "code": "SAUR", "label": "Unemployment rate (seasonally adjusted)",
         "slot": 1},
        {"role": "udr", "code": "UDR", "label": "Underemployment rate", "slot": 2},
    ],
    "kinds": KINDS,
    "kind_default": "level",
}


def fetch():
    return censtatd.fetch([t["id"] for t in TABLES])


canonical_bytes = censtatd.canonical_bytes


def _name(spec, sv, stat, part, desc):
    who = {"Male": "men", "Female": "women"}.get(part)
    return "%s%s — 3 months to the month shown" % (stat, ", " + who if who else "")


def parse(raw_bytes):
    return censtatd.parse(raw_bytes, TABLES, name_fn=_name)


def validate(series, observations):
    if censtatd.kinds(series) != KINDS:
        raise ValidationError("series kinds changed: %s" % censtatd.kinds(series))
    if len(series) != 22:
        raise ValidationError("%d series parsed, expected 22" % len(series))
    latest = censtatd.check(series, observations, ["SAUR", "UR", "UDR", "LFPR", "LF", "EM",
                                                   "UE", "UDE"],
                            first_period=datetime.date(1985, 3, 1), max_age_days=150,
                            ranges={"percent": (0.0, 100.0), "persons_1000": (0.0, 10000.0)})
    sa = dict((o["period"], o["value"]) for o in observations if o["code"] == "SAUR")
    return {"series": len(series), "observations": len(observations),
            "latest_period": latest.isoformat(), "unemployment_rate_sa": sa.get(latest)}


MANIFEST = censtatd.manifest(
    DATASET, SOURCE, PRESENTATION, section="labour",
    name={"en": "Hong Kong labour force and unemployment", "ja": "香港労働力・失業率"},
    summary=("Hong Kong's labour force, employment, unemployment and "
             "underemployment — counts and rates by sex, and the seasonally adjusted "
             "unemployment rate — for rolling three-month periods, monthly from 1985."),
    page="/hk-economy.html", cite="/hk-economy.html?dataset=labour-hk", history_from="1985-03",
    measures=[
        {"id": "index", "label": "Published value — rates in percent, counts in thousands of "
                                 "persons",
         "unit": "index", "trust": "official"},
    ],
    notes=[
        "Every figure is for a rolling three-month period, dated by its last month: "
        "2026-08 is June–August 2026. Neighbouring months share two months of data.",
        "Rates are in percent; their change is read in percentage points, and a "
        "percentage change of a rate is refused.",
    ])
