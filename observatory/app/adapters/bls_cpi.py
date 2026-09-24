"""What every US CPI dataset shares: the BLS CPI-U files, how a cut is
selected from them, and the card.

The BLS publishes the Consumer Price Index for All Urban Consumers (CPI-U) as
one flat-file directory (`cu`, see bls_flat.py): about 8,100 series, one per
item × area × seasonal adjustment × frequency. The platform's three US CPI
datasets are three cuts of that one directory, in the same way the Japanese
CPI is cut into national, seasonally adjusted and Tokyo tables:

    cpi-us        U.S. city average, not seasonally adjusted  (~400 series)
    cpi-us-sa     U.S. city average, seasonally adjusted      (~325 series)
    cpi-us-areas  regions, size classes and metro areas, NSA  (~3,400 series)

Each keeps the BLS series id (`CUUR0000SA0`) as its code, so any figure here
can be looked up on bls.gov by the same id.

Left out, on purpose:

- **Semiannual series** (periodicity S) — the same items at half-year
  frequency, published for areas that are priced every other month. The
  monthly series of those areas are here, gaps and all.
- **Alternate-base series** (base code A, "- old base", e.g. 1967=100) —
  the same index rescaled to an older reference period. Rates of change are
  identical, and two index levels for one item would invite a wrong one.
- **Purchasing power of the consumer dollar** — a dollar amount derived
  from the index, not an index. A YoY rate on it would be arithmetic noise.
- **Annual averages (M13)** — the BLS's own mean of the twelve months.

**Reference periods differ by series.** Most indices are 1982-84=100; items
introduced later carry their own (December 1997=100, December 2017=100, ...).
The dataset-level base says 1982-84=100, so any series on another base names
its base in its own title. Rates of change do not depend on the base.

**Seasonal factors are revised.** Each February the BLS recomputes five
years of seasonally adjusted values. That arrives here as a new vintage of
cpi-us-sa; the not-seasonally-adjusted indices are final when first
published and are not revised.
"""
import datetime

from . import bls_flat

AGENCY = "U.S. Bureau of Labor Statistics"
CREDIT = "Source: U.S. Bureau of Labor Statistics."
LICENSE_NOTE = ("Work of the United States Government, in the public domain "
                "(17 U.S.C. §105). Cite the Bureau of Labor Statistics as the source.")
SOURCE_PAGE = "https://www.bls.gov/cpi/data.htm"
BASE = "1982-84=100"
STALE_AFTER_DAYS = 75     # released ~2 weeks after the reference month

META_FILES = ["cu.series", "cu.item", "cu.area"]

# The split data files. Each covers every year of its series; the US ones
# hold the U.S. city average (seasonally adjusted and not), the rest the
# areas. Metro and regional series also appear in some US files.
US_FILES = ["cu.data.1.AllItems", "cu.data.2.Summaries",
            "cu.data.11.USFoodBeverage", "cu.data.12.USHousing",
            "cu.data.13.USApparel", "cu.data.14.USTransportation",
            "cu.data.15.USMedical", "cu.data.16.USRecreation",
            "cu.data.17.USEducationAndCommunication",
            "cu.data.18.USOtherGoodsAndServices",
            "cu.data.20.USCommoditiesServicesSpecial"]
AREA_FILES = US_FILES + ["cu.data.3.AsizeNorthEast", "cu.data.4.AsizeNorthCentral",
                         "cu.data.5.AsizeSouth", "cu.data.6.AsizeWest",
                         "cu.data.7.OtherNorthEast", "cu.data.8.OtherNorthCentral",
                         "cu.data.9.OtherSouth", "cu.data.10.OtherWest",
                         "cu.data.19.PopulationSize"]

# The eight major expenditure groups of the CPI, in the BLS's own order.
GROUP_ITEMS = ["SAF", "SAH", "SAA", "SAT", "SAM", "SAR", "SAE", "SAG"]

