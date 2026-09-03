# -*- coding: utf-8 -*-
u"""Equity product API — AGM voting results (臨時報告書, 株主総会決議).

What shareholders actually did, proposal by proposal and — for board elections
— director by director. Served from the same DuckDB file and reader as the
rest of the equity product.

WHAT A CONSUMER MUST NOT ASSUME, carried in the data rather than in prose:

  1. THE PERCENTAGE IS THE COMPANY'S, NOT OURS, AND CANNOT BE REBUILT FROM THE
     COUNTS. Almost every filer states that it stopped tallying attending
     votes once the outcome was settled (出席した株主の議決権の数の一部を加算
     しなかった理由), so the denominator behind 賛成割合 is never published.
     `approval_pct` is exactly as filed and carries the official badge.
     `approval_pct_of_counted` is OUR arithmetic over the disclosed counts and
     carries its formula instead; the two differ by a median of 0.14pp and
     occasionally much more. Never present the derived one as the company's.
  2. A BOARD ELECTION HAS NO PROPOSAL-LEVEL VOTE. The filing publishes one
     result per candidate and no total, so proposal-level counts are null for
     those and `candidates` says how many rows sit underneath. Summing the
     candidates would invent a figure nobody filed.
  3. VOTING RIGHTS ARE NOT SHARES. Counts are in 個 — voting-right units, one
     per trading unit — so they do not equal share counts and must not be
     compared with the shares in the 5% filings or the register.
  4. ABSENCE IS NOT DISSENT. A shareholder who did not vote appears nowhere.
     A low approval percentage means votes actively cast against, which is why
     it is a much sharper signal in Japan than a low turnout would be.
  5. A DISMISSAL VOTE READS BACKWARDS, AND IS NEVER RANKED WITH ELECTIONS.
     取締役の解任の件 asks shareholders to REMOVE a named director, so 0.5%
     approval means the attempt was crushed and the director kept the seat —
     the opposite of what the same number means under an election. Ranking the
     two together put retained directors at the top of "lowest support", which
     is a wrong number, not a presentational quibble. /directors serves
     elections by default; `kind=dismissal` serves removal votes, where a HIGH
     percentage is the adverse signal.
  6. A RANKING SHOWS ONLY ROWS WE CAN CORROBORATE. Every row is stored as
     filed, but /directors and /proposals rank only those whose filed
     percentage our own arithmetic over the disclosed counts can reproduce
     within 15pp (`pct_consistent`). Without that a single misread cell — an
     against-rate column read as an approval rate — would put a fictitious
     0.1% at the top of "lowest support" and above every genuine result.
     `include_unverified=true` returns them anyway, flagged.
  7. THE ARCHIVE STARTS IN APRIL 2024. 臨時報告書 leave EDINET's public
     inspection window far sooner than annual reports do; nothing earlier
     survived to be captured, and no back-fill can recover it.
"""
from fastapi import APIRouter, HTTPException, Query

from .equity_api import NAMES_NOTE, PROVENANCE, _cur, _rows

router = APIRouter(prefix="/api/v1/equity/agm")

CLEAN = "status IN ('clean','partial')"

CALC = {
    "approval_pct": ("as filed by the company (賛成割合). NOT recomputed — the "
                     "denominator it uses is not disclosed"),
    "approval_pct_of_counted": ("100 × 賛成 / (賛成 + 反対 + 棄権), computed by "
                                "this platform from the disclosed counts. It "
                                "differs from approval_pct because the filer "
                                "did not tally every attending vote"),
    "against_pct_of_counted": "100 × 反対 / (賛成 + 反対 + 棄権), computed by this platform",
    "dissent_pct": ("100 − approval_pct, as filed: the share of counted votes "
                    "not supporting the resolution"),
    "pct_consistent": ("whether approval_pct and approval_pct_of_counted agree "
                       "within 15 percentage points. False means this platform "
                       "could not corroborate its own reading of the filing's "
                       "table, so the row is excluded from rankings by default"),
}

