# -*- coding: utf-8 -*-
"""What a crawler that does not run JavaScript is served.

Every page here is a shell: the header is drawn by nav.js and the numbers
arrive from /api after load. A browser therefore sees a full page and a
crawler that skips JavaScript sees neither the site's links nor a single
figure. Measured before this module existed, cpi.html served 169 words, one
internal link and no data at all, against 633 words and 17 links once
scripts had run.

That gap costs more than search rank. Google renders JavaScript, but on a
second pass that a new domain waits at the back of; the crawlers behind AI
assistants mostly do not render at all, and for a product meant to be cited
those are readers too.

So three things are written into the HTML on the way out:

  * the navigation, as plain links, inside the header shell nav.js fills;
  * the latest reading, in a <noscript> block at the top of <main>;
  * a meta description, which no page had.

The links go inside the header element whose innerHTML nav.js assigns on
load (nav.js:192), and that script is synchronous and sits immediately
after the element, so a browser never paints the plain list. The figures go
in <noscript> rather than into the subtitle slot they would otherwise fit:
that slot is filled by the page script only once its fetch returns, so a
sentence placed there would be visible until the data landed and would move
the layout when it was replaced. Neither addition changes a rendered pixel,
and both state what the rendered page states — progressive enhancement, not
cloaking.

Everything is best-effort. Any failure — an unparseable nav, a dataset
without an overview, a database mid-swap — serves the file untouched rather
than failing the request. A page that renders is worth more than a page that
is perfectly annotated.
"""
import datetime
import json
import re
import threading
from urllib.parse import parse_qsl

WEB_DIR = None  # set by main, so this module imports without touching the disk

# Nav entries are `{ id: "…", label: "…", href: "…" }` with label immediately
# before href. Anchor text and destination are all a crawler needs; the
# section hierarchy is nav.js's business.
_NAV_ENTRY = re.compile(r'label:\s*"([^"]+)"\s*,\s*href:\s*"([^"]+\.html)"')
_HEADER_SHELL = re.compile(r'(<header class="site-header"[^>]*>)(\s*)(</header>)')
_MAIN_OPEN = re.compile(r'(<main\b[^>]*>)')
_HEAD_END = re.compile(r'</head>', re.IGNORECASE)
_HAS_DESC = re.compile(r'(?is)<meta[^>]+name=["\']description["\']')
_HAS_CANONICAL = re.compile(r'(?is)<link[^>]+rel=["\']canonical["\']')
_DATASET = re.compile(r'<main[^>]*\sdata-dataset="([^"]+)"')

_lock = threading.Lock()
_nav_cache = {"mtime": None, "html": ""}
_summary_cache = {}


def _escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# the navigation, as links
# ---------------------------------------------------------------------------

