# -*- coding: utf-8 -*-
"""M3/M4 — production cross-shareholding extractor.

Reads annual-report CSV packages (EDINET type=5), extracts the 政策保有株式
tables, entity-matches held names against the EDINET code list, validates
against the filings' own tagged totals, and writes the eq_* tables into a
dedicated DuckDB file (separate from the macro product's DB; one writer at a
time — this runs offline, the API reads read-only).

Two sources. `--source local` reads the laptop archive; `--source s3` reads the
cloud bucket, which is the authoritative one (the laptop copy is a partial
backup). Multi-year needs no schema change: each filing is its own doc_id with
its own period_end, so five fiscal years is simply five times the filings.

Usage:
    python extract.py                                 # financial sector, local
    python extract.py --all                           # every archived filer, local
    python extract.py --all --source s3               # FULL UNIVERSE, 5 years
    python extract.py --all --source s3 --workers 16  # tune fetch concurrency

Inherits the M1 lessons (see m1/README.md): Deemed-table context collision,
element-name variants by filer structure, purpose/reciprocity element families,
filing-era names needing an alias map, missing values stay missing.
Python 3.9.
"""
import argparse
import csv
import glob
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(HERE, "data", "raw", "edinet")
CODELIST = os.path.join(HERE, "m1", "EdinetcodeDlInfo.csv")
DB_PATH = os.path.join(HERE, "..", "observatory", "data", "equity.duckdb")
PARSER_VERSION = "m4-1"

FIN_INDUSTRIES = ("銀行業", "保険業", "証券", "その他金融業")

DETAIL_MARK = "DetailsOfSpecifiedInvestmentEquitySecurities"
VARIANTS = [("SecondLargestHoldingCompany", "second_largest"),
            ("LargestHoldingCompany", "largest"),
            ("ReportingCompany", "reporting")]


def variant_of(local):
    for suffix, label in VARIANTS:
        if suffix in local:
            return label
    return "unspecified"


def field_of(local):
    for prefix, label in [("NameOfSecurities", "name"),
                          ("NumberOfSharesHeld", "shares"),
                          ("BookValue", "book_value"),
                          ("PurposeOfShareholding", "purpose"),
                          ("WhetherIssuer", "reciprocal")]:
        if local.startswith(prefix):
            return label
    return None


# ---- entity naming (M1 lessons) -------------------------------------------
LEGAL = re.compile(r"(株式会社|株式會社|（株）|\(株\)|ホールディングス|グループ本社)")
# footnote markers filers glue onto names: (※5), （注）３, （注４）, (注)4 …
FOOTNOTE = re.compile(r"[（(]\s*(?:※|注)?\s*[0-9０-９]+\s*[）)]|[（(]注[）)][0-9０-９]*")
ALIASES = {  # filing-era base name -> current registered base name (eq_name_map seed)
    # NOTE: hand-curation works at sector scale; M4 (3,829 filers) needs a
    # systematic rename feed keyed on securities codes instead.
    "日本碍子": "NGK",
    "大阪ガス": "大阪瓦斯",
    "パナソニックHD": "パナソニック",
    "第一生命": "第一ライフグループ",
    "サッポロ": "サッポロビール",
    "南海電気鉄道": "NANKAI",
    "上新電機": "Joshin",
    "大和冷機工業": "だいわ",
}
KYUJITAI = str.maketrans("會條檢國櫻眞壽鐵髙﨑", "会条検国桜真寿鉄高崎")


def norm(s):
    import html
    s = html.unescape(s or "")               # filings carry &amp; etc.
    s = unicodedata.normalize("NFKC", s).strip()
    s = FOOTNOTE.sub("", s)
    return s.replace(" ", "").replace("　", "").translate(KYUJITAI)


def base_name(s):
    b = LEGAL.sub("", norm(s))
    b = ALIASES.get(b, b)
    return LEGAL.sub("", b)


def is_foreign(name):
    if not re.search(r"[぀-ヿ一-鿿]", name):
        return True
    return bool(re.search(r"(有限公司|股份有限公司|銀行有限公司)", name))


def load_codelist():
    text = open(CODELIST, "rb").read().decode("cp932")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[1]
    return [dict(zip(header, r)) for r in rows[2:] if len(r) == len(header)]


