# -*- coding: utf-8 -*-
u"""Corporate events (臨時報告書) — the deal and governance tape, parser `ev-1`.

WHAT THIS READS
---------------
    180 臨時報告書       every extraordinary report
    190 訂正臨時報告書   and its corrections

An 臨時報告書 is filed when something happens that shareholders must be told
about before the next periodic report: a merger, a share exchange, a company
split, the purchase or loss of a subsidiary, a change of chief executive, a
change of major shareholder, a change of auditor, litigation, a covenant
breach, or an event with a material effect on the accounts.

WHY THIS EXISTS SEPARATELY FROM agm_extract.py
----------------------------------------------
Roughly half of these filings are annual general meeting voting results, and
`agm_extract.py` has parsed those since 2026-08. It opens every other one,
finds no vote table, writes `not_agm`, and moves on — 13,631 filings whose
contents were downloaded and discarded. This reads the same documents for what
they actually say. AGM filings are classified here too, so the tape is
complete and reconciles against the archive, but their detail is not
duplicated: it stays in `eq_agm_*`.

THE EVENT TYPE IS TAGGED, NOT GUESSED
-------------------------------------
Each filing carries exactly one inline-XBRL block naming the event —
`DecisionOnShareExchangeTextBlock`, `ChangesInMajorShareholderTextBlock` — in
386 of 392 sampled filings, and two in the other six. That block name is the
classification: authoritative, stable, and nothing like the keyword matching a
free-text approach would need. The filing also cites the enabling clause
(企業内容等の開示に関する内閣府令 第19条第2項第N号), which is stored beside it
as an independent cross-check.

WHAT IS PARSED IN DETAIL
------------------------
Every filing is classified and summarised. Four families also get their
structured detail, chosen for what they move rather than for how common they
are:

  * major shareholder changes  -> `eq_event_shareholders` (votes and share of
    the vote, before and after)
  * representative director changes -> `eq_event_officers`
  * deal decisions — merger, share exchange, share transfer, company split,
    subsidiary purchase or sale -> `eq_event_parties` (the counterparty's
    name, capital, net assets, total assets, business)
  * parent and specified-subsidiary changes -> `eq_event_parties`, parsed from
    NUMBERED PROSE rather than a table, because that is how the form is
    written: `1 名称 :NESIC BRASIL S/A  2 住所 :…  4 資本金 :2,142百万円`.

Everything else — stock option grants, material-impact events, litigation,
covenant breaches — is classified, dated and summarised, with its detail left
in the summary text. Nothing is dropped silently.

MONEY IS WRITTEN IN UNITS
-------------------------
These tables print 資本金 as `2,142百万円` and 総資産 as `6,101,086百万円`. The
unit is part of the cell, it differs between rows of the same table, and it is
sometimes 千円 or 億円. Values are converted to yen on the way in and the unit
that was found is kept, so a wrong multiplier is visible rather than silent.

Usage (from observatory/equity/):
    ../.venv/bin/python event_extract.py --limit 20
    ../.venv/bin/python event_extract.py --all --source s3 --new-only   # nightly
"""
import argparse
import datetime as dt
import hashlib
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

from extract import (LocalSource, S3Source, compact, DB_PATH,
                     incremental_window, record_run,
                     select_pending, catch_up_start, CATCH_UP_DAYS,
                     recorded_floor,
                     sec_code_of)
from edinet_honbun import (honbun, blocks, tables_in, section, section_text,
                           grid_of, norm, jp_date, to_int, NoHonbun)

PARSER_VERSION = "ev-1"
EXTRACTOR = "corporate-events"
EVENT_TYPES = ("180", "190")

REASON_BLOCK = "ReasonForFilingTextBlock"

