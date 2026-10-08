"""Dagelijkse afstemming van de eigen administratie met de broker.

Zes keer in een paar weken is een fout in de koppeling gevonden door een
schermafdruk van het brokeroverzicht naast het rapport te leggen: verkeerde
uitstapprijzen, verwisselde trades, open posities die als gesloten golden.
Elke keer handmatig, en elke keer pas nadat de fout dagen had doorgewerkt.

Deze module doet dat werk: elke gesloten trade wordt gezocht in het
transactieoverzicht van de broker, met dezelfde koppelregel als de correctie,
en vergeleken op uitstapprijs en bedrag.

**Wat telt als afwijking.** Een uitstapprijs die meer dan een cent verschilt,
of een bedrag in accountvaluta dat meer dan twee procent afwijkt. Die twee
procent is geen slordigheid: de broker rekent winst en verlies tegen
verschillende wisselkoersen om, en één koers voor beide geeft kleine
verschillen die niets met een fout te maken hebben.

**Overnemen (5.6.2).** Noemt de broker de koers waartegen hij omrekende
("converted at ..."), dan is zijn bedrag exact te controleren én over te nemen.
Het bedrag in accountvaluta, de koers, de omvang en het resultaat in dollars
komen dan van de broker; wat eerst binnen de tolerantie "klopte", klopt dan op
de cent. Een uitstapprijs wordt alleen overgenomen bij hooguit een cent
verschil (5.7), met de oude waarde in ``exit_price_provenance``; een groter
verschil wijst op een verkeerde koppeling en blijft een zichtbare afwijking.

**Sterke koppeling (1.4).** Klopt de instapprijs op de cent, de omvang en
het openingsmoment van de broker (``openDateUtc``) binnen tien minuten, dan is
het zeker dezelfde trade. Een groter verschil in uitstapprijs is dan geen
verkeerde koppeling maar slippage: de broker vulde anders dan de koers die de
lus zag. Dan wordt zijn prijs overgenomen, met de oude waarde in
``exit_price_provenance``, en geldt het niet als afwijking. Bij een zwakke
koppeling blijft een groter verschil wel een afwijking.

**Kosten (1.4).** Met de afrekening van de broker erbij worden de kosten van
de trade gemeten (zie ``kosten.py``) en gaat ``cost_source`` naar
``measured``.

**Voorlopige afwikkelingen (1.7.3).** Een trade die op een geschatte
uitstapprijs is afgerekend (``reconciliation_status == "pending"``) krijgt
hier de prijs van de broker, ook bij een zwakke koppeling: zijn eigen prijs
was een schatting, dus een verschil is geen afwijking. Tegelijk krijgt hij
zijn sluitreden en daarmee gemeten kosten, zodat ``sluitreden_onbekend`` en
``kosten_gemeten`` niet op een aparte correctieronde hoeven te wachten.

**Wat niet telt.** Trades die nog niet in het overzicht staan. Dat overzicht
loopt uren achter, dus een ontbrekende trade van vandaag is geen afwijking maar
geduld. Pas na twee dagen heet hij ontbrekend.
"""

from __future__ import annotations

import json

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Sequence

from ..storage.database import Trade
from .kosten import meet_kosten

#: Een uitstapprijs mag hooguit zoveel verschillen.
PRIJS_TOLERANTIE = 0.01

#: Een bedrag in accountvaluta mag hooguit dit deel afwijken.
BEDRAG_TOLERANTIE = 0.02

#: Pas na zoveel dagen geldt een trade zonder transactie als ontbrekend.
ONTBREKEND_NA_DAGEN = 2.0

#: Met de koers van de broker erbij: zoveel euro mag het eigen bedrag afwijken
#: voordat het wordt overgenomen. De broker rondt af op centen.
CENT_TOLERANTIE = 0.015

#: Omvang in ounce: kleinere verschillen zijn afronding.
OMVANG_TOLERANTIE = 0.005


@dataclass(slots=True)
class Afwijking:
    ticket: str
    soort: str
    uitleg: str

    def as_dict(self) -> dict:
        return {"ticket": self.ticket, "soort": self.soort, "uitleg": self.uitleg}