def build_index(codelist):
    idx = {}
    for d in codelist:
        nm = d.get("提出者名", "")
        listed = d.get("上場区分", "") == "上場"
        for key in {norm(nm), base_name(nm)}:
            if key and (key not in idx or (listed and idx[key][2] != "上場")):
                idx[key] = (d.get("ＥＤＩＮＥＴコード", ""),
                            (d.get("証券コード", "") or "")[:4],
                            d.get("上場区分", ""), nm)
    return idx


# ---- filing discovery ------------------------------------------------------
class LocalSource(object):
    """The laptop archive: manifest.jsonl + whatever daily lists it holds."""

    name = "local"

    def filings(self):
        out = {}
        for line in open(os.path.join(ARCHIVE, "manifest.jsonl"), encoding="utf-8"):
            r = json.loads(line)
            if r.get("status") == "ok" and r.get("doc_type") == "120" and r.get("dl_type") == "5":
                out[r["doc_id"]] = r
        return out

    def list_metadata(self):
        meta = {}
        for f in glob.glob(os.path.join(ARCHIVE, "lists", "*.json")):
            for r in json.load(open(f)).get("results") or []:
                meta[r["docID"]] = r
        return meta

    def read_zip(self, doc_id, date):
        with open(os.path.join(ARCHIVE, "docs", date, doc_id + "_t5.zip"), "rb") as f:
            return f.read()


class S3Source(object):
    """The cloud bucket — authoritative, and the only copy with all 5 years.

    Filings are discovered from the object listing (one pass over docs/, far
    cheaper than reading 128k per-document manifest objects). The daily lists
    carry edinetCode/secCode/periodEnd and are cached locally on first use,
    since every future extractor wants them too.
    """

    name = "s3"

    def __init__(self, workers=12):
        import boto3
        from botocore.config import Config
        self.bucket = os.environ["EDINET_S3_BUCKET"]
        self.c = boto3.client(
            "s3",
            endpoint_url=os.environ["EDINET_S3_ENDPOINT"],
            aws_access_key_id=os.environ["EDINET_S3_KEY_ID"],
            aws_secret_access_key=os.environ["EDINET_S3_SECRET"],
            region_name=os.environ.get("EDINET_S3_REGION", "auto"),
            config=Config(max_pool_connections=workers + 4,
                          retries={"max_attempts": 5, "mode": "standard"}))
        self.workers = workers

    def _keys(self, prefix):
        token = None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": 1000}
            if token:
                kw["ContinuationToken"] = token
            r = self.c.list_objects_v2(**kw)
            for o in r.get("Contents") or []:
                yield o["Key"]
            if not r.get("IsTruncated"):
                return
            token = r.get("NextContinuationToken")

    def filings(self):
        """doc_id -> {date} for every archived CSV package. Type filtering is
        done later against the daily list, which is the authority on doc type."""
        out = {}
        for key in self._keys("docs/"):
            parts = key.split("/")                     # docs/YYYY-MM-DD/DOCID_t5.zip
            if len(parts) != 3 or not parts[2].endswith("_t5.zip"):
                continue
            out[parts[2][:-len("_t5.zip")]] = {"date": parts[1]}
        return out

    def list_metadata(self):
        cache = os.path.join(ARCHIVE, "lists")
        os.makedirs(cache, exist_ok=True)
        remote = [k for k in self._keys("lists/") if k.endswith(".json")]
        todo = [k for k in remote if not os.path.exists(os.path.join(cache, k.split("/")[-1]))]
        if todo:
            print("caching %d daily lists from the bucket…" % len(todo))

            def grab(key):
                blob = self.c.get_object(Bucket=self.bucket, Key=key)["Body"].read()
                path = os.path.join(cache, key.split("/")[-1])
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(blob)
                os.replace(tmp, path)

            with ThreadPoolExecutor(max_workers=self.workers) as ex:
                for i, _ in enumerate(ex.map(grab, todo), 1):
                    if i % 200 == 0:
                        print("  %d/%d" % (i, len(todo)))
        meta = {}
        for key in remote:
            path = os.path.join(cache, key.split("/")[-1])
            try:
                for r in json.load(open(path)).get("results") or []:
                    meta[r["docID"]] = r
            except ValueError:
                continue
        return meta

    def read_zip(self, doc_id, date):
        key = "docs/%s/%s_t5.zip" % (date, doc_id)
        return self.c.get_object(Bucket=self.bucket, Key=key)["Body"].read()


