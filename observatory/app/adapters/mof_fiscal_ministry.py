# -*- coding: utf-8 -*-
"""Adapter: general-account spending by ministry — MOF 財政統計 第5表・第6表.

Source: 財務省, 財政統計 第5表「明治26年度以降一般会計歳出所管別予算」 and 第6表
「明治初年度以降一般会計歳出所管別決算」 — the general account split by the body
that spends it rather than by what it is spent on. Budget from fiscal 1893 and
settlement from the first Meiji accounting periods, in ¥ million.

**Ministries are published under the name they had, and so are the series.**
The 2001 central government reorganisation did not rename ministries so much as
rebuild them: 大蔵省 became 財務省 but lost bank supervision to the new Financial
Services Agency; 厚生省 and 労働省 merged into 厚生労働省; 運輸省, 建設省, 国土庁
and 北海道開発庁 became 国土交通省; 総理府 became 内閣府. Splicing 大蔵省 onto
財務省 would draw a continuous line across a discontinuity, so each name is its
own series. A chart of Japanese ministry spending across 2001 is a chart of
series ending and series beginning, which is what actually happened.

**The war ministries are in here, because they were in the budget.** 陸軍省 and
海軍省 run to fiscal 1945, 軍需省 and 大東亜省 cover the war years, and the two
demobilisation ministries (第一復員省, 第二復員省) exist for 1946 and 1947. They
are published because the table publishes them; the extraordinary war accounts
(臨時軍事費特別会計) were a *separate* account and are not in the general account
at all, which is why the general account looks small for 1937-45.

**Early years are sampled, and the gaps are real.** The Meiji and Taisho sheets
print every fifth year, not every year, so the series genuinely has holes before
the 1920s. They are left as holes — never interpolated, never carried forward.

**Years run across the columns and the era carries left to right.** A header row
reads 「平成30年度」, 「令和元年度」, then a bare 「2」 and 「3」 meaning 令和2 and
令和3, so each header is resolved against the era last seen to its left. The
eight pre-1875 accounting periods (明治第1期, 第5期) have no fiscal year and are
skipped rather than being given one.
"""
import base64
import json
import re

from . import boj_ts, jp_era, xlsx


class ValidationError(Exception):
    pass


BASE = "https://www.mof.go.jp/policy/budget/reference/statistics/"
TABLES = [("budget", "05.xlsx", "budgeted"), ("settlement", "06.xlsx", "settled")]

