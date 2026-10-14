"""Schaduwtrades voor uitgezette groepen (2.7.1, hypothese H-GS-003).

Sinds 2.6.1 staan veldproef 1m, veldproef 3m en scalp (incl. turbo) uit: als
groep n >= 200 en t < -3 (13-10-2026 ~17:47 UTC). Dat besluit is genomen op
de data tot dat moment. Om het op ongeziene data te toetsen zonder weer echt
te handelen - echte orders zouden de risico- en clusterlimieten van de
lopende hypotheses H-GS-001/002 opeten - wordt elk geldig signaal van een
uitgezette opzet hier gesimuleerd:

* per opzet hooguit één open schaduwtrade en één instap per bar, zoals echt;
* instap op laat (long) of bied (short), dus inclusief de gemeten spread;
* stop, doel en uitstapregels van de opzet zelf (``ExitManager`` per opzet,
  veldproef in R); deelsluiting wordt niet nagebootst;
* grootte zoals een echte order hem zou krijgen;
* slippage per zijde ``SLIPPAGE_PER_ZIJDE`` USD/oz: het gemeten gemiddelde
  van 1m/3m/scalp bij IG (kosten per oz min spread, 14-10, n=1159).

Alles hier is **geschat** (gesimuleerd), nooit gemeten: eigen tabel, telt
nergens mee in het echte resultaat, de bewijsfase of de live-poort.

Zuiver Python, zonder Home Assistant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .schaduw import SchaduwKosten, SchaduwTrade, _iso, stap_trade

#: Gemeten: (kosten/oz - spread) voor veldproef 1m (+0,016), 3m (+0,076) en
#: scalp (-0,015) over 30 dagen demo; gemiddeld ~0,03 rondreis. Per zijde de
#: helft, afgerond naar boven.
SLIPPAGE_PER_ZIJDE = 0.02
REDEN = "uitgezet"
HERKOMST = "geschat"


@dataclass(slots=True)
class UitgezetTrade(SchaduwTrade):
    strategie: str = ""
    bar: str | None = None


@dataclass
class UitgezetBoek:
    kosten: SchaduwKosten = field(
        default_factory=lambda: SchaduwKosten(slippage=SLIPPAGE_PER_ZIJDE))
    open_trades: dict[str, UitgezetTrade] = field(default_factory=dict)
    laatste_bar: dict[str, str] = field(default_factory=dict)
    gesloten: list[UitgezetTrade] = field(default_factory=list)
    vervallen: int = 0

    def openen(self, *, strategie: str, signal, bid: float, ask: float,
               nu: datetime, units: float, run_id=None) -> UitgezetTrade | None:
        if not strategie or strategie in self.open_trades:
            return None
        if not getattr(signal, "geldig", False):
            return None
        richting = int(getattr(signal, "direction", 0) or 0)
        if richting not in (1, -1) or getattr(signal, "stop_loss", None) is None:
            return None
        bar = (getattr(signal, "components", None) or {}).get("bar")
        bar = str(bar) if bar is not None else None
        if bar is not None and self.laatste_bar.get(strategie) == bar:
            return None
        if units is None or units <= 0:
            return None
        instap = ask if richting == 1 else bid
        t = UitgezetTrade(
            run_id=run_id, richting=richting, open_time=_iso(nu),
            open_price=float(instap), open_mid=(bid + ask) / 2.0,
            open_spread=ask - bid, units=float(units),
            stop_loss=signal.stop_loss, take_profit=getattr(signal, "take_profit", None),
            reden=REDEN, reden_tekst=f"{strategie} uitgezet; gesimuleerd",
            score=round(float(getattr(signal, "score", 0.0) or 0.0), 4),
            laatst_bijgewerkt=_iso(nu), strategie=strategie, bar=bar,
        )
        self.open_trades[strategie] = t
        if bar is not None:
            self.laatste_bar[strategie] = bar
        return t

    def bijwerken(self, *, bid: float, ask: float, hoog: float | None,
                  laag: float | None, nu: datetime,
                  exits_voor: Callable[[str], object],
                  maat_voor: Callable[[UitgezetTrade], float]) -> list[UitgezetTrade]:
        """Eén cyclus voor alle open trades; geeft de gewijzigde terug."""
        gewijzigd: list[UitgezetTrade] = []
        rondreis = (ask - bid) + 2 * self.kosten.slippage
        for naam, t in list(self.open_trades.items()):
            maat = maat_voor(t)
            if not maat or maat <= 0:
                continue
            uitkomst = stap_trade(
                t, exits_voor(naam), self.kosten, bid=bid, ask=ask, hoog=hoog,
                laag=laag, atr=maat, nu=nu, rondreis_kosten=rondreis,
            )
            if uitkomst == "vervallen":
                del self.open_trades[naam]
                self.vervallen += 1
            elif uitkomst == "gesloten":
                del self.open_trades[naam]
                self.gesloten.append(t)
                self.gesloten = self.gesloten[-500:]
            gewijzigd.append(t)
        return gewijzigd


def als_onderzoeksrij(rij: dict) -> dict:
    """Een rij uit ``uitgezet_schaduw`` in de vorm die learning/onderzoek
    verwacht (netto in USD; geen accountvaluta)."""
    return {
        "id": rij.get("id"),
        "strategie": rij.get("strategie"),
        "side": "buy" if rij.get("richting") == 1 else "sell",
        "open_time": rij.get("open_time"),
        "close_time": rij.get("close_time"),
        "open_spread": rij.get("open_spread"),
        "gross_pnl": rij.get("bruto"),
        "total_cost": rij.get("kosten"),
        "net_pnl": rij.get("netto"),
        "net_pnl_account": None,
        "broker_ticket": None,
        "reconciliation_status": None,
        "herkomst": HERKOMST,
    }
