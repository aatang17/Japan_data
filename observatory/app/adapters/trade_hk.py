"""Adapter: external merchandise trade — Hong Kong (C&SD), monthly.

Source: the Census and Statistics Department's web tables (censtatd.py):

- 410-50001  imports (c.i.f.), total exports (f.o.b.), total trade and the
             merchandise trade balance, in HK$ million — monthly from January
             1952 (total trade from 1972);
- 410-50002  seasonally adjusted imports and total exports, published only as
             the change of the latest three months over the preceding three,
             in percent — monthly from June 1974.

Total exports are domestic exports plus re-exports, as the C&SD publishes
them. The balance crosses zero and is served as a flow: a percentage change
of it is refused. The seasonally adjusted rates are stored as published, as
rates.
"""
import datetime

from . import censtatd
from .censtatd import ValidationError  # noqa: F401 — part of the adapter contract

TABLES = [
    {"id": "410-50001", "freq": "M", "sv_order": ["VAL_TX", "VAL_IM", "BAL", "VAL_TT"]},
    {"id": "410-50002", "freq": "M", "rates_of_change": True,
     "sv_order": ["SA_VAL_TX", "SA_VAL_IM"]},
]

DATASET = {
    "slug": "trade-hk",
    "title": "External merchandise trade — Hong Kong (exports, imports, balance)",
    "country": "Hong Kong",
    "agency": censtatd.AGENCY,
    "agency_ja": None,
    "base": None,
    "frequency": "monthly",
    "description": (
        "Hong Kong's monthly merchandise trade from the Census and Statistics "
        "Department: total exports, imports, total trade and the trade balance "
        "in HK$ million from 1952, and the seasonally adjusted three-month "
        "change in exports and imports from 1974."
    ),
}

SOURCE = {
    "source_id": "censtatd:410-5000x",
    "name": "C&SD tables 410-50001 and 410-50002 — External merchandise trade",
    "name_ja": None,
    "url": censtatd.WEB_TABLE % "410-50001",
    "license_note": censtatd.LICENSE_NOTE,
}

DOWNLOAD_URL = censtatd.table_url("410-50001")
RAW_SUFFIX = ".json"

FLOWS = ("BAL",)
KINDS = {"BAL": "flow", "SA_VAL_TX": "rate", "SA_VAL_IM": "rate"}

PRESENTATION = {
    "credit_line": censtatd.CREDIT,
    "stale_after_days": 95,   # released ~4 weeks after the month
    "overview_tiles": [
        {"key": "exports", "code": "VAL_TX", "label": "Total exports", "type": "level",
         "compare_months": 12},
        {"key": "imports", "code": "VAL_IM", "label": "Imports", "type": "level",
         "compare_months": 12},
        {"key": "balance", "code": "BAL", "label": "Trade balance", "type": "level",
         "compare_months": 12},
        {"key": "sa_exports", "code": "SA_VAL_TX", "label": "Exports, SA 3-month change",
         "type": "level"},
    ],
    "main_series": [
        {"role": "exports", "code": "VAL_TX", "label": "Total exports", "slot": 1},
        {"role": "imports", "code": "VAL_IM", "label": "Imports", "slot": 2},
    ],
    "kinds": KINDS,
    "kind_default": "level",
}


def fetch():
    return censtatd.fetch([t["id"] for t in TABLES])


canonical_bytes = censtatd.canonical_bytes


def _name(spec, sv, stat, part, desc):
    if sv.startswith("SA_"):
        return "%s: change of the latest 3 months over the preceding 3" % stat
    return stat


def parse(raw_bytes):
    return censtatd.parse(raw_bytes, TABLES, name_fn=_name)


def validate(series, observations):
    if censtatd.kinds(series, FLOWS) != KINDS:
        raise ValidationError("series kinds changed: %s" % censtatd.kinds(series, FLOWS))
    codes = ["VAL_TX", "VAL_IM", "BAL", "VAL_TT", "SA_VAL_TX", "SA_VAL_IM"]
    if sorted(s["code"] for s in series) != sorted(codes):
        raise ValidationError("series %s, expected %s" % (sorted(s["code"] for s in series), codes))
    latest = censtatd.check(series, observations, codes,
                            first_period=datetime.date(1952, 1, 1), max_age_days=150,
                            ranges={"hkd_million": (-1e6, 2e6), "percent": (-90.0, 300.0)})
    # The balance is exports less imports, as published; a mismatch beyond
    # rounding is a column read wrongly.
    v = dict(((o["code"], o["period"]), o["value"]) for o in observations)
    for (code, period), bal in v.items():
        if code != "BAL" or ("VAL_TX", period) not in v or ("VAL_IM", period) not in v:
            continue
        if abs(v[("VAL_TX", period)] - v[("VAL_IM", period)] - bal) > 2:
            raise ValidationError("balance %s: %r is not exports less imports" % (period, bal))
    return {"series": len(series), "observations": len(observations),
            "latest_period": latest.isoformat(), "exports_hkd_million": v.get(("VAL_TX", latest)),
            "balance_hkd_million": v.get(("BAL", latest))}


MANIFEST = censtatd.manifest(
    DATASET, SOURCE, PRESENTATION, section="trade",
    name={"en": "Hong Kong merchandise trade", "ja": "香港貨物貿易"},
    summary=("Hong Kong's monthly merchandise trade — total exports, imports, total "
             "trade and the balance from 1952, and the seasonally adjusted "
             "three-month change in exports and imports from 1974."),
    page="/hk-economy.html", cite="/hk-economy.html?dataset=trade-hk", history_from="1952-01",
    measures=[
        {"id": "index", "label": "Published value — HK$ million; the seasonally adjusted "
                                 "series are rates in percent",
         "unit": "index", "trust": "official"},
    ],
    notes=[
        "Total exports are domestic exports plus re-exports. Imports are c.i.f., "
        "exports f.o.b.",
        "The trade balance crosses zero; a percentage change of it is refused.",
        "A year-on-year rate calculated from the published values matches the "
        "C&SD's own to 0.1 pp from 1968 on; in the 1950s and 1960s, when monthly "
        "trade was a few hundred HK$ million published to the whole million, it "
        "can differ by up to 0.4 pp.",
        "The seasonally adjusted series are published only as the change of the "
        "latest three months over the preceding three, and are stored as published.",
    ])
