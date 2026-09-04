"""Adapter: Japan population by municipality — Basic Resident Register.

The same six-workbook release as `juki_population`, taken at the 市区町村別
cut instead of the 都道府県別 one: every city, town, village and ward on the
register, about 1,900 of them, three resident segments deep, with the year's
register flows and five-year age bands. This is where "which places are
emptying out" is actually answerable — a prefecture average hides a
depopulating village inside a growing prefecture.

Everything about parsing, measures, age bands and dating is shared with
`juki_population` and imported from it; what is genuinely different is the
geography, and it is more delicate than it looks.

**The workbook mixes four levels of area in one column, and three of them
overlap.** Under each prefecture it lists:

  01000  北海道           the prefecture
  01100  札幌市           a designated city — the sum of its wards
  01101  札幌市中央区      one of those wards
  ...
  02300  東津軽郡         a district — the sum of the towns in it
  02301  東津軽郡平内町    one of those towns
  13360  島しょ           Tokyo's islands — the sum of the towns below it

Add every municipality row up and you get 160 million people in a country of
124 million. The rows that are sums have to be identified and excluded from
any total, which this adapter does with two independent signals and then
proves by reconciliation:

1. **Name containment.** A grouping row's name is a strict prefix of the rows
   it groups (札幌市 → 札幌市中央区, 東津軽郡 → 東津軽郡平内町). This finds
   327 of the 328.
2. **Outline sums**, read from the all-residents workbook only. The workbook
   is an outline: a grouping row is immediately followed by the rows it
   groups, and its value is their sum. This catches 島しょ, whose name is not
   a prefix of anything.

The set is derived once, from the all-residents workbook, because which areas
*are* grouping rows is a fact about geography, not about a headcount — and
deriving it per segment does not work: foreign-resident counts are small
enough that a run of them coincidentally sums to the row above (it happens in
Yamaguchi), which would silently drop five real municipalities. The set is
then applied unchanged to all three segments, and every one of them must
reconcile to its prefecture exactly or the ingest fails.

Grouping rows are still stored — a reader wants Sapporo as a whole — but they
carry level="group" and must never be added to the leaves. `PRESENTATION`
serves the level of every area so a surface cannot get this wrong by
accident.
"""
import base64
import datetime
import json
import re

from . import xlsx
from .juki_population import (
    AGE_BANDS, AGE_ORDER, AGE_STEM, AGE_65_PLUS, AGE_LABEL, AGE_UNDER_15,
    AGE_WORKING, COLUMN_MEASURE, MEASURES, MEASURE_JA, MEASURE_KIND,
    MEASURE_LABEL, MEASURE_ORDER, MEASURE_UNIT, PREFECTURES, SEGMENTS,
    SEGMENT_EN, SEGMENT_JA, SEXES, SEX_LABEL, SEX_SUFFIX,
    PAGE_URL, SITE_ROOT, USER_AGENT, _era_years, _get, ValidationError,
)

DOWNLOAD_URL = PAGE_URL
RAW_SUFFIX = ".json"

NATIONAL = ("00000", "合計", "Japan")
PREFECTURE_JA = dict((code, ja) for code, ja, _en in PREFECTURES)
PREFECTURE_EN = dict((code, en) for code, _ja, en in PREFECTURES)

DATASET = {
    "slug": "population-jp-municipal",
    "title": "Population by Municipality — Japan (Basic Resident Register)",
    "country": "Japan",
    "agency": "Ministry of Internal Affairs and Communications",
    "agency_ja": "総務省",
    "base": None,
    "frequency": "annual",
    "description": (
        "Population, households and the year's register flows for every "
        "municipality in Japan — about 1,900 cities, towns, villages and "
        "wards — from the Basic Resident Register as of 1 January, split "
        "into all residents, Japanese residents and foreign residents, with "
        "population by five-year age band and sex for each. Designated "
        "cities, districts and Tokyo's island grouping are published as "
        "totals alongside the municipalities they contain; those rows are "
        "marked and must never be added to the rest."
    ),
}