def nav_links_html():
    """Every destination in the site header, as plain anchors.

    Read out of nav.js rather than listed again here: that file is already
    the only place a page is named, and a second list would drift from it
    the first time a page moved.
    """
    path = WEB_DIR / "assets" / "nav.js"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return ""
    with _lock:
        if _nav_cache["mtime"] == mtime:
            return _nav_cache["html"]
    try:
        source = path.open(encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    seen, links = set(), []
    for label, href in _NAV_ENTRY.findall(source):
        if href in seen:
            continue
        seen.add(href)
        links.append('<a href="%s">%s</a>' % (_escape(href), _escape(label)))
    html = ('<nav class="site-nav-fallback">%s</nav>' % "".join(links)) if links else ""
    with _lock:
        _nav_cache["mtime"] = mtime
        _nav_cache["html"] = html
    return html


# ---------------------------------------------------------------------------
# the latest reading
# ---------------------------------------------------------------------------

def _format(value, unit):
    """A figure as a reader would write it, for text meant to be parsed.

    A plain hyphen rather than the true minus the visible tiles use, since
    this line is read by crawlers and language models rather than people.
    Large magnitudes get thousands separators and lose a meaningless
    trailing ".0" — "5,193,819 \u00a5100mn" rather than "5193819.0\u00a5100mn".
    """
    if value is None:
        return None
    unit = unit or ""
    if unit in ("%", "pp"):
        # A rate keeps its decimal: 2.0% and 2% do not say the same thing
        # about precision, and the visible tile shows the first.
        shown = "%.1f" % value
    elif abs(value) >= 1000:
        shown = "{:,.0f}".format(value)
    else:
        shown = ("%.1f" % value).rstrip("0").rstrip(".")
    # A percentage sits against its number; a named unit is a separate word.
    joiner = "" if unit in ("%", "pp") else " "
    return shown + joiner + unit if unit else shown


def summary_text(dataset):
    """One sentence carrying the dataset's headline figures, or "".

    Drawn from the same api.overview() the page's own tiles are drawn from,
    so the served sentence and the rendered tiles cannot disagree.
    """
    from . import api, db
    try:
        version = db.file_version()
    except Exception:  # noqa: BLE001 — a summary is never worth an error page
        version = None
    key = (dataset, version)
    with _lock:
        if key in _summary_cache:
            return _summary_cache[key]
    text = ""
    try:
        data = api.overview(dataset)
        period = data.get("release", {}).get("latest_period")
        parts = []
        for tile in data.get("tiles") or []:
            shown = _format(tile.get("value"), tile.get("unit"))
            if shown is not None:
                parts.append("%s %s" % (tile.get("label") or "", shown))
        if parts and period:
            when = datetime.date.fromisoformat(period).strftime("%B %Y")
            text = "Latest reading, %s: %s." % (when, "; ".join(parts))
    except Exception:  # noqa: BLE001 — see module docstring: best-effort only
        text = ""
    with _lock:
        if len(_summary_cache) > 200:
            _summary_cache.clear()
        _summary_cache[key] = text
    return text


# ---------------------------------------------------------------------------
# meta descriptions
# ---------------------------------------------------------------------------

# The snippet under a search result. Written per page because no field on the
# page says what the page is *for*: an <h1> of "Buybacks" tells a reader
# nothing they did not already know from clicking. Kept to roughly 160
# characters, which is where search engines cut.
DESCRIPTIONS = {
    "index.html":
        "Japanese official statistics and company disclosures, free and citable: "
        "consumer prices, the Bank of Japan balance sheet, trade, tourism and EDINET filings.",
    "cpi.html":
        "Japan's Consumer Price Index — headline, core and core-core inflation with "
        "contributions by expenditure group, monthly from 1970, as published by the Statistics Bureau.",
    "explorer.html":
        "Every item in Japan's CPI basket: 582 individually priced goods and services with "
        "their weights and year-over-year rates, searchable, monthly from 1970.",
    "cpi-sa.html":
        "Japan's Consumer Price Index as seasonally adjusted by the Statistics Bureau, "
        "with month-over-month and three-month annualized rates.",
    "cpi-long.html":
        "Japan's Consumer Price Index back to August 1946 — all items less imputed rent, "
        "the longest continuous run the Statistics Bureau publishes.",
    "goods-services.html":
        "Japan's CPI split into goods and services — the cut that separates traded-goods "
        "prices from domestic wage-driven ones, monthly from the Statistics Bureau.",
    "tokyo.html":
        "Tokyo ward-area CPI, published mid-month as an advance read on national Japanese "
        "inflation two weeks before the national figure.",
    "macro.html":
        "Japan's macro picture on one page: consumer prices, the Bank of Japan balance sheet, "
        "the JGB yield curve and bank credit, from official sources.",
    "boj.html":
        "The Bank of Japan's balance sheet — JGB holdings, the monetary base and current "
        "account balances, in ¥100mn, from the BOJ's own time-series data.",
    "rates.html":
        "The Japanese government bond yield curve — every published maturity from 1 year to "
        "40, daily, from Ministry of Finance data.",
    "banks.html":
        "Japanese banks — non-performing loans, earnings and per-bank statements, from the "
        "Financial Services Agency and the Japanese Bankers Association.",
    "gdp.html":
        "Japan's quarterly GDP and its expenditure components, from Cabinet Office national "
        "accounts.",
    "fiscal.html":
        "Japan's public finances — the general account budget and settlement since 1875, tax "
        "receipts against budget, spending by policy purpose and ministry, government debt, the "
        "whole of government on the IMF GFS basis, and all 47 prefectures.",
    "semis.html":
        "Japan's semiconductor trade — exports and imports by partner country and product, "
        "monthly, from Ministry of Finance customs data.",
    "autos.html":
        "Japan's motor vehicle trade — exports and imports by partner country, monthly, from "
        "Ministry of Finance customs data.",
    "energy.html":
        "Japan's energy imports — crude oil, LNG and coal by source country, monthly, from "
        "Ministry of Finance customs data.",
    "machinery.html":
        "Japan's machinery trade — exports and imports by partner country, monthly, from "
        "Ministry of Finance customs data.",
    "pharma.html":
        "Japan's pharmaceutical trade — exports and imports by partner country, monthly, from "
        "Ministry of Finance customs data.",
    "food.html":
        "Japan's food trade — imports and exports by partner country, monthly, from Ministry "
        "of Finance customs data.",
    "population.html":
        "Japan's population by prefecture from the resident register — levels and change, "
        "including the natural and migration components.",
    "representation.html":
        "Vote weight in Japan's House of Councillors: electors per seat by constituency, and "
        "how far apart the best and worst represented are.",
    "inbound.html":
        "Visitor arrivals to Japan by nationality, monthly, from Japan National Tourism "
        "Organization data.",
    "accommodation.html":
        "Guest nights and occupancy in Japanese accommodation, by prefecture and lodging type, "
        "from the Japan Tourism Agency survey.",
    "lodging-regions.html":
        "Guest nights in Japan by region and visitor nationality, showing where inbound "
        "travel actually lands.",
    "rice.html":
        "Japanese rice and farm prices — private rice inventories by stage and crop age, and "
        "the price indices for what farmers sell and buy.",
    "ja.html":
        "Japan's agricultural co-operatives by segment — where JA actually earns, from "
        "banking and insurance to farm marketing, and what farm guidance costs.",
    "equities.html":
        "Japanese listed companies from their own EDINET filings: cross-shareholdings, "
        "boards and pay, AGM votes, buybacks and financial statements.",
    "holdings.html":
        "Japanese cross-shareholdings (政策保有株式) as filed in annual securities reports — "
        "who holds whom, at what value, and what is being unwound.",
    "stakes.html":
        "Japanese 5% filings (大量保有報告書) — who crossed the disclosure threshold in a "
        "listed company, when, and in which direction.",
    "ownership.html":
        "The ten largest shareholders of Japanese listed companies, as filed in each "
        "company's annual securities report.",
    "governance.html":
        "Boards and pay at Japanese listed companies — directors, independence and officer "
        "remuneration, as filed on EDINET.",
    "agm.html":
        "AGM voting results at Japanese listed companies — director approval rates and "
        "proposal outcomes, from extraordinary reports.",
    "buyback.html":
        "Share buybacks by Japanese listed companies — programmes announced and monthly "
        "progress, from EDINET filings.",
    "financials.html":
        "Financial statements of Japanese listed companies as tagged on EDINET, with the "
        "five-year summary and ratios calculated from them.",
    "company.html":
        "One Japanese listed company across every dataset here: ownership, board, pay, "
        "buybacks, financials, facilities and customers.",
    "screener.html":
        "Screen Japanese listed companies on financial and governance measures taken from "
        "their own EDINET filings.",
    "cohorts.html":
        "Compare Japanese listed companies as peer groups — one measure ranked across a "
        "cohort you pick or one already defined.",
    "facilities.html":
        "Major facilities and land held by Japanese listed companies, as filed: sites, book "
        "value and rented floor space.",
    "customers.html":
        "Named customers and supplier dependency at Japanese listed companies, from segment "
        "disclosures in annual reports.",
    "corporate.html":
        "Corporate finance aggregates for Japan drawn from company filings.",
    "datasets.html":
        "Every dataset on the platform, what each covers, how far back it runs and when it "
        "was last updated.",
    "methodology.html":
        "How every figure here is calculated: formulas for each derived rate, what is "
        "official and what is computed, and the known limitations.",
    "manual.html":
        "Use this data from an AI assistant: what the tools do, what they return and how to "
        "check an answer against the published numbers.",
    "connect.html":
        "Connect an AI assistant to Japanese official statistics and company filings over "
        "MCP, with every answer traceable to a published figure.",
    "api.html":
        "The read-only JSON API for Japanese statistics and company filings. No key, stable "
        "URLs, one contract across every dataset.",
}


# ---------------------------------------------------------------------------
# entity pages
# ---------------------------------------------------------------------------
#
# company.html is 4,232 pages wearing one page's clothes. Every securities
# code served the same <title>, the same description and an <h1> reading
# "Company Profile", because all three live in the file and only the query
# string says which company was asked for. To a crawler that is one page
# repeated, and a search engine that decides it has seen a page before does
# not index the other 4,231.
#
# So a company page states, before any script runs, which company it is:
# the name in the title and the h1, and the filed facts a person would have
# searched for in the description and a <noscript> line. Everything here is
# as-filed — names, the report behind them, counts of rows in it — so no
# figure needs a badge it cannot carry, and the page script overwrites the
# h1 with the same name it already holds.

_TITLE_TAG = re.compile(r'(?is)<title>.*?</title>')
_CO_NAME_H1 = re.compile(r'(?is)(<h1[^>]*\sid=["\']co-name["\'][^>]*>)(.*?)(</h1>)')
# Every sec_code in the file is four characters; anything else is a typed URL
# and gets the plain shell rather than a database lookup.
_SEC_CODE = re.compile(r'^[0-9A-Za-z]{4}$')
_SPACE = re.compile(r'[\s\u3000]+')

_CREDIT = ("Source: company filings on EDINET "
           "(Financial Services Agency of Japan).")

_company_cache = {}
_entity_cache = {}


def _equity_version():
    from . import equity_api
    return equity_api.file_version()


def _macro_version():
    from . import db
    return db.file_version()


def _one(sql, params):
    """One row from the equity database, or None."""
    from . import equity_api
    return equity_api._cur().execute(sql, params).fetchone()


def _one_macro(sql, params):
    """One row from the macro database, or None."""
    from . import db
    return db.read_cursor().execute(sql, params).fetchone()


def _cached(key, version_fn, build):
    """build()'s answer, remembered until the database it came from changes.

    One cache for every entity view, keyed by the view's own name as well as
    the entity, so a company's holdings line and its AGM line never collide.
    """
    try:
        version = version_fn()
    except Exception:  # noqa: BLE001 — never worth an error page
        version = None
    full = key + (version,)
    with _lock:
        if full in _entity_cache:
            return _entity_cache[full]
    try:
        value = build()
    except Exception:  # noqa: BLE001 — see module docstring: best-effort only
        value = None
    with _lock:
        if len(_entity_cache) > 20000:
            _entity_cache.clear()
        _entity_cache[full] = value
    return value

# One trip for the identity and the three counts a reader searches by. The
# counts come off the latest annual report's doc_id, which is the filing the
# page itself renders, so the sentence and the tables cannot disagree.
_COMPANY_SQL = """
WITH latest AS (
  SELECT doc_id, sec_code, filer_name, filer_name_en, period_end, filed_date
  FROM eq_filings WHERE sec_code = ?
  ORDER BY period_end DESC NULLS LAST, filed_date DESC NULLS LAST LIMIT 1)
SELECT l.filer_name, l.filer_name_en, l.period_end, l.filed_date, l.doc_id,
       e.name_en, e.name_ja, e.industry,
       (SELECT count(*) FROM eq_holdings h WHERE h.doc_id = l.doc_id),
       (SELECT count(*) FROM eq_board b WHERE b.doc_id = l.doc_id),
       (SELECT count(*) FROM eq_major_shareholders m WHERE m.doc_id = l.doc_id)
FROM latest l
LEFT JOIN (SELECT sec_code, any_value(name_en) AS name_en,
                  any_value(name_ja) AS name_ja, any_value(industry) AS industry
           FROM eq_entities WHERE sec_code IS NOT NULL GROUP BY sec_code) e
  ON e.sec_code = l.sec_code
"""


def _clean(text):
    """Filed names carry ideographic spaces and doubled ones. Titles do not."""
    return _SPACE.sub(" ", (text or "").strip())


def company_meta(code):
    """Title, description, h1 and a noscript line for one company, or None.

    None whenever the code is not one we hold a filing for, which is the
    honest answer for a typed URL and leaves the page exactly as it shipped.
    """
    if not code or not _SEC_CODE.match(code):
        return None
    from . import equity_api
    try:
        version = equity_api.file_version()
    except Exception:  # noqa: BLE001 — never worth an error page
        version = None
    key = (code, version)
    with _lock:
        if key in _company_cache:
            return _company_cache[key]
    meta = None
    try:
        meta = _company_meta(code)
    except Exception:  # noqa: BLE001 — see module docstring: best-effort only
        meta = None
    with _lock:
        # The whole universe is about four thousand entries of a few hundred
        # bytes; the cap is a guard against a flood of invalid codes, not a
        # working limit, so it is cleared rather than evicted one at a time.
        if len(_company_cache) > 6000:
            _company_cache.clear()
        _company_cache[key] = meta
    return meta


def _company_meta(code):
    from . import equity_api
    row = equity_api._cur().execute(_COMPANY_SQL, [code]).fetchone()
    if not row:
        return None
    (filer_name, filer_name_en, period_end, filed_date, doc_id,
     name_en, name_ja, industry, holdings, board, shareholders) = row

    english = _clean(name_en or filer_name_en)
    japanese = _clean(name_ja or filer_name)
    name = english or japanese or code
    if not name:
        return None
    industry_en = ""
    try:
        industry_en = equity_api.INDUSTRY_EN.get(industry) or ""
    except Exception:  # noqa: BLE001
        industry_en = ""

    # "the year to March 2026" — the fiscal year a reader would name, not the
    # ISO date the table stores.
    period = period_end.strftime("%B %Y") if period_end else ""

    # Identity first, because that is what was searched for; then the counts
    # that make this page different from the next company's.
    ident = "%s (%s)" % (name, code)
    if japanese and japanese != name:
        ident = "%s (%s, %s)" % (name, japanese, code)

    counts = []
    # Only counts that are actually there. A zero here cannot tell "this
    # company holds no cross-shareholdings" apart from "that table was not
    # extracted", and the site does not print a number it cannot stand behind.
    if holdings:
        counts.append("%d cross-shareholding%s" % (holdings, "" if holdings == 1 else "s"))
    if board:
        counts.append("a board of %d" % board)
    if shareholders:
        counts.append("%d largest shareholders" % shareholders)

    sentence = ident + ("%s." % (", " + industry_en) if industry_en else ".")
    if counts and period:
        sentence += " %s, as filed on EDINET for the year to %s." % (
            _join(counts).capitalize(), period)
    elif period:
        sentence += " Annual securities report for the year to %s." % period

    title = "%s (%s) \u2014 Ownership, Board & Financials \u00b7 Plover Analytics" % (name, code)

    noscript = sentence
    if doc_id and filed_date:
        noscript += " EDINET filing %s, filed %s. Source: company filings on EDINET " \
                    "(Financial Services Agency of Japan)." % (doc_id, filed_date)

    return {"title": title, "description": sentence, "h1": name,
            "noscript": noscript, "code": code, "name_ja": japanese,
            "name": name, "ident": ident}


def _join(parts):
    """"a, b and c" — the way a sentence lists things."""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# ---------------------------------------------------------------------------
# the other per-entity views
# ---------------------------------------------------------------------------
#
# Three more pages serve one subject per address: a company's cross-
# shareholdings, its AGM results, and one series of the CPI. Each had the
# same problem company.html had, and each needs its own answer rather than
# the company blurb repeated three times — three pages carrying one
# description for the same company is the duplicate problem again, only
# spread sideways. So each states what *that* page shows.

_HOLDINGS_SQL = """
WITH l AS (
  SELECT doc_id, period_end FROM eq_filings WHERE sec_code = ?
  ORDER BY period_end DESC NULLS LAST, filed_date DESC NULLS LAST LIMIT 1)
SELECT l.period_end, count(h.row_no), sum(h.book_value_yen),
       count(h.held_sec_code)
FROM l LEFT JOIN eq_holdings h USING (doc_id)
GROUP BY l.period_end
"""

_AGM_SQL = """
SELECT count(DISTINCT m.doc_id), max(m.filed_date),
       min(v.approval_pct_filed), count(v.seq)
FROM eq_agm_meetings m LEFT JOIN eq_agm_votes v USING (doc_id)
WHERE m.issuer_sec_code = ?
"""

_BUYBACK_SQL = """
SELECT count(DISTINCT f.doc_id), max(f.submitted),
       max(p.authorised_yen), max(p.progress_yen_pct)
FROM eq_buyback_filings f LEFT JOIN eq_buyback_programs p USING (doc_id)
WHERE f.sec_code = ?
"""

_SERIES_SQL = """
SELECT s.name_en, s.name_ja, s.weight_per_10000,
       (SELECT min(o.period) FROM observations o WHERE o.series_id = s.series_id),
       (SELECT max(o.period) FROM observations o WHERE o.series_id = s.series_id)
FROM series s WHERE s.dataset = ? AND s.code = ?
"""

# The explorer holds two CPI datasets and defaults to the categories one, the
# same default its own urlState() applies. Anything else in ?dataset= is not
# a view this page serves, so it gets the page's own description.
_EXPLORER_DATASETS = {
    "cpi-jp": "Japan's CPI categories",
    "cpi-jp-items": "Japan's CPI at full item depth",
}
_EXPLORER_DEFAULT = "cpi-jp"


def _yen_bn(value):
    """A book value as the tables show it: billions of yen, one decimal."""
    if not value:
        return None
    return "{:,.1f}".format(float(value) / 1e9)


def _holdings_view(values):
    code = (values.get("c") or "").strip()
    base = company_meta(code)
    if not base:
        return None
    facts = _cached(("holdings", code), _equity_version,
                    lambda: _one(_HOLDINGS_SQL, [code]))
    name, ident = base["name"], base["ident"]
    held = total = listed = 0
    period = ""
    if facts:
        period_end, held, total, listed = facts
        held, listed = held or 0, listed or 0
        period = period_end.strftime("%B %Y") if period_end else ""
    if not held:
        return None
    sentence = "%s holds %d cross-shareholding%s" % (
        ident, held, "" if held == 1 else "s")
    money = _yen_bn(total)
    if money:
        sentence += ", \u00a5%sbn at book value" % money
    if listed:
        sentence += ", %d of them in companies also covered here" % listed
    sentence += ", as filed in its annual securities report%s." % (
        " for the year to " + period if period else "")
    return {"title": "%s (%s) \u2014 Cross-Shareholdings \u00b7 Plover Analytics"
                     % (name, code),
            "description": sentence, "h1": name,
            "noscript": sentence + " " + _CREDIT,
            "code": code, "name_ja": base.get("name_ja")}


def _agm_view(values):
    code = (values.get("company") or "").strip()
    base = company_meta(code)
    if not base:
        return None
    facts = _cached(("agm", code), _equity_version,
                    lambda: _one(_AGM_SQL, [code]))
    if not facts or not facts[0]:
        return None
    meetings, latest, lowest, votes = facts
    name, ident = base["name"], base["ident"]
    sentence = "AGM voting results for %s: %d meeting%s on file" % (
        ident, meetings, "" if meetings == 1 else "s")
    if votes and lowest is not None:
        # As filed by the company; never recomputed here.
        sentence += ", lowest reported approval %.2f%%" % lowest
    if latest:
        sentence += ", latest filed %s" % latest
    sentence += ", from extraordinary reports on EDINET."
    return {"title": "%s (%s) \u2014 AGM Voting Results \u00b7 Plover Analytics"
                     % (name, code),
            "description": sentence, "h1": name,
            "noscript": sentence + " " + _CREDIT,
            "code": code, "name_ja": base.get("name_ja")}


def _buyback_view(values):
    code = (values.get("c") or "").strip()
    base = company_meta(code)
    if not base:
        return None
    facts = _cached(("buyback", code), _equity_version,
                    lambda: _one(_BUYBACK_SQL, [code]))
    if not facts or not facts[0]:
        return None
    filings, latest, authorised, progress = facts
    name, ident = base["name"], base["ident"]
    sentence = "Share buybacks by %s: %d monthly filing%s on file" % (
        ident, filings, "" if filings == 1 else "s")
    money = _yen_bn(authorised)
    if money:
        sentence += ", largest programme authorised at \u00a5%sbn" % money
    if latest:
        sentence += ", latest filed %s" % latest
    sentence += ", from EDINET."
    return {"title": "%s (%s) \u2014 Share Buybacks \u00b7 Plover Analytics"
                     % (name, code),
            "description": sentence, "h1": name,
            "noscript": sentence + " " + _CREDIT,
            "code": code, "name_ja": base.get("name_ja")}


def _explorer_view(values):
    code = (values.get("series") or "").strip()
    dataset = (values.get("dataset") or "").strip() or _EXPLORER_DEFAULT
    if not code or dataset not in _EXPLORER_DATASETS:
        return None
    facts = _cached(("series", dataset, code), _macro_version,
                    lambda: _one_macro(_SERIES_SQL, [dataset, code]))
    if not facts:
        return None
    # The two CPI datasets overlap: all 78 category codes are published again
    # inside the item table, with identical observations, so ?series=0001 and
    # ?series=0001&dataset=cpi-jp-items are one series at two addresses. The
    # shorter one — the explorer's own default — is named as the real one.
    canonical = None
    if dataset != _EXPLORER_DEFAULT and _in_default_dataset(code):
        canonical = "%s/explorer.html?series=%s" % (
            SITE_BASE_URL_FOR_JSONLD(), code)
    name_en, name_ja, weight, first, last = facts
    name = (name_en or name_ja or "").strip()
    if not name:
        return None
    ident = "%s (%s)" % (name, name_ja) if name_ja and name_ja != name else name
    sentence = "%s in %s, item code %s." % (ident, _EXPLORER_DATASETS[dataset], code)
    if weight and weight >= 10000:
        # The all-items total is the basket, not a share of it.
        sentence += " The whole basket, 10,000 parts per 10,000."
    elif weight:
        # Parts per 10,000 (\u4e00\u4e07\u5206\u6bd4), as the Bureau publishes them — never percent.
        sentence += " Weight %s per 10,000 of the basket." % (
            "{:,.0f}".format(weight) if weight >= 1 else "%.1f" % weight)
    if first and last:
        sentence += " Monthly index from %s to %s, as published by the Statistics Bureau." % (
            first.strftime("%B %Y"), last.strftime("%B %Y"))
    # The code is in the title because the names are not unique: the same
    # item is published as both an aggregate and a leaf ("Electricity" is
    # 0056 and 3500), and several parenthetical names ("(ordinary fares)")
    # mean different things under different parents. The explorer's own
    # search box already invites the code, so it is what a reader searches.
    return {"title": "%s (%s) \u2014 Japan CPI \u00b7 Plover Analytics" % (name, code),
            "description": sentence,
            "noscript": sentence + " Source: Statistics Bureau of Japan.",
            "datasets": [dataset], "canonical": canonical}


def _in_default_dataset(code):
    """Is this code also published in the explorer's default dataset?"""
    return bool(_cached(("in-default", code), _macro_version,
                        lambda: _one_macro(
                            "SELECT 1 FROM series WHERE dataset = ? AND code = ?",
                            [_EXPLORER_DEFAULT, code])))


def _company_view(values):
    base = company_meta((values.get("code") or "").strip())
    if not base:
        return None
    return {"title": base["title"], "description": base["description"],
            "h1": base["h1"], "noscript": base["noscript"]}


# Which page serves one entity per address, and how to describe it. A page
# whose query only filters a table is still one page and stays out.
ENTITY_PAGES = {
    "company.html": _company_view,
    "holdings.html": _holdings_view,
    "agm.html": _agm_view,
    "buyback.html": _buyback_view,
    "explorer.html": _explorer_view,
}


def entity_meta(page_name, query_string):
    """Per-entity head and heading for this exact address, or None."""
    view = ENTITY_PAGES.get(page_name)
    if not view or not query_string:
        return None
    try:
        return view(dict(parse_qsl(query_string, keep_blank_values=True)))
    except Exception:  # noqa: BLE001 — see module docstring: best-effort only
        return None


# ---------------------------------------------------------------------------
# what a machine is told
# ---------------------------------------------------------------------------
#
# Two additions aimed past the browser.
#
# The icons, because every page needs the same four <link> tags and they were
# copied into all 46 heads by hand: the 47th page would have been the one that
# forgot them. Written here, adding a page cannot get them wrong. Root-absolute
# rather than relative, so they survive a page served from a deeper path later.
#
# And the data, because the page is a shell. An assistant that fetches
# /company.html?code=7203 gets the nav, a sentence and nothing else — the
# holdings arrive from /api afterwards, from a fetch the assistant does not
# run. rel="alternate" names the JSON behind the page, and the JSON-LD block
# says what the page is in the vocabulary search engines already parse.
# Neither invents anything: every field comes from the dataset's MANIFEST or
# from the company row, and a page with no dataset and no company gets neither.

ICON_LINKS = (
    '<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48">'
    '<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">'
    '<link rel="icon" href="/assets/favicon-48.png" type="image/png" sizes="48x48">'
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
)
_HAS_ICON = re.compile(r'(?is)<link[^>]+rel=["\']icon["\']')

# Where a page's own numbers can be read as JSON. A dataset page is answered
# by its manifest's summary endpoint; an entity page by the endpoint that
# serves that one entity.
ENTITY_API = {
    "company.html": "/api/v1/company/%s",
    "holdings.html": "/api/v1/equity/company/%s",
    "agm.html": "/api/v1/equity/agm/company/%s",
    "buyback.html": "/api/v1/equity/buyback/company/%s",
}

SITE = "Plover Analytics"


def _json_string(text):
    """JSON-LD sits inside a <script>, where the danger is not the quote but
    the closing tag: a name containing "</script>" would end the block early."""
    out = json.dumps(text, ensure_ascii=False)
    return out.replace("<", "\\u003c").replace(">", "\\u003e")


def _jsonld(fields):
    """A @graph-free Dataset node, rendered small and deterministic."""
    parts = []
    for key, value in fields:
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str):
            parts.append('%s:%s' % (_json_string(key), _json_string(value)))
        else:
            parts.append('%s:%s' % (_json_string(key), json.dumps(
                value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")))
    return '<script type="application/ld+json">{%s}</script>' % ",".join(parts)


def _download(url, fmt):
    return {"@type": "DataDownload", "contentUrl": url, "encodingFormat": fmt}


def dataset_jsonld(dataset, canonical):
    """schema.org/Dataset for a statistical page, straight from its MANIFEST.

    The manifest is the same object the catalog and the API reference are
    built from, so a claim here cannot drift from what the dataset says about
    itself. license is deliberately absent: the platform has no single one —
    each source carries its own terms, which travel as usageInfo text.
    """
    from . import registry
    manifest = registry.get(dataset)
    if not manifest:
        return ""
    source = manifest.get("source") or {}
    endpoints = manifest.get("endpoints") or {}
    base = SITE_BASE_URL_FOR_JSONLD()
    distribution = []
    for key in ("summary", "series"):
        path = endpoints.get(key)
        if path:
            distribution.append(_download(base + path, "application/json"))
    name = (manifest.get("name") or {}).get("en") or dataset
    return _jsonld([
        ("@context", "https://schema.org"),
        ("@type", "Dataset"),
        ("name", name),
        ("description", manifest.get("summary")),
        ("url", canonical),
        ("identifier", dataset),
        ("isAccessibleForFree", True),
        ("creator", {"@type": "Organization", "name": SITE, "url": base + "/"}),
        ("sourceOrganization", {"@type": "Organization",
                                "name": source.get("publisher")}
         if source.get("publisher") else None),
        ("creditText", source.get("credit")),
        ("usageInfo", source.get("license_note")),
        ("isBasedOn", source.get("url")),
        ("distribution", distribution),
    ])


def company_jsonld(entity, canonical, api_url):
    """schema.org/Dataset whose subject is the company, so the filings and the
    company are both stated rather than one standing in for the other."""
    base = SITE_BASE_URL_FOR_JSONLD()
    about = {"@type": "Organization", "name": entity["h1"]}
    if entity.get("name_ja") and entity["name_ja"] != entity["h1"]:
        about["alternateName"] = entity["name_ja"]
    if entity.get("code"):
        about["tickerSymbol"] = entity["code"]
    return _jsonld([
        ("@context", "https://schema.org"),
        ("@type", "Dataset"),
        ("name", entity["title"].split(" \u00b7 ")[0]),
        ("description", entity["description"]),
        ("url", canonical),
        ("isAccessibleForFree", True),
        ("about", about),
        ("creator", {"@type": "Organization", "name": SITE, "url": base + "/"}),
        ("creditText", "Source: company filings on EDINET "
                       "(Financial Services Agency of Japan)."),
        ("distribution", [_download(api_url, "application/json")]),
    ])


_page_map_cache = {"ids": None, "map": {}}


def page_datasets(html, page_name):
    """Which datasets this page is the front of.

    The page's own data-dataset attribute names its principal one and wins.
    Where there is none — every equity page — the registry is asked instead:
    each MANIFEST already records the page it belongs to, and holdings.html,
    the page that ranks today, is one of those. A page may front several
    datasets (fiscal.html fronts eight), and each is stated separately rather
    than one being chosen to stand for the rest.
    """
    found = _DATASET.search(html)
    if found:
        return [found.group(1)]
    from . import registry
    ids = tuple(registry.ids())
    with _lock:
        if _page_map_cache["ids"] != ids:
            built = {}
            for mid in ids:
                page = (registry.get(mid) or {}).get("page")
                if page:
                    built.setdefault(page, []).append(mid)
            _page_map_cache["ids"] = ids
            _page_map_cache["map"] = built
        return _page_map_cache["map"].get("/" + page_name, [])


def SITE_BASE_URL_FOR_JSONLD():
    """The public origin, from the one place that already owns it."""
    from . import seo
    return seo.SITE_BASE_URL


# ---------------------------------------------------------------------------
# injection
# ---------------------------------------------------------------------------

def inject(html, page_name, canonical=None, query_string=""):
    """Serve-time additions for one HTML page. Never raises."""
    try:
        return _inject(html, page_name, canonical, query_string)
    except Exception:  # noqa: BLE001 — a page that renders beats an annotated one
        return html


def _inject(html, page_name, canonical=None, query_string=""):
    # The address this page is to be indexed under, whatever hostname it was
    # fetched from. Written here rather than into the 46 files because only
    # the server knows which host answered and which view was asked for; a
    # literal in each file would say the same thing 46 times and drift.
    # What this address is, when the address names one company or one series
    # rather than the page's whole subject. Falls back to the page's own
    # description the moment the code is unknown, so a typo serves the shell
    # rather than an error. Read before the canonical is written, because a
    # view that shares its subject with another address says so here.
    entity = entity_meta(page_name, query_string)
    if entity and entity.get("canonical"):
        canonical = entity["canonical"]

    if canonical and not _HAS_CANONICAL.search(html):
        tag = '<link rel="canonical" href="%s">\n' % _escape(canonical)
        html = _HEAD_END.sub(tag + "</head>", html, count=1)

    if entity:
        html = _TITLE_TAG.sub(
            lambda m: "<title>%s</title>" % _escape(entity["title"]), html, count=1)
        if entity.get("h1"):
            html = _CO_NAME_H1.sub(
                lambda m: m.group(1) + _escape(entity["h1"]) + m.group(3),
                html, count=1)

    description = (entity or {}).get("description") or DESCRIPTIONS.get(page_name)
    if description and not _HAS_DESC.search(html):
        tag = '<meta name="description" content="%s">\n' % _escape(description)
        html = _HEAD_END.sub(tag + "</head>", html, count=1)

    # The icons every page carries, written once here rather than 46 times.
    if not _HAS_ICON.search(html):
        html = _HEAD_END.sub(ICON_LINKS + "\n</head>", html, count=1)

    # Where this page's numbers can be read as data, and what the page is.
    # A company view states the company; a series view is still a view of its
    # dataset, so it keeps the dataset node and only the wording changes.
    template = ENTITY_API.get(page_name) if entity else None
    company_node = bool(template and entity.get("code"))
    if company_node:
        datasets = []
    elif entity and entity.get("datasets"):
        # A series view names the dataset it is a view of, since the page
        # itself carries no data-dataset and the registry maps no page to it.
        datasets = entity["datasets"]
    else:
        datasets = page_datasets(html, page_name)
    alternates = []
    nodes = []
    if company_node:
        path = template % entity["code"]
        alternates.append((path, entity.get("h1") or entity["title"]))
        nodes.append(company_jsonld(
            entity, canonical or "", SITE_BASE_URL_FOR_JSONLD() + path))
    else:
        from . import registry
        for mid in datasets:
            manifest = registry.get(mid) or {}
            endpoints = manifest.get("endpoints") or {}
            path = endpoints.get("summary") or endpoints.get("series")
            if path:
                alternates.append(
                    (path, (manifest.get("name") or {}).get("en") or mid))
            node = dataset_jsonld(mid, canonical or "")
            if node:
                nodes.append(node)
    for path, label in alternates:
        html = _HEAD_END.sub(
            '<link rel="alternate" type="application/json" href="%s" title="%s">\n</head>'
            % (_escape(path), _escape(label)), html, count=1)
    for node in nodes:
        html = _HEAD_END.sub(node + "\n</head>", html, count=1)

    links = nav_links_html()
    if links:
        html = _HEADER_SHELL.sub(
            lambda m: m.group(1) + links + m.group(3), html, count=1)

    text = ""
    if entity:
        text = entity["noscript"]
    elif datasets:
        text = summary_text(datasets[0])
    if text:
        block = "<noscript><p>%s</p></noscript>" % _escape(text)
        html = _MAIN_OPEN.sub(lambda m: m.group(1) + block, html, count=1)
    return html
