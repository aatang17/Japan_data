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
