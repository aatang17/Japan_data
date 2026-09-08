"""Adapter: agricultural price indices — MAFF 農業物価統計.

Source: 農林水産省, 農業物価統計調査 (e-Stat statsCode 00500204), the two
class-level price-index tables on the current base — 農産物 (1) 類別月別年次別
価格指数 and 農業生産資材 (1) 類別月別年次別価格指数, both 「ア　価格指数」.

What it is: the prices farmers *receive* for what they grow, and the prices
farmers *pay* for fertiliser, feed, agricultural chemicals, machinery, fuel and
hired services — on one index base, monthly, back to 1957. Holding the two
against each other is the farmer's terms of trade, which is the single number
that says whether Japanese farming is being squeezed, and the cleanest public
read-across to the listed fertiliser, feed and farm-machinery names.

**Two tables, one dataset.** Output and input are separate e-Stat tables with
separate classification axes, but they share the base year, the calendar and
the survey, so they belong on one grid. Series codes carry the side —
`out.*` for what is sold, `in.*` for what is bought — and nothing here ever
mixes the two into a single number: the ratio is a calculation, and on this
platform a calculation carries its formula rather than being stored.

**e-Stat republishes this table under a new id every year.** Pinning an id
would quietly freeze the dataset at whatever year it was written, so the
newest edition is discovered from the table list each run and the id is
recorded on the artifact.

Input prices run from April 1957 and output prices from April 1963; a class
introduced later starts later, and that is coverage, not a gap to fill.

**Timeliness is the honest weakness.** These are the 確報 confirmed annual
reports: the edition covering calendar year Y carries every month of Y and
lands well over a year later. As of the 令和6年 edition the newest month is
December 2024. The staleness gate is set to notice a *missing* edition, not
to pretend the data is fresh — the lag is disclosed rather than hidden.

**Only monthly rows are ingested.** The table's period axis mixes months
(「2024年8月」), calendar years (「2024年」) and fiscal years (「1951年度」) on one
list. The annual rows are averages of the monthly ones, so storing both would
put two different things on one series; only the months are kept.

Rate columns — 対前月騰落率 and 対前年同月騰落率 — are published in their own
tables and are deliberately not ingested. They are calculations, and
`/observations?measure=yoy` reaches the same number and shows its formula.

The class-level cut is what this dataset serves: 20 output classes and 17
input classes. e-Stat also publishes the same indices at item depth (134 and
173 series), which is a second dataset in the way `cpi-jp-items` is a second
dataset next to `cpi-jp` — not a change to this one.
"""
import datetime
import json
import re

from . import estat_api


class ValidationError(Exception):
    pass


STATS_CODE = "00500204"          # 農業物価統計調査

# The two tables this dataset is built from, identified by what their title
# says rather than by an id that changes every year. The base-year wording
# ("令和２年基準") is deliberately not part of the match, so a rebasing is
# picked up rather than breaking discovery.
TABLES = [
    ("out", "農産物", "農産物", "Farm output prices"),
    ("in", "input", "農業生産資材", "Farm input prices"),
]
_TITLE = re.compile(r"類別月別年次別価格指数.*ア[\s　]*価格指数")

# Period labels on the one axis: a month, a calendar year, a fiscal year.
# Only months are ingested — see the module docstring.
_MONTH = re.compile(r"^(\d{4})年(\d{1,2})月$")
_YEAR = re.compile(r"^(\d{4})年$")
_FISCAL = re.compile(r"^(\d{4})年度$")

