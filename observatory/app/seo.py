"""What search engines and AI clients are told about the site: robots.txt,
sitemap.xml and llms.txt.

Both are generated on request rather than stored as files, so neither can
drift from what the site actually serves. The page list is the contents of
``web/`` minus the pages that declare themselves unlisted, which means adding
a page to the site is the whole of adding it to the sitemap — there is no
second list to remember.

A page declares itself unlisted the same way it already tells a crawler to
skip it, with ``<meta name="robots" content="noindex">`` in its own head.
That tag and this module then agree by construction; a sitemap that invites
Google to a page whose head turns it away is the usual way these two drift.

No ``<lastmod>``. The honest value would be when a page's *data* last
changed, which is not something the file's timestamp knows: every file in the
container carries the timestamp of the deploy that built it, so a lastmod
here would announce that all 42 pages changed every time anything shipped.
Google discounts the field when it reads like that, and an ignored field is
worth less than an absent one. ``<changefreq>`` and ``<priority>`` are
omitted for the simpler reason that Google states it ignores both.
"""
import os
import pathlib
import re
import threading
from urllib.parse import parse_qsl, urlencode, urlsplit
from xml.sax.saxutils import escape

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from starlette.datastructures import Headers

WEB_DIR = pathlib.Path(__file__).resolve().parent.parent / "web"

# The site's public address, and the one every generated link uses. Held here
# rather than derived from the incoming request on purpose: the Railway
# deploy domain still answers to the same app, and a sitemap that named
# whichever host fetched it would offer Google two copies of every page to
# choose a canonical from. Naming one host makes that choice for it.
SITE_BASE_URL = os.environ.get(
    "SITE_BASE_URL", "https://ploveranalytics.com").rstrip("/")

# Paths no crawler should spend itself on. /api/ is deliberately absent:
# every page draws its numbers from it after load, and a crawler that is
# forbidden the API renders a page of empty charts and indexes that.
DISALLOWED = ("/admin.html", "/admin/")

_NOINDEX = re.compile(
    r"<meta[^>]+name=[\"']robots[\"'][^>]*content=[\"'][^\"']*noindex",
    re.IGNORECASE)

# Search Console proves ownership by asking for a file at a name it chooses,
# carrying one line it chooses. It lands in web/ because that is what the
# server publishes, but it is a token, not a page: it must be reachable and
# must not be edited — so it cannot carry the noindex tag every other
# excluded page uses to opt out, and is named here instead.
_VERIFICATION = re.compile(r"^google[0-9a-f]{8,}\.html$", re.IGNORECASE)


def _listed(page):
    """Does this page belong in the index? Only the page itself can say."""
    if _VERIFICATION.match(page.name):
        return False
    try:
        head = page.open("r", encoding="utf-8", errors="replace").read(4096)
    except OSError:
        return False
    return not _NOINDEX.search(head)


def page_urls():
    """Absolute URLs of every listed page, the landing page first.

    ``index.html`` is published as the bare directory URL, since that is the
    address people link to and the one the site's own header points home at;
    offering both spellings would be the same duplicate-content problem at a
    smaller scale.
    """
    names = sorted(p.name for p in WEB_DIR.glob("*.html") if _listed(p))
    # The landing page leads; the rest follow in the order a person reading
    # the file would look for them.
    ordered = ([""] if "index.html" in names else []) + [
        n for n in names if n != "index.html"]
    return [SITE_BASE_URL + "/" + name for name in ordered]


# ---------------------------------------------------------------------------
# the long tail
# ---------------------------------------------------------------------------
#
# The 46 files in web/ are the site's furniture, not its contents. The
# contents are the four thousand companies behind company.html, and a crawler
# has no way to reach them: nothing on the site links to a company page
# except a search box that only runs once JavaScript has, so the pages exist
# and are reachable only by someone who already knows the code. Listing them
# here is the one mechanism that does not depend on a script running.
#
# Listed from the filings table rather than the entity registry, because a
# page is worth indexing when there is a filing behind it to render — the
# registry knows of companies we hold nothing for, and those pages would be
# the thin duplicates that make a search engine trust the rest of them less.

_COMPANY_SQL = """
SELECT DISTINCT sec_code FROM eq_filings
WHERE sec_code IS NOT NULL AND sec_code <> '' ORDER BY sec_code
"""

