"""What search engines are told about the site: robots.txt and sitemap.xml.

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


router = APIRouter()


@router.get("/robots.txt", include_in_schema=False)
def robots():
    lines = ["User-agent: *", "Allow: /"]
    lines += ["Disallow: " + path for path in DISALLOWED]
    lines += ["", "Sitemap: " + SITE_BASE_URL + "/sitemap.xml", ""]
    return PlainTextResponse("\n".join(lines))


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    body = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    for url in page_urls():
        body.append("  <url><loc>%s</loc></url>" % escape(url))
    body.append("</urlset>")
    body.append("")
    return Response("\n".join(body), media_type="application/xml")


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
