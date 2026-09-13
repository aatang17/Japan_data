"""Adapter: Japan CPI, national, seasonally adjusted indices (2025 base).

Source: Statistics Bureau of Japan via e-Stat file download
(statInfId 000040482947) — 全国 季節調整済指数（2010年1月〜最新月）, 2025年基準.
Same long-run CSV layout as the middle-class table (see estat_csv.py) but
only five series — headline, core, core-core, goods, services — each
seasonally adjusted by the Bureau, from January 2010, and **published
without weights**: the weight rows are blank, so there is no group
decomposition and no contribution on this dataset.

This is the table for the month-on-month and three-month-annualised
readings. The unadjusted indices carry a seasonal pattern (April price
resets, year-end) that makes a single month's change unreadable; the
Bureau's adjustment removes it, and every month of the adjusted history
is revised when the adjustment is re-estimated — which is why the
vintage store matters for this small table.
"""
from . import cpi_common, estat_csv
from .estat_csv import ValidationError  # noqa: F401 — part of the adapter contract

STAT_INF_ID = "000040482947"

DATASET = {
    "slug": "cpi-jp-sa",
    "title": "Consumer Price Index — Japan (national, seasonally adjusted)",
    "country": "Japan",
    "agency": cpi_common.AGENCY,
    "agency_ja": cpi_common.AGENCY_JA,
    "base": cpi_common.BASE_2025,
    "frequency": "monthly",
    "description": (
        "Official seasonally adjusted national CPI from January 2010 to the "
        "latest month, on the 2025 base: headline, core (less fresh food), "
        "core-core (less fresh food and energy), goods and services. "
        "Adjusted by the Statistics Bureau; the whole history moves when "
        "the adjustment is re-estimated."
    ),
}

SOURCE = cpi_common.source(
    STAT_INF_ID,
    "CPI Japan, national, seasonally adjusted indices (Jan 2010 – latest month), 2025 base",
    "消費者物価指数 全国 1 季節調整済指数（2010年1月～最新月） 2025年基準")

DOWNLOAD_URL = cpi_common.download_url(STAT_INF_ID)

PRESENTATION = {
    "main_series": [
        {"role": "headline", "name_ja": "総合（季節調整済）",
         "label": "Headline CPI (seasonally adjusted)", "slot": 1},
        {"role": "core", "name_ja": "生鮮食品を除く総合（季節調整済）",
         "label": "Core CPI (less fresh food, seasonally adjusted)", "slot": 2},
        {"role": "corecore", "name_ja": "生鮮食品及びエネルギーを除く総合（季節調整済）",
         "label": "Core-core CPI (less fresh food & energy, seasonally adjusted)", "slot": 3},
        {"role": "goods", "name_ja": "財（季節調整済）",
         "label": "Goods (seasonally adjusted)", "slot": 4},
        {"role": "services", "name_ja": "サービス（季節調整済）",
         "label": "Services (seasonally adjusted)", "slot": 5},
    ],
    "groups_ja": [],           # no weights are published for this table
    "stale_after_days": cpi_common.STALE_AFTER_DAYS,
}


def fetch():
    return estat_csv.fetch_bytes(DOWNLOAD_URL)


def parse(raw_bytes):
    return estat_csv.parse_long_csv(raw_bytes)


def validate(series, observations):
    return estat_csv.check_common(
        series, observations,
        min_series=5, min_observations=900,
        required_ja=("総合（季節調整済）", "生鮮食品を除く総合（季節調整済）"),
        headline_ja="総合（季節調整済）")


MANIFEST = cpi_common.manifest(
    DATASET, SOURCE, PRESENTATION,
    name={"en": "Consumer Price Index — seasonally adjusted",
          "ja": "消費者物価指数（季節調整済）"},
    summary=("Seasonally adjusted national CPI on the 2025 base — headline, core, "
             "core-core, goods and services — monthly from January 2010, for "
             "month-on-month and three-month annualised readings free of the "
             "seasonal pattern."),
    page="/cpi-sa.html", history_from="2010-01",
    weights=False, contributions=False,
    notes=[
        "Seasonal adjustment is the Bureau's; the whole adjusted history is revised "
        "when the adjustment is re-estimated, and each revision is a new vintage.",
        "No weights are published for the adjusted series, so there is no group "
        "decomposition on this dataset.",
    ])
