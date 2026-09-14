"""Adapter: national tax receipts against budget — MOF 租税及び印紙収入決算額調.

Source: 財務省, 租税及び印紙収入決算額調 — one workbook per fiscal year giving,
for every national tax, what the supplementary budget assumed (補正後予算額) and
what was actually collected (決算額).

**What this is for.** Japan's tax take is where the fiscal position actually
turns, and it is the number the Ministry itself gets wrong most often: in every
one of the four years published here the outturn beat the budget, twice by more
than ¥3tn. Carrying both figures as separate series makes the miss measurable
instead of anecdotal. The Ministry's own 進捗割合 (outturn ÷ budget) and 増減
(the difference) columns are deliberately **not** ingested — both are arithmetic
on the two series that are, so the platform computes them where they are shown
and carries the formula, per the trust contract.

**Two blocks, and they must not be mixed.** The workbook runs the general
account's taxes down to 一般会計分計, then a （参考） block of taxes that fund
local government or a special account — 地方法人税, the 譲与分 shares handed to
prefectures, 復興特別所得税 — and a 総計 over both. 「その他」 appears in each
block with different values, so every series is prefixed by its block: `general.`
for the general account and `ref.` for the reference taxes. Nothing sums across
the two except the Ministry's own 総計.

**Income tax is written one character per row.** Rows 7 to 9 carry 「所」「得」
「税」 in column A, one kanji each, with the split (源泉分 withheld at source,
申告分 self-assessed, 計) in column B beside them — a vertical label, not three
taxes. The parser rebuilds the name from the run of rows, so a layout that looks
like three unknown taxes is read as the one it is.

**A new tax stops the ingest rather than being guessed at.** 森林環境税 first
appears in the fiscal-2024 workbook; 防衛特別法人税 is legislated and will
appear. An unrecognised Japanese tax name raises, the previous release stays
live, and the tax gets a name and a slug before it gets published — an English
label invented by a parser is exactly the kind of number an institutional user
cannot check.

**Four fiscal years, and that is the whole run.** The Ministry keeps only the
current and three prior workbooks on the live site; fiscal 2021 and earlier sit
in the National Diet Library's WARP archive, which refuses our requests. The
history here therefore accumulates one year at a time from fiscal 2022 — which
is the point of storing it at all.
"""
import base64
import json
import re

from . import boj_ts, jp_era, xls


class ValidationError(Exception):
    pass


INDEX_URL = "https://www.mof.go.jp/tax_policy/reference/account/data.htm"
_BASE = "https://www.mof.go.jp/tax_policy/reference/account/"
_FILE_RE = re.compile(r'href="\./?(r(\d{4})\.xls)"')

# Column layout, stable across every workbook published.
_COL_BUDGET = "C"
_COL_SETTLEMENT = "D"

