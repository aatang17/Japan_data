"""Adapter: Japan CPI, national, middle-class indices (2020 base).

Source: Statistics Bureau of Japan via e-Stat file download
(statInfId 000032103842) — 中分類指数（全国・月次・1970年1月〜最新月）.
CSV layout and parsing are shared with the other long-run CPI files;
see estat_csv.py. The adapter returns plain dicts; it never touches
the database schema.
"""
from . import estat_csv
from .estat_csv import ValidationError  # noqa: F401 — part of the adapter contract

DATASET = {
    "slug": "cpi-jp",
    "title": "Consumer Price Index — Japan (national, middle-class indices)",
    "country": "Japan",
    "agency": "Statistics Bureau of Japan (Ministry of Internal Affairs and Communications)",
    "agency_ja": "総務省統計局",
    "base": "2020=100",
    "frequency": "monthly",
    "description": (
        "Official national CPI middle-class indices from January 1970 to the "
        "latest month, on the 2020 base. Includes headline and exclusion-based "
        "aggregates, the ten major expenditure groups, and middle-class items."
    ),
}

SOURCE = {
    "source_id": "e-stat:000032103842",
    "name": "CPI Japan, national, Table 1: middle-class indices (Jan 1970 – latest month)",
    "name_ja": "消費者物価指数 全国 1 中分類指数（1970年1月～最新月）",
    "url": "https://www.e-stat.go.jp/stat-search/files?stat_infid=000032103842",
    "license_note": (
        "e-Stat terms of use: reuse permitted with attribution to the "
        "Statistics Bureau of Japan."
    ),
}

DOWNLOAD_URL = (
    "https://www.e-stat.go.jp/stat-search/file-download"
    "?statInfId=000032103842&fileKind=1"
)


# Presentation config consumed by the API layer. Dataset-specific roles
# (what "headline" means, which series are the major groups) live here so
# the core schema and API code stay dataset-agnostic. Series are resolved
# by official Japanese name at query time, never by column position.
PRESENTATION = {
    "main_series": [
        {"role": "headline", "name_ja": "総合", "label": "Headline CPI", "slot": 1},
        {"role": "core", "name_ja": "生鮮食品を除く総合",
         "label": "Core CPI (less fresh food)", "slot": 2},
        {"role": "corecore", "name_ja": "生鮮食品及びエネルギーを除く総合",
         "label": "Core-core CPI (less fresh food & energy)", "slot": 3},
    ],
    "groups_ja": ["食料", "住居", "光熱・水道", "家具・家事用品", "被服及び履物",
                  "保健医療", "交通・通信", "教育", "教養娯楽", "諸雑費"],
    # official releases land roughly three weeks after the reference month;
    # beyond this many days after the latest period the surface is stale
    "stale_after_days": 90,
}


def fetch():
    return estat_csv.fetch_bytes(DOWNLOAD_URL)


def parse(raw_bytes):
    return estat_csv.parse_long_csv(raw_bytes)


def validate(series, observations):
    return estat_csv.check_common(
        series, observations,
        min_series=50, min_observations=30_000,
        required_ja=("総合", "生鮮食品を除く総合",
                     "生鮮食品及びエネルギーを除く総合", "食料"),
    )


# The dataset's card: what it is, where it comes from, which numbers are
# published and which are calculated (with the formula the API uses — checked
# against api.py by app/registry.py, so the two cannot drift).
MANIFEST = {
    "id": DATASET["slug"],
    "section": "prices",
    "name": {"en": "Consumer Price Index — categories",
             "ja": "消費者物価指数（中分類）"},
    "shape": "series",
    "summary": ("National CPI on the 2020 base — headline, the exclusion-based "
                "cores and the ten major expenditure groups — monthly from "
                "January 1970, with contributions to headline inflation."),
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
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search", "summary"],
    "cite": "/cpi.html",
    "page": "/cpi.html",
    "notes": [
        "Index levels are exactly as published. A rate computed from published "
        "(rounded) indices can differ from the Bureau's own published rate by "
        "±0.1 pp; nothing is adjusted to close that gap.",
        "Weights are parts per 10,000 (１万分比), not percent.",
        "A missing value is missing, never zero.",
    ],
}
