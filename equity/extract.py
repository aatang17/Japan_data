# -*- coding: utf-8 -*-
"""M3 — production cross-shareholding extractor.

Reads annual-report CSV packages (EDINET type=5) from the local raw archive,
extracts the 政策保有株式 tables, entity-matches held names against the EDINET
code list, validates against the filings' own tagged totals, and writes the
eq_* tables into a dedicated DuckDB file (separate from the macro product's DB;
one writer at a time — this runs offline, the API reads read-only).

Usage:
    python extract.py                 # financial sector (banks/insurers/
                                      # securities/other financials)
    python extract.py --all           # every filer with an archived annual report

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
import unicodedata
import zipfile
from collections import defaultdict

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(HERE, "data", "raw", "edinet")
CODELIST = os.path.join(HERE, "m1", "EdinetcodeDlInfo.csv")
DB_PATH = os.path.join(HERE, "..", "observatory", "data", "equity.duckdb")
PARSER_VERSION = "m3-1"

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
def archived_filings():
    """(doc_id) -> manifest rec for annual-report CSV packages in the archive."""
    out = {}
    for line in open(os.path.join(ARCHIVE, "manifest.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("status") == "ok" and r.get("doc_type") == "120" and r.get("dl_type") == "5":
            out[r["doc_id"]] = r
    return out


def list_metadata():
    """doc_id -> daily-list record (edinetCode, secCode, periodEnd, ...)."""
    meta = {}
    for f in glob.glob(os.path.join(ARCHIVE, "lists", "*.json")):
        for r in json.load(open(f)).get("results") or []:
            meta[r["docID"]] = r
    return meta


# ---- per-filing extraction (M1 core, hardened) -----------------------------
def parse_filing(zip_path):
    """Return (holdings rows, tagged totals, warnings)."""
    with zipfile.ZipFile(zip_path) as z:
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
    args = ap.parse_args()

    codelist = load_codelist()
    idx = build_index(codelist)
    ecode_info = {d["ＥＤＩＮＥＴコード"]: d for d in codelist}
    fin_codes = {d["ＥＤＩＮＥＴコード"] for d in codelist
                 if d["上場区分"] == "上場"
                 and any(k in d["提出者業種"] for k in FIN_INDUSTRIES)}

    filings = archived_filings()
    meta = list_metadata()
    targets = []
    for doc_id, rec in sorted(filings.items()):
        m = meta.get(doc_id) or {}
        ecode = m.get("edinetCode")
        if args.all or ecode in fin_codes:
            targets.append((doc_id, rec, m))
    print("target filings: %d (%s)" % (len(targets), "all" if args.all else "financial sector"))

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
    for doc_id, rec, m in targets:
        zip_path = os.path.join(ARCHIVE, "docs", rec["date"], doc_id + "_t5.zip")
        period_end = m.get("periodEnd") or None
        base = (doc_id, m.get("edinetCode"), (m.get("secCode") or "")[:4] or None,
                rec.get("filer"), period_end, rec["date"], rec["sha256"], PARSER_VERSION)
        try:
            holdings, totals, warnings = parse_filing(zip_path)
        except Exception as e:
            con.execute("INSERT OR REPLACE INTO eq_filings VALUES (?,?,?,?,?,?,?,?,?,?)",
                        base + ("failed", str(e)[:200]))
            stats["failed"] += 1
            continue

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
