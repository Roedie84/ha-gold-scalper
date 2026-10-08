import sys, random; sys.argv=[0,'.']
exec(open('replay.py').read())
base=[simulate(t) for t in TR]
V={'T':[simulate(t,time_stops=True) for t in TR],
   'C1':[simulate(t,confirm=('bars',1)) for t in TR],
   'C3':[simulate(t,confirm=('move',0.25)) for t in TR],
   'B':[None if t['regime']=='range' else simulate(t) for t in TR],
   'TP3.0':[simulate(t,tp_mult=3.0) for t in TR],
   'T+C1':[simulate(t,time_stops=True,confirm=('bars',1)) for t in TR],
   'TP3.0+C3':[simulate(t,tp_mult=3.0,confirm=('move',0.25)) for t in TR]}
cls=sorted(set(t['cluster'] for t in TR))
def percl(res):
    d={c:0.0 for c in cls}
    for t,r in zip(TR,res):
        if r: d[t['cluster']]+=r['net']
    return [d[c] for c in cls]
b=percl(base)
# time exits count for T
print('T exits',{k:sum(1 for r in V['T'] if r['why']==k) for k in ('stop','target','time')}, 'avg dur base %.0f T %.0f'%(st.mean(r['exit_t']-t['e'] for t,r in zip(TR,base)), st.mean(r['exit_t']-r['e_t'] for r in V['T'])))
for k,res in V.items():
    v=percl(res); d=[x-y for x,y in zip(v,b)]
    mu,sd=st.mean(d),st.stdev(d); mua,sda=st.mean(v),st.stdev(v)
    need2=(2*sd/mu)**2 if mu>0 else float('inf'); need3=(3.6*sd/mu)**2 if mu>0 else float('inf')
    needa=(2*sda/mua)**2 if mua>0 else float('inf')
    # cluster bootstrap of per-trade mean (variant) 
    random.seed(2); bs=[]
    for _ in range(5000):
        s=[random.choice(cls) for _ in cls]; xs=[r['net'] for c in s for t,r in zip(TR,res) if r and t['cluster']==c]
        if xs: bs.append(st.mean(xs))
    bs.sort()
    print(k,'diff/cluster mu %.1f sd %.1f t %.2f | clusters nodig verschil t=2: %.0f, t=3.6(Bonferroni 30): %.0f | absoluut netto/cluster mu %.1f sd %.1f, nodig t=2: %s | per-trade 90%%-CI [%.2f, %.2f]'%(mu,sd,mu/(sd/len(d)**.5),need2,need3,mua,sda,('%.0f'%needa) if mua>0 else 'n.v.t. (negatief)',bs[250],bs[4750]))
