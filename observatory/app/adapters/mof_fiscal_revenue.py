"""Adapter: general-account revenue by head — MOF 財政統計 第3表 and 第4表.

Source: 財務省, 財政統計 第3表「昭和57年度以降一般会計歳入主要科目別予算」 and
第4表「…決算」 — where the general account's money comes from, split into the
heads the Ministry itself uses, budget and settlement side by side from fiscal
1982.

**The head that matters is 公債金.** Bond issuance is booked as *revenue* in
Japan's general account, alongside tax. That is not an accounting curiosity: it
is why the headline "revenue" figure and the tax take differ by tens of
trillions of yen, and why a chart of "government revenue" that does not separate
borrowing from tax is misleading. Every head is a separate series here and
nothing is netted, so borrowing is always visible as its own line.

**Two tables, one dataset, never one series.** 第3表 is what was budgeted and
第4表 is what came in; they have the same eleven columns and are read by the
same code, and every head therefore exists twice — `.budget` and `.settlement`.
The budget table runs a further two fiscal years ahead of the settlement table,
because a year's accounts close about twenty months after it starts.

**Dead heads stay.** 専売納付金 — the payments from the tobacco and alcohol
monopolies — stopped when Japan Tobacco was privatised in 1985 and the Ministry
now prints a dash. A dash is missing, not zero, so the series simply ends; it is
not back-filled with zeroes and not removed, because a reader looking at 1983
should still find it.

**Two revenue heads exist only in a footnote, and they are ingested from it.**
The Ministry's 合計 includes bonds that have no column: the 臨時特別公債 that
paid Japan's contribution to the 1991 Gulf War, the 減税特例公債 that covered
the tax cut before consumption tax went from 3% to 5%, the 復興債 of fiscal
2011, and the 年金特例公債 that funded half the basic pension. Table 4 also
carries receipts from the 決算調整資金 in five years. Together they are why the
eleven printed heads fail to add to the printed total in thirteen of the
forty-four years. Both are parsed out of the note text and published as their
own series, so every year reconciles and the residual is named rather than
hidden — ¥11.55tn of reconstruction borrowing is not a rounding difference.

**The column headers are checked, not trusted to position.** Both tables put the
head names across two merged header rows. Those names are re-read on every
ingest and compared with the eleven this adapter knows; a Ministry re-ordering
stops the ingest instead of quietly relabelling every number in the table.
"""
import base64
import json
import re

from . import boj_ts, jp_era, xlsx


class ValidationError(Exception):
    pass


BASE = "https://www.mof.go.jp/policy/budget/reference/statistics/"
TABLES = [("budget", "03.xlsx", "budgeted"), ("settlement", "04.xlsx", "settled")]

# column -> (code, English name, the header text that must be above it)
HEADS = [
    ("E", "tax", "Tax", "租税"),
    ("F", "stamp-revenue", "Stamp revenue", "印紙収入"),
    ("G", "tax-and-stamp", "Tax and stamp revenue", "計"),
    ("H", "monopoly.tobacco", "Monopoly payments — Japan Tobacco and Salt Corporation",
     "日本専売公社納付金"),
    ("I", "monopoly.alcohol", "Monopoly payments — alcohol monopoly special account",
     "アルコール専売事業特別会計納付金"),
    ("J", "monopoly", "Monopoly payments", "計"),
    ("K", "government-enterprise", "Government enterprise profits and revenue",
     "官業益金及官業収入"),
    ("L", "asset-disposal", "Government asset disposal revenue", "政府資産整理収入"),
    ("M", "miscellaneous", "Miscellaneous revenue", "雑収入"),
    ("N", "bond-issuance", "Bond issuance (borrowing)", "公債金"),
    ("O", "prior-year-surplus", "Surplus carried in from the prior year",
     "前年度剰余金受入"),
    ("P", "total", "Total revenue", "合計"),
]
# Heads the Ministry publishes only in the footnote under the table. They
# have no column; their amounts are parsed out of the note text.
FOOTNOTE_HEADS = [
    ("bridge-bonds", "Bridge bonds (Gulf War, tax-cut, reconstruction and pension)",
     "つなぎ公債"),
    ("settlement-adjustment-fund", "Receipts from the settlement adjustment fund",
     "決算調整資金受入"),
]
HEAD_ORDER = dict((code, i) for i, (_c, code, _e, _j) in enumerate(HEADS))
HEAD_ORDER.update((code, len(HEADS) + i)
                  for i, (code, _e, _j) in enumerate(FOOTNOTE_HEADS))