# Block name -> (event type, family). The family is what the detail parsers
# switch on; the type is what a reader sees. Anything not listed is still
# classified — as the block name itself, lower-cased — so a taxonomy the
# regulator adds to does not silently become "other".
EVENTS = {
    "ResolutionOfShareholdersMeetingTextBlock": ("agm-results", "agm"),
    "AmendmentOrRejectionByShareholdersMeetingTextBlock": ("agm-amended", "agm"),
    "EventWithSignificantEffectsOnFinancialPositionBusinessPerformanceAndCashFlowsTextBlock":
        ("material-impact", "text"),
    "EventWithSignificantEffectsOnFinancialPositionBusinessPerformanceAndCashFlowsOfGroupTextBlock":
        ("material-impact-group", "text"),
    "ChangesInParentCompaniesOrSpecifiedSubsidiariesTextBlock":
        ("parent-or-subsidiary-change", "subsidiary"),
    "ChangesInMajorShareholderTextBlock": ("major-shareholder-change", "shareholder"),
    "ChangesInRepresentativeDirectorsTextBlock": ("representative-director-change", "officer"),
    "ChangeInIndependentAuditorsTextBlock": ("auditor-change", "text"),
    "IssueOfStockOptionsNotSubjectToSecuritiesRegistrationTextBlock":
        ("stock-options", "text"),
    "DecisionOnShareExchangeTextBlock": ("share-exchange", "deal"),
    "DecisionOnShareTransferTextBlock": ("share-transfer", "deal"),
    "DecisionOnAbsorptionTypeMergerTextBlock": ("merger-absorption", "deal"),
    "DecisionOnIncorporationTypeMergerTextBlock": ("merger-new-company", "deal"),
    "DecisionOnAbsorptionTypeSplitTextBlock": ("split-absorption", "deal"),
    "DecisionOnIncorporationTypeSplitTextBlock": ("split-new-company", "deal"),
    "DecisionOnAcquisitionOfSubsidiaryTextBlock": ("subsidiary-acquisition", "deal"),
    "DecisionOnTransferOfSubsidiaryTextBlock": ("subsidiary-disposal", "deal"),
    "DecisionOnTransferOrAcquisitionOfBusinessTextBlock": ("business-transfer", "deal"),
    "DecisionOnShareDeliveryTextBlock": ("share-delivery", "deal"),
    "CommencementOrResolutionOfLitigationTextBlock": ("litigation", "text"),
    "FinancialCovenantsTextBlock": ("financial-covenant", "text"),
    "FinancialCovenantsOfConsolidatedSubsidiariesTextBlock":
        ("financial-covenant-subsidiary", "text"),
    "LikelihoodOfUncollectibleOrDelinquentAccountsTextBlock": ("bad-debt", "text"),
    "PublicOfferingOrSecondaryDistributionOfSecuritiesOutsideJapanTextBlock":
        ("offering-outside-japan", "text"),
    "PrivatePlacementOfSecuritiesTextBlock": ("private-placement", "text"),
    "DecisionOnHoldingShareholdersMeetingForPurposeOfReverseStockSplitTextBlock":
        ("reverse-split-meeting", "text"),
    "NotificationOfRequestForSaleOfSharesFromSpecialControllingShareholdersOrDecisionOnWhetherToApproveRequestForSaleOfSharesOrNotTextBlock":
        ("squeeze-out-request", "text"),
    "CorporateShareholderAgreementOnShareTransferEtcTextBlock":
        ("shareholder-agreement", "text"),
}


class NotAnEvent(Exception):
    u"""The package holds no extraordinary report we recognise."""


def slug_of(block_name):
    u"""A readable event type for a block this build has not been told about.

    `DecisionOnSomethingNewTextBlock` -> `decision-on-something-new`. Keeping
    the regulator's own word beats bucketing it as "other", which is how a new
    event type disappears for a year.
    """
    s = re.sub(r"TextBlock$", "", block_name)
    s = re.sub(r"(?<!^)(?=[A-Z])", "-", s).lower()
    return s[:60]


# ------------------------------------------------------------------- money

# 資本金 and 総資産 print their unit inside the cell, and it varies row to row.
UNITS = ((u"百万円", 10 ** 6), (u"千円", 10 ** 3), (u"億円", 10 ** 8),
         (u"兆円", 10 ** 12), (u"円", 1))


