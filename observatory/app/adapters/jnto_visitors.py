"""Adapter: JNTO visitor arrivals — foreign visitors to Japan by market.

Source: the Japan National Tourism Organization's 「国籍/月別 訪日外客数」
workbook — one sheet per year, January 2003 to the latest month, with
~54 rows per recent year (the grand total, six regional totals, two
sub-regional groups, named markets, and residual "other" rows).

JNTO does not collect these numbers: it computes them from the Ministry
of Justice's immigration statistics, excluding foreign permanent
residents and crew and including short landings. They are still an
official statistic as published by JNTO — the trust badge is
`Official Statistic`; any share, growth rate or recovery index we draw
from them is derived and carries its formula instead.

Measure type is *people* — a count, not an index, a yen level, a stock
or a flow. `weight_per_10000` is meaningless here and stays NULL, and
these series must never be ranked or aggregated against price data.

Data facts the parser and gates rely on, all verified against the live
file on 2026-08-29:

- **The download URL rotates every month.** It is stamped with the
  release date and time (`…/20241218_1615-5.xlsx` → `20250618_1615-5`
  → `20260819_1615-5`), so the file is discovered from the statistics
  page rather than hard-coded, unlike the MOF and BOJ sources.
- **The column layout shifts in 2020.** Sheets for 2019 and earlier put
  the first month in column B; from 2020 a sub-market label column is
  inserted and months start at C. Both are parsed from the header row,
  never from fixed column letters.
- **Labels carry embedded furigana.** Read naively the shared string for
  韓国 comes back as "韓国カンコク"; the `rPh` phonetic runs are dropped.
- **The two newest months are deliberately incomplete.** At the estimate
  (推計値) stage JNTO publishes only 31 of the 54 rows, rounded to the
  nearest 100, and the regional totals are absent — so named markets do
  not sum to the headline for those months and the residual has to be
  shown, not hidden. The provisional (暫定値) release two months later
  fills in the detail; the definitive (確定値) figures follow.
- **Estimate status is encoded as italic styling**, so it is read
  exactly rather than inferred from the calendar. Those periods are
  reported in the release's validation summary; revision status is not
  a trust level and never becomes a third badge.

Revision behaviour, measured by diffing three vintages of this workbook
(December 2024, June 2025, August 2026): once finalised, history is
never revised — the 2019, 2023 and 2024 sheets are bit-identical across
vintages. The only movement is the estimate→final rounding, about
+0.006% at the headline. Vintages are still stored, because the
guardrail is unconditional, but this dataset is not sold on them.

Obligation: JNTO requires the credit line 「日本政府観光局(JNTO)」 on any
reproduction — carried in PRESENTATION and rendered on the page and in
every export.
"""
import datetime
import io
import re
import urllib.request
import zipfile
from xml.etree import ElementTree as ET


class ValidationError(Exception):
    pass


USER_AGENT = "ObservatoryIngest/0.1 (data pipeline; contact: repo owner)"

STATS_PAGE = "https://www.jnto.go.jp/statistics/data/visitors-statistics/"
SITE_ROOT = "https://www.jnto.go.jp"

# The stable page we resolve from. fetch() rewrites this to the file it
# actually downloaded, so `source_artifacts.url` records the exact
# rotating URL rather than the landing page — see fetch().
DOWNLOAD_URL = STATS_PAGE

RAW_SUFFIX = ".xlsx"   # archive the pristine workbook, openable as-is

# Anchors for link discovery: the workbook is the only .xlsx on the page
# whose label names both of these.
LINK_LABEL_TERMS = ("国籍", "訪日外客数")

