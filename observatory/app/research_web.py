# -*- coding: utf-8 -*-
"""The research panel's reach outside Plover: web search, and reading a page.

Search
------
Brave Search's web API, one HTTP call over stdlib urllib. Switched on by
``BRAVE_SEARCH_API_KEY``; without it search answers "not configured" and the
panel says so — reading a page from its address still works. Each writer gets
60 searches an hour, which bounds what a stuck script could cost.

Reading a page
--------------
The server fetches the page for the writer and returns its text, so a writer
can read and cite a source without leaving the draft. That makes this a
server-side fetch of an address a person typed, and it is guarded as one:

* http and https only, ports 80 and 443 only;
* the host is resolved first and refused if any address it resolves to is
  private, loopback, link-local, reserved or multicast — so it cannot be
  pointed at the platform's own internal network or the cloud metadata
  service;
* redirects are followed by hand, at most five, each one checked the same way;
* at most 3 MB is read, with a 12-second timeout.

The check resolves the name before urllib resolves it again to connect, so a
hostile DNS server could in principle answer differently the second time.
Only signed-in writers can reach this, and the request carries no
credentials, which keeps that residual risk small.

Text extraction is an HTMLParser pass that keeps headings, paragraphs, list
items, quotations and table cells and drops navigation, scripts and forms.
Nothing from the page is ever rendered as HTML in the desk: the panel shows
it as text.
"""
import html
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
SEARCHES_PER_HOUR = 60
MAX_BYTES = 3 * 1024 * 1024
TIMEOUT = 12
MAX_REDIRECTS = 5
TEXT_MAX = 60000
UA = "Mozilla/5.0 (compatible; PloverResearch/1.0; +https://ploveranalytics.com/research)"

_hits = {}


class WebError(ValueError):
    """Worded for the writer."""


def search_key():
    return os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()


def _rate_ok(who):
    now = time.time()
    hits = [t for t in _hits.get(who, []) if now - t < 3600]
    if len(hits) >= SEARCHES_PER_HOUR:
        _hits[who] = hits
        return False
    hits.append(now)
    _hits[who] = hits
    return True


