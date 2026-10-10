"""Sluitredenen als vaste soort, en achteraf invullen uit de broker (1.10.0).

**Groeperen.** Het exitbeheer gaf de sluitreden als vrije tekst mee, met de
looptijd erin: "na 243s nog binnen 0.3xATR van het instappunt; geen scalp
me". Elke looptijd werd zo een eigen reden - op 10-10 zestien verschillende
voor in wezen twee soorten. :func:`normaliseer` maakt er een vaste soort van
(``tijdslimiet``, ``max_duur``) en zet de looptijd apart in ``looptijd_s``.
De database doet dat bij elke opslag en bij het openen voor de historie.

**Achteraf invullen.** Een trade die sloot terwijl Home Assistant herstartte,
werd later door de broker afgewikkeld zonder dat bekend was waarom hij sloot:
sluitreden onbekend. Het activiteitenoverzicht van de broker zegt wél wie
sloot (``channel``): het systeem van de broker (stop of doel), deze
integratie via de API, of iemand met de hand. :func:`reden_uit_broker` leidt
daaruit een reden af, zo goed als die gegevens het toelaten, met het bewijs
erbij. Alleen lezen: hier wordt niets bij de broker gedaan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .exit_stats import PRIJS_BEWIJS

#: Tijdstop van het exitbeheer: na de tijdstop nog in de dode zone.
TIJDSLIMIET = "tijdslimiet"
#: Harde bovengrens op de positieduur.
MAX_DUUR = "max_duur"

#: Bron van een achteraf ingevulde reden (veld ``close_reason_source``).
BRON_AFSTEMMING = "afstemming"

_TIJDSTOP = re.compile(r"^na\s+(\d+(?:\.\d+)?)\s*s\b.*\bbinnen\b", re.IGNORECASE)
_MAX_DUUR = re.compile(
    r"^maximale positieduur van\s+(\d+(?:\.\d+)?)\s*s", re.IGNORECASE
)

#: Kanalen van IG: wie de sluiting deed.
_KANAAL_API = {"PUBLIC_WEB_API", "PUBLIC_FIX_API"}
_KANAAL_HAND = {"WEB", "MOBILE", "DEALER"}
_KANAAL_SYSTEEM = {"SYSTEM"}



def normaliseer(reden: str | None) -> tuple[str | None, int | None]:
    """``(soort, looptijd_s)`` voor een sluitreden.

    Een vaste reden ("stop_loss", "handmatig", ...) blijft zoals hij is, met
    looptijd None. Idempotent: een soort normaliseert naar zichzelf.
    """
    if reden is None:
        return None, None
    tekst = str(reden).strip()
    m = _TIJDSTOP.match(tekst)
    if m:
        return TIJDSLIMIET, int(round(float(m.group(1))))
    m = _MAX_DUUR.match(tekst)
    if m:
        return MAX_DUUR, int(round(float(m.group(1))))
    return tekst, None


def normaliseer_trade(trade) -> None:
    """Sluitreden van een trade (of rij) in place normaliseren.

    ``close_reason`` en ``original_close_reason`` worden de soort; de looptijd
    uit de tekst komt in ``looptijd_s`` als die nog leeg is.
    """
    looptijd = None
    for veld in ("close_reason", "original_close_reason"):
        waarde = getattr(trade, veld, None)
        if not waarde:
            continue
        soort, s = normaliseer(waarde)
        if soort != waarde:
            setattr(trade, veld, soort)
        if s is not None and looptijd is None:
            looptijd = s
    if looptijd is not None and getattr(trade, "looptijd_s", None) is None:
        trade.looptijd_s = looptijd


@dataclass(slots=True)
class BrokerReden:
    reden: str
    bewijs: str
    bron: str = BRON_AFSTEMMING


def _utc(waarde) -> datetime | None:
    if not waarde:
        return None
    if isinstance(waarde, datetime):
        m = waarde
    else:
        try:
            m = datetime.fromisoformat(str(waarde).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return m if m.tzinfo else m.replace(tzinfo=timezone.utc)


def looptijd_van(trade, gesloten=None) -> int | None:
    """Looptijd in seconden: instap tot sluiting (broker of eigen boeking)."""
    begin = _utc(getattr(trade, "open_time", None))
    eind = _utc(gesloten) or _utc(getattr(trade, "close_time", None))
    if begin is None or eind is None:
        return None
    s = (eind - begin).total_seconds()
    return int(round(s)) if s >= 0 else None


def reden_uit_broker(
    trade,
    uitstap: float | None,
    activiteit: dict | None,
    tijdstop_s: float | None,
    max_duur_s: float | None,
    gesloten=None,
) -> BrokerReden | None:
    """Sluitreden uit wat de broker weet, of None als dat niet volstaat.

    Volgorde, van sterk naar zwak bewijs:

    1. uitstap op het doel (binnen een cent): ``take_profit``;
    2. door het systeem van de broker gesloten en uitstap op de stop:
       ``stop_loss`` (het systeem sloot, dus de stop - ook als die in de
       database van vóór het terugschrijven van verplaatste stops is);
    3. door het systeem gesloten, niet op het doel: ``stop_loss`` - een
       (verplaatste) stop; het doel staat vast en is dan uitgesloten;
    4. via de API gesloten, dus door deze integratie: ``max_duur`` of
       ``tijdslimiet`` als de looptijd die grens haalde, anders ``eigen_exit``;
    5. met de hand gesloten (web, mobiel, dealer): ``handmatig``.

    Zonder activiteit alleen regel 1: een prijs op de stop is zonder kanaal
    geen bewijs (de stop kan verouderd zijn).

    ``gesloten`` is het sluitmoment van de broker (``dateUtc`` uit het
    transactieoverzicht) als dat er is; anders het moment van de activiteit,
    en anders de eigen boeking.
    """
    doel = getattr(trade, "take_profit", None)
    stop = getattr(trade, "stop_loss", None)
    if uitstap is not None and doel is not None and abs(uitstap - doel) <= PRIJS_BEWIJS:
        return BrokerReden(
            "take_profit",
            f"uitstap {uitstap} binnen {PRIJS_BEWIJS} van doel {doel} "
            "(achteraf uit de afstemming)",
        )
    if not activiteit:
        return None
    kanaal = str(activiteit.get("channel") or "").upper()
    if not kanaal:
        return None
    if kanaal in _KANAAL_SYSTEEM:
        if uitstap is not None and stop is not None and abs(uitstap - stop) <= PRIJS_BEWIJS:
            return BrokerReden(
                "stop_loss",
                f"door de broker (SYSTEM) gesloten op {uitstap}, binnen "
                f"{PRIJS_BEWIJS} van stop {stop} (achteraf uit de afstemming)",
            )
        return BrokerReden(
            "stop_loss",
            f"door de broker (SYSTEM) gesloten op {uitstap}, niet op doel "
            f"{doel}: een (verplaatste) stop (achteraf uit de afstemming)",
        )
    if kanaal in _KANAAL_API:
        looptijd = looptijd_van(trade, gesloten or activiteit.get("activity_date"))
        if looptijd is not None and max_duur_s and looptijd >= max_duur_s:
            soort = MAX_DUUR
        elif looptijd is not None and tijdstop_s and looptijd >= tijdstop_s:
            soort = TIJDSLIMIET
        else:
            soort = "eigen_exit"
        return BrokerReden(
            soort,
            f"door deze integratie gesloten ({kanaal}) na "
            f"{looptijd if looptijd is not None else '?'}s "
            "(achteraf uit de afstemming)",
        )
    if kanaal in _KANAAL_HAND:
        return BrokerReden(
            "handmatig",
            f"met de hand gesloten ({kanaal}) (achteraf uit de afstemming)",
        )
    return None
