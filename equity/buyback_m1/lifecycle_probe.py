# -*- coding: utf-8 -*-
"""Probe — can we see the whole buyback lifecycle from the 220 filings alone?

Production `buyback.py` (parser bb-1) reads only the two acquisition blocks, so
it answers "how much was executed against the authorisation". The lifecycle
question needs two more things, and this probe checks whether the source
actually carries them:

  announcement  the 決議状況 row label carries the acquisition WINDOW
                (取得期間 X~Y), not just the resolution date.
  cancellation  【株式の処理状況及び保有状況】 carries a prescribed 消却 row
                (shares retired in the month + yen) plus 発行済株式総数 and
                保有自己株式数 at month end.

Reads the LOCAL edinet archive only (no S3, no DB writes). Python 3.9.

    ../observatory/.venv/bin/python buyback_m1/lifecycle_probe.py --csv out/lifecycle.csv
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import buyback as bb                                    # reuse the gated parser

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(HERE, "..", "data", "raw", "edinet")
BLOCKS = dict(bb.BLOCKS, disposal="DisposalsOfTreasurySharesTextBlock",
              holding="HoldingOfTreasurySharesTextBlock")
# ~1% of filers date the resolution in the Reiwa era (令和8年 = 2026). Production
# bb-1 misses these and stores a null resolution_date for them.
DATE = re.compile(r"(?:(令和)\s*)?(\d{1,4})年\s*(\d{1,2})月\s*(\d{1,2})日")
# 消却 / 募集 / 移転 / その他, in prescribed order; 合計 closes the table
# 消却 / 募集 / 移転 / その他, in prescribed order; 合計 closes the table.
# その他 is NOT one row: filers open a separate その他(...) block per reason
# (Sony files three), so it must accumulate or the sum gate fails on a
# perfectly good filing.
CATEGORIES = (("offer", "引き受ける者の募集"), ("cancel", "消却"),
              ("transfer", "移転"), ("other", "その他"))


def all_dates(text):
    out = []
    for era, y, mo, d in DATE.findall(bb.norm(text)):
        year = 2018 + int(y) if era else int(y)
        if year < 1900:
            continue
        out.append("%04d-%02d-%02d" % (year, int(mo), int(d)))
    return out


def rows_of(seg):
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
        cells = [c for c in bb.cells_of(row) if c]
        if cells:
            yield cells


def parse_window(label, block_text):
    """Resolution date from the 決議状況 label; the window from the 取得期間
    fragment, which some filers (Idemitsu) put in a row of its own rather than
    in the label — so read it from the block text, not the label."""
    res = all_dates(label)
    m = re.search(r"取得期間[^)）]*", block_text)
    win = all_dates(m.group(0)) if m else []
    start = win[0] if len(win) >= 2 else None
    end = win[1] if len(win) >= 2 else (win[0] if win else None)
    # No fallback to other dates in the block: when a filer leaves the
    # template blank (MonotaRO) the resolution date is genuinely absent, and
    # substituting the as-of date would invent one.
    return (res[0] if res else None), start, end


def parse_disposal(seg):
    """Category totals come from each category's 計 row — never the header row,
    which carries the disposal DATE in the same cell run."""
    out = {k: (None, None) for k, _ in CATEGORIES}
    out["total"] = (None, None)
    current = None
    for cells in rows_of(seg):
        label = cells[0]
        if label.startswith("合計"):
            out["total"] = bb.last_two_numbers(cells)
            current = None
            continue
        if label.startswith("計"):
            if current:
                a, b = bb.last_two_numbers(cells)
                have = out[current]
                out[current] = (None if a is None and have[0] is None else zero(have[0]) + zero(a),
                                None if b is None and have[1] is None else zero(have[1]) + zero(b))
            current = None
            continue
        hit = next((k for k, kw in CATEGORIES if kw in label), None)
        if hit:
            current = hit
    return out


def parse_holding(seg):
    out = {}
    for cells in rows_of(seg):
        v = bb.to_num(cells[-1])
        if v is None:
            continue
        if "発行済株式総数" in cells[0]:
            out["shares_outstanding"] = v
        elif "保有自己株式数" in cells[0]:
            out["treasury_shares"] = v
    return out


def zero(v):
    return 0.0 if v is None else v


def check_disposal(d):
    """The filing publishes its own 合計 — recompute it from the four category
    rows and require it back. In this block ― means no disposal occurred, so it
    sums as zero; that is the form's own convention, not our imputation."""
    if all(v == (None, None) for k, v in d.items() if k != "total"):
        return "no_rows", None
    if d["total"] == (None, None):
        return "unverified", "filing published no 合計 row"
    probs = []
    for i, unit in ((0, "shares"), (1, "yen")):
        calc = sum(zero(d[k][i]) for k, _ in CATEGORIES)
        stated = zero(d["total"][i])
        if abs(calc - stated) > 1:
            probs.append("%s: categories sum to %.0f vs stated 合計 %.0f" % (unit, calc, stated))
    return ("partial", "; ".join(probs)) if probs else ("clean", None)