def money(cell):
    u"""(yen, unit found) from `2,142百万円`. (None, None) when it is not money."""
    s = norm(cell or "")
    for mark, mult in UNITS:
        if mark in s:
            m = re.search(u"([0-9][0-9,\\.]*)\\s*" + mark, s)
            if m:
                try:
                    return int(float(m.group(1).replace(",", "")) * mult), mark
                except ValueError:
                    return None, None
    return (None, None)


PCT_RE = re.compile(u"([0-9]+[.,][0-9]+|[0-9]+)\\s*[%％]")


def pct(cell):
    u"""Share of the vote as a fraction. `16,00%` is a filer's comma for a
    decimal point and is read as 16.00%, not as sixteen hundred."""
    s = norm(cell or "")
    m = PCT_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ".")) / 100.0
    except ValueError:
        return None


# ------------------------------------------------------------------ readers

def event_blocks(bl):
    u"""[(block name, inner html)] for the event blocks, reason block aside."""
    return [(n, h) for n, h in sorted(bl.items()) if n != REASON_BLOCK]


RESOLUTION_RE = re.compile(u"(\\d{4}年\\s*\\d{1,2}月\\s*\\d{1,2}日)\\s*(?:開催|付)")
ARTICLE_RE = re.compile(u"第19条第2項第(\\d+)号")


def reason_facts(bl, html):
    u"""(resolution date, article items) from 【提出理由】."""
    text = section_text(bl, html, (REASON_BLOCK,), (u"【提出理由】",))
    m = RESOLUTION_RE.search(text)
    items = sorted(set(ARTICLE_RE.findall(text)), key=lambda x: int(x))
    return (jp_date(m.group(1)) if m else None), (",".join(items) or None), text


EFFECTIVE_LABELS = (u"効力発生日", u"実施予定日", u"当該異動年月日",
                    u"異動の年月日", u"異動年月日", u"異動予定日",
                    u"取得日", u"譲渡日", u"異動 年月日", u"就任日")


def effective_date(html_block, text):
    u"""The date the thing actually happens, from a labelled row or the prose."""
    for t in tables_in(html_block):
        cells, _ = grid_of(t)
        for row in cells:
            label = norm(row[0] if row else "")
            if any(lb in label for lb in EFFECTIVE_LABELS):
                for v in row[1:]:
                    d = jp_date(v)
                    if d:
                        return d
    for lb in EFFECTIVE_LABELS:
        i = text.find(lb)
        if i >= 0:
            d = jp_date(text[i:i + 60])
            if d:
                return d
    return None


# THE SAME FACT IS A TABLE IN ONE FILING AND A NUMBERED SENTENCE IN THE NEXT.
# There is no XBRL tagging inside 【報告内容】, and no house style either: the
# identity of an acquired subsidiary is a two-column table in one filing and
# `1 商号 : 株式会社メディックス 2 本店の所在地: …` in another, by the same
# rules on the same date. Both readers run, table first, prose second. Reading
# only the table shape loses roughly a third of these filings.

def shareholder_names(text):
    u"""[(name, direction)] — who became, or stopped being, a major holder."""
    out = []
    for pat, direction in ((u"主要株主となる(?:者|もの)", "becoming"),
                           (u"主要株主でなくなる(?:者|もの)", "ceasing")):
        # The name runs until the next thing the form prints, which is one of
        # a handful of fixed phrases. Without them the capture swallowed the
        # whole before/after table into the holder's name.
        for m in re.finditer(pat + u"\\s*[:：]?\\s*(.{1,60}?)\\s*"
                             u"(?=主要株主|所有議決権|総株主|異動前|異動後|"
                             u"[0-9０-９]+\\s*[.．]?\\s*当該|当該異動|"
                             u"[（(]\\d|[（(]注|、|$)", text):
            # The list marker travels with the name: the form writes
            # `主要株主でなくなる者 1) 3Dインベストメント…`, and the digit is
            # eaten by the label pattern, leaving a bare bracket in front of
            # the holder. Strip the punctuation a list can start with.
            name = norm(m.group(1)).strip(u" 、,()（）0123456789０１２３４５６７８９.．:：")
            if name and name not in (u"該当事項はありません",):
                out.append((name[:120], direction))
    # The phrase can appear twice — once in the heading, once in the list —
    # and a duplicate matters: two names means the before/after numbers cannot
    # be attributed to one holder, so a duplicate would silently drop them.
    seen, uniq = set(), []
    for n, d in out:
        if (n, d) not in seen:
            seen.add((n, d))
            uniq.append((n, d))
    return uniq