# ---- per-filing extraction (M1 core, hardened) -----------------------------
def parse_filing(blob):
    """Return (holdings rows, tagged totals, warnings) for a CSV-package zip."""
    with zipfile.ZipFile(io.BytesIO(blob) if isinstance(blob, bytes) else blob) as z:
        members = [m for m in z.namelist() if "jpcrp030000-asr" in m]
        if len(members) != 1:
            raise ValueError("expected 1 jpcrp030000-asr csv, got %d" % len(members))
        text = z.read(members[0]).decode("utf-16")
    body = list(csv.reader(io.StringIO(text), delimiter="\t"))[1:]

    tables = defaultdict(dict)
    totals = {}          # (variant) -> tagged listed carrying amount, current yr
    for row in body:
        if len(row) != 9:
            continue
        eid, item, ctx, relyr, cons, pit, unit_id, unit, val = row
        local = eid.split(":")[-1]
        in_row = bool(re.search(r"Row\d+Member", ctx))
        if in_row and "Deemed" not in local:
            f = field_of(local)
            if f and (DETAIL_MARK in local
                      or local.startswith(("PurposeOfShareholding", "WhetherIssuer"))):
                tables[(variant_of(local), ctx)][f] = val
        elif (not in_row and relyr == "当期末" and val.isdigit()
              and local.startswith("CarryingAmountSharesOtherThanThoseNotListed")):
            totals[variant_of(local)] = int(val)

    def row_key(ctx):
        m = re.search(r"Row(\d+)Member", ctx)
        return m.group(1) if m else None

    prior = {(v, row_key(c)): f for (v, c), f in tables.items()
             if c.startswith("Prior1YearInstant") and row_key(c)}
    holdings, warnings = [], []
    for (variant, ctx), f in sorted(tables.items()):
        if not ctx.startswith("CurrentYearInstant") or "name" not in f:
            continue
        p = prior.get((variant, row_key(ctx)), {})
        holdings.append({
            "holder_table": variant, "row": row_key(ctx),
            "held_name": f.get("name", ""),
            "shares": f.get("shares", ""), "book_value": f.get("book_value", ""),
            "prior_shares": p.get("shares", ""), "prior_book_value": p.get("book_value", ""),
            "purpose": f.get("purpose", ""), "reciprocal": f.get("reciprocal", ""),
        })
    return holdings, totals, warnings


def to_int(s):
    s = (s or "").replace(",", "")
    return int(s) if s.isdigit() else None