# e-Stat class names are the full path with underscores, e.g.
# 農産物総合_野菜_果菜_総合. The trailing 総合 is "all of this class".
CLASSES = {
    # --- what farmers sell -------------------------------------------------
    "農産物総合": ("out.total", "Farm output prices — all items"),
    "農産物総合_米_総合": ("out.rice", "Rice"),
    "農産物総合_麦_総合": ("out.wheat-barley", "Wheat and barley"),
    "農産物総合_雑穀_総合": ("out.other-cereals", "Miscellaneous cereals"),
    "農産物総合_豆_総合": ("out.pulses", "Beans and pulses"),
    "農産物総合_いも_総合": ("out.potatoes", "Potatoes and sweet potatoes"),
    "農産物総合_野菜_総合": ("out.vegetables", "Vegetables"),
    "農産物総合_野菜_果菜_総合": ("out.vegetables.fruit",
                                  "Vegetables — fruit vegetables"),
    "農産物総合_野菜_葉茎菜_総合": ("out.vegetables.leaf",
                                    "Vegetables — leaf and stem vegetables"),
    "農産物総合_野菜_根菜_総合": ("out.vegetables.root",
                                  "Vegetables — root vegetables"),
    "農産物総合_野菜_まめ科野菜_総合": ("out.vegetables.legume",
                                        "Vegetables — legume vegetables"),
    "農産物総合_果実_総合": ("out.fruit", "Fruit"),
    "農産物総合_工芸農作物_総合": ("out.industrial-crops", "Industrial crops"),
    "農産物総合_花き_総合": ("out.flowers", "Flowers and ornamental plants"),
    "農産物総合_畜産物_総合": ("out.livestock", "Livestock products"),
    "農産物総合_畜産物_鶏卵_Ｍ、１級": ("out.livestock.eggs",
                                        "Livestock — hen eggs (size M, grade 1)"),
    "農産物総合_畜産物_生乳_総合乳価": ("out.livestock.raw-milk",
                                        "Livestock — raw milk (all-use price)"),
    "農産物総合_畜産物_肉畜_総合": ("out.livestock.meat-animals",
                                    "Livestock — animals for meat"),
    "農産物総合_畜産物_子畜_総合": ("out.livestock.young-animals",
                                    "Livestock — young animals"),
    "農産物総合_畜産物_成畜_総合": ("out.livestock.mature-animals",
                                    "Livestock — mature animals"),
    # --- what farmers buy --------------------------------------------------
    "農業生産資材総合": ("in.total", "Farm input prices — all items"),
    "農業生産資材総合_種苗及び苗木_総合": ("in.seeds", "Seeds and seedlings"),
    "農業生産資材総合_畜産用動物_総合": ("in.livestock-animals",
                                        "Animals bought for livestock farming"),
    "農業生産資材総合_肥料_総合": ("in.fertiliser", "Fertiliser"),
    "農業生産資材総合_肥料_無機質_総合": ("in.fertiliser.inorganic",
                                          "Fertiliser — inorganic"),
    "農業生産資材総合_肥料_有機質_総合": ("in.fertiliser.organic",
                                          "Fertiliser — organic"),
    "農業生産資材総合_飼料_総合": ("in.feed", "Feed"),
    "農業生産資材総合_農業薬剤_総合": ("in.agrichemicals", "Agricultural chemicals"),
    "農業生産資材総合_諸材料_総合": ("in.materials", "Sundry materials"),
    "農業生産資材総合_光熱動力_総合": ("in.fuel-power", "Fuel and power"),
    "農業生産資材総合_農機具_総合": ("in.machinery", "Machinery and implements"),
    "農業生産資材総合_農機具_小農具_総合": ("in.machinery.small",
                                            "Machinery — small implements"),
    "農業生産資材総合_農機具_大農具_総合": ("in.machinery.large",
                                            "Machinery — large machinery"),
    "農業生産資材総合_自動車・同関係料金_総合": ("in.vehicles",
                                                "Motor vehicles and related charges"),
    "農業生産資材総合_建築資材_総合": ("in.building-materials", "Building materials"),
    "農業生産資材総合_農用被服_総合": ("in.clothing", "Farm clothing"),
    "農業生産資材総合_賃借料及び料金_総合": ("in.rents-services",
                                            "Rents and service charges"),
}
ORDER = dict((name, i) for i, name in enumerate(CLASSES))

DATASET = {
    "slug": "agri-prices",
    "title": "Agricultural Price Indices — Output and Inputs (Japan)",
    "country": "Japan",
    "agency": "Ministry of Agriculture, Forestry and Fisheries",
    "agency_ja": "農林水産省",
    "base": "2020=100",
    "frequency": "monthly",
    "description": (
        "Monthly price indices for what Japanese farmers sell and what they "
        "buy, on the 2020 base — 20 classes of farm output "
        "from rice to raw milk, and 17 classes of farm input from fertiliser "
        "and feed to machinery, fuel and hired services. The confirmed annual "
        "report is published with a long lag, so the newest month is normally "
        "more than a year old. Input prices run from April 1957 and output "
        "prices from April 1963."
    ),
}

