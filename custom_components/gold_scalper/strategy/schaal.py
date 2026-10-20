"""Prijs- en eenheidsschaal per instrument (2.17.0, Bitvavo).

Gold Scalper is gebouwd en gekalibreerd op goud: vaste afstanden in USD per
ounce (een minimale stop van 1 USD, break-even na 0,6 USD, slippage 0,02),
afronding van koersen op twee of drie decimalen, en orders van minstens 1 oz
in stappen van 0,1. Bij goud rond 4000 USD kloppen die getallen. Bij crypto
niet: bitcoin staat rond 90.000 euro, sommige munten op 0,00001 euro.

In plaats van elk getal per instrument te herschrijven, rekent deze module ze
om met één factor: ``prijs = koers / REF_PRIJS``. Een afstand van 1 USD bij
goud (1/4000 = 0,025 %) wordt bij een munt van 90.000 euro 22,5 euro - dezelfde
verhouding tot de koers. Eenheden komen van de exchange: de kleinste stap en
de kleinste order. Kosten als percentage (``tarief`` per zijde) komen bij de
vaste kosten per lot.

De schaal staat in een ``ContextVar``: elke coordinator zet hem aan het begin
van zijn eigen cyclus, en alles wat daarbinnen draait leest hem. Voor goud
wordt niets gezet en geldt ``GOUD``: alle functies geven dan exact wat ze
vóór 2.17.0 gaven (factor 1,0, ``round`` zoals het stond, 0,1 oz-stappen).
"""

from __future__ import annotations

import math
from contextvars import ContextVar
from dataclasses import dataclass

#: De koers waarop de vaste afstanden gekalibreerd zijn (goud, USD/oz).
REF_PRIJS = 4000.0
#: Significante cijfers voor koersen als de schaal actief is.
SIGNIFICANT = 8


@dataclass(frozen=True, slots=True)
class Schaal:
    #: Factor op absolute koersafstanden (bij goud 1,0).
    prijs: float = 1.0
    #: Kleinste stap in units; None = zoals bij goud.
    eenheid_stap: float | None = None
    #: Kleinste order in units; None = zoals bij goud (1 oz).
    min_eenheden: float | None = None
    #: Kosten per zijde als fractie van het bedrag (bijv. 0,0025).
    tarief: float = 0.0
    #: Spot: geen hefboom en geen short.
    spot: bool = False

    @property
    def is_goud(self) -> bool:
        return self.prijs == 1.0 and self.eenheid_stap is None and not self.spot and not self.tarief


GOUD = Schaal()
_huidig: ContextVar[Schaal] = ContextVar("gold_scalper_schaal", default=GOUD)


def huidig() -> Schaal:
    return _huidig.get()


def zet(schaal: Schaal):
    """Zet de schaal voor de lopende taak (en alles wat eruit voortkomt).

    Geeft een token terug; ``terug(token)`` herstelt de vorige schaal. Wie
    meerdere coordinators in één taak aanroept (de diensten), moet dat doen,
    anders erft de volgende coordinator de schaal van de vorige.
    """
    return _huidig.set(schaal)


def terug(token) -> None:
    try:
        _huidig.reset(token)
    except (ValueError, RuntimeError):   # token uit een andere context
        _huidig.set(GOUD)


def voor_markt(koers: float, eenheid_stap: float | None, min_eenheden: float | None,
               tarief: float, spot: bool = True) -> Schaal:
    factor = float(koers) / REF_PRIJS if koers and koers > 0 else 1.0
    return Schaal(prijs=factor, eenheid_stap=eenheid_stap or None,
                  min_eenheden=min_eenheden if min_eenheden and min_eenheden > 0 else None,
                  tarief=max(0.0, float(tarief or 0.0)), spot=spot)


def usd(bedrag: float) -> float:
    """Een vaste koersafstand (gekalibreerd in USD/oz bij goud) voor dit instrument."""
    return bedrag * _huidig.get().prijs


def rond_prijs(waarde, decimalen: int):
    """Een koers afronden: bij goud ``round(waarde, decimalen)`` zoals altijd,
    anders op ``SIGNIFICANT`` significante cijfers (0,00001234 blijft heel)."""
    if waarde is None:
        return None
    s = _huidig.get()
    if s.is_goud:
        return round(waarde, decimalen)
    if not waarde or not math.isfinite(waarde):
        return waarde
    return float(f"{waarde:.{SIGNIFICANT}g}")


def stap(standaard: float) -> float:
    s = _huidig.get()
    return s.eenheid_stap if s.eenheid_stap else standaard


def min_eenheden(standaard: float) -> float:
    s = _huidig.get()
    return s.min_eenheden if s.min_eenheden else standaard


def _decimalen(stapgrootte: float) -> int:
    if stapgrootte >= 1:
        return 0
    return max(0, min(12, int(round(-math.log10(stapgrootte)))))


def omlaag(units: float, standaard_stap: float) -> float:
    """Naar beneden op de eenheidsstap (bij goud ``floor(x * 10) / 10`` voor 0,1)."""
    st = stap(standaard_stap)
    if _huidig.get().eenheid_stap is None:
        return math.floor(units / st) * st if st != 0.1 else math.floor(units * 10) / 10
    return round(math.floor(units / st + 1e-9) * st, _decimalen(st))


def rond_units(units: float, decimalen: int) -> float:
    """Bij goud ``round(units, decimalen)``; anders naar beneden op de stap."""
    s = _huidig.get()
    if s.eenheid_stap is None:
        return round(units, decimalen)
    return omlaag(units, s.eenheid_stap)


def commissie_rondreis_per_unit(koers: float | None) -> float:
    """Procentuele kosten van in- en uitstappen per unit, in koersvaluta."""
    s = _huidig.get()
    if not s.tarief or not koers:
        return 0.0
    return 2.0 * s.tarief * float(koers)


def gesloten_drempel(standaard: float = 0.005) -> float:
    """Onder welke omvang een positie als gesloten geldt."""
    s = _huidig.get()
    if s.eenheid_stap:
        return s.eenheid_stap / 2.0
    return standaard
