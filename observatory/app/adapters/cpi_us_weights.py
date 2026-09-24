"""Adapter: US CPI relative importance — how much each item weighs in the
basket, as the BLS publishes it each December.

Source: U.S. Bureau of Labor Statistics, "Relative importance of components
in the Consumer Price Indexes: U.S. city average", one workbook per December
at bls.gov/cpi/tables/relative-importance/<year>.xlsx, Table 1, CPI-U column.
Values are percent of all items (All items = 100), to the BLS's three
decimals: shelter is about a third of the basket, eggs a rounding error.

Three things about the source shape the code here.

**It is published for December only.** The relative importance of an item is
its expenditure weight carried forward by its own price change relative to
all items, so it moves every month; the BLS publishes the December value, and
the new weights that take effect in January. One observation per item per
year, dated December.

**Rows are named, not coded.** The workbook identifies each row by the item's
English name. Every name that exactly matches an item in the CPI code list
(`cu.item`) takes that item's code — `SAH1` for Shelter, `SEFH` for Eggs —
so a weight joins to its index series (`CUUR0000` + code in cpi-us). About
27 rows ("Unsampled furniture", "Housing at school, excluding board", ...)
have no published index and so no code; they keep a stable code built from
the name, prefixed `RI-`.

**The workbooks start in December 2020.** Earlier Decembers exist (1987–2019
as text and PDF archives, 1947–1986 in one historical workbook) in layouts
that differ from year to year; they are not loaded yet. The CPI-W column and
the regional and metro tables (Tables 2–7) are not loaded either.

Public domain (US Government work, 17 U.S.C. §105).
"""
import datetime
import json
import re

from . import bls_flat, xlsx


class ValidationError(Exception):
    pass


FIRST_YEAR = 2020
URL = "https://www.bls.gov/cpi/tables/relative-importance/%d.xlsx"

DATASET = {
    "slug": "cpi-us-weights",
    "title": "Consumer Price Index — United States basket weights (relative importance, CPI-U)",
    "country": "United States",
    "agency": "U.S. Bureau of Labor Statistics",
    "agency_ja": None,
    "base": None,
    "frequency": "annual",
    "description": (
        "Relative importance of each component of the CPI for All Urban "
        "Consumers, U.S. city average, as published by the Bureau of Labor "
        "Statistics each December: percent of all items, about 320 items and "
        "aggregates, December 2020 onward. Joins to the cpi-us index series by "
        "BLS item code."
    ),
}

SOURCE = {
    "source_id": "bls:cpi-relative-importance",
    "name": "BLS Relative importance of components in the Consumer Price Indexes: U.S. city average (Table 1)",
    "name_ja": None,
    "url": "https://www.bls.gov/cpi/tables/relative-importance/home.htm",
    "license_note": ("Work of the United States Government, in the public domain "
                     "(17 U.S.C. §105). Cite the Bureau of Labor Statistics as the source."),
}

DOWNLOAD_URL = SOURCE["url"]
RAW_SUFFIX = ".json"

TILES = [
    ("shelter", "SAH1", "Shelter"),
    ("food", "SAF1", "Food"),
    ("transport", "SAT", "Transportation"),
    ("medical", "SAM", "Medical care"),
    ("energy", "SA0E", "Energy"),
    ("eggs", "SEFH", "Eggs"),
]

PRESENTATION = {
    "credit_line": "Source: U.S. Bureau of Labor Statistics.",
    # December's table arrives with the January CPI in mid-February.
    "stale_after_days": 470,
    "overview_tiles": [{"key": k, "code": c, "label": l, "type": "level"}
                       for k, c, l in TILES],
    "main_series": [{"role": k, "code": c, "label": l, "slot": i + 1}
                    for i, (k, c, l) in enumerate(TILES[:5])],
    # Every series is a share of the basket, so /observations refuses a
    # percentage change of one. The codes come from the workbook, so the
    # kind is declared once for all of them rather than listed.
    "kind_default": "rate",
}


def fetch():
    """Every December workbook from 2020, plus the CPI item list the names
    are matched against, in one deterministic envelope. A year the BLS has
    not published yet answers 404 and is simply not there."""
    import base64
    files = {}
    this_year = datetime.date.today().year
    for year in range(FIRST_YEAR, this_year + 1):
        try:
            raw = bls_flat.fetch_url(URL % year, "ri-%d.xlsx" % year, accept_prefix=b"PK")
        except bls_flat.FetchError:
            if year >= this_year - 1:
                continue       # December of last year may not be out until February
            raise
        files["%d.xlsx" % year] = {"url": URL % year,
                                   "b64": base64.b64encode(raw).decode("ascii")}
    item = bls_flat.fetch_file("cu", "cu.item")
    files["cu.item"] = {"url": bls_flat.BASE + "cu/cu.item",
                        "b64": base64.b64encode(item).decode("ascii")}
    return json.dumps({"files": files}, sort_keys=True).encode("utf-8")


def _slug(name):
    return "RI-" + re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")


def _year_rows(raw, origin):
    """One workbook -> [(indent, name, value)] from Table 1's CPI-U column."""
    sheets = xlsx.sheets(raw)
    table = sheets.get("Table 1")
    if table is None:
        raise ValidationError("%s: no 'Table 1' sheet (have %s)" % (origin, list(sheets)))
    title = xlsx.cell_text(table.get(1, {}).get("B"))
    if "U.S. city average" not in title or "December" not in title:
        raise ValidationError("%s: Table 1 title is %r" % (origin, title[:120]))
    # Column C must be the CPI-U column; the header sits in the first rows.
    header = " ".join(xlsx.cell_text(table.get(r, {}).get("C")) for r in range(1, 8))
    if "CPI-U" not in header:
        raise ValidationError("%s: column C is not CPI-U (%r)" % (origin, header))
    out = []
    for r in sorted(table):
        row = table[r]
        name = xlsx.cell_text(row.get("B")).strip()
        cell = xlsx.cell_text(row.get("C")).strip()
        if not name or not cell:
            continue
        try:
            value = float(cell)
        except ValueError:
            continue           # header and label rows
        indent = xlsx.cell_text(row.get("A")).strip()
        out.append((int(indent) if indent.isdigit() else None, name, value))
    return out


