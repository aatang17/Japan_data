# -*- coding: utf-8 -*-
u"""Adapter: margin balances — JPX 信用取引現在高, weekly since August 2002.

Source: Japan Exchange Group, the two long-run tables on the 過去推移表 page of
信用取引残高等. Every Friday (or the last trading day of the week) the exchange
publishes how much stock is held long on borrowed money and how much is held
short on borrowed stock, across the Tokyo and Nagoya markets.

Why it matters: this is the leverage in the Japanese market, and the only
weekly one published free. A margin-buy balance that keeps climbing into a
rally is the overhang that turns a setback into a liquidation; a short balance
that keeps climbing is the fuel under a squeeze. The ratio between them —
信用倍率 — is the single number a Japanese equity desk quotes about
positioning. Because both sides are reported on the same day in the same units,
they can be compared to each other, which is the whole point.

**Two files, one dataset, and they check each other.** The page publishes the
same balance twice, cut two ways:

  * 信用取引現在高 — by whose account it sits in: 委託 (customers) and 自己
    (the member firm's own book), which sum to 合計.
  * 信用取引現在高（一般信用取引・制度信用取引別） — by which kind of margin
    it is: 一般信用取引 (negotiable, terms set by the broker) and 制度信用取引
    (standardised, six months, eligible for securities-finance lending), which
    also sum to 合計.

Both carry the same 合計, so the two cuts reconcile against each other as well
as within themselves. Those identities are validation gates below, and they are
also what confirms the column mapping is right — these workbooks label their
columns with merged header cells that no parser can read unambiguously.

**Shares and value are different measures.** Every balance is published twice,
as a share count in 千株 and as a value in 百万円, and each is stored in the
unit it was published in and never rescaled. They are never summed or ranked
against one another: the value column is struck at contract prices for the
account balances and at the latest close for the securities-finance ones, so
it is not a mark-to-market of the share column.

**A definition break in July 2013, disclosed on the chart, never smoothed.**
Figures up to the 2013-07-12 application date cover Tokyo, Osaka and Nagoya;
from 2013-07-19 they cover Tokyo and Nagoya only, the Osaka cash equity market
having merged into Tokyo. JPX prints this note on the file and the series is
stored exactly as published either side of it — the level steps, and the step
is real.

**The week is dated by its application date** (申込日基準), the day the margin
transaction was applied for, which is how JPX dates the whole table. It is a
Friday in 1,187 of the 1,225 weeks, and a Thursday or earlier when the market
closed for a holiday; a week with no entry is absent rather than zero.

Not ingested here: the per-issue weekly balances (銘柄別信用取引週末残高), which
are published as a separate per-issue table, and the daily balances for the
日々公表銘柄 watchlist. Both are per-company data and belong with the equity
datasets, not in a market aggregate.
"""
import base64
import datetime
import json
import re
import urllib.parse

from . import boj_ts, xls


class ValidationError(Exception):
    pass


PAGE = "https://www.jpx.co.jp/markets/statistics-equities/margin/06.html"
DOWNLOAD_URL = PAGE
RAW_SUFFIX = ".json"

_ANCHOR = re.compile(r'href="([^"]+\.xlsx?)"', re.I)

# The sheet name is the only reliable identity for each workbook: the file
# names are opaque CMS ids that change whenever JPX republishes the page.
SHEET_ACCOUNT = u"信用取引現在高"
SHEET_KIND = u"信用取引現在高（一般信用取引・制度信用取引別）"

EPOCH = datetime.date(1899, 12, 30)     # Excel day zero

# (column pair, code stem, English name). Both workbooks lay their columns out
# as alternating 株数 / 金額 pairs across one row per week; the mapping is
# asserted by the sum gates in validate(), never trusted on its own.
ACCOUNT_COLUMNS = [
    ("B", "C", "customer.sales",      "Customers' account — shares sold short"),
    ("D", "E", "customer.purchases",  "Customers' account — shares bought on margin"),
    ("F", "G", "proprietary.sales",   "Members' own account — shares sold short"),
    ("H", "I", "proprietary.purchases", "Members' own account — shares bought on margin"),
    ("J", "K", "total.sales",         "Total — shares sold short"),
    ("L", "M", "total.purchases",     "Total — shares bought on margin"),
]