_company_lock = threading.Lock()
_company_cache = {"version": object(), "urls": []}


def company_urls():
    """Absolute URLs of every company page with a filing behind it.

    Empty whenever the equity database cannot be read — mid-swap, or on a
    macro-only deploy. An incomplete sitemap costs a crawl; a failed one
    costs the whole file, so this never raises.
    """
    from . import equity_api
    try:
        version = equity_api.file_version()
    except Exception:  # noqa: BLE001 — a sitemap is never worth an error page
        return []
    with _company_lock:
        if _company_cache["version"] == version:
            return _company_cache["urls"]
    try:
        rows = equity_api._cur().execute(_COMPANY_SQL).fetchall()
    except Exception:  # noqa: BLE001
        return []
    urls = [SITE_BASE_URL + "/company.html?code=" + row[0] for row in rows]
    with _company_lock:
        _company_cache["version"] = version
        _company_cache["urls"] = urls
    return urls


router = APIRouter()


@router.get("/robots.txt", include_in_schema=False)
def robots():
    lines = ["User-agent: *", "Allow: /"]
    lines += ["Disallow: " + path for path in DISALLOWED]
    lines += ["", "Sitemap: " + SITE_BASE_URL + "/sitemap.xml"]
    # Not part of the robots standard, and ignored by crawlers that do not know
    # it. It is here because the clients that DO look for llms.txt often read
    # robots.txt first, and a line they ignore costs nothing.
    lines += ["LLM-Guidance: " + SITE_BASE_URL + "/llms.txt", ""]
    return PlainTextResponse("\n".join(lines))


def _urlset(urls):
    body = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    for url in urls:
        body.append("  <url><loc>%s</loc></url>" % escape(url))
    body.append("</urlset>")
    body.append("")
    return Response("\n".join(body), media_type="application/xml")


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    """An index of the two sitemaps, not a list of pages.

    Split so that Search Console reports the two halves separately: the 46
    built pages and the four thousand company pages are indexed at very
    different rates, and one combined number would hide which. The companies
    half is omitted rather than served empty when the equity database is
    unreadable, so a crawler is never told the answer is "none".
    """
    parts = [SITE_BASE_URL + "/sitemap-pages.xml"]
    if company_urls():
        parts.append(SITE_BASE_URL + "/sitemap-companies.xml")
    body = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<sitemapindex xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    for url in parts:
        body.append("  <sitemap><loc>%s</loc></sitemap>" % escape(url))
    body.append("</sitemapindex>")
    body.append("")
    return Response("\n".join(body), media_type="application/xml")


@router.get("/sitemap-pages.xml", include_in_schema=False)
def sitemap_pages():
    return _urlset(page_urls())


@router.get("/sitemap-companies.xml", include_in_schema=False)
def sitemap_companies():
    return _urlset(company_urls())


# ---------------------------------------------------------------------------
# what an AI client is told
# ---------------------------------------------------------------------------
#
# /llms.txt is the convention (llmstxt.org) for a page addressed to a language
# model rather than to a person: what the site is, what it holds, and how to
# quote it. It earns its place here more than on most sites, because an
# assistant that lifts a number off a chart page without its trust label will
# report a rate this platform calculated as an official statistic — which is
# the one failure the whole product exists to prevent. Saying so in the one
# file those clients already fetch costs nothing.
#
# Generated from the registry rather than kept as a file, for the same reason
# the sitemap is: a dataset appears here because it is registered and serving
# data, so this cannot drift from what the site actually has.

