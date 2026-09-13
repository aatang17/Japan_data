"""Adapter: Tokyo ward-area CPI, middle-class indices (2025 base) — the advance reading.

Source: Statistics Bureau of Japan via e-Stat file download
(statInfId 000040482965) — 東京都区部 中分類指数（1970年1月〜最新月）, 2025年基準.
Same long-run CSV layout as the national table (see estat_csv.py) and the
same 78 series, for the 23 wards of Tokyo.

Why it earns its own page: the Bureau publishes the Tokyo ward area's
figure for a month at the end of that month — the 中旬速報値, the
mid-month advance — three weeks before the national figure for the same
month. The long-run file carries the advance as its newest month, so this
dataset is always one month ahead of `cpi-jp`, and the page reads the two
side by side. Tokyo is about a tenth of the national basket by weight and
runs a little cooler on rent and hotter on services than the country, so
it is a lead, not a forecast.

Vintages matter more here than anywhere: the advance is revised to a
final figure a month later and the two are stored as separate releases.
"""
from . import cpi_common, estat_csv
from .estat_csv import ValidationError  # noqa: F401 — part of the adapter contract

STAT_INF_ID = "000040482965"

DATASET = {
    "slug": "cpi-tokyo",
    "title": "Consumer Price Index — Tokyo ward area (middle-class indices, advance)",
    "country": "Japan",
    "agency": cpi_common.AGENCY,
    "agency_ja": cpi_common.AGENCY_JA,
    "base": cpi_common.BASE_2025,
    "frequency": "monthly",
    "description": (
        "Official Tokyo ward-area CPI middle-class indices from January 1970 "
        "to the latest month, on the 2025 base — headline, the exclusion-based "
        "cores, the ten major expenditure groups and middle-class items. The "
        "newest month is the mid-month advance, published about three weeks "
        "before the national figure for the same month."
    ),
}

SOURCE = cpi_common.source(
    STAT_INF_ID,
    "CPI Japan, Tokyo ward area, Table 1: middle-class indices (Jan 1970 – latest month), 2025 base",
    "消費者物価指数 東京都区部 1 中分類指数（1970年1月～最新月） 2025年基準")

DOWNLOAD_URL = cpi_common.download_url(STAT_INF_ID)

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
    # The advance for a month lands at the end of that month, so this
    # surface is stale sooner than the national one.
    "stale_after_days": 60,
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
                     "生鮮食品及びエネルギーを除く総合", "食料"))


MANIFEST = cpi_common.manifest(
    DATASET, SOURCE, PRESENTATION,
    name={"en": "Consumer Price Index — Tokyo ward area (advance)",
          "ja": "消費者物価指数（東京都区部・中分類）"},
    summary=("Tokyo ward-area CPI on the 2025 base — headline, the exclusion-based "
             "cores and the ten major expenditure groups — monthly from January "
             "1970. The newest month is the mid-month advance, about three weeks "
             "ahead of the national release, with contributions to headline."),
    page="/tokyo.html", history_from="1970-01",
    notes=[
        "The newest month is the Tokyo ward-area mid-month advance (中旬速報値), "
        "revised to a final figure with the following month's release; both are "
        "stored as vintages.",
        "Tokyo's basket weights differ from the national ones (rent is heavier, "
        "food lighter), so Tokyo and national rates are compared, never combined.",
    ])
