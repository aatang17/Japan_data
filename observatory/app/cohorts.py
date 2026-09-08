# -*- coding: utf-8 -*-
u"""Cohorts — the peer group a number is read against.

A rank over the whole listed market answers almost nothing. "Third-lowest
female board representation" is a different claim among 3,700 issues than
inside TOPIX Core30, and a cross-shareholding ratio that is ordinary for a
regional bank is remarkable for a Prime-listed machinery maker. Every
cross-company surface in the product therefore takes an optional cohort, and
this module is the single place that turns a cohort into a set of security
codes.

A cohort is named by a short spec string, because it has to survive in a URL:

    size:core30          the TOPIX scale bands   (core30 large70 mid400 small1 small2)
    topix                every TOPIX constituent (any scale band)
    segment:prime        JPX market segment      (prime standard growth)
    ind33:3650           JPX 33-industry code
    ind17:6              JPX 17-industry code
    index:nk225          Nikkei 225 membership   — restricted, see below
    codes:7203,6758      an ad-hoc basket you define

Baskets are deliberately stateless. Guardrail 5 says the serving process never
writes to the database, so there is nowhere on the server to save a named
basket to — and that turns out to be the better design anyway: a basket that
lives entirely in its spec string is a permanent, citable URL, which is what
the whole platform is for. The front end remembers names for baskets in the
reader's own browser; the server only ever sees the codes.

Restricted cohorts
------------------
The JPX classification is published for public reference. The Nikkei 225
constituent file is not: it carries an explicit notice that it is Nikkei's
copyrighted work and may not be reproduced or redistributed without
permission. Its rows are stored with ``public = FALSE`` and this module will
not resolve them unless ``INTERNAL_COHORTS`` is an explicit truthy value in
the environment — off by default, the same shape of kill switch as
ASK_ENABLED. A deployment that turns it on is asserting it has the right to
show that membership to whoever can reach it.

Point-in-time
-------------
Each source file is stored as a vintage stamped with its own effective date.
`as_of=None` resolves against the newest vintage; a date resolves against the
newest vintage at or before it, so a cohort can be reconstructed as it stood.
"""
import os

# Ordering is the product's, not the source's: bands run large to small,
# segments run by listing standard, so a catalogue never comes back arbitrary.
SIZE_BANDS = [
    ("core30",  u"TOPIX Core30"),
    ("large70", u"TOPIX Large70"),
    ("mid400",  u"TOPIX Mid400"),
    ("small1",  u"TOPIX Small 1"),
    ("small2",  u"TOPIX Small 2"),
]
SEGMENTS = [
    ("prime",    u"Prime"),
    ("standard", u"Standard"),
    ("growth",   u"Growth"),
]
SIZE_KEYS = dict(SIZE_BANDS)
SEGMENT_KEYS = dict(SEGMENTS)

# Composites people actually ask for, above the raw bands.
SIZE_ROLLUPS = {
    "large": (("core30", "large70"), u"TOPIX Large (Core30 + Large70)"),
    "small": (("small1", "small2"),  u"TOPIX Small (Small 1 + Small 2)"),
}

INDEXES = {"nk225": (u"Nikkei 225", False)}

MAX_BASKET = 500


class CohortError(ValueError):
    u"""A spec that cannot be honoured — malformed, unknown, or restricted."""


def internal_enabled():
    u"""Kill switch for cohorts whose membership we may not redistribute."""
    return os.environ.get("INTERNAL_COHORTS", "").strip().lower() in (
        "1", "true", "yes", "on")


def available(cur):
    u"""Is the classification present at all? (An old database predates it.)"""
    row = cur.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_name IN ('eq_classification','eq_class_vintages')"
    ).fetchone()
    return bool(row and row[0] == 2)


