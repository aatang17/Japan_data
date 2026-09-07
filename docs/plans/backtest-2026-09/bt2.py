"""Round-two backtest. Rules and criteria: SPEC2.md (pre-registered)."""
import json, collections, statistics, math, csv, datetime, pathlib, sys
SP=pathlib.Path('/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad')

# ---------------------------------------------------------------- calendar
def months(a,b):
    out=[]; y,m=a
    while (y,m)<=b: out.append((y,m)); y,m=(y+1,1) if m==12 else (y,m+1)
    return out
ALL=months((2001,1),(2026,9)); IDX={k:i for i,k in enumerate(ALL)}
def key(y,m): return IDX.get((y,m))
def ym(s): return (int(s[:4]), int(s[5:7]))

# ---------------------------------------------------------------- loaders
def series_from_dict(d):
    """{'YYYY-MM': v} -> list aligned to ALL (None where absent)."""
    out=[None]*len(ALL)
    for k,v in d.items():
        i=key(*ym(k))
        if i is not None and v is not None: out[i]=float(v)
    return out

def load_japan_trade():
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
    return V,Q

def load_finmind(ids):
    tot=collections.defaultdict(float)
    for i in ids:
        for r in json.load(open(SP/f'finmind_{i}.json'))['data']:
            tot[(r['revenue_year'], r['revenue_month'])]+=r['revenue']
    out=[None]*len(ALL)
    for (y,m),v in tot.items():
        j=key(y,m)
        if j is not None: out[j]=v
    return out

def load_fred(sid):
    d={}
    for r in csv.DictReader(open(SP/'fred'/f'{sid}.csv')):
        v=r[sid]
        if v not in ('.',''): d[r['observation_date'][:7]]=float(v)
    return series_from_dict(d)

def load_wsts(region='Worldwide'):
    return series_from_dict(json.load(open(SP/'wsts.json'))[region])

def load_iip():
    d=json.load(open(SP/'iip_invratio.json'))
    # splice: newest base wins; older bases rescaled to match on overlap
    bases=['0004052184','0004018301','0003272951']
    out={}
    for b in bases:
        s=d[b]
        if not out: out=dict(s); continue
        ov=[k for k in s if k in out]
        if ov:
            f=statistics.mean(out[k]/s[k] for k in ov if s[k])
        else: f=1.0
        for k,v in s.items():
            if k not in out: out[k]=v*f
    return series_from_dict(out)

def load_comtrade():
    d=json.load(open(SP/'comtrade_kr_8542.json'))
    return series_from_dict({f"{k[:4]}-{k[4:6]}":(v if isinstance(v,(int,float)) else None) for k,v in d.items()})

def load_air():
    d=json.load(open(SP/'air_hs.json'))
    def agg(part, codes):
        V=[0.0]*len(ALL)
        for k,v in d[part]['V'].items():
            c,y,m=k.split('|')
            if c in codes:
                j=key(int(y),int(m))
                if j is not None: V[j]+=v
        return [x if x>0 else None for x in V]
    mlcc={'853224000'}
    caps={c for c in {k.split('|')[0] for k in d['all']['V']} if c.startswith('8532')}
    ics={c for c in {k.split('|')[0] for k in d['all']['V']} if c.startswith('8542')}
    return {n:(agg('air',cs),agg('all',cs)) for n,cs in (('mlcc',mlcc),('caps',caps),('ics',ics))}

def load_prices():
    px={}
    for t in ('6981.T','6976.T','6762.T','6971.T','2327.TW','2492.TW','009150.KS','MU','000660.KS','005930.KS','1306.T','1321.T','SOXX'):
        me=json.load(open(SP/'pxd'/f'{t}.json'))
        s=[None]*len(ALL)
        for k_,(c,ac,d_) in me.items():
            j=key(*ym(k_))
            if j is not None and ac and ac>0: s[j]=ac   # month-end adjusted close
        px[t]=s
    return px

# ---------------------------------------------------------------- transforms
def w(a,i,n=3):
    if i-n+1<0 or i>=len(a): return None
    seg=a[i-n+1:i+1]
    if any(x is None for x in seg): return None
    s=sum(seg); return s if s!=0 else None
def y3(a,i):
    c,p=w(a,i),w(a,i-12)
    return (c/p-1) if (c and p) else None
def mean3(a,i):
    s=w(a,i); return s/3 if s is not None else None
def improving(f,i,k):
    seq=[f(i-j) for j in range(k+1)]
    if any(s is None for s in seq): return False
    return all(seq[j]>seq[j+1] for j in range(k))