KIND_NOTE = {
    "election": ("Election results only. A vote to REMOVE a director "
                 "(取締役の解任の件) is excluded here because its percentage "
                 "inverts — low approval there means the director was "
                 "retained. Those are served with kind=dismissal."),
    "dismissal": ("Votes to REMOVE a named director. Read these the other way "
                  "up: a HIGH approval percentage is the adverse signal, and a "
                  "low one means the attempt failed and the director stayed."),
    "all": ("Elections and removal votes together. Their percentages mean "
            "opposite things — check `category` on every row before comparing."),
}

VERIFY_NOTE = (
    "Rankings show only rows whose filed percentage this platform can "
    "reproduce from the counts printed beside it, within 15 percentage points. "
    "Rows that fail that check are kept in the dataset and returned by "
    "include_unverified=true, flagged — they are not deleted, because the "
    "filing says what it says.")

TALLY_NOTE = (
    "Japanese issuers routinely count advance votes plus enough of the votes "
    "in the room to settle the outcome, then stop — and disclose that they did "
    "(出席した株主の議決権の数の一部を加算しなかった理由). partial_tally flags "
    "each such filing. It means the published percentage rests on a base the "
    "filing does not state, so it can be quoted but not reconstructed.")

ELECTION_NOTE = (
    "A board election publishes one result per candidate and no figure for the "
    "proposal as a whole, so proposal-level vote counts are null for those "
    "rows and the per-director results are served from /directors.")

UNIT_NOTE = (
    "Counts are voting rights (個), one per trading unit — not shares. They are "
    "not comparable with the share counts in the 5% filings or the register.")

COVERAGE_NOTE = (
    "Built from every archived 臨時報告書 (EDINET type 180/190). That document "
    "type also carries mergers, subsidiary changes and officer changes; only "
    "the ones reporting a general meeting produce rows here, and the rest are "
    "recorded as examined-and-not-a-meeting so the count reconciles with the "
    "archive. Coverage begins in April 2024 — earlier filings had already left "
    "EDINET's public inspection window before capture began.")

COUNTED = "(for_votes + coalesce(against_votes,0) + coalesce(abstain_votes,0))"
PCT_OF_COUNTED = ("CASE WHEN %s > 0 THEN round(100.0 * for_votes / %s, 2) END"
                  % (COUNTED, COUNTED))


def _notes(head):
    head["verification_note"] = VERIFY_NOTE
    head["tally_note"] = TALLY_NOTE
    head["election_note"] = ELECTION_NOTE
    head["unit_note"] = UNIT_NOTE
    head["names_note"] = NAMES_NOTE
    head["calc"] = CALC
    head["provenance"] = PROVENANCE
    return head


def _require():
    cur = _cur()
    names = {r[0] for r in cur.execute(
        "SELECT table_name FROM duckdb_tables()").fetchall()}
    if "eq_agm_meetings" not in names:
        raise HTTPException(503, "AGM voting results not published yet")
    return cur


