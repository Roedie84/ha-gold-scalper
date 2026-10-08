"""Trade-level replay of the live Gold Scalper entries on the 10-s mid path.

Read-only analysis. Exit logic mirrors broker/exits.py (ExitConfig defaults)
plus the broker-side stop/limit; costs: half spread 0.40 at entry and exit,
0.06 USD/oz slippage on stop fills (measured), 0 on limit fills.
"""
import bisect
import json
import math
import statistics as st
import sys

D = sys.argv[1]
P = json.load(open(f"{D}/price.json"))
PT = [p[0] for p in P]
TR = json.load(open(f"{D}/trades.json"))

HS = 0.40          # half spread
SLIP = 0.06        # slippage on stop fills
BE_TRIG, BE_BUF = 0.8, 1.2 * 0.84
TRAIL_ACT, TRAIL_DIST = 1.5, 1.2
MAX_PATH = 4 * 3600


def path(t0):
    i = bisect.bisect_left(PT, t0)
    out = []
    while i < len(P) and P[i][0] <= t0 + MAX_PATH:
        out.append(P[i]); i += 1
    return out


def mid_at(t):
    i = bisect.bisect_right(PT, t) - 1
    return P[i]


def simulate(tr, tp_mult=1.5, confirm=None, time_stops=False):
    d = 1 if tr["side"] == "buy" else -1
    atr = tr["atr"]
    e_t = tr["e"]
    entry = tr["open"]
    if confirm:
        kind, arg = confirm
        m0 = tr["mid_e"]
        if kind == "bars":       # n x 60 s steps all in signal direction
            prev = m0; t = e_t
            for k in range(arg):
                t += 60
                m = mid_at(t)[1]
                if (m - prev) * d <= 0:
                    return None
                prev = m
            e_t = t; entry = prev + d * HS
        elif kind == "move":     # mid moves >= arg*ATR in direction within 180 s
            hit = None
            for (t, m) in path(e_t):
                if t > e_t + 180: break
                if (m - m0) * d >= arg * atr:
                    hit = (t, m); break
            if not hit:
                return None
            e_t = hit[0]; entry = hit[1] + d * HS
    stop = entry - d * atr
    tp = entry + d * tp_mult * atr
    for (t, m) in path(e_t + 1):
        px = m - d * HS                          # price we would exit at
        if (px - stop) * d <= 0:
            fill = stop - d * SLIP if (px - stop) * d > -SLIP else px - d * SLIP
            return dict(net=(fill - entry) * d * tr["units"], exit_t=t, why="stop", e_t=e_t)
        if (px - tp) * d >= 0:
            return dict(net=(tp - entry) * d * tr["units"], exit_t=t, why="target", e_t=e_t)
        prof = (px - entry) * d / atr
        age = t - e_t
        if time_stops:
            if age >= 900 or (age >= 240 and abs(prof) < 0.3):
                return dict(net=(px - entry) * d * tr["units"], exit_t=t, why="time", e_t=e_t)
        if prof >= TRAIL_ACT:
            trail = px - d * atr * TRAIL_DIST
            if (trail - stop) * d > 0: stop = trail
        if prof >= BE_TRIG:
            be = entry + d * BE_BUF
            if (be - stop) * d > 0: stop = be
    return dict(net=(P[-1][1] - d * HS - entry) * d * tr["units"], exit_t=None, why="open", e_t=e_t)


def tstat(xs):
    if len(xs) < 2: return float("nan")
    s = st.stdev(xs)
    return st.mean(xs) / (s / math.sqrt(len(xs))) if s > 0 else float("nan")


def summarize(res, clusters_subset=None):
    rows = [(TR[i]["cluster"], r) for i, r in enumerate(res)
            if r is not None and (clusters_subset is None or TR[i]["cluster"] in clusters_subset)]
    nets = [r["net"] for _, r in rows]
    if not nets:
        return dict(n=0, k=0, net=0, per=float("nan"), pf=float("nan"), t=float("nan"))
    per_cl = {}
    for c, r in rows: per_cl[c] = per_cl.get(c, 0) + r["net"]
    # clusters with zero trades in variant count as 0 (paired with baseline)
    allc = sorted(set(t["cluster"] for t in TR if clusters_subset is None or t["cluster"] in clusters_subset))
    cl = [per_cl.get(c, 0.0) for c in allc]
    win = sum(x for x in nets if x > 0); loss = -sum(x for x in nets if x < 0)
    return dict(n=len(nets), k=len(per_cl), net=sum(nets), per=st.mean(nets),
                pf=win / loss if loss else float("inf"), t=tstat(cl), cl=cl,
                tgt=sum(1 for _, r in rows if r["why"] == "target") / len(nets),
                win=sum(1 for x in nets if x > 0) / len(nets))
