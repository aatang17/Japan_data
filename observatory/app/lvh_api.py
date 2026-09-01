# -*- coding: utf-8 -*-
u"""Equity product API — 5% filings (大量保有報告書・変更報告書).

The tape: who is accumulating, in whom, how fast, and — filed, not inferred —
whether they say they may make important proposals to the board. Served from
the same DuckDB file and reader as the rest of the equity product.

WHAT A CONSUMER MUST NOT ASSUME, carried in the data rather than in prose:

  1. A REPORT IS AN EVENT, NOT A POSITION. Every filing is a snapshot at its
     own trigger date (requirement_date, 提出義務発生日). "Who holds 5% of X
     today" is the LATEST report per (issuer, filing group) — which is what
     /company returns — and a group that has fallen below 5% files a final
     report and then stops, so a stale-looking row may be an exit. `is_current`
     says whether the latest report still shows 5% or more.
  2. THE GROUP IS THE UNIT. A report covers a filer and its joint holders, and
     the group ratio is not the sum of its members: the form deducts claims
     between joint holders, and a member that has just left is still described
     in the document with last-report figures only. Members that count toward
     the group carry in_group_total.
  3. 重要提案行為 IS NOT ASKED ON EVERY FORM. The change report (第三号様式)
     and the special form (第二号様式 — the exemption for institutions that
     undertake to make no such proposals) carry no such field at all, so
     important_proposal is null on them. `proposal_asked` says which case a
     null is: false means the form never put the question, true means it did
     and the filer left it blank. Null never means "no".
  4. A CHANGE REPORT OFTEN RESTATES THE ORIGINAL OBLIGATION DATE. 提出義務
     発生日 on a 変更報告書 is frequently the date the holder first crossed 5%,
     not the date of the change reported — so requirement_date orders the tape
     but the gap to filed_date is not a lateness measure.
  5. THE RATIO IS THE STATUTORY ONE. Its denominator is 発行済株式等総数 plus
     the holder's own potential shares, so it does not equal shares_held /
     shares_outstanding and the difference is not an error.
"""
from fastapi import APIRouter, HTTPException, Query

from .equity_api import NAMES_NOTE, NAME_CTES, PROVENANCE, _cur, _rows
from .filer_labels import (GROUP_NOTE, TYPE_EN, TYPE_NOTE, group_of, group_size,
                           type_of)

router = APIRouter(prefix="/api/v1/equity/stakes")

THRESHOLD_PCT = 5.0

CALC = {
    "ratio_change_pp": "ratio_pct − prior_ratio_pct, both as filed (percentage points)",
    "is_current": "the group's latest report shows ratio_pct >= 5",
    "activist_filings": "filings where any holder states an act under 重要提案行為等",
    "filed_date": ("the date EDINET received the document, from its own "
                   "submission record — not the date printed on the cover page, "
                   "which the filer types and occasionally gets wrong "
                   "(cover_date keeps that one)"),
    "days_to_file": ("filed_date − requirement_date, in days. NOT a lateness "
                     "measure: a change report often restates the date the "
                     "holder first crossed 5%, years earlier"),
}

TAPE_NOTE = (
    "The tape is ordered by the date each report was FILED, which is when the "
    "market could read it. The trigger date beside it is the filing's own "
    "提出義務発生日 and is shown as filed — a change report often restates the "
    "date the holder first crossed 5%, and a handful of filers mistype it "
    "outright, so ordering on it would put a typo at the top of the page.")

EVENT_NOTE = (
    "Each row is one report as filed on its own trigger date, not a running "
    "position. A holding group that drops below 5% files once more and then "
    "stops filing, so the absence of recent reports is not evidence of a "
    "position.")

GROUP_NOTE = (
    "Positions are per filing GROUP (a filer plus its joint holders). The "
    "group ratio is the filing's own, not our sum of the members: the form "
    "deducts claims between joint holders, and a member that has left the "
    "group is still described in the report with last-report figures only.")

PROPOSAL_NOTE = (
    "important_proposal is the filed answer to 重要提案行為等 — the acts under "
    "Article 27-26 that separate a campaign from a passive stake. Only the "
    "general first-schedule form asks it: the change report and the special "
    "form carry no such field, and proposal_asked is false on those. A null "
    "answer never means 'no'.")

