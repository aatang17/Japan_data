"""Round three. Spec: SPEC3.md. Target is forward-looking; no signal touches the target series."""
import json, csv, collections, statistics, random, pathlib
SP = pathlib.Path('/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad')
random.seed(20260908)

def months(a, b):
    out = []; y, m = a
    while (y, m) <= b:
        out.append((y, m)); y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out
ALL = months((2001, 1), (2026, 12)); IDX = {k: i for i, k in enumerate(ALL)}
def blank(): return [None] * len(ALL)
def put(arr, y, m, v):
    j = IDX.get((int(y), int(m)))
    if j is not None and v is not None: arr[j] = (arr[j] or 0) + v

# ------------------------------------------------------------------ loaders
def load_hs(fn, part, code, qslot=None):
    d = json.load(open(SP / fn)); d = d[part] if part else d
    V, Q = blank(), blank()
    for k, v in d['V'].items():
        c, y, m = k.split('|')
        if c == code: put(V, y, m, v)
    qsrc = d.get('Q') if qslot is None else d.get(qslot, {})
    for k, v in qsrc.items():
        c, y, m = k.split('|')
        if c == code: put(Q, y, m, v)
    return V, Q

def load_finmind(ids):
    tot = collections.defaultdict(float); seen = collections.defaultdict(int)
    for i in ids:
        for r in json.load(open(SP / f'finmind_{i}.json'))['data']:
            tot[(r['revenue_year'], r['revenue_month'])] += r['revenue']; seen[(r['revenue_year'], r['revenue_month'])] += 1
    a = blank()
    for k, v in tot.items():
        if seen[k] == len(ids) and k in IDX: a[IDX[k]] = v
    return a

def load_hk(name, field):
    d = json.load(open(SP / 'hk_idds.json'))[name]; a = blank()
    for p, r in d.items():
        if field in r: put(a, p[:4], p[4:6], r[field])
    return a

def load_fred(sid):
    a = blank()
    for r in csv.DictReader(open(SP / 'fred' / f'{sid}.csv')):
        v = r[sid]
        if v not in ('.', ''): put(a, r['observation_date'][:4], r['observation_date'][5:7], float(v))
    return a

def load_ymkeys(d):
    a = blank()
    for k, v in d.items():
        y, m = k.split('|'); put(a, y, m, v)
    return a

def load_iip():
    d = json.load(open(SP / 'iip_invratio.json')); out = {}
    for b in ['0004052184', '0004018301', '0003272951']:
        s = d[b]
        if not out: out = dict(s); continue
        ov = [k for k in s if k in out and s[k]]
        f = statistics.median(out[k] / s[k] for k in ov) if len(ov) >= 6 else 1.0
        for k, v in s.items():
            if k not in out: out[k] = v * f
    a = blank()
    for k, v in out.items(): put(a, k[:4], k[5:7], v)
    return a

# ------------------------------------------------------------------ transforms
def w(a, i, n=3):
    if i - n + 1 < 0 or i >= len(a): return None
    s = a[i - n + 1:i + 1]
    if any(x is None for x in s): return None
    t = sum(s); return t if t else None
def y3(a, i):
    c, p = w(a, i), w(a, i - 12); return (c / p - 1) if (c and p) else None
def price3(v, q, i):
    a, b, c, d = w(v, i), w(q, i), w(v, i - 12), w(q, i - 12)
    return ((a / b) / (c / d) - 1) if (a and b and c and d) else None
def level3(v, q, i):
    a, b = w(v, i), w(q, i); return a / b if (a and b) else None
def mean3(a, i):
    s = w(a, i); return s / 3 if s is not None else None
def run_up(f, i, cap=24):
    k = 0
    while k < cap:
        c, p = f(i - k), f(i - k - 1)
        if c is None or p is None or c <= p: break
        k += 1
    return k
def run_down(f, i, cap=24):
    k = 0
    while k < cap:
        c, p = f(i - k), f(i - k - 1)
        if c is None or p is None or c >= p: break
        k += 1
    return k

# ------------------------------------------------------------------ TARGET (Japan MLCC export price — used for NOTHING else)
TV, TQ = load_hs('air_hs.json', 'all', '853224000')
def pyoy(i): return price3(TV, TQ, i)
def P3(i): return level3(TV, TQ, i)
LAST = max(i for i in range(len(ALL)) if TV[i])
def spike_start(i):
    """Primary: not spiking now; does a spike (>= +8% yoy) begin within 6 months? None = not scorable."""
    p = pyoy(i)
    if p is None or p >= 0.08: return None
    fut = [pyoy(i + j) for j in range(1, 7)]
    if any(x is None for x in fut): return None
    return any(x >= 0.08 for x in fut)
def rise6(i):
    a, b = P3(i), P3(i + 6)
    return (b / a - 1 >= 0.05) if (a and b) else None
# episode starts (for lead-time reporting only)
EPS = []; cur = None
for i in range(len(ALL)):
    p = pyoy(i)
    if p is not None and p >= 0.08:
        if cur is None: cur = [i, i]
        else: cur[1] = i
    else:
        if cur and cur[1] - cur[0] >= 2: EPS.append(cur[0])
        cur = None