def falling(f,i,k):
    seq=[f(i-j) for j in range(k+1)]
    if any(s is None for s in seq): return False
    return all(seq[j]<seq[j+1] for j in range(k))

# ---------------------------------------------------------------- build inputs
VJ,QJ=load_japan_trade()
def jp_line(code):
    v=[VJ.get((code,)+k) for k in ALL]; q=[QJ.get((code,)+k) for k in ALL]
    v=[x if x else None for x in v]; q=[x if x else None for x in q]
    return v,q
CAP_V,CAP_Q=jp_line('70329000')
def cap_P3(i):
    a,b=w(CAP_V,i),w(CAP_Q,i)
    return a*1000/b if (a and b) else None

TW_MLCC=load_finmind(['2327','2492','3026'])
KR_IC=load_comtrade()
M3_NO=load_fred('A34SNO'); M3_SH=load_fred('A34SVS'); M3_IS=load_fred('A34SIS')
M3_INV=[(a*b if (a is not None and b is not None) else None) for a,b in zip(M3_IS,M3_SH)]
P1=load_fred('WPU117811'); P2=load_fred('WPU117854')
# splice PPI: WPU117854 (Dec-2022=100) scaled to WPU117811 at Dec-2022
j=key(2022,12); f=P1[j]/P2[j]
PPI=[(P1[i] if P1[i] is not None else (P2[i]*f if P2[i] is not None else None)) for i in range(len(ALL))]
IIP=load_iip()
WSTS=load_wsts()
AIR=load_air()
PX=load_prices()

# ---------------------------------------------------------------- signals
def S1(i):
    # validated in round one; recompute here on the capacitor line only is NOT the rule —
    # S1 is universe-wide. Load the fires file from round one instead.
    return None
S1_FIRES=set()
for f in json.load(open(SP/'fires_A.json')) if (SP/'fires_A.json').exists() else []:
    pass
# Round-one persistence fires are recomputed here exactly as split.py did (k=8), universe-wide.
def s1_fires():
    codes=sorted({k[0] for k in VJ})
    R={}
    for c in codes:
        v,q=jp_line(c)
        for i in range(len(ALL)):
            cv,pv,cq,pq=w(v,i),w(v,i-12),w(q,i),w(q,i-12)
            if cv and pv and cq and pq: R[(c,i)]=((cv*1000/cq)/(pv*1000/pq)-1, cv/pv-1, cq/pq-1)
    out=[]; last={}
    for i in range(len(ALL)):
        for c in codes:
            if (c,i) not in R: continue
            r3,v3,q3=R[(c,i)]
            if r3<0.08 or q3<=0 or v3<=0: continue
            seq=[R.get((c,i-j)) for j in range(9)]
            if any(s is None for s in seq) or not all(seq[j][0]>seq[j+1][0] for j in range(8)): continue
            if i-last.get(c,-99)<6: continue
            last[c]=i; out.append((i,c))
    return out

SIG={}   # name -> dict(fn=lambda i,k: bool, ks=[...], lag=L, target='T1'|'T2')
def air_rule(name):
    air,tot=AIR[name]
    def a3(i):
        a,b=w(air,i),w(tot,i)
        return a/b if (a and b) else None
    def fn(i,k):
        if not improving(a3,i,k): return False
        hist=[a3(s) for s in range(i-36,i-12)]; hist=[h for h in hist if h is not None]
        return len(hist)>=12 and a3(i)>statistics.median(hist)
    return fn
SIG['S2 air share MLCC']=dict(fn=air_rule('mlcc'),lag=1,target='T1')
SIG['S2 air share ICs']=dict(fn=air_rule('ics'),lag=1,target='T2')
SIG['S3 Taiwan MLCC revenue']=dict(fn=lambda i,k: improving(lambda j:y3(TW_MLCC,j),i,k) and y3(TW_MLCC,i)>=0,lag=1,target='T1')
SIG['S4 Korea IC exports']=dict(fn=lambda i,k: improving(lambda j:y3(KR_IC,j),i,k) and y3(KR_IC,i)>=0,lag=1,target='T2')
def m3d(i):
    a,b=y3(M3_NO,i),y3(M3_INV,i)
    return (a-b) if (a is not None and b is not None) else None
SIG['S5 US orders−inventories']=dict(fn=lambda i,k: improving(m3d,i,k) and m3d(i)>0,lag=2,target='T2')
def ppi_p3(i):
    c,p=mean3(PPI,i),mean3(PPI,i-12)
    return (c/p-1) if (c and p) else None