# Every body the two tables name, in the order they are first printed, with
# the code that identifies it for good. Names are the ministry's own English
# style where it has one.
MINISTRIES = [
    ("皇室費", "imperial-household", "Imperial Household"),
    ("国会", "diet", "The Diet"),
    ("裁判所", "courts", "The Courts"),
    ("会計検査院", "board-of-audit", "Board of Audit"),
    ("内閣", "cabinet", "Cabinet"),
    ("内閣府", "cabinet-office", "Cabinet Office"),
    ("総理庁", "prime-ministers-agency", "Prime Minister's Agency"),
    ("総理府", "prime-ministers-office", "Prime Minister's Office"),
    ("デジタル庁", "digital-agency", "Digital Agency"),
    ("復興庁", "reconstruction-agency", "Reconstruction Agency"),
    ("防災庁", "disaster-management-agency", "Disaster Management Agency"),
    ("経済安定本部", "economic-stabilisation-board", "Economic Stabilisation Board"),
    ("司法省", "justice-ministry-prewar", "Ministry of Justice (to 1948)"),
    ("法務庁", "attorney-generals-office", "Attorney-General's Office"),
    ("法務府", "attorney-generals-office-1949", "Attorney-General's Office (1949-52)"),
    ("法務省", "justice", "Ministry of Justice"),
    ("外務省", "foreign-affairs", "Ministry of Foreign Affairs"),
    ("大東亜省", "greater-east-asia", "Ministry of Greater East Asia"),
    ("拓務省", "colonial-affairs", "Ministry of Colonial Affairs"),
    ("大蔵省", "finance-okurasho", "Ministry of Finance (大蔵省, to 2000)"),
    ("財務省", "finance", "Ministry of Finance"),
    ("内務省", "home-affairs-prewar", "Ministry of Home Affairs (to 1947)"),
    ("自治省", "home-affairs", "Ministry of Home Affairs (自治省, 1960-2000)"),
    ("総務省", "internal-affairs", "Ministry of Internal Affairs and Communications"),
    ("文部省", "education-monbusho", "Ministry of Education (文部省, to 2000)"),
    ("文部科学省", "education",
     "Ministry of Education, Culture, Sports, Science and Technology"),
    ("厚生省", "health-and-welfare", "Ministry of Health and Welfare"),
    ("労働省", "labour", "Ministry of Labour"),
    ("厚生労働省", "health-labour-and-welfare", "Ministry of Health, Labour and Welfare"),
    ("農商務省", "agriculture-and-commerce", "Ministry of Agriculture and Commerce"),
    ("農商省", "agriculture-and-commerce-wartime",
     "Ministry of Agriculture and Commerce (wartime)"),
    ("農林省", "agriculture-and-forestry", "Ministry of Agriculture and Forestry"),
    ("農林水産省", "agriculture-forestry-and-fisheries",
     "Ministry of Agriculture, Forestry and Fisheries"),
    ("商工省", "commerce-and-industry", "Ministry of Commerce and Industry"),
    ("軍需省", "munitions", "Ministry of Munitions"),
    ("通商産業省", "miti", "Ministry of International Trade and Industry"),
    ("経済産業省", "economy-trade-and-industry", "Ministry of Economy, Trade and Industry"),
    ("逓信省", "communications-prewar", "Ministry of Communications"),
    ("電気通信省", "telecommunications", "Ministry of Telecommunications"),
    ("郵政省", "posts-and-telecommunications", "Ministry of Posts and Telecommunications"),
    ("運輸通信省", "transport-and-communications", "Ministry of Transport and Communications"),
    ("運輸省", "transport", "Ministry of Transport"),
    ("建設省", "construction", "Ministry of Construction"),
    ("国土交通省", "land-infrastructure-and-transport",
     "Ministry of Land, Infrastructure, Transport and Tourism"),
    ("環境省", "environment", "Ministry of the Environment"),
    ("陸軍省", "army", "Ministry of the Army"),
    ("海軍省", "navy", "Ministry of the Navy"),
    ("第一復員省", "first-demobilisation", "First Demobilisation Ministry"),
    ("第二復員省", "second-demobilisation", "Second Demobilisation Ministry"),
    ("防衛省", "defence", "Ministry of Defense"),
    ("合計", "total", "Total expenditure"),
]
MINISTRY_CODE = dict((jp_era.normalize(ja), code) for ja, code, _en in MINISTRIES)
MINISTRY_NAME = dict((code, en) for _ja, code, en in MINISTRIES)
MINISTRY_JA = dict((code, ja) for ja, code, _en in MINISTRIES)
MINISTRY_ORDER = dict((code, i) for i, (_ja, code, _en) in enumerate(MINISTRIES))

_UNIT_TO_MILLION = {"円": 1e-6, "千円": 1e-3, "百万円": 1.0, "億円": 100.0, "兆円": 1e6}
_UNIT_CELL = re.compile(r"単位[：:]\s*([^）)、,\s]+)")
_MISSING = ("", "-", "‐", "－", "―", "ー", "…", "***", "×", "x", "X")
_SKIP = {"所管", "年度", "年度所管"}

FIRST_BUDGET_YEAR = 1893
MIN_YEARS = 100
# Every body is rounded to the nearest ¥1,000 and there are up to twenty of
# them, so the printed 合計 and the sum of the printed parts differ by
# thousandths of a ¥ million.
SUM_TOLERANCE = 1.0