# ---- main ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every archived filer")
    ap.add_argument("--source", choices=("local", "s3"), default="local")
    ap.add_argument("--workers", type=int, default=12, help="parallel fetches (s3)")
    ap.add_argument("--limit", type=int, help="stop after N filings (smoke test)")
    args = ap.parse_args()

    src = S3Source(args.workers) if args.source == "s3" else LocalSource()

    codelist = load_codelist()
    idx = build_index(codelist)
    ecode_info = {d["ＥＤＩＮＥＴコード"]: d for d in codelist}
    fin_codes = {d["ＥＤＩＮＥＴコード"] for d in codelist
                 if d["上場区分"] == "上場"
                 and any(k in d["提出者業種"] for k in FIN_INDUSTRIES)}

    meta = src.list_metadata()
    filings = src.filings()
    targets = []
    for doc_id, rec in sorted(filings.items()):
        m = meta.get(doc_id) or {}
        # the daily list is the authority on doc type; the local manifest also
        # records it, but S3 discovery only knows the key exists
        if (m.get("docTypeCode") or rec.get("doc_type")) != "120":
            continue
        if args.all or m.get("edinetCode") in fin_codes:
            targets.append((doc_id, rec, m))
    if args.limit:
        targets = targets[:args.limit]
    years = sorted({(m.get("periodEnd") or "?")[:4] for _, _, m in targets})
    print("target filings: %d (%s, source=%s) spanning %s"
          % (len(targets), "all" if args.all else "financial sector",
             src.name, "/".join(years)))

    con = duckdb.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS eq_entities (
            edinet_code VARCHAR PRIMARY KEY, sec_code VARCHAR, name_ja VARCHAR,
            name_en VARCHAR, industry VARCHAR, listed BOOLEAN);
        CREATE TABLE IF NOT EXISTS eq_filings (
            doc_id VARCHAR PRIMARY KEY, edinet_code VARCHAR, sec_code VARCHAR,
            filer_name VARCHAR, period_end DATE, filed_date DATE,
            sha256 VARCHAR, parser_version VARCHAR, status VARCHAR, detail VARCHAR);
        CREATE TABLE IF NOT EXISTS eq_holdings (
            doc_id VARCHAR, holder_table VARCHAR, row_no VARCHAR,
            held_name_raw VARCHAR, held_edinet_code VARCHAR, held_sec_code VARCHAR,
            match_status VARCHAR, shares BIGINT, book_value_yen BIGINT,
            prior_shares BIGINT, prior_book_value_yen BIGINT,
            purpose_ja VARCHAR, reciprocal VARCHAR);
    """)

    # entities (refresh wholesale — registry data, not vintage data)
    con.execute("DELETE FROM eq_entities")
    con.executemany(
        "INSERT INTO eq_entities VALUES (?,?,?,?,?,?)",
        [(d["ＥＤＩＮＥＴコード"], (d["証券コード"] or "")[:4] or None, d["提出者名"],
          d.get("提出者名（英字）") or None, d.get("提出者業種") or None,
          d["上場区分"] == "上場") for d in codelist if d.get("ＥＤＩＮＥＴコード")])

    stats = {"clean": 0, "partial": 0, "failed": 0}
    matched = domestic = foreign = 0

    def fetch_and_parse(t):
        """Runs in a worker thread: network + CPU only, never touches DuckDB."""
        doc_id, rec, m = t
        try:
            return t, parse_filing(src.read_zip(doc_id, rec["date"])), None
        except Exception as e:
            return t, None, str(e)[:200]

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(fetch_and_parse, t) for t in targets]
        for fut in as_completed(futures):
            (doc_id, rec, m), parsed, err = fut.result()
            done += 1
            if done % 500 == 0:
                print("  %d/%d filings" % (done, len(targets)))
                sys.stdout.flush()
            period_end = m.get("periodEnd") or None
            base = (doc_id, m.get("edinetCode"), (m.get("secCode") or "")[:4] or None,
                    rec.get("filer") or m.get("filerName"), period_end, rec["date"],
                    rec.get("sha256"), PARSER_VERSION)
            if err:
                con.execute("INSERT OR REPLACE INTO eq_filings VALUES (?,?,?,?,?,?,?,?,?,?)",
                            base + ("failed", err))
                stats["failed"] += 1
                continue
            holdings, totals, warnings = parsed

            # reconciliation gate: named sum must not exceed the filing's own total
            sums = defaultdict(int)
            for h in holdings:
                v = to_int(h["book_value"])
                if v:
                    sums[h["holder_table"]] += v
            breaches = [v for v in sums if v in totals and sums[v] > totals[v]]
            status = "partial" if breaches else "clean"
            detail = ("named sum exceeds tagged total: %s" % breaches) if breaches else None
            con.execute("INSERT OR REPLACE INTO eq_filings VALUES (?,?,?,?,?,?,?,?,?,?)",
                        base + (status, detail))
            stats[status] += 1

            con.execute("DELETE FROM eq_holdings WHERE doc_id = ?", [doc_id])
            rows = []
            for h in holdings:
                nm = h["held_name"]
                hit = idx.get(norm(nm)) or idx.get(base_name(nm))
                if hit:
                    mstat, ec, sc = "matched", hit[0], hit[1] or None
                    matched += 1
                    domestic += 1
                elif is_foreign(nm):
                    mstat, ec, sc = "foreign", None, None
                    foreign += 1
                else:
                    mstat, ec, sc = "unmatched", None, None
                    domestic += 1
                rows.append((doc_id, h["holder_table"], h["row"], nm, ec, sc, mstat,
                             to_int(h["shares"]), to_int(h["book_value"]),
                             to_int(h["prior_shares"]), to_int(h["prior_book_value"]),
                             h["purpose"] or None, (h["reciprocal"] or "").strip() or None))
            if rows:
                con.executemany("INSERT INTO eq_holdings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    con.close()
    n = con = None
    print("filings: clean %(clean)d, partial %(partial)d, failed %(failed)d" % stats)
    if domestic:
        print("entity matching: %d/%d domestic (%.1f%%), %d foreign"
              % (matched, domestic, 100.0 * matched / domestic, foreign))
    print("wrote", os.path.normpath(DB_PATH))


if __name__ == "__main__":
    main()
