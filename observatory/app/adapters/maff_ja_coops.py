"""Adapter: agricultural co-operatives — MAFF 総合農協統計表.

Source: 農林水産省, 農業協同組合及び同連合会一斉調査 (e-Stat statsCode
00500602) — the annual census of every 総合農協 in Japan. What is ingested is
the **segment profit and loss account**: the co-ops' whole income statement,
split across the five businesses they run.

Why the segment P&L is the point. JA is usually described rather than
measured: a bank and an insurer with a farm-supply arm attached, cross-
subsidising farming out of the deposit book. This table is that description
as an income statement. 信用事業 (banking) and 共済事業 (mutual insurance)
carry their own revenue, costs and pre-tax profit; 農業関連事業 (marketing
and supply) and 営農指導事業 (farm guidance) carry theirs; and the last two
lines show the farm-guidance loss being *allocated back* across the earning
segments, which is the cross-subsidy written down by the ministry itself.
Nothing in English carries it.

**Two table shapes, one series.** The long-run table carries a time axis and
covers fiscal 2004 through 2016; from fiscal 2017 each year is republished as
its own table with no time axis and with the segment and line axes the other
way round. Both are read by matching the *names* on each axis rather than the
axis id, so the layout swap cannot silently transpose the grid.

**A fiscal year is dated to 1 April.** 令和5事業年度 runs April 2023 to March
2024 and is stored at 2023-04-01, so a year-on-year measure compares like with
like and the period sorts with everything else on the platform.

**Money is 千円 as published and counts are co-ops** — the two never share a
series. The published figures are the survey's own totals; the ratio a reader
usually wants (how much of group profit banking earns, how many co-ops lose
money on farming) is a calculation and is computed where it is shown.

**This is national.** The ministry publishes the segment income statement for
the country, not by prefecture, so neither does this dataset.

**The co-op count is deliberately not here yet.** The same survey publishes the
number of co-operatives by prefecture — the consolidation from 661 in fiscal
2016 to 537 in fiscal 2023 — but its area axis is not trustworthy to parse
without more work: several editions list the same prefecture label twice under
different class codes with different values, and the axis mixes prefectures,
membership bands, ratios and year rows in one vocabulary that changes shape
almost every edition. Publishing a number that might be the wrong block is
worse than publishing none, so the count waits for a parser that can tell the
blocks apart.
"""
import datetime
import json
import re

from . import estat_api


class ValidationError(Exception):
    pass


STATS_CODE = "00500602"
SEARCH_WORD = "総合農協統計表"

_SEGMENT_TITLE = re.compile(r"部門別損益計算書")
_PART_ONE = re.compile(r"第１部")

# The five businesses, the group total and the overhead that is not any one of
# them. Names are as e-Stat writes them on whichever axis carries them.
SEGMENTS = {
    "計": ("all", "All businesses"),
    "信用事業": ("credit", "Banking"),
    "共済事業": ("kyosai", "Mutual insurance"),
    "農業関連事業": ("agri", "Farm marketing and supply"),
    "生活その他事業": ("living", "Living services and other"),
    "営農指導事業": ("guidance", "Farm guidance"),
    "共通管理費等": ("overhead", "Common overhead"),
}
SEGMENT_ORDER = dict((ja, i) for i, ja in enumerate(SEGMENTS))

