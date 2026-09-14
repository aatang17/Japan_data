"""Adapter: the general account — MOF 財政統計 第1表.

Source: 財務省, 財政統計 第1表「明治初年度以降一般会計歳入歳出予算決算」 — the
central government's general account (一般会計), budget and settlement, revenue
and expenditure, one row per fiscal year since 明治8年度 (1875).

**Why this table and not the budget press pack.** The Ministry publishes the
coming year's budget every December in slide decks, and the settled accounts
every November in a different one. This table is the only place both live on
one axis, back to the Meiji period, in a machine-readable file. Four series,
a hundred and fifty years.

**Four numbers per year, and the difference between them is the point.**
予算額 is what the Diet voted — the initial budget plus every supplementary
passed during the year. 決算額 is what was actually collected and actually
spent. Japan under-spends its budget every year and over-collects revenue in
most, so the gap between the two is a real signal and the two are never mixed
into one series.

**Five sheets, three units, and the unit is read from the sheet.** 明治・大正
and 昭和元〜21 are published in 円; 昭和22年度 onward in 千円. Everything is
normalised to ¥ million so the series is one series — the only rescaling this
adapter does, and it is forced: a series that silently changes unit in 1947 is
worse than useless. The multiplier comes from the sheet's own 「（単位：〜）」
cell, never from the sheet's position, so a Ministry re-issue that changes the
unit fails loudly instead of moving every number by a thousand.

**Only the 計 row is a year.** From 昭和元年度 the sheets break each fiscal year
into the rows the Diet actually passed — 本予算, 暫定予算, and a numbered
補正予算 per session — and only the 計 row underneath them is the year's total.
Summing the component rows here would double-count, because 計 already is the
sum and the supplementary rows carry net increases that can be negative.

**The eight pre-1875 accounting periods are excluded.** 明治第1期 to 第8期 run
from four to fifteen months each (the first covers December 1867 to December
1868), so they are not fiscal years and cannot sit on an annual axis. They are
in the source file; they are deliberately not in this dataset.

**A fiscal year is dated to 1 April, which before 1886 is a convention.** The
Meiji fiscal year began in October and then in July; only from 明治19年度 does
it begin in April. Dating every year to its April keeps the axis comparable
with every other Japanese series on the platform, and the Methodology page
says so rather than the data pretending the calendar never moved.
"""
import base64
import datetime
import json
import re

from . import boj_ts, jp_era, xlsx


class ValidationError(Exception):
    pass


TABLE_URL = "https://www.mof.go.jp/policy/budget/reference/statistics/01.xlsx"

# The four columns, per sheet layout. Sheet 1 carries the era in column A and
# the year in column B, so its data starts one column further right.
_COLUMNS_WIDE = {"D": "revenue.budget", "E": "revenue.settlement",
                 "F": "expenditure.budget", "G": "expenditure.settlement"}
_COLUMNS_NARROW = {"C": "revenue.budget", "D": "revenue.settlement",
                   "E": "expenditure.budget", "F": "expenditure.settlement"}

MEASURES = [
    ("revenue.budget", "General account revenue — budget", "一般会計歳入 予算額"),
    ("revenue.settlement", "General account revenue — settlement", "一般会計歳入 決算額"),
    ("expenditure.budget", "General account expenditure — budget", "一般会計歳出 予算額"),
    ("expenditure.settlement", "General account expenditure — settlement",
     "一般会計歳出 決算額"),
]
MEASURE_ORDER = dict((code, i) for i, (code, _e, _j) in enumerate(MEASURES))

# Published unit -> multiplier onto ¥ million. Read from the sheet, never
# assumed: see the module docstring.
_UNIT_TO_MILLION = {"円": 1e-6, "千円": 1e-3, "百万円": 1.0, "億円": 100.0,
                    "兆円": 1e6}
_UNIT_CELL = re.compile(r"単位[：:]\s*([^）)\s]+)")
_TOTAL_ROW = "計"
_MISSING = ("", "-", "‐", "－", "―", "ー", "…", "･･･", "***", "×", "x", "X")

