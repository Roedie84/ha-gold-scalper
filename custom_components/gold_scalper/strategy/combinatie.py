"""Combinatie van daghandel en scalpen (2.1.0, L-GS-015).

Besluit van Ruud (12-10-2026): beide strategieën tegelijk met echte orders,
om ze naast elkaar te blijven meten. Elke positie draagt de strategie die haar
opende; daaruit volgen haar uitstapregels, haar grootte en haar limieten:

* **daghandel**: risicogestuurde grootte, hooguit één positie, uitstap
  volgens ``daghandel.exit_config`` (volgstop, dicht om 20:45 UTC);
* **scalp**: vaste kleine grootte (``scalp_units``), de limiet per richting,
  het oorspronkelijke exitbeheer met tijdstop.

Spreiding en cooldown gelden per strategie: een scalppositie blokkeert geen
daghandelinstap en omgekeerd. Marge, vloer, daglimiet en het totaal aantal
posities blijven over alles samen gaan. De verliesreeks telt alleen de
daghandel (anders legt een gewone scalpreeks ook de daghandel stil).

Zuivere hulpfuncties, zonder Home Assistant.
"""
from __future__ import annotations

import math
from typing import Iterable

from ..const import STRATEGIE_ALLES, STRATEGIE_COMBINATIE, STRATEGIE_DAGHANDEL, STRATEGIE_SCALP
from . import veldproef

COMBINATIE_VERSIE = "combinatie-1.9.0"  # 2.6.3: veldproef-uitstap in R. 2.6.2: 2.6.2: veldproef op risico. 2.6.1: 2.6.1: scalp/tijdvak als groep uit. 2.5.9: deelwinst. 2.5.7: winstslot. 2.5.5: 2.5.5: break-even uiterlijk +1,5 USD


def strategieen(keuze: str) -> tuple[str, ...]:
    """Welke strategieën beslissen, in volgorde (daghandel eerst: die heeft
    de zeldzame signalen en mag niet achter een scalpinstap in de cyclus
    aansluiten)."""
    if keuze == STRATEGIE_COMBINATIE:
        return (STRATEGIE_DAGHANDEL, STRATEGIE_SCALP)
    if keuze == STRATEGIE_ALLES:
        # 2.4.0: daarna alle veldproefopzetten.
        return (STRATEGIE_DAGHANDEL, STRATEGIE_SCALP, *veldproef.namen())
    if keuze == STRATEGIE_SCALP:
        return (STRATEGIE_SCALP,)
    return (STRATEGIE_DAGHANDEL,)


def strategie_van_trade(trade, run_versie: str | None, standaard: str) -> str:
    """De strategie van een trade: het eigen veld, anders afgeleid uit de
    strategieversie van de run, anders de standaard."""
    eigen = getattr(trade, "strategie", None)
    if eigen in (STRATEGIE_DAGHANDEL, STRATEGIE_SCALP) or veldproef.is_veldproef(eigen):
        return eigen
    versie = str(run_versie or "")
    if versie.startswith("daghandel"):
        return STRATEGIE_DAGHANDEL
    if versie.startswith("scalp"):
        return STRATEGIE_SCALP
    return standaard


def per_strategie(gesloten: Iterable, standaard: str) -> dict:
    """Resultaat per strategie over de gesloten trades van de run."""
    groepen: dict[str, list] = {}
    for t in gesloten:
        if getattr(t, "net_pnl", None) is None:
            continue
        groepen.setdefault(strategie_van_trade(t, None, standaard), []).append(t)
    uit = {}
    for naam, trades in sorted(groepen.items()):
        netto = [float(t.net_pnl) for t in trades]
        bruto = [float(t.gross_pnl or 0.0) for t in trades]
        n = len(netto)
        gem = sum(netto) / n
        if n > 1:
            sd = math.sqrt(sum((x - gem) ** 2 for x in netto) / (n - 1))
            t_stat = round(gem / (sd / math.sqrt(n)), 2) if sd > 0 else None
        else:
            t_stat = None
        uit[naam] = {
            "trades": n,
            "netto": round(sum(netto), 2),
            "bruto": round(sum(bruto), 2),
            "kosten": round(sum(float(t.total_cost or 0.0) for t in trades), 2),
            "netto_per_trade": round(gem, 3),
            "winst_pct": round(100.0 * sum(1 for x in netto if x > 0) / n, 1),
            "t_per_trade": t_stat,
        }
    return uit
