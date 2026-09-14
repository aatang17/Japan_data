"""Adapter: private rice inventories — MAFF 民間在庫の推移（全国）.

Source: 農林水産省, the 民間在庫の推移 table published every month alongside
the contract-price survey (same page, same release). It reports how much
brown rice the private trade is holding at the end of each month — the stock
that is neither on the farm nor in the government reserve — split by the stage
of the chain that holds it and by the age of the crop.

Why it matters: rice inventories lead the rice price by months. The stock
build through the 2025-26 rice year is what said the shortage was over well
before the advance payments were cut, and the same table is what showed the
2024 squeeze coming. It is the natural companion to `rice-prices-jp`.

**Shape.** Three stages — 出荷+販売 (the whole trade), 出荷 (shippers) and
販売 (wholesalers) — each split into the current crop and one-year-old rice,
whose sum is the stage total. Figures are 万玄米トン, ten thousand tonnes of
brown rice, as published; they are stored in that unit and never rescaled.

**A rice year runs July to June**, one row per rice year across twelve month
columns, so 「７/８年」 is July 2025 through June 2026. That is a different
year from the crop year `rice-prices-jp` uses (September to August); the two
datasets are monthly and line up month by month, which is what matters.

**MAFF prints a 対前年差 row and it is not ingested.** A year-on-year
difference is a calculation, and on this platform calculations carry their
formula rather than a badge — `/observations?measure=yoy` computes it from
the levels below, which is the same number reached the same way.

**Zero and missing are different here.** The current crop genuinely holds
zero stock in July, before the harvest, and MAFF prints 0; a month that has
not happened yet is blank. The first is a real zero, the second stays a gap.
"""
import base64
import datetime
import json
import re
import urllib.parse

from . import boj_ts, xlsx


class ValidationError(Exception):
    pass


BASE = "https://www.maff.go.jp/j/seisan/keikaku/soukatu/"
PAGE = BASE + "aitaikakaku.html"
DOWNLOAD_URL = PAGE
RAW_SUFFIX = ".json"

# Everything above this heading is the current month's release; below it is the
# archive, which carries last year's copy of the same workbook under a similar
# label. Only the current release is read.
_ARCHIVE_HEADING = "これまでに公表した資料等"
_STOCK_LABEL = re.compile(r"民間在庫の推移（速報）")
_ANCHOR = re.compile(r"<a\b[^>]*?href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.S | re.I)
_CHUNK = re.compile(r"</(?:li|p)>", re.I)
_TAGS = re.compile(r"<[^>]+>")

SHEET = "全国"

# (heading in the sheet, code stem, English stage name). The three stages are
# published as separate blocks down the one sheet.
STAGES = [
    ("（１）出荷+販売段階", "trade", "shippers and wholesalers"),
    ("（２）出荷段階", "shippers", "shippers"),
    ("（３）販売段階", "wholesalers", "wholesalers"),
]

# Within a stage, four rows repeat per rice year. 対前年差 is a calculated
# difference and is deliberately not ingested — see the module docstring.
ROW_TOTAL, ROW_NEW, ROW_OLD = "total", "new-crop", "old-crop"

_ERA_BASE = 2018                      # 令和1 = 2019
_FULLWIDTH = dict(zip("０１２３４５６７８９", "0123456789"))
_RICE_YEAR = re.compile(r"^([0-9０-９]+|元)\s*/\s*([0-9０-９]+|元)\s*年$")
_NEW_CROP = re.compile(r"^([0-9０-９]+|元)\s*年産米$")
_OLD_CROP = re.compile(r"^１?1?年古米")
_MONTH = re.compile(r"^(\d+)月$")

# Published start of the table as MAFF currently carries it.
FIRST_RICE_YEAR = 2020

DATASET = {
    "slug": "rice-inventory-jp",
    "title": "Private Rice Inventories — Japan",
    "country": "Japan",
    "agency": "Ministry of Agriculture, Forestry and Fisheries",
    "agency_ja": "農林水産省",
    "base": None,
    "frequency": "monthly",
    "description": (
        "End-of-month private-sector stocks of brown rice held by the trade, "
        "in ten thousand tonnes, monthly from July 2020. Split by the stage "
        "holding the stock — shippers, wholesalers and the two combined — and "
        "within each stage between the current crop and one-year-old rice. "
        "Published by MAFF with the monthly rice contract-price release."
    ),
}

SOURCE = {
    "source_id": "maff:minkanzaiko",
    "name": "MAFF — Private rice inventories (民間在庫の推移)",
    "name_ja": "農林水産省 民間在庫の推移",
    "url": PAGE,
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Agriculture, "
        "Forestry and Fisheries. Figures are provisional (速報) and cover "
        "private-sector stocks only — neither on-farm stocks nor the "
        "government reserve are included."
    ),
}

