"""Adapter: bank earnings by group — FSA 銀行の決算の状況.

Source: 金融庁 (Financial Services Agency), 主要行等の決算の概要 and 地域銀行の
決算の概要 — the two long-run workbooks behind the FSA's half-yearly results
summary: one for the major banks (主要行等, from the March 2008 half-year) and
one for the regional banks (地域銀行, from March 2005). Each carries the
aggregate income statement — gross business profit and its three parts, bond
gains, expenses, net business profit, core net business profit, credit costs,
equity gains and write-offs, net income — with loans outstanding, the
bad-loan stock and ratio, and the capital ratios under both the international
and the domestic standard.

**Two files, one dataset.** The major-bank file is on a consolidated basis
for the income statement (the FSA labels it （連結）) with the starred lines
on a non-consolidated basis; the regional-bank file is non-consolidated
throughout. The lines are stored under the label the FSA gives them —
`net-business-profit` for the majors' （連結）業務純益, `real-net-business-profit`
for the regionals' 実質業務純益 — so the two groups are never silently
treated as the same measure.

**Two sheets, two lengths.** The 3月期 sheet is the full fiscal year and the
9月期 sheet the first half. Income-statement lines are therefore two series
each: `.fy` on March points and `.h1` on September points. Stocks — loans,
bad loans, the ratios — are point-in-time and stay one series.

**Ratios are stored in percent.** The FSA stores them as fractions formatted
as percentages (0.1745 shown as 17.45%); the fraction is read and multiplied
by 100, exactly. Amounts are 億円 for the income statement and 兆円 for loans
and bad loans, as published, never rescaled.

**Capital ratios change basis at March 2013.** Basel III split the disclosure
into internationally active banks (total, Tier 1 and CET1 ratios) and
domestic-standard banks (one ratio). The single pre-split ratio is kept as its
own series (`capital-ratio-all`) rather than spliced onto either successor.
"""
import base64
import datetime
import json
import re

from . import boj_ts, xlsx


class ValidationError(Exception):
    pass


FILES = {
    "major": "https://www.fsa.go.jp/status/ginkou_kessan/04.xlsx",
    "regional": "https://www.fsa.go.jp/status/ginkou_kessan/05.xlsx",
}
GROUPS = {
    "major": ("Major banks", "主要行等", 0),
    "regional": ("Regional banks", "地域銀行", 1),
}

# (slug, English, unit, is_flow, order), keyed by the FSA's label once
# asterisks, brackets and whitespace are stripped. The capital ratios are
# resolved with their block header below, not here.
LINES = {
    "業務粗利益": ("gross-profit", "Gross business profit", "jpy_100mn", True, 0),
    "資金利益": ("net-interest-income", "Net interest income", "jpy_100mn", True, 1),
    "役務取引等利益": ("fee-income", "Net fees and commissions", "jpy_100mn", True, 2),
    "その他業務利益": ("other-income", "Other business profit", "jpy_100mn", True, 3),
    "うち債券等関係損益": ("bond-gains", "of which gains on bonds", "jpy_100mn", True, 4),
    "うち債券等償却": ("bond-writeoffs", "of which bond write-offs", "jpy_100mn", True, 5),
    "経費": ("expenses", "Expenses", "jpy_100mn", True, 6),
    "業務純益": ("net-business-profit", "Net business profit (consolidated)", "jpy_100mn", True, 7),
    "実質業務純益": ("real-net-business-profit", "Real net business profit", "jpy_100mn", True, 7),
    "コア業務純益": ("core-net-business-profit", "Core net business profit", "jpy_100mn", True, 8),
    "コア業務純益（除く投資信託解約損益）": (
        "core-net-business-profit-ex-trusts",
        "Core net business profit excluding investment-trust cancellation gains",
        "jpy_100mn", True, 9),
    "与信関係費用": ("credit-costs", "Credit costs", "jpy_100mn", True, 10),
    "株式等関係損益": ("equity-gains", "Gains on equities", "jpy_100mn", True, 11),
    "うち株式等償却": ("equity-writeoffs", "of which equity write-offs", "jpy_100mn", True, 12),
    "当期純利益": ("net-income", "Net income", "jpy_100mn", True, 13),
    "中間純利益": ("net-income", "Net income", "jpy_100mn", True, 13),
    "親会社株主に帰属する当期純利益": ("net-income", "Net income attributable to parent", "jpy_100mn", True, 13),
    "貸出金（末残）": ("loans", "Loans outstanding, period end", "jpy_trillion", False, 14),
    "不良債権額": ("npl", "Bad loans outstanding", "jpy_trillion", False, 15),
    "不良債権残高": ("npl", "Bad loans outstanding", "jpy_trillion", False, 15),
    "不良債権比率": ("npl-ratio", "Bad-loan ratio", "pct", False, 16),
}
# Capital-ratio lines are the same label under different block headers.
BLOCKS = {
    "国際統一基準行": "intl",
    "国内基準行": "domestic",
    "主要行等計": "all",
    "国内、国際基準行分離前の開示": "all",
}
RATIOS = {
    ("intl", "総自己資本比率"): ("capital-ratio-intl", "Total capital ratio, international-standard banks", 17),
    ("intl", "Tier1比率"): ("tier1-ratio-intl", "Tier 1 ratio, international-standard banks", 18),
    ("intl", "普通株式等Tier1比率"): ("cet1-ratio-intl", "CET1 ratio, international-standard banks", 19),
    ("domestic", "自己資本比率"): ("capital-ratio-domestic", "Capital ratio, domestic-standard banks", 20),
    ("all", "自己資本比率"): ("capital-ratio-all", "Capital ratio, all banks before the Basel III split", 21),
}
# Footnote markers and whitespace; the consolidated tag the FSA prefixes to
# the majors' income-statement lines. Brackets stay: they distinguish core
# net business profit from the same line excluding trust-cancellation gains.
_NOISE = re.compile(r"[*＊※]+|[\s　]+|^（連結）")
_PERIOD_TEXT = re.compile(r"^(\d{4})/(\d{1,2})$")
_EPOCH = datetime.date(1899, 12, 30)