def _prose_pairs(text):
    u"""(votes, share) before and after, from `異動前 30,090個 異動後 0個`."""
    votes = {}
    share = {}
    for label, key in ((u"異動前", "before"), (u"異動後", "after")):
        for m in re.finditer(label + u"\\s*([0-9,]+|―|－|-)\\s*個", text):
            votes.setdefault(key, to_int(m.group(1)))
        for m in re.finditer(label + u"\\s*([0-9]+(?:[.,][0-9]+)?|―|－|-)\\s*[%％]", text):
            share.setdefault(key, pct(m.group(1) + "%"))
    if not votes and not share:
        return None
    return {"votes_before": votes.get("before"), "share_before": share.get("before"),
            "votes_after": votes.get("after"), "share_after": share.get("after")}


def _table_pairs(html_block):
    u"""The same, from the 異動前 / 異動後 rows of a table."""
    for t in tables_in(html_block):
        cells, _ = grid_of(t)
        got = {}
        for row in cells:
            label = norm(row[0] if row else "")
            if label not in (u"異動前", u"異動後"):
                continue
            key = "before" if label == u"異動前" else "after"
            for v in row[1:]:
                p = pct(v)
                if p is not None:
                    got.setdefault("share_" + key, p)
                else:
                    n = to_int(re.sub(u"個$", "", norm(v)))
                    if n is not None:
                        got.setdefault("votes_" + key, n)
        if got:
            return {"votes_before": got.get("votes_before"),
                    "share_before": got.get("share_before"),
                    "votes_after": got.get("votes_after"),
                    "share_after": got.get("share_after")}
    return None


def shareholder_rows(html_block, text):
    u"""[(name, direction, votes_before, share_before, votes_after, share_after)].

    One row per holder whose status changed. Where the filing names exactly
    one holder, the before/after numbers are attached to it; where it names
    several, the numbers cannot be attributed to one of them from the document
    alone and are left NULL rather than guessed onto the first.
    """
    pairs = _table_pairs(html_block) or _prose_pairs(text)
    names = shareholder_names(text)
    if names and len(names) == 1 and pairs:
        n, d = names[0]
        return [(n, d, pairs["votes_before"], pairs["share_before"],
                 pairs["votes_after"], pairs["share_after"])]
    if names:
        return [(n, d, None, None, None, None) for n, d in names]
    if pairs:
        return [(None, None, pairs["votes_before"], pairs["share_before"],
                 pairs["votes_after"], pairs["share_after"])]
    return []


def officer_rows(html_block):
    u"""[(name, new title, old title, shares)] from a director-change table."""
    out = []
    for t in tables_in(html_block):
        cells, _ = grid_of(t)
        if not cells:
            continue
        head = [norm(c) for c in cells[0]]
        if not any(u"氏名" in c for c in head):
            continue
        ni = next((i for i, c in enumerate(head) if u"氏名" in c), 0)
        new_i = next((i for i, c in enumerate(head) if u"新役職" in c), None)
        old_i = next((i for i, c in enumerate(head) if u"現役職" in c or u"旧役職" in c), None)
        pos_i = next((i for i, c in enumerate(head) if c.strip() == u"役職名"), None)
        sh_i = next((i for i, c in enumerate(head) if u"所有" in c and u"株式" in c), None)
        seen = set()
        for row in cells[1:]:
            name = norm(row[ni]) if ni < len(row) else ""
            if not name or name in seen:
                continue
            seen.add(name)
            out.append((
                name[:80],
                norm(row[new_i])[:60] if new_i is not None and new_i < len(row)
                else (norm(row[pos_i])[:60] if pos_i is not None and pos_i < len(row) else None),
                norm(row[old_i])[:60] if old_i is not None and old_i < len(row) else None,
                to_int(row[sh_i]) if sh_i is not None and sh_i < len(row) else None))
        if out:
            break
    return out


