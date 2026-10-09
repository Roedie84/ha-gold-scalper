"""Risicolimieten en noodremmen.

Het uitgangspunt van deze module: de bot draait onbeheerd. Er kijkt niemand
mee. Wat er dus toe doet is niet hoe goed hij handelt op een goede dag, maar
hoeveel schade hij kan aanrichten op een slechte dag terwijl jij op je werk zit.

Elke limiet hier is een *harde* stop, geen waarschuwing. Bij overschrijding
gaat de bot naar ``HALTED`` en handelt niet meer tot een mens hem handmatig
herstart. Dat is bewust: een automatische hervatting na een noodstop betekent
dat dezelfde storing zich in een lus kan herhalen.

Belangrijk: deze limieten beschermen tegen *runaway*-gedrag, niet tegen een
verliesgevende strategie. Een bot die netjes binnen alle limieten elke dag 1%
verliest, wordt hier niet tegengehouden. Daar is de bewijsfase voor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum

from ..timeutil import parse_utc, trading_day


_LOGGER = logging.getLogger(__name__)


class TradingState(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"      # tijdelijk, hervat vanzelf
    HALTED = "halted"      # vereist handmatig ingrijpen



def risicobasis(starting_balance: float | None, referentie: float | None) -> float:
    """De kleinste positieve van startbalans en accountreferentie (1.9.4).

    De daglimiet en verliesvloer rekenen hierover, zodat een groot
    demosaldo de beveiligingen niet buiten werking zet en een saldo onder
    de startbalans ze niet versoepelt.
    """
    waarden = [float(w) for w in (starting_balance, referentie) if w and w > 0]
    return min(waarden) if waarden else 0.0


@dataclass(slots=True)
class RiskLimits:
    """Grenzen waarbinnen de bot mag opereren.

    De defaults zijn streng. Bij 200:1 hefboom op goud kan een positie van
    0,10 lot bij een beweging van 30 dollar al een derde van een account van
    1.000 euro wegnemen; de standaardwaarden gaan daarom uit van kleine
    posities en een lage dagelijkse verlieslimiet.
    """

    #: Maximaal verlies per dag, als percentage van de startbalans van die dag.
    max_daily_loss_pct: float = 2.0
    #: Absolute ondergrens voor de equity. Daaronder stopt alles.
    equity_floor_pct: float = 80.0
    #: Maximaal aantal trades per dag. Vangt een vastgelopen lus af.
    max_trades_per_day: int = 100
    #: Maximaal aantal verliezers achter elkaar voordat de bot pauzeert.
    max_consecutive_losses: int = 5
    #: Duur van de pauze na een reeks verliezers, in minuten.
    cooldown_minutes: int = 60
    #: Maximale positiegrootte in lots.
    max_volume: float = 0.10
    #: Maximaal aantal gelijktijdige posities.
    max_open_positions: int = 1
    #: Maximale duur van een positie. Vangt een positie af die blijft hangen
    #: doordat de bot is vastgelopen.
    max_position_age_seconds: int = 900
    #: Weiger bij een spread boven dit deel van de ATR.
    #:
    #: Bewust ruimer dan de grens in de strategie (0,35): dit is een vangnet
    #: tegen nieuwsmomenten waarop de spread vervijfvoudigt, niet het filter
    #: dat bepaalt of een trade de moeite waard is. Die twee door elkaar halen
    #: leverde een absolute grens van 0,60 op die IG's normale spread van 0,80
    #: al weigerde.
    max_spread_atr_ratio: float = 0.75
    #: Absolute bovengrens als laatste vangnet, in prijs-eenheden. Hoog gezet:
    #: bij goud rond 4600 is een spread van 0,80 normaal, bij goud op 3300 was
    #: dat 0,25. Een vast getal deugt hier niet als primaire grens.
    max_spread: float = 10.0
    #: Maximale tijd zonder nieuwe tick voordat de bot de dataverbinding
    #: als dood beschouwt en posities sluit.
    max_data_staleness_seconds: int = 30
    #: Hoe vaak je per dag mag hervatten na een noodstop.
    #:
    #: Onbeperkt hervatten maakt van de daglimiet een suggestie: je kunt dan
    #: telkens opnieuw hetzelfde percentage verliezen. Twee keer geeft ruimte
    #: om een storing te herstellen zonder de rem te ondermijnen.
    max_resumes_per_day: int = 2


@dataclass(slots=True)
class RiskState:
    """Lopende toestand. Reset per dag, behalve ``HALTED``."""

    state: TradingState = TradingState.RUNNING
    day: date = field(default_factory=lambda: trading_day(datetime.now(timezone.utc)))
    day_start_balance: float = 0.0
    trades_today: int = 0
    #: Aantal handmatige hervattingen vandaag.
    resumes_today: int = 0
    consecutive_losses: int = 0
    paused_until: datetime | None = None
    halt_reason: str | None = None
    triggered: list[str] = field(default_factory=list)


class RiskManager:
    """Bewaakt de limieten en blokkeert nieuwe posities bij overschrijding."""

    def __init__(
        self,
        limits: RiskLimits,
        starting_balance: float,
        now: datetime | None = None,
    ) -> None:
        self.limits = limits
        # ``now`` is expliciet meegeefbaar zodat de handelsdag niet stilzwijgend
        # van de wandklok afhangt; dat maakt het gedrag rond middernacht
        # testbaar in plaats van afhankelijk van wanneer je de test draait.
        moment = now or datetime.now(timezone.utc)
        self.state = RiskState(
            day=trading_day(parse_utc(moment)), day_start_balance=starting_balance,
        )
        #: 1.7.7: aantal gesloten trades (ook deelsluitingen) sinds de start;
        #: de saldosprongbewaker leest hieraan af of een sprong verklaard is.
        self.sluitingen = 0
        #: 1.7.7: bewaker op saldosprongen zonder trade. Is er een actieve
        #: sprong, dan rolt de dagstart naar de vorige betrouwbare referentie
        #: in plaats van naar de sprongwaarde. Wordt door de coordinator gezet.
        self.saldosprong = None
        #: 1.9.4: de startbalans van de laatste toets, zodat ``as_dict`` de
        #: risicobasis van de daglimiet kan tonen (dashboard en limiet gelijk).
        self.startbalans: float | None = starting_balance

    def dagbasis(self, starting_balance: float | None = None) -> float:
        """Waarover het dagverliespercentage rekent (1.9.4): de kleinste van
        dagstartsaldo en startbalans."""
        if starting_balance is None:
            starting_balance = self.startbalans
        return risicobasis(starting_balance, self.state.day_start_balance)

    def dagverlies_pct(
        self, balance: float, equity: float,
        starting_balance: float | None = None,
    ) -> float:
        """Dagverlies in procenten van :meth:`dagbasis`, op het slechtste van
        saldo en equity. Dezelfde berekening als de daglimiet in
        :meth:`can_open`, zodat dashboard en limiet nooit uiteenlopen."""
        basis = self.dagbasis(starting_balance)
        if not self.state.day_start_balance or not basis:
            return 0.0
        worst = min(balance, equity)
        return (self.state.day_start_balance - worst) / basis * 100.0

    def floor_breakdown(
        self, starting_balance: float, opening_equity: float | None,
        current_equity: float | None = None,
    ) -> dict:
        """De vermogensvloer en alle onderdelen waaruit hij volgt.

        De vloer rekende op de ingestelde startbalans (10.000), terwijl het
        werkelijke saldo bij de start van een run lager kan liggen (7.266). Alleen
        op de werkelijke equity overstappen zou de vloer verlagen - van 5.000
        naar 3.633 - en dat is een stille versoepeling van een bescherming.

        Daarom telt de strengste van de twee: de vloer op de ingestelde balans
        en die op de equity bij de start van de run. Het percentage verandert
        niet.

        1.9.4: daarnaast een **verliesvloer**: vanaf de equity bij de start
        van de run mag hooguit (100 - pct)% van de *kleinste* van startbalans
        en die equity verloren gaan. Op de IG-demo staat ~10 miljoen; de
        procentvloeren lagen daar op 5 miljoen en deden feitelijk niets. Met
        de verliesvloer is het maximale verlies 5.000 (bij 50% en een
        startbalans van 10.000), ongeacht hoe groot het demosaldo is. Op een
        echt account met equity rond de startbalans verandert er niets: de
        strengste vloer wint nog steeds.
        """
        pct = self.limits.equity_floor_pct
        geconfigureerd = (starting_balance or 0.0) * pct / 100.0
        run = (opening_equity * pct / 100.0) if opening_equity else None
        verlies = None
        max_verlies = None
        if opening_equity:
            basis = risicobasis(starting_balance, opening_equity)
            max_verlies = basis * (100.0 - pct) / 100.0
            verlies = opening_equity - max_verlies
        kandidaten = {
            "configured_floor": geconfigureerd,
            "run_floor": run if run is not None else float("-inf"),
            "verliesvloer": verlies if verlies is not None else float("-inf"),
        }
        applied = max(kandidaten, key=kandidaten.get)
        effectief = max(0.0, kandidaten[applied])
        return {
            "configured_starting_balance": starting_balance,
            "opening_equity_account": opening_equity,
            "current_equity_account": current_equity,
            "equity_floor_pct": pct,
            "configured_floor": round(geconfigureerd, 2),
            "run_floor": round(run, 2) if run is not None else None,
            "verliesvloer": round(verlies, 2) if verlies is not None else None,
            "max_verlies_run": (
                round(max_verlies, 2) if max_verlies is not None else None
            ),
            "effective_equity_floor": round(effectief, 2),
            "applied": applied,
        }

    # -- dagwissel ---------------------------------------------------------- #

    def _roll_day(self, now: datetime, balance: float) -> None:
        # Alleen vooruit rollen. Bij ``!=`` zou een klok die terugspringt - een
        # NTP-correctie, een tijdzonewissel, een herstart met verkeerde tijd -
        # de dagverliesteller op nul zetten. Dat is precies de limiet die moet
        # blijven staan als er iets vreemds aan de hand is.
        # Dezelfde handelsdag als het rapport en de live-poort. Eerst rolde
        # het dagverlies om 00:00 UTC, twee uur later dan de dag in het
        # periodeoverzicht.
        vandaag = trading_day(parse_utc(now))
        if vandaag > self.state.day:
            _LOGGER.info(
                "Nieuwe handelsdag; teller op nul (gisteren %d trades)",
                self.state.trades_today,
            )
            self.state.day = vandaag
            # 1.7.7: geen nieuwe dagstart op een onverklaarde saldosprong.
            if self.saldosprong is not None and self.saldosprong.actief:
                betrouwbaar = self.saldosprong.betrouwbaar(balance)
                _LOGGER.warning(
                    "Dagstart op de vorige referentie %.2f in plaats van %.2f: "
                    "%s", betrouwbaar, balance, self.saldosprong.reden,
                )
                balance = betrouwbaar
            self.state.day_start_balance = balance
            self.state.resumes_today = 0
            self.state.trades_today = 0
            self.state.consecutive_losses = 0
            # HALTED overleeft de dagwissel bewust: een noodstop hoort niet
            # om middernacht vanzelf op te lossen.
            if self.state.state is TradingState.PAUSED:
                self.state.state = TradingState.RUNNING
                self.state.paused_until = None

    # -- toetsen ------------------------------------------------------------ #

    def can_open(
        self,
        now: datetime,
        balance: float,
        equity: float,
        starting_balance: float,
        open_positions: int,
        volume: float,
        spread: float,
        last_tick_age: float,
        market_open: bool = True,
        atr: float | None = None,
        opening_equity: float | None = None,
    ) -> tuple[bool, str | None]:
        """Mag er nu een positie open? Geeft (toegestaan, reden bij weigering)."""
        self.startbalans = starting_balance
        self._roll_day(now, balance)

        if self.state.state is TradingState.HALTED:
            return False, f"noodstop actief: {self.state.halt_reason}"

        if self.state.state is TradingState.PAUSED:
            if self.state.paused_until and now < self.state.paused_until:
                remaining = (self.state.paused_until - now).total_seconds() / 60
                return False, f"pauze nog {remaining:.0f} minuten"
            self.state.state = TradingState.RUNNING
            self.state.paused_until = None

        # Gesloten markt is geen storing. Goud handelt niet in het weekend en
        # kent een dagelijkse onderbreking; de laatste koers is dan uren oud
        # zonder dat er iets mis is. Zonder dit onderscheid legt de bot zichzelf
        # de eerste vrijdagavond permanent stil met een noodstop die handmatige
        # interventie vereist.
        if not market_open:
            return False, "markt gesloten"

        # Dode dataverbinding tijdens handelsuren is wél het gevaarlijkste
        # scenario: de bot denkt te weten wat de prijs is terwijl die verouderd is.
        if last_tick_age > self.limits.max_data_staleness_seconds:
            self.halt(f"geen tickdata gedurende {last_tick_age:.0f}s tijdens handelsuren")
            return False, "dataverbinding dood"

        vloer = self.floor_breakdown(starting_balance, opening_equity, equity)
        sprong = self.saldosprong is not None and self.saldosprong.actief
        if equity < vloer["effective_equity_floor"]:
            if sprong:
                # 1.9.4: een onverklaarde saldosprong (bijv. een reset van het
                # demosaldo) is een dataprobleem, geen verlies. Niet openen,
                # maar ook geen noodstop die handmatig hervat moet worden.
                return False, "saldosprong: vloer niet betrouwbaar te toetsen"
            self.halt(
                f"equity {equity:.2f} onder de ondergrens van "
                f"{vloer['effective_equity_floor']:.2f} ({vloer['applied']})"
            )
            return False, "equity onder de ondergrens"

        # Op equity rekenen, niet op balance. Balance bevat alleen gesloten
        # trades; open posities met een fors onrealiseerd verlies telden dus
        # niet mee. In de praktijk liep het onrealiseerde verlies op tot ruim
        # het dubbele van de daglimiet zonder dat er iets afging, omdat er
        # simpelweg nog niets was afgerekend.
        #
        # De strengste van de twee wint: een gerealiseerd verlies dat al boven
        # de limiet ligt mag niet gemaskeerd worden door een open positie die
        # toevallig in de plus staat.
        #
        # 1.9.4: het percentage geldt over de kleinste van dagstartsaldo en
        # startbalans. Op de IG-demo (~10 miljoen) was 10% anders 1 miljoen en
        # ging de daglimiet nooit af; nu is het 10% van 10.000. Op een echt
        # account rond de startbalans verandert er niets.
        day_loss_pct = self.dagverlies_pct(balance, equity, starting_balance)
        if day_loss_pct >= self.limits.max_daily_loss_pct and sprong:
            return False, "saldosprong: daglimiet niet betrouwbaar te toetsen"
        if day_loss_pct >= self.limits.max_daily_loss_pct:
            unrealised = equity - balance
            self.halt(
                f"dagverlies {day_loss_pct:.2f}% bereikt de limiet van "
                f"{self.limits.max_daily_loss_pct:.2f}%"
                + (
                    f" (waarvan {unrealised:.2f} nog niet gerealiseerd)"
                    if abs(unrealised) > 0.01 else ""
                )
            )
            return False, "daglimiet bereikt"

        if self.state.trades_today >= self.limits.max_trades_per_day:
            self.halt(f"{self.state.trades_today} trades vandaag; limiet bereikt")
            return False, "dagelijkse trade-limiet bereikt"

        if open_positions >= self.limits.max_open_positions:
            return False, "maximaal aantal posities open"

        if volume > self.limits.max_volume:
            return False, (
                f"volume {volume} boven de limiet {self.limits.max_volume}"
            )

        if spread > self.limits.max_spread:
            return False, (
                f"spread {spread:.3f} boven de absolute vangnetgrens "
                f"{self.limits.max_spread:.3f}"
            )

        # Relatief aan de beweging: een spread van 0,80 is krap bij een ATR van
        # 1,0 en verwaarloosbaar bij een ATR van 4,1.
        if atr and atr > 0:
            ratio = spread / atr
            if ratio > self.limits.max_spread_atr_ratio:
                return False, (
                    f"spread {spread:.3f} is {ratio:.0%} van de ATR ({atr:.2f}); "
                    f"vangnetgrens ligt op {self.limits.max_spread_atr_ratio:.0%}"
                )

        return True, None

    # -- terugkoppeling ----------------------------------------------------- #

    def record_open(self) -> None:
        self.state.trades_today += 1

    def record_close(self, net_pnl: float, now: datetime) -> None:
        self.sluitingen += 1
        if net_pnl < 0:
            self.state.consecutive_losses += 1
            if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
                self.pause(now, f"{self.state.consecutive_losses} verliezers achter elkaar")
        else:
            self.state.consecutive_losses = 0

    def positions_to_force_close(self, now: datetime, open_trades: list) -> list:
        """Posities die te lang openstaan. Vangt een vastgelopen bot af."""
        stale = []
        for trade in open_trades:
            opened = datetime.fromisoformat(trade.open_time)
            if (now - opened).total_seconds() > self.limits.max_position_age_seconds:
                stale.append(trade)
        return stale

    # -- toestandsovergangen ------------------------------------------------ #

    def pause(self, now: datetime, reason: str) -> None:
        from datetime import timedelta

        self.state.state = TradingState.PAUSED
        self.state.paused_until = now + timedelta(minutes=self.limits.cooldown_minutes)
        self.state.triggered.append(f"{now.isoformat(timespec='seconds')} pauze: {reason}")
        _LOGGER.warning("Handel gepauzeerd tot %s: %s", self.state.paused_until, reason)

    def restore_halt(self, reason: str) -> None:
        """Een bewaarde noodstop terugzetten na een herstart, zonder hem als
        nieuwe gebeurtenis te melden of te registreren."""
        self.state.state = TradingState.HALTED
        self.state.halt_reason = reason

    def halt(self, reason: str) -> None:
        """Noodstop. Hervat alleen na handmatig ingrijpen."""
        if self.state.state is TradingState.HALTED:
            return
        self.state.state = TradingState.HALTED
        self.state.halt_reason = reason
        self.state.triggered.append(
            f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} NOODSTOP: {reason}"
        )
        _LOGGER.error("NOODSTOP: %s. Handmatige herstart vereist.", reason)

    def reset_day(self, balance: float) -> str:
        """Zet de dagtellers terug alsof er een nieuwe handelsdag begint.

        Bestaat omdat de teller anders alleen om middernacht reset, en dat is
        soms te laat: je hebt de limiet bereikt door een instelling die je
        inmiddels hebt gecorrigeerd, en dan wachten tot morgen is geen
        bescherming maar een obstakel.

        De omweg was het bewerken van .storage, en die werkt niet: de
        integratie houdt de waarde in het geheugen en schrijft hem elke cyclus
        terug. Een bestand aanpassen dat binnen twintig seconden wordt
        overschreven, is geen oplossing maar een valstrik.

        Wat hier *niet* gebeurt: het verlies wegpoetsen. Dat blijft in de
        database staan en telt gewoon mee in je resultaten. Alleen de noodrem
        begint opnieuw.
        """
        verloren = self.state.day_start_balance - balance
        hervattingen = self.state.resumes_today
        trades = self.state.trades_today

        self.state.day_start_balance = balance
        self.state.resumes_today = 0
        self.state.trades_today = 0
        self.state.consecutive_losses = 0
        if self.state.state is TradingState.HALTED:
            self.state.state = TradingState.RUNNING
            self.state.halt_reason = None

        bericht = (
            f"Dagtellers teruggezet. Vandaag stond er {verloren:.2f} verlies, "
            f"{trades} trades en {hervattingen} hervattingen; die blijven in de "
            "database staan en tellen mee in je resultaten. Alleen de noodrem "
            f"begint opnieuw, vanaf een saldo van {balance:.2f}."
        )
        _LOGGER.warning(bericht)
        return bericht

    def manual_resume(self, balance: float | None = None) -> tuple[bool, str]:
        """Hervat na een noodstop, met een nieuw dagijkpunt.

        Zonder dat ijkpunt is hervatten zinloos: de volgende cyclus rekent het
        dagverlies opnieuw uit vanaf hetzelfde beginsaldo, ziet nog steeds een
        overschrijding, en stopt meteen weer. Een hervatknop die faalt in
        precies het geval waarvoor hij bestaat, is geen hervatknop.

        Er zit wel een rem op. Onbeperkt hervatten maakt van de daglimiet een
        suggestie: je kunt dan elke keer opnieuw twee procent verliezen. Na
        ``max_resumes_per_day`` weigert hij, en dan is wachten tot morgen de
        enige uitweg - wat bij een slechte dag ook de juiste is.
        """
        if self.state.resumes_today >= self.limits.max_resumes_per_day:
            message = (
                f"Al {self.state.resumes_today} keer hervat vandaag; de limiet is "
                f"{self.limits.max_resumes_per_day}. Verder hervatten zou van de "
                "daglimiet een suggestie maken.\n\nWacht tot morgen - de teller "
                "reset om middernacht - of roep gold_scalper.reset_day aan als "
                "je de limiet raakte door een instelling die inmiddels is "
                "gecorrigeerd."
            )
            _LOGGER.warning(message)
            return False, message

        previous = self.state.halt_reason
        self.state.resumes_today += 1
        self.state.state = TradingState.RUNNING
        self.state.halt_reason = None
        self.state.consecutive_losses = 0

        if balance is not None:
            # Het dagverlies wordt voortaan vanaf hier gemeten. Het verlies dat
            # al geleden is blijft in de database staan en telt gewoon mee in de
            # resultaten; alleen de noodrem begint opnieuw.
            verloren = self.state.day_start_balance - balance
            self.state.day_start_balance = balance
            _LOGGER.warning(
                "Handmatige hervatting na: %s. Dagijkpunt verzet naar %.2f "
                "(%.2f al verloren vandaag, hervatting %d van %d).",
                previous, balance, verloren,
                self.state.resumes_today, self.limits.max_resumes_per_day,
            )
        else:
            _LOGGER.warning("Handmatige hervatting na: %s", previous)

        return True, "Hervat."

    def as_dict(self) -> dict:
        return {
            "state": self.state.state.value,
            "trades_today": self.state.trades_today,
            "resumes_today": self.state.resumes_today,
            "max_resumes_per_day": self.limits.max_resumes_per_day,
            "consecutive_losses": self.state.consecutive_losses,
            "day_start_balance": round(self.state.day_start_balance, 2),
            # 1.9.4: waarover de daglimiet rekent en hoeveel dat is.
            "risicobasis": round(self.dagbasis(), 2),
            "max_daily_loss_pct": self.limits.max_daily_loss_pct,
            "daglimiet_bedrag": round(
                self.dagbasis() * self.limits.max_daily_loss_pct / 100.0, 2
            ),
            "halt_reason": self.state.halt_reason,
            "paused_until": (
                self.state.paused_until.isoformat() if self.state.paused_until else None
            ),
            "recent_triggers": self.state.triggered[-10:],
        }