SOURCE = {
    "source_id": "soumu:juki-jinko-shikuchoson",
    "name": ("Population, Vital Statistics and Number of Households Based on "
             "the Basic Resident Register — by municipality"),
    "name_ja": "住民基本台帳に基づく人口、人口動態及び世帯数（市区町村別）",
    "url": PAGE_URL,
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with "
        "CC BY 4.0): free to use with attribution to the Ministry of "
        "Internal Affairs and Communications."
    ),
}

_ANCHOR = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)


def _resolve_links(page_html):
    """(segment, table) -> URL for the six 市区町村別 workbooks."""
    found = {}
    for href, label in _ANCHOR.findall(page_html):
        if not href.lower().split("?")[0].endswith((".xls", ".xlsx")):
            continue
        text = re.sub(r"<[^>]+>", "", label)
        if "市区町村別" not in text:
            continue
        segment = None
        for code, ja, _en in SEGMENTS:
            if "【%s】" % ja in text:
                segment = code
                break
        if segment is None:
            continue
        if "年齢階級別" in text:
            table = "age"
        elif "人口動態" in text or "人口・世帯数" in text:
            table = "dynamics"
        else:
            continue
        url = href if href.startswith("http") else SITE_ROOT + href
        key = (segment, table)
        if key in found and found[key] != url:
            raise ValidationError(
                "two different files claim to be %s/%s" % key)
        found[key] = url
    missing = [(s, t) for s, _ja, _en in SEGMENTS for t in ("dynamics", "age")
               if (s, t) not in found]
    if missing:
        raise ValidationError(
            "ministry page is missing %d of the 6 municipality workbooks: %s"
            % (len(missing), missing))
    return found


def fetch():
    page = _get(PAGE_URL).decode("cp932", "replace")
    links = _resolve_links(page)
    envelope = {}
    for (segment, table), url in sorted(links.items()):
        envelope["%s.%s" % (segment, table)] = base64.b64encode(
            _get(url)).decode("ascii")
    global _RESOLVED
    _RESOLVED = dict(("%s.%s" % k, v) for k, v in links.items())
    return json.dumps(envelope, sort_keys=True).encode("utf-8")


_RESOLVED = {}
_AUDIT = {}
_SUPPRESSED_COUNT = [0]


# --- reading one workbook ---------------------------------------------------

def _sheet(raw, label):
    sheets = xlsx.sheets(raw)
    if len(sheets) != 1:
        raise ValidationError("%s: expected one sheet, found %d" % (label, len(sheets)))
    return list(sheets.values())[0]


def _header_row(grid, label):
    for row in sorted(grid):
        if xlsx.cell_text(grid[row].get("A")).strip() == "団体コード":
            return row
    raise ValidationError("%s: no 団体コード header row" % label)


# The ministry suppresses small cells at municipality level so that an
# individual cannot be identified — 17,829 of them in the 2026 foreign-resident
# age workbook alone. A suppressed cell is MISSING, never zero: a village with
# three foreign residents has three, not none, and its age bands are withheld
# rather than empty.
SUPPRESSED = ("X", "x", "Ｘ", "ｘ")


def _number(text, label, row, column):
    text = text.replace(",", "").strip()
    if text in SUPPRESSED:
        return None
    try:
        return float(text)
    except ValueError:
        raise ValidationError(
            "%s row %d column %s: %r is not a number" % (label, row, column, text))


def _area(code, pref_name, muni_name, label, row):
    """(geo id, display name, level). Five-digit JIS throughout, so a
    prefecture and its municipalities share a code space."""
    code = code.strip()
    if code in ("", "-", "－"):
        if pref_name != NATIONAL[1]:
            raise ValidationError(
                "%s row %d: a code-less row named %r" % (label, row, pref_name))
        return NATIONAL[0], NATIONAL[1], "national"
    if len(code) < 5 or not code[:5].isdigit():
        raise ValidationError(
            "%s row %d: unreadable local-government code %r" % (label, row, code))
    jis = code[:5]
    if muni_name in ("", "-", "－"):
        return jis, pref_name, "prefecture"
    return jis, muni_name, "municipality"