# 一般会計分 — the taxes that fund the general account.
GENERAL_TAXES = [
    ("所得税", "income-tax", "Income tax"),
    ("法人税", "corporation-tax", "Corporation tax"),
    ("相続税", "inheritance-tax", "Inheritance tax"),
    ("消費税", "consumption-tax", "Consumption tax"),
    ("酒税", "liquor-tax", "Liquor tax"),
    ("たばこ税", "tobacco-tax", "Tobacco tax"),
    ("揮発油税", "gasoline-tax", "Gasoline tax"),
    ("石油ガス税", "lpg-tax", "Liquefied petroleum gas tax"),
    ("航空機燃料税", "aviation-fuel-tax", "Aviation fuel tax"),
    ("石油石炭税", "petroleum-and-coal-tax", "Petroleum and coal tax"),
    ("電源開発促進税", "power-development-tax", "Power development promotion tax"),
    ("自動車重量税", "motor-vehicle-tonnage-tax", "Motor vehicle tonnage tax"),
    ("国際観光旅客税", "international-tourist-tax", "International tourist tax"),
    ("関税", "customs-duty", "Customs duty"),
    ("とん税", "tonnage-due", "Tonnage due"),
    ("その他", "other", "Other taxes"),
    ("印紙収入", "stamp-revenue", "Stamp revenue"),
    ("一般会計分計", "total", "Total — general account"),
]
# （参考） — taxes collected nationally that fund local government or a
# special account, plus the grand total over both blocks.
REFERENCE_TAXES = [
    ("地方法人税", "local-corporation-tax", "Local corporation tax"),
    ("地方揮発油税", "local-gasoline-tax", "Local gasoline tax"),
    ("石油ガス税(譲与分)", "lpg-tax-transferred",
     "Liquefied petroleum gas tax — transferred to local government"),
    ("航空機燃料税(譲与分)", "aviation-fuel-tax-transferred",
     "Aviation fuel tax — transferred to local government"),
    ("自動車重量税(譲与分)", "motor-vehicle-tonnage-tax-transferred",
     "Motor vehicle tonnage tax — transferred to local government"),
    ("特別とん税", "special-tonnage-due", "Special tonnage due"),
    ("森林環境税", "forest-environment-tax", "Forest environment tax"),
    ("特別法人事業税", "special-corporate-enterprise-tax",
     "Special corporate enterprise tax"),
    ("たばこ特別税", "special-tobacco-tax", "Special tobacco tax"),
    ("復興特別所得税", "reconstruction-income-surtax",
     "Reconstruction special income surtax"),
    ("その他", "other", "Other taxes"),
    ("総計", "grand-total", "Grand total — all national taxes"),
]
# The split published under 所得税, in column B.
INCOME_SPLIT = {
    "源泉分": ("withheld", "Income tax — withheld at source"),
    "申告分": ("self-assessed", "Income tax — self-assessed"),
    "計": (None, None),   # the total keeps the plain `income-tax` code
}

_BLOCK_BREAK = "（参考）"
_GENERAL_END = "一般会計分計"
MEASURES = [("budget", "budgeted in the supplementary budget", _COL_BUDGET),
            ("settlement", "collected", _COL_SETTLEMENT)]

_MISSING = ("", "-", "‐", "－", "―", "ー", "…", "***", "×", "x", "X")
_UNIT_CELL = re.compile(r"単位[：:]\s*([^）)、,\s]+)")
FIRST_YEAR = 2022
MIN_YEARS = 3
# Every tax is published rounded to the nearest ¥ million, so the rounded
# parts and the rounded total disagree by a few million on a ¥70tn base. This
# allows that and nothing more: the smallest tax in the table, とん税, is
# ¥9bn, so a tax read into the wrong block or missed altogether is still two
# orders of magnitude outside it.
SUM_TOLERANCE = 50.0

DATASET = {
    "slug": "tax-receipts-jp",
    "title": "National Tax Receipts — Budget vs Outturn (Japan)",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "annual",
    "description": (
        "Every national tax Japan levies, by fiscal year from 2022, in ¥ "
        "million: what the supplementary budget assumed and what was actually "
        "collected, carried as two series so the miss is measurable. Covers "
        "the general account's taxes, the taxes handed on to local government "
        "and the reconstruction surtax, with the Ministry's own totals."
    ),
}

SOURCE = {
    "source_id": "mof:tax-receipts",
    "name": "MOF — Settlement of national tax and stamp revenues",
    "name_ja": "財務省 租税及び印紙収入決算額調",
    "url": INDEX_URL,
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Finance."
    ),
}

