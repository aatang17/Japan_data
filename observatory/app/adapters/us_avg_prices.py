"""Adapter: US average retail prices (BLS Average Price Data).

Source: U.S. Bureau of Labor Statistics, CPI Average Price Data — flat files
at download.bls.gov/pub/time.series/ap/ (see bls_flat.py). What a shopper
actually paid, in US dollars per unit: eggs per dozen, regular gasoline per
gallon, ground beef per pound, electricity per kilowatt-hour — about 160
items, for the U.S. city average and for regions and some metro areas,
monthly, food from 1980, gasoline from 1973 and household fuels from 1978.

These are prices, not an index: each series is a dollar level in the unit its
name states (per lb., per doz., per gallon, per therm, per kWh). A change is
a change in dollars; a percentage change is calculated here and labelled as
such. Never compare two items' levels — a pound of coffee and a gallon of
milk share a currency, not a unit.

The BLS computes these from the same price quotes as the CPI but they are
not a substitute for it: an average price does not adjust for quality or
size changes the way the index does. Not seasonally adjusted.

A handful of cells the BLS prints as 0.000 (metro fuels, 1996) or '-'
(October 2025: "data unavailable due to the 2025 lapse in
appropriations") are gaps here.
"""
import datetime

from . import bls_flat


class ValidationError(Exception):
    pass


DATASET = {
    "slug": "us-avg-prices",
    "title": "US Average Retail Prices (BLS Average Price Data)",
    "country": "United States",
    "agency": "U.S. Bureau of Labor Statistics",
    "agency_ja": None,
    "base": None,
    "frequency": "monthly",
    "description": (
        "Average retail prices paid by urban consumers, in US dollars per unit "
        "— eggs per dozen, gasoline per gallon, ground beef per pound, "
        "electricity per kWh and about 160 other items — for the U.S. city "
        "average, regions and some metro areas, monthly from 1973–1980 by "
        "item. Published by the Bureau of Labor Statistics from the CPI's price "
        "quotes; not seasonally adjusted and not quality-adjusted."
    ),
}

SOURCE = {
    "source_id": "bls:ap",
    "name": "BLS Consumer Price Index — Average Price Data",
    "name_ja": None,
    "url": "https://www.bls.gov/cpi/factsheets/average-prices.htm",
    "license_note": ("Work of the United States Government, in the public domain "
                     "(17 U.S.C. §105). Cite the Bureau of Labor Statistics as the source."),
}

DOWNLOAD_URL = bls_flat.BASE + "ap/"
RAW_SUFFIX = ".zip"

META_FILES = ["ap.series", "ap.item", "ap.area"]
# The split files hold every series and every year; ap.data.0.Current is
# the same series from 1995 only, so it is not fetched.
DATA_FILES = ["ap.data.1.HouseholdFuels", "ap.data.2.Gasoline", "ap.data.3.Food"]

TILES = [
    ("eggs", "APU0000708111", "Eggs, grade A large · per dozen"),
    ("gasoline", "APU000074714", "Gasoline, regular · per gallon"),
    ("beef", "APU0000703112", "Ground beef · per lb"),
    ("milk", "APU0000709112", "Milk, whole · per gallon"),
    ("coffee", "APU0000717311", "Coffee, ground · per lb"),
    ("electricity", "APU000072610", "Electricity · per kWh"),
]

PRESENTATION = {
    "credit_line": "Source: U.S. Bureau of Labor Statistics.",
    "stale_after_days": 75,
    "overview_tiles": [{"key": k, "code": c, "label": l, "type": "level"}
                       for k, c, l in TILES],
    "main_series": [{"role": k, "code": c, "label": l, "slot": i + 1}
                    for i, (k, c, l) in enumerate(TILES[:4])],
}


def fetch():
    files = {}
    for name in META_FILES + DATA_FILES:
        files[name] = bls_flat.fetch_file("ap", name)
    return bls_flat.bundle(files)