@dataclass(slots=True)
class Afstemming:
    trades: int = 0
    gevonden: int = 0
    kloppend: int = 0
    nog_niet_verwerkt: int = 0
    #: Uitstapprijzen die bij een sterke koppeling naar de broker gingen.
    slippage_overgenomen: int = 0
    #: Trades waarvan de kosten in deze ronde zijn gemeten.
    kosten_gemeten: int = 0
    #: 1.7.3: voorlopige afwikkelingen (geschatte uitstap) die hier hun
    #: brokerprijs en sluitreden kregen.
    voorlopig_bijgewerkt: int = 0
    afwijkingen: list = field(default_factory=list)
    #: Trades waarvan bedrag, koers of omvang naar de broker is bijgewerkt:
    #: ``{"trade_id", "ticket", "velden": {...}}``. De coordinator legt ze vast.
    overnames: list = field(default_factory=list)

    @property
    def in_orde(self) -> bool:
        return not self.afwijkingen

    def samenvatting(self) -> str:
        if not self.trades:
            return "Geen gesloten trades om af te stemmen."
        tekst = (
            f"{self.kloppend} van {self.gevonden} gevonden trades kloppen met "
            f"de broker"
        )
        if self.nog_niet_verwerkt:
            tekst += (
                f"; {self.nog_niet_verwerkt} nog niet in zijn overzicht "
                "(dat loopt uren achter)"
            )
        if self.overnames:
            tekst += (
                f"; {len(self.overnames)} bijgewerkt naar het bedrag van de broker"
            )
        if self.afwijkingen:
            tekst += f". {len(self.afwijkingen)} afwijking(en)."
        else:
            tekst += "."
        return tekst

    def as_dict(self) -> dict:
        return {
            "trades": self.trades,
            "gevonden": self.gevonden,
            "kloppend": self.kloppend,
            "nog_niet_verwerkt": self.nog_niet_verwerkt,
            "afwijkingen": [a.as_dict() for a in self.afwijkingen],
            "bijgewerkt": len(self.overnames),
            "slippage_overgenomen": self.slippage_overgenomen,
            "kosten_gemeten": self.kosten_gemeten,
            "voorlopig_bijgewerkt": self.voorlopig_bijgewerkt,
            "in_orde": self.in_orde,
            "samenvatting": self.samenvatting(),
        }


def _moment(waarde) -> datetime | None:
    if not waarde:
        return None
    try:
        m = datetime.fromisoformat(str(waarde))
    except (TypeError, ValueError):
        return None
    return m if m.tzinfo else m.replace(tzinfo=timezone.utc)