# Two of the 259 year-and-measure pairs in the two tables do not add up in the
# Ministry's own file: the fiscal 1977 budget by ¥8mn and the fiscal 1978
# settlement by ¥91mn, on bases of ¥29tn and ¥34tn — transcription slips of
# three parts in ten million and three in a hundred thousand. They are pinned
# as ceilings, so every other year stays exact and a correction still passes,
# and the figures are published exactly as printed.
TOLERATED_RESIDUAL = {("budget", 1977): 10.0, ("settlement", 1978): 100.0}

DATASET = {
    "slug": "fiscal-jp-ministry",
    "title": "General Account Spending by Ministry (Japan)",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "annual",
    "description": (
        "Japan's general account split by the ministry that spends it, in ¥ "
        "million — budget by fiscal year from 1893 and settlement from the "
        "Meiji period. Every body is published under the name it had, so the "
        "2001 reorganisation reads as series ending and series beginning "
        "rather than a continuous line across a discontinuity. Early years "
        "are sampled by the source and the gaps are left as gaps."
    ),
}

SOURCE = {
    "source_id": "mof:fiscal-stats-05-06",
    "name": "MOF — Fiscal Statistics, Tables 5 and 6 (general account expenditure by ministry)",
    "name_ja": "財務省 財政統計 第5表・第6表 一般会計歳出所管別予算・決算",
    "url": "https://www.mof.go.jp/policy/budget/reference/statistics/data.htm",
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Finance."
    ),
}

DOWNLOAD_URL = BASE + "05.xlsx and 06.xlsx"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": "Source: Ministry of Finance — Fiscal Statistics (財政統計), Tables 5 and 6.",
    "stale_after_days": 500,
    "main_series": [
        {"role": "headline", "code": "total.settlement",
         "label": "Total, settled", "slot": 1},
        {"role": "mhlw", "code": "health-labour-and-welfare.settlement",
         "label": "Health, Labour and Welfare", "slot": 2},
        {"role": "mof", "code": "finance.settlement", "label": "Finance", "slot": 3},
        {"role": "mlit", "code": "land-infrastructure-and-transport.settlement",
         "label": "Land and Transport", "slot": 4},
    ],
    "overview_tiles": [
        {"key": "total", "type": "level", "code": "total.budget",
         "label": "Total Spending"},
        {"key": "mhlw", "type": "level", "code": "health-labour-and-welfare.budget",
         "label": "Health and Welfare"},
        {"key": "mof", "type": "level", "code": "finance.budget",
         "label": "Finance"},
        {"key": "defence", "type": "level", "code": "defence.budget",
         "label": "Defense"},
    ],
    "kinds": dict(
        ("%s.%s" % (code, measure), "level")
        for _ja, code, _en in MINISTRIES
        for measure, _n, _d in TABLES),
}


# --- fetching ---------------------------------------------------------------

