"""Adapter: food trade — Japan's food imports and exports by partner country.

The same principal-commodity by country tables (概況品別国別表) of the Ministry
of Finance *Trade Statistics of Japan* that `mof_trade` reads for
semiconductors, read for food and live animals (食料品及び動物): the section
total plus beef, pork, fish and shellfish, wheat and maize on the import
side; the total plus meat, fish and shellfish, rice and other food
preparations on the export side. Monthly by partner country from January
2001, led by **imports**: Japan buys roughly eight times the food it sells.

Everything mechanical is `mof_trade`'s; this adapter owns the commodity
table, the validation anchors and the page configuration. Facts of the
slice:

- **The food total is a section total** (the Ministry's level-1 code
  `00000000`), published with no quantity — it sums tonnes of wheat and
  kilograms of fish. It has no unit value.
- **Codes are the same in both directions for the lines carried here**,
  which is unusual in these tables, but the two schedules still differ
  beneath them (import pork is `00305010` inside `00305000`; the export
  schedule has no such split). Each direction still carries its own map.
- **Quantities are tonnes**, except fish and shellfish imports, which the
  Ministry publishes in kilograms. A unit value is yen per tonne or per
  kilogram accordingly and is never compared between lines.
"""
from . import mof_trade
from .mof_trade import (PARTNER_EN, PARTNER_JA, PARTNERS, REGIONS, REGION_LABEL,  # noqa: F401
                        partner_region)


class ValidationError(Exception):
    pass


# (code, English label, Japanese label, sort order, level, chart label).
COMMODITIES = {
    "imp": [
        ("00000000", "Food & live animals (all)", "食料品及び動物", 0, "group", "All food"),
        ("00701000", "Fish & shellfish", "魚介類", 1, "item", "Fish & shellfish"),
        ("00305010", "Pork", "豚肉", 2, "item", "Pork"),
        ("00301000", "Beef", "牛肉", 3, "item", "Beef"),
        ("00907000", "Maize", "とうもろこし", 4, "item", "Maize"),
        ("00901000", "Wheat", "小麦及びメスリン", 5, "item", "Wheat"),
    ],
    "exp": [
        ("00000000", "Food & live animals (all)", "食料品及び動物", 0, "group", "All food"),
        ("00701000", "Fish & shellfish", "魚介類", 1, "item", "Fish & shellfish"),
        ("01900000", "Other food preparations", "その他の調製食料品", 2, "item",
         "Other food preparations"),
        ("00300000", "Meat & meat preparations", "肉類及び同調製品", 3, "item", "Meat"),
        ("00903000", "Rice", "米", 4, "item", "Rice"),
    ],
}

VALUE_UNIT = mof_trade.VALUE_UNIT
FIRST_YEAR = mof_trade.FIRST_YEAR
CACHE_KIND = "data-food"


DATASET = {
    "slug": "trade-food",
    "title": "Food Trade — Imports and Exports by Partner",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Monthly Japanese food imports and exports by partner country from "
        "January 2001: the food section total plus fish and shellfish, pork, "
        "beef, maize and wheat (imports), and fish and shellfish, other food "
        "preparations, meat and rice (exports). Value in thousands of yen "
        "and quantity in tonnes (kilograms for imported fish), exactly as "
        "released by the Ministry of Finance in the principal-commodity by "
        "country tables of the Trade Statistics of Japan."
    ),
}

SOURCE = {
    "source_id": "estat:00350300:gaikyohin-food",
    "name": ("Ministry of Finance — Trade Statistics of Japan, principal "
             "commodity by country tables (food and live animals)"),
    "name_ja": "財務省 普通貿易統計 概況品別国別表（食料品及び動物）",
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


# Beef must arrive from Australia and the United States every month; food as
# a whole must reach the United States and Hong Kong. If either stops, the
# parse is wrong, not the trade.
FLAGSHIP = {"imp": "00301000", "exp": "00000000"}
ANCHOR_PARTNERS = {"imp": ("50601", "50304"), "exp": ("50304", "50108")}
MIN_OBSERVATIONS = 170_000   # 339,968 on first ingest

PROFILE = {"flagship": FLAGSHIP, "anchors": ANCHOR_PARTNERS,
           "min_observations": MIN_OBSERVATIONS,
           "flagship_name": "beef / food-total", "stat_prefix": "flagship"}


def validate(series, observations):
    try:
        return mof_trade.validate(series, observations, PROFILE)
    except mof_trade.ValidationError as e:
        raise ValidationError(str(e))


BALANCE_CALC = mof_trade.balance_calc("food & live animals", "food & live animals")

PRESENTATION = {
    "credit_line": mof_trade.CREDIT_LINE,
    "stale_after_days": mof_trade.STALE_AFTER_DAYS,
    "trade": mof_trade.trade_presentation(
        COMMODITIES, "imp", {"imp": "00301000", "exp": "00701000"},
        # The suppliers a food desk reads first: the United States, China,
        # Australia, Thailand, Canada and Chile.
        ["50304", "50105", "50601", "50111", "50302", "50409"],
        {
            "name": "Food trade",
            "file_tag": "food",
            "subtitle": ("Monthly food imports — beef, pork, seafood, wheat, maize — "
                         "by supplier, and food exports by destination"),
            "partner_slots": {"50304": 2, "50105": 3, "50601": 4, "50111": 5, "50302": 6},
            "default_partners": ["50601", "50304"],
            "tiles": [
                {"kind": "month", "flow": "imp", "commodity": "00000000",
                 "label": "Food Imports",
                 "title": "World total of Japan's food imports"},
                {"kind": "month", "flow": "imp", "commodity": "00701000",
                 "label": "Fish & Shellfish Imports",
                 "title": "World total of Japan's fish and shellfish imports"},
                {"kind": "month", "flow": "imp", "commodity": "00301000",
                 "label": "Beef Imports",
                 "title": "World total of Japan's beef imports"},
                {"kind": "balance", "exp": "00000000", "imp": "00000000",
                 "label": "Food: Exports − Imports",
                 "title": "Food and live animals, exports less imports"},
            ],
            "balance_calc": BALANCE_CALC,
            "strip_foot": ("The first three tiles are single months and move with "
                           "cargo timing and world prices; the balance is a twelve-month "
                           "sum and is negative: Japan imports far more food than it "
                           "exports."),
        }),
}

MANIFEST = {
    "id": DATASET["slug"],
    "section": "trade",
    "name": {"en": "Food trade — imports and exports by partner",
             "ja": "食料品の輸出入（相手国別）"},
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
    "measures": mof_trade.MEASURES + [
        {"id": "balance", "label": "Trade balance in food, 12-month totals",
         "unit": "JPY_thousand", "trust": "derived", "calc": BALANCE_CALC},
    ],
    "endpoints": mof_trade.endpoints(DATASET["slug"]),
    "capabilities": ["series"],
    "cite": "/food.html?flow=imp",
    "page": "/food.html",
    "notes": [
        "The food total is the Ministry's level-1 section (00000000), published without "
        "a quantity and therefore without a unit value.",
        "Imported fish and shellfish are published in kilograms, every other line in "
        "tonnes.",
    ] + mof_trade.NOTES,
}
