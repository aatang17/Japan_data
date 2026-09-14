# -*- coding: utf-8 -*-
"""Adapter: general-account spending by policy purpose — MOF 財政統計 第19表・第20表.

Source: 財務省, 財政統計 第20表「昭和42年度以降主要経費別分類による一般会計歳出
予算現額及び決算額」 and 第19表(2)「…主(重)要経費別分類による一般会計歳出当初予算
及び補正予算」 — what Japan's general account is actually spent on, under the
Ministry's own 主要経費 (major expense) classification.

**Five measures, because "the budget" is five different numbers.** 当初予算 is
what the Diet passed in March; 補正予算 is the net of every supplementary
during the year; their 計 is what was voted in total; 予算現額 adds carry-overs
from the prior year and reserve drawdowns, so it is what was actually available
to spend; 決算額 is what was spent. They are never merged. The gap between the
last two is the money voted and not spent — ¥14.6tn in fiscal 2024 — which is
only visible because both are carried.

**Group totals, not line items.** The classification has about fourteen top-
level headings that have held their meaning for sixty years — social security,
debt service, local allocation tax, defence, public works — and underneath them
line items that the Ministry re-cuts every few years (社会保障関係費 was five
items in 1967 and seven quite different ones in 2024). The top level is what is
comparable across the run, so that is what is published; the line items are in
the source file and deliberately not here, because a series that changes
meaning halfway is worse than no series.

**One-off reserves are named, not swept into "other".** The COVID-19 reserve,
the Ukraine reserve, the Tohoku earthquake reserve, the Middle East reserve
opened for fiscal 2026 — each gets its own series for the one or two years it
exists. That is the point of the classification: a ¥5tn contingency reserve is
the fiscal story of its year, and bundling it into a residual would erase it.

**Negative figures in table 20 are parenthesised reference numbers.** Through
the 1960s and 1970s the Ministry printed a second, larger figure in brackets
for lines that include a transfer to a special account, and the workbook stores
those brackets as a negative sign. Nothing in the general account's expenditure
is ever actually negative, so a negative cell is taken as the reference figure
and the real one is read from the unlabelled row printed directly beneath it —
which is checked, every year, by the requirement that the parts add to the
Ministry's own 計 and 合計.

**Table 19(1) — fiscal 1949 to 1984 — is deliberately not ingested.** It uses
the older 重要経費 vocabulary (終戦処理費, 賠償施設処理費, 解除物件処理費 — war
termination, reparations, requisitioned property), which is not the same
classification wearing different words. It needs its own mapping and its own
dataset, and until it has one it stays out rather than being force-fitted onto
headings that did not exist.
"""
import base64
import json
import re

from . import boj_ts, jp_era, xlsx


class ValidationError(Exception):
    pass


BASE = "https://www.mof.go.jp/policy/budget/reference/statistics/"

# table key -> (file, {measure: column}, English gloss per measure)
TABLES = {
    # `brackets`: whether a negative cell in this table is the Ministry's
    # bracket notation for a reference figure. True only for table 20, whose
    # columns are gross amounts that cannot be negative. In table 19 a
    # negative is real — a supplementary budget that CUTS a heading, which is
    # exactly what 補正予算 is for — so treating it as notation would throw
    # away the most interesting numbers in the table.
    "20": {"file": "20.xlsx", "brackets": True,
           "measures": [("budget-final", "D", "budget as finally available"),
                        ("settlement", "E", "settled")]},
    "19b": {"file": "19b.xlsx", "brackets": False,
            "measures": [("initial-budget", "E", "initial budget"),
                         ("supplementary", "F", "supplementary budgets, net"),
                         ("budget-total", "G", "budget as voted")]},
}
MEASURE_ORDER = ["initial-budget", "supplementary", "budget-total",
                 "budget-final", "settlement"]

