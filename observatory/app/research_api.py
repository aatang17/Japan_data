# -*- coding: utf-8 -*-
"""The research desk's API, under /admin/api/research.

Every endpoint needs a signed-in person with the Writing permission (see
app/staff.py); every change is written to the admin audit trail with their
email. Publishing reads each chart's data as it stands today, freezes it into
the new version, renders the page and Markdown from the same draft, and
stores all of it at once (app/research.py) — a version is never edited
afterwards.

Nothing here touches the DuckDB datasets except to read chart data through
the same function /api/v1 serves it with.
"""
import datetime
import json
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import research, research_backup, research_doc as rd, research_pages as rp, seo, staff
from .admin_api import _client_ip, _require_admin, audit

router = APIRouter(prefix="/admin/api/research", include_in_schema=False)

PRESENCE_SECONDS = 75
_presence = {}   # article id -> {actor email: (name, last seen)}


def _writer(request):
    return _require_admin(request, "writing")


def _who(person):
    return staff.actor_label(person)


def _article_or_404(article_id):
    a = research.get(article_id)
    if a is None:
        raise HTTPException(404, "No such article")
    return a


def _audit(request, person, action, detail):
    audit(action, detail, _client_ip(request), by=_who(person))


def _authors_for(ids):
    names = []
    for i in ids:
        p = staff.get(i)
        if p is not None:
            names.append(p["name"])
    return names


def _today():
    return datetime.datetime.utcnow().date().isoformat()


# ---------------------------------------------------------------------------
# list, create, import

@router.get("/articles")
def list_articles(request: Request):
    _writer(request)
    return {"articles": research.list_articles(), "backup": research_backup.read_status(),
            "site": seo.SITE_BASE_URL}


@router.get("/authors")
def authors(request: Request):
    """Everyone who can be credited: active people with the Writing permission."""
    _writer(request)
    return {"authors": [{"id": p["id"], "name": p["name"]} for p in staff.list_all()
                        if p["status"] == "active" and "writing" in p["permissions"]]}


@router.post("/articles")
def create_article(request: Request):
    person = _writer(request)
    draft = rd.new_draft()
    if not person.get("shared"):
        draft["authors"] = [person["id"]]
    a = research.create(_who(person), draft)
    _audit(request, person, "article_created", "article %d" % a["id"])
    return a


class ImportBody(BaseModel):
    markdown: str


@router.post("/import")
def import_markdown(body: ImportBody, request: Request):
    person = _writer(request)
    if len(body.markdown) > 2000000:
        raise HTTPException(400, "That file is too large to import.")
    try:
        draft = rd.import_markdown(body.markdown)
    except rd.DocError as exc:
        raise HTTPException(400, str(exc))
    if not person.get("shared"):
        draft["authors"] = [person["id"]]
    a = research.create(_who(person), draft)
    _audit(request, person, "article_imported", "article %d: %s" % (a["id"], draft["title"]))
    return a


# ---------------------------------------------------------------------------
# one article

def _others(article_id, me):
    now = time.time()
    seen = _presence.get(article_id, {})
    return [{"name": name, "email": email} for email, (name, at) in seen.items()
            if email != me and now - at < PRESENCE_SECONDS]


@router.get("/articles/{article_id}")
def get_article(article_id: int, request: Request):
    person = _writer(request)
    a = _article_or_404(article_id)
    a["others"] = _others(article_id, _who(person))
    a["site"] = seo.SITE_BASE_URL
    return a


@router.post("/articles/{article_id}/presence")
def presence(article_id: int, request: Request):
    """Called every half minute by an open editor: who else has it open."""
    person = _writer(request)
    a = research.get(article_id)
    if a is None:
        raise HTTPException(404, "No such article")
    _presence.setdefault(article_id, {})[_who(person)] = (person["name"], time.time())
    return {"others": _others(article_id, _who(person)), "revision": a["revision"],
            "updated_by": a["updated_by"], "updated_at": a["updated_at"]}


class SaveBody(BaseModel):
    draft: dict
    base_revision: int
    label: Optional[str] = None


@router.put("/articles/{article_id}")
def save_article(article_id: int, body: SaveBody, request: Request):
    person = _writer(request)
    _article_or_404(article_id)
    if body.draft.get("slug"):
        slug = rd.plain(body.draft.get("slug"), rd.SLUG_MAX).lower()
        if rd._SLUG.match(slug) and research.slug_taken(slug, article_id):
            raise HTTPException(400, "Another article already uses the address /research/%s."
                                % slug)
    try:
        saved = research.save(article_id, body.draft, body.base_revision, _who(person),
                              label=rd.plain(body.label, 80) or None)
    except research.Conflict as exc:
        return JSONResponse(status_code=409, content={
            "detail": "%s saved a newer version of this article." % exc.current["updated_by"],
            "current": exc.current})
    except (rd.DocError, research.ResearchError) as exc:
        raise HTTPException(400, str(exc))
    return saved


@router.delete("/articles/{article_id}")
def delete_article(article_id: int, request: Request):
    person = _writer(request)
    a = _article_or_404(article_id)
    try:
        research.delete_draft(article_id)
    except research.ResearchError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "article_deleted", "article %d: %s" % (article_id, a["title"]))
    return {"deleted": article_id}


