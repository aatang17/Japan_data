# -*- coding: utf-8 -*-
"""Candidate miner for the component -> company exposure map.

Generates candidates for `app/curation/semi_supply_chain.json` from filings we
already hold. It proposes; a human disposes. The curation file's own rule is
what this exists to satisfy:

    "A company appears under a commodity only if its own annual report
     describes that product as a reportable segment or a principal product.
     Market commentary is not evidence."

So every candidate this emits carries the filer's own words, verbatim, with the
doc_id behind them. Nothing is inferred from what the platform (or its author)
happens to know about an industry.

Three evidence routes, deliberately kept separate because they answer different
questions and fail differently:

  facilities  主要な設備の状況 — the filer names a plant and says what it makes.
              The only route that MEASURES exposure: book value and headcount
              of the plants whose filed text names the product, over the
              filer's disclosed total. Misses any filer that writes
              「生産設備等」 and nothing else — which includes Murata, the
              largest MLCC maker in the world.
  segments    セグメント情報 — the filer's own reportable segment names. Broader
              reach, no plant-level weight, and it cannot tell a maker from a
              distributor: a trading house's 電子部品事業 matches the same
              keyword as a manufacturer's. Hence `role_hint`.
  customers   主要な顧客 — who names whom. Demand-side exposure, not supply.
              Reported for context; never used to claim a company MAKES a thing.

Exposure weight is filed, not modelled: tagged plant book value over the
filer's own total for the rows it puts in its totals table. It is a floor and
says so — a filer that describes only three of its ten plants gets a weight
computed over what it disclosed. Where a filer discloses no per-row book value
(Mitsubishi Materials prints none for its 伸銅品 plants) the weight is null,
never zero.

Usage:
    python component_miner.py                          # every product below
    python component_miner.py --product capacitors     # one
    python component_miner.py --format json            # draft curation entries
"""
from __future__ import print_function

import argparse
import io
import json
import os
import sys

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get(
    "EQUITY_DB_PATH", os.path.join(HERE, "..", "data", "equity.duckdb"))

# Wholesale and trading: a segment keyword match here is a distributor until a
# human says otherwise. The industry is EDINET's own 業種, not our judgement.
TRADING_INDUSTRIES = (u"卸売業", u"小売業")

# --- the products under test -------------------------------------------------
#
# `customs` names the line in the trade datasets this product maps to, in the
# same key form the curation file uses (flow.commodity). `include` is matched
# against the filer's own text; `exclude` kills the false friends a bare
# keyword drags in. Both are POSIX regex, applied to Japanese text as filed.
PRODUCTS = {
    # "Capacitor" is a category, not a product. Customs splits it by dielectric
    # and every split line carries a quantity, so each has its own price. The
    # blended 概況品 line is kept because the price signal was validated on it,
    # but it is 75% MLCC by value and hides what the others are doing.
    "capacitors-all": {
        "label": u"Capacitors, all types — exports (概況品 70329)",
        "customs": ["exp.70329000"],
        "include": u"コンデンサ|キャパシタ",
        "exclude": None,
        "note": u"Blended. Use the dielectric-specific products below to attribute.",
    },
    "capacitors-mlcc": {
        "label": u"MLCC — multilayer ceramic capacitors (HS 8532.24)",
        "customs": ["hs.853224000"],
        # Filings do not state the dielectric: Japanese filers write 「コンデンサ」
        # and stop. This keyword therefore returns the whole capacitor field and
        # the MLCC makers must be picked out by hand. Worse than useless if
        # trusted blind — Taiyo Yuden, an MLCC house, names ONLY アルミ電解 in
        # its filing, because of its Elna subsidiary. See `type_trap`.
        "include": u"積層セラミック|セラミックコンデンサ|チップコンデンサ",
        "exclude": None,
        "type_trap": True,
    },
    "capacitors-aluminium": {
        "label": u"Aluminium electrolytic capacitors (HS 8532.22)",
        "customs": ["hs.853222000"],
        "include": u"アルミ電解|アルミニウム電解",
        "exclude": None,
    },
    "capacitors-tantalum": {
        "label": u"Tantalum capacitors (HS 8532.21)",
        "customs": ["hs.853221000"],
        "include": u"タンタルコンデンサ|タンタル",
        "exclude": None,
    },
    "capacitors-film": {
        "label": u"Paper and plastic-film capacitors (HS 8532.25)",
        "customs": ["hs.853225000"],
        "include": u"フィルムコンデンサ|プラスチックフィルムコンデンサ",
        "exclude": None,
    },
    "wrought-copper": {
        "label": u"Copper & copper-alloy sheet, strip and bar — exports "
                 u"(概況品 61301; brass 6130101)",
        "customs": ["exp.61301050", "exp.61301010", "exp.61301030"],
        "include": u"伸銅|銅板|銅条|銅帯|銅合金|黄銅|銅管|銅棒",
        # 電線/ケーブル is drawn wire, a separate line (70305) with its own makers.
        "exclude": u"^光ファイバ",
        "sub": {"brass": u"黄銅"},
    },
}


