"""What every Statistics Bureau CPI dataset shares: the source identity
pattern, the published-versus-calculated measures, and the card.

The Bureau publishes one long-run CSV layout for every cut of the index —
national and Tokyo ward area, middle-class and item depth, goods/services,
seasonally adjusted, and the 1946– all-items-less-imputed-rent series.
estat_csv.py parses them; this module builds the identical parts of each
adapter so a new cut is a file id, a base year, the roles its series play,
and nothing else.

Base years matter here. The Bureau rebases every five years and publishes
the rebased history under a **new** e-Stat file id; the old id keeps
serving the old base and stops updating. The 2025 base arrived on
2026-08-28 (Tokyo ward area, August 2026 advance) with the 2020-base files
frozen at July 2026. Every adapter therefore names its base explicitly and
the pages read it from the release rather than assuming one.
"""

AGENCY = "Statistics Bureau of Japan (Ministry of Internal Affairs and Communications)"
AGENCY_JA = "総務省統計局"
CREDIT = "Source: Statistics Bureau of Japan."
LICENSE_NOTE = ("e-Stat terms of use: reuse permitted with attribution to the "
                "Statistics Bureau of Japan.")
STALE_AFTER_DAYS = 90     # releases land ~3 weeks after the reference month

BASE_2025 = "2025=100"

CALC_YOY = "(index[t] / index[t−12 months] − 1) × 100, from published index values."
CALC_MOM = "(index[t] / index[t−1 month] − 1) × 100, from published index values."
CALC_ANN3M = "((index[t] / index[t−3 months]) ^ 4 − 1) × 100, from published index values."
CALC_CONTRIB = ("contribution[g,t] = weight[g] × (index[g,t] − index[g,t−12]) "
                "/ (10000 × headline_index[t−12]) × 100, in percentage points. "
                "Group contributions sum to headline YoY up to a small residual from "
                "the rounding of published indices and weights.")
CALC_NOTES = ("step: the 12-month move is decomposed into its 12 monthly log changes; raised when "
              "the largest single month is at least 70% of the summed absolute change and moved the "
              "index by at least 10%. low_base: raised when the latest index level is below 5.0 "
              "(base year = 100). Both are calculated from published index values.")

COMMON_NOTES = [
    "Index levels are exactly as published. A rate computed from published "
    "(rounded) indices can differ from the Bureau's own published rate by "
    "±0.1 pp; nothing is adjusted to close that gap.",
    "Weights are parts per 10,000 (１万分比), not percent.",
    "A missing value is missing, never zero.",
    "The Bureau rebases every five years and publishes the rebased history under a "
    "new e-Stat file; the switch from the 2020 base to the 2025 base is stored as a "
    "new vintage, and an as-of query before it returns the 2020-base figures.",
]


def source(stat_inf_id, name, name_ja):
    return {
        "source_id": "e-stat:%s" % stat_inf_id,
        "name": name,
        "name_ja": name_ja,
        "url": "https://www.e-stat.go.jp/stat-search/files?stat_infid=%s" % stat_inf_id,
        "license_note": LICENSE_NOTE,
    }


def download_url(stat_inf_id):
    return ("https://www.e-stat.go.jp/stat-search/file-download"
            "?statInfId=%s&fileKind=1" % stat_inf_id)


def measures(base, weights=True, contributions=True):
    """The card's measure list: published index (and weight), then the
    calculated rates with the formulas the API uses (checked by the registry)."""
    out = [{"id": "index", "label": "Index level (%s)" % base.replace("=", " = "),
            "unit": "index", "trust": "official"}]
    if weights:
        out.append({"id": "weight", "label": "Basket weight (parts per 10,000)",
                    "unit": "per_10000", "trust": "official"})
    out += [
        {"id": "yoy", "label": "Year over year", "unit": "%", "trust": "derived",
         "calc": CALC_YOY},
        {"id": "mom", "label": "Month over month", "unit": "%", "trust": "derived",
         "calc": CALC_MOM},
        {"id": "ann3m", "label": "3-month annualized", "unit": "%", "trust": "derived",
         "calc": CALC_ANN3M},
    ]
    if contributions:
        out.append({"id": "contrib_pp", "label": "Contribution to headline YoY",
                    "unit": "pp", "trust": "derived", "calc": CALC_CONTRIB})
    out.append({"id": "notes", "label": "Flags on the latest reading (step, low_base)",
                "unit": "category", "trust": "derived", "calc": CALC_NOTES})
    return out


def manifest(dataset, src, presentation, name, summary, page, history_from,
             notes=(), weights=True, contributions=True, breadth=False, cite=None):
    slug = dataset["slug"]
    endpoints = {
        "series": "/api/v1/%s/observations" % slug,
        "search": "/api/v1/%s/series" % slug,
        "summary": "/api/v1/%s/overview" % slug,
        "releases": "/api/v1/%s/releases" % slug,
        "revisions": "/api/v1/%s/revisions" % slug,
    }
    if contributions:
        endpoints["contributions"] = "/api/v1/%s/contributions" % slug
    if breadth:
        endpoints["breadth"] = "/api/v1/%s/breadth" % slug
    return {
        "id": slug,
        "section": "prices",
        "name": name,
        "shape": "series",
        "summary": summary,
        "source": {
            "publisher": dataset["agency"],
            "publisher_ja": dataset["agency_ja"],
            "document": src["name"],
            "url": src["url"],
            "credit": CREDIT,
            "license_note": src["license_note"],
        },
        "keys": ["series_code", "period"],
        "frequency": dataset["frequency"],
        "vintage": {
            "unit": "release", "as_of_basis": "release-in-force",
            "as_of_supported": True, "history_from": history_from,
            "stale_after_days": presentation["stale_after_days"],
        },
        "measures": measures(dataset["base"], weights=weights, contributions=contributions),
        "endpoints": endpoints,
        "capabilities": ["series", "search", "summary"],
        "cite": cite or page,
        "page": page,
        "notes": list(notes) + COMMON_NOTES,
    }