CALC_YOY = "(index[t] / index[t−12 months] − 1) × 100, from published index values."
CALC_MOM = "(index[t] / index[t−1 month] − 1) × 100, from published index values."
CALC_ANN3M = "((index[t] / index[t−3 months]) ^ 4 − 1) × 100, from published index values."
CALC_NOTES = ("step: the 12-month move is decomposed into its 12 monthly log changes; raised when "
              "the largest single month is at least 70% of the summed absolute change and moved the "
              "index by at least 10%. low_base: raised when the latest index level is below 5.0 "
              "(base year = 100). Both are calculated from published index values.")

COMMON_NOTES = [
    "Series codes are the BLS series ids (e.g. CUUR0000SA0), so every figure "
    "can be checked on bls.gov under the same id.",
    "Index levels are exactly as published, to the BLS's three decimals. A "
    "rate computed from published indices can differ from the BLS's own "
    "published percent change by ±0.1 pp; nothing is adjusted to close it.",
    "Most indices are 1982-84=100; a series on any other reference period "
    "names it in its title. Rates of change do not depend on the base.",
    "No contribution-to-headline breakdown is computed: US weights (relative "
    "importance) are published for December only and move every month with "
    "relative prices, so a fixed-weight decomposition would not reconcile to "
    "headline. The December weights are served as cpi-us-weights.",
    "Semiannual series, alternate-base ('old base') series, purchasing power "
    "of the consumer dollar and the BLS annual averages (M13) are not carried.",
    "A missing value is missing, never zero.",
]


class ValidationError(Exception):
    pass


def fetch(data_files):
    files = {}
    for name in META_FILES + list(data_files):
        files[name] = bls_flat.fetch_file("cu", name)
    return bls_flat.bundle(files)


def _base_label(base_period):
    """'DECEMBER 2017=100' -> 'Dec 2017 = 100'; '1987=100' -> '1987 = 100'."""
    left, _, right = base_period.partition("=")
    words = left.split()
    if len(words) == 2 and words[1].isdigit():
        left = words[0][:3].title() + " " + words[1]
    return "%s = %s" % (left, right)


def carried(row):
    """Whether a cu.series row belongs to any US CPI dataset at all."""
    return (row["periodicity_code"] == "R"          # monthly (not semiannual)
            and row["base_code"] == "S"             # current base, not "old base"
            and row["item_code"] not in PURCHASING_POWER)


# Named, not matched by pattern: "ends in R" also catches Recreation (SAR)
# and Sugar and sweets (SEFR).
PURCHASING_POWER = ("SA0R", "AA0R")


def parse(raw_bytes, select, name_fn, sort_fn):
    """The bundle -> (series, observations) for the cu.series rows `select`
    accepts. `name_fn(item_name, area_name)` titles a series and
    `sort_fn(item_row, area_row)` orders it."""
    try:
        files = bls_flat.unbundle(raw_bytes)
    except Exception as exc:
        raise ValidationError("not a BLS bundle: %s" % exc)
    for name in META_FILES:
        if name not in files:
            raise ValidationError("bundle is missing %s" % name)
    items = dict((r["item_code"], r) for r in bls_flat.read_table(files["cu.item"]))
    areas = dict((r["area_code"], r) for r in bls_flat.read_table(files["cu.area"]))

    chosen = {}
    for row in bls_flat.read_table(files["cu.series"]):
        if not row.get("series_id") or not carried(row) or not select(row):
            continue
        item, area = items.get(row["item_code"]), areas.get(row["area_code"])
        if item is None or area is None:
            raise ValidationError("%s: item %r or area %r not in the code lists"
                                  % (row["series_id"], row["item_code"], row["area_code"]))
        chosen[row["series_id"]] = (row, item, area)

    values = {}
    for name in sorted(n for n in files if n.startswith("cu.data.")):
        bls_flat.read_values(files[name], chosen, name, ValidationError, into=values)

    series, observations = [], []
    for sid, (row, item, area) in sorted(
            chosen.items(), key=lambda kv: (sort_fn(kv[1][1], kv[1][2]), kv[0])):
        vals = values.get(sid)
        if not vals:
            continue            # a series listed but never published: nothing to carry
        name = name_fn(item["item_name"], area["area_name"])
        if row["base_period"] != BASE:
            name += " (%s)" % _base_label(row["base_period"])
        series.append({
            "code": sid,
            "name_en": name,
            "name_ja": None,
            "unit": "index",
            "weight_per_10000": None,   # see COMMON_NOTES: no fixed US weights
            "sort_order": len(series),
        })
        for period in sorted(vals):
            observations.append({"code": sid, "period": period, "value": vals[period]})
    return series, observations