@router.get("/articles/{article_id}/history")
def article_history(article_id: int, request: Request):
    _writer(request)
    _article_or_404(article_id)
    return {"history": research.history(article_id)}


@router.get("/articles/{article_id}/history/{history_id}")
def article_history_draft(article_id: int, history_id: int, request: Request):
    _writer(request)
    draft = research.history_draft(article_id, history_id)
    if draft is None:
        raise HTTPException(404, "No such saved copy")
    return {"draft": draft}


def _check(a):
    """(problems, author names, snapshots) for the article's saved draft."""
    draft = a["draft"]
    names = _authors_for(draft["authors"])
    problems = rd.publish_problems(draft, names)
    if draft["slug"] and rd._SLUG.match(draft["slug"]) and not a["slug_locked"] and \
            research.slug_taken(draft["slug"], a["id"]):
        problems.append("Another article already uses the address /research/%s."
                        % draft["slug"])
    snaps = rp.build_snapshots(draft, _today())
    charts, _ = rd.chart_numbering(draft["blocks"])
    for b in draft["blocks"]:
        if b["type"] == "chart" and b["dataset"] and b["series"]:
            err = (snaps.get(b["id"]) or {}).get("error")
            if err:
                problems.append("Chart %d: %s" % (charts[b["id"]], err))
    return problems, names, snaps


@router.get("/articles/{article_id}/check")
def check_article(article_id: int, request: Request):
    _writer(request)
    a = _article_or_404(article_id)
    problems, names, _ = _check(a)
    return {"problems": problems, "authors": names, "revision": a["revision"],
            "version": (a["published_version"] or 0) + 1,
            "url": seo.SITE_BASE_URL + "/research/" + (a["slug"] or a["draft"]["slug"] or "")}


def _preview_version(a, names, snaps):
    draft = a["draft"]
    return {
        "slug": draft["slug"] or "preview",
        "version": (a["published_version"] or 0) + 1,
        "title": draft["title"] or "Untitled",
        "dek": draft["dek"],
        "summary": draft["summary"],
        "authors": names,
        "published_at": datetime.datetime.utcnow().isoformat() + "Z",
        "body_html": rd.render_body(draft, snaps),
        "doc": draft,
        "snapshots": snaps,
    }


@router.get("/articles/{article_id}/preview")
def preview_article(article_id: int, request: Request):
    """The saved draft exactly as the published page would show it now."""
    _writer(request)
    a = _article_or_404(article_id)
    names = _authors_for(a["draft"]["authors"])
    snaps = rp.build_snapshots(a["draft"], _today())
    v = _preview_version(a, names, snaps)
    versions = [dict(x, change_note=x["change_note"]) for x in
                research.versions_meta(article_id)] if a["published_version"] else []
    versions.append({"version": v["version"], "published_at": v["published_at"],
                     "change_note": "This preview."})
    main = rp.article_main(v, versions, v["version"], "", preview=True)
    text = rp.page("Preview · %s" % v["title"], v["summary"], None, main,
                   data=rp._chart_data(v), robots="noindex, nofollow", preview=True)
    headers = dict(rp.SECURITY_HEADERS)
    headers["Cache-Control"] = "no-store"
    return HTMLResponse(text, headers=headers)


class PublishBody(BaseModel):
    base_revision: int
    change_note: str = ""


@router.post("/articles/{article_id}/publish")
def publish_article(article_id: int, body: PublishBody, request: Request):
    person = _writer(request)
    a = _article_or_404(article_id)
    if a["revision"] != body.base_revision:
        return JSONResponse(status_code=409, content={
            "detail": "%s saved a newer version of this article. Reload it, check it, and "
                      "publish again." % a["updated_by"]})
    if a["status"] == "withdrawn":
        raise HTTPException(400, "Reinstate the article before publishing a new version.")
    problems, names, snaps = _check(a)
    if problems:
        return JSONResponse(status_code=400, content={
            "detail": "The article is not ready to publish.", "problems": problems})
    draft = dict(a["draft"])
    if a["slug_locked"]:
        draft["slug"] = a["slug"]
    body_html = rd.render_body(draft, snaps)
    markdown = rd.render_markdown(draft, snaps, site=seo.SITE_BASE_URL)
    try:
        done = research.publish(article_id, body.base_revision, _who(person),
                                rd.plain(body.change_note, 400), draft, names, snaps,
                                body_html, markdown)
    except research.Conflict:
        return JSONResponse(status_code=409, content={
            "detail": "Someone saved while this was publishing. Reload and publish again."})
    except research.ResearchError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "article_published", "/research/%s version %d"
           % (done["slug"], done["version"]))
    rp.announce(done["slug"])
    research_backup.soon()
    done["url"] = seo.SITE_BASE_URL + "/research/" + done["slug"]
    return done


class WithdrawBody(BaseModel):
    reason: str


