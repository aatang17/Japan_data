"""Adapter: rice production cost — MAFF 農業経営統計調査 米生産費.

Source: 農林水産省, 農業経営統計調査 農産物生産費 (e-Stat), the two 米生産費
累年 tables — the national long run (昭和26年産 onward) and the comparison by
planted-area band (昭和35年産 onward).

What it is for: it turns "is the farm-gate price below the cost of growing it?"
from an assertion into a number. The survey costs a crop of rice the way an
accountant would — seed, fertiliser, chemicals, fuel, machinery depreciation,
hired and family labour, then imputed interest on the farmer's own capital and
imputed rent on land the farmer owns — and states the result both per 10 ares
and per 60kg, the same 60kg bag `rice-prices-jp` is quoted in. The two datasets
are meant to be read against each other.

**Three cost levels, and the difference between them is the whole point.**
費用合計 is what was spent. 生産費（副産物価額差引） nets off the straw and
other by-products. 全算入生産費 adds imputed interest on own capital and
imputed rent on own land — costs a family farm does not write a cheque for but
which are real. A price can sit above the first and below the third, and which
one is quoted is usually where an argument about farm policy is actually being
had. All three are stored, none is preferred.

**Planted-area bands are the second cut**, because the national average hides
the thing that matters: a 30-are grower and a 500-are grower do not have the
same cost per bag. The bands are as MAFF published them — the boundaries have
not moved, but the smallest bands are dropped from later years as the sample
thins, and a band that was not published is missing, never zero.

**Annual, and slow.** A crop year 令和5年産 is the 2023 harvest, dated here to
1 January 2023 so it sorts and joins with everything else on the platform. The
confirmed report lands about eighteen months after the harvest, so the newest
crop year is normally two years back — this is structural depth, not a
timely indicator.

**e-Stat republishes both tables under a new id every year**, so the ids are
discovered from the table list rather than pinned; a pinned id would silently
freeze the dataset at the year this file was written.

Costs are yen, quantities are kilograms and labour is hours. They are never
mixed: each series carries its own unit and the API refuses to rank across them.
"""
import datetime
import json
import re

from . import estat_api


class ValidationError(Exception):
    pass


STATS_CODE = "00500201"          # 農業経営統計調査

# The two tables, matched on what their titles say. The edition year is in the
# title too ("昭和26年産～令和５年産"), which is exactly why the match must not
# depend on it.
NATIONAL_TITLE = re.compile(r"米生産費・累年.*全国累年統計.*10a当たり生産費")
BANDS_TITLE = re.compile(r"米生産費・累年.*全国作付規模別・年次別比較")

_ERA = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}
_FULLWIDTH = dict(zip("０１２３４５６７８９", "0123456789"))
_CROP_YEAR = re.compile(r"^(明治|大正|昭和|平成|令和)\s*(元|[0-9０-９]+)\s*年産$")