def _parse_dynamics(raw, segment):
    label = "%s municipal dynamics workbook" % segment
    grid = _sheet(raw, label)
    header = _header_row(grid, label)
    title = xlsx.cell_text(grid.get(1, {}).get("A"))
    years = _era_years(title)
    if len(years) < 2:
        raise ValidationError(
            "%s: title %r does not name both a stock year and a flow year"
            % (label, title[:60]))
    stock_year, flow_year = years[0], years[1]
    if flow_year != stock_year - 1:
        raise ValidationError(
            "%s: flow year %d is not the year before stock year %d"
            % (label, flow_year, stock_year))

    group, sub = grid[header - 2], grid[header - 1]
    columns = {}
    for column in sorted(sub):
        pair = (xlsx.cell_text(group.get(column)).strip(),
                xlsx.cell_text(sub.get(column)).strip())
        if not pair[1]:
            continue
        if pair not in COLUMN_MEASURE:
            raise ValidationError(
                "%s column %s: unrecognised header %r" % (label, column, pair))
        columns[column] = COLUMN_MEASURE[pair]

    rows = []
    for row in sorted(grid):
        if row <= header:
            continue
        cells = grid[row]
        pref_name = xlsx.cell_text(cells.get("B")).strip()
        if not pref_name:
            continue
        geo, name, level = _area(
            xlsx.cell_text(cells.get("A")), pref_name,
            xlsx.cell_text(cells.get("C")).strip(), label, row)
        values = {}
        for column, measure in columns.items():
            text = xlsx.cell_text(cells.get(column)).strip()
            if not text:
                continue
            number = _number(text, label, row, column)
            if number is None:
                _SUPPRESSED_COUNT[0] += 1
                continue
            values[measure] = number
        rows.append({"geo": geo, "name": name, "level": level,
                     "prefecture": pref_name, "values": values})
    return stock_year, flow_year, rows


def _parse_age(raw, segment):
    label = "%s municipal age workbook" % segment
    grid = _sheet(raw, label)
    header = _header_row(grid, label)
    title = xlsx.cell_text(grid.get(1, {}).get("A"))
    years = _era_years(title)
    if not years:
        raise ValidationError("%s: title %r names no year" % (label, title[:60]))

    bands = grid[header - 1]
    columns = {}
    for column in sorted(bands):
        text = xlsx.cell_text(bands.get(column)).strip()
        if not text:
            continue
        if text not in AGE_STEM:
            raise ValidationError(
                "%s column %s: unrecognised age band %r" % (label, column, text))
        columns[column] = AGE_STEM[text]
    if len(columns) != len(AGE_BANDS):
        raise ValidationError(
            "%s: %d age columns, expected %d" % (label, len(columns), len(AGE_BANDS)))

    out = {}
    withheld = set()
    for row in sorted(grid):
        if row <= header:
            continue
        cells = grid[row]
        pref_name = xlsx.cell_text(cells.get("B")).strip()
        if not pref_name:
            continue
        sex_ja = xlsx.cell_text(cells.get("D")).strip()
        if sex_ja not in SEX_SUFFIX:
            raise ValidationError(
                "%s row %d: unrecognised sex %r" % (label, row, sex_ja))
        suffix = SEX_SUFFIX[sex_ja]
        geo, _name, _level = _area(
            xlsx.cell_text(cells.get("A")), pref_name,
            xlsx.cell_text(cells.get("C")).strip(), label, row)
        values = out.setdefault(geo, {})
        for column, stem in columns.items():
            text = xlsx.cell_text(cells.get(column)).strip()
            if not text:
                continue
            number = _number(text, label, row, column)
            if number is None:
                _SUPPRESSED_COUNT[0] += 1
                withheld.add((geo, suffix))
                continue
            values["%s_%s" % (stem, suffix)] = number
    return years[0], out, withheld


# --- which rows are sums of other rows ---------------------------------------