DOWNLOAD_URL = INDEX_URL + " (every fiscal-year workbook listed)"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": ("Source: Ministry of Finance — Settlement of national tax and "
                    "stamp revenues (租税及び印紙収入決算額調)."),
    # A fiscal year's workbook appears in the spring after the year ends and
    # is revised until the settlement closes that autumn. The newest period is
    # therefore up to about eighteen months old the day before the next one
    # lands; this allows that plus three months.
    "stale_after_days": 640,
    "main_series": [
        {"role": "headline", "code": "general.total.settlement",
         "label": "General account tax revenue, collected", "slot": 1},
        {"role": "consumption", "code": "general.consumption-tax.settlement",
         "label": "Consumption tax", "slot": 2},
        {"role": "income", "code": "general.income-tax.settlement",
         "label": "Income tax", "slot": 3},
        {"role": "corporation", "code": "general.corporation-tax.settlement",
         "label": "Corporation tax", "slot": 4},
    ],
    "overview_tiles": [
        {"key": "total", "type": "level", "code": "general.total.settlement",
         "label": "Tax Revenue (Collected)"},
        {"key": "consumption", "type": "level",
         "code": "general.consumption-tax.settlement", "label": "Consumption Tax"},
        {"key": "income", "type": "level", "code": "general.income-tax.settlement",
         "label": "Income Tax"},
        {"key": "corporation", "type": "level",
         "code": "general.corporation-tax.settlement", "label": "Corporation Tax"},
    ],
    # Every series is a published amount, which is what lets /series list
    # them; the platform's level surfaces are gated on this being populated.
    "kinds": dict(
        [("%s.%s.%s" % (block, slug, measure), "level")
         for block, table in (("general", GENERAL_TAXES), ("ref", REFERENCE_TAXES))
         for _ja, slug, _en in table
         for measure, _d, _c in MEASURES]
        # 所得税 is the only tax published split, so it is the only one that
        # gets the split codes; inventing them for every tax would put codes
        # in the catalogue that no series will ever have.
        + [("general.income-tax.%s.%s" % (part, measure), "level")
           for part, _label in INCOME_SPLIT.values() if part
           for measure, _d, _c in MEASURES]),
}


# --- fetching ---------------------------------------------------------------

def discover():
    """{fiscal year: workbook URL} for every year the Ministry still lists."""
    index = boj_ts.fetch_bytes(INDEX_URL).decode("utf-8", "replace")
    found = dict((int(year), _BASE + name) for name, year in _FILE_RE.findall(index))
    if not found:
        raise ValidationError(
            "no rYYYY.xls workbook is linked from %s — the index page changed"
            % INDEX_URL)
    return found


def fetch():
    envelope = {}
    for year, url in sorted(discover().items()):
        envelope[str(year)] = {
            "url": url,
            "b64": base64.b64encode(boj_ts.fetch_bytes(url)).decode("ascii"),
        }
    return json.dumps({"years": envelope}, sort_keys=True).encode("utf-8")


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


def _check_unit(rows, year):
    """The workbook is in 百万円. Anything else would silently rescale a tax."""
    for row in sorted(rows)[:8]:
        for text in (cell[0] or "" for cell in rows[row].values()):
            found = _UNIT_CELL.search(jp_era.normalize(text))
            if found and found.group(1) != "百万円":
                raise ValidationError(
                    "the fiscal %d workbook is published in %r, not 百万円"
                    % (year, found.group(1)))
            if found:
                return
    raise ValidationError("the fiscal %d workbook carries no 単位 cell" % year)


def _labelled_rows(rows):
    """[(row, tax name, sub-label)] with vertical names rebuilt.

    A run of consecutive rows that all carry a sub-label in column B is one
    tax whose name is written one character per row down column A — the
    Ministry's layout for 所得税. Anything else is a tax per row.
    """
    ordered = sorted(rows)
    out, run = [], []

    def flush():
        if not run:
            return
        name = "".join(_a for _r, _a, _b in run)
        for row, _a, sub in run:
            out.append((row, name, sub))
        del run[:]

    for row in ordered:
        name = jp_era.normalize(_text(rows, row, "A"))
        sub = jp_era.normalize(_text(rows, row, "B"))
        if sub:
            run.append((row, name, sub))
            continue
        flush()
        if name:
            out.append((row, name, None))
    flush()
    return out


