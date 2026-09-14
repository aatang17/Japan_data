"""Adapter: pharmaceutical trade — Japan's medical-product imports and exports by partner.

The same principal-commodity by country tables (概況品別国別表) of the Ministry
of Finance *Trade Statistics of Japan* that `mof_trade` reads for
semiconductors, read for medical products (医薬品): the published group in
both directions plus the ingredient lines the Ministry breaks out beneath
it — vitamins, antibiotics and their preparations, hormones. Monthly by
partner country from January 2001, led by **imports**: the question this
slice answers is the size and the sourcing of Japan's pharmaceutical
deficit.

Everything mechanical is `mof_trade`'s; this adapter owns the commodity
table, the validation anchors and the page configuration. Three facts of
the slice:

- **The group is the trade; the lines are small.** Finished medicines are
  inside the medical-products group and are not published as a line of
  their own in this table, so the group is many times the sum of the
  vitamin, antibiotic and hormone lines beneath it. The lines are carried
  because they are published, not because they add up.
- **Commodity codes are direction-specific.** `50703000` is vitamin
  preparations on the export schedule and antibiotics on the import
  schedule; `50705000` is antibiotics on export and hormones on import.
- **Quantities are in kilograms**, except imported antibiotics, which the
  Ministry publishes in grams. A unit value is yen per kilogram (or per
  gram) and is never compared between lines.
"""
from . import mof_trade
from .mof_trade import (PARTNER_EN, PARTNER_JA, PARTNERS, REGIONS, REGION_LABEL,  # noqa: F401
                        partner_region)


class ValidationError(Exception):
    pass


# (code, English label, Japanese label, sort order, level, chart label).
COMMODITIES = {
    "imp": [
        ("50700000", "Medical products", "医薬品", 0, "group", "Medical products"),
        ("50701000", "Provitamins & vitamins", "プロビタミン及びビタミン", 1, "item", "Vitamins"),
        ("50703000", "Antibiotics", "抗生物質", 2, "item", "Antibiotics"),
        ("50705000", "Hormones", "ホルモン", 3, "item", "Hormones"),
        ("50707000", "Antibiotic preparations", "抗生物質製剤", 4, "item",
         "Antibiotic preparations"),
    ],
    "exp": [
        ("50700000", "Medical products", "医薬品", 0, "group", "Medical products"),
        ("50701000", "Provitamins & vitamins", "プロビタミン及びビタミン", 1, "item", "Vitamins"),
        ("50703000", "Vitamin preparations", "ビタミン製剤", 2, "item", "Vitamin preparations"),
        ("50705000", "Antibiotics", "抗生物質", 3, "item", "Antibiotics"),
        ("50709000", "Antibiotic preparations", "抗生物質製剤", 4, "item",
         "Antibiotic preparations"),
    ],
}

VALUE_UNIT = mof_trade.VALUE_UNIT
FIRST_YEAR = mof_trade.FIRST_YEAR
CACHE_KIND = "data-pharma"


DATASET = {
    "slug": "trade-pharma",
    "title": "Pharmaceutical Trade — Imports and Exports by Partner",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Monthly Japanese imports and exports of medical products by partner "
        "country from January 2001: the published group plus the vitamin, "
        "antibiotic and hormone lines beneath it. Value in thousands of yen "
        "and quantity in kilograms (grams for imported antibiotics), exactly "
        "as released by the Ministry of Finance in the principal-commodity "
        "by country tables of the Trade Statistics of Japan. Finished "
        "medicines are inside the group and are not published as a line of "
        "their own. Export and import commodity codes are separate "
        "vocabularies and do not correspond."
    ),
}

SOURCE = {
    "source_id": "estat:00350300:gaikyohin-pharma",
    "name": ("Ministry of Finance — Trade Statistics of Japan, principal "
             "commodity by country tables (medical products)"),
    "name_ja": "財務省 普通貿易統計 概況品別国別表（医薬品）",
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


# The group is the flagship in both directions: medical products must arrive
# from the United States and Germany, and reach the United States and
# Switzerland, every month.
FLAGSHIP = {"imp": "50700000", "exp": "50700000"}
ANCHOR_PARTNERS = {"imp": ("50304", "50213"), "exp": ("50304", "50215")}
MIN_OBSERVATIONS = 150_000   # 300,024 on first ingest

PROFILE = {"flagship": FLAGSHIP, "anchors": ANCHOR_PARTNERS,
           "min_observations": MIN_OBSERVATIONS,
           "flagship_name": "medical-product", "stat_prefix": "pharma"}


def validate(series, observations):
    try:
        return mof_trade.validate(series, observations, PROFILE)
    except mof_trade.ValidationError as e:
        raise ValidationError(str(e))


BALANCE_CALC = mof_trade.balance_calc("medical products", "medical products")

PRESENTATION = {
    "credit_line": mof_trade.CREDIT_LINE,
    "stale_after_days": mof_trade.STALE_AFTER_DAYS,
    "trade": mof_trade.trade_presentation(
        COMMODITIES, "imp", {"imp": "50700000", "exp": "50700000"},
        # The suppliers that make the deficit: the United States, Germany,
        # Switzerland, Ireland, Puerto Rico (a US territory the Ministry
        # codes separately) and China.
        ["50304", "50213", "50215", "50206", "50324", "50105"],
        {
            "name": "Pharmaceutical trade",
            "file_tag": "pharmaceutical",
            "subtitle": ("Monthly imports and exports of medical products — the "
                         "published group and its vitamin, antibiotic and hormone "
                         "lines — by partner country"),
            "partner_slots": {"50304": 2, "50213": 3, "50215": 4, "50206": 5, "50105": 6},
            "default_partners": ["50304", "50213", "50215"],
            "tiles": [
                {"kind": "month", "flow": "imp", "commodity": "50700000",
                 "label": "Medical Product Imports",
                 "title": "World total of Japan's medical-product imports"},
                {"kind": "month", "flow": "exp", "commodity": "50700000",
                 "label": "Medical Product Exports",
                 "title": "World total of Japan's medical-product exports"},
                {"kind": "ttm", "flow": "imp", "commodity": "50700000",
                 "label": "Imports, 12 Months",
                 "title": "World total of Japan's medical-product imports"},
                {"kind": "balance", "exp": "50700000", "imp": "50700000",
                 "label": "Medical Products: Exports − Imports",
                 "title": "Medical products, exports less imports"},
            ],
            "balance_calc": BALANCE_CALC,
            "strip_foot": ("The first two tiles are single months and move with "
                           "shipment timing; the twelve-month total and the balance "
                           "are twelve-month sums. The balance is negative: Japan "
                           "imports far more medicine than it exports."),
        }),
}

MANIFEST = {
    "id": DATASET["slug"],
    "section": "trade",
    "name": {"en": "Pharmaceutical trade — imports and exports by partner",
             "ja": "医薬品の輸出入（相手国別）"},
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
        {"id": "balance", "label": "Trade balance in medical products, 12-month totals",
         "unit": "JPY_thousand", "trust": "derived", "calc": BALANCE_CALC},
    ],
    "endpoints": mof_trade.endpoints(DATASET["slug"]),
    "capabilities": ["series", "search"],
    "cite": "/pharma.html?flow=imp",
    "page": "/pharma.html",
    "notes": [
        "Finished medicines are inside the medical-products group and are not published "
        "as a line of their own; the group is many times the sum of the lines beneath it.",
        "50703000 is vitamin preparations on the export side and antibiotics on the import "
        "side; 50705000 is antibiotics on export and hormones on import.",
        "Imported antibiotics are published in grams, every other line in kilograms.",
    ] + mof_trade.NOTES,
}
