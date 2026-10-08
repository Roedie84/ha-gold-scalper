"""Saldosprong zonder trade: een dataprobleem, geen resultaat (1.7.7).

Op een demo-account past de broker het saldo soms zelf aan: het IG-demosaldo
sprong van ongeveer tienduizend naar tien miljoen, en later nog eens zonder
dat er een trade was gesloten. Zo'n sprong is geen handelsresultaat. Wie hem
als gewone meting behandelt, zet de dagstart, de equity bij de start van een
run en daarmee de vermogensvloer op een waarde die nergens op slaat.

Deze bewaker kijkt per meting of de equity meer dan ``DREMPEL`` (relatief)
afwijkt van de vorige, betrouwbare meting zonder dat er een verklaring is: een
positie die open staat of stond, of een trade die kort ervoor is gesloten. Is
die verklaring er niet, dan:

* staat de binaire sensor *Dataprobleem* aan, met de reden;
* blijft de vorige referentie gelden voor een nieuwe dagstart, een nieuwe
  run-opening (de vloer) en het dagijkpunt bij hervatten of dag opnieuw;
* wordt er één WARNING gelogd per gebeurtenis, niet per cyclus.

De handel zelf en de noodstop worden hier niet aan- of uitgezet. De bestaande
limieten blijven rekenen met de werkelijke equity van dit moment.

Herstel, zonder knop:

* keert de equity terug tot binnen ``DREMPEL`` van de referentie, dan is het
  probleem voorbij (INFO);
* blijft de sprongwaarde ``STABIEL_NA`` lang binnen ``DREMPEL`` van zichzelf,
  dan wordt hij de nieuwe referentie (INFO). Een broker die het saldo bewust
  aanpast, laat het daarna staan; een storing doet dat zelden een dag lang.

Eerste meting zonder referentie (na installatie, of als er nog niets bewaard
is): die wordt zonder vergelijking de referentie. Er is dan niets om een
sprong tegen af te zetten, en een account dat al op tien miljoen staat mag
niet bij de eerste start als sprong worden gezien.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..timeutil import parse_utc

_LOGGER = logging.getLogger(__name__)

#: Relatieve verandering tussen twee metingen waarboven een onverklaarde
#: sprong als dataprobleem geldt.
DREMPEL = 0.10
#: Hoe lang een sprongwaarde stabiel moet blijven voordat hij de nieuwe
#: referentie wordt.
STABIEL_NA = timedelta(hours=24)
#: Hoe lang een gesloten trade of open positie een verandering verklaart. De
#: accountopvraging van de broker loopt soms een cyclus achter op de sluiting;
#: zonder marge zou de verwerking van een gewone trade als sprong tellen.
VERKLARING_GELDIG = timedelta(minutes=5)


def _relatief(nieuw: float, oud: float) -> float:
    return abs(nieuw - oud) / abs(oud)


class SaldoSprongBewaker:
    """Houdt de betrouwbare saldoreferentie bij en herkent onverklaarde sprongen."""

    def __init__(self) -> None:
        #: Laatste betrouwbare meting.
        self.referentie: float | None = None
        #: Actieve sprong: de gemeten waarde en sinds wanneer die geldt.
        self.sprong_waarde: float | None = None
        self.sprong_sinds: datetime | None = None
        self.reden: str | None = None
        #: Laatste moment waarop een positie open stond of een trade sloot.
        self._verklaard_om: datetime | None = None
        #: Stand van de sluitingsteller bij de vorige meting.
        self._sluitingen: int | None = None

    @property
    def actief(self) -> bool:
        return self.sprong_waarde is not None

    def betrouwbaar(self, waarde: float | None) -> float | None:
        """De waarde om een dagstart, run-opening of ijkpunt op te baseren."""
        if self.actief and self.referentie is not None:
            return self.referentie
        return waarde

    # -- meten -------------------------------------------------------------- #

    def meet(
        self, now: datetime, waarde: float | None, positie_open: bool,
        sluitingen: int,
    ) -> None:
        """Verwerk één meting van de equity.

        ``positie_open``: staat er nu een positie of onbevestigde order open.
        ``sluitingen``: oplopende teller van gesloten trades (ook deelsluitingen).
        """
        if self._sluitingen is not None and sluitingen != self._sluitingen:
            self._verklaard_om = now
        self._sluitingen = sluitingen
        if positie_open:
            self._verklaard_om = now

        if waarde is None or waarde <= 0:
            return
        waarde = float(waarde)

        if self.referentie is None or self.referentie <= 0:
            # Eerste meting: zonder referentie valt er niets te vergelijken.
            self.referentie = waarde
            return

        if self.actief:
            self._tijdens_sprong(now, waarde)
            return

        if _relatief(waarde, self.referentie) <= DREMPEL:
            self.referentie = waarde
            return

        verklaard = (
            self._verklaard_om is not None
            and now - self._verklaard_om <= VERKLARING_GELDIG
        )
        if verklaard:
            self.referentie = waarde
            return

        self._begin_sprong(now, waarde, self.referentie)

    def _begin_sprong(self, now: datetime, waarde: float, vanaf: float) -> None:
        self.sprong_waarde = waarde
        self.sprong_sinds = now
        self.reden = (
            f"saldosprong zonder trade: equity van {vanaf:.2f} naar {waarde:.2f} "
            f"({(waarde - vanaf) / vanaf * 100:+.1f}%) terwijl er geen positie "
            f"open stond en geen trade sloot; dagstart, run-opening en vloer "
            f"blijven op {self.referentie:.2f}"
        )
        _LOGGER.warning(
            "Dataprobleem: %s. Wordt na %d uur stabiel de nieuwe referentie.",
            self.reden, int(STABIEL_NA.total_seconds() // 3600),
        )

    def _tijdens_sprong(self, now: datetime, waarde: float) -> None:
        assert self.referentie is not None and self.sprong_waarde is not None
        if _relatief(waarde, self.referentie) <= DREMPEL:
            _LOGGER.info(
                "Saldosprong voorbij: equity %.2f ligt weer binnen %.0f%% van "
                "de referentie %.2f.", waarde, DREMPEL * 100, self.referentie,
            )
            self.referentie = waarde
            self._wis()
            return
        if _relatief(waarde, self.sprong_waarde) > DREMPEL:
            # Opnieuw gesprongen: een nieuwe gebeurtenis, opnieuw wachten.
            self._begin_sprong(now, waarde, self.sprong_waarde)
            return
        if self.sprong_sinds is not None and now - self.sprong_sinds >= STABIEL_NA:
            _LOGGER.info(
                "Saldosprong %d uur stabiel: %.2f is de nieuwe referentie "
                "(was %.2f).", int(STABIEL_NA.total_seconds() // 3600),
                waarde, self.referentie,
            )
            self.referentie = waarde
            self._wis()

    def _wis(self) -> None:
        self.sprong_waarde = None
        self.sprong_sinds = None
        self.reden = None

    # -- bewaren ------------------------------------------------------------ #

    def export(self) -> dict:
        return {
            "referentie": self.referentie,
            "sprong_waarde": self.sprong_waarde,
            "sprong_sinds": (
                self.sprong_sinds.isoformat() if self.sprong_sinds else None
            ),
            "reden": self.reden,
        }

    def herstel(self, data: dict | None) -> None:
        """Bewaarde toestand terugzetten; onleesbaar of leeg = opnieuw beginnen."""
        if not isinstance(data, dict):
            return
        try:
            ref = data.get("referentie")
            self.referentie = float(ref) if ref is not None else None
            sprong = data.get("sprong_waarde")
            sinds = data.get("sprong_sinds")
            if sprong is not None and sinds:
                self.sprong_waarde = float(sprong)
                self.sprong_sinds = parse_utc(sinds)
                self.reden = data.get("reden")
        except (TypeError, ValueError):
            _LOGGER.debug("Bewaarde saldoreferentie onleesbaar; opnieuw beginnen")
            self.referentie = None
            self._wis()

    def as_dict(self) -> dict:
        return {
            "actief": self.actief,
            "reden": self.reden,
            "referentie": (
                round(self.referentie, 2) if self.referentie is not None else None
            ),
            "sprong_waarde": (
                round(self.sprong_waarde, 2) if self.sprong_waarde is not None else None
            ),
            "sprong_sinds": (
                self.sprong_sinds.isoformat() if self.sprong_sinds else None
            ),
            "drempel_pct": DREMPEL * 100,
            "stabiel_na_uur": STABIEL_NA.total_seconds() / 3600,
        }