# The income statement, in published order. The last two lines are the whole
# argument: farm guidance runs at a loss, and that loss is charged back to the
# segments that earn.
#
# **Lines are matched by position, not by name, and that is deliberate.** The
# ministry has relabelled these same twenty lines in almost every edition —
# appending the published reference number (事業収益１), the formula that
# defines the line (事業総利益３（１－２）), moving the うち markers, changing
# which parent a sub-line hangs off, and in the 2017 edition simply misspelling
# 事業外費用 as 事業外費. The twenty lines and their order have never changed,
# and the ministry's own numbering 1-20 says so, so position is the stable key.
# ANCHORS below re-checks that assumption on every ingest: a line whose name
# still does not match after the labelling noise is stripped stops the ingest
# rather than being silently mapped to the wrong row.
LINES = [
    ("revenue", "Business revenue", "事業収益"),
    ("cost-of-business", "Business costs", "事業費用"),
    ("gross-profit", "Gross business profit", "事業総利益"),
    ("opex", "Operating expenses", "事業管理費"),
    ("opex.depreciation", "Operating expenses — depreciation", None),
    ("opex.common", "Operating expenses — common overhead", None),
    ("opex.common.depreciation",
     "Operating expenses — common overhead, depreciation", None),
    ("operating-profit", "Operating profit", "事業利益"),
    ("non-operating-income", "Non-operating income", "事業外収益"),
    ("non-operating-income.common", "Non-operating income — common", None),
    ("non-operating-expense", "Non-operating expenses", None),
    ("non-operating-expense.common", "Non-operating expenses — common", None),
    ("ordinary-profit", "Ordinary profit", "経常利益"),
    ("extraordinary-gain", "Extraordinary gains", "特別利益"),
    ("extraordinary-gain.common", "Extraordinary gains — common", None),
    ("extraordinary-loss", "Extraordinary losses", "特別損失"),
    ("extraordinary-loss.common", "Extraordinary losses — common", None),
    ("pre-tax-profit", "Pre-tax profit", "税引前当期利益"),
    ("guidance-charge", "Farm-guidance loss charged to this segment",
     "営農指導事業分配賦額"),
    ("pre-tax-profit-after-guidance",
     "Pre-tax profit after the farm-guidance charge",
     "営農指導事業分配賦後税引前当期利益"),
]
# Which positions carry a name stable enough to check. The sub-lines are not
# among them: some editions publish them as a bare 「（うち減価償却費）」 with no
# parent, which normalises to nothing at all.
ANCHORS = dict((i, root) for i, (_s, _e, root) in enumerate(LINES) if root)

# Labelling noise the ministry adds and removes between editions: the
# published reference number, the formula in brackets, and the うち marker
# that says "of which".
_LINE_NOISE = re.compile(r"[0-9０-９]+|[（(][^）)]*[）)]|うち")

_FISCAL = re.compile(r"^(\d{4})年度$")
_ERA = {"平成": 1988, "令和": 2018}
_FULLWIDTH = dict(zip("０１２３４５６７８９", "0123456789"))

DATASET = {
    "slug": "ja-statistics",
    "title": "Agricultural Co-operatives — Segment Income Statement (Japan)",
    "country": "Japan",
    "agency": "Ministry of Agriculture, Forestry and Fisheries",
    "agency_ja": "農林水産省",
    "base": None,
    "frequency": "annual",
    "description": (
        "The Japanese agricultural co-operatives' own income statement, split "
        "across the businesses they run — banking, mutual insurance, farm "
        "marketing and supply, living services and farm guidance — in thousands "
        "of yen by fiscal year from 2004, including the farm-guidance loss "
        "charged back to the segments that earn. National, from MAFF's annual "
        "census of every multi-purpose co-operative."
    ),
}

SOURCE = {
    "source_id": "estat:00500602-ja",
    "name": "MAFF — Survey of Agricultural Co-operatives (総合農協統計表)",
    "name_ja": "農林水産省 農業協同組合及び同連合会一斉調査 総合農協統計表",
    "url": "https://www.maff.go.jp/j/tokei/kouhyou/sougou_nougyou/",
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Agriculture, "
        "Forestry and Fisheries. Retrieved through the e-Stat API."
    ),
}

DOWNLOAD_URL = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData (00500602)"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": ("Source: Ministry of Agriculture, Forestry and Fisheries — "
                    "Survey of Agricultural Co-operatives (総合農協統計表)."),
    # Calibrated to the survey's own record, not guessed: e-Stat opened the
    # fiscal-2022 edition on 2025-01-31 and the fiscal-2023 edition on
    # 2026-03-31, so a fiscal year is published about three years after the
    # April it began. The newest period is therefore already ~1,095 days old
    # the day it lands, and up to ~1,460 days old the day before the next
    # edition. This allows that plus two months, so the flag means "an edition
    # that was due has not come", never "this survey is slow".
    "stale_after_days": 1_520,
    "main_series": [
        {"role": "headline", "code": "pl.all.pre-tax-profit",
         "label": "Pre-tax profit, all businesses", "slot": 1},
        {"role": "credit", "code": "pl.credit.pre-tax-profit",
         "label": "Banking", "slot": 2},
        {"role": "agri", "code": "pl.agri.pre-tax-profit",
         "label": "Farm marketing and supply", "slot": 3},
    ],
    "overview_tiles": [
        {"key": "profit", "type": "level", "code": "pl.all.pre-tax-profit",
         "label": "Pre-Tax Profit"},
        {"key": "credit", "type": "level", "code": "pl.credit.pre-tax-profit",
         "label": "Banking"},
        {"key": "agri", "type": "level", "code": "pl.agri.pre-tax-profit",
         "label": "Farm Business"},
        {"key": "guidance", "type": "level", "code": "pl.guidance.pre-tax-profit",
         "label": "Farm Guidance"},
    ],
    "kinds": dict(("pl.%s.%s" % (seg[0], line[0]), "level")
                  for seg in SEGMENTS.values() for line in LINES),
}


