# -*- coding: utf-8 -*-
u"""Capital raises (有価証券届出書) — new shares and who gets them, parser `iss-1`.

WHAT THIS READS
---------------
    030 有価証券届出書        the registration statement for a new issue
    040 訂正有価証券届出書    its corrections, each a new vintage

Every public issue of shares by a Japanese listed company passes through this
document: a public offering, a rights issue, an IPO, and — the one that moves
governance — a THIRD-PARTY ALLOTMENT (第三者割当), where new shares are sold to
named people at a set price without the other shareholders getting a look.
That is the classic dilution and entrenchment signal, and the filing names the
allottees, their business, and their existing relationship with the issuer.

WHAT IS PARSED
--------------
Five tables, all with stable headings across the archive:

    【新規発行株式】              class and number of new shares
    【募集の方法】                the split: rights / third-party / public
    【募集の条件】                issue price and the payment date
    【新規発行による手取金の額】   gross proceeds, costs, net proceeds
    【割当予定先の状況】           who the third-party shares go to

None of it is inline-XBRL tagged in most filings, so all of it is read from
the honbun tables by heading (see edinet_honbun.section).

WHAT THE 発行価格 IS NOT
------------------------
The issue price in 【募集の条件】 is not always what the company receives per
share: in a discounted third-party allotment the reference price and the
payment amount differ, and 発行価格 465 against 490,079,310 yen for 1,102,500
shares means the company was paid 444.5. Both numbers are stored; neither is
recomputed into the other, and there is no gate between them because they are
not the same quantity.

GATES
-----
  G1  the offering split adds up: rights + third-party + public = total shares.
  G2  the same for the money column (発行価額の総額).
  G3  gross proceeds - issue costs = net proceeds, to the yen.
All three are identities printed in the filing, not approximations.

Usage (from observatory/equity/):
    ../.venv/bin/python issue_extract.py --limit 20
    ../.venv/bin/python issue_extract.py --all --source s3 --new-only   # nightly
"""
import argparse
import datetime as dt
import hashlib
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

from extract import (LocalSource, S3Source, compact, DB_PATH,
                     incremental_window, record_run,
                     select_pending, catch_up_start, CATCH_UP_DAYS,
                     recorded_floor)
from edinet_honbun import (honbun, blocks, tables_in, section, taxonomy_prefix,
                           grid_of, norm, jp_date, to_int, NoHonbun)

PARSER_VERSION = "iss-1"
EXTRACTOR = "capital-raises"
ISSUE_TYPES = ("030", "040")


class NotAnIssue(Exception):
    u"""The package holds no registration statement we recognise."""


# The daily list's description is the only place the FLAVOUR of the filing is
# stated plainly, and the flavours behave very differently: an IPO is not a
# dilution event for existing holders, a shelf filing is not an issue at all
# until it is drawn down, and a reorganisation issues shares as deal
# consideration rather than for cash.
KINDS = [(u"新規公開時", "ipo"),
         (u"組織再編成・上場", "reorganisation-listing"),
         (u"組織再編成", "reorganisation"),
         (u"少額募集", "small"),
         (u"組込方式", "shelf-incorporated"),
         (u"参照方式", "shelf-referenced"),
         (u"通常方式", "ordinary"),
         (u"外国会社", "foreign")]


def kind_of(description):
    d = norm(description or "")
    for jp, en in KINDS:
        if jp in d:
            return en
    return None


# ----------------------------------------------------------------- readers

def new_shares(bl, html):
    u"""(security class, number of new shares) from 【新規発行株式】."""
    h = section(bl, html, (), (u"【新規発行株式】",))
    for t in tables_in(h):
        cells, _ = grid_of(t)
        if not cells:
            continue
        head = [norm(c) for c in cells[0]]
        if not any(u"発行数" in c for c in head):
            continue
        ci = next((i for i, c in enumerate(head) if u"発行数" in c), None)
        for row in cells[1:]:
            label = norm(row[0] if row else "")
            v = to_int(row[ci]) if ci is not None and ci < len(row) else None
            if v is not None and label:
                return label[:40], v
    return (None, None)


