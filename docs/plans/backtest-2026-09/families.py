"""What else the same machinery detects. Rules unchanged from the validated backtest:
   - Persistence rule (k months of improving 3m yoy, volumes growing) — S1/S3 family
   - Inventory-ratio rule (k months falling, below its own 12m mean) — S7 family
No re-tuning: k is taken from the backtest (S3 k=4, S7 k=4).
"""
import json, collections, statistics, pathlib
SP=pathlib.Path('/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad')
NAMES=json.load(open(SP/'scan.json'))['NAMES']

def months(a,b):
    out=[]; y,m=a
    while (y,m)<=b: out.append((y,m)); y,m=(y+1,1) if m==12 else (y,m+1)
    return out
ALL=months((2001,1),(2026,9)); IDX={k:i for i,k in enumerate(ALL)}
def ymk(s): return IDX.get((int(s[:4]),int(s[5:7])))
def w(a,i,n=3):
    if i-n+1<0 or i>=len(a): return None
    seg=a[i-n+1:i+1]
    if any(x is None for x in seg): return None
    s=sum(seg); return s if s else None
def y3(a,i):
    c,p=w(a,i),w(a,i-12); return (c/p-1) if (c and p) else None
def mean3(a,i):
    s=w(a,i); return s/3 if s is not None else None
def run_up(f,i,cap=24):
    k=0
    while k<cap and f(i-k) is not None and f(i-k-1) is not None and f(i-k)>f(i-k-1): k+=1
    return k
def run_down(f,i,cap=24):
    k=0
    while k<cap and f(i-k) is not None and f(i-k-1) is not None and f(i-k)<f(i-k-1): k+=1
    return k

# ---------- family A: Japan export price/volume, all 254 lines (S1, k=8) ----------
V=collections.defaultdict(float); Q=collections.defaultdict(float)
for fn in ('hist.json','scan.json'):
    d=json.load(open(SP/fn))
    for k,v in d['V'].items():
        c,y,m=k.split('|'); kk=(c,int(y),int(m))
        if fn=='scan.json' and kk in V: continue
        V[kk]=v
    for k,v in d['Q'].items():
        c,y,m=k.split('|'); kk=(c,int(y),int(m))
        if fn=='scan.json' and kk in Q: continue
        Q[kk]=v
codes=sorted({k[0] for k in V})
def line(c):
    v=[V.get((c,)+k) or None for k in ALL]; q=[Q.get((c,)+k) or None for k in ALL]
    return v,q
LAST=IDX[(2026,7)]
print("="*92)
print("FAMILY A — Japan export prices: 254 product lines, monthly, 25-day lag")
print("           rule as validated: 3m unit-value yoy improving 8 months, volumes growing")
print("="*92)
rows=[]
for c in codes:
    v,q=line(c)
    def r3(i):
        cv,pv,cq,pq=w(v,i),w(v,i-12),w(q,i),w(q,i-12)
        return ((cv*1000/cq)/(pv*1000/pq)-1) if (cv and pv and cq and pq) else None
    cur=r3(LAST)
    if cur is None: continue
    ann=sum(x for x in v[LAST-11:LAST+1] if x)
    if ann<2e7: continue
    qg=(w(q,LAST)/w(q,LAST-12)-1) if (w(q,LAST) and w(q,LAST-12)) else None
    if qg is None or qg<=0 or cur<0.05: continue
    rows.append((run_up(r3,LAST), cur, qg, ann, c))
rows.sort(reverse=True)
print(f"  {'run':>3} {'line':38} {'¥bn/yr':>7} {'price':>7} {'volume':>7}   status")
for k,cur,qg,ann,c in rows[:14]:
    st='FIRING' if k>=8 else f'{8-k} months short'
    print(f"  {k:3} {NAMES.get(c,c)[:38]:38} {ann/1e6:7.0f} {cur*100:6.1f}% {qg*100:6.1f}%   {st}")