# Longest label first: searching for 資本金 inside `資本金の額 : 93百万円` matches
# the prefix and then looks for a colon that is three characters further on.
PARTY_LABELS = ((u"本店の所在地", "location"), (u"代表者の氏名", "representative"),
                (u"資本金の額", "capital"), (u"純資産の額", "net_assets"),
                (u"総資産の額", "total_assets"), (u"事業の内容", "business"),
                (u"商号", "name"), (u"名称", "name"), (u"所在地", "location"),
                (u"住所", "location"), (u"資本金", "capital"))


def party_from_table(html_block):
    u"""The counterparty's identity card, as a vertical label/value table."""
    for t in tables_in(html_block):
        cells, _ = grid_of(t)
        got = {}
        for row in cells:
            label = norm(row[0] if row else "").replace(" ", "")
            value = next((norm(v) for v in row[1:] if norm(v)), "")
            if not value:
                continue
            for jp, key in PARTY_LABELS:
                if label == jp:
                    got.setdefault(key, value)
                    break
        if "name" in got:
            return got
    return None


# THE LABEL MUST BE NUMBERED. The section heading that introduces this list
# contains every label word in one breath — `当該異動に係る特定子会社の名称、
# 住所、代表者の氏名、資本金及び事業の内容` — so a pattern that accepts a bare
# label reads the heading as the company's name. In the list itself every
# label is numbered (`1 商号 :`, `2住所`), and requiring that digit is what
# separates the data from the sentence describing it.
PROSE_RE = (u"[0-9０-９]\\s*%s\\s*[:：]?\\s*(.{1,140}?)"
            u"(?=\\s*[0-9０-９]\\s*(?:商号|名称|本店の所在地|住所|所在地|"
            u"代表者の氏名|資本金の額|資本金|純資産の額|総資産の額|事業の内容)|"
            u"\\s*[（(]\\d|$)")


def party_from_prose(text):
    u"""The same identity card written as `1 商号 : X 2 本店の所在地: Y`."""
    got = {}
    for jp, key in PARTY_LABELS:
        if key in got:
            continue
        m = re.search(PROSE_RE % jp, text)
        if m:
            v = norm(m.group(1)).strip(u" 、,")
            if v and v not in (u"―", u"－", "-"):
                got[key] = v
    return got if got.get("name") else None


def parse(blob, doc_type):
    html = honbun(blob)
    bl = blocks(html)
    evs = event_blocks(bl)
    resolution, items, reason_text = reason_facts(bl, html)
    if not evs and not reason_text:
        raise NotAnEvent("no reason and no event block")

    name, inner = (evs[0] if evs else (None, ""))
    etype, family = EVENTS.get(name, (slug_of(name) if name else "unclassified",
                                      "text"))
    body_text = norm(re.sub(r"<[^>]+>", " ", inner)) if inner else \
        section_text(bl, html, (), (u"【報告内容】",))

    row = {"event_type": etype, "event_family": family, "event_block": name,
           "article_items": items, "resolution_date": resolution,
           "event_count": len(evs),
           "effective_date": effective_date(inner, body_text),
           "summary": (body_text or None) and body_text[:1200]}

    row["shareholders"] = []
    row["officers"] = []
    row["parties"] = []
    if family == "shareholder":
        row["shareholders"] = shareholder_rows(inner, body_text)
    elif family == "officer":
        row["officers"] = officer_rows(inner)
    elif family in ("deal", "subsidiary"):
        p = party_from_table(inner) or party_from_prose(body_text)
        if p:
            row["parties"] = [("counterparty" if family == "deal" else "subsidiary", p)]
    # A parent or subsidiary change also states the holding before and after,
    # in the same shape a major-shareholder change does; it is the same fact
    # about the same company and belongs in the same table.
    if family in ("subsidiary", "shareholder") and not row["shareholders"]:
        row["shareholders"] = shareholder_rows(inner, body_text)
    return row


