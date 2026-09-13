"""Adapter: energy trade — Japan's mineral-fuel imports and refined-product exports by partner.

The same principal-commodity by country tables (概況品別国別表) of the Ministry
of Finance *Trade Statistics of Japan* that `mof_trade` reads for
semiconductors, read for the fuel lines. On the import side: the mineral-fuel
total, crude oil, liquefied natural gas, coal, refined petroleum products and
liquefied petroleum gas. On the export side, where Japan is a refiner rather
than a producer: the mineral-fuel total, refined products and the three
product lines beneath them (gasoline, kerosene and jet fuel, gas oil).
Monthly by partner country from January 2001.

Everything mechanical is `mof_trade`'s — the year-block tables, the
publisher-stamped cache, the partner vocabulary, the coverage rule for
months the Ministry has not compiled, the series-code shape — so the
`/trade` surface and the shared trade page serve this dataset unchanged.
This adapter owns the commodity table, the validation anchors and the page
configuration, and it leads with **imports**: the question an energy desk
brings to Japan's customs data is the fuel bill, not the exports.

Three facts of this slice that the reader of the numbers needs:

- **Commodity codes are direction-specific.** `30301000` is *crude oil* on
  the import side and *refined petroleum products* on the export side. Each
  direction carries its own map and the two are never joined on a code.
- **The mineral-fuel total (`30000000`) is published without a quantity** —
  it sums tonnes, kilolitres and cubic metres — so it has no unit value, and
  the page disables that view for it rather than drawing an empty chart.
- **Quantities differ by fuel**: crude and refined products in kilolitres,
  coal, LNG and LPG in metric tonnes. A unit value is yen per kilolitre or
  yen per tonne accordingly, and the fuels are never compared on one.
"""
from . import mof_trade
from .mof_trade import (PARTNER_EN, PARTNER_JA, PARTNERS, REGIONS, REGION_LABEL,  # noqa: F401
                        partner_region)


class ValidationError(Exception):
    pass


# (code, English label, Japanese label, sort order, level, chart label).
# "Mineral fuels" is the published section total and, as everywhere in these
# tables, exceeds the sum of the lines carried beneath it. On the export side
# "Petroleum products" is itself the parent of the three product lines.
COMMODITIES = {
    "imp": [
        ("30000000", "Mineral fuels (all)", "鉱物性燃料", 0, "group", "All mineral fuels"),
        ("30301000", "Crude oil", "原油及び粗油", 1, "item", "Crude oil"),
        ("30501030", "Liquefied natural gas (LNG)", "液化天然ガス", 2, "item", "LNG"),
        ("30101000", "Coal", "石炭", 3, "item", "Coal"),
        ("30303000", "Petroleum products", "石油製品", 4, "item", "Petroleum products"),
        ("30501010", "Liquefied petroleum gas (LPG)", "液化石油ガス", 5, "item", "LPG"),
    ],
    "exp": [
        ("30000000", "Mineral fuels (all)", "鉱物性燃料", 0, "group", "All mineral fuels"),
        ("30301000", "Petroleum products", "石油製品", 1, "group", "Petroleum products"),
        ("30301010", "Gasoline (petroleum spirits)", "揮発油", 2, "item", "Gasoline"),
        ("30301030", "Kerosene & jet fuel", "灯油（含ジェット燃料油）", 3, "item",
         "Kerosene & jet fuel"),
        ("30301050", "Gas oil (diesel)", "軽油", 4, "item", "Gas oil"),
    ],
}

VALUE_UNIT = mof_trade.VALUE_UNIT
FIRST_YEAR = mof_trade.FIRST_YEAR
CACHE_KIND = "data-energy"


DATASET = {
    "slug": "trade-energy",
    "title": "Energy Trade — Fuel Imports and Refined-Product Exports by Partner",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Monthly Japanese imports of crude oil, liquefied natural gas, coal, "
        "refined petroleum products and liquefied petroleum gas, and exports "
        "of refined petroleum products, by partner country, from January "
        "2001. Value in thousands of yen and quantity in the published unit "
        "(kilolitres for oil, tonnes for gas and coal), exactly as released "
        "by the Ministry of Finance in the principal-commodity by country "
        "tables of the Trade Statistics of Japan. Export and import "
        "commodity codes are separate vocabularies and do not correspond."
    ),
}

SOURCE = {
    "source_id": "estat:00350300:gaikyohin-energy",
    "name": ("Ministry of Finance — Trade Statistics of Japan, principal "
             "commodity by country tables (mineral-fuel commodities)"),
    "name_ja": "財務省 普通貿易統計 概況品別国別表（鉱物性燃料）",
    "url": mof_trade.SOURCE["url"],
    "license_note": mof_trade.SOURCE["license_note"],
}

