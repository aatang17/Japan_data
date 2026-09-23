"""The desk's Drive: files a person keeps on the desk, and their Google Drive.

Two sources behind one page and two specialist tools.

* **My drive** — files uploaded to the desk and folders made on it, held in
  `ia_drive_items` (same SQLite file as the rest of the desk). Deleting goes to
  Trash first; only "Delete forever" in Trash removes a row.
* **Google Workspace** — the person's own Google Drive, connected with Google's
  OAuth consent screen. **Read-only** (`drive.readonly`): the desk can list and
  read files; it never creates, edits, moves or deletes anything there. The
  refresh token is sealed with `keychain` like every other desk secret; the
  short-lived access token lives only in this process's memory.

The Google side is switched on by two variables from a Google Cloud OAuth
client ("Web application"): `GOOGLE_OAUTH_CLIENT_ID` and
`GOOGLE_OAUTH_CLIENT_SECRET`. The redirect URI registered with Google must be
`<PUBLIC_BASE_URL>/api/v1/assistant/google/callback`, or whatever
`GOOGLE_OAUTH_REDIRECT_URI` says. Without them the page says Google is not set
up and everything else works.

HTTP goes through urllib (no Google SDK), through `_http` so tests can swap it.
"""
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import keychain, store

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_DESK_BYTES = 1024 * 1024 * 1024
READ_LIMIT_CHARS = 6000  # one chunk; the runner clips any tool result at 8,000
STATE_TTL_SECONDS = 600

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE_URL = "https://www.googleapis.com/drive/v3/files"
SCOPES = "openid email https://www.googleapis.com/auth/drive.readonly"
GOOGLE_FIELDS = "id,name,mimeType,size,modifiedTime,webViewLink,shared,owners(displayName,me)"
FOLDER_MIME = "application/vnd.google-apps.folder"
# Google's own formats have no bytes to download; they are exported.
EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
TEXT_MIMES = ("application/json", "application/xml", "application/csv", "application/x-yaml")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ia_drive_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL,
  parent_id INTEGER,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  mime TEXT,
  size INTEGER NOT NULL DEFAULT 0,
  content BLOB,
  sha256 TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  trashed_at INTEGER
);
CREATE INDEX IF NOT EXISTS ia_drive_parent ON ia_drive_items (account_id, parent_id);
CREATE TABLE IF NOT EXISTS ia_google (
  account_id INTEGER PRIMARY KEY,
  email TEXT,
  scopes TEXT,
  ct TEXT NOT NULL,
  connected_at INTEGER NOT NULL,
  last_used_at INTEGER
);
"""

_schema_done = set()
_lock = threading.Lock()
_access = {}  # account_id -> (token, expires_at)


class DriveError(Exception):
    """Something the person can act on; the message is shown as is."""


def _db():
    c = store.conn()
    key = str(store.DB_PATH)
    if key not in _schema_done:
        with _lock:
            c.executescript(SCHEMA)
            c.commit()
            _schema_done.add(key)
    return c


def _write(sql, params=()):
    c = _db()
    with store._lock:
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid


def _rows(sql, params=()):
    return [dict(r) for r in _db().execute(sql, params).fetchall()]


def _row(sql, params=()):
    r = _db().execute(sql, params).fetchone()
    return dict(r) if r else None


# ------------------------------------------------------------- My drive

_COLS = "id, parent_id, kind, name, mime, size, created_at, updated_at, trashed_at"


def _shape(r):
    r["source"] = "desk"
    r["ref"] = "desk:%d" % r["id"]
    return r


def item(account_id, item_id):
    r = _row("SELECT " + _COLS + " FROM ia_drive_items WHERE id = ? AND account_id = ?",
             (item_id, account_id))
    return _shape(r) if r else None


def _folder_or_none(account_id, folder_id):
    if folder_id in (None, 0, ""):
        return None
    f = item(account_id, int(folder_id))
    if f is None or f["kind"] != "folder" or f["trashed_at"]:
        raise DriveError("That folder does not exist.")
    return f


def path_of(account_id, folder_id):
    """[{id, name}] from the top of My drive down to this folder."""
    out = []
    seen = set()
    f = _folder_or_none(account_id, folder_id)
    while f is not None and f["id"] not in seen:
        seen.add(f["id"])
        out.insert(0, {"id": f["id"], "name": f["name"]})
        f = item(account_id, f["parent_id"]) if f["parent_id"] else None
    return out


def children(account_id, folder_id=None):
    _folder_or_none(account_id, folder_id)
    if folder_id in (None, 0, ""):
        rows = _rows("SELECT " + _COLS + " FROM ia_drive_items WHERE account_id = ? "
                     "AND parent_id IS NULL AND trashed_at IS NULL", (account_id,))
    else:
        rows = _rows("SELECT " + _COLS + " FROM ia_drive_items WHERE account_id = ? "
                     "AND parent_id = ? AND trashed_at IS NULL", (account_id, int(folder_id)))
    rows.sort(key=lambda r: (r["kind"] != "folder", r["name"].lower()))
    return [_shape(r) for r in rows]


def _live_ids(account_id):
    """Ids of items not in Trash and not inside a trashed folder."""
    rows = _rows("SELECT id, parent_id, trashed_at FROM ia_drive_items WHERE account_id = ?",
                 (account_id,))
    by_id = dict((r["id"], r) for r in rows)
    live = set()
    for r in rows:
        cur, ok, hops = r, True, 0
        while cur is not None and hops < 64:
            if cur["trashed_at"]:
                ok = False
                break
            cur = by_id.get(cur["parent_id"]) if cur["parent_id"] else None
            hops += 1
        if ok:
            live.add(r["id"])
    return live


def recent(account_id, limit=50):
    live = _live_ids(account_id)
    rows = _rows("SELECT " + _COLS + " FROM ia_drive_items WHERE account_id = ? AND kind = 'file' "
                 "ORDER BY updated_at DESC LIMIT ?", (account_id, limit * 2))
    return [_shape(r) for r in rows if r["id"] in live][:limit]


def trash(account_id):
    """What was put in Trash directly (a trashed folder's contents go with it)."""
    rows = _rows("SELECT " + _COLS + " FROM ia_drive_items WHERE account_id = ? "
                 "AND trashed_at IS NOT NULL ORDER BY trashed_at DESC", (account_id,))
    return [_shape(r) for r in rows]


def usage(account_id):
    r = _row("SELECT COALESCE(SUM(size), 0) AS used, COUNT(*) AS n FROM ia_drive_items "
             "WHERE account_id = ? AND kind = 'file'", (account_id,))
    return {"used": r["used"], "limit": MAX_DESK_BYTES, "files": r["n"]}


def _clean_name(name):
    name = " ".join(str(name or "").replace("/", " ").replace("\\", " ").split()).strip()
    if not name or name in (".", ".."):
        raise DriveError("Give it a name.")
    return name[:200]


def _free_name(account_id, parent_id, name, skip_id=None):
    """The name, or 'name (2).ext' if the folder already holds one."""
    if parent_id:
        taken = _rows("SELECT id, name FROM ia_drive_items WHERE account_id = ? AND parent_id = ? "
                      "AND trashed_at IS NULL", (account_id, parent_id))
    else:
        taken = _rows("SELECT id, name FROM ia_drive_items WHERE account_id = ? AND parent_id IS NULL "
                      "AND trashed_at IS NULL", (account_id,))
    names = set(r["name"].lower() for r in taken if r["id"] != skip_id)
    if name.lower() not in names:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    for i in range(2, 1000):
        cand = "%s (%d)%s" % (stem, i, ("." + ext) if ext else "")
        if cand.lower() not in names:
            return cand
    raise DriveError("Too many items with that name here.")


def make_folder(account_id, name, parent_id=None):
    parent = _folder_or_none(account_id, parent_id)
    pid = parent["id"] if parent else None
    name = _free_name(account_id, pid, _clean_name(name))
    t = store.now()
    new_id = _write("INSERT INTO ia_drive_items (account_id, parent_id, kind, name, created_at, updated_at) "
                    "VALUES (?, ?, 'folder', ?, ?, ?)", (account_id, pid, name, t, t))
    return item(account_id, new_id)


def upload(account_id, name, data, mime=None, parent_id=None):
    if not data:
        raise DriveError("That file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise DriveError("Files can be up to 25 MB.")
    if usage(account_id)["used"] + len(data) > MAX_DESK_BYTES:
        raise DriveError("This desk's drive is full (1 GB). Empty Trash or remove files first.")
    parent = _folder_or_none(account_id, parent_id)
    pid = parent["id"] if parent else None
    name = _free_name(account_id, pid, _clean_name(name))
    mime = (mime or "").split(";")[0].strip() or mimetypes.guess_type(name)[0] or "application/octet-stream"
    if mime == "application/octet-stream":
        mime = mimetypes.guess_type(name)[0] or mime
    t = store.now()
    new_id = _write("INSERT INTO ia_drive_items (account_id, parent_id, kind, name, mime, size, content, "
                    "sha256, created_at, updated_at) VALUES (?, ?, 'file', ?, ?, ?, ?, ?, ?, ?)",
                    (account_id, pid, name, mime, len(data), data, hashlib.sha256(data).hexdigest(), t, t))
    return item(account_id, new_id)


def rename(account_id, item_id, name):
    it = item(account_id, item_id)
    if it is None:
        raise DriveError("That item does not exist.")
    name = _free_name(account_id, it["parent_id"], _clean_name(name), skip_id=it["id"])
    _write("UPDATE ia_drive_items SET name = ?, updated_at = ? WHERE id = ? AND account_id = ?",
           (name, store.now(), item_id, account_id))
    return item(account_id, item_id)


def content(account_id, item_id):
    r = _row("SELECT id, name, mime, size, content, trashed_at, kind FROM ia_drive_items "
             "WHERE id = ? AND account_id = ?", (item_id, account_id))
    if r is None or r["kind"] != "file":
        return None
    return r


def move_to_trash(account_id, item_id):
    if item(account_id, item_id) is None:
        raise DriveError("That item does not exist.")
    _write("UPDATE ia_drive_items SET trashed_at = ? WHERE id = ? AND account_id = ?",
           (store.now(), item_id, account_id))


def restore(account_id, item_id):
    it = item(account_id, item_id)
    if it is None:
        raise DriveError("That item does not exist.")
    pid = it["parent_id"]
    if pid and pid not in _live_ids(account_id):
        pid = None  # its folder is gone or in Trash: bring it back to the top
    name = _free_name(account_id, pid, it["name"], skip_id=it["id"])
    _write("UPDATE ia_drive_items SET trashed_at = NULL, parent_id = ?, name = ? "
           "WHERE id = ? AND account_id = ?", (pid, name, item_id, account_id))


def delete_forever(account_id, item_id):
    """Only from Trash. Takes a folder's contents with it."""
    it = item(account_id, item_id)
    if it is None:
        raise DriveError("That item does not exist.")
    if not it["trashed_at"]:
        raise DriveError("Move it to Trash first.")
    ids, frontier = [it["id"]], [it["id"]]
    while frontier:
        marks = ",".join("?" * len(frontier))
        kids = _rows("SELECT id FROM ia_drive_items WHERE account_id = ? AND parent_id IN (%s)" % marks,
                     tuple([account_id] + frontier))
        frontier = [k["id"] for k in kids if k["id"] not in ids]
        ids.extend(frontier)
    marks = ",".join("?" * len(ids))
    _write("DELETE FROM ia_drive_items WHERE account_id = ? AND id IN (%s)" % marks,
           tuple([account_id] + ids))


def search_desk(account_id, q, limit=25):
    live = _live_ids(account_id)
    like = "%" + (q or "").replace("%", "").replace("_", "") + "%"
    rows = _rows("SELECT " + _COLS + " FROM ia_drive_items WHERE account_id = ? AND name LIKE ? "
                 "ORDER BY updated_at DESC LIMIT ?", (account_id, like, limit * 2))
    return [_shape(r) for r in rows if r["id"] in live][:limit]


# ------------------------------------------------------ Google Workspace

def google_configured():
    return bool((os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
                and (os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip())


def redirect_uri(base_url):
    explicit = (os.environ.get("GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    if explicit:
        return explicit
    base = (os.environ.get("PUBLIC_BASE_URL") or base_url).rstrip("/")
    return base + "/api/v1/assistant/google/callback"


def _http(method, url, headers=None, data=None, timeout=30):
    """(status, body bytes, content-type). Never raises for an HTTP status."""
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:  # noqa: BLE001
            body = b""
        return exc.code, body, ""
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DriveError("Google could not be reached (%s)." % getattr(exc, "reason", exc))


def _json(body):
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _state_key():
    return hashlib.sha256(("google-oauth-state:" + (os.environ.get("ASSISTANT_SECRET") or "")).encode()).digest()


def make_state(account_id):
    payload = "%d.%d.%s" % (account_id, int(time.time()), secrets.token_urlsafe(12))
    sig = hmac.new(_state_key(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(("%s.%s" % (payload, sig)).encode()).decode().rstrip("=")


def check_state(state, account_id):
    try:
        raw = base64.urlsafe_b64decode((state or "") + "=" * (-len(state or "") % 4)).decode()
        payload, sig = raw.rsplit(".", 1)
        aid, ts, _ = payload.split(".", 2)
    except (ValueError, UnicodeDecodeError):
        return False
    expect = hmac.new(_state_key(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return (hmac.compare_digest(sig, expect) and int(aid) == account_id
            and time.time() - int(ts) < STATE_TTL_SECONDS)


def auth_url(account_id, base_url):
    if not google_configured():
        raise DriveError("Google sign-in is not set up on this server.")
    if not keychain.enabled():
        raise DriveError("This server cannot store keys yet: ASSISTANT_SECRET is not set.")
    q = {"client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"].strip(),
         "redirect_uri": redirect_uri(base_url), "response_type": "code", "scope": SCOPES,
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
         "state": make_state(account_id)}
    return AUTH_URL + "?" + urllib.parse.urlencode(q)


def _email_from_id_token(id_token):
    # Came straight from Google's token endpoint over TLS, so the payload can
    # be read without checking the signature (Google's own guidance).
    try:
        part = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("email")
    except (IndexError, ValueError, AttributeError):
        return None


def finish(account_id, code, base_url):
    body = urllib.parse.urlencode({
        "code": code, "client_id": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
        "redirect_uri": redirect_uri(base_url), "grant_type": "authorization_code"}).encode()
    status, raw, _ = _http("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body)
    tok = _json(raw)
    if status != 200 or not tok.get("access_token"):
        raise DriveError("Google did not accept the sign-in (%s)." % (tok.get("error_description") or tok.get("error") or status))
    if not tok.get("refresh_token"):
        raise DriveError("Google did not grant ongoing access. Remove Plover from your Google account's "
                         "third-party access and connect again.")
    if "drive.readonly" not in (tok.get("scope") or ""):
        raise DriveError("Drive access was not granted. Connect again and tick the Drive box.")
    email = _email_from_id_token(tok.get("id_token"))
    t = store.now()
    _write("INSERT INTO ia_google (account_id, email, scopes, ct, connected_at) VALUES (?, ?, ?, ?, ?) "
           "ON CONFLICT(account_id) DO UPDATE SET email = excluded.email, scopes = excluded.scopes, "
           "ct = excluded.ct, connected_at = excluded.connected_at",
           (account_id, email, tok.get("scope"), keychain.seal(tok["refresh_token"]), t))
    _access[account_id] = (tok["access_token"], time.time() + int(tok.get("expires_in") or 3000) - 60)
    return google_status(account_id)


def google_status(account_id):
    r = _row("SELECT email, scopes, connected_at, last_used_at FROM ia_google WHERE account_id = ?",
             (account_id,))
    return {"configured": google_configured(), "keychain": keychain.enabled(),
            "connected": r is not None, "email": r["email"] if r else None,
            "connected_at": r["connected_at"] if r else None,
            "last_used_at": r["last_used_at"] if r else None}


def google_connected(account_id):
    return _row("SELECT 1 AS x FROM ia_google WHERE account_id = ?", (account_id,)) is not None


def disconnect(account_id):
    r = _row("SELECT ct FROM ia_google WHERE account_id = ?", (account_id,))
    if r:
        try:  # best effort: tell Google too, so the grant disappears from the account
            _http("POST", REVOKE_URL + "?" + urllib.parse.urlencode({"token": keychain.open_(r["ct"])}),
                  {"Content-Type": "application/x-www-form-urlencoded"}, b"", timeout=10)
        except (DriveError, ValueError, RuntimeError):
            pass
    _write("DELETE FROM ia_google WHERE account_id = ?", (account_id,))
    _access.pop(account_id, None)


def _token(account_id):
    cached = _access.get(account_id)
    if cached and cached[1] > time.time():
        return cached[0]
    r = _row("SELECT ct FROM ia_google WHERE account_id = ?", (account_id,))
    if r is None:
        raise DriveError("Google Workspace is not connected.")
    try:
        refresh = keychain.open_(r["ct"])
    except (ValueError, RuntimeError):
        raise DriveError("The stored Google access could not be read. Connect again.")
    body = urllib.parse.urlencode({
        "client_id": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
        "refresh_token": refresh, "grant_type": "refresh_token"}).encode()
    status, raw, _ = _http("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body)
    tok = _json(raw)
    if status != 200 or not tok.get("access_token"):
        if tok.get("error") == "invalid_grant":
            raise DriveError("Google access was withdrawn or expired. Connect again in Cloud storage.")
        raise DriveError("Google refused to refresh access (%s)." % (tok.get("error") or status))
    _access[account_id] = (tok["access_token"], time.time() + int(tok.get("expires_in") or 3000) - 60)
    return tok["access_token"]


def _gget(account_id, url, params=None, raw=False):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    status, body, ctype = _http("GET", full, {"Authorization": "Bearer " + _token(account_id)})
    if status == 401:  # token revoked mid-life: try once more with a fresh one
        _access.pop(account_id, None)
        status, body, ctype = _http("GET", full, {"Authorization": "Bearer " + _token(account_id)})
    if status != 200:
        msg = (_json(body).get("error") or {}).get("message") if isinstance(_json(body).get("error"), dict) else None
        raise DriveError("Google Drive answered %s. %s" % (status, msg or ""))
    _write("UPDATE ia_google SET last_used_at = ? WHERE account_id = ?", (store.now(), account_id))
    return (body, ctype) if raw else _json(body)


def _q_str(s):
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _shape_g(f):
    folder = f.get("mimeType") == FOLDER_MIME
    owners = f.get("owners") or []
    return {"id": f.get("id"), "ref": "google:" + str(f.get("id")), "source": "google",
            "kind": "folder" if folder else "file", "name": f.get("name"), "mime": f.get("mimeType"),
            "size": int(f["size"]) if f.get("size") else None,
            "modified": f.get("modifiedTime"), "link": f.get("webViewLink"),
            "owner": None if (not owners or owners[0].get("me")) else owners[0].get("displayName")}


def google_list(account_id, view="mydrive", folder=None, q=None, page_token=None):
    params = {"fields": "nextPageToken,files(%s)" % GOOGLE_FIELDS, "pageSize": 100,
              "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
    if q:
        params["q"] = "name contains %s and trashed = false" % _q_str(q)
        params["orderBy"] = "modifiedTime desc"
    elif view == "shared":
        params["q"] = "sharedWithMe = true and trashed = false"
        params["orderBy"] = "modifiedTime desc"
    elif view == "recent":
        params["q"] = "trashed = false and mimeType != '%s'" % FOLDER_MIME
        params["orderBy"] = "modifiedTime desc"
        params["pageSize"] = 50
    else:
        params["q"] = "%s in parents and trashed = false" % _q_str(folder or "root")
        params["orderBy"] = "folder,name"
    if page_token:
        params["pageToken"] = page_token
    d = _gget(account_id, DRIVE_URL, params)
    out = {"items": [_shape_g(f) for f in d.get("files") or []], "next": d.get("nextPageToken")}
    if view == "mydrive" and folder and not q:
        meta = _gget(account_id, DRIVE_URL + "/" + urllib.parse.quote(folder),
                     {"fields": "id,name", "supportsAllDrives": "true"})
        out["folder"] = {"id": meta.get("id"), "name": meta.get("name")}
    return out


def google_read(account_id, file_id):
    meta = _gget(account_id, DRIVE_URL + "/" + urllib.parse.quote(file_id),
                 {"fields": GOOGLE_FIELDS, "supportsAllDrives": "true"})
    mime = meta.get("mimeType") or ""
    if mime == FOLDER_MIME:
        raise DriveError("That is a folder. List it instead.")
    if mime in EXPORTS:
        body, _ = _gget(account_id, DRIVE_URL + "/" + urllib.parse.quote(file_id) + "/export",
                        {"mimeType": EXPORTS[mime]}, raw=True)
    elif _is_text(mime, meta.get("name")):
        body, _ = _gget(account_id, DRIVE_URL + "/" + urllib.parse.quote(file_id),
                        {"alt": "media", "supportsAllDrives": "true"}, raw=True)
    else:
        return _shape_g(meta), None
    return _shape_g(meta), body.decode("utf-8", "replace")


# ------------------------------------------------------ for specialists

def _is_text(mime, name):
    mime = mime or ""
    if mime.startswith("text/") or mime in TEXT_MIMES:
        return True
    return str(name or "").lower().rsplit(".", 1)[-1] in ("md", "txt", "csv", "tsv", "json", "yaml", "yml")


def available(account_id):
    """Offer the drive tools only when there is something to find."""
    try:
        has_desk = _row("SELECT 1 AS x FROM ia_drive_items WHERE account_id = ? AND kind = 'file' "
                        "AND trashed_at IS NULL LIMIT 1", (account_id,)) is not None
    except Exception:  # noqa: BLE001
        return False
    return has_desk or (google_configured() and google_connected(account_id))


TOOL_SCHEMAS = [
    {"name": "drive_search",
     "description": ("Find files in this desk's Drive: files uploaded to the desk and, if connected, "
                     "the person's Google Drive (read-only). Matches on file name; empty query lists "
                     "the most recent. Returns a ref for drive_read."),
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Words in the file name, or empty for recent files."}},
         "required": []}},
    {"name": "drive_read",
     "description": ("Read a text file from the desk's Drive by its ref (desk:<id> or google:<id>), "
                     "6,000 characters at a time. "
                     "Google Docs and Slides come back as plain text, Sheets as CSV. PDFs and images "
                     "cannot be read. Cite the ref as a source."),
     "parameters": {"type": "object", "properties": {
         "ref": {"type": "string", "description": "A ref from drive_search."},
         "offset": {"type": "integer", "description": "Character to start from; use next_offset from the previous chunk."}},
         "required": ["ref"]}},
]
TOOL_NAMES = tuple(s["name"] for s in TOOL_SCHEMAS)


def _brief(it):
    return {"ref": it["ref"], "name": it["name"], "source": "Google Drive" if it["source"] == "google" else "My drive",
            "type": it.get("mime"), "size": it.get("size"),
            "modified": it.get("modified") or it.get("updated_at")}


def run_tool(account_id, name, args):
    """(text, is_error) for a specialist's call."""
    try:
        if name == "drive_search":
            q = (args.get("query") or "").strip()
            hits = [_brief(i) for i in (search_desk(account_id, q) if q else recent(account_id, 25))]
            notes = []
            if google_configured() and google_connected(account_id):
                try:
                    g = google_list(account_id, view="recent" if not q else "mydrive", q=q or None)
                    hits += [_brief(i) for i in g["items"] if i["kind"] == "file"][:25]
                except DriveError as exc:
                    notes.append(str(exc))
            return json.dumps({"files": hits, "notes": notes}, ensure_ascii=False), False
        if name == "drive_read":
            ref = str(args.get("ref") or "").strip()
            src, _, key = ref.partition(":")
            if src == "desk" and key.isdigit():
                r = content(account_id, int(key))
                if r is None or r["trashed_at"]:
                    return json.dumps({"error": "No such file in My drive."}), True
                if not _is_text(r["mime"], r["name"]):
                    return json.dumps({"error": "'%s' is not a text file and cannot be read." % r["name"]}), True
                text = bytes(r["content"]).decode("utf-8", "replace")
                meta = {"ref": ref, "name": r["name"]}
            elif src == "google" and key:
                meta_g, text = google_read(account_id, key)
                if text is None:
                    return json.dumps({"error": "'%s' is not a text file or Google Doc and cannot be read." % meta_g["name"]}), True
                meta = {"ref": ref, "name": meta_g["name"], "link": meta_g.get("link")}
            else:
                return json.dumps({"error": "A ref looks like desk:12 or google:<id>."}), True
            try:
                start = max(0, int(args.get("offset") or 0))
            except (TypeError, ValueError):
                start = 0
            end = start + READ_LIMIT_CHARS
            meta.update({"content": text[start:end], "total_chars": len(text),
                         "next_offset": end if end < len(text) else None})
            return json.dumps(meta, ensure_ascii=False), False
    except DriveError as exc:
        return json.dumps({"error": str(exc)}), True
    return json.dumps({"error": "Unknown drive tool."}), True