def fetch():
    envelope = {}
    for measure, name, _desc in TABLES:
        url = BASE + name
        envelope[measure] = {"url": url,
                             "b64": base64.b64encode(boj_ts.fetch_bytes(url)).decode("ascii")}
    return json.dumps({"tables": envelope}, sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _text(rows, row, col):
    cell = rows.get(row, {}).get(col)
    return (cell[0] if cell else "") or ""


def _value(text):
    text = jp_era.normalize(text).replace(",", "").replace("△", "-")
    if text in _MISSING:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _unit_multiplier(rows, sheet):
    for row in sorted(rows)[:8]:
        for cell in rows[row].values():
            found = _UNIT_CELL.search(jp_era.normalize((cell[0] or "").split("\n")[0]))
            if found:
                if found.group(1) not in _UNIT_TO_MILLION:
                    raise ValidationError(
                        "sheet %r is published in %r" % (sheet, found.group(1)))
                return _UNIT_TO_MILLION[found.group(1)]
    raise ValidationError("sheet %r carries no 単位 cell" % sheet)


def _header_years(rows, row, sheet):
    """{column: fiscal year} for one header row, or {} if it is not one.

    Eras carry left to right: 「令和元年度」 followed by a bare 「2」 is 2019
    then 2020. The pre-1875 accounting periods resolve to nothing and are
    simply absent, which is how they stay out of an annual series.
    """
    era, found = None, {}
    for col in sorted(rows[row], key=lambda c: (len(c), c)):
        label = _text(rows, row, col)
        seen = jp_era.era_of(label)
        if seen:
            era = seen
        year = jp_era.fiscal_year(label, era)
        if year is not None:
            found[col] = jp_era.check(year, "%s %s" % (sheet, label))
    if len(found) < 2:
        return {}
    ordered = [found[col] for col in sorted(found, key=lambda c: (len(c), c))]
    if ordered != sorted(ordered):
        raise ValidationError(
            "sheet %r row %d reads years %s left to right, which is not "
            "ascending — an era carried wrong" % (sheet, row, ordered))
    return found


def _blocks(rows, sheet):
    """[(header row, {column: year}, last row of the block)].

    A sheet is not one table: the Meiji and Taisho sheets stack two or three
    blocks of five years each down the page, every one with its own header and
    its own copy of the ministry list. Reading a sheet as a single grid found
    皇室費 twice and stopped, which is how the stacking was noticed.
    """
    ordered = sorted(rows)
    headers = [(row, _header_years(rows, row, sheet)) for row in ordered]
    headers = [(row, years) for row, years in headers if years]
    if not headers:
        raise ValidationError(
            "sheet %r has no header row with fiscal years across it" % sheet)
    out = []
    for index, (row, years) in enumerate(headers):
        end = headers[index + 1][0] if index + 1 < len(headers) else ordered[-1] + 1
        out.append((row, years, end))
    return out


def _read_sheet(rows, sheet):
    """One sheet -> {(ministry code, fiscal year): value in ¥ million}."""
    multiplier = _unit_multiplier(rows, sheet)
    out, saw_total = {}, False
    for header_row, columns, end in _blocks(rows, sheet):
        seen_codes = set()
        for row in sorted(rows):
            if not header_row < row < end:
                continue
            label = None
            for col in ("B", "A", "C"):
                text = jp_era.normalize(_text(rows, row, col))
                if text:
                    label = text
                    break
            if not label or label in _SKIP or label.startswith("（") \
                    or "/" in label or len(label) > 14:
                continue
            if label not in MINISTRY_CODE:
                raise ValidationError(
                    "sheet %r row %d names %r, which is not a body this adapter "
                    "knows. Give it a code and an English name before "
                    "publishing it." % (sheet, row, label))
            code = MINISTRY_CODE[label]
            found = dict((year, _value(_text(rows, row, col)))
                         for col, year in columns.items())
            found = dict((year, value) for year, value in found.items()
                         if value is not None)
            if not found:
                # The Ministry leaves a blank copy of the ministry list under
                # the filled one, ready for the next five years. An empty row
                # is that template, not a second reading of the same body.
                continue
            if code in seen_codes:
                raise ValidationError(
                    "sheet %r names %s twice with figures inside the block "
                    "starting at row %d" % (sheet, code, header_row))
            seen_codes.add(code)
            for year, value in found.items():
                out[(code, year)] = value * multiplier
        saw_total = saw_total or "total" in seen_codes
    if not saw_total:
        raise ValidationError("sheet %r has no 合計 row" % sheet)
    return out


def _read_table(raw, table):
    merged = {}
    for sheet, rows in xlsx.sheets(raw).items():
        for key, value in _read_sheet(rows, sheet).items():
            if key in merged and merged[key] != value:
                raise ValidationError(
                    "%s publishes %s fiscal %d twice with different values "
                    "(%s, %s)" % (table, key[0], key[1], merged[key], value))
            merged[key] = value
    if not merged:
        raise ValidationError("%s yielded nothing" % table)
    return merged


def parse(raw):
    tables = json.loads(raw.decode("utf-8"))["tables"]
    meta, observations = {}, []
    for measure, name, desc in TABLES:
        if measure not in tables:
            raise ValidationError("the envelope has no %r table" % measure)
        found = _read_table(base64.b64decode(tables[measure]["b64"]), name)
        for (code, year), value in sorted(found.items()):
            series_code = "%s.%s" % (code, measure)
            meta.setdefault(series_code, {
                "code": series_code,
                "name_en": "%s — %s" % (MINISTRY_NAME[code], desc),
                "name_ja": MINISTRY_JA[code], "unit": "jpy_million",
                "weight_per_10000": None,
                "sort_order": MINISTRY_ORDER[code] * 10 + (0 if measure == "budget" else 1),
            })
            observations.append({"code": series_code, "period": jp_era.period(year),
                                 "value": value})
    return [meta[code] for code in sorted(meta)], observations


# --- validation -------------------------------------------------------------

def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for required in ("total.settlement", "total.budget", "finance.settlement",
                     "health-labour-and-welfare.settlement", "defence.settlement"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    checked, worst = 0, 0.0
    for measure in ("budget", "settlement"):
        total = by_code["total." + measure]
        periods = sorted(total)
        if len(periods) < MIN_YEARS:
            raise ValidationError(
                "only %d %s years; the tables carry at least %d"
                % (len(periods), measure, MIN_YEARS))
        parts = [code for _ja, code, _en in MINISTRIES if code != "total"]
        for period, published in sorted(total.items()):
            component = sum(by_code.get("%s.%s" % (code, measure), {}).get(period, 0.0)
                            for code in parts)
            gap = abs(component - published)
            worst = max(worst, gap)
            allowed = max(SUM_TOLERANCE,
                          TOLERATED_RESIDUAL.get((measure, period.year), 0.0))
            if gap > allowed:
                raise ValidationError(
                    "fiscal %d %s: the ministries sum to %s but the printed 合計 "
                    "is %s — a body is being missed or double-counted"
                    % (period.year, measure, component, published))
            checked += 1

    budget_years = sorted(by_code["total.budget"])
    if budget_years[0].year != FIRST_BUDGET_YEAR:
        raise ValidationError(
            "the budget table starts at fiscal %d, not %d — an era was read wrong"
            % (budget_years[0].year, FIRST_BUDGET_YEAR))

    for code, points in by_code.items():
        for period, value in points.items():
            if value < 0:
                raise ValidationError(
                    "%s fiscal %d is negative (%s)" % (code, period.year, value))

    latest = max(o["period"] for o in observations)
    return {
        "series": len(codes),
        "observations": len(observations),
        "first_period": str(min(o["period"] for o in observations)),
        "latest_period": str(latest),
        "settled_years": len(by_code["total.settlement"]),
        "budget_years": len(budget_years),
        "totals_reconciled": checked,
        "worst_total_gap": worst,
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "fiscal",
    "name": {"en": "General account spending by ministry", "ja": "一般会計歳出所管別予算・決算"},
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
        "as_of_supported": True, "history_from": "1877",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published amount, ¥ million", "unit": "JPY_million",
         "trust": "official"},
        {"id": "yoy", "label": "Change on the previous fiscal year", "unit": "%", "trust": "derived",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search"],
    "cite": "/fiscal.html?dataset=fiscal-jp-ministry",
    "page": "/fiscal.html",
    "notes": [
        "Series codes are {body}.{budget|settlement}. Every body is published under the name it had, so 大蔵省 and 財務省 are two series, as are 厚生省, 労働省 and 厚生労働省. The 2001 reorganisation split and merged ministries rather than renaming them, and splicing the series would draw a continuous line across a discontinuity.",
        "The Meiji and Taisho sheets print every fifth year rather than every year, so the series genuinely has gaps before the 1920s. They are left as gaps and never interpolated.",
        "The war ministries are here because the budget had them: 陸軍省 and 海軍省 to 1945, 軍需省, 大東亜省 and the two demobilisation ministries. The extraordinary war accounts (臨時軍事費特別会計) were a separate account and are not in the general account at all.",
        "Two of the 259 year-and-measure pairs do not add up in the Ministry's own file — the fiscal 1977 budget by ¥8mn and the fiscal 1978 settlement by ¥91mn. Both are published as printed.",
    ],
}
