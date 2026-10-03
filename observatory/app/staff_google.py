# -*- coding: utf-8 -*-
"""A writer's own Google Drive, for the AI tab: search and read, nothing else.

Each person on the team connects their own Google account once (Admin → AI
Setup, or the AI tab). Access is read-only (drive.readonly): the AI can find
a file and read it as text — a Google Doc as plain text, a Sheet as CSV, a
PDF through pdftotext where the server has it — and never creates, edits,
moves or deletes anything. The refresh token is sealed with ASSISTANT_SECRET;
the access token lives only in this process's memory.

It shares the investment assistant's Google OAuth client and Google calls
(assistant/drive.py) and keeps its own store, keyed by the staff account.
Switched on by GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET; Google
must list <site>/admin/api/ai/google/callback as a redirect URI (or whatever
GOOGLE_STAFF_REDIRECT_URI says). The team can switch Drive off for everyone.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.parse

from . import staff
from .assistant import drive as gd, keychain

STATE_TTL = 600
READ_MAX_BYTES = 15 * 1024 * 1024
TEXT_MAX = 60000
_access = {}          # staff id -> (access token, expires at)
_FILE_ID = re.compile(r"(?:/d/|[?&]id=|/folders/)([A-Za-z0-9_-]{20,})")


class GoogleError(ValueError):
    """Worded for the writer."""


def configured():
    return gd.google_configured()


def team_enabled():
    return staff.team_setting("google_drive", "on") != "off"


def set_team_enabled(on):
    staff.set_team_setting("google_drive", "on" if on else "off")


def redirect_uri(base_url):
    explicit = (os.environ.get("GOOGLE_STAFF_REDIRECT_URI") or "").strip()
    if explicit:
        return explicit
    base = (os.environ.get("PUBLIC_BASE_URL") or base_url).rstrip("/")
    return base + "/admin/api/ai/google/callback"


def _key():
    return hashlib.sha256(("staff-google-state:" + (os.environ.get("ASSISTANT_SECRET") or "")).encode()).digest()


def make_state(staff_id):
    payload = "%d.%d.%s" % (staff_id, int(time.time()), secrets.token_urlsafe(12))
    sig = hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(("%s.%s" % (payload, sig)).encode()).decode().rstrip("=")


def check_state(state, staff_id):
    try:
        raw = base64.urlsafe_b64decode((state or "") + "=" * (-len(state or "") % 4)).decode()
        payload, sig = raw.rsplit(".", 1)
        sid, ts, _ = payload.split(".", 2)
    except (ValueError, UnicodeDecodeError):
        return False
    expect = hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expect) and int(sid) == staff_id and time.time() - int(ts) < STATE_TTL


def auth_url(staff_id, base_url):
    if not configured():
        raise GoogleError("Google sign-in is not set up on this server yet.")
    if not team_enabled():
        raise GoogleError("Google Drive is switched off for the team.")
    if not keychain.enabled():
        raise GoogleError("This server cannot store a sign-in yet: ASSISTANT_SECRET is not set.")
    q = {"client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"].strip(),
         "redirect_uri": redirect_uri(base_url), "response_type": "code", "scope": gd.SCOPES,
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
         "state": make_state(staff_id)}
    return gd.AUTH_URL + "?" + urllib.parse.urlencode(q)


def finish(staff_id, code, base_url):
    body = urllib.parse.urlencode({
        "code": code, "client_id": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
        "redirect_uri": redirect_uri(base_url), "grant_type": "authorization_code"}).encode()
    try:
        status, raw, _ = gd._http("POST", gd.TOKEN_URL,
                                  {"Content-Type": "application/x-www-form-urlencoded"}, body)
    except gd.DriveError as exc:
        raise GoogleError(str(exc))
    tok = gd._json(raw)
    if status != 200 or not tok.get("access_token"):
        raise GoogleError("Google did not accept the sign-in (%s)."
                          % (tok.get("error_description") or tok.get("error") or status))
    if not tok.get("refresh_token"):
        raise GoogleError("Google did not grant ongoing access. Remove Plover from your Google "
                          "account's third-party access and connect again.")
    if "drive.readonly" not in (tok.get("scope") or ""):
        raise GoogleError("Drive access was not granted. Connect again and tick the Drive box.")
    c = staff.conn()
    with staff._lock:
        c.execute("INSERT INTO staff_google (staff_id, email, scopes, ct, connected_at) VALUES (?, ?, ?, ?, ?) "
                  "ON CONFLICT(staff_id) DO UPDATE SET email = excluded.email, scopes = excluded.scopes, "
                  "ct = excluded.ct, connected_at = excluded.connected_at",
                  (staff_id, gd._email_from_id_token(tok.get("id_token")), tok.get("scope"),
                   keychain.seal(tok["refresh_token"]), int(time.time())))
        c.commit()
    _access[staff_id] = (tok["access_token"], time.time() + int(tok.get("expires_in") or 3000) - 60)
    return status_for(staff_id)


def status_for(staff_id):
    r = staff.conn().execute("SELECT email, connected_at, last_used_at FROM staff_google "
                             "WHERE staff_id = ?", (staff_id,)).fetchone()
    return {"configured": configured(), "team_enabled": team_enabled(),
            "connected": r is not None, "email": r["email"] if r else None,
            "connected_at": r["connected_at"] if r else None,
            "last_used_at": r["last_used_at"] if r else None}


def usable(staff_id):
    if staff_id in _handed:
        return team_enabled()
    return configured() and team_enabled() and status_for(staff_id)["connected"]


_handed = set()       # staff ids whose access token a run's tool server was given


def hand_token(staff_id, token):
    """In a CLI run's tool server: use the access token the run was handed
    (it has no keychain secret and cannot refresh one itself)."""
    _access[staff_id] = (token, time.time() + 3000)
    _handed.add(staff_id)


def disconnect(staff_id):
    r = staff.conn().execute("SELECT ct FROM staff_google WHERE staff_id = ?", (staff_id,)).fetchone()
    if r:
        try:   # best effort: tell Google too, so the grant leaves the account
            gd._http("POST", gd.REVOKE_URL + "?" + urllib.parse.urlencode({"token": keychain.open_(r["ct"])}),
                     {"Content-Type": "application/x-www-form-urlencoded"}, b"", timeout=10)
        except (gd.DriveError, ValueError, RuntimeError):
            pass
    c = staff.conn()
    with staff._lock:
        c.execute("DELETE FROM staff_google WHERE staff_id = ?", (staff_id,))
        c.commit()
    _access.pop(staff_id, None)


def _token(staff_id):
    hit = _access.get(staff_id)
    if hit and hit[1] > time.time():
        return hit[0]
    r = staff.conn().execute("SELECT ct FROM staff_google WHERE staff_id = ?", (staff_id,)).fetchone()
    if r is None:
        raise GoogleError("Google Drive is not connected.")
    try:
        refresh = keychain.open_(r["ct"])
    except (ValueError, RuntimeError):
        raise GoogleError("The stored Google access could not be read. Connect again.")
    body = urllib.parse.urlencode({
        "client_id": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
        "refresh_token": refresh, "grant_type": "refresh_token"}).encode()
    try:
        status, raw, _ = gd._http("POST", gd.TOKEN_URL,
                                  {"Content-Type": "application/x-www-form-urlencoded"}, body)
    except gd.DriveError as exc:
        raise GoogleError(str(exc))
    tok = gd._json(raw)
    if status != 200 or not tok.get("access_token"):
        if tok.get("error") == "invalid_grant":
            raise GoogleError("Google access was withdrawn or has expired. Connect Google Drive again.")
        raise GoogleError("Google refused to refresh access (%s)." % (tok.get("error") or status))
    _access[staff_id] = (tok["access_token"], time.time() + int(tok.get("expires_in") or 3000) - 60)
    return tok["access_token"]


def _get(staff_id, url, params=None, raw=False):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        status, body, ctype = gd._http("GET", full, {"Authorization": "Bearer " + _token(staff_id)})
        if status == 401:   # revoked mid-life: once more with a fresh token
            _access.pop(staff_id, None)
            status, body, ctype = gd._http("GET", full, {"Authorization": "Bearer " + _token(staff_id)})
    except gd.DriveError as exc:
        raise GoogleError(str(exc))
    if status != 200:
        err = gd._json(body).get("error")
        msg = err.get("message") if isinstance(err, dict) else None
        raise GoogleError("Google Drive answered %s. %s" % (status, msg or ""))
    c = staff.conn()
    with staff._lock:
        c.execute("UPDATE staff_google SET last_used_at = ? WHERE staff_id = ?", (int(time.time()), staff_id))
        c.commit()
    return (body, ctype) if raw else gd._json(body)


def search(staff_id, query, limit=20):
    """Files whose name or text matches, newest first."""
    q = (query or "").strip()
    params = {"fields": "files(%s)" % gd.GOOGLE_FIELDS, "pageSize": max(1, min(int(limit or 20), 50)),
              "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "orderBy": "modifiedTime desc"}
    if q:
        params["q"] = "(name contains %s or fullText contains %s) and trashed = false" % (gd._q_str(q), gd._q_str(q))
        params.pop("orderBy")       # Drive refuses orderBy with a fullText search
    else:
        params["q"] = "trashed = false and mimeType != '%s'" % gd.FOLDER_MIME
    d = _get(staff_id, gd.DRIVE_URL, params)
    return [{"id": f.get("id"), "name": f.get("name"), "type": _kind(f.get("mimeType")),
             "modified": f.get("modifiedTime"), "link": f.get("webViewLink")}
            for f in d.get("files") or []]


def _kind(mime):
    return {"application/vnd.google-apps.document": "Google Doc",
            "application/vnd.google-apps.spreadsheet": "Google Sheet",
            "application/vnd.google-apps.presentation": "Google Slides",
            "application/pdf": "PDF", gd.FOLDER_MIME: "Folder"}.get(mime or "", mime or "file")


def file_id(ref):
    ref = (ref or "").strip()
    m = _FILE_ID.search(ref)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z0-9_-]{10,}$", ref):
        return ref
    raise GoogleError("Give a Drive file id or its link.")


def _pdf_text(data):
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "f.pdf")
        with open(src, "wb") as f:
            f.write(data)
        out = subprocess.run([exe, "-layout", "-q", src, "-"], capture_output=True, timeout=60)
        return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None


def read(staff_id, ref):
    """{id, name, type, link, text} — the file as text, cut to TEXT_MAX."""
    fid = file_id(ref)
    q = urllib.parse.quote(fid)
    meta = _get(staff_id, gd.DRIVE_URL + "/" + q, {"fields": gd.GOOGLE_FIELDS, "supportsAllDrives": "true"})
    mime = meta.get("mimeType") or ""
    out = {"id": meta.get("id"), "name": meta.get("name"), "type": _kind(mime),
           "modified": meta.get("modifiedTime"), "link": meta.get("webViewLink")}
    if mime == gd.FOLDER_MIME:
        raise GoogleError("That is a folder; search for the file inside it.")
    if mime in gd.EXPORTS:
        body, _ = _get(staff_id, gd.DRIVE_URL + "/" + q + "/export", {"mimeType": gd.EXPORTS[mime]}, raw=True)
        text = body.decode("utf-8", "replace")
    elif mime == "application/pdf" or gd._is_text(mime, meta.get("name")):
        if meta.get("size") and int(meta["size"]) > READ_MAX_BYTES:
            raise GoogleError("That file is too large to read (over 15 MB).")
        body, _ = _get(staff_id, gd.DRIVE_URL + "/" + q, {"alt": "media", "supportsAllDrives": "true"}, raw=True)
        if mime == "application/pdf":
            text = _pdf_text(body)
            if text is None:
                raise GoogleError("This server cannot read PDFs as text.")
        else:
            text = body.decode("utf-8", "replace")
    else:
        raise GoogleError("%s files cannot be read as text." % _kind(mime))
    out["truncated"] = len(text) > TEXT_MAX
    out["text"] = text[:TEXT_MAX]
    return out