@router.get("/summary")
def summary():
    u"""Coverage first, then what the votes show."""
    cur = _require()
    head = _rows(cur, """
        SELECT count(*) AS meetings,
               count(DISTINCT issuer_sec_code) AS companies,
               min(meeting_date) AS earliest_meeting,
               max(meeting_date) AS latest_meeting,
               sum(CASE WHEN partial_tally THEN 1 ELSE 0 END) AS partial_tally_filings
        FROM eq_agm_meetings WHERE %s""" % CLEAN)[0]
    head["proposals"] = _rows(cur,
        "SELECT count(*) AS n FROM eq_agm_proposals")[0]["n"]
    head["director_results"] = _rows(cur,
        "SELECT count(*) AS n FROM eq_agm_votes")[0]["n"]
    head["by_category"] = _rows(cur, """
        SELECT category, count(*) AS n,
               round(median(approval_pct_filed), 2) AS median_approval_pct
        FROM eq_agm_proposals GROUP BY 1 ORDER BY 2 DESC""")
    head["director_approval"] = _rows(cur, """
        SELECT count(*) AS results,
               round(median(approval_pct_filed), 2) AS median_pct,
               sum(CASE WHEN approval_pct_filed < 80 THEN 1 ELSE 0 END) AS below_80,
               sum(CASE WHEN approval_pct_filed < 70 THEN 1 ELSE 0 END) AS below_70,
               sum(CASE WHEN approval_pct_filed < 50 THEN 1 ELSE 0 END) AS below_50
        FROM eq_agm_votes WHERE approval_pct_filed IS NOT NULL
                                  AND pct_consistent""")[0]
    # The shape of the dataset in one object: almost every director clears 90%,
    # and the whole interest is in the tail. Bucketed in SQL so the page never
    # has to pull every row to draw it.
    head["approval_distribution"] = _rows(cur, """
        SELECT CASE
                 WHEN approval_pct_filed < 50 THEN 'under 50'
                 WHEN approval_pct_filed < 60 THEN '50-60'
                 WHEN approval_pct_filed < 70 THEN '60-70'
                 WHEN approval_pct_filed < 80 THEN '70-80'
                 WHEN approval_pct_filed < 90 THEN '80-90'
                 WHEN approval_pct_filed < 95 THEN '90-95'
                 ELSE '95-100' END AS bucket,
               min(approval_pct_filed) AS lo,
               count(*) AS n
        FROM eq_agm_votes WHERE approval_pct_filed IS NOT NULL
                                  AND pct_consistent
        GROUP BY 1 ORDER BY lo""")
    head["shareholder_proposals"] = _rows(cur, """
        SELECT count(*) AS n,
               sum(CASE WHEN result = '否決' THEN 1 ELSE 0 END) AS rejected
        FROM eq_agm_proposals WHERE shareholder_proposal""")[0]
    status = _rows(cur, "SELECT status, count(*) AS n FROM eq_agm_meetings GROUP BY 1")
    head["extraction_status"] = {r["status"]: r["n"] for r in status}
    head["coverage_note"] = COVERAGE_NOTE
    return _notes(head)


@router.get("/directors")
def directors(limit: int = Query(50, ge=1, le=500),
              order: str = Query("lowest", description="'lowest' or 'highest' approval"),
              max_pct: float = Query(100.0, ge=0, le=100),
              sec_code: str = Query("", description="restrict to one issuer"),
              year: int = Query(0, description="meeting calendar year"),
              kind: str = Query("election", description="'election', 'dismissal' or 'all'"),
              include_unverified: str = Query("", description="'true' to include "
                                              "rows this platform could not corroborate")):
    u"""Named directors by the support they actually received.

    The lowest end is the point of the dataset: a director returned on 62% has
    a mandate problem that no other public dataset in Japan will tell you
    about, and the same name can be looked up across companies and years.
    """
    cur = _require()
    where = ["v.approval_pct_filed IS NOT NULL", "v.approval_pct_filed <= ?"]
    params = [max_pct]
    if include_unverified.lower() not in ("1", "true", "yes"):
        where.append("v.pct_consistent")
    kind = kind if kind in KIND_NOTE else "election"
    if kind == "election":
        where.append("(p.category IS NULL OR p.category <> 'dismissal')")
    elif kind == "dismissal":
        where.append("p.category = 'dismissal'")
    if sec_code:
        where.append("m.issuer_sec_code = ?")
        params.append(sec_code[:4])
    if year:
        where.append("year(m.meeting_date) = ?")
        params.append(year)
    params.append(limit)
    direction = "ASC" if order == "lowest" else "DESC"
    rows = _rows(cur, """
        SELECT m.issuer_sec_code AS sec_code, m.issuer_name, m.meeting_date,
               p.label AS proposal, p.category, p.shareholder_proposal,
               v.candidate_name, v.for_votes, v.against_votes, v.abstain_votes,
               v.approval_pct_filed AS approval_pct,
               %s AS approval_pct_of_counted,
               v.result, v.pct_consistent, m.partial_tally, m.doc_id
        FROM eq_agm_votes v
        JOIN eq_agm_meetings m USING (doc_id)
        LEFT JOIN eq_agm_proposals p
               ON p.doc_id = v.doc_id AND p.seq = v.proposal_seq
        WHERE %s AND %s
        ORDER BY v.approval_pct_filed %s, v.for_votes DESC
        LIMIT ?""" % (PCT_OF_COUNTED.replace("for_votes", "v.for_votes")
                                    .replace("against_votes", "v.against_votes")
                                    .replace("abstain_votes", "v.abstain_votes"),
                      " AND ".join(where), CLEAN.replace("status", "m.status"),
                      direction), params)
    return _notes({"order": order, "kind": kind, "kind_note": KIND_NOTE[kind],
                   "rows": rows,
                   "cite": "/agm.html?order=%s&kind=%s&limit=%d" % (order, kind, limit)})