def _rows(cur, sql, params=None):
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _quote(evidence, inc):
    """The filer's words that actually matched, and which field they came from.

    Four of the seven capacitor filers name the product ONLY in the segment
    column; quoting the largest plant's `contents` would show unrelated text
    and make a correct match look like a false one.
    """
    import re
    rx = re.compile(inc)
    for row in evidence:
        for field in ("contents", "segment", "name"):
            val = row.get(field) or u""
            if rx.search(val):
                return val, field
    return u"", None


def _is_input(quote, inc):
    """「コンデンサ用セパレータ」 — a material FOR the product, not the product.

    The filer's own particle does the work: 用 immediately after the product
    name means the plant makes something that goes INTO it.
    """
    import re
    return bool(re.search(u"(?:" + inc + u")\\s*用", quote or u""))


def _facilities(cur, spec):
    """Per company: the plants whose filed text names the product, and weight."""
    inc = spec["include"]
    exc = spec.get("exclude")
    where = "regexp_matches(txt, ?)"
    params = [inc]
    if exc:
        where += " AND NOT regexp_matches(txt, ?)"
        params.append(exc)
    sql = (
        "WITH f AS ("
        "  SELECT e.sec_code, e.name_ja, e.name_en, e.industry, ff.doc_id,"
        "         ff.period_end,"
        "         coalesce(fa.contents,'')||' '||coalesce(fa.segment,'')||' '"
        "           ||coalesce(fa.name,'') AS txt,"
        "         fa.contents, fa.segment, fa.name, fa.location,"
        "         fa.total_yen, fa.employees, fa.in_totals"
        "  FROM eq_facilities fa"
        "  JOIN eq_fac_filings ff USING(doc_id)"
        "  JOIN eq_entities e ON e.edinet_code = ff.edinet_code)"
        "SELECT sec_code, name_ja, name_en, industry, doc_id, period_end,"
        "       sum(CASE WHEN " + where + " THEN coalesce(total_yen,0) ELSE 0 END) AS tagged_yen,"
        "       sum(CASE WHEN in_totals THEN coalesce(total_yen,0) ELSE 0 END) AS total_yen,"
        "       sum(CASE WHEN " + where + " THEN coalesce(employees,0) ELSE 0 END) AS tagged_emp,"
        "       count(*) FILTER (WHERE " + where + ") AS tagged_rows,"
        "       count(*) AS all_rows "
        "FROM f GROUP BY 1,2,3,4,5,6 HAVING tagged_rows > 0 "
        "ORDER BY tagged_yen DESC")
    out = _rows(cur, sql, params * 3)
    for c in out:
        ev = _rows(cur,
                   "SELECT contents, segment, name, location, total_yen, employees "
                   "FROM eq_facilities WHERE doc_id = ? AND regexp_matches("
                   "coalesce(contents,'')||' '||coalesce(segment,'')||' '"
                   "||coalesce(name,''), ?) ORDER BY total_yen DESC NULLS LAST LIMIT 4",
                   [c["doc_id"], inc])
        c["evidence"] = ev
        c["quote"], c["field"] = _quote(ev, inc)
        # A filer can name the product on plants whose book value it does not
        # print (Mitsubishi Materials does exactly this). Zero disclosed yen is
        # not zero exposure, so the weight is unknown, never 0%.
        c["weight_pct"] = (100.0 * c["tagged_yen"] / c["total_yen"]
                           if (c["total_yen"] and c["tagged_yen"]) else None)
        c["input_supplier"] = _is_input(c["quote"], inc)
    return out


