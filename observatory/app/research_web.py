# -*- coding: utf-8 -*-
"""The research panel's reach outside Plover: reading a page.

Web search is left to the writers' own Claude or Codex, which search the web
themselves and write into a draft over /mcp/research; the server runs no
search engine of its own.

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

Reading a pasted page
---------------------
FT and WSJ refuse the server outright and Nikkei serves it the teaser, so a
writer who subscribes copies the article in their own browser (select all,
copy) and pastes it into the desk. A whole-page copy carries the site's
menus, "recommended" lists and newsletter boxes as well; read_pasted keeps
the article: it drops blocks that are mostly link text, then keeps the
longest run of real paragraphs. A short paste with no menus in it (a
passage the writer selected) is kept whole.
"""
import html
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

MAX_BYTES = 3 * 1024 * 1024
TIMEOUT = 12
MAX_REDIRECTS = 5
TEXT_MAX = 60000
UA = "Mozilla/5.0 (compatible; PloverResearch/1.0; +https://ploveranalytics.com/research)"

class WebError(ValueError):
    """Worded for the writer."""


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
        self.limit = TEXT_MAX

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
            if text and self.chars < self.limit and (self.cur.startswith("h") or len(text) > 1):
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


# ---------------------------------------------------------------------------
# reading a pasted page

PASTE_MAX = 10 * 1024 * 1024   # characters of pasted HTML; past it, the plain text is used
LINK_SHARE = 0.5               # a block this much link text is a menu or a headline list
BODY_WEIGHT = 80               # a paragraph at least this long is article text
GAP = 5                        # more short blocks than this in a row ends the article
PASSAGE_WEIGHT = 3000          # a paste this short with no menus in it: a passage, kept whole
PASTE_TEXT_MAX = 400000
_CJK = re.compile(r"[\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]")


class _PasteReader(_Reader):
    """_Reader that also measures how much of each block is link text."""

    def __init__(self):
        _Reader.__init__(self)
        self.limit = PASTE_TEXT_MAX   # the menus before the article count too
        self.in_a = 0
        self.link_chars = 0
        self.shares = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.in_a += 1
        _Reader.handle_starttag(self, tag, attrs)

    def handle_endtag(self, tag):
        if tag == "a" and self.in_a:
            self.in_a -= 1
        _Reader.handle_endtag(self, tag)

    def handle_data(self, data):
        if self.cur and not self.skip and self.in_a:
            self.link_chars += len(re.sub(r"\s+", "", data))
        _Reader.handle_data(self, data)

    def _flush(self):
        n = len(self.blocks)
        total = len(re.sub(r"\s+", "", "".join(self.buf))) or 1
        share = self.link_chars / float(total)
        self.link_chars = 0
        _Reader._flush(self)
        if len(self.blocks) > n:
            self.shares.append(share)


def _weight(text):
    """Length, with Japanese, Chinese and Korean characters counted half again:
    a sentence of them carries more than the same number of Latin letters."""
    return len(text) + 0.5 * len(_CJK.findall(text))


def _article(blocks, links):
    """(blocks, heading above them, whether this was a passage): the longest
    run of article paragraphs. A short paste with no menus in it is a passage
    the writer selected, kept whole, and so is one with no paragraph long
    enough to tell. links[i] marks a block of mostly link text: never kept,
    but it still counts as a break, so a "Recommended" list ends the article."""
    if not any(links) and sum(_weight(b["text"]) for b in blocks) < PASSAGE_WEIGHT:
        return blocks, None, True
    body = [i for i, b in enumerate(blocks)
            if not links[i] and b["kind"] != "h" and _weight(b["text"]) >= BODY_WEIGHT]
    if not body:
        return [b for b, link in zip(blocks, links) if not link], None, True
    runs, run = [], [body[0]]
    for i in body[1:]:
        if i - run[-1] - 1 > GAP:
            runs.append(run)
            run = []
        run.append(i)
    runs.append(run)
    best = max(runs, key=lambda r: sum(_weight(blocks[i]["text"]) for i in r))
    start, end = best[0], best[-1]
    heading = None
    for i in range(start - 1, -1, -1):
        if blocks[i]["kind"] == "h" and not links[i]:
            heading = blocks[i]["text"]
            break
    return [b for b, link in zip(blocks[start:end + 1], links[start:end + 1]) if not link], heading, False


def read_pasted(html_text, text):
    """{title, blocks, selection} from what a writer pasted: the clipboard's
    HTML when there is any, its plain text otherwise. title is the heading
    just above the article, when there is one."""
    html_text = html_text or ""
    blocks, shares = [], []
    if html_text and len(html_text) <= PASTE_MAX:
        p = _PasteReader()
        try:
            p.feed(html_text)
            p.close()
        except Exception:  # noqa: BLE001 — a broken paste still gives what was read
            pass
        p._flush()
        blocks, shares = p.blocks, p.shares
    if all(share >= LINK_SHARE for share in shares):
        blocks, shares = [], []
        for line in re.split(r"\n+", text or ""):
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                blocks.append({"kind": "p", "text": line})
                shares.append(0.0)
    seen, unique, links = set(), [], []
    for b, share in zip(blocks, shares):
        if b["text"] not in seen:
            seen.add(b["text"])
            unique.append(b)
            links.append(share >= LINK_SHARE)
    if not any(not link for link in links):
        return {"title": "", "blocks": [], "selection": False}
    kept, heading, passage = _article(unique, links)
    return {"title": heading or "", "blocks": kept, "selection": passage}
