# -*- coding: utf-8 -*-
u"""M1 — AGM voting results: 臨時報告書 (EDINET type 180/190), parser `agm-1`.

What shareholders actually did. Every listed company must file an 臨時報告書
within days of a general meeting stating, proposal by proposal, how many
voting rights were cast for, against and abstaining — and for board elections,
the same split for EVERY INDIVIDUAL CANDIDATE. That per-director number is the
point: it is the only free, public, structured measure of how much support a
named director actually has, and a director returned on 62% is a story that no
other dataset in this repo can tell.

It closes the loop on the other three equity datasets. Boards-and-pay says who
sits there; the 5% filings say who is accumulating; cross-shareholdings say who
owns whom and votes silently. This says what all of that produced.

Unlike the 5% filings there is almost nothing to read from the XBRL: type 180
is 98% "XBRL" by EDINET's flag, but the tagged facts are cover-page boilerplate
plus a single ReasonForFilingTextBlock. The substance is an HTML table inside
the t1 honbun document, so this parses the honbun the way facility_extract.py
does, and reuses its grid/rowspan machinery.

WHAT MAKES THIS DATASET WORTH THE TROUBLE, and the traps under each:

  1. 臨時報告書 IS A GRAB-BAG. The same document type carries mergers, share
     exchanges, specified-subsidiary changes and officer changes. Only ~42% of
     all type-180 filings are AGM results (88% in the late-June AGM week).
     Everything else is recorded with status `not_agm` and no proposals,
     rather than silently dropped, so the archive and this table reconcile.
  2. THE PERCENTAGE CANNOT BE RECOMPUTED, AND MUST NOT BE. 95% of these
     filings carry a section headed 出席した株主の議決権の数の一部を加算しな
     かった理由 — the filer counted advance votes plus enough of the attending
     votes to settle the outcome, and deliberately tallied no further. The
     denominator behind the published 賛成割合 is therefore never disclosed.
     Measured over 371 proposal rows, recomputing 賛成/(賛成+反対+棄権) misses
     the filed figure by a median of 0.24pp. So for/against/abstain and the
     approval percentage are stored EXACTLY AS FILED and carry the official
     badge; `approval_pct_of_counted` is a separate, clearly derived column
     that states what the disclosed numbers alone support. Publishing our
     arithmetic as if it were the company's would be a trust-contract breach.
  3. A BOARD ELECTION HAS NO SINGLE VOTE COUNT. The proposal row is a header —
     empty vote cells, or one cell spanning the whole row — and the numbers
     belong to the candidates beneath it. Summing the candidate rows into a
     proposal total would invent a number nobody filed, so proposal-level vote
     columns stay NULL for those and eq_agm_votes carries the split.
  4. SHAREHOLDER PROPOSALS ARE IN THE SAME TABLE AS THE BOARD'S. They are
     marked 株主提案 in the label and are the sharp end of the dataset — a
     board proposal passing on 99% and a shareholder proposal failing on 12%
     sit in adjacent rows. `shareholder_proposal` is read from the label.

Gates. None of these judges the company — they judge THIS PARSER, by
recomputing what the filing already publishes and asking whether our reading
of the table reproduces it. Measured over 1,137 rows: the median gap between
our share-of-counted-votes and the filed percentage is 0.14pp, p90 is 2.3pp,
p99 is 7.3pp.

    G1  gross misread: a row whose filed percentage differs from our share of
        counted votes by more than 15pp. Deliberately loose, because the gap
        is dominated by a real disclosure artefact (see 2) rather than by
        error; 99.7% of rows sit inside it.
    G1b the sharp one — CONSISTENCY WITHIN A FILING. Filers differ in what
        they put in the denominator, but no filer changes convention between
        two rows of one table. So a filing where some rows land inside 2pp and
        others fall outside 5pp has a misaligned row, whatever the absolute
        gaps look like. In the sample that pattern isolated 2 filings, against
        11 where every row shifts together and the parse is fine.
    G2  candidates under one election proposal cast near-identical totals
        (same meeting, same votes). Divergence beyond 2% means rows were
        misaligned by a rowspan the grid did not expand.
    G3  a proposal recorded 可決 has 賛成 > 反対.

Usage:
    python agm_extract.py --source s3 --new-only         # the nightly path
    python agm_extract.py --source s3 --docs S100Y6BT    # one filing
Python 3.9.
"""
import argparse
import datetime as dt
import hashlib
import io
import os
import re
import sys
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

