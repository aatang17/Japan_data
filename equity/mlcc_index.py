# -*- coding: utf-8 -*-
"""MLCC Tightness Index — a 0-100 monthly reading from six independent sources.

*** RETRACTED, 8 September 2026 — do not use for decisions. ***
Component 2 (japan_price) IS the Japanese MLCC export price this index was
built to anticipate, so the index rises with a spike rather than before it.
With that component removed, the remainder sits above 45 in 60% of all months
and has no demonstrated skill against a random-timing null (see
docs/plans/BACKTEST-SIGNALS-RESULTS.md §14 and backtest-2026-09/bt3_out.txt).
Kept for the record of how the flaw was found. The original description follows.


WHAT THIS IS. The one robust finding of the September 2026 backtest was that
agreement between independent signals beats any single signal: three or more
firing within a quarter left capacitor prices higher six months later 83% of
the time against a 63% base rate, versus 78% for the best single signal. This
index is that finding made continuous. It is an ATTENTION score, not a
probability and not a forecast — 70 does not mean a 70% chance of anything.

HOW IT IS WEIGHTED. Not by taste. Each component's weight is its evidence:

   30  Taiwan MLCC revenue      validated out of sample (78% vs 63% base),
                                10-day lag, self-reported and never revised
   25  Japan MLCC export price  validated rule family (73% vs 59%), 25-day lag
   15  Corridor concentration   untested, but the sharpest read of WHICH
                                squeeze this is; capped low for that reason
   10  US orders − inventories  validated and truly point-in-time, but it is
                                the electronics cycle, not MLCC specifically
   10  Barium carbonate price   the precursor one step upstream; untested
   10  METI ceramic production  the best measurement we found — Japanese
                                output by unit AND yen — but e-Stat carries it
                                a year late, so it is NOT WIRED. See `WIRED`.

Each component scores 0..1 and contributes weight × score. Where a component
has both a level and a run of consecutive improvement, the two split the
weight evenly: half for "the condition holds now", half for "it has been
building". A level with no run is a state; a run with no level is noise.

READ IT AS BANDS, NOT POINTS. The precision is false below about ten points:
six supply cycles cannot calibrate a 100-point scale. Use the bands in
`BANDS`, and watch the direction of travel more than the level.
"""
from __future__ import print_function

import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.environ.get("MLCC_DATA_DIR", "")

WEIGHTS = collections.OrderedDict([
    ("taiwan_revenue", 30),
    ("japan_price", 25),
    ("corridor", 15),
    ("us_orders", 10),
    ("barium_carbonate", 10),
    ("meti_production", 10),
])
# Components with a live feed today. The unwired weight is excluded from the
# denominator and the shortfall is disclosed, never silently scored as zero:
# "no data" and "no tightening" are different readings.
WIRED = ("taiwan_revenue", "japan_price", "corridor", "us_orders",
         "barium_carbonate")

BANDS = [
    (0, 25, "Loose", "Nothing is building. Prices drifting or falling."),
    (25, 45, "Stirring", "One or two sources turning. Normal cycle noise."),
    (45, 65, "Building", "Several sources agree and runs are lengthening. "
                         "This is where 2017-09 and 2025-11 sat."),
    (65, 85, "Tight", "Broad agreement, prices moving, volumes still growing."),
    (85, 101, "Acute", "Every wired source firing at once. Rare; check for a "
                       "data fault before believing it."),
]


def months(a, b):
    out = []
    y, m = a
    while (y, m) <= b:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


ALL = months((2001, 1), (2026, 12))
IDX = dict((k, i) for i, k in enumerate(ALL))


def _win(a, i, n=3):
    if i - n + 1 < 0 or i >= len(a):
        return None
    seg = a[i - n + 1:i + 1]
    if any(x is None for x in seg):
        return None
    s = sum(seg)
    return s if s else None


def y3(a, i):
    c, p = _win(a, i), _win(a, i - 12)
    return (c / p - 1) if (c and p) else None


def price3(v, q, i):
    a, b = _win(v, i), _win(q, i)
    c, d = _win(v, i - 12), _win(q, i - 12)
    return ((a / b) / (c / d) - 1) if (a and b and c and d) else None


def run_up(f, i, cap=24):
    """Consecutive months in which f has improved, ending at i."""
    k = 0
    while k < cap:
        cur, prev = f(i - k), f(i - k - 1)
        if cur is None or prev is None or cur <= prev:
            break
        k += 1
    return k


