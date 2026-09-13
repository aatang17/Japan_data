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
import re
import threading

WEB_DIR = None  # set by main, so this module imports without touching the disk

# Nav entries are `{ id: "…", label: "…", href: "…" }` with label immediately
# before href. Anchor text and destination are all a crawler needs; the
# section hierarchy is nav.js's business.
_NAV_ENTRY = re.compile(r'label:\s*"([^"]+)"\s*,\s*href:\s*"([^"]+\.html)"')
_HEADER_SHELL = re.compile(r'(<header class="site-header"[^>]*>)(\s*)(</header>)')
_MAIN_OPEN = re.compile(r'(<main\b[^>]*>)')
_HEAD_END = re.compile(r'</head>', re.IGNORECASE)
_HAS_DESC = re.compile(r'(?is)<meta[^>]+name=["\']description["\']')
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
# injection
# ---------------------------------------------------------------------------

def inject(html, page_name):
    """Serve-time additions for one HTML page. Never raises."""
    try:
        return _inject(html, page_name)
    except Exception:  # noqa: BLE001 — a page that renders beats an annotated one
        return html


def _inject(html, page_name):
    description = DESCRIPTIONS.get(page_name)
    if description and not _HAS_DESC.search(html):
        tag = '<meta name="description" content="%s">\n' % _escape(description)
        html = _HEAD_END.sub(tag + "</head>", html, count=1)

    links = nav_links_html()
    if links:
        html = _HEADER_SHELL.sub(
            lambda m: m.group(1) + links + m.group(3), html, count=1)

    found = _DATASET.search(html)
    if found:
        text = summary_text(found.group(1))
        if text:
            block = "<noscript><p>%s</p></noscript>" % _escape(text)
            html = _MAIN_OPEN.sub(lambda m: m.group(1) + block, html, count=1)
    return html
