# -*- coding: utf-8 -*-
"""Pages a writer sends from their own browser: reading what they subscribe to.

The desk's page reader (research_web.py) fetches a page from the server, with
no login, so an FT, WSJ or Nikkei article comes back as its teaser. "Send to
Plover" is a bookmark the writer keeps in their own browser: on a page they
can read, it takes the article's text from that page — in the browser, where
they are signed in — and opens /clip.html with the text in the address's
#fragment. The fragment never leaves the browser in a request, so the text is
not in any server or proxy log; clip.html posts it here and the desk shows it
in Research › Web Page, to cite or quote, and the AI tab's read_page uses it.

Why the fragment and not postMessage: FT serves its pages with
Cross-Origin-Opener-Policy: same-origin, which cuts the link between the
article and any window it opens, so the two cannot message each other.

What is kept, and who sees it
-----------------------------
A sent page belongs to the person who sent it: only they can list, read or
delete it, and an AI run reads only the pages of the writer who started it.
Text only, as the writer's browser extracted it — nothing from the page is
ever rendered as HTML. The same address sent again replaces the earlier
copy, and each person keeps their newest KEEP pages. The copy is for reading
and citing; the desk's citation names the publisher's address, not ours.

The browser is the writer's, so what arrives is what they say the page said:
the desk labels it "sent from your browser", and the address is checked only
for shape.
"""
import json
import re
import time
import urllib.parse
from typing import List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import research

KEEP = 50
TEXT_MAX = 120000          # characters across all blocks
BLOCKS_MAX = 1500
KINDS = ("h", "p", "quote")

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY,
    staff_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    match_key TEXT NOT NULL,
    title TEXT NOT NULL,
    site TEXT NOT NULL,
    published TEXT NOT NULL,
    author TEXT NOT NULL,
    blocks TEXT NOT NULL,
    chars INTEGER NOT NULL,
    selection INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS clips_by_person ON clips (staff_id, created_at);
"""

_ready = set()


class ClipError(ValueError):
    """Worded for the writer."""


def _conn():
    c = research.conn()
    path = str(research.db_path())
    if path not in _ready:
        c.executescript(SCHEMA)
        c.commit()
        _ready.add(path)
    return c


def _clean(text, limit):
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def match_key(url):
    """The address without its query or fragment, lower-cased host: how a
    later read_page of the same article finds the copy (WSJ and FT add
    tracking parameters)."""
    p = urllib.parse.urlsplit(url.strip())
    return "%s://%s%s" % (p.scheme.lower(), (p.netloc or "").lower(), p.path.rstrip("/") or "/")


def _check_url(url):
    url = (url or "").strip()
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.netloc or len(url) > 2000:
        raise ClipError("The page's address did not come through. Click Send to Plover again on the page.")
    return url


def _shape(r, full=False):
    out = {"id": r["id"], "url": r["url"], "title": r["title"], "site": r["site"],
           "published": r["published"], "author": r["author"], "chars": r["chars"],
           "selection": bool(r["selection"]), "sent_at": r["created_at"], "sent": True, "pdf": False}
    if full:
        out["blocks"] = json.loads(r["blocks"])
    return out


def add(staff_id, url, title, site, published, author, blocks, selection=False):
    url = _check_url(url)
    kept, total = [], 0
    for b in (blocks or [])[:BLOCKS_MAX]:
        kind = b.get("kind") if isinstance(b, dict) else None
        text = _clean(b.get("text") if isinstance(b, dict) else "", 20000)
        if kind not in KINDS or not text:
            continue
        if total + len(text) > TEXT_MAX:
            break
        kept.append({"kind": kind, "text": text})
        total += len(text)
    if not kept:
        raise ClipError("No article text came through from that page. Open the article itself "
                        "(not a list of headlines), or select the passage you want and click again.")
    host = urllib.parse.urlsplit(url).hostname or ""
    row = (staff_id, url, match_key(url), _clean(title, 300) or url, _clean(site, 120) or host,
           _clean(published, 30), _clean(author, 120), json.dumps(kept, ensure_ascii=False),
           total, 1 if selection else 0, int(time.time()))
    c = _conn()
    with c:
        c.execute("DELETE FROM clips WHERE staff_id = ? AND match_key = ?", (staff_id, row[2]))
        cur = c.execute(
            "INSERT INTO clips (staff_id, url, match_key, title, site, published, author, blocks, "
            "chars, selection, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
        new_id = cur.lastrowid
        c.execute("DELETE FROM clips WHERE staff_id = ? AND id NOT IN (SELECT id FROM clips "
                  "WHERE staff_id = ? ORDER BY created_at DESC, id DESC LIMIT ?)",
                  (staff_id, staff_id, KEEP))
    return get(staff_id, new_id)


def list_for(staff_id):
    rows = _conn().execute("SELECT * FROM clips WHERE staff_id = ? ORDER BY created_at DESC, id DESC",
                           (staff_id,)).fetchall()
    return [_shape(r) for r in rows]


def get(staff_id, clip_id):
    r = _conn().execute("SELECT * FROM clips WHERE id = ? AND staff_id = ?",
                        (clip_id, staff_id)).fetchone()
    return _shape(r, full=True) if r is not None else None


def find(staff_id, url):
    """The writer's copy of this page, or None — for the AI tab's read_page."""
    try:
        key = match_key(url)
    except ValueError:
        return None
    r = _conn().execute("SELECT * FROM clips WHERE staff_id = ? AND match_key = ? "
                        "ORDER BY created_at DESC LIMIT 1", (staff_id, key)).fetchone()
    return _shape(r, full=True) if r is not None else None


def delete(staff_id, clip_id):
    c = _conn()
    with c:
        n = c.execute("DELETE FROM clips WHERE id = ? AND staff_id = ?", (clip_id, staff_id)).rowcount
    return n > 0


# ---------------------------------------------------------------------------
# the API, under /admin/api/research like the rest of the desk

router = APIRouter(prefix="/admin/api/research", include_in_schema=False)


def _writer(request):
    from .research_api import _writer as writer
    return writer(request)


class Block(BaseModel):
    kind: str
    text: str


class ClipBody(BaseModel):
    url: str
    title: str = ""
    site: str = ""
    published: str = ""
    author: str = ""
    selection: bool = False
    blocks: List[Block] = []


@router.post("/clips")
def send_clip(body: ClipBody, request: Request):
    person = _writer(request)
    try:
        return add(person["id"], body.url, body.title, body.site, body.published, body.author,
                   [{"kind": b.kind, "text": b.text} for b in body.blocks], body.selection)
    except ClipError as exc:
        raise HTTPException(400, str(exc))


@router.get("/clips")
def list_clips(request: Request):
    person = _writer(request)
    return {"clips": list_for(person["id"]), "keep": KEEP}


@router.get("/clips/{clip_id}")
def read_clip(clip_id: int, request: Request):
    person = _writer(request)
    clip = get(person["id"], clip_id)
    if clip is None:
        raise HTTPException(404, "That page is no longer in your sent pages.")
    return clip


@router.delete("/clips/{clip_id}")
def delete_clip(clip_id: int, request: Request):
    person = _writer(request)
    if not delete(person["id"], clip_id):
        raise HTTPException(404, "That page is no longer in your sent pages.")
    return {"ok": True}
