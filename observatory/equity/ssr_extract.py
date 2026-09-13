# -*- coding: utf-8 -*-
u"""Semiannual reports (半期報告書) — the mid-year numbers, parser `ssr-1`.

WHY THIS EXISTS
---------------
Japan abolished the quarterly report (四半期報告書) in 2024. Since then the
半期報告書 is the ONLY statutory financial statement between one annual report
and the next: without it a listed company's filed accounts go dark for twelve
months at a time. The archive already holds these filings (types 160 and 170,
with the CSV package, exactly like the annual report); this reads them.

WHY A SEPARATE TABLE, NOT A COLUMN ON eq_fin_facts
--------------------------------------------------
A half-year revenue and a full-year revenue are the same element, the same
unit, and the same company. Put them in one table and the only thing standing
between a reader and a 2x error is remembering to filter. The tables are
therefore separate — `eq_ssr_filings` / `eq_ssr_facts` — so that every existing
query against the annual data keeps returning annual data, and a cross-section
of interim numbers has to be asked for on purpose. It costs a join; it removes
a whole class of silent error.

CONTEXTS
--------
The interim taxonomy names its periods differently from the annual one, and
the current period carries NO `Current` prefix at all:

    InterimDuration          the six months just reported
    InterimInstant           the balance-sheet date at the end of them
    Prior1InterimDuration    the same six months a year earlier
    Prior1YearInstant        the LAST FULL-YEAR balance sheet, as comparative
    Prior1YearDuration       the prior full year, where a filer prints it

`span` records which of the two a fact belongs to — `interim` for a
half-year or interim instant, `year` for a full-year comparative — so a
six-month figure and a twelve-month figure are never added together even
inside this table.

GATE
----
The same identity the annual extractor checks: assets = liabilities + net
assets on the interim balance-sheet date, per basis. A filing that tags the
totals and fails it, or that tags none at all, is `partial` with the reason;
nothing is dropped and nothing is corrected.

Usage (from observatory/equity/):
    ../.venv/bin/python ssr_extract.py --limit 20
    ../.venv/bin/python ssr_extract.py --all --source s3 --new-only   # nightly
"""
import argparse
import csv
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
                     incremental_window, record_run,
                     select_pending, catch_up_start, CATCH_UP_DAYS,
                     recorded_floor)
from fin_extract import (NUM_RE, STANDARD_DEI, CONSOLIDATED_DEI, balance_check,
                         summary_check)

PARSER_VERSION = "ssr-1"
EXTRACTOR = "semiannual"
SSR_TYPES = ("160", "170")

# The current interim period has no `Current` prefix — `InterimDuration`, not
# `CurrentInterimDuration` — so the prefix has to be optional. Group 1/2 give
# the year offset, 3 says interim or full year, 4 instant or duration, 5 marks
# the parent-only twin.
CTX_RE = re.compile(r"^(Current|Prior([1-9]))?"
                    r"(Year|Interim|YTD|Quarter)(Instant|Duration)"
                    r"(_NonConsolidatedMember)?$")

# THREE PERIOD LENGTHS, NEVER INTERCHANGEABLE. The 2024 transition left three
# shapes in the archive: the半期 form (Interim, six months), the second-quarter
# form used during the changeover (YTD, also six months; Quarter, three), and
# the full-year comparative every one of them prints (Year). A three-month
# figure added to a six-month one is the error this column exists to prevent.
SPAN_OF = {"Year": "year", "Interim": "interim", "YTD": "interim",
           "Quarter": "quarter"}

# The report itself is a jpcrp member; the jpaud members beside it are the
# auditor's review report and carry no financial data. Which jpcrp form it is
# varies — 040300-ssr (ordinary semiannual), 040300-q2r (the transitional
# second-quarter form), 050000/050200-ssr (specified securities issuers) — so
# the member is chosen by namespace and the form recorded, rather than being
# pinned to one spelling that only held for one year.
CSV_MARK = "/jpcrp"