# The first fiscal year that is a year rather than an accounting period, and
# the count of years the file must still carry. 1875 through the budget year
# is about 152; a file that lost a fifth of its history is a broken download,
# not a revision.
FIRST_YEAR = 1875
MIN_YEARS = 140
# Year-on-year ratio that can only be a unit change; see validate().
UNIT_JUMP = 20

DATASET = {
    "slug": "fiscal-jp",
    "title": "General Account — Budget and Settlement (Japan)",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "annual",
    "description": (
        "Japan's central government general account by fiscal year since 1875 "
        "— revenue and expenditure, each as the Diet budgeted it (the initial "
        "budget plus every supplementary) and as it was finally settled, in ¥ "
        "million. The gap between budget and settlement is carried as four "
        "separate series and never netted. Fiscal years are dated to the 1 "
        "April they begin on."
    ),
}

SOURCE = {
    "source_id": "mof:fiscal-stats-01",
    "name": "MOF — Fiscal Statistics, Table 1 (general account budget and settlement)",
    "name_ja": "財務省 財政統計 第1表 明治初年度以降一般会計歳入歳出予算決算",
    "url": "https://www.mof.go.jp/policy/budget/reference/statistics/data.htm",
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Finance."
    ),
}

DOWNLOAD_URL = TABLE_URL
RAW_SUFFIX = ".xlsx"

PRESENTATION = {
    "credit_line": "Source: Ministry of Finance — Fiscal Statistics (財政統計), Table 1.",
    # The file gains the coming fiscal year when its budget passes, in the
    # spring, and gains that year's settlement about twenty months later. The
    # newest period is therefore up to about a year old the day before the
    # next budget lands; this allows that plus four months.
    "stale_after_days": 500,
    "main_series": [
        {"role": "headline", "code": "expenditure.settlement",
         "label": "Expenditure, settled", "slot": 1},
        {"role": "revenue", "code": "revenue.settlement",
         "label": "Revenue, settled", "slot": 2},
        {"role": "budget", "code": "expenditure.budget",
         "label": "Expenditure, budgeted", "slot": 3},
    ],
    "overview_tiles": [
        {"key": "spend", "type": "level", "code": "expenditure.budget",
         "label": "Expenditure (Budgeted)"},
        {"key": "revenue", "type": "level", "code": "revenue.budget",
         "label": "Revenue (Budgeted)"},
        {"key": "spend-settled", "type": "level", "code": "expenditure.settlement",
         "label": "Expenditure (Settled)"},
        {"key": "revenue-settled", "type": "level", "code": "revenue.settlement",
         "label": "Revenue (Settled)"},
    ],
    "kinds": dict((code, "level") for code, _e, _j in MEASURES),
}


# --- fetching ---------------------------------------------------------------

def fetch():
    return boj_ts.fetch_bytes(TABLE_URL)


# --- parsing ----------------------------------------------------------------

def _text(rows, row, col):
    cell = rows.get(row, {}).get(col)
    return (cell[0] if cell else "") or ""


def _value(text):
    """A published cell -> a number, or None. Blank and dashes are missing."""
    text = jp_era.normalize(text).replace(",", "").replace("△", "-")
    if text in _MISSING:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _unit_multiplier(rows, sheet):
    """The sheet's own 「（単位：〜）」, as a multiplier onto ¥ million."""
    for row in sorted(rows)[:12]:
        for text in (cell[0] or "" for cell in rows[row].values()):
            found = _UNIT_CELL.search(jp_era.normalize(text))
            if not found:
                continue
            unit = found.group(1)
            if unit not in _UNIT_TO_MILLION:
                raise ValidationError(
                    "sheet %r is published in %r, which this adapter has no "
                    "multiplier for" % (sheet, unit))
            return _UNIT_TO_MILLION[unit]
    raise ValidationError(
        "sheet %r carries no 単位 cell — the unit would have to be guessed, "
        "and guessing it wrong moves every number by a factor of a thousand"
        % sheet)