def grouping_rows(rows):
    """The geo ids that are totals of other rows, by two independent signals.

    Derived from the all-residents workbook only and then applied to every
    segment: whether an area is a grouping row is a fact about geography, and
    the value-based signal is not safe on a small segment (a run of foreign
    counts can add up to the row above it by coincidence).
    """
    municipalities = [r for r in rows if r["level"] == "municipality"]
    parents = set()

    # 1. a grouping row's name is a strict prefix of the rows it groups
    by_pref = {}
    for r in municipalities:
        by_pref.setdefault(r["prefecture"], []).append(r)
    for kids in by_pref.values():
        names = [k["name"] for k in kids]
        for k in kids:
            if any(other != k["name"] and other.startswith(k["name"])
                   for other in names):
                parents.add(k["geo"])

    # 2. the workbook is an outline: a grouping row is immediately followed by
    #    the rows it groups and equals their sum
    for kids in by_pref.values():
        n = len(kids)
        i = 0
        while i < n:
            target = kids[i]["values"].get("population")
            run = 0.0
            hit = None
            j = i + 1
            while j < n and target is not None and run < target:
                run += kids[j]["values"].get("population") or 0.0
                if run == target and j > i:
                    hit = j
                    break
                j += 1
            if hit is not None and target:
                parents.add(kids[i]["geo"])
                i = hit + 1
            else:
                i += 1
    return parents


def parse(raw_bytes):
    _SUPPRESSED_COUNT[0] = 0
    envelope = json.loads(raw_bytes.decode("utf-8"))
    expected = set("%s.%s" % (s, t) for s, _ja, _en in SEGMENTS
                   for t in ("dynamics", "age"))
    if set(envelope) != expected:
        raise ValidationError(
            "artifact holds %s, expected %s" % (sorted(envelope), sorted(expected)))

    parsed = {}
    stock_years, flow_years = set(), set()
    for segment, _ja, _en in SEGMENTS:
        stock_year, flow_year, rows = _parse_dynamics(
            base64.b64decode(envelope["%s.dynamics" % segment]), segment)
        age_year, ages, withheld = _parse_age(
            base64.b64decode(envelope["%s.age" % segment]), segment)
        if age_year != stock_year:
            raise ValidationError(
                "%s: age workbook is for %d, population workbook for %d"
                % (segment, age_year, stock_year))
        stock_years.add(stock_year)
        flow_years.add(flow_year)
        parsed[segment] = (rows, ages, withheld)
    if len(stock_years) != 1 or len(flow_years) != 1:
        raise ValidationError(
            "the three segments disagree on the reference years: %s / %s"
            % (sorted(stock_years), sorted(flow_years)))
    stock_year, flow_year = stock_years.pop(), flow_years.pop()
    stock_period = datetime.date(stock_year, 1, 1)
    flow_period = datetime.date(flow_year, 1, 1)

    base_rows = parsed["all"][0]
    parents = grouping_rows(base_rows)
    areas = {}
    for r in base_rows:
        level = r["level"]
        if level == "municipality" and r["geo"] in parents:
            level = "group"
        areas[r["geo"]] = {"name": r["name"], "level": level,
                           "prefecture": r["prefecture"]}

    order = dict((geo, i) for i, geo in enumerate(a["geo"] for a in base_rows))
    series, observations = {}, []
    segment_index = dict((c, i) for i, (c, _j, _e) in enumerate(SEGMENTS))

    def add(geo, segment, measure, rank, name_en, name_ja, unit, period, value):
        code = "%s.%s.%s" % (geo, segment, measure)
        if code not in series:
            series[code] = {"code": code, "name_en": name_en, "name_ja": name_ja,
                            "unit": unit, "weight_per_10000": None,
                            "sort_order": rank}
        observations.append({"code": code, "period": period, "value": value})

    for segment, _ja, _en in SEGMENTS:
        rows, ages, _withheld = parsed[segment]
        for r in rows:
            geo = r["geo"]
            info = areas.get(geo)
            if info is None:
                raise ValidationError(
                    "%s names area %s which the all-residents workbook does not"
                    % (segment, geo))
            base = order.get(geo, 0) * 1000 + segment_index[segment] * 300
            en = _area_en(geo, info)
            for measure, value in r["values"].items():
                if measure.startswith("~"):
                    continue
                add(geo, segment, measure, base + MEASURE_ORDER[measure],
                    "%s — %s (%s)" % (en, MEASURE_LABEL[measure], SEGMENT_EN[segment]),
                    "%s %s（%s）" % (info["name"], MEASURE_JA[measure], SEGMENT_JA[segment]),
                    MEASURE_UNIT[measure],
                    stock_period if MEASURE_KIND[measure] == "stock" else flow_period,
                    value)
            for measure, value in (ages.get(geo) or {}).items():
                stem, suffix = measure.rsplit("_", 1)
                add(geo, segment, measure,
                    base + 100 + AGE_ORDER[stem] * 3 +
                    ["total", "male", "female"].index(suffix),
                    "%s — %s, %s (%s)" % (en, AGE_LABEL[stem], SEX_LABEL[suffix],
                                          SEGMENT_EN[segment]),
                    "%s 年齢階級別人口 %s（%s・%s）"
                    % (info["name"], _age_ja(stem), _sex_ja(suffix), SEGMENT_JA[segment]),
                    "persons", stock_period, value)

    _AUDIT.clear()
    _AUDIT.update({"stock_year": stock_year, "flow_year": flow_year,
                   "areas": areas, "parents": sorted(parents),
                   "suppressed_cells": _SUPPRESSED_COUNT[0],
                   "withheld": dict((seg, parsed[seg][2]) for seg, _j, _e in SEGMENTS)})
    return sorted(series.values(), key=lambda s: s["sort_order"]), observations