RATIO_NOTE = (
    "ratio_pct is the statutory 株券等保有割合. Its denominator is 発行済株式等"
    "総数 plus the holder's own potential shares and its numerator excludes "
    "underwritten shares, so it does not equal shares_held / shares_outstanding; "
    "both are published as filed.")


def _require():
    cur = _cur()
    try:
        cur.execute("SELECT 1 FROM eq_lvh_filings LIMIT 1")
    except Exception:                                            # noqa: BLE001
        raise HTTPException(503, "5% filings dataset not published yet")
    return cur


def _notes(head):
    head["event_note"] = EVENT_NOTE
    head["tape_note"] = TAPE_NOTE
    head["group_note"] = GROUP_NOTE
    head["proposal_note"] = PROPOSAL_NOTE
    head["ratio_note"] = RATIO_NOTE
    head["names_note"] = NAMES_NOTE
    head["calc"] = CALC
    head["provenance"] = PROVENANCE
    return head


# The latest report per (issuer, filing group). A correction (訂正報告書,
# EDINET type 360) supersedes on the surface while both rows stay queryable —
# the same rule the rest of the platform applies to a revised vintage.
LATEST_STAKE = """
    WITH ranked AS (
        SELECT f.*, coalesce(f.issuer_sec_code, f.issuer_edinet_code,
                             f.issuer_name_raw) AS issuer_key,
               row_number() OVER (
                   PARTITION BY coalesce(f.issuer_sec_code, f.issuer_edinet_code,
                                         f.issuer_name_raw),
                                coalesce(f.filer_edinet_code, f.filer_name)
                   ORDER BY coalesce(f.requirement_date, f.filed_date) DESC,
                            f.filed_date DESC,
                            CASE WHEN f.doc_type = '360' THEN 1 ELSE 0 END DESC,
                            f.doc_id DESC) AS rn
        FROM eq_lvh_filings f
        WHERE f.status IN ('clean','partial')
    ),
    current_stakes AS (SELECT * FROM ranked WHERE rn = 1)
"""

FILING_COLS = """
        f.doc_id, f.doc_type, f.report_type, f.change_no, f.is_special_form,
        f.filer_edinet_code, f.filer_name, f.issuer_name_raw, f.issuer_sec_code,
        f.issuer_edinet_code, f.listing, f.exchange, f.requirement_date,
        f.filed_date, f.cover_date, f.holders_declared, f.holders_rows, f.shares_held,
        f.shares_outstanding, f.ratio_pct, f.prior_ratio_pct, f.ratio_change_pp,
        f.important_proposal, f.proposal_asked, f.filing_reason_ja, f.purpose_ja,
        f.own_funds_yen, f.borrowings_yen, f.funding_implausible, f.status,
        f.detail, date_diff('day', f.requirement_date, f.filed_date) AS days_to_file
"""


@router.get("/summary")
def summary():
    u"""Coverage first, then what the tape shows."""
    cur = _require()
    head = _rows(cur, """
        SELECT count(*) AS filings,
               count(DISTINCT issuer_sec_code) AS issuers,
               count(DISTINCT filer_edinet_code) AS filers,
               min(filed_date) AS earliest_filed, max(filed_date) AS latest_filed,
               min(requirement_date) AS earliest_trigger,
               max(requirement_date) AS latest_trigger,
               sum(CASE WHEN important_proposal THEN 1 ELSE 0 END) AS activist_filings,
               sum(CASE WHEN is_special_form THEN 1 ELSE 0 END) AS special_form_filings,
               median(date_diff('day', requirement_date, filed_date)) AS median_days_to_file
        FROM eq_lvh_filings WHERE status IN ('clean','partial')""")[0]
    head["by_report_type"] = _rows(cur, """
        SELECT report_type, count(*) AS n FROM eq_lvh_filings
        WHERE status IN ('clean','partial') GROUP BY 1 ORDER BY 2 DESC""")
    head["current_positions"] = _rows(cur, LATEST_STAKE + """
        SELECT count(*) AS groups,
               sum(CASE WHEN ratio_pct >= ? THEN 1 ELSE 0 END) AS at_or_above_5pct,
               count(DISTINCT issuer_key) AS issuers
        FROM current_stakes""", [THRESHOLD_PCT])[0]
    status = _rows(cur, "SELECT status, count(*) AS n FROM eq_lvh_filings GROUP BY 1")
    head["extraction_status"] = {r["status"]: r["n"] for r in status}
    head["coverage_note"] = (
        "Every archived 大量保有報告書 and 訂正報告書 is parsed. The archive "
        "reaches back only as far as the capture does — EDINET's own list API "
        "reaches about five years — so an accumulation that began earlier is "
        "visible from its first captured report onward, not from its start.")
    return _notes(head)


