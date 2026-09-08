import os, sys, json, urllib.request, time, pathlib, collections
os.chdir('/Users/aatang17/Japan_data/Japan_data/observatory')
for line in open('.env'):
    line=line.strip()
    if line and not line.startswith('#') and '=' in line:
        k,v=line.split('=',1); os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0,'.')
from app.adapters import estat_api
SP=pathlib.Path('/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/8d61d0e1-7ccf-4a80-a69c-eec3f814e719/scratchpad')
OUT=SP/'hk_universe.json'
# HS6 list from Japan's HS-9 export classification, electronics/materials chapters
meta=estat_api.call('getMetaInfo', statsDataId='0004049306')['GET_META_INFO']['METADATA_INF']['CLASS_INF']['CLASS_OBJ']
items=[c for c in meta if c['@id']=='cat01'][0]['CLASS']
CH=('84','85','90','28','39','74','75','76')
hs6=sorted({i['@code'][:6] for i in items if i['@code'][:2] in CH})
print('HS6 candidates', len(hs6), flush=True)
have=json.load(open(OUT)) if OUT.exists() else {}
op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
def call(codes):
    url=("https://tradeidds.censtatd.gov.hk/api/get?lang=EN&sv=VCm,QCm&freq=M&period=201501,202607"
         "&ttype=1&codeclass=HKHS6&code="+",".join(codes))
    for a in range(4):
        try:
            d=json.load(op.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=180))
            return d
        except Exception as ex:
            time.sleep(5*(a+1))
    return None
def absorb(d):
    for r in d.get('dataSet',[]):
        c=r.get('code'); p=r.get('period')
        if not c or not p: continue
        fg=r.get('figure')
        if fg in (None,'','-','..'): continue
        try: have.setdefault(c,{}).setdefault(p,{})['v' if r['sv']=='VCm' else 'q']=float(str(fg).replace(',',''))
        except ValueError: continue
def fetch(codes):
    d=call(codes)
    if d is None: print('  network fail', codes[:3], flush=True); return
    st=d['header']['status']
    if st['name']=='Success': absorb(d); return
    msgs=st.get('message',[])
    bad={m.split('(')[1].split(')')[0] for m in msgs if 'Commodity code' in m and '(' in m}
    good=[c for c in codes if c not in bad]
    if bad and good: fetch(good)
    elif not bad:
        if len(codes)>1: fetch(codes[:len(codes)//2]); fetch(codes[len(codes)//2:])
        else: print('  rejected', codes, msgs[:1], flush=True)
todo=[c for c in hs6 if c not in have]
for i in range(0,len(todo),20):
    fetch(todo[i:i+20])
    if (i//20)%5==0:
        json.dump(have, open(OUT,'w')); print(f'  {i+20}/{len(todo)} codes, {len(have)} with data', flush=True)
    time.sleep(0.8)
json.dump(have, open(OUT,'w'))
withq=sum(1 for c in have if any(r.get('q') for r in have[c].values()))
print('DONE', len(have), 'codes with data;', withq, 'with quantity', flush=True)
