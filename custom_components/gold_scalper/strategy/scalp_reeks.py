"""2.4.9: scalpreeks - snel bijkopen in de richting van een lopende scalp.

Wens van Ruud (13-10): "bij scalpen veel meer trades in de minuut-candle,
soort pyramide opbouwen ... mogelijk zelfs met 1 USD winst; tot wel 100
trades". Anders dan de gewone piramide (bijkopen pas na winst in ATR, krimpende
stukken, maximaal 5) koopt de reeks bij elke ``stap_usd`` die de koers sinds
het vorige stuk in de goede richting loopt een stuk van dezelfde grootte bij.
Elk stuk heeft een eigen klein doel (``doel_usd``) en deelt de stop van de
eerste positie. Alleen bijkopen bij bevestiging, nooit bij tegenslag.

Let op bij de analyse: stukken van één reeks zijn geen onafhankelijke
waarnemingen; ze horen als één cluster te tellen (open_reason
"pyramide van <ticket>").
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(slots=True)
class ReeksConfig:
    enabled: bool = False
    #: Koersstap in de goede richting per extra stuk (USD/oz).
    stap_usd: float = 0.3
    #: Maximaal aantal stukken per reeks (bovenop de eerste positie).
    max_stukken: int = 100
    #: Winstdoel per stuk (USD/oz).
    doel_usd: float = 1.0
    #: Hooguit zoveel stukken per cyclus (spaart de IG-limieten).
    per_cyclus: int = 3


def stukken_nu(
    cfg: ReeksConfig, *, side: str, entry_price: float, current_price: float,
    last_price: float | None, done: int,
) -> int:
    """Hoeveel stukken er nu bij mogen (0 = niet).

    Gerekend vanaf het laatste stuk (of de instap): elke volle stap in de
    goede richting is één stuk, begrensd per cyclus en per reeks.
    """
    if not cfg.enabled or cfg.stap_usd <= 0 or done >= cfg.max_stukken:
        return 0
    richting = 1.0 if side == "buy" else -1.0
    ref = last_price if last_price is not None else entry_price
    beweging = (current_price - ref) * richting
    if beweging < cfg.stap_usd - 1e-9:
        return 0
    stappen = int(math.floor(beweging / cfg.stap_usd + 1e-9))
    return max(0, min(stappen, cfg.per_cyclus, cfg.max_stukken - done))