# Name components, as e-Stat writes them in an underscore-joined path. One map
# builds both the series code and the English name for either table: a path is
# translated component by component, so a component that turns up in a new
# combination is handled, and one that has never been seen stops the ingest
# rather than being guessed at.
COMPONENTS = {
    # cost blocks
    "物財費": ("materials", "materials and other non-labour costs"),
    "種苗費": ("seed", "seed"),
    "肥料費": ("fertiliser", "fertiliser"),
    "農業薬剤費": ("agrichemicals", "agricultural chemicals"),
    "光熱動力費": ("fuel-power", "fuel and power"),
    "その他の諸材料費": ("other-materials", "other materials"),
    "土地改良及び水利費": ("land-water", "land improvement and irrigation"),
    "賃借料及び料金": ("rents-services", "rent and service charges"),
    "物件税及び公課諸負担": ("property-tax", "property tax and public levies"),
    "建物費": ("buildings", "buildings"),
    "自動車費": ("vehicles", "motor vehicles"),
    "農機具費": ("machinery", "farm machinery"),
    "生産管理費": ("management", "farm management"),
    "生産管理": ("management", "farm management"),
    "畜力費": ("draught-animals", "draught animals"),
    "その他の物財費": ("other-non-labour", "other non-labour costs"),
    "労働費": ("labour", "labour cost"),
    # qualifiers
    "家族": ("family", "family"),
    "雇用": ("hired", "hired"),
    "購入": ("purchased", "purchased"),
    "購入（支払）": ("purchased", "purchased or paid"),
    "自給": ("home-produced", "home-produced"),
    "償却": ("depreciation", "depreciation"),
    "償却費": ("depreciation", "depreciation"),
    "修繕費": ("repairs", "repairs"),
    "修繕費及び購入補充費": ("repairs", "repairs and replacement"),
    "計": ("total", "total"),
    "主産物": ("main-product", "main product"),
    "副産物": ("by-products", "by-products"),
    # totals and the three cost levels
    "費用合計": ("total-cost", "total cost"),
    "副産物価額": ("by-product-value", "value of by-products"),
    "生産費(副産物価額差引)": ("cost-net", "production cost, net of by-products"),
    "支払利子": ("interest-paid", "interest paid"),
    "支払地代": ("rent-paid", "rent paid"),
    "支払利子・地代算入生産費": ("cost-with-paid",
                                "production cost including interest and rent paid"),
    "支払利子･地代算入生産費": ("cost-with-paid",
                                "production cost including interest and rent paid"),
    "自己資本利子": ("own-capital-interest", "imputed interest on own capital"),
    "自作地地代": ("own-land-rent", "imputed rent on own land"),
    "資本利子･地代全額算入生産費（全算入生産費）":
        ("cost-full", "full production cost, interest and land rent imputed"),
    "資本利子・地代全額算入生産費":
        ("cost-full", "full production cost, interest and land rent imputed"),
    # the per-60kg block, and the revenue and labour measures
    "60kg当たり": ("per60kg", "per 60kg"),
    "主産物数量": ("main-product-quantity", "main product harvested"),
    "粗収益": ("gross-revenue", "gross revenue"),
    "投下労働時間": ("labour-hours", "labour hours"),
    "畜力使役時間": ("draught-animal-hours", "draught animal hours"),
    "動力運転時間": ("machine-hours", "machine operating hours"),
    "10ａ当たり所得": ("income-per-10a", "income per 10 ares"),
    "１日当たり所得": ("income-per-day", "income per day of labour"),
    "１日当たり家族労働報酬": ("family-earnings-per-day",
                              "family labour earnings per day"),
}

# Planted-area bands. The boundaries were redrawn more than once — the early
# surveys split the smallest farms at 30 ares, later ones at 50 — so a band is
# only comparable with itself, and each published band is its own series
# rather than being forced onto a single ladder. The unsuffixed entry is every
# farm in the survey, not a band. Order is by lower bound, then by width.
BANDS = [
    ("", "all", "all farms"),
    ("30ａ未満", "u30a", "under 30 ares"),
    ("30～50", "30-50a", "30 to 50 ares"),
    ("50ａ未満", "u50a", "under 50 ares"),
    ("50～100", "50-100a", "50 to 100 ares"),
    ("100～150", "100-150a", "100 to 150 ares"),
    ("100～200", "100-200a", "100 to 200 ares"),
    ("100～300", "100-300a", "100 to 300 ares"),
    ("150～200", "150-200a", "150 to 200 ares"),
    ("200～250", "200-250a", "200 to 250 ares"),
    ("200～300", "200-300a", "200 to 300 ares"),
    ("250～300", "250-300a", "250 to 300 ares"),
    ("300ａ以上", "300a-plus", "300 ares and over"),
    ("うち500ａ以上", "500a-plus", "of which 500 ares and over"),
]
BAND_BY_JA = dict((ja, (slug, label)) for ja, slug, label in BANDS)
BAND_ORDER = dict((slug, i) for i, (_ja, slug, _l) in enumerate(BANDS))

# e-Stat's unit strings for these tables -> the platform's unit keys.
UNITS = {"円": "jpy", "kg": "kg", "時間": "hours", "": "jpy"}

DATASET = {
    "slug": "rice-production-cost",
    "title": "Rice Production Cost — Japan",
    "country": "Japan",
    "agency": "Ministry of Agriculture, Forestry and Fisheries",
    "agency_ja": "農林水産省",
    "base": None,
    "frequency": "annual",
    "description": (
        "What it costs to grow a crop of rice in Japan, by crop year — every "
        "cost line from seed and fertiliser to machinery depreciation and "
        "family labour, and the three published cost levels: total spend, "
        "cost net of by-products, and full cost with interest on own capital "
        "and rent on own land imputed. Stated per 10 ares and per 60kg, "
        "nationally from the 1951 crop and by planted-area band from 1960."
    ),
}

