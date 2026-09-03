"""Internal admin API: login, ingest health, vintage browser, audit log.

Everything here is read-only against the DuckDB store — the one-writer rule
(see CLAUDE.md, Ingest Guardrails 5) holds: the serving process never writes
to the database. The only thing the admin surface writes anywhere is its own
audit trail, an append-only JSONL file under data/admin/, which survives
redeploys because data/ is the mounted volume.

Auth is a single shared password in ADMIN_PASSWORD (environment or .env).
With it unset the whole surface answers 503 and the admin page says so —
there is no default credential. A successful login sets an HttpOnly cookie
signed with a per-boot secret, so every deploy or restart signs everyone out;
for a one-operator internal tool that is a feature, not a bug.

Paths live under /admin/api on purpose: the response cache only touches GETs
under /api/v1, so nothing authenticated can ever be served from cache.
"""
import datetime
import hashlib
import hmac
import json
import os
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from . import db
from .api import ADAPTERS, health

router = APIRouter(prefix="/admin/api")

ADMIN_DIR = db.DATA_DIR / "admin"
AUDIT_PATH = ADMIN_DIR / "audit.jsonl"

COOKIE = "obs_admin"
SESSION_HOURS = 12
# Per-boot signing secret: restarting the server invalidates every session.
_SECRET = os.urandom(32)

# Login attempts per IP, sliding window — same in-process shape as the /ask
# rate limit: it bounds one worker, which is the whole deployment.
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_PER_WINDOW = 5
_LOGIN_HITS = {}


def _password():
    value = os.environ.get("ADMIN_PASSWORD", "").strip()
    return value or None


def _sign(expiry):
    mac = hmac.new(_SECRET, str(expiry).encode("ascii"), hashlib.sha256)
    return "%d.%s" % (expiry, mac.hexdigest())


def _token_valid(token):
    if not token or "." not in token:
        return False
    expiry_part = token.split(".", 1)[0]
    if not expiry_part.isdigit():
        return False
    expiry = int(expiry_part)
    if expiry < time.time():
        return False
    return hmac.compare_digest(_sign(expiry), token)


def _require_admin(request):
    if _password() is None:
        raise HTTPException(503, "Admin is disabled: ADMIN_PASSWORD is not set")
    if not _token_valid(request.cookies.get(COOKIE)):
        raise HTTPException(401, "Not signed in")


def _client_ip(request):
    return request.client.host if request.client else "unknown"


def _too_many_attempts(ip):
    now = time.monotonic()
    cutoff = now - LOGIN_WINDOW_SECONDS
    for stale in [k for k, hits in _LOGIN_HITS.items() if not hits or hits[-1] < cutoff]:
        del _LOGIN_HITS[stale]
    hits = [t for t in _LOGIN_HITS.get(ip, []) if t >= cutoff]
    if len(hits) >= LOGIN_MAX_PER_WINDOW:
        _LOGIN_HITS[ip] = hits
        return True
    hits.append(now)
    _LOGIN_HITS[ip] = hits
    return False


# --- audit trail -------------------------------------------------------------