# The Ministry's top-level headings, in the order it prints them. A heading
# that has appeared under two names over the run maps to one code so the
# series does not split in the middle.
CATEGORIES = [
    ("社会保障関係費", "social-security", "Social security"),
    ("文教及び科学振興費", "education-and-science", "Education and science"),
    ("国債費", "debt-service", "National debt service"),
    ("恩給関係費", "public-service-pensions", "Public service pensions (恩給)"),
    ("地方交付税交付金", "local-allocation-tax", "Local allocation tax grants"),
    ("地方特例交付金", "local-special-grants", "Local special grants"),
    ("臨時地方特例交付金", "local-special-grants-temporary",
     "Temporary local special grants"),
    ("臨時沖縄特別交付金", "okinawa-special-grants", "Temporary Okinawa special grants"),
    ("地方財政関係費", "local-finance", "Local government finance"),
    ("防衛関係費", "defence", "Defence"),
    ("公共事業関係費", "public-works", "Public works"),
    ("貿易振興及び経済協力費", "trade-and-economic-cooperation",
     "Trade promotion and economic cooperation"),
    ("経済協力費", "economic-cooperation", "Economic cooperation"),
    ("海運対策費", "shipping", "Shipping measures"),
    ("中小企業対策費", "small-business", "Small and medium enterprises"),
    ("石炭対策費", "coal", "Coal measures"),
    ("エネルギー対策費", "energy", "Energy measures"),
    ("農業保険費", "agricultural-insurance", "Agricultural insurance"),
    ("農林水産業構造改善対策費", "agriculture-structural-improvement",
     "Agriculture, forestry and fisheries structural improvement"),
    ("食糧管理費", "food-control", "Food control"),
    ("主要食糧関係費", "staple-food", "Staple food"),
    ("食料安定供給関係費", "food-supply", "Stable food supply"),
    ("食糧管理特別会計へ繰入", "transfer-food-control-account",
     "Transfer to the food control special account"),
    ("産業投資特別会計へ繰入", "transfer-industrial-investment-account",
     "Transfer to the industrial investment special account"),
    ("借入金等利子財源繰入", "transfer-borrowing-interest",
     "Transfer to fund interest on borrowings"),
    ("特殊対外債務処理費", "special-external-debt",
     "Settlement of special external debt"),
    ("緊急金融安定化資金", "financial-stabilisation-fund",
     "Emergency financial stabilisation fund"),
    ("改革推進公共投資事業償還時補助等", "reform-public-investment",
     "Reform-promotion public investment — redemption subsidies"),
    ("その他の事項経費", "other-items", "Other expenditure items"),
    ("予備費", "reserve", "Reserve for contingencies"),
    ("給与改善予備費", "reserve.pay", "Reserve — pay revision"),
    ("公共事業等予備費", "reserve.public-works", "Reserve — public works"),
    ("経済緊急対応予備費", "reserve.economic-emergency",
     "Reserve — emergency economic response"),
    ("経済危機対応・地域活性化予備費", "reserve.economic-crisis",
     "Reserve — economic crisis response and regional revitalisation"),
    ("東日本大震災復旧・復興予備費", "reserve.tohoku",
     "Reserve — Great East Japan Earthquake recovery"),
    ("熊本地震復旧等予備費", "reserve.kumamoto", "Reserve — Kumamoto earthquake recovery"),
    ("新型コロナウイルス感染症対策予備費", "reserve.covid", "Reserve — COVID-19 response"),
    ("新型コロナウイルス感染症及び原油価格・物価高騰対策予備費", "reserve.covid-and-prices",
     "Reserve — COVID-19 and oil price and inflation response"),
    ("ウクライナ情勢経済緊急対応予備費", "reserve.ukraine",
     "Reserve — emergency economic response to the situation in Ukraine"),
    ("原油価格・物価高騰対策及び賃上げ促進環境整備対応予備費", "reserve.prices-and-wages",
     "Reserve — oil price and inflation response and wage-increase support"),
    ("中東情勢等対応予備費", "reserve.middle-east",
     "Reserve — response to the situation in the Middle East"),
    ("主要経費計", "major-expenses-subtotal", "Major expenses — subtotal"),
    ("合計", "total", "Total expenditure"),
    ("総合計", "grand-total", "Grand total including the shortfall refund"),
]
CATEGORY_CODE = dict((jp_era.normalize(ja), code) for ja, code, _en in CATEGORIES)
CATEGORY_NAME = dict((code, en) for _ja, code, en in CATEGORIES)
CATEGORY_JA = dict((code, ja) for ja, code, _en in CATEGORIES)
CATEGORY_ORDER = dict((code, i) for i, (_ja, code, _en) in enumerate(CATEGORIES))

