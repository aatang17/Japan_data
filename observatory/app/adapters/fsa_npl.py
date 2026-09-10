"""Adapter: bad loans by bank group — FSA 金融再生法開示債権の状況.

Source: 金融庁 (Financial Services Agency), 金融再生法開示債権の状況等 — the
half-yearly disclosure of loans classified under the Financial Reconstruction
Act, aggregated by type of lender: city banks, the former long-term credit
banks, trust banks, the regional banks in both associations, shinkin banks,
credit co-operatives, and the totals that stack them. What is ingested is
**table 1** of every release: total credit, the disclosed-claim total and its
three tiers (bankrupt or quasi-bankrupt, doubtful, special attention), normal
claims, the bad-loan ratio, the loss booked disposing of bad loans and real
net business profit.

**Every release is a partial window, so every release is read.** A single
file carries about twenty half-years — the newest is 2016-09 to 2025-09,
the oldest 1999-03 to 2006-03 — and no file carries them all. The adapter
downloads table 1 from every release the FSA lists and stitches them, newest
release winning wherever two overlap, because a later release carries the
FSA's own restatements (its note 10 says so for 2007-09 to 2010-03). The
result runs from the 1999-03 half-year without a gap.

**Two era conventions in the headers.** Files up to 2022-02 label periods in
Heisei or Reiwa years without saying which (14年3月期 is 2002, 3年3月期 is
2021, 元年9月期 is 2019); files from 2022-08 use the Western year. A label is
resolved against the release date and the column before it, so the choice is
checked rather than guessed.

**A half-year is dated to the first day of its closing month**: 3月期 is
YYYY-03-01, 9月期 is YYYY-09-01. That is what lets the platform's twelve-month
comparison line up March with March.

**Flows are split by length, never mixed.** The FSA's note 9: the disposal
loss and real net business profit are the half-year figure at 9月期 and the
full fiscal year at 3月期. One series alternating between six and twelve
months is a sawtooth, so those two lines are stored as two series each —
`.fy` (March points, full year) and `.h1` (September points, first half).
Stocks — credit, claims, the ratio — are point-in-time and stay one series.

**Units are as published and differ by line.** Claims and credit are 億円,
rounded by the FSA to the nearest 10億; the ratio is percent; the two flows
are 兆円 to one decimal. Nothing is rescaled.

**Bank-type sub-groups appear from the 2014-08 release.** Earlier files carry
only the combined group (都銀・旧長信銀・信託), the major banks, the regional
banks, the two co-operative types and the totals; city, long-term-credit and
trust banks separately, and the two regional associations separately, begin
at 2002-03 in the newer files' back history.
"""
import base64
import datetime
import json
import re

from . import boj_ts, xlsx


class ValidationError(Exception):
    pass


INDEX_URL = "https://www.fsa.go.jp/status/npl/index.html"
_RELEASE_RE = re.compile(r'href="(/status/npl/(\d{8})\.html)"')
_TABLE1_RE = re.compile(r'href="(/status/npl/\d{8}/(?:01(?:-\d)?|data01)\.xlsx)"')

# Lender groups, keyed by the label in column A or B once whitespace is
# stripped. The first label changed once (長信銀等 → 旧長信銀) and both are
# the same aggregate.
GROUPS = {
    "都銀・旧長信銀・信託": ("city-lt-trust", "City, former long-term credit and trust banks", 0),
    "都銀・長信銀等・信託": ("city-lt-trust", "City, former long-term credit and trust banks", 0),
    "都市銀行": ("city", "City banks", 1),
    "旧長期信用銀行": ("lt-credit", "Former long-term credit banks", 2),
    "信託銀行": ("trust", "Trust banks", 3),
    "主要行": ("major", "Major banks", 4),
    "地域銀行": ("regional", "Regional banks", 5),
    "地方銀行": ("regional-1", "Regional banks (first association)", 6),
    "第二地方銀行": ("regional-2", "Regional banks (second association)", 7),
    "全国銀行": ("all-banks", "All banks", 8),
    "協同組織金融機関": ("cooperative", "Co-operative financial institutions", 9),
    "信用金庫": ("shinkin", "Shinkin banks", 10),
    "信用組合": ("shinkumi", "Credit co-operatives", 11),
    "預金取扱金融機関": ("deposit-takers", "All deposit-taking institutions", 12),
}
GROUP_JA = dict((v[0], k) for k, v in GROUPS.items() if k != "都銀・長信銀等・信託")