@router.get("/recent")
def recent(limit: int = Query(50, ge=1, le=500),
           activist: str = Query("", description="'true' for filings stating an "
                                                 "important-proposal act"),
           min_ratio: float = Query(0.0, ge=0, le=100),
           min_change: float = Query(0.0, ge=0, le=100,
                                     description="minimum absolute change in "
                                                 "percentage points"),
           report_type: str = Query("", description="initial | change | amendment")):
    u"""The tape, newest trigger date first."""
    cur = _require()
    where = ["f.status IN ('clean','partial')"]
    params = []
    if (activist or "").strip().lower() == "true":
        where.append("f.important_proposal")
    if min_ratio:
        where.append("f.ratio_pct >= ?")
        params.append(min_ratio)
    if min_change:
        where.append("abs(f.ratio_change_pp) >= ?")
        params.append(min_change)
    if report_type.strip():
        where.append("f.report_type = ?")
        params.append(report_type.strip())
    rows = _rows(cur, "WITH x AS (SELECT 1)" + NAME_CTES + """
        SELECT """ + FILING_COLS + """,
               coalesce(es.name_en, ee.name_en) AS issuer_name_en
        FROM eq_lvh_filings f
        LEFT JOIN en_scode es ON es.sec_code = f.issuer_sec_code
        LEFT JOIN en_ecode ee ON ee.edinet_code = f.issuer_edinet_code
        WHERE """ + " AND ".join(where) + """
        ORDER BY f.filed_date DESC, f.requirement_date DESC, f.doc_id DESC
        LIMIT ?""", params + [limit])
    return _notes({"filings": rows, "filters": {
        "activist": (activist or "").strip().lower() == "true",
        "min_ratio": min_ratio, "min_change": min_change,
        "report_type": report_type.strip() or None}})


@router.get("/companies")
def companies(q: str = Query("", description="issuer name or code substring")):
    u"""Search feed: issuers that at least one 5% report names."""
    cur = _require()
    like = "%" + q.strip() + "%"
    return {"companies": _rows(cur, "WITH x AS (SELECT 1)" + NAME_CTES + """
        SELECT f.issuer_sec_code AS sec_code,
               any_value(f.issuer_name_raw) AS name,
               any_value(coalesce(es.name_en, ee.name_en)) AS name_en,
               count(*) AS reports,
               count(DISTINCT coalesce(f.filer_edinet_code, f.filer_name)) AS groups,
               max(coalesce(f.requirement_date, f.filed_date)) AS latest_report,
               sum(CASE WHEN f.important_proposal THEN 1 ELSE 0 END) AS activist_reports
        FROM eq_lvh_filings f
        LEFT JOIN en_scode es ON es.sec_code = f.issuer_sec_code
        LEFT JOIN en_ecode ee ON ee.edinet_code = f.issuer_edinet_code
        WHERE f.status IN ('clean','partial') AND f.issuer_sec_code IS NOT NULL
          AND (f.issuer_sec_code LIKE ? OR f.issuer_name_raw LIKE ?
               OR lower(coalesce(es.name_en, ee.name_en, '')) LIKE lower(?))
        GROUP BY 1 ORDER BY reports DESC LIMIT 25""", [like, like, like]),
        "names_note": NAMES_NOTE}