# 株主割当 is a rights issue (every holder gets the chance); その他の者に対する
# 割当 is the third-party allotment; 一般募集 is a public offering. 発起人の引受
# appears only in an incorporation and is counted with the third-party column
# for the purpose of "did existing holders get a look" — it is recorded
# separately below so nothing is lost.
SPLIT_ROWS = [(u"株主割当", "rights"),
              (u"その他の者に対する割当", "third_party"),
              (u"一般募集", "public"),
              (u"発起人の引受", "founders")]


def _add(pair, shares, amount):
    u"""Accumulate a sub-row into its category, keeping NULL distinct from 0."""
    s0, a0 = pair
    s = shares if s0 is None else (s0 if shares is None else s0 + shares)
    a = amount if a0 is None else (a0 if amount is None else a0 + amount)
    return (s, a)


def offering_split(bl, html):
    u"""{bucket: (shares, amount_yen)}, the filed total, and treasury disposals.

    A CATEGORY CAN HAVE SUB-ROWS, AND THEY MUST BE ADDED, NOT REPLACED. The
    first column is often merged over two lines — 一般募集 splitting into
    新株式発行 and 自己株式の処分 — and taking the last row seen reports a
    1,083,000-share offering as an 83,000-share one. The filed 計 row is what
    catches that, which is why G1 exists.

    自己株式の処分 is a disposal of shares the company already holds, not an
    issue of new ones. It still dilutes voting power, so it belongs in the
    total, but it is a different act and is counted separately as well.
    """
    h = section(bl, html, (), (u"【募集の方法】",))
    out, total, treasury = {}, (None, None), (None, None)
    for t in tables_in(h):
        cells, _ = grid_of(t)
        if not cells:
            continue
        head = [norm(c) for c in cells[0]]
        if not (any(u"発行数" in c for c in head)
                and any(u"発行価額" in c for c in head)):
            continue
        si = next((i for i, c in enumerate(head) if u"発行数" in c), None)
        ai = next((i for i, c in enumerate(head) if u"発行価額" in c), None)
        for row in cells[1:]:
            label = norm(row[0] if row else "")
            sub = norm(row[1]) if len(row) > 1 else ""
            shares = to_int(row[si]) if si is not None and si < len(row) else None
            amount = to_int(row[ai]) if ai is not None and ai < len(row) else None
            if label.startswith(u"計") or u"総発行株式" in label:
                total = (shares, amount)
                continue
            if u"自己株式の処分" in sub or u"自己株式の処分" in label:
                treasury = _add(treasury, shares, amount)
            for jp, key in SPLIT_ROWS:
                if jp in label:
                    out[key] = _add(out.get(key, (None, None)), shares, amount)
                    break
        if out or total != (None, None):
            break
    return out, total, treasury


def offering_terms(bl, html):
    u"""(issue price, payment date) from 【募集の条件】."""
    h = section(bl, html, (), (u"【募集の条件】",))
    for t in tables_in(h):
        cells, _ = grid_of(t)
        if len(cells) < 2:
            continue
        head = [norm(c) for c in cells[0]]
        pi = next((i for i, c in enumerate(head) if u"発行価格" in c), None)
        di = next((i for i, c in enumerate(head) if u"払込期日" in c), None)
        if pi is None and di is None:
            continue
        row = cells[1]
        price = to_int(row[pi]) if pi is not None and pi < len(row) else None
        paid = jp_date(row[di]) if di is not None and di < len(row) else None
        return price, paid
    return (None, None)