@router.get("/proposals")
def proposals(category: str = Query("", description="e.g. takeover_defence"),
              shareholder: str = Query("", description="'true' for shareholder proposals"),
              limit: int = Query(50, ge=1, le=500),
              include_unverified: str = Query("", description="'true' to include "
                                              "rows this platform could not corroborate")):
    u"""Proposals, filterable to the ones worth arguing about."""
    cur = _require()
    where = ["1=1"]
    params = []
    if category:
        where.append("p.category = ?")
        params.append(category)
    if shareholder.lower() in ("1", "true", "yes"):
        where.append("p.shareholder_proposal")
    if include_unverified.lower() not in ("1", "true", "yes"):
        where.append("(p.pct_consistent OR p.approval_pct_filed IS NULL)")
    params.append(limit)
    rows = _rows(cur, """
        SELECT m.issuer_sec_code AS sec_code, m.issuer_name, m.meeting_date,
               p.proposal_no, p.label, p.category, p.shareholder_proposal,
               p.for_votes, p.against_votes, p.abstain_votes,
               p.approval_pct_filed AS approval_pct,
               %s AS approval_pct_of_counted,
               p.result, p.candidates, p.pct_consistent, m.partial_tally, m.doc_id
        FROM eq_agm_proposals p
        JOIN eq_agm_meetings m USING (doc_id)
        WHERE %s AND %s
        ORDER BY m.meeting_date DESC, p.seq
        LIMIT ?""" % (PCT_OF_COUNTED.replace("for_votes", "p.for_votes")
                                    .replace("against_votes", "p.against_votes")
                                    .replace("abstain_votes", "p.abstain_votes"),
                      " AND ".join(where), CLEAN.replace("status", "m.status")),
        params)
    return _notes({"category": category or None, "rows": rows,
                   "cite": "/agm.html?category=%s" % category})


@router.get("/company/{sec_code}")
def company(sec_code: str):
    u"""Every meeting we hold for one issuer, with its proposals and directors."""
    cur = _require()
    code = sec_code[:4]
    meetings = _rows(cur, """
        SELECT doc_id, meeting_date, meeting_type, issuer_name, issuer_sec_code,
               proposals, candidates, partial_tally, partial_tally_reason, status
        FROM eq_agm_meetings
        WHERE issuer_sec_code = ? AND %s
        ORDER BY meeting_date DESC""" % CLEAN, [code])
    if not meetings:
        raise HTTPException(404, "no AGM voting results for %s" % code)
    ids = [m["doc_id"] for m in meetings]
    ph = ",".join(["?"] * len(ids))
    props = _rows(cur, """
        SELECT doc_id, seq, proposal_no, label, category, shareholder_proposal,
               for_votes, against_votes, abstain_votes,
               approval_pct_filed AS approval_pct, result, candidates
        FROM eq_agm_proposals WHERE doc_id IN (%s) ORDER BY doc_id, seq""" % ph, ids)
    votes = _rows(cur, """
        SELECT doc_id, proposal_seq, candidate_name, for_votes, against_votes,
               abstain_votes, approval_pct_filed AS approval_pct, result
        FROM eq_agm_votes WHERE doc_id IN (%s) ORDER BY doc_id, seq""" % ph, ids)
    by_doc = {}
    for p in props:
        by_doc.setdefault(p["doc_id"], []).append(dict(p, directors=[]))
    for v in votes:
        for p in by_doc.get(v["doc_id"], []):
            if p["seq"] == v["proposal_seq"]:
                p["directors"].append(v)
                break
    for m in meetings:
        m["proposal_rows"] = by_doc.get(m["doc_id"], [])
    return _notes({"sec_code": code, "name": meetings[0]["issuer_name"],
                   "meetings": meetings,
                   "cite": "/agm.html?company=%s" % code})