def _area_en(geo, info):
    if geo == NATIONAL[0]:
        return NATIONAL[2]
    if info["level"] == "prefecture":
        return PREFECTURE_EN.get(geo[:2], info["name"])
    # Municipality names are published only in Japanese; the prefecture is
    # named in English so an English reader can still place the row.
    return "%s, %s" % (info["name"], PREFECTURE_EN.get(geo[:2], ""))


def _age_ja(stem):
    for ja, s, _en in AGE_BANDS:
        if s == stem:
            return ja
    return stem


def _sex_ja(suffix):
    for ja, s, _en in SEXES:
        if s == suffix:
            return ja
    return suffix


# --- validate ---------------------------------------------------------------

POPULATION_MIN = 100_000_000
POPULATION_MAX = 140_000_000
# 1,718 municipalities plus 175 wards in the designated cities and Tokyo's 23
# special wards. A classification fault would move this by hundreds.
MIN_LEAVES = 1_700
MAX_LEAVES = 2_100
MIN_GROUPS = 250
MAX_GROUPS = 450
# Ceilings by level. A single village can legitimately have every foreign age
# band withheld, so per-area ceilings only make sense where suppression is
# immaterial; municipalities are held to an aggregate instead. Observed in the
# 2026 release: national 0.00%, worst prefecture 5.59%, aggregate across all
# municipalities 0.155% (foreign residents) and 0.005% (all residents).
MAX_UNRECORDED_SHARE_NATIONAL = 0.01
MAX_UNRECORDED_SHARE_PREFECTURE = 15.0
MAX_UNBANDED_AGGREGATE = 3.0


