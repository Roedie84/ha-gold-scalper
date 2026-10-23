"""Open posities als attribuut van de sensor *Open posities* (L-GS-019, 2.21.2).

Los van Home Assistant, zodat het zonder HA te toetsen is. Per positie staat
naast ticket, richting en prijzen ook de strategie/opzet die haar opende
(bijv. ``vp:inside:3m`` of ``daghandel``). Zonder die regel was bij twee
open posities niet te zien welke opzet ze hield (limiet per richting, 2.21.0).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping


def ticket_van(positie: Any) -> str:
    return str(getattr(positie, "ticket", None) or getattr(positie, "id", "") or "")


def positie_regels(posities: Iterable[Any] | None,
                   strategie_per_positie: Mapping[str, str] | None = None) -> list[dict]:
    """Eén regel per open positie; ``strategie`` is None als onbekend."""
    strategieen = strategie_per_positie or {}
    regels = []
    for p in posities or []:
        ticket = ticket_van(p)
        regels.append({
            # 1.9.0: per ticket, zodat meerdere posities uit elkaar te houden zijn.
            "ticket": ticket,
            "side": p.side,
            "units": getattr(p, "units", None) or getattr(p, "volume", None),
            "open_price": p.open_price,
            "stop_loss": getattr(p, "stop_loss", None),
            "take_profit": getattr(p, "take_profit", None),
            "strategie": strategieen.get(ticket) or getattr(p, "strategie", None) or None,
        })
    return regels
