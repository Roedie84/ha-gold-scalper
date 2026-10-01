"""De ene definitie van handelssessies: Azië, Londen, New York, in UTC.

Een sessie is een blok beursuren in UTC, geen kalenderdag - voor de
handelsdag bestaat ``timeutil.trading_day`` (Europe/Amsterdam). De twee worden
nooit gemengd.

Deze module staat los van de leerlaag, zodat zowel de leerlaag als het
Experiment Lab dezelfde definitie gebruiken. ``learning/sessions.py``
importeert de tabel en de functie hiervandaan; het gedrag is ongewijzigd.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class Session:
    name: str
    start: time
    end: time
    note: str

    def contains(self, moment: datetime) -> bool:
        klok = moment.astimezone(UTC).time()
        if self.start <= self.end:
            return self.start <= klok < self.end
        return klok >= self.start or klok < self.end


#: De drie sessies, met de grenzen waarop ze in de literatuur worden gesplitst.
SESSIONS = (
    Session(
        "azie", time(23, 0), time(7, 0),
        "Tokio. Overwegend niet-geïnformeerde handel; rustiger, vormt vaak de "
        "openingsrange van de dag.",
    ),
    Session(
        "londen", time(7, 0), time(13, 0),
        "Londen vóór de opening van New York.",
    ),
    Session(
        "newyork", time(13, 0), time(23, 0),
        "New York en de overlap met Londen. Hoogste volatiliteit, en volgens "
        "onderzoek de sessie waarin geïnformeerde handel domineert.",
    ),
)


def session_of(moment: datetime) -> str:
    for sessie in SESSIONS:
        if sessie.contains(moment):
            return sessie.name
    return "onbekend"