# --- the market registry ----------------------------------------------------
#
# (code, name_ja, name_en, parent code, kind) in workbook order, which is
# also the display order. The Japanese label is the join key against the
# file: a label outside this table fails the ingest rather than being
# silently dropped, because a market appearing unannounced is exactly the
# change we must not miss.
#
# The hierarchy is the *current* one. It has widened twice — 中東地域
# (with GCC6) appears from 2020 and 北欧地域 from 2023; before those years
# their members sit directly under the region. Codes are stable across
# both arrangements, so the era only affects which parents exist in a
# given sheet, never what a series means.
MARKETS = [
    ("total",           "総数",             "Total",                None,        "total"),
    ("asia",            "アジア計",          "Asia",                 "total",     "region"),
    ("kr",              "韓国",             "South Korea",          "asia",      "market"),
    ("cn",              "中国",             "China",                "asia",      "market"),
    ("tw",              "台湾",             "Taiwan",               "asia",      "market"),
    ("hk",              "香港",             "Hong Kong",            "asia",      "market"),
    ("th",              "タイ",             "Thailand",             "asia",      "market"),
    ("sg",              "シンガポール",       "Singapore",            "asia",      "market"),
    ("my",              "マレーシア",         "Malaysia",             "asia",      "market"),
    ("id",              "インドネシア",       "Indonesia",            "asia",      "market"),
    ("ph",              "フィリピン",         "Philippines",          "asia",      "market"),
    ("vn",              "ベトナム",          "Vietnam",              "asia",      "market"),
    ("in",              "インド",            "India",                "asia",      "market"),
    ("mideast",         "中東地域",          "Middle East",          "asia",      "group"),
    ("il",              "イスラエル",         "Israel",               "mideast",   "market"),
    ("tr",              "トルコ",            "Turkey",               "mideast",   "market"),
    ("gcc6",            "GCC6か国",         "GCC 6 countries",      "mideast",   "market"),
    ("mo",              "マカオ",            "Macau",                "asia",      "market"),
    ("mn",              "モンゴル",          "Mongolia",             "asia",      "market"),
    ("asia-other",      "その他アジア",       "Other Asia",           "asia",      "residual"),
    ("europe",          "ヨーロッパ計",       "Europe",               "total",     "region"),
    ("gb",              "英国",             "United Kingdom",       "europe",    "market"),
    ("fr",              "フランス",          "France",               "europe",    "market"),
    ("de",              "ドイツ",            "Germany",              "europe",    "market"),
    ("it",              "イタリア",          "Italy",                "europe",    "market"),
    ("es",              "スペイン",          "Spain",                "europe",    "market"),
    ("ru",              "ロシア",            "Russia",               "europe",    "market"),
    ("nordic",          "北欧地域",          "Nordic Countries",     "europe",    "group"),
    ("se",              "スウェーデン",       "Sweden",               "nordic",    "market"),
    ("dk",              "デンマーク",         "Denmark",              "nordic",    "market"),
    ("no",              "ノルウェー",         "Norway",               "nordic",    "market"),
    ("fi",              "フィンランド",       "Finland",              "nordic",    "market"),
    ("nl",              "オランダ",          "Netherlands",          "europe",    "market"),
    ("ch",              "スイス",            "Switzerland",          "europe",    "market"),
    ("be",              "ベルギー",          "Belgium",              "europe",    "market"),
    ("pl",              "ポーランド",         "Poland",               "europe",    "market"),
    ("at",              "オーストリア",       "Austria",              "europe",    "market"),
    ("pt",              "ポルトガル",         "Portugal",             "europe",    "market"),
    ("ie",              "アイルランド",       "Ireland",              "europe",    "market"),
    ("europe-other",    "その他ヨーロッパ",    "Other Europe",         "europe",    "residual"),
    ("africa",          "アフリカ計",         "Africa",               "total",     "region"),
    ("namerica",        "北アメリカ計",       "North America",        "total",     "region"),
    ("us",              "米国",             "U.S.A.",               "namerica",  "market"),
    ("ca",              "カナダ",            "Canada",               "namerica",  "market"),
    ("mx",              "メキシコ",          "Mexico",               "namerica",  "market"),
    ("namerica-other",  "その他北アメリカ",    "Other North America",  "namerica",  "residual"),
    ("samerica",        "南アメリカ計",       "South America",        "total",     "region"),
    ("br",              "ブラジル",          "Brazil",               "samerica",  "market"),
    ("samerica-other",  "その他南アメリカ",    "Other South America",  "samerica",  "residual"),
    ("oceania",         "オセアニア計",       "Oceania",              "total",     "region"),
    ("au",              "豪州",             "Australia",            "oceania",   "market"),
    ("nz",              "ニュージーランド",    "New Zealand",          "oceania",   "market"),
    ("oceania-other",   "その他オセアニア",    "Other Oceania",        "oceania",   "residual"),
    ("stateless-other", "無国籍・その他",      "Stateless and Others", "total",     "residual"),
]

