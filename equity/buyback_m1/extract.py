# -*- coding: utf-8 -*-
"""M1 prototype — Japanese share buyback execution (自己株券買付状況報告書).

EDINET document type 220: the monthly report a company files while a buyback
programme is running. It states the authorising resolution (shares and yen),
what was actually bought in the month, the cumulative total against the
authorisation, and the filer's own progress percentage.

Unlike the cross-shareholding tables, these filings are NOT individually
XBRL-tagged: the body carries a handful of TextBlock facts and the numbers sit
in HTML tables inside them. So this is table parsing, which is more fragile
than element lookup. Two things keep it honest:

  - the form is regulator-prescribed, so the row labels are stable;
  - the filing publishes 自己株式取得の進捗状況（％）, so every extraction can be
    checked against the filer's own arithmetic. That is the gate: recompute
    cumulative / authorised and require it to reproduce the stated percentage.

Reads from the cloud archive (EDINET_S3_*). Python 3.9, stdlib + boto3.

    python extract.py --limit 50          # prototype sample
    python extract.py --limit 50 --csv out/buybacks.csv
"""
import argparse
import collections
import csv
import glob
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
LISTS = os.path.join(HERE, "..", "data", "raw", "edinet", "lists")
DOC_TYPE = "220"

# Row labels in the prescribed form. Matched on a distinctive substring after
# width-normalisation, never on position — filers pad and merge cells freely.
ROW_AUTHORISED = "決議状況"
ROW_MONTH_TOTAL = "計"
ROW_CUMULATIVE = "累計"
ROW_PROGRESS = "進捗状況"

BLOCKS = {
    "board": "AcquisitionsByResolutionOfBoardOfDirectorsMeetingTextBlock",
    "agm": "AcquisitionsByResolutionOfShareholdersMeetingTextBlock",
    "disposal": "DisposalsOfTreasurySharesTextBlock",
    "holding": "HoldingOfTreasurySharesTextBlock",
}

# filers write this several ways: 該当事項はありません / 該当事項なし / 該当なし
NOT_APPLICABLE_RE = re.compile(r"該当(?:事項)?\s*(?:は)?\s*(?:あり)?(?:ません|なし|無し)")


def norm(s):
    """Width-fold and collapse whitespace. Filings mix full and half width."""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace(" ", " ").replace("&#160;", " ")
    return re.sub(r"\s+", " ", s).strip()


def strip_tags(s):
    return norm(re.sub(r"<[^>]+>", " ", s))


def to_num(s):
    """'1,234' -> 1234 ; '70.83' -> 70.83 ; '－'/'-'/'' -> None (never 0).

    Filers are inconsistent about units in the cell: the progress row may read
    "55.17%" in one filing and "55.17" in the next, and share counts sometimes
    carry 株/円. Strip the unit rather than reject the number — rejecting it
    silently shifts the trailing-pair read onto the wrong column.
    """
    s = norm(s).replace(",", "")
    s = re.sub(r"[%％株円]+$", "", s).strip()
    if not s or s in ("-", "−", "―", "ー", "—"):
        return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def cells_of(row_html):
    out = []
    for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S):
        out.append(strip_tags(c))
    return out


def last_two_numbers(cells):
    """Rows carry (label, [date,] shares, yen); take the trailing numeric pair."""
    nums = [(i, to_num(c)) for i, c in enumerate(cells)]
    nums = [(i, v) for i, v in nums if v is not None]
    if len(nums) < 2:
        return (nums[0][1] if nums else None), None
    return nums[-2][1], nums[-1][1]


def parse_block(seg):
    """One acquisition table -> dict of the rows we care about."""
    out = {"authorised_shares": None, "authorised_yen": None,
           "resolution_date": None, "month_shares": None, "month_yen": None,
           "cumulative_shares": None, "cumulative_yen": None,
           "progress_shares_pct": None, "progress_yen_pct": None,
           "daily_rows": 0, "as_of": None}
    m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日現在", norm(seg))
    if m:
        out["as_of"] = "%04d-%02d-%02d" % tuple(int(x) for x in m.groups())
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
        cells = [c for c in cells_of(row) if c]
        if not cells:
            continue
        label = cells[0]
        a, b = last_two_numbers(cells)
        if ROW_AUTHORISED in label:
            out["authorised_shares"], out["authorised_yen"] = a, b
            d = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", label)
            if d:
                out["resolution_date"] = "%04d-%02d-%02d" % tuple(int(x) for x in d.groups())
        elif ROW_PROGRESS in label:
            out["progress_shares_pct"], out["progress_yen_pct"] = a, b
        elif ROW_CUMULATIVE in label:
            out["cumulative_shares"], out["cumulative_yen"] = a, b
        elif label == ROW_MONTH_TOTAL or label.startswith(ROW_MONTH_TOTAL):
            out["month_shares"], out["month_yen"] = a, b
        elif re.search(r"\d+月\s*\d+日", " ".join(cells)):
            out["daily_rows"] += 1
    return out


def parse_filing(blob):
    z = zipfile.ZipFile(io.BytesIO(blob))
    hon = [n for n in z.namelist() if "honbun" in n and n.endswith(".htm")]
    if not hon:
        raise ValueError("no honbun ixbrl document in package")
    html = z.read(hon[0]).decode("utf-8", "replace")
    found = {}
    for key, element in BLOCKS.items():
        m = re.search(r'<ix:nonNumeric[^>]*name="[^"]*%s"[^>]*>(.*?)</ix:nonNumeric>'
                      % re.escape(element), html, re.S)
        if not m:
            continue
        seg = m.group(1)
        # "該当事項はありません" may sit in a bare paragraph OR inside a one-row
        # table, so test the stripped text rather than the presence of markup
        text = strip_tags(seg)
        if NOT_APPLICABLE_RE.search(text) and len(text) < 60:
            found[key] = None                       # explicitly not applicable
            continue
        found[key] = parse_block(seg) if key in ("board", "agm") else strip_tags(seg)[:120]
    return found