def proceeds(bl, html):
    u"""(gross, costs, net) from 【新規発行による手取金の額】."""
    h = section(bl, html, (), (u"【新規発行による手取金の額】",))
    for t in tables_in(h):
        cells, _ = grid_of(t)
        if len(cells) < 2:
            continue
        head = [norm(c) for c in cells[0]]
        gi = next((i for i, c in enumerate(head) if u"払込金額の総額" in c), None)
        ci = next((i for i, c in enumerate(head) if u"発行諸費用" in c), None)
        ni = next((i for i, c in enumerate(head) if u"手取" in c), None)
        if gi is None:
            continue
        row = cells[1]
        g = to_int(row[gi]) if gi < len(row) else None
        c_ = to_int(row[ci]) if ci is not None and ci < len(row) else None
        n = to_int(row[ni]) if ni is not None and ni < len(row) else None
        return g, c_, n
    return (None, None, None)


# An allottee block is a vertical label/value table: 名称 for a company, 氏名
# for a person. Both spellings appear, and which one is used is itself the
# fact that says whether the new shares went to an institution or to an
# individual — often a director of the issuer.
ALLOTTEE_LABELS = ((u"名称", "company"), (u"氏名", "person"))


def allottees(bl, html):
    u"""[(ord, name, party_kind)] from 【割当予定先の状況】.

    ONE ALLOTTEE PER TABLE. Each allottee gets its own label/value block, and
    inside that block the filing also names the allottee's OWN major investors,
    its general partner, and its directors — all under the same 名称 / 氏名
    labels. Taking every match turns one buyer into five and makes
    `allottee_count` useless. The first match in each table is the allottee;
    everything below it describes that allottee.
    """
    h = section(bl, html, (), (u"【割当予定先の状況】",))
    out, seen = [], set()
    for t in tables_in(h):
        cells, _ = grid_of(t)
        found = None
        for row in cells:
            labels = [norm(c) for c in row]
            for i, cell in enumerate(labels):
                for jp, kind in ALLOTTEE_LABELS:
                    if cell == jp:
                        # A merged label cell is duplicated across the columns
                        # it spans, so the cell after 名称 is often 名称 again.
                        # Skipping repeats of the label is what stops the
                        # literal word being stored as the buyer's name.
                        for v in labels[i + 1:]:
                            v = norm(v)
                            if v and v != cell and v not in (u"―", "-", u"－"):
                                found = (v[:120], kind)
                                break
                        break
                if found:
                    break
            if found:
                break
        if found and found[0] not in seen:
            seen.add(found[0])
            out.append((len(out), found[0], found[1]))
    return out


# -------------------------------------------------------------------- gates

def gates(row):
    problems, checked, passed = [], 0, 0
    parts = [row.get("shares_rights"), row.get("shares_third_party"),
             row.get("shares_public"), row.get("shares_founders")]
    if row.get("shares_total") and any(p is not None for p in parts):
        checked += 1
        s = sum(p or 0 for p in parts)
        if s == row["shares_total"]:
            passed += 1
        else:
            problems.append("G1 share split %d != total %d" % (s, row["shares_total"]))
    amts = [row.get("amount_rights"), row.get("amount_third_party"),
            row.get("amount_public"), row.get("amount_founders")]
    if row.get("amount_total") and any(a is not None for a in amts):
        checked += 1
        s = sum(a or 0 for a in amts)
        if s == row["amount_total"]:
            passed += 1
        else:
            problems.append("G2 amount split %d != total %d" % (s, row["amount_total"]))
    if (row.get("gross_proceeds_yen") and row.get("issue_costs_yen") is not None
            and row.get("net_proceeds_yen")):
        checked += 1
        if row["gross_proceeds_yen"] - row["issue_costs_yen"] == row["net_proceeds_yen"]:
            passed += 1
        else:
            problems.append("G3 %d - %d != %d" % (row["gross_proceeds_yen"],
                                                  row["issue_costs_yen"],
                                                  row["net_proceeds_yen"]))
    return problems, checked, passed


