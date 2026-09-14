"""Adapter: central government debt — MOF 国債及び借入金並びに政府保証債務現在高.

Source: 財務省, 国債及び借入金並びに政府保証債務現在高 — the quarterly statement
of everything the central government owes: government bonds by tenor, the FILP
bonds, the odd non-marketable issues, borrowings, financing bills, and the
guarantees it has written. This is the ¥1,200tn number, broken into the parts
it is actually made of.

**It is a stock, and it never shares a series with a flow.** Every figure is
the amount outstanding at the end of the quarter, so it is dated to the first
day of its closing month — 2026 June is 2026-06-01 — which is what lets the
platform's twelve-month comparison put a June beside a June.

**The published file is a rolling five-year window, so the adapter keeps its
own back copies.** The Ministry replaces one file every quarter: the newest
quarter arrives and the oldest leaves, and nothing on the site archives what
left. Parsing only the current download would mean the live series silently
shortened by a quarter every quarter — the opposite of what this platform is
for. `fetch()` therefore assembles one envelope from the fresh download plus
every copy this installation has archived before, and `parse()` stitches them
with the newest file winning wherever two cover the same quarter, so the
Ministry's own revisions are respected while the history keeps growing. A
fresh installation with no archive simply starts with the five years on offer.

**「―」 is not zero.** The GX transition bonds do not exist before fiscal 2023
and the Ministry writes a dash; the FILP short-term bonds genuinely fall to
zero in 2022 and it writes 0. The two are stored differently, as they must be.

**Published in 億円 and stored in 億円.** The Ministry rounds each line to the
nearest ¥100mn, which is why its own note says the parts may not add to the
total; the adapter checks the sum against that tolerance rather than
pretending it is exact.
"""
import base64
import datetime
import json
import re

from .. import db
from . import boj_ts, jp_era, xls


class ValidationError(Exception):
    pass


TABLE_URL = "https://www.mof.go.jp/jgbs/reference/gbb/suii.xls"

# Every line of the statement, keyed by the Japanese label with its English
# gloss and the indent column it appears in. The Ministry writes both
# languages into one cell separated by a newline, so only the first line is
# matched and the English is ours, fixed, rather than whatever the file says
# that quarter.
LINES = [
    ("内国債", "domestic-bonds", "Government bonds", 0),
    ("普通国債", "general-bonds", "General bonds", 1),
    ("（うち復興債）", "general-bonds.reconstruction",
     "General bonds — of which reconstruction bonds", 2),
    ("（うちＧＸ経済移行債）", "general-bonds.gx",
     "General bonds — of which GX economy transition bonds", 2),
    ("長期国債（10年以上）", "general-bonds.long",
     "General bonds — long-term (10 years and over)", 2),
    ("中期国債（2年から5年）", "general-bonds.medium",
     "General bonds — medium-term (2 to 5 years)", 2),
    ("短期国債（1年以下）", "general-bonds.short",
     "General bonds — short-term (1 year and under)", 2),
    ("財政投融資特別会計国債", "filp-bonds", "Fiscal Investment and Loan Program bonds", 1),
    ("長期国債（10年以上）", "filp-bonds.long",
     "FILP bonds — long-term (10 years and over)", 2),
    ("中期国債（2年から5年）", "filp-bonds.medium",
     "FILP bonds — medium-term (2 to 5 years)", 2),
    ("短期国債（1年以下）", "filp-bonds.short",
     "FILP bonds — short-term (1 year and under)", 2),
    ("交付国債", "subsidy-bonds", "Subsidy bonds", 1),
    ("出資･拠出国債", "subscription-bonds", "Subscription and contribution bonds", 1),
    ("株式会社日本政策投資銀行危機対応業務国債", "dbj-crisis-bonds",
     "Bonds for the Development Bank of Japan crisis-response operations", 1),
    ("原子力損害賠償・廃炉等支援機構国債", "nuclear-compensation-bonds",
     "Bonds for the Nuclear Damage Compensation and Decommissioning Facilitation "
     "Corporation", 1),
    ("借入金", "borrowings", "Borrowings", 0),
    ("長期（1年超）", "borrowings.long", "Borrowings — long-term (over 1 year)", 2),
    ("短期（1年以下）", "borrowings.short", "Borrowings — short-term (1 year and under)", 2),
    ("政府短期証券", "financing-bills", "Financing bills", 0),
    ("合計", "total", "Total central government debt", 0),
    ("政府保証債務", "guaranteed-debt", "Government-guaranteed debt", 0),
]
# A label alone is ambiguous — 長期国債（10年以上） appears under both the
# general bonds and the FILP bonds — so a line is matched by its label *and*
# the parent heading above it.
_PARENTS = {"普通国債": "general-bonds", "財政投融資特別会計国債": "filp-bonds",
            "借入金": "borrowings"}
