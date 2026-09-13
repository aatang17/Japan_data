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
from xml.sax.saxutils import escape

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

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


def _listed(page):
    """Does this page belong in the index? Only the page itself can say."""
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
