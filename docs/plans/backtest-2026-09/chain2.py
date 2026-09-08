"""Test 3 permutation + ex-copper; Test 4 final customer (HK re-exports to China of finished goods; Taiwan ODM revenue)."""
import json, collections, statistics, random, runpy, io, contextlib, pathlib, urllib.request
SP=pathlib.Path('/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad')
random.seed(9)
buf=io.StringIO()
with contextlib.redirect_stdout(buf): g=runpy.run_path(str(SP/'bt4.py'), run_name='lib')
Line,load_hk,ALL,IDX=(g[k] for k in ('Line','load_hk','ALL','IDX'))
with contextlib.redirect_stdout(buf): c1=runpy.run_path(str(SP/'chain.py'), run_name='lib')
CHAINS,hk,T0,LAST,fires_line,test_dir=(c1[k] for k in ('CHAINS','hk','T0','LAST','fires_line','test_dir'))

# ---------- Test 3: permutation on the pooled upstream->downstream result, and ex-copper
print("="*100+"\nTEST 3 (cont.) — permutation null for 'upstream BOTH fire -> downstream spike within 6m'")
def pooled_obs(chains):
    events=[]   # (dst, fire_month)
    for name,(up,down) in chains.items():
        for s in up:
            if s not in hk: continue
            for i in fires_line(hk[s]):
                for d in down:
                    if d in hk and hk[d].spike_start(i) is not None: events.append((d,i,name))
    return events
def perm(events, draws=500):
    obs=sum(hk[d].spike_start(i) for d,i,_ in events)/len(events)
    per=collections.Counter(d for d,i,_ in events); ge=0
    pools={d:[i for i in range(T0,LAST-5) if hk[d].spike_start(i) is not None] for d in per}
    for _ in range(draws):
        hits=[]
        for d,n in per.items():
            pick=[random.choice(pools[d]) for _ in range(n)]   # same destination lines, random months
            hits+=[hk[d].spike_start(i) for i in pick]
        if sum(hits)/len(hits)>=obs-1e-9: ge+=1
    return obs, ge/draws
ev=pooled_obs(CHAINS)
o,p=perm(ev); print(f"  all chains:      {o*100:.1f}% on {len(ev)}  permutation p = {p:.3f}")
ev2=[e for e in ev if not e[2].startswith('copper')]
o2,p2=perm(ev2); print(f"  excluding copper: {o2*100:.1f}% on {len(ev2)}  permutation p = {p2:.3f}")
ev3=[e for e in ev if e[2].startswith('copper')]
o3,p3=perm(ev3); print(f"  copper chain only: {o3*100:.1f}% on {len(ev3)}  permutation p = {p3:.3f}")

# ---------- Test 4: final customer
print("\n"+"="*100+"\nTEST 4 — FINAL CUSTOMER: do finished-goods flows to China, or Taiwan's server makers, lead component prices?")
FIN=['847130','847141','847149','847150','847170','851713','851714','851762','852852','850760','850440']
COMP=['853221','853222','853224','853225','853310','853321','853400','854231','854232','854239','853690','854411','854420','850431','850450']
out=SP/'hk_rex_cn.json'
if not out.exists():
    op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    url=("https://tradeidds.censtatd.gov.hk/api/get?lang=EN&sv=VCm,QCm&freq=M&period=201501,202607&ttype=3&codeclass=HKHS6&code="+",".join(FIN)+"&ccclass=C&cc=CN")
    d=json.load(op.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=180))
    st=d['header']['status']; print("  fetch:",st['name'],st.get('message',''))
    rows={}
    for r in d.get('dataSet',[]):
        fg=r.get('figure')
        if fg in (None,'','-'): continue
        rows.setdefault(r['code'],{}).setdefault(r['period'],{})['v' if r['sv']=='VCm' else 'q']=float(fg)
    json.dump(rows,open(out,'w'))