# The lines of table 1, keyed by the label in column C or D with whitespace
# and the bracketed unit removed. (slug, English, unit, is_flow, order)
MEASURES = {
    "総与信": ("total-credit", "Total credit", "jpy_100mn", False, 0),
    "金融再生法開示債権": ("disclosed", "Disclosed claims (FRA), total", "jpy_100mn", False, 1),
    "破産更生等債権": ("bankrupt", "Bankrupt and quasi-bankrupt claims", "jpy_100mn", False, 2),
    "危険債権": ("doubtful", "Doubtful claims", "jpy_100mn", False, 3),
    "要管理債権": ("special-attention", "Special-attention claims", "jpy_100mn", False, 4),
    "正常債権": ("normal", "Normal claims", "jpy_100mn", False, 5),
    "不良債権比率": ("npl-ratio", "Bad-loan ratio", "pct", False, 6),
    "不良債権処分損": ("disposal-loss", "Loss on disposal of bad loans", "jpy_trillion", True, 7),
    "実質業務純益": ("core-profit", "Real net business profit", "jpy_trillion", True, 8),
}
_UNIT_NOTE = re.compile(r"[（(][^）)]*[）)]")
_PERIOD = re.compile(r"^(?:(\d{4})|(元|\d{1,2}))年(3|9)月期$")
_FULLWIDTH = dict(zip("０１２３４５６７８９", "0123456789"))

DATASET = {
    "slug": "fsa-npl",
    "title": "Bad Loans by Bank Group — FRA Disclosed Claims (Japan)",
    "country": "Japan",
    "agency": "Financial Services Agency",
    "agency_ja": "金融庁",
    "base": None,
    "frequency": "semiannual",
    "description": (
        "Loans classified under the Financial Reconstruction Act, by type of "
        "lender — city, former long-term credit, trust and regional banks, "
        "shinkin banks and credit co-operatives, with the totals that stack "
        "them — every half-year from March 1999: total credit, the disclosed "
        "claims in their three tiers, the bad-loan ratio, the loss booked "
        "disposing of them and real net business profit. Stitched from every "
        "release the FSA has published, newest release winning."
    ),
}

SOURCE = {
    "source_id": "fsa:npl",
    "name": "FSA — Status of Claims Disclosed under the Financial Reconstruction Act",
    "name_ja": "金融庁 金融再生法開示債権の状況等",
    "url": "https://www.fsa.go.jp/status/npl/",
    "license_note": (
        "Financial Services Agency website terms of use (compatible with CC BY "
        "4.0): free to use with attribution to the Financial Services Agency."
    ),
}

DOWNLOAD_URL = INDEX_URL + " (table 1 of every release)"
RAW_SUFFIX = ".json"