SOURCE = {
    "source_id": "estat:00500204-classes",
    "name": "MAFF — Agricultural Price Statistics, class-level price indices",
    "name_ja": "農林水産省 農業物価統計調査 類別価格指数",
    "url": "https://www.maff.go.jp/j/tokei/kouhyou/noubukka/",
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Agriculture, "
        "Forestry and Fisheries. Retrieved through the e-Stat API."
    ),
}

DOWNLOAD_URL = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData (00500204)"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": ("Source: Ministry of Agriculture, Forestry and Fisheries — "
                    "Agricultural Price Statistics (農業物価統計)."),
    # Calibrated to the survey's own record: e-Stat opened the calendar-2024
    # edition on 2026-03-31, so December of year Y is published about fifteen
    # months later and is up to ~850 days old the day before the next edition
    # lands. This allows that plus a little, so the flag means an edition is
    # genuinely missing — the routine lag is disclosed on the page and in the
    # manifest instead of being flagged every year.
    "stale_after_days": 900,
    "main_series": [
        {"role": "output", "code": "out.total",
         "label": "Farm output prices", "slot": 1},
        {"role": "input", "code": "in.total",
         "label": "Farm input prices", "slot": 2},
        {"role": "rice", "code": "out.rice", "label": "Rice", "slot": 3},
    ],
    # What farmers are paid, what they pay, and the two inputs that move most.
    # These are index levels, not flows.
    "overview_tiles": [
        {"key": "output", "type": "level", "code": "out.total", "label": "Output Prices"},
        {"key": "input", "type": "level", "code": "in.total", "label": "Input Prices"},
        {"key": "fertiliser", "type": "level", "code": "in.fertiliser",
         "label": "Fertiliser"},
        {"key": "feed", "type": "level", "code": "in.feed", "label": "Feed"},
    ],
    "kinds": dict((code, "level") for code, _label in CLASSES.values()),
}


# --- fetching ---------------------------------------------------------------

def _table_list():
    """Every table in the survey, with the count checked against the API's own.

    A silently truncated list looks exactly like "the table no longer exists",
    which would freeze the dataset at its last release without anything saying
    so, so the two counts must agree.
    """
    payload = estat_api.call("getStatsList", statsCode=STATS_CODE, limit=10000)
    listing = payload["GET_STATS_LIST"]["DATALIST_INF"]
    tables = listing.get("TABLE_INF", [])
    tables = [tables] if isinstance(tables, dict) else tables
    reported = listing.get("NUMBER")
    if reported is not None and int(reported) != len(tables):
        raise ValidationError(
            "the table list is truncated: the API reports %s tables under "
            "statsCode %s and returned %d" % (reported, STATS_CODE, len(tables)))
    return tables


def _title_of(table):
    title = table.get("TITLE")
    return title.get("$") if isinstance(title, dict) else (title or "")


def newest_tables(tables):
    """{side: (statsDataId, survey date, title)} for the newest edition.

    Both tables share one title shape and differ only by which side of the
    farm gate they describe, so the side is read from the title too.
    """
    best = {}
    for table in tables:
        title = _title_of(table)
        if not _TITLE.search(title):
            continue
        for side, _key, marker, _label in TABLES:
            if not title.startswith("農業物価統計") or marker not in title:
                continue
            # 農産物 is a substring of nothing else here, but 農業生産資材
            # contains neither, so the longer marker must win.
            if marker == "農産物" and "農業生産資材" in title:
                continue
            survey = str(table.get("SURVEY_DATE"))
            if side not in best or survey > best[side][1]:
                best[side] = (table["@id"], survey, title)
    missing = [side for side, _k, _m, _l in TABLES if side not in best]
    if missing:
        raise ValidationError(
            "no class-level price-index table found for %s under statsCode %s"
            % (", ".join(missing), STATS_CODE))
    return best


