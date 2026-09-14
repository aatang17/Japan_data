"""Adapter: general-machinery trade — Japan exports and imports by partner country.

The same principal-commodity by country tables (概況品別国別表) of the Ministry
of Finance *Trade Statistics of Japan* that `mof_trade` reads for
semiconductors, read for general machinery (一般機械): the published group
plus the capital-goods lines beneath it — machine tools, construction and
mining machinery, internal-combustion engines, pumps and compressors,
bearings on the export side; machine tools, construction machinery,
computers, power-generating machinery and air conditioners on the import
side. Monthly by partner country from January 2001.

Everything mechanical is `mof_trade`'s; this adapter owns the commodity
table, the validation anchors and the page configuration. Two facts of the
slice:

- **Commodity codes are direction-specific.** Construction machinery is
  `70119000` on the export schedule and `70117000` on the import schedule;
  `70119000` on the import side is heating and cooling equipment. Each
  direction carries its own map and the two are never joined on a code.
- **Quantities differ by line and some lines have none.** Machine tools and
  computers are counted in number, engines in kilograms, bearings and
  construction machinery (imports) in tonnes; the group, construction
  machinery (exports), pumps and air conditioners are published with no
  quantity. A line without a quantity has no unit value.
"""
from . import mof_trade
from .mof_trade import (PARTNER_EN, PARTNER_JA, PARTNERS, REGIONS, REGION_LABEL,  # noqa: F401
                        partner_region)


class ValidationError(Exception):
    pass


# (code, English label, Japanese label, sort order, level, chart label).
COMMODITIES = {
    "exp": [
        ("70100000", "General machinery", "一般機械", 0, "group", "General machinery"),
        ("70107010", "Machine tools", "工作機械", 1, "item", "Machine tools"),
        ("70119000", "Construction & mining machinery", "建設用・鉱山用機械", 2, "item",
         "Construction machinery"),
        ("70101030", "Internal-combustion engines", "内燃機関", 3, "item", "Engines"),
        ("70125000", "Pumps & compressors", "ポンプ及び遠心分離機", 4, "item",
         "Pumps & compressors"),
        ("70129000", "Bearings", "ベアリング及び同部分品", 5, "item", "Bearings"),
    ],
    "imp": [
        ("70100000", "General machinery", "一般機械", 0, "group", "General machinery"),
        ("70105050", "Computers & units", "電算機類（含周辺機器）", 1, "item", "Computers"),
        ("70101000", "Power-generating machinery", "原動機", 2, "item",
         "Power-generating machinery"),
        ("70107010", "Machine tools", "工作機械", 3, "item", "Machine tools"),
        ("70117000", "Construction & mining machinery", "建設用・鉱山用機械", 4, "item",
         "Construction machinery"),
        ("70119010", "Air conditioners", "エアコン", 5, "item", "Air conditioners"),
    ],
}

VALUE_UNIT = mof_trade.VALUE_UNIT
FIRST_YEAR = mof_trade.FIRST_YEAR
CACHE_KIND = "data-machinery"


DATASET = {
    "slug": "trade-machinery",
    "title": "Machinery Trade — Exports and Imports by Partner",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Monthly Japanese exports and imports of general machinery by partner "
        "country from January 2001: the published group plus machine tools, "
        "construction and mining machinery, internal-combustion engines, pumps "
        "and compressors and bearings (exports), and computers, "
        "power-generating machinery, machine tools, construction machinery "
        "and air conditioners (imports). Value in thousands of yen and "
        "quantity in the published unit where one is published, exactly as "
        "released by the Ministry of Finance in the principal-commodity by "
        "country tables of the Trade Statistics of Japan. Export and import "
        "commodity codes are separate vocabularies and do not correspond."
    ),
}

SOURCE = {
    "source_id": "estat:00350300:gaikyohin-machinery",
    "name": ("Ministry of Finance — Trade Statistics of Japan, principal "
             "commodity by country tables (general-machinery commodities)"),
    "name_ja": "財務省 普通貿易統計 概況品別国別表（一般機械）",
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


# Machine tools must reach China and the United States every month; computers
# must arrive from China and the United States. If either stops, the parse
# is wrong, not the trade.
FLAGSHIP = {"exp": "70107010", "imp": "70105050"}
ANCHOR_PARTNERS = {"exp": ("50105", "50304"), "imp": ("50105", "50304")}
MIN_OBSERVATIONS = 320_000   # 640,706 on first ingest

PROFILE = {"flagship": FLAGSHIP, "anchors": ANCHOR_PARTNERS,
           "min_observations": MIN_OBSERVATIONS,
           "flagship_name": "machine-tool / computer", "stat_prefix": "flagship"}


def validate(series, observations):
    try:
        return mof_trade.validate(series, observations, PROFILE)
    except mof_trade.ValidationError as e:
        raise ValidationError(str(e))


BALANCE_CALC = mof_trade.balance_calc("general machinery", "general machinery")

PRESENTATION = {
    "credit_line": mof_trade.CREDIT_LINE,
    "stale_after_days": mof_trade.STALE_AFTER_DAYS,
    "trade": mof_trade.trade_presentation(
        COMMODITIES, "exp", {"exp": "70107010", "imp": "70105050"},
        # China and the United States first — the machinery story is the
        # gap between the two — then Taiwan, Korea, Germany and Thailand.
        ["50105", "50304", "50106", "50103", "50213", "50111"],
        {
            "name": "Machinery trade",
            "file_tag": "machinery",
            "subtitle": ("Monthly trade in general machinery — machine tools, "
                         "construction equipment, engines, pumps, bearings, "
                         "computers — by partner country"),
            "partner_slots": {"50105": 2, "50304": 3, "50106": 4, "50103": 5, "50213": 6},
            "default_partners": ["50105", "50304"],
            "tiles": [
                {"kind": "month", "flow": "exp", "commodity": "70100000",
                 "label": "Machinery Exports",
                 "title": "World total of Japan's general-machinery exports"},
                {"kind": "month", "flow": "exp", "commodity": "70107010",
                 "label": "Machine Tool Exports",
                 "title": "World total of Japan's machine-tool exports"},
                {"kind": "month", "flow": "exp", "commodity": "70119000",
                 "label": "Construction Machinery Exports",
                 "title": "World total of Japan's construction and mining machinery exports"},
                {"kind": "balance", "exp": "70100000", "imp": "70100000",
                 "label": "Machinery: Exports − Imports",
                 "title": "General machinery, exports less imports"},
            ],
            "balance_calc": BALANCE_CALC,
            "strip_foot": ("The first three tiles are single months and move with "
                           "shipment timing; the balance is a twelve-month sum."),
        }),
}

MANIFEST = {
    "id": DATASET["slug"],
    "section": "trade",
    "name": {"en": "Machinery trade — exports and imports by partner",
             "ja": "一般機械の輸出入（相手国別）"},
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
        {"id": "balance", "label": "Trade balance in general machinery, 12-month totals",
         "unit": "JPY_thousand", "trust": "derived", "calc": BALANCE_CALC},
    ],
    "endpoints": mof_trade.endpoints(DATASET["slug"]),
    "capabilities": ["series", "search"],
    "cite": "/machinery.html",
    "page": "/machinery.html",
    "notes": [
        "Construction and mining machinery is 70119000 on the export side and 70117000 on "
        "the import side; 70119000 on the import side is heating and cooling equipment.",
        "The group, construction machinery (exports), pumps and air conditioners are "
        "published without a quantity and therefore have no unit value.",
    ] + mof_trade.NOTES,
}