# --- fetching ---------------------------------------------------------------

def _title_of(table):
    title = table.get("TITLE")
    title = title.get("$") if isinstance(title, dict) else (title or "")
    return re.sub(r"\s+", "", str(title))


def table_list():
    """Every table under the survey's search term, with the count checked.

    The survey publishes about 1,600 tables. A truncated list looks exactly
    like "the table is gone", which would freeze the dataset silently.
    """
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


def chosen_tables(tables):
    """{'segment': [statsDataId, ...]} — the long run plus each fiscal year.

    A long-run table (SURVEY_DATE 0) carries its own time axis; every other
    edition is one fiscal year. The newest table wins for a given survey date,
    so a re-published year does not appear twice.
    """
    picked = {"segment": {}}
    for table in tables:
        title = _title_of(table)
        if not _PART_ONE.search(title) or not _SEGMENT_TITLE.search(title):
            continue
        survey = str(table.get("SURVEY_DATE"))
        current = picked["segment"].get(survey)
        if current is None or table["@id"] > current:
            picked["segment"][survey] = table["@id"]
    if not picked["segment"]:
        raise ValidationError(
            "no 部門別損益計算書 table found under statsCode %s" % STATS_CODE)
    return dict((k, [picked[k][s] for s in sorted(picked[k])]) for k in picked)


def fetch():
    picked = chosen_tables(table_list())
    out = {"tables": {}}
    for key, ids in sorted(picked.items()):
        out["tables"][key] = [
            {"statsDataId": tid, "pages": estat_api.get_stats_data(tid)}
            for tid in ids]
    return json.dumps(out, ensure_ascii=False, sort_keys=True).encode("utf-8")