def parse(blob):
    html = honbun(blob)
    bl = blocks(html)
    row = {"form": taxonomy_prefix(blob)}
    row["security_class"], row["shares_new"] = new_shares(bl, html)
    split, total, treasury = offering_split(bl, html)
    row["treasury_disposal_shares"], row["treasury_disposal_amount"] = treasury
    for key in ("rights", "third_party", "public", "founders"):
        s, a = split.get(key, (None, None))
        row["shares_" + key] = s
        row["amount_" + key] = a
    row["shares_total"], row["amount_total"] = total
    row["issue_price_yen"], row["payment_date"] = offering_terms(bl, html)
    row["gross_proceeds_yen"], row["issue_costs_yen"], row["net_proceeds_yen"] = \
        proceeds(bl, html)
    row["third_party_allotment"] = bool(row.get("shares_third_party"))
    row["allottees"] = allottees(bl, html)
    row["allottee_count"] = len(row["allottees"])
    if not any(row.get(k) is not None for k in
               ("shares_new", "shares_total", "gross_proceeds_yen")):
        raise NotAnIssue("no issue tables found")
    return row


SCHEMA_SQL = u"""
CREATE TABLE IF NOT EXISTS eq_issue_filings (
    doc_id VARCHAR PRIMARY KEY, doc_type VARCHAR, form VARCHAR, kind VARCHAR,
    edinet_code VARCHAR, sec_code VARCHAR, filer_name VARCHAR, filed_date DATE,
    security_class VARCHAR, shares_new BIGINT, shares_total BIGINT,
    shares_rights BIGINT, shares_third_party BIGINT, shares_public BIGINT,
    shares_founders BIGINT,
    treasury_disposal_shares BIGINT,
    treasury_disposal_amount BIGINT,
    amount_total BIGINT, amount_rights BIGINT, amount_third_party BIGINT,
    amount_public BIGINT, amount_founders BIGINT,
    issue_price_yen BIGINT, payment_date DATE,
    gross_proceeds_yen BIGINT, issue_costs_yen BIGINT, net_proceeds_yen BIGINT,
    third_party_allotment BOOLEAN, allottee_count INTEGER,
    sha256 VARCHAR, parser_version VARCHAR, status VARCHAR, detail VARCHAR,
    gate_checked INTEGER, gate_passed INTEGER);
CREATE TABLE IF NOT EXISTS eq_issue_allottees (
    doc_id VARCHAR, ord INTEGER, name VARCHAR, party_kind VARCHAR);
"""

COLS = ["doc_id", "doc_type", "form", "kind", "edinet_code", "sec_code",
        "filer_name", "filed_date", "security_class", "shares_new",
        "shares_total", "shares_rights", "shares_third_party", "shares_public",
        "shares_founders", "treasury_disposal_shares",
        "treasury_disposal_amount", "amount_total", "amount_rights",
        "amount_third_party", "amount_public", "amount_founders",
        "issue_price_yen", "payment_date", "gross_proceeds_yen",
        "issue_costs_yen", "net_proceeds_yen", "third_party_allotment",
        "allottee_count", "sha256", "parser_version", "status", "detail",
        "gate_checked", "gate_passed"]


def s3_t1(src, start_after=None):
    out = {}
    for key in src._keys("docs/", start_after):
        p = key.split("/")
        if len(p) == 3 and p[2].endswith("_t1.zip"):
            out[p[2][:-len("_t1.zip")]] = {"date": p[1]}
    return out


