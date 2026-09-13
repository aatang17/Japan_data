"""Adapter: Tokyo ward-area CPI, detailed item indices (2025 base).

Source: Statistics Bureau of Japan via e-Stat file download
(statInfId 000040482967) — 東京都区部 品目別価格指数（1970年1月〜最新月）, 2025年基準.
Same long-run CSV layout as the national item table (see estat_csv.py):
about 750 columns spanning the headline, every aggregation level and the
individually priced items. It exists here for the breadth measure on the
Tokyo advance page — the share of items rising — one month ahead of the
national reading.
"""
from . import cpi_common, estat_csv
from .estat_csv import ValidationError  # noqa: F401 — part of the adapter contract

STAT_INF_ID = "000040482967"

DATASET = {
    "slug": "cpi-tokyo-items",
    "title": "Consumer Price Index — Tokyo ward area (detailed items, advance)",
    "country": "Japan",
    "agency": cpi_common.AGENCY,
    "agency_ja": cpi_common.AGENCY_JA,
    "base": cpi_common.BASE_2025,
    "frequency": "monthly",
    "description": (
        "Official Tokyo ward-area CPI at full item depth from January 1970 to "
        "the latest month, on the 2025 base: every published aggregation "
        "level plus the individual items priced for the index (about 750 "
        "series). The newest month is the mid-month advance."
    ),
}

SOURCE = cpi_common.source(
    STAT_INF_ID,
    "CPI Japan, Tokyo ward area, item-level price indices (Jan 1970 – latest month), 2025 base",
    "消費者物価指数 東京都区部 1 品目別価格指数（1970年1月～最新月） 2025年基準")

DOWNLOAD_URL = cpi_common.download_url(STAT_INF_ID)

PRESENTATION = {
    "main_series": [
        {"role": "headline", "name_ja": "総合", "label": "Headline CPI", "slot": 1},
    ],
    "groups_ja": ["食料", "住居", "光熱・水道", "家具・家事用品", "被服及び履物",
                  "保健医療", "交通・通信", "教育", "教養娯楽", "諸雑費"],
    # leaf items = the individually priced series; aggregates and exclusion
    # indices all carry codes starting with "0" in this table
    "breadth": {"exclude_code_prefix": "0"},
    "stale_after_days": 60,
}


def fetch():
    return estat_csv.fetch_bytes(DOWNLOAD_URL)


def parse(raw_bytes):
    return estat_csv.parse_long_csv(raw_bytes)


def validate(series, observations):
    return estat_csv.check_common(
        series, observations,
        min_series=500, min_observations=200_000,
        required_ja=("総合", "食料", "生鮮食品を除く総合"))


MANIFEST = cpi_common.manifest(
    DATASET, SOURCE, PRESENTATION,
    name={"en": "Consumer Price Index — Tokyo ward area, items (advance)",
          "ja": "消費者物価指数（東京都区部・品目別）"},
    summary=("Tokyo ward-area CPI at full item depth on the 2025 base — every "
             "published aggregate plus the individually priced items — monthly "
             "from January 1970, with the breadth of price rises across the "
             "basket one month ahead of the national reading."),
    page="/tokyo.html", history_from="1970-01", breadth=True,
    notes=[
        "Codes starting with 0 are aggregates; every other code is an individually "
        "priced item. Breadth is computed over the priced items only.",
    ])