def _segments(cur, spec):
    sql = ("SELECT DISTINCT e.sec_code, e.name_ja, e.name_en, e.industry,"
           "       sf.doc_id, s.segment_label_ja, s.external_revenue_yen,"
           "       s.segment_profit_yen "
           "FROM eq_seg_products s JOIN eq_seg_filings sf USING(doc_id) "
           "JOIN eq_entities e ON e.edinet_code = sf.edinet_code "
           "WHERE s.year_offset = 0 AND regexp_matches(s.segment_label_ja, ?) "
           "ORDER BY s.external_revenue_yen DESC NULLS LAST")
    out = _rows(cur, sql, [spec["include"]])
    for c in out:
        tot = _rows(cur, "SELECT sum(external_revenue_yen) t FROM eq_seg_products "
                         "WHERE doc_id = ? AND year_offset = 0", [c["doc_id"]])
        t = tot[0]["t"] if tot else None
        c["segment_share_pct"] = (100.0 * c["external_revenue_yen"] / t
                                  if (t and c["external_revenue_yen"]) else None)
    return out


def _customers(cur, spec):
    return _rows(cur,
                 "SELECT e.sec_code, coalesce(e.name_en, e.name_ja) AS filer,"
                 "       c.customer_name, c.value_yen, c.segment_label "
                 "FROM eq_seg_customers c JOIN eq_seg_filings sf USING(doc_id) "
                 "JOIN eq_entities e ON e.edinet_code = sf.edinet_code "
                 "WHERE c.year_offset = 0 AND regexp_matches("
                 "coalesce(c.segment_label,''), ?) "
                 "ORDER BY c.value_yen DESC NULLS LAST LIMIT 20", [spec["include"]])


def _role_hint(industry, route):
    if industry in TRADING_INDUSTRIES:
        return "distributor?"
    return "maker?" if route == "facilities" else "maker/distributor?"


def _name(c):
    return c.get("name_en") or c.get("name_ja") or "?"


def review_sheet(cur, key, spec, out):
    w = out.write
    w(u"\n## %s\n\n" % spec["label"])
    w(u"Customs line(s): `%s`  ·  keyword: `%s`\n"
      % (", ".join(spec["customs"]), spec["include"]))

    fac = _facilities(cur, spec)
    w(u"\n### Route A — plants the filer itself describes (measured exposure)\n\n")
    if not fac:
        w(u"_No filer names this product in its facilities note._\n")
    else:
        w(u"| ✓ | Code | Company | Industry | Tagged plant | Disclosed total |"
          u" Weight | Staff | Role | Filed words |\n")
        w(u"|---|---|---|---|---:|---:|---:|---:|---|---|\n")
        for c in fac:
            wt = ("%.0f%%" % c["weight_pct"]) if c["weight_pct"] is not None else u"—"
            tg = (u"¥%.1fbn" % (c["tagged_yen"] / 1e9)) if c["tagged_yen"] else u"not disclosed"
            tl = (u"¥%.1fbn" % (c["total_yen"] / 1e9)) if c["total_yen"] else u"—"
            role = ("input supplier?" if c["input_supplier"]
                    else _role_hint(c["industry"], "facilities"))
            w(u"| ☐ | %s | %s | %s | %s | %s | %s | %s | %s | 「%s」 _(%s)_ |\n"
              % (c["sec_code"] or u"—", _name(c)[:32], c["industry"] or u"—",
                 tg, tl, wt, "{:,}".format(c["tagged_emp"] or 0), role,
                 (c["quote"] or u"")[:40], c["field"] or u"?"))

    seg = _segments(cur, spec)
    seen = set(c["sec_code"] for c in fac)
    w(u"\n### Route B — reportable segment names (reach, no weight)\n\n")
    if not seg:
        w(u"_No filer names this product in a segment label._\n")
    else:
        w(u"| ✓ | Code | Company | Industry | Segment as filed | Segment revenue |"
          u" Share of revenue | Role | Also in A |\n")
        w(u"|---|---|---|---|---|---:|---:|---|---|\n")
        for c in seg:
            rev = (u"¥%.1fbn" % (c["external_revenue_yen"] / 1e9)
                   if c["external_revenue_yen"] else u"not tagged")
            sh = ("%.0f%%" % c["segment_share_pct"]) if c["segment_share_pct"] else u"—"
            w(u"| ☐ | %s | %s | %s | %s | %s | %s | %s | %s |\n"
              % (c["sec_code"] or u"—", _name(c)[:30], c["industry"] or u"—",
                 c["segment_label_ja"][:24], rev, sh,
                 _role_hint(c["industry"], "segments"),
                 u"yes" if c["sec_code"] in seen else u"—"))

    cus = _customers(cur, spec)
    if cus:
        w(u"\n### Route C — customers named inside a matching segment (demand side)\n\n")
        w(u"| Filer | Names as customer | Revenue |\n|---|---|---:|\n")
        for c in cus:
            v = (u"¥%.1fbn" % (c["value_yen"] / 1e9)) if c["value_yen"] else u"—"
            w(u"| %s | %s | %s |\n" % (c["filer"][:30], c["customer_name"][:34], v))

    for sub, pat in (spec.get("sub") or {}).items():
        hits = _rows(cur,
                     "SELECT DISTINCT e.sec_code, coalesce(e.name_en,e.name_ja) nm, "
                     "fa.contents FROM eq_facilities fa JOIN eq_fac_filings ff "
                     "USING(doc_id) JOIN eq_entities e ON e.edinet_code=ff.edinet_code "
                     "WHERE regexp_matches(coalesce(fa.contents,'')||' '||"
                     "coalesce(fa.segment,''), ?)", [pat])
        w(u"\n**%s specifically** (`%s`): %s\n"
          % (sub, pat,
             u", ".join(u"%s %s 「%s」" % (h["sec_code"], h["nm"], (h["contents"] or u"")[:24])
                        for h in hits) or u"no filer uses this wording"))
    return fac, seg


