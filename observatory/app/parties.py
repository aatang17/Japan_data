# -*- coding: utf-8 -*-
u"""The party registry: who a fund, company or person IS, curated by hand.

Every equity surface names the same institutions and none of them agree on who
they are. The 5% filings carry an EDINET code for almost every holder, but the
register top-ten (`eq_major_shareholders`) has none for 17,345 of its 25,320
rows, and no director in `eq_board` has one at all. BlackRock files under
sixteen codes, Fidelity thirteen, Nomura eight. So the source's identifier
cannot be ours: a party gets an id of our own, and the source keys hang off it
as aliases.

Three things this module is deliberately NOT:

  * It is **not** `filer_labels.py`. That module reads `filer_type` out of the
    filing's own 事業内容 -- evidence, derived at serve time, never stored, and
    auditable against the document. This one holds OUR JUDGEMENT: no filing
    anywhere says "hedge fund". Both render, side by side, and a disagreement
    between them is a work queue rather than a defect.

  * It is **not** a DuckDB table. `admin_api.py` is read-only against the
    database on purpose (Ingest Guardrail 5 -- the serving process never
    writes), so curation lives where the audit trail lives: a JSON file under
    `data/admin/`, written atomically. At ~1,700 parties that is a few hundred
    KB and loads in milliseconds, and it makes the git-committed backup free
    because the store IS the export format.

  * It **never touches `eq_*`.** No vintage can be rewritten from here.

The taxonomy is three fields rather than one longer list, because one list
forces false choices. Evo Fund is a hedge fund AND a convert-arb shop; Nomura
Asset Management is an asset manager running both index and active money; and
日本マスタートラスト信託銀行(信託口) -- the second most frequent name on the
Japanese register -- is a trust bank that is not the owner of anything it
holds. `party_class` says what it is, `strategy` says how it invests, and
`holder_role` says why it is on the register.
"""
import copy
import datetime
import json
import os
import re
import tempfile

from . import db

STORE_PATH = db.DATA_DIR / "admin" / "parties.json"
# The git-committed copy. Seeds an empty volume and is what `export` writes
# back to, so hand-typed curation is versioned and diffable rather than living
# only on a mounted disk.
SEED_PATH = db.ROOT / "curation" / "parties.json"

SCHEMA_VERSION = 1


# --- vocabularies ------------------------------------------------------------
#
# Served to the admin form from here, so the options offered can never drift
# from what validation accepts. Order is display order.

# What the party legally is. Exactly one, required.
PARTY_CLASS = (
    ("asset_manager", u"Asset manager"),
    ("hedge_fund", u"Hedge fund"),
    ("private_equity", u"Private equity"),
    ("venture_capital", u"Venture capital"),
    ("pension_fund", u"Pension fund"),
    ("sovereign_wealth_fund", u"Sovereign wealth fund"),
    ("insurer", u"Insurer"),
    ("bank", u"Bank"),
    ("trust_bank", u"Trust bank"),
    ("broker_dealer", u"Broker-dealer"),
    ("custodian", u"Custodian / nominee"),
    ("operating_company", u"Operating company"),
    ("family_vehicle", u"Family / founder vehicle"),
    ("employee_trust", u"ESOP / employee trust"),
    ("government_body", u"Government body"),
    ("foundation", u"Foundation / endowment"),
    ("individual", u"Individual"),
    ("unknown", u"Unknown"),
)

# How it invests. Zero or many, and only meaningful for investors -- an
# operating company holding a supplier's shares has no strategy.
STRATEGY = (
    ("passive_index", u"Passive / index"),
    ("active_long_only", u"Active long-only"),
    ("activist", u"Activist"),
    ("engagement", u"Engagement (constructive)"),
    ("event_driven", u"Event-driven / merger arb"),
    ("convert_arb", u"Convertible & warrant arb"),
    ("long_short", u"Long-short equity"),
    ("quant", u"Quant / systematic"),
    ("multi_strategy", u"Multi-strategy"),
    ("buyout", u"Buyout"),
    ("growth_minority", u"Growth / minority"),
    ("credit", u"Credit"),
    ("market_making", u"Market-making / own book"),
)

