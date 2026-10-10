"""Sluitredenen op bewijs, en exitstatistiek met teller en noemer.

Bij een correctie werd de sluitreden overschreven met
``broker_gesloten_gecorrigeerd``. Of de positie op zijn stop of zijn doel
sloot, ging daarbij verloren - en de gemelde 14,6% doeltreffers was daardoor
een ondergrens zonder dat het rapport dat zei.

Twee regels:

* De **oorspronkelijke** sluitreden wordt nooit overschreven. Een afstemming
  schrijft naar eigen velden.
* Een stop- of doeltreffer wordt alleen afgeleid met **bewijs**. Zonder bewijs
  is de reden ``unknown``, en dat telt apart mee in plaats van weggemoffeld.

Bewijs:

* **doeltreffer**: de uitstapprijs van de broker ligt binnen
  ``PRIJS_BEWIJS`` van het doelniveau. Het doel wordt door deze integratie
  nooit verplaatst, dus het niveau in de database is het niveau bij de broker.
* **stoptreffer**: idem voor de stop, maar alleen als de stop in de database
  betrouwbaar is. Tot versie 5.3.3 werd een verplaatste stop (break-even,
  trailing) niet teruggeschreven; voor die trades kan de stop in de database
  verouderd zijn, en dan is een prijsmatch geen bewijs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

#: Afstand tussen uitstapprijs en niveau die als bewijs geldt.
PRIJS_BEWIJS = 0.01

#: Sluitredenen van het eigen exitbeheer: die zijn door deze integratie zelf
#: genomen en dus bekend.
EIGEN_EXITS = {
    "timeout", "time_stop", "trailing", "break_even", "breakeven",
    "partial_close", "close_all", "drain", "handmatig", "exit",
    # 1.10.0: vaste soorten (zie ``sluitreden.py``).
    "tijdslimiet", "max_duur", "eigen_exit",
}


@dataclass(slots=True)
class AfgeleideReden:
    reden: str            # take_profit / stop_loss / unknown
    bron: str             # reconciled_price_match / none
    bewijs: str

    def as_dict(self) -> dict:
        return {"reden": self.reden, "bron": self.bron, "bewijs": self.bewijs}


def derive_close_reason(
    exit_price: float | None,
    take_profit: float | None,
    stop_loss: float | None,
    stop_trusted: bool,
) -> AfgeleideReden:
    """Leid een sluitreden af uit de uitstapprijs van de broker - of niet."""
    if exit_price is None:
        return AfgeleideReden("unknown", "none", "geen uitstapprijs van de broker")

    if take_profit is not None and abs(exit_price - take_profit) <= PRIJS_BEWIJS:
        return AfgeleideReden(
            "take_profit", "reconciled_price_match",
            f"uitstap {exit_price} binnen {PRIJS_BEWIJS} van doel {take_profit}",
        )

    if stop_loss is not None and abs(exit_price - stop_loss) <= PRIJS_BEWIJS:
        if stop_trusted:
            return AfgeleideReden(
                "stop_loss", "reconciled_price_match",
                f"uitstap {exit_price} binnen {PRIJS_BEWIJS} van stop {stop_loss}",
            )
        return AfgeleideReden(
            "unknown", "none",
            f"uitstap {exit_price} ligt op de stop {stop_loss}, maar die stop "
            "kan verouderd zijn (van vóór het terugschrijven van verplaatste "
            "stops); geen bewijs",
        )

    return AfgeleideReden(
        "unknown", "none",
        f"uitstap {exit_price} ligt niet op doel {take_profit} of stop {stop_loss}",
    )


def effective_reason(trade) -> str:
    """De sluitreden waarop statistiek rust.

    Een afgeleide reden heeft voorrang als er een is; anders de oorspronkelijke.
    Labels die alleen zeggen wie sloot - de broker - tellen als onbekend.
    """
    afgeleid = getattr(trade, "reconciled_close_reason", None)
    if afgeleid:
        return afgeleid
    oorspronkelijk = (
        getattr(trade, "original_close_reason", None)
        or getattr(trade, "close_reason", None)
        or ""
    )
    if oorspronkelijk.startswith("broker_gesloten") or oorspronkelijk in ("", "unknown"):
        return "unknown"
    return oorspronkelijk


def exit_stats(trades: Sequence) -> dict:
    """Doeltreffers, stoptreffers, eigen exits en onbekend - met teller en noemer.

    De noemer is altijd het aantal gesloten trades. Het onbekende deel staat
    ernaast: een doeltrefferpercentage zonder dat getal zegt niet hoeveel het
    ondergrens is.
    """
    gesloten = [t for t in trades if getattr(t, "close_time", None)]
    noemer = len(gesloten)
    telling = {"take_profit": 0, "stop_loss": 0, "eigen_exit": 0, "unknown": 0}
    afgestemd = 0
    achteraf = 0
    for t in gesloten:
        reden = effective_reason(t)
        if getattr(t, "reconciliation_status", None) == "reconciled":
            afgestemd += 1
        # 1.10.0: reden achteraf uit de afstemming ingevuld.
        if getattr(t, "close_reason_source", None) == "afstemming":
            achteraf += 1
        if reden == "take_profit":
            telling["take_profit"] += 1
        elif reden == "stop_loss":
            telling["stop_loss"] += 1
        elif reden == "unknown":
            telling["unknown"] += 1
        else:
            telling["eigen_exit"] += 1

    def deel(n):
        return round(n / noemer * 100, 1) if noemer else 0.0

    return {
        "noemer": noemer,
        "afgestemd": afgestemd,
        "achteraf_ingevuld": achteraf,
        **{
            soort: {"n": n, "pct": deel(n)}
            for soort, n in telling.items()
        },
        "toelichting": (
            f"Van {noemer} gesloten trades is bij {telling['unknown']} de "
            "sluitreden niet te bewijzen. Het doeltreffer- en "
            "stoptrefferpercentage zijn daarom ondergrenzen."
            if telling["unknown"] else
            f"Alle {noemer} sluitredenen zijn bekend of bewezen."
        ),
    }