def validate(series, observations):
    if not _AUDIT:
        raise ValidationError("validate() called before parse()")
    areas = _AUDIT["areas"]

    value = {}
    for o in observations:
        key = (o["code"], o["period"])
        if key in value:
            raise ValidationError("duplicate observation %s %s" % key)
        value[key] = o["value"]
    latest = {}
    for (code, _period), v in value.items():
        latest[code] = v

    segments = [c for c, _j, _e in SEGMENTS]
    prefectures = [g for g, a in areas.items() if a["level"] == "prefecture"]
    leaves = [g for g, a in areas.items() if a["level"] == "municipality"]
    groups = [g for g, a in areas.items() if a["level"] == "group"]

    if len(prefectures) != 47:
        raise ValidationError("%d prefecture rows, expected 47" % len(prefectures))
    if not (MIN_LEAVES <= len(leaves) <= MAX_LEAVES):
        raise ValidationError(
            "%d municipalities after excluding grouping rows — outside the "
            "expected %d–%d, so the grouping rows were misidentified"
            % (len(leaves), MIN_LEAVES, MAX_LEAVES))
    if not (MIN_GROUPS <= len(groups) <= MAX_GROUPS):
        raise ValidationError(
            "%d grouping rows identified — outside the expected %d–%d"
            % (len(groups), MIN_GROUPS, MAX_GROUPS))

    # 1. Municipalities add to their prefecture, exactly, in every segment.
    #    This is what proves the grouping rows were identified correctly: get
    #    it wrong and a prefecture is out by a whole city.
    by_prefecture = {}
    for geo in leaves:
        by_prefecture.setdefault(areas[geo]["prefecture"], []).append(geo)
    pref_by_name = dict((areas[g]["prefecture"], g) for g in prefectures)
    reconciled = 0
    for segment in segments:
        for measure in ("population", "households", "births", "deaths",
                        "net_change", "natural_change", "social_change"):
            for pref_name, kids in by_prefecture.items():
                pref_geo = pref_by_name.get(pref_name)
                if pref_geo is None:
                    raise ValidationError("no prefecture row for %s" % pref_name)
                total = latest.get("%s.%s.%s" % (pref_geo, segment, measure))
                if total is None:
                    continue
                parts = [latest.get("%s.%s.%s" % (g, segment, measure)) for g in kids]
                if any(p is None for p in parts):
                    continue
                if sum(parts) != total:
                    raise ValidationError(
                        "%s %s %s: %d municipalities sum to %d, the prefecture "
                        "row says %d" % (segment, pref_name, measure, len(kids),
                                         sum(parts), total))
                reconciled += 1

    # 2. The 47 prefectures add to the national row.
    for segment in segments:
        for measure in ("population", "households", "births", "deaths", "net_change"):
            total = latest.get("%s.%s.%s" % (NATIONAL[0], segment, measure))
            parts = [latest.get("%s.%s.%s" % (g, segment, measure)) for g in prefectures]
            if total is None or any(p is None for p in parts):
                continue
            if sum(parts) != total:
                raise ValidationError(
                    "%s %s: 47 prefectures sum to %d, the national row says %d"
                    % (segment, measure, sum(parts), total))
            reconciled += 1

    # 3. All residents = Japanese + foreign, everywhere including the groups.
    for geo in areas:
        for measure in ("population", "households", "births", "deaths"):
            keys = ["%s.%s.%s" % (geo, s, measure) for s in ("all", "jp", "fgn")]
            vals = [latest.get(k) for k in keys]
            if any(v is None for v in vals):
                continue
            if vals[0] != vals[1] + vals[2]:
                raise ValidationError(
                    "%s %s: all %d but Japanese %d + foreign %d"
                    % (geo, measure, vals[0], vals[1], vals[2]))

    # 4. The register's own arithmetic, on every area at every level.
    for segment in segments:
        for geo in areas:
            def v(measure):
                return latest.get("%s.%s.%s" % (geo, segment, measure))
            if None in (v("additions_total"), v("deletions_total"), v("net_change")):
                continue
            if v("additions_total") - v("deletions_total") != v("net_change"):
                raise ValidationError(
                    "%s %s: additions less deletions is not the net change" % (segment, geo))
            if v("births") - v("deaths") != v("natural_change"):
                raise ValidationError(
                    "%s %s: births less deaths is not the natural change" % (segment, geo))
            if v("natural_change") + v("social_change") != v("net_change"):
                raise ValidationError(
                    "%s %s: natural and social do not add to the net change" % (segment, geo))

    # 5. Age bands against the published total. Three different things sit
    #    under a shortfall here and only two of them can be held to a ceiling:
    #      - residents with no usable birth date (tiny, everywhere);
    #      - cells the ministry suppressed as too small to publish;
    #      - small band values published as 0 on a grouping row, which is the
    #        same disclosure control by another route.
    #    In one Hokkaido village every foreign band is withheld — a 100%
    #    shortfall that is entirely correct. So the per-area ceiling applies
    #    only to the national and prefecture rows, where suppression is
    #    immaterial, and municipalities are gated in aggregate instead, which
    #    is what would move if the parse were wrong.
    worst_area = {}
    unbanded = {}
    banded_total = {}
    for segment in segments:
        for geo, info in areas.items():
            head = latest.get("%s.%s.age_total_total" % (geo, segment))
            pop = latest.get("%s.%s.population" % (geo, segment))
            if head is None or pop is None:
                continue
            if head != pop:
                raise ValidationError(
                    "%s %s: age workbook totals %d, population workbook %d"
                    % (segment, geo, head, pop))
            banded = sum(latest.get("%s.%s.%s_total" % (geo, segment, stem), 0.0)
                         for stem in AGE_ORDER if stem != "age_total")
            gap = head - banded
            if gap < 0:
                raise ValidationError(
                    "%s %s: age bands exceed the published total by %d"
                    % (segment, geo, -gap))
            share = gap / head * 100.0 if head else 0.0
            level = info["level"]
            if level in ("national", "prefecture"):
                ceiling = (MAX_UNRECORDED_SHARE_NATIONAL if level == "national"
                           else MAX_UNRECORDED_SHARE_PREFECTURE)
                if share > ceiling:
                    raise ValidationError(
                        "%s %s (%s): %d of %d have no age band (%.2f%%), above "
                        "the %.2f%% ceiling for that level"
                        % (segment, geo, level, gap, head, share, ceiling))
            elif level == "municipality":
                unbanded[segment] = unbanded.get(segment, 0.0) + gap
                banded_total[segment] = banded_total.get(segment, 0.0) + head
            key = "%s.%s" % (segment, level)
            if share > worst_area.get(key, (0.0, None))[0]:
                worst_area[key] = (round(share, 2), geo)

    for segment in segments:
        total = banded_total.get(segment) or 0.0
        if not total:
            continue
        share = unbanded.get(segment, 0.0) / total * 100.0
        if share > MAX_UNBANDED_AGGREGATE:
            raise ValidationError(
                "%s: %d of %d residents across all municipalities fall outside "
                "the age bands (%.3f%%), above the %.2f%% ceiling — that is a "
                "parsing fault, not disclosure control"
                % (segment, unbanded[segment], total, share, MAX_UNBANDED_AGGREGATE))

    national = latest.get("%s.all.population" % NATIONAL[0])
    if national is None or not (POPULATION_MIN <= national <= POPULATION_MAX):
        raise ValidationError("national population %s outside the sanity band" % national)

    stock_year = _AUDIT["stock_year"]
    newest = max(o["period"] for o in observations)
    if newest != datetime.date(stock_year, 1, 1):
        raise ValidationError(
            "latest period %s does not match the stock year %d" % (newest, stock_year))

    return {
        "series": len(series),
        "observations": len(observations),
        "latest_period": newest.isoformat(),
        "stock_year": stock_year,
        "flow_year": _AUDIT["flow_year"],
        "areas": len(areas),
        "municipalities": len(leaves),
        "grouping_rows": len(groups),
        "prefectures": len(prefectures),
        "reconciliations": reconciled,
        "population_total": int(national),
        # The area list travels with the release: a surface needs every
        # municipality's name, prefecture and level, and the level is what
        # stops it adding a designated city to its own wards.
        "geographies": [
            {"code": geo, "name": info["name"], "level": info["level"],
             "prefecture": geo[:2] if info["level"] != "national" else None}
            for geo, info in sorted(areas.items())],
        "suppressed_cells": _AUDIT.get("suppressed_cells", 0),
        "worst_unbanded_share_pct": dict(
            (k, v[0]) for k, v in sorted(worst_area.items())),
        "unbanded_share_of_municipalities_pct": dict(
            (seg, round(unbanded.get(seg, 0.0) / banded_total[seg] * 100.0, 4))
            for seg in segments if banded_total.get(seg)),
        "resolved_urls": dict(_RESOLVED),
    }


