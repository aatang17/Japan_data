# -*- coding: utf-8 -*-
"""Admin → Assistant Settings, under /admin/api/ai: PloverResearch's skills,
house style and connectors, and each person's Google Drive connection.

Every publication has its own skills, house style and connectors; its owner
and editors keep them in the Writer Desk (app/writer_api.py). This page is
PloverResearch's (publication 1) only, and never reaches another's.

Anyone with the Writing permission can read all of it and edit the skills and
the house style — writers are the people who use them. Connectors and the
team's Google Drive switch need the Team permission: a connector decides what
data an AI run can reach. Google Drive is connected per person, with their own
Google account, and needs a personal login (the shared password is nobody).
Every change is written to the admin audit trail.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import connectors, research, seo, skills, staff, staff_google
from .admin_api import _client_ip, _require_admin, audit

router = APIRouter(prefix="/admin/api/ai", include_in_schema=False)
HOME = research.HOME


def _writer(request):
    return _require_admin(request, "writing")


def _team(request):
    return _require_admin(request, "team")


def _personal(request):
    person = _writer(request)
    if person.get("shared") or not person.get("id"):
        raise HTTPException(403, "Sign in with your own account: a Google connection is personal.")
    return person


def _audit(request, person, action, detail):
    audit(action, detail, _client_ip(request), by=staff.actor_label(person))


def _base(request):
    # behind the proxy the request looks like http; Google wants the exact
    # https address it has on file (the same rule as the setup links)
    return seo.SITE_BASE_URL if seo.is_https(request) else str(request.base_url).rstrip("/")


@router.get("/setup")
def setup(request: Request):
    """Everything the Assistant Settings page shows, in one call."""
    person = _writer(request)
    me = person.get("id") if not person.get("shared") else None
    return {"skills": skills.list_skills(publication_id=HOME), "house_style": skills.house_style(HOME),
            "default_house_style": skills.HOUSE_STYLE,
            "connectors": connectors.list_connectors(publication_id=HOME),
            "google": dict(staff_google.status_for(me) if me else
                           {"configured": staff_google.configured(),
                            "team_enabled": staff_google.team_enabled(), "connected": False},
                           redirect_uri=staff_google.redirect_uri(_base(request)), personal=bool(me)),
            "can_manage": "team" in person["permissions"]}


# ---------------------------------------------------------------- skills

class SkillBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    enabled: Optional[bool] = None
    writes: Optional[bool] = None


@router.post("/skills")
def skill_create(body: SkillBody, request: Request):
    person = _writer(request)
    try:
        s = skills.create(body.name, body.description, body.instructions, staff.actor_label(person),
                          True if body.writes is None else body.writes, publication_id=HOME)
    except skills.SkillError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "ai_skill_created", s["name"])
    return s


@router.put("/skills/{skill_id}")
def skill_update(skill_id: int, body: SkillBody, request: Request):
    person = _writer(request)
    try:
        s = skills.update(skill_id, staff.actor_label(person), body.name, body.description,
                          body.instructions, body.enabled, body.writes, publication_id=HOME)
    except skills.SkillError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "ai_skill_updated", s["name"])
    return s


@router.delete("/skills/{skill_id}")
def skill_delete(skill_id: int, request: Request):
    person = _writer(request)
    s = skills.get(skill_id, HOME)
    if s is None:
        raise HTTPException(404, "No such skill")
    skills.delete(skill_id, HOME)
    _audit(request, person, "ai_skill_deleted", s["name"])
    return {"ok": True}


class StyleBody(BaseModel):
    text: str


@router.put("/house-style")
def house_style(body: StyleBody, request: Request):
    person = _writer(request)
    try:
        text = skills.set_house_style(body.text, HOME)
    except skills.SkillError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "ai_house_style", "%d characters" % len(text))
    return {"house_style": text}


# ---------------------------------------------------------------- connectors

class ConnectorBody(BaseModel):
    label: Optional[str] = None
    url: Optional[str] = None
    auth_kind: Optional[str] = None
    header_name: Optional[str] = None
    key: Optional[str] = None
    enabled: Optional[bool] = None


class ToolBody(BaseModel):
    tool: str
    on: bool


@router.post("/connectors")
def connector_create(body: ConnectorBody, request: Request):
    person = _team(request)
    try:
        c = connectors.create(body.label, body.url, body.auth_kind or "none", body.header_name,
                              (body.key or "").strip() or None, staff.actor_label(person),
                              publication_id=HOME)
    except connectors.ConnectorError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "ai_connector_added", "%s %s" % (c["label"], c["url"]))
    return c


@router.put("/connectors/{connector_id}")
def connector_update(connector_id: int, body: ConnectorBody, request: Request):
    person = _team(request)
    try:
        c = connectors.update(connector_id, staff.actor_label(person), body.label, body.url,
                              body.auth_kind, body.header_name, (body.key or "").strip() or None,
                              body.enabled, publication_id=HOME)
    except connectors.ConnectorError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "ai_connector_updated", c["label"])
    return c


@router.post("/connectors/{connector_id}/check")
def connector_check(connector_id: int, request: Request):
    person = _team(request)
    try:
        return connectors.check(connector_id, publication_id=HOME)
    except connectors.ConnectorError as exc:
        raise HTTPException(400, str(exc))


@router.put("/connectors/{connector_id}/tools")
def connector_tool(connector_id: int, body: ToolBody, request: Request):
    person = _team(request)
    try:
        c = connectors.set_tool(connector_id, body.tool, body.on, publication_id=HOME)
    except connectors.ConnectorError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "ai_connector_tool", "%s: %s %s" % (c["label"], body.tool,
                                                               "on" if body.on else "off"))
    return c


@router.delete("/connectors/{connector_id}")
def connector_delete(connector_id: int, request: Request):
    person = _team(request)
    c = connectors.get(connector_id, publication_id=HOME)
    if c is None:
        raise HTTPException(404, "No such connector")
    connectors.delete(connector_id, publication_id=HOME)
    _audit(request, person, "ai_connector_removed", c["label"])
    return {"ok": True}


# ---------------------------------------------------------------- Google Drive

class SwitchBody(BaseModel):
    on: bool


@router.put("/google/team")
def google_team(body: SwitchBody, request: Request):
    person = _team(request)
    staff_google.set_team_enabled(body.on)
    _audit(request, person, "ai_google_team", "on" if body.on else "off")
    return {"team_enabled": staff_google.team_enabled()}


@router.get("/google")
def google_status(request: Request):
    return staff_google.status_for(_personal(request)["id"])


@router.post("/google/start")
def google_start(request: Request):
    """The Google consent address; the page sends the person there."""
    person = _personal(request)
    try:
        return {"url": staff_google.auth_url(person["id"], _base(request))}
    except staff_google.GoogleError as exc:
        raise HTTPException(400, str(exc))


@router.get("/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Google sends the person back here. The answer is a redirect to Assistant Settings
    with the outcome, never a page of its own."""
    person = _personal(request)
    if error:
        return RedirectResponse("/admin.html?google=refused#ai", status_code=303)
    if not staff_google.check_state(state, person["id"]):
        return RedirectResponse("/admin.html?google=expired#ai", status_code=303)
    try:
        staff_google.finish(person["id"], code, _base(request))
    except staff_google.GoogleError:
        return RedirectResponse("/admin.html?google=failed#ai", status_code=303)
    _audit(request, person, "ai_google_connected", "")
    return RedirectResponse("/admin.html?google=connected#ai", status_code=303)


@router.post("/google/disconnect")
def google_disconnect(request: Request):
    person = _personal(request)
    staff_google.disconnect(person["id"])
    _audit(request, person, "ai_google_disconnected", "")
    return staff_google.status_for(person["id"])