KIND_COLUMNS = [
    ("B", "C", "kind.total.sales",     "Total — shares sold short"),
    ("D", "E", "kind.total.purchases", "Total — shares bought on margin"),
    ("F", "G", "negotiable.sales",     "Negotiable margin — shares sold short"),
    ("H", "I", "standardized.sales",   "Standardised margin — shares sold short"),
    ("J", "K", "negotiable.purchases", "Negotiable margin — shares bought on margin"),
    ("L", "M", "standardized.purchases", "Standardised margin — shares bought on margin"),
]

# The 合計 columns of the second workbook restate the first workbook's total.
# They are read only to check that, and are not stored as series of their own.
KIND_CHECK_ONLY = ("kind.total.sales", "kind.total.purchases")

SHARES, VALUE = "shares", "value"
UNIT_SHARES, UNIT_VALUE = "thousand shares", "jpy_million"

# The market coverage changed on this application date; see the module
# docstring. Stored as published either side of it.
MARKET_BREAK = datetime.date(2013, 7, 19)

FIRST_WEEK = datetime.date(2002, 8, 2)

DATASET = {
    "slug": "margin-jp",
    "title": "Margin Balances — Japan",
    "country": "Japan",
    "agency": "Japan Exchange Group",
    "agency_ja": "日本取引所グループ",
    "base": None,
    "frequency": "weekly",
    "description": (
        "Outstanding margin balances on the Tokyo and Nagoya markets, weekly "
        "since August 2002: stock bought on margin and stock sold short, each "
        "as a share count in thousands and a value in ¥ million, split by "
        "whose account it sits in (customers or the member firm's own book) "
        "and by which kind of margin it is (negotiable or standardised). "
        "Dated by application date, as the exchange dates them."
    ),
}

SOURCE = {
    "source_id": "jpx:margin-history",
    "name": "JPX — Outstanding margin transactions, historical (信用取引現在高 過去推移表)",
    "name_ja": "日本取引所グループ 信用取引現在高 過去推移表",
    "url": PAGE,
    "license_note": (
        "Published by Japan Exchange Group for public reference. Figures up to "
        "the 2013-07-12 application date cover the Tokyo, Osaka and Nagoya "
        "markets; from 2013-07-19 they cover Tokyo and Nagoya. Account-balance "
        "values are struck at contract prices, not marked to market."
    ),
}

PRESENTATION = {
    "credit_line": "Source: Japan Exchange Group — Outstanding margin transactions "
                   "(信用取引現在高).",
    # Published weekly, on the second business day after the Friday it covers.
    # Three weeks allows a New Year closure plus a slow republication of the
    # long-run file, which lags the weekly release by a week or two.
    "stale_after_days": 21,
    "kinds": {},
    "unit_label": "¥mn / k shares",
}


# --- fetching ---------------------------------------------------------------

def workbook_urls(html, page_url):
    u"""The .xls links on the 過去推移表 page, absolute, in page order."""
    out = []
    for href in _ANCHOR.findall(html):
        url = urllib.parse.urljoin(page_url, href)
        if url not in out:
            out.append(url)
    if len(out) < 2:
        raise ValidationError(
            "found %d workbooks on %s; the page carries two (by account and by "
            "kind of margin) — the layout changed" % (len(out), page_url))
    return out


def fetch():
    u"""Both long-run workbooks, verbatim, with the URLs they came from."""
    html = boj_ts.fetch_bytes(PAGE).decode("utf-8", "replace")
    books = []
    for url in workbook_urls(html, PAGE):
        books.append({"url": url,
                      "b64": base64.b64encode(boj_ts.fetch_bytes(url)).decode("ascii")})
    return json.dumps({"books": books}, sort_keys=True).encode("utf-8")


# --- parsing ----------------------------------------------------------------

def _squash(text):
    return re.sub(r"\s+", "", text or "")


def _number(text):
    u"""A published figure, or None. JPX writes a withheld week as '-'."""
    text = (text or "").strip().replace(",", "").replace(u"　", "")
    if text in ("", "-", u"－", u"ー", u"…", u"―"):
        return None
    text = text.replace(u"▲", "-")
    try:
        return float(text)
    except ValueError:
        return None


def _week(text):
    text = (text or "").strip()
    if not text.isdigit():
        return None
    serial = int(text)
    if serial < 30000 or serial > 80000:
        return None
    return EPOCH + datetime.timedelta(days=serial)