@router.get("/company/{sec_code}")
def company(sec_code: str,
            history: int = Query(50, ge=1, le=500,
                                 description="how many past reports to return")):
    u"""Who has filed 5% on this company — the view no single filing shows."""
    cur = _require()
    code = (sec_code or "").strip()
    current = _rows(cur, LATEST_STAKE + NAME_CTES + """
        SELECT f.*, (f.ratio_pct >= ?) AS is_current,
               coalesce(es.name_en, ee.name_en) AS issuer_name_en
        FROM current_stakes f
        LEFT JOIN en_scode es ON es.sec_code = f.issuer_sec_code
        LEFT JOIN en_ecode ee ON ee.edinet_code = f.issuer_edinet_code
        WHERE f.issuer_sec_code = ? OR f.issuer_edinet_code = ?
        ORDER BY f.ratio_pct DESC NULLS LAST""", [THRESHOLD_PCT, code, code])
    if not current:
        raise HTTPException(404, "no 5% filings archived for %s" % code)
    for row in current:
        row.pop("rn", None)
        row.pop("issuer_key", None)
        row["holders"] = _rows(cur, """
            SELECT holder_no, name_raw, name_en, holder_type_ja, is_individual,
                   holder_edinet_code, holder_sec_code, match_status, shares_held,
                   ratio_pct, prior_ratio_pct, in_group_total, purpose_ja,
                   important_proposal, own_funds_yen, borrowings_yen
            FROM eq_lvh_holders WHERE doc_id = ? ORDER BY holder_no""",
            [row["doc_id"]])
    head = {"issuer_sec_code": code,
            "issuer_name": current[0]["issuer_name_raw"],
            "issuer_name_en": current[0].get("issuer_name_en"),
            "groups": current,
            "groups_at_or_above_5pct": sum(1 for r in current if r.get("is_current")),
            "combined_current_pct": round(sum(r["ratio_pct"] or 0 for r in current
                                              if r.get("is_current")), 2) or None}
    head["reports"] = _rows(cur, """
        SELECT """ + FILING_COLS + """
        FROM eq_lvh_filings f
        WHERE (f.issuer_sec_code = ? OR f.issuer_edinet_code = ?)
          AND f.status IN ('clean','partial')
        ORDER BY coalesce(f.requirement_date, f.filed_date) DESC, f.doc_id DESC
        LIMIT ?""", [code, code, history])
    head["combined_note"] = (
        "combined_current_pct adds the current groups' filed ratios. Groups "
        "file independently and their statutory denominators differ slightly, "
        "so it is an indication of how much of the register is disclosed above "
        "5%, not an exact share of the company.")
    return _notes(head)


@router.get("/holder/{key}")
def holder(key: str, limit: int = Query(200, ge=1, le=1000)):
    u"""One holder's book: every issuer it has filed on, latest position first.

    `key` is the holder's EDINET code. Joint holders are coded in the filing
    even when they never file themselves, so the code identifies a holder
    across every report it appears in — including the ones EDINET's public
    filer registry has no row for (match_status = code_not_in_registry).
    """
    cur = _require()
    k = (key or "").strip()
    rows = _rows(cur, "WITH x AS (SELECT 1)" + NAME_CTES + """
        SELECT h.name_raw, h.name_en, h.holder_edinet_code, h.business_ja,
               h.holder_type_ja, h.is_individual, f.issuer_sec_code,
               f.issuer_name_raw, coalesce(es.name_en, ee.name_en) AS issuer_name_en,
               f.report_type, f.requirement_date, f.filed_date, h.shares_held,
               h.ratio_pct, h.prior_ratio_pct, h.important_proposal, h.purpose_ja,
               f.doc_id, f.status
        FROM eq_lvh_holders h JOIN eq_lvh_filings f USING (doc_id)
        LEFT JOIN en_scode es ON es.sec_code = f.issuer_sec_code
        LEFT JOIN en_ecode ee ON ee.edinet_code = f.issuer_edinet_code
        WHERE h.holder_edinet_code = ? AND f.status IN ('clean','partial')
        ORDER BY coalesce(f.requirement_date, f.filed_date) DESC LIMIT ?""",
        [k, limit])
    if not rows:
        raise HTTPException(404, "no 5% filings archived for holder %s" % k)
    latest = {}
    for r in rows:
        latest.setdefault(r["issuer_sec_code"] or r["issuer_name_raw"], r)
    # Counted over every report this holder has filed, not the page returned:
    # an active filer has more reports than `limit`, and reporting the page
    # size as its number of issuers would understate its book.
    totals = _rows(cur, """
        SELECT count(*) AS reports,
               count(DISTINCT coalesce(f.issuer_sec_code, f.issuer_name_raw)) AS issuers
        FROM eq_lvh_holders h JOIN eq_lvh_filings f USING (doc_id)
        WHERE h.holder_edinet_code = ? AND f.status IN ('clean','partial')""", [k])[0]
    profile = _label({"holder_edinet_code": k, "name_ja": rows[0]["name_raw"],
                      "name_en": rows[0]["name_en"],
                      "business_ja": rows[0].get("business_ja"),
                      "holder_type_ja": rows[0].get("holder_type_ja"),
                      "is_individual": rows[0].get("is_individual")})
    return _notes({"holder_edinet_code": k, "name": rows[0]["name_raw"],
                   "name_en": rows[0]["name_en"],
                   "filer_type": profile["filer_type"],
                   "filer_type_en": profile["filer_type_en"],
                   "filer_type_evidence": profile["filer_type_evidence"],
                   "business_ja": rows[0].get("business_ja"),
                   "group": profile["group"],
                   "group_entities": profile["group_entities"],
                   "type_note": TYPE_NOTE, "group_note": GROUP_NOTE,
                   "issuers": totals["issuers"], "reports_total": totals["reports"],
                   "reports_returned": len(rows),
                   "current": sorted(latest.values(),
                                     key=lambda r: -(r["ratio_pct"] or 0)),
                   "reports": rows})