def _series(d, key="V"):
    out = collections.defaultdict(lambda: [None] * len(ALL))
    for k, v in d.get(key, {}).items():
        parts = k.split("|")
        code, y, m = (parts + [None])[0], parts[-2], parts[-1]
        j = IDX.get((int(y), int(m)))
        if j is not None:
            out[code][j] = (out[code][j] or 0) + v
    return out


def load(scratch):
    """Every input this index needs, from the research pulls."""
    g = lambda n: json.load(open(os.path.join(scratch, n)))
    d = {}
    air = g("air_hs.json")["all"]
    d["mlcc_v"] = _series(air, "V")["853224000"]
    d["mlcc_q"] = _series(air, "Q")["853224000"]

    tw = collections.defaultdict(float)
    seen = collections.defaultdict(int)
    for sec in ("2327", "2492", "3026"):
        for r in g("finmind_%s.json" % sec)["data"]:
            tw[(r["revenue_year"], r["revenue_month"])] += r["revenue"]
            seen[(r["revenue_year"], r["revenue_month"])] += 1
    d["tw"] = [tw[k] if seen.get(k) == 3 else None for k in ALL]

    dest = g("mlcc_dest.json")
    d["dest_v"], d["dest_q"] = dest["V"], dest["Q"]

    fred = {}
    for sid in ("A34SNO", "A34SVS", "A34SIS"):
        col = {}
        with open(os.path.join(scratch, "fred", sid + ".csv")) as fh:
            next(fh)
            for line in fh:
                p = line.strip().split(",")
                if len(p) > 1 and p[1] not in (".", ""):
                    col[p[0][:7]] = float(p[1])
        arr = [None] * len(ALL)
        for k, v in col.items():
            j = IDX.get((int(k[:4]), int(k[5:7])))
            if j is not None:
                arr[j] = v
        fred[sid] = arr
    d["m3_no"] = fred["A34SNO"]
    d["m3_inv"] = [(a * b if (a is not None and b is not None) else None)
                   for a, b in zip(fred["A34SIS"], fred["A34SVS"])]

    ba = g("baco3.json")["imp"]
    q = ba["Q2"] if sum(ba["Q2"].values()) > sum(ba["Q1"].values()) else ba["Q1"]
    d["ba_v"] = [None] * len(ALL)
    d["ba_q"] = [None] * len(ALL)
    for k, v in ba["V"].items():
        y, m = k.split("|")
        j = IDX.get((int(y), int(m)))
        if j is not None:
            d["ba_v"][j] = v
    for k, v in q.items():
        y, m = k.split("|")
        j = IDX.get((int(y), int(m)))
        if j is not None:
            d["ba_q"][j] = v
    return d


CORRIDOR = ("50106", "50108", "50112")          # Taiwan, Hong Kong, Singapore