def vintage(cur, source, as_of=None):
    u"""The newest vintage of `source` at or before `as_of` (newest if None).

    Returns None when the source has no vintage that old — which is the
    honest answer for a date before we started collecting, and never a
    silent fall-through to today's membership.
    """
    sql = ("SELECT vintage_id, as_of, public FROM eq_class_vintages "
           "WHERE source = ?")
    params = [source]
    if as_of:
        sql += " AND as_of <= ?"
        params.append(as_of)
    sql += " ORDER BY as_of DESC, fetched_at DESC LIMIT 1"
    return cur.execute(sql, params).fetchone()


def _codes(cur, sql, params):
    return [r[0] for r in cur.execute(sql, params).fetchall()]


def parse(spec):
    u"""Split a spec into (kind, value). 'topix' has no value."""
    spec = (spec or "").strip()
    if not spec:
        return None, None
    if ":" not in spec:
        return spec.lower(), None
    kind, _, value = spec.partition(":")
    return kind.strip().lower(), value.strip()


def resolve(cur, spec, as_of=None):
    u"""spec -> {'spec', 'label', 'members' (sorted codes), 'as_of', 'public'}.

    Raises CohortError for anything it will not answer. A cohort that resolves
    to no members is returned as an empty cohort, not an error: an industry
    with nothing in it at an early vintage is a fact, not a bad request.
    """
    kind, value = parse(spec)
    if kind is None:
        raise CohortError("no cohort given")

    if kind == "codes":
        raw = [c.strip().upper() for c in (value or "").split(",") if c.strip()]
        if not raw:
            raise CohortError("codes: needs at least one security code")
        if len(raw) > MAX_BASKET:
            raise CohortError("a basket holds at most %d codes" % MAX_BASKET)
        bad = [c for c in raw if not (len(c) == 4 and c[:3].isdigit())]
        if bad:
            raise CohortError("not security codes: %s" % ", ".join(bad[:5]))
        # Order is the caller's; duplicates collapse. Codes are NOT filtered
        # against the registry here — a basket that names a company we hold no
        # filing for should come back short, visibly, rather than silently.
        members, seen = [], set()
        for c in raw:
            if c not in seen:
                seen.add(c)
                members.append(c)
        return {"spec": "codes:" + ",".join(members),
                "label": u"Custom basket (%d)" % len(members),
                "members": members, "as_of": None, "public": True,
                "kind": "codes"}

    if kind == "index":
        name_public = INDEXES.get(value or "")
        if not name_public:
            raise CohortError("unknown index: %s" % value)
        label, is_public = name_public
        if not is_public and not internal_enabled():
            raise CohortError(
                "%s membership is not ours to serve: the constituent file is "
                "the publisher's copyrighted work. Set INTERNAL_COHORTS to "
                "use it on a deployment entitled to it." % label)
        v = vintage(cur, "nikkei-225", as_of)
        if not v:
            return {"spec": spec, "label": label, "members": [],
                    "as_of": None, "public": False, "kind": "index"}
        members = _codes(cur,
                         "SELECT sec_code FROM eq_index_member "
                         "WHERE vintage_id = ? AND index_code = ? "
                         "ORDER BY sec_code", [v[0], value])
        return {"spec": spec, "label": label, "members": members,
                "as_of": v[1], "public": False, "kind": "index"}

    v = vintage(cur, "jpx-listed", as_of)
    if not v:
        raise CohortError("no JPX classification vintage%s"
                          % (" at or before %s" % as_of if as_of else ""))
    vid, vas_of = v[0], v[1]
    base = ("SELECT sec_code FROM eq_classification WHERE vintage_id = ? "
            "AND domestic")
    if kind == "topix":
        sql = base + " AND size_code IS NOT NULL ORDER BY sec_code"
        return _cohort(spec, u"TOPIX (all constituents)",
                       _codes(cur, sql, [vid]), vas_of)
    if kind == "size":
        if value in SIZE_ROLLUPS:
            bands, label = SIZE_ROLLUPS[value]
            marks = ", ".join("?" * len(bands))
            sql = base + (" AND size_code IN (%s) ORDER BY sec_code" % marks)
            return _cohort(spec, label, _codes(cur, sql, [vid] + list(bands)),
                           vas_of)
        if value not in SIZE_KEYS:
            raise CohortError("unknown size band: %s" % value)
        sql = base + " AND size_code = ? ORDER BY sec_code"
        return _cohort(spec, SIZE_KEYS[value], _codes(cur, sql, [vid, value]),
                       vas_of)
    if kind == "segment":
        if value not in SEGMENT_KEYS:
            raise CohortError("unknown market segment: %s" % value)
        sql = base + " AND segment = ? ORDER BY sec_code"
        return _cohort(spec, SEGMENT_KEYS[value] + u" market",
                       _codes(cur, sql, [vid, value]), vas_of)
    if kind in ("ind33", "ind17"):
        col = "ind33" if kind == "ind33" else "ind17"
        row = cur.execute(
            "SELECT %s_name FROM eq_classification WHERE vintage_id = ? "
            "AND %s_code = ? LIMIT 1" % (col, col), [vid, value]).fetchone()
        if not row:
            raise CohortError("unknown %s industry code: %s" % (col, value))
        sql = base + (" AND %s_code = ? ORDER BY sec_code" % col)
        return _cohort(spec, row[0], _codes(cur, sql, [vid, value]), vas_of)

    raise CohortError("unknown cohort: %s" % spec)