def parse_facts(blob):
    u"""(facts, labels, dei) from the semiannual CSV package.

    facts: (ord, element, context, year_offset, kind, span, basis, scope_ja,
            unit, value)
    """
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        members = sorted(n for n in z.namelist()
                         if n.endswith(".csv") and CSV_MARK in n)
        if not members:
            raise ValueError("no jpcrp report csv in package")
        form = members[0].split("/")[-1].split("_")[0]
        text = z.read(members[0]).decode("utf-16")
    body = list(csv.reader(io.StringIO(text), delimiter="\t"))[1:]

    facts, labels, seen = [], {}, set()
    dei = {"standard": None, "consolidated": None, "form": form}
    for i, row in enumerate(body):
        if len(row) != 9:
            continue
        eid, item, ctx, relyr, cons, pit, unit_id, unit, val = row
        if eid == STANDARD_DEI:
            dei["standard"] = val.strip() or None
            continue
        if eid == CONSOLIDATED_DEI:
            dei["consolidated"] = val.strip().lower() == "true"
            continue
        m = CTX_RE.match(ctx)
        if not m:
            continue                     # dimensional contexts belong to the
                                         # extractors that own those tables
        v = val.strip().replace(",", "")
        if not NUM_RE.match(v):
            continue                     # "－", blank, text: missing, never zero
        if (eid, ctx) in seen:
            continue
        seen.add((eid, ctx))
        offset = 0 if m.group(2) is None else -int(m.group(2))
        span = SPAN_OF.get(m.group(3), "interim")
        kind = "instant" if m.group(4) == "Instant" else "duration"
        basis = "parent" if m.group(5) else "consolidated"
        facts.append((i, eid, ctx, offset, kind, span, basis, cons or None,
                      unit_id or None, float(v)))
        if eid not in labels:
            labels[eid] = item
    return facts, labels, dei


def annualish(facts):
    u"""The fact tuples in the shape balance_check/summary_check expect.

    Those two read (ord, element, ctx, offset, kind, basis, ...) — the annual
    shape, which has no `span`. The interim balance sheet is the current
    instant either way, so dropping the extra field is enough and the identity
    check stays exactly the one the annual extractor applies.
    """
    return [(i, eid, ctx, off, kind, basis, cons, unit, val)
            for (i, eid, ctx, off, kind, span, basis, cons, unit, val) in facts]


