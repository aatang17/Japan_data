"""Adapter: motor-vehicle trade — Japan exports and imports by partner country.

The same principal-commodity by country tables (概況品別国別表) of the Ministry
of Finance *Trade Statistics of Japan* that `mof_trade` reads for
semiconductors, read for the vehicle lines: finished vehicles, passenger
cars, buses and trucks, vehicle parts and motorcycles, in both directions,
monthly from January 2001.

Everything mechanical is `mof_trade`'s — the year-block tables, the
publisher-stamped cache, the partner vocabulary, the coverage rule for
months the Ministry has not compiled, the series-code shape — so the
`/trade` surface and the shared trade page serve this dataset unchanged.
What is this adapter's own is the commodity table, the validation anchors
and the page configuration.

The code trap is the same as for semiconductors and worth restating:
**commodity codes are direction-specific.** `70503000` is motor vehicles on
the export side and *parts of* motor vehicles on the import side; `70505000`
(parts) exists only on the export schedule. Each direction carries its own
map and the two are never joined on a code.

Units: vehicles are counted in number (ＮＯ); parts are weighed in
kilograms. A unit value is therefore yen per vehicle for the vehicle lines
and yen per kilogram for parts, and the two are never compared.
"""
from . import mof_trade
from .mof_trade import (PARTNER_EN, PARTNER_JA, PARTNERS, REGIONS, REGION_LABEL,  # noqa: F401
                        partner_region)


class ValidationError(Exception):
    pass


# (code, English label, Japanese label, sort order, level, chart label).
# "Motor vehicles" is the published parent of passenger cars and buses &
# trucks, and — as everywhere in these tables — is larger than the two
# together, because the Ministry publishes children this dataset does not
# carry (chassis, used cars as a sub-line). Parts and motorcycles sit beside
# it as their own published lines.
COMMODITIES = {
    "exp": [
        ("70503000", "Motor vehicles", "自動車", 0, "group", "Motor vehicles"),
        ("70503010", "Passenger cars", "乗用車", 1, "item", "Passenger cars"),
        ("70503030", "Buses & trucks", "バス・トラック", 2, "item", "Buses & trucks"),
        ("70505000", "Motor vehicle parts", "自動車の部分品", 3, "item", "Vehicle parts"),
        ("70507010", "Motorcycles", "二輪自動車・原動機付自転車", 4, "item", "Motorcycles"),
    ],
    "imp": [
        ("70501000", "Motor vehicles", "自動車", 0, "group", "Motor vehicles"),
        ("70501010", "Passenger cars", "乗用車", 1, "item", "Passenger cars"),
        ("70501030", "Buses & trucks", "バス・トラック", 2, "item", "Buses & trucks"),
        ("70503000", "Motor vehicle parts", "自動車の部分品", 3, "item", "Vehicle parts"),
        ("70504010", "Motorcycles", "二輪自動車・原動機付自転車", 4, "item", "Motorcycles"),
    ],
}

VALUE_UNIT = mof_trade.VALUE_UNIT
FIRST_YEAR = mof_trade.FIRST_YEAR
CACHE_KIND = "data-autos"


DATASET = {
    "slug": "trade-autos",
    "title": "Motor Vehicle Trade — Exports and Imports by Partner",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Monthly Japanese exports and imports of motor vehicles, passenger "
        "cars, buses and trucks, vehicle parts and motorcycles, by partner "
        "country, from January 2001. Value in thousands of yen and quantity "
        "in the published unit (number of vehicles; kilograms for parts), "
        "exactly as released by the Ministry of Finance in the "
        "principal-commodity by country tables of the Trade Statistics of "
        "Japan. Export and import commodity codes are separate "
        "vocabularies and do not correspond."
    ),
}

