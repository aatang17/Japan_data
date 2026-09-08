"""Round four — pooled own-line test. Spec: SPEC4.md."""
import json, collections, random, statistics, sys, pathlib
SP = pathlib.Path('/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad')
random.seed(4)

def months(a, b):
    out = []; y, m = a
    while (y, m) <= b: out.append((y, m)); y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out
ALL = months((2001, 1), (2026, 12)); IDX = {k: i for i, k in enumerate(ALL)}

def load_japan():
    V = collections.defaultdict(lambda: [None] * len(ALL)); Q = collections.defaultdict(lambda: [None] * len(ALL))
    seenV = set(); seenQ = set()
    for fn in ('hist.json', 'scan.json'):
        d = json.load(open(SP / fn))
        for k, v in d['V'].items():
            if k in seenV: continue
            seenV.add(k); c, y, m = k.split('|'); j = IDX.get((int(y), int(m)))
            if j is not None and v > 0: V[c][j] = v
        for k, v in d['Q'].items():
            if k in seenQ: continue
            seenQ.add(k); c, y, m = k.split('|'); j = IDX.get((int(y), int(m)))
            if j is not None and v > 0: Q[c][j] = v
    uni = set(json.load(open(SP / 'universe.json')))
    return {c: (V[c], Q[c]) for c in uni if c in V and c in Q}

def load_hk():
    d = json.load(open(SP / 'hk_universe.json'))
    out = {}
    for code, rows in d.items():
        V = [None] * len(ALL); Q = [None] * len(ALL)
        for p, r in rows.items():
            j = IDX.get((int(p[:4]), int(p[4:6])))
            if j is None: continue
            if r.get('v'): V[j] = r['v']
            if r.get('q'): Q[j] = r['q']
        if sum(1 for x in Q if x) >= 60: out[code] = (V, Q)
    return out

def w(a, i, n=3):
    if i - n + 1 < 0 or i >= len(a): return None
    s = a[i - n + 1:i + 1]
    if any(x is None for x in s): return None
    t = sum(s); return t if t else None

class Line:
    def __init__(self, V, Q):
        n = len(ALL)
        self.pv = [None] * n; self.qv = [None] * n; self.vv = [None] * n; self.p = [None] * n
        for i in range(n):
            a, b, c, d = w(V, i), w(Q, i), w(V, i - 12), w(Q, i - 12)
            if a and b: self.p[i] = a / b
            if a and b and c and d:
                self.pv[i] = (a / b) / (c / d) - 1; self.qv[i] = b / d - 1; self.vv[i] = a / c - 1
    def run(self, arr, i, cap=24):
        k = 0
        while k < cap and i - k - 1 >= 0 and arr[i - k] is not None and arr[i - k - 1] is not None and arr[i - k] > arr[i - k - 1]: k += 1
        return k
    def spike_start(self, i):
        p = self.pv[i]
        if p is None or p >= 0.08: return None
        fut = self.pv[i + 1:i + 7]
        if len(fut) < 6 or any(x is None for x in fut): return None
        return any(x >= 0.08 for x in fut)
    def rise6(self, i):
        a = self.p[i]; b = self.p[i + 6] if i + 6 < len(self.p) else None
        return (b / a - 1 >= 0.05) if (a and b) else None
    def fire(self, sig, k, i):
        pv, qv, vv = self.pv[i], self.qv[i], self.vv[i]
        if sig == 'PRICE': return pv is not None and pv >= 0 and self.run(self.pv, i) >= k
        if sig == 'VOLUME': return qv is not None and qv >= 0 and self.run(self.qv, i) >= k
        if sig == 'BOTH': return (pv is not None and qv is not None and pv >= 0 and qv >= 0
                                  and self.run(self.pv, i) >= k and self.run(self.qv, i) >= k)
        if sig == 'VALUE': return vv is not None and vv >= 0 and self.run(self.vv, i) >= k
        if sig == 'VOL-LEADS': return (qv is not None and pv is not None and qv >= 0.10 and pv <= 0.03
                                       and self.run(self.qv, i) >= k)
        return False

SIGS = ['PRICE', 'VOLUME', 'BOTH', 'VALUE', 'VOL-LEADS']

def fires(lines, sig, k, lo, hi, last):
    out = []
    for c, L in lines.items():
        prev = -99
        for i in range(len(ALL)):
            if not (lo <= ALL[i][0] <= hi) or i > last: continue
            if L.fire(sig, k, i) and i - prev >= 6: prev = i; out.append((c, i))
    return out

def evaluate(lines, F, lo, hi):
    hits = []; mid = 0; byyear = collections.defaultdict(lambda: [0, 0]); ex = []
    for c, i in F:
        s = lines[c].spike_start(i)
        if s is None: mid += 1; continue
        hits.append(s); byyear[ALL[i][0]][0] += s; byyear[ALL[i][0]][1] += 1
        if ALL[i][0] not in (2021, 2022): ex.append(s)
    h2 = [lines[c].rise6(i) for c, i in F]; h2 = [x for x in h2 if x is not None]
    return dict(n=len(hits), hit=(sum(hits) / len(hits) if hits else None), mid=mid,
                hit_ex2122=(sum(ex) / len(ex) if ex else None), n_ex=len(ex),
                hit2=(sum(h2) / len(h2) if h2 else None), n2=len(h2), byyear=dict(byyear))