if cur and cur[1] - cur[0] >= 2: EPS.append(cur[0])

# ------------------------------------------------------------------ CANDIDATES
S = collections.OrderedDict()
def add(name, f, kind, first_year, split=True, note=''):
    S[name] = dict(f=f, kind=kind, first=first_year, split=split, note=note)
tw = load_finmind(['2327', '2492', '3026']); add('1 Taiwan MLCC revenue', lambda i: y3(tw, i), 'growth', 2005)
odm = load_finmind(['2382', '2356', '6669']); add('2 Taiwan server ODM revenue', lambda i: y3(odm, i), 'growth', 2005)
mem = load_finmind(['2408', '2344', '2337']); add('3 Taiwan memory revenue', lambda i: y3(mem, i), 'growth', 2005)
hiv, hiq = load_hk('imp_all', 'v'), load_hk('imp_all', 'q')
add('4 HK MLCC import price (all origins)', lambda i: price3(hiv, hiq, i), 'growth', 2018, False, 'partial overlap: 29% Japanese product')
rcq = load_hk('rex_cn', 'q'); add('5 HK MLCC re-exports to China (units)', lambda i: y3(rcq, i), 'growth', 2018, False)
rxq = load_hk('rex_all', 'q')
gap = [((a - b) if (a is not None and b is not None) else None) for a, b in zip(hiq, rxq)]
add('6 HK channel gap (imp−rex units), inverted', lambda i: mean3(gap, i), 'inv', 2018, False)
rxv = load_hk('rex_all', 'v')
def markup(i):
    o, n = level3(rxv, rxq, i), level3(hiv, hiq, i); return (o / n - 1) if (o and n) else None
add('7 HK re-export markup', markup, 'gap', 2018, False)
no, sh, isr = load_fred('A34SNO'), load_fred('A34SVS'), load_fred('A34SIS')
inv = [(a * b if (a is not None and b is not None) else None) for a, b in zip(isr, sh)]
add('8 US orders − inventories', lambda i: ((y3(no, i) - y3(inv, i)) if (y3(no, i) is not None and y3(inv, i) is not None) else None), 'gap', 2001)
p1, p2 = load_fred('WPU117811'), load_fred('WPU117854'); j = IDX[(2022, 12)]; fct = p1[j] / p2[j]
ppi = [(p1[i] if p1[i] is not None else (p2[i] * fct if p2[i] is not None else None)) for i in range(len(ALL))]
add('9 US PPI capacitors', lambda i: ((mean3(ppi, i) / mean3(ppi, i - 12) - 1) if (mean3(ppi, i) and mean3(ppi, i - 12)) else None), 'growth', 2001)
ba = json.load(open(SP / 'baco3.json'))['imp']; bq = ba['Q2'] if sum(ba['Q2'].values()) > sum(ba['Q1'].values()) else ba['Q1']
bav, baq = load_ymkeys(ba['V']), load_ymkeys(bq)
add('10 Barium carbonate import price', lambda i: price3(bav, baq, i), 'growth', 2001)
niv, _ = load_hs('mats_hs2.json', None, '750400000', 'Q2'); add('11 Nickel powder export value', lambda i: y3(niv, i), 'growth', 2001)
iip = load_iip(); add('12 Japan parts inventory ratio, inverted', lambda i: mean3(iip, i), 'inv', 2008)
ws = blank()
for k, v in json.load(open(SP / 'wsts.json'))['Worldwide'].items(): put(ws, k[:4], k[5:7], v)
add('13 WSTS worldwide billings', lambda i: y3(ws, i), 'growth', 2001)
kr = blank()
for k, v in json.load(open(SP / 'comtrade_kr_8542.json')).items():
    if isinstance(v, (int, float)): put(kr, k[:4], k[4:6], v)
add('14 Korea IC exports', lambda i: y3(kr, i), 'growth', 2013, False)

# ------------------------------------------------------------------ fire rule
def fires(sig, k, lo, hi):
    f, kind = sig['f'], sig['kind']; out = []; last = -99
    for i in range(len(ALL)):
        if not (lo <= ALL[i][0] <= hi): continue
        v = f(i)
        if v is None: continue
        if kind == 'growth': ok = v >= 0 and run_up(f, i) >= k
        elif kind == 'gap': ok = v > 0 and run_up(f, i) >= k
        elif kind == 'inv':
            hist = [f(i - j) for j in range(1, 13)]; hist = [h for h in hist if h is not None]
            ok = len(hist) >= 10 and v < statistics.mean(hist) and run_down(f, i) >= k
        if ok and i - last >= 6: last = i; out.append(i)
    return out

# ------------------------------------------------------------------ scoring
def score(F, tf):
    xs = [tf(i) for i in F]; xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs) if xs else None), len(xs)
def base(tf, lo, hi):
    xs = [tf(i) for i in range(len(ALL)) if lo <= ALL[i][0] <= hi]; xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs) if xs else None), len(xs)