# What the Ministry's own 合計 is made of. 租税 and 印紙収入 are inside
# tax-and-stamp, and the two monopoly lines inside monopoly, so neither is
# counted twice.
TOTAL_PARTS = ("tax-and-stamp", "monopoly", "government-enterprise",
               "asset-disposal", "miscellaneous", "bond-issuance",
               "prior-year-surplus", "bridge-bonds",
               "settlement-adjustment-fund")

# The one year the Ministry's own table does not add up. In the fiscal 2026
# budget column the eleven heads exceed the published 合計 by ¥732.5bn, with
# no footnote and no bridge bond to explain it; every other year in both
# tables reconciles to the yen once the footnote heads are in. It is pinned as
# a ceiling, not an expected value, so the check still passes the day the
# Ministry corrects the file — and a residual in any *other* year still stops
# the ingest, because this is a fact about one cell and not a licence.
TOLERATED_RESIDUAL = {("budget", 2026): 733_000.0}

_UNIT_TO_MILLION = {"円": 1e-6, "千円": 1e-3, "百万円": 1.0, "億円": 100.0, "兆円": 1e6}
_UNIT_CELL = re.compile(r"単位[：:]\s*([^）)、,\s]+)")
_MISSING = ("", "-", "‐", "－", "―", "ー", "…", "***", "×", "x", "X")

FIRST_YEAR = 1982
MIN_YEARS = 40
# Every head is published rounded to the nearest ¥ million, so eleven of them
# and the total disagree by a few. The smallest head that is ever non-zero,
# 官業益金及官業収入, is about ¥50bn, so a head read into the wrong column is
# three orders of magnitude outside this.
SUM_TOLERANCE = 50.0

DATASET = {
    "slug": "fiscal-jp-revenue",
    "title": "General Account Revenue by Head — Budget and Settlement (Japan)",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "annual",
    "description": (
        "Where Japan's general account gets its money, by fiscal year from "
        "1982, in ¥ million — tax and stamp revenue, bond issuance, asset "
        "disposals, miscellaneous revenue and the surplus carried in from the "
        "prior year — each as budgeted and as settled. Bond issuance is booked "
        "as revenue in Japan's general account and is carried as its own "
        "series, never merged with tax."
    ),
}

SOURCE = {
    "source_id": "mof:fiscal-stats-03-04",
    "name": "MOF — Fiscal Statistics, Tables 3 and 4 (general account revenue by head)",
    "name_ja": "財務省 財政統計 第3表・第4表 一般会計歳入主要科目別予算・決算",
    "url": "https://www.mof.go.jp/policy/budget/reference/statistics/data.htm",
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Finance."
    ),
}

DOWNLOAD_URL = BASE + "03.xlsx and 04.xlsx"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": "Source: Ministry of Finance — Fiscal Statistics (財政統計), Tables 3 and 4.",
    "stale_after_days": 500,
    "main_series": [
        {"role": "headline", "code": "total.settlement",
         "label": "Total revenue, settled", "slot": 1},
        {"role": "tax", "code": "tax-and-stamp.settlement",
         "label": "Tax and stamp revenue", "slot": 2},
        {"role": "bonds", "code": "bond-issuance.settlement",
         "label": "Bond issuance", "slot": 3},
        {"role": "misc", "code": "miscellaneous.settlement",
         "label": "Miscellaneous", "slot": 4},
    ],
    "overview_tiles": [
        {"key": "total", "type": "level", "code": "total.budget",
         "label": "Total Revenue"},
        {"key": "tax", "type": "level", "code": "tax-and-stamp.budget",
         "label": "Tax and Stamps"},
        {"key": "bonds", "type": "level", "code": "bond-issuance.budget",
         "label": "Bond Issuance"},
        {"key": "misc", "type": "level", "code": "miscellaneous.budget",
         "label": "Miscellaneous"},
    ],
    "kinds": dict(
        ("%s.%s" % (code, measure), "level")
        for code in ([c for _col, c, _e, _j in HEADS]
                     + [c for c, _e, _j in FOOTNOTE_HEADS])
        for measure, _n, _d in TABLES),
}


# --- fetching ---------------------------------------------------------------

def fetch():
    envelope = {}
    for measure, name, _desc in TABLES:
        envelope[measure] = {
            "url": BASE + name,
            "b64": base64.b64encode(boj_ts.fetch_bytes(BASE + name)).decode("ascii"),
        }
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


def _unit_multiplier(rows, table):
    for row in sorted(rows)[:8]:
        for cell in rows[row].values():
            found = _UNIT_CELL.search(jp_era.normalize(cell[0] or ""))
            if found:
                if found.group(1) not in _UNIT_TO_MILLION:
                    raise ValidationError(
                        "%s is published in %r, which has no multiplier here"
                        % (table, found.group(1)))
                return _UNIT_TO_MILLION[found.group(1)]
    raise ValidationError("%s carries no 単位 cell" % table)