SOURCE = {
    "source_id": "estat:00500201-rice-cost",
    "name": "MAFF — Farm Management Statistics, rice production cost (long run)",
    "name_ja": "農林水産省 農業経営統計調査 農産物生産費 米生産費・累年",
    "url": "https://www.maff.go.jp/j/tokei/kouhyou/noukei/seisanhi_nousan/",
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Agriculture, "
        "Forestry and Fisheries. Retrieved through the e-Stat API."
    ),
}

DOWNLOAD_URL = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData (00500201)"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": ("Source: Ministry of Agriculture, Forestry and Fisheries — "
                    "Farm Management Statistics, rice production cost."),
    # Calibrated to the survey's own record: e-Stat opened the 2022-crop
    # edition on 2025-02-28 and the 2023-crop edition on 2026-03-31, so a crop
    # year is published about three years after the January it is dated to.
    # The newest period is ~1,185 days old the day it lands and up to ~1,550
    # days old the day before the next edition; this allows that plus two
    # months, so the flag means an edition is genuinely missing.
    "stale_after_days": 1_610,
    "main_series": [
        {"code": "nat.per60kg.cost-full",
         "name_en": "Full production cost per 60kg"},
    ],
}


# --- fetching ---------------------------------------------------------------

def _title_of(table):
    title = table.get("TITLE")
    return title.get("$") if isinstance(title, dict) else (title or "")


def newest_tables(tables):
    """{'national'|'bands': (id, survey date, title)} for the newest edition."""
    best = {}
    for table in tables:
        title = re.sub(r"\s+", "", _title_of(table))
        for key, pattern in (("national", NATIONAL_TITLE), ("bands", BANDS_TITLE)):
            if not pattern.search(title):
                continue
            survey = str(table.get("SURVEY_DATE"))
            if key not in best or survey > best[key][1]:
                best[key] = (table["@id"], survey, _title_of(table))
    missing = [k for k in ("national", "bands") if k not in best]
    if missing:
        raise ValidationError(
            "no 米生産費・累年 table found for %s under statsCode %s"
            % (", ".join(missing), STATS_CODE))
    return best


# 農業経営統計調査 carries about 25,000 tables, far past what one list call
# returns, so the list is narrowed by search term. The count is checked against
# the total the API reports: a silently truncated list would look exactly like
# "the table no longer exists" and would freeze the dataset at its last release.
SEARCH_WORD = "米生産費"


def table_list():
    payload = estat_api.call("getStatsList", statsCode=STATS_CODE,
                             searchWord=SEARCH_WORD, limit=10000)
    listing = payload["GET_STATS_LIST"]["DATALIST_INF"]
    tables = listing.get("TABLE_INF", [])
    tables = [tables] if isinstance(tables, dict) else tables
    reported = listing.get("NUMBER")
    if reported is not None and int(reported) != len(tables):
        raise ValidationError(
            "the table list is truncated: the API reports %s tables for %r and "
            "returned %d" % (reported, SEARCH_WORD, len(tables)))
    return tables


def fetch():
    chosen = newest_tables(table_list())
    out = {"tables": {}}
    for key, (stats_data_id, survey, title) in sorted(chosen.items()):
        out["tables"][key] = {
            "statsDataId": stats_data_id, "survey_date": survey, "title": title,
            "pages": estat_api.get_stats_data(stats_data_id),
        }
    return json.dumps(out, ensure_ascii=False, sort_keys=True).encode("utf-8")