def _sheet(books, want):
    u"""The grid of the workbook whose first sheet is named `want`."""
    for book in books:
        try:
            sheets = xls.sheets(base64.b64decode(book["b64"]))
        except Exception as exc:                                 # noqa: BLE001
            raise ValidationError("%s is not a readable workbook: %s"
                                  % (book["url"], exc))
        if not sheets:
            continue
        name = list(sheets.keys())[0]
        if _squash(name) == _squash(want):
            return sheets[name]
    raise ValidationError(
        "no workbook on the page has a %r sheet; found %r — JPX renamed a "
        "table or changed the page" % (want, [book["url"] for book in books]))


def _read(grid, columns, label_prefix):
    u"""One workbook -> {code: {period: value}}, {code: series meta}."""
    values, meta = {}, {}
    for row in sorted(grid):
        cells = grid[row]
        period = _week(xls.cell_text(cells.get("A")) if "A" in cells else "")
        if period is None:
            continue
        for shares_col, value_col, stem, name in columns:
            for col, kind, unit, suffix in (
                    (shares_col, SHARES, UNIT_SHARES, "shares, thousands"),
                    (value_col, VALUE, UNIT_VALUE, "value, ¥ million")):
                code = "%s.%s" % (stem, kind)
                meta.setdefault(code, {
                    "code": code,
                    "name_en": "%s (%s)" % (name, suffix),
                    "name_ja": None,
                    "unit": unit,
                    "weight_per_10000": None,
                    "sort_order": 0,
                })
                number = _number(xls.cell_text(cells.get(col)) if col in cells else "")
                if number is None:
                    continue                 # a withheld week stays a gap
                previous = values.setdefault(code, {}).get(period)
                if previous is not None and previous != number:
                    raise ValidationError(
                        "%s %s is published twice with different values (%s and %s)"
                        % (code, period, previous, number))
                values[code][period] = number
    if not values:
        raise ValidationError("%s workbook carried no dated rows" % label_prefix)
    return values, meta


def parse(raw):
    envelope = json.loads(raw.decode("utf-8"))
    books = envelope["books"]

    account_values, account_meta = _read(_sheet(books, SHEET_ACCOUNT),
                                         ACCOUNT_COLUMNS, "account")
    kind_values, kind_meta = _read(_sheet(books, SHEET_KIND),
                                   KIND_COLUMNS, "kind")

    # The second workbook's 合計 columns restate the first's. They are checked
    # in validate() and then dropped: one number, one series.
    checks = {}
    for stem in KIND_CHECK_ONLY:
        for kind in (SHARES, VALUE):
            code = "%s.%s" % (stem, kind)
            checks[code] = kind_values.pop(code, {})
            kind_meta.pop(code, None)

    values = dict(account_values)
    values.update(kind_values)
    meta = dict(account_meta)
    meta.update(kind_meta)

    order = [c for _s, _v, c, _n in ACCOUNT_COLUMNS] + \
            [c for _s, _v, c, _n in KIND_COLUMNS if c not in KIND_CHECK_ONLY]
    for i, stem in enumerate(order):
        for j, kind in enumerate((SHARES, VALUE)):
            code = "%s.%s" % (stem, kind)
            if code in meta:
                meta[code]["sort_order"] = i * 2 + j

    series = sorted(meta.values(), key=lambda s: s["sort_order"])
    observations = [{"code": code, "period": period, "value": value}
                    for code in sorted(values)
                    for period, value in sorted(values[code].items())]
    # Carried to validate() through the observations themselves would be
    # impossible, so the cross-file check rides along on the module's own
    # contract: parse returns (series, observations) and validate re-derives
    # the totals from them. The restated 合計 is checked here, where it exists.
    _check_kind_split(kind_values, checks)
    _check_restated_total(values, checks)
    return series, observations


def _check_kind_split(kind_values, checks):
    u"""Within the kind workbook: 一般 + 制度 must equal its own 合計.

    Checked here rather than in validate() because that workbook's 合計 is not
    stored — the account workbook publishes the same total and is the one kept.
    Strict, because both sides come from one file and one rounding.
    """
    for side in ("sales", "purchases"):
        for kind in (SHARES, VALUE):
            whole = checks.get("kind.total.%s.%s" % (side, kind), {})
            for period, value in whole.items():
                parts = [kind_values["%s.%s.%s" % (p, side, kind)].get(period)
                         for p in ("negotiable", "standardized")]
                if any(p is None for p in parts):
                    continue
                if abs(sum(parts) - value) > SUM_TOLERANCE:
                    raise ValidationError(
                        "%s %s %s: negotiable + standardised = %s but that "
                        "workbook's own total is %s"
                        % (side, kind, period, sum(parts), value))


