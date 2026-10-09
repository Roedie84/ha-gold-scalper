"""Schaduwtrades: geldige signalen die niet werden uitgevoerd, gesimuleerd (1.9.0).

Een signaal dat door alle signaalfilters komt maar niet wordt uitgevoerd -
omdat de positielimiet bereikt is, de cooldown loopt, de marge het niet
toelaat - is een waarneming die anders verloren gaat. Hier wordt die trade
gesimuleerd met precies de regels van een echte:

* **Instap** op de laat (long) of bied (short) van dat moment, dus inclusief
  de spread; stop en doel uit het signaal.
* **Stop en doel** getoetst tegen de uitersten van de bars sinds de vorige
  cyclus, zoals de papersimulatie: bied voor een long, laat voor een short.
  Zijn beide in hetzelfde interval geraakt, dan telt de stop (de enige
  verdedigbare aanname). Afgerekend op het niveau zelf.
* **Tijdstop, maximale duur, trailing en break-even** via dezelfde
  ``ExitManager`` als de echte posities.
* **Kosten**: de spread zit in de instap- en uitstapprijs; daarbovenop de
  geschatte slippage per zijde en de commissie uit de strategie-instellingen.

Geen extra verzoeken bij de broker: alleen de koers en bars die de bot toch
al ophaalt. Opgeslagen in een eigen tabel; ze tellen nergens mee in het echte
resultaat, de bewijsfase of de live-poort.

**Welke redenen tellen.** Zie ``SCHADUW_REDENEN``. Niet: signaalfilters (dan
was er geen geldig signaal), een gesloten markt of verouderde koers (dan is
er geen betrouwbare instapprijs), de sluitingsbuffer (de trade zou door de
sluiting worden overvallen) en de spreidingsregel (dat is per definitie een
kopie van een positie die er al staat).

**Ontdubbeling.** Een signaal blijft vaak meerdere cycli staan. Per richting
hooguit één schaduwtrade per candle, en met dezelfde minimale spreiding als
echte posities (0,3 x ATR) ten opzichte van open schaduwtrades en echte
posities in die richting.

**Herstart.** Een schaduwtrade die langer dan ``MAX_GAT_SECONDEN`` niet is
bijgewerkt (herstart, gesloten markt) is niet meer eerlijk te volgen: hij
krijgt de status ``vervallen`` en telt niet mee.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Iterable

from ..broker.exits import ExitManager
from ..const import CONTRACT_SIZE
from .posities import MIN_SPREIDING_ATR, bar_index, richting_van


#: Redenen waarom een geldig signaal niet werd uitgevoerd en dat wél een
#: schaduwtrade oplevert, met hun categorie.
SCHADUW_REDENEN = {
    "positielimiet": "positielimiet per richting bereikt",
    "cooldown": "cooldown tussen instappen",
    "marge": "geschatte marge past niet in de vrije marge",
    "vloer": "alle stops samen zouden onder de vermogensvloer komen",
    "netting": "hedgen uitgeschakeld na gedetecteerde verrekening",
    "risico": "risicolimiet (daglimiet, noodstop, pauze, tradelimiet, spreadvangnet)",
    "handel_uit": "handel staat uit",
    "levenscyclus": "levenscyclus neemt geen nieuwe posities aan",
    "onbevestigde_order": "eerst een onbevestigde order terugvinden",
    "wisselkoers": "geen bruikbare wisselkoers",
    "per_cyclus": "al een positie geopend in deze cyclus",
}

#: Na zoveel seconden zonder bijwerking is een open schaduwtrade niet eerlijk
#: meer te volgen.
MAX_GAT_SECONDEN = 300
#: Vangnet tegen een op hol geslagen lus.
MAX_OPEN = 50


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _tijd(tekst) -> datetime | None:
    if not tekst:
        return None
    try:
        m = datetime.fromisoformat(str(tekst))
    except (TypeError, ValueError):
        return None
    return m if m.tzinfo else m.replace(tzinfo=timezone.utc)


@dataclass(slots=True)
class SchaduwTrade:
    run_id: int | None
    richting: int
    open_time: str
    open_price: float
    open_mid: float
    open_spread: float
    units: float
    stop_loss: float | None
    take_profit: float | None
    reden: str
    reden_tekst: str | None = None
    score: float | None = None
    status: str = "open"            # open | gesloten | vervallen
    close_time: str | None = None
    close_price: float | None = None
    close_mid: float | None = None
    close_reason: str | None = None
    bruto: float | None = None      # mid op mid, zonder kosten
    kosten: float | None = None     # spread + geschatte slippage + commissie
    netto: float | None = None
    mfe: float = 0.0
    mae: float = 0.0
    laatst_bijgewerkt: str | None = None
    id: int | None = None

    @property
    def side(self) -> str:
        return "buy" if self.richting == 1 else "sell"

    # Voor de clusterdefinitie uit storage/performance.py.
    @property
    def net_pnl(self) -> float | None:
        return self.netto

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class SchaduwKosten:
    #: Geschatte slippage per zijde in USD per ounce.
    slippage: float = 0.02
    #: Commissie per lot per zijde.
    commissie_per_lot: float = 0.0


def sluit_trade(t, prijs: float, mid: float, nu: datetime, reden: str,
                kosten: SchaduwKosten) -> None:
    """Sluit een gesimuleerde trade af op ``prijs`` (1.9.5: gedeeld).

    Netto: uitstap min instap (beide inclusief spread), min geschatte
    slippage per zijde en commissie. Bruto: mid op mid.
    """
    r = t.richting
    lots = t.units / CONTRACT_SIZE
    commissie = 2 * kosten.commissie_per_lot * lots
    slippage = 2 * kosten.slippage * t.units
    t.close_time = _iso(nu)
    t.close_price = round(prijs, 3)
    t.close_mid = round(mid, 3)
    t.close_reason = reden
    t.bruto = round((mid - t.open_mid) * r * t.units, 4)
    t.netto = round((prijs - t.open_price) * r * t.units - slippage - commissie, 4)
    t.kosten = round(t.bruto - t.netto, 4)
    t.status = "gesloten"
    t.laatst_bijgewerkt = _iso(nu)


def sluitcode(reden: str | None) -> str:
    """Reden van het exitbeheer als korte code: max_duur, tijdstop of exit."""
    reden = reden or ""
    if "maximale positieduur" in reden:
        return "max_duur"
    if "dode zone" in reden or "binnen" in reden:
        return "tijdstop"
    return "exit"


def stap_trade(t, exits: ExitManager, kosten: SchaduwKosten, *, bid: float,
               ask: float, hoog: float | None, laag: float | None, atr: float,
               nu: datetime, rondreis_kosten: float) -> str:
    """Eén gesimuleerde trade één cyclus verder (1.9.5: gedeeld).

    Geeft ``"vervallen"``, ``"gesloten"`` of ``"open"`` terug; de trade zelf
    wordt bijgewerkt. Dezelfde regels voor schaduwtrades en
    tijdstopvarianten:

    * na meer dan ``MAX_GAT_SECONDEN`` zonder bijwerking: vervallen;
    * stop en doel tegen de uitersten (bied voor een long, laat voor een
      short); beide geraakt telt de stop; afgerekend op het niveau;
    * daarna de ``ExitManager`` (tijdstop, maximale duur, trailing,
      break-even), afgerekend op bied (long) of laat (short).
    """
    half = (ask - bid) / 2.0
    mid = (bid + ask) / 2.0
    laagste_bied = bid if laag is None else min(bid, laag - half)
    hoogste_laat = ask if hoog is None else max(ask, hoog + half)
    hoogste_bied = bid if hoog is None else max(bid, hoog - half)
    laagste_laat = ask if laag is None else min(ask, laag + half)
    vorige = _tijd(t.laatst_bijgewerkt) or _tijd(t.open_time)
    if vorige is not None and (nu - vorige).total_seconds() > MAX_GAT_SECONDEN:
        t.status = "vervallen"
        t.close_reason = "niet te volgen (gat in de koersdata)"
        t.close_time = _iso(nu)
        return "vervallen"
    long = t.richting == 1
    slechtst = laagste_bied if long else hoogste_laat
    best = hoogste_bied if long else laagste_laat
    t.mfe = max(t.mfe, (best - t.open_price) * t.richting)
    t.mae = min(t.mae, (slechtst - t.open_price) * t.richting)
    stop_geraakt = t.stop_loss is not None and (
        slechtst <= t.stop_loss if long else slechtst >= t.stop_loss)
    doel_geraakt = t.take_profit is not None and (
        best >= t.take_profit if long else best <= t.take_profit)
    if stop_geraakt or doel_geraakt:
        niveau = t.stop_loss if stop_geraakt else t.take_profit
        niveau_mid = niveau + half if long else niveau - half
        sluit_trade(t, niveau, niveau_mid, nu,
                    "stop_loss" if stop_geraakt else "take_profit", kosten)
        return "gesloten"
    actie = exits.evaluate(
        side=t.side, volume=t.units, open_price=t.open_price,
        current_stop=t.stop_loss, bid=bid, ask=ask, atr=atr,
        opened_at=_tijd(t.open_time) or nu, now=nu,
        round_trip_cost_per_oz=rondreis_kosten,
    )
    t.laatst_bijgewerkt = _iso(nu)
    if actie.kind == "close":
        prijs = bid if long else ask
        sluit_trade(t, prijs, mid, nu, sluitcode(actie.reason or "exit"), kosten)
        return "gesloten"
    if actie.kind == "modify_stop" and actie.new_stop is not None:
        t.stop_loss = actie.new_stop
    # Gedeeltelijk sluiten staat standaard uit en wordt hier niet
    # nagebootst: een gesimuleerde trade loopt dan als geheel door.
    return "open"


@dataclass
class SchaduwBoek:
    """Open en gesloten schaduwtrades van één run, in het geheugen.

    De opslag (database) staat erbuiten: de coordinator schrijft wat
    ``open`` en ``bijwerken`` teruggeven weg. Zo is dit los te toetsen.
    """

    exits: ExitManager
    kosten: SchaduwKosten = field(default_factory=SchaduwKosten)
    bar_seconden: int = 60
    open_trades: list[SchaduwTrade] = field(default_factory=list)
    gesloten: list[SchaduwTrade] = field(default_factory=list)
    vervallen: int = 0

    # -- openen ------------------------------------------------------------ #

    def mag_openen(self, richting: int, instap: float, atr: float | None,
                   nu: datetime, echte_posities: Iterable = ()) -> tuple[bool, str | None]:
        """Ontdubbeling: één per richting per candle, met minimale spreiding."""
        if len(self.open_trades) >= MAX_OPEN:
            return False, "maximum aantal open schaduwtrades"
        nu_bar = bar_index(nu, self.bar_seconden)
        bestaand = [
            (t.open_price, t.open_time) for t in self.open_trades
            if t.richting == richting
        ]
        for p in echte_posities:
            if richting_van(getattr(p, "side", "buy")) != richting:
                continue
            bestaand.append((
                getattr(p, "open_price", None),
                getattr(p, "open_time", None),
            ))
        laatste = [t for t in self.open_trades + self.gesloten[-20:]
                   if t.richting == richting]
        if laatste and nu_bar is not None:
            if max(bar_index(t.open_time, self.bar_seconden) or -1
                   for t in laatste) >= nu_bar:
                return False, "al een schaduwtrade in deze richting in deze candle"
        if not atr or atr <= 0:
            return False, "geen bruikbare ATR"
        prijzen = [float(p) for p, _ in bestaand if p is not None]
        if prijzen and min(abs(instap - p) for p in prijzen) < MIN_SPREIDING_ATR * atr:
            return False, "te dicht bij een open positie of schaduwtrade"
        return True, None

    def openen(self, *, run_id, signal, bid: float, ask: float, nu: datetime,
             units: float, reden: str, reden_tekst: str | None,
             atr: float | None, echte_posities: Iterable = ()) -> SchaduwTrade | None:
        if reden not in SCHADUW_REDENEN:
            return None
        if not getattr(signal, "geldig", False):
            return None
        richting = int(getattr(signal, "direction", 0) or 0)
        if richting not in (1, -1) or signal.stop_loss is None:
            return None
        instap = ask if richting == 1 else bid
        ok, _ = self.mag_openen(richting, instap, atr, nu, echte_posities)
        if not ok:
            return None
        trade = SchaduwTrade(
            run_id=run_id, richting=richting, open_time=_iso(nu),
            open_price=float(instap), open_mid=(bid + ask) / 2.0,
            open_spread=ask - bid, units=float(units),
            stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            reden=reden, reden_tekst=(reden_tekst or "")[:200] or None,
            score=round(float(signal.score), 4),
            laatst_bijgewerkt=_iso(nu),
        )
        self.open_trades.append(trade)
        return trade

    # -- bijwerken --------------------------------------------------------- #

    def _sluit(self, t: SchaduwTrade, prijs: float, mid: float, spread_uit: float,
               nu: datetime, reden: str) -> None:
        sluit_trade(t, prijs, mid, nu, reden, self.kosten)

    def bijwerken(self, *, bid: float, ask: float, hoog: float | None,
                  laag: float | None, atr: float, nu: datetime) -> list[SchaduwTrade]:
        """Eén cyclus. Geeft de trades terug die veranderden (om weg te schrijven).

        ``hoog`` en ``laag`` zijn de uitersten (mid) van de bars sinds de
        vorige cyclus, zoals de papersimulatie ze krijgt.
        """
        gewijzigd: list[SchaduwTrade] = []
        rondreis = (ask - bid) + 2 * self.kosten.slippage
        for t in list(self.open_trades):
            uitkomst = stap_trade(
                t, self.exits, self.kosten, bid=bid, ask=ask, hoog=hoog,
                laag=laag, atr=atr, nu=nu, rondreis_kosten=rondreis,
            )
            if uitkomst == "vervallen":
                self.open_trades.remove(t)
                self.vervallen += 1
            elif uitkomst == "gesloten":
                self.open_trades.remove(t)
                self.gesloten.append(t)
            gewijzigd.append(t)
        return gewijzigd

    # -- statistiek -------------------------------------------------------- #

    def statistiek(self) -> dict:
        return schaduw_statistiek(self.gesloten, len(self.open_trades), self.vervallen)


def schaduw_statistiek(gesloten: list, open_aantal: int = 0, vervallen: int = 0) -> dict:
    """Aantal, winst%, PF, netto en t-statistiek over clusters.

    Dezelfde clusterdefinitie als de echte statistiek (``storage/performance``):
    gesorteerd op opening, een trade die opent vóór of binnen tien minuten na
    het laatste sluitmoment hoort bij hetzelfde cluster. Gelijktijdig open
    schaduwtrades vallen daardoor altijd in één cluster.
    """
    from ..storage.performance import CLUSTER_MINUTEN, _t, cluster_resultaten

    rijen = [t for t in gesloten if getattr(t, "netto", None) is not None]
    n = len(rijen)
    netto = [t.netto for t in rijen]
    winst = [x for x in netto if x > 0]
    verlies = [x for x in netto if x < 0]
    bruto_winst = sum(winst)
    bruto_verlies = abs(sum(verlies))
    clusters = cluster_resultaten([
        SimpleNamespace(open_time=t.open_time, close_time=t.close_time, net_pnl=t.netto)
        for t in rijen
    ])
    redenen: dict[str, int] = {}
    sluit: dict[str, int] = {}
    for t in rijen:
        redenen[t.reden] = redenen.get(t.reden, 0) + 1
        sluit[t.close_reason or "?"] = sluit.get(t.close_reason or "?", 0) + 1
    t_stat = _t(clusters) if len(clusters) > 1 else 0.0
    return {
        "trades": n,
        "open": open_aantal,
        "vervallen": vervallen,
        "winst": len(winst),
        "verlies": len(verlies),
        "winst_pct": round(len(winst) / n * 100.0, 1) if n else None,
        "profit_factor": (
            round(bruto_winst / bruto_verlies, 3) if bruto_verlies > 0 else None
        ),
        "netto": round(sum(netto), 2) if n else 0.0,
        "bruto": round(sum(t.bruto or 0.0 for t in rijen), 2) if n else 0.0,
        "kosten": round(sum(t.kosten or 0.0 for t in rijen), 2) if n else 0.0,
        "verwachting": round(sum(netto) / n, 3) if n else None,
        "clusters": len(clusters),
        "t_statistiek": round(t_stat, 3) if math.isfinite(t_stat) else None,
        "t_basis": (
            f"{len(clusters)} clusters uit {n} schaduwtrades "
            f"(herinstap binnen {CLUSTER_MINUTEN:.0f} min = zelfde cluster)"
        ),
        "per_reden": redenen,
        "per_sluitreden": sluit,
        "let_op": "Gesimuleerd. Telt niet mee in het echte resultaat of de bewijsfase.",
    }
