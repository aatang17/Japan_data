# -*- coding: utf-8 -*-
"""Who is writing, and what they may do in each publication.

Who
---
A writer is a person in ``app/staff.py`` — the same record that holds their
AI settings, personal keys and Google link. They reach the desk one of two
ways, and both land on that record:

* an **email sign-in link** (``app/accounts.py``): the address is looked up
  in staff. Writers invited to a publication sign in this way and never see
  the admin console.
* a **staff password session** (the admin console's login): how the Plover
  team has always signed in.

The shared admin password is never a writer: it is nobody, and an article's
history must say who wrote it.

Roles
-----
Each publication has members with one role:

``owner``   everything an editor can, plus the publication's settings and its
            members
``editor``  write, edit, publish, withdraw and reinstate any of its articles
``writer``  write and preview their own articles (started by them or crediting
            them); ask an editor to publish. Cannot publish.

PloverResearch (publication 1) also counts the admin console's Writing
permission: Writing makes a person its editor, Writing with Team its owner.
That keeps the Team page working as before; explicit membership only ever
adds to it.
"""
from fastapi import HTTPException

from . import accounts, research, staff

RANK = {"writer": 1, "editor": 2, "owner": 3}
ROLE_LABEL = {"owner": "Owner", "editor": "Editor", "writer": "Writer"}
WRITE_PAGE = "write.html"


# ---------------------------------------------------------------- identity

def current_writer(request):
    """The signed-in person (staff record), or None."""
    from .admin_api import current_person, STAFF_COOKIE
    if request.cookies.get(STAFF_COOKIE):
        person = current_person(request)
        if person is not None and not person.get("shared"):
            return person
    account = accounts.current_account(request)
    if account is not None:
        person = staff.get_by_email(account["email"])
        if person is not None and person["status"] == "active":
            return person
    return None


def signed_in_email(request):
    """An email-link session's address, even when it has no writer record."""
    account = accounts.current_account(request)
    return account["email"] if account else None


def require_writer(request):
    """The signed-in person with at least one publication, or 401/403."""
    person = current_writer(request)
    if person is None:
        from .admin_api import current_person
        shared = current_person(request)
        if shared is not None and shared.get("shared"):
            raise HTTPException(403, "The shared admin password is nobody, and every article "
                                     "says who wrote it. Sign in with your own account to write.")
        raise HTTPException(401, "Not signed in")
    if not roles(person):
        raise HTTPException(403, "You are not a member of any publication yet. Ask the owner "
                                 "of the publication you write for to invite you.")
    return person


# ------------------------------------------------------------------- roles

def _implied_home(person):
    perms = person.get("permissions") or []
    if "writing" not in perms:
        return None
    return "owner" if "team" in perms else "editor"


def _better(a, b):
    return a if RANK.get(a, 0) >= RANK.get(b, 0) else b


def role(person, publication_id):
    """The person's role in a publication, or None."""
    best = research.member_role(publication_id, person.get("email"))
    if publication_id == research.HOME:
        best = _better(_implied_home(person), best)
    return best


def roles(person):
    """{publication id: role} for everywhere the person can write."""
    out = research.memberships(person.get("email"))
    implied = _implied_home(person)
    if implied:
        out[research.HOME] = _better(implied, out.get(research.HOME))
    return dict((k, v) for k, v in out.items() if v)


def at_least(person, publication_id, needed):
    return RANK.get(role(person, publication_id), 0) >= RANK[needed]


def _own(person, article):
    return (article.get("created_by") == person.get("email")
            or person.get("id") in (article.get("authors") or []))


def can(person, action, article):
    """Whether the person may do ``action`` to an article (a summary or full
    article from app/research.py). Actions: view, edit, publish (also
    withdraw and reinstate), delete."""
    r = role(person, article["publication_id"])
    if r is None:
        return False
    if RANK[r] >= RANK["editor"]:
        return True
    if action in ("view", "edit"):
        return _own(person, article)
    if action == "delete":
        return article.get("created_by") == person.get("email") and not article.get("published_version")
    return False


def require(person, action, article):
    if not can(person, action, article):
        if action in ("view", "edit") or role(person, article["publication_id"]) is None:
            # say nothing about an article the person may not see
            raise HTTPException(404, "No such article")
        if action == "publish":
            raise HTTPException(403, "Writers cannot publish. Use Ask to Publish and an editor "
                                     "of the publication will publish it.")
        raise HTTPException(403, "Only an editor of the publication can do that.")


def permissions_for(person, article):
    """What the editor should offer on this article."""
    return dict((a, can(person, a, article)) for a in ("edit", "publish", "delete"))


def can_create_publications(person):
    """Opening a publication is the Plover team's decision while publications
    are by invitation."""
    return "team" in (person.get("permissions") or [])


