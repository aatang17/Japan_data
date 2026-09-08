"""Round five — what else moves these prices? Common factor, co-movement, and chain lead-lag.
Chain pairs are written here BEFORE running (HS-6, upstream -> downstream)."""
import json, collections, statistics, random, runpy, io, contextlib, pathlib, math
SP = pathlib.Path('/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad')
random.seed(5)
buf = io.StringIO()
with contextlib.redirect_stdout(buf): g = runpy.run_path(str(SP / 'bt4.py'), run_name='lib')
Line, load_hk, load_japan, ALL, IDX = (g[k] for k in ('Line', 'load_hk', 'load_japan', 'ALL', 'IDX'))

# ------------------------------------------------------------ pre-specified chains (HS-6)
CHAINS = {
 'copper -> cables/connectors/transformers': (['740311','740710','740811','740911','740919','740921'], ['854411','854419','854420','854442','854449','853690','850431','850440','850450']),
 'nickel powder & ceramic precursors -> capacitors': (['750400','283660','284190','282300'], ['853221','853222','853224','853225']),
 'silicon wafers & photoresist -> ICs/discretes': (['381800','370790'], ['854231','854232','854233','854239','854110','854121','854129']),
 'plastic film & epoxy -> film caps / PCBs': (['392062','392069','390730'], ['853225','853400']),
 'passives + ICs + PCBs -> computers/servers': (['853221','853222','853224','853310','853321','853400','854231','854232','854239'], ['847130','847141','847149','847150','847170','847180']),
 'passives + ICs -> phones/network gear': (['853224','854231','854232','854239','853400'], ['851712','851713','851762','851769']),
 'ICs + memory -> storage / SSD': (['854232','854239'], ['852351','852352','847170']),
 'li-ion cells -> EVs & e-bikes': (['850760','850750'], ['870380','870340','871160']),
 'steel & alu sheet -> cars & parts': (['720839','721049','721070','760612'], ['870321','870322','870323','870324','870332','870333','870829','870899']),
 'power semis + capacitors -> power supplies/inverters': (['854129','854110','853222','853224'], ['850440','850431','850490']),
}
GROUPS = {'materials': ('28','29','38','39','72','74','75','76'), 'components': ('8532','8533','8534','8536','8541','8542','8544','8504','8523'),
          'devices': ('8471','8517','8528','8507','8543','8525','8529'), 'autos': ('8703','8708','8711')}
def group_of(code):
    for gname, prefs in GROUPS.items():
        if any(code.startswith(p) for p in prefs): return gname
    return 'other'

hk = {c: Line(V, Q) for c, (V, Q) in load_hk().items()}
LAST = max(i for L in hk.values() for i in range(len(ALL)) if L.p[i] is not None)
T0 = IDX[(2016, 1)]
print(f"Hong Kong panel: {len(hk)} lines, 2016-01 to {ALL[LAST][0]}-{ALL[LAST][1]:02d}")
print("groups:", {k: sum(1 for c in hk if group_of(c) == k) for k in list(GROUPS) + ['other']})

# ------------------------------------------------------------ TEST 1: common factor and residual signal
print("\n" + "=" * 100 + "\nTEST 1 — how much of each line's price move is the market, and does BOTH survive on the residual?")
def med_at(i, lines):
    xs = [L.pv[i] for L in lines.values() if L.pv[i] is not None]
    return statistics.median(xs) if len(xs) >= 20 else None
def r2(x, y):
    pts = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pts) < 30: return None
    ax, ay = [p[0] for p in pts], [p[1] for p in pts]
    mx, my = statistics.mean(ax), statistics.mean(ay)
    sxy = sum((a - mx) * (b - my) for a, b in pts); sxx = sum((a - mx) ** 2 for a in ax); syy = sum((b - my) ** 2 for b in ay)
    return (sxy * sxy / (sxx * syy)) if (sxx and syy) else None
for uname, lines in (('Hong Kong', hk), ('Japan', {c: Line(V, Q) for c, (V, Q) in load_japan().items()})):
    last = max(i for L in lines.values() for i in range(len(ALL)) if L.p[i] is not None)
    med = [med_at(i, lines) if T0 <= i <= last else None for i in range(len(ALL))]
    r2s = []; byg = collections.defaultdict(list)
    for c, L in lines.items():
        v = r2([L.pv[i] for i in range(T0, last + 1)], [med[i] for i in range(T0, last + 1)])
        if v is not None: r2s.append(v); byg[group_of(c) if uname == 'Hong Kong' else 'all'].append(v)
    print(f"\n  {uname}: share of a line's price-yoy variance explained by the cross-line median (R²):")
    print(f"    median line R² = {statistics.median(r2s):.2f}; 75th pct {sorted(r2s)[int(len(r2s)*.75)]:.2f}; lines with R² > 0.5: {sum(1 for v in r2s if v>.5)}/{len(r2s)}")
    for gname, vs in sorted(byg.items()):
        if len(vs) >= 5: print(f"    {gname:11} median R² {statistics.median(vs):.2f} (n={len(vs)})")
    # residual BOTH: replace pv with pv - median, re-run the rule and the spike-start target on residual price
    class RLine(Line):
        pass
    res = {}
    for c, L in lines.items():
        R = RLine.__new__(RLine); R.p = L.p; R.qv = L.qv; R.vv = L.vv
        R.pv = [((L.pv[i] - med[i]) if (L.pv[i] is not None and med[i] is not None) else None) for i in range(len(ALL))]
        res[c] = R
    def fires(ls, sig, k, last):
        out = []
        for c, L in ls.items():
            prev = -99
            for i in range(T0, last - 6 + 1):
                if L.fire(sig, k, i) and i - prev >= 6: prev = i; out.append((c, i))
        return out
    F = fires(res, 'BOTH', 2, last)
    sc = [(c, i) for c, i in F if res[c].spike_start(i) is not None]
    hit = sum(res[c].spike_start(i) for c, i in sc) / len(sc) if sc else None
    allel = [res[c].spike_start(i) for c in res for i in range(T0, last - 5) if res[c].spike_start(i) is not None]
    per = collections.Counter(c for c, i in sc); ge = 0; D = 300
    for _ in range(D):
        hits = []
        for c, n in per.items():
            pool = [i for i in range(T0, last - 5) if res[c].spike_start(i) is not None]
            pick = []; t = 0
            while len(pick) < n and t < 200:
                x = random.choice(pool); t += 1
                if all(abs(x - q) >= 6 for q in pick): pick.append(x)
            hits += [res[c].spike_start(i) for i in pick]
        if hits and sum(hits) / len(hits) >= hit - 1e-9: ge += 1
    print(f"    BOTH on RESIDUAL price (line minus market): hit {hit*100:.1f}% on {len(sc)} vs base {sum(allel)/len(allel)*100:.1f}%, permutation p = {ge/D:.3f}")