PRESENTATION = {
    "credit_line": ("Source: Financial Services Agency — Status of claims disclosed "
                    "under the Financial Reconstruction Act (金融再生法開示債権の状況等)."),
    # The September half-year has landed the following February and the March
    # half-year between August and the following December (2024-03 came on
    # 2024-09-24, 2025-03 on 2025-12-26). The newest period is therefore up to
    # about fifteen months old the day before the next release; this allows
    # that plus two months.
    "stale_after_days": 520,
    "main_series": [
        {"role": "headline", "code": "all-banks.npl-ratio",
         "label": "Bad-loan ratio, all banks", "slot": 1},
        {"role": "major", "code": "major.npl-ratio", "label": "Major banks", "slot": 2},
        {"role": "regional", "code": "regional.npl-ratio", "label": "Regional banks", "slot": 3},
    ],
    "overview_tiles": [
        {"key": "ratio", "type": "level", "code": "all-banks.npl-ratio",
         "label": "Bad-Loan Ratio"},
        {"key": "disclosed", "type": "level", "code": "all-banks.disclosed",
         "label": "Disclosed Claims"},
        {"key": "major", "type": "level", "code": "major.npl-ratio",
         "label": "Major Banks"},
        {"key": "regional", "type": "level", "code": "regional.npl-ratio",
         "label": "Regional Banks"},
    ],
    "kinds": {},
}


# --- fetching ---------------------------------------------------------------

def _html(url):
    return boj_ts.fetch_bytes(url).decode("utf-8", "replace")


def discover():
    """{release date: table-1 URL} for every release the index lists.

    Every release page carries the same table under one of three file names
    (01.xlsx, 01-N.xlsx after a correction, data01.xlsx before 2008). A
    release with no readable table is skipped, not fatal: the two 2007 pages
    and 2006 page are the only ones without one today.
    """
    index = _html(INDEX_URL)
    pages = {}
    for path, stamp in _RELEASE_RE.findall(index):
        pages.setdefault(stamp, "https://www.fsa.go.jp" + path)
    if len(pages) < 30:
        raise ValidationError(
            "the FSA index lists only %d releases; expected at least 30" % len(pages))
    out = {}
    for stamp, page in sorted(pages.items()):
        m = _TABLE1_RE.search(_html(page))
        if m:
            out[stamp] = "https://www.fsa.go.jp" + m.group(1)
    return out


