# -*- coding: utf-8 -*-
u"""TDnet — the fast tape and its earnings summaries, parser `td-1`.

WHY THIS ONE MATTERS MOST
-------------------------
TDnet is the Tokyo Stock Exchange's timely-disclosure wire. It keeps
disclosures public for about 31 DAYS and then deletes them. There is no
backfill, no API, and no second source. `tdnet_capture.py` has been banking
the wire since 2026-07-10, which makes our archive the only copy of it that
exists outside the exchange — and the only part of this platform that cannot
be reconstructed if it is lost.

It is also the fast half of the record. A company files its 決算短信 here
roughly six weeks before the statutory report reaches EDINET, and the 短信
carries something EDINET never does at all: MANAGEMENT'S OWN FORECAST for the
current year, with an upper and a lower bound, revised whenever the company
changes its mind.

WHAT THIS WRITES
----------------
  eq_tdnet_items     every disclosure on the wire — timestamp, company, title,
                     whether it carried XBRL, and a coarse kind read from the
                     title. 1,627 items on a single August day, most of which
                     will never be parsed further; the index is the point.
  eq_tdnet_filings   one row per earnings release whose Summary XBRL we read.
  eq_tdnet_facts     the Summary, long: element, context, and the context
                     decoded into columns.

DECODING THE CONTEXT IS THE WHOLE JOB
-------------------------------------
A TDnet context stacks four independent facts into one string:

    CurrentYearDuration_ConsolidatedMember_ForecastMember
    CurrentAccumulatedQ1Duration_ConsolidatedMember_ResultMember
    CurrentYearDuration_YearEndMember_NonConsolidatedMember_LowerMember

  period     CurrentYear · CurrentAccumulatedQ1..Q3 · PriorYear · NextYear
  nature     Result (what happened) · Forecast · Upper · Lower (what is
             promised) — the single most important distinction in the file,
             because an actual and a forecast are the same element in the same
             unit and a mixed cross-section is worthless
  basis      Consolidated · NonConsolidated
  sub-period FirstQuarter · SecondQuarter · ThirdQuarter · YearEnd · Annual,
             used by the dividend rows

Left as an opaque string, every query over this table would need a regex and
would get it subtly wrong. They are parsed into columns once, here.

GATES
-----
  G1  a forecast range must not be inverted: Upper >= Lower for the same
      element, period and basis.
  G2  a filing this parser accepted must carry at least one numeric result
      fact for the current period, otherwise it is not an earnings release we
      actually read and says so.

Usage (from observatory/equity/):
    ../.venv/bin/python tdnet_extract.py --limit 5           # 5 days
    ../.venv/bin/python tdnet_extract.py --all --source s3 --new-only  # nightly
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

from extract import DB_PATH, record_run, compact
from edinet_honbun import norm

PARSER_VERSION = "td-1"
EXTRACTOR = "tdnet"

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_ROOT = os.environ.get(
    "TDNET_ARCHIVE_ROOT", os.path.join(HERE, "data", "raw", "tdnet"))

# A late disclosure can be archived a day or two after its own date, and the
# capture job re-scans a trailing window. Re-reading a few days each run costs
# nothing (the rows are replaced) and is what stops a gap forming.
LOOKBACK_DAYS = 5


# ------------------------------------------------------------------ sources

class LocalTdnet(object):
    name = "local"

    def days(self):
        d = os.path.join(LOCAL_ROOT, "lists")
        if not os.path.isdir(d):
            return []
        return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))

    def listing(self, day):
        with open(os.path.join(LOCAL_ROOT, "lists", day + ".json"), "rb") as f:
            return json.loads(f.read().decode("utf-8", "ignore"))

    def doc(self, day, name):
        with open(os.path.join(LOCAL_ROOT, "docs", day, name), "rb") as f:
            return f.read()


class S3Tdnet(object):
    name = "s3"

    def __init__(self):
        import boto3
        self.bucket = os.environ["EDINET_S3_BUCKET"]
        self.c = boto3.client(
            "s3",
            endpoint_url=os.environ["EDINET_S3_ENDPOINT"],
            aws_access_key_id=os.environ["EDINET_S3_KEY_ID"],
            aws_secret_access_key=os.environ["EDINET_S3_SECRET"],
            region_name=os.environ.get("EDINET_S3_REGION", "auto"))

    def days(self):
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": "tdnet/lists/"}
            if token:
                kw["ContinuationToken"] = token
            r = self.c.list_objects_v2(**kw)
            for o in r.get("Contents") or []:
                n = o["Key"].rsplit("/", 1)[-1]
                if n.endswith(".json"):
                    out.append(n[:-5])
            if not r.get("IsTruncated"):
                return sorted(out)
            token = r.get("NextContinuationToken")

    def listing(self, day):
        b = self.c.get_object(Bucket=self.bucket,
                              Key="tdnet/lists/%s.json" % day)["Body"].read()
        return json.loads(b.decode("utf-8", "ignore"))

    def doc(self, day, name):
        return self.c.get_object(Bucket=self.bucket,
                                 Key="tdnet/docs/%s/%s" % (day, name))["Body"].read()


# ------------------------------------------------------------- the wire index

# Coarse, title-based, and honestly so: TDnet has no disclosure-type code, only
# a headline the company wrote. This is for filtering the tape, never for
# counting events — a company that titles a buyback resolution unusually is
# simply `other`, and the title is stored so nothing is lost.
KINDS = ((u"決算短信", "earnings"),
         (u"業績予想", "forecast-revision"),
         (u"業績の修正", "forecast-revision"),
         (u"配当予想", "dividend-forecast"),
         (u"配当", "dividend"),
         (u"自己株式の取得", "buyback"),
         (u"自己株式", "treasury-shares"),
         (u"公開買付", "tender-offer"),
         (u"株式分割", "share-split"),
         (u"新株予約権", "stock-options"),
         (u"第三者割当", "third-party-allotment"),
         (u"株主優待", "shareholder-perk"),
         (u"人事", "personnel"),
         (u"異動", "change"),
         (u"説明資料", "presentation"),
         (u"訂正", "correction"))


def kind_of(title):
    t = norm(title or "")
    for jp, en in KINDS:
        if jp in t:
            return en
    return "other"


def sec4(code):
    u"""TDnet writes a five-digit code with a trailing 0; the market uses four."""
    c = (code or "").strip()
    if len(c) == 5 and c.endswith("0"):
        return c[:4]
    return c[:4] or None


# ------------------------------------------------------------- summary XBRL

# A FACT THE COMPANY DID NOT GIVE IS SELF-CLOSING, AND MUST NOT BE READ.
# `<ix:nonFraction ... xsi:nil="true" />` means "no number". Matched with a
# lazy `(.*?)</ix:nonFraction>` the pattern sails past the slash and captures
# the text of the NEXT tagged fact, so an absent next-year forecast quietly
# takes its neighbour's digits: Nihon Ski Resort's blank guidance came out as
# 15.8 yen against 11.5bn of actual sales. Refusing a tag whose attributes end
# in `/` is the whole fix. Same trap as EDINET's instance documents; see
# edinet_honbun.FACT_RE.
IX_RE = re.compile(
    r'<ix:non(Fraction|Numeric)\s+([^>]*?)(?<!/)>(.*?)</ix:non(?:Fraction|Numeric)>',
    re.S)
ATTR = lambda a, n: (re.search(n + r'="([^"]*)"', a) or [None, None])[1]  # noqa: E731

PERIODS = (("CurrentAccumulatedQ1", "q1-ytd"), ("CurrentAccumulatedQ2", "q2-ytd"),
           ("CurrentAccumulatedQ3", "q3-ytd"), ("CurrentQuarter", "quarter"),
           ("CurrentYear", "year"), ("NextYear", "next-year"),
           ("PriorAccumulatedQ1", "prior-q1-ytd"),
           ("PriorAccumulatedQ2", "prior-q2-ytd"),
           ("PriorAccumulatedQ3", "prior-q3-ytd"),
           ("PriorYear", "prior-year"))
NATURES = (("ResultMember", "result"), ("ForecastMember", "forecast"),
           ("UpperMember", "forecast-upper"), ("LowerMember", "forecast-lower"))
SUBPERIODS = (("FirstQuarterMember", "q1"), ("SecondQuarterMember", "q2"),
              ("ThirdQuarterMember", "q3"), ("YearEndMember", "year-end"),
              ("AnnualMember", "annual"))


def decode_context(ctx):
    u"""(period, kind, nature, basis, sub_period) from a stacked context id."""
    period = next((v for k, v in PERIODS if ctx.startswith(k)), None)
    kind = "instant" if "Instant" in ctx else ("duration" if "Duration" in ctx else None)
    nature = next((v for k, v in NATURES if k in ctx), None)
    if "NonConsolidatedMember" in ctx:
        basis = "parent"
    elif "ConsolidatedMember" in ctx:
        basis = "consolidated"
    else:
        basis = None
    sub = next((v for k, v in SUBPERIODS if k in ctx), None)
    return period, kind, nature, basis, sub


NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


def summary_facts(blob):
    u"""(facts, header) from the Summary section of a 決算短信 XBRL package.

    facts: (ord, element, context, period, period_kind, nature, basis,
            sub_period, unit, value)
    """
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        members = [n for n in z.namelist()
                   if "/Summary/" in n and n.endswith("-ixbrl.htm")]
        if not members:
            raise ValueError("no Summary ixbrl in package")
        html = z.read(sorted(members)[0]).decode("utf-8", "ignore")

    facts, header, seen = [], {}, set()
    for i, m in enumerate(IX_RE.finditer(html)):
        numeric, attrs, inner = m.group(1) == "Fraction", m.group(2), m.group(3)
        name = ATTR(attrs, "name")
        ctx = ATTR(attrs, "contextRef")
        if not name:
            continue
        local = name.split(":")[-1]
        text = norm(re.sub(r"<[^>]+>", " ", inner))
        if local in ("CompanyName", "SecuritiesCode", "DocumentName",
                     "FilingDate", "URL", "NameRepresentative"):
            header.setdefault(local, text)
        if not numeric:
            continue
        if ATTR(attrs, "xsi:nil") == "true":
            continue                     # explicitly no value; never a zero
        raw = text.replace(",", "").replace(u"△", "-").replace(u"▲", "-")
        sign = ATTR(attrs, "sign")
        if not NUM_RE.match(raw):
            continue                     # "－", "-", blank: missing, never zero
        value = float(raw)
        if sign == "-":
            value = -value
        scale = ATTR(attrs, "scale")
        if scale:
            try:
                value *= 10 ** int(scale)
            except ValueError:
                pass
        key = (local, ctx)
        if key in seen:
            continue
        seen.add(key)
        period, pkind, nature, basis, sub = decode_context(ctx or "")
        facts.append((i, local, ctx, period, pkind, nature, basis, sub,
                      ATTR(attrs, "unitRef"), value))
    return facts, header


DOC_PERIOD = ((u"第１四半期", "q1"), (u"第1四半期", "q1"),
              (u"第２四半期", "q2"), (u"第2四半期", "q2"), (u"中間期", "q2"),
              (u"第３四半期", "q3"), (u"第3四半期", "q3"))


def doc_period(document_name, title):
    t = norm((document_name or "") + " " + (title or ""))
    for jp, en in DOC_PERIOD:
        if jp in t:
            return en
    return "full-year" if u"決算短信" in t else None


# -------------------------------------------------------------------- gates

def gates(facts):
    problems, checked, passed = [], 0, 0

    ranges = {}
    for _, el, _, period, _, nature, basis, sub, _, val in facts:
        if nature in ("forecast-upper", "forecast-lower"):
            ranges.setdefault((el, period, basis, sub), {})[nature] = val
    for key, pair in ranges.items():
        if "forecast-upper" in pair and "forecast-lower" in pair:
            checked += 1
            if pair["forecast-upper"] >= pair["forecast-lower"]:
                passed += 1
            else:
                problems.append("G1 %s %s forecast upper %.0f < lower %.0f"
                                % (key[0], key[1], pair["forecast-upper"],
                                   pair["forecast-lower"]))
    checked += 1
    if any(n == "result" and p and p.startswith(("q", "year"))
           for _, _, _, p, _, n, _, _, _, _ in facts):
        passed += 1
    else:
        problems.append("G2 no current-period result facts")
    return problems, checked, passed


SCHEMA_SQL = u"""
CREATE TABLE IF NOT EXISTS eq_tdnet_items (
    disclosed_on DATE, disclosed_at VARCHAR, ord INTEGER,
    sec_code VARCHAR, title VARCHAR, kind VARCHAR,
    pdf_name VARCHAR, xbrl_name VARCHAR,
    PRIMARY KEY (disclosed_on, ord));