CODE_BY_JA = dict((ja, code) for code, ja, _en, _p, _k in MARKETS)
PARENT = dict((code, parent) for code, _ja, _en, parent, _k in MARKETS)
ORDER = dict((code, i) for i, (code, _ja, _en, _p, _k) in enumerate(MARKETS))

# The seven series that partition the headline. Verified exact for every
# complete month from January 2003 to July 2026.
TOP_LEVEL = ("asia", "europe", "africa", "namerica", "samerica", "oceania",
             "stateless-other")

DATASET = {
    "slug": "jnto-visitors",
    "title": "Visitor Arrivals to Japan — by market",
    "country": "Japan",
    "agency": "Japan National Tourism Organization",
    "agency_ja": "日本政府観光局（JNTO）",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Monthly foreign visitor arrivals to Japan by market, from January "
        "2003, as published by the Japan National Tourism Organization: the "
        "national total, six regional totals, and named markets down to "
        "individual countries. Computed by JNTO from Ministry of Justice "
        "immigration statistics; excludes foreign permanent residents and "
        "crew, includes landings at a port of call, in transit and cruise "
        "passengers. The two most recent months are estimates covering a "
        "subset of markets, superseded by provisional and then definitive "
        "figures."
    ),
}

SOURCE = {
    "source_id": "jnto:visitors-by-nationality-monthly",
    "name": "JNTO — Visitor arrivals by nationality and month (2003–latest)",
    "name_ja": "日本政府観光局 国籍/月別 訪日外客数",
    "url": STATS_PAGE,
    "license_note": (
        "JNTO statistics may be reproduced provided the source is credited "
        "as 「日本政府観光局(JNTO)」 / Japan National Tourism Organization. "
        "Figures are computed by JNTO from Ministry of Justice immigration "
        "statistics."
    ),
}


# --- fetch ------------------------------------------------------------------

def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def resolve_download_url():
    """Find this month's workbook on the statistics page.

    The link is date-stamped and changes with every release, so it is
    discovered rather than stored. Exactly one .xlsx on the page must
    carry a label naming both 国籍 and 訪日外客数; zero or several means
    the page has been restructured and the ingest must stop rather than
    guess, since publishing the wrong table would be worse than
    publishing nothing.
    """
    html = _get(STATS_PAGE).decode("utf-8", "replace")
    hits = []
    for href, label_html in re.findall(
            r'href="([^"]+\.xlsx)"[^>]*>(.*?)</a>', html, re.S):
        label = re.sub(r"<[^>]+>", "", label_html)
        if all(term in label for term in LINK_LABEL_TERMS):
            hits.append(href)
    hits = sorted(set(hits))
    if len(hits) != 1:
        raise ValidationError(
            "expected exactly one workbook link matching %s on %s, found %d: %r"
            % (list(LINK_LABEL_TERMS), STATS_PAGE, len(hits), hits))
    href = hits[0]
    return href if href.startswith("http") else SITE_ROOT + href


def fetch():
    """The workbook, verbatim.

    Rewrites the module's DOWNLOAD_URL to the resolved link before
    returning, so the ingest runner records the exact file fetched in
    `source_artifacts.url`. The archived artifact is the untouched
    .xlsx.
    """
    global DOWNLOAD_URL
    url = resolve_download_url()
    raw = _get(url)
    DOWNLOAD_URL = url
    return raw


# --- workbook reading -------------------------------------------------------
#
# The XLSX reader lives in xlsx.py so every Excel adapter reads files the
# same way; this source needs its italic flag, which marks provisional
# months.

from .xlsx import (shared_strings as _shared_strings,           # noqa: E402
                   italic_styles as _italic_styles,
                   sheet_targets as _sheet_targets,
                   grid as _grid)


# --- parse ------------------------------------------------------------------

_MONTH_HEADER = re.compile(r"^(\d{1,2})月$")


def _clean(text):
    """Trim, and drop the ideographic space that indents sub-market rows."""
    return (text or "").replace("　", " ").strip()