def base(lines, lo, hi, last):
    a = []; b = []
    for L in lines.values():
        for i in range(len(ALL)):
            if lo <= ALL[i][0] <= hi and i <= last:
                s = L.spike_start(i); r = L.rise6(i)
                if s is not None: a.append(s)
                if r is not None: b.append(r)
    return (sum(a) / len(a) if a else None), (sum(b) / len(b) if b else None), len(a)

def perm(lines, F, lo, hi, last, observed, draws=300):
    per_line = collections.Counter(c for c, i in F if lines[c].spike_start(i) is not None)
    elig = {}
    for c in per_line:
        elig[c] = [i for i in range(len(ALL)) if lo <= ALL[i][0] <= hi and i <= last and lines[c].spike_start(i) is not None]
    ge = 0
    for _ in range(draws):
        hits = []
        for c, n in per_line.items():
            pool = elig[c]; pick = []; tries = 0
            while len(pick) < n and tries < 200:
                x = random.choice(pool); tries += 1
                if all(abs(x - p) >= 6 for p in pick): pick.append(x)
            hits += [lines[c].spike_start(i) for i in pick]
        if hits and sum(hits) / len(hits) >= observed - 1e-9: ge += 1
    return ge / draws

def run(name, lines, k_fixed=None):
    last = max(i for L in lines.values() for i in range(len(ALL)) if L.p[i] is not None) - 6
    first_year = min(ALL[i][0] for L in lines.values() for i in range(len(ALL)) if L.p[i] is not None)
    TR = (max(2005, first_year + 1), 2015); TE = (2016, 2026)
    if k_fixed is None and TR[1] - TR[0] < 5: TR = None
    print(f"\n{'='*104}\nUNIVERSE {name}: {len(lines)} lines, data to {ALL[last+6][0]}-{ALL[last+6][1]:02d}, test {TE[0]}-{TE[1]}")
    b1, b2, nb = base(lines, *TE, last)
    print(f"  base rate on test: spike-start {b1*100:.1f}%  price+5% {b2*100:.1f}%  ({nb:,} eligible line-months)")
    print(f"  {'signal':10} {'k':>2} {'fires':>6} {'n':>5} {'hit':>6} {'base':>6} {'p':>6} {'ex21-22':>8} {'+5%hit':>7} {'base':>6}  verdict")
    chosen = {}
    for sig in SIGS:
        if k_fixed is not None: k = k_fixed[sig]; kl = f"{k}*"
        else:
            best = None
            for k in (2, 3, 4, 6, 8):
                ev = evaluate(lines, fires(lines, sig, k, *TR, last), *TR)
                if ev['n'] >= 30 and (best is None or ev['hit'] > best[1]): best = (k, ev['hit'])
            if best is None: print(f"  {sig:10} no k gives 30 train fires"); continue
            k = best[0]; kl = str(k)
        chosen[sig] = k
        F = fires(lines, sig, k, *TE, last); ev = evaluate(lines, F, *TE)
        if ev['n'] == 0: print(f"  {sig:10} {kl:>2} {len(F):6} no scorable fires"); continue
        p = perm(lines, F, *TE, last, ev['hit'])
        ok = ev['hit'] > b1 and p <= 0.05 and ev['n'] >= 50 and (ev['hit_ex2122'] or 0) > b1
        verdict = 'RELIABLE' if ok else ('suggestive' if (ev['hit'] > b1 and p <= 0.20) else 'no evidence')
        f = lambda x: f"{x*100:5.1f}%" if x is not None else "    –"
        print(f"  {sig:10} {kl:>2} {len(F):6} {ev['n']:5} {f(ev['hit'])} {f(b1)} {p:6.2f} {f(ev['hit_ex2122']):>8} {f(ev['hit2']):>7} {f(b2)}  {verdict.upper()}")
        yrs = ' '.join(f"{y}:{v[0]}/{v[1]}" for y, v in sorted(ev['byyear'].items()))
        print(f"             by year (hits/fires): {yrs}")
    return chosen

if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'japan'
    if which == 'japan':
        jp = {c: Line(V, Q) for c, (V, Q) in load_japan().items()}
        chosen = run('A — Japan exports, 138 lines', jp)
        json.dump(chosen, open(SP / 'bt4_k.json', 'w'))
    else:
        chosen = json.load(open(SP / 'bt4_k.json'))
        hk = {c: Line(V, Q) for c, (V, Q) in load_hk().items()}
        run('B — Hong Kong imports (replication, k from A)', hk, k_fixed=chosen)