DATASET = {
    "slug": "fsa-bank-results",
    "title": "Bank Earnings by Group — Major and Regional Banks (Japan)",
    "country": "Japan",
    "agency": "Financial Services Agency",
    "agency_ja": "金融庁",
    "base": None,
    "frequency": "semiannual",
    "description": (
        "The FSA's half-yearly summary of bank results for the major banks "
        "(from March 2008) and the regional banks (from March 2005): gross "
        "business profit and its parts, expenses, net and core net business "
        "profit, credit costs, equity gains, net income, loans outstanding, "
        "bad loans and the ratio, and capital ratios under the international "
        "and domestic standards. Amounts in 億円 and 兆円 as published."
    ),
}

SOURCE = {
    "source_id": "fsa:ginkou-kessan",
    "name": "FSA — Summary of Bank Financial Results (主要行等・地域銀行の決算の概要)",
    "name_ja": "金融庁 銀行の決算の状況（主要行等・地域銀行の決算の概要）",
    "url": "https://www.fsa.go.jp/status/ginkou_kessan/index.html",
    "license_note": (
        "Financial Services Agency website terms of use (compatible with CC BY "
        "4.0): free to use with attribution to the Financial Services Agency."
    ),
}

DOWNLOAD_URL = SOURCE["url"] + " (04.xlsx and 05.xlsx)"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": ("Source: Financial Services Agency — Summary of bank financial "
                    "results (主要行等・地域銀行の決算の概要)."),
    # Fiscal-year results land in early June (令和7年度 on 2026-06-10) and
    # first-half results in early December, so the newest half-year is at most
    # about nine months old the day before the next lands. Allows two more.
    "stale_after_days": 330,
    "main_series": [
        {"role": "headline", "code": "major.net-income.fy",
         "label": "Net income, major banks", "slot": 1},
        {"role": "regional", "code": "regional.net-income.fy",
         "label": "Net income, regional banks", "slot": 2},
    ],
    "overview_tiles": [
        {"key": "major_ni", "type": "level", "code": "major.net-income.fy",
         "label": "Major Banks Net Income"},
        {"key": "regional_ni", "type": "level", "code": "regional.net-income.fy",
         "label": "Regional Banks Net Income"},
        {"key": "major_loans", "type": "level", "code": "major.loans",
         "label": "Major Banks Loans"},
        {"key": "regional_loans", "type": "level", "code": "regional.loans",
         "label": "Regional Banks Loans"},
    ],
    "kinds": {},
}


# --- fetching ---------------------------------------------------------------