_SUB_LABELS = {"長期国債（10年以上）": "long", "中期国債（2年から5年）": "medium",
               "短期国債（1年以下）": "short", "長期（1年超）": "long",
               "短期（1年以下）": "short", "（うち復興債）": "reconstruction",
               "（うちＧＸ経済移行債）": "gx"}

# The lookup tables above are written the way the Ministry prints them; every
# comparison happens after jp_era.normalize, so the keys are folded once here
# rather than at each use.
_PARENTS = dict((jp_era.normalize(k), v) for k, v in _PARENTS.items())
_SUB_LABELS = dict((jp_era.normalize(k), v) for k, v in _SUB_LABELS.items())

# The total's three parts. Checked every quarter: a line silently renamed by
# the Ministry would otherwise just stop being ingested.
TOTAL_PARTS = ("domestic-bonds", "borrowings", "financing-bills")

_MISSING = ("", "-", "‐", "－", "―", "ー", "…", "***", "×", "x", "X")
_UNIT_CELL = re.compile(r"単位[：:]\s*([^）)、,\s]+)")
_HEADER_EN = re.compile(r"^(\d{4})(January|February|March|April|May|June|July|"
                        r"August|September|October|November|December)$")
_HEADER_JA = re.compile(r"^([MTSHR]|明治|大正|昭和|平成|令和)(元|\d{1,2})\.(\d{1,2})末$")
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]

MIN_QUARTERS = 20
# The Ministry rounds every line to ¥100mn and says so; the total can differ
# from its three parts by a few hundred million yen on a ¥1,200tn base.
SUM_TOLERANCE = 5.0

DATASET = {
    "slug": "govt-debt-jp",
    "title": "Central Government Debt Outstanding (Japan)",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "quarterly",
    "description": (
        "Everything Japan's central government owes, at the end of every "
        "quarter, in ¥100mn: government bonds split into general bonds and "
        "FILP bonds and then by tenor, the non-marketable issues, borrowings, "
        "financing bills and the guarantees written — with the Ministry's own "
        "total. Stocks at quarter end, dated to the first day of the closing "
        "month. History is stitched across every published edition, because "
        "the file itself carries only the last five years."
    ),
}

SOURCE = {
    "source_id": "mof:gbb",
    "name": "MOF — Central Government Debt Outstanding",
    "name_ja": "財務省 国債及び借入金並びに政府保証債務現在高",
    "url": "https://www.mof.go.jp/jgbs/reference/gbb/",
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Finance."
    ),
}

DOWNLOAD_URL = TABLE_URL
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": ("Source: Ministry of Finance — Central Government Debt "
                    "Outstanding (国債及び借入金並びに政府保証債務現在高)."),
    # Published about ten weeks after each quarter end (the June 2026 quarter
    # came on 2026-08-07), so the newest period is up to about five months old
    # the day before the next one lands. This allows that plus two months.
    "stale_after_days": 220,
    "main_series": [
        {"role": "headline", "code": "total", "label": "Total debt", "slot": 1},
        {"role": "general", "code": "general-bonds", "label": "General bonds", "slot": 2},
        {"role": "filp", "code": "filp-bonds", "label": "FILP bonds", "slot": 3},
        {"role": "bills", "code": "financing-bills", "label": "Financing bills", "slot": 4},
    ],
    "overview_tiles": [
        {"key": "total", "type": "level", "code": "total", "label": "Total Debt"},
        {"key": "general", "type": "level", "code": "general-bonds",
         "label": "General Bonds"},
        {"key": "bills", "type": "level", "code": "financing-bills",
         "label": "Financing Bills"},
        {"key": "guaranteed", "type": "level", "code": "guaranteed-debt",
         "label": "Guaranteed Debt"},
    ],
    "kinds": dict((code, "level") for _ja, code, _en, _i in LINES),
}


# --- fetching ---------------------------------------------------------------