PRESENTATION = {
    "credit_line": ("Source: Ministry of Agriculture, Forestry and Fisheries — "
                    "Private rice inventories (民間在庫の推移)."),
    "stale_after_days": 95,
    "main_series": [
        {"role": "headline", "code": "trade.total",
         "label": "Trade stock, total", "slot": 1},
        {"role": "shippers", "code": "shippers.total",
         "label": "Shippers", "slot": 2},
        {"role": "wholesalers", "code": "wholesalers.total",
         "label": "Wholesalers", "slot": 3},
    ],
    # How much rice the trade is sitting on, how far that is off its own peak,
    # and how the two stages split it. Stocks are levels, never flows.
    "overview_tiles": [
        {"key": "total", "type": "level", "code": "trade.total",
         "label": "Trade Stock"},
        {"key": "from_peak", "type": "drawdown", "code": "trade.total",
         "label": "From Peak"},
        {"key": "shippers", "type": "level", "code": "shippers.total",
         "label": "Shippers"},
        {"key": "wholesalers", "type": "level", "code": "wholesalers.total",
         "label": "Wholesalers"},
    ],
    "kinds": dict(("%s.%s" % (stem, kind), "stock")
                  for _h, stem, _n in STAGES
                  for kind in (ROW_TOTAL, ROW_NEW, ROW_OLD)),
    "unit_label": "10k t",
}


# --- fetching ---------------------------------------------------------------

def _text(html):
    return re.sub(r"\s+", "", _TAGS.sub("", html).replace("&nbsp;", " "))


def stock_workbook_url(html, page_url):
    """The current release's inventory workbook, from the monthly release page."""
    current = html.split(_ARCHIVE_HEADING)[0]
    for chunk in _CHUNK.split(current):
        if not _STOCK_LABEL.search(_text(chunk)):
            continue
        for href, _label in _ANCHOR.findall(chunk):
            if href.lower().split("?")[0].endswith((".xls", ".xlsx")):
                return urllib.parse.urljoin(page_url, href)
    raise ValidationError(
        "no 民間在庫の推移 workbook in the current-release section of %s — the "
        "page layout changed" % page_url)