DOWNLOAD_URL = mof_trade.DOWNLOAD_URL
RAW_SUFFIX = mof_trade.RAW_SUFFIX


def fetch():
    return mof_trade.fetch_commodities(COMMODITIES, CACHE_KIND)


def parse(raw_bytes):
    try:
        return mof_trade.parse(raw_bytes, COMMODITIES)
    except mof_trade.ValidationError as e:
        raise ValidationError(str(e))


# Crude oil is the import flagship and must arrive from Saudi Arabia and the
# United Arab Emirates every month; refined products are the export flagship
# and must reach Korea and Australia. If either stops, the parse is wrong.
FLAGSHIP = {"imp": "30301000", "exp": "30301000"}
ANCHOR_PARTNERS = {"imp": ("50137", "50147"), "exp": ("50103", "50601")}
MIN_OBSERVATIONS = 120_000   # 197,544 on first ingest

PROFILE = {"flagship": FLAGSHIP, "anchors": ANCHOR_PARTNERS,
           "min_observations": MIN_OBSERVATIONS,
           "flagship_name": "crude-oil / refined-product",
           "stat_prefix": "petroleum"}


def validate(series, observations):
    try:
        return mof_trade.validate(series, observations, PROFILE)
    except mof_trade.ValidationError as e:
        raise ValidationError(str(e))


PRESENTATION = {
    "credit_line": mof_trade.CREDIT_LINE,
    "stale_after_days": mof_trade.STALE_AFTER_DAYS,
    "trade": mof_trade.trade_presentation(
        COMMODITIES, "imp", {"imp": "30301000", "exp": "30301000"},
        # The suppliers an energy desk reads first: Saudi Arabia, the UAE,
        # Australia, the United States, Qatar and Malaysia. Order is the
        # picker's, not a ranking.
        ["50137", "50147", "50601", "50304", "50140", "50113"],
        {
            "name": "Energy trade",
            "file_tag": "energy",
            "subtitle": ("Monthly imports of crude oil, LNG, coal and refined "
                         "products, and exports of refined products, by partner country"),
            "partner_slots": {"50137": 2, "50147": 3, "50601": 4, "50304": 5, "50140": 6},
            "default_partners": ["50137", "50147", "50304"],
            "tiles": [
                {"kind": "month", "flow": "imp", "commodity": "30301000",
                 "label": "Crude Oil Imports",
                 "title": "World total of Japan's crude-oil imports"},
                {"kind": "month", "flow": "imp", "commodity": "30501030",
                 "label": "LNG Imports",
                 "title": "World total of Japan's liquefied-natural-gas imports"},
                {"kind": "month", "flow": "imp", "commodity": "30101000",
                 "label": "Coal Imports",
                 "title": "World total of Japan's coal imports"},
                {"kind": "ttm", "flow": "imp", "commodity": "30000000",
                 "label": "All Mineral Fuels, 12 Months",
                 "title": "World total of Japan's mineral-fuel imports"},
            ],
            "strip_foot": ("The first three tiles are single months and move with "
                           "cargo timing and the oil price; the fuel bill is a "
                           "twelve-month sum."),
        }),
}

MANIFEST = {
    "id": DATASET["slug"],
    "section": "trade",
    "name": {"en": "Energy trade — fuel imports and refined-product exports by partner",
             "ja": "鉱物性燃料の輸出入（相手国別）"},
    "shape": "series",
    "summary": DATASET["description"],
    "source": {
        "publisher": DATASET["agency"], "publisher_ja": DATASET["agency_ja"],
        "document": SOURCE["name"], "url": SOURCE["url"],
        "credit": PRESENTATION["credit_line"], "license_note": SOURCE["license_note"],
    },
    "keys": ["series_code", "period"],
    "frequency": DATASET["frequency"],
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "2001-01",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": list(mof_trade.MEASURES),
    "endpoints": mof_trade.endpoints(DATASET["slug"]),
    "capabilities": ["series"],
    "cite": "/energy.html?flow=imp",
    "page": "/energy.html",
    "notes": [
        "30301000 is crude oil on the import side and refined petroleum products on "
        "the export side.",
        "The mineral-fuel total (30000000) is published without a quantity, so it has "
        "no unit value.",
        "Crude and refined products are measured in kilolitres; coal, LNG and LPG in "
        "metric tonnes. Unit values are never compared between fuels.",
    ] + mof_trade.NOTES,
}