def _label(row):
    u"""Attach the two derived labels to one filing-entity row."""
    kind, evidence = type_of(row.get("business_ja"), row.get("is_individual"),
                             row.get("holder_type_ja"))
    row["filer_type"] = kind
    row["filer_type_en"] = TYPE_EN[kind]
    row["filer_type_evidence"] = evidence
    row["group"] = group_of(row.get("holder_edinet_code"),
                            row.get("name_en") or row.get("name_ja"))
    row["group_entities"] = group_size(row["group"]) or 1
    return row


# One row per FILING ENTITY, before any grouping. Everything the labels need
# travels with it: what the entity filed as its business, and whether the
# filing called it a person.
ENTITY_ROLLUP = """
    SELECT coalesce(h.holder_edinet_code, h.name_key) AS holder_key,
           any_value(h.holder_edinet_code) AS holder_edinet_code,
           min(h.name_raw) AS name_ja, min(h.name_en) AS name_en,
           any_value(h.holder_type_ja) AS holder_type_ja,
           any_value(h.is_individual) AS is_individual,
           max(h.business_ja) AS business_ja,
           count(*) AS reports,
           count(DISTINCT coalesce(f.issuer_sec_code, f.issuer_name_raw)) AS issuers,
           max(h.ratio_pct) AS max_ratio_pct,
           sum(CASE WHEN h.important_proposal THEN 1 ELSE 0 END) AS proposal_reports,
           max(coalesce(f.requirement_date, f.filed_date)) AS latest_report
    FROM eq_lvh_holders h JOIN eq_lvh_filings f USING (doc_id)
    WHERE {WHERE}
    GROUP BY 1
"""


