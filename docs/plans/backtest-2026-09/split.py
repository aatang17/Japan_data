"""Train/test split. Rule and objective declared before running; k chosen on
2001-2015 only, evaluated untouched on 2016-2026."""
import json, collections, statistics
SP='/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad/'
NAMES=json.load(open(SP+'scan.json'))['NAMES']
V=collections.defaultdict(float); Q=collections.defaultdict(float)
for fn in ('hist.json','scan.json'):
    d=json.load(open(SP+fn))
    for k,v in d['V'].items():
        c,y,m=k.split('|'); key=(c,int(y),int(m))
        if fn=='scan.json' and key in V: continue
        V[key]=v
    for k,v in d['Q'].items():
        c,y,m=k.split('|'); key=(c,int(y),int(m))
        if fn=='scan.json' and key in Q: continue
        Q[key]=v
allm=[]; y,m=2001,1
while (y,m)<=(2026,7):
    allm.append((y,m)); y,m=(y+1,1) if m==12 else (y,m+1)
codes=sorted({k[0] for k in V}); S={}
for c in codes:
    v=[V.get((c,)+k,0.0) for k in allm]; q=[Q.get((c,)+k,0.0) for k in allm]
    last=max([i for i,x in enumerate(v) if x>0] or [-1]); S[c]=(v[:last+1], q[:last+1])
def w(a,i,n=3):
    if i-n+1<0 or i>=len(a): return None
    s=sum(a[i-n+1:i+1]); return s if s>0 else None
def P(c,i):
    v,q=S[c]; a,b=w(v,i),w(q,i); return a*1000/b if a and b else None
R={}
for c in codes:
    v,q=S[c]
    for i in range(len(v)):
        cv,pv,cq,pq=w(v,i),w(v,i-12),w(q,i),w(q,i-12)
        if cv and pv and cq and pq:
            R[(c,i)]=((cv*1000/cq)/(pv*1000/pq)-1, cv/pv-1, cq/pq-1)

# RULE P (declared before running): price yoy has improved k months running,
# is >= +8%, and volumes are growing. 6-month cooldown. No z-score.
def fires(k, lo, hi):
    out=[]; last={}
    for i in range(len(allm)):
        if not (lo<=allm[i][0]<=hi): continue
        for c in codes:
            if (c,i) not in R: continue
            r3,v3,q3=R[(c,i)]
            if r3<0.08 or q3<=0 or v3<=0: continue
            seq=[R.get((c,i-j)) for j in range(k+1)]
            if any(s is None for s in seq): continue
            if not all(seq[j][0]>seq[j+1][0] for j in range(k)): continue
            if i-last.get(c,-99)<6: continue
            last[c]=i; out.append((c,i,r3,v3,q3))
    return out
def stats(F):
    cont=[]; b6=[]
    for c,i,*_ in F:
        p0=P(c,i); fwd=[P(c,i+j) for j in range(1,7)]; fwd=[x for x in fwd if x]
        if p0 and len(fwd)>=3:
            cont.append(statistics.median(fwd)/p0-1)
            p6=P(c,i+6)
            if p6: b6.append(p6>=p0)
    per=collections.Counter(allm[i] for _c,i,*_ in F)
    yrs=[m for m in allm if m[0]>=2001]
    load=statistics.mean([per.get(m,0) for m in yrs])
    return (len(F), load,
            statistics.median(cont)*100 if cont else None,
            (sum(1 for x in cont if x>0)/len(cont)*100) if cont else None,
            (sum(b6)/len(b6)*100) if b6 else None)
def baserate(lo,hi):
    b=[]; b6=[]
    for c in codes:
        for i in range(12,len(S[c][0])-6):
            if not (lo<=allm[i][0]<=hi): continue
            p0=P(c,i); fwd=[P(c,i+j) for j in range(1,7)]; fwd=[x for x in fwd if x]
            if p0 and len(fwd)>=3:
                b.append(statistics.median(fwd)/p0-1)
                p6=P(c,i+6)
                if p6: b6.append(p6>=p0)
    return statistics.median(b)*100, sum(1 for x in b if x>0)/len(b)*100, sum(b6)/len(b6)*100

print("TRAIN 2001-2015 — choose k. Objective: maximise 'still above 6m later'")
print("subject to alert load <= 3/month.  Base rate:", "%.2f%% / %.0f%% / %.0f%%" % baserate(2001,2015))
best=None
for k in (2,3,4,5,6,8):
    n,load,cm,hit,ab=stats(fires(k,2001,2015))
    print(f"  k={k}: fires {n:4}  load {load:4.2f}/mo  fwd6m median {cm:+5.1f}%  hit {hit:3.0f}%  above-6m {ab:3.0f}%")
    if load<=3 and (best is None or ab>best[1]): best=(k,ab)
k=best[0]
print(f"\n  --> k = {k} chosen on the training period alone\n")
print("TEST 2016-2026 — untouched.  Base rate:", "%.2f%% / %.0f%% / %.0f%%" % baserate(2016,2026))
F=fires(k,2016,2026)
n,load,cm,hit,ab=stats(F)
print(f"  fires {n}  load {load:.2f}/mo  fwd6m median {cm:+.1f}%  hit {hit:.0f}%  above-6m {ab:.0f}%")
print("  fires by year: " + ' '.join(f"{y}:{c}" for y,c in sorted(collections.Counter(allm[i][0] for _c,i,*_ in F).items())))
print("\n  every test-period fire:")
for c,i,r3,v3,q3 in F:
    print(f"    {allm[i][0]}-{allm[i][1]:02d}  {NAMES.get(c,c)[:34]:34} price {r3*100:+6.1f}%  value {v3*100:+6.1f}%  qty {q3*100:+6.1f}%")
