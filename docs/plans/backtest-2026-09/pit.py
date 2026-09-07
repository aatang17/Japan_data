"""Point-in-time check: would S5 / S6 have fired on the data as it stood at publication?"""
import csv, glob, calendar, pathlib, statistics
A=pathlib.Path('/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad/alf')
def load(s,vd):
    f=A/f"{s}_{vd}.csv"
    if not f.exists() or f.stat().st_size==0: return None
    d={}
    for r in csv.reader(open(f)):
        if len(r)>1 and r[0][:2] in ('19','20') and r[1] not in ('.',''): d[r[0][:7]]=float(r[1])
    return d
def addm(ym,k):
    y,m=int(ym[:4]),int(ym[5:])+k
    while m>12: m-=12; y+=1
    while m<1: m+=12; y-=1
    return f"{y}-{m:02d}"
def vd(ym,lag):
    y,m=map(int,addm(ym,lag).split('-')); return f"{y}-{m:02d}-{calendar.monthrange(y,m)[1]}"
def w(d,ym,n=3):
    ks=[addm(ym,-j) for j in range(n)]
    if any(k not in d for k in ks): return None
    return sum(d[k] for k in ks)
def y3(d,ym):
    c,p=w(d,ym),w(d,addm(ym,-12)); return (c/p-1) if (c and p) else None
def improving(f,ym,k):
    seq=[f(addm(ym,-j)) for j in range(k+1)]
    return (not any(s is None for s in seq)) and all(seq[j]>seq[j+1] for j in range(k))
print("S5 US orders−inventories (k=2, lag 2): rule on the vintage available at the end of t+2")
for t in ['2016-02','2017-09','2018-05','2019-04','2020-10','2023-12','2024-06','2025-01','2025-07','2026-01']:
    v=vd(t,2); NO,SH,IS=load('A34SNO',v),load('A34SVS',v),load('A34SIS',v)
    if not (NO and SH and IS): print(f"  {t}: vintage {v} missing"); continue
    INV={k:IS[k]*SH[k] for k in IS if k in SH}
    def d(ym):
        a,b=y3(NO,ym),y3(INV,ym); return (a-b) if (a is not None and b is not None) else None
    ok = improving(d,t,2) and (d(t) or 0)>0
    avail = t in NO
    print(f"  {t}: vintage {v}  data month present={avail}  d(t)={d(t) if d(t) is None else round(d(t)*100,2)}  fires={ok}")
print("\nS6 US PPI capacitors (k=2, lag 1): rule on the vintage available at the end of t+1")
for t in ['2017-02','2018-04','2018-10','2020-02','2021-01','2021-07','2022-07','2023-01','2023-07','2024-02','2025-06']:
    v=vd(t,1); P1,P2=load('WPU117811',v),load('WPU117854',v)
    if not P1 and not P2: print(f"  {t}: vintage {v} missing"); continue
    P=dict(P1 or {})
    if P2 and '2022-12' in P and '2022-12' in P2:
        f=P['2022-12']/P2['2022-12']
        for k,x in P2.items():
            if k not in P: P[k]=x*f
    elif P2 and not P1: P=P2
    def p3(ym):
        a,b=w(P,ym),w(P,addm(ym,-12)); return (a/b-1) if (a and b) else None
    ok = improving(p3,t,2) and (p3(t) is not None and p3(t)>=0)
    print(f"  {t}: vintage {v}  data month present={t in P}  p3(t)={p3(t) if p3(t) is None else round(p3(t)*100,2)}  fires={ok}")