def _year_rows(rows, year_col, era_col):
    """[(fiscal year, first row)] in sheet order, era headings resolved.

    The Ministry writes the era once — sometimes in the cell above the first
    year, sometimes in the column beside it — and then bare numbers down the
    rows beneath it, so both columns are watched and the era carries forward.
    """
    found, era = [], None
    for row in sorted(rows):
        for col in (era_col, year_col):
            if col is None:
                continue
            seen = jp_era.era_of(_text(rows, row, col))
            if seen:
                era = seen
        year = jp_era.fiscal_year(_text(rows, row, year_col), era)
        if year is not None:
            found.append((jp_era.check(year, _text(rows, row, year_col)), row))
    return found


def _read_flat_sheet(rows, columns, year_col, era_col):
    """A sheet with one row per fiscal year — the Meiji and Taisho sheet."""
    out = {}
    for year, row in _year_rows(rows, year_col, era_col):
        values = dict((measure, _value(_text(rows, row, col)))
                      for col, measure in columns.items())
        if all(v is None for v in values.values()):
            continue
        if year in out:
            raise ValidationError("fiscal %d appears on two rows of one sheet" % year)
        out[year] = values
    return out


def _read_block_sheet(rows, sheet):
    """A sheet that breaks each fiscal year into the votes the Diet passed.

    The year's totals are the 計 row underneath them — the component rows are
    net changes that can be negative, so summing them would be wrong as well
    as unnecessary.

    **The settlement columns are read from the whole block, not from the 計
    row.** In the 平成 sheet the two settlement figures for fiscal 2005 are
    typed one row above their 計 row, against the last supplementary instead.
    Nothing marks it; reading only the 計 row drops the year silently, which
    is how it was found. A settlement figure appears exactly once per year
    wherever it is typed, so the block is scanned for it and two of them in
    one block stops the ingest rather than picking one.
    """
    ordered = _year_rows(rows, year_col="A", era_col="A")
    out = {}
    for index, (year, start) in enumerate(ordered):
        end = ordered[index + 1][1] if index + 1 < len(ordered) else max(rows) + 1
        block = [row for row in sorted(rows) if start <= row < end]
        totals = [row for row in block
                  if jp_era.normalize(_text(rows, row, "B")) == _TOTAL_ROW]
        if not totals:
            continue
        if len(totals) > 1:
            raise ValidationError(
                "sheet %r: fiscal %d has %d 計 rows; a fiscal year has one total"
                % (sheet, year, len(totals)))
        values = {}
        for col, measure in _COLUMNS_NARROW.items():
            if measure.endswith(".budget"):
                values[measure] = _value(_text(rows, totals[0], col))
                continue
            seen = [(row, _value(_text(rows, row, col))) for row in block]
            seen = [(row, value) for row, value in seen if value is not None]
            if len(seen) > 1:
                raise ValidationError(
                    "sheet %r: fiscal %d carries %d values for %s (rows %s) — "
                    "a settled figure is published once"
                    % (sheet, year, len(seen), measure,
                       ", ".join(str(row) for row, _v in seen)))
            values[measure] = seen[0][1] if seen else None
        if all(v is None for v in values.values()):
            continue
        if year in out:
            raise ValidationError("fiscal %d appears twice on sheet %r" % (year, sheet))
        out[year] = values
    return out


def parse(raw):
    sheets = xlsx.sheets(raw)
    if not sheets:
        raise ValidationError("the workbook has no sheets")

    by_year = {}
    for index, (sheet, rows) in enumerate(sheets.items()):
        multiplier = _unit_multiplier(rows, sheet)
        # The first sheet lists one row per year with the era in column A and
        # the year in column B; every later sheet puts the year in column A
        # and breaks the year into Diet votes, of which only 計 is the total.
        if index == 0:
            found = _read_flat_sheet(rows, _COLUMNS_WIDE, year_col="B", era_col="A")
        else:
            found = _read_block_sheet(rows, sheet)
        for year, values in found.items():
            if year < FIRST_YEAR:
                continue
            if year in by_year:
                raise ValidationError(
                    "fiscal %d is published on two sheets (%s and an earlier "
                    "one) — the sheets are meant to cover disjoint spans"
                    % (year, sheet))
            by_year[year] = dict(
                (measure, None if value is None else value * multiplier)
                for measure, value in values.items())

    series = [{"code": code, "name_en": name_en, "name_ja": name_ja,
               "unit": "jpy_million", "weight_per_10000": None,
               "sort_order": MEASURE_ORDER[code]}
              for code, name_en, name_ja in MEASURES]
    observations = []
    for year in sorted(by_year):
        period = jp_era.period(year)
        for code, value in sorted(by_year[year].items()):
            if value is not None:
                observations.append({"code": code, "period": period, "value": value})
    return series, observations


