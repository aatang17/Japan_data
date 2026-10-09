# -*- coding: utf-8 -*-
"""The Writer Desk's own API, under /admin/api/write (``web/write.html``).

The article endpoints the desk shares with the editor are in
app/research_api.py. This module holds what is about the writer and their
publications rather than one article:

``GET  /me``                                who is signed in, and where they write
``POST /signout``                           end this browser's writer sessions
``POST /publications``                      open a publication (Team permission)
``PUT  /publications/{id}``                 its name, tagline and description (owner)
``GET  /publications/{id}/members``         who writes there (any member)
``POST /publications/{id}/members``         invite someone (owner); returns a sign-in link
``PUT  /publications/{id}/members``         change a role (owner)
``DELETE /publications/{id}/members``       remove someone (owner)
``POST /publications/{id}/members/link``    a fresh sign-in link for a member (owner)
``GET/POST/DELETE /keys``                   personal keys for the writer's own AI agent

It sits under /admin/api only so that the Plover team's staff session cookie
(scoped to /admin) reaches it; nothing here is part of the admin console.
"""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from . import accounts, mailer, research, seo, staff, writers
from .admin_api import STAFF_COOKIE, _client_ip, audit

router = APIRouter(prefix="/admin/api/write", include_in_schema=False)


def _audit(request, person, action, detail):
    audit(action, detail, _client_ip(request), by=staff.actor_label(person))


def _pub_or_404(publication_id):
    pub = research.publication(publication_id)
    if pub is None:
        raise HTTPException(404, "No such publication")
    return pub


def _need(person, publication_id, role):
    pub = _pub_or_404(publication_id)
    if writers.role(person, publication_id) is None:
        raise HTTPException(404, "No such publication")
    if not writers.at_least(person, publication_id, role):
        raise HTTPException(403, "Only the publication's %ss can do that." % role)
    return pub


def _pub_view(pub, role):
    return {"id": pub["id"], "slug": pub["slug"], "name": pub["name"], "tagline": pub["tagline"],
            "about": pub["about"], "base": pub["base"], "home": pub["home"], "role": role,
            "url": seo.SITE_BASE_URL + pub["base"]}


# ------------------------------------------------------------------ who

@router.get("/me")
def me(request: Request):
    """Never 401: the page uses this to choose between the sign-in screen and
    the desk, and says why someone signed in still cannot write."""
    sign_in = {"email_links": accounts.enabled(), "email_delivery": mailer.configured()}
    person = writers.current_writer(request)
    if person is None:
        email = writers.signed_in_email(request)
        return {"signed_in": bool(email), "writer": False, "email": email, "sign_in": sign_in}
    mine = writers.roles(person)
    pubs = [_pub_view(research.publication(pid), r) for pid, r in sorted(mine.items())]
    return {"signed_in": True, "writer": bool(pubs), "email": person["email"],
            "person": {"id": person["id"], "name": person["name"], "email": person["email"]},
            "publications": pubs,
            "can_create_publications": writers.can_create_publications(person),
            "sign_in": sign_in}


@router.post("/signout")
def signout(request: Request, response: Response):
    """Ends both kinds of session this browser may hold for the desk."""
    person = writers.current_writer(request)
    staff.end_session(request.cookies.get(STAFF_COOKIE))
    response.delete_cookie(STAFF_COOKIE, path="/admin")
    raw = request.cookies.get(accounts.COOKIE)
    if raw:
        db = accounts.conn()
        with accounts._lock:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (accounts._hash(raw),))
            db.commit()
        response.delete_cookie(accounts.COOKIE, path="/")
    if person is not None:
        _audit(request, person, "writer_signout", "signed out of the Writer Desk")
    return {"signed_out": True}


# --------------------------------------------------------- publications

class NewPublication(BaseModel):
    slug: str
    name: str
    tagline: str = ""
    owner_email: str
    owner_name: str = ""


@router.post("/publications")
def create_publication(body: NewPublication, request: Request):
    """Open a publication and make its first owner. While publications are by
    invitation, only the Plover team (Team permission) opens them."""
    person = writers.require_writer(request)
    if not writers.can_create_publications(person):
        raise HTTPException(403, "Publications are opened by the Plover team for now.")
    actor = staff.actor_label(person)
    owner_email = staff.normalise_email(body.owner_email)
    try:
        if owner_email != person["email"]:
            staff.ensure_person(owner_email, body.owner_name, actor)
        pub = research.create_publication(body.slug, body.name, body.tagline, actor)
    except (staff.StaffError, research.ResearchError) as exc:
        raise HTTPException(400, str(exc))
    research.set_member(pub["id"], owner_email, "owner", actor)
    link = None if owner_email == person["email"] else writers.signin_link(request, owner_email)
    _audit(request, person, "publication_created", "%s (%s), owner %s"
           % (pub["base"], pub["name"], owner_email))
    return {"publication": _pub_view(pub, writers.role(person, pub["id"])), "link": link,
            "owner_email": owner_email}