def stem_af(
    trades: Sequence[Trade],
    transacties: list,
    koers: float | None,
    now: datetime,
    contract_size: float = 100.0,
) -> Afstemming:
    """Leg de eigen trades naast het transactieoverzicht van de broker."""
    from ..broker.ig_capital import match_transaction

    uitslag = Afstemming()
    for trade in trades:
        if not trade.close_time or not trade.broker_ticket:
            continue
        # Stops en doelen die de lus zelf afwikkelde staan ook in het
        # overzicht; alles wat bij de broker liep, wordt gecontroleerd.
        uitslag.trades += 1
        units = (trade.volume or 0) * contract_size
        match = match_transaction(
            transacties, trade.broker_ticket, trade.open_price,
            trade.side, units or None, trade.open_time,
        )

        if match is None:
            gesloten = _moment(trade.close_time)
            leeftijd = (now - gesloten).total_seconds() / 86400 if gesloten else 0
            if leeftijd > ONTBREKEND_NA_DAGEN:
                uitslag.afwijkingen.append(Afwijking(
                    str(trade.broker_ticket), "ontbreekt",
                    f"Trade met instap {trade.open_price} staat na "
                    f"{leeftijd:.1f} dagen niet in het overzicht van de broker.",
                ))
            else:
                uitslag.nog_niet_verwerkt += 1
            continue

        uitslag.gevonden += 1
        fouten = []

        broker_uit = match.get("exit_price")
        uit_velden: dict = {}
        slippage = False
        voorlopig = _voorlopig(trade)
        if broker_uit is not None and trade.close_price is not None:
            verschil = round(broker_uit - trade.close_price, 6)
            if abs(verschil) > PRIJS_TOLERANTIE + 1e-9 and voorlopig:
                # 1.7.3: de eigen prijs was uitdrukkelijk een schatting. Een
                # verschil is dan geen afwijking maar precies wat er nog
                # ontbrak; de correctie neemt dezelfde koppeling ook over.
                slippage = True
                uit_velden = {
                    "close_price": broker_uit,
                    "exit_price_provenance": json.dumps({
                        "original_local": trade.close_price, "broker": broker_uit,
                        "difference": verschil,
                        "status": "ADOPTED_BROKER_SETTLEMENT_ESTIMATE",
                        "matched_on": match.get("matched_on"),
                        "broker_reference": match.get("reference"),
                        "source": "broker_transactions", "at": now.isoformat(),
                    }, sort_keys=True),
                }
            elif abs(verschil) > PRIJS_TOLERANTIE + 1e-9 and _sterk(trade, match, units):
                # Zeker dezelfde trade: het verschil is slippage. De broker is
                # de afrekening.
                slippage = True
                uitslag.slippage_overgenomen += 1
                uit_velden = {
                    "close_price": broker_uit,
                    "exit_price_provenance": json.dumps({
                        "original_local": trade.close_price, "broker": broker_uit,
                        "difference": verschil,
                        "status": "ADOPTED_BROKER_SETTLEMENT_SLIPPAGE",
                        "matched_on": match.get("matched_on"),
                        "broker_reference": match.get("reference"),
                        "source": "broker_transactions", "at": now.isoformat(),
                    }, sort_keys=True),
                }
            elif abs(verschil) > PRIJS_TOLERANTIE + 1e-9:
                # Groter dan een cent bij een zwakke koppeling: nooit stil
                # gelijkgesteld.
                fouten.append(
                    f"uitstap {trade.close_price} tegen {broker_uit} bij de broker"
                )
            elif verschil != 0:
                # Hooguit een cent: de broker is de afrekening. Overnemen, met
                # de oude waarde erbij.
                uit_velden = {
                    "close_price": broker_uit,
                    "exit_price_provenance": json.dumps({
                        "original_local": trade.close_price, "broker": broker_uit,
                        "difference": verschil, "status": "ADOPTED_BROKER_SETTLEMENT",
                        "source": "broker_transactions", "at": now.isoformat(),
                    }, sort_keys=True),
                }

        broker_bedrag = match.get("profit_account")
        broker_koers = match.get("conversion_rate")
        prijs_klopt = not fouten
        velden = dict(uit_velden)
        if (broker_bedrag is not None and broker_koers and prijs_klopt
                and trade.net_pnl is not None):
            # Met de koers van de broker: exact controleren en overnemen.
            bedrag_velden, fout = _overname(trade, match, contract_size)
            # Na overgenomen slippage verschilt het oude bedrag vanzelf: dat
            # verschil is verklaard en geen afwijking.
            if fout and not slippage:
                fouten.append(fout)
            velden.update(bedrag_velden)
        elif broker_bedrag is not None and koers and trade.net_pnl is not None:
            # Zonder koers van de broker: vergelijken met de middenkoers, met
            # ruimte voor het verschil tussen zijn winst- en verlieskoers.
            eigen = trade.net_pnl * koers
            verschil = abs(eigen - broker_bedrag)
            grens = max(0.05, abs(broker_bedrag) * BEDRAG_TOLERANTIE)
            if verschil > grens:
                fouten.append(
                    f"bedrag {eigen:+.2f} tegen {broker_bedrag:+.2f} bij de broker"
                )
        if slippage and "net_pnl" not in velden and trade.open_price is not None:
            richting = 1.0 if trade.side == "buy" else -1.0
            netto = round((broker_uit - trade.open_price) * richting * units, 4)
            velden["net_pnl"] = netto

        # 1.7.3: een voorlopige afwikkeling krijgt met de brokerprijs ook
        # zijn sluitreden. Zonder die reden kan meet_kosten niets en bleef de
        # trade "onbekend" en "berekend" tot de correctie hem apart oppakte.
        meet_op = trade
        if voorlopig and broker_uit is not None and prijs_klopt:
            reden = _reden_velden(trade, broker_uit, now)
            velden.update(reden)
            uitslag.voorlopig_bijgewerkt += 1
            meet_op = replace(trade, **{
                k: v for k, v in reden.items() if k != "close_reason"
            })

        if trade.cost_source != "measured" and broker_uit is not None and prijs_klopt:
            kosten = meet_kosten(meet_op, broker_uit, contract_size)
            if kosten is not None:
                netto = velden.get("net_pnl", trade.net_pnl)
                velden.update({
                    "total_cost": kosten["total_cost"],
                    "spread_cost": kosten["spread_cost"],
                    "slippage_cost": kosten["slippage_cost"],
                    "cost_source": "measured",
                })
                if netto is not None:
                    velden["gross_pnl"] = round(netto + kosten["total_cost"], 4)
                uitslag.kosten_gemeten += 1

        if velden:
            uitslag.overnames.append({
                "trade_id": trade.id, "ticket": str(trade.broker_ticket), "velden": velden,
            })

        if fouten:
            uitslag.afwijkingen.append(Afwijking(
                str(trade.broker_ticket), "verschilt",
                f"Instap {trade.open_price}: " + "; ".join(fouten) + ".",
            ))
        else:
            uitslag.kloppend += 1

    return uitslag