def fetch():
    """Table 1 of every release, verbatim, in one deterministic envelope."""
    files = discover()
    envelope = {}
    for stamp, url in sorted(files.items()):
        envelope[stamp] = {
            "url": url,
            "b64": base64.b64encode(boj_ts.fetch_bytes(url)).decode("ascii"),
        }
    return json.dumps({"releases": envelope}, sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _norm(text):
    return re.sub(r"[\s　]+", "", text or "")


def _colnum(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _period(label, release_year, previous):
    """A column header -> the half-year's date, era resolved by context.

    A two-digit label is Heisei or Reiwa. The candidate is the one that is
    after the previous column and not after the release itself; both fitting
    would mean an ambiguous file, which has never happened because the two
    eras are thirty years apart and a file spans about ten.
    """
    text = "".join(_FULLWIDTH.get(c, c) for c in _norm(label))
    m = _PERIOD.match(text)
    if not m:
        return None
    month = int(m.group(3))
    if m.group(1):
        return datetime.date(int(m.group(1)), month, 1)
    n = 1 if m.group(2) == "元" else int(m.group(2))
    fits = []
    for year in (1988 + n, 2018 + n):
        date = datetime.date(year, month, 1)
        if year <= release_year and (previous is None or date > previous):
            fits.append(date)
    if len(fits) != 1:
        raise ValidationError(
            "cannot place %r in an era (release %d, previous column %s)"
            % (label, release_year, previous))
    return fits[0]


def _value(text):
    text = (text or "").strip().replace(",", "")
    if text in ("", "-", "－", "…", "***", "x", "X", "△"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _read_release(stamp, raw):
    """One table-1 workbook -> [(group slug, measure key, period, value)].

    The grid is read by its labels: a header row is any row with two or more
    period labels, a group starts at a label in column A or B, and a line is
    a label in column C or D. Nothing is addressed by row number.
    """
    book = xlsx.sheets(raw)
    grid = list(book.values())[0]
    release_year = int(stamp[:4])
    out = []
    header = None
    group = None
    seen_groups = set()
    for row in sorted(grid):
        cells = grid[row]
        labels = {}
        previous = None
        for col in sorted(cells, key=_colnum):
            if _colnum(col) < 5:
                continue
            period = _period(cells[col][0], release_year, previous)
            if period:
                labels[col] = period
                previous = period
        if len(labels) >= 2:
            header = labels
            continue
        if header is None:
            continue
        for col in ("A", "B"):
            key = _norm(cells.get(col, ("",))[0])
            if key in GROUPS:
                group = GROUPS[key][0]
                seen_groups.add(group)
        line = None
        for col in ("C", "D"):
            key = _UNIT_NOTE.sub("", _norm(cells.get(col, ("",))[0]))
            if key in MEASURES:
                line = key
        if group is None or line is None:
            continue
        for col, period in header.items():
            value = _value(cells.get(col, ("",))[0])
            if value is not None:
                out.append((group, line, period, value))
    if not out:
        raise ValidationError("release %s: no table-1 values found" % stamp)
    if "all-banks" not in seen_groups:
        raise ValidationError("release %s: the 全国銀行 block is missing" % stamp)
    return out


def _series_code(group, key, period):
    slug, _en, _unit, is_flow, _order = MEASURES[key]
    code = "%s.%s" % (group, slug)
    if is_flow:
        code += ".fy" if period.month == 3 else ".h1"
    return code


def parse(raw):
    releases = json.loads(raw.decode("utf-8"))["releases"]
    values = {}      # code -> {period: value}
    origin = {}      # (code, period) -> release stamp that set it
    for stamp in sorted(releases):            # oldest first: newest wins
        entry = releases[stamp]
        for group, key, period, value in _read_release(
                stamp, base64.b64decode(entry["b64"])):
            code = _series_code(group, key, period)
            values.setdefault(code, {})[period] = value
            origin[(code, period)] = stamp

    series = []
    for code in values:
        group, slug = code.split(".")[0], code.split(".")[1]
        suffix = code.split(".")[2] if code.count(".") == 2 else None
        key = next(k for k, v in MEASURES.items() if v[0] == slug)
        _s, en, unit, _flow, order = MEASURES[key]
        group_en = next(v[1] for v in GROUPS.values() if v[0] == group)
        group_order = next(v[2] for v in GROUPS.values() if v[0] == group)
        name_en = "%s — %s" % (group_en, en)
        name_ja = "%s %s" % (GROUP_JA[group], key)
        if suffix == "fy":
            name_en += " (fiscal year)"
            name_ja += "（通期）"
        elif suffix == "h1":
            name_en += " (first half)"
            name_ja += "（中間期）"
        series.append({
            "code": code, "name_en": name_en, "name_ja": name_ja, "unit": unit,
            "weight_per_10000": None,
            "sort_order": group_order * 100 + order * 4 + (1 if suffix == "h1" else 0),
        })
    series.sort(key=lambda s: (s["sort_order"], s["code"]))
    observations = [{"code": code, "period": period, "value": value}
                    for code in sorted(values)
                    for period, value in sorted(values[code].items())]
    return series, observations


# --- validation -------------------------------------------------------------

FIRST_PERIOD = datetime.date(1999, 3, 1)
MIN_SERIES = 100
# The all-bank ratio peaked near 8.4% in 2002 and has been under 2% since
# 2010; a figure outside this band is a unit error, not a data point.
RATIO_FLOOR, RATIO_CEILING = 0.0, 15.0
# Claims are rounded to the nearest ¥1bn (10 億円) per line, so three tiers
# can miss their total by up to ¥1.5bn and the FSA's own rounding of the
# total adds another.
TIER_TOLERANCE = 25.0


def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")
    codes = set(s["code"] for s in series)
    for required in ("all-banks.npl-ratio", "all-banks.disclosed", "major.npl-ratio",
                     "regional.npl-ratio", "all-banks.total-credit"):
        if required not in codes:
            raise ValidationError("the %r series is missing" % required)
    if len(codes) < MIN_SERIES:
        raise ValidationError(
            "only %d series; expected at least %d" % (len(codes), MIN_SERIES))

    by_code, seen = {}, set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]

    ratio = by_code["all-banks.npl-ratio"]
    periods = sorted(ratio)
    if periods[0] != FIRST_PERIOD:
        raise ValidationError(
            "the all-bank series starts %s; the oldest release starts %s"
            % (periods[0], FIRST_PERIOD))
    for a, b in zip(periods, periods[1:]):
        months = (b.year - a.year) * 12 + b.month - a.month
        if months != 6:
            raise ValidationError(
                "no half-year between %s and %s — a release window was lost" % (a, b))
    for period, value in ratio.items():
        if not (RATIO_FLOOR <= value <= RATIO_CEILING):
            raise ValidationError(
                "%s: all-bank bad-loan ratio of %s%% is outside the plausible range"
                % (period, value))

    # The three tiers must add to the disclosed total, and the total must not
    # exceed total credit, for every group at every half-year.
    for code in by_code:
        if not code.endswith(".disclosed"):
            continue
        group = code[:-len(".disclosed")]
        for period, total in by_code[code].items():
            tiers = [by_code.get("%s.%s" % (group, t), {}).get(period)
                     for t in ("bankrupt", "doubtful", "special-attention")]
            if all(t is not None for t in tiers):
                if abs(sum(tiers) - total) > TIER_TOLERANCE:
                    raise ValidationError(
                        "%s %s: the three tiers sum to %s but disclosed claims are %s"
                        % (group, period, sum(tiers), total))
            credit = by_code.get("%s.total-credit" % group, {}).get(period)
            if credit is not None and total > credit:
                raise ValidationError(
                    "%s %s: disclosed claims %s exceed total credit %s"
                    % (group, period, total, credit))

    latest = max(o["period"] for o in observations)
    return {
        "series": len(codes),
        "observations": len(observations),
        "groups": len(set(c.split(".")[0] for c in codes)),
        "half_years": len(set(o["period"] for o in observations)),
        "first_period": min(o["period"] for o in observations).isoformat(),
        "latest_period": latest.isoformat(),
        "latest_all_bank_npl_ratio_pct": ratio.get(latest),
        "latest_all_bank_disclosed_jpy_100mn": by_code["all-banks.disclosed"].get(latest),
    }


MANIFEST = {
    "id": DATASET["slug"],
    "section": "banking",
    "name": {"en": "Bad loans by bank group — FRA disclosed claims",
             "ja": "金融再生法開示債権の状況（業態別）"},
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
        "as_of_supported": True, "history_from": "1999-03",
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
        "Series codes are {group}.{line}: claims and credit in 億円 as published "
        "(rounded by the FSA to the nearest 10億), the bad-loan ratio in percent, "
        "the disposal loss and real net business profit in 兆円. Units differ by "
        "line and nothing is rescaled.",
        "A half-year is dated to the first day of its closing month: 3月期 is "
        "YYYY-03-01 and 9月期 is YYYY-09-01.",
        "The disposal loss and real net business profit are the full fiscal year "
        "at March and the first half at September (FSA note 9), so each is two "
        "series — .fy on March points and .h1 on September points — never one.",
        "Every FSA release carries about twenty half-years and none carries them "
        "all. The dataset stitches table 1 of every release; where releases "
        "overlap the newest wins, which is how the FSA's own restatements of "
        "2007-09 to 2010-03 (its note 10) are carried.",
        "City, former long-term credit and trust banks separately, and the two "
        "regional associations separately, begin at 2002-03; the combined "
        "groups and totals begin at 1999-03.",
        "The major-bank figure is city banks plus trust banks; regional banks "
        "include Saitama Resona from 2003-03; all deposit-taking institutions "
        "exclude the prefectural agricultural credit federations except in the "
        "two flow lines (FSA notes 4, 5 and 7).",
    ],
}
