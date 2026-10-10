"""Adapter: Gross Domestic Product — Hong Kong (C&SD), quarterly.

Source: the Census and Statistics Department's web tables (censtatd.py):

- 310-31001  GDP at current market prices and in chained (2024) dollars,
             and the implicit price deflator (2024 = 100);
- 310-31002  GDP by expenditure component at current market prices;
- 310-31003  GDP by expenditure component in chained (2024) dollars.

Quarterly from 1973 Q1, not seasonally adjusted, in HK$ million — exactly as
published. Per capita GDP is published for calendar years only and is not
in this quarterly dataset. A C&SD quarter is published as its last
month (202606 is Q2 2026) and stored, like every quarter on the platform, on
its first month. The component tables' "Total" is GDP itself; it is checked
against 310-31001, not stored twice.

Imports are published as a positive amount that GDP subtracts ("Less:
Imports of goods and services"); they are stored as published. Changes in
inventories cross zero and are served as a flow: a percentage change of them
is refused.

The C&SD publishes seasonally adjusted real GDP only as a quarter-on-quarter
rate; it is not stored here. The calendar-year totals are the four quarters
summed and are not stored either.
"""
import datetime

from . import censtatd
from .censtatd import ValidationError  # noqa: F401 — part of the adapter contract

COMPONENTS = ["FD", "DD", "PCE", "GCE", "GDFCF", "CIV", "XGS", "MGS", "XG", "XS", "MG", "MS"]

TABLES = [
    {"id": "310-31001", "freq": "Q", "sv_order": ["CON", "CUR", "DEF"]},
    {"id": "310-31003", "freq": "Q", "drop_total": True},
    {"id": "310-31002", "freq": "Q", "drop_total": True},
]

DATASET = {
    "slug": "gdp-hk",
    "title": "Gross Domestic Product — Hong Kong (quarterly, by expenditure component)",
    "country": "Hong Kong",
    "agency": censtatd.AGENCY,
    "agency_ja": None,
    "base": "chained (2024) dollars; deflator 2024=100",
    "frequency": "quarterly",
    "description": (
        "Hong Kong's quarterly GDP from the Census and Statistics Department: "
        "nominal and real (chained 2024 dollars) GDP, the implicit price "
        "deflator, and the expenditure components — consumption, "
        "investment, inventories, exports and imports of goods and services — "
        "quarterly from 1973, not seasonally adjusted, in HK$ million as published."
    ),
}

SOURCE = {
    "source_id": "censtatd:310-3100x",
    "name": "C&SD tables 310-31001, 310-31002 and 310-31003 — Gross Domestic Product",
    "name_ja": None,
    "url": censtatd.WEB_TABLE % "310-31001",
    "license_note": censtatd.LICENSE_NOTE,
}

DOWNLOAD_URL = censtatd.table_url("310-31001")
RAW_SUFFIX = ".json"

FLOWS = ("CUR.CIV", "CON.CIV")
KINDS = dict((c, "flow") for c in FLOWS)

PRESENTATION = {
    "credit_line": censtatd.CREDIT,
    # The advance estimate lands about a month after the quarter ends; a
    # quarter dated by its first month is ~215 days old when the next is due.
    "stale_after_days": 230,
    "overview_tiles": [
        {"key": "real", "code": "CON", "label": "Real GDP", "type": "level", "compare_months": 12},
        {"key": "nominal", "code": "CUR", "label": "Nominal GDP", "type": "level",
         "compare_months": 12},
        {"key": "deflator", "code": "DEF", "label": "GDP deflator", "type": "level",
         "compare_months": 12},
        {"key": "consumption", "code": "CON.PCE", "label": "Real private consumption",
         "type": "level", "compare_months": 12},
    ],
    "main_series": [
        {"role": "real", "code": "CON", "label": "Real GDP (chained 2024 dollars)", "slot": 1},
        {"role": "consumption", "code": "CON.PCE", "label": "Private consumption", "slot": 2},
        {"role": "exports", "code": "CON.XGS", "label": "Exports of goods and services", "slot": 3},
    ],
    "kinds": KINDS,
    "kind_default": "level",
}


def fetch():
    return censtatd.fetch([t["id"] for t in TABLES])


canonical_bytes = censtatd.canonical_bytes


# The C&SD's names lead with the table ("GDP components in chained (2024)
# dollars — Private consumption expenditure"); the platform's lead with the
# component and end with the price basis, so a column of them can be scanned.
NAMES = {"CON": "GDP, chained (2024) dollars", "CUR": "GDP, current market prices",
         "DEF": "GDP deflator"}


def _name(spec, sv, stat, part, desc):
    if not part:
        return NAMES.get(sv, stat)
    basis = "chained (2024) dollars" if sv == "CON" else "current market prices"
    return "%s, %s" % (part, basis)


def parse(raw_bytes):
    return censtatd.parse(raw_bytes, TABLES, name_fn=_name)


def validate(series, observations):
    if censtatd.kinds(series, FLOWS) != KINDS:
        raise ValidationError("series kinds changed: %s" % censtatd.kinds(series, FLOWS))
    required = (["CON", "CUR", "DEF"]
                + ["CON." + c for c in COMPONENTS] + ["CUR." + c for c in COMPONENTS])
    if len(series) != len(required):
        raise ValidationError("%d series parsed, expected %d" % (len(series), len(required)))
    flows = set(FLOWS)
    # Levels are positive; only the change in inventories may be negative.
    for o in observations:
        if o["code"] not in flows and o["value"] <= 0:
            raise ValidationError("%s %s: %r is not positive" % (o["code"], o["period"], o["value"]))
    latest = censtatd.check(series, observations, required,
                            first_period=datetime.date(1973, 1, 1), max_age_days=240,
                            ranges={"hkd_million": (-5e6, 5e7), "index": (1.0, 500.0)})
    real = dict((o["period"], o["value"]) for o in observations if o["code"] == "CON")
    year_ago = datetime.date(latest.year - 1, latest.month, 1)
    growth = (None if year_ago not in real else
              round((real[latest] / real[year_ago] - 1) * 100, 1))
    return {"series": len(series), "observations": len(observations),
            "latest_period": latest.isoformat(), "real_gdp_hkd_million": real.get(latest),
            "real_gdp_yoy_pct_calculated": growth}


MANIFEST = censtatd.manifest(
    DATASET, SOURCE, PRESENTATION, section="national-accounts",
    name={"en": "Hong Kong GDP", "ja": "香港国内総生産"},
    summary=("Hong Kong's quarterly GDP — nominal, real (chained 2024 dollars), the "
             "deflator and every expenditure component — from 1973, "
             "not seasonally adjusted, as the Census and Statistics Department "
             "publishes it."),
    page="/hk-economy.html", history_from="1973-01",
    measures=[
        {"id": "index", "label": "Published value — HK$ million; the deflator 2024 = 100",
         "unit": "index", "trust": "official"},
    ],
    notes=[
        "A quarter is dated by its first month: 2026-04 is Q2 2026, which the "
        "C&SD publishes as 202606.",
        "Not seasonally adjusted: compare a quarter with the same quarter a year "
        "earlier. The C&SD's seasonally adjusted real GDP is published only as a "
        "quarter-on-quarter rate and is not stored.",
        "Imports are positive amounts that GDP subtracts, as published. Changes in "
        "inventories cross zero; a percentage change of them is refused.",
    ])