def fetch():
    """The inventory workbook, verbatim, with the URL it came from."""
    html = boj_ts.fetch_bytes(PAGE).decode("utf-8", "replace")
    url = stock_workbook_url(html, PAGE)
    return json.dumps(
        {"url": url,
         "b64": base64.b64encode(boj_ts.fetch_bytes(url)).decode("ascii")},
        sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _digits(text):
    return "".join(_FULLWIDTH.get(c, c) for c in text)


def _era_year(text):
    text = _digits(text)
    return _ERA_BASE + (1 if text == "元" else int(text))


def _label(cells, columns):
    for col in columns:
        text = re.sub(r"\s+", "", xlsx.cell_text(cells.get(col)))
        if text:
            return col, text
    return None, ""


def _number(text):
    text = (text or "").strip().replace(",", "").replace("　", "")
    if text in ("", "-", "－", "ー", "…", "‐", "―"):
        return None
    # The table writes a negative difference with the Japanese minus ▲.
    text = text.replace("▲", "-").replace("±", "")
    try:
        return float(text)
    except ValueError:
        return None


def _month_columns(grid, row):
    """{column: month number} for a stage's month header row."""
    out = {}
    for col, cell in grid[row].items():
        m = _MONTH.match(re.sub(r"\s+", "", xlsx.cell_text(cell)))
        if m:
            out[col] = int(m.group(1))
    return out


def parse(raw):
    envelope = json.loads(raw.decode("utf-8"))
    sheets = xlsx.sheets(base64.b64decode(envelope["b64"]))
    if SHEET not in sheets:
        raise ValidationError("no %r sheet; found %s" % (SHEET, sorted(sheets)))
    grid = sheets[SHEET]
    rows = sorted(grid)

    # Where each stage's block starts, in sheet order.
    starts = []
    for row in rows:
        text = re.sub(r"\s+", "", xlsx.cell_text(grid[row].get("B")))
        for heading, stem, name in STAGES:
            if text.startswith(heading):
                starts.append((row, stem, name))
    if len(starts) != len(STAGES):
        raise ValidationError(
            "found %d of the %d stage headings (%s)"
            % (len(starts), len(STAGES), [s[1] for s in starts]))

    meta, values = {}, {}
    for index, (start, stem, stage_name) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else rows[-1] + 1
        months = {}
        rice_year = None
        for row in [r for r in rows if start < r < end]:
            cells = grid[row]
            if not months:
                found = _month_columns(grid, row)
                if len(found) == 12:
                    months = found
                    continue
            col, text = _label(cells, ("B", "C", "D", "E"))
            if not text:
                continue
            year = _RICE_YEAR.match(text)
            if year:
                rice_year = _era_year(year.group(1))
                kind = ROW_TOTAL
            elif _NEW_CROP.match(text):
                kind = ROW_NEW
            elif _OLD_CROP.match(text):
                kind = ROW_OLD
            else:
                continue                       # 対前年差, notes, blank rows
            if rice_year is None:
                raise ValidationError(
                    "row %d (%s) appears before any rice-year row" % (row, text))
            if not months:
                raise ValidationError(
                    "stage %r has no month header row" % stem)

            code = "%s.%s" % (stem, kind)
            meta.setdefault(code, {
                "code": code,
                "name_en": "%s — %s" % (
                    stage_name[0].upper() + stage_name[1:],
                    {ROW_TOTAL: "total stock",
                     ROW_NEW: "current crop",
                     ROW_OLD: "one-year-old rice"}[kind]),
                "name_ja": None,
                "unit": "t10k_brown_rice",
                "weight_per_10000": None,
                "sort_order": 0,
            })
            for col, month in months.items():
                value = _number(xlsx.cell_text(cells.get(col)))
                if value is None:
                    continue
                # A rice year runs July to June: July-December sit in the
                # first named year, January-June in the next.
                year_of = rice_year if month >= 7 else rice_year + 1
                period = datetime.date(year_of, month, 1)
                previous = values.setdefault(code, {}).get(period)
                if previous is not None and previous != value:
                    raise ValidationError(
                        "%s %s is published twice with different values "
                        "(%s and %s)" % (code, period, previous, value))
                values[code][period] = value

    order = {"%s.%s" % (stem, kind): i * 3 + j
             for i, (_h, stem, _n) in enumerate(STAGES)
             for j, kind in enumerate((ROW_TOTAL, ROW_NEW, ROW_OLD))}
    for code in meta:
        meta[code]["sort_order"] = order.get(code, 99)

    series = sorted(meta.values(), key=lambda s: s["sort_order"])
    observations = [{"code": code, "period": period, "value": value}
                    for code in sorted(values)
                    for period, value in sorted(values[code].items())]
    return series, observations


# --- validation -------------------------------------------------------------

# National private stocks have run between about 60 and 350 (万トン) since
# 2020. Nothing here can be negative: a stock is a level, not a flow.
STOCK_CEILING = 1_000.0
# The two stages sum to the combined row exactly, bar rounding: MAFF rounds
# each row to whole 万トン independently.
SUM_TOLERANCE = 2.0


def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")

    codes = set(s["code"] for s in series)
    expected = set("%s.%s" % (stem, kind)
                   for _h, stem, _n in STAGES
                   for kind in (ROW_TOTAL, ROW_NEW, ROW_OLD))
    if codes != expected:
        raise ValidationError(
            "series set mismatch: %s" % sorted(codes.symmetric_difference(expected)))

    by_code, periods, seen = {}, set(), set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        if o["value"] < 0:
            raise ValidationError(
                "%s %s: a stock of %s cannot be negative"
                % (o["code"], o["period"], o["value"]))
        if o["value"] > STOCK_CEILING:
            raise ValidationError(
                "%s %s: %s万トン is outside the plausible range"
                % (o["code"], o["period"], o["value"]))
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]
        periods.add(o["period"])

    ordered = sorted(periods)
    if ordered[0] > datetime.date(FIRST_RICE_YEAR, 7, 1):
        raise ValidationError(
            "history starts %s; the published table should reach %d-07"
            % (ordered[0], FIRST_RICE_YEAR))
    for previous, current in zip(ordered, ordered[1:]):
        months = ((current.year - previous.year) * 12
                  + current.month - previous.month)
        if months != 1:
            raise ValidationError(
                "no data at all between %s and %s" % (previous, current))

    # The crop-age split does not exhaust the stage total: MAFF itemises the
    # current crop and one-year-old rice, and anything two years old or more
    # sits in the total without a row of its own. So the gate is containment,
    # not equality — the parts must never exceed the whole.
    for _h, stem, _n in STAGES:
        for period, total in by_code["%s.%s" % (stem, ROW_TOTAL)].items():
            parts = [by_code["%s.%s" % (stem, kind)].get(period)
                     for kind in (ROW_NEW, ROW_OLD)]
            if any(p is None for p in parts):
                continue
            if sum(parts) > total + SUM_TOLERANCE:
                raise ValidationError(
                    "%s %s: current crop + one-year-old rice = %s, more than "
                    "the stage total of %s" % (stem, period, sum(parts), total))

    # The two stages do sum to the combined row, at every month.
    for period, total in by_code["trade.total"].items():
        parts = [by_code["shippers.total"].get(period),
                 by_code["wholesalers.total"].get(period)]
        if any(p is None for p in parts):
            continue
        if abs(sum(parts) - total) > SUM_TOLERANCE:
            raise ValidationError(
                "%s: shippers + wholesalers = %s but the combined stage is %s"
                % (period, sum(parts), total))

    latest = ordered[-1]
    return {
        "series": len(codes),
        "observations": len(observations),
        "months": len(ordered),
        "first_period": ordered[0].isoformat(),
        "latest_period": latest.isoformat(),
        "latest_total_stock_10k_tonnes": by_code["trade.total"].get(latest),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "agriculture",
    "name": {"en": "Private rice inventories — by stage and crop age",
             "ja": "民間在庫の推移（全国）"},
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
        "as_of_supported": True, "history_from": "2020-07",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "End-of-month stock, 10,000 tonnes of brown rice",
         "unit": "tonnes_10k", "trust": "official"},
        {"id": "yoy", "label": "Change on a year earlier", "unit": "%",
         "trust": "derived",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
        {"id": "mom", "label": "Change on the previous month", "unit": "%",
         "trust": "derived",
         "calc": "(value[t] / value[t−1 month] − 1) × 100, from published values."},
        {"id": "ann3m", "label": "3-month change, annualised", "unit": "%",
         "trust": "derived",
         "calc": ("((value[t] / value[t−3 months]) ^ 4 − 1) × 100, from "
                  "published values.")},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search"],
    "cite": "/rice.html?dataset=rice-inventory-jp",
    "page": "/rice.html",
    "notes": [
        "Private-sector stocks only: rice still on the farm and the government "
        "reserve are both outside this table.",
        "A rice year runs July to June, so 「７/８年」 is July 2025 to June 2026 "
        "— a different year from the September-to-August crop year used by the "
        "contract-price dataset.",
        "The current crop is a real zero before the harvest, not a gap; a month "
        "that has not been published yet is missing and stays missing.",
        "MAFF prints a 対前年差 row. It is a calculated difference, so it is not "
        "stored — request measure=yoy, which computes it from these levels and "
        "shows its formula.",
        "The crop-age split does not add up to the stage total, and is not meant "
        "to: MAFF itemises the current crop and one-year-old rice, while rice two "
        "years old and older is inside the total with no row of its own. The "
        "residual is the difference and is never shown as zero.",
        "Shippers and wholesalers sum to the combined stage. Each row is rounded "
        "to whole 10,000 tonnes independently, so that sum can miss by a unit of "
        "rounding.",
    ],
}
