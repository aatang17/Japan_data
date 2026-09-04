"""Adapter: Japan CPI, national, detailed item indices (2020 base).

Source: Statistics Bureau of Japan via e-Stat file download
(statInfId 000032103844) — 品目別価格指数（全国・月次・1970年1月〜最新月）.
Same long-run CSV layout as the middle-class table (see estat_csv.py)
but at full item depth: ~740 columns spanning the headline, every
aggregation level, and individual items (rice varieties, bread,
electricity, mobile phone charges, ...). Many items enter the basket
after 1970, so early cells are blank — missing stays missing.
"""
from . import estat_csv
from .estat_csv import ValidationError  # noqa: F401 — part of the adapter contract

DATASET = {
    "slug": "cpi-jp-items",
    "title": "Consumer Price Index — Japan (national, detailed items)",
    "country": "Japan",
    "agency": "Statistics Bureau of Japan (Ministry of Internal Affairs and Communications)",
    "agency_ja": "総務省統計局",
    "base": "2020=100",
    "frequency": "monthly",
    "description": (
        "Official national CPI at full item depth from January 1970 to the "
        "latest month, on the 2020 base: every published aggregation level "
        "plus the individual items priced for the index (about 740 series)."
    ),
}

SOURCE = {
    "source_id": "e-stat:000032103844",
    "name": "CPI Japan, national, item-level price indices (Jan 1970 – latest month)",
    "name_ja": "消費者物価指数 全国 品目別価格指数（1970年1月～最新月）",
    "url": "https://www.e-stat.go.jp/stat-search/files?stat_infid=000032103844",
    "license_note": (
        "e-Stat terms of use: reuse permitted with attribution to the "
        "Statistics Bureau of Japan."
    ),
}

DOWNLOAD_URL = (
    "https://www.e-stat.go.jp/stat-search/file-download"
    "?statInfId=000032103844&fileKind=1"
)


PRESENTATION = {
    "main_series": [
        {"role": "headline", "name_ja": "総合", "label": "Headline CPI", "slot": 1},
    ],
    # the ten major expenditure groups appear in this table too
    "groups_ja": ["食料", "住居", "光熱・水道", "家具・家事用品", "被服及び履物",
                  "保健医療", "交通・通信", "教育", "教養娯楽", "諸雑費"],
    # leaf items = the 582 individually priced series; aggregates and
    # exclusion indices all carry codes starting with "0" in this table
    "breadth": {"exclude_code_prefix": "0"},
    "stale_after_days": 90,
}


def fetch():
    return estat_csv.fetch_bytes(DOWNLOAD_URL)


def parse(raw_bytes):
    return estat_csv.parse_long_csv(raw_bytes)


def validate(series, observations):
    # ~744 series; early decades are sparse (items enter the basket over
    # time), so the observation floor is well below series × months
    return estat_csv.check_common(
        series, observations,
        min_series=600, min_observations=200_000,
        required_ja=("総合", "食料", "米類", "電気代"),
    )


# The dataset's card — see cpi_jp.MANIFEST for the shape. Formulas are checked
# against api.py by app/registry.py.
MANIFEST = {
    "id": DATASET["slug"],
    "section": "prices",
    "name": {"en": "Consumer Price Index — items",
             "ja": "消費者物価指数（品目別）"},
    "shape": "series",
    "summary": ("National CPI at full item depth on the 2020 base — every "
                "published aggregate plus the 582 individually priced items — "
                "monthly from January 1970, with the breadth of price rises "
                "across the basket."),
    "source": {
        "publisher": DATASET["agency"],
        "publisher_ja": DATASET["agency_ja"],
        "document": SOURCE["name"],
        "url": SOURCE["url"],
        "credit": "Source: Statistics Bureau of Japan.",
        "license_note": SOURCE["license_note"],
    },
    "keys": ["series_code", "period"],
    "frequency": DATASET["frequency"],
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "1970-01",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Index level (2020 = 100)", "unit": "index",
         "trust": "official"},
        {"id": "weight", "label": "Basket weight (parts per 10,000)",
         "unit": "per_10000", "trust": "official"},
        {"id": "yoy", "label": "Year over year", "unit": "%", "trust": "derived",
         "calc": "(index[t] / index[t−12 months] − 1) × 100, from published index values."},
        {"id": "mom", "label": "Month over month", "unit": "%", "trust": "derived",
         "calc": "(index[t] / index[t−1 month] − 1) × 100, from published index values."},
        {"id": "ann3m", "label": "3-month annualized", "unit": "%", "trust": "derived",
         "calc": "((index[t] / index[t−3 months]) ^ 4 − 1) × 100, from published index values."},
        {"id": "contrib_pp", "label": "Contribution to headline YoY", "unit": "pp",
         "trust": "derived",
         "calc": ("contribution[g,t] = weight[g] × (index[g,t] − index[g,t−12]) "
                  "/ (10000 × headline_index[t−12]) × 100, in percentage points. "
                  "Group contributions sum to headline YoY up to a small residual from "
                  "the rounding of published indices and weights.")},
        {"id": "breadth_pct", "label": "Breadth: share of priced items rising / above threshold",
         "unit": "%", "trust": "derived",
         "calc": ("For each month, over the individually priced items with an index value "
                  "in both t and t−12: share with YoY above the threshold, share rising "
                  "(YoY > 0), and share falling (YoY < 0), each as % of those items.")},
        {"id": "notes", "label": "Flags on the latest reading (step, low_base)",
         "unit": "category", "trust": "derived",
         "calc": ("step: the 12-month move is decomposed into its 12 monthly log changes; raised when "
                  "the largest single month is at least 70% of the summed absolute change and moved the "
                  "index by at least 10%. low_base: raised when the latest index level is below 5.0 "
                  "(2020 = 100). Both are calculated from published index values.")},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "summary": "/api/v1/%s/overview" % DATASET["slug"],
        "contributions": "/api/v1/%s/contributions" % DATASET["slug"],
        "breadth": "/api/v1/%s/breadth" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search", "summary"],
    "cite": "/cpi.html",
    "page": "/cpi.html",
    "notes": [
        "Leaf items are the series whose code does not start with 0 (582 "
        "individually priced items; weights sum to about 10,000). Codes "
        "starting with 0 are aggregates and exclusion indices.",
        "Index levels are exactly as published; rates computed from rounded "
        "indices can differ from the Bureau's published rate by ±0.1 pp.",
        "A missing value is missing, never zero.",
    ],
}