def _read_year(year, raw):
    """One workbook -> {series code: value}, both measures, both blocks."""
    sheets = xls.sheets(raw)
    if not sheets:
        raise ValidationError("the fiscal %d workbook has no sheets" % year)
    rows = list(sheets.values())[0]
    _check_unit(rows, year)

    general = dict((ja, (slug, en)) for ja, slug, en in GENERAL_TAXES)
    reference = dict((ja, (slug, en)) for ja, slug, en in REFERENCE_TAXES)
    order = dict((ja, i) for i, (ja, _s, _e) in enumerate(GENERAL_TAXES))
    order.update((ja, 100 + i) for i, (ja, _s, _e) in enumerate(REFERENCE_TAXES))

    out, block, seen_end = {}, "general", False
    for row, name, sub in _labelled_rows(rows):
        if name == _BLOCK_BREAK:
            block = "ref"
            continue
        table = general if block == "general" else reference
        if name not in table:
            # Header rows and the Ministry's own title line reach here too;
            # only a row that actually carries numbers is a tax we missed.
            if not any(_value(_text(rows, row, col)) is not None
                       for _m, _d, col in MEASURES):
                continue
            raise ValidationError(
                "the fiscal %d workbook has a tax this adapter does not know: "
                "%r in the %s block. Give it a slug and an English name before "
                "publishing it." % (year, name, block))
        slug, name_en = table[name]
        if sub is not None:
            if sub not in INCOME_SPLIT:
                raise ValidationError(
                    "fiscal %d: %r has an unknown split %r" % (year, name, sub))
            suffix, split_en = INCOME_SPLIT[sub]
            if suffix:
                slug, name_en = slug + "." + suffix, split_en
        for measure, _desc, col in MEASURES:
            value = _value(_text(rows, row, col))
            if value is None:
                continue
            code = "%s.%s.%s" % (block, slug, measure)
            if code in out:
                raise ValidationError(
                    "fiscal %d publishes %s twice" % (year, code))
            out[code] = (value, name_en, name, order[name])
        if name == _GENERAL_END:
            seen_end = True
    if not seen_end:
        raise ValidationError(
            "the fiscal %d workbook has no 一般会計分計 row — the general-account "
            "block could not be closed" % year)
    return out


def parse(raw):
    years = json.loads(raw.decode("utf-8"))["years"]
    meta, observations = {}, []
    for year_text in sorted(years):
        year = int(year_text)
        found = _read_year(year, base64.b64decode(years[year_text]["b64"]))
        period = jp_era.period(year)
        for code, (value, name_en, name_ja, sort_order) in sorted(found.items()):
            measure = code.rsplit(".", 1)[1]
            label = "%s — %s" % (name_en, dict(
                (m, d) for m, d, _c in MEASURES)[measure])
            meta.setdefault(code, {
                "code": code, "name_en": label, "name_ja": name_ja,
                "unit": "jpy_million", "weight_per_10000": None,
                "sort_order": sort_order * 10 + (0 if measure == "budget" else 1),
            })
            observations.append({"code": code, "period": period, "value": value})
    return [meta[code] for code in sorted(meta)], observations


# --- validation -------------------------------------------------------------

