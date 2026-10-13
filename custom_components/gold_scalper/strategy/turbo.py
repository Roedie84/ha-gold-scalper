"""Turbosignaal: uitbraak op de live koers (2.5.2, Ruud 13-10, keuze "2").

Turbo-scalp (2.5.0) reageerde sneller, maar alleen op het gewone
scalpsignaal, en dat kwam zelden boven de drempel (score ~0,1 tegen 0,30):
0 turbotrades. Dit is een eigen signaal op de ticks van de IG-stroom:

* **Venster**: de middenkoersen van de laatste ``VENSTER_S`` seconden, zonder
  de laatste ``VERS_S`` seconden (die vormen de uitbraak zelf).
* **Uitbraak**: de huidige middenkoers ligt minstens ``MARGE_USD`` boven het
  hoogste (long) of onder het laagste (short) punt van dat venster.
* **Doorzetting**: de koers bewoog in de laatste ``DOORZET_S`` seconden
  minstens ``MIN_DOORZET_USD`` in die richting (geen enkele uitschieter).
* **Bandbreedte**: het venster had minstens ``MIN_BAND_USD`` bandbreedte en
  hooguit ``MAX_BAND_USD`` (stil = ruis, wild = nieuws).
* **Spread**: hooguit ``cfg.max_spread``.
* Stop en doel zijn die van scalp (``stop_loss_usd``/``take_profit_usd``,
  anders ATR-gebaseerd); de positie is een scalppositie met de scalpexits
  (break-even bij +0,6 USD/oz, 2.5.1).

Zuiver, zonder Home Assistant. Meet zichzelf: ``components["turbo_signaal"]``.
"""
from __future__ import annotations

from collections import deque

from .scalping import ScalpConfig, ScalpSignal

TURBO_SIGNAAL_VERSIE = "turbo-uitbraak-1.0.0"

VENSTER_S = 45.0
VERS_S = 2.0
DOORZET_S = 10.0
MARGE_USD = 0.10
MIN_DOORZET_USD = 0.30
MIN_BAND_USD = 0.40
MAX_BAND_USD = 6.0
MIN_TICKS = 8
#: Na een turbo-instap minstens zoveel seconden wachten.
WACHT_S = 30.0
BEWAAR_S = 120.0


class TickUitbraak:
    """Houdt de recente ticks bij en geeft een uitbraaksignaal."""

    def __init__(self) -> None:
        self.ticks: deque[tuple[float, float]] = deque()

    def voeg_toe(self, t: float, bid: float, ask: float) -> None:
        if not bid or not ask or ask < bid:
            return
        self.ticks.append((float(t), (float(bid) + float(ask)) / 2.0))
        grens = float(t) - BEWAAR_S
        while self.ticks and self.ticks[0][0] < grens:
            self.ticks.popleft()

    def evalueer(self, t: float, bid: float, ask: float, cfg: ScalpConfig,
                 atr: float | None, sinds_instap: float = 1e9) -> ScalpSignal:
        def weiger(reden: str, tekst: str, richting: int = 0, onderdelen=None) -> ScalpSignal:
            return ScalpSignal(direction=richting, score=0.0, confidence=0.0,
                               should_trade=False, reject_reason=reden, reason=tekst,
                               components={"turbo_signaal": "uitbraak", **(onderdelen or {})})

        spread = ask - bid
        if spread > cfg.max_spread:
            return weiger("spread_too_wide", f"Turbo: spread {spread:.2f} boven {cfg.max_spread:.2f}")
        mid = (bid + ask) / 2.0
        venster = [m for ts, m in self.ticks if t - VENSTER_S <= ts < t - VERS_S]
        if len(venster) < MIN_TICKS:
            return weiger("insufficient_data", f"Turbo: {len(venster)} ticks in het venster")
        hoog, laag = max(venster), min(venster)
        band = hoog - laag
        onderdelen = {"band": round(band, 3), "hoog": hoog, "laag": laag, "mid": round(mid, 3)}
        if band < MIN_BAND_USD:
            return weiger("te_stil", f"Turbo: bandbreedte {band:.2f} onder {MIN_BAND_USD}", 0, onderdelen)
        if band > MAX_BAND_USD:
            return weiger("te_wild", f"Turbo: bandbreedte {band:.2f} boven {MAX_BAND_USD}", 0, onderdelen)
        if mid >= hoog + MARGE_USD:
            d = 1
        elif mid <= laag - MARGE_USD:
            d = -1
        else:
            return weiger("geen_uitbraak", "Turbo: koers binnen de band", 0, onderdelen)
        eerder = [m for ts, m in self.ticks if t - DOORZET_S <= ts <= t - VERS_S]
        doorzet = (mid - eerder[0]) * d if eerder else 0.0
        onderdelen["doorzet"] = round(doorzet, 3)
        if doorzet < MIN_DOORZET_USD:
            return weiger("geen_doorzetting",
                          f"Turbo: uitbraak zonder doorzetting ({doorzet:.2f} USD)", d, onderdelen)
        if sinds_instap < WACHT_S:
            return weiger("cooldown", f"Turbo: nog {WACHT_S - sinds_instap:.0f}s wachten", d, onderdelen)

        a = atr if atr and atr > 0 else 0.0
        doel = cfg.take_profit_usd if cfg.take_profit_usd > 0 else a * cfg.take_profit_atr
        stop = cfg.stop_loss_usd if cfg.stop_loss_usd > 0 else a * cfg.stop_loss_atr
        if doel <= 0 or stop <= 0:
            return weiger("insufficient_data", "Turbo: geen stop of doel (ATR onbekend)", d, onderdelen)
        instap = ask if d == 1 else bid
        kant = "long" if d == 1 else "short"
        return ScalpSignal(
            direction=d, score=float(d), confidence=1.0, should_trade=True,
            reject_reason=None, geldig=True,
            reason=(f"Turbo {kant}: koers {mid:.2f} door de band van {VENSTER_S:.0f}s "
                    f"({laag:.2f}-{hoog:.2f}), {doorzet:.2f} USD doorgezet in "
                    f"{DOORZET_S:.0f}s; doel {doel:.2f}, stop {stop:.2f}"),
            stop_loss=round(instap - d * stop, 2),
            take_profit=round(instap + d * doel, 2),
            expected_move=round(doel, 3),
            expected_cost=round(spread + 2 * cfg.expected_slippage, 3),
            components={"turbo_signaal": "uitbraak", **onderdelen},
        )
