"""Bekende handelstijden voor goud, als onafhankelijke controle.

De integratie leunt op het veld ``marketState`` dat de broker meestuurt. Dat
werkt, maar het is één bron: klopt dat veld niet, dan handelt de bot op
verouderde koersen zonder dat iets het merkt. Een tweede, onafhankelijke bron
maakt dat zichtbaar.

**Bij onenigheid wint 'gesloten'.** Zegt de broker open en het rooster dicht, of
andersom, dan wordt er niet gehandeld. Dat is niet uit voorzichtigheid maar uit
rekenkunde: een gemiste kans kost je niets, handelen op een koers van uren
geleden kan je alles kosten.

**Het rooster is geen waarheid.** Feestdagen, vervroegde sluitingen en
uitzonderingen staan er niet in, en tijden veranderen zonder aankondiging. Het
dient dus als *vangnet* en niet als vervanging - vandaar dat een afwijking
gemeld wordt in plaats van stil gecorrigeerd. Blijft die afwijking bestaan, dan
klopt het rooster niet meer en moet het bijgesteld.

Elk rooster rekent in zijn eigen tijdzone (``Session.tz``). Spot goud volgt
de Amerikaanse markt en staat sinds 2.25.0 (L-GS-031) in America/New_York:
week open zondag 18:00, dagpauze 17:00-18:00, week dicht vrijdag 17:00. Zo
schuift het rooster mee met de Amerikaanse zomertijd; in de weken waarin
Europa en de VS niet tegelijk omschakelen (~3 weken in maart, ~1 week eind
oktober) valt de pauze een uur eerder in Nederlandse tijd (22:00-23:00).
Meldingen tonen de tijden in Europe/Amsterdam, want zo kijk jij ernaar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_LOGGER = logging.getLogger(__name__)

MARKET_TZ = ZoneInfo("Europe/Amsterdam")
#: 2.25.0 (L-GS-031): de tijdzone van de Amerikaanse goudmarkt.
NEW_YORK_TZ = ZoneInfo("America/New_York")

_DAG_S = 86400
_WEEK_S = 7 * _DAG_S

#: Zo dicht bij een opening of sluiting is een verschil tussen broker en
#: rooster een klokrand, geen afwijking om te melden (1.7.10).
ROOSTERGRENS_MARGE_S = 15


@dataclass(slots=True)
class Session:
    """Wanneer een instrument volgens het rooster open is."""

    name: str
    #: Weekdag en tijd waarop de week opent (0 = maandag).
    opens_weekday: int
    opens_at: time
    #: Weekdag en tijd waarop de week sluit.
    closes_weekday: int
    closes_at: time
    #: Dagelijkse onderbreking (begin, einde; het einde is het eerste moment
    #: dat de markt weer open is), of None.
    daily_break: tuple[time, time] | None = None
    #: 2.25.0: de tijdzone waarin de tijden hierboven gelden.
    tz: ZoneInfo = MARKET_TZ


#: Spot goud bij IG: zondag 18:00 tot vrijdag 17:00 New Yorkse tijd, met een
#: dagelijkse pauze van 17:00 tot 18:00 New York.
#:
#: Tot 2.24.3 stond dit vast in Nederlandse tijd (maandag 00:00 tot vrijdag
#: 23:00, pauze 23:00-24:00). Dat klopt alleen als Europa en de VS allebei
#: zomer- of allebei wintertijd hebben. Gemeten 24-26/10 (L-GS-031, 3 van 3
#: avonden): beide brokers dicht 22:00 en weer open 23:01 CET (= 17:00-18:00
#: New York; de VS houden zomertijd tot 1-11). Het oude rooster hield IG dan
#: tot 24:00 dicht terwijl Pepperstone om 23:01 weer handelde.
#:
#: Het rooster blijft een *vermoeden*, geen waarheid: feestdagen en vervroegde
#: sluitingen staan er niet in, en bij onenigheid wint altijd 'gesloten', dus
#: er wordt nooit tegen de broker in gehandeld. Het dient om te merken wanneer
#: het veld ``marketState`` zelf niet deugt; zie ook ``observed_closures``.
SPOT_GOLD = Session(
    name="spot goud",
    opens_weekday=6, opens_at=time(18, 0),
    closes_weekday=4, closes_at=time(17, 0),
    daily_break=(time(17, 0), time(18, 0)),
    tz=NEW_YORK_TZ,
)

#: Weekendhandel bij IG: zaterdag 09:00 tot zondag 23:40. Een apart instrument
#: met een veel bredere spread; alleen relevant als je daar bewust op handelt.
WEEKEND_GOLD = Session(
    name="weekend goud",
    opens_weekday=5, opens_at=time(9, 0),
    closes_weekday=6, closes_at=time(23, 40),
)


def _week_seconde(weekday: int, klok: time) -> int:
    return weekday * _DAG_S + klok.hour * 3600 + klok.minute * 60 + klok.second


def _lokaal(session: Session, moment: datetime, klok: time, dagen: int = 0) -> str:
    """Een tijd van het rooster (in ``session.tz``) als Nederlandse kloktijd,
    op de dag van ``moment`` (in ``session.tz``) plus ``dagen``."""
    dag = moment.astimezone(session.tz).date() + timedelta(days=dagen)
    lokaal = datetime.combine(dag, klok, tzinfo=session.tz).astimezone(MARKET_TZ)
    return f"{lokaal:%H:%M}"


def _in_pauze(session: Session, klok: time) -> bool:
    if not session.daily_break:
        return False
    start, eind = session.daily_break
    if start < eind:
        return start <= klok < eind
    # Over middernacht heen (bijv. 23:00 tot 00:00).
    return klok >= start or klok < eind


def is_open(session: Session, moment: datetime | None = None) -> tuple[bool, str]:
    """Zou de markt volgens het rooster open moeten zijn?

    2.25.0: gerekend in de tijdzone van het rooster (spot goud: New York), de
    reden noemt de Nederlandse kloktijden.
    """
    moment = (moment or datetime.now(timezone.utc)).astimezone(session.tz)
    weekday = moment.weekday()
    # 1.7.10: hele seconden. Om 23:59:59,06 zei het rooster 'open' terwijl de
    # broker (terecht) nog dicht was - elke nacht een valse waarschuwing
    # (leerronde 9 oktober). Het einde van de pauze is het eerste open moment.
    clock = moment.time().replace(microsecond=0)
    pos = _week_seconde(weekday, clock)
    opent = _week_seconde(session.opens_weekday, session.opens_at)
    sluit = _week_seconde(session.closes_weekday, session.closes_at)

    if opent <= sluit:
        in_week = opent <= pos < sluit
    else:
        # Loopt over het einde van de week (zondag tot vrijdag in New York,
        # of zaterdag tot zondag).
        in_week = pos >= opent or pos < sluit
    if not in_week:
        if weekday == session.closes_weekday and clock >= session.closes_at:
            return False, f"gesloten sinds {_lokaal(session, moment, session.closes_at)}"
        if weekday == session.opens_weekday and clock < session.opens_at:
            return False, f"opent om {_lokaal(session, moment, session.opens_at)}"
        return False, "buiten de handelsweek"

    if _in_pauze(session, clock):
        start, eind = session.daily_break
        extra = 1 if eind <= start and clock >= start else 0
        return False, (
            f"dagelijkse onderbreking van {_lokaal(session, moment, start, 0 if clock >= start else -1)} "
            f"tot {_lokaal(session, moment, eind, extra)}"
        )
    return True, "binnen de handelstijden"


def _seconden_tot_sluiting(session: Session, moment: datetime) -> tuple[float | None, float | None]:
    """(tot de eerstvolgende sluiting, tot de weeksluiting) in seconden vanaf
    ``moment`` (in ``session.tz``); de eerste is de pauze of de weeksluiting,
    wat het eerst komt. Alleen zinvol als de markt open is."""
    lokaal = moment.astimezone(session.tz)
    pos = _week_seconde(lokaal.weekday(), lokaal.time()) + lokaal.microsecond / 1e6
    sluit = _week_seconde(session.closes_weekday, session.closes_at)
    tot_week = (sluit - pos) % _WEEK_S
    kandidaten = [tot_week] if tot_week > 0 else []
    if session.daily_break:
        start = session.daily_break[0]
        start_s = start.hour * 3600 + start.minute * 60 + start.second
        dag_s = pos % _DAG_S
        tot_pauze = (start_s - dag_s) % _DAG_S
        if tot_pauze > 0:
            kandidaten.append(tot_pauze)
    return (min(kandidaten) if kandidaten else None), (tot_week if tot_week > 0 else None)


def bij_roostergrens(
    session: Session, moment: datetime | None = None, marge_s: float = ROOSTERGRENS_MARGE_S
) -> bool:
    """Ligt `moment` binnen `marge_s` seconden van een opening of sluiting
    volgens het rooster (1.7.10)?

    Op de grens zelf lopen onze klok en die van de broker een fractie uiteen:
    om 22:59:59 meldde de broker al gesloten. Dat is geen feestdag en geen
    verouderd rooster, alleen een klokrand. Bedoeld om de melding dan stil te
    houden; wat er gehandeld mag worden verandert niet.
    """
    moment = moment or datetime.now(timezone.utc)
    marge = timedelta(seconds=marge_s)
    voor, _ = is_open(session, moment - marge)
    na, _ = is_open(session, moment + marge)
    return voor != na


def minutes_until_close(
    session: Session, moment: datetime | None = None
) -> float | None:
    """Hoeveel minuten tot de eerstvolgende sluiting, of None als hij dicht is.

    Bedoeld om te voorkomen dat er kort voor sluiting nog een positie opengaat.
    Een trade met een tijdslimiet van vijf minuten die om 22:58 opengaat, wordt
    door de sluiting overvallen: je zit dan met een positie in een markt die
    niet meer beweegt en pas de volgende sessie weer opent - met een gat.

    2.25.0: gerekend in de tijdzone van het rooster (dagpauze of weeksluiting,
    wat het eerst komt).
    """
    moment = moment or datetime.now(timezone.utc)
    open_now, _ = is_open(session, moment)
    if not open_now:
        return None
    eerst, _week = _seconden_tot_sluiting(session, moment)
    return eerst / 60.0 if eerst is not None else None


#: 2.22.0: een sluiting met minstens zoveel uur tot de volgende opening is een
#: weekendsluiting (de dagpauze van een paar minuten tot een uur is dat niet).
WEEKENDGAT_UUR = 6


def minuten_tot_weekendsluiting(
    session: Session, moment: datetime | None = None
) -> float | None:
    """2.22.0: minuten tot de sluiting van de handelsweek, of None.

    Alleen op de sluitdag van de week (in de tijdzone van het rooster) en
    zolang de markt open is; de dagelijkse onderbreking telt niet. 2.25.0:
    spot goud sluit vrijdag 17:00 New York, dus 23:00 CET normaal en 22:00 CET
    in de week waarin de VS nog zomertijd hebben (vr 30-10-2026). De grendels
    van 2.22.0 (geen instap in het laatste uur, sluiten vanaf 30 minuten
    ervoor) schuiven daarmee vanzelf mee.
    """
    moment = moment or datetime.now(timezone.utc)
    open_now, _ = is_open(session, moment)
    if not open_now:
        return None
    if moment.astimezone(session.tz).weekday() != session.closes_weekday:
        return None
    _eerst, tot_week = _seconden_tot_sluiting(session, moment)
    if tot_week is None or tot_week >= _DAG_S:
        return None
    return tot_week / 60.0


def cross_check(
    broker_says_open: bool,
    session: Session = SPOT_GOLD,
    moment: datetime | None = None,
) -> tuple[bool, str | None]:
    """Vergelijk wat de broker zegt met het rooster.

    Geeft terug of er gehandeld mag worden, plus een melding als de twee het
    oneens zijn. Bij onenigheid wint altijd 'gesloten': een gemiste kans kost
    je niets, handelen op een koers van uren geleden kan je alles kosten.
    """
    schedule_open, reason = is_open(session, moment)

    if broker_says_open == schedule_open:
        return schedule_open, None

    if broker_says_open and not schedule_open:
        return False, (
            f"De broker meldt de markt open, maar volgens het rooster is hij "
            f"dicht ({reason}). Er wordt niet gehandeld. Klopt dit vaker, dan "
            "is het rooster verouderd en moet het bijgesteld."
        )

    # De broker weet het beter dan het rooster.
    #
    # Feestdagen en vervroegde sluitingen staan hier niet in, en een kalender
    # bijhouden zou betekenen dat je hem elk jaar moet onderhouden - met als
    # risico dat een vergeten dag je op verouderde koersen laat handelen.
    #
    # Andersom is het rooster wél nuttig: als de broker "open" zegt terwijl het
    # rooster dicht zegt, is er iets mis met het veld en wil je dat weten.
    return False, (
        f"De broker meldt de markt gesloten terwijl het rooster hem open zegt "
        f"({reason}). Vrijwel altijd een feestdag of vervroegde sluiting - de "
        "Amerikaanse kalender staat niet in het rooster. De broker heeft "
        "gelijk; er wordt niet gehandeld."
    )


@dataclass(slots=True)
class ClosureObservation:
    """Wanneer de broker de markt werkelijk gesloten meldde.

    Bestaat omdat het rooster een vermoeden is en de waarneming niet. Twee
    bronnen geven verschillende tijden voor spot goud bij IG, en welke klopt
    valt van buitenaf niet vast te stellen. Wat je wél kunt doen is bijhouden
    wanneer de broker sluit, en het rooster daarna bijstellen op grond van wat
    er werkelijk gebeurde.

    Bewust alleen waarnemen, niet automatisch aanpassen: een rooster dat
    zichzelf bijstelt op grond van een storing bij de broker, sluit je uit van
    een markt die gewoon open is.
    """

    #: Per uur van de dag (lokale tijd) hoe vaak de broker gesloten meldde.
    closed_by_hour: dict = field(default_factory=dict)
    #: Per uur hoe vaak er überhaupt gekeken is.
    seen_by_hour: dict = field(default_factory=dict)

    def record(self, moment: datetime, broker_says_open: bool) -> None:
        hour = moment.astimezone(MARKET_TZ).hour
        self.seen_by_hour[hour] = self.seen_by_hour.get(hour, 0) + 1
        if not broker_says_open:
            self.closed_by_hour[hour] = self.closed_by_hour.get(hour, 0) + 1

    def export(self) -> dict:
        """De ruwe tellingen, om over een herstart heen te bewaren (1.7.5)."""
        return {
            "closed_by_hour": {str(h): n for h, n in self.closed_by_hour.items()},
            "seen_by_hour": {str(h): n for h, n in self.seen_by_hour.items()},
        }

    def restore(self, data: dict | None) -> None:
        """Bewaarde tellingen terugzetten; onleesbare regels overslaan.

        JSON kent alleen tekst als sleutel, dus de uren komen als tekst terug
        en worden hier weer getallen - anders telde hetzelfde uur dubbel.
        """
        if not isinstance(data, dict):
            return
        for veld in ("closed_by_hour", "seen_by_hour"):
            doel = getattr(self, veld)
            for uur, aantal in (data.get(veld) or {}).items():
                try:
                    h, n = int(uur), int(aantal)
                except (TypeError, ValueError):
                    continue
                if 0 <= h <= 23 and n >= 0:
                    doel[h] = doel.get(h, 0) + n

    def as_dict(self) -> dict:
        """Per uur het aandeel waarnemingen waarin de markt dicht was.

        Uren met minder dan twintig waarnemingen blijven weg: daaronder zegt
        een percentage niets.
        """
        uren = {}
        for hour, seen in sorted(self.seen_by_hour.items()):
            if seen < 20:
                continue
            closed = self.closed_by_hour.get(hour, 0)
            uren[hour] = {
                "waarnemingen": seen,
                "dicht": closed,
                "aandeel": round(closed / seen, 3),
            }
        return uren

    def suggest_break(self) -> str | None:
        """Welke uren zijn structureel dicht volgens de waarneming?"""
        data = self.as_dict()
        if not data:
            return None
        dicht = [h for h, v in data.items() if v["aandeel"] > 0.8]
        if not dicht:
            return None
        return (
            "Volgens de waarneming is de markt structureel gesloten in de uren "
            + ", ".join(f"{h:02d}:00" for h in sorted(dicht))
            + " (lokale tijd). Wijkt dat af van het rooster, dan is het "
            "rooster verouderd."
        )