SIG['S6 US PPI capacitors']=dict(fn=lambda i,k: improving(ppi_p3,i,k) and ppi_p3(i)>=0,lag=1,target='T1')
def iip_r3(i): return mean3(IIP,i)
def s7(i,k):
    if not falling(iip_r3,i,k): return False
    hist=[iip_r3(s) for s in range(i-12,i)]; hist=[h for h in hist if h is not None]
    return len(hist)>=10 and iip_r3(i)<statistics.mean(hist)
SIG['S7 Japan parts inventory ratio']=dict(fn=s7,lag=1,target='T1')
SIG['S8 WSTS billings']=dict(fn=lambda i,k: improving(lambda j:y3(WSTS,j),i,k) and y3(WSTS,i)>=0,lag=2,target='T2')

KS=[2,3,4,6,8]
def fires_for(name,k,lo,hi):
    fn=SIG[name]['fn']; out=[]; last=-99
    for i in range(len(ALL)):
        if not (lo<=ALL[i][0]<=hi): continue
        try: ok=fn(i,k)
        except Exception: ok=False
        if ok and i-last>=6: last=i; out.append(i)
    return out

# ---------------------------------------------------------------- targets
def t1(i):
    a,b=cap_P3(i),cap_P3(i+6)
    return (b>=a) if (a and b) else None
def t2(i):
    a,b=w(KR_IC,i),w(KR_IC,i+6)
    return (b>=a) if (a and b) else None
TARGET={'T1':t1,'T2':t2}
def base_rate(tf,lo,hi):
    xs=[tf(i) for i in range(len(ALL)) if lo<=ALL[i][0]<=hi]
    xs=[x for x in xs if x is not None]
    return (sum(xs)/len(xs), len(xs)) if xs else (None,0)
def hit(F,tf):
    xs=[tf(i) for i in F]; xs=[x for x in xs if x is not None]
    return (sum(xs)/len(xs), len(xs)) if xs else (None,0)

def basket_ret(tickers, bench, i_entry, h):
    rs=[]
    for t in tickers:
        s=PX[t]
        if i_entry+h<len(s) and s[i_entry] and s[i_entry+h]: rs.append(s[i_entry+h]/s[i_entry]-1)
    if not rs: return None
    b=PX[bench]
    if not (i_entry+h<len(b) and b[i_entry] and b[i_entry+h]): return None
    return statistics.mean(rs)-(b[i_entry+h]/b[i_entry]-1)
MLCC_B=['6981.T','6976.T','6762.T','2327.TW','2492.TW','009150.KS']; MEM_B=['MU','000660.KS','005930.KS']
def equity(F,lag,which,h):
    tick,bench=(MLCC_B,'1321.T') if which=='T1' else (MEM_B,'SOXX')
    xs=[basket_ret(tick,bench,i+lag,h) for i in F]; xs=[x for x in xs if x is not None]
    return (statistics.mean(xs), sum(1 for x in xs if x>0)/len(xs), len(xs), statistics.median(xs)) if xs else (None,None,0,None)
def equity_base(lo,hi,which,h):
    tick,bench=(MLCC_B,'1321.T') if which=='T1' else (MEM_B,'SOXX')
    xs=[basket_ret(tick,bench,i,h) for i in range(len(ALL)) if lo<=ALL[i][0]<=hi]; xs=[x for x in xs if x is not None]
    return (statistics.mean(xs), sum(1 for x in xs if x>0)/len(xs), len(xs), statistics.median(xs)) if xs else (None,None,0,None)

# ---------------------------------------------------------------- run
def fmt(x,pct=True): return ('%+.1f%%'%(x*100)) if (x is not None and pct) else ('–' if x is None else str(x))
print("ROUND TWO — multi-source backtest (spec: SPEC2.md)\n")
print("Data coverage:")
for n,s in (('TW MLCC rev',TW_MLCC),('KR IC exp',KR_IC),('US M3 orders',M3_NO),('US PPI caps',PPI),('JP IIP inv ratio',IIP),('WSTS',WSTS),('JP cap export val',CAP_V)):
    ks=[ALL[i] for i,x in enumerate(s) if x is not None]
    print(f"  {n:18} {ks[0][0]}-{ks[0][1]:02d} .. {ks[-1][0]}-{ks[-1][1]:02d}  n={len(ks)}")