def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for required in ("general.total.settlement", "general.total.budget",
                     "general.consumption-tax.settlement",
                     "general.income-tax.settlement",
                     "general.corporation-tax.settlement",
                     "ref.grand-total.settlement"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    total = by_code["general.total.settlement"]
    periods = sorted(total)
    if len(periods) < MIN_YEARS:
        raise ValidationError(
            "only %d fiscal years; the Ministry lists at least %d"
            % (len(periods), MIN_YEARS))
    if periods[0].year < FIRST_YEAR:
        raise ValidationError(
            "a fiscal %d workbook appeared; this adapter has only ever seen "
            "%d onward and its layout is unverified before that"
            % (periods[0].year, FIRST_YEAR))
    for earlier, later in zip(periods, periods[1:]):
        if later.year - earlier.year != 1:
            raise ValidationError(
                "no workbook between fiscal %d and %d" % (earlier.year, later.year))

    # The general-account block must add up to the Ministry's own 一般会計分計,
    # and the grand total to both blocks. If it does not, a row was read into
    # the wrong block or missed entirely — which is the failure mode that a
    # per-tax table makes invisible.
    parts = [slug for _ja, slug, _en in GENERAL_TAXES if slug != "total"]
    for measure in ("budget", "settlement"):
        for period, published in sorted(by_code["general.total." + measure].items()):
            component = sum(by_code.get("general.%s.%s" % (slug, measure), {})
                            .get(period, 0.0) for slug in parts)
            if abs(component - published) > SUM_TOLERANCE:
                raise ValidationError(
                    "fiscal %d %s: the general-account taxes sum to %s but the "
                    "Ministry's 一般会計分計 is %s"
                    % (period.year, measure, component, published))

    ref_parts = [slug for _ja, slug, _en in REFERENCE_TAXES if slug != "grand-total"]
    for measure in ("budget", "settlement"):
        for period, published in sorted(by_code["ref.grand-total." + measure].items()):
            component = by_code["general.total.%s" % measure].get(period, 0.0)
            component += sum(by_code.get("ref.%s.%s" % (slug, measure), {})
                             .get(period, 0.0) for slug in ref_parts)
            if abs(component - published) > SUM_TOLERANCE:
                raise ValidationError(
                    "fiscal %d %s: the two blocks sum to %s but the Ministry's "
                    "総計 is %s" % (period.year, measure, component, published))

    # Income tax's two halves must add to its own total.
    for measure in ("budget", "settlement"):
        whole = by_code.get("general.income-tax." + measure, {})
        for period, published in sorted(whole.items()):
            halves = [by_code.get("general.income-tax.%s.%s" % (part, measure), {})
                      .get(period) for part in ("withheld", "self-assessed")]
            if all(h is not None for h in halves) and abs(sum(halves) - published) > SUM_TOLERANCE:
                raise ValidationError(
                    "fiscal %d %s: withheld plus self-assessed income tax is %s "
                    "but the published total is %s"
                    % (period.year, measure, sum(halves), published))

    for code, points in by_code.items():
        for period, value in points.items():
            if value < 0:
                raise ValidationError(
                    "%s fiscal %d is negative (%s) — a tax take does not run "
                    "backwards" % (code, period.year, value))

    latest = max(o["period"] for o in observations)
    return {
        "series": len(codes),
        "observations": len(observations),
        "fiscal_years": len(periods),
        "first_period": str(min(periods)),
        "latest_period": str(latest),
        "general_account_tax_latest": total[max(total)],
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "fiscal",
    "name": {"en": "National tax receipts — budget vs outturn", "ja": "租税及び印紙収入決算額調"},
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
        "as_of_supported": True, "history_from": "2022",
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
    "cite": "/fiscal.html?dataset=tax-receipts-jp",
    "page": "/fiscal.html",
    "notes": [
        "Series codes are {general|ref}.{tax}.{budget|settlement}. The block prefix matters: 「その他」 appears in both the general-account block and the （参考） block with different values.",
        "Income tax carries its published split as well as its total: general.income-tax.withheld (源泉分) and general.income-tax.self-assessed (申告分).",
        "The Ministry's 進捗割合 and 増減 columns are not ingested. Both are arithmetic on the two series that are, so the platform computes them where they are shown and carries the formula.",
        "Only the current and three prior fiscal years are on the Ministry's site; fiscal 2021 and earlier sit in the National Diet Library's WARP archive, which refuses our requests. The history here accumulates one year at a time from fiscal 2022.",
    ],
}
