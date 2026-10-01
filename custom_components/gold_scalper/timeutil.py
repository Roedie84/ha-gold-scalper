"""Eén definitie van tijd en handelsdag voor de hele integratie.

Er waren drie definities van "een dag": het periodeoverzicht rekende in
Amsterdamse tijd, de dagcijfers, het rapport en de live-poort in UTC, en de
risicodag ook in UTC. Trades die tussen 22:00 en 24:00 UTC sloten, vielen
daardoor in het ene overzicht op de ene dag en in het andere op de volgende. De
live-poort telde handelsdagen en de beste-dagtoets op een andere dag dan het
rapport liet zien.

Regels:

* Tijden worden **in UTC** opgeslagen.
* Europe/Amsterdam wordt **alleen** gebruikt om de handelsdag af te leiden.
* Een tijd zonder tijdzone wordt geweigerd, behalve bij het lezen uit de
  database: die schrijft altijd UTC, en ``parse_utc`` maakt dat expliciet.

Sessies (Azië, Londen, New York) staan hier bewust buiten: dat zijn beursuren in
UTC, geen kalenderdag.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

#: De tijdzone waarin een handelsdag begint en eindigt. De dagelijkse
#: onderbreking van goud (23:00-24:00 lokaal) valt zo samen met de dagwissel.
TRADING_TZ = ZoneInfo("Europe/Amsterdam")


def parse_utc(waarde) -> datetime:
    """Een opgeslagen tijd als tijdzonebewuste UTC-datetime.

    De database schrijft UTC. Een tijd zonder tijdzone uit de database is dus
    UTC; dat wordt hier expliciet gemaakt in plaats van stilzwijgend
    aangenomen op elke plek.
    """
    if isinstance(waarde, datetime):
        moment = waarde
    else:
        moment = datetime.fromisoformat(str(waarde))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def trading_day(moment: datetime) -> date:
    """De handelsdag waarop dit moment valt.

    Weigert een tijd zonder tijdzone: dan is niet te weten welke dag bedoeld
    is, en raden was precies hoe de drie definities ontstonden.
    """
    if not isinstance(moment, datetime):
        raise TypeError("trading_day verwacht een datetime")
    if moment.tzinfo is None:
        raise ValueError(
            "trading_day weigert een tijd zonder tijdzone; gebruik parse_utc "
            "voor waarden uit de database"
        )
    return moment.astimezone(TRADING_TZ).date()


def trading_day_of(opgeslagen) -> date:
    """Handelsdag van een opgeslagen tijd (UTC-tekst uit de database)."""
    return trading_day(parse_utc(opgeslagen))


def local(moment: datetime) -> datetime:
    """Een tijdzonebewust moment in de handelstijdzone, voor weergave."""
    if moment.tzinfo is None:
        raise ValueError("local weigert een tijd zonder tijdzone")
    return moment.astimezone(TRADING_TZ)