def parse(raw_bytes):
    try:
        files = bls_flat.unbundle(raw_bytes)
    except Exception as exc:
        raise ValidationError("not a BLS bundle: %s" % exc)
    for name in META_FILES:
        if name not in files:
            raise ValidationError("bundle is missing %s" % name)
    items = dict((r["item_code"], r) for r in bls_flat.read_table(files["ap.item"]))
    areas = dict((r["area_code"], r) for r in bls_flat.read_table(files["ap.area"]))
    area_order = dict((code, i) for i, code in enumerate(areas))   # file order

    chosen = {}
    for row in bls_flat.read_table(files["ap.series"]):
        sid = row.get("series_id")
        if not sid:
            continue
        item, area = items.get(row["item_code"]), areas.get(row["area_code"])
        if item is None or area is None:
            raise ValidationError("%s: item %r or area %r not in the code lists"
                                  % (sid, row["item_code"], row["area_code"]))
        chosen[sid] = (row, item, area)

    values = {}
    for name in DATA_FILES:
        if name not in files:
            raise ValidationError("bundle is missing %s" % name)
        bls_flat.read_values(files[name], chosen, name, ValidationError, into=values)

    def order(kv):
        row, item, area = kv[1]
        # the nation first, then the areas in the BLS's own order; items by code
        return (area_order.get(row["area_code"], 999), row["item_code"], kv[0])

    series, observations = [], []
    for sid, (row, item, area) in sorted(chosen.items(), key=order):
        vals = values.get(sid)
        if not vals:
            continue
        name = item["item_name"]
        if row["area_code"] != "0000":
            name = "%s — %s" % (area["area_name"], name)
        series.append({
            "code": sid, "name_en": name, "name_ja": None,
            "unit": "usd", "weight_per_10000": None, "sort_order": len(series),
        })
        for period in sorted(vals):
            observations.append({"code": sid, "period": period, "value": vals[period]})
    return series, observations


def validate(series, observations):
    if len(series) < 1200:
        raise ValidationError("only %d series parsed" % len(series))
    if len(observations) < 250000:
        raise ValidationError("only %d observations parsed" % len(observations))
    codes = set(s["code"] for s in series)
    missing = [c for _k, c, _l in TILES if c not in codes]
    if missing:
        raise ValidationError("headline items missing: %s" % ", ".join(missing))
    latest, first = None, None
    last_by = {}
    for o in observations:
        v = o["value"]
        # Cheapest item: electricity at ~$0.02/kWh in the 1970s; dearest:
        # steaks and fuel oil in the tens of dollars. A three-digit price per
        # unit is a parse fault, not a price.
        if not (0 < v < 500):
            raise ValidationError("%s %s: price %r out of range" % (o["code"], o["period"], v))
        p = o["period"]
        latest = p if latest is None or p > latest else latest
        first = p if first is None or p < first else first
        if p > last_by.get(o["code"], datetime.date.min):
            last_by[o["code"]] = p
    if first > datetime.date(1973, 12, 1):
        raise ValidationError("history starts %s, expected by 1973" % first)
    for _k, c, _l in TILES:
        if last_by.get(c) != latest:
            raise ValidationError("%s ends %s but the release runs to %s"
                                  % (c, last_by.get(c), latest))
    latest_vals = dict((o["code"], o["value"]) for o in observations if o["period"] == latest)
    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": latest.isoformat(),
        "eggs_per_dozen": latest_vals.get("APU0000708111"),
        "gasoline_per_gallon": latest_vals.get("APU000074714"),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "prices",
    "name": {"en": "US average retail prices", "ja": "米国平均小売価格"},
    "shape": "series",
    "summary": ("What US urban shoppers paid, in dollars per unit — eggs per "
                "dozen, gasoline per gallon, ground beef per pound and about 160 "
                "other items — nationally, by region and for some metro areas, "
                "monthly from the 1970s."),
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
        "as_of_supported": True, "history_from": "1973-01",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Average price, US dollars per the unit in the item's name",
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
    "cite": "/us-prices.html",
    "page": "/us-prices.html",
    "notes": [
        "Dollar prices, not an index: each series is in the unit its name "
        "states (per lb., per doz., per gallon, per therm, per kWh). Levels of "
        "two different items are never comparable.",
        "Series codes are the BLS series ids (APU + area + item), so every "
        "figure can be checked on bls.gov under the same id.",
        "Not seasonally adjusted and not quality-adjusted: an average price is "
        "not a substitute for the CPI item index.",
        "Cells the BLS prints as '-' (October 2025, the 2025 lapse in appropriations) or "
        "0.000 (a few metro fuels in 1996) are missing, never zero.",
    ],
}