def _cohort(spec, label, members, as_of):
    return {"spec": spec, "label": label, "members": members,
            "as_of": as_of, "public": True, "kind": parse(spec)[0]}


def catalogue(cur, as_of=None):
    u"""Every cohort that can be asked for right now, with its size.

    Counts come from the same vintage the cohort would resolve against, so a
    catalogue never advertises a peer group that turns out to be empty.
    """
    out = {"as_of": None, "index_as_of": None, "groups": []}
    v = vintage(cur, "jpx-listed", as_of)
    if v:
        vid, out["as_of"] = v[0], v[1]
        counts = dict(cur.execute(
            "SELECT size_code, count(*) FROM eq_classification "
            "WHERE vintage_id = ? AND domestic AND size_code IS NOT NULL "
            "GROUP BY 1", [vid]).fetchall())
        bands = [{"spec": "size:" + k, "label": lbl, "count": counts.get(k, 0)}
                 for k, lbl in SIZE_BANDS]
        rollups = [{"spec": "size:" + k,
                    "label": lbl,
                    "count": sum(counts.get(b, 0) for b in members)}
                   for k, (members, lbl) in sorted(SIZE_ROLLUPS.items())]
        out["groups"].append({
            "key": "size", "label": u"TOPIX scale",
            "note": u"The scale bands JPX assigns; the issues carrying one "
                    u"are the TOPIX constituents.",
            "cohorts": [{"spec": "topix", "label": u"TOPIX (all constituents)",
                         "count": sum(counts.values())}] + rollups + bands})

        seg = dict(cur.execute(
            "SELECT segment, count(*) FROM eq_classification "
            "WHERE vintage_id = ? AND domestic GROUP BY 1", [vid]).fetchall())
        out["groups"].append({
            "key": "segment", "label": u"Market segment",
            "note": u"Where the issue is listed on the Tokyo Stock Exchange.",
            "cohorts": [{"spec": "segment:" + k, "label": lbl,
                         "count": seg.get(k, 0)} for k, lbl in SEGMENTS]})

        for col, key, label in (("ind33", "ind33", u"Industry (33)"),
                                ("ind17", "ind17", u"Industry (17)")):
            rows = cur.execute(
                "SELECT %s_code, any_value(%s_name), count(*) "
                "FROM eq_classification WHERE vintage_id = ? AND domestic "
                "AND %s_code IS NOT NULL GROUP BY 1 ORDER BY 1"
                % (col, col, col), [vid]).fetchall()
            out["groups"].append({
                "key": key, "label": label,
                "note": u"JPX's own sector classification, as filed.",
                "cohorts": [{"spec": "%s:%s" % (key, r[0]), "label": r[1],
                             "count": r[2]} for r in rows]})

    iv = vintage(cur, "nikkei-225", as_of)
    if iv and internal_enabled():
        out["index_as_of"] = iv[1]
        n = cur.execute("SELECT count(*) FROM eq_index_member "
                        "WHERE vintage_id = ?", [iv[0]]).fetchone()[0]
        out["groups"].append({
            "key": "index", "label": u"Index membership",
            "note": u"Restricted — the constituent list is the publisher's "
                    u"copyrighted work and is not served publicly.",
            "restricted": True,
            "cohorts": [{"spec": "index:nk225", "label": u"Nikkei 225",
                         "count": n, "public": False}]})
    return out