def _month_columns(sheet, year):
    """Locate the header row and map month number -> column letter.

    Driven by the header text rather than fixed columns, because the
    first month sits in B up to 2019 and in C from 2020. The growth-rate
    columns between them are simply not in the map, so they can never be
    read as values.
    """
    for rownum in sorted(sheet)[:12]:
        found = {}
        for col, (text, _ital) in sheet[rownum].items():
            m = _MONTH_HEADER.match(_clean(text))
            if m:
                found[int(m.group(1))] = col
        if len(found) >= 12:
            if sorted(found) != list(range(1, 13)):
                raise ValidationError(
                    "sheet %s: header months are %s, expected 1-12"
                    % (year, sorted(found)))
            return rownum, found
    raise ValidationError("sheet %s: no month header row found" % year)


def _parse_sheet(sheet, year):
    """One year sheet -> [(code, period, value, provisional)]."""
    header_row, month_col = _month_columns(sheet, year)
    # Labels live in A, and from 2020 also in B for sub-market rows. Where
    # B carries a month it is a value column and must not be read as a label.
    label_cols = ["A"]
    if "B" not in month_col.values():
        label_cols.append("B")

    out = []
    seen_codes = set()
    for rownum in sorted(sheet):
        if rownum <= header_row:
            continue
        row = sheet[rownum]
        label = ""
        for col in label_cols:
            cell = row.get(col)
            if cell and _clean(cell[0]):
                label = _clean(cell[0])
                break
        if not label:
            continue
        if label.startswith("注"):
            break                     # footnote block ends the table
        code = CODE_BY_JA.get(label)
        if code is None:
            raise ValidationError(
                "sheet %s row %d: unknown market label %r — the source has "
                "added or renamed a market and the registry must be updated "
                "deliberately" % (year, rownum, label))
        if code in seen_codes:
            raise ValidationError(
                "sheet %s: market %s appears twice" % (year, label))
        seen_codes.add(code)

        for month, col in month_col.items():
            cell = row.get(col)
            if cell is None:
                continue              # not published yet, or never — stays absent
            text = _clean(cell[0])
            if not text:
                continue
            try:
                value = float(text)
            except ValueError:
                raise ValidationError(
                    "sheet %s row %d %s: non-numeric value %r"
                    % (year, rownum, col, text))
            out.append((code, datetime.date(year, month, 1), value, cell[1]))
    return out


def parse(raw_bytes):
    z = zipfile.ZipFile(io.BytesIO(raw_bytes))
    shared = _shared_strings(z)
    italic_styles = _italic_styles(z)
    targets = _sheet_targets(z)

    years = sorted(name for name in targets if re.match(r"^\d{4}$", name))
    if not years:
        raise ValidationError("no year sheets in workbook")

    rows = []
    for name in years:
        sheet = _grid(z, shared, italic_styles, targets[name])
        rows.extend(_parse_sheet(sheet, int(name)))

    present = set(code for code, _p, _v, _prov in rows)
    series = []
    for code, name_ja, name_en, _parent, _kind in MARKETS:
        if code not in present:
            continue
        series.append({
            "code": code,
            "name_en": name_en,
            "name_ja": name_ja,
            "unit": "persons",
            "weight_per_10000": None,   # meaningless for a count of people
            "sort_order": ORDER[code],
        })

    observations = []
    for code, period, value, provisional in sorted(
            rows, key=lambda r: (r[1], ORDER[r[0]])):
        obs = {"code": code, "period": period, "value": value}
        if provisional:
            # Revision status, not trust: these are the 推計値 months, still
            # official, rounded to the nearest 100 and covering a subset of
            # markets. Carried through so validate() can report the periods;
            # the ingest runner ignores keys it does not know.
            obs["provisional"] = True
        observations.append(obs)
    return series, observations


# --- validate ---------------------------------------------------------------

FIRST_PERIOD = datetime.date(2003, 1, 1)

# 13,496 observations at the August 2026 release, growing by ~31–54 a
# month. A file that parses to materially less has lost sheets.
MIN_OBSERVATIONS = 13_000

# A month's arrivals for any single series. The headline peaked near
# 3.9mn; the ceiling is far above any plausible outturn and exists to
# catch a units change or a misread column, not to second-guess data.
MAX_MONTHLY = 20_000_000