for n,(a,t) in AIR.items():
    ks=[ALL[i] for i,x in enumerate(a) if x is not None]
    print(f"  air {n:14} {ks[0][0]}-{ks[0][1]:02d} .. {ks[-1][0]}-{ks[-1][1]:02d}  n={len(ks)}")

TR=(2005,2015); TE=(2016,2026)
results={}
print("\n== Base rates ==")
for tn,tf in TARGET.items():
    for lab,(lo,hi) in (('train',TR),('test',TE)):
        p,n=base_rate(tf,lo,hi); print(f"  {tn} {lab}: {fmt(p)} (n={n})")
for which,h in (('T1',6),('T2',6)):
    m,hr,n,md=equity_base(TE[0],TE[1],which,h); print(f"  equity {which} basket 6m excess, test: mean {fmt(m)} median {fmt(md)} hit {fmt(hr)} n={n}")

print("\n== S1 (fixed from round one) ==")
F1=s1_fires()
F1_test=[i for i,c in F1 if TE[0]<=ALL[i][0]<=TE[1]]
p,n=hit(F1_test,t1); print(f"  test fires {len(F1_test)} (universe-wide); own-line result from round one: 73% still elevated at 6m vs 59% base. Scoring against T1 here is NOT meaningful (one target series shared by all fires): {fmt(p)}")
F1_cap=[i for i,c in F1 if c=='70329000']
print("  capacitor fires:", [f"{ALL[i][0]}-{ALL[i][1]:02d}" for i in F1_cap])
results['S1']={'fires_test':F1_test}

print("\n== Single signals: k chosen on TRAIN, evaluated on TEST ==")
allfires={}
for name,cfg in SIG.items():
    tf=TARGET[cfg['target']]
    # POST-HOC (data availability, recorded in SPEC2): T2 (Korea) starts 2013, so a
    # signal whose natural target is T2 is trained on T1 when T2 has < 3 scorable train fires.
    def choose(ttf):
        best=None
        for k in KS:
            F=fires_for(name,k,*TR)
            p,n=hit(F,ttf)
            if p is None or n<3: continue
            if best is None or p>best[1]: best=(k,p,n,len(F)/132)
        return best
    best=choose(tf)
    if best is None and cfg['target']=='T2':
        best=choose(t1)
        if best: print(f"  [{name}: k trained on T1 — too few T2-scorable train fires]")
    if best is None:
        print(f"  {name:32} no usable train fires"); continue
    k=best[0]
    Ft=fires_for(name,k,*TE)
    p,n=hit(Ft,tf); bp,_=base_rate(tf,*TE)
    se=math.sqrt(p*(1-p)/n) if (p is not None and n) else None
    e3=equity(Ft,cfg['lag'],cfg['target'],3); e6=equity(Ft,cfg['lag'],cfg['target'],6); e12=equity(Ft,cfg['lag'],cfg['target'],12)
    allfires[name]=Ft
    print(f"  {name:32} k={k} | train hit {fmt(best[1])} (n={best[2]}) | TEST fires {len(Ft)}  {cfg['target']} hit {fmt(p)}±{fmt(se) if se else '–'} vs base {fmt(bp)} (n={n}) | equity 6m excess mean {fmt(e6[0])} median {fmt(e6[3])} hit {fmt(e6[1])} (n={e6[2]}); 3m {fmt(e3[0])} 12m {fmt(e12[0])}")
    print("      fires:", ' '.join(f"{ALL[i][0]}-{ALL[i][1]:02d}" for i in Ft))
    results[name]={'k':k,'fires_test':Ft,'hit':p,'n':n,'base':bp,'eq6':e6}

tot=len(F1_test)+sum(len(v) for v in allfires.values())
print(f"\n== Alert load on TEST: {tot} fires over 127 months = {tot/127:.2f}/month (S1 universe-wide contributes {len(F1_test)}) ==")
print("\n== Combination: count of signals (S1–S8) fired within [t-2,t] ==")
fired_at=collections.defaultdict(set)
for i in F1_test: fired_at[i].add('S1')
for name,Ft in allfires.items():
    for i in Ft: fired_at[i].add(name)
def count_at(i):
    s=set()
    for j in (i-2,i-1,i): s|=fired_at.get(j,set())
    return len(s), s
