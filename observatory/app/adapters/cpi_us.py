"""Adapter: US CPI-U, U.S. city average, not seasonally adjusted.

Source: U.S. Bureau of Labor Statistics, Consumer Price Index for All Urban
Consumers, flat files at download.bls.gov/pub/time.series/cu/ (see
bls_cpi.py for what is carried and what is left out). Every published item
and aggregate for the nation — all items, the cores, the eight major groups,
and each item down to eggs, rent of primary residence and motor vehicle
insurance — monthly, all items from January 1913.

Not seasonally adjusted, like the headline 12-month rate the BLS announces;
the seasonally adjusted cut, for month-on-month readings, is cpi-us-sa.
"""
import datetime

from . import bls_cpi
from .bls_cpi import ValidationError  # noqa: F401 — part of the adapter contract

DATASET = {
    "slug": "cpi-us",
    "title": "Consumer Price Index — United States (CPI-U, all items and categories)",
    "country": "United States",
    "agency": bls_cpi.AGENCY,
    "agency_ja": None,
    "base": bls_cpi.BASE,
    "frequency": "monthly",
    "description": (
        "Official CPI for All Urban Consumers (CPI-U), U.S. city average, not "
        "seasonally adjusted: all items, the cores, the eight major groups and "
        "every published item (about 400 series), monthly — all items from "
        "January 1913. Index levels as published by the Bureau of Labor Statistics."
    ),
}

SOURCE = {
    "source_id": "bls:cu:us-nsa",
    "name": "BLS Consumer Price Index for All Urban Consumers (CPI-U), U.S. city average, not seasonally adjusted",
    "name_ja": None,
    "url": bls_cpi.SOURCE_PAGE,
    "license_note": bls_cpi.LICENSE_NOTE,
}

DOWNLOAD_URL = bls_cpi.bls_flat.BASE + "cu/"
RAW_SUFFIX = ".zip"

HEADLINE = "CUUR0000SA0"

PRESENTATION = {
    "measure_type": "index",
    "main_series": [
        {"role": "headline", "code": "CUUR0000SA0", "label": "Headline CPI", "slot": 1},
        {"role": "core", "code": "CUUR0000SA0L1E",
         "label": "Core CPI (less food and energy)", "slot": 2},
        {"role": "food", "code": "CUUR0000SAF1", "label": "Food", "slot": 3},
        {"role": "energy", "code": "CUUR0000SA0E", "label": "Energy", "slot": 4},
    ],
    "group_codes": ["CUUR0000" + i for i in bls_cpi.GROUP_ITEMS],
    "credit_line": bls_cpi.CREDIT,
    "stale_after_days": bls_cpi.STALE_AFTER_DAYS,
}


def fetch():
    return bls_cpi.fetch(bls_cpi.US_FILES)


def parse(raw_bytes):
    return bls_cpi.parse(
        raw_bytes,
        select=lambda r: r["area_code"] == "0000" and r["seasonal"] == "U",
        name_fn=lambda item, area: item,
        sort_fn=lambda item, area: int(item["sort_sequence"] or 0))


def validate(series, observations):
    latest = bls_cpi.check(
        series, observations, min_series=350, min_observations=150000,
        required=[m["code"] for m in PRESENTATION["main_series"]]
                 + PRESENTATION["group_codes"],
        first_period=datetime.date(1913, 1, 1))
    head = dict((o["period"], o["value"]) for o in observations if o["code"] == HEADLINE)
    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "headline_index": head.get(latest),
    }


MANIFEST = bls_cpi.manifest(
    DATASET, SOURCE, PRESENTATION,
    name={"en": "US Consumer Price Index — categories", "ja": "米国消費者物価指数（品目別）"},
    summary=("US CPI for All Urban Consumers, U.S. city average, not seasonally "
             "adjusted — all items, the cores, the eight major groups and every "
             "published item — monthly, all items from 1913."),
    page="/us-inflation.html",
    history_from="1913-01",
    notes=["Not seasonally adjusted: the basis of the headline 12-month rate the "
           "BLS announces. For month-on-month readings use cpi-us-sa."])