PRESENTATION = {
    "credit_line": ("Source: Ministry of Internal Affairs and Communications, "
                    "Japan — Basic Resident Register."),
    "stale_after_days": 600,
    "prefectures": {
        "headline": "population",
        "national": NATIONAL[0],
        "segments": [{"code": c, "label": e, "label_ja": j} for c, j, e in SEGMENTS],
        "measures": [{"code": c, "label": l, "kind": k, "unit": u}
                     for c, l, k, u in MEASURES],
        "age_bands": [{"code": s, "label": e, "label_ja": j}
                      for j, s, e in AGE_BANDS if s != "age_total"],
        "age_groups": {"under_15": AGE_UNDER_15, "working_15_64": AGE_WORKING,
                       "aged_65_plus": AGE_65_PLUS},
        "sexes": [{"code": s, "label": e} for _j, s, e in SEXES],
        # The level of every area, because adding a designated city to its own
        # wards double-counts a million people and nothing on the wire would
        # otherwise say so.
        "levels": ["national", "prefecture", "group", "municipality"],
        # 585,000 series is not a payload; the API insists on one prefecture.
        "requires_area_filter": True,
        "companion_dataset": "population-jp",
    },
}


# The dataset's card. The municipal sibling of population-jp: same register,
# same measures, ~1,900 areas instead of 47. The level of every area is served
# because adding a designated city to its own wards double-counts.
MANIFEST = {
    "id": DATASET["slug"],
    "section": "demography",
    "name": {"en": "Population by municipality — Basic Resident Register",
             "ja": "住民基本台帳に基づく人口・世帯数（市区町村別）"},
    "shape": "series",
    "summary": ("Registered residents, households and the year's register flows "
                "for every municipality in Japan — about 1,900 cities, towns, "
                "villages and wards — as of 1 January, split into all, Japanese "
                "and foreign residents with five-year age bands by sex."),
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
        "as_of_supported": True, "history_from": "2025-01-01",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Registered residents, households or register flows, as published",
         "unit": "persons", "trust": "official"},
        {"id": "yoy", "label": "Year over year", "unit": "%", "trust": "derived",
         "where": "annual series: t−12 months is the previous 1 January",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
        {"id": "change_pct", "label": "Change during the year", "unit": "%",
         "trust": "derived",
         "calc": "change % = net change ÷ (population − net change) × 100"},
        {"id": "natural_pct", "label": "Natural change", "unit": "%", "trust": "derived",
         "calc": "natural % = (births − deaths) ÷ (population − net change) × 100"},
        {"id": "social_pct", "label": "Social change", "unit": "%", "trust": "derived",
         "calc": "social % = (net change − natural change) ÷ (population − net change) × 100"},
        {"id": "foreign_pct", "label": "Foreign residents' share", "unit": "%",
         "trust": "derived",
         "calc": "foreign share % = foreign residents ÷ all residents × 100"},
        {"id": "aged_pct", "label": "Aged 65 and over", "unit": "%", "trust": "derived",
         "calc": ("aged 65+ % = (sum of the five-year bands from 65 upward) ÷ all "
                  "residents × 100")},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "prefectures": "/api/v1/%s/prefectures" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series"],
    "cite": "/population.html",
    "page": "/population.html",
    "notes": [
        "Designated cities, districts and Tokyo's island grouping are published "
        "as totals alongside the municipalities they contain. Every area carries "
        "its level — adding a designated city to its own wards double-counts a "
        "million people.",
        "About 585,000 series: /prefectures requires an area filter and serves "
        "one prefecture at a time.",
        "Counts are as of 1 January; flows cover the preceding calendar year.",
    ],
}