def validate(series, observations):
    expected = set(code for code, _ja, _en, _p, _k in MARKETS)
    got = set(s["code"] for s in series)
    if got != expected:
        raise ValidationError(
            "market set mismatch: %s" % sorted(got.symmetric_difference(expected)))

    if len(observations) < MIN_OBSERVATIONS:
        raise ValidationError("only %d observations parsed" % len(observations))

    by_period = {}
    seen = set()
    provisional_periods = set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        if not (0 <= o["value"] <= MAX_MONTHLY):
            raise ValidationError(
                "%s %s: %s arrivals outside sanity band"
                % (o["code"], o["period"], o["value"]))
        by_period.setdefault(o["period"], {})[o["code"]] = o["value"]
        if o.get("provisional"):
            provisional_periods.add(o["period"])

    periods = sorted(by_period)
    if periods[0] != FIRST_PERIOD:
        raise ValidationError(
            "history starts %s, expected %s — a year sheet is missing"
            % (periods[0], FIRST_PERIOD))

    # Every month from the start to the latest must carry a headline: a
    # hole would otherwise pass unnoticed as "not published yet".
    latest = periods[-1]
    month = FIRST_PERIOD
    while month <= latest:
        if "total" not in by_period.get(month, {}):
            raise ValidationError("no headline value for %s" % month)
        month = (datetime.date(month.year + 1, 1, 1) if month.month == 12
                 else datetime.date(month.year, month.month + 1, 1))

    if (datetime.date.today() - latest).days > 120:
        raise ValidationError(
            "latest period %s is implausibly old for a changed file" % latest)

    # Reconciliation. The seven top-level series partition the headline
    # exactly in every complete month on record, so any drift is a
    # misread column or a market assigned to the wrong parent.
    complete_months = 0
    for period, values in by_period.items():
        if not all(code in values for code in TOP_LEVEL):
            continue                  # estimate month: detail not yet published
        complete_months += 1
        total = sum(values[code] for code in TOP_LEVEL)
        if abs(total - values["total"]) > 0.5:
            raise ValidationError(
                "%s: regions sum to %d against a headline of %d"
                % (period, total, values["total"]))

    # No parent may be exceeded by the children present. Equality is not
    # required: before 2016 the source published no residual rows, so the
    # named markets legitimately fall short of their regional total.
    for period, values in by_period.items():
        for parent in set(PARENT.values()):
            if parent is None or parent not in values:
                continue
            kids = [v for code, v in values.items() if PARENT.get(code) == parent]
            if sum(kids) - values[parent] > 0.5:
                raise ValidationError(
                    "%s: children of %s sum to %d, above the parent's %d"
                    % (period, parent, sum(kids), values[parent]))

    if complete_months < 200:
        raise ValidationError(
            "only %d months carry a full regional breakdown" % complete_months)

    return {
        "series": len(series),
        "observations": len(observations),
        "months": len(periods),
        "latest_period": latest.isoformat(),
        "headline_latest": by_period[latest]["total"],
        "complete_months": complete_months,
        # Revision status for the front end and the CSV header. These are
        # the 推計値 months: official, rounded to the nearest 100, and
        # covering a subset of markets.
        "provisional_periods": [p.isoformat() for p in sorted(provisional_periods)],
        "resolved_url": DOWNLOAD_URL,
    }


# Presentation config consumed by the API and the inbound page. The
# hierarchy lives here rather than in the schema: `series` has no parent
# column and adding one would be a core change for one dataset.
PRESENTATION = {
    "credit_line": "Source: Japan National Tourism Organization (JNTO).",
    "stale_after_days": 90,   # monthly, published ~19th of the following month
    "arrivals": {
        "headline": "total",
        "regions": list(TOP_LEVEL),
        "hierarchy": dict(
            (code, parent) for code, _ja, _en, parent, _k in MARKETS),
        "kinds": dict(
            (code, kind) for code, _ja, _en, _p, kind in MARKETS),
        # The comparison an analyst actually uses: the same month of the
        # last pre-pandemic year.
        "baseline_year": 2019,
        "feature_markets": ["cn", "kr", "tw", "hk", "us", "au"],
    },
}