def _first_data_row(rows):
    """The first row that carries a fiscal year, i.e. where the header stops."""
    era = None
    for row in sorted(rows):
        found = jp_era.era_of(_text(rows, row, "A"))
        if found:
            era = found
        if jp_era.fiscal_year(_text(rows, row, "B"), era) is not None:
            return row
    raise ValidationError("no row carries a fiscal year")


def _check_headers(rows, table):
    """Every head still sits under the name this adapter expects.

    The names live across two merged header rows — the group name on one, the
    sub-column on the other — so each column takes whichever of the two
    carries text. Only rows above the first data row are read: the first
    figure in column E is a number that would otherwise be taken for a header.
    """
    header_end = _first_data_row(rows)
    for col, _code, _en, expected in HEADS:
        seen = ""
        for row in sorted(rows):
            if row >= header_end:
                break
            text = jp_era.normalize(_text(rows, row, col))
            if text and "単位" not in text:
                seen = text
        if seen != expected:
            raise ValidationError(
                "%s column %s is headed %r, not %r — the heads have been "
                "re-ordered and matching them by column is no longer safe"
                % (table, col, seen, expected))


_ERA_NAMES = "明治|大正|昭和|平成|令和"
_NOTE_YEAR_AMOUNT = re.compile(r"(%s)(元|\d{1,2})年度[：:]([\d,]+)百万円" % _ERA_NAMES)
_NOTE_YEAR = re.compile(r"(%s)(元|\d{1,2})年度" % _ERA_NAMES)
_NOTE_AMOUNT = re.compile(r"([\d,]+)百万円")
_BRIDGE_MARKER = "つなぎ公債"
_FUND_MARKER = "決算調整資金"


def _note_text(rows):
    """The note block under the table, whitespace folded, or ''."""
    for row in sorted(rows, reverse=True):
        for cell in rows[row].values():
            text = jp_era.normalize(cell[0] or "")
            if _BRIDGE_MARKER in text:
                return text
    return ""


def _footnote_heads(rows, table):
    """{head code: {fiscal year: amount}} for the heads that have no column.

    The bridge bonds are written as 「平成23年度：11,550,000百万円」 — year and
    amount adjacent, so each pair is read directly. The settlement adjustment
    fund is written the other way round, every year first and then every
    amount in the same order, so the two lists are zipped and a length
    mismatch is fatal rather than silently truncated.
    """
    note = _note_text(rows)
    if not note:
        raise ValidationError(
            "%s has no note under the table; the heads the Ministry publishes "
            "only in the note would go missing and the year would not reconcile"
            % table)
    out = {"bridge-bonds": {}, "settlement-adjustment-fund": {}}
    bridge_at = note.index(_BRIDGE_MARKER)
    for era, digits, amount in _NOTE_YEAR_AMOUNT.findall(note[bridge_at:]):
        year = jp_era.fiscal_year(era + digits)
        if year is None:
            raise ValidationError("%s: unreadable year %r in the note" % (table, era + digits))
        out["bridge-bonds"][year] = float(amount.replace(",", ""))

    head = note[:bridge_at]
    if _FUND_MARKER in head:
        at = head.index(_FUND_MARKER)
        years = [jp_era.fiscal_year(era + digits)
                 for era, digits in _NOTE_YEAR.findall(head[:at])]
        amounts = [float(a.replace(",", "")) for a in _NOTE_AMOUNT.findall(head[at:])]
        if len(years) != len(amounts) or not years:
            raise ValidationError(
                "%s: the settlement-adjustment-fund note lists %d years and %d "
                "amounts" % (table, len(years), len(amounts)))
        out["settlement-adjustment-fund"] = dict(zip(years, amounts))
    return out


def _read_table(raw, table):
    """One workbook -> {fiscal year: {head code: value in ¥ million}}."""
    sheets = xlsx.sheets(raw)
    if not sheets:
        raise ValidationError("%s has no sheets" % table)
    rows = list(sheets.values())[0]
    multiplier = _unit_multiplier(rows, table)
    _check_headers(rows, table)

    out, era = {}, None
    for row in sorted(rows):
        found = jp_era.era_of(_text(rows, row, "A"))
        if found:
            era = found
        year = jp_era.fiscal_year(_text(rows, row, "B"), era)
        if year is None:
            continue
        year = jp_era.check(year, table)
        values = {}
        for col, code, _en, _ja in HEADS:
            value = _value(_text(rows, row, col))
            if value is not None:
                values[code] = value * multiplier
        if not values:
            continue
        if year in out:
            raise ValidationError("%s publishes fiscal %d twice" % (table, year))
        out[year] = values

    for code, amounts in sorted(_footnote_heads(rows, table).items()):
        for year, amount in sorted(amounts.items()):
            if year not in out:
                raise ValidationError(
                    "%s: the note gives %s for fiscal %d, a year the table does "
                    "not carry" % (table, code, year))
            out[year][code] = amount * multiplier
    return out


