"""Vaste marktdata voor tests: onafhankelijk van de klok.

De simulator berekent prijzen als functie van het absolute tijdstip en
verankert ``candles()`` aan "nu". Elke test die ``candles()`` gebruikt, krijgt
daardoor elk moment andere marktdata. Deze hulpfunctie bouwt bars met
**dezelfde** prijsfunctie, maar vanaf een vast begintijdstip: morgen exact
dezelfde bars als vandaag.
"""
from __future__ import annotations

from gold_scalper.analysis.signals import Candles
from gold_scalper.broker.simulator import SUBSAMPLES, SimulatorVenue

#: Maandag 7 september 2026, 00:00 UTC. Op het M15-raster.
VAST_BEGIN = 1_788_739_200


def vaste_bars(n: int, seed: int = 11, begin: int = VAST_BEGIN, stap: int = 900,
               decimalen: int = 2) -> Candles:
    """``n`` bars vanaf ``begin``, zoals de simulator ze op dat moment zou maken."""
    venue = SimulatorVenue(seed=seed)
    ts, o, h, l, c, v = [], [], [], [], [], []
    for i in range(n):
        start = begin + i * stap
        punten = [venue.price_at(start + stap * k / SUBSAMPLES) for k in range(SUBSAMPLES + 1)]
        ts.append(start)
        o.append(round(punten[0], decimalen))
        c.append(round(punten[-1], decimalen))
        h.append(round(max(punten), decimalen))
        l.append(round(min(punten), decimalen))
        v.append(100.0)
    return Candles(ts, o, h, l, c, v)
