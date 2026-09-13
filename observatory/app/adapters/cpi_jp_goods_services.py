"""Adapter: Japan CPI, national, goods and services classification (2025 base).

Source: Statistics Bureau of Japan via e-Stat file download
(statInfId 000040482946) — 全国 財・サービス分類指数（1970年1月〜最新月）, 2025年基準.
Same long-run CSV layout as the middle-class table (see estat_csv.py),
41 series cutting the same basket the other way: goods (agricultural
products, industrial products, utilities, publications) against services
(public and general), plus the durable / semi-durable / non-durable and
public-utility-charge groupings.

The split is the one the Bank of Japan reads for the second-round
question: goods inflation is imported and fades, services inflation is
wages and sticks. Six of the published groups partition the headline
exactly — agricultural products, industrial products, electricity/gas/water,
publications, public services, general services — and those carry the
contributions on the page. Several sub-lines share a Japanese name across
the public and general branches (外食, 家事関連サービス, …); they are stored
under their own codes and never resolved by name.
"""
from . import cpi_common, estat_csv
from .estat_csv import ValidationError  # noqa: F401 — part of the adapter contract

STAT_INF_ID = "000040482946"

DATASET = {
    "slug": "cpi-jp-goods-services",
    "title": "Consumer Price Index — Japan (national, goods and services classification)",
    "country": "Japan",
    "agency": cpi_common.AGENCY,
    "agency_ja": cpi_common.AGENCY_JA,
    "base": cpi_common.BASE_2025,
    "frequency": "monthly",
    "description": (
        "Official national CPI on the goods and services classification from "
        "January 1970 to the latest month, on the 2025 base: goods and their "
        "components (agricultural, industrial, utilities, publications), "
        "services (public and general, rent and imputed rent), and the "
        "durability and public-utility groupings — 41 series."
    ),
}

SOURCE = cpi_common.source(
    STAT_INF_ID,
    "CPI Japan, national, goods and services classification indices (Jan 1970 – latest month), 2025 base",
    "消費者物価指数 全国 1 財・サービス分類指数（1970年1月～最新月） 2025年基準")

DOWNLOAD_URL = cpi_common.download_url(STAT_INF_ID)

PRESENTATION = {
    "main_series": [
        {"role": "headline", "name_ja": "総合", "label": "Headline CPI", "slot": 1},
        {"role": "goods", "name_ja": "財", "label": "Goods", "slot": 2},
        {"role": "services", "name_ja": "サービス", "label": "Services", "slot": 3},
    ],
    # Six published groups that partition the headline: four goods, two
    # services. Weights sum to 10,001 of 10,000 from published rounding.
    "groups_ja": ["農水畜産物", "工業製品", "電気・都市ガス・水道", "出版物",
                  "公共サービス", "一般サービス"],
    "stale_after_days": cpi_common.STALE_AFTER_DAYS,
}


def fetch():
    return estat_csv.fetch_bytes(DOWNLOAD_URL)


def parse(raw_bytes):
    return estat_csv.parse_long_csv(raw_bytes)


def validate(series, observations):
    return estat_csv.check_common(
        series, observations,
        min_series=30, min_observations=20_000,
        required_ja=("総合", "財", "サービス", "工業製品", "一般サービス"))


MANIFEST = cpi_common.manifest(
    DATASET, SOURCE, PRESENTATION,
    name={"en": "Consumer Price Index — goods and services",
          "ja": "消費者物価指数（財・サービス分類）"},
    summary=("National CPI on the 2025 base cut into goods and services — "
             "agricultural and industrial products, utilities, public and "
             "general services, durables — monthly from January 1970, with "
             "each group's contribution to headline inflation."),
    page="/goods-services.html", history_from="1970-01",
    notes=[
        "Several sub-lines share a Japanese name across the public-services and "
        "general-services branches; series are identified by code, never by name.",
        "The two rent splits by structure (wooden / non-wooden) are published "
        "without weights.",
    ])