@router.get("/holders")
def holders(limit: int = Query(50, ge=1, le=500),
            by: str = Query("group", description="'group' (default) consolidates "
                                                 "a family's filing entities; "
                                                 "'entity' lists them separately"),
            filer_type: str = Query("", description="one filer_type to filter to; "
                                                    "see /holder-types"),
            group: str = Query("", description="one group, to list its entities"),
            activist: str = Query("", description="'true' for holders that have "
                                                  "stated an important-proposal act")):
    u"""The most active 5% filers, by family or by filing entity.

    Grouped is the default because the alternative misleads: BlackRock files
    under sixteen EDINET codes and Fidelity thirteen, so an entity ranking puts
    nine BlackRock subsidiaries in a top twenty and reads as nine investors.
    """
    cur = _require()
    where = ["f.status IN ('clean','partial')"]
    if (activist or "").strip().lower() == "true":
        where.append("h.important_proposal")
    entities = [_label(r) for r in
                _rows(cur, ENTITY_ROLLUP.replace("{WHERE}", " AND ".join(where)))]

    wanted_type = (filer_type or "").strip()
    if wanted_type:
        entities = [e for e in entities if e["filer_type"] == wanted_type]
    wanted_group = (group or "").strip()
    if wanted_group:
        entities = [e for e in entities if e["group"] == wanted_group]

    by_entity = (by or "").strip().lower() == "entity" or bool(wanted_group)
    if by_entity:
        rows = sorted(entities, key=lambda e: (-(e["issuers"] or 0), -(e["reports"] or 0)))
    else:
        # A group's issuer count is the number of DISTINCT companies its
        # entities file on, which is not the sum of theirs: BlackRock's
        # sixteen entities file on largely the same names, and adding them
        # would report it holding 5% of more companies than exist.
        keys = [e["holder_key"] for e in entities]
        per_issuer = _issuers_by_entity(cur, where) if keys else {}
        merged = {}
        for e in entities:
            g = merged.setdefault(e["group"], {
                "group": e["group"], "entities": [], "reports": 0,
                "max_ratio_pct": None, "proposal_reports": 0,
                "latest_report": None, "issuer_set": set()})
            g["entities"].append({
                "holder_key": e["holder_key"],
                "holder_edinet_code": e["holder_edinet_code"],
                "name_ja": e["name_ja"], "name_en": e["name_en"],
                "filer_type": e["filer_type"], "filer_type_en": e["filer_type_en"],
                "issuers": e["issuers"], "reports": e["reports"],
                "max_ratio_pct": e["max_ratio_pct"],
                "proposal_reports": e["proposal_reports"]})
            g["reports"] += e["reports"] or 0
            g["proposal_reports"] += e["proposal_reports"] or 0
            if e["max_ratio_pct"] is not None:
                g["max_ratio_pct"] = max(g["max_ratio_pct"] or 0, e["max_ratio_pct"])
            if e["latest_report"] and (not g["latest_report"]
                                       or e["latest_report"] > g["latest_report"]):
                g["latest_report"] = e["latest_report"]
            g["issuer_set"] |= per_issuer.get(e["holder_key"], set())
        rows = []
        for g in merged.values():
            g["issuers"] = len(g["issuer_set"])
            g.pop("issuer_set")
            g["entity_count"] = len(g["entities"])
            # The type of a group is its entities' type where they agree, and
            # stated as mixed where they do not — a bank group that also runs
            # an asset manager is both, and picking one would be a claim.
            kinds = sorted({e["filer_type"] for e in g["entities"]})
            g["filer_type"] = kinds[0] if len(kinds) == 1 else "mixed"
            # "Mixed" is the label; WHICH kinds it mixes is detail for a
            # tooltip, not a sentence inside a badge.
            g["filer_type_en"] = TYPE_EN[kinds[0]] if len(kinds) == 1 else "Mixed"
            g["filer_type_mix"] = [TYPE_EN[k] for k in kinds]
            g["entities"].sort(key=lambda e: -(e["issuers"] or 0))
            rows.append(g)
        rows.sort(key=lambda g: (-(g["issuers"] or 0), -(g["reports"] or 0)))

    head = {"holders": rows[:limit],
            "by": "entity" if by_entity else "group",
            "filer_type": wanted_type or None,
            "group": wanted_group or None,
            "activist_only": (activist or "").strip().lower() == "true",
            "filers_total": len(entities),
            "groups_total": (None if by_entity else len(rows))}
    head["type_note"] = TYPE_NOTE
    head["group_note"] = GROUP_NOTE
    return _notes(head)


def _issuers_by_entity(cur, where):
    u"""entity key -> the set of issuers it has filed on."""
    out = {}
    for r in _rows(cur, """
            SELECT coalesce(h.holder_edinet_code, h.name_key) AS holder_key,
                   coalesce(f.issuer_sec_code, f.issuer_name_raw) AS issuer
            FROM eq_lvh_holders h JOIN eq_lvh_filings f USING (doc_id)
            WHERE """ + " AND ".join(where)):
        out.setdefault(r["holder_key"], set()).add(r["issuer"])
    return out


@router.get("/holder-types")
def holder_types():
    u"""The filer types, with how many filing entities carry each."""
    cur = _require()
    counts = {}
    for r in _rows(cur, ENTITY_ROLLUP.replace(
            "{WHERE}", "f.status IN ('clean','partial')")):
        kind, _ = type_of(r.get("business_ja"), r.get("is_individual"),
                          r.get("holder_type_ja"))
        counts[kind] = counts.get(kind, 0) + 1
    return {"types": [{"filer_type": k, "label": TYPE_EN[k], "filers": counts.get(k, 0)}
                      for k in TYPE_EN if counts.get(k)],
            "type_note": TYPE_NOTE, "calc": CALC, "provenance": PROVENANCE}