# ---------- family B: Japan inventory ratios, every industry (S7, k=4) ----------
panel=json.load(open(SP/'iip_panel.json'))
def splice(ind):
    s=dict(panel['2020'].get(ind,{}))
    old=panel['2015'].get(ind)
    if old:
        ov=[k for k in old if k in s and s[k]]
        if len(ov)>=6:
            f=statistics.median(s[k]/old[k] for k in ov)
            for k,x in old.items():
                if k not in s: s[k]=x*f
    out=[None]*len(ALL)
    for k,x in s.items():
        j=ymk(k)
        if j is not None: out[j]=x
    return out
print()
print("="*92)
print("FAMILY B — Japan inventory ratios: 124 industries, monthly, 30-day lag")
print("           rule as validated: 3m ratio falling 4 months AND below its own 12m mean")
print("="*92)
lastB=max(i for i in range(len(ALL)) if any(splice(k)[i] is not None for k in list(panel['2020'])[:3]))
res=[]
for ind in panel['2020']:
    s=splice(ind)
    if s[lastB] is None: continue
    f=lambda i: mean3(s,i)
    if f(lastB) is None: continue
    hist=[f(lastB-j) for j in range(1,13)]; hist=[h for h in hist if h is not None]
    if len(hist)<10: continue
    k=run_down(f,lastB)
    yy=y3(s,lastB)
    res.append((k, f(lastB)/statistics.mean(hist)-1, yy, ind))
res.sort(reverse=True)
print(f"  as of {ALL[lastB][0]}-{ALL[lastB][1]:02d}   {'run':>3} {'industry':44} {'vs 12m mean':>11} {'yoy':>7}")
for k,rel,yy,ind in res[:14]:
    st='FIRING' if (k>=4 and rel<0) else ('below mean, no run' if rel<0 else '')
    print(f"  {'':>10} {k:3} {ind.split(' ',1)[-1][:44]:44} {rel*100:+10.1f}% {(yy*100 if yy is not None else float('nan')):6.1f}%  {st}")

# ---------- family C: Taiwan supply-chain baskets (S3, k=4) ----------
BASKETS={
 'Passives / MLCC':        ['2327','2492','3026'],
 'ABF substrates':         ['3037','8046','3189'],
 'CCL / PCB materials':    ['2383'],
 'Foundry':                ['2330','2303','6770'],
 'Test & packaging (OSAT)':['3711','6239','2449'],
 'Server ODM':             ['2382','2356','6669'],
 'Power & thermal':        ['2308','3017'],
 'Memory':                 ['2408','2344','2337'],
 'ASIC / analog design':   ['3661','6415','2379'],
 'Fab tools & build-out':  ['2360','1560','2404'],
}
LABEL={'2327':'Yageo','2492':'Walsin','3026':'Holy Stone','2330':'TSMC','2303':'UMC','6770':'PSMC',
 '3037':'Unimicron','8046':'Nan Ya PCB','3189':'Kinsus','2383':'Elite Material','3711':'ASE','6239':'Powertech',
 '2449':'KYEC','2382':'Quanta','2356':'Inventec','6669':'Wiwynn','2308':'Delta','3017':'AVC','2408':'Nanya',
 '2344':'Winbond','2337':'Macronix','3661':'Alchip','6415':'Silergy','2379':'Realtek','2360':'Chroma',
 '1560':'Kinik','2404':'United Integrated'}
def basket(ids):
    tot=collections.defaultdict(float); seen=collections.defaultdict(int)
    for i in ids:
        for r in json.load(open(SP/f'finmind_{i}.json'))['data']:
            tot[(r['revenue_year'],r['revenue_month'])]+=r['revenue']; seen[(r['revenue_year'],r['revenue_month'])]+=1
    out=[None]*len(ALL)
    for k,v in tot.items():
        j=IDX.get(k)
        if j is not None and seen[k]==len(ids): out[j]=v
    return out
print()
print("="*92)
print("FAMILY C — Taiwan monthly revenue baskets: every listed company, 10-day lag")
print("           rule as validated: 3m revenue yoy improving 4 months AND >= 0")
print("="*92)
lastC=max(i for i in range(len(ALL)) if basket(['2330'])[i] is not None)
print(f"  as of {ALL[lastC][0]}-{ALL[lastC][1]:02d}")
print(f"  {'run':>3} {'basket':26} {'members':34} {'3m yoy':>8} {'12m yoy':>8}  status")
out=[]
for name,ids in BASKETS.items():
    b=basket(ids)
    f=lambda i: y3(b,i)
    if f(lastC) is None: continue
    k=run_up(f,lastC)
    ttm=(sum(x for x in b[lastC-11:lastC+1] if x)/sum(x for x in b[lastC-23:lastC-11] if x)-1) if all(b[lastC-23:lastC+1]) else None
    out.append((k, f(lastC), ttm, name, ids))
