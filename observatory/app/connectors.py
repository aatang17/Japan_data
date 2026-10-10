# -*- coding: utf-8 -*-
"""Each publication's connectors: outside tool servers an AI run may call.

A connector is any MCP server reachable over https — a research database, a
note-taking app, an internal tool — added by the publication's owner (in the
Writer Desk's Assistant Settings; PloverResearch's also in Admin, with the
Team permission), with its key if it needs one (sealed with ASSISTANT_SECRET,
like every other secret here). A connector carries its publication's keys, so
a run reaches only the connectors of its article's publication. "Check" connects, lists the server's tools and keeps
the list, so a run never waits on a round trip to learn them; each tool can be
switched off, and a tool its server marks as destructive starts off.

Calls go through the investment assistant's client (assistant/mcp_client.py),
which refuses private addresses, redirects and oversized replies. Like the
skills, connectors are not tied to one product: the research desk uses them
now and the assistant can when the two merge.

Every connector tool reaches the model under a prefixed name — x<id>_<tool> —
so it cannot collide with Plover's own tools or another server's.
"""
import json
import re
import time

from . import research, staff
from .assistant import keychain, mcp_client

LABEL_MAX = 40
CONNECTORS_MAX = 12
AUTH_KINDS = ("none", "bearer", "header")
HOME = research.HOME
_NAME_OK = re.compile(r"[^A-Za-z0-9_-]")


class ConnectorError(ValueError):
    """Worded for the person editing."""


def _now():
    return int(time.time())


def _shape(r, with_secret=False):
    tools = json.loads(r["tools_json"] or "[]")
    off = set(json.loads(r["off_tools_json"] or "[]"))
    out = {"id": r["id"], "publication_id": r["publication_id"], "label": r["label"], "url": r["url"], "auth_kind": r["auth_kind"],
           "header_name": r["header_name"], "key_last4": r["secret_last4"],
           "has_key": bool(r["secret_ct"]), "enabled": bool(r["enabled"]),
           "server_name": r["server_name"], "checked_at": r["checked_at"],
           "last_error": r["last_error"], "updated_by": r["updated_by"],
           "tools": [dict(t, on=t["name"] not in off) for t in tools]}
    if with_secret:
        out["_secret_ct"] = r["secret_ct"]
    return out


def list_connectors(enabled_only=False, with_secret=False, publication_id=HOME):
    sql = ("SELECT * FROM team_connectors WHERE publication_id = ?" + (" AND enabled = 1" if enabled_only else "")
           + " ORDER BY label")
    return [_shape(r, with_secret) for r in staff.conn().execute(sql, (int(publication_id),)).fetchall()]


def get(connector_id, with_secret=False, publication_id=None):
    """A connector by id, or None. With a publication id, another
    publication's connector is None too."""
    r = staff.conn().execute("SELECT * FROM team_connectors WHERE id = ?", (int(connector_id),)).fetchone()
    if r is None or (publication_id is not None and r["publication_id"] != int(publication_id)):
        return None
    return _shape(r, with_secret)


def _secret(c):
    if not c.get("_secret_ct"):
        return None
    try:
        return keychain.open_(c["_secret_ct"])
    except (ValueError, RuntimeError):
        raise ConnectorError("The stored key for %s could not be read; enter it again." % c["label"])


def _server(c):
    return {"url": c["url"], "auth_kind": c["auth_kind"], "header_name": c["header_name"]}


def _clean(label, url, auth_kind, header_name):
    label = " ".join((label or "").split())
    if not label:
        raise ConnectorError("Give the connector a name.")
    if len(label) > LABEL_MAX:
        raise ConnectorError("Keep the name under %d characters." % LABEL_MAX)
    if auth_kind not in AUTH_KINDS:
        raise ConnectorError("Choose how the server is signed in to.")
    header_name = (header_name or "").strip() or None
    if auth_kind == "header" and (not header_name or not re.match(r"^[A-Za-z0-9-]{1,60}$", header_name)):
        raise ConnectorError("Give the header's name, e.g. X-API-Key.")
    try:
        url = mcp_client.check_url(url)
    except mcp_client.RemoteError as exc:
        raise ConnectorError(str(exc))
    return label, url, auth_kind, header_name


def create(label, url, auth_kind, header_name, secret, by, publication_id=HOME):
    label, url, auth_kind, header_name = _clean(label, url, auth_kind, header_name)
    if secret and not keychain.enabled():
        raise ConnectorError("This server cannot store a key yet: ASSISTANT_SECRET is not set.")
    c = staff.conn()
    with staff._lock:
        if c.execute("SELECT COUNT(*) AS n FROM team_connectors WHERE publication_id = ?",
                     (int(publication_id),)).fetchone()["n"] >= CONNECTORS_MAX:
            raise ConnectorError("This publication has %d connectors, the most it can keep." % CONNECTORS_MAX)
        cur = c.execute(
            "INSERT INTO team_connectors (publication_id, label, url, auth_kind, header_name, secret_ct, "
            "secret_last4, enabled, created_at, created_by, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (int(publication_id), label, url, auth_kind, header_name, keychain.seal(secret) if secret else None,
             keychain.last4(secret) if secret else None, _now(), by, _now(), by))
        c.commit()
    return check(cur.lastrowid)


