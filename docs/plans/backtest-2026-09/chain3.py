"""Reverse direction: do HK component prices lead the customer? And are Taiwan fires coincident with spikes already under way?"""
import json, collections, statistics, random, runpy, io, contextlib, pathlib
SP=pathlib.Path('/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad')
random.seed(11); buf=io.StringIO()
with contextlib.redirect_stdout(buf): g=runpy.run_path(str(SP/'bt4.py'), run_name='lib')
Line,ALL,IDX=(g[k] for k in ('Line','ALL','IDX'))
with contextlib.redirect_stdout(buf): c1=runpy.run_path(str(SP/'chain.py'), run_name='lib')
hk,T0,LAST,fires_line=(c1[k] for k in ('hk','T0','LAST','fires_line'))
def fm(ids):
    tot=collections.defaultdict(float); seen=collections.defaultdict(int)
    for i in ids:
        for r in json.load(open(SP/f'finmind_{i}.json'))['data']:
            tot[(r['revenue_year'],r['revenue_month'])]+=r['revenue']; seen[(r['revenue_year'],r['revenue_month'])]+=1
    V=[tot[k] if seen.get(k)==len(ids) else None for k in ALL]
    return Line(V,[1.0 if v else None for v in V])
TW={'server ODM':fm(['2382','2356','6669']),'MLCC makers':fm(['2327','2492','3026']),'foundry':fm(['2330','2303','6770']),'memory':fm(['2408','2344','2337'])}
COMP=['853221','853222','853224','853225','853310','853321','853400','854231','854232','854239','853690','854411','854420','850431','850450']
CAPS=['853221','853222','853224','853225']; ICS=['854231','854232','854239','854110','854129']
print("="*100+"\nTEST 4b — REVERSE: HK component price fire (BOTH) -> Taiwan customer revenue accelerating within 6m?")
print("  outcome: revenue yoy (3m) at t+6 exceeds yoy at t by >= 5pp")
def rev_accel(L,i):
    a,b=L.vv[i],L.vv[i+6] if i+6<len(ALL) else None
    return (b-a>=0.05) if (a is not None and b is not None) else None
for label,dst,src in (('components -> server ODM',TW['server ODM'],COMP),('capacitors -> MLCC makers',TW['MLCC makers'],CAPS),
                      ('ICs/discretes -> foundry',TW['foundry'],ICS),('memory ICs -> memory makers',TW['memory'],['854232'])):
    ev=[]
    for s in src:
        if s not in hk: continue
        for i in fires_line(hk[s]):
            r=rev_accel(dst,i)
            if r is not None: ev.append((i,r))
    if not ev: print(f"  {label:32} no events"); continue
    obs=sum(r for i,r in ev)/len(ev)
    base=[rev_accel(dst,i) for i in range(T0,LAST-5)]; base=[b for b in base if b is not None]
    # permutation: same number of random months
    ge=0
    for _ in range(500):
        pick=[random.choice(range(T0,LAST-5)) for _ in ev]; h=[rev_accel(dst,i) for i in pick]; h=[x for x in h if x is not None]
        if h and sum(h)/len(h)>=obs-1e-9: ge+=1
    print(f"  {label:32} {obs*100:5.1f}% on {len(ev):3} vs base {sum(base)/len(base)*100:.1f}%  p = {ge/500:.3f}")
print("\nTEST 4c — COINCIDENCE: when Taiwan revenue fires, are HK component prices ALREADY spiking?")
print("  share of destination lines with price yoy >= +8% in the fire month, vs the average month")
for label,L,dst in (('server ODM -> components',TW['server ODM'],COMP),('MLCC makers -> capacitors',TW['MLCC makers'],CAPS),('foundry -> ICs',TW['foundry'],ICS)):
    fires=[]; prev=-99
    for i in range(T0,LAST+1):
        if L.vv[i] is not None and L.vv[i]>=0 and L.run(L.vv,i)>=4 and i-prev>=6: prev=i; fires.append(i)
    def share(i): 
        xs=[hk[d].pv[i] for d in dst if d in hk and hk[d].pv[i] is not None]; return (sum(1 for x in xs if x>=0.08)/len(xs)) if xs else None
    at=[share(i) for i in fires]; at=[x for x in at if x is not None]
    allm=[share(i) for i in range(T0,LAST+1)]; allm=[x for x in allm if x is not None]
    print(f"  {label:32} at Taiwan fire months {statistics.mean(at)*100:.0f}% of lines already spiking (n={len(at)} fires)  vs  average month {statistics.mean(allm)*100:.0f}%")