# -------------------------------------------------------------------- gates

def gates(row):
    u"""(problems, checked, passed).

    There is no arithmetic identity in an extraordinary report to check, so
    the gates are about the classification being usable rather than the
    numbers reconciling: a filing must be classified, and a filing whose type
    promises structured detail must have produced some. A `deal` row with no
    counterparty is the failure mode that would quietly empty this dataset.
    """
    problems, checked, passed = [], 0, 0

    checked += 1
    if row.get("event_block"):
        passed += 1
    else:
        problems.append("G1 no event block: type could not be tagged")

    fam = row.get("event_family")
    if fam in ("shareholder", "officer", "deal", "subsidiary"):
        checked += 1
        got = (row.get("shareholders") or row.get("officers") or row.get("parties"))
        if got:
            passed += 1
        else:
            problems.append("G2 %s event yielded no detail rows" % fam)
    return problems, checked, passed


SCHEMA_SQL = u"""
CREATE TABLE IF NOT EXISTS eq_event_filings (
    doc_id VARCHAR PRIMARY KEY, doc_type VARCHAR, edinet_code VARCHAR,
    sec_code VARCHAR, filer_name VARCHAR, filed_date DATE,
    event_type VARCHAR, event_family VARCHAR, event_block VARCHAR,
    event_count INTEGER, article_items VARCHAR,
    resolution_date DATE, effective_date DATE, summary VARCHAR,
    sha256 VARCHAR, parser_version VARCHAR, status VARCHAR, detail VARCHAR,
    gate_checked INTEGER, gate_passed INTEGER);
CREATE TABLE IF NOT EXISTS eq_event_shareholders (
    doc_id VARCHAR, ord INTEGER, holder_name VARCHAR, direction VARCHAR,
    votes_before BIGINT, share_before DOUBLE,
    votes_after BIGINT, share_after DOUBLE);
CREATE TABLE IF NOT EXISTS eq_event_officers (
    doc_id VARCHAR, ord INTEGER, name VARCHAR, new_title VARCHAR,
    old_title VARCHAR, shares_held BIGINT);
CREATE TABLE IF NOT EXISTS eq_event_parties (
    doc_id VARCHAR, ord INTEGER, role VARCHAR, name VARCHAR, location VARCHAR,
    representative VARCHAR, business VARCHAR,
    capital_yen BIGINT, capital_unit VARCHAR,
    net_assets_yen BIGINT, total_assets_yen BIGINT);
"""