# The two workbooks restate the same 合計, and across 1,224 weeks × 4 measures
# they agree everywhere but four cells, all in 2003-2004 and all under half a
# percent (see KNOWN_DISAGREEMENTS). That is JPX's own inconsistency in two
# tables built from the same returns, not a parsing error, and it is disclosed
# rather than reconciled: both numbers stay as published, and the account cut
# is the one stored. The gate is therefore proportionate — a column mapped to
# the wrong field disagrees by whole multiples, never by a tenth of a percent.
# Both workbooks round independently to whole 千株 / 百万円, so a sum of two
# rounded parts can miss the rounded whole by a unit either way.
SUM_TOLERANCE = 2.0

RESTATEMENT_TOLERANCE_PCT = 0.5
RESTATEMENT_TOLERANCE_ABS = 2.0

KNOWN_DISAGREEMENTS = (
    "2003-06-13 (value, 0.43% on the short side and 0.22% on the long) and "
    "2004-03-12 (0.013% of the short balance in shares)")


def _check_restated_total(values, checks):
    u"""The second workbook's 合計 must equal the first workbook's."""
    for stem in KIND_CHECK_ONLY:
        mirror = stem[len("kind."):]
        for kind in (SHARES, VALUE):
            restated = checks.get("%s.%s" % (stem, kind), {})
            original = values.get("%s.%s" % (mirror, kind), {})
            for period, value in restated.items():
                other = original.get(period)
                if other is None:
                    continue
                allowed = max(RESTATEMENT_TOLERANCE_ABS,
                              abs(other) * RESTATEMENT_TOLERANCE_PCT / 100.0)
                if abs(value - other) > allowed:
                    raise ValidationError(
                        "%s %s %s: the two workbooks disagree on the total "
                        "(%s and %s, %.3f%%) — the column mapping is wrong or "
                        "a file was republished mid-revision"
                        % (mirror, kind, period, value, other,
                           abs(value - other) / abs(other) * 100 if other else 0))


# --- validation -------------------------------------------------------------

# The total margin-buy balance has run between roughly 1.5 and 4.5 million
# 千株 over the published history. A ceiling two orders above that catches a
# unit change without ever firing on a real market.
CEILING = 100_000_000.0

# Weeks are 7 days apart, 6 or 8 when a holiday moves the application date and
# 14 when a week is skipped entirely. Anything longer means the file lost rows.
MAX_WEEK_GAP_DAYS = 21


def validate(series, observations):
    if not observations:
        raise ValidationError("no observations parsed")

    by_code, periods, seen = {}, set(), set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        if o["value"] < 0:
            raise ValidationError(
                "%s %s: a balance of %s cannot be negative — a margin balance "
                "is a level, not a flow" % (o["code"], o["period"], o["value"]))
        if o["value"] > CEILING:
            raise ValidationError(
                "%s %s: %s is outside the plausible range; check the published "
                "unit" % (o["code"], o["period"], o["value"]))
        by_code.setdefault(o["code"], {})[o["period"]] = o["value"]
        periods.add(o["period"])

    expected = set()
    for stem in [c for _s, _v, c, _n in ACCOUNT_COLUMNS] + \
                [c for _s, _v, c, _n in KIND_COLUMNS if c not in KIND_CHECK_ONLY]:
        expected.add("%s.%s" % (stem, SHARES))
        expected.add("%s.%s" % (stem, VALUE))
    codes = set(s["code"] for s in series)
    if codes != expected:
        raise ValidationError(
            "series set mismatch: %s" % sorted(codes.symmetric_difference(expected)))

    ordered = sorted(periods)
    if ordered[0] > FIRST_WEEK:
        raise ValidationError(
            "history starts %s; the published table reaches %s"
            % (ordered[0], FIRST_WEEK))
    for previous, current in zip(ordered, ordered[1:]):
        gap = (current - previous).days
        if gap > MAX_WEEK_GAP_DAYS:
            raise ValidationError(
                "%d days with no data at all between %s and %s"
                % (gap, previous, current))

    # The identity that confirms the account workbook's column mapping: the two
    # accounts add to the published total, in both units, every week. The
    # negotiable/standardised split is checked against its own workbook's total
    # in parse(), and the two workbooks against each other there too — those
    # totals are published separately and agree to within half a percent.
    for kind in (SHARES, VALUE):
        for side in ("sales", "purchases"):
            total = by_code["total.%s.%s" % (side, kind)]
            for period, whole in total.items():
                got = [by_code["%s.%s.%s" % (p, side, kind)].get(period)
                       for p in ("customer", "proprietary")]
                if any(g is None for g in got):
                    continue
                if abs(sum(got) - whole) > SUM_TOLERANCE:
                    raise ValidationError(
                        "%s %s %s: customers + members' own = %s but the "
                        "published total is %s"
                        % (side, kind, period, sum(got), whole))

    latest = ordered[-1]
    before = [p for p in ordered if p < MARKET_BREAK]
    return {
        "series": len(codes),
        "observations": len(observations),
        "weeks": len(ordered),
        "first_period": ordered[0].isoformat(),
        "latest_period": latest.isoformat(),
        "weeks_before_market_change": len(before),
        "latest_total_purchases_k_shares": by_code["total.purchases.shares"].get(latest),
        "latest_total_sales_k_shares": by_code["total.sales.shares"].get(latest),
    }