for thr in (2,3):
    C=[]; last=-99
    for i in range(len(ALL)):
        if not (TE[0]<=ALL[i][0]<=TE[1]): continue
        n,s=count_at(i)
        if n>=thr and i-last>=6: last=i; C.append((i,s))
    for tn,tf in TARGET.items():
        p,n=hit([i for i,_ in C],tf); bp,_=base_rate(tf,*TE)
        print(f"  C{thr}: {len(C)} fires | {tn} hit {fmt(p)} vs base {fmt(bp)} (n={n})")
    for which in ('T1','T2'):
        e=equity([i for i,_ in C],2,which,6); print(f"      equity {which} 6m excess mean {fmt(e[0])} median {fmt(e[3])} hit {fmt(e[1])} n={e[2]}")
    for i,s in C: print(f"      {ALL[i][0]}-{ALL[i][1]:02d}  {sorted(s)}")

print("\n== Episode recall (test window): which signals fired in each window ==")
EP={'2017-18 MLCC/passives & DRAM':((2016,10),(2018,6)),'2021-22 semis shortage':((2020,9),(2022,3)),'2025-26 AI buildout':((2025,3),(2026,7))}
for ep,(a,b) in EP.items():
    lo,hi=IDX[a],IDX[b]
    print(f"  {ep}:")
    for name,Ft in [('S1 (any line)',F1_test)]+list(allfires.items()):
        xs=[ALL[i] for i in Ft if lo<=i<=hi]
        print(f"    {name:32} {' '.join(f'{y}-{m:02d}' for y,m in xs) or '—'}")
    xs=[ALL[i] for i in F1_cap if lo<=i<=hi]; print(f"    {'S1 capacitors line':32} {' '.join(f'{y}-{m:02d}' for y,m in xs) or '—'}")
json.dump({k:{kk:(vv if not isinstance(vv,list) else vv) for kk,vv in v.items()} for k,v in results.items()}, open(SP/'bt2_results.json','w'), default=str)

# ---------------------------------------------------------------- post-hoc additions
print("\n== S4 Korea IC exports — UNTRAINED (series starts 2013): evaluated at k=4, borrowed from S8, same rule family ==")
Ft=fires_for('S4 Korea IC exports',4,*TE)
p,n=hit(Ft,t2); bp,_=base_rate(t2,*TE); e6=equity(Ft,1,'T2',6)
print(f"  TEST fires {len(Ft)}  T2 hit {fmt(p)} vs base {fmt(bp)} (n={n}) | equity 6m excess mean {fmt(e6[0])} median {fmt(e6[3])} hit {fmt(e6[1])} (n={e6[2]})")
print("  fires:", ' '.join(f"{ALL[i][0]}-{ALL[i][1]:02d}" for i in Ft))

print("\n== Lead time to the target's local peak (months from PUBLICATION month of the firing data) ==")
def peak_after(series_fn, i, horizon=18):
    best=None
    for j in range(i, min(i+horizon, len(ALL))):
        v=series_fn(j)
        if v is not None and (best is None or v>best[1]): best=(j,v)
    return best
EPW={'2017-18':((2016,10),(2018,6)),'2021-22':((2020,9),(2022,3)),'2025-26':((2025,3),(2026,7))}
lags={'S1':1,'S2 air share MLCC':1,'S2 air share ICs':1,'S3 Taiwan MLCC revenue':1,'S4 Korea IC exports':1,'S5 US orders−inventories':2,'S6 US PPI capacitors':1,'S7 Japan parts inventory ratio':1,'S8 WSTS billings':2}
allf=dict(allfires); allf['S4 Korea IC exports']=Ft; allf['S1 capacitors line']=F1_cap
for ep,(a,b) in EPW.items():
    lo,hi=IDX[a],IDX[b]
    # capacitor unit value peak and Korea IC export peak after the window start
    pk1=peak_after(cap_P3, lo, hi-lo+12); pk2=peak_after(lambda j: w(KR_IC,j), lo, hi-lo+12)
    print(f"  {ep}: capacitor price peak {ALL[pk1[0]][0]}-{ALL[pk1[0]][1]:02d}" + (f", Korea IC export peak {ALL[pk2[0]][0]}-{ALL[pk2[0]][1]:02d}" if pk2 else ""))
    for name,F in allf.items():
        first=[i for i in F if lo<=i<=hi]
        if not first: continue
        i=first[0]; L=lags.get(name,1); pub=i+L
        tgt=pk1 if name in ('S1','S1 capacitors line','S2 air share MLCC','S3 Taiwan MLCC revenue','S6 US PPI capacitors','S7 Japan parts inventory ratio') else (pk2 or pk1)
        lead=tgt[0]-pub
        print(f"     {name:30} first fire {ALL[i][0]}-{ALL[i][1]:02d}, published {ALL[pub][0]}-{ALL[pub][1]:02d}, lead to peak {lead:+d} months")