def parse(raw):
    tables = json.loads(raw.decode("utf-8"))["tables"]
    meta, observations = {}, []
    for measure, name, desc in TABLES:
        if measure not in tables:
            raise ValidationError("the envelope has no %r table" % measure)
        found = _read_table(base64.b64decode(tables[measure]["b64"]), name)
        for year in sorted(found):
            period = jp_era.period(year)
            for code, name_en, name_ja in (
                    [(code, en, ja) for _c, code, en, ja in HEADS] + FOOTNOTE_HEADS):
                if code not in found[year]:
                    continue
                series_code = "%s.%s" % (code, measure)
                meta.setdefault(series_code, {
                    "code": series_code,
                    "name_en": "%s — %s" % (name_en, desc),
                    "name_ja": name_ja, "unit": "jpy_million",
                    "weight_per_10000": None,
                    "sort_order": HEAD_ORDER[code] * 10 + (0 if measure == "budget" else 1),
                })
                observations.append({"code": series_code, "period": period,
                                     "value": found[year][code]})
    return [meta[code] for code in sorted(meta)], observations


# --- validation -------------------------------------------------------------

def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for required in ("total.settlement", "total.budget", "tax-and-stamp.settlement",
                     "bond-issuance.settlement", "bond-issuance.budget"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    for measure in ("budget", "settlement"):
        total = by_code["total." + measure]
        periods = sorted(total)
        if len(periods) < MIN_YEARS:
            raise ValidationError(
                "only %d %s years; the table has always carried at least %d"
                % (len(periods), measure, MIN_YEARS))
        if periods[0].year != FIRST_YEAR:
            raise ValidationError(
                "%s starts at fiscal %d, not %d — the era of the first row was "
                "read wrong" % (measure, periods[0].year, FIRST_YEAR))
        for earlier, later in zip(periods, periods[1:]):
            if later.year - earlier.year != 1:
                raise ValidationError(
                    "no %s between fiscal %d and %d" % (measure, earlier.year, later.year))
        for period, published in sorted(total.items()):
            component = sum(by_code.get("%s.%s" % (code, measure), {}).get(period, 0.0)
                            for code in TOTAL_PARTS)
            allowed = max(SUM_TOLERANCE,
                          TOLERATED_RESIDUAL.get((measure, period.year), 0.0))
            if abs(component - published) > allowed:
                raise ValidationError(
                    "fiscal %d %s: the heads sum to %s but the Ministry's 合計 "
                    "is %s — a head is being missed or double-counted"
                    % (period.year, measure, component, published))
        # 租税 + 印紙収入 is the Ministry's own 計, and the two monopoly lines
        # are theirs. Both are published, so both are checked rather than
        # assumed.
        for whole, parts in (("tax-and-stamp", ("tax", "stamp-revenue")),
                             ("monopoly", ("monopoly.tobacco", "monopoly.alcohol"))):
            for period, published in sorted(by_code.get("%s.%s" % (whole, measure), {}).items()):
                halves = [by_code.get("%s.%s" % (part, measure), {}).get(period)
                          for part in parts]
                if all(h is not None for h in halves) and \
                        abs(sum(halves) - published) > SUM_TOLERANCE:
                    raise ValidationError(
                        "fiscal %d %s: %s sums to %s but is published as %s"
                        % (period.year, measure, whole, sum(halves), published))

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
        "budget_years": len(by_code["total.budget"]),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "fiscal",
    "name": {"en": "General account revenue by head", "ja": "一般会計歳入主要科目別予算・決算"},
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
        "as_of_supported": True, "history_from": "1982",
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
    "cite": "/fiscal.html?dataset=fiscal-jp-revenue",
    "page": "/fiscal.html",
    "notes": [
        "Series codes are {head}.{budget|settlement}. Bond issuance (公債金) is booked as revenue in Japan's general account and is its own series; a revenue total that is not split between tax and borrowing says very little.",
        "bridge-bonds and settlement-adjustment-fund have no column in the source. They are published only in the note under the table — the Gulf War 臨時特別公債, the 減税特例公債, the 2011 復興債 and the 年金特例公債 — and are parsed out of that note so that the heads reconcile to the Ministry's own 合計 in every year.",
        "専売納付金 (the tobacco and alcohol monopoly payments) ends when Japan Tobacco was privatised in 1985. A dash is missing, never zero, so the series simply stops.",
        "The fiscal 2026 budget column is the one year where the Ministry's own heads exceed its printed 合計, by ¥732.5bn and with no footnote. The figures are published exactly as printed.",
    ],
}