def perm_p(sig, F_scorable_n, observed, lo, hi, n_draw=2000):
    """Random fire dates among months where the signal has data AND the primary target is scorable."""
    elig = [i for i in range(len(ALL)) if lo <= ALL[i][0] <= hi and sig['f'](i) is not None and spike_start(i) is not None]
    if F_scorable_n == 0 or len(elig) < F_scorable_n * 6: return None
    ge = 0
    for _ in range(n_draw):
        pick = []; tries = 0
        while len(pick) < F_scorable_n and tries < 500:
            c = random.choice(elig); tries += 1
            if all(abs(c - p) >= 6 for p in pick): pick.append(c)
        if len(pick) < F_scorable_n: continue
        h = sum(1 for i in pick if spike_start(i)) / len(pick)
        if h >= observed - 1e-9: ge += 1
    return ge / n_draw

def lead_times(F):
    out = []
    for e in EPS:
        prior = [i for i in F if e - 12 <= i < e]
        if prior: out.append(e - prior[-1])
    return out

# ------------------------------------------------------------------ run
print("ROUND THREE — forward target, no leakage, base rate + permutation test on every row")
print("target: Japan MLCC export price (HS 8532.24) — a spike (>= +8% yoy) STARTS within 6 months of the fire")
print(f"data to {ALL[LAST][0]}-{ALL[LAST][1]:02d}; last scorable fire month {ALL[LAST-6][0]}-{ALL[LAST-6][1]:02d}")
print(f"episode starts in the data: {', '.join(f'{ALL[e][0]}-{ALL[e][1]:02d}' for e in EPS)}\n")
KS = [2, 3, 4, 6, 8]
rows = []
for name, sig in S.items():
    if sig['split']:
        tr = (max(2005, sig['first'] + 1), 2015); te = (2016, 2026)
        best = None
        for k in KS:
            F = fires(sig, k, *tr); h, n = score(F, spike_start)
            if h is None or n < 3: continue
            if best is None or h > best[1]: best = (k, h, n)
        if best is None: print(f"  {name:42} no trainable fires"); continue
        k = best[0]; kmode = f"k={k} (train {tr[0]}-{tr[1]}: {best[1]*100:.0f}% on {best[2]})"
    else:
        k = 4; te = (sig['first'] + 1, 2026); kmode = "k=4 UNTUNED"
    F = fires(sig, k, *te)
    Fs = [i for i in F if i <= LAST - 6]
    h1, n1 = score(Fs, spike_start); b1, _ = base(spike_start, *te)
    h2, n2 = score(Fs, rise6); b2, _ = base(rise6, *te)
    mid = sum(1 for i in Fs if spike_start(i) is None)
    p = perm_p(sig, n1, h1, *te) if h1 is not None else None
    leads = lead_times(F)
    verdict = ('RELIABLE' if (h1 is not None and b1 is not None and h1 > b1 and p is not None and p <= 0.10 and n1 >= 5)
               else 'suggestive' if (h1 is not None and b1 is not None and h1 > b1 and p is not None and p <= 0.25)
               else 'no evidence')
    rows.append((name, kmode, len(F), n1, mid, h1, b1, p, h2, b2, leads, verdict, sig['note'], F))
    f = lambda x: f"{x*100:3.0f}%" if x is not None else "  –"
    print(f"  {name:42} {kmode:34}")
    print(f"      fires {len(F):2} | spike-start: hit {f(h1)} vs base {f(b1)} (n={n1}, {mid} mid-spike) p={p if p is None else round(p,2)} | "
          f"price+5%: {f(h2)} vs {f(b2)} | lead to episode (m): {leads or '—'} | {verdict.upper()}")
    if sig['note']: print(f"      note: {sig['note']}")

# ------------------------------------------------------------------ combination among the non-'no evidence' rows
print("\nCOMBINATION — count of signals fired within the trailing 3 months (all 14 candidates, pre-registered):")
fired = collections.defaultdict(set)
for name, *_ , F in rows:
    for i in F: fired[i].add(name)
def cnt(i): return len(set().union(*[fired.get(j, set()) for j in (i-2, i-1, i)]))
for thr in (2, 3, 4):
    C = []; last = -99
    for i in range(IDX[(2019, 1)], LAST - 5):
        if cnt(i) >= thr and i - last >= 6: last = i; C.append(i)
    h, n = score(C, spike_start); b, _ = base(spike_start, 2019, 2026)
    h2, _ = score(C, rise6); b2, _ = base(rise6, 2019, 2026)
    print(f"  >={thr} agree: {len(C)} clusters | spike-start hit {h*100 if h else 0:.0f}% vs base {b*100:.0f}% (n={n}) | price+5% {h2*100 if h2 else 0:.0f}% vs {b2*100:.0f}% | "
          + ' '.join(f"{ALL[i][0]}-{ALL[i][1]:02d}" for i in C))
json.dump([dict(name=r[0], k=r[1], fires=r[2], n=r[3], hit=r[5], base=r[6], p=r[7], verdict=r[11],
                fire_dates=[f"{ALL[i][0]}-{ALL[i][1]:02d}" for i in r[13]]) for r in rows],
          open(SP / 'bt3_results.json', 'w'), indent=1)
