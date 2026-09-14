# -*- coding: utf-8 -*-
"""Adapter: prefecture finances — MIC 都道府県決算状況調, 第1表 決算状況.

Source: 総務省, 地方財政状況調査関係資料「都道府県決算状況調」第1表 — the settled
accounts of all 47 prefectures, one workbook per fiscal year from 2002: revenue,
expenditure, the difference between them, the money carried into the next year
and the 実質収支 (real balance) that is left after it.

**Why the prefectures and not just "local government".** The GFS dataset on this
platform has local government as one consolidated sector; this one has the
geography. Japanese prefectures differ by an order of magnitude — Tokyo settles
more revenue than the twelve smallest put together — and the fiscal stress that
matters politically is a prefecture-level fact, not a national one.

**実質収支 is the number prefectures are judged on, and it is published, not
derived.** 歳入歳出差引 is simply revenue less expenditure; 実質収支 takes out
the money already committed to next year's carried-over projects, and it is the
figure the Local Autonomy Act's fiscal-health rules key off. Both come from the
file, and the two identities that link them — revenue less expenditure is the
difference, and the difference less the carry-over is the real balance — are
checked for every prefecture in every year.

**Amounts are published in ¥ thousand and stored in ¥ thousand.** Every other
fiscal dataset here is in ¥ million; this one is not rescaled, because the unit
is stable across the whole run and the platform's rule is to store what was
published. The API carries the unit on every series, and a chart that puts this
beside a central-government series has to convert.

**Column letters are not stable and are not used.** The fiscal 2002 workbook
starts its grid in column P rather than column A, and the sheet carries the
prior year and a comparison block with identically-named columns beside the
current year. Columns are found by reading the fiscal-year labels across the
header and taking the block that belongs to the year the page is for, then
checking that the five columns inside it say what they should.

**Municipalities are not in this dataset.** MIC publishes a parallel 市町村別
決算状況調 covering about 1,700 municipalities, with its own layout and its own
demographic tables. It is a dataset in its own right, not a few more rows here.
"""
import base64
import json
import re
import urllib.parse

from . import boj_ts, jp_era, juki_population, xls, xlsx


class ValidationError(Exception):
    pass


SITE = "https://www.soumu.go.jp"
INDEX_URL = SITE + "/iken/kessan_jokyo_1.html"
# The link text on a year page that leads to the first table. The Ministry
# also links 「決算の状況」 (public hospitals) and 「参考資料」 from the same
# page, so the match is anchored to the start of the label.
TABLE_LABEL = "決算状況"
_YEAR_PAGE = re.compile(
    r'href="([^"]*(?:todohuken|050411_1)[^"]*\.html)"[^>]*>(.*?)</a>',
    re.S | re.I)
# Case matters: the fiscal 2012 page links its workbook as .XLS in capitals,
# which a case-sensitive pattern misses and which then looks exactly like a
# year the Ministry never published.
_FILE = re.compile(r'href="([^"]+\.xlsx?)"[^>]*>(.*?)</a>', re.S | re.I)
_TAG = re.compile(r"<[^>]+>")

PREFECTURES = juki_population.PREFECTURES
PREF_BY_JA = dict((jp_era.normalize(ja), (code, en)) for code, ja, en in PREFECTURES)
PREF_ORDER = dict((code, i) for i, (code, _ja, _en) in enumerate(PREFECTURES))
TOTAL_JA = "合計"
TOTAL_CODE = "total"

# The five columns of the current-year block, in the order the Ministry prints
# them, with the word each column's header must contain.
MEASURES = [
    ("revenue", "歳入", "Revenue"),
    ("expenditure", "歳出", "Expenditure"),
    ("balance", "歳入歳出差引", "Revenue less expenditure"),
    ("carry-forward", "繰り越すべき財源", "Funds to be carried forward"),
    ("real-balance", "実質収支", "Real balance"),
]

_MISSING = ("", "-", "‐", "－", "―", "ー", "…", "***", "×", "x", "X")
_UNIT_CELL = re.compile(r"単位[　\s]*[：:]?[　\s]*([^）)、,\s]+)")
EXPECTED_UNIT = "千円"

FIRST_YEAR = 2002
MIN_YEARS = 20
# Every figure is a whole number of ¥1,000, so the 47 prefectures and the
# printed 合計 agree exactly; this allows a single unit of rounding and no more.
SUM_TOLERANCE = 1.0

DATASET = {
    "slug": "local-finance-jp",
    "title": "Prefecture Finances — Settled Accounts (Japan)",
    "country": "Japan",
    "agency": "Ministry of Internal Affairs and Communications",
    "agency_ja": "総務省",
    "base": None,
    "frequency": "annual",
    "description": (
        "The settled accounts of all 47 Japanese prefectures by fiscal year "
        "from 2002, in ¥ thousand as published — revenue, expenditure, the "
        "difference between them, the funds carried into the next year and the "
        "real balance that is left, with the national total. The real balance "
        "is the figure the fiscal-health rules key off, and it is taken from "
        "the Ministry's file rather than computed."
    ),
}