SOURCE = {
    "source_id": "estat:00350300:gaikyohin-autos",
    "name": ("Ministry of Finance — Trade Statistics of Japan, principal "
             "commodity by country tables (motor-vehicle commodities)"),
    "name_ja": "財務省 普通貿易統計 概況品別国別表（自動車関連品目）",
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


# Passenger cars are the flagship in both directions. Exports must reach the
# United States and Australia, imports must arrive from Germany and the
# United Kingdom, in every plausible month — if not, the parse is wrong.
FLAGSHIP = {"exp": "70503010", "imp": "70501010"}
ANCHOR_PARTNERS = {"exp": ("50304", "50601"), "imp": ("50213", "50205")}
MIN_OBSERVATIONS = 400_000   # 720,148 on first ingest

PROFILE = {"flagship": FLAGSHIP, "anchors": ANCHOR_PARTNERS,
           "min_observations": MIN_OBSERVATIONS,
           "flagship_name": "passenger-car", "stat_prefix": "cars"}


def validate(series, observations):
    try:
        return mof_trade.validate(series, observations, PROFILE)
    except mof_trade.ValidationError as e:
        raise ValidationError(str(e))


BALANCE_CALC = mof_trade.balance_calc("motor vehicles", "motor vehicles")

PRESENTATION = {
    "credit_line": mof_trade.CREDIT_LINE,
    "stale_after_days": mof_trade.STALE_AFTER_DAYS,
    "trade": mof_trade.trade_presentation(
        COMMODITIES, "exp", {"exp": "70503010", "imp": "70501010"},
        # The markets an auto desk reads first: the United States, China,
        # Australia, Germany, Thailand and Mexico. Order is the picker's, not
        # a ranking.
        ["50304", "50105", "50601", "50213", "50111", "50305"],
        {
            "name": "Motor vehicle trade",
            "file_tag": "motor-vehicle",
            "subtitle": ("Monthly trade in motor vehicles, vehicle parts and "
                         "motorcycles by partner country"),
            "partner_slots": {"50304": 2, "50105": 3, "50601": 4, "50213": 5, "50111": 6},
            "default_partners": ["50304", "50105"],
            "tiles": [
                {"kind": "month", "flow": "exp", "commodity": "70503010",
                 "label": "Passenger Car Exports",
                 "title": "World total of Japan's passenger-car exports"},
                {"kind": "month", "flow": "exp", "commodity": "70505000",
                 "label": "Vehicle Parts Exports",
                 "title": "World total of Japan's motor-vehicle parts exports"},
                {"kind": "month", "flow": "imp", "commodity": "70501010",
                 "label": "Passenger Car Imports",
                 "title": "World total of Japan's passenger-car imports"},
                {"kind": "balance", "exp": "70503000", "imp": "70501000",
                 "label": "Vehicles: Exports − Imports",
                 "title": "Motor vehicles, exports less imports"},
            ],
            "balance_calc": BALANCE_CALC,
            "strip_foot": ("The first three tiles are single months and move with "
                           "shipment timing; the balance is a twelve-month sum."),
        }),
}

MANIFEST = {
    "id": DATASET["slug"],
    "section": "trade",
    "name": {"en": "Motor vehicle trade — exports and imports by partner",
             "ja": "自動車関連品目の輸出入（相手国別）"},
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
        {"id": "balance", "label": "Trade balance in motor vehicles, 12-month totals",
         "unit": "JPY_thousand", "trust": "derived", "calc": BALANCE_CALC},
    ],
    "endpoints": mof_trade.endpoints(DATASET["slug"]),
    "capabilities": ["series", "search"],
    "cite": "/autos.html",
    "page": "/autos.html",
    "notes": [
        "70503000 is motor vehicles on the export side and parts of motor vehicles "
        "on the import side; the parts line on the export side is 70505000.",
        "Vehicles are counted in number and parts are weighed in kilograms, so a unit "
        "value is yen per vehicle for the vehicle lines and yen per kilogram for parts.",
    ] + mof_trade.NOTES,
}