CREATE TABLE IF NOT EXISTS eq_tdnet_filings (
    doc_key VARCHAR PRIMARY KEY, disclosed_on DATE, disclosed_at VARCHAR,
    sec_code VARCHAR, company_name VARCHAR, title VARCHAR,
    document_name VARCHAR, period VARCHAR,
    sha256 VARCHAR, parser_version VARCHAR, status VARCHAR, detail VARCHAR,
    facts INTEGER, gate_checked INTEGER, gate_passed INTEGER);
CREATE TABLE IF NOT EXISTS eq_tdnet_facts (
    doc_key VARCHAR, ord INTEGER, element VARCHAR, context VARCHAR,
    period VARCHAR, period_kind VARCHAR, nature VARCHAR, basis VARCHAR,
    sub_period VARCHAR, unit VARCHAR, value DOUBLE);
"""

FILING_COLS = 15


def entries_of(payload):
    return payload if isinstance(payload, list) else (
        payload.get("items") or payload.get("results") or [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("local", "s3"), default="local")
    ap.add_argument("--all", action="store_true", help="kept for symmetry")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, help="process at most this many days")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--new-only", action="store_true",
                    help="only archive days after the recorded watermark, less "
                         "a short lookback; what the nightly refresh uses.")
    ap.add_argument("--no-compact", action="store_true")
    args = ap.parse_args()

    src = S3Tdnet() if args.source == "s3" else LocalTdnet()
    days = src.days()
    if not days:
        print("no TDnet archive days found (source=%s)" % src.name)
        return 0

    con = duckdb.connect(args.db)
    con.execute(SCHEMA_SQL)
    since = None
    if args.new_only:
        row = con.execute("SELECT through_date FROM eq_extract_runs "
                          "WHERE extractor = ?", [EXTRACTOR]).fetchone()
        if row and row[0]:
            since = (row[0] - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
            days = [d for d in days if d >= since]
            print("incremental: %d archive days at or after %s" % (len(days), since))
    if args.limit:
        days = days[-args.limit:]
    through = max(src.days())
    print("days to read: %d (source=%s)" % (len(days), src.name))

    n_items = n_fil = n_facts = 0
    stats = defaultdict(int)
    g_checked = g_passed = 0

    for day in days:
        try:
            payload = src.listing(day)
        except Exception as e:                                    # noqa: BLE001
            print("  %s list unreadable: %s" % (day, str(e)[:90]))
            stats["day-unreadable"] += 1
            continue
        entries = entries_of(payload)
        con.execute("DELETE FROM eq_tdnet_items WHERE disclosed_on = ?", [day])
        rows = []
        for i, it in enumerate(entries):
            rows.append((day, it.get("time"), i, sec4(it.get("sec_code")),
                         (it.get("title") or "")[:300], kind_of(it.get("title")),
                         it.get("pdf"), it.get("xbrl")))
        if rows:
            con.executemany(
                "INSERT INTO eq_tdnet_items VALUES (?,?,?,?,?,?,?,?)", rows)
            n_items += len(rows)

        # Only earnings releases carry a Summary worth parsing; the rest of the
        # XBRL on the wire is dividend and buyback boilerplate whose numbers are
        # already in the title-level index.
        targets = [it for it in entries
                   if it.get("xbrl") and kind_of(it.get("title")) == "earnings"]

        def fetch(it):
            try:
                blob = src.doc(day, it["xbrl"])
            except Exception as e:                                # noqa: BLE001
                return it, None, None, "fetch: %s" % str(e)[:110]
            sha = hashlib.sha256(blob).hexdigest()
            try:
                return it, summary_facts(blob), sha, None
            except Exception as e:                                # noqa: BLE001
                return it, None, sha, "%s: %s" % (type(e).__name__, str(e)[:110])

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for fut in as_completed([ex.submit(fetch, it) for it in targets]):
                it, parsed, sha, err = fut.result()
                doc_key = it["xbrl"].rsplit(".", 1)[0]
                con.execute("DELETE FROM eq_tdnet_filings WHERE doc_key = ?", [doc_key])
                con.execute("DELETE FROM eq_tdnet_facts WHERE doc_key = ?", [doc_key])
                base = [doc_key, day, it.get("time"), sec4(it.get("sec_code"))]
                if err:
                    stats["failed"] += 1
                    con.execute("INSERT INTO eq_tdnet_filings VALUES (%s)"
                                % ",".join(["?"] * FILING_COLS),
                                base + [None, (it.get("title") or "")[:300], None,
                                        None, sha, PARSER_VERSION, "failed",
                                        err, 0, 0, 0])
                    continue
                facts, header = parsed
                problems, checked, passed = gates(facts)
                g_checked += checked
                g_passed += passed
                status = "partial" if problems else "clean"
                stats[status] += 1
                con.execute(
                    "INSERT INTO eq_tdnet_filings VALUES (%s)"
                    % ",".join(["?"] * FILING_COLS),
                    base + [header.get("CompanyName"),
                            (it.get("title") or "")[:300],
                            header.get("DocumentName"),
                            doc_period(header.get("DocumentName"), it.get("title")),
                            sha, PARSER_VERSION, status,
                            "; ".join(problems[:3]) or None,
                            len(facts), checked, passed])
                if facts:
                    con.executemany(
                        "INSERT INTO eq_tdnet_facts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        [(doc_key,) + f for f in facts])
                    n_facts += len(facts)
                n_fil += 1
        print("  %s: %d items, %d earnings" % (day, len(rows), len(targets)))

    con.close()
    record_run(args.db, EXTRACTOR, dt.date.fromisoformat(through),
               n_items, PARSER_VERSION)
    if not args.no_compact:
        compact(args.db)
    print("items: %d | earnings filings: %d %s | facts: %d"
          % (n_items, n_fil, dict(stats), n_facts))
    if g_checked:
        print("gates: %d/%d = %.1f%%" % (g_passed, g_checked,
                                         100.0 * g_passed / g_checked))
    print("wrote", os.path.normpath(args.db))


if __name__ == "__main__":
    main()