def _archived_editions():
    """Every edition this installation has already archived, oldest first.

    The envelope written by a previous ingest holds the workbooks it knew
    about; reading the newest one back is enough to carry the whole chain
    forward, and a missing or unreadable archive is not fatal — it only means
    the history starts at the five years the Ministry currently publishes.
    """
    try:
        archived = sorted(db.RAW_DIR.glob("%s-*%s" % (DATASET["slug"], RAW_SUFFIX)))
    except OSError:
        return {}
    for path in reversed(archived):
        try:
            payload = json.loads(path.read_bytes().decode("utf-8"))
            editions = payload.get("editions")
            if isinstance(editions, dict) and editions:
                return editions
        except (OSError, ValueError):
            continue
    return {}


def fetch():
    """The fresh workbook plus every edition already archived, in one envelope.

    Keyed by the workbook's own SHA-256, so re-downloading an unchanged file
    adds nothing and the envelope is byte-identical between quarters — which
    is what lets the ingest's unchanged check skip it.
    """
    import hashlib

    editions = dict(_archived_editions())
    raw = boj_ts.fetch_bytes(TABLE_URL)
    editions[hashlib.sha256(raw).hexdigest()] = {
        "url": TABLE_URL,
        "b64": base64.b64encode(raw).decode("ascii"),
    }
    return json.dumps({"editions": editions}, sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _text(rows, row, col):
    cell = rows.get(row, {}).get(col)
    return (cell[0] if cell else "") or ""


def _label(text):
    """The Japanese half of a bilingual cell, spaces stripped."""
    return jp_era.normalize((text or "").split("\n")[0])


def _value(text):
    text = jp_era.normalize(text).replace(",", "").replace("△", "-")
    if text in _MISSING:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _check_unit(rows):
    for row in sorted(rows)[:6]:
        for cell in rows[row].values():
            found = _UNIT_CELL.search(jp_era.normalize((cell[0] or "").split("\n")[0]))
            if found:
                if found.group(1) != "億円":
                    raise ValidationError(
                        "the workbook is published in %r, not 億円" % found.group(1))
                return
    raise ValidationError("the workbook carries no 単位 cell")


def _period(header):
    """A bilingual column header -> the first day of the quarter's last month.

    Both halves are read and must agree. 「R8.6末」 and 「2026 June」 say the
    same thing two ways, and an era base read wrong would move one of them by
    thirty years — so the disagreement is the check.
    """
    parts = [p for p in (header or "").split("\n") if p.strip()]
    if len(parts) != 2:
        return None
    japanese, english = (jp_era.normalize(parts[0]), jp_era.normalize(parts[1]))
    match_en = _HEADER_EN.match(english)
    match_ja = _HEADER_JA.match(japanese)
    if not match_en or not match_ja:
        return None
    western = datetime.date(int(match_en.group(1)),
                            _MONTHS.index(match_en.group(2)) + 1, 1)
    year = jp_era.fiscal_year(match_ja.group(1) + match_ja.group(2))
    era_dated = datetime.date(year, int(match_ja.group(3)), 1)
    if era_dated != western:
        raise ValidationError(
            "column header %r reads %s in Japanese and %s in English"
            % (header.replace("\n", " / "), era_dated, western))
    return western


def _read_edition(raw):
    """One workbook -> {(code, period): value}."""
    sheets = xls.sheets(raw)
    if not sheets:
        raise ValidationError("an archived workbook has no sheets")
    rows = list(sheets.values())[0]
    _check_unit(rows)

    columns = {}
    for row in sorted(rows):
        for col, cell in rows[row].items():
            period = _period(cell[0])
            if period is not None:
                columns[col] = period
    if not columns:
        raise ValidationError("no quarter columns found — the header changed")

    # Labels are matched after the same normalisation the cells get: the
    # Ministry writes 「（うち　Ｇ　Ｘ　経　済　移　行　債）」 with full-width
    # Latin letters and ideographic spaces between every character. Comparing
    # raw text against a literal here dropped the GX bonds for every quarter
    # they exist, without a word — which is why _read_edition now insists on
    # finding every line it knows about.
    known = {}
    for label, code, _en, _indent in LINES:
        known.setdefault(jp_era.normalize(label), []).append(code)

    out, parent, found_codes = {}, None, set()
    for row in sorted(rows):
        label = None
        for col in ("A", "B", "C"):
            found = _label(_text(rows, row, col))
            if found:
                label = found
                break
        if not label or label not in known:
            continue
        if label in _PARENTS:
            parent = _PARENTS[label]
        codes = known[label]
        if len(codes) == 1:
            code = codes[0]
        else:
            suffix = _SUB_LABELS.get(label)
            code = "%s.%s" % (parent, suffix)
            if code not in codes:
                raise ValidationError(
                    "line %r at row %d has no parent heading above it" % (label, row))
        if label not in _SUB_LABELS and label not in _PARENTS:
            parent = None
        for col, period in columns.items():
            value = _value(_text(rows, row, col))
            if value is not None:
                out[(code, period)] = value
        found_codes.add(code)

    missing = sorted(set(code for _l, code, _e, _i in LINES) - found_codes)
    if missing:
        raise ValidationError(
            "the workbook has no row for %s — a line was renamed and would "
            "otherwise just stop being ingested" % ", ".join(missing))
    return out


def parse(raw):
    editions = json.loads(raw.decode("utf-8"))["editions"]
    merged = {}
    # Oldest first by the quarters it covers, so the newest edition's numbers
    # win wherever two of them carry the same quarter.
    read = []
    for sha in sorted(editions):
        found = _read_edition(base64.b64decode(editions[sha]["b64"]))
        newest = max((period for _code, period in found), default=None)
        read.append((newest, found))
    for _newest, found in sorted(read, key=lambda item: (item[0] is None, item[0])):
        merged.update(found)

    names = dict((code, (name_en, label, index))
                 for index, (label, code, name_en, _i) in enumerate(LINES))
    series = [{"code": code, "name_en": name_en, "name_ja": label,
               "unit": "jpy_100mn", "weight_per_10000": None, "sort_order": index}
              for code, (name_en, label, index) in sorted(names.items(),
                                                          key=lambda kv: kv[1][2])]
    observations = [{"code": code, "period": period, "value": value}
                    for (code, period), value in sorted(merged.items())]
    return series, observations


# --- validation -------------------------------------------------------------

def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for required in ("total", "general-bonds", "filp-bonds", "financing-bills",
                     "borrowings", "guaranteed-debt"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    total = by_code["total"]
    periods = sorted(total)
    if len(periods) < MIN_QUARTERS:
        raise ValidationError(
            "only %d quarters; the published file alone carries at least %d"
            % (len(periods), MIN_QUARTERS))
    for earlier, later in zip(periods, periods[1:]):
        months = (later.year - earlier.year) * 12 + later.month - earlier.month
        if months != 3:
            raise ValidationError(
                "no quarter between %s and %s — an edition was lost" % (earlier, later))

    for period, published in sorted(total.items()):
        component = sum(by_code.get(code, {}).get(period, 0.0) for code in TOTAL_PARTS)
        if abs(component - published) > SUM_TOLERANCE:
            raise ValidationError(
                "%s: bonds, borrowings and financing bills sum to %s but the "
                "Ministry's 合計 is %s — a line is being missed"
                % (period, component, published))

    for code, points in by_code.items():
        for period, value in points.items():
            if value < 0:
                raise ValidationError(
                    "%s %s is negative (%s) — an amount outstanding is a stock"
                    % (code, period, value))

    latest = max(periods)
    return {
        "series": len(codes),
        "observations": len(observations),
        "quarters": len(periods),
        "first_period": str(min(periods)),
        "latest_period": str(latest),
        "total_debt_latest": total[latest],
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "fiscal",
    "name": {"en": "Central government debt outstanding", "ja": "国債及び借入金並びに政府保証債務現在高"},
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
        "as_of_supported": True, "history_from": "2021-09",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Amount outstanding, ¥100mn", "unit": "JPY_100mn",
         "trust": "official"},
        {"id": "yoy", "label": "Change on the same quarter a year earlier", "unit": "%", "trust": "derived",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search"],
    "cite": "/fiscal.html?dataset=govt-debt-jp",
    "page": "/fiscal.html",
    "notes": [
        "Every figure is a stock at quarter end, dated to the first day of the closing month: the June 2026 quarter is 2026-06-01.",
        "The published workbook is a rolling five-year window — one quarter arrives and the oldest leaves, and nothing on the Ministry's site archives what left. The adapter keeps its own back copies and stitches them, newest edition winning, so the history grows instead of shrinking.",
        "「―」 is missing and 0 is zero: the GX transition bonds do not exist before fiscal 2023 and the Ministry writes a dash, while the FILP short-term bonds genuinely fall to zero in 2022.",
        "The Ministry rounds each line to ¥100mn and notes that the parts may not add to the total; the check that bonds, borrowings and financing bills sum to 合計 allows that rounding and nothing more.",
    ],
}