def components(d, i):
    """Each component: score 0..1, plus the numbers behind it."""
    out = collections.OrderedDict()

    # 1. Taiwan MLCC revenue — level: 3m yoy >= 0; run: k=4 (validated)
    f = lambda j: y3(d["tw"], j)
    cur, run = f(i), run_up(lambda j: y3(d["tw"], j), i)
    out["taiwan_revenue"] = dict(
        score=(0.5 * (1 if (cur is not None and cur >= 0) else 0)
               + 0.5 * min(run / 4.0, 1.0)) if cur is not None else None,
        detail="3m revenue %+.1f%% yoy, improving %d months (fires at 4)"
               % (cur * 100, run) if cur is not None else "no data")

    # 2. Japan MLCC export price — level: price >= +8% and volume growing;
    #    run: k=8 (validated on the same rule family)
    pf = lambda j: price3(d["mlcc_v"], d["mlcc_q"], j)
    p, vol, run = pf(i), y3(d["mlcc_q"], i), run_up(pf, i)
    lvl = 1 if (p is not None and p >= 0.08 and vol is not None and vol > 0) else 0
    out["japan_price"] = dict(
        score=(0.5 * lvl + 0.5 * min(run / 8.0, 1.0)) if p is not None else None,
        detail="price %+.1f%%, volume %+.1f%%, improving %d months (fires at 8)"
               % (p * 100, (vol or 0) * 100, run) if p is not None else "no data")

    # 3. Corridor concentration — how much more the AI-server corridor is
    #    paying than everyone else. Full credit at a 12pp spread.
    def dest_price(codes):
        cv = cq = pv = pq = 0.0
        for a in codes:
            for k in range(12):
                j = i - k
                cv += d["dest_v"].get("%s|%d|%d" % (a, ALL[j][0], ALL[j][1]), 0)
                cq += d["dest_q"].get("%s|%d|%d" % (a, ALL[j][0], ALL[j][1]), 0)
                j2 = i - k - 12
                pv += d["dest_v"].get("%s|%d|%d" % (a, ALL[j2][0], ALL[j2][1]), 0)
                pq += d["dest_q"].get("%s|%d|%d" % (a, ALL[j2][0], ALL[j2][1]), 0)
        return ((cv / cq) / (pv / pq) - 1) if (cv and cq and pv and pq) else None
    everyone = set(k.split("|")[0] for k in d["dest_v"])
    hot = dest_price(CORRIDOR)
    rest = dest_price(sorted(everyone - set(CORRIDOR)))
    spread = (hot - rest) if (hot is not None and rest is not None) else None
    out["corridor"] = dict(
        score=min(max(spread, 0) / 0.12, 1.0) if spread is not None else None,
        detail="corridor %+.1f%% vs rest %+.1f%% — spread %.1fpp (full at 12pp)"
               % (hot * 100, rest * 100, spread * 100) if spread is not None else "no data")

    # 4. US orders minus inventories — level: gap > 0; run: k=2 (validated)
    gf = lambda j: ((y3(d["m3_no"], j) - y3(d["m3_inv"], j))
                    if (y3(d["m3_no"], j) is not None and y3(d["m3_inv"], j) is not None)
                    else None)
    gap, run = gf(i), run_up(gf, i)
    out["us_orders"] = dict(
        score=(0.5 * (1 if gap > 0 else 0) + 0.5 * min(run / 2.0, 1.0))
              if gap is not None else None,
        detail="orders−inventories %+.1fpp, improving %d months (fires at 2)"
               % (gap * 100, run) if gap is not None else "no data")

    # 5. Barium carbonate import price — untested, so level only, full at +10%
    bp = price3(d["ba_v"], d["ba_q"], i)
    out["barium_carbonate"] = dict(
        score=min(max(bp, 0) / 0.10, 1.0) if bp is not None else None,
        detail="precursor import price %+.1f%% (full at +10%%)" % (bp * 100)
               if bp is not None else "no data")

    # 6. METI production — not wired; e-Stat publishes a year late.
    out["meti_production"] = dict(score=None,
                                  detail="not wired — needs a METI scraper")
    return out


def index(d, i):
    comp = components(d, i)
    earned = avail = 0.0
    for k, w in WEIGHTS.items():
        s = comp[k]["score"]
        if s is None or k not in WIRED:
            continue
        earned += w * s
        avail += w
    score = 100.0 * earned / avail if avail else None
    return score, avail, comp


def band(score):
    for lo, hi, name, gloss in BANDS:
        if lo <= score < hi:
            return name, gloss
    return "—", ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=SCRATCH, help="directory of the research pulls")
    ap.add_argument("--history", type=int, default=0, help="also print N prior months")
    args = ap.parse_args()
    if not args.data:
        print("give --data (the directory holding air_hs.json, finmind_*.json, "
              "mlcc_dest.json, baco3.json, fred/)", file=sys.stderr)
        return 2
    d = load(args.data)
    last = max(j for j, v in enumerate(d["mlcc_v"]) if v)
    score, avail, comp = index(d, last)
    name, gloss = band(score)

    print("MLCC TIGHTNESS INDEX — %d-%02d data" % ALL[last])
    print("=" * 68)
    print("  %.0f / 100   %s" % (score, name.upper()))
    print("  %s" % gloss)
    print("  scored on %d of 100 points of wired sources" % avail)
    print()
    print("  %-22s %5s %6s  %s" % ("component", "wt", "score", "reading"))
    for k, w in WEIGHTS.items():
        c = comp[k]
        s = c["score"]
        print("  %-22s %5d %6s  %s"
              % (k, w, ("%.2f" % s) if s is not None else "  —", c["detail"]))
    if args.history:
        print("\n  trailing:")
        for back in range(args.history, 0, -1):
            j = last - back
            sc, av, _ = index(d, j)
            if sc is not None:
                print("    %d-%02d  %3.0f  %s" % (ALL[j][0], ALL[j][1], sc, band(sc)[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
