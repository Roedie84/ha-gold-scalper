import sys; sys.argv=[0,'.']
exec(open('replay.py').read())
IS={1,2,3,4,5}; OOS={6,7,8,9,10}
CONF={'-':None,'C1':('bars',1),'C2':('bars',2),'C3':('move',0.25)}
base=[simulate(t) for t in TR]
bcl=summarize(base)['cl']
out=[]
for tp in (1.5,2.25,3.0):
  for B in (False,True):
    for cn,cf in CONF.items():
      res=[]
      for t in TR:
        if B and t['regime']=='range': res.append(None); continue
        res.append(simulate(t,tp_mult=tp,confirm=cf))
      a=summarize(res); i=summarize(res,IS); o=summarize(res,OOS)
      diff=[x-y for x,y in zip(a['cl'],bcl)]
      name=f"TP{tp}"+("+B" if B else "")+("+"+cn if cn!='-' else "")
      out.append((name,a,i,o,tstat(diff),sum(diff)))
for tsv in (False,True):
  res=[simulate(t,time_stops=True)] if False else [simulate(t,time_stops=True) for t in TR]
a=summarize(res); i=summarize(res,IS); o=summarize(res,OOS); diff=[x-y for x,y in zip(a['cl'],bcl)]
out.append(("TP1.5+tijdstops",a,i,o,tstat(diff),sum(diff)))
f=lambda x:('%.2f'%x)
print('variant | n | k | netto | netto/tr | PF | t_cl | win | doel | IS n/netto/tr/t | OOS n/netto/tr/t | t_diff vs basis | delta')
for name,a,i,o,td,dd in out:
  print(name,'|',a['n'],'|',a['k'],'|',f(a['net']),'|',f(a['per']),'|',f(a['pf']),'|',f(a['t']),'|',f(a['win']),'|',f(a['tgt']),'|',i['n'],f(i['net']),f(i['per']),f(i['t']),'|',o['n'],f(o['net']),f(o['per']),f(o['t']),'|',f(td),'|',f(dd))
json.dump([(n,a['cl']) for n,a,*_ in out],open('cl.json','w'))