# 「昭和56年度決算不足補てん繰戻」, 「平成13度決算不足補てん繰戻」 (the Ministry's own
# typo for 13年度) and four others: the same line, named after whichever year's
# shortfall is being refunded, appearing once each. They never co-occur, so
# they are one series rather than six one-point ones.
_SHORTFALL = re.compile(r"決算不足補てん繰戻$")
SHORTFALL_CODE = "settlement-shortfall-refund"
CATEGORY_NAME[SHORTFALL_CODE] = "Refund to cover a prior-year settlement shortfall"
CATEGORY_JA[SHORTFALL_CODE] = "決算不足補てん繰戻"
CATEGORY_ORDER[SHORTFALL_CODE] = len(CATEGORIES)

# Sub-totals and headings that are never a series of their own.
_SKIP_LABELS = {"小計", "主要経費別", "重要経費別", "計"}
_ITEM_NUMBER = re.compile(r"^\d+[.．]$")
_NOTE = re.compile(r"^[（(]?注")
_TOTAL_LABEL = "合計"
_GROUP_TOTAL = "計"

# What 合計 is made of: every top-level heading except the sub-totals that
# restate part of it.
_NOT_A_PART = ("total", "grand-total", "major-expenses-subtotal")

_UNIT_TO_MILLION = {"円": 1e-6, "千円": 1e-3, "百万円": 1.0, "億円": 100.0, "兆円": 1e6}
_UNIT_CELL = re.compile(r"単位[：:]\s*([^）)、,\s]+)")
_MISSING = ("", "-", "‐", "－", "―", "ー", "…", "***", "×", "x", "X")

FIRST_YEAR = 1967
MIN_YEARS = 55
# Every line is published rounded to the nearest ¥1,000, so a dozen of them
# and the total disagree by a few thousand yen at most — thousandths of a ¥mn.
SUM_TOLERANCE = 1.0

# The two places in fifty-eight years where the Ministry's own file does not
# add up, pinned as ceilings so every other year stays strict and a correction
# still passes:
#
#   fiscal 1973, 予算現額 — 国債費 is printed as ¥699,204,805 thousand, but the
#   差引額 column on the same row (¥3,271,418 thousand against a settled
#   ¥684,933,386 thousand) implies ¥688,204,804 thousand. An ¥11bn typo in the
#   third digit. The figure is published exactly as printed: this platform does
#   not silently correct a source, and the settlement column for the same year
#   reconciles to ¥6 thousand.
#
#   fiscal 1968, 決算額 — the headings exceed the printed 合計 by ¥3mn on a
#   ¥6tn base, which is a rounding slip and nothing else.
TOLERATED_RESIDUAL = {("budget-final", 1973): 11_000.0,
                      ("settlement", 1968): 4.0}

DATASET = {
    "slug": "fiscal-jp-expenditure",
    "title": "General Account Spending by Policy Purpose (Japan)",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "annual",
    "description": (
        "What Japan's general account is spent on, by fiscal year from 1967, "
        "in ¥ million, under the Ministry's own major-expense classification — "
        "social security, debt service, local allocation tax grants, defence, "
        "public works, education and the one-off contingency reserves. Five "
        "measures per heading, never merged: the initial budget, the net of "
        "supplementaries, the budget as voted, the budget as finally available "
        "after carry-overs, and what was actually spent."
    ),
}

SOURCE = {
    "source_id": "mof:fiscal-stats-19-20",
    "name": ("MOF — Fiscal Statistics, Tables 19(2) and 20 (general account "
             "expenditure by major expense)"),
    "name_ja": "財務省 財政統計 第19表(2)・第20表 主要経費別分類による一般会計歳出",
    "url": "https://www.mof.go.jp/policy/budget/reference/statistics/data.htm",
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Finance."
    ),
}