# --- validation -------------------------------------------------------------

def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for code, _en, _ja in MEASURES:
        if code not in codes:
            raise ValidationError("the %r series is missing" % code)

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    settled = by_code["expenditure.settlement"]
    years = sorted(settled)
    if len(years) < MIN_YEARS:
        raise ValidationError(
            "only %d settled years; the file has always carried at least %d"
            % (len(years), MIN_YEARS))
    if years[0].year != FIRST_YEAR:
        raise ValidationError(
            "settled expenditure starts at fiscal %d, not %d — the era of the "
            "first row was read wrong" % (years[0].year, FIRST_YEAR))
    for earlier, later in zip(years, years[1:]):
        if later.year - earlier.year != 1:
            raise ValidationError(
                "no settled expenditure between fiscal %d and %d — a year was "
                "dropped" % (earlier.year, later.year))

    # Every figure here is a gross total of an account that cannot run
    # backwards: a negative one means a supplementary row was read as a year.
    for code, points in by_code.items():
        for period, value in points.items():
            if value <= 0:
                raise ValidationError(
                    "%s fiscal %d is %s — a general-account total is never zero "
                    "or negative" % (code, period.year, value))

    # The unit check that catches a mis-read 単位 cell. A unit slip moves a
    # year by exactly 1,000; the largest real move in a hundred and fifty
    # years is the 5.4x of fiscal 1946, when post-war inflation took settled
    # spending from ¥21bn to ¥115bn. Twenty is clear of the one and nowhere
    # near the other.
    for code, points in sorted(by_code.items()):
        ordered = sorted(points)
        for earlier, later in zip(ordered, ordered[1:]):
            if later.year - earlier.year != 1:
                continue
            before, after = points[earlier], points[later]
            if after > before * UNIT_JUMP or before > after * UNIT_JUMP:
                raise ValidationError(
                    "%s jumps from %s to %s between fiscal %d and %d — that is "
                    "a unit change being read as a number"
                    % (code, before, after, earlier.year, later.year))

    latest = max(o["period"] for o in observations)
    return {
        "series": len(codes),
        "observations": len(observations),
        "first_period": str(min(o["period"] for o in observations)),
        "latest_period": str(latest),
        "fiscal_years": len(years),
        "settled_expenditure_latest": settled[max(settled)],
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "fiscal",
    "name": {"en": "General account — budget and settlement", "ja": "一般会計歳入歳出予算決算"},
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
        "as_of_supported": True, "history_from": "1875",
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
    "cite": "/fiscal.html?dataset=fiscal-jp",
    "page": "/fiscal.html",
    "notes": [
        "Series codes are {revenue|expenditure}.{budget|settlement}. 予算額 is the initial budget plus every supplementary the Diet passed; 決算額 is what was collected and spent. They are four series and are never netted into one.",
        "Published in 円 for 1875-1946 and 千円 from 1947, and normalised here to ¥ million so the series does not change unit mid-run. The multiplier is read from each sheet's own 単位 cell, never assumed.",
        "A fiscal year is dated to the 1 April it begins on. Before 明治19年度 (1886) the Japanese fiscal year began in October and then in July, so that dating is a platform convention for those years rather than a fact.",
        "The eight pre-1875 accounting periods (明治第1期 to 第8期) run from four to fifteen months and are not fiscal years. They are in the source file and deliberately not in this dataset.",
        "The settlement series ends about two fiscal years before the budget series: a year's accounts close roughly twenty months after it starts.",
    ],
}