def fetch():
    """Both tables, every page of each, exactly as the API returned them."""
    chosen = newest_tables(_table_list())
    payload = {"tables": {}}
    for side, (stats_data_id, survey, title) in sorted(chosen.items()):
        payload["tables"][side] = {
            "statsDataId": stats_data_id,
            "survey_date": survey,
            "title": title,
            "pages": estat_api.get_stats_data(stats_data_id),
        }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def canonical_bytes(raw):
    """The artifact with every served-at timestamp removed.

    Each e-Stat response carries the time it was served, so two identical
    downloads never match byte for byte and the runner would publish a new
    release every month whether or not a figure moved.
    """
    return json.dumps(estat_api.strip_timestamps(json.loads(raw.decode("utf-8"))),
                      ensure_ascii=False, sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _period(label):
    """A monthly period, or None for the annual and fiscal-year rows."""
    month = _MONTH.match(label)
    if month:
        return datetime.date(int(month.group(1)), int(month.group(2)), 1)
    if _YEAR.match(label) or _FISCAL.match(label):
        return None
    raise ValidationError("unrecognised period label %r" % label)


def _value(text):
    text = (text or "").strip().replace(",", "")
    if text in ("", "-", "－", "…", "***", "x", "X", "†"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse(raw):
    payload = json.loads(raw.decode("utf-8"))["tables"]
    meta, values = {}, {}

    for side in sorted(payload):
        pages = payload[side]["pages"]
        for page in pages:
            data = page["GET_STATS_DATA"]["STATISTICAL_DATA"]
            periods = dict(
                (code, _period(name))
                for code, name in estat_api.class_values(data, "cat01").items())
            classes = estat_api.class_values(data, "cat02")
            entries = data["DATA_INF"]["VALUE"]
            entries = [entries] if isinstance(entries, dict) else entries
            for entry in entries:
                period = periods.get(entry["@cat01"])
                if period is None:
                    continue                        # annual / fiscal-year row
                name = classes.get(entry["@cat02"])
                if name not in CLASSES:
                    raise ValidationError(
                        "unknown %s class %r — the classification changed; add "
                        "it to CLASSES in maff_agri_prices.py" % (side, name))
                code, name_en = CLASSES[name]
                value = _value(entry.get("$"))
                if value is None:
                    continue
                meta.setdefault(code, {
                    "code": code, "name_en": name_en, "name_ja": name,
                    "unit": "index", "weight_per_10000": None,
                    "sort_order": ORDER[name],
                })
                previous = values.setdefault(code, {}).get(period)
                if previous is not None and previous != value:
                    raise ValidationError(
                        "%s %s is published twice with different values (%s, %s)"
                        % (code, period, previous, value))
                values[code][period] = value

    series = sorted(meta.values(), key=lambda s: s["sort_order"])
    observations = [{"code": code, "period": period, "value": value}
                    for code in sorted(values)
                    for period, value in sorted(values[code].items())]
    return series, observations


# --- validation -------------------------------------------------------------

INDEX_FLOOR, INDEX_CEILING = 1.0, 1_000.0
# The two sides of the farm gate were not surveyed from the same date: input
# prices run from April 1957, output prices only from April 1963. Each
# headline is held to its own published start, so a truncated download is
# caught without pretending the two histories are the same length.
FIRST_PERIOD = {"in.total": datetime.date(1957, 4, 1),
                "out.total": datetime.date(1963, 4, 1)}
MIN_SERIES = 30


def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")

    codes = set(s["code"] for s in series)
    for required in ("out.total", "in.total"):
        if required not in codes:
            raise ValidationError("the %r headline index is missing" % required)
    if len(codes) < MIN_SERIES:
        raise ValidationError(
            "only %d series; expected at least %d classes" % (len(codes), MIN_SERIES))

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        if not (INDEX_FLOOR <= o["value"] <= INDEX_CEILING):
            raise ValidationError(
                "%s %s: index %s is outside the %s-%s band"
                % (o["code"], o["period"], o["value"], INDEX_FLOOR, INDEX_CEILING))
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    for headline in ("out.total", "in.total"):
        points = by_code[headline]
        first = min(points)
        if first != FIRST_PERIOD[headline]:
            raise ValidationError(
                "%s starts %s; the published table starts %s"
                % (headline, first, FIRST_PERIOD[headline]))
        # Consecutive months on the headline. A class can be introduced or
        # retired mid-history; the two headlines never can.
        months = sorted(points)
        for previous, current in zip(months, months[1:]):
            step = ((current.year - previous.year) * 12
                    + current.month - previous.month)
            if step != 1:
                raise ValidationError(
                    "%s has no data between %s and %s" % (headline, previous, current))

    # The base year must actually be the base: the twelve months of the base
    # year average to 100 on every index. This is what catches a silent
    # rebasing, which would otherwise splice two incompatible series together.
    base_year = int((DATASET["base"] or "2020=100").split("=")[0])
    for headline in ("out.total", "in.total"):
        base = [v for p, v in by_code[headline].items() if p.year == base_year]
        if len(base) != 12:
            raise ValidationError(
                "%s has %d months in the base year %d, not 12"
                % (headline, len(base), base_year))
        mean = sum(base) / 12.0
        if abs(mean - 100.0) > 0.5:
            raise ValidationError(
                "%s averages %.2f across %d, not 100 — the table has been "
                "rebased and DATASET['base'] is now wrong"
                % (headline, mean, base_year))

    latest = max(o["period"] for o in observations)
    return {
        "series": len(codes),
        "observations": len(observations),
        "first_period": min(o["period"] for o in observations).isoformat(),
        "latest_period": latest.isoformat(),
        "latest_output_index": by_code["out.total"].get(latest),
        "latest_input_index": by_code["in.total"].get(latest),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "agriculture",
    "name": {"en": "Agricultural price indices — output and inputs",
             "ja": "農業物価指数（類別）"},
    "shape": "series",
    "summary": DATASET["description"],
    "source": {
        "publisher": DATASET["agency"],
        "publisher_ja": DATASET["agency_ja"],
        "document": SOURCE["name"],
        "url": SOURCE["url"],
        "credit": PRESENTATION["credit_line"],
        "license_note": SOURCE["license_note"],
    },
    "keys": ["series_code", "period"],
    "frequency": DATASET["frequency"],
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "1957-04",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Price index (2020 = 100)", "unit": "index",
         "trust": "official"},
        {"id": "yoy", "label": "Change on a year earlier", "unit": "%",
         "trust": "derived",
         "calc": ("(index[t] / index[t−12 months] − 1) × 100, from published "
                  "index values.")},
        {"id": "mom", "label": "Change on the previous month", "unit": "%",
         "trust": "derived",
         "calc": ("(index[t] / index[t−1 month] − 1) × 100, from published "
                  "index values.")},
        {"id": "ann3m", "label": "3-month change, annualised", "unit": "%",
         "trust": "derived",
         "calc": ("((index[t] / index[t−3 months]) ^ 4 − 1) × 100, from "
                  "published index values.")},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series"],
    "cite": "/rice.html?dataset=agri-prices",
    "page": "/rice.html",
    "notes": [
        "The confirmed report is annual and lands more than a year after the "
        "year it covers, so the newest month here is normally 12-20 months old. "
        "It is the deepest public history of Japanese farm-gate and farm-input "
        "prices, not a timely indicator.",
        "The two sides start on different dates: input prices from April 1957, "
        "output prices from April 1963. Individual classes start later still "
        "when they were introduced — miscellaneous cereals only from 2005.",
        "Output and input indices share a base year and a calendar but are "
        "separate published tables. The farmer's terms of trade is the ratio of "
        "the two; it is a calculation, so it is computed where it is shown and "
        "carries its formula, never stored as a published value.",
        "The period axis mixes months, calendar years and fiscal years. Only the "
        "monthly rows are stored — the annual rows are averages of them, and "
        "putting both on one series would mix two different things.",
        "MAFF also publishes the month-on-month and year-on-year rate tables. "
        "They are not ingested: request measure=mom or measure=yoy, which "
        "computes the same change from these index levels and shows the formula.",
        "The same indices exist at item depth — 134 output items and 173 input "
        "items. That is a separate dataset, in the way cpi-jp-items sits beside "
        "cpi-jp, and is not served here.",
    ],
}
