"""Adapter: US CPI-U, U.S. city average, seasonally adjusted.

Same BLS flat files as cpi_us (see bls_cpi.py); the seasonally adjusted
series (ids beginning CUSR) — what month-on-month and three-month
annualised readings are read from. The BLS revises five years of seasonal
factors every February; each revision arrives here as a new vintage, and
the earlier figures stay retrievable with as_of.
"""
import datetime

from . import bls_cpi
from .bls_cpi import ValidationError  # noqa: F401 — part of the adapter contract

DATASET = {
    "slug": "cpi-us-sa",
    "title": "Consumer Price Index — United States (CPI-U, seasonally adjusted)",
    "country": "United States",
    "agency": bls_cpi.AGENCY,
    "agency_ja": None,
    "base": bls_cpi.BASE,
    "frequency": "monthly",
    "description": (
        "Official CPI for All Urban Consumers (CPI-U), U.S. city average, "
        "seasonally adjusted by the Bureau of Labor Statistics: all items, the "
        "cores, the major groups and the items the BLS adjusts (about 325 "
        "series), monthly — all items from January 1947. Seasonal factors are "
        "revised each February; each revision is a new vintage."
    ),
}

SOURCE = {
    "source_id": "bls:cu:us-sa",
    "name": "BLS Consumer Price Index for All Urban Consumers (CPI-U), U.S. city average, seasonally adjusted",
    "name_ja": None,
    "url": bls_cpi.SOURCE_PAGE,
    "license_note": bls_cpi.LICENSE_NOTE,
}

DOWNLOAD_URL = bls_cpi.bls_flat.BASE + "cu/"
RAW_SUFFIX = ".zip"

HEADLINE = "CUSR0000SA0"

PRESENTATION = {
    "measure_type": "index",
    "main_series": [
        {"role": "headline", "code": "CUSR0000SA0", "label": "Headline CPI, adjusted", "slot": 1},
        {"role": "core", "code": "CUSR0000SA0L1E",
         "label": "Core CPI (less food and energy), adjusted", "slot": 2},
    ],
    "group_codes": ["CUSR0000" + i for i in bls_cpi.GROUP_ITEMS],
    "credit_line": bls_cpi.CREDIT,
    "stale_after_days": bls_cpi.STALE_AFTER_DAYS,
}


def fetch():
    return bls_cpi.fetch(bls_cpi.US_FILES)


def parse(raw_bytes):
    return bls_cpi.parse(
        raw_bytes,
        select=lambda r: r["area_code"] == "0000" and r["seasonal"] == "S",
        name_fn=lambda item, area: item,
        sort_fn=lambda item, area: int(item["sort_sequence"] or 0))


def validate(series, observations):
    latest = bls_cpi.check(
        series, observations, min_series=280, min_observations=80000,
        required=[m["code"] for m in PRESENTATION["main_series"]]
                 + PRESENTATION["group_codes"],
        first_period=datetime.date(1947, 1, 1))
    head = dict((o["period"], o["value"]) for o in observations if o["code"] == HEADLINE)
    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "headline_index": head.get(latest),
    }


MANIFEST = bls_cpi.manifest(
    DATASET, SOURCE, PRESENTATION,
    name={"en": "US Consumer Price Index — seasonally adjusted",
          "ja": "米国消費者物価指数（季節調整済）"},
    summary=("US CPI for All Urban Consumers, U.S. city average, seasonally "
             "adjusted by the BLS — the basis of the month-on-month rate it "
             "announces — monthly, all items from 1947."),
    page="/us-cpi-sa.html",
    history_from="1947-01",
    notes=["Seasonally adjusted by the BLS. Five years of seasonal factors are "
           "revised each February; each revision is stored as a new vintage and "
           "earlier figures stay retrievable with as_of.",
           "For the 12-month rate use cpi-us (not seasonally adjusted), which is "
           "what the BLS announces as the headline annual change."])