DOWNLOAD_URL = BASE + "20.xlsx and 19b.xlsx"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": ("Source: Ministry of Finance — Fiscal Statistics (財政統計), "
                    "Tables 19(2) and 20."),
    "stale_after_days": 500,
    "main_series": [
        {"role": "headline", "code": "total.settlement",
         "label": "Total expenditure, settled", "slot": 1},
        {"role": "social", "code": "social-security.settlement",
         "label": "Social security", "slot": 2},
        {"role": "debt", "code": "debt-service.settlement",
         "label": "Debt service", "slot": 3},
        {"role": "local", "code": "local-allocation-tax.settlement",
         "label": "Local allocation tax", "slot": 4},
    ],
    "overview_tiles": [
        {"key": "total", "type": "level", "code": "total.initial-budget",
         "label": "Total Spending"},
        {"key": "social", "type": "level", "code": "social-security.initial-budget",
         "label": "Social Security"},
        {"key": "debt", "type": "level", "code": "debt-service.initial-budget",
         "label": "Debt Service"},
        {"key": "defence", "type": "level", "code": "defence.initial-budget",
         "label": "Defence"},
    ],
    "kinds": dict(
        ("%s.%s" % (code, measure), "level")
        for code in ([c for _ja, c, _e in CATEGORIES] + [SHORTFALL_CODE])
        for measure in MEASURE_ORDER),
}


# --- fetching ---------------------------------------------------------------

