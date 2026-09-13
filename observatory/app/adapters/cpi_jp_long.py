"""Adapter: Japan CPI, national, all items less imputed rent, from August 1946 (2025 base).

Source: Statistics Bureau of Japan via e-Stat file download
(statInfId 000040482944) — 全国 持家の帰属家賃を除く総合指数（1946年8月〜最新月）, 2025年基準.
Same long-run CSV layout as the other tables (see estat_csv.py) with a
single column: the longest consumer-price series the Bureau publishes,
eighty years of monthly readings on one base.

Why *less imputed rent*: the rent a homeowner notionally pays themself
only entered the index in 1970, so the one aggregate that can be carried
back to the post-war price collapse is the headline without it. On the
2025 base it covers 8,366 of the 10,000 basket weight. The post-war
months carry inflation rates in the hundreds of percent, which is the
point of the page: the reference every "highest since" claim needs.
"""
from . import cpi_common, estat_csv
from .estat_csv import ValidationError  # noqa: F401 — part of the adapter contract

STAT_INF_ID = "000040482944"

DATASET = {
    "slug": "cpi-jp-long",
    "title": "Consumer Price Index — Japan (all items less imputed rent, from 1946)",
    "country": "Japan",
    "agency": cpi_common.AGENCY,
    "agency_ja": cpi_common.AGENCY_JA,
    "base": cpi_common.BASE_2025,
    "frequency": "monthly",
    "description": (
        "Official national CPI for all items less imputed rent from August "
        "1946 to the latest month, on the 2025 base — the longest consumer "
        "price series the Statistics Bureau publishes, linked across every "
        "rebasing since the post-war index began."
    ),
}

SOURCE = cpi_common.source(
    STAT_INF_ID,
    "CPI Japan, national, all items less imputed rent (Aug 1946 – latest month), 2025 base",
    "消費者物価指数 全国 1 持家の帰属家賃を除く総合指数（1946年8月～最新月） 2025年基準")

DOWNLOAD_URL = cpi_common.download_url(STAT_INF_ID)

PRESENTATION = {
    "main_series": [
        {"role": "headline", "name_ja": "持家の帰属家賃を除く総合",
         "label": "All items less imputed rent", "slot": 1},
    ],
    "groups_ja": [],
    "stale_after_days": cpi_common.STALE_AFTER_DAYS,
}


def fetch():
    return estat_csv.fetch_bytes(DOWNLOAD_URL)


def parse(raw_bytes):
    return estat_csv.parse_long_csv(raw_bytes)


def validate(series, observations):
    return estat_csv.check_common(
        series, observations,
        min_series=1, min_observations=900,
        required_ja=("持家の帰属家賃を除く総合",),
        headline_ja="持家の帰属家賃を除く総合")


MANIFEST = cpi_common.manifest(
    DATASET, SOURCE, PRESENTATION,
    name={"en": "Consumer Price Index — since 1946",
          "ja": "消費者物価指数（持家の帰属家賃を除く総合・1946年〜）"},
    summary=("National CPI for all items less imputed rent on the 2025 base, "
             "monthly from August 1946 — eighty years on one linked base, the "
             "reference for any 'highest since' comparison."),
    page="/cpi-long.html", history_from="1946-08",
    contributions=False,
    notes=[
        "Imputed rent entered the index in 1970, so the aggregate that reaches back "
        "to 1946 is the headline without it (8,366 of 10,000 by weight on the 2025 base).",
        "Post-war months carry year-over-year rates in the hundreds of percent; they "
        "are published figures and are shown as such.",
    ])