def _voorlopig(trade: Trade) -> bool:
    """Is deze trade afgerekend op een geschatte uitstapprijs die nog open staat?"""
    status = getattr(trade, "reconciliation_status", None)
    if status == "pending":
        return True
    return status is None and trade.close_reason == "broker_gesloten_geschat"


def _reden_velden(trade: Trade, broker_uit: float, now: datetime) -> dict:
    """Sluitreden uit de brokerprijs, zoals de coordinator die afleidt.

    Dezelfde regel als ``_apply_reconciliation``: de stop telt alleen als
    bewijs bij uitvoeringsversie 2 of later, want daarvóór kan de stop in de
    database verouderd zijn.
    """
    from .exit_stats import derive_close_reason

    afgeleid = derive_close_reason(
        broker_uit, trade.take_profit, trade.stop_loss,
        (getattr(trade, "execution_semantics", None) or 0) >= 2,
    )
    return {
        "reconciled_close_reason": afgeleid.reden,
        "close_reason_source": afgeleid.bron,
        "close_reason_evidence": afgeleid.bewijs,
        "reconciliation_status": "reconciled",
        "reconciled_at": now.isoformat(),
        "reconciliation_source": "broker_transactions",
        "close_reason": "broker_gesloten_gecorrigeerd",
    }


def _sterk(trade: Trade, match: dict, units: float) -> bool:
    """Zeker dezelfde trade: instap op de cent, omvang en openingsmoment."""
    if match.get("matched_on") != "instapprijs+opentijd":
        return False
    instap = match.get("open_price")
    if instap is None or trade.open_price is None:
        return False
    if abs(instap - trade.open_price) > PRIJS_TOLERANTIE + 1e-9:
        return False
    omvang = _omvang(match)
    if omvang is not None and units and abs(omvang - units) > OMVANG_TOLERANTIE:
        return False
    return True


def _overname(trade: Trade, match: dict, contract_size: float) -> tuple[dict, str | None]:
    """Wat er aan deze trade moet veranderen om exact met de broker te kloppen.

    Geeft ``(velden, afwijking)``. ``velden`` is leeg als alles al op de cent
    klopt. ``afwijking`` is gevuld als het verschil groter is dan wat
    afronding en koersasymmetrie verklaren: dan wordt er wel overgenomen, maar
    blijft het zichtbaar.

    Het resultaat in dollars komt bij voorkeur uit de prijzen en de omvang van
    de broker: dat is exact. Rijmt dat niet met zijn eurobedrag, dan geldt het
    eurobedrag gedeeld door zijn koers - wat hij boekte, is wat er gebeurde.
    """
    bedrag = float(match["profit_account"])
    koers = float(match["conversion_rate"])
    velden: dict = {}

    units = (trade.volume or 0) * contract_size
    omvang = _omvang(match)
    if omvang is not None and abs(omvang - units) > OMVANG_TOLERANTIE:
        velden["volume"] = round(omvang / contract_size, 6)
        units = omvang

    richting = 1.0 if trade.side == "buy" else -1.0
    instap = match.get("open_price") or trade.open_price
    uit = match["exit_price"]
    usd = None
    if instap is not None and units:
        uit_prijzen = round((uit - instap) * richting * units, 4)
        if abs(uit_prijzen * koers - bedrag) <= CENT_TOLERANTIE:
            usd = uit_prijzen
    if usd is None:
        usd = round(bedrag / koers, 4)

    afwijking = None
    oud_eur = (trade.net_pnl or 0.0) * koers
    if abs(oud_eur - bedrag) > max(0.05, abs(bedrag) * BEDRAG_TOLERANTIE):
        afwijking = (
            f"bedrag {oud_eur:+.2f} tegen {bedrag:+.2f} bij de broker "
            "(overgenomen van de broker)"
        )

    if trade.net_pnl is None or abs(trade.net_pnl - usd) > 0.0005:
        velden["net_pnl"] = usd
        velden["gross_pnl"] = round(usd + (trade.total_cost or 0.0), 4)
    if trade.net_pnl_account is None or abs(trade.net_pnl_account - bedrag) > 0.0005:
        velden["net_pnl_account"] = bedrag
    if trade.fx_rate is None or abs(trade.fx_rate - koers) > 1e-9:
        velden["fx_rate"] = koers
    if trade.fx_source != "broker_settlement" and velden:
        velden["fx_source"] = "broker_settlement"
    return velden, afwijking


def _omvang(match: dict) -> float | None:
    """De omvang zoals de broker hem afrekende, in ounce, zonder teken."""
    omvang = match.get("size")
    if omvang is None:
        return None
    try:
        return abs(float(omvang))
    except (TypeError, ValueError):
        return None
