import sys, random; sys.argv=[0,'.']
exec(open('replay.py').read())
IS={1,2,3,4,5}; OOS={6,7,8,9,10}
base=[simulate(t) for t in TR]; bn=[r['net'] for r in base]
# selection test: kept trades by confirmation, evaluated with BASELINE outcome (pure selection effect, no entry-price effect)
def sel(cf, B=False):
    keep=[(simulate(t,confirm=cf) is not None) and not (B and t['regime']=='range') for t in TR]
    k=[bn[i] for i in range(len(TR)) if keep[i]]; d=[bn[i] for i in range(len(TR)) if not keep[i]]
    obs=sum(k); n=len(k); random.seed(1)
    ge=sum(1 for _ in range(20000) if sum(random.sample(bn,n))>=obs)
    return n, st.mean(k), st.mean(d) if d else float('nan'), ge/20000
for name,cf,B in [('C1',('bars',1),False),('C2',('bars',2),False),('C3',('move',0.25),False),('B',None,True),('B+C3',('move',0.25),True)]:
    if cf is None:
        keep=[t['regime']!='range' for t in TR]; k=[bn[i] for i in range(len(TR)) if keep[i]]; d=[bn[i] for i in range(len(TR)) if not keep[i]]
        random.seed(1); ge=sum(1 for _ in range(20000) if sum(random.sample(bn,len(k)))>=sum(k))
        print(name,'kept',len(k),'kept/tr(baseline-uitkomst) %.2f'%st.mean(k),'weg/tr %.2f'%st.mean(d),'perm p %.3f'%(ge/20000))
    else:
        n,mk,md,p=sel(cf,B); print(name,'kept',n,'kept/tr(baseline-uitkomst) %.2f'%mk,'weg/tr %.2f'%md,'perm p %.3f'%p)
# combos with time stops
for name,kw,B in [('T+C1',dict(confirm=('bars',1),time_stops=True),False),('T+C3',dict(confirm=('move',0.25),time_stops=True),False),('T+B',dict(time_stops=True),True),('T+TP3.0',dict(time_stops=True,tp_mult=3.0),False),('T+TP3.0+C3',dict(time_stops=True,tp_mult=3.0,confirm=('move',0.25)),False)]:
    res=[None if (B and t['regime']=='range') else simulate(t,**kw) for t in TR]
    a=summarize(res);i=summarize(res,IS);o=summarize(res,OOS)
    print(name,a['n'],a['k'],'%.2f %.2f pf%.2f t%.2f'%(a['net'],a['per'],a['pf'],a['t']),'IS %d %.2f'%(i['n'],i['per']),'OOS %d %.2f'%(o['n'],o['per']))
# time of day (baseline)
def sess(h): return 'Azie 00-07' if h<7 else 'Londen 07-12' if h<12 else 'NY 12-17' if h<17 else 'laat 17-21'
from datetime import datetime,timezone
g={}
for t,r in zip(TR,base):
    h=datetime.fromtimestamp(t['e'],timezone.utc).hour; g.setdefault(sess(h),[]).append((t['cluster'],r['net']))
for s,v in sorted(g.items()): print(s,'n',len(v),'clusters',len(set(c for c,_ in v)),'netto/tr %.2f'%st.mean(x for _,x in v))
# regime x confirm
g={}
for t,r in zip(TR,base): g.setdefault(t['regime'],[]).append(r['net'])
for k,v in g.items(): print('regime',k,len(v),'%.2f'%st.mean(v))
# MFE first 60s: how many losers went immediately wrong