def parse(raw_bytes):
    import base64
    envelope = json.loads(raw_bytes.decode("utf-8"))["files"]
    items = bls_flat.read_table(base64.b64decode(envelope["cu.item"]["b64"]))
    by_name = dict((r["item_name"].lower(), r) for r in items)

    names, orders = {}, {}
    observations = []
    for key in sorted(k for k in envelope if k.endswith(".xlsx")):
        year = int(key[:4])
        period = datetime.date(year, 12, 1)
        seen = {}
        for pos, (_indent, name, value) in enumerate(
                _year_rows(base64.b64decode(envelope[key]["b64"]), key)):
            item = by_name.get(name.lower())
            code = item["item_code"] if item else _slug(name)
            # The BLS prints three decimals; the workbook stores the binary
            # float behind them (0.038 as 3.7999999999999999E-2).
            value = round(value, 3)
            if code in seen:
                # The same component listed twice (an aggregate repeated under
                # the special-aggregate block) must carry the same weight.
                if seen[code] != value:
                    raise ValidationError("%s: %s listed twice, %r and %r"
                                          % (key, name, seen[code], value))
                continue
            seen[code] = value
            names[code] = name
            orders.setdefault(code, pos)
            observations.append({"code": code, "period": period, "value": value})

    series = []
    for code in sorted(names, key=lambda c: (orders[c], c)):
        series.append({"code": code, "name_en": names[code], "name_ja": None,
                       "unit": "percent", "weight_per_10000": None,
                       "sort_order": len(series)})
    return series, observations


def validate(series, observations):
    years = sorted(set(o["period"] for o in observations))
    if not years or years[0] != datetime.date(FIRST_YEAR, 12, 1):
        raise ValidationError("first December is %s, expected %d" % (years[:1], FIRST_YEAR))
    for a, b in zip(years, years[1:]):
        if b.year != a.year + 1:
            raise ValidationError("a December is missing between %s and %s" % (a, b))
    for year in years:
        rows = dict((o["code"], o["value"]) for o in observations if o["period"] == year)
        if len(rows) < 280:
            raise ValidationError("%s: only %d components" % (year, len(rows)))
        if rows.get("SA0") != 100.0:
            raise ValidationError("%s: All items is %r, not 100" % (year, rows.get("SA0")))
        # The eight major groups partition all items; their weights must sum
        # to 100 within the rounding of eight three-decimal numbers.
        groups = [rows.get(c) for c in ("SAF", "SAH", "SAA", "SAT", "SAM", "SAR", "SAE", "SAG")]
        if any(g is None for g in groups):
            raise ValidationError("%s: a major group is missing" % year)
        if abs(sum(groups) - 100.0) > 0.01:
            raise ValidationError("%s: major groups sum to %.3f, not 100" % (year, sum(groups)))
        for code, v in rows.items():
            if not (0 <= v <= 100):
                raise ValidationError("%s %s: weight %r outside 0–100" % (year, code, v))
    matched = sum(1 for s in series if not s["code"].startswith("RI-"))
    if matched < 250:
        raise ValidationError("only %d components matched a CPI item code" % matched)
    latest = years[-1]
    last = dict((o["code"], o["value"]) for o in observations if o["period"] == latest)
    return {
        "series": len(series),
        "observations": len(observations),
        "decembers": len(years),
        "matched_to_cpi_codes": matched,
        "latest_period": latest.isoformat(),
        "shelter_pct": last.get("SAH1"),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "prices",
    "name": {"en": "US CPI basket weights (relative importance)",
             "ja": "米国消費者物価指数ウエイト（相対的重要度）"},
    "shape": "series",
    "summary": ("How much each item counts in the US CPI: the BLS's relative "
                "importance of every component, percent of all items, each "
                "December from 2020."),
    "source": {
        "publisher": DATASET["agency"],
        "publisher_ja": None,
        "document": SOURCE["name"],
        "url": SOURCE["url"],
        "credit": PRESENTATION["credit_line"],
        "license_note": SOURCE["license_note"],
    },
    "keys": ["series_code", "period"],
    "frequency": DATASET["frequency"],
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "2020-12",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Relative importance, percent of all items (December)",
         "unit": "%", "trust": "official"},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "summary": "/api/v1/%s/overview" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search", "summary"],
    "cite": "/us-weights.html",
    "page": "/us-weights.html",
    "notes": [
        "Percent of all items (All items = 100), not parts per 10,000 — the "
        "Japanese CPI's weight unit. Never compare the two without rescaling.",
        "One value per item per year, for December. Relative importance moves "
        "every month with relative prices; the BLS publishes December only.",
        "Codes are BLS CPI item codes (SAH1 Shelter, SEFH Eggs); the matching "
        "index is CUUR0000 + code in cpi-us. Rows with no published index "
        "carry an RI- code built from their name.",
        "A share of the basket, not a price: a percentage change of a weight is "
        "refused; the change between Decembers is in percentage points.",
        "December 2020 onward. Earlier Decembers (1947–2019) and the CPI-W, "
        "regional and metro tables are published but not yet loaded.",
    ],
}
