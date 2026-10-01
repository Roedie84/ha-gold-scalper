"""Fase 3: thread tegenover proces. Gebruik:

    python tools/lab_executor_benchmark.py <aanvraag.json>

De aanvraag is een RunRequest als JSON (zie experiment_lab/worker.py).

Thread tegenover proces: wat merkt een event loop zoals die van Home Assistant?

Nagebootst, want Home Assistant draait hier niet: een asyncio-lus met
  - een tik elke 50 ms, waarvan de vertraging wordt gemeten (event-loop-lag)
  - elke seconde een 'coordinatorcyclus': de strategie-evaluatie op 800 bars,
    het CPU-deel van een echte cyclus, waarvan de duur wordt gemeten.
"""
import asyncio, json, os, resource, statistics, subprocess, sys, threading, time
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests")); import conftest  # noqa: E402,F401
sys.path.append(os.path.join(ROOT, "custom_components"))
from gold_scalper.broker.simulator import SimulatorVenue
from gold_scalper.strategy.scalping import ScalpConfig, evaluate
from gold_scalper.experiment_lab.worker import RunRequest, execute, Cancelled
ENTRY=os.path.join(ROOT,"custom_components","gold_scalper","experiment_lab","worker_entry.py")
REQ=json.load(open(sys.argv[1]))
WINDOW=asyncio.run(SimulatorVenue(seed=3).candles("XAU_USD","15m",800))
CFG=ScalpConfig()
def pct(xs,p):
    xs=sorted(xs); return xs[min(len(xs)-1,int(len(xs)*p))] if xs else 0.0
def p(*a): print(*a, flush=True)

async def probe(klaar):
    lag, cyclus = [], []
    volgende = time.perf_counter()
    laatste_cyclus = time.perf_counter()
    while not klaar():
        volgende += 0.05
        await asyncio.sleep(max(0, volgende - time.perf_counter()))
        lag.append((time.perf_counter() - volgende) * 1000)
        if time.perf_counter() - laatste_cyclus >= 1.0:
            laatste_cyclus = time.perf_counter()
            t = time.perf_counter()
            evaluate(WINDOW, WINDOW.close[-1]-0.3, WINDOW.close[-1]+0.3, CFG, 12, 0)
            cyclus.append((time.perf_counter() - t) * 1000)
    return lag, cyclus

def rapport(naam, lag, cyclus, duur, cpu, mem_mb, bars):
    p(f"{naam:9s} | {duur:6.1f}s | {bars/duur if duur else 0:6.0f} bars/s | CPU {cpu:5.1f}s | piek {mem_mb:6.1f} MB | "
      f"cyclus med {statistics.median(cyclus):5.1f} p90 {pct(cyclus,.9):5.1f} p99 {pct(cyclus,.99):5.1f} ms | "
      f"lus-lag med {statistics.median(lag):5.2f} p90 {pct(lag,.9):5.2f} p99 {pct(lag,.99):5.2f} max {max(lag):6.1f} ms")

async def baseline(sec):
    t0=time.perf_counter(); c0=time.process_time()
    lag,cyc=await probe(lambda: time.perf_counter()-t0>sec)
    rapport("baseline",lag,cyc,sec,time.process_time()-c0,resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,0)

async def thread_variant(cancel_na=None):
    req=RunRequest(**REQ); stop=threading.Event(); uit={}
    def werk():
        try: uit["r"]=execute(req, stop.is_set, lambda a,b: None)
        except Cancelled: uit["c"]=True
    th=threading.Thread(target=werk); t0=time.perf_counter(); c0=time.process_time(); th.start()
    if cancel_na:
        await asyncio.sleep(cancel_na); tc=time.perf_counter(); stop.set()
        while th.is_alive(): await asyncio.sleep(0.005)
        return (time.perf_counter()-tc)*1000
    lag,cyc=await probe(lambda: not th.is_alive())
    rapport("thread",lag,cyc,time.perf_counter()-t0,time.process_time()-c0,
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024, uit["r"]["provenance"]["bars"])

async def process_variant(cancel_na=None):
    c0=time.process_time(); r0=resource.getrusage(resource.RUSAGE_CHILDREN)
    t0=time.perf_counter()
    proc=await asyncio.create_subprocess_exec(sys.executable,"-I",ENTRY,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        env={"PATH":os.environ.get("PATH","")}, cwd="/tmp", limit=2**27)
    proc.stdin.write((json.dumps(REQ)+"\n").encode()); await proc.stdin.drain()
    uitvoer=[]
    async def lees():
        async for regel in proc.stdout:
            bericht=json.loads(regel); uitvoer.append(bericht)
            if bericht["type"] in ("result","cancelled","error"):
                proc.stdin.close()
    lezer=asyncio.create_task(lees())
    if cancel_na:
        await asyncio.sleep(cancel_na); tc=time.perf_counter()
        proc.stdin.write(b'{"cancel": true}\n'); await proc.stdin.drain()
        await proc.wait(); await lezer
        return (time.perf_counter()-tc)*1000
    lag,cyc=await probe(lambda: proc.returncode is not None or lezer.done())
    await proc.wait(); await lezer
    r1=resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu=(time.process_time()-c0)+(r1.ru_utime-r0.ru_utime)+(r1.ru_stime-r0.ru_stime)
    res=next(u["result"] for u in uitvoer if u["type"]=="result")
    rapport("proces",lag,cyc,time.perf_counter()-t0,cpu,r1.ru_maxrss/1024,res["provenance"]["bars"])

async def main():
    await baseline(20)
    await thread_variant()
    await process_variant()
    for naam,f in (("thread",thread_variant),("proces",process_variant)):
        lat=[await f(cancel_na=3) for _ in range(3)]
        p(f"annuleren {naam}: {', '.join(f'{x:.0f}' for x in lat)} ms")
    p("KLAAR")
asyncio.run(main())