def canonical_bytes(raw):
    """The artifact without e-Stat's served-at timestamps — see estat_api."""
    return json.dumps(estat_api.strip_timestamps(json.loads(raw.decode("utf-8"))),
                      ensure_ascii=False, sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _fiscal_year(label):
    """A fiscal-year label -> its starting calendar year, or None."""
    text = re.sub(r"\s+", "", label)
    match = _FISCAL.match(text)
    if match:
        return int(match.group(1))
    match = re.match(r"^(平成|令和)(元|[0-9０-９]+)(事業年度|年度)$", text)
    if match:
        digits = "".join(_FULLWIDTH.get(c, c) for c in match.group(2))
        return _ERA[match.group(1)] + (1 if digits == "元" else int(digits))
    return None


def _survey_fiscal_year(table):
    """The fiscal year an annual edition covers, from its SURVEY_DATE."""
    survey = str(table)
    if len(survey) >= 6 and survey[:6].isdigit():
        return int(survey[:4])
    return None


def _axes(data):
    """{axis id: {code: name}} for every classification axis of a response."""
    out = {}
    for obj in data["CLASS_INF"]["CLASS_OBJ"]:
        entries = obj["CLASS"]
        entries = [entries] if isinstance(entries, dict) else entries
        out[obj["@id"]] = dict((e["@code"], e["@name"]) for e in entries)
    return out


def _axis_carrying(axes, names):
    """The id of the axis whose values are the given vocabulary.

    The long-run and annual tables put the segment and the income-statement
    line on opposite axes, so neither can be addressed by its id. Matching on
    the vocabulary is what makes the swap safe.
    """
    best, best_hits = None, 0
    for axis, values in axes.items():
        hits = sum(1 for v in values.values() if re.sub(r"\s+", "", v) in names)
        if hits > best_hits:
            best, best_hits = axis, hits
    return best


def _axis_order(data, axis):
    """The axis's class codes in the order the API lists them.

    `_axes` returns a mapping, which says nothing about order; the income
    statement is matched by position, so the order is what matters here.
    """
    for obj in data["CLASS_INF"]["CLASS_OBJ"]:
        if obj["@id"] != axis:
            continue
        entries = obj["CLASS"]
        entries = [entries] if isinstance(entries, dict) else entries
        return [e["@code"] for e in entries]
    return []


def _line_axis(axes, seg_axis, table_id):
    """The income-statement axis, checked against the anchors.

    It is the axis with exactly twenty values that is not the segment axis or
    the time axis. Its anchor rows must still carry their published names once
    the reference numbers, bracketed formulas and うち markers are stripped —
    if they do not, the twenty lines are no longer the twenty lines this
    adapter knows and nothing is published.
    """
    for axis, values in axes.items():
        if axis in (seg_axis, "time", "area") or len(values) != len(LINES):
            continue
        order = [values[code] for code in sorted(values)]
        break
    else:
        raise ValidationError(
            "table %s has no axis with the %d income-statement lines"
            % (table_id, len(LINES)))
    return axis


def _check_anchors(names, table_id):
    """Every anchor line still says what it should, noise stripped."""
    for position, root in ANCHORS.items():
        got = _LINE_NOISE.sub("", re.sub(r"\s+", "", names[position])).strip("_")
        got = got.split("_")[-1]
        if got != root:
            raise ValidationError(
                "table %s: income-statement line %d reads %r, not %r — the "
                "published order of the twenty lines has changed and matching "
                "them by position is no longer safe"
                % (table_id, position + 1, names[position], root))


def _value(text):
    text = (text or "").strip().replace(",", "")
    if text in ("", "-", "－", "…", "***", "x", "X"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _entries(data):
    values = data["DATA_INF"]["VALUE"]
    return [values] if isinstance(values, dict) else values


def parse(raw):
    tables = json.loads(raw.decode("utf-8"))["tables"]
    meta, values = {}, {}

    def record(code, name_en, name_ja, unit, sort_order, year, value):
        # A fiscal year is dated to the 1 April it starts on.
        period = datetime.date(year, 4, 1)
        meta.setdefault(code, {
            "code": code, "name_en": name_en, "name_ja": name_ja, "unit": unit,
            "weight_per_10000": None, "sort_order": sort_order,
        })
        previous = values.setdefault(code, {}).get(period)
        if previous is not None and previous != value:
            raise ValidationError(
                "%s fiscal %d is published twice with different values (%s, %s)"
                % (code, year, previous, value))
        values[code][period] = value

    # --- segment income statement ------------------------------------------
    for entry in tables["segment"]:
        for page in entry["pages"]:
            data = page["GET_STATS_DATA"]["STATISTICAL_DATA"]
            axes = _axes(data)
            seg_axis = _axis_carrying(axes, set(SEGMENTS))
            line_axis = _line_axis(axes, seg_axis, entry["statsDataId"])
            if seg_axis is None:
                raise ValidationError(
                    "table %s carries no segment axis" % entry["statsDataId"])
            order = _axis_order(data, line_axis)
            _check_anchors([axes[line_axis][code] for code in order],
                           entry["statsDataId"])
            line_at = dict((code, i) for i, code in enumerate(order))
            years = dict(
                (code, _fiscal_year(name))
                for code, name in axes.get("time", {}).items())
            table_year = _fiscal_year(
                str(data["TABLE_INF"].get("SURVEY_DATE", ""))[:4] + "年度")

            for value_row in _entries(data):
                segment_ja = re.sub(r"\s+", "", axes[seg_axis][value_row["@" + seg_axis]])
                if segment_ja not in SEGMENTS:
                    continue
                position = line_at.get(value_row.get("@" + line_axis))
                if position is None:
                    continue
                year = (years.get(value_row.get("@time"))
                        if "@time" in value_row else table_year)
                number = _value(value_row.get("$"))
                if year is None or number is None:
                    continue
                seg_slug, seg_en = SEGMENTS[segment_ja]
                line_slug, line_en, _root = LINES[position]
                record("pl.%s.%s" % (seg_slug, line_slug),
                       "%s — %s" % (seg_en, line_en),
                       "%s %s" % (segment_ja,
                                  axes[line_axis][value_row["@" + line_axis]]),
                       "jpy_1000",
                       SEGMENT_ORDER[segment_ja] * 100 + position,
                       year, number)

    series = sorted(meta.values(), key=lambda s: (s["sort_order"], s["code"]))
    observations = [{"code": code, "period": period, "value": value}
                    for code in sorted(values)
                    for period, value in sorted(values[code].items())]
    return series, observations


# --- validation -------------------------------------------------------------

FIRST_SEGMENT_YEAR = 2004
# Seven segments times twenty lines is 140 combinations, but not every line
# applies to every segment — 共通管理費等 is overhead, so it carries costs and
# no revenue — and an empty cell stays empty. About 120 combinations are
# actually published.
MIN_SERIES = 100
# The whole group's revenue has run between about ¥4tn and ¥6tn (in 千円,
# 4e9 to 6e9). A figure an order of magnitude outside that is a unit error.
REVENUE_FLOOR, REVENUE_CEILING = 1e9, 2e10


def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")

    codes = set(s["code"] for s in series)
    for required in ("pl.all.revenue", "pl.all.pre-tax-profit",
                     "pl.credit.pre-tax-profit", "pl.guidance.pre-tax-profit"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)
    if len(codes) < MIN_SERIES:
        raise ValidationError(
            "only %d series; expected at least %d" % (len(codes), MIN_SERIES))

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    revenue = by_code["pl.all.revenue"]
    years = sorted(revenue)
    if years[0].year != FIRST_SEGMENT_YEAR:
        raise ValidationError(
            "the segment income statement starts in fiscal %d; the published "
            "long-run table starts in fiscal %d"
            % (years[0].year, FIRST_SEGMENT_YEAR))
    for period, value in revenue.items():
        if not (REVENUE_FLOOR <= value <= REVENUE_CEILING):
            raise ValidationError(
                "fiscal %d: group revenue of %s thousand yen is outside the "
                "plausible range" % (period.year, value))
    # No fiscal year may be missing between the first and the last: a gap
    # means an edition stopped being listed and a whole year vanished.
    for previous, current in zip(years, years[1:]):
        if current.year - previous.year != 1:
            raise ValidationError(
                "no segment income statement between fiscal %d and fiscal %d"
                % (previous.year, current.year))

    # The segments must add up to the group, at every year the parts exist.
    # 共通管理費等 is overhead that is not a business, so it is part of the
    # total but is not one of the five; the gate allows for the ministry
    # rounding each column independently.
    parts = ["pl.%s.revenue" % SEGMENTS[ja][0] for ja in SEGMENTS if ja != "計"]
    for period, total in revenue.items():
        values = [by_code.get(p, {}).get(period) for p in parts]
        if any(v is None for v in values):
            continue
        if abs(sum(values) - total) > max(1_000.0, abs(total) * 0.001):
            raise ValidationError(
                "fiscal %d: the segments' revenue sums to %s but the group "
                "total is %s" % (period.year, sum(values), total))

    latest = max(o["period"] for o in observations)
    return {
        "series": len(codes),
        "observations": len(observations),
        "fiscal_years": len(set(o["period"] for o in observations)),
        "first_period": min(o["period"] for o in observations).isoformat(),
        "latest_period": latest.isoformat(),
        "latest_group_revenue_jpy_1000": revenue.get(latest),
        "latest_farm_guidance_pre_tax_jpy_1000":
            by_code.get("pl.guidance.pre-tax-profit", {}).get(latest),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "agriculture",
    "name": {"en": "Agricultural co-operatives — segment income statement",
             "ja": "総合農協統計表（部門別損益計算書）"},
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
        "as_of_supported": True, "history_from": "2004",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published amount, thousands of yen",
         "unit": "JPY_thousand", "trust": "official"},
        {"id": "yoy", "label": "Change on the previous fiscal year", "unit": "%",
         "trust": "derived",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series"],
    "cite": "/ja.html",
    "page": "/ja.html",
    "notes": [
        "National. MAFF does not publish the segment income statement by "
        "prefecture, so neither does this dataset.",
        "The last two lines are the cross-subsidy written down: 営農指導事業分配賦額 "
        "is the farm-guidance loss charged back to each earning segment, and the "
        "line after it is that segment's pre-tax profit once it has borne the "
        "charge. Read them together or the farm-guidance segment looks like a "
        "rounding error rather than a cost the banking arm carries.",
        "共通管理費等 is overhead that belongs to no single business. It is part of "
        "the group total and is not one of the five businesses; adding the five "
        "without it does not reconcile.",
        "A fiscal year runs April to March and is dated to the 1 April it starts "
        "on: 令和5事業年度 is 2023-04-01. The confirmed census lands well over a "
        "year after the year it covers.",
        "Amounts are thousands of yen exactly as published, never rescaled.",
        "The same survey publishes the number of co-operatives by prefecture. It "
        "is not ingested yet: several editions list the same prefecture twice "
        "under different class codes with different values, and the area axis "
        "mixes prefectures, membership bands, ratios and year rows in a "
        "vocabulary that changes shape almost every edition.",
        "The long-run table covers fiscal 2004 to 2016 with a time axis; later "
        "years are one table each and put the segment and the income-statement "
        "line on opposite axes. Both are read by name, so the layout change "
        "cannot transpose the grid.",
    ],
}