COLS = ["doc_id", "doc_type", "edinet_code", "sec_code", "filer_name",
        "filed_date", "event_type", "event_family", "event_block",
        "event_count", "article_items", "resolution_date", "effective_date",
        "summary", "sha256", "parser_version", "status", "detail",
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
            if (r.get("status") == "ok" and r.get("doc_type") in EVENT_TYPES
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
    since, have = (incremental_window(args.db, EXTRACTOR, "eq_event_filings")
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
        if doc_type not in EVENT_TYPES or m.get("fundCode"):
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
            return t, parse(blob, doc_type), sha, None
        except (NotAnEvent, NoHonbun) as e:
            return t, None, sha, ("no_event", str(e)[:120])
        except Exception as e:                                    # noqa: BLE001
            return t, None, sha, ("failed", "%s: %s" % (type(e).__name__, str(e)[:120]))

    stats = defaultdict(int)
    g_checked = g_passed = n_sh = n_of = n_pa = done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(fetch_and_parse, t) for t in targets]
        for fut in as_completed(futures):
            (doc_id, rec, m, doc_type), row, sha, err = fut.result()
            done += 1
            if done % 2000 == 0:
                print("  %d/%d filings" % (done, len(targets)))
            base = dict.fromkeys(COLS)
            d = m.get("submitDateTime") or rec.get("date")
            base.update({"doc_id": doc_id, "doc_type": doc_type, "sha256": sha,
                         "parser_version": PARSER_VERSION,
                         "edinet_code": m.get("edinetCode"),
                         "sec_code": sec_code_of(m),
                         "filer_name": rec.get("filer") or m.get("filerName"),
                         "filed_date": dt.date.fromisoformat(str(d)[:10]) if d else None,
                         "gate_checked": 0, "gate_passed": 0})
            for t in ("eq_event_filings", "eq_event_shareholders",
                      "eq_event_officers", "eq_event_parties"):
                con.execute("DELETE FROM %s WHERE doc_id = ?" % t, [doc_id])
            if err:
                base["status"], base["detail"] = err
                stats[base["status"]] += 1
                con.execute("INSERT INTO eq_event_filings VALUES (%s)"
                            % ",".join(["?"] * len(COLS)), [base[c] for c in COLS])
                continue
            sh = row.pop("shareholders")
            of = row.pop("officers")
            pa = row.pop("parties")
            base.update({k: v for k, v in row.items() if k in COLS})
            problems, checked, passed = gates(dict(row, shareholders=sh,
                                                   officers=of, parties=pa))
            g_checked += checked
            g_passed += passed
            base["gate_checked"] = checked
            base["gate_passed"] = passed
            base["status"] = "partial" if problems else "clean"
            base["detail"] = "; ".join(problems[:3]) or None
            stats[base["status"]] += 1
            stats["type:" + base["event_type"]] += 1
            con.execute("INSERT INTO eq_event_filings VALUES (%s)"
                        % ",".join(["?"] * len(COLS)), [base[c] for c in COLS])
            if sh:
                con.executemany(
                    "INSERT INTO eq_event_shareholders VALUES (?,?,?,?,?,?,?,?)",
                    [(doc_id, i) + tuple(r) for i, r in enumerate(sh)])
                n_sh += len(sh)
            if of:
                con.executemany("INSERT INTO eq_event_officers VALUES (?,?,?,?,?,?)",
                                [(doc_id, i, n, nt, ot, s)
                                 for i, (n, nt, ot, s) in enumerate(of)])
                n_of += len(of)
            if pa:
                rows = []
                for i, (role, p) in enumerate(pa):
                    cap, unit = money(p.get("capital"))
                    na, _ = money(p.get("net_assets"))
                    ta, _ = money(p.get("total_assets"))
                    rows.append((doc_id, i, role, (p.get("name") or "")[:160] or None,
                                 (p.get("location") or "")[:200] or None,
                                 (p.get("representative") or "")[:120] or None,
                                 (p.get("business") or "")[:200] or None,
                                 cap, unit, na, ta))
                con.executemany(
                    "INSERT INTO eq_event_parties VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
                n_pa += len(rows)
    con.close()
    record_run(args.db, EXTRACTOR, through, len(filings), PARSER_VERSION,
               back_to=catch_up_floor)
    if not args.no_compact:
        compact(args.db)
    top = {k: v for k, v in stats.items() if not k.startswith("type:")}
    print("filings: %s" % top)
    types = sorted(((v, k[5:]) for k, v in stats.items() if k.startswith("type:")),
                   reverse=True)
    print("event types: %s" % ", ".join("%s=%d" % (k, v) for v, k in types[:14]))
    print("detail rows: %d shareholder, %d officer, %d party" % (n_sh, n_of, n_pa))
    if g_checked:
        print("gates: %d/%d = %.1f%%" % (g_passed, g_checked,
                                         100.0 * g_passed / g_checked))
    print("wrote", os.path.normpath(args.db))


if __name__ == "__main__":
    main()