SCHEMA_SQL = u"""
CREATE TABLE IF NOT EXISTS eq_ssr_filings (
    doc_id VARCHAR PRIMARY KEY, doc_type VARCHAR, edinet_code VARCHAR,
    sec_code VARCHAR, filer_name VARCHAR, period_end DATE, filed_date DATE,
    sha256 VARCHAR, parser_version VARCHAR, form VARCHAR,
    status VARCHAR, detail VARCHAR,
    accounting_standard VARCHAR, consolidated BOOLEAN, facts INTEGER,
    bs_consolidated VARCHAR, bs_parent VARCHAR,
    total_assets_yen DOUBLE, net_assets_yen DOUBLE);
CREATE TABLE IF NOT EXISTS eq_ssr_facts (
    doc_id VARCHAR, ord INTEGER, element VARCHAR, context VARCHAR,
    year_offset INTEGER, period_kind VARCHAR, span VARCHAR, basis VARCHAR,
    scope_ja VARCHAR, unit VARCHAR, value DOUBLE);
"""
FILINGS_COLS = 19


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every filer, not just listed")
    ap.add_argument("--source", choices=("local", "s3"), default="local")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--docs", help="comma-separated docIDs")
    ap.add_argument("--sec-codes", help="comma-separated 4-digit securities codes")
    ap.add_argument("--new-only", action="store_true",
                    help="extract only filings archived since the last recorded "
                         "run (plus a lookback); what the nightly refresh uses.")
    ap.add_argument("--no-compact", action="store_true")
    ap.add_argument("--catch-up", type=int, default=CATCH_UP_DAYS, metavar="DAYS",
                    help="on a --new-only run, also read the DAYS deepest archive "
                         "days below this extractor's own floor.")
    args = ap.parse_args()

    src = S3Source(args.workers) if args.source == "s3" else LocalSource()
    codelist = load_codelist()
    listed = {d[u"ＥＤＩＮＥＴコード"] for d in codelist
              if d[u"上場区分"] == u"上場"}

    since, have = (incremental_window(args.db, EXTRACTOR, "eq_ssr_filings")
                   if args.new_only else (None, set()))
    filings = src.filings(catch_up_start(since, args.catch_up if args.new_only else 0))
    through = max((r["date"] for r in filings.values()), default=None)
    pending, catch_up_floor = select_pending(
        filings, since, have, args.catch_up if args.new_only else 0,
        recorded_floor(args.db, EXTRACTOR))
    if since is not None:
        print("incremental: %d of %d archived filings are new since %s"
              % (len(pending), len(filings), since))
    meta = src.list_metadata(
        days=None if since is None else {r["date"] for r in pending.values()})

    targets = []
    for doc_id, rec in sorted(pending.items()):
        m = meta.get(doc_id) or {}
        doc_type = m.get("docTypeCode") or rec.get("doc_type")
        if doc_type not in SSR_TYPES:
            continue
        if m.get("fundCode"):
            continue                     # investment trusts file these too
        if args.all or m.get("edinetCode") in listed:
            targets.append((doc_id, rec, m, doc_type))
    if args.docs:
        want = {d.strip() for d in args.docs.split(",") if d.strip()}
        targets = [t for t in targets if t[0] in want]
    if args.sec_codes:
        want = {c.strip()[:4] for c in args.sec_codes.split(",") if c.strip()}
        targets = [t for t in targets if (t[2].get("secCode") or "")[:4] in want]
    if args.limit:
        targets = targets[:args.limit]
    print("target filings: %d (source=%s)" % (len(targets), src.name))

    con = duckdb.connect(args.db)
    con.execute(SCHEMA_SQL)

    def fetch_and_parse(t):
        doc_id, rec, m, doc_type = t
        try:
            blob = src.read_zip(doc_id, rec["date"])
            sha = hashlib.sha256(blob).hexdigest()
            return t, parse_facts(blob), sha, None
        except Exception as e:                                    # noqa: BLE001
            return t, None, None, "%s: %s" % (type(e).__name__, str(e)[:160])

    stats = defaultdict(int)
    n_facts = done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(fetch_and_parse, t) for t in targets]
        for fut in as_completed(futures):
            (doc_id, rec, m, doc_type), parsed, sha, err = fut.result()
            done += 1
            if done % 500 == 0:
                print("  %d/%d filings, %d facts" % (done, len(targets), n_facts))
                sys.stdout.flush()
            base = [doc_id, doc_type, m.get("edinetCode"),
                    (m.get("secCode") or "")[:4] or None,
                    rec.get("filer") or m.get("filerName"),
                    m.get("periodEnd") or None, rec["date"], sha, PARSER_VERSION]
            con.execute("DELETE FROM eq_ssr_filings WHERE doc_id = ?", [doc_id])
            con.execute("DELETE FROM eq_ssr_facts WHERE doc_id = ?", [doc_id])
            if err:
                stats["failed"] += 1
                con.execute("INSERT INTO eq_ssr_filings VALUES (%s)"
                            % ",".join(["?"] * FILINGS_COLS),
                            base + [None, "failed", err] + [None] * (FILINGS_COLS - 12))
                continue
            facts, labels, dei = parsed
            flat = annualish(facts)
            checks, _cur = balance_check(flat)
            s_assets, s_equity, s_ok = summary_check(flat)
            problems = []
            for basis in ("consolidated", "parent"):
                if checks[basis] and checks[basis] != "ok":
                    problems.append("%s balance sheet %s" % (basis, checks[basis]))
            if not any(checks.values()):
                problems.append("no balance-sheet totals tagged")
            if s_ok is False:
                problems.append("summary net assets exceed total assets")
            if not facts:
                problems.append("no numeric facts in interim contexts")
            status = "partial" if problems else "clean"
            stats[status] += 1
            con.execute("INSERT INTO eq_ssr_filings VALUES (%s)"
                        % ",".join(["?"] * FILINGS_COLS),
                        base + [dei.get("form"), status,
                                "; ".join(problems[:4]) or None,
                                dei.get("standard"), dei.get("consolidated"),
                                len(facts), checks["consolidated"], checks["parent"],
                                s_assets, s_equity])
            if facts:
                con.executemany(
                    "INSERT INTO eq_ssr_facts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [(doc_id, i, eid, ctx, off, kind, span, basis, cons, unit, val)
                     for (i, eid, ctx, off, kind, span, basis, cons, unit, val) in facts])
                n_facts += len(facts)
    con.close()
    record_run(args.db, EXTRACTOR, through, len(filings), PARSER_VERSION,
               back_to=catch_up_floor)
    if not args.no_compact:
        compact(args.db)
    print("filings: %s" % dict(stats))
    print("facts: %d" % n_facts)
    print("wrote", os.path.normpath(args.db))


if __name__ == "__main__":
    main()
