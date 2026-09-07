"""Backtest of the divergence detector. Spec: SPEC.md (pre-registered)."""
import json, collections, statistics, sys

SP='/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad/'
NAMES=json.load(open(SP+'scan.json'))['NAMES']

def load():
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
    return V,Q

def months(a,b):
    out=[]; y,m=a
    while (y,m)<=b:
        out.append((y,m)); y,m=(y+1,1) if m==12 else (y,m+1)
    return out

def run():
    V,Q=load()
    codes=sorted({k[0] for k in V})
    allm=months((2001,1),(2026,7))
    idx={k:i for i,k in enumerate(allm)}
    # per line: monthly arrays, trailing zero months dropped (uncovered)
    S={}
    for c in codes:
        v=[V.get((c,)+k,0.0) for k in allm]
        q=[Q.get((c,)+k,0.0) for k in allm]
        last=max([i for i,x in enumerate(v) if x>0] or [-1])
        S[c]=(v[:last+1], q[:last+1])
    def win(a,i,n=3):
        if i-n+1<0 or i>=len(a): return None
        return sum(a[i-n+1:i+1])
    def r3v3q3(c,i):
        v,q=S[c]
        cv,pv=win(v,i),win(v,i-12); cq,pq=win(q,i),win(q,i-12)
        if not cv or not pv or not cq or not pq: return None
        return (cv*1000/cq)/(pv*1000/pq)-1, cv/pv-1, cq/pq-1
    R={}
    for c in codes:
        for i in range(len(S[c][0])):
            r=r3v3q3(c,i)
            if r: R[(c,i)]=r
    # cross-sectional median of r3 by month (FX / global inflation control)
    bym=collections.defaultdict(list)
    for (c,i),(r,_v,_q) in R.items(): bym[i].append(r)
    xmed={i:statistics.median(v) for i,v in bym.items() if len(v)>=30}
    def score(c,i,use_x):
        hist=[]
        for s in range(i-132,i-12):
            if (c,s) in R:
                r=R[(c,s)][0]
                if use_x:
                    if s not in xmed: continue
                    r=r-xmed[s]
                hist.append(r)
        if len(hist)<60: return None
        med=statistics.median(hist)
        mad=statistics.median([abs(h-med) for h in hist])*1.4826
        cur=R[(c,i)][0]-(xmed.get(i,0.0) if use_x else 0.0)
        return (cur-med)/max(mad,0.02), cur
    def fires(use_x):
        out=[]; last={}
        for i in range(len(allm)):
            for c in codes:
                if (c,i) not in R: continue
                sc=score(c,i,use_x)
                if not sc: continue
                z,cur=sc
                r3,v3,q3=R[(c,i)]
                if z<3.0 or cur<0.08 or v3<=0 or q3<-0.15: continue
                if i-last.get(c,-99)<6: continue
                last[c]=i
                out.append(dict(code=c,i=i,month=allm[i],z=z,cur=cur,r3=r3,v3=v3,q3=q3))
        return out
    def evaluate(F,label):
        print('\n'+'='*78); print(label); print('='*78)
        print(f"fires: {len(F)} over {len(allm)} months, {len(codes)} lines")
        per=collections.Counter(f['month'] for f in F)
        loads=[per.get(m,0) for m in allm[132:]]
        print(f"alert load per month: median {statistics.median(loads):.1f}, mean {statistics.mean(loads):.2f}, max {max(loads)}")
        cont=[]; blip=[]
        for f in F:
            c,i=f['code'],f['i']; v,q=S[c]
            def P(j):
                a,b=win(v,j),win(q,j)
                return (a*1000/b) if a and b else None
            p0=P(i)
            fwd=[P(i+k) for k in range(1,7)]
            fwd=[x for x in fwd if x]
            if p0 and len(fwd)>=3:
                cont.append(statistics.median(fwd)/p0-1)
                p6=P(i+6)
                if p6: blip.append(p6>=p0)
        if cont:
            print(f"continuation: median forward 6m unit value {statistics.median(cont)*100:+.1f}%, "
                  f"hit rate {sum(1 for x in cont if x>0)/len(cont)*100:.0f}% (n={len(cont)})")
        if blip:
            print(f"still above 6m later: {sum(blip)/len(blip)*100:.0f}%")
        return F
    for use_x,label in ((False,'VARIANT A — own-history z-score'),
                        (True,'VARIANT B — excess over cross-sectional median')):
        F=evaluate(fires(use_x),label)
        print('\n  fires by year:')
        yr=collections.Counter(f['month'][0] for f in F)
        print('   ', ' '.join(f"{y}:{n}" for y,n in sorted(yr.items())))
        print('\n  every fire on capacitors (70329000) and ICs (70323050):')
        for f in F:
            if f['code'] in ('70329000','70323050'):
                print(f"    {f['month'][0]}-{f['month'][1]:02d}  {NAMES.get(f['code'],f['code'])[:28]:28} "
                      f"z={f['z']:5.1f}  price {f['cur']*100:+6.1f}%  value {f['v3']*100:+6.1f}%  qty {f['q3']*100:+6.1f}%")
        print('\n  most recent 25 fires:')
        for f in F[-25:]:
            print(f"    {f['month'][0]}-{f['month'][1]:02d}  {NAMES.get(f['code'],f['code'])[:30]:30} "
                  f"z={f['z']:5.1f}  price {f['cur']*100:+6.1f}%  value {f['v3']*100:+6.1f}%  qty {f['q3']*100:+6.1f}%")
        json.dump([{**f,'month':f"{f['month'][0]}-{f['month'][1]:02d}",'name':NAMES.get(f['code'],f['code'])} for f in F],
                  open(SP+('fires_%s.json'%('B' if use_x else 'A')),'w'), ensure_ascii=False, indent=1)

run()