SOURCE = {
    "source_id": "soumu:todohuken-kessan",
    "name": "MIC — Survey of Prefectural Settled Accounts, Table 1",
    "name_ja": "総務省 都道府県決算状況調 第1表 決算状況",
    "url": INDEX_URL,
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Internal "
        "Affairs and Communications."
    ),
}

DOWNLOAD_URL = INDEX_URL + " (table 1 of every fiscal year listed)"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": ("Source: Ministry of Internal Affairs and Communications — "
                    "Survey of Prefectural Settled Accounts (都道府県決算状況調)."),
    # A fiscal year's workbook appears the autumn after the year ends, so a
    # period is about 18 months old when it is first published and about 30
    # months old the day before the next one lands. This allows that plus two
    # months; anything tighter flags the dataset as stale while it is current.
    "stale_after_days": 1_050,
    "main_series": [
        {"role": "headline", "code": "total.expenditure",
         "label": "All prefectures — expenditure", "slot": 1},
        {"role": "revenue", "code": "total.revenue",
         "label": "All prefectures — revenue", "slot": 2},
        {"role": "tokyo", "code": "13.expenditure", "label": "Tokyo", "slot": 3},
        {"role": "osaka", "code": "27.expenditure", "label": "Osaka", "slot": 4},
    ],
    "overview_tiles": [
        {"key": "spend", "type": "level", "code": "total.expenditure",
         "label": "Expenditure"},
        {"key": "revenue", "type": "level", "code": "total.revenue",
         "label": "Revenue"},
        {"key": "balance", "type": "level", "code": "total.real-balance",
         "label": "Real Balance"},
        {"key": "tokyo", "type": "level", "code": "13.expenditure",
         "label": "Tokyo"},
    ],
    "kinds": dict(
        ("%s.%s" % (area, measure), "level")
        for area in [c for c, _ja, _en in PREFECTURES] + [TOTAL_CODE]
        for measure, _w, _e in MEASURES),
}


# --- fetching ---------------------------------------------------------------