def update(connector_id, by, label=None, url=None, auth_kind=None, header_name=None, secret=None,
           enabled=None, publication_id=None):
    cur = get(connector_id, with_secret=True, publication_id=publication_id)
    if cur is None:
        raise ConnectorError("No such connector.")
    label, url, auth_kind, header_name = _clean(
        cur["label"] if label is None else label, cur["url"] if url is None else url,
        cur["auth_kind"] if auth_kind is None else auth_kind,
        cur["header_name"] if header_name is None else header_name)
    fields = {"label": label, "url": url, "auth_kind": auth_kind, "header_name": header_name,
              "updated_at": _now(), "updated_by": by}
    if secret:
        if not keychain.enabled():
            raise ConnectorError("This server cannot store a key yet: ASSISTANT_SECRET is not set.")
        fields["secret_ct"] = keychain.seal(secret)
        fields["secret_last4"] = keychain.last4(secret)
    if auth_kind == "none":
        fields["secret_ct"] = fields["secret_last4"] = None
    if enabled is not None:
        fields["enabled"] = int(bool(enabled))
    c = staff.conn()
    with staff._lock:
        c.execute("UPDATE team_connectors SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in fields),
                  list(fields.values()) + [cur["id"]])
        c.commit()
    if url != cur["url"] or secret or auth_kind != cur["auth_kind"]:
        return check(cur["id"])
    return get(cur["id"])


def delete(connector_id, publication_id=None):
    if get(connector_id, publication_id=publication_id) is None:
        return
    c = staff.conn()
    with staff._lock:
        c.execute("DELETE FROM team_connectors WHERE id = ?", (int(connector_id),))
        c.commit()


def check(connector_id, publication_id=None):
    """Connect, list the tools and keep them. A failure is stored and shown,
    and the tools from the last good check stay."""
    cur = get(connector_id, with_secret=True, publication_id=publication_id)
    if cur is None:
        raise ConnectorError("No such connector.")
    fields = {"checked_at": _now()}
    try:
        info, tools = mcp_client.connect(_server(cur), _secret(cur))
        fields.update({"tools_json": json.dumps(tools), "last_error": None,
                       "server_name": (info.get("title") or info.get("name") or "")[:80] or None})
        if not cur["tools"]:
            # a tool its server marks as destructive starts off
            off = [t["name"] for t in tools if (t.get("annotations") or {}).get("destructiveHint") is True]
            fields["off_tools_json"] = json.dumps(off)
    except (mcp_client.RemoteError, ConnectorError) as exc:
        fields["last_error"] = str(exc)[:300]
    c = staff.conn()
    with staff._lock:
        c.execute("UPDATE team_connectors SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in fields),
                  list(fields.values()) + [cur["id"]])
        c.commit()
    return get(cur["id"])


def set_tool(connector_id, tool_name, on, publication_id=None):
    cur = get(connector_id, publication_id=publication_id)
    if cur is None:
        raise ConnectorError("No such connector.")
    if tool_name not in [t["name"] for t in cur["tools"]]:
        raise ConnectorError("That server has no tool called %s." % tool_name)
    off = set(t["name"] for t in cur["tools"] if not t["on"])
    if on:
        off.discard(tool_name)
    else:
        off.add(tool_name)
    c = staff.conn()
    with staff._lock:
        c.execute("UPDATE team_connectors SET off_tools_json = ? WHERE id = ?",
                  (json.dumps(sorted(off)), cur["id"]))
        c.commit()
    return get(cur["id"])


# ---------------------------------------------------------------------------
# for a run

def tool_name(connector_id, remote_name):
    return ("x%d_%s" % (connector_id, _NAME_OK.sub("_", remote_name)))[:64]


def run_tools(publication_id=HOME):
    """[{name, description, parameters, connector_id, remote, label}] for every
    tool switched on in every enabled connector of one publication, from the
    last check."""
    out = []
    for c in list_connectors(enabled_only=True, publication_id=publication_id):
        for t in c["tools"]:
            if not t["on"]:
                continue
            out.append({"name": tool_name(c["id"], t["name"]),
                        "description": ("[%s] " % c["label"]) + (t.get("description") or ""),
                        "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                        "connector_id": c["id"], "remote": t["name"], "label": c["label"]})
    return out


def call(connector_id, remote_name, args, key=None, key_given=False, publication_id=None):
    """(text, is_error) — the same contract as the local tools. A run's tool
    server passes the key it was handed (key_given) instead of unsealing it;
    a run passes its article's publication, and another's connector is refused."""
    c = get(connector_id, with_secret=True, publication_id=publication_id)
    if c is None or not c["enabled"]:
        return json.dumps({"error": "That connector has been switched off."}), True
    if not any(t["name"] == remote_name and t["on"] for t in c["tools"]):
        return json.dumps({"error": "That tool is switched off for this publication."}), True
    try:
        secret = key if key_given else _secret(c)
    except ConnectorError as exc:
        return json.dumps({"error": str(exc)}), True
    return mcp_client.call_tool(_server(c), remote_name, args, secret)
