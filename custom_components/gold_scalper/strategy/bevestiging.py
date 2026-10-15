"""Schaduwmeting: instap met bevestiging op 15m (2.11.0, besluit Ruud 15-10).

Doorgerekend op 15-10 (1m-koersen van cTrader, echte veldproefposities):
"wacht op de eerste 1m-candle na het signaal; sluit die in de richting van
de trade, stap dan in op de slotkoers (zelfde stop en doel), anders geen
trade". IG 15m: -0,26R -> +0,02R per trade (t 2,9, n=55); Pepperstone 15m
-0,07R -> +0,17R (n=14). Met 4 regels x 5 tijdvakken x 2 brokers bekeken kan
dat toeval zijn. Daarom eerst meten op nieuwe data, zonder echte orders.

Per 15m-signaal dat echt wordt gehandeld, twee gesimuleerde trades met
dezelfde simulator (``schaduw.stap_trade``, uitersten alleen van na de
instap), dus een eerlijke paarvergelijking:

* **direct**: instap op het moment van het signaal (laat/bied);
* **bevestigd**: instap na de eerste afgesloten 1m-bar die ná het signaal
  begon, alleen als die in de richting sloot en de stop niet raakte;
  anders "niet bevestigd" (uitkomst 0, geen trade).

Uitkomst per paar in R (de stopafstand bij het signaal). Zuiver Python.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .schaduw import SchaduwKosten, _iso, _tijd, stap_trade, uitersten_voor
from .uitgezet_schaduw import UitgezetTrade

#: Alleen dit tijdvak (besluit 15-10).
TIJDVAK = "15m"
#: Zonder afgesloten 1m-bar na zoveel seconden: paar vervalt.
MAX_WACHT_S = 300
#: Zoveel afgeronde paren bewaard in het geheugen.
MAX_PAREN = 500


@dataclass
class Paar:
    strategie: str
    richting: int
    signaal_tijd: str
    stop: float
    doel: float | None
    r: float
    bar: str | None
    direct: UitgezetTrade
    bevestigd: UitgezetTrade | None = None
    status: str = "wacht"          # wacht | bevestigd | niet_bevestigd | vervallen
    id: int | None = None

    def klaar(self) -> bool:
        if self.status == "vervallen":
            return True
        if self.direct.status != "gesloten":
            return False
        if self.status == "wacht":
            return False
        return self.status == "niet_bevestigd" or (
            self.bevestigd is not None and self.bevestigd.status == "gesloten")

    def r_direct(self) -> float | None:
        if self.direct.netto is None or not self.r:
            return None
        return self.direct.netto / (self.r * self.direct.units)

    def r_bevestigd(self) -> float | None:
        if self.status == "niet_bevestigd":
            return 0.0
        b = self.bevestigd
        if b is None or b.netto is None or not self.r:
            return None
        return b.netto / (self.r * b.units)

    def als_rij(self) -> dict:
        return {
            "id": self.id, "strategie": self.strategie, "richting": self.richting,
            "signaal_tijd": self.signaal_tijd, "stop": self.stop, "doel": self.doel,
            "r": self.r, "status": self.status,
            "direct_instap": self.direct.open_price,
            "direct_sluit": self.direct.close_time, "direct_reden": self.direct.close_reason,
            "direct_netto": self.direct.netto, "direct_r": self.r_direct(),
            "bevestigd_instap": self.bevestigd.open_price if self.bevestigd else None,
            "bevestigd_sluit": self.bevestigd.close_time if self.bevestigd else None,
            "bevestigd_reden": self.bevestigd.close_reason if self.bevestigd else None,
            "bevestigd_netto": self.bevestigd.netto if self.bevestigd else None,
            "bevestigd_r": self.r_bevestigd(),
        }


def _trade(strategie, richting, nu, bid, ask, stop, doel, reden) -> UitgezetTrade:
    instap = ask if richting == 1 else bid
    return UitgezetTrade(
        run_id=None, richting=richting, open_time=_iso(nu), open_price=float(instap),
        open_mid=(bid + ask) / 2.0, open_spread=ask - bid, units=1.0,
        stop_loss=stop, take_profit=doel, reden=reden,
        reden_tekst=f"{strategie}: {reden}", laatst_bijgewerkt=_iso(nu),
        strategie=strategie,
    )


def t_statistiek(x: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    m = sum(x) / n
    v = sum((a - m) ** 2 for a in x) / (n - 1)
    return round(m / math.sqrt(v / n), 2) if v > 0 else None


@dataclass
class BevestigingBoek:
    kosten: SchaduwKosten = field(default_factory=SchaduwKosten)
    open_paren: list[Paar] = field(default_factory=list)
    klaar: list[Paar] = field(default_factory=list)
    laatste_bar: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def hoort_erbij(strategie: str | None) -> bool:
        return bool(strategie) and str(strategie).startswith("vp:") \
            and str(strategie).endswith(f":{TIJDVAK}")

    def aanmelden(self, *, strategie: str, signal, bid: float, ask: float,
                  nu: datetime) -> Paar | None:
        """Een 15m-signaal dat echt wordt gehandeld; één paar per opzet per bar."""
        if not self.hoort_erbij(strategie):
            return None
        richting = int(getattr(signal, "direction", 0) or 0)
        stop = getattr(signal, "stop_loss", None)
        doel = getattr(signal, "take_profit", None)
        if richting not in (1, -1) or stop is None or not bid or not ask:
            return None
        bar = (getattr(signal, "components", None) or {}).get("bar")
        bar = str(bar) if bar is not None else None
        if bar is not None and self.laatste_bar.get(strategie) == bar:
            return None
        instap = ask if richting == 1 else bid
        if (instap - stop) * richting <= 0:
            return None
        r = abs(float(doel) - instap) / 2.0 if doel is not None else abs(instap - stop)
        if r <= 0:
            return None
        paar = Paar(strategie=strategie, richting=richting, signaal_tijd=_iso(nu),
                    stop=float(stop), doel=float(doel) if doel is not None else None,
                    r=r, bar=bar,
                    direct=_trade(strategie, richting, nu, bid, ask, stop, doel, "direct"))
        self.open_paren.append(paar)
        if bar is not None:
            self.laatste_bar[strategie] = bar
        return paar

    def bijwerken(self, *, bid: float, ask: float, hoog: float | None, laag: float | None,
                  uitersten_vanaf: datetime | None, nu: datetime,
                  bar_1m: list | None, exits_voor: Callable[[str], object],
                  maat_voor: Callable[[UitgezetTrade], float]) -> list[Paar]:
        """Eén cyclus. ``bar_1m`` = laatste afgesloten 1m-bar [start_ts, o, h, l, c, v].

        Geeft de paren terug die deze cyclus klaar kwamen.
        """
        afgerond: list[Paar] = []
        rondreis = (ask - bid) + 2 * self.kosten.slippage
        for paar in list(self.open_paren):
            if paar.status == "wacht":
                self._beslis(paar, bid, ask, nu, bar_1m)
            for t in (paar.direct, paar.bevestigd):
                if t is None or t.status != "open":
                    continue
                maat = maat_voor(t)
                if not maat or maat <= 0:
                    continue
                h, lg = uitersten_voor(t, hoog, laag, uitersten_vanaf)
                uitkomst = stap_trade(
                    t, exits_voor(paar.strategie), self.kosten, bid=bid, ask=ask,
                    hoog=h, laag=lg, atr=maat, nu=nu, rondreis_kosten=rondreis)
                if uitkomst == "vervallen":
                    paar.status = "vervallen"
            if paar.klaar():
                self.open_paren.remove(paar)
                self.klaar.append(paar)
                self.klaar = self.klaar[-MAX_PAREN:]
                afgerond.append(paar)
        return afgerond

    def _beslis(self, paar: Paar, bid: float, ask: float, nu: datetime, bar_1m) -> None:
        signaal = _tijd(paar.signaal_tijd)
        if signaal is None:
            paar.status = "vervallen"
            return
        if bar_1m:
            try:
                start, o, h, l, c = (float(bar_1m[i]) for i in range(5))
            except (TypeError, ValueError, IndexError):
                start = None
            if start is not None and start >= signaal.timestamp():
                d = paar.richting
                ongunstig = l if d == 1 else h
                if (c - o) * d > 0 and (ongunstig - paar.stop) * d > 0:
                    instap = ask if d == 1 else bid
                    if (instap - paar.stop) * d > 0 and (
                            paar.doel is None or (paar.doel - instap) * d > 0):
                        paar.bevestigd = _trade(paar.strategie, d, nu, bid, ask,
                                                paar.stop, paar.doel, "bevestigd")
                        paar.status = "bevestigd"
                        return
                paar.status = "niet_bevestigd"
                return
        if (nu - signaal).total_seconds() > MAX_WACHT_S:
            paar.status = "vervallen"

    def statistiek(self, rijen: list[dict] | None = None) -> dict:
        """Paarvergelijking in R; ``rijen`` uit de database, anders het geheugen."""
        if rijen is None:
            rijen = [p.als_rij() for p in self.klaar]
        paren = [r for r in rijen if r.get("status") in ("bevestigd", "niet_bevestigd")
                 and r.get("direct_r") is not None and r.get("bevestigd_r") is not None]
        n = len(paren)
        direct = [float(r["direct_r"]) for r in paren]
        bevestigd = [float(r["bevestigd_r"]) for r in paren]
        verschil = [b - a for a, b in zip(direct, bevestigd)]
        return {
            "tijdvak": TIJDVAK,
            "paren": n,
            "bevestigd": sum(1 for r in paren if r["status"] == "bevestigd"),
            "niet_bevestigd": sum(1 for r in paren if r["status"] == "niet_bevestigd"),
            "open": len(self.open_paren),
            "direct_r_per_trade": round(sum(direct) / n, 3) if n else None,
            "bevestigd_r_per_trade": round(sum(bevestigd) / n, 3) if n else None,
            "verschil_r_per_trade": round(sum(verschil) / n, 3) if n else None,
            "t_verschil": t_statistiek(verschil),
            "oordeel": oordeel(n, verschil, bevestigd),
            "let_op": "Gesimuleerd (schaduw). Telt niet mee in het resultaat of de bewijsfase.",
        }


def oordeel(n: int, verschil: list[float], bevestigd: list[float]) -> str:
    """Pas iets zeggen na 30 paren; doorvoeren alleen als beide gelden."""
    if n < 30:
        return f"te weinig paren ({n} van 30)"
    t = t_statistiek(verschil)
    gem = sum(bevestigd) / n
    if t is not None and t >= 2 and gem > 0:
        return "bevestiging beter én winstgevend: voorstel om door te voeren"
    if t is not None and t >= 2:
        return "bevestiging beter, maar nog niet winstgevend"
    return "geen aantoonbaar verschil"