def _page(url):
    """A MIC page as text. The site is cp932; a few pages are not."""
    raw = boj_ts.fetch_bytes(url)
    for encoding in ("cp932", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", "replace")


def _label(html):
    return jp_era.normalize(_TAG.sub("", html))


def _absolute(href):
    return urllib.parse.urljoin(SITE + "/iken/", href)


def year_pages():
    """{fiscal year: page URL} for every year the index lists."""
    index = _page(INDEX_URL)
    out = {}
    for href, text in _YEAR_PAGE.findall(index):
        year = jp_era.fiscal_year(_label(text).split("年度")[0] + "年度")
        if year is None:
            continue
        out.setdefault(jp_era.check(year, text), _absolute(href))
    if len(out) < MIN_YEARS:
        raise ValidationError(
            "the index lists only %d fiscal years; expected at least %d"
            % (len(out), MIN_YEARS))
    return out


def table_urls():
    """{fiscal year: workbook URL} — table 1 of every year page."""
    out = {}
    for year, page in sorted(year_pages().items()):
        for href, text in _FILE.findall(_page(page)):
            if _label(text).startswith(TABLE_LABEL):
                out[year] = _absolute(href)
                break
        else:
            raise ValidationError(
                "the fiscal %d page (%s) has no 決算状況 workbook" % (year, page))
    return out


def fetch():
    envelope = {}
    for year, url in sorted(table_urls().items()):
        envelope[str(year)] = {
            "url": url,
            "b64": base64.b64encode(boj_ts.fetch_bytes(url)).decode("ascii"),
        }
    return json.dumps({"years": envelope}, sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _colnum(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


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


def _sheets(raw):
    """The workbook, whichever of the two Excel formats it is in."""
    reader = xlsx if raw[:2] == b"PK" else xls
    sheets = reader.sheets(raw)
    for rows in sheets.values():
        if any((cell[0] or "").strip() for row in rows.values() for cell in row.values()):
            return rows
    raise ValidationError("the workbook has no sheet with anything on it")


def _check_unit(rows, year):
    for row in sorted(rows)[:10]:
        for cell in rows[row].values():
            found = _UNIT_CELL.search(jp_era.normalize(cell[0] or ""))
            if found:
                if found.group(1) != EXPECTED_UNIT:
                    raise ValidationError(
                        "the fiscal %d workbook is published in %r, not %r"
                        % (year, found.group(1), EXPECTED_UNIT))
                return
    raise ValidationError("the fiscal %d workbook carries no 単位 cell" % year)


def _block(rows, year):
    """The five columns of the year's own block, and the row data starts at.

    The sheet prints the current year, then the prior year, then a comparison,
    all with the same column names. The fiscal-year labels across the top say
    where the current year's block starts and where it ends, and the five
    columns inside it are then checked against the words they should carry.
    """
    year_row, labels = None, {}
    for row in sorted(rows)[:12]:
        found = {}
        for col in rows[row]:
            seen = jp_era.fiscal_year(_text(rows, row, col))
            if seen is not None:
                found[col] = seen
        if len(found) >= 2:
            year_row, labels = row, found
            break
    if year_row is None:
        raise ValidationError(
            "the fiscal %d workbook has no row of fiscal-year labels" % year)
    if year not in labels.values():
        raise ValidationError(
            "the fiscal %d workbook heads its blocks %s — none of them is the "
            "year the page is for" % (year, sorted(set(labels.values()))))

    ordered = sorted(labels, key=_colnum)
    start = [col for col in ordered if labels[col] == year][0]
    after = [col for col in ordered if _colnum(col) > _colnum(start)]
    end = _colnum(after[0]) if after else None

    header_end = year_row
    for row in sorted(rows):
        if row > year_row and _value(_text(rows, row, start)) is not None:
            header_end = row
            break
    else:
        raise ValidationError("the fiscal %d workbook has no data rows" % year)

    block = [col for col in sorted(rows.get(header_end, {}), key=_colnum)
             if _colnum(col) >= _colnum(start) and (end is None or _colnum(col) < end)]
    if len(block) != len(MEASURES):
        raise ValidationError(
            "the fiscal %d block has %d columns, not the %d the table has "
            "always had" % (year, len(block), len(MEASURES)))
    for col, (measure, word, _en) in zip(block, MEASURES):
        header = "".join(jp_era.normalize(_text(rows, row, col))
                         for row in sorted(rows) if year_row - 1 <= row < header_end)
        if word not in header:
            raise ValidationError(
                "the fiscal %d workbook heads the %s column %r, which does not "
                "mention %r" % (year, measure, header, word))
    return dict(zip([m for m, _w, _e in MEASURES], block)), header_end


def _read_year(year, raw):
    """One workbook -> {(area code, measure): value}."""
    rows = _sheets(raw)
    _check_unit(rows, year)
    columns, first_data = _block(rows, year)
    label_col = sorted(rows.get(first_data, {}), key=_colnum)[0]
    if _colnum(label_col) >= _colnum(columns["revenue"]):
        label_col = None
    out, seen = {}, set()
    for row in sorted(rows):
        if row < first_data:
            continue
        label = jp_era.normalize(_text(rows, row, label_col)) if label_col else ""
        if not label:
            for col in sorted(rows[row], key=_colnum):
                if _colnum(col) < _colnum(columns["revenue"]):
                    label = jp_era.normalize(_text(rows, row, col))
                    if label:
                        break
        if not label:
            continue
        if label == TOTAL_JA:
            area = TOTAL_CODE
        elif label in PREF_BY_JA:
            area = PREF_BY_JA[label][0]
        else:
            continue            # the note under the table
        if area in seen:
            raise ValidationError(
                "the fiscal %d workbook lists %r twice" % (year, label))
        seen.add(area)
        for measure, col in columns.items():
            value = _value(_text(rows, row, col))
            if value is not None:
                out[(area, measure)] = value
    missing = set(code for code, _ja, _en in PREFECTURES) - seen
    if missing:
        raise ValidationError(
            "the fiscal %d workbook is missing %d prefectures (%s)"
            % (year, len(missing), ", ".join(sorted(missing))))
    if TOTAL_CODE not in seen:
        raise ValidationError("the fiscal %d workbook has no 合計 row" % year)
    return out


def parse(raw):
    years = json.loads(raw.decode("utf-8"))["years"]
    names = dict((code, (ja, en)) for code, ja, en in PREFECTURES)
    names[TOTAL_CODE] = ("合計", "All prefectures")
    labels = dict((measure, en) for measure, _w, en in MEASURES)
    order = dict((measure, i) for i, (measure, _w, _e) in enumerate(MEASURES))

    meta, observations = {}, []
    for year_text in sorted(years, key=int):
        year = int(year_text)
        period = jp_era.period(year)
        found = _read_year(year, base64.b64decode(years[year_text]["b64"]))
        for (area, measure), value in sorted(found.items()):
            code = "%s.%s" % (area, measure)
            name_ja, name_en = names[area]
            meta.setdefault(code, {
                "code": code,
                "name_en": "%s — %s" % (name_en, labels[measure]),
                "name_ja": "%s %s" % (name_ja, dict(
                    (m, w) for m, w, _e in MEASURES)[measure]),
                "unit": "jpy_1000", "weight_per_10000": None,
                "sort_order": PREF_ORDER.get(area, len(PREFECTURES)) * 10 + order[measure],
            })
            observations.append({"code": code, "period": period, "value": value})
    return [meta[code] for code in sorted(meta)], observations


# --- validation -------------------------------------------------------------

def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for required in ("total.revenue", "total.expenditure", "total.real-balance",
                     "13.revenue", "01.expenditure"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    periods = sorted(by_code["total.revenue"])
    if len(periods) < MIN_YEARS:
        raise ValidationError(
            "only %d fiscal years; the Ministry lists at least %d"
            % (len(periods), MIN_YEARS))
    if periods[0].year != FIRST_YEAR:
        raise ValidationError(
            "the run starts at fiscal %d, not %d" % (periods[0].year, FIRST_YEAR))
    for earlier, later in zip(periods, periods[1:]):
        if later.year - earlier.year != 1:
            raise ValidationError(
                "no workbook between fiscal %d and %d" % (earlier.year, later.year))

    areas = [code for code, _ja, _en in PREFECTURES]
    checks = 0
    for measure, _word, _en in MEASURES:
        published = by_code["total." + measure]
        for period, total in sorted(published.items()):
            parts = [by_code.get("%s.%s" % (area, measure), {}).get(period)
                     for area in areas]
            if any(part is None for part in parts):
                raise ValidationError(
                    "fiscal %d %s: a prefecture is missing" % (period.year, measure))
            if abs(sum(parts) - total) > SUM_TOLERANCE:
                raise ValidationError(
                    "fiscal %d %s: the 47 prefectures sum to %s but the printed "
                    "合計 is %s" % (period.year, measure, sum(parts), total))
            checks += 1

    # The two identities the table is built on, for every prefecture and year.
    identity_checks = 0
    for area in areas + [TOTAL_CODE]:
        for period in sorted(by_code.get("%s.revenue" % area, {})):
            got = dict((measure, by_code.get("%s.%s" % (area, measure), {}).get(period))
                       for measure, _w, _e in MEASURES)
            if None in (got["revenue"], got["expenditure"], got["balance"]):
                continue
            if abs(got["revenue"] - got["expenditure"] - got["balance"]) > SUM_TOLERANCE:
                raise ValidationError(
                    "%s fiscal %d: revenue less expenditure is not the printed "
                    "歳入歳出差引" % (area, period.year))
            identity_checks += 1
            if None in (got["carry-forward"], got["real-balance"]):
                continue
            if abs(got["balance"] - got["carry-forward"]
                   - got["real-balance"]) > SUM_TOLERANCE:
                raise ValidationError(
                    "%s fiscal %d: the difference less the carry-forward is not "
                    "the printed 実質収支" % (area, period.year))
            identity_checks += 1

    for measure in ("revenue", "expenditure"):
        for code, points in by_code.items():
            if not code.endswith("." + measure):
                continue
            for period, value in points.items():
                if value <= 0:
                    raise ValidationError(
                        "%s fiscal %d is %s — a prefecture's %s is never zero "
                        "or negative" % (code, period.year, value, measure))

    latest = max(periods)
    return {
        "series": len(codes),
        "observations": len(observations),
        "fiscal_years": len(periods),
        "first_period": str(min(periods)),
        "latest_period": str(latest),
        "total_checks": checks,
        "identity_checks": identity_checks,
        "total_expenditure_latest": by_code["total.expenditure"][latest],
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "fiscal",
    "name": {"en": "Prefecture finances — settled accounts", "ja": "都道府県決算状況調"},
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
        "as_of_supported": True, "history_from": "2002",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Published amount, ¥ thousand", "unit": "JPY_thousand",
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
    "cite": "/fiscal.html?dataset=local-finance-jp",
    "page": "/fiscal.html",
    "notes": [
        "Series codes are {prefecture JIS code}.{measure}, with total.* for the national figure. Measures are revenue, expenditure, balance (歳入歳出差引), carry-forward (翌年度に繰り越すべき財源) and real-balance (実質収支).",
        "実質収支 is the figure the Local Autonomy Act's fiscal-health rules key off, and it is taken from the Ministry's file rather than computed. The two identities that link the measures are checked for every prefecture in every year.",
        "Amounts are in ¥ thousand as published, not rescaled. Every other fiscal dataset on the platform is in ¥ million, so a chart that puts them side by side has to convert.",
        "Municipalities are not in this dataset. MIC publishes a parallel 市町村別決算状況調 covering about 1,700 municipalities with its own layout; it is a dataset in its own right.",
    ],
}