LLMS_INTRO = """# Plover Analytics

> Japanese official statistics and company disclosures, taken from the primary
> sources, published exactly as issued or filed, and archived so that any
> figure can also be read as it stood on an earlier date. Free to use, free to
> quote, and built to be cited rather than paraphrased.

Sources are the Statistics Bureau of Japan, the Bank of Japan, the Ministry of
Finance, the Cabinet Office, the Ministry of Internal Affairs and
Communications, and company filings on EDINET (Financial Services Agency).
Nothing here is scraped from another aggregator.

## How to quote a number from this site

Every value the API returns carries a `trust` field, and it means something
exact:

- `trust: "official"` — the figure exactly as the publisher released it or the
  company filed it. Never recomputed, never smoothed, never corrected. Filer
  errors are published as filed and flagged, not fixed.
- `trust: "derived"` — this platform calculated it, and the `calc` field beside
  it states the formula in full. When you quote such a number, quote the
  formula with it, or say that it is calculated. Do not describe it as an
  official statistic.

A missing value is missing: it is returned as null and shown as an em dash. It
is never zero, and must never be reported as zero.

Rates computed from published (rounded) index levels can differ from the
publisher's own published rate by up to 0.1 percentage points. That is
disclosed, not an error, and must not be "corrected" by rounding to match.

Stocks, flows, levels and price changes are different measure types and are
never summed, netted or ranked against one another.

## How to cite

Cite the page URL — it encodes the entire view, so it resolves to the same
chart later — together with the publisher's own credit line, which every
response carries at `source.credit`. For example:

    Plover Analytics, "Consumer Price Index - items",
    https://ploveranalytics.com/cpi.html, retrieved 2026-09-17.
    Source: Statistics Bureau of Japan.

Some publishers require their credit line verbatim wherever the data appears,
including in exports. The Bank of Japan is one. Each dataset's own required
wording is in its manifest at /api/v1/catalog/manifests.

## Reading the data as it stood on an earlier date

Every accepted release is archived with the SHA-256 of the source file, so the
data can be read as of a past date rather than only as it is now:

- `/api/v1/{dataset}/observations?series=...&as_of=YYYY-MM-DD` returns the
  numbers a reader would have had on that date, before later revisions.
- `/api/v1/{dataset}/releases` lists every release with its date and hash.

This history begins when this platform began collecting, not when the
statistic began. The API says so plainly if you ask for a date before the
first release.

## The API

No key, no registration, JSON or CSV.

- `/api/v1/catalog/datasets` - every dataset with its id and description
- `/api/v1/catalog/manifests` - the full card: sources, measures, formulas,
  endpoints, credit lines
- `/api/v1/{dataset}/series` - the series codes a dataset offers
- `/api/v1/{dataset}/observations?series=CODE&measure=index` - the values;
  `measure` may be `index` (as published) or a calculated rate the dataset
  lists, and `format=csv` returns a file with its sources in the header
- Company datasets are under `/api/v1/equity/...` and are keyed by the
  company's securities code
- `/api/openapi.json` - the full specification

A Model Context Protocol server is at /mcp, which answers the same questions
through the same functions, with the trust label attached to every figure.

## Terms

Free to use, including commercially, with attribution to the original
publisher as described above. The underlying statistics and filings are public
records; this platform's contribution is the collection, the archive and the
stated formulas. If you train on this material or quote it in an answer,
attribute the publisher and, where the number is calculated, say so.
"""


def _one_line(text, limit=210):
    """A dataset summary shortened to a sentence, without cutting a word in
    half. The manifests are written for a reader; this file is a directory."""
    body = " ".join((text or "").split())
    if len(body) <= limit:
        return body
    cut = body.rfind(" ", 0, limit)
    return body[:cut if cut > 0 else limit].rstrip(" ,;:-") + "..."


def llms_txt():
    """The body of /llms.txt, built from the registry and the page list."""
    from . import registry
    parts = [LLMS_INTRO.rstrip(), ""]

    labels = dict((s["id"], s["label"]) for s in registry.SECTIONS)
    holdings = {}
    for card in registry.datasets():
        if not card.get("available"):
            continue  # a dataset with no data behind it is not something to point at
        holdings.setdefault(card["section"], []).append(card)

    if holdings:
        parts.append("## Datasets")
        parts.append("")
        for section in registry.SECTIONS:
            cards = holdings.get(section["id"])
            if not cards:
                continue
            parts.append("### " + labels.get(section["id"], section["id"]))
            parts.append("")
            for card in cards:
                name = (card.get("name") or {}).get("en") or card["id"]
                page = SITE_BASE_URL + (card.get("page") or "/")
                publisher = (card.get("source") or {}).get("publisher") or ""
                line = "- [%s](%s) - id `%s`" % (name, page, card["id"])
                if publisher:
                    line += ", from %s" % publisher
                parts.append(line + ". " + _one_line(card.get("summary")))
            parts.append("")

    pages = page_urls()
    if pages:
        parts.append("## Pages")
        parts.append("")
        parts.append("Every page below states its sources and lets any view be "
                     "downloaded as CSV with those sources in the file header.")
        parts.append("")
        for url in pages:
            parts.append("- " + url)
        parts.append("")

    parts.append("## Not part of the site")
    parts.append("")
    for path in DISALLOWED:
        parts.append("- " + SITE_BASE_URL + path + " - an internal console, "
                     "excluded in robots.txt and carrying no published data")
    parts.append("")
    return "\n".join(parts)