def fetch():
    envelope = {}
    for key in sorted(TABLES):
        url = BASE + TABLES[key]["file"]
        envelope[key] = {"url": url,
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


def _category(label):
    """A top-level heading -> its code, or None if it is not one.

    Brackets are the Ministry's way of marking a heading that has line items
    beneath it, so 「（社会保障関係費）」 and 「社会保障関係費」 are the same
    heading and must not become two series.
    """
    text = jp_era.normalize(label).strip("（）()")
    if not text:
        return None
    if text in CATEGORY_CODE:
        return CATEGORY_CODE[text]
    if _SHORTFALL.search(text):
        return SHORTFALL_CODE
    return None


def _read_sheet(rows, sheet, measures, multiplier, brackets):
    """One fiscal year's sheet -> {category code: {measure: ¥ million}}.

    Rows are classified as they are read: a heading with no figures opens a
    group whose total is its 計 row; a numbered row or any row inside an open
    group is a line item and is skipped; anything else carrying figures at the
    top level is a heading in its own right.
    """
    ordered = sorted(rows)
    out, group, open_at, items = {}, None, None, []

    def figures(row):
        """The row's measures, with a bracketed reference figure resolved.

        A negative cell is the Ministry's bracket notation; the real figure is
        on the unlabelled row printed beneath it.
        """
        found, needed_next = {}, False
        for measure, col, _gloss in measures:
            value = _value(_text(rows, row, col))
            if value is None:
                continue
            if brackets and value < 0:
                needed_next = True
                continue
            found[measure] = value
        if not needed_next:
            return found
        following = [r for r in ordered if r > row]
        if not following:
            raise ValidationError(
                "sheet %r row %d holds a bracketed figure with no row beneath "
                "it to carry the real one" % (sheet, row))
        nxt = following[0]
        if jp_era.normalize(_text(rows, nxt, "B")) or jp_era.normalize(_text(rows, nxt, "C")):
            raise ValidationError(
                "sheet %r row %d holds a bracketed figure but row %d beneath it "
                "is labelled, so the real figure cannot be read"
                % (sheet, row, nxt))
        for measure, col, _gloss in measures:
            if measure in found:
                continue
            value = _value(_text(rows, nxt, col))
            if value is None or value < 0:
                raise ValidationError(
                    "sheet %r: no real figure for %s under the bracketed one at "
                    "row %d" % (sheet, measure, row))
            found[measure] = value
        return found

    def record(code, values, row):
        if not values:
            return
        if code in out:
            raise ValidationError(
                "sheet %r publishes %s twice (again at row %d)" % (sheet, code, row))
        out[code] = dict((measure, value * multiplier)
                         for measure, value in values.items())

    def close_without_total(row):
        """A heading whose group has no 計 row.

        Fiscal 1985 prints 地方財政関係費 with 地方交付税交付金 as its only line
        and no total — the heading's amount simply *is* that line's, which is
        an identity rather than a calculation. More than one line and there is
        no published total to stand on, so nothing is published.
        """
        if len(items) != 1:
            raise ValidationError(
                "sheet %r: heading %r opened at row %d, has %d lines and no 計 "
                "row, so its total is not published anywhere"
                % (sheet, group, open_at, len(items)))
        record(group, items[0], row)

    for row in ordered:
        label = jp_era.normalize(_text(rows, row, "B"))
        if not label:
            # An unnumbered line inside an open group carries its name in
            # column C; it is still one of the group's lines.
            if group is not None and jp_era.normalize(_text(rows, row, "C")):
                found = figures(row)
                if found:
                    items.append(found)
            continue
        if _NOTE.match(label) or len(label) > 40:
            continue
        if _ITEM_NUMBER.match(label):
            found = figures(row)
            if found and group is not None:
                items.append(found)
            continue            # a numbered line item; its name is in column C
        if label == _GROUP_TOTAL:
            if group is not None:
                record(group, figures(row), row)
                group, items = None, []
            continue
        if label in _SKIP_LABELS:
            continue
        code = _category(label)
        values = figures(row)
        if code is None:
            if group is None:
                raise ValidationError(
                    "sheet %r row %d: %r is a top-level heading this adapter "
                    "does not know. Give it a code and an English name before "
                    "publishing it." % (sheet, row, label))
            if values:
                items.append(values)
            continue            # a line item inside an open group
        if not values:
            if group is not None:
                close_without_total(row)
            group, open_at, items = code, row, []
            continue
        if group is not None:
            # A heading the adapter knows, carrying figures, while a group is
            # still open: the open group had no 計 row and this row is the next
            # heading, not one of its lines.
            close_without_total(row)
            group, items = None, []
        record(code, values, row)
    if group is not None:
        close_without_total(max(ordered))
    return out


def _read_table(raw, key):
    """One workbook -> {fiscal year: {category: {measure: value}}}."""
    sheets = xlsx.sheets(raw)
    measures = TABLES[key]["measures"]
    out = {}
    for sheet, rows in sheets.items():
        year = jp_era.fiscal_year(sheet)
        if year is None:
            continue            # the notes tab
        year = jp_era.check(year, sheet)
        found = _read_sheet(rows, sheet, measures, _unit_multiplier(rows, sheet),
                            TABLES[key]["brackets"])
        if not found:
            raise ValidationError("sheet %r yielded nothing" % sheet)
        if year in out:
            raise ValidationError(
                "table %s has two sheets for fiscal %d" % (key, year))
        out[year] = found
    if not out:
        raise ValidationError("table %s has no fiscal-year sheets" % key)
    return out


def parse(raw):
    tables = json.loads(raw.decode("utf-8"))["tables"]
    by_year = {}
    for key in sorted(TABLES):
        if key not in tables:
            raise ValidationError("the envelope has no table %s" % key)
        for year, found in _read_table(base64.b64decode(tables[key]["b64"]), key).items():
            for code, measures in found.items():
                for measure, value in measures.items():
                    slot = by_year.setdefault(year, {}).setdefault(code, {})
                    if measure in slot and slot[measure] != value:
                        raise ValidationError(
                            "fiscal %d %s %s is published twice with different "
                            "values (%s, %s)" % (year, code, measure, slot[measure], value))
                    slot[measure] = value

    meta, observations = {}, []
    for year in sorted(by_year):
        period = jp_era.period(year)
        for code in sorted(by_year[year]):
            for measure in MEASURE_ORDER:
                if measure not in by_year[year][code]:
                    continue
                series_code = "%s.%s" % (code, measure)
                gloss = dict((m, g) for t in TABLES.values()
                             for m, _c, g in t["measures"])[measure]
                meta.setdefault(series_code, {
                    "code": series_code,
                    "name_en": "%s — %s" % (CATEGORY_NAME[code], gloss),
                    "name_ja": CATEGORY_JA[code], "unit": "jpy_million",
                    "weight_per_10000": None,
                    "sort_order": CATEGORY_ORDER[code] * 10 + MEASURE_ORDER.index(measure),
                })
                observations.append({"code": series_code, "period": period,
                                     "value": by_year[year][code][measure]})
    return [meta[code] for code in sorted(meta)], observations


# --- validation -------------------------------------------------------------

def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for required in ("total.settlement", "total.budget-final", "total.initial-budget",
                     "social-security.settlement", "debt-service.settlement",
                     "local-allocation-tax.settlement", "defence.settlement"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    settled = by_code["total.settlement"]
    periods = sorted(settled)
    if len(periods) < MIN_YEARS:
        raise ValidationError(
            "only %d settled years; the table has always carried at least %d"
            % (len(periods), MIN_YEARS))
    if periods[0].year != FIRST_YEAR:
        raise ValidationError(
            "settled spending starts at fiscal %d, not %d"
            % (periods[0].year, FIRST_YEAR))
    for earlier, later in zip(periods, periods[1:]):
        if later.year - earlier.year != 1:
            raise ValidationError(
                "no settled spending between fiscal %d and %d"
                % (earlier.year, later.year))

    parts = [code for _ja, code, _en in CATEGORIES if code not in _NOT_A_PART]
    parts.append(SHORTFALL_CODE)
    checked = 0
    for measure in MEASURE_ORDER:
        total = by_code.get("total." + measure, {})
        for period, published in sorted(total.items()):
            component = sum(by_code.get("%s.%s" % (code, measure), {}).get(period, 0.0)
                            for code in parts)
            # 総合計 is the Ministry's own total including the shortfall refund;
            # where it is published, 合計 excludes that line.
            grand = by_code.get("grand-total.%s" % measure, {}).get(period)
            refund = by_code.get("%s.%s" % (SHORTFALL_CODE, measure), {}).get(period, 0.0)
            if grand is not None:
                component -= refund
            allowed = max(SUM_TOLERANCE,
                          TOLERATED_RESIDUAL.get((measure, period.year), 0.0))
            if abs(component - published) > allowed:
                raise ValidationError(
                    "fiscal %d %s: the headings sum to %s but the Ministry's 合計 "
                    "is %s — a heading is being missed or double-counted"
                    % (period.year, measure, component, published))
            checked += 1

    for code, points in by_code.items():
        if code.endswith(".supplementary"):
            continue            # a supplementary is a net change and goes negative
        for period, value in points.items():
            if value < 0:
                raise ValidationError(
                    "%s fiscal %d is negative (%s) — only a supplementary is"
                    % (code, period.year, value))

    latest = max(o["period"] for o in observations)
    return {
        "series": len(codes),
        "observations": len(observations),
        "first_period": str(min(o["period"] for o in observations)),
        "latest_period": str(latest),
        "settled_years": len(periods),
        "totals_reconciled": checked,
        "settled_total_latest": settled[max(settled)],
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "fiscal",
    "name": {"en": "General account spending by policy purpose", "ja": "主要経費別分類による一般会計歳出"},
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
        "as_of_supported": True, "history_from": "1967",
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
    "cite": "/fiscal.html?dataset=fiscal-jp-expenditure",
    "page": "/fiscal.html",
    "notes": [
        "Series codes are {heading}.{measure} over five measures that are never merged: initial-budget (当初予算), supplementary (補正予算, a net change that can be negative), budget-total (計), budget-final (予算現額, after carry-overs and reserve drawdowns) and settlement (決算額).",
        "Top-level headings only. The line items beneath them are re-cut by the Ministry every few years — 社会保障関係費 was five items in 1967 and seven different ones in 2024 — so only the headings are comparable across the run.",
        "One-off contingency reserves are named rather than swept into a residual: the COVID-19, Ukraine, Tohoku and Kumamoto reserves each have their own series for the years they exist.",
        "A negative figure in table 20 is the Ministry's bracket notation for a reference amount; the real figure is on the unlabelled row beneath it, and the requirement that the headings sum to the printed 合計 checks that reading every year.",
        "Table 19(1), fiscal 1949 to 1984, is not ingested: it uses the older 重要経費 vocabulary (終戦処理費, 賠償施設処理費), which is a different classification and needs its own mapping.",
    ],
}
