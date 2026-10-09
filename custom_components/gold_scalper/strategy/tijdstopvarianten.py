"""Tijdstopvarianten: elke echte trade nagespeeld met een andere tijdstop (1.9.5).

**Alleen meting, geen strategiewijziging.** Het echte exitbeheer (de
``ExitManager`` van de coordinator en zijn configuratie) wordt hier nooit
aangeraakt; elke variant krijgt een eigen kopie van die configuratie.

Waarom (L-GS-008): in run 101 sloten 35 van 45 trades op de tijdstop (na
240 s nog binnen 0,3 x ATR van het instappunt), het doel van 1,5 x ATR werd
in 2% geraakt. De strategie werkt op candles van 5 minuten; 240 s valt binnen
één candle. Is dat te snel? Een replay liet zien dát tijdstops helpen, niet
welke waarde.

Per echte positie die de bot opent (broker of papier) lopen vier
gesimuleerde "varianten" mee, met dezelfde instapprijs (de werkelijke fill
als die bekend is, anders de instapkoers), dezelfde grootte, dezelfde
beginstop en hetzelfde doel, en dezelfde trailing- en break-evenregels als
het echte exitbeheer. Alleen de tijdstop verschilt:

* ``240``: spiegel van de huidige instelling. Dient om de simulatie te
  toetsen tegen de echte uitkomst (overeenkomst).
* ``480`` en ``720``: langere tijdstop.
* ``geen_tijdstop``: tijdstop uit.

Allemaal met de ingestelde maximale positieduur (900 s). Een variant loopt
door nadat de echte trade sloot, tot zijn eigen uitstap.

Simulatie met dezelfde regels als de schaduwtrades
(``strategy/schaduw.stap_trade``): stop en doel tegen de uitersten van de
bars, beide geraakt telt de stop, afrekenen op bied (long) of laat (short),
slippage en commissie als bij ``SchaduwKosten``. Eén verfijning: de
uitersten van bars tellen alleen voor bars die deze cyclus afsloten en
begonnen ná de instap. Anders zou een candle van vóór de instap (of dezelfde
candle cyclus na cyclus) een stop kunnen raken die de echte positie nooit
zag. Geen extra verzoeken bij de broker.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Iterable

from ..broker.exits import ExitManager
from .schaduw import SchaduwKosten, _iso, _tijd, stap_trade

#: Variant -> (tijdstop in s of None = uit, maximale duur in s of None = zoals
#: ingesteld). Volgorde = weergavevolgorde.
VARIANTEN: dict[str, tuple[int | None, int | None]] = {
    "240": (240, None),
    "480": (480, None),
    "720": (720, None),
    "geen_tijdstop": (None, None),
}
#: De variant die de huidige instelling spiegelt; basis voor de gepaarde toets.
BASIS = "240"
#: Tijdstop "uit": groter dan elke denkbare positieduur.
UIT = 10 ** 9
#: Vangnet tegen een op hol geslagen lus (12 echte posities x 4 varianten).
MAX_OPEN_VARIANTEN = 60
#: Oordeel pas vanaf zoveel uurblokken (L-GS-005, besluit c).
MIN_BLOKKEN = 20
#: Drempel voor een duidelijk verschil.
T_DREMPEL = 2.0
#: Overeenkomst met de echte trade: zelfde sluitreden en netto binnen dit
#: bedrag (USD).
OVEREENKOMST_USD = 0.5


@dataclass(slots=True)
class VariantTrade:
    run_id: int | None
    trade_ref: str
    variant: str
    richting: int
    open_time: str
    open_price: float
    open_mid: float
    open_spread: float
    units: float
    stop_loss: float | None
    take_profit: float | None
    time_stop_seconds: int | None = None
    max_hold_seconds: int | None = None
    status: str = "open"            # open | gesloten | vervallen
    close_time: str | None = None
    close_price: float | None = None
    close_mid: float | None = None
    close_reason: str | None = None
    bruto: float | None = None
    kosten: float | None = None
    netto: float | None = None
    mfe: float = 0.0
    mae: float = 0.0
    laatst_bijgewerkt: str | None = None
    id: int | None = None

    @property
    def side(self) -> str:
        return "buy" if self.richting == 1 else "sell"

    def as_dict(self) -> dict:
        return asdict(self)


#: Kolommen in de tabel ``tijdstop_varianten`` (zonder id).
VARIANT_KOLOMMEN = tuple(
    k for k in VariantTrade.__dataclass_fields__ if k != "id"
)


@dataclass
class VariantenBoek:
    """Open en gesloten tijdstopvarianten van één run, in het geheugen.

    ``exits`` is de echte ``ExitManager``; alleen zijn configuratie wordt
    gelezen (en gekopieerd), nooit gewijzigd.
    """

    exits: ExitManager
    kosten: SchaduwKosten = field(default_factory=SchaduwKosten)
    #: Opslag per cyclus voor de break-evenbuffer, zoals het echte
    #: exitbeheer hem rekent: spread + 0,04 (geschatte slippage beide zijden).
    slippage_rondreis: float = 0.04
    open_trades: list[VariantTrade] = field(default_factory=list)
    gesloten: list[VariantTrade] = field(default_factory=list)
    vervallen: int = 0

    # -- configuratie ------------------------------------------------------ #

    def manager(self, variant: str) -> ExitManager:
        """Een eigen ExitManager voor deze variant, op een kópie van de echte
        configuratie. De echte configuratie blijft onaangeroerd."""
        tijdstop, max_duur = VARIANTEN[variant]
        cfg = replace(
            self.exits.config,
            time_stop_seconds=UIT if tijdstop is None else int(tijdstop),
            max_hold_seconds=(
                self.exits.config.max_hold_seconds if max_duur is None
                else int(max_duur)
            ),
        )
        return ExitManager(cfg)

    # -- openen ------------------------------------------------------------ #

    def openen(self, *, run_id, trade_ref: str, side: str, open_price: float,
               open_mid: float, spread: float, units: float,
               stop_loss: float | None, take_profit: float | None,
               nu: datetime) -> list[VariantTrade]:
        """Vier varianten voor één echte positie. Leeg als dat niet kan."""
        ref = str(trade_ref or "")
        if not ref or not units or units <= 0 or open_price is None:
            return []
        if any(t.trade_ref == ref for t in self.open_trades) or any(
            t.trade_ref == ref for t in self.gesloten[-200:]
        ):
            return []
        if len(self.open_trades) + len(VARIANTEN) > MAX_OPEN_VARIANTEN:
            return []
        richting = 1 if side == "buy" else -1
        uit: list[VariantTrade] = []
        for variant, (tijdstop, max_duur) in VARIANTEN.items():
            t = VariantTrade(
                run_id=run_id, trade_ref=ref, variant=variant,
                richting=richting, open_time=_iso(nu),
                open_price=float(open_price), open_mid=float(open_mid),
                open_spread=float(spread or 0.0), units=float(units),
                stop_loss=stop_loss, take_profit=take_profit,
                time_stop_seconds=tijdstop,
                max_hold_seconds=(
                    self.exits.config.max_hold_seconds if max_duur is None
                    else max_duur
                ),
                laatst_bijgewerkt=_iso(nu),
            )
            self.open_trades.append(t)
            uit.append(t)
        return uit

    # -- bijwerken --------------------------------------------------------- #

    def bijwerken(self, *, bid: float, ask: float, hoog: float | None,
                  laag: float | None, atr: float, nu: datetime,
                  uitersten_vanaf: datetime | None = None) -> list[VariantTrade]:
        """Eén cyclus. Geeft de varianten terug die veranderden.

        ``uitersten_vanaf``: begin van de oudste bar waar ``hoog``/``laag``
        uit komen. Een variant die ná dat moment opende, wordt alleen tegen
        de actuele koers getoetst.
        """
        gewijzigd: list[VariantTrade] = []
        managers = {v: self.manager(v) for v in VARIANTEN}
        rondreis = (ask - bid) + self.slippage_rondreis
        for t in list(self.open_trades):
            geopend = _tijd(t.open_time)
            met_uitersten = not (
                uitersten_vanaf is not None and geopend is not None
                and geopend > uitersten_vanaf
            )
            uitkomst = stap_trade(
                t, managers.get(t.variant) or managers[BASIS], self.kosten,
                bid=bid, ask=ask,
                hoog=hoog if met_uitersten else None,
                laag=laag if met_uitersten else None,
                atr=atr, nu=nu, rondreis_kosten=rondreis,
            )
            if uitkomst == "vervallen":
                self.open_trades.remove(t)
                self.vervallen += 1
            elif uitkomst == "gesloten":
                self.open_trades.remove(t)
                self.gesloten.append(t)
            gewijzigd.append(t)
        return gewijzigd

    def laat_vervallen(self, nu: datetime, reden: str) -> list[VariantTrade]:
        """Alle open varianten vervallen (bijv. nieuwe run)."""
        uit = []
        for t in list(self.open_trades):
            t.status = "vervallen"
            t.close_reason = reden[:120]
            t.close_time = _iso(nu)
            self.open_trades.remove(t)
            self.vervallen += 1
            uit.append(t)
        return uit

    def statistiek(self, echte: dict | None = None) -> dict:
        return varianten_statistiek(
            self.gesloten, echte or {}, len(self.open_trades), self.vervallen,
        )


# --------------------------------------------------------------------------- #
# Statistiek                                                                  #
# --------------------------------------------------------------------------- #

def echte_sluitcode(reden: str | None) -> str:
    """Sluitreden van een echte trade als code die varianten ook gebruiken."""
    tekst = str(reden or "")
    if tekst in ("stop_loss", "take_profit"):
        return tekst
    if "maximale positieduur" in tekst:
        return "max_duur"
    if ("binnen" in tekst and "ATR" in tekst) or "dode zone" in tekst:
        return "tijdstop"
    if tekst in ("time_stop", "timeout"):
        return "tijdstop"
    return tekst or "unknown"


def _duur(t) -> float | None:
    a, b = _tijd(t.open_time), _tijd(t.close_time)
    return (b - a).total_seconds() if a and b else None


def _pct(n: int, totaal: int) -> float | None:
    return round(n / totaal * 100.0, 1) if totaal else None


def per_variant(rijen: list) -> dict:
    n = len(rijen)
    netto = [t.netto for t in rijen]
    winst = [x for x in netto if x > 0]
    verlies = [x for x in netto if x < 0]
    redenen: dict[str, int] = {}
    for t in rijen:
        redenen[t.close_reason or "?"] = redenen.get(t.close_reason or "?", 0) + 1
    duren = [d for d in (_duur(t) for t in rijen) if d is not None]
    return {
        "trades": n,
        "netto": round(sum(netto), 2) if n else 0.0,
        "bruto": round(sum(t.bruto or 0.0 for t in rijen), 2) if n else 0.0,
        "kosten": round(sum(t.kosten or 0.0 for t in rijen), 2) if n else 0.0,
        "netto_per_trade": round(sum(netto) / n, 3) if n else None,
        "winst_pct": _pct(len(winst), n),
        "profit_factor": (
            round(sum(winst) / abs(sum(verlies)), 3) if verlies else None
        ),
        "doel_pct": _pct(redenen.get("take_profit", 0), n),
        "stop_pct": _pct(redenen.get("stop_loss", 0), n),
        "tijdstop_pct": _pct(redenen.get("tijdstop", 0), n),
        "max_duur_pct": _pct(redenen.get("max_duur", 0), n),
        "gem_duur_s": round(sum(duren) / len(duren), 1) if duren else None,
    }


def varianten_statistiek(gesloten: Iterable, echte: dict, open_aantal: int = 0,
                         vervallen: int = 0) -> dict:
    """Per variant, gepaard tegen 240 (per trade en per uurblok) en overeenkomst.

    ``echte``: trade_ref -> object met ``close_reason`` (effectieve reden) en
    ``net_pnl`` (USD) van de gesloten echte trade.

    Gepaard alleen over trades waarvan álle varianten gesloten zijn: dan
    rusten alle vergelijkingen op dezelfde trades en dezelfde blokken. Een
    blok is het uur (UTC) waarin de echte trade opende; per blok telt de som
    van de verschillen. t over blokken, met de lag-1-autocorrelatie van de
    blokverschillen ernaast (blokken zijn niet volledig onafhankelijk).
    """
    from ..storage.performance import blok_sleutel, blok_toets

    rijen = [t for t in gesloten if getattr(t, "netto", None) is not None]
    per_v: dict[str, list] = {v: [] for v in VARIANTEN}
    per_ref: dict[str, dict[str, object]] = {}
    for t in rijen:
        if t.variant not in per_v:
            continue
        per_v[t.variant].append(t)
        per_ref.setdefault(t.trade_ref, {})[t.variant] = t
    volledig = {
        ref: d for ref, d in per_ref.items() if len(d) == len(VARIANTEN)
    }

    gepaard: dict[str, dict] = {}
    blokken_alle: set[str] = set()
    for variant in VARIANTEN:
        if variant == BASIS:
            continue
        verschil_trade: list[float] = []
        per_blok: dict[str, float] = {}
        for ref, d in volledig.items():
            v = d[variant].netto - d[BASIS].netto
            verschil_trade.append(v)
            blok = blok_sleutel(d[BASIS].open_time)
            if blok is None:
                continue
            per_blok[blok] = per_blok.get(blok, 0.0) + v
        blokken_alle.update(per_blok)
        reeks = [per_blok[b] for b in sorted(per_blok)]
        toets_trade = blok_toets(verschil_trade)
        toets_blok = blok_toets(reeks)
        gepaard[variant] = {
            "trades": len(verschil_trade),
            "verschil_per_trade": toets_trade["gemiddeld"],
            "t_per_trade": toets_trade["t"],
            "blokken": toets_blok["n"],
            "verschil_per_blok": toets_blok["gemiddeld"],
            "t_blokken": toets_blok["t"],
            "lag1": toets_blok["lag1"],
        }

    # Overeenkomst van de 240-variant met de echte trade.
    vergeleken = gelijk_reden = overeenkomst = 0
    verschillen: list[float] = []
    for t in per_v[BASIS]:
        echt = echte.get(t.trade_ref)
        if echt is None or getattr(echt, "net_pnl", None) is None:
            continue
        vergeleken += 1
        zelfde = echte_sluitcode(getattr(echt, "close_reason", None)) == t.close_reason
        verschil = t.netto - float(echt.net_pnl)
        verschillen.append(verschil)
        gelijk_reden += int(zelfde)
        overeenkomst += int(zelfde and abs(verschil) < OVEREENKOMST_USD)

    n_blokken = len(blokken_alle)
    return {
        "blokken": n_blokken,
        "volledige_trades": len(volledig),
        "open": open_aantal,
        "vervallen": vervallen,
        "per_variant": {v: per_variant(per_v[v]) for v in VARIANTEN},
        "gepaard_tegen_240": gepaard,
        "overeenkomst": {
            "vergeleken": vergeleken,
            "overeenkomst_pct": _pct(overeenkomst, vergeleken),
            "zelfde_sluitreden_pct": _pct(gelijk_reden, vergeleken),
            "gem_verschil_netto": (
                round(sum(verschillen) / len(verschillen), 3)
                if verschillen else None
            ),
            "regel": (
                f"zelfde sluitreden en |netto 240-variant - echt| < "
                f"{OVEREENKOMST_USD} USD"
            ),
        },
        "oordeel": oordeel(n_blokken, gepaard),
        "let_op": (
            "Gesimuleerd, alleen meting. Telt niet mee in het echte resultaat; "
            "de echte tijdstop blijft 240 s tot Ruud anders beslist."
        ),
    }


def oordeel(n_blokken: int, gepaard: dict) -> str:
    if n_blokken < MIN_BLOKKEN:
        return (
            f"te weinig blokken ({n_blokken} van {MIN_BLOKKEN} uurblokken); "
            "nog geen oordeel"
        )
    beter = [
        (v, g) for v, g in gepaard.items()
        if g.get("t_blokken") is not None and g["t_blokken"] >= T_DREMPEL
        and (g.get("verschil_per_blok") or 0) > 0
    ]
    if beter:
        v, g = max(beter, key=lambda x: x[1]["verschil_per_blok"])
        return (
            f"variant {v} beter dan 240 s: {g['verschil_per_blok']:+.2f} USD "
            f"per uurblok, t={g['t_blokken']:.2f} over {g['blokken']} blokken "
            f"(lag-1 {g['lag1']}); beslissing ligt bij Ruud"
        )
    slechter = [
        g for g in gepaard.values()
        if g.get("t_blokken") is not None and g["t_blokken"] <= -T_DREMPEL
    ]
    if gepaard and len(slechter) == len(gepaard):
        return (
            f"240 s (huidige instelling) het best: alle varianten slechter "
            f"met t ≤ -{T_DREMPEL:.0f} over {n_blokken} blokken"
        )
    return f"geen duidelijk verschil over {n_blokken} uurblokken"