@router.get("/llms.txt", include_in_schema=False)
def llms():
    """Served as plain text so it reads in a browser as well as in a fetcher.

    Never fails: if the registry cannot be read, the standing part of the file
    — how to quote a number, how to cite it, what the API is — is still worth
    serving on its own, and is the part that prevents a misquote.
    """
    try:
        body = llms_txt()
    except Exception:  # noqa: BLE001 - an advisory file is never worth an error
        body = LLMS_INTRO
    return PlainTextResponse(body, media_type="text/plain; charset=utf-8")


# ---------------------------------------------------------------------------
# one address per page
# ---------------------------------------------------------------------------
#
# The site answers on more hostnames than it has: the apex and the www
# spelling both resolve, and the Railway deploy domain answers too. Every one
# of them serves all 46 pages, so a crawler that meets two of them has two
# copies of the site and has to guess which is real — it guessed www, while
# the sitemap above names the apex, and the two halves of that split then
# compete with each other for the same query.
#
# Two things settle it, and SITE_BASE_URL is the single source of truth for
# both: the www spelling is redirected to the canonical host permanently, and
# every page states its own canonical address on the way out, which covers
# the deploy domain and anything else pointed at the app later.

# Parameters that identify where a reader came from, not what they asked to
# see. A link shared from the newsletter carries them and would otherwise
# index as a page of its own.
_TRACKING = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref_src")


def _is_tracking(key):
    return key.startswith("utm_") or key in _TRACKING


def is_https(request):
    """Whether the READER's connection is https.

    Not the same question as ``request.url.scheme``, which describes the hop
    between the platform's proxy and this process and is always plain http.
    Uvicorn only believes X-Forwarded-* from 127.0.0.1 and the proxy is not
    on it, so the scheme reads http on a site that is https-only — and a
    cookie marked Secure only when that reading says https is never marked
    Secure at all. Read the header ourselves, exactly as the visit counter
    reads the forwarded address.
    """
    proto = (request.headers.get("x-forwarded-proto") or "")
    proto = proto.split(",")[0].strip().lower()
    return (proto or request.url.scheme) == "https"


def canonical_url(path, query_string=""):
    """The one address for a request's path and query.

    View state lives in the query string ("URL encodes the full view"), so it
    is kept: ``company.html?code=7203`` is a different page from
    ``company.html``, and collapsing the two would drop every company from
    the index. Only the tracking parameters are dropped, and ``index.html``
    resolves to the bare directory URL the sitemap already publishes.
    """
    path = path or "/"
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    kept = [(k, v) for k, v in parse_qsl(query_string, keep_blank_values=True)
            if not _is_tracking(k)]
    query = urlencode(kept)
    return SITE_BASE_URL + path + ("?" + query if query else "")


class CanonicalHost:
    """Redirects the other spelling of our hostname to the one we publish.

    Deliberately narrow: exactly one host is redirected, the www/apex twin of
    whatever SITE_BASE_URL names. Every other Host header is passed through
    untouched — localhost in development, the private domain the Railway
    healthcheck arrives on, and the deploy domain, none of which may be
    answered with a redirect to the public site.
    """

    def __init__(self, app):
        self.app = app
        host = (urlsplit(SITE_BASE_URL).hostname or "").lower()
        if not host:
            self.other = ""
        elif host.startswith("www."):
            self.other = host[4:]
        else:
            self.other = "www." + host

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.other:
            requested = Headers(scope=scope).get("host", "")
            if requested.split(":")[0].lower() == self.other:
                target = canonical_url(scope.get("path", "/"),
                                       scope.get("query_string", b"").decode("latin-1"))
                response = RedirectResponse(target, status_code=301)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