def classify(cur, sec_code, as_of=None):
    u"""One company's own classification, plus the cohorts it sits in.

    Returns None when the company is not in the classification at all —
    delisted, a fund, or listed since the vintage was published.
    """
    v = vintage(cur, "jpx-listed", as_of)
    if not v:
        return None
    row = cur.execute(
        "SELECT name_ja, segment, segment_ja, domestic, ind33_code, "
        "ind33_name, ind17_code, ind17_name, size_code, size_name "
        "FROM eq_classification WHERE vintage_id = ? AND sec_code = ?",
        [v[0], sec_code]).fetchone()
    if not row:
        return None
    out = {
        "sec_code": sec_code, "as_of": v[1], "name_ja": row[0],
        "segment": row[1], "segment_label": SEGMENT_KEYS.get(row[1], row[2]),
        "domestic": row[3],
        "ind33_code": row[4], "ind33_name": row[5],
        "ind17_code": row[6], "ind17_name": row[7],
        "size_code": row[8], "size_name": row[9],
        "in_topix": row[8] is not None,
        "cohorts": [],
    }
    if row[8]:
        out["cohorts"].append({"spec": "size:" + row[8], "label": row[9]})
    if row[1] in SEGMENT_KEYS:
        out["cohorts"].append({"spec": "segment:" + row[1],
                               "label": SEGMENT_KEYS[row[1]] + u" market"})
    if row[4]:
        out["cohorts"].append({"spec": "ind33:" + row[4], "label": row[5]})
    if row[6]:
        out["cohorts"].append({"spec": "ind17:" + row[6], "label": row[7]})

    iv = vintage(cur, "nikkei-225", as_of)
    if iv and internal_enabled():
        hit = cur.execute("SELECT weight_pct FROM eq_index_member "
                          "WHERE vintage_id = ? AND sec_code = ?",
                          [iv[0], sec_code]).fetchone()
        out["in_nk225"] = hit is not None
        if hit:
            out["nk225_weight_pct"] = hit[0]
            out["cohorts"].append({"spec": "index:nk225",
                                   "label": u"Nikkei 225", "public": False})
    return out


def natural(cur, sec_code, as_of=None):
    u"""The default peer group for a company: its 33-industry, which is the
    comparison an analyst reaches for first. Falls back to its market segment,
    then to nothing — never to "the whole market", which is the denominator
    this module exists to replace."""
    info = classify(cur, sec_code, as_of)
    if not info:
        return None
    if info["ind33_code"]:
        return "ind33:" + info["ind33_code"]
    if info["segment"] in SEGMENT_KEYS:
        return "segment:" + info["segment"]
    return None


def member_set(cur, spec, as_of=None):
    u"""(set of codes, cohort) for a spec, or (None, None) when none was given.

    The shape every screen takes its optional ?cohort= through, so "within
    TOPIX Core30" means the same population on the financials screener as it
    does on the board screen.
    """
    if not (spec or "").strip():
        return None, None
    c = resolve(cur, spec, as_of)
    return set(c["members"]), c