# Why the party appears on a register or a filing. Exactly one. This is the
# field that stops a nominee being ranked as an owner.
HOLDER_ROLE = (
    ("beneficial_owner", u"Beneficial owner"),
    ("nominee", u"Nominee / custodian"),
    ("standing_proxy", u"Standing proxy (常任代理人)"),
    ("trust_account", u"Trust account (信託口)"),
    ("strategic", u"Strategic / business"),
    ("insider", u"Insider / founder"),
    ("employee_plan", u"Employee plan"),
    ("unknown", u"Unknown"),
)

# Which arm of a group this party is. Answers "what do we call Nomura when it
# is AM, Securities and Banking" -- we call each arm by its function and let
# the parent carry the group name.
GROUP_ROLE = (
    ("holding_company", u"Holding company"),
    ("asset_management", u"Asset management"),
    ("securities", u"Securities"),
    ("banking", u"Banking"),
    ("trust", u"Trust"),
    ("insurance", u"Insurance"),
    ("advisory", u"Advisory"),
    ("fund_vehicle", u"Fund vehicle"),
    ("operating", u"Operating"),
    ("other", u"Other"),
)

# How much we care. Drives the work queue's sort, nothing else.
COVERAGE_TIER = (
    ("a", u"A - core coverage"),
    ("b", u"B - watched"),
    ("c", u"C - long tail"),
)

ACTIVIST_STANCE = (
    ("yes", u"Yes - has run a campaign"),
    ("watch", u"Watch - could turn activist"),
    ("no", u"No"),
    ("unknown", u"Unknown"),
)

LIFECYCLE = (
    ("active", u"Active"),
    ("renamed", u"Renamed"),
    ("merged", u"Merged"),
    ("dissolved", u"Dissolved"),
)

ALIAS_KEY_TYPES = ("edinet_code", "name_key", "sec_code", "person_key")

VOCAB = {
    "party_class": PARTY_CLASS,
    "strategy": STRATEGY,
    "holder_role": HOLDER_ROLE,
    "group_role": GROUP_ROLE,
    "coverage_tier": COVERAGE_TIER,
    "activist": ACTIVIST_STANCE,
    "lifecycle": LIFECYCLE,
}

# Free-text and flag fields a profile carries, with the type the validator
# enforces. Kept as data rather than a pile of ifs so adding a field is one
# line here and one input in the form.
TEXT_FIELDS = (
    "legal_name_ja", "legal_name_en", "display_name", "group_name",
    "lei", "jurisdiction", "hq_country", "hq_city", "website",
    "sec_code", "fsa_registration", "home_regulator",
    "aum_currency", "aum_as_of", "aum_source",
    "voting_records_url", "thesis", "key_people", "contacts", "notes",
    "founded_year", "successor_party_id",
)
NUMBER_FIELDS = ("aum_amount_musd", "japan_equity_aum_musd")
FLAG_FIELDS = (
    "files_13f", "stewardship_code_signatory", "publishes_voting_records",
    "pri_signatory", "public",
)

MAX_TEXT = 4000


def vocab_payload():
    u"""The taxonomy, shaped for the admin form."""
    out = {}
    for name, pairs in VOCAB.items():
        out[name] = [{"value": v, "label": l} for v, l in pairs]
    out["alias_key_types"] = list(ALIAS_KEY_TYPES)
    out["text_fields"] = list(TEXT_FIELDS)
    out["number_fields"] = list(NUMBER_FIELDS)
    out["flag_fields"] = list(FLAG_FIELDS)
    return out


def _values(name):
    return set(v for v, _ in VOCAB[name])


def label_of(name, value):
    for v, l in VOCAB.get(name, ()):
        if v == value:
            return l
    return None