BREAK_NOTE = (
    "Figures up to the 2013-07-12 application date cover the Tokyo, Osaka and "
    "Nagoya markets; from 2013-07-19 they cover Tokyo and Nagoya, the Osaka "
    "cash equity market having merged into Tokyo. The level steps at that "
    "week and is stored exactly as published either side of it — the break is "
    "shown on the chart rather than smoothed away.")

UNIT_NOTE = (
    "Every balance is published twice, as a share count in thousands and as a "
    "value in ¥ million, and each is stored in the unit it was published in. "
    "They are different measures and are never summed or ranked against each "
    "other. The value of an account balance is struck at contract prices, so "
    "it is not a mark-to-market of the share count.")

DATE_NOTE = (
    "A week is dated by its application date (申込日), as the exchange dates "
    "the table — a Friday in all but about forty of the weeks, and earlier "
    "when the market closed for a holiday. A week the exchange did not publish "
    "is absent, never zero.")

CUT_NOTE = (
    "The same balance is published cut two ways: by whose account it sits in "
    "(委託 customers, 自己 the member firm's own book) and by which kind of "
    "margin it is (一般 negotiable, terms set by the broker; 制度 standardised, "
    "six months and eligible for securities-finance lending). Each cut sums to "
    "the same total, which is checked at every ingest.")

RESTATEMENT_NOTE = (
    "The two workbooks publish the same total, and they agree in every week "
    "but two: " + KNOWN_DISAGREEMENTS + ". Both figures are JPX's own; the "
    "account cut is the one stored, and the discrepancy is disclosed here "
    "rather than reconciled away. An ingest fails if any week's two totals "
    "differ by more than half a percent.")

SCOPE_NOTE = (
    "Per-issue margin balances — the weekly table by company and the daily one "
    "for the watchlist issues — are not in this dataset. It is the market "
    "aggregate only.")

MANIFEST = {
    "id": DATASET["slug"],
    "section": "market",
    "name": {"en": "Margin balances — outstanding margin transactions",
             "ja": "信用取引現在高"},
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
        "as_of_supported": True, "history_from": "2002-08-02",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Outstanding balance — value in ¥ million, or the "
                                 "share count in thousands, as published",
         "unit": "JPY_million", "trust": "official"},
        {"id": "shares", "label": "Outstanding balance in thousands of shares",
         "unit": "shares_thousand", "trust": "official"},
        {"id": "ratio", "label": "Margin ratio (信用倍率)", "unit": "x",
         "trust": "derived",
         "calc": ("ratio[t] = total shares bought on margin[t] ÷ total shares "
                  "sold short[t], from published share counts — the 信用倍率 a "
                  "Japanese desk quotes. Above one means more stock is held long "
                  "on borrowed money than is held short on borrowed stock. It is "
                  "the reciprocal of the exchange's own 取組比率, which is "
                  "published per issue and divides the other way round.")},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "search": "/api/v1/%s/series" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series", "search"],
    "cite": "/margin.html",
    "page": "/margin.html",
    "notes": [CUT_NOTE, UNIT_NOTE, BREAK_NOTE, DATE_NOTE, RESTATEMENT_NOTE,
              SCOPE_NOTE],
}
