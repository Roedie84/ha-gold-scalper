"""Rekenen met twee valuta zonder ze door elkaar te halen.

Goud noteert in dollars, maar een account kan in euro's staan. Dan meet je je
resultaat in de ene eenheid en je risicolimieten in de andere, en dat gaat mis
op twee plekken:

* **Positiegrootte.** Het budget volgt uit het eigen vermogen in euro's, de
  stopafstand staat in dollars per ounce. Delen zonder omrekenen levert een
  positie op die bij een koers rond 1,08 zo'n acht procent te groot is.
* **Kostenprojectie en resultaat.** Trades worden in dollars geboekt, het
  saldo in euro's. Ze naast elkaar zetten suggereert een nauwkeurigheid die er
  niet is.

**De koers komt van de broker, niet van een externe bron.** IG rekent zelf om
bij het afrekenen, en de koers die hij daarbij hanteert is de enige die
klopt voor jouw rekening. Een tarief van een website erbij halen zou een tweede
waarheid introduceren die net iets anders is.

Zolang die koers niet bekend is, wordt er **niet** omgerekend maar gemeld dat
het niet kan. Een geschatte koers is hier gevaarlijker dan geen koers: hij
maakt een fout onzichtbaar in plaats van zichtbaar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_LOGGER = logging.getLogger(__name__)


#: Een koers is gewoon bruikbaar tot deze leeftijd.
MAX_AGE_NORMAL = timedelta(hours=24)

#: Tijdens een aantoonbare marktsluiting mag hij tot deze leeftijd.
MAX_AGE_CLOSED = timedelta(hours=72)


@dataclass(slots=True)
class Conversion:
    """Hoe je van de instrumentvaluta naar de accountvaluta komt.

    ``rate`` is accountvaluta per eenheid instrumentvaluta (euro per dollar,
    rond 0,87): het midden, voor rapportage.

    ``risk_rate`` is dezelfde verhouding aan de voorzichtige kant, voor de
    positiegrootte. Een budget in euro's gaat naar dollars door te delen door
    deze koers; het kleinste dollarbudget - dus het kleinste risico - komt uit
    de hoogste euro-per-dollar, en dat is de biedkoers van EUR/USD. Het midden
    gebruiken zou het risico kunnen onderschatten.
    """

    instrument: str = "USD"
    account: str = "USD"
    #: Hoeveel accountvaluta één eenheid instrumentvaluta waard is.
    #: Bij USD naar EUR met een koers van 1,08 dollar per euro is dit 0,926.
    rate: float | None = None
    #: Voorzichtige koers voor de positiegrootte; zie hierboven.
    risk_rate: float | None = None
    #: Wanneer de koers gold (niet wanneer hij is opgehaald).
    rate_timestamp: datetime | None = None
    #: ig_instrument / ig_market / broker_settlement / persisted
    rate_source: str | None = None
    #: Waarop de voorzichtige koers voor de positiegrootte rust.
    risk_basis: str | None = None
    #: Meldde de bron bij de laatste ophaling dat de markt gesloten is?
    #: None = onbekend; dan geldt de veilige grens van 24 uur.
    market_closed: bool | None = None

    def age(self, now: datetime) -> timedelta | None:
        if self.rate_timestamp is None:
            return None
        return now - self.rate_timestamp

    def usable_for_entry(self, now: datetime) -> tuple[bool, str]:
        """Mag met deze koers een nieuwe positie worden geopend?

        Alleen nieuwe posities hangen hiervan af. Exitbeheer, afstemming en
        veiligheidsfuncties werken altijd door: een verlopen koers mag een
        bestaande positie nooit onbeheerd laten.
        """
        if not self.needed:
            return True, "geen omrekening nodig"
        if self.rate is None or self.rate <= 0:
            return False, "geen wisselkoers bekend"
        leeftijd = self.age(now)
        if leeftijd is None:
            return False, "leeftijd van de koers onbekend"
        uren = leeftijd.total_seconds() / 3600
        if leeftijd <= MAX_AGE_NORMAL:
            return True, f"koers {uren:.1f} uur oud, binnen 24 uur"
        if leeftijd > MAX_AGE_CLOSED:
            return False, f"koers {uren:.1f} uur oud, ouder dan 72 uur"
        if self.market_closed is True:
            return True, (
                f"koers {uren:.1f} uur oud; de markt is aantoonbaar gesloten, "
                "grens 72 uur"
            )
        return False, (
            f"koers {uren:.1f} uur oud en de markt is niet aantoonbaar "
            "gesloten; grens 24 uur"
        )

    @property
    def needed(self) -> bool:
        return self.instrument.upper() != self.account.upper()

    @property
    def usable(self) -> bool:
        """Kan er betrouwbaar omgerekend worden?"""
        if not self.needed:
            return True
        return self.rate is not None and self.rate > 0

    def to_account(self, amount: float) -> float:
        """Reken een bedrag in instrumentvaluta om naar accountvaluta."""
        if not self.needed:
            return amount
        if not self.usable:
            # Bewust ongewijzigd teruggeven én melden. Stil een geschatte koers
            # gebruiken zou de fout onzichtbaar maken.
            return amount
        return amount * (self.rate or 1.0)

    def to_instrument(self, amount: float) -> float:
        """Reken een bedrag in accountvaluta om naar instrumentvaluta.

        Dit is de richting die de positiegrootte nodig heeft: een risicobudget
        in euro's moet naar dollars voordat je het door een stopafstand in
        dollars per ounce deelt.
        """
        if not self.needed:
            return amount
        if not self.usable:
            return amount
        return amount / (self.rate or 1.0)

    def note(self) -> str | None:
        """Waarschuwing als er omgerekend moet worden maar dat niet kan."""
        if not self.needed:
            return None
        if self.usable:
            return None
        return (
            f"Het instrument noteert in {self.instrument} en het account staat "
            f"in {self.account}, maar de wisselkoers is niet bekend. Er wordt "
            "niet omgerekend: positiegrootte en resultaat staan daardoor in "
            "verschillende eenheden, wat bij een koers rond 1,08 zo'n acht "
            "procent scheelt."
        )

    def as_dict(self) -> dict:
        nu = datetime.now(timezone.utc)
        bruikbaar, reden = self.usable_for_entry(nu)
        leeftijd = self.age(nu)
        return {
            "instrument": self.instrument,
            "account": self.account,
            "direction": f"{self.account} per {self.instrument}",
            "rate": self.rate,
            "risk_rate": self.risk_rate,
            "risk_basis": self.risk_basis,
            "rate_source": self.rate_source,
            "rate_timestamp": (
                self.rate_timestamp.isoformat() if self.rate_timestamp else None
            ),
            "rate_age_hours": (
                round(leeftijd.total_seconds() / 3600, 2)
                if leeftijd is not None else None
            ),
            "market_closed": self.market_closed,
            "needed": self.needed,
            "usable": self.usable,
            "usable_for_entry": bruikbaar,
            "entry_reason": reden,
            "note": self.note(),
        }


def derive_rate_from_position(
    unrealised_account: float | None,
    open_price: float,
    current_price: float | None,
    units: float,
    side: str,
) -> float | None:
    """Leid de koers af uit een open positie.

    IG meldt de onrealiseerde winst (``upl``) in accountvaluta, terwijl de
    prijsbeweging in instrumentvaluta staat. De verhouding tussen die twee is
    de koers, en hij komt dus van de broker zelf - precies degene die ook
    afrekent.

    Geeft None bij een te kleine beweging: dan bepaalt afronding de uitkomst en
    is de afgeleide koers onbetrouwbaar.
    """
    if unrealised_account is None or not current_price or units <= 0:
        return None

    richting = 1.0 if side == "buy" else -1.0
    beweging = (current_price - open_price) * richting * units
    if abs(beweging) < 1.0:
        # Onder één eenheid bepaalt afronding de uitkomst.
        return None

    koers = unrealised_account / beweging
    if not 0.1 < koers < 10.0:
        _LOGGER.debug(
            "Afgeleide koers %.4f uit een positie ligt buiten het aannemelijke "
            "bereik; genegeerd.", koers,
        )
        return None
    return koers


def derive_rate(
    account_balance: float, account_balance_in_instrument: float | None
) -> float | None:
    """Leid de koers af uit twee weergaven van hetzelfde saldo.

    Geeft None terug bij ontbrekende of onzinnige waarden. Een koers die uit
    afronding van kleine bedragen komt, is onbetrouwbaar; daarom een ondergrens
    op het saldo.
    """
    if not account_balance_in_instrument or account_balance_in_instrument <= 0:
        return None
    if abs(account_balance) < 100:
        return None
    koers = account_balance / account_balance_in_instrument
    # Buiten dit bereik gaat het niet om een gangbaar valutapaar maar om een
    # rekenfout, en dan is geen koers beter dan een verkeerde.
    if not 0.1 < koers < 10.0:
        _LOGGER.warning(
            "Afgeleide wisselkoers %.4f ligt buiten het aannemelijke bereik; "
            "er wordt niet omgerekend.", koers,
        )
        return None
    return koers