out.sort(reverse=True)
for k,cur,ttm,name,ids in out:
    st='FIRING' if (k>=4 and cur>=0) else (f'{4-k} months short' if cur>=0 else 'yoy negative')
    mem=', '.join(LABEL[i] for i in ids)[:34]
    print(f"  {k:3} {name:26} {mem:34} {cur*100:7.1f}% {(ttm*100 if ttm is not None else float('nan')):7.1f}%  {st}")

# history: when did each basket last fire, and what happened to it
print()
print("  Fire history per basket (k=4 rule, since 2016):")
for name,ids in BASKETS.items():
    b=basket(ids); f=lambda i: y3(b,i)
    fires=[]; last=-99
    for i in range(len(ALL)):
        if ALL[i][0]<2016 or i>lastC: continue
        seq=[f(i-j) for j in range(5)]
        if any(s is None for s in seq): continue
        if all(seq[j]>seq[j+1] for j in range(4)) and seq[0]>=0 and i-last>=6:
            last=i; fires.append(i)
    print(f"    {name:26} {' '.join(f'{ALL[i][0]}-{ALL[i][1]:02d}' for i in fires) or '—'}")

# ---------- family D: US M3, every industry cell (S5 rule, k=2) ----------
import csv
def fred(sid):
    d={}
    for r in csv.DictReader(open(SP/'fred'/f'{sid}.csv')):
        v=r.get(sid)
        if v not in ('.','',None): d[r['observation_date'][:7]]=float(v)
    out=[None]*len(ALL)
    for k,x in d.items():
        j=ymk(k)
        if j is not None: out[j]=x
    return out
CELLS={'Total manufacturing':('AMTMNO','AMTMTI',None),
       'Core capex (nondef ex-air)':('ANDENO',None,'ANDEUO'),
       'Food/textiles (NAICS 311-16)':('A31SNO','A31SVS','A31SIS'),
       'Chemicals/paper/plastics (32)':('A32SNO',None,'A32SIS'),
       'Metals & machinery (33)':('A33SNO','A33SVS','A33SIS'),
       'Computers & electronics (334)':('A34SNO','A34SVS','A34SIS'),
       'Transport equipment (336)':('A36SNO','A36SVS','A36SIS')}
print()
print("="*92)
print("FAMILY D — US manufacturing orders: 7 industry cells, monthly, 35-day lag, ALFRED vintages")
print("           rule as validated: (orders yoy − inventories yoy) improving 2 months AND > 0")
print("="*92)
lastD=max(i for i in range(len(ALL)) if fred('A34SNO')[i] is not None)
print(f"  as of {ALL[lastD][0]}-{ALL[lastD][1]:02d}")
print(f"  {'run':>3} {'industry cell':32} {'orders−inv gap':>15} {'orders yoy':>11}  status")
rowsD=[]
for name,(no,vs,iss) in CELLS.items():
    NO=fred(no)
    if iss and vs:
        SH=fred(vs); IS=fred(iss)
        INV=[(a*b if (a is not None and b is not None) else None) for a,b in zip(IS,SH)]
    elif iss:
        INV=fred(iss)          # unfilled orders as the stock for core capex
    else:
        INV=fred(vs)
    def d(i):
        a,b=y3(NO,i),y3(INV,i); return (a-b) if (a is not None and b is not None) else None
    if d(lastD) is None: continue
    rowsD.append((run_up(d,lastD), d(lastD), y3(NO,lastD), name))
rowsD.sort(reverse=True)
for k,gap,oy,name in rowsD:
    st='FIRING' if (k>=2 and gap>0) else ('gap negative' if gap<=0 else f'{2-k} months short')
    print(f"  {k:3} {name:32} {gap*100:+14.1f}pp {oy*100:10.1f}%  {st}")