def check(series, observations, min_series, min_observations, required,
          first_period, max_index=100000.0):
    if len(series) < min_series:
        raise ValidationError("only %d series parsed (expected ≥ %d)" % (len(series), min_series))
    if len(observations) < min_observations:
        raise ValidationError("only %d observations parsed (expected ≥ %d)"
                              % (len(observations), min_observations))
    codes = set(s["code"] for s in series)
    missing = [c for c in required if c not in codes]
    if missing:
        raise ValidationError("required series missing: %s" % ", ".join(missing))
    latest = None
    first = None
    per_series_latest = {}
    for o in observations:
        v = o["value"]
        # An index is positive. Levels far above 100 are real: televisions
        # (SERA01, 1982-84=100) stood at 15,573 in 1950 and near 1 today.
        # The ceiling only catches a parse fault (a year or an id read as a value).
        if not (0 < v < max_index):
            raise ValidationError("%s %s: index %r out of range" % (o["code"], o["period"], v))
        p = o["period"]
        latest = p if latest is None or p > latest else latest
        first = p if first is None or p < first else first
        if p > per_series_latest.get(o["code"], datetime.date.min):
            per_series_latest[o["code"]] = p
    if first > first_period:
        raise ValidationError("history starts %s, expected by %s" % (first, first_period))
    # Every required series must reach the newest month: a headline that
    # stopped short means a data file was served truncated.
    for c in required:
        if per_series_latest.get(c) != latest:
            raise ValidationError("%s ends %s but the release runs to %s"
                                  % (c, per_series_latest.get(c), latest))
    return latest


def manifest(dataset, source, presentation, name, summary, page, history_from,
             cite=None, notes=()):
    slug = dataset["slug"]
    return {
        "id": slug,
        "section": "prices",
        "name": name,
        "shape": "series",
        "summary": summary,
        "source": {
            "publisher": dataset["agency"],
            "publisher_ja": None,
            "document": source["name"],
            "url": source["url"],
            "credit": CREDIT,
            "license_note": source["license_note"],
        },
        "keys": ["series_code", "period"],
        "frequency": dataset["frequency"],
        "vintage": {
            "unit": "release", "as_of_basis": "release-in-force",
            "as_of_supported": True, "history_from": history_from,
            "stale_after_days": presentation["stale_after_days"],
        },
        "measures": [
            {"id": "index", "label": "Index level (1982-84 = 100 unless the series says otherwise)",
             "unit": "index", "trust": "official"},
            {"id": "yoy", "label": "Year over year", "unit": "%", "trust": "derived",
             "calc": CALC_YOY},
            {"id": "mom", "label": "Month over month", "unit": "%", "trust": "derived",
             "calc": CALC_MOM},
            {"id": "ann3m", "label": "3-month annualized", "unit": "%", "trust": "derived",
             "calc": CALC_ANN3M},
            {"id": "notes", "label": "Flags on the latest reading (step, low_base)",
             "unit": "category", "trust": "derived", "calc": CALC_NOTES},
        ],
        "endpoints": {
            "series": "/api/v1/%s/observations" % slug,
            "search": "/api/v1/%s/series" % slug,
            "summary": "/api/v1/%s/overview" % slug,
            "releases": "/api/v1/%s/releases" % slug,
            "revisions": "/api/v1/%s/revisions" % slug,
        },
        "capabilities": ["series", "search", "summary"],
        "cite": cite or page,
        "page": page,
        "notes": list(notes) + COMMON_NOTES,
    }