def local_t1():
    import json
    from extract import ARCHIVE
    out = {}
    path = os.path.join(ARCHIVE, "manifest.jsonl")
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if (r.get("status") == "ok" and r.get("doc_type") in ISSUE_TYPES
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
    ap.add_argument("--docs", help="comma-separated docIDs")
    ap.add_argument("--new-only", action="store_true",
                    help="extract only filings archived since the last recorded "
                         "run (plus a lookback); what the nightly refresh uses.")
    ap.add_argument("--no-compact", action="store_true")
    ap.add_argument("--catch-up", type=int, default=CATCH_UP_DAYS, metavar="DAYS",
                    help="on a --new-only run, also read the DAYS deepest archive "
                         "days below this extractor's own floor.")
    args = ap.parse_args()

    src = S3Source(args.workers) if args.source == "s3" else LocalSource()
    since, have = (incremental_window(args.db, EXTRACTOR, "eq_issue_filings")
                   if args.new_only else (None, set()))
    filings = (local_t1() if src.name == "local"
               else s3_t1(src, catch_up_start(since, args.catch_up if args.new_only else 0)))
    through = max((r["date"] for r in filings.values()), default=None)
    pending, catch_up_floor = select_pending(
        filings, since, have, args.catch_up if args.new_only else 0,
        recorded_floor(args.db, EXTRACTOR))
    if since is not None:
        print("incremental: %d of %d archived documents are new since %s"
              % (len(pending), len(filings), since))
    meta = src.list_metadata(
        days=None if since is None else {r["date"] for r in pending.values()})

    targets = []
    for doc_id, rec in sorted(pending.items()):
        m = meta.get(doc_id) or {}
        doc_type = m.get("docTypeCode") or rec.get("doc_type")
        if doc_type not in ISSUE_TYPES or m.get("fundCode"):
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
        except Exception as e:                                    # noqa: BLE001
            return t, None, None, ("failed", "fetch: %s" % str(e)[:120])
        sha = hashlib.sha256(blob).hexdigest()
        try:
            return t, parse(blob), sha, None
        except (NotAnIssue, NoHonbun) as e:
            return t, None, sha, ("no_issue_tables", str(e)[:120])
        except Exception as e:                                    # noqa: BLE001
            return t, None, sha, ("failed", "%s: %s" % (type(e).__name__, str(e)[:120]))

    stats = defaultdict(int)
    g_checked = g_passed = n_all = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(fetch_and_parse, t) for t in targets]
        for fut in as_completed(futures):
            (doc_id, rec, m, doc_type), row, sha, err = fut.result()
            base = dict.fromkeys(COLS)
            base.update({"doc_id": doc_id, "doc_type": doc_type, "sha256": sha,
                         "parser_version": PARSER_VERSION,
                         "kind": kind_of(m.get("docDescription")),
                         "edinet_code": m.get("edinetCode"),
                         "sec_code": (m.get("secCode") or "")[:4] or None,
                         "filer_name": rec.get("filer") or m.get("filerName"),
                         "gate_checked": 0, "gate_passed": 0})
            d = m.get("submitDateTime") or rec.get("date")
            base["filed_date"] = dt.date.fromisoformat(str(d)[:10]) if d else None
            con.execute("DELETE FROM eq_issue_filings WHERE doc_id = ?", [doc_id])
            con.execute("DELETE FROM eq_issue_allottees WHERE doc_id = ?", [doc_id])
            if err:
                base["status"], base["detail"] = err
                stats[base["status"]] += 1
                con.execute("INSERT INTO eq_issue_filings VALUES (%s)"
                            % ",".join(["?"] * len(COLS)), [base[c] for c in COLS])
                continue
            people = row.pop("allottees")
            base.update({k: v for k, v in row.items() if k in COLS})
            problems, checked, passed = gates(base)
            g_checked += checked
            g_passed += passed
            base["gate_checked"] = checked
            base["gate_passed"] = passed
            base["status"] = "partial" if problems else "clean"
            base["detail"] = "; ".join(problems[:3]) or None
            stats[base["status"]] += 1
            stats["kind:" + (base["kind"] or "?")] += 1
            con.execute("INSERT INTO eq_issue_filings VALUES (%s)"
                        % ",".join(["?"] * len(COLS)), [base[c] for c in COLS])
            if people:
                con.executemany("INSERT INTO eq_issue_allottees VALUES (?,?,?,?)",
                                [(doc_id, o, n, k) for o, n, k in people])
                n_all += len(people)
    con.close()
    record_run(args.db, EXTRACTOR, through, len(filings), PARSER_VERSION,
               back_to=catch_up_floor)
    if not args.no_compact:
        compact(args.db)
    print("filings: %s" % dict(stats))
    print("allottee rows: %d" % n_all)
    if g_checked:
        print("gates: %d/%d = %.1f%%" % (g_passed, g_checked,
                                         100.0 * g_passed / g_checked))
    print("wrote", os.path.normpath(args.db))


if __name__ == "__main__":
    main()