def canonical_bytes(raw):
    """The artifact without e-Stat's served-at timestamps — see estat_api."""
    return json.dumps(estat_api.strip_timestamps(json.loads(raw.decode("utf-8"))),
                      ensure_ascii=False, sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _crop_year(label):
    """「令和5年産」 -> 2023. The crop year is dated to its 1 January."""
    match = _CROP_YEAR.match(re.sub(r"\s+", "", label))
    if not match:
        return None
    digits = "".join(_FULLWIDTH.get(c, c) for c in match.group(2))
    number = 1 if digits == "元" else int(digits)
    return _ERA[match.group(1)] + number


def translate(path, prefix, order):
    """An underscore-joined e-Stat name -> (series code, English name)."""
    parts = [p for p in path.split("_") if p]
    slugs, labels = [], []
    for part in parts:
        if part not in COMPONENTS:
            raise ValidationError(
                "unknown cost component %r in %r — the classification changed; "
                "add it to COMPONENTS in maff_rice_cost.py" % (part, path))
        slug, label = COMPONENTS[part]
        slugs.append(slug)
        labels.append(label)
    name = labels[0][0].upper() + labels[0][1:]
    if len(labels) > 1:
        name += " — " + ", ".join(labels[1:])
    return "%s.%s" % (prefix, ".".join(slugs)), name, order


def _value(text):
    text = (text or "").strip().replace(",", "")
    if text in ("", "-", "－", "…", "***", "x", "X", "nan"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _units_for(data, axis):
    """{class code: unit string} for one axis of a getStatsData response."""
    for obj in data["CLASS_INF"]["CLASS_OBJ"]:
        if obj["@id"] != axis:
            continue
        entries = obj["CLASS"]
        entries = [entries] if isinstance(entries, dict) else entries
        return dict((e["@code"], e.get("@unit", "")) for e in entries)
    return {}


def _split_band(label):
    """「令和５年産_うち500ａ以上」 -> (2023, band slug, band label)."""
    text = re.sub(r"\s+", "", label)
    band_ja = ""
    if "_" in text:
        text, band_ja = text.split("_", 1)
    year = _crop_year(text)
    if year is None:
        return None, None, None
    if band_ja not in BAND_BY_JA:
        raise ValidationError(
            "unknown planted-area band %r; add it to BANDS in maff_rice_cost.py"
            % band_ja)
    slug, band_label = BAND_BY_JA[band_ja]
    return year, slug, band_label


def parse(raw):
    tables = json.loads(raw.decode("utf-8"))["tables"]
    meta, values = {}, {}

    def record(code, name_en, name_ja, unit, sort_order, year, value):
        period = datetime.date(year, 1, 1)
        meta.setdefault(code, {
            "code": code, "name_en": name_en, "name_ja": name_ja,
            "unit": unit, "weight_per_10000": None, "sort_order": sort_order,
        })
        previous = values.setdefault(code, {}).get(period)
        if previous is not None and previous != value:
            raise ValidationError(
                "%s %s is published twice with different values (%s, %s)"
                % (code, year, previous, value))
        values[code][period] = value

    # --- national long run: items down cat01, crop years across cat02 -------
    for page in tables["national"]["pages"]:
        data = page["GET_STATS_DATA"]["STATISTICAL_DATA"]
        items = estat_api.class_values(data, "cat01")
        item_units = _units_for(data, "cat01")
        years = dict((code, _crop_year(name))
                     for code, name in estat_api.class_values(data, "cat02").items())
        item_order = dict((code, i) for i, code in enumerate(items))
        entries = data["DATA_INF"]["VALUE"]
        entries = [entries] if isinstance(entries, dict) else entries
        for entry in entries:
            year = years.get(entry["@cat02"])
            value = _value(entry.get("$"))
            if year is None or value is None:
                continue
            path = items[entry["@cat01"]]
            code, name_en, _o = translate(path, "nat", 0)
            record(code, name_en, path,
                   UNITS.get(item_units.get(entry["@cat01"], ""), "jpy"),
                   item_order[entry["@cat01"]], year, value)

    # --- by planted-area band: crop year and band share cat01 --------------
    for page in tables["bands"]["pages"]:
        data = page["GET_STATS_DATA"]["STATISTICAL_DATA"]
        rows = estat_api.class_values(data, "cat01")
        items = estat_api.class_values(data, "cat02")
        item_units = _units_for(data, "cat02")
        item_order = dict((code, i) for i, code in enumerate(items))
        entries = data["DATA_INF"]["VALUE"]
        entries = [entries] if isinstance(entries, dict) else entries
        for entry in entries:
            year, band, band_label = _split_band(rows[entry["@cat01"]])
            value = _value(entry.get("$"))
            if year is None or value is None:
                continue
            path = items[entry["@cat02"]]
            code, name_en, _o = translate(path, "band.%s" % band, 0)
            record(code, "%s (%s)" % (name_en, band_label), path,
                   UNITS.get(item_units.get(entry["@cat02"], ""), "jpy"),
                   1_000 + BAND_ORDER[band] * 100 + item_order[entry["@cat02"]],
                   year, value)

    series = sorted(meta.values(), key=lambda s: (s["sort_order"], s["code"]))
    observations = [{"code": code, "period": period, "value": value}
                    for code in sorted(values)
                    for period, value in sorted(values[code].items())]
    return series, observations


# --- validation -------------------------------------------------------------

FIRST_CROP_YEAR = 1951
MIN_SERIES = 150
# Nothing in this survey is negative except income and family earnings, which
# genuinely go below zero when the price falls under cost.
MAY_BE_NEGATIVE = ("income-per-10a", "income-per-day", "family-earnings-per-day")


def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")

    codes = set(s["code"] for s in series)
    required = ("nat.total-cost", "nat.cost-net", "nat.cost-full",
                "nat.per60kg.total-cost", "nat.per60kg.cost-full")
    for code in required:
        if code not in codes:
            raise ValidationError("the %r series is missing" % code)
    if len(codes) < MIN_SERIES:
        raise ValidationError(
            "only %d series; expected at least %d" % (len(codes), MIN_SERIES))

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        if o["value"] < 0 and not any(m in o["code"] for m in MAY_BE_NEGATIVE):
            raise ValidationError(
                "%s %s: a cost of %s cannot be negative"
                % (o["code"], o["period"], o["value"]))
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    national = by_code["nat.cost-full"]
    first, latest = min(national), max(national)
    if first.year > FIRST_CROP_YEAR:
        raise ValidationError(
            "the national series starts with the %d crop; the published table "
            "reaches back to %d" % (first.year, FIRST_CROP_YEAR))

    # The three cost levels must nest: total spend, then net of by-products
    # (lower, because the by-product value is deducted), then full cost with
    # imputed interest and rent added back (higher than the level before it).
    for period in sorted(national):
        total = by_code["nat.total-cost"].get(period)
        net = by_code["nat.cost-net"].get(period)
        full = by_code["nat.cost-full"].get(period)
        with_paid = by_code.get("nat.cost-with-paid", {}).get(period)
        if None in (total, net, full):
            continue
        if net > total:
            raise ValidationError(
                "%s: cost net of by-products (%s) exceeds total cost (%s)"
                % (period.year, net, total))
        if with_paid is not None and not (net <= with_paid <= full):
            raise ValidationError(
                "%s: the three cost levels do not nest — net %s, with interest "
                "and rent paid %s, full %s" % (period.year, net, with_paid, full))
        if full < net:
            raise ValidationError(
                "%s: full production cost (%s) is below cost net of "
                "by-products (%s)" % (period.year, full, net))

    per_60kg = by_code["nat.per60kg.cost-full"]
    newest_60kg = per_60kg.get(latest)
    return {
        "series": len(codes),
        "observations": len(observations),
        "crop_years": len(set(o["period"] for o in observations)),
        "first_period": min(o["period"] for o in observations).isoformat(),
        "latest_period": latest.isoformat(),
        "latest_full_cost_per_10a_jpy": national.get(latest),
        "latest_full_cost_per_60kg_jpy": newest_60kg,
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "agriculture",
    "name": {"en": "Rice production cost — national and by planted-area band",
             "ja": "米生産費（累年・作付規模別）"},
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
        "as_of_supported": True, "history_from": "1951",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published cost, revenue, quantity or hours",
         "unit": "JPY", "trust": "official"},
        {"id": "yoy", "label": "Change on the previous crop year", "unit": "%",
         "trust": "derived",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series"],
    "cite": "/rice.html?dataset=rice-production-cost",
    "page": "/rice.html",
    "notes": [
        "Three cost levels are published and all three are stored: 費用合計 total "
        "spend, 生産費（副産物価額差引） net of by-products, and 全算入生産費 with "
        "interest on the farmer's own capital and rent on the farmer's own land "
        "imputed. A farm-gate price can sit above the first and below the third; "
        "which level is quoted is usually where the policy argument is.",
        "Per-60kg costs are on the same 60kg bag of brown rice that "
        "rice-prices-jp quotes, so the two datasets can be read against each "
        "other directly.",
        "A crop year is dated to 1 January of its harvest year: the 令和5年産 crop "
        "is 2023-01-01. The confirmed report lands about eighteen months after "
        "the harvest, so the newest crop year is normally two years back.",
        "Planted-area bands are as published, and the boundaries were redrawn "
        "more than once — the early surveys split the smallest farms at 30 ares, "
        "later ones at 50. Each published band is its own series, so a band is "
        "only ever compared with itself; a band not published in a year is "
        "missing, never zero.",
        "The band table is five-yearly from the 1960 crop to the 2015 crop and "
        "annual from 2019. The national long run is annual throughout. Gaps in "
        "the band series are the publication schedule, not missing data.",
        "Costs are yen, the main product is kilograms and labour is hours. Each "
        "series carries its own unit and they are never summed together.",
    ],
}