def fetch():
    envelope = {}
    for group, url in sorted(FILES.items()):
        envelope[group] = {
            "url": url,
            "b64": base64.b64encode(boj_ts.fetch_bytes(url)).decode("ascii"),
        }
    return json.dumps({"files": envelope}, sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _colnum(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _period(text):
    """A header cell -> the half-year's date, or None.

    Headers are either "2008/3" text or an Excel serial date (38412 is
    2005-03-01): the FSA typed the early columns as dates and the later ones
    as text. Both mean the first day of the closing month.
    """
    text = (text or "").strip()
    m = _PERIOD_TEXT.match(text)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), 1)
    try:
        serial = float(text)
    except ValueError:
        return None
    if 36000 <= serial <= 60000 and serial == int(serial):
        date = _EPOCH + datetime.timedelta(days=int(serial))
        return datetime.date(date.year, date.month, 1)
    return None


def _is_header(periods, half):
    """A row of dates is a header only if it is a calendar, not a coincidence.

    Five-digit amounts in 億円 decode as plausible serial dates too, so a row
    of income figures can look like a row of headers. A real header steps
    forward exactly twelve months per column and every column closes in the
    sheet's own month; the FSA typed a few of the serials as 31 March or
    2 September, which first-of-month normalisation already absorbs.
    """
    dates = [periods[col] for col in sorted(periods, key=_colnum)]
    if any(d.month != half for d in dates):
        return False
    return all((b.year - a.year) * 12 + b.month - a.month == 12
               for a, b in zip(dates, dates[1:]))