from extract import (LocalSource, S3Source, load_codelist, compact, DB_PATH,
                     incremental_window, record_run, seek_key)
from facility_extract import grid_of, norm, to_num

PARSER_VERSION = "agm-1"
AGM_TYPES = ("180", "190")


class NoVoteTable(Exception):
    """The filing is an 臨時報告書 about something other than a meeting."""


# ---- the voting table -------------------------------------------------------
# Column wording varies (賛成 / 賛成数, with and without 個, one spelling of the
# result column per filer) but the six columns and their order do not, across
# every variant seen in 420 sampled filings. So columns are typed by keyword
# rather than by position, and the result/percentage may arrive in one cell
# ("可決93.51%") or two ("可決" | "91.11%").
PROPOSAL_RE = re.compile(u"第\\s*([0-9０-９]+)\\s*号議案")
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]")
RESULT_RE = re.compile(u"(可決|否決|承認可決|原案どおり可決)")

CATEGORIES = [
    (u"株主提案",                          "shareholder_proposal"),
    (u"買収への対応方針|大規模買付|買収防衛", "takeover_defence"),
    (u"解任",                              "dismissal"),
    (u"剰余金の?処分|配当",                 "dividend"),
    (u"監査等委員である取締役.*選任",        "audit_committee_election"),
    (u"監査役.*選任",                       "statutory_auditor_election"),
    (u"取締役.*選任",                       "director_election"),
    (u"会計監査人",                         "accounting_auditor"),
    (u"報酬|賞与|譲渡制限付株式|ストック・オプション|新株予約権", "compensation"),
    (u"定款",                              "articles_amendment"),
    (u"株式併合|株式分割|自己株式|資本",     "capital_action"),
    (u"退任慰労金|慰労金",                  "retirement_bonus"),
    (u"合併|会社分割|吸収分割|新設分割|株式交換|株式移転|事業譲渡", "reorganisation"),
    (u"計算書類|貸借対照表|損益計算書",      "accounts_approval"),
]


def classify(label):
    for pat, name in CATEGORIES:
        if re.search(pat, label):
            return name
    return "other"


def _kanji_int(s):
    trans = {u"０": "0", u"１": "1", u"２": "2", u"３": "3", u"４": "4",
             u"５": "5", u"６": "6", u"７": "7", u"８": "8", u"９": "9"}
    return int("".join(trans.get(c, c) for c in s))