@router.post("/articles/{article_id}/withdraw")
def withdraw_article(article_id: int, body: WithdrawBody, request: Request):
    person = _writer(request)
    a = _article_or_404(article_id)
    try:
        research.withdraw(article_id, _who(person), body.reason)
    except research.ResearchError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "article_withdrawn", "/research/%s: %s" % (a["slug"], body.reason))
    research_backup.soon()
    return research.get(article_id)


@router.post("/articles/{article_id}/reinstate")
def reinstate_article(article_id: int, request: Request):
    person = _writer(request)
    a = _article_or_404(article_id)
    try:
        research.reinstate(article_id)
    except research.ResearchError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "article_reinstated", "/research/%s" % a["slug"])
    return research.get(article_id)


@router.get("/articles/{article_id}/substack")
def substack(article_id: int, request: Request):
    """What to paste into Substack: the title, the standfirst, the summary and
    a link to the full piece. Rich text and plain text, so either paste works."""
    _writer(request)
    a = _article_or_404(article_id)
    if not a["published_version"]:
        raise HTTPException(400, "Publish the article first: the Substack post links to it.")
    v = research.version(article_id, a["published_version"])
    url = seo.SITE_BASE_URL + "/research/" + v["slug"]
    link_text = "Read the full note, with the charts and data, on PloverResearch"
    html = "".join([
        "<p>%s</p>" % rd.esc(v["summary"]),
        '<p><a href="%s">%s →</a></p>' % (rd.esc(url), link_text),
    ])
    text = "%s\n\n%s: %s\n" % (v["summary"], link_text, url)
    charts = []
    for b in v["doc"]["blocks"]:
        if b["type"] == "chart" and not (v["snapshots"].get(b["id"]) or {}).get("error"):
            charts.append({"id": b["id"], "title": b["title"], "block": b,
                           "snap": v["snapshots"][b["id"]]})
    return {"title": v["title"], "subtitle": v["dek"], "html": html, "text": text, "url": url,
            "charts": charts, "version": v["version"]}


# ---------------------------------------------------------------------------
# research panel: Plover data, and reading a web page

# Company pages a chart can be copied from, with the parameter each one reads
# its company from (company.html takes `code`; the dataset pages take `c`).
COMPANY_PAGES = [
    ("Company Overview", "/company.html?code=%s"),
    ("Financials", "/financials.html?c=%s"),
    ("Ownership", "/ownership.html?c=%s"),
    ("Earnings", "/earnings.html?c=%s"),
    ("Buybacks", "/buyback.html?c=%s"),
    ("Business Risks", "/risks.html?c=%s"),
]


@router.get("/data/search")
def data_search(request: Request, q: str = ""):
    """Plover datasets, series and companies matching q — the same search the
    public MCP server runs — with the page each hit lives on."""
    _writer(request)
    from . import registry, tools_v2
    if not q.strip():
        return {"series": [], "companies": []}
    raw = json.loads(tools_v2.search(q.strip()[:200], limit=15))
    if raw.get("error"):
        raise HTTPException(400, raw["error"])
    series = []
    for h in raw.get("series") or []:
        card = registry.get(h["dataset"]) or {}
        series.append({"dataset": h["dataset"], "code": h["code"], "name": h["name_en"],
                       "unit": h.get("unit"),
                       "dataset_name": (card.get("name") or {}).get("en") or h["dataset"],
                       "page": card.get("page")})
    companies = []
    for c in raw.get("companies") or []:
        # Japanese listed companies only: the copyable pages below read a
        # securities code; a US filer (cik:…) has no such pages.
        if not c.get("sec_code") or str(c["sec_code"]).startswith("cik:"):
            continue
        if len(companies) >= 8:
            break
        companies.append({"code": c["sec_code"], "name": c.get("name_en") or c.get("name"),
                          "name_ja": c.get("name"),
                          "pages": [{"label": lab, "url": tpl % c["sec_code"]}
                                    for lab, tpl in COMPANY_PAGES]})
    return {"series": series, "companies": companies}


class ReadBody(BaseModel):
    url: str


@router.post("/web/read")
def web_read(body: ReadBody, request: Request):
    _writer(request)
    from . import research_web
    try:
        return research_web.read(body.url)
    except research_web.WebError as exc:
        raise HTTPException(400, str(exc))


# ---------------------------------------------------------------------------
# images

@router.post("/media")
async def upload_media(request: Request):
    """The image as the raw request body; X-File-Name carries its name. A raw
    body, not a multipart form, so no form-parsing package is needed."""
    person = _writer(request)
    length = int(request.headers.get("content-length") or 0)
    if length > research.MEDIA_MAX_BYTES:
        raise HTTPException(413, "Images can be up to %d MB."
                            % (research.MEDIA_MAX_BYTES // (1024 * 1024)))
    data = await request.body()
    try:
        info = research.add_media(data, request.headers.get("x-file-name", ""), _who(person))
    except research.ResearchError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "image_uploaded", "%s.%s (%d bytes)"
           % (info["media"][:12], info["ext"], info["bytes"]))
    return info


@router.post("/backup")
def backup_now(request: Request):
    person = _writer(request)
    status = research_backup.run()
    _audit(request, person, "backup_run", "ok" if status.get("ok") else status.get("error"))
    return status


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)