def draft_json(cur, key, spec):
    fac, seg = _facilities(cur, spec), _segments(cur, spec)
    by = {}
    for c in fac:
        if not c["sec_code"]:
            continue
        by[c["sec_code"]] = {
            "sec_code": c["sec_code"],
            "role": ("input_supplier" if c["input_supplier"]
                     else ("maker" if c["industry"] not in TRADING_INDUSTRIES
                           else "REVIEW")),
            "why": u"facilities note (%s): 「%s」" % (c["field"], (c["quote"] or u"")[:60]),
            "exposure": {
                "basis": "disclosed plant book value",
                "tagged_yen": c["tagged_yen"] or None,
                "disclosed_total_yen": c["total_yen"] or None,
                "weight_pct": (round(c["weight_pct"], 1)
                               if c["weight_pct"] is not None else None),
                "tagged_employees": c["tagged_emp"] or None,
                "doc_id": c["doc_id"],
            },
            "confirmed": False,
        }
    for c in seg:
        if not c["sec_code"] or c["sec_code"] in by:
            continue
        by[c["sec_code"]] = {
            "sec_code": c["sec_code"],
            "role": "REVIEW" if c["industry"] in TRADING_INDUSTRIES else "maker",
            "why": u"reportable segment 「%s」" % c["segment_label_ja"],
            "exposure": {"basis": "segment revenue share",
                         "weight_pct": (round(c["segment_share_pct"], 1)
                                        if c["segment_share_pct"] else None),
                         "doc_id": c["doc_id"]},
            "confirmed": False,
        }
    return {"label": spec["label"], "customs": spec["customs"],
            "companies": sorted(by.values(),
                                key=lambda x: -(x["exposure"].get("weight_pct") or 0))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--product", action="append", choices=sorted(PRODUCTS))
    ap.add_argument("--format", choices=("review", "json"), default="review")
    args = ap.parse_args()

    keys = args.product or sorted(PRODUCTS)
    con = duckdb.connect(args.db, read_only=True)
    cur = con.cursor()
    try:
        if args.format == "json":
            print(json.dumps({k: draft_json(cur, k, PRODUCTS[k]) for k in keys},
                             ensure_ascii=False, indent=2))
            return 0
        out = io.StringIO()
        out.write(u"# Component exposure — candidates for review\n\n"
                  u"Every row is the filer's own words from its annual securities "
                  u"report, with the doc_id behind it. Nothing here is confirmed: "
                  u"tick a row to accept it into `app/curation/semi_supply_chain.json`.\n")
        for k in keys:
            review_sheet(cur, k, PRODUCTS[k], out)
        sys.stdout.write(out.getvalue())
    finally:
        cur.close()
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