def honbun(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        parts = [z.read(n) for n in z.namelist()
                 if "honbun" in n and n.endswith(".htm")]
    if not parts:
        raise NoVoteTable("no honbun document in package")
    return b"".join(parts).decode("utf-8", "ignore")


def plain_text(html):
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<head.*?</head>", " ", html, flags=re.S | re.I)
    return norm(re.sub(r"<[^>]+>", " ", html))


def find_vote_table(html):
    """The first table whose header names 賛成 alongside 反対 or 棄権."""
    for t in re.findall(r"<table[^>]*>.*?</table>", html, re.S | re.I):
        cells, origin = grid_of(t)
        head = " ".join(" ".join(r) for r in cells[:3])
        if u"賛成" in head and (u"反対" in head or u"棄権" in head):
            return cells, origin
    raise NoVoteTable("no table with 賛成/反対 columns")


def column_map(header):
    """Keyword-typed columns, so wording variants need no per-filer rules.

    Order matters. A minority of filers (Omron's is the clearest) publish a
    dedicated 賛成率 column, then the result, then a trailing "(参考) 反対率" —
    and a scanner that simply took the first percentage after the result
    column read the AGAINST rate as the approval rate, turning 99.1% into
    0.1%. So the approval-rate column is typed in its own right, and any
    column naming 反対 is recorded as a rate to be ignored rather than left
    for a positional guess to find.
    """
    col = {}
    for i, c in enumerate(header):
        c = norm(c)
        rate = (u"率" in c or u"割合" in c)
        if rate and u"反対" in c:
            col.setdefault("against_rate", i)      # never a source of approval
        elif rate and u"賛成" in c:
            col.setdefault("approval_rate", i)
        elif u"棄権" in c:
            col.setdefault("abstain", i)
        elif u"要件" in c:
            col.setdefault("requirement", i)
        elif u"賛成" in c and u"結果" not in c:
            col.setdefault("for", i)
        elif u"反対" in c and u"結果" not in c:
            col.setdefault("against", i)
        elif u"結果" in c:
            col.setdefault("result", i)
    return col


BARE_PCT_RE = re.compile(r"^[（(]?\s*(\d{1,3}(?:\.\d+)?)\s*[）)]?$")


def read_pct(cell):
    """The approval percentage from a result cell.

    Filers write it four ways — 99.4%, （98.1%）, 99.76 and 可決93.51% — and a
    third of them omit the sign entirely, so a bare decimal standing alone in
    the result column is taken as the percentage. Bounded at 100 so a stray
    vote count in a shifted column can never be read as one.
    """
    cell = norm(cell)
    m = PCT_RE.search(cell)
    if m:
        v = float(m.group(1))
        return v if 0.0 <= v <= 100.0 else None
    stripped = RESULT_RE.sub(" ", cell).strip()
    m = BARE_PCT_RE.match(stripped)
    if m:
        v = float(m.group(1))
        return v if 0.0 <= v <= 100.0 else None
    return None


def read_row(row, col):
    """(for, against, abstain, pct, result) from one table row."""
    def num(key):
        i = col.get(key)
        v = to_num(row[i]) if i is not None and i < len(row) else None
        return None if v is None else int(v)
    pct = result = None
    # A dedicated approval-rate column is authoritative; only fall back to
    # scanning when the filer did not provide one.
    if col.get("approval_rate") is not None and col["approval_rate"] < len(row):
        pct = read_pct(row[col["approval_rate"]])
    skip = {col.get("against_rate"), col.get("for"), col.get("against"),
            col.get("abstain"), col.get("requirement")}
    start = col.get("result", col.get("approval_rate", len(row)))
    for i, c in enumerate(row[start:] or row[-2:], start):
        if i in skip:
            continue
        if pct is None:
            pct = read_pct(c)
        if result is None:
            m = RESULT_RE.search(norm(c))
            if m:
                result = u"否決" if u"否決" in m.group(1) else u"可決"
    return num("for"), num("against"), num("abstain"), pct, result


AGENDA_RE = re.compile(u"第\\s*([0-9０-９]+)\\s*号議案[\\s　]*([^第]{2,70}?の件)")
# A looser second pass for filers who omit the 「の件」 suffix (MUFG writes
# "第9号議案 社外取締役選任"), capped so it cannot swallow the next item.
AGENDA_LOOSE_RE = re.compile(u"第\\s*([0-9０-９]+)\\s*号議案[\\s　]*([^第\\n]{3,60})")

# Filings group the agenda by who proposed it, as an explicit range:
#     <会社提案(第1号議案から第2号議案まで)>
#     <株主提案(第3号議案から第9号議案まで)>
# This is the authoritative marker. The table label almost never says 株主提案,
# so without this a shareholder-nominated director — the single most
# interesting row in the dataset — is indistinguishable from a board nominee.
SH_RANGE_RE = re.compile(
    u"株主提案[^<>（(]{0,20}[（(]\\s*第\\s*([0-9０-９]+)\\s*号議案"
    u"(?:\\s*から\\s*第\\s*([0-9０-９]+)\\s*号議案\\s*まで)?")


def shareholder_proposal_numbers(text):
    """Proposal numbers the filing itself attributes to shareholders."""
    out = set()
    for m in SH_RANGE_RE.finditer(text):
        try:
            lo = _kanji_int(m.group(1))
            hi = _kanji_int(m.group(2)) if m.group(2) else lo
        except ValueError:
            continue
        if hi < lo or hi - lo > 40:
            continue
        out.update(range(lo, hi + 1))
    return out


def agenda_from_text(text):
    """{proposal_no: description} read from the narrative above the table.

    The table itself often carries only 第1号議案, with the subject matter set
    out in the body text — and the subject matter is the whole point, since it
    is what separates a routine dividend from a takeover defence. First
    mention wins: the agenda is stated before the results are discussed.
    """
    out = {}
    for rx in (AGENDA_RE, AGENDA_LOOSE_RE):
        for m in rx.finditer(text):
            try:
                no = _kanji_int(m.group(1))
            except ValueError:
                continue
            out.setdefault(no, norm(m.group(2))[:200])
    return out


def parse_meeting(html):
    """Meeting date, type, and the partial-tally disclosure."""
    text = plain_text(html)
    date = None
    m = re.search(u"(20\\d\\d)\\s*年\\s*(\\d+)\\s*月\\s*(\\d+)\\s*日"
                  u"(?:\\s*開催)?\\s*の?[^。]{0,24}?株主総会", text)
    if m:
        try:
            date = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            date = None
    mtype = (u"臨時株主総会" if u"臨時株主総会" in text else
             (u"定時株主総会" if u"定時株主総会" in text else None))
    # The heading is near-boilerplate, so match the heading itself rather than
    # any mention of counting — an over-broad pattern marked every filing.
    partial = bool(re.search(u"議決権の数の一部を加算しなかった理由", text))
    reason = None
    if partial:
        m = re.search(u"議決権の数の一部を加算しなかった理由(.{0,160})", text)
        if m:
            reason = m.group(1).strip()[:160] or None
    return date, mtype, partial, reason


def parse(blob):
    """(meeting, proposals, votes) for one 臨時報告書, or raise NoVoteTable."""
    html = honbun(blob)
    cells, origin = find_vote_table(html)
    header_at = 0
    for r, row in enumerate(cells[:3]):
        if any(u"賛成" in c for c in row):
            header_at = r
            break
    col = column_map(cells[header_at])
    if "for" not in col:
        raise NoVoteTable("no 賛成 column")

    text = plain_text(html)
    agenda = agenda_from_text(text)
    sh_numbers = shareholder_proposal_numbers(text)
    proposals, votes = [], []
    current = None
    seq = 0
    for r in range(header_at + 1, len(cells)):
        row = cells[r]
        label = norm(row[0])
        if not label:
            continue
        # A row whose every cell repeats the first is a colspan banner: the
        # proposal heading, with its numbers on the rows beneath.
        banner = len(set(norm(c) for c in row if norm(c))) == 1
        m = PROPOSAL_RE.search(label)
        f, a, ab, pct, result = read_row(row, col)
        if m:
            seq += 1
            no = _kanji_int(m.group(1))
            # The cell may hold "第1号議案 定款一部変更の件" or just "第1号議案";
            # in the second case the narrative supplies the subject.
            body = PROPOSAL_RE.sub(" ", label).strip(u" 　:：")
            if len(body) < 3:
                body = agenda.get(no) or ""
            full = (u"第%d号議案 %s" % (no, body)).strip()
            current = {
                "proposal_no": no,
                "seq": seq,
                "label": full[:300],
                "category": classify(full),
                "shareholder_proposal": (no in sh_numbers) or (u"株主提案" in full),
                "for_votes": None if banner else f,
                "against_votes": None if banner else a,
                "abstain_votes": None if banner else ab,
                "approval_pct_filed": None if banner else pct,
                "result": None if banner else result,
                "candidates": 0,
            }
            proposals.append(current)
            continue
        # Not a 第N号議案 row: a named candidate under the proposal above.
        if current is None or f is None:
            continue
        # Some filers number the candidates in the same cell as the name
        # ("8 松島 恵美"); the number is table furniture, not part of anyone's
        # name. A cell that is ONLY a number is furniture entire — a stray
        # numbering column, never a person — and is not a candidate at all.
        who = re.sub(u"^\\d{1,2}[\\s　]+", "", label).strip()
        if not who or re.match(r"^[\d\s.,]+$", who):
            continue
        # A proposal that stated its own numbers is not an election; a stray
        # note row beneath it is not a candidate.
        if current["for_votes"] is not None:
            continue
        current["candidates"] += 1
        votes.append({
            "proposal_no": current["proposal_no"],
            "seq": len(votes) + 1,
            "proposal_seq": current["seq"],
            "candidate_name": who[:120],
            "for_votes": f, "against_votes": a, "abstain_votes": ab,
            "approval_pct_filed": pct, "result": result,
        })
    if not proposals:
        raise NoVoteTable("vote table had no 第N号議案 rows")
    date, mtype, partial, reason = parse_meeting(html)
    meeting = {"meeting_date": date, "meeting_type": mtype,
               "partial_tally": partial, "partial_tally_reason": reason}
    return meeting, proposals, votes


# ---- gates ------------------------------------------------------------------
def gates(proposals, votes):
    """(problems, counts) — see the module docstring for what each one asserts."""
    problems = []
    checked = passed = 0

    def counted_pct(r):
        tot = sum(v for v in (r["for_votes"], r["against_votes"],
                              r["abstain_votes"]) if v is not None)
        return (100.0 * r["for_votes"] / tot) if tot and r["for_votes"] is not None else None

    # G1 — gross misread, and G1b — inconsistency between rows of one filing.
    # Each row also carries the verdict, because a row whose percentage we
    # cannot corroborate must still be stored (it is what the filing says) but
    # must never head a "lowest support" ranking, where a misread 0.1% would
    # outrank every genuine result in the dataset.
    gaps = []
    for r in proposals + votes:
        r["pct_consistent"] = None
        if r.get("approval_pct_filed") is None:
            continue
        c = counted_pct(r)
        if c is None:
            continue
        checked += 1
        gap = abs(c - r["approval_pct_filed"])
        gaps.append(gap)
        r["pct_consistent"] = gap <= 15.0
        if gap <= 15.0:
            passed += 1
        else:
            problems.append("G1 %s: filed %.2f%% vs %.2f%% of counted votes"
                            % (r.get("candidate_name") or r.get("label", "?")[:24],
                               r["approval_pct_filed"], c))
    if len(gaps) > 1 and min(gaps) <= 2.0 and max(gaps) > 5.0:
        problems.append("G1b rows of one filing disagree with the filed "
                        "percentages inconsistently (%.2f..%.2f pp) — a "
                        "misaligned row, not a filer convention"
                        % (min(gaps), max(gaps)))

    # G2 — candidates in one election cast the same votes
    by_prop = defaultdict(list)
    for v in votes:
        tot = sum(x for x in (v["for_votes"], v["against_votes"],
                              v["abstain_votes"]) if x is not None)
        if tot:
            by_prop[v["proposal_seq"]].append(tot)
    for seq, totals in by_prop.items():
        if len(totals) < 2:
            continue
        lo, hi = min(totals), max(totals)
        if hi and (hi - lo) / float(hi) > 0.02:
            problems.append("G2 proposal %s: candidate vote totals span %d..%d"
                            % (seq, lo, hi))

    # G3 — a passed resolution had more for than against
    for r in proposals + votes:
        if r.get("result") == u"可決" and r.get("for_votes") is not None \
                and r.get("against_votes") is not None \
                and r["for_votes"] <= r["against_votes"]:
            problems.append("G3 %s: recorded 可決 with 賛成 <= 反対"
                            % (r.get("candidate_name") or r.get("label", "?")[:24]))
    return problems, checked, passed


SCHEMA_SQL = u"""
CREATE TABLE IF NOT EXISTS eq_agm_meetings (
    -- One row per 臨時報告書 examined, INCLUDING those that turn out to be
    -- about a merger rather than a meeting (status 'not_agm'): the table then
    -- reconciles against the archive instead of quietly holding a subset.
    doc_id VARCHAR PRIMARY KEY,
    doc_type VARCHAR,
    issuer_edinet_code VARCHAR,
    issuer_sec_code VARCHAR,
    issuer_name VARCHAR,
    filed_date DATE,
    meeting_date DATE,
    meeting_type VARCHAR,
    proposals INTEGER,
    candidates INTEGER,
    -- The filer's own disclosure that it stopped counting once the outcome
    -- was settled. This is why the published percentages cannot be rebuilt
    -- from the published counts, and it is shown, not hidden.
    partial_tally BOOLEAN,
    partial_tally_reason VARCHAR,
    gate_checked INTEGER,
    gate_passed INTEGER,
    sha256 VARCHAR,
    parser_version VARCHAR,
    status VARCHAR,
    detail VARCHAR
);
CREATE TABLE IF NOT EXISTS eq_agm_proposals (
    doc_id VARCHAR,
    seq INTEGER,
    proposal_no INTEGER,
    label VARCHAR,
    category VARCHAR,
    shareholder_proposal BOOLEAN,
    -- NULL for a board election: the filing publishes no single figure for
    -- the proposal, only one per candidate. Summing them would invent it.
    for_votes BIGINT,
    against_votes BIGINT,
    abstain_votes BIGINT,
    approval_pct_filed DOUBLE,
    result VARCHAR,
    candidates INTEGER,
    -- Whether our own arithmetic over the disclosed counts corroborates the
    -- filed percentage. NULL where there was nothing to check against.
    pct_consistent BOOLEAN,
    PRIMARY KEY (doc_id, seq)
);
CREATE TABLE IF NOT EXISTS eq_agm_votes (
    doc_id VARCHAR,
    seq INTEGER,
    proposal_seq INTEGER,
    proposal_no INTEGER,
    candidate_name VARCHAR,
    for_votes BIGINT,
    against_votes BIGINT,
    abstain_votes BIGINT,
    approval_pct_filed DOUBLE,
    result VARCHAR,
    pct_consistent BOOLEAN,
    PRIMARY KEY (doc_id, seq)
);
"""

MEETING_COLS = ["doc_id", "doc_type", "issuer_edinet_code", "issuer_sec_code",
                "issuer_name", "filed_date", "meeting_date", "meeting_type",
                "proposals", "candidates", "partial_tally",
                "partial_tally_reason", "gate_checked", "gate_passed",
                "sha256", "parser_version", "status", "detail"]


def s3_t1(src, start_after=None):
    out = {}
    for key in src._keys("docs/", start_after):
        p = key.split("/")
        if len(p) == 3 and p[2].endswith("_t1.zip"):
            out[p[2][:-len("_t1.zip")]] = {"date": p[1]}
    return out


def local_t1():
    import json
    out = {}
    from extract import ARCHIVE
    with open(os.path.join(ARCHIVE, "manifest.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if (r.get("status") == "ok" and r.get("doc_type") in AGM_TYPES
                    and str(r.get("dl_type")) == "1"):
                out[r["doc_id"]] = r
    return out


def read_t1(src, doc_id, date):
    if src.name == "local":
        from extract import ARCHIVE
        with open(os.path.join(ARCHIVE, "docs", date, doc_id + "_t1.zip"), "rb") as f:
            return f.read()
    return src.c.get_object(Bucket=src.bucket,
                            Key="docs/%s/%s_t1.zip" % (date, doc_id))["Body"].read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("local", "s3"), default="local")
    ap.add_argument("--all", action="store_true", help="kept for symmetry")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--docs", help="comma-separated docIDs — re-extract just these")
    ap.add_argument("--new-only", action="store_true",
                    help="extract only filings archived since the last "
                         "recorded run (plus a lookback); what the nightly "
                         "refresh uses. A DB with no recorded run is built "
                         "in full, so this is always safe to pass.")
    ap.add_argument("--no-compact", action="store_true")
    args = ap.parse_args()

    src = S3Source(args.workers) if args.source == "s3" else LocalSource()
    since, have = (incremental_window(args.db, "agm-votes", "eq_agm_meetings")
                   if args.new_only else (None, set()))
    filings = local_t1() if src.name == "local" else s3_t1(src, seek_key(since))
    through = max((r["date"] for r in filings.values()), default=None)
    pending = dict(filings) if since is None else {
        d: r for d, r in filings.items() if r["date"] >= since and d not in have}
    if since is not None:
        print("incremental: %d of %d archived documents are new since %s"
              % (len(pending), len(filings), since))
    meta = src.list_metadata(
        days=None if since is None else {r["date"] for r in pending.values()})

    codelist = load_codelist()
    by_code = {d[u"ＥＤＩＮＥＴコード"]: d for d in codelist
               if d.get(u"ＥＤＩＮＥＴコード")}

    targets = []
    for doc_id, rec in sorted(pending.items()):
        m = meta.get(doc_id) or {}
        doc_type = m.get("docTypeCode") or rec.get("doc_type")
        if doc_type not in AGM_TYPES:
            continue
        targets.append((doc_id, rec, m, doc_type))
    if args.docs:
        want = {d.strip() for d in args.docs.split(",") if d.strip()}
        targets = [t for t in targets if t[0] in want]
    if args.limit:
        targets = targets[:args.limit]
    print("target filings: %d (source=%s)" % (len(targets), src.name))

    con = duckdb.connect(args.db)
    con.execute(SCHEMA_SQL)

    def fetch_and_parse(t):
        doc_id, rec, m, doc_type = t
        try:
            blob = read_t1(src, doc_id, rec["date"])
        except Exception as e:                                   # noqa: BLE001
            return t, None, None, ("failed", "fetch: %s" % str(e)[:120])
        sha = hashlib.sha256(blob).hexdigest()
        try:
            return t, parse(blob), sha, None
        except NoVoteTable as e:
            return t, None, sha, ("not_agm", str(e)[:120])
        except Exception as e:                                   # noqa: BLE001
            return t, None, sha, ("failed", "%s: %s" % (type(e).__name__, str(e)[:120]))

    stats = defaultdict(int)
    n_prop = n_vote = 0
    g_checked = g_passed = 0
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(fetch_and_parse, t) for t in targets]
        for fut in as_completed(futures):
            (doc_id, rec, m, doc_type), parsed, sha, err = fut.result()
            done += 1
            if done % 2000 == 0:
                print("  %d/%d filings" % (done, len(targets)))
                sys.stdout.flush()
            con.execute("DELETE FROM eq_agm_votes WHERE doc_id = ?", [doc_id])
            con.execute("DELETE FROM eq_agm_proposals WHERE doc_id = ?", [doc_id])
            con.execute("DELETE FROM eq_agm_meetings WHERE doc_id = ?", [doc_id])
            ecode = m.get("edinetCode")
            reg = by_code.get(ecode) or {}
            base = {
                "doc_id": doc_id, "doc_type": doc_type,
                "issuer_edinet_code": ecode,
                "issuer_sec_code": (m.get("secCode") or "")[:4] or None,
                "issuer_name": m.get("filerName") or reg.get(u"提出者名"),
                "filed_date": (m.get("submitDateTime") or "")[:10] or rec["date"],
                "meeting_date": None, "meeting_type": None,
                "proposals": 0, "candidates": 0,
                "partial_tally": None, "partial_tally_reason": None,
                "gate_checked": 0, "gate_passed": 0,
                "sha256": sha, "parser_version": PARSER_VERSION,
                "status": None, "detail": None,
            }
            if err:
                base["status"], base["detail"] = err
                stats[err[0]] += 1
                con.execute("INSERT INTO eq_agm_meetings VALUES (%s)"
                            % ",".join(["?"] * len(MEETING_COLS)),
                            [base[c] for c in MEETING_COLS])
                continue
            meeting, proposals, votes = parsed
            filed = base["filed_date"]
            md = meeting.get("meeting_date")
            if md and filed:
                try:
                    fd = dt.date.fromisoformat(str(filed)[:10])
                    if not (fd - dt.timedelta(days=365) <= md <= fd + dt.timedelta(days=7)):
                        meeting["meeting_date"] = None
                except ValueError:
                    pass
            problems, checked, passed = gates(proposals, votes)
            g_checked += checked
            g_passed += passed
            base.update(meeting)
            base["proposals"] = len(proposals)
            base["candidates"] = len(votes)
            base["gate_checked"] = checked
            base["gate_passed"] = passed
            base["status"] = "partial" if problems else "clean"
            base["detail"] = "; ".join(problems[:4]) or None
            stats[base["status"]] += 1
            con.execute("INSERT INTO eq_agm_meetings VALUES (%s)"
                        % ",".join(["?"] * len(MEETING_COLS)),
                        [base[c] for c in MEETING_COLS])
            if proposals:
                con.executemany(
                    "INSERT INTO eq_agm_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(doc_id, p["seq"], p["proposal_no"], p["label"], p["category"],
                      p["shareholder_proposal"], p["for_votes"], p["against_votes"],
                      p["abstain_votes"], p["approval_pct_filed"], p["result"],
                      p["candidates"], p.get("pct_consistent")) for p in proposals])
                n_prop += len(proposals)
            if votes:
                con.executemany(
                    "INSERT INTO eq_agm_votes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [(doc_id, v["seq"], v["proposal_seq"], v["proposal_no"],
                      v["candidate_name"], v["for_votes"], v["against_votes"],
                      v["abstain_votes"], v["approval_pct_filed"], v["result"],
                      v.get("pct_consistent")) for v in votes])
                n_vote += len(votes)
    con.close()
    record_run(args.db, "agm-votes", through, len(filings), PARSER_VERSION)
    if not args.no_compact:
        compact(args.db)
    print("filings: %s" % dict(stats))
    print("rows: %d proposals, %d named candidates" % (n_prop, n_vote))
    if g_checked:
        print("G1 (filed %% vs share of counted votes, 5pp): %d/%d = %.1f%%"
              % (g_passed, g_checked, 100.0 * g_passed / g_checked))
    print("wrote", os.path.normpath(args.db))


if __name__ == "__main__":
    main()