def targets():
    out = []
    for f in sorted(glob.glob(os.path.join(ARCHIVE, "lists", "*.json"))):
        day = os.path.basename(f)[:10]
        try:
            rows = json.load(open(f)).get("results") or []
        except ValueError:
            continue
        for r in rows:
            if r.get("docTypeCode") != bb.DOC_TYPE or r.get("fundCode"):
                continue
            p = os.path.join(ARCHIVE, "docs", day, "%s_t1.zip" % r["docID"])
            if os.path.exists(p):
                out.append((p, day, r))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    todo = targets()
    if args.limit:
        todo = todo[:args.limit]
    print("local 220 filings: %d" % len(todo))

    st, months, rows = collections.Counter(), {}, []
    for path, day, meta in todo:
        z = zipfile.ZipFile(path)
        hon = [n for n in z.namelist() if "honbun" in n and n.endswith(".htm")]
        if not hon:
            st["no_honbun"] += 1
            continue
        html = z.read(hon[0]).decode("utf-8", "replace")
        st["filings"] += 1
        seg = {}
        for key, el in BLOCKS.items():
            m = re.search(r'<ix:nonNumeric[^>]*name="[^"]*%s"[^>]*>(.*?)</ix:nonNumeric>'
                          % re.escape(el), html, re.S)
            seg[key] = m.group(1) if m else None
            st["block_present:" + key] += 1 if m else 0

        # ---- cancellation + treasury -------------------------------------
        disp = parse_disposal(seg["disposal"]) if seg["disposal"] else None
        dstatus, ddetail = check_disposal(disp) if disp else ("no_block", None)
        st["disposal:" + dstatus] += 1
        cancel_shares = disp["cancel"][0] if disp else None
        cancel_yen = disp["cancel"][1] if disp else None
        if cancel_shares:
            st["cancelled_shares_nonzero"] += 1
        hold = parse_holding(seg["holding"]) if seg["holding"] else {}
        if "shares_outstanding" in hold and "treasury_shares" in hold:
            st["holding:clean"] += 1
            if hold["treasury_shares"] > hold["shares_outstanding"]:
                st["holding:impossible"] += 1
        else:
            st["holding:incomplete"] += 1

        # ---- announcement window + execution -----------------------------
        for kind in ("board", "agm"):
            if not seg[kind]:
                continue
            text = bb.strip_tags(seg[kind])
            if bb.NOT_APPLICABLE_RE.search(text) and len(text) < 60:
                continue
            if not re.search(r"<table", seg[kind], re.I):
                continue
            rec = bb.parse_block(seg[kind])
            status, detail = bb.check(rec)
            st["exec:%s:%s" % (kind, status)] += 1
            label = next((c[0] for c in rows_of(seg[kind]) if "決議状況" in c[0]), "")
            rdate, wstart, wend = parse_window(label, text)
            st["window_found"] += 1 if wend else 0
            st["window_missing"] += 0 if wend else 1
            rows.append(dict(
                doc_id=meta["docID"], submitted=day, sec_code=(meta.get("secCode") or "")[:4],
                filer=meta.get("filerName"), kind=kind, as_of=rec["as_of"],
                resolution_date=rdate or rec["resolution_date"],
                window_start=wstart, window_end=wend,
                authorised_shares=rec["authorised_shares"], authorised_yen=rec["authorised_yen"],
                month_shares=rec["month_shares"], month_yen=rec["month_yen"],
                cumulative_shares=rec["cumulative_shares"], cumulative_yen=rec["cumulative_yen"],
                progress_yen_pct=rec["progress_yen_pct"], exec_status=status,
                cancelled_shares=cancel_shares, cancelled_yen=cancel_yen,
                disposal_status=dstatus, shares_outstanding=hold.get("shares_outstanding"),
                treasury_shares=hold.get("treasury_shares")))
            key = (meta.get("edinetCode"), kind, rdate or rec["resolution_date"])
            prev = months.get(key)
            if prev is None or (rec["as_of"] or "") > (prev["as_of"] or ""):
                months[key] = rows[-1]
            months[key]["filings"] = (prev or {}).get("filings", 0) + 1

    print("\n--- blocks & gates -------------------------------------------")
    for k in sorted(st):
        print("  %-32s %d" % (k, st[k]))

    # ---- programme lifecycle rollup --------------------------------------
    life = collections.Counter()
    TODAY = "2026-08-24"
    for key, last in months.items():
        auth, cum = last["authorised_yen"], last["cumulative_yen"]
        pct = (100.0 * cum / auth) if (auth and cum is not None) else None
        if pct is None:
            life["unknown"] += 1
        elif pct >= 99.5:
            life["completed"] += 1
        elif last["window_end"] and last["window_end"] < TODAY:
            life["expired_short"] += 1
        else:
            life["running"] += 1
    print("\n--- programmes seen (last filing of each) ---------------------")
    print("  programmes: %d" % len(months))
    for k in sorted(life):
        print("  %-32s %d" % (k, life[k]))
    short = sorted([m for m in months.values()
                    if m["authorised_yen"] and m["cumulative_yen"] is not None
                    and m["window_end"] and m["window_end"] < TODAY
                    and 100.0 * m["cumulative_yen"] / m["authorised_yen"] < 99.5],
                   key=lambda m: 100.0 * m["cumulative_yen"] / m["authorised_yen"])[:8]
    if short:
        print("\n  window closed with authorisation unspent (the 'cancellation' signal):")
        for m in short:
            print("    %-28s %s→%s  spent %.1f%% of ¥%.1fbn"
                  % (m["filer"][:28], m["resolution_date"], m["window_end"],
                     100.0 * m["cumulative_yen"] / m["authorised_yen"],
                     m["authorised_yen"] / 1e9))
    if args.csv:
        path = args.csv if os.path.isabs(args.csv) else os.path.join(HERE, args.csv)
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=sorted(rows[0]), extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print("\nwrote %s (%d rows)" % (path, len(rows)))


if __name__ == "__main__":
    main()
