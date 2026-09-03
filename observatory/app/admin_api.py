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

import duckdb

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from . import db, filer_labels, parties
from .api import ADAPTERS, health
from .equity_api import DB_PATH as EQUITY_DB_PATH

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


# --- equity reads for the curation queue --------------------------------------
#
# Its own short-lived read-only connection rather than equity_api's cached
# reader: the queue is opened by one operator a few times a day, and borrowing
# the serving reader would let an admin page hold a cursor open across the
# nightly refresh's file swap.

def _equity_rows(sql, params=()):
    if not EQUITY_DB_PATH.exists():
        raise HTTPException(503, "equity database not built yet")
    con = duckdb.connect(str(EQUITY_DB_PATH), read_only=True)
    try:
        cur = con.execute(sql, list(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def _lvh_entities():
    """Every distinct 5% filer, with what it filed about itself and how much
    it files. `business_ja` is picked from the most recent filing that states
    one -- a holder that left the field blank once should not lose the
    description it gave in every other report."""
    return _equity_rows("""
        WITH ranked AS (
            SELECT h.holder_edinet_code AS edinet_code,
                   h.name_raw, h.name_en, h.address_raw, h.is_individual,
                   h.business_ja, h.occupation_ja, f.filed_date,
                   ROW_NUMBER() OVER (
                       PARTITION BY h.holder_edinet_code
                       ORDER BY (h.business_ja IS NOT NULL) DESC,
                                f.filed_date DESC) AS rn
            FROM eq_lvh_holders h
            JOIN eq_lvh_filings f USING (doc_id)
            WHERE h.holder_edinet_code IS NOT NULL
        ), agg AS (
            SELECT h.holder_edinet_code AS edinet_code,
                   COUNT(DISTINCT h.doc_id) AS filings,
                   COUNT(DISTINCT f.issuer_edinet_code) AS issuers,
                   MIN(f.filed_date) AS first_filed,
                   MAX(f.filed_date) AS last_filed,
                   MAX(CASE WHEN h.important_proposal THEN 1 ELSE 0 END) AS ever_proposal,
                   MAX(CASE WHEN h.borrowings_yen > 0 THEN 1 ELSE 0 END) AS ever_borrowed
            FROM eq_lvh_holders h
            JOIN eq_lvh_filings f USING (doc_id)
            WHERE h.holder_edinet_code IS NOT NULL
            GROUP BY 1
        )
        SELECT a.edinet_code, r.name_raw, r.name_en, r.address_raw,
               COALESCE(r.is_individual, FALSE) AS is_individual,
               r.business_ja, r.occupation_ja,
               a.filings, a.issuers, a.first_filed, a.last_filed,
               a.ever_proposal = 1 AS ever_proposal,
               a.ever_borrowed = 1 AS ever_borrowed
        FROM agg a JOIN ranked r ON r.edinet_code = a.edinet_code AND r.rn = 1
        ORDER BY a.filings DESC, a.edinet_code
    """)


def _party_evidence(party):
    """What the filings say about the EDINET codes this profile claims -- the
    check that a profile is about the entity the operator thinks it is, and
    the place a curated class can be seen disagreeing with the filed one."""
    codes = [a["key_value"] for a in party.get("aliases") or ()
             if a["key_type"] == "edinet_code"]
    if not codes:
        return []
    placeholders = ", ".join(["?"] * len(codes))
    rows = _equity_rows("""
        SELECT h.holder_edinet_code AS edinet_code,
               ANY_VALUE(h.name_raw) AS name_raw,
               ANY_VALUE(h.business_ja) AS business_ja,
               COALESCE(ANY_VALUE(h.is_individual), FALSE) AS is_individual,
               COUNT(DISTINCT h.doc_id) AS filings,
               MAX(f.filed_date) AS last_filed
        FROM eq_lvh_holders h JOIN eq_lvh_filings f USING (doc_id)
        WHERE h.holder_edinet_code IN (%s)
        GROUP BY 1 ORDER BY filings DESC
    """ % placeholders, codes)
    for row in rows:
        derived, evidence = filer_labels.type_of(
            row["business_ja"], row["is_individual"], None)
        row["derived_type"] = derived
        row["derived_type_label"] = filer_labels.TYPE_EN.get(derived, derived)
        row["derived_evidence"] = evidence
    return rows

# --- party profiles ----------------------------------------------------------
#
# The one thing on this surface that WRITES. It stays inside the one-writer
# rule because it does not write to DuckDB: curation lives in a JSON file
# beside the audit trail (see app/parties.py). Nothing here can touch an eq_*
# table, so no vintage can be rewritten from the admin console.

async def _json_body(request):
    """The submitted profile, as a plain dict. `parties.normalise` is the
    validator -- it rejects unknown keys, so a pass-through pydantic model
    would add nothing but a dependency on its extra-field semantics."""
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    return body


def _party_actor(request):
    """Who made the edit. One shared password means the honest answer is the
    address it came from -- better an accurate IP than a fictional username."""
    return "admin@" + _client_ip(request)


def _party_or_404(party_id):
    doc = parties.load()
    if party_id not in doc["parties"]:
        raise HTTPException(404, "No party %s" % party_id)
    return doc


@router.get("/parties/vocab")
def party_vocab(request: Request):
    _require_admin(request)
    return parties.vocab_payload()


@router.get("/parties/candidates")
def party_candidates(request: Request, min_filings: int = 5,
                     include_individuals: bool = False,
                     unprofiled_only: bool = True, limit: int = 400):
    """The work queue: 5% filers ranked by how much they file, each marked
    with the type DERIVED from its own 事業内容 and with the profile it already
    has, if any. The derived label is a starting point for the operator, never
    a value that gets saved on its behalf."""
    _require_admin(request)
    rows = _lvh_entities()
    index = parties.alias_index()
    doc = parties.load()

    # Coverage over the WHOLE archive, not just the rows this call returns:
    # the queue is filtered, and "how much filing activity now belongs to a
    # profile" is the number that says whether curation is getting anywhere.
    total_filings = sum(r["filings"] for r in rows)
    attributed = sum(r["filings"] for r in rows
                     if ("edinet_code", r["edinet_code"]) in index)

    out = []
    for row in rows:
        if row["filings"] < max(1, min_filings):
            continue
        if row["is_individual"] and not include_individuals:
            continue
        party_id = index.get(("edinet_code", row["edinet_code"]))
        if unprofiled_only and party_id:
            continue
        derived, evidence = filer_labels.type_of(
            row["business_ja"], row["is_individual"], None)
        item = dict(row)
        item["derived_type"] = derived
        item["derived_type_label"] = filer_labels.TYPE_EN.get(derived, derived)
        item["derived_evidence"] = evidence
        item["derived_group"] = filer_labels.group_of(row["edinet_code"])
        item["party_id"] = party_id
        if party_id:
            party = doc["parties"][party_id]
            item["party_display"] = parties.display_of(party)
            item["party_class"] = party.get("party_class")
        out.append(item)
        if len(out) >= max(1, min(limit, 2000)):
            break
    return {"candidates": out,
            "filings_total": total_filings,
            "filings_attributed": attributed,
            "filings_unattributed": total_filings - attributed,
            "entities_total": len(rows),
            "note": ("Ranked by filing count. derived_type is read from the "
                     "filer's own 事業内容 and is evidence, not curation.")}


@router.get("/parties")
def party_list(request: Request, q: str = "", party_class: str = "",
               tier: str = "", limit: int = 500):
    _require_admin(request)
    doc = parties.load()
    needle = (q or "").strip().lower()
    items = []
    for party_id in doc["parties"]:
        party = parties.decorate(doc, party_id)
        if party_class and party.get("party_class") != party_class:
            continue
        if tier and party.get("coverage_tier") != tier:
            continue
        if needle:
            hay = " ".join(str(party.get(f) or "") for f in
                           ("party_id", "display", "legal_name_ja",
                            "legal_name_en", "group_name", "group_label"))
            hay += " " + " ".join(a["key_value"] for a in party.get("aliases") or ())
            if needle not in hay.lower():
                continue
        items.append(party)
    items.sort(key=lambda p: (p.get("completeness", 0), p.get("display") or ""))
    return {"parties": items[:max(1, min(limit, 2000))],
            "total": len(doc["parties"])}


@router.post("/parties/export")
def party_export(request: Request):
    """Copy the live store over the git-tracked seed, so hand-typed curation
    is versioned and survives the volume. Deliberately manual and deliberately
    one-way: the seed only ever loads into an ABSENT store."""
    _require_admin(request)
    doc = parties.load()
    parties.SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)
    with open(str(parties.SEED_PATH), "w", encoding="utf-8") as f:
        f.write(payload + "\n")
    audit("party_exported", "%d parties -> %s"
          % (len(doc["parties"]), parties.SEED_PATH.name), _client_ip(request))
    return {"path": str(parties.SEED_PATH), "parties": len(doc["parties"]),
            "bytes": len(payload) + 1,
            "note": "Commit observatory/curation/parties.json to version this."}


@router.get("/parties/{party_id}")
def party_detail(party_id: str, request: Request):
    _require_admin(request)
    doc = _party_or_404(party_id)
    party = parties.decorate(doc, party_id)
    party["evidence"] = _party_evidence(party)
    return party


@router.post("/parties")
async def party_create(request: Request):
    _require_admin(request)
    body = await _json_body(request)
    try:
        party = parties.create(body, _party_actor(request))
    except parties.ProfileError as exc:
        raise HTTPException(400, str(exc))
    audit("party_created", "%s (%s)" % (party["party_id"], party["display"]),
          _client_ip(request))
    return party


@router.put("/parties/{party_id}")
async def party_update(party_id: str, request: Request):
    _require_admin(request)
    _party_or_404(party_id)
    body = await _json_body(request)
    try:
        party = parties.update(party_id, body, _party_actor(request))
    except parties.ProfileError as exc:
        raise HTTPException(400, str(exc))
    audit("party_updated", "%s (%s)" % (party_id, party["display"]),
          _client_ip(request))
    return party


@router.delete("/parties/{party_id}")
def party_delete(party_id: str, request: Request):
    _require_admin(request)
    _party_or_404(party_id)
    try:
        parties.delete(party_id)
    except parties.ProfileError as exc:
        raise HTTPException(409, str(exc))
    audit("party_deleted", party_id, _client_ip(request))
    return {"deleted": party_id}