def _value(text):
    text = (text or "").strip().replace(",", "")
    if text in ("", "-", "－", "…", "***"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _read_sheet(grid, group, half):
    """One sheet -> [(line slug, English, unit, is_flow, order, period, value)]."""
    out = []
    header, block = None, None
    for row in sorted(grid):
        cells = grid[row]
        periods = {}
        for col in sorted(cells, key=_colnum):
            if _colnum(col) >= 5:
                period = _period(cells[col][0])
                if period:
                    periods[col] = period
        if len(periods) >= 5 and _is_header(periods, half):
            header = periods
            label = _NOISE.sub("", cells.get("B", ("",))[0])
            block = BLOCKS.get(label, block if label == "" else None)
            continue
        if header is None:
            continue
        label = None
        for col in ("B", "C", "D"):
            text = _NOISE.sub("", cells.get(col, ("",))[0])
            if text:
                label = text
                break
        if not label:
            continue
        spec = None
        if label in LINES:
            spec = LINES[label]
        elif block and (block, label) in RATIOS:
            slug, en, order = RATIOS[(block, label)]
            spec = (slug, en, "pct", False, order)
        if spec is None:
            continue
        for col, period in header.items():
            value = _value(cells.get(col, ("",))[0])
            if value is None:
                continue
            if spec[2] == "pct":
                if value >= 1.0:
                    raise ValidationError(
                        "%s %s %s: ratio %s is not a fraction; the file's "
                        "percent convention has changed" % (group, label, period, value))
                value = round(value * 100.0, 4)
            if period.month != half:
                raise ValidationError(
                    "%s: a %d月期 sheet carries a %s column" % (group, half, period))
            out.append(spec + (period, value))
    if not out:
        raise ValidationError("%s: no lines recognised" % group)
    return out


def parse(raw):
    files = json.loads(raw.decode("utf-8"))["files"]
    meta, values = {}, {}
    for group in sorted(files):
        if group not in GROUPS:
            raise ValidationError("unknown group %r in the envelope" % group)
        book = xlsx.sheets(base64.b64decode(files[group]["b64"]))
        group_en, group_ja, group_order = GROUPS[group]
        for sheet_name, grid in book.items():
            name = sheet_name.strip()
            half = 3 if "3月期" in name else 9 if "9月期" in name else None
            if half is None:
                raise ValidationError("%s: sheet %r is neither 3月期 nor 9月期" % (group, name))
            for slug, en, unit, is_flow, order, period, value in _read_sheet(grid, group, half):
                code = "%s.%s" % (group, slug)
                name_en = "%s — %s" % (group_en, en)
                name_ja = "%s %s" % (group_ja, slug)
                sort_order = group_order * 100 + order * 4
                if is_flow:
                    code += ".fy" if half == 3 else ".h1"
                    name_en += " (fiscal year)" if half == 3 else " (first half)"
                    sort_order += 0 if half == 3 else 1
                meta.setdefault(code, {
                    "code": code, "name_en": name_en, "name_ja": name_ja,
                    "unit": unit, "weight_per_10000": None, "sort_order": sort_order,
                })
                previous = values.setdefault(code, {}).get(period)
                if previous is not None and previous != value:
                    raise ValidationError(
                        "%s %s appears twice with different values (%s, %s)"
                        % (code, period, previous, value))
                values[code][period] = value
    series = sorted(meta.values(), key=lambda s: (s["sort_order"], s["code"]))
    observations = [{"code": code, "period": period, "value": value}
                    for code in sorted(values)
                    for period, value in sorted(values[code].items())]
    return series, observations


# --- validation -------------------------------------------------------------

FIRST = {"major": datetime.date(2008, 3, 1), "regional": datetime.date(2005, 3, 1)}
MIN_SERIES = 40
# Loans: the majors have run ¥240-450tn and the regionals ¥190-330tn.
LOANS_FLOOR, LOANS_CEILING = 100.0, 800.0
RATIO_CEILING = 10.0


def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for required in ("major.net-income.fy", "major.net-income.h1", "regional.net-income.fy",
                     "regional.net-income.h1", "major.loans", "regional.loans",
                     "major.npl-ratio", "regional.npl-ratio", "major.cet1-ratio-intl"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)
    if len(codes) < MIN_SERIES:
        raise ValidationError("only %d series; expected at least %d" % (len(codes), MIN_SERIES))

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    for group, first in FIRST.items():
        # The bad-loan stock is the line the FSA has carried from each file's
        # first column; loans outstanding begin a few half-years later.
        npl = by_code["%s.npl" % group]
        if min(npl) != first:
            raise ValidationError(
                "%s bad loans start %s; the file has always started %s"
                % (group, min(npl), first))
        loans = by_code["%s.loans" % group]
        periods = sorted(loans)
        for a, b in zip(periods, periods[1:]):
            if (b.year - a.year) * 12 + b.month - a.month != 6:
                raise ValidationError("%s: no half-year between %s and %s" % (group, a, b))
        for period, value in loans.items():
            if not (LOANS_FLOOR <= value <= LOANS_CEILING):
                raise ValidationError(
                    "%s %s: loans of %s 兆円 are outside the plausible range" % (group, period, value))
        for period, value in by_code["%s.npl-ratio" % group].items():
            if not (0.0 <= value <= RATIO_CEILING):
                raise ValidationError(
                    "%s %s: bad-loan ratio %s%% is outside the plausible range" % (group, period, value))

    latest = max(o["period"] for o in observations)
    return {
        "series": len(codes),
        "observations": len(observations),
        "half_years": len(set(o["period"] for o in observations)),
        "first_period": min(o["period"] for o in observations).isoformat(),
        "latest_period": latest.isoformat(),
        "latest_major_net_income_fy_jpy_100mn":
            by_code["major.net-income.fy"].get(max(by_code["major.net-income.fy"])),
        "latest_regional_net_income_fy_jpy_100mn":
            by_code["regional.net-income.fy"].get(max(by_code["regional.net-income.fy"])),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "banking",
    "name": {"en": "Bank earnings by group — major and regional banks",
             "ja": "銀行の決算の状況（主要行等・地域銀行）"},
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
    "frequency": "semiannual",
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "2005-03",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published amount or ratio, as released",
         "unit": "JPY_100mn", "trust": "official"},
        {"id": "yoy", "label": "Change on the same half-year a year earlier", "unit": "%",
         "trust": "derived",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series"],
    "cite": "/banks.html",
    "page": "/banks.html",
    "notes": [
        "Series codes are {group}.{line}: income-statement lines in 億円, loans "
        "and bad loans in 兆円, ratios in percent — each as published, never "
        "rescaled. Ratios the FSA stores as fractions are multiplied by 100 exactly.",
        "Income-statement lines are the full fiscal year on March points (.fy) "
        "and the first half on September points (.h1); they are separate series "
        "and are never spliced.",
        "The major-bank income statement is consolidated (the FSA's （連結） "
        "lines); loans, bad loans, core net business profit, equity write-offs "
        "and net income attributable to parent are marked non-consolidated by "
        "the FSA. The regional-bank file is non-consolidated throughout. The "
        "majors' 業務純益 and the regionals' 実質業務純益 are different measures "
        "and carry different codes.",
        "Capital ratios split at March 2013 into international-standard banks "
        "(total, Tier 1, CET1) and domestic-standard banks (one ratio); the "
        "single pre-split ratio is kept as capital-ratio-all and not spliced "
        "onto either.",
        "A half-year is dated to the first day of its closing month: 3月期 is "
        "YYYY-03-01 and 9月期 is YYYY-09-01.",
        "The FSA's per-bank tables for the major banks before September 2007 "
        "(02.xlsx) have a different shape and are not ingested.",
    ],
}