class PublicationBody(BaseModel):
    name: str
    tagline: str = ""
    about: str = ""


@router.put("/publications/{publication_id}")
def update_publication(publication_id: int, body: PublicationBody, request: Request):
    person = writers.require_writer(request)
    pub = _need(person, publication_id, "owner")
    if pub["home"]:
        raise HTTPException(400, "PloverResearch's name and description are part of the site "
                                 "and are changed with it, not here.")
    try:
        pub = research.update_publication(publication_id, staff.actor_label(person), body.name,
                                          body.tagline, body.about)
    except research.ResearchError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "publication_updated", pub["base"])
    return _pub_view(pub, writers.role(person, publication_id))


# --------------------------------------------------------------- members

@router.get("/publications/{publication_id}/members")
def members(publication_id: int, request: Request):
    person = writers.require_writer(request)
    _need(person, publication_id, "writer")
    return {"members": writers.member_list(publication_id),
            "manage": writers.at_least(person, publication_id, "owner")}


class InviteBody(BaseModel):
    email: str
    name: str = ""
    role: str = "writer"


@router.post("/publications/{publication_id}/members")
def invite(publication_id: int, body: InviteBody, request: Request):
    person = writers.require_writer(request)
    pub = _need(person, publication_id, "owner")
    row, link = writers.invite(request, publication_id, body.email, body.name, body.role,
                               staff.actor_label(person))
    _audit(request, person, "member_invited", "%s to %s as %s" % (row["email"], pub["base"],
                                                                  row["role"]))
    return {"member": row, "link": link}


class RoleBody(BaseModel):
    email: str
    role: str


@router.put("/publications/{publication_id}/members")
def change_role(publication_id: int, body: RoleBody, request: Request):
    person = writers.require_writer(request)
    pub = _need(person, publication_id, "owner")
    writers.set_role(publication_id, body.email, body.role, staff.actor_label(person))
    _audit(request, person, "member_role", "%s in %s: %s" % (body.email, pub["base"], body.role))
    return {"members": writers.member_list(publication_id), "manage": True}


@router.delete("/publications/{publication_id}/members")
def remove(publication_id: int, request: Request, email: str = ""):
    person = writers.require_writer(request)
    pub = _need(person, publication_id, "owner")
    writers.remove(publication_id, email)
    _audit(request, person, "member_removed", "%s from %s" % (email, pub["base"]))
    return {"members": writers.member_list(publication_id), "manage": True}


class LinkBody(BaseModel):
    email: str


@router.post("/publications/{publication_id}/members/link")
def fresh_link(publication_id: int, body: LinkBody, request: Request):
    """A new sign-in link for a member who lost theirs. It cancels the old one."""
    person = writers.require_writer(request)
    pub = _need(person, publication_id, "owner")
    email = staff.normalise_email(body.email)
    if not any(m["email"] == email for m in writers.member_list(publication_id)):
        raise HTTPException(404, "%s does not write here." % email)
    link = writers.signin_link(request, email)
    if link is None:
        raise HTTPException(400, "Email sign-in is switched off on this server.")
    _audit(request, person, "member_link", "%s in %s" % (email, pub["base"]))
    return {"link": link, "email": email}


# ------------------------------------------------------------------ keys

def _mcp_url(request):
    base = seo.SITE_BASE_URL if seo.is_https(request) else str(request.base_url).rstrip("/")
    return base + "/mcp/research"


@router.get("/keys")
def my_keys(request: Request):
    person = writers.require_writer(request)
    return {"keys": staff.list_keys(person["id"]), "endpoint": _mcp_url(request)}


class KeyBody(BaseModel):
    label: str = ""


@router.post("/keys")
def make_key(body: KeyBody, request: Request):
    person = writers.require_writer(request)
    try:
        made = staff.create_key(person["id"], body.label)
    except staff.StaffError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "key_created", made["label"])
    made["endpoint"] = _mcp_url(request)
    return made


@router.delete("/keys/{key_id}")
def drop_key(key_id: int, request: Request):
    person = writers.require_writer(request)
    try:
        staff.revoke_key(person["id"], key_id)
    except staff.StaffError as exc:
        raise HTTPException(404, str(exc))
    _audit(request, person, "key_revoked", "key %d" % key_id)
    return {"revoked": key_id}
