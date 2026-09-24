"""Adapter: US CPI-U for regions, city-size classes and metropolitan areas.

Same BLS flat files as cpi_us (see bls_cpi.py); every area other than the
U.S. city average — four regions, nine divisions, size classes, and 23
metro areas plus urban Alaska and Hawaii — not seasonally adjusted, monthly.

**Most metro areas are not priced every month.** The three largest (New York,
Los Angeles, Chicago) are monthly; the rest are published every other month
(odd or even months by area) or, for a few items, less often. The months in
between are absent — missing, never interpolated and never zero — and a
year-on-year rate is computed only where both months were published.
"""
import datetime

from . import bls_cpi
from .bls_cpi import ValidationError  # noqa: F401 — part of the adapter contract

DATASET = {
    "slug": "cpi-us-areas",
    "title": "Consumer Price Index — United States regions and metro areas (CPI-U)",
    "country": "United States",
    "agency": bls_cpi.AGENCY,
    "agency_ja": None,
    "base": bls_cpi.BASE,
    "frequency": "monthly",
    "description": (
        "Official CPI for All Urban Consumers (CPI-U) for the four census "
        "regions, their divisions, city-size classes and 23 metropolitan areas "
        "plus urban Alaska and Hawaii, not seasonally adjusted, by item (about "
        "3,400 series). Most metro areas are priced every other month; the "
        "months between are absent, never filled."
    ),
}

SOURCE = {
    "source_id": "bls:cu:areas",
    "name": "BLS Consumer Price Index for All Urban Consumers (CPI-U), regions, size classes and metropolitan areas",
    "name_ja": None,
    "url": "https://www.bls.gov/cpi/regional-resources.htm",
    "license_note": bls_cpi.LICENSE_NOTE,
}

DOWNLOAD_URL = bls_cpi.bls_flat.BASE + "cu/"
RAW_SUFFIX = ".zip"

PRESENTATION = {
    "measure_type": "index",
    "main_series": [
        {"role": "northeast", "code": "CUUR0100SA0", "label": "Northeast", "slot": 1},
        {"role": "midwest", "code": "CUUR0200SA0", "label": "Midwest", "slot": 2},
        {"role": "south", "code": "CUUR0300SA0", "label": "South", "slot": 3},
        {"role": "west", "code": "CUUR0400SA0", "label": "West", "slot": 4},
    ],
    "credit_line": bls_cpi.CREDIT,
    "stale_after_days": bls_cpi.STALE_AFTER_DAYS,
    # The listing is ~3,400 rows; it is a search, not a dump.
    "series_requires_query": True,
}


def fetch():
    return bls_cpi.fetch(bls_cpi.AREA_FILES)


def parse(raw_bytes):
    return bls_cpi.parse(
        raw_bytes,
        select=lambda r: r["area_code"] != "0000" and r["seasonal"] == "U",
        name_fn=lambda item, area: "%s — %s" % (area, item),
        sort_fn=lambda item, area: (int(area["sort_sequence"] or 0) * 1000
                                    + int(item["sort_sequence"] or 0)))


# All-items series for the monthly metros: the three published every month.
MONTHLY_METROS = ["CUURS12ASA0", "CUURS49ASA0", "CUURS23ASA0"]


def validate(series, observations):
    latest = bls_cpi.check(
        series, observations, min_series=3000, min_observations=500000,
        required=[m["code"] for m in PRESENTATION["main_series"]],
        first_period=datetime.date(1914, 12, 1))
    codes = set(s["code"] for s in series)
    missing = [c for c in MONTHLY_METROS if c not in codes]
    if missing:
        raise ValidationError("monthly metro series missing: %s" % ", ".join(missing))
    areas = set(s["code"][4:8] for s in series)
    if len(areas) < 50:
        raise ValidationError("only %d areas parsed" % len(areas))
    return {
        "series": len(series),
        "observations": len(observations),
        "areas": len(areas),
        "latest_period": latest.isoformat(),
    }


MANIFEST = bls_cpi.manifest(
    DATASET, SOURCE, PRESENTATION,
    name={"en": "US Consumer Price Index — regions and metro areas",
          "ja": "米国消費者物価指数（地域・都市圏別）"},
    summary=("US CPI for All Urban Consumers by region, city-size class and "
             "metropolitan area — 23 metros plus urban Alaska and Hawaii — by "
             "item, not seasonally adjusted, monthly."),
    page="/us-cpi-areas.html",
    history_from="1914-12",
    notes=["Series codes carry the BLS area code in characters 5–8 (0100 "
           "Northeast, S12A New York, S49A Los Angeles, ...).",
           "Most metro areas are priced every other month; the months between "
           "are absent, never interpolated. New York, Los Angeles and Chicago "
           "are monthly.",
           "The series listing is a search: pass ?q= (an area or an item)."])