# --------------------------------------------------------------- sign-in

def may_sign_in(email):
    """Admits a writer past ACCOUNTS_ALLOWED_EMAILS (see accounts.EXTRA_ALLOWED)."""
    if research.memberships(email):
        return True
    person = staff.get_by_email(email)
    return bool(person and person["status"] == "active" and _implied_home(person))


if may_sign_in not in accounts.EXTRA_ALLOWED:
    accounts.EXTRA_ALLOWED.append(may_sign_in)


def signin_link(request, email):
    """A sign-in link for an owner to send by hand, or None when email
    sign-in is switched off on this server."""
    if not accounts.enabled():
        return None
    # behind the platform's proxy the request reads http and an inside host;
    # the link must carry the public https address (as the setup links do)
    import os
    from . import seo
    if os.environ.get("PUBLIC_BASE_URL"):
        base = accounts.base_url(request)
    elif seo.is_https(request):
        base = seo.SITE_BASE_URL + "/"
    else:
        base = str(request.base_url)
    return accounts.issue_link(email, WRITE_PAGE, base)


# ---------------------------------------------------------------- members

def _last_seen(person, email):
    """The later of a password sign-in and an email-link session's last use."""
    times = [t for t in ((person or {}).get("last_login_at"), accounts.last_seen(email)) if t]
    return max(times) if times else None


def member_list(publication_id):
    """Everyone who can write in a publication, with where their role comes
    from: ``member`` (managed here) or ``team`` (the admin console's Team
    page, PloverResearch only)."""
    rows = {}
    for m in research.members(publication_id):
        p = staff.get_by_email(m["email"])
        rows[m["email"]] = {"email": m["email"], "name": p["name"] if p else m["email"],
                            "role": m["role"], "source": "member", "added_at": m["added_at"],
                            "active": bool(p and p["status"] == "active"),
                            "last_login_at": _last_seen(p, m["email"]),
                            "id": p["id"] if p else None}
    if publication_id == research.HOME:
        for p in staff.list_all():
            implied = _implied_home(p) if p["status"] == "active" else None
            if not implied:
                continue
            row = rows.get(p["email"])
            if row is None or RANK[implied] >= RANK[row["role"]]:
                rows[p["email"]] = {"email": p["email"], "name": p["name"], "role": implied,
                                    "source": "team", "added_at": p["created_at"], "active": True,
                                    "last_login_at": _last_seen(p, p["email"]), "id": p["id"]}
    order = sorted(rows.values(), key=lambda r: (-RANK[r["role"]], r["name"].lower()))
    return order


def _owners_after(publication_id, email, new_role):
    """How many owners a publication would have if ``email`` had ``new_role``
    (None = removed)."""
    count = 0
    for m in member_list(publication_id):
        r = new_role if m["email"] == email and m["source"] == "member" else m["role"]
        if r == "owner":
            count += 1
    return count


def set_role(publication_id, email, new_role, actor):
    email = staff.normalise_email(email)
    if research.member_role(publication_id, email) is None:
        raise HTTPException(404, "%s is not a member here." % email)
    if new_role not in RANK:
        raise HTTPException(400, "A role is Owner, Editor or Writer.")
    if publication_id != research.HOME and _owners_after(publication_id, email, new_role) < 1:
        raise HTTPException(400, "A publication needs at least one owner. Make someone else "
                                 "an owner first.")
    research.set_member(publication_id, email, new_role, actor)


def remove(publication_id, email):
    email = staff.normalise_email(email)
    if research.member_role(publication_id, email) is None:
        raise HTTPException(404, "%s is not a member here. People who write through the "
                                 "Team page's Writing permission are changed there." % email)
    if publication_id != research.HOME and _owners_after(publication_id, email, None) < 1:
        raise HTTPException(400, "A publication needs at least one owner. Make someone else "
                                 "an owner first.")
    research.remove_member(publication_id, email)


def invite(request, publication_id, email, name, new_role, actor):
    """Add a person to a publication. Returns (member row, sign-in link)."""
    if new_role not in RANK:
        raise HTTPException(400, "A role is Owner, Editor or Writer.")
    try:
        person = staff.ensure_person(email, name, actor)
    except staff.StaffError as exc:
        raise HTTPException(400, str(exc))
    current = research.member_role(publication_id, person["email"])
    if current is not None:
        raise HTTPException(400, "%s is already a member, as %s." % (
            person["email"], ROLE_LABEL[current].lower()))
    research.set_member(publication_id, person["email"], new_role, actor)
    row = [m for m in member_list(publication_id) if m["email"] == person["email"]][0]
    return row, signin_link(request, person["email"])