def stated_dp(x):
    """Decimal places the filer actually printed (21.8 -> 1, 70.83 -> 2)."""
    s = ("%.10f" % x).rstrip("0")
    return len(s.split(".")[1]) if "." in s and s.split(".")[1] else 0


def check(rec):
    """Gate: recompute progress and require the filer's own figure back.

    Filers are NOT consistent about rounding: Dai-ichi Life prints 21.8 for a
    true 21.893% (truncation), while Yoshicon prints 59.7 for 59.65 (rounding).
    So the tolerance is one unit in the last place the filer actually used —
    the tightest bound that admits both conventions and still catches a row
    read from the wrong line, which is always wrong by far more than that.

    Returns (status, detail): 'clean' | 'partial' | 'no_table'.
    """
    if rec is None:
        return "no_table", "filing states 該当事項なし"
    probs = []
    for unit, cum, auth, stated in (
            ("shares", rec["cumulative_shares"], rec["authorised_shares"], rec["progress_shares_pct"]),
            ("yen", rec["cumulative_yen"], rec["authorised_yen"], rec["progress_yen_pct"])):
        if stated is None or not auth or cum is None:
            continue
        calc = 100.0 * cum / auth
        tol = 10.0 ** -stated_dp(stated)
        if abs(calc - stated) >= tol:
            probs.append("%s: recomputed %.4f%% vs stated %s (tol %g)"
                         % (unit, calc, stated, tol))
    if probs:
        return "partial", "; ".join(probs)
    if rec["authorised_shares"] is None and rec["cumulative_shares"] is None:
        return "partial", "no authorisation or cumulative row found"
    return "clean", None


def sample_filings(limit):
    """Spread the sample across months and filers rather than one busy day."""
    by_month = collections.defaultdict(list)
    for f in sorted(glob.glob(os.path.join(LISTS, "*.json"))):
        day = os.path.basename(f)[:10]
        try:
            rows = json.load(open(f)).get("results") or []
        except ValueError:
            continue
        for r in rows:
            if r.get("docTypeCode") == DOC_TYPE and not r.get("fundCode") and r.get("secCode"):
                by_month[day[:7]].append((day, r["docID"], r.get("filerName"), r.get("secCode")))
    out, months = [], sorted(by_month)
    i = 0
    while len(out) < limit and months:
        m = months[i % len(months)]
        if by_month[m]:
            out.append(by_month[m].pop(len(by_month[m]) // 2))
        else:
            months.remove(m)
            continue
        i += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--csv")
    args = ap.parse_args()

    import boto3
    from botocore.config import Config
    s3 = boto3.client("s3", endpoint_url=os.environ["EDINET_S3_ENDPOINT"],
                      aws_access_key_id=os.environ["EDINET_S3_KEY_ID"],
                      aws_secret_access_key=os.environ["EDINET_S3_SECRET"],
                      region_name=os.environ.get("EDINET_S3_REGION", "auto"),
                      config=Config(max_pool_connections=args.workers + 4))
    bucket = os.environ["EDINET_S3_BUCKET"]

    targets = sample_filings(args.limit)
    print("sampled %d buyback filings across %d months"
          % (len(targets), len({d[:7] for d, _, _, _ in targets})))

    def work(t):
        day, doc, name, sec = t
        try:
            blob = s3.get_object(Bucket=bucket, Key="docs/%s/%s_t1.zip" % (day, doc))["Body"].read()
            return t, parse_filing(blob), None
        except Exception as e:
            return t, None, "%s: %s" % (type(e).__name__, str(e)[:120])

    stats = collections.Counter()
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for fut in as_completed([ex.submit(work, t) for t in targets]):
            (day, doc, name, sec), parsed, err = fut.result()
            if err:
                stats["fetch_or_parse_error"] += 1
                print("  FAILED %s %s  %s" % (doc, (name or "")[:18], err))
                continue
            for kind in ("board", "agm"):
                if kind not in parsed:
                    continue
                rec = parsed[kind]
                status, detail = check(rec)
                stats["%s:%s" % (kind, status)] += 1
                if status == "partial":
                    print("  PARTIAL %s %-18s %-5s %s" % (doc, (name or "")[:18], kind, detail))
                if rec:
                    rows.append(dict(doc_id=doc, sec_code=(sec or "")[:4], filer=name,
                                     submitted=day, kind=kind, status=status, **rec))
    print("\n--- M1 result ---")
    for k in sorted(stats):
        print("  %-28s %d" % (k, stats[k]))
    clean = sum(v for k, v in stats.items() if k.endswith(":clean"))
    checked = sum(v for k, v in stats.items() if k.endswith((":clean", ":partial")))
    if checked:
        print("  gate pass rate: %d/%d = %.1f%%" % (clean, checked, 100.0 * clean / checked))
    if args.csv and rows:
        os.makedirs(os.path.dirname(os.path.abspath(args.csv)), exist_ok=True)
        keys = sorted({k for r in rows for k in r})
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        print("  wrote %s (%d rows)" % (args.csv, len(rows)))


if __name__ == "__main__":
    main()
