"""Adapter: retail sales — Hong Kong (C&SD), monthly.

Source: the Census and Statistics Department's web tables (censtatd.py):

- 620-67001  total retail sales: the value in HK$ million, the value index
             and the volume index (the value with price changes removed);
- 620-67002  the value and value index by type of retail outlet — 24 types,
             with sub-types nested under their parents.

Monthly from October 2004, as published. Outlet type 49, "Supermarkets and
supermarket sections of department stores", is a memo line the C&SD prints
across two other types; it is stored as published and is not part of any sum.
The outlet table's "Total" is checked against 620-67001, not stored twice.
"""
import datetime

from . import censtatd
from .censtatd import ValidationError  # noqa: F401 — part of the adapter contract

TABLES = [
    {"id": "620-67001", "freq": "M", "sv_order": ["VOL_IDX_RS", "VAL_IDX_RS", "VAL_RS"]},
    {"id": "620-67002", "freq": "M", "drop_total": True, "sv_order": ["VAL_RS", "VAL_IDX_RS"]},
]

DATASET = {
    "slug": "retail-hk",
    "title": "Retail sales — Hong Kong (value, volume, by type of outlet)",
    "country": "Hong Kong",
    "agency": censtatd.AGENCY,
    "agency_ja": None,
    "base": None,
    "frequency": "monthly",
    "description": (
        "Hong Kong's monthly retail sales from the Census and Statistics "
        "Department: the total value in HK$ million, the value and volume "
        "indices, and the value by type of retail outlet — jewellery and "
        "watches, department stores, supermarkets, medicines and cosmetics "
        "and more — monthly from October 2004."
    ),
}

SOURCE = {
    "source_id": "censtatd:620-6700x",
    "name": "C&SD tables 620-67001 and 620-67002 — Retail sales",
    "name_ja": None,
    "url": censtatd.WEB_TABLE % "620-67001",
    "license_note": censtatd.LICENSE_NOTE,
}

DOWNLOAD_URL = censtatd.table_url("620-67001")
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": censtatd.CREDIT,
    "stale_after_days": 100,  # released ~5 weeks after the month
    "overview_tiles": [
        {"key": "volume", "code": "VOL_IDX_RS", "label": "Retail sales volume index",
         "type": "level", "compare_months": 12},
        {"key": "value", "code": "VAL_RS", "label": "Retail sales value", "type": "level",
         "compare_months": 12},
        {"key": "jewellery", "code": "VAL_RS.32", "label": "Jewellery and watches",
         "type": "level", "compare_months": 12},
        {"key": "medicine", "code": "VAL_RS.39", "label": "Medicines and cosmetics",
         "type": "level", "compare_months": 12},
    ],
    "main_series": [
        {"role": "volume", "code": "VOL_IDX_RS", "label": "Volume index", "slot": 1},
        {"role": "value", "code": "VAL_IDX_RS", "label": "Value index", "slot": 2},
    ],
    "kind_default": "level",
}


def fetch():
    return censtatd.fetch([t["id"] for t in TABLES])


canonical_bytes = censtatd.canonical_bytes


def parse(raw_bytes):
    return censtatd.parse(raw_bytes, TABLES)


def validate(series, observations):
    if len(series) != 51:
        raise ValidationError("%d series parsed, expected 51 (3 totals, 2 × 24 outlet types)"
                              % len(series))
    latest = censtatd.check(series, observations,
                            ["VOL_IDX_RS", "VAL_IDX_RS", "VAL_RS", "VAL_RS.32", "VAL_RS.39"],
                            first_period=datetime.date(2004, 10, 1), max_age_days=150,
                            ranges={"hkd_million": (0.0, 1e6), "index": (0.0, 1000.0)})
    vol = dict((o["period"], o["value"]) for o in observations if o["code"] == "VOL_IDX_RS")
    return {"series": len(series), "observations": len(observations),
            "latest_period": latest.isoformat(), "volume_index": vol.get(latest)}


MANIFEST = censtatd.manifest(
    DATASET, SOURCE, PRESENTATION, section="corporate",
    name={"en": "Hong Kong retail sales", "ja": "香港小売売上高"},
    summary=("Hong Kong's monthly retail sales — total value, value and volume "
             "indices, and value by type of outlet — from October 2004, as the "
             "Census and Statistics Department publishes them."),
    page="/hk-economy.html", cite="/hk-economy.html?dataset=retail-hk", history_from="2004-10",
    measures=[
        {"id": "index", "label": "Published value — HK$ million, or an index",
         "unit": "index", "trust": "official"},
    ],
    notes=[
        "The volume index is the value with price changes removed: the measure of "
        "how much was bought, not what it cost.",
        "Outlet type 49 (supermarkets and supermarket sections of department stores) "
        "is a memo line overlapping two other types; it is not part of any sum.",
    ])