# --- the store ---------------------------------------------------------------
#
# One JSON document: {"schema": 1, "parties": {id: profile}}. Held in memory
# and reloaded when the file's mtime/size changes, the same cheap staleness
# check `equity_api._cur()` uses for the database.

_CACHE = None
_CACHE_VERSION = None


def _empty():
    return {"schema": SCHEMA_VERSION, "parties": {}}


def _version(path):
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _read(path):
    try:
        with open(str(path), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("parties"), dict):
        return None
    return doc


def load():
    u"""The whole store. Seeded from the git copy when the volume has none."""
    global _CACHE, _CACHE_VERSION
    version = _version(STORE_PATH)
    if _CACHE is not None and _CACHE_VERSION == version:
        return _CACHE
    doc = _read(STORE_PATH) if STORE_PATH.exists() else None
    if doc is None:
        # An unreadable live store must never be silently replaced by the seed
        # -- that would discard curation. Only an ABSENT one seeds.
        if STORE_PATH.exists():
            raise RuntimeError(
                "%s exists but is not readable as a party store; refusing to "
                "overwrite it with the seed" % STORE_PATH)
        doc = _read(SEED_PATH) or _empty()
    _CACHE, _CACHE_VERSION = doc, version
    return doc


def save(doc):
    u"""Write the store atomically: a half-written file would lose everything
    typed so far, and this is hand-entered data with no upstream to re-fetch."""
    global _CACHE, _CACHE_VERSION
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(dir=str(STORE_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(STORE_PATH))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    _CACHE, _CACHE_VERSION = doc, _version(STORE_PATH)
    return doc


def _now():
    return (datetime.datetime.now(datetime.timezone.utc)
            .replace(tzinfo=None, microsecond=0).isoformat() + "Z")


# --- ids ---------------------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text):
    u"""A readable id stem. Japanese-only names have no ASCII to slug, so they
    fall back to a numbered stem rather than producing an empty id."""
    slug = _SLUG_STRIP.sub("-", (text or "").lower()).strip("-")
    return slug[:48] or ""


def new_id(doc, preferred):
    parties = doc["parties"]
    stem = slugify(preferred) or "party"
    if stem not in parties:
        return stem
    n = 2
    while "%s-%d" % (stem, n) in parties:
        n += 1
    return "%s-%d" % (stem, n)


# --- aliases -----------------------------------------------------------------

def alias_index(doc=None):
    u"""(key_type, key_value) -> party_id, for resolving a filed row to a
    profile. Built on read; the store is far too small for this to matter."""
    doc = doc or load()
    index = {}
    for pid, party in doc["parties"].items():
        for alias in party.get("aliases", ()):
            index[(alias.get("key_type"), alias.get("key_value"))] = pid
    return index


def resolve(key_type, key_value, doc=None):
    return alias_index(doc).get((key_type, key_value))


def alias_owner(doc, key_type, key_value, exclude=None):
    for pid, party in doc["parties"].items():
        if pid == exclude:
            continue
        for alias in party.get("aliases", ()):
            if alias.get("key_type") == key_type and alias.get("key_value") == key_value:
                return pid
    return None


# --- validation --------------------------------------------------------------

class ProfileError(ValueError):
    u"""A rejected edit. The message is shown to the operator verbatim."""


def _clean_text(name, value):
    if value is None:
        return None
    if not isinstance(value, (str, bytes)):
        raise ProfileError("%s must be text" % name)
    value = value.strip()
    if len(value) > MAX_TEXT:
        raise ProfileError("%s is longer than %d characters" % (name, MAX_TEXT))
    return value or None


def normalise(body, doc, party_id=None):
    u"""Validate one submitted profile into its stored shape.

    Unknown keys are rejected rather than ignored: a typo'd field name that is
    quietly dropped looks exactly like a save that worked, and this is data
    someone typed by hand.
    """
    if not isinstance(body, dict):
        raise ProfileError("expected an object")
    known = (set(TEXT_FIELDS) | set(NUMBER_FIELDS) | set(FLAG_FIELDS) |
             {"party_class", "holder_role", "group_role", "coverage_tier",
              "activist", "lifecycle", "strategy", "parent_id", "aliases",
              "tags", "source", "as_of", "confidence"})
    unknown = sorted(set(body) - known)
    if unknown:
        raise ProfileError("unknown field(s): %s" % ", ".join(unknown))

    out = {}
    for field in TEXT_FIELDS:
        out[field] = _clean_text(field, body.get(field))
    for field in NUMBER_FIELDS:
        value = body.get(field)
        if value in (None, ""):
            out[field] = None
            continue
        try:
            out[field] = float(value)
        except (TypeError, ValueError):
            raise ProfileError("%s must be a number" % field)
        if out[field] < 0:
            raise ProfileError("%s cannot be negative" % field)
    for field in FLAG_FIELDS:
        value = body.get(field)
        out[field] = None if value is None else bool(value)

    # Single-valued vocabularies.
    for field, vocab, required in (("party_class", "party_class", True),
                                   ("holder_role", "holder_role", False),
                                   ("group_role", "group_role", False),
                                   ("coverage_tier", "coverage_tier", False),
                                   ("activist", "activist", False),
                                   ("lifecycle", "lifecycle", False)):
        value = body.get(field) or None
        if value is None:
            if required:
                raise ProfileError("%s is required" % field)
            out[field] = None
            continue
        if value not in _values(vocab):
            raise ProfileError("%s: %r is not one of %s"
                               % (field, value, ", ".join(sorted(_values(vocab)))))
        out[field] = value

    # Strategy is a set, and order is display order rather than entry order so
    # two profiles with the same strategies always read the same.
    raw = body.get("strategy") or []
    if isinstance(raw, (str, bytes)):
        raw = [raw]
    if not isinstance(raw, list):
        raise ProfileError("strategy must be a list")
    picked = set()
    for item in raw:
        if item not in _values("strategy"):
            raise ProfileError("strategy: %r is not a known value" % (item,))
        picked.add(item)
    out["strategy"] = [v for v, _ in STRATEGY if v in picked]

    tags = body.get("tags") or []
    if isinstance(tags, (str, bytes)):
        tags = [t.strip() for t in tags.split(",")]
    if not isinstance(tags, list):
        raise ProfileError("tags must be a list")
    out["tags"] = sorted(set(t.strip() for t in tags if isinstance(t, str) and t.strip()))

    out["source"] = _clean_text("source", body.get("source"))
    out["as_of"] = _clean_text("as_of", body.get("as_of"))
    out["confidence"] = _clean_text("confidence", body.get("confidence"))

    # Parent. A party cannot be its own parent, the parent must exist, and the
    # chain must not close a loop -- a cycle would hang every roll-up that
    # walks to the group.
    parent = _clean_text("parent_id", body.get("parent_id"))
    if parent:
        if parent == party_id:
            raise ProfileError("a party cannot be its own parent")
        if parent not in doc["parties"]:
            raise ProfileError("parent_id %r does not exist" % parent)
        if party_id:
            seen, cursor = {party_id}, parent
            while cursor:
                if cursor in seen:
                    raise ProfileError("parent_id %r would make a cycle" % parent)
                seen.add(cursor)
                cursor = (doc["parties"].get(cursor) or {}).get("parent_id")
    out["parent_id"] = parent

    # Aliases. Every one must be unique across the whole store, or one filed
    # row would resolve to two profiles and a ranking would double-count.
    aliases, seen = [], set()
    raw_aliases = body.get("aliases")
    if raw_aliases is None:
        raw_aliases = []
    if not isinstance(raw_aliases, list):
        raise ProfileError("aliases must be a list")
    for alias in raw_aliases:
        if not isinstance(alias, dict):
            raise ProfileError("each alias must be an object")
        key_type = alias.get("key_type")
        key_value = _clean_text("alias key_value", alias.get("key_value"))
        if key_type not in ALIAS_KEY_TYPES:
            raise ProfileError("alias key_type %r is not one of %s"
                               % (key_type, ", ".join(ALIAS_KEY_TYPES)))
        if not key_value:
            raise ProfileError("an alias needs a key_value")
        pair = (key_type, key_value)
        if pair in seen:
            continue
        owner = alias_owner(doc, key_type, key_value, exclude=party_id)
        if owner:
            raise ProfileError("%s %s already belongs to %s"
                               % (key_type, key_value, owner))
        seen.add(pair)
        aliases.append({"key_type": key_type, "key_value": key_value,
                        "note": _clean_text("alias note", alias.get("note"))})
    out["aliases"] = aliases

    if not (out["display_name"] or out["legal_name_en"] or out["legal_name_ja"]):
        raise ProfileError("a party needs at least one name")
    return out


def completeness(party):
    u"""How filled-in a profile is, 0-100. Drives the work queue so the next
    thing to type is always at the top. The fields counted are the ones that
    make a profile useful to a reader, not every field that exists."""
    counted = ("display_name", "legal_name_en", "party_class", "holder_role",
               "jurisdiction", "hq_country", "website", "coverage_tier",
               "activist", "thesis")
    have = sum(1 for f in counted if party.get(f))
    if party.get("strategy"):
        have += 1
    return int(round(100.0 * have / (len(counted) + 1)))


def display_of(party):
    return (party.get("display_name") or party.get("legal_name_en")
            or party.get("legal_name_ja") or "")


def group_label(doc, party):
    u"""The group name a party rolls up to: the parent's group_name, else the
    parent's display name, else the party's own group_name."""
    parent_id = party.get("parent_id")
    if parent_id:
        parent = doc["parties"].get(parent_id) or {}
        return parent.get("group_name") or display_of(parent) or None
    return party.get("group_name") or None


def decorate(doc, party_id):
    u"""One profile plus the fields the UI shows but nobody types."""
    party = copy.deepcopy(doc["parties"][party_id])
    party["party_id"] = party_id
    party["display"] = display_of(party)
    party["completeness"] = completeness(party)
    party["group_label"] = group_label(doc, party)
    party["party_class_label"] = label_of("party_class", party.get("party_class"))
    party["holder_role_label"] = label_of("holder_role", party.get("holder_role"))
    party["group_role_label"] = label_of("group_role", party.get("group_role"))
    party["strategy_labels"] = [label_of("strategy", s)
                                for s in party.get("strategy") or ()]
    party["children"] = sorted(
        pid for pid, p in doc["parties"].items() if p.get("parent_id") == party_id)
    return party


# --- writes ------------------------------------------------------------------

def create(body, actor):
    doc = copy.deepcopy(load())
    profile = normalise(body, doc, party_id=None)
    party_id = new_id(doc, profile.get("legal_name_en") or profile.get("display_name"))
    profile["created_at"] = profile["updated_at"] = _now()
    profile["updated_by"] = actor
    doc["parties"][party_id] = profile
    save(doc)
    return decorate(load(), party_id)


def update(party_id, body, actor):
    doc = copy.deepcopy(load())
    if party_id not in doc["parties"]:
        raise KeyError(party_id)
    existing = doc["parties"][party_id]
    profile = normalise(body, doc, party_id=party_id)
    profile["created_at"] = existing.get("created_at") or _now()
    profile["updated_at"] = _now()
    profile["updated_by"] = actor
    doc["parties"][party_id] = profile
    save(doc)
    return decorate(load(), party_id)


def delete(party_id):
    u"""Remove a profile. Refused while another party names it as parent --
    an orphaned parent_id would break every roll-up that walks the chain."""
    doc = copy.deepcopy(load())
    if party_id not in doc["parties"]:
        raise KeyError(party_id)
    kids = sorted(pid for pid, p in doc["parties"].items()
                  if p.get("parent_id") == party_id)
    if kids:
        raise ProfileError("%s is the parent of %s; reassign them first"
                           % (party_id, ", ".join(kids)))
    del doc["parties"][party_id]
    save(doc)