def audit(action, detail, ip):
    """Append one action to the audit trail. Never raises: an unwritable log
    must not take the admin surface down, but it is loudly reported."""
    entry = {
        "at": datetime.datetime.now(datetime.timezone.utc)
              .replace(tzinfo=None).isoformat() + "Z",
        "action": action,
        "detail": detail,
        "ip": ip,
    }
    try:
        ADMIN_DIR.mkdir(parents=True, exist_ok=True)
        with open(str(AUDIT_PATH), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        print("AUDIT WRITE FAILED (%s): %s" % (exc, entry))


def _read_audit(limit):
    if not AUDIT_PATH.exists():
        return []
    entries = []
    with open(str(AUDIT_PATH), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                entries.append({"at": None, "action": "unparseable_entry",
                                "detail": line[:200], "ip": None})
    return entries[-limit:][::-1]


# --- session -----------------------------------------------------------------

class LoginBody(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    if _password() is None:
        raise HTTPException(503, "Admin is disabled: ADMIN_PASSWORD is not set")
    ip = _client_ip(request)
    if _too_many_attempts(ip):
        audit("login_locked_out", "too many attempts", ip)
        raise HTTPException(429, "Too many attempts — wait a few minutes")
    if not hmac.compare_digest(body.password.encode("utf-8"),
                               _password().encode("utf-8")):
        audit("login_failed", "wrong password", ip)
        raise HTTPException(401, "Wrong password")
    expiry = int(time.time()) + SESSION_HOURS * 3600
    response.set_cookie(
        COOKIE, _sign(expiry), max_age=SESSION_HOURS * 3600, path="/admin",
        httponly=True, samesite="strict",
        secure=request.url.scheme == "https")
    audit("login", "signed in", ip)
    expires = datetime.datetime.fromtimestamp(expiry, datetime.timezone.utc)
    return {"ok": True,
            "expires_at": expires.replace(tzinfo=None).isoformat() + "Z"}


@router.post("/logout")
def logout(request: Request, response: Response):
    response.delete_cookie(COOKIE, path="/admin")
    if _token_valid(request.cookies.get(COOKIE)):
        audit("logout", "signed out", _client_ip(request))
    return {"ok": True}


@router.get("/session")
def session(request: Request):
    """Lets the page decide between the login screen and the dashboard
    without a failed request in the console."""
    if _password() is None:
        return {"enabled": False, "authenticated": False}
    return {"enabled": True,
            "authenticated": _token_valid(request.cookies.get(COOKIE))}


# --- ingest health -----------------------------------------------------------

@router.get("/overview")
def overview(request: Request):
    """The public health check, widened with what an operator needs next:
    the artifact behind each live release and its validation summary."""
    _require_admin(request)
    report = health()
    con = db.read_cursor()
    extra = {}
    for slug in ADAPTERS:
        row = con.execute(
            "SELECT r.release_id, r.label, r.validation, a.sha256, a.bytes, "
            "       a.retrieved_at, a.url "
            "FROM releases r JOIN source_artifacts a USING(artifact_id) "
            "WHERE r.dataset=? AND r.status='published'", [slug]).fetchone()
        counts = con.execute(
            "SELECT count(*), count(*) FILTER (status='rejected') "
            "FROM releases WHERE dataset=?", [slug]).fetchone()
        series_n = con.execute(
            "SELECT count(*) FILTER (active), count(*) "
            "FROM series WHERE dataset=?", [slug]).fetchone()
        extra[slug] = {
            "release_id": row[0] if row else None,
            "label": row[1] if row else None,
            "validation": json.loads(row[2]) if row and row[2] else None,
            "artifact_sha256": row[3] if row else None,
            "artifact_bytes": row[4] if row else None,
            "artifact_retrieved_at":
                row[5].isoformat() + "Z" if row else None,
            "artifact_url": row[6] if row else None,
            "releases_total": counts[0],
            "releases_rejected": counts[1],
            "series_active": series_n[0],
            "series_total": series_n[1],
        }
    for d in report["datasets"]:
        d.update(extra.get(d["dataset"], {}))
    return report


# --- vintage browser ---------------------------------------------------------

@router.get("/releases/{dataset}")
def releases(dataset, request: Request):
    """Every stored release of one dataset, newest first, with what each one
    changed. The counts come straight from observation_vintages, so a release
    that merely republished unchanged data shows zero — which is the truth."""
    _require_admin(request)
    if dataset not in ADAPTERS:
        raise HTTPException(404, "Unknown dataset '%s'" % dataset)
    con = db.read_cursor()
    rows = con.execute(
        "SELECT r.release_id, r.label, r.latest_period, r.ingested_at, r.status, "
        "       a.sha256, a.bytes, a.retrieved_at, "
        "       count(v.release_id) FILTER (v.value IS NOT NULL) AS recorded, "
        "       count(v.release_id) FILTER (v.value IS NULL) AS withdrawn "
        "FROM releases r "
        "JOIN source_artifacts a USING(artifact_id) "
        "LEFT JOIN observation_vintages v USING(release_id) "
        "WHERE r.dataset=? "
        "GROUP BY 1,2,3,4,5,6,7,8 ORDER BY r.ingested_at DESC", [dataset]).fetchall()
    first_release = rows[-1][0] if rows else None
    out = []
    for r in rows:
        out.append({
            "release_id": r[0], "label": r[1],
            "latest_period": r[2].isoformat(),
            "ingested_at": r[3].isoformat() + "Z",
            "status": r[4],
            "sha256": r[5], "bytes": r[6],
            "retrieved_at": r[7].isoformat() + "Z",
            "recorded": r[8], "withdrawn": r[9],
            "is_first_vintage": r[0] == first_release,
        })
    return {"dataset": dataset, "releases": out}


CHANGES_CAP = 500


@router.get("/releases/{dataset}/{release_id}/changes")
def release_changes(dataset, release_id: int, request: Request):
    """What one release did, split the way an operator reads it: values that
    REVISED an earlier vintage (with the prior value alongside), values for
    new periods, and withdrawals. Lists are capped; the counts never are."""
    _require_admin(request)
    if dataset not in ADAPTERS:
        raise HTTPException(404, "Unknown dataset '%s'" % dataset)
    con = db.read_cursor()
    owner = con.execute("SELECT dataset FROM releases WHERE release_id=?",
                        [release_id]).fetchone()
    if owner is None or owner[0] != dataset:
        raise HTTPException(404, "No release %d in dataset '%s'" % (release_id, dataset))

    # Each vintage row of this release, with the value previously in force:
    # the newest earlier vintage row for the same (series, period).
    rows = con.execute(
        "SELECT s.code, s.name_en, v.period, v.value, "
        "  (SELECT p.value FROM observation_vintages p "
        "   JOIN releases rp ON rp.release_id = p.release_id "
        "   JOIN releases rv ON rv.release_id = v.release_id "
        "   WHERE p.series_id = v.series_id AND p.period = v.period "
        "     AND rp.ingested_at < rv.ingested_at "
        "   ORDER BY rp.ingested_at DESC LIMIT 1) AS prior, "
        "  EXISTS (SELECT 1 FROM observation_vintages p "
        "   JOIN releases rp ON rp.release_id = p.release_id "
        "   JOIN releases rv ON rv.release_id = v.release_id "
        "   WHERE p.series_id = v.series_id AND p.period = v.period "
        "     AND rp.ingested_at < rv.ingested_at) AS had_prior "
        "FROM observation_vintages v JOIN series s USING(series_id) "
        "WHERE v.release_id=? ORDER BY s.code, v.period", [release_id]).fetchall()

    revisions, new_values, withdrawals = [], [], []
    for code, name, period, value, prior, had_prior in rows:
        entry = {"code": code, "name": name, "period": period.isoformat(),
                 "value": value, "prior": prior}
        if value is None:
            withdrawals.append(entry)
        elif had_prior:
            revisions.append(entry)
        else:
            new_values.append(entry)

    def clip(entries):
        return {"count": len(entries), "rows": entries[:CHANGES_CAP],
                "truncated": len(entries) > CHANGES_CAP}

    return {"dataset": dataset, "release_id": release_id,
            "revisions": clip(revisions),
            "new_values": clip(new_values),
            "withdrawals": clip(withdrawals)}


# --- audit log ---------------------------------------------------------------

@router.get("/audit")
def audit_log(request: Request, limit: int = 200):
    _require_admin(request)
    return {"entries": _read_audit(max(1, min(limit, 1000)))}