rex=json.load(open(out))
def mk(code):
    V=[None]*len(ALL); Q=[None]*len(ALL)
    for p,r in rex.get(code,{}).items():
        j=IDX.get((int(p[:4]),int(p[4:6])))
        if j is None: continue
        if r.get('v'): V[j]=r['v']
        if r.get('q'): Q[j]=r['q']
    return Line(V,Q) if sum(1 for x in Q if x)>=48 else None
fin={c:mk(c) for c in FIN}; fin={c:L for c,L in fin.items() if L}
print(f"  finished-goods re-exports to China with usable units: {sorted(fin)}")
def lead(src_lines, dst_codes, label):
    events=[]
    for s,L in src_lines.items():
        for i in fires_line(L):
            for d in dst_codes:
                if d in hk and hk[d].spike_start(i) is not None: events.append((d,i,label))
    if not events: print(f"  {label:58} no events"); return
    o,p=perm(events)
    base=[hk[d].spike_start(i) for d in dst_codes if d in hk for i in range(T0,LAST-5) if hk[d].spike_start(i) is not None]
    print(f"  {label:58} {o*100:5.1f}% on {len(events):3} vs base {sum(base)/len(base)*100:.1f}%  p = {p:.3f}")
lead(fin, COMP, "China-bound finished goods (BOTH fire) -> component import price spike")
lead({c:fin[c] for c in fin if c.startswith('8471')}, COMP, "  computers/servers to China only -> components")
lead({c:fin[c] for c in fin if c.startswith('8517')}, COMP, "  phones/network to China only -> components")
# reverse: components -> finished goods to China
events=[]
for s in COMP:
    if s not in hk: continue
    for i in fires_line(hk[s]):
        for d,L in fin.items():
            if L.spike_start(i) is not None: events.append((d,i,'rev'))
if events:
    obs=sum(fin[d].spike_start(i) for d,i,_ in events)/len(events)
    base=[L.spike_start(i) for L in fin.values() for i in range(T0,LAST-5) if L.spike_start(i) is not None]
    print(f"  {'REVERSE: component price fire -> finished-goods-to-China spike':58} {obs*100:5.1f}% on {len(events):3} vs base {sum(base)/len(base)*100:.1f}%")
# Taiwan demand
def fm(ids):
    tot=collections.defaultdict(float); seen=collections.defaultdict(int)
    for i in ids:
        for r in json.load(open(SP/f'finmind_{i}.json'))['data']:
            tot[(r['revenue_year'],r['revenue_month'])]+=r['revenue']; seen[(r['revenue_year'],r['revenue_month'])]+=1
    V=[tot[k] if seen.get(k)==len(ids) else None for k in ALL]
    L=Line(V,[1.0 if v else None for v in V]); return L
tw_odm=fm(['2382','2356','6669']); tw_mlcc=fm(['2327','2492','3026']); tw_found=fm(['2330','2303','6770'])
def lead_rev(L, dst, label):
    events=[]; prev=-99
    for i in range(T0,LAST-5):
        if L.vv[i] is not None and L.vv[i]>=0 and L.run(L.vv,i)>=4 and i-prev>=6:
            prev=i
            for d in dst:
                if d in hk and hk[d].spike_start(i) is not None: events.append((d,i,label))
    if not events: print(f"  {label:58} no events"); return
    o,p=perm(events); base=[hk[d].spike_start(i) for d in dst if d in hk for i in range(T0,LAST-5) if hk[d].spike_start(i) is not None]
    print(f"  {label:58} {o*100:5.1f}% on {len(events):3} vs base {sum(base)/len(base)*100:.1f}%  p = {p:.3f}")
CAPS=['853221','853222','853224','853225']
lead_rev(tw_odm, COMP, "Taiwan server ODM revenue (4m run) -> HK component prices")
lead_rev(tw_odm, CAPS, "Taiwan server ODM revenue -> HK capacitor prices")
lead_rev(tw_mlcc, CAPS, "Taiwan MLCC makers' revenue -> HK capacitor prices")
lead_rev(tw_found, ['854231','854232','854239','854110','854129'], "Taiwan foundry revenue -> HK IC / discrete prices")
