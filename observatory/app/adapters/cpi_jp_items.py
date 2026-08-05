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