# ------------------------------------------------------------ TEST 2: co-movement map
print("\n" + "=" * 100 + "\nTEST 2 — what moves with what (Hong Kong, price yoy correlations 2016-2026, lines with >=60 months)")
def corr(x, y):
    pts = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pts) < 60: return None
    ax, ay = [p[0] for p in pts], [p[1] for p in pts]; mx, my = statistics.mean(ax), statistics.mean(ay)
    n = sum((a - mx) * (b - my) for a, b in pts); d = math.sqrt(sum((a - mx) ** 2 for a in ax) * sum((b - my) ** 2 for b in ay))
    return n / d if d else None
codes = [c for c in hk if sum(1 for i in range(T0, LAST + 1) if hk[c].pv[i] is not None) >= 60 and group_of(c) != 'other']
series = {c: [hk[c].pv[i] for i in range(T0, LAST + 1)] for c in codes}
within = collections.defaultdict(list); between = collections.defaultdict(list); pairs = []
for a in range(len(codes)):
    for b in range(a + 1, len(codes)):
        r = corr(series[codes[a]], series[codes[b]])
        if r is None: continue
        ga, gb = group_of(codes[a]), group_of(codes[b])
        (within[ga] if ga == gb else between[tuple(sorted((ga, gb)))]).append(r)
        if ga != gb: pairs.append((r, codes[a], codes[b]))
print("  average correlation of price yoy:")
for gname, rs in sorted(within.items()): print(f"    within {gname:11}: {statistics.mean(rs):+.2f} (n={len(rs)} pairs)")
for gp, rs in sorted(between.items()): print(f"    {gp[0]:>11} x {gp[1]:11}: {statistics.mean(rs):+.2f} (n={len(rs)})")
print("  strongest cross-group pairs (|r| > 0.6):")
for r, a, b in sorted(pairs, key=lambda x: -abs(x[0]))[:12]:
    print(f"    {a} ({group_of(a)}) ~ {b} ({group_of(b)}): r = {r:+.2f}")

# ------------------------------------------------------------ TEST 3: chain lead-lag, pooled, both directions
print("\n" + "=" * 100 + "\nTEST 3 — does a BOTH fire on one end of a chain raise the odds of a spike starting at the other end within 6 months?")
def fires_line(L, k=2):
    out = []; prev = -99
    for i in range(T0, LAST - 6 + 1):
        if L.fire('BOTH', k, i) and i - prev >= 6: prev = i; out.append(i)
    return out
def test_dir(src_codes, dst_codes):
    hits = []; base = []
    for s in src_codes:
        if s not in hk: continue
        for i in fires_line(hk[s]):
            for d in dst_codes:
                if d in hk and hk[d].spike_start(i) is not None: hits.append(hk[d].spike_start(i))
    for d in dst_codes:
        if d not in hk: continue
        for i in range(T0, LAST - 5):
            v = hk[d].spike_start(i)
            if v is not None: base.append(v)
    return (sum(hits) / len(hits) if hits else None), len(hits), (sum(base) / len(base) if base else None)
print(f"  {'chain':52} {'up->down':>9} {'n':>5} | {'down->up':>9} {'n':>5} | base(dst)")
agg_ud = []; agg_du = []
for name, (up, down) in CHAINS.items():
    h1, n1, b1 = test_dir(up, down); h2, n2, b2 = test_dir(down, up)
    f = lambda x: f"{x*100:7.1f}%" if x is not None else "      –"
    print(f"  {name:52} {f(h1):>9} {n1:5} | {f(h2):>9} {n2:5} | {f(b1)} / {f(b2)}")
    if h1 is not None: agg_ud += [(h1, n1, b1)]
    if h2 is not None: agg_du += [(h2, n2, b2)]
def pooled(rows):
    n = sum(r[1] for r in rows); return sum(r[0] * r[1] for r in rows) / n, n, sum(r[2] * r[1] for r in rows) / n
u = pooled(agg_ud); d = pooled(agg_du)
print(f"\n  POOLED  upstream fire -> downstream spike: {u[0]*100:.1f}% (n={u[1]}) vs base {u[2]*100:.1f}%")
print(f"  POOLED  downstream fire -> upstream spike: {d[0]*100:.1f}% (n={d[1]}) vs base {d[2]*100:.1f}%")