def _strip(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def search(query, who):
    key = search_key()
    if not key:
        raise WebError("Web search is not switched on: add BRAVE_SEARCH_API_KEY to the server "
                       "settings. Reading a page from its address works without it.")
    query = (query or "").strip()[:400]
    if not query:
        raise WebError("Type something to search for.")
    if not _rate_ok(who):
        raise WebError("You have run %d searches in the last hour; wait a little."
                       % SEARCHES_PER_HOUR)
    url = BRAVE_ENDPOINT + "?" + urllib.parse.urlencode({"q": query, "count": 12})
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "X-Subscription-Token": key, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise WebError("The search service refused the request (HTTP %d)." % exc.code)
    except Exception:  # noqa: BLE001
        raise WebError("The search service could not be reached. Try again in a moment.")
    out = []
    for r in ((body.get("web") or {}).get("results") or [])[:12]:
        u = r.get("url") or ""
        out.append({"title": _strip(r.get("title")), "url": u,
                    "site": (r.get("profile") or {}).get("name") or urllib.parse.urlsplit(u).hostname,
                    "snippet": _strip(r.get("description")), "age": r.get("age") or ""})
    return out


# ---------------------------------------------------------------------------
# reading a page

def _check_url(url):
    parts = urllib.parse.urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebError("Give a full web address starting with https://.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in (80, 443):
        raise WebError("Only standard web addresses can be read.")
    try:
        infos = socket.getaddrinfo(parts.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise WebError("That address does not resolve: check it for typos.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or
                ip.is_multicast or ip.is_unspecified or
                (ip.version == 6 and ip.ipv4_mapped is not None and
                 (ip.ipv4_mapped.is_private or ip.ipv4_mapped.is_loopback))):
            raise WebError("That address points inside a private network and cannot be read.")
    return parts.geturl()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _fetch(url):
    for _ in range(MAX_REDIRECTS + 1):
        url = _check_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept":
                                                   "text/html,application/xhtml+xml,*/*;q=0.5"})
        try:
            resp = _OPENER.open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                url = urllib.parse.urljoin(url, exc.headers["Location"])
                continue
            raise WebError("The site answered HTTP %d." % exc.code)
        except WebError:
            raise
        except Exception:  # noqa: BLE001
            raise WebError("The page could not be reached. It may block automated readers.")
        with resp:
            ctype = resp.headers.get("Content-Type", "")
            data = resp.read(MAX_BYTES + 1)
        return url, ctype, data[:MAX_BYTES]
    raise WebError("The page redirected too many times.")


_SKIP = ("script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg",
         "button", "select", "template", "iframe")
_KEEP = ("h1", "h2", "h3", "h4", "p", "li", "blockquote", "td", "th", "pre", "figcaption", "dd")


class _Reader(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.meta = {}
        self.title = []
        self.in_title = False
        self.skip = 0
        self.cur = None
        self.buf = []
        self.blocks = []
        self.chars = 0

    def handle_starttag(self, tag, attrs):
        a = dict((k.lower(), v or "") for k, v in attrs)
        if tag == "meta":
            k = (a.get("property") or a.get("name") or "").lower()
            if k and a.get("content"):
                self.meta.setdefault(k, a["content"])
            return
        if tag == "title":
            self.in_title = True
        if tag in _SKIP:
            self.skip += 1
        if tag in _KEEP and not self.skip:
            self._flush()
            self.cur = tag
        if tag == "br" and self.cur:
            self.buf.append(" ")
        if tag == "time" and a.get("datetime"):
            self.meta.setdefault("time", a["datetime"])

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in _SKIP and self.skip:
            self.skip -= 1
        if tag in _KEEP and self.cur == tag:
            self._flush()

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif self.cur and not self.skip:
            self.buf.append(data)

    def _flush(self):
        if self.cur:
            text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            if text and self.chars < TEXT_MAX and (self.cur.startswith("h") or len(text) > 1):
                kind = "h" if self.cur in ("h1", "h2", "h3", "h4") else (
                    "quote" if self.cur == "blockquote" else "p")
                if not (self.blocks and self.blocks[-1]["text"] == text):
                    self.blocks.append({"kind": kind, "text": text})
                    self.chars += len(text)
        self.cur = None
        self.buf = []


def _decode(data, ctype):
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.IGNORECASE)
    enc = m.group(1) if m else None
    if not enc:
        head = data[:4000].decode("ascii", "ignore")
        mm = re.search(r"<meta[^>]+charset=[\"']?([\w\-]+)", head, re.IGNORECASE)
        enc = mm.group(1) if mm else "utf-8"
    for e in (enc, "utf-8", "cp932"):
        try:
            return data.decode(e)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


def read(url):
    """{url, title, site, published, author, blocks:[{kind, text}], pdf}."""
    final, ctype, data = _fetch(url)
    host = urllib.parse.urlsplit(final).hostname or ""
    if "pdf" in ctype.lower() or final.lower().endswith(".pdf"):
        name = urllib.parse.unquote(final.rsplit("/", 1)[-1])
        return {"url": final, "title": name, "site": host, "published": "", "author": "",
                "blocks": [], "pdf": True}
    if "html" not in ctype.lower() and "xml" not in ctype.lower() and ctype:
        raise WebError("That address is not a web page (%s)." % ctype.split(";")[0])
    p = _Reader()
    try:
        p.feed(_decode(data, ctype))
        p.close()
    except Exception:  # noqa: BLE001 — a broken page still gives what was read
        pass
    p._flush()
    m = p.meta
    title = (m.get("og:title") or "".join(p.title)).strip()
    return {
        "url": final,
        "title": re.sub(r"\s+", " ", title)[:300],
        "site": (m.get("og:site_name") or host)[:120],
        "published": (m.get("article:published_time") or m.get("date") or m.get("dc.date")
                      or m.get("time") or "")[:30],
        "author": (m.get("author") or m.get("article:author") or "")[:120],
        "blocks": p.blocks[:600],
        "pdf": False,
    }
