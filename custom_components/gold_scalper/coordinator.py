"""Coordinator: de handelslus, draaiend in het Home Assistant-proces.

Volgorde per cyclus, en die volgorde is niet willekeurig:

1. Koers ophalen. Zonder verse prijs gebeurt er verder niets.
2. Nieuwe afgesloten candle? Dan de incrementele indicatoren bijwerken.
3. **Open posities beheren.** Dit gaat vóór het zoeken naar nieuwe signalen.
   Een bestaande positie beschermen is altijd urgenter dan een nieuwe openen.
4. Risicotoetsen.
5. Pas dan strategie evalueren en eventueel openen.
6. Administratie wegschrijven.

Alles draait binnen HA. Er is geen tweede proces, geen bridge, geen Windows.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .analysis.signals import Candles
from .broker.adapter import (
    ExecutionVenue, OrderResult, VenueError, VenueQuote, size_says_closed,
)
from .broker.execution_safety import BrokerLimits, SafeExecutor
from .broker.currency import Conversion, derive_rate_from_position
from .broker.reconcile_audit import SLUIT_GENADE_SECONDEN, compare_positions
from .broker.schedule import (
    SPOT_GOLD, ClosureObservation, cross_check, minutes_until_close,
)
from .broker.exits import ExitConfig, ExitManager
from .broker.ig_capital import CapitalVenue, IgVenue
from .broker.oanda import OandaVenue
from .broker.public_data import PublicDataVenue
from .broker.stooq import StooqVenue
from .broker.simulator import SimulatorVenue
from .broker.paper import CONTRACT_SIZE, BrokerCosts, PaperBroker
from .broker.paper import Quote as PaperQuote
from .broker.risk import RiskLimits, RiskManager, TradingState
from .broker.saldosprong import SaldoSprongBewaker
from .const import (
    STRATEGY_WINDOW_BARS,
    EXECUTION_SEMANTICS_VERSION,
    EXIT_REGIME_HUIDIG,
    INTEGRATION_VERSION,
    ARCHIVE_FILENAME,
    CONF_ACCOUNT_ID, CONF_API_KEY, CONF_ASSUMED_SPREAD, CONF_BUILD_FROM_QUOTES,
    CONF_NOTIFY_CRITICAL, CONF_NOTIFY_HOURLY, CONF_NOTIFY_SERVICE,
    CONF_CLOSE_BUFFER_MINUTES, CONF_USE_SCHEDULE,
    CONF_NOTIFY_SKIP_QUIET, CONF_PYRAMID_ENABLED, CONF_PYRAMID_MAX_ADDITIONS,
    CONF_PYRAMID_TRIGGER_ATR, CONF_RISK_BASED_SIZING, CONF_RISK_PER_TRADE_PCT,
    CONF_SCALE_WITH_CONFIDENCE, CONF_STOP_LOSS_ATR, CONF_STOP_LOSS_USD,
    CONF_TAKE_PROFIT_ATR, CONF_TAKE_PROFIT_USD, NOTIFY_NONE,
    CONF_ENFORCE_TRADING_HOURS,
    CONF_EPIC, CONF_IDENTIFIER, CONF_PASSWORD, DEFAULT_EPIC, VENUE_CAPITAL, VENUE_IG,
    CONF_REGIME_SWITCHING, DEFAULT_ASSUMED_SPREAD, VENUE_PUBLIC,
    VENUE_STOOQ,
    CONF_SIM_SEED, CONF_SIM_SPREAD, CONF_VENUE,
    DEFAULT_SIM_SEED, DEFAULT_SIM_SPREAD, DEFAULT_VENUE, VENUE_SIMULATOR, CONF_ENTRY_THRESHOLD, CONF_ENVIRONMENT, CONF_EQUITY_FLOOR_PCT,
    CONF_MAX_CONSECUTIVE_LOSSES, CONF_MAX_DAILY_LOSS_PCT, CONF_MAX_RESUMES_PER_DAY, CONF_MAX_SPREAD, CONF_MAX_SPREAD_ATR,
    CONF_MAX_TRADES_PER_DAY, CONF_MAX_UNITS, CONF_MIN_EDGE_MULTIPLE, CONF_MODE,
    CONF_STARTING_BALANCE, CONF_SYMBOL, CONF_TIMEFRAME, CONF_TOKEN,
    CONF_TRADING_END_HOUR, CONF_TRADING_START_HOUR, CONF_UNITS, CONF_UPDATE_SECONDS,
    DATABASE_FILENAME, DEFAULT_ENVIRONMENT, DEFAULT_MAX_UNITS, DEFAULT_MODE,
    DEFAULT_STARTING_BALANCE, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME, DEFAULT_UNITS,
    DEFAULT_UPDATE_SECONDS, DOMAIN, MIN_UPDATE_SECONDS, MIN_WARMUP_CANDLES,
    WARMUP_CANDLES, KOERS_HOUD_MAX_MISLUKT, KOERS_HOUD_MAX_SECONDEN,
)
from .learning.analysis import evaluate_threshold, measure_execution, regime_performance
from .learning.postmortem import analyse_losses
from .lifecycle import DrainPolicy, LifecycleController, veilig_herstarten
from .notify import Notifier, NotifierConfig
from .status import build_status
from .modes import LiveGate, ModeLockedError, TradingMode, require_live_unlocked
from .storage import performance
from .storage.bar_archive import BarArchive
from .storage.periods import build_periods
from .settings import candle_source, resolve
from .timeutil import parse_utc, trading_day
from .storage.database import MODE_LIVE, MODE_PAPER, Trade, TradeDatabase
from .storage.state import ResultsStore, RuntimeState, StateStore
from .storage.latency import (
    LATENCY_VENSTER, LatencyBudget, LatencyTracker, install_buffered_signals,
)
from .strategy.scalping import STRATEGY_VERSION, ScalpConfig, evaluate
from .learning.robustness import evaluate_robustness
from .learning.sessions import build_news_impact, build_sessions
from .strategy.aggregator import BAR_SECONDS, QuoteAggregator, closed_only
from .strategy.pyramid import PyramidConfig, consider_addition
from .strategy.sizing import SizingConfig, position_size
from .strategy.streaming import StreamState

_LOGGER = logging.getLogger(__name__)

#: Standaard voor ``_on_bars_closed``: dezelfde bars archiveren als binnenkomen.
_ZELFDE = object()

#: Koersen uit de markt van de broker: die gaan voor op een uit een trade
#: afgeleide koers.
MARKT_BRONNEN = frozenset({"ig_market", "ig_instrument"})


def _as_datetime(value, fallback: datetime) -> datetime:
    """Zet open_time om naar een datetime, ongeacht de vorm.

    De paper-broker bewaart ISO-strings in de database; de venue-adapter geeft
    datetimes terug. Beide komen in dezelfde lus binnen, dus de omzetting hoort
    op één plek te staan in plaats van in een reeks ternaire expressies waar
    makkelijk een tak fout gaat.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return fallback
    return fallback


def _veilig_utc(waarde) -> datetime | None:
    """Een bewaarde tijd als UTC, of None als hij ontbreekt of onleesbaar is."""
    if not waarde:
        return None
    try:
        return parse_utc(waarde)
    except (TypeError, ValueError):
        return None


def _as_int(value, fallback: int) -> int:
    """Config-flow-waarden komen als float binnen; coërceer op de grens."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


#: 1.7.3: na zoveel seconden na een afwikkeling op een schatting wordt de
#: uitstapprijs opnieuw bij de broker nagevraagd (activiteitenoverzicht en
#: bevestiging). Vier pogingen in vier minuten, één verzoek per poging; daarna
#: neemt de gewone correctie het over. De lus draait elke twintig seconden, dus
#: een poging valt hooguit een cyclus later dan gepland.
HERKANSING_SCHEMA = (20, 60, 120, 240)


@dataclass(slots=True)
class _TicketOnly:
    """Minimale positieverwijzing voor het afsluiten van een verdwenen trade.

    Alleen het ticketnummer is nodig; de rest staat al in de database. Een
    klasse in plaats van een dict-truc, zodat de attribuutnaam vastligt.
    """

    ticket: str


class GoldScalperCoordinator(DataUpdateCoordinator[dict]):
    """Houdt de handelslus, de administratie en alle bewaking bij elkaar."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        options = {**entry.data, **entry.options}
        self.entry = entry
        self.symbol: str = options.get(CONF_SYMBOL, DEFAULT_SYMBOL)
        self.timeframe: str = options.get(CONF_TIMEFRAME, DEFAULT_TIMEFRAME)
        #: Wat de gebruiker koos. Kan afwijken van ``self.mode`` als de
        #: databron niet kan uitvoeren - zie ``mode_override_reason``.
        requested = options.get(CONF_MODE, DEFAULT_MODE)
        # Bestaande entries kunnen 'backtest' bevatten uit een eerdere versie.
        if requested == TradingMode.BACKTEST.value:
            requested = TradingMode.PAPER.value
        self.requested_mode = TradingMode(requested)
        self.mode = self.requested_mode
        self.mode_override_reason: str | None = None
        self.units: float = options.get(CONF_UNITS, DEFAULT_UNITS)
        self.starting_balance: float = options.get(
            CONF_STARTING_BALANCE, DEFAULT_STARTING_BALANCE
        )

        venue_name = options.get(CONF_VENUE, DEFAULT_VENUE)

        # Brokers gebruiken hun eigen instrumentcode (bij IG een 'epic'), en
        # die staat in een apart veld. Bij herconfigureren blijft het oude
        # symbool uit de vorige databron in de entry staan, en dat werd hier
        # gebruikt - waarna elke aanroep de venue om 'XAU_USD' vroeg in plaats
        # van om 'CS.D.CFDGOLD.CFDGC.IP'. De broker antwoordde dan met een
        # 404 die niets over het instrument zei.
        if venue_name in (VENUE_IG, VENUE_CAPITAL):
            epic = options.get(CONF_EPIC)
            if epic:
                self.symbol = epic
        # Databronnen zonder uitvoering kunnen alleen papierhandel doen. Dat
        # stilzwijgend afdwingen is gevaarlijk: iemand die 'live' koos, denkt
        # dan dat het live staat. Daarom wordt de reden vastgelegd en via de
        # modus-sensor getoond.
        if (venue_name in (VENUE_PUBLIC, VENUE_STOOQ, VENUE_SIMULATOR)
                and self.mode is not TradingMode.PAPER):
            self.mode_override_reason = (
                f"Databron '{venue_name}' kan niet uitvoeren, dus modus "
                f"'{self.requested_mode.value}' is genegeerd en er wordt op "
                "papier gehandeld."
            )
            _LOGGER.warning(self.mode_override_reason)
        if venue_name == VENUE_PUBLIC:
            self.venue: ExecutionVenue = PublicDataVenue(
                session=async_get_clientsession(hass),
                symbol=self.symbol,
                assumed_spread=options.get(
                    CONF_ASSUMED_SPREAD, DEFAULT_ASSUMED_SPREAD
                ),
            )
            self.mode = TradingMode.PAPER
        elif venue_name in (VENUE_IG, VENUE_CAPITAL):
            factory = IgVenue if venue_name == VENUE_IG else CapitalVenue
            self.venue = factory(
                session=async_get_clientsession(hass),
                api_key=options[CONF_API_KEY],
                identifier=options[CONF_IDENTIFIER],
                password=options[CONF_PASSWORD],
                environment=options.get(CONF_ENVIRONMENT, "demo"),
                epic=options.get(CONF_EPIC, DEFAULT_EPIC),
                # Pas ingeschakeld nadat de poort opengaat; zie _refresh_gate.
                trading_enabled=False,
                max_units=options.get(CONF_MAX_UNITS, DEFAULT_MAX_UNITS),
            )
        elif venue_name == VENUE_STOOQ:
            self.venue = StooqVenue(
                session=async_get_clientsession(hass),
                symbol=self.symbol,
                assumed_spread=options.get(CONF_ASSUMED_SPREAD, DEFAULT_ASSUMED_SPREAD),
            )
            self.mode = TradingMode.PAPER
        elif venue_name == VENUE_SIMULATOR:
            self.venue = SimulatorVenue(
                seed=_as_int(options.get(CONF_SIM_SEED), DEFAULT_SIM_SEED),
                spread=options.get(CONF_SIM_SPREAD, DEFAULT_SIM_SPREAD),
                balance=self.starting_balance,
            )
            self.mode = TradingMode.PAPER
        else:
            self.venue = OandaVenue(
                session=async_get_clientsession(hass),
                token=options[CONF_TOKEN],
                account_id=options[CONF_ACCOUNT_ID],
                environment=options.get(CONF_ENVIRONMENT, DEFAULT_ENVIRONMENT),
                # Live handel wordt pas ingeschakeld nadat de poort opengaat;
                # zie _refresh_gate. Bij het opstarten staat hij altijd dicht.
                trading_enabled=False,
                max_units=options.get(CONF_MAX_UNITS, DEFAULT_MAX_UNITS),
            )

        self.strategy_cfg = ScalpConfig(
            max_spread=options.get(CONF_MAX_SPREAD, 3.00),
            max_spread_atr_ratio=options.get(CONF_MAX_SPREAD_ATR, 0.35),
            min_edge_multiple=options.get(CONF_MIN_EDGE_MULTIPLE, 2.0),
            entry_threshold=options.get(CONF_ENTRY_THRESHOLD, 0.45),
            take_profit_atr=options.get(CONF_TAKE_PROFIT_ATR, 1.5),
            stop_loss_atr=options.get(CONF_STOP_LOSS_ATR, 1.0),
            take_profit_usd=options.get(CONF_TAKE_PROFIT_USD, 0.0),
            stop_loss_usd=options.get(CONF_STOP_LOSS_USD, 0.0),
            regime_switching=options.get(CONF_REGIME_SWITCHING, True),
            enforce_trading_hours=options.get(CONF_ENFORCE_TRADING_HOURS, False),
            # Alleen een broker levert een echte bied/laat-spread; publieke
            # bronnen en de simulator geven een aanname.
            real_spread=getattr(self.venue, "has_real_spread", True),
            trading_hours_utc=(
                _as_int(options.get(CONF_TRADING_START_HOUR), 7),
                _as_int(options.get(CONF_TRADING_END_HOUR), 20),
            ),
            commission_per_lot_per_side=0.0,  # OANDA rekent in de spread
            volume=self.units / CONTRACT_SIZE,
        )

        self.risk = RiskManager(
            RiskLimits(
                max_daily_loss_pct=options.get(CONF_MAX_DAILY_LOSS_PCT, 2.0),
                max_trades_per_day=_as_int(options.get(CONF_MAX_TRADES_PER_DAY), 100),
                max_consecutive_losses=_as_int(
                    options.get(CONF_MAX_CONSECUTIVE_LOSSES), 5
                ),
                equity_floor_pct=options.get(CONF_EQUITY_FLOOR_PCT, 80.0),
                max_volume=options.get(CONF_MAX_UNITS, DEFAULT_MAX_UNITS) / CONTRACT_SIZE,
                max_resumes_per_day=_as_int(
                    options.get(CONF_MAX_RESUMES_PER_DAY), 2
                ),
            ),
            self.starting_balance,
        )
        #: 1.7.7: saldosprong zonder trade = dataprobleem.
        self.saldosprong = SaldoSprongBewaker()
        self.risk.saldosprong = self.saldosprong

        # Beschermingslaag rond echte orders. Papermodus kent de storingen die
        # hij afvangt niet, dus de bewijsfase leert je daar niets over.
        self.executor = SafeExecutor(
            self.venue,
            BrokerLimits(
                max_volume=options.get(CONF_MAX_UNITS, DEFAULT_MAX_UNITS),
                min_stop_distance=options.get("min_stop_distance", 0.0),
            ),
        )
        #: Cyclusteller voor de periodieke positiecontrole.
        self._audit_counter = 0
        #: Posities zoals ze deze cyclus bij de broker stonden. Aan het begin
        #: van elke cyclus gewist, en na elke order verversd.
        self._positions_cache: list | None = None

        self.sizing = SizingConfig(
            fixed_units=self.units,
            risk_based=options.get(CONF_RISK_BASED_SIZING, False),
            risk_per_trade_pct=options.get(CONF_RISK_PER_TRADE_PCT, 0.5),
            scale_with_confidence=options.get(CONF_SCALE_WITH_CONFIDENCE, False),
            max_units=options.get(CONF_MAX_UNITS, DEFAULT_MAX_UNITS),
        )
        self.pyramid = PyramidConfig(
            enabled=options.get(CONF_PYRAMID_ENABLED, False),
            trigger_atr=options.get(CONF_PYRAMID_TRIGGER_ATR, 1.0),
            max_additions=_as_int(options.get(CONF_PYRAMID_MAX_ADDITIONS), 2),
        )
        #: Per ticket: hoeveel toevoegingen en op welke prijs de laatste.
        self._pyramid_state: dict[str, dict] = {}
        if self.pyramid.enabled:
            # Bekende beperking (5.7): bijkopen wordt niet in de administratie
            # vastgelegd; elke toevoeging wordt bij de afstemming een
            # onbekende positie. De instelling wordt bewust niet gewijzigd.
            _LOGGER.warning(
                "Piramide staat aan, maar bijkopen wordt nog niet vastgelegd in de "
                "administratie of de afstemming. Zet het uit tot dat is opgelost."
            )
        #: Per ticket de uiterste mee- en tegenbeweging sinds de instap.
        #:
        #: Bij brokertrades werden die niet bijgehouden, terwijl de
        #: verliesanalyse erop filtert. Gevolg: die analyse sloeg elke
        #: demotrade over en meldde "0 verliezende trades" naast een
        #: performance die er wél telde - dood in precies de modus die ertoe
        #: doet.
        self._excursions: dict[str, dict] = {}
        self.robustness: dict = {}
        self.periods: dict = {}
        self.sessions: dict = {}
        self.news_impact: dict = {}
        #: Archief van bars over herstarts heen. De beperking van dit project
        #: is het aantal metingen, niet het aantal ideeën: met een jaar
        #: historie is een hypothese in een minuut te toetsen in plaats van in
        #: drie weken.
        self.archive: BarArchive | None = None
        #: Uitkomst van de vergelijking tussen backtest en live-resultaat.
        self.validation: dict = {}
        #: Laatst gemeten klantsentiment bij de broker.
        self.sentiment: dict = {}
        #: Drawdown op de equity in accountvaluta.
        self.account_drawdown: dict = {}
        #: Tickets van open trades uit een eerdere run die nog live staan.
        self._carried_tickets: set[str] = set()
        #: Equity bij de start van de run, in accountvaluta.
        self.opening_equity: float | None = None
        #: Laatst gemelde equity van de broker, in accountvaluta.
        self.current_equity: float | None = None
        #: Laatste omrekenkoers die de broker bij een afrekening noemde.
        self._broker_fx_ref: float | None = None
        #: Recentste verlieskoers van de broker, en wanneer.
        self._loss_fx_rate: float | None = None
        self._loss_fx_at: datetime | None = None
        self._fx_richting_gemeld = False
        #: Wanneer EUR/USD voor het laatst is opgehaald.
        self._fx_checked: datetime | None = None
        #: Waarom nieuwe posities op de wisselkoers wachten (voor de melding).
        self._fx_block_reason: str | None = None
        #: Doeltreffers, stoptreffers, eigen exits en onbekend.
        self.exit_stats: dict = {}
        #: Uitkomst van de laatste afstemming met de broker.
        self.reconciliation: dict = {}
        #: Handelsdag waarop voor het laatst automatisch is afgestemd.
        self._afgestemd_op: str | None = None
        self._afgestemd_om: datetime | None = None
        #: Kosten uit het ledger en hoeveel daarvan gemeten zijn.
        self.ledger_cost_info: dict = {}
        self._ledger_cost_value: float | None = None
        self._ledger_cost_count: int = -1
        #: Laatste uitslag van het indicatorlab.
        self.lab: dict = {}
        #: Bevindingen die al gemeld zijn, om herhaling te onderdrukken.
        self._audit_gemeld: set = set()
        #: 1.7.8: tickets waarvoor wij een sluitverzoek verstuurden, met het
        #: moment (monotone klok). De controle telt zo'n positie binnen de
        #: genadetermijn niet als wees: IG toont hem soms nog even.
        self._sluitverzoeken: dict[str, float] = {}
        #: Aantal trades dat op een geschatte uitstapprijs is afgerekend.
        self._geschatte_afwikkelingen = 0
        #: Cyclusteller voor het bijwerken van geschatte afwikkelingen.
        self._correctie_teller = 0
        #: 1.7.3: verse schattingen die nog kort bij de broker worden
        #: nagevraagd: ``ticket -> {"pogingen", "sinds"}``.
        self._herkansingen: dict = {}
        self.backtest: dict = {}
        self.audit: dict = {}
        self._use_schedule: bool = options.get(CONF_USE_SCHEDULE, True)
        self._close_buffer: int = _as_int(
            options.get(CONF_CLOSE_BUFFER_MINUTES), 10
        )
        self.schedule_note: str | None = None
        #: Laatst gemelde roosterafwijking, om herhaling te onderdrukken.
        self._last_schedule_note: str | None = None
        #: Waarneming van wanneer de broker werkelijk sluit. Het rooster is een
        #: vermoeden; dit is wat er gebeurde.
        self.closures = ClosureObservation()
        #: Omrekening tussen instrument- en accountvaluta. Wordt bij elke
        #: accountopvraging bijgewerkt; zolang de koers onbekend is, wordt er
        #: niet omgerekend maar gemeld dat het niet kan.
        self.conversion = Conversion(instrument="USD")
        self.last_sizing: dict = {}

        service = options.get(CONF_NOTIFY_SERVICE, NOTIFY_NONE)
        self.notifier = Notifier(hass, NotifierConfig(
            service=None if service in (NOTIFY_NONE, "", None) else service,
            hourly=options.get(CONF_NOTIFY_HOURLY, True),
            critical=options.get(CONF_NOTIFY_CRITICAL, True),
            skip_quiet_hours=options.get(CONF_NOTIFY_SKIP_QUIET, True),
        ))
        #: Vorige risicostand, om een overgang naar noodstop te herkennen.
        self._previous_risk_state: str | None = None
        #: Opeenvolgende cycli die langer duurden dan het pollinterval.
        self._slow_cycles = 0
        self.executor_notes: list[str] = []

        self.lifecycle = LifecycleController(DrainPolicy.WAIT_THEN_CLOSE)
        self.exits = ExitManager(ExitConfig())
        # 1.7.6: 2000 metingen, en bewaard over een herstart heen (zie
        # _resultaten). Eerst begon de steekproef na elke herstart opnieuw en
        # bepaalde één uitschieter de p99.
        self.latency = LatencyTracker(window=LATENCY_VENSTER)
        self.state = StreamState()
        self.gate = LiveGate().evaluate({}, {}, []).as_dict()

        self.db: TradeDatabase | None = None
        self.run_id: int | None = None
        self.paper: PaperBroker | None = None
        self._candles: Candles | None = None
        self._last_bar_ts: int = 0
        self._last_entry_ts: float = 0.0
        #: Tickets waarvan al een deel is afgeroomd.
        #:
        #: Deze stond alleen in het geheugen. Na een herstart was hij leeg,
        #: waardoor dezelfde positie opnieuw voor de helft gesloten werd - en
        #: bij herhaling tot niets. Gaat nu mee in de bewaarde toestand.
        self._partial_taken: set[str] = set()
        self._open_time_cache: dict[str, datetime] = {}
        self._last_quote: VenueQuote | None = None
        #: 1.7.0: mislukte koersopvragingen op rij, het moment van de laatste
        #: geslaagde, en wat die cyclus teruggaf. Zo blijft bij een losse
        #: time-out het laatste beeld staan in plaats van alles onbeschikbaar.
        self._koers_mislukt: int = 0
        self._laatste_verse_koers_om: datetime | None = None
        self._laatste_data: dict | None = None
        self._last_signal = None
        #: Aantal gesloten trades bij de laatste poortberekening. De poort
        #: herberekenen is duur (meerdere queries), dus dat gebeurt alleen als
        #: er werkelijk iets veranderd is.
        self._gate_trade_count: int = -1
        #: Wat er uit de eigen historie geleerd is.
        self.execution_facts: dict = {}
        self.proposals: list[dict] = []
        self.regime_stats: dict = {}
        self.postmortem: dict = {}
        #: Waarom er een nieuwe run begon, en welke standaardwaarden er
        #: stilzwijgend zijn overgenomen. Beide horen zichtbaar te zijn.
        self.run_changed_because: list[str] = []
        self.adopted_defaults: list[str] = []
        #: Aantal candles dat sinds de vorige positiecontrole is afgesloten.
        self._bars_since_last_check: int = 1
        self._new_bars_this_cycle: int = 0
        #: Bars zelf opbouwen in plaats van historie opvragen.
        # Eén resolver voor een instelling die op twee plekken kan staan. De
        # opties winnen; staat hij daar niet, dan de basisconfiguratie.
        self.candle_setting = resolve(
            entry.data, entry.options, CONF_BUILD_FROM_QUOTES, False,
        )
        self._build_from_quotes: bool = bool(self.candle_setting.effective)
        self._aggregator: QuoteAggregator | None = None
        self._enabled: bool = False
        self._store = StateStore(hass, entry.entry_id)
        self._state = RuntimeState()
        #: 1.7.5: backtest, validatie, lab en sluitingswaarneming, in een eigen
        #: bestand naast de toestand.
        self._results_store = ResultsStore(hass, entry.entry_id)
        self._resultaten_bewaard_om: datetime | None = None
        #: 1.7.5: één cyclus tegelijk, en het afsluiten wacht op een lopende
        #: cyclus voordat de database dichtgaat.
        self._cyclus_slot = asyncio.Lock()
        self._afgesloten = False
        #: 1.7.5: kwam de accountvaluta bij het opstarten niet van de broker
        #: maar uit de laatst bekende waarde? Dan wordt de vingerafdruk van een
        #: run er nooit op aangepast.
        self._valuta_onzeker = False
        #: 1.7.5: kwam de verzendtoestand van de meldingen uit de opslag?
        self._notify_hersteld = False

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.symbol}",
            update_interval=timedelta(
                seconds=max(
                    MIN_UPDATE_SECONDS,
                    _as_int(options.get(CONF_UPDATE_SECONDS), DEFAULT_UPDATE_SECONDS),
                )
            ),
        )

    # -- opstarten ---------------------------------------------------------- #

    async def async_setup(self) -> None:
        """Toestand herstellen, database openen, historie ophalen, afstemmen."""
        instelling = self.candle_setting
        _LOGGER.info(
            "Candlebron: %s (build_from_quotes=%s, uit %s)",
            candle_source(self._build_from_quotes), instelling.effective,
            {"options": "de opties", "data": "de basisconfiguratie",
             "default": "de standaard"}[instelling.origin],
        )
        if instelling.conflicting:
            _LOGGER.warning(
                "build_from_quotes staat in de basisconfiguratie op %s en in de "
                "opties op %s. De opties gelden: de bars worden %s. Wijzig het in "
                "de opties als je iets anders wilt.",
                instelling.configured, instelling.override,
                "zelf opgebouwd uit koersen" if self._build_from_quotes
                else "bij de broker gehaald",
            )
        # Eerst de bewaarde toestand: een noodstop uit een vorige sessie moet
        # gelden vóórdat er ook maar één cyclus draait.
        self._state = await self._store.async_load()
        # De laatst bekende wisselkoers terugzetten. Zonder dit begon elke
        # herstart zonder koers, en tot de eerstvolgende gecorrigeerde trade werd
        # de positiegrootte niet omgerekend.
        # Een bewaarde koers geldt als terugval, met zijn eigen leeftijd. Zonder
        # tijdstip (bewaard door een oudere versie) is de leeftijd onbekend,
        # en dan is hij niet bruikbaar voor een nieuwe positie.
        if self._state.conversion_rate:
            self.conversion.rate = self._state.conversion_rate
            self.conversion.risk_rate = (
                self._state.conversion_risk_rate or self._state.conversion_rate
            )
            self.conversion.rate_source = "persisted"
            self.conversion.rate_timestamp = (
                parse_utc(self._state.conversion_rate_at)
                if self._state.conversion_rate_at else None
            )
            self.conversion.market_closed = self._state.conversion_market_closed
        if self._state.conversion_loss_rate:
            self._loss_fx_rate = self._state.conversion_loss_rate
            self._broker_fx_ref = self._state.conversion_loss_rate
            self._loss_fx_at = (
                parse_utc(self._state.conversion_loss_rate_at)
                if self._state.conversion_loss_rate_at else None
            )
            self.sizing.account_to_instrument = 1.0 / self.conversion.risk_rate
        self._enabled = self._state.enabled
        if self._state.halted:
            # Terugzetten, niet opnieuw uitvoeren: opnieuw uitvoeren logde
            # dezelfde NOODSTOP-regel als de oorspronkelijke, en dat leek een
            # nieuwe detectie. De opslag meldt al dat hij blijft staan.
            self.risk.restore_halt(
                self._state.halt_reason or "noodstop uit vorige sessie"
            )
        self.risk.state.resumes_today = self._state.resumes_today
        self._partial_taken = set(self._state.partial_taken or [])
        self.risk.state.consecutive_losses = self._state.consecutive_losses
        if self._state.day and self._state.day_start_balance is not None:
            from datetime import date as _date
            try:
                self.risk.state.day = _date.fromisoformat(self._state.day)
                self.risk.state.day_start_balance = self._state.day_start_balance
                self.risk.state.trades_today = self._state.trades_today
            except ValueError:
                _LOGGER.debug("Bewaarde handelsdag onleesbaar; opnieuw beginnen")
        # 1.7.7: de laatst betrouwbare saldoreferentie en een eventuele actieve
        # sprong. Na de installatie van 1.7.7 staat hier niets; de eerste
        # meting wordt dan zonder vergelijking de referentie.
        self.saldosprong.herstel(self._state.saldosprong)
        self._herstel_geheugen()

        path = self.hass.config.path(DATABASE_FILENAME)
        self.db = TradeDatabase(path)
        await self.hass.async_add_executor_job(self.db.connect)
        # Eenmalig en idempotent: dollarbedragen die met de verkeerde koers
        # uit het brokerbedrag waren teruggerekend (tot 5.6.2).
        hersteld = await self.hass.async_add_executor_job(
            self.db.repair_broker_settlement_usd
        )
        if hersteld:
            _LOGGER.info(
                "%d trade(s) herrekend met de omrekenkoers van de broker.", hersteld
            )

        # Het archief naast de tradedatabase, in een eigen bestand: bars
        # groeien veel sneller dan trades en horen los opgeruimd te kunnen
        # worden.
        #
        # Zonder deze twee regels bestaat het archief alleen op papier: het
        # veld staat op None, elke bar wordt stil overgeslagen en de diensten
        # melden "Het archief is niet geopend".
        self.archive = BarArchive(self.hass.config.path(ARCHIVE_FILENAME))
        await self.hass.async_add_executor_job(self.archive.connect)
        install_buffered_signals(self.db)

        config = self._run_config()

        # De accountvaluta vóór de vingerafdruk ophalen.
        #
        # Hij zit in de vingerafdruk omdat de positiegrootte ervan afhangt,
        # maar hij werd pas bekend bij de eerste accountopvraging in de
        # handelslus - ruim ná dit punt. De vingerafdruk las dan altijd de
        # standaardwaarde en veranderde dus nooit, waardoor een
        # valutaomschakeling stilzwijgend in dezelfde bewijsfase belandde.
        if self.mode.places_orders:
            bevestigd = False
            try:
                snapshot = await self.venue.account()
                valuta = getattr(snapshot, "currency", None)
                if valuta:
                    self.conversion.account = valuta
                    bevestigd = True
            except VenueError as err:
                _LOGGER.debug(
                    "Accountvaluta nog niet op te halen: %s. De laatst bekende "
                    "waarde geldt.", err,
                )
            if not bevestigd:
                # 1.7.5: niet terugvallen op de standaard "USD". Een korte
                # storing bij de broker tijdens de herstart liet de
                # vingerafdruk dan van valuta wisselen: de run werd "met een
                # gewijzigde standaardwaarde" voortgezet en zijn vingerafdruk
                # overschreven - of er begon zelfs een nieuwe bewijsfase.
                bekend = await self._laatst_bekende_valuta()
                if bekend:
                    self.conversion.account = bekend
                    _LOGGER.info(
                        "Accountvaluta bij het opstarten niet op te halen; de "
                        "laatst bekende (%s) geldt tot de broker antwoordt.", bekend,
                    )
                self._valuta_onzeker = True
            else:
                self._state.account_currency = self.conversion.account

        material = self._fingerprint_material(config)
        config["fingerprint_material"] = material
        fingerprint = self._hash_material(material)

        existing = await self.hass.async_add_executor_job(
            self.db.find_matching_run, fingerprint
        )
        if not existing:
            # Geen exacte match: kijk of er een recente run is die alleen
            # verschilt door een gewijzigde standaardwaarde. Jouw bewijsfase
            # hoort niet op nul te springen omdat ík een default aanpas.
            existing = await self._adoptable_run(material, fingerprint)
        if existing:
            # Zelfde opzet: de lopende bewijsfase voortzetten. Elke herstart een
            # nieuwe run beginnen maakte de eis van dertig dagen onhaalbaar - één
            # Home Assistant-update zette de teller op nul.
            self.run_id = int(existing["id"])
            self.starting_balance = float(existing["starting_balance"])
            self.opening_equity = existing.get("opening_equity_account")
            _LOGGER.info(
                "Bewijsfase voortgezet: run %s, gestart %s",
                self.run_id, existing["started_at"],
            )
        else:
            # De vorige run afsluiten hoort hier, en alleen hier: bij een
            # gewijzigde opzet. Niet bij een herstart - dan zou de volgende
            # start hem niet meer herkennen en telde elke herstart als een
            # nieuwe bewijsfase.
            vorige = await self.hass.async_add_executor_job(
                self.db.latest_open_run
            )
            if vorige:
                await self.hass.async_add_executor_job(
                    self.db.end_run, vorige["id"]
                )

            self.run_id = await self.hass.async_add_executor_job(
                self.db.start_run, self.mode.value, STRATEGY_VERSION,
                self.symbol, config, self.starting_balance, None, fingerprint,
            )
            await self._record_opening_equity()
            _LOGGER.info(
                "Nieuwe bewijsfase gestart (run %s): de opzet is gewijzigd. "
                "Eerdere runs blijven bewaard en staan onderaan het rapport.",
                self.run_id,
            )

        if not self.mode.places_orders:
            # Slippage volgt de aangenomen spread: staat die op nul, dan is de
            # hele kostenkant uitgeschakeld en moet dat consistent zijn.
            spread = getattr(self.venue, "assumed_spread", 0.0)
            self.paper = PaperBroker(
                self.db, self.run_id, self.symbol, self.starting_balance,
                BrokerCosts(
                    commission_per_lot_per_side=0.0,
                    base_slippage=0.0 if spread <= 0 else 0.02,
                    volatility_slippage_factor=0.0 if spread <= 0 else 0.05,
                    size_slippage_per_lot=0.0,
                ),
            )

        # 1.7.5: wat uit de run zelf volgt terugzetten (papersaldo, laatste
        # instap, beginstand van het uurbericht), en wat bewaard was.
        await self._herstel_uit_run()

        # Historie opwarmen. Zonder dit begint elke herstart met een blinde
        # periode van 60 candles - bij 1m een heel uur.
        if self._build_from_quotes:
            self._aggregator = QuoteAggregator.from_dict(
                self._state.bars or {}, self.timeframe
            )
            self._candles = await self._warmup_from_quotes()
            if self._candles is not None:
                self.state = StreamState()
                await self.hass.async_add_executor_job(
                    self.state.warm_up, self._candles
                )
                self._last_bar_ts = self._candles.timestamp[-1]
            _LOGGER.info(
                "Opwarmen uit live koersen: %d bars beschikbaar",
                self._aggregator.bar_count,
            )
            await self._na_opwarmen()
            return

        try:
            self._candles = await self._fetch_warmup()
            self.state = StreamState()
            await self.hass.async_add_executor_job(self.state.warm_up, self._candles)
            self._last_bar_ts = self._candles.timestamp[-1]
            _LOGGER.info(
                "Opgewarmd met %d candles voor %s op %s",
                len(self._candles), self.symbol, self.timeframe,
            )
        except VenueError as err:
            raise UpdateFailed(f"Kon historie niet ophalen: {err}") from err

        await self._na_opwarmen()

    async def _na_opwarmen(self) -> None:
        """Afstemmen, leren en de poort berekenen: het laatste deel van het
        opstarten.

        1.7.5: eerst onbevestigde orders uit de vorige sessie terugzoeken. Een
        order die tijdens de herstart is uitgevoerd, stond anders bij de
        afstemming als onbekende positie en legde de handel stil. Daarna eerst
        leren en dan pas de poort: de poort leest de robuustheid, en die was
        bij het opstarten nog leeg - waardoor de live-poort na elke herstart
        dicht bleef tot er een trade bij kwam, en in live-modus komt die er
        met een dichte poort nooit.
        """
        if self.mode.places_orders and self.executor.has_pending:
            await self._resolve_pending_orders()
        await self._reconcile()
        if self.run_id is not None:
            closed = await self.hass.async_add_executor_job(
                self.db.closed_trades, self.run_id
            )
            await self._relearn(closed)
        await self._refresh_gate()

    async def _warmup_from_quotes(self) -> Candles | None:
        """Bouw bars op uit de koersen die toch al binnenkomen.

        Geeft None zolang er te weinig bars zijn. De integratie draait dan
        gewoon door en meldt via de statussensor hoe lang het nog duurt; falen
        zou hier onterecht zijn, want er is niets mis.
        """
        if self._aggregator is None:
            return None
        if self._aggregator.bar_count < MIN_WARMUP_CANDLES:
            return None
        return self._aggregator.candles(STRATEGY_WINDOW_BARS)

    async def _fetch_warmup(self) -> Candles:
        """Haal historie op, en vraag minder als de broker weigert.

        Hoeveel candles een broker teruggeeft hangt af van het instrument, het
        tijdsframe, de omgeving en soms een weekquotum. IG antwoordt op een te
        grote aanvraag met ``error.price-history.io-error``, wat niet verklapt
        dat het aantal het probleem is.

        Een vast getal is daarom altijd ergens fout. Beter beginnen bij wat je
        wilt en afbouwen tot wat je krijgt: liever een kortere historie dan een
        integratie die niet opstart.
        """
        # Klein beginnen en alleen opschalen als het lukt. Andersom - groot
        # beginnen en afbouwen - verbruikt bij elke mislukte poging opnieuw
        # datapunten uit het quotum van de broker, en juist de eerste poging is
        # dan de duurste.
        attempts = [MIN_WARMUP_CANDLES, 120, 250, WARMUP_CANDLES]
        best: Candles | None = None
        last_error: Exception | None = None

        for count in attempts:
            try:
                candles = await self.venue.candles(
                    self.symbol, self.timeframe, count
                )
            except VenueError as err:
                last_error = err
                if "allowance" in str(err) or "quotum" in str(err).lower():
                    # Verder proberen verbruikt alleen meer van een quotum dat
                    # al op is.
                    _LOGGER.error("Datalimiet van de broker bereikt: %s", err)
                    break
                _LOGGER.debug("Opwarmen met %d candles faalde: %s", count, err)
                continue

            if len(candles) >= MIN_WARMUP_CANDLES:
                best = candles
                if len(candles) < count:
                    # De broker gaf minder dan gevraagd: meer vragen heeft geen
                    # zin en kost alleen datapunten.
                    break
                continue

            last_error = VenueError(
                f"Slechts {len(candles)} candles ontvangen bij een aanvraag van "
                f"{count}; minimaal {MIN_WARMUP_CANDLES} nodig."
            )

        if best is not None:
            if len(best) < WARMUP_CANDLES:
                _LOGGER.warning(
                    "Opgewarmd met %d candles in plaats van %d. "
                    "Langetermijnindicatoren zijn met minder historie minder "
                    "betrouwbaar.", len(best), WARMUP_CANDLES,
                )
            # Ook de historie eindigt bij de bar die nog loopt.
            return closed_only(
                best, datetime.now(timezone.utc).timestamp(), self.timeframe,
            )

        raise VenueError(
            f"Kon geen bruikbare historie ophalen voor {self.symbol} op "
            f"{self.timeframe}. Laatste fout: {last_error}. Probeer een hoger "
            "tijdsframe; dat kost minder datapunten en reikt verder terug."
        )

    async def _relearn(self, trades: list) -> None:
        """Werk bij wat er uit de eigen historie te leren valt.

        Metingen worden toegepast: die vervangen een aanname door een feit.
        Parametervoorstellen worden alleen getoond - een bot die zijn eigen
        drempel bijstelt na een slechte week, past zich aan de ruis van die
        week aan en wordt daarmee instabieler in plaats van beter.
        """
        assumed = getattr(
            self.paper.costs, "base_slippage", 0.02
        ) if self.paper else 0.02

        facts = await self.hass.async_add_executor_job(
            measure_execution, trades, assumed
        )
        self.execution_facts = facts.as_dict()

        # De gemeten slippage wordt gebruikt voor de *verwachting* in de
        # kostenpoort, maar niet teruggezet in het kostenmodel van de
        # papersimulatie.
        #
        # Dat laatste deed ik wel, en het was een terugkoppelingslus: de meting
        # bevat al de volatiliteitscomponent (ATR x factor), en die werd er als
        # nieuwe basis opnieuw bovenop gelegd. Elke ronde telde hij dubbel. Na
        # veertig trades stond de slippage op het zesvoudige en was een
        # winstgevende reeks omgeslagen in een verlies van 224 - allemaal
        # boekhouding, geen markt.
        #
        # Dit is precies de val waar deze module tegen waarschuwt: een systeem
        # dat leert van zijn eigen uitvoer in plaats van van de werkelijkheid.
        if facts.measured_slippage is not None:
            self.strategy_cfg.expected_slippage = facts.measured_slippage
            if self.paper is not None:
                modelled = self.paper.costs.base_slippage + (
                    (self.state.atr.value or 0.0)
                    * self.paper.costs.volatility_slippage_factor
                )
                if modelled > 0 and facts.measured_slippage > modelled * 2:
                    _LOGGER.warning(
                        "Gemeten slippage %.3f is meer dan het dubbele van wat het "
                        "model voorspelt (%.3f). Controleer of de kostenboeking "
                        "klopt voordat je hier conclusies aan verbindt.",
                        facts.measured_slippage, modelled,
                    )

        proposal = await self.hass.async_add_executor_job(
            evaluate_threshold, trades,
            self.strategy_cfg.entry_threshold, [0.30, 0.35, 0.40, 0.50, 0.55, 0.60],
        )
        self.proposals = [proposal.as_dict()] if proposal else []
        if proposal and proposal.accept:
            _LOGGER.info(
                "Voorstel: instapdrempel van %s naar %s. %s",
                proposal.current, proposal.suggested, proposal.reasoning,
            )

        self.regime_stats = await self.hass.async_add_executor_job(
            regime_performance, trades
        )

        # Houdt het resultaat stand over de tijd, of komt het uit één periode?
        # De bewijsfase telt trades; dit toetst of ze iets betekenen.
        robust = await self.hass.async_add_executor_job(
            evaluate_robustness, trades
        )
        self.robustness = robust.as_dict()

        from homeassistant.util import dt as dt_util

        self.periods = build_periods(trades).as_dict()

        # Resultaat per handelssessie. Uitsluitend observatie: er wordt niets
        # gefilterd, want bij vijftig trades per sessie is elk verschil ruis.
        self.sessions = (
            await self.hass.async_add_executor_job(build_sessions, trades)
        ).as_dict()

        # Presteren trades rond publicatietijden anders? Ook dit is alleen
        # waarnemen: het venster wordt niet geblokkeerd.
        self.news_impact = (
            await self.hass.async_add_executor_job(build_news_impact, trades)
        ).as_dict()

        # Verliezen ordenen naar oorzaak. Niet om omstandigheden te vermijden -
        # dat filtert de winnaars mee weg - maar om te zien of ze aan het
        # exitontwerp liggen of aan de markt.
        post = await self.hass.async_add_executor_job(
            analyse_losses, trades,
            # De doel- en stopmultipliers horen bij de strategie, niet bij de
            # exitmanager: die laatste beheert alleen wat er ná de instap
            # gebeurt (break-even, trailing, tijdslimiet).
            self.strategy_cfg.take_profit_atr,
            self.strategy_cfg.stop_loss_atr,
            self.state.atr.value,
        )
        self.postmortem = post.as_dict()

        # Doeltreffers, stoptreffers en onbekend - met teller en noemer. Het
        # onbekende deel staat ernaast, zodat een doeltrefferpercentage niet
        # stilzwijgend een ondergrens is.
        from .learning.exit_stats import exit_stats
        self.exit_stats = exit_stats(trades)

        # Het aantal openstaande schattingen hier ook bijwerken. Anders staat
        # het rapport op nul tot de correctielus voor het eerst draait, en dan
        # lijkt er niets te corrigeren terwijl er trades op een schatting
        # staan.
        if self.run_id is not None:
            geschat = await self.hass.async_add_executor_job(
                self.db.estimated_trades, self.run_id
            )
            self._geschatte_afwikkelingen = len(geschat)
        if post.patterns and post.patterns[0].actionable and post.fixable_share >= 0.25:
            _LOGGER.info("Verliesanalyse: %s", post.conclusion)

    async def _adoptable_run(self, material: dict, fingerprint: str):
        """Zoek een lopende run die alleen verschilt in wat jij niet koos.

        De vingerafdruk hoort te reageren op jóuw keuzes, niet op mijn
        releases. Wordt een standaardwaarde in een nieuwe versie aangepast en
        heb jij die instelling nooit zelf gezet, dan is dat geen wijziging van
        de strategie door jou - en dan mag de teller niet op nul.

        Verschilt er iets dat je wél zelf hebt ingesteld, dan begint er terecht
        een nieuwe run en wordt in het logboek genoemd wát er verschilde.
        """
        recent = await self.hass.async_add_executor_job(self.db.list_runs, 10)
        options_set = set(self.entry.options)

        for run in recent:
            if run.get("ended_at") or run["id"] == 0:
                continue
            try:
                stored = json.loads(run.get("config_json") or "{}")
            except (TypeError, ValueError):
                continue
            previous = stored.get("fingerprint_material")
            if not previous:
                continue

            differences = {
                key for key in set(previous) | set(material)
                if previous.get(key) != material.get(key)
            }
            if not differences:
                continue

            # Onderscheid: heeft de gebruiker deze instelling zelf gezet?
            user_chosen = {
                key for key in differences
                if self._OPTION_FOR.get(key) in options_set
            }
            # Structureel: een ander uitvoeringsgedrag of een andere bron van
            # de bars meet iets anders, ook als de gebruiker niets koos. Zonder
            # deze twee zou een run als 97 - die twee gedragingen mengt - na de
            # update gewoon worden voortgezet.
            structural = differences & {
                "venue", "symbol", "timeframe", "simulated",
                "execution_semantics", "candle_source",
            }

            if user_chosen or structural:
                _LOGGER.info(
                    "Nieuwe bewijsfase: %s gewijzigd. Eerdere runs blijven in "
                    "het rapport staan.", ", ".join(sorted(user_chosen | structural)),
                )
                self.run_changed_because = sorted(user_chosen | structural)
                return None

            if self._valuta_onzeker:
                # 1.7.5: de accountvaluta komt nu niet van de broker maar uit
                # de laatst bekende waarde. Dan de run voortzetten maar de
                # vingerafdruk níet bijwerken: een terugvalwaarde mag nooit
                # vastleggen hoe een run eruitziet. Bij de volgende start met
                # een antwoord van de broker gebeurt dat alsnog, of niet.
                _LOGGER.info(
                    "Bewijsfase voortgezet (%s verschilt); de vingerafdruk "
                    "blijft staan omdat de accountvaluta nog niet door de "
                    "broker is bevestigd.", ", ".join(sorted(differences)),
                )
                self.adopted_defaults = sorted(differences - {"account_currency"})
                return run

            # Alleen standaardwaarden verschillen; run voortzetten en de
            # vingerafdruk bijwerken zodat het de volgende keer meteen matcht.
            _LOGGER.info(
                "Bewijsfase voortgezet ondanks gewijzigde standaardwaarden (%s). "
                "Die heb je niet zelf ingesteld, dus dit telt niet als een "
                "wijziging van de strategie.", ", ".join(sorted(differences)),
            )
            self.adopted_defaults = sorted(differences)
            await self.hass.async_add_executor_job(
                self.db.update_run_fingerprint, run["id"], fingerprint, material
            )
            return run
        return None

    #: Van vingerafdrukveld naar de optienaam waarmee je het zelf instelt.
    _OPTION_FOR = {
        "mode": "mode",
        "entry_threshold": "entry_threshold",
        "regime_switching": "regime_switching",
        "min_edge_multiple": "min_edge_multiple",
        "max_spread": "max_spread",
        "max_spread_atr_ratio": "max_spread_atr_ratio",
        "take_profit": "take_profit_usd",
        "stop_loss": "stop_loss_usd",
        "enforce_hours": "enforce_trading_hours",
        "trading_hours": "trading_start_hour",
        "units": "units",
        "assumed_spread": "assumed_spread",
        "sizing": "risk_based_sizing",
    }

    async def _notify(self, stats: dict) -> None:
        """Stuur meldingen bij een toestandsovergang of op het hele uur.

        Op de *overgang* melden en niet op de toestand: een noodstop duurt tot
        je hem opheft, en zonder dit onderscheid zou elke cyclus dezelfde
        waarschuwing versturen.
        """
        if not self.notifier.enabled:
            return

        payload = {
            "stats": stats,
            "status": build_status({**(self.data or {}), "stats": stats}),
        }

        risk_state = self.risk.state.state.value
        if risk_state == "halted" and self._previous_risk_state != "halted":
            used = self.risk.state.resumes_today
            allowed = self.risk.limits.max_resumes_per_day
            await self.notifier.alert(
                "halt",
                "Gold Scalper: NOODSTOP",
                f"{self.risk.state.halt_reason}\n\n"
                f"Handel ligt stil tot je hervat. Vandaag {used} van {allowed} "
                "hervattingen gebruikt.",
            )
        elif risk_state != "halted" and self._previous_risk_state == "halted":
            self.notifier.clear("halt")
            await self.notifier.alert(
                "resumed", "Gold Scalper: hervat",
                "De noodstop is opgeheven; er wordt weer gehandeld.",
                critical=False,
            )
        self._previous_risk_state = risk_state

        if self.lifecycle.state.value == "diverged":
            await self.notifier.alert(
                "diverged", "Gold Scalper: posities kloppen niet",
                "Database en broker zijn het oneens over open posities. "
                "Handel is geblokkeerd tot dit is opgelost.",
            )
        else:
            self.notifier.clear("diverged")

        if self.executor_notes and any(
            "zonder stop" in note.lower() for note in self.executor_notes
        ):
            await self.notifier.alert(
                "unprotected", "Gold Scalper: positie zonder stop",
                "\n".join(self.executor_notes[:3]),
            )

        if self.notifier.hourly_due():
            await self.notifier.send_hourly(payload)

    def _run_config(self) -> dict:
        """De opzet van een run, zoals die in de database wordt vastgelegd.

        Uit ``async_setup`` gehaald zodat een handmatig gestarte run precies
        dezelfde opzet vastlegt. Twee kopieën van deze samenstelling zouden
        uiteenlopen, en dan zijn runs niet meer vergelijkbaar - terwijl
        vergelijkbaarheid het enige is waar een bewijsfase voor bestaat.
        """
        return {
            "symbol": self.symbol, "timeframe": self.timeframe,
            "mode": self.mode.value, "units": self.units,
            "strategy": STRATEGY_VERSION,
            "venue": self.venue.name,
            # Provenance: welke software, welk uitvoeringsgedrag, welke bron.
            "integration_version": INTEGRATION_VERSION,
            "execution_semantics": EXECUTION_SEMANTICS_VERSION,
            "environment": getattr(self.venue, "environment", None),
            "candle_source": candle_source(self._build_from_quotes),
            "instrument_currency": self.conversion.instrument,
            "risk": {
                "risk_based_sizing": self.sizing.risk_based,
                "risk_per_trade_pct": self.sizing.risk_per_trade_pct,
                "max_daily_loss_pct": self.risk.limits.max_daily_loss_pct,
                "equity_floor_pct": self.risk.limits.equity_floor_pct,
                "max_positions": self.strategy_cfg.max_positions,
            },
            # Wordt door LiveGate gelezen. Zonder dit merkteken zou een
            # geslaagde simulatie de poort kunnen openen.
            "simulated": getattr(self.venue, "is_simulated", False),
            "assumed_spread": getattr(self.venue, "assumed_spread", None),
            "costs_disabled": getattr(self.venue, "costs_disabled", False),
            # Voor het rapport: zonder deze twee kan de tabel geen bedragen in
            # accountvaluta tonen, en dan is hij niet te vergelijken met het
            # overzicht van de broker.
            "account_currency": self.conversion.account,
            "conversion_rate": self.conversion.rate,
        }

    def _fingerprint_material(self, config: dict) -> dict:
        """Hash van alles wat het handelsgedrag bepaalt.

        Wijzigt hier iets, dan zijn de resultaten niet meer vergelijkbaar en
        hoort er een nieuwe run te beginnen. Wijzigt er niets - een herstart,
        een update, een gewijzigde risicolimiet - dan loopt de bewijsfase door.

        Strategieparameters zitten er bewust in: je kunt een strategie niet
        bewijzen terwijl je hem verandert. Risicolimieten zitten er bewust
        níet in; die begrenzen de schade maar veranderen de signalen niet.
        """
        return {
            "venue": config["venue"],
            "symbol": config["symbol"],
            "timeframe": config["timeframe"],
            "strategy": config["strategy"],
            "simulated": config["simulated"],
            "assumed_spread": config["assumed_spread"],
            "units": config["units"],
            "entry_threshold": self.strategy_cfg.entry_threshold,
            "regime_switching": self.strategy_cfg.regime_switching,
            "min_edge_multiple": self.strategy_cfg.min_edge_multiple,
            "enforce_hours": self.strategy_cfg.enforce_trading_hours,
            "real_spread": self.strategy_cfg.real_spread,
            "trading_hours": (
                list(self.strategy_cfg.trading_hours_utc)
                if self.strategy_cfg.enforce_trading_hours else None
            ),
            "max_spread": self.strategy_cfg.max_spread,
            "max_spread_atr_ratio": self.strategy_cfg.max_spread_atr_ratio,
            # De valuta hoort erbij: zodra er wordt omgerekend, verandert de
            # positiegrootte bij hetzelfde risicopercentage. Trades van voor en
            # na die omschakeling zijn niet vergelijkbaar.
            "account_currency": self.conversion.account,
            "take_profit": (
                self.strategy_cfg.take_profit_usd
                or self.strategy_cfg.take_profit_atr
            ),
            "stop_loss": (
                self.strategy_cfg.stop_loss_usd or self.strategy_cfg.stop_loss_atr
            ),
            # Het uitvoeringsgedrag en de bron van de bars horen erbij: dezelfde
            # strategie op zichtbare of onzichtbare posities, of op zelf
            # opgebouwde of van de broker gehaalde bars, meet iets anders.
            "execution_semantics": EXECUTION_SEMANTICS_VERSION,
            "candle_source": candle_source(self._build_from_quotes),
            # De modus hoort erbij: papertrades hebben gemodelleerde kosten,
            # demotrades gemeten. Die in één bewijsfase mengen zou de hele
            # uitkomst waardeloos maken - juist het verschil tussen die twee
            # is wat je wilt meten.
            "mode": self.mode.value,
            # De groottemethode hoort erbij (1.1): vast of uit risico bepaald
            # verandert het resultaat per trade in dollars. Run 99 mengde beide.
            # Het maximum blijft erbuiten: dat is een risicolimiet.
            "sizing": {
                "risk_based": bool(self.sizing.risk_based),
                "risk_per_trade_pct": (
                    float(self.sizing.risk_per_trade_pct) if self.sizing.risk_based else None
                ),
                "scale_with_confidence": bool(self.sizing.scale_with_confidence),
            },
        }

    @staticmethod
    def _hash_material(material: dict) -> str:
        blob = json.dumps(material, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    async def _reconcile(self) -> None:
        """Vergelijk de broker met onze database voordat er iets gebeurt."""
        try:
            broker_positions = await self.venue.positions(self.symbol)
        except VenueError as err:
            _LOGGER.warning("Kon posities niet ophalen bij afstemmen: %s", err)
            broker_positions = []

        open_trades = await self._managed_open_trades(
            [str(p.ticket) for p in broker_positions]
        )
        # Tickets als tekst vergelijken: IG gebruikt sleutels als
        # 'DIAAAAYCJETQ7A8', alleen MetaTrader en OANDA leveren getallen.
        db_tickets = [str(t.broker_ticket) for t in open_trades if t.broker_ticket]

        # 1.7.8: een positie die wij net sloten en die de broker nog even
        # toont, is geen onbekende positie (binnen de genadetermijn).
        onderweg = {
            t for t, leeftijd in self._sluit_leeftijden().items()
            if leeftijd <= SLUIT_GENADE_SECONDEN
        }
        result = await self.lifecycle.reconcile(
            [{"ticket": str(p.ticket), "volume": p.units, "side": p.side}
             for p in broker_positions if str(p.ticket) not in onderweg],
            db_tickets,
        )
        if not result.consistent:
            self.risk.halt(result.message)

    async def _refresh_gate(self) -> None:
        """Herbereken of live handel vrijgegeven mag worden."""
        if self.run_id is None:
            return
        trades = await self.hass.async_add_executor_job(
            self.db.closed_trades, self.run_id
        )
        stats = await self.hass.async_add_executor_job(
            performance.compute_for_run, self.db, self.run_id, trades
        )
        run = await self.hass.async_add_executor_job(self.db.get_run, self.run_id)
        daily = performance.daily_breakdown(trades)
        self.gate = LiveGate().evaluate(
            stats, run or {}, daily, self.robustness
        ).as_dict()

        # De venue mag alleen handelen als álles klopt: live modus, poort open,
        # en de gebruiker heeft de schakelaar bewust omgezet.
        self.venue.supports_trading = bool(
            self._enabled and (
                # Demo: orders sturen zodra de gebruiker het aanzet. Er staat
                # geen geld op het spel en het doel is juist meten.
                self.mode is TradingMode.DEMO
                # Live: alleen als de bewijsfase geslaagd is.
                or (self.mode is TradingMode.LIVE and self.gate["unlocked"])
            )
        )

    # -- bediening ---------------------------------------------------------- #

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def async_set_enabled(self, value: bool) -> None:
        self._enabled = value
        await self._persist()
        await self._refresh_gate()
        await self.async_request_refresh()

    async def _persist(self) -> None:
        """Sla de toestand op die een herstart moet overleven."""
        self._state.enabled = self._enabled
        self._state.halted = self.risk.state.state is TradingState.HALTED
        self._state.halt_reason = self.risk.state.halt_reason
        self._state.consecutive_losses = self.risk.state.consecutive_losses
        self._state.day = self.risk.state.day.isoformat()
        self._state.day_start_balance = self.risk.state.day_start_balance
        self._state.trades_today = self.risk.state.trades_today
        self._state.resumes_today = self.risk.state.resumes_today
        self._state.partial_taken = sorted(self._partial_taken)
        self._state.run_id = self.run_id
        if self._aggregator is not None:
            self._state.bars = self._aggregator.to_dict()
        # 1.7.5: wat verder nog alleen in het geheugen stond.
        self._state.paused_until = (
            self.risk.state.paused_until.isoformat()
            if self.risk.state.state is TradingState.PAUSED
            and self.risk.state.paused_until else None
        )
        self._state.risk_triggered = list(self.risk.state.triggered[-50:])
        self._state.excursions = {
            str(t): {"mfe": float(r.get("mfe", 0.0)), "mae": float(r.get("mae", 0.0))}
            for t, r in self._excursions.items()
        }
        if self.paper is not None:
            self._state.paper_excursions = {
                str(t.id): {"mfe": float(t.mfe or 0.0), "mae": float(t.mae or 0.0)}
                for t in self.paper.open_positions if t.id is not None
            }
        self._state.last_entry_ts = self._last_entry_ts or None
        if not self._valuta_onzeker and self.mode.places_orders:
            self._state.account_currency = self.conversion.account
        self._state.pending_orders = self.executor.export_pending(
            self._context_naar_dict
        )
        self._state.herkansingen = {
            str(t): {
                "pogingen": int(v.get("pogingen", 0)),
                "sinds": (
                    v["sinds"].isoformat() if isinstance(v.get("sinds"), datetime)
                    else v.get("sinds")
                ),
            }
            for t, v in self._herkansingen.items()
        }
        self._state.audit_gemeld = sorted(self._audit_gemeld)
        self._state.notify_sent = self.notifier.export()
        self._state.saldosprong = self.saldosprong.export()
        await self._store.async_save(self._state)
        await self._bewaar_resultaten()

    # -- herstartbestendigheid (1.7.5) -------------------------------------- #

    #: Hoe vaak de sluitingswaarneming tussentijds wordt weggeschreven. De
    #: uitkomsten van diensten gaan meteen; bij afsluiten gaat alles mee.
    RESULTATEN_INTERVAL = timedelta(minutes=15)

    #: Hoe lang het afsluiten wacht op een lopende cyclus.
    AFSLUITEN_WACHT_S = 15.0

    #: Signaalonderdelen die bij het vastleggen van een teruggevonden order
    #: nodig zijn (zie ``_record_broker_open``). Meer wordt er niet bewaard.
    _CONTEXT_ONDERDELEN = (
        "regime", "atr", "adx", "rsi_reversion", "ema_dist", "trend",
        "momentum", "williams_r", "cci",
    )

    def _resultaten(self) -> dict:
        return {
            "closures": self.closures.export(),
            "backtest": self.backtest or {},
            "validation": self.validation or {},
            "lab": self.lab or {},
            # 1.7.6: de latencysteekproef, zodat p99 niet na elke herstart
            # weer op een handvol metingen rust.
            "latency": self.latency.export(),
        }

    async def _bewaar_resultaten(self, direct: bool = False) -> None:
        """Uitkomsten en sluitingswaarneming wegschrijven, begrensd in tempo."""
        nu = datetime.now(timezone.utc)
        if (
            not direct and self._resultaten_bewaard_om is not None
            and nu - self._resultaten_bewaard_om < self.RESULTATEN_INTERVAL
        ):
            return
        self._resultaten_bewaard_om = nu
        try:
            await self._results_store.async_save(self._resultaten())
        except Exception as err:  # noqa: BLE001 - meting mag de lus niet slopen
            _LOGGER.debug("Uitkomsten niet bewaard: %s", err)

    async def async_bewaar_resultaten(self) -> None:
        """Na een backtest, validatie of indicatorlab: meteen bewaren."""
        await self._bewaar_resultaten(direct=True)

    async def _herstel_resultaten(self) -> None:
        data = await self._results_store.async_load()
        if not data:
            return
        self.closures.restore(data.get("closures"))
        self.latency.restore(data.get("latency"))
        for veld in ("backtest", "validation", "lab"):
            waarde = data.get(veld)
            if isinstance(waarde, dict) and waarde and not getattr(self, veld):
                setattr(self, veld, waarde)

    def _herstel_geheugen(self) -> None:
        """Wat uit de bewaarde toestand alleen terug in het geheugen hoeft.

        Vóór de eerste cyclus, net als de noodstop. Alles is optioneel: een
        toestand van een oudere versie heeft deze velden niet.
        """
        st = self._state
        # Pauze na een verliesreeks. Verlopen is niet erg: de eerste toets
        # hervat dan vanzelf, precies zoals zonder herstart.
        if st.paused_until and not st.halted:
            moment = _veilig_utc(st.paused_until)
            if moment is not None:
                self.risk.state.state = TradingState.PAUSED
                self.risk.state.paused_until = moment
        if st.risk_triggered:
            self.risk.state.triggered = [str(r) for r in st.risk_triggered][-50:]
        # De vorige risicostand is de bewaarde: een teruggezette noodstop is
        # geen nieuwe overgang en hoort geen tweede melding te geven.
        self._previous_risk_state = self.risk.state.state.value

        self._excursions = {}
        for ticket, r in (st.excursions or {}).items():
            try:
                self._excursions[str(ticket)] = {
                    "mfe": float(r.get("mfe", 0.0)), "mae": float(r.get("mae", 0.0)),
                }
            except (AttributeError, TypeError, ValueError):
                continue
        if st.last_entry_ts:
            try:
                self._last_entry_ts = max(self._last_entry_ts, float(st.last_entry_ts))
            except (TypeError, ValueError):
                pass
        self._herkansingen = {}
        for ticket, v in (st.herkansingen or {}).items():
            sinds = _veilig_utc(v.get("sinds")) if isinstance(v, dict) else None
            if sinds is None:
                continue
            try:
                self._herkansingen[str(ticket)] = {
                    "pogingen": int(v.get("pogingen", 0)), "sinds": sinds,
                }
            except (TypeError, ValueError):
                continue
        self._audit_gemeld = set(st.audit_gemeld or [])
        self._notify_hersteld = self.notifier.restore(st.notify_sent)
        if st.pending_orders:
            aantal = self.executor.restore_pending(
                st.pending_orders, self._context_uit_dict
            )
            if aantal:
                _LOGGER.warning(
                    "%d onbevestigde order(s) uit de vorige sessie; die worden "
                    "eerst bij de broker teruggezocht. Er gaat geen nieuwe "
                    "order uit tot dat is gebeurd.", aantal,
                )

    async def _herstel_uit_run(self) -> None:
        """Wat uit de database van de lopende run volgt.

        Het papersaldo stond na elke herstart weer op de startbalans, en de
        tijd sinds de laatste instap op "nooit". Beide volgen uit de trades
        van de run zelf; de database is de bron.
        """
        if self.run_id is None or self.db is None:
            return
        await self._herstel_resultaten()
        gesloten = await self.hass.async_add_executor_job(
            self.db.closed_trades, self.run_id
        )
        if self.paper is not None:
            netto = sum(t.net_pnl or 0.0 for t in gesloten)
            kosten = sum(t.total_cost or 0.0 for t in gesloten)
            self.paper.balance = self.paper.starting_balance + netto
            self.paper.cumulative_cost = kosten
            # Uitersten van open papertrades: die staan pas bij het sluiten
            # in de database.
            bewaard = self._state.paper_excursions or {}
            for trade in self.paper.open_positions:
                r = bewaard.get(str(trade.id))
                if not isinstance(r, dict):
                    continue
                try:
                    trade.mfe = max(trade.mfe or 0.0, float(r.get("mfe", 0.0)))
                    trade.mae = min(trade.mae or 0.0, float(r.get("mae", 0.0)))
                except (TypeError, ValueError):
                    continue

        laatste = await self.hass.async_add_executor_job(
            self.db.latest_open_time, self.run_id
        )
        if laatste is not None:
            self._last_entry_ts = max(self._last_entry_ts, laatste.timestamp())

        # Beginstand van het uurbericht uit de run, als er geen bewaarde stand
        # is (oudere versie) of het uurbericht nog nooit een vertrekpunt had.
        if not self._notify_hersteld or not self.notifier.has_hourly_baseline:
            stats = await self.hass.async_add_executor_job(
                performance.compute_for_run, self.db, self.run_id, gesloten,
            )
            self.notifier.seed(stats.get("trades") or 0, stats.get("net_pnl") or 0.0)

        # Uitersten van tickets die niet meer open staan, opruimen.
        if self._excursions:
            open_trades = await self.hass.async_add_executor_job(
                self.db.open_trades_by_tickets, list(self._excursions)
            )
            nog_open = {str(t.broker_ticket) for t in open_trades if t.broker_ticket}
            self._excursions = {
                t: r for t, r in self._excursions.items() if t in nog_open
            }

    async def _laatst_bekende_valuta(self) -> str | None:
        """De accountvaluta zoals die het laatst van de broker kwam.

        Eerst de bewaarde toestand; anders de vingerafdruk of de opening van de
        laatste open run. Niet de ``account_currency`` in de runconfiguratie:
        die werd vóór de opvraging samengesteld en bevat de standaard.
        """
        if self._state.account_currency:
            return str(self._state.account_currency)
        try:
            run = await self.hass.async_add_executor_job(self.db.latest_open_run)
        except Exception:  # noqa: BLE001
            return None
        if not run:
            return None
        try:
            materiaal = json.loads(run.get("config_json") or "{}").get(
                "fingerprint_material"
            ) or {}
        except (TypeError, ValueError, AttributeError):
            materiaal = {}
        return materiaal.get("account_currency") or run.get("account_currency")

    def _context_naar_dict(self, context) -> dict | None:
        """Ordercontext (signaal, koers, richting, moment) als platte gegevens."""
        signal, quote, side, moment = context
        onderdelen = {}
        for naam in self._CONTEXT_ONDERDELEN:
            waarde = (getattr(signal, "components", None) or {}).get(naam)
            if isinstance(waarde, bool) or waarde is None:
                continue
            if isinstance(waarde, (int, float)):
                if waarde == waarde and abs(waarde) != float("inf"):
                    onderdelen[naam] = float(waarde)
            elif isinstance(waarde, str):
                onderdelen[naam] = waarde
        return {
            "direction": int(getattr(signal, "direction", 0) or 0),
            "score": float(getattr(signal, "score", 0.0) or 0.0),
            "confidence": float(getattr(signal, "confidence", 0.0) or 0.0),
            "stop_loss": getattr(signal, "stop_loss", None),
            "take_profit": getattr(signal, "take_profit", None),
            "components": onderdelen,
            "bid": float(quote.bid), "ask": float(quote.ask),
            "quote_time": quote.time.isoformat(),
            "side": side,
            "moment": moment.isoformat(),
        }

    def _context_uit_dict(self, data: dict):
        """Terug naar de vorm die ``_resolve_pending_orders`` verwacht."""
        from .strategy.scalping import ScalpSignal

        signal = ScalpSignal(
            direction=int(data.get("direction", 0)),
            score=float(data.get("score", 0.0)),
            confidence=float(data.get("confidence", 0.0)),
            should_trade=True, reject_reason=None,
            reason="onbevestigde order uit de vorige sessie",
            stop_loss=data.get("stop_loss"), take_profit=data.get("take_profit"),
            components=dict(data.get("components") or {}),
        )
        quote = VenueQuote(
            bid=float(data["bid"]), ask=float(data["ask"]),
            time=parse_utc(data["quote_time"]),
        )
        side = str(data["side"])
        if side not in ("buy", "sell"):
            raise ValueError(f"onbekende richting {side!r}")
        return signal, quote, side, parse_utc(data["moment"])

    async def async_prepare_shutdown(self) -> dict:
        """Wikkel af zodat HA veilig herstart kan worden."""
        result = await self.lifecycle.drain(self._open_positions, self._close_position)
        await self.async_request_refresh()
        return result.as_dict()

    async def async_close_all(self) -> None:
        for position in await self._open_positions():
            await self._close_position(position, "handmatig")
        await self.async_request_refresh()

    async def async_new_run(self, note: str | None = None) -> int:
        """Begin bewust een nieuwe bewijsfase.

        Tot nu toe begon een run alleen als de vingerafdruk wijzigde - dus als
        je een instelling aanpaste. Maar er is een geval waarin je opnieuw wilt
        beginnen zonder iets aan de strategie te veranderen: wanneer blijkt dat
        de meting fout was.

        Dat gebeurde: de uitstapprijzen van door de broker gesloten posities
        werden op de ontdekkingskoers afgerekend in plaats van op de werkelijke
        prijs. Alle resultaten daaruit zijn onbruikbaar, terwijl de strategie
        ongewijzigd is.

        Zonder deze dienst zou je een instelling moeten verzinnen om aan te
        passen, en dan meet je twee dingen tegelijk.
        """
        vorige = self.run_id
        await self.hass.async_add_executor_job(self.db.flush_signals)

        if vorige is not None:
            await self.hass.async_add_executor_job(self.db.end_run, vorige)

        config = self._run_config()
        materiaal = self._fingerprint_material(config)
        config["fingerprint_material"] = materiaal
        fingerprint = self._hash_material(materiaal)

        self.run_id = await self.hass.async_add_executor_job(
            self.db.start_run, self.mode.value, STRATEGY_VERSION,
            self.symbol, config, self.starting_balance,
            note or "handmatig gestart", fingerprint,
        )
        await self._record_opening_equity()
        _LOGGER.warning(
            "Nieuwe bewijsfase gestart (run %s), de vorige (%s) is afgesloten. "
            "Reden: %s. Eerdere runs blijven bewaard en staan onderaan het "
            "rapport.",
            self.run_id, vorige, note or "handmatig gestart",
        )
        await self.async_request_refresh()
        return self.run_id

    async def async_reset_day(self) -> str:
        """Begin de handelsdag opnieuw, zonder op middernacht te wachten."""
        balance = self.starting_balance
        if self.paper is not None:
            balance = self.paper.balance
        elif self.mode.places_orders:
            try:
                snapshot = await self.venue.account()
                balance = snapshot.equity
            except VenueError as err:
                _LOGGER.warning(
                    "Kon het saldo niet ophalen; er wordt gerekend met de "
                    "startbalans: %s", err,
                )

        # 1.7.7: geen dagijkpunt op een onverklaarde saldosprong.
        bericht = self.risk.reset_day(self.saldosprong.betrouwbaar(balance))
        await self._persist()
        await self.async_request_refresh()
        return bericht

    async def async_resume(self) -> bool:
        """Hervat na een noodstop. Bewust handmatig.

        Geeft het huidige saldo mee zodat de daglimiet vanaf nu telt; anders
        zou de volgende cyclus dezelfde overschrijding zien en meteen weer
        stoppen.
        """
        balance = self.starting_balance
        if self.paper is not None:
            balance = self.paper.balance
        elif self.mode.places_orders:
            try:
                snapshot = await self.venue.account()
                balance = snapshot.equity
            except VenueError as err:
                _LOGGER.warning(
                    "Kon het saldo niet ophalen voor het nieuwe dagijkpunt: %s. "
                    "Er wordt gerekend met de startbalans.", err,
                )

        # 1.7.7: geen dagijkpunt op een onverklaarde saldosprong.
        allowed, message = self.risk.manual_resume(
            self.saldosprong.betrouwbaar(balance)
        )
        if not allowed:
            _LOGGER.warning("Hervatten geweigerd: %s", message)
            return False

        await self._persist()
        await self._reconcile()
        await self.async_request_refresh()
        return True

    # -- posities ----------------------------------------------------------- #

    async def _open_positions(self, refresh: bool = False) -> list:
        """Open posities, uit de bron die ze werkelijk houdt.

        Binnen één cyclus wordt het antwoord hergebruikt. Zodra de posities bij
        de broker staan in plaats van in de papersimulatie, kost elke aanroep
        een netwerkverzoek van rond de honderd milliseconde - en de lus deed er
        vier per cyclus. Dat verviervoudigde de cyclustijd en leverde bij tien
        seconden verversen vierentwintig verzoeken per minuut op, precies waar
        rate limits vandaan komen.

        ``refresh`` forceert een verse ophaling; nodig na het openen of sluiten
        van een positie, want dan is het antwoord verouderd.

        In demomodus staan de posities bij de broker, niet in de
        papersimulatie. Hier op LIVE toetsen in plaats van op places_orders
        liet de strategie in demomodus altijd nul posities zien, waardoor de
        limiet van één positie nooit aansloeg: er kwam elke cyclus een nieuwe
        bij, allemaal dezelfde kant op. Vier gestapelde longs in een dalende
        markt.
        """
        if not self.mode.places_orders:
            # De papersimulatie houdt ze in het geheugen; cachen heeft geen zin.
            return self.paper.open_positions if self.paper else []

        if not refresh and self._positions_cache is not None:
            return self._positions_cache

        self._positions_cache = await self.venue.positions(self.symbol)
        return self._positions_cache

    async def _close_position(self, position, reason: str) -> None:
        if self.mode.places_orders:
            ticket = str(position.ticket)
            resultaat = await self.venue.close(position.ticket)
            self._positions_cache = None
            # 1.7.8: alleen als gesloten boeken wat de broker aannam. Een
            # geweigerd verzoek werd tot nu toe toch afgeboekt: dan stond de
            # positie open bij de broker en dicht in de database - onbewaakt.
            if not getattr(resultaat, "success", False):
                _LOGGER.error(
                    "Sluiten van %s (%s) niet aangenomen door de broker: %s. "
                    "De positie blijft open en bewaakt.", ticket, reason,
                    getattr(resultaat, "error", None) or "geen bevestiging",
                )
                return
            # setdefault: een herhaald verzoek verlengt de termijn niet.
            self._sluitverzoeken.setdefault(ticket, time.monotonic())
            if self._last_quote is not None:
                await self._record_broker_close(
                    position, self._last_quote, reason,
                    datetime.now(timezone.utc),
                )
            return
        if self.paper and self._last_quote:
            self.paper.close_position(position, self._paper_quote(self._last_quote), reason)

    def _paper_quote(self, quote: VenueQuote) -> PaperQuote:
        """Vertaal een venue-quote naar een paper-quote met de uitersten erbij.

        De high en low komen uit de candles die sinds de vorige cyclus zijn
        afgesloten. Zonder die twee toetst de simulatie stops alleen op het
        pollmoment en mist zo ongeveer 12% van de stops - allemaal in je
        voordeel, wat de bewijsfase waardeloos maakt.
        """
        high = low = None
        if self._candles is not None and self._candles.high:
            bars = max(1, self._bars_since_last_check)
            high = max(self._candles.high[-bars:])
            low = min(self._candles.low[-bars:])
            # De actuele koers hoort er ook bij: hij kan buiten de laatste
            # afgesloten candle liggen.
            high = max(high, quote.ask)
            low = min(low, quote.bid)
        return PaperQuote(
            bid=quote.bid, ask=quote.ask, time=quote.time,
            atr=self.state.atr.value or 0.0, high=high, low=low,
        )

    # -- de lus ------------------------------------------------------------- #

    async def _async_refresh(self, *args, **kwargs) -> None:
        """Eén cyclus tegelijk, en niet meer na het afsluiten (1.7.5).

        Om de verversing van Home Assistant heen, zodat de cyclus zelf
        ongewijzigd blijft. Het afsluiten wacht op dit slot: de database gaat
        niet dicht terwijl een cyclus er nog in schrijft.
        """
        if self._afgesloten:
            return
        async with self._cyclus_slot:
            if self._afgesloten:
                return
            await super()._async_refresh(*args, **kwargs)

    async def _async_update_data(self) -> dict:
        budget = LatencyBudget()
        budget.mark("start")
        self._positions_cache = None

        try:
            quote = await self.venue.quote(self.symbol)
        except VenueError as err:
            # Bij een gesloten markt zonder eerdere koers is er niets mis; dan
            # wachten tot de handel opent in plaats van blijven falen. HA zou
            # anders elke cyclus een foutmelding loggen voor een situatie die
            # zichzelf oplost.
            if "gesloten" in str(err).lower() and self._last_quote is not None:
                quote = self._last_quote
                _LOGGER.debug("Markt gesloten; laatst bekende koers aangehouden")
            else:
                # 1.7.0: een losse mislukte opvraging houdt het laatste beeld
                # vast. Er wordt in deze cyclus niets beslist: geen instap,
                # geen stop verplaatsen, geen sluiting op een oude koers. De
                # stops en doelen staan bij de broker en werken gewoon door.
                vastgehouden = self._houd_laatste_data(err)
                if vastgehouden is not None:
                    return vastgehouden
                raise UpdateFailed(f"Geen koers beschikbaar: {err}") from err
        self._last_quote = quote
        budget.mark("quote")

        now = datetime.now(timezone.utc)
        if self._koers_mislukt:
            _LOGGER.info(
                "Koers weer beschikbaar na %d mislukte opvraging(en).",
                self._koers_mislukt,
            )
            self._koers_mislukt = 0
        self._laatste_verse_koers_om = now
        tick_age = (now - quote.time).total_seconds()

        # -- bars bijwerken --------------------------------------------------- #
        if self._build_from_quotes:
            await self._update_from_quote(quote)
        else:
            await self._maybe_update_candles()
        self._bars_since_last_check = max(1, self._new_bars_this_cycle)
        budget.mark("candles")

        open_positions_precheck = bool(await self._open_positions())

        # Posities die de broker zélf sloot - op de server-side stop of het
        # doel - verdwijnen zonder dat wij er iets van merken. Zonder deze
        # afstemming blijft de rij eeuwig open in de database en telt hij
        # nergens in mee, want de bewijsfase kijkt naar gesloten trades.
        if self.mode.places_orders and quote.tradeable:
            await self._settle_vanished_positions(quote, now)
            # 1.7.3: verse schattingen binnen enkele minuten nog een paar keer
            # bij de broker navragen. Alleen opvragen en boeken.
            await self._herkans_voorlopige_afwikkelingen(now)

            # Eerder geschatte afwikkelingen bijwerken. Het overzicht van de
            # broker loopt uren achter, dus de eerste poging mislukt vaak en
            # een tweede kans is onmisbaar.
            # Elke tien cycli, en de eerste keer meteen.
            #
            # Dertig cycli is tien minuten, en dat is te lang om twee redenen:
            # bij een herstart staan er vaak al schattingen uit de vorige
            # sessie, en zolang de correctie niet heeft gedraaid blijft ook de
            # wisselkoers onbekend - die komt uit dezelfde lus.
            self._correctie_teller += 1
            if self._correctie_teller == 1 or self._correctie_teller >= 10:
                self._correctie_teller = 2
                await self._correct_estimated_settlements(now)

            # Eenmaal per handelsdag afstemmen, na 06:00 UTC: dan heeft de
            # broker de nacht verwerkt.
            dag = trading_day(parse_utc(now)).isoformat()
            # Daarnaast elk uur: het overzicht van de broker loopt uren achter,
            # en zonder tussentijdse afstemming bleven de bedragen van vandaag
            # tot morgen benaderingen.
            #
            # Staat er nog iets open - een afwijking of een trade die de broker
            # nog niet verwerkte - dan elk kwartier (1.4). Anders bleef een
            # afwijking die zichzelf al had opgelost tot een uur zichtbaar, en
            # werden late transacties pas op het volgende hele uur afgerekend.
            vorige = self.reconciliation or {}
            open_eind = bool(
                vorige.get("afwijkingen") or vorige.get("nog_niet_verwerkt")
            )
            interval = 900 if open_eind else 3600
            uur_voorbij = (
                self._afgestemd_om is None
                or (now - self._afgestemd_om).total_seconds() >= interval
            )
            if (self._afgestemd_op != dag and now.hour >= 6) or uur_voorbij:
                self._afgestemd_op = dag
                self._afgestemd_om = now
                try:
                    await self.async_reconcile()
                except Exception as err:  # noqa: BLE001 - controle mag de lus niet slopen
                    _LOGGER.debug("Afstemming niet gelukt: %s", err)

        # -- open posities beheren, vóór alles anders ------------------------ #
        # Bij een gesloten markt niet ingrijpen: een stop verplaatsen of een
        # positie sluiten op een koers van uren geleden is erger dan wachten.
        if quote.tradeable:
            await self._manage_open_positions(quote, now)

        # De wisselkoers elke cyclus verversen - met een pauze van vijf minuten
        # - en niet pas bij een handelssignaal. Eerst werd hij alleen vlak vóór
        # een instap opgehaald: de diagnostiek toonde dan "geblokkeerd" tot het
        # eerste signaal, en werkte het ophalen niet, dan was dat signaal
        # meteen verloren. Ook bij een gesloten goudmarkt: dan wordt
        # vastgelegd of EUR/USD dicht is, en dat heeft de 72-uursregel nodig.
        await self._refresh_fx(now)
        budget.mark("exits")

        # -- rooster als tweede bron ------------------------------------------ #
        #
        # Niet alleen op het veld van de broker vertrouwen. Klopt dat veld niet,
        # dan handelt de bot op verouderde koersen zonder dat iets het merkt.
        # Bij onenigheid wint 'gesloten': een gemiste kans kost niets, handelen
        # op een koers van uren geleden kan alles kosten.
        tradeable = quote.tradeable
        self.schedule_note = None
        # Altijd vastleggen wanneer de broker sluit, ook als het rooster uit
        # staat: dit is de enige bron die niet op een aanname rust.
        self.closures.record(now, quote.tradeable)

        if self._use_schedule:
            tradeable, note = cross_check(quote.tradeable, SPOT_GOLD, now)
            if note:
                self.schedule_note = note
                # Eén keer per afwijking loggen, niet per cyclus.
                #
                # Op Labor Day sloten de Amerikaanse markten vervroegd; het
                # rooster kent geen feestdagen en meldde dat terecht. Maar de
                # melding stond 903 keer in het logboek over drieënhalf uur -
                # dezelfde tekst, elke twintig seconden. Zo'n stortvloed maakt
                # het logboek onbruikbaar voor de meldingen die er wél toe doen.
                if note != self._last_schedule_note:
                    _LOGGER.warning("Handelstijden: %s", note)
                    self._last_schedule_note = note
            elif self._last_schedule_note is not None:
                _LOGGER.info(
                    "Handelstijden: broker en rooster zijn het weer eens."
                )
                self._last_schedule_note = None

        # -- periodieke controle op onbeschermde posities --------------------- #
        # Een stop kan verdwijnen doordat een wijziging half doorkwam of doordat
        # de broker hem introk. Zonder controle merk je dat pas als het geld weg
        # is. Elke tiende cyclus volstaat; vaker belast de broker-API onnodig.
        # Niet vergelijken bij een gesloten markt: er kan niets bewegen, dus
        # elk verschil is er een van vóór de sluiting. Wel blijven controleren
        # zou alleen ruis opleveren in het weekend.
        if self.mode.places_orders and open_positions_precheck and quote.tradeable:
            self._audit_counter += 1
            if self._audit_counter >= 10:
                self._audit_counter = 0
                await self._audit_against_broker()

        # -- boekhouding ----------------------------------------------------- #
        #: 1.7.7: alleen een werkelijk gemeten equity telt voor de
        #: saldosprongbewaking; de terugval op de startbalans bij een mislukte
        #: opvraging is geen meting.
        gemeten_equity: float | None = None
        if self.paper:
            self.paper.update_positions(self._paper_quote(quote))
            balance, equity = self.paper.balance, self.paper.equity(self._paper_quote(quote))
            gemeten_equity = equity
        else:
            try:
                snapshot = await self.venue.account()
                balance, equity = snapshot.balance, snapshot.equity
                self.current_equity = equity
                gemeten_equity = equity
            except VenueError:
                balance = equity = self.starting_balance

        # Eerst onbevestigde orders terugzoeken: vóór de telling, zodat een
        # teruggevonden positie meetelt en vastgelegd is voordat de strategie
        # opnieuw beslist.
        if self.mode.places_orders and self.executor.has_pending:
            await self._resolve_pending_orders()

        open_positions = await self._open_positions()
        # Onbevestigde orders tellen mee als open positie: ze kunnen er één
        # zijn. Anders houdt de positielimiet niet zolang de broker ze nog niet
        # in zijn lijst toont.
        aantal_open = len(open_positions) + (
            len(self.executor.pending) if self.mode.places_orders else 0
        )

        # 1.7.7: saldosprong zonder trade herkennen, vóór de risicotoets zodat
        # een dagwissel in deze cyclus al op de betrouwbare referentie rolt.
        self.saldosprong.meet(
            now, gemeten_equity,
            positie_open=bool(aantal_open or open_positions_precheck),
            sluitingen=self.risk.sluitingen,
        )

        # -- signaal --------------------------------------------------------- #
        # Zelfgebouwde bars onderschatten de uitersten; zonder correctie is de
        # kostenpoort te streng en mis je kansen.
        if self._build_from_quotes and self._aggregator is not None:
            self.strategy_cfg.atr_correction = self._aggregator.correction

        signal = None
        if self._candles is not None and len(self._candles) >= 60:
            # Richting van de lopende positie meegeven, zodat een geweigerd
            # signaal uitgesplitst kan worden naar 'zelfde richting' of
            # 'tegengesteld'. Zonder dat verschil zie je alleen dat er niets
            # gebeurde, niet of je systeem ondertussen van mening veranderde.
            side = 0
            if open_positions:
                first = open_positions[0]
                side = 1 if getattr(first, "side", "buy") == "buy" else -1

            signal = await self.hass.async_add_executor_job(
                evaluate, self._candles, quote.bid, quote.ask, self.strategy_cfg,
                now.hour, aantal_open,
                now.timestamp() - self._last_entry_ts, side,
            )
            self._last_signal = signal
        budget.mark("signal")

        # -- mag er gehandeld worden? ---------------------------------------- #
        reject_reason = None
        if signal is not None:
            if not self.lifecycle.accepts_new_positions:
                reject_reason = f"levenscyclus: {self.lifecycle.state.value}"
            elif not self._enabled:
                reject_reason = "handel staat uit"
            elif self.mode.places_orders and self.executor.has_pending:
                reject_reason = "onbevestigde order: eerst terugvinden"
            elif not signal.should_trade:
                reject_reason = signal.reject_reason
            else:
                fx_ok, fx_reden = self.conversion.usable_for_entry(now)
                allowed, why = self.risk.can_open(
                    now=now, balance=balance, equity=equity,
                    starting_balance=self.starting_balance,
                    open_positions=aantal_open,
                    volume=self.units / CONTRACT_SIZE,
                    spread=quote.spread, last_tick_age=tick_age,
                    market_open=tradeable,
                    atr=self.state.atr.value,
                    opening_equity=self.opening_equity,
                )
                reject_reason = None if allowed else f"risico: {why}"

                # Geen nieuwe positie zonder bruikbare wisselkoers wanneer er
                # omgerekend moet worden: de positiegrootte is dan niet te
                # garanderen. Alleen nieuwe posities - exitbeheer, afstemming
                # en veiligheid lopen gewoon door.
                if allowed and not fx_ok:
                    allowed = False
                    reject_reason = f"wisselkoers: {fx_reden}"
                    if self._fx_block_reason != fx_reden:
                        self._fx_block_reason = fx_reden
                        _LOGGER.warning(
                            "Geen nieuwe posities: %s (bron %s).",
                            fx_reden, self.conversion.rate_source or "geen",
                        )
                elif fx_ok:
                    self._fx_block_reason = None

                # Kort voor sluiting geen nieuwe posities. Een trade met een
                # tijdslimiet van vijf minuten die om 22:58 opengaat, wordt door
                # de sluiting overvallen: je zit dan tot de volgende sessie
                # vast, en die opent met een gat waar geen stop tussen zit.
                if allowed and self._use_schedule and self._close_buffer > 0:
                    resterend = minutes_until_close(SPOT_GOLD, now)
                    if resterend is not None and resterend <= self._close_buffer:
                        allowed = False
                        reject_reason = (
                            f"nog {resterend:.0f} minuten tot sluiting; een "
                            "nieuwe positie zou door de sluiting worden "
                            "overvallen"
                        )

            if reject_reason is None and signal.should_trade:
                await self._open_position(signal, quote, now)

            await self.hass.async_add_executor_job(
                self.db.log_signal, self.run_id, signal.score, signal.confidence,
                "buy" if signal.direction > 0 else "sell" if signal.direction < 0 else "flat",
                None, quote.spread, reject_reason is None and signal.should_trade,
                reject_reason, signal.components,
            )

        await self.hass.async_add_executor_job(
            self.db.record_equity, self.run_id, balance, equity,
            len(open_positions), await self._ledger_cost(),
        )
        budget.mark("bookkeeping")
        self.latency.record(budget)

        stats = await self.hass.async_add_executor_job(
            performance.compute_for_run, self.db, self.run_id, None,
            self.account_drawdown or None,
        )

        # Poort bijwerken zodra er trades bij zijn gekomen. Zonder dit blijft
        # de uitkomst staan zoals hij bij het opstarten was, en meldt hij na
        # duizend trades nog steeds "0 trades in de bewijsfase" - precies het
        # getal waar de hele bewijsfase op steunt. Alleen bij verandering,
        # want de berekening kost meerdere queries.
        trade_count = stats.get("trades", 0)
        if trade_count != self._gate_trade_count:
            self.account_drawdown = await self.hass.async_add_executor_job(
                self.db.account_drawdown, self.run_id
            )
            # Eén keer ophalen en tweemaal gebruiken: de poort en de leerlaag
            # hebben dezelfde tradelijst nodig, en die tabel inlezen is de
            # duurste stap in deze cyclus.
            closed = await self.hass.async_add_executor_job(
                self.db.closed_trades, self.run_id
            )
            # Eerst leren, dan de poort: de poort leest de robuustheid die
            # het leren berekent (1.7.5; omgekeerd keek hij naar die van de
            # vorige keer, en na een herstart naar niets).
            await self._relearn(closed)
            await self._refresh_gate()
            self._gate_trade_count = trade_count
            # 1.7.5: met de drawdown op de equity, zoals bovenaan deze cyclus.
            # Zonder viel hij weg in elke cyclus waarin het aantal trades
            # veranderde - en dus in de eerste cyclus na elke herstart.
            stats = await self.hass.async_add_executor_job(
                performance.compute_for_run, self.db, self.run_id, closed,
                self.account_drawdown or None,
            )

        # Elke cyclus bewaren, niet alleen bij afsluiten: een noodstop die
        # halverwege afgaat mag niet verloren gaan als HA daarna hardhandig
        # stopt.
        # Een cyclus die langer duurt dan het pollinterval betekent dat de
        # volgende al had moeten beginnen. Eén keer is ruis; herhaling niet.
        cycle_ms = budget.total_ms() or 0.0
        if cycle_ms > self.update_interval.total_seconds() * 1000:
            self._slow_cycles += 1
            if self._slow_cycles in (5, 25, 100):
                _LOGGER.warning(
                    "%d cycli duurden langer dan het verversingsinterval "
                    "(laatste %.0f ms tegen %.0f ms interval). Overweeg een "
                    "ruimer interval; sneller pollen levert bij bars van %s "
                    "toch geen nieuwe signalen op.",
                    self._slow_cycles, cycle_ms,
                    self.update_interval.total_seconds() * 1000, self.timeframe,
                )
        else:
            self._slow_cycles = 0

        await self._persist()
        await self._notify(stats)

        columns = ("timestamp", "open", "high", "low", "close", "volume")
        candle_lengths = (
            {len(getattr(self._candles, f)) for f in columns}
            if self._candles is not None else set()
        )

        data = {
            "quote": quote,
            "price": quote.mid,
            # 1.7.0: verse koers; bij een vastgehouden cyclus staan hier de
            # leeftijd en het aantal mislukte opvragingen.
            "koers_verouderd": False,
            "koers_leeftijd_seconden": None,
            "koers_mislukt_op_rij": 0,
            "koers_fout": None,
            "candles": len(self._candles) if self._candles else 0,
            "market_open": quote.tradeable,
            "quote_age_seconds": round(tick_age, 1),
            "candles_consistent": len(candle_lengths) <= 1,
            "spread": quote.spread,
            "atr": self.state.atr.value,
            "signal": signal,
            "reject_reason": reject_reason,
            "balance": balance,
            "equity": equity,
            # 1.7.7: onverklaarde saldosprong (dataprobleem).
            "saldosprong": self.saldosprong.as_dict(),
            "open_positions": open_positions,
            "stats": stats,
            "gate": self.gate,
            "risk": self.risk.as_dict(),
            "lifecycle": {
                **self.lifecycle.as_dict(),
                # 1.5.0: dezelfde bron als de binaire sensor Veilig herstarten
                "safe_to_restart": veilig_herstarten(open_positions, self.lifecycle),
                "levenscyclus_afgewikkeld": self.lifecycle.safe_to_restart,
            },
            "latency": self.latency.stats(),
            "ig_requests": (
                self.venue.request_stats() if hasattr(self.venue, "request_stats") else None
            ),
            "executor_notes": self.executor_notes,
            "warmup": (
                self._aggregator.progress(MIN_WARMUP_CANDLES)
                if self._aggregator is not None else None
            ),
            "build_from_quotes": self._build_from_quotes,
            "sizing": self.last_sizing,
            "periods": self.periods,
            "sessions": self.sessions,
            "news_impact": self.news_impact,
            "backtest": self.backtest,
            "audit": self.audit,
            "schedule_note": self.schedule_note,
            "closures": self.closures.as_dict(),
            "conversion": self.conversion.as_dict(),
            # Meetkwaliteit, voor sensoren en overzicht: zonder dit stond alles
            # wat 5.4 meet alleen in de diagnostiek.
            "balances": {
                **self.risk.floor_breakdown(
                    self.starting_balance, self.opening_equity, equity,
                ),
                "account_currency": self.conversion.account,
            },
            "exit_stats": self.exit_stats,
            "reconciliation": self.reconciliation,
            "candle_setting": self.candle_setting.as_dict(),
            "ledger_costs": self.ledger_cost_info,
            "validation": self.validation,
            "estimated_settlements": self._geschatte_afwikkelingen,
            "archive": (
                self.archive.stats(self.symbol, self.timeframe).as_dict()
                if self.archive is not None else None
            ),
            "closure_hint": self.closures.suggest_break(),
            "run_changed_because": self.run_changed_because,
            "adopted_defaults": self.adopted_defaults,
            "learning": {
                "execution": self.execution_facts,
                "proposals": self.proposals,
                "regimes": self.regime_stats,
                "losses": self.postmortem,
                "robustness": self.robustness,
            },
            "mode": self.mode.value,
            "requested_mode": self.requested_mode.value,
            "mode_override_reason": self.mode_override_reason,
            "enabled": self._enabled,
        }
        self._laatste_data = data
        return data

    def _houd_laatste_data(self, err: Exception) -> dict | None:
        """Laatste gegevens aanhouden na een mislukte koersopvraging (1.7.0).

        Live op 7 oktober: de koersopvraging bij IG liep zes keer in
        anderhalf uur tegen de time-out van 6 s aan, steeds één cyclus. Elke
        keer werd álles onbeschikbaar, ook de noodstop - precies de indicator
        die je bij een storing wilt blijven zien.

        Geeft een kopie van de laatste gegevens terug met ``koers_verouderd``
        aan, of None als de drempel voorbij is (dan de oude storing). De
        cyclus beslist niets: geen signaal, geen instap, geen exitbeheer op
        een oude koers. Stops en doelen staan bij de broker en werken door.
        """
        self._koers_mislukt += 1
        vorige = self._laatste_data
        if vorige is None or self._laatste_verse_koers_om is None:
            return None
        now = datetime.now(timezone.utc)
        leeftijd = (now - self._laatste_verse_koers_om).total_seconds()
        if (
            self._koers_mislukt > KOERS_HOUD_MAX_MISLUKT
            or leeftijd > KOERS_HOUD_MAX_SECONDEN
        ):
            _LOGGER.warning(
                "Koersopvraging %d keer op rij mislukt (laatste verse koers "
                "%.0f s oud); entiteiten worden onbeschikbaar tot de koers "
                "terug is.", self._koers_mislukt, leeftijd,
            )
            return None

        _LOGGER.warning(
            "Koersopvraging mislukt (%d van max. %d op rij): %s. Laatste "
            "gegevens aangehouden (koers %.0f s oud); geen nieuwe posities "
            "en geen exitbeheer tot er een verse koers is.",
            self._koers_mislukt, KOERS_HOUD_MAX_MISLUKT, err, leeftijd,
        )
        data = dict(vorige)
        quote = vorige.get("quote")
        if quote is not None and getattr(quote, "time", None) is not None:
            data["quote_age_seconds"] = round((now - quote.time).total_seconds(), 1)
        data.update({
            "koers_verouderd": True,
            "koers_leeftijd_seconden": round(leeftijd, 1),
            "koers_mislukt_op_rij": self._koers_mislukt,
            "koers_fout": str(err)[:200],
            # Er is in deze cyclus niets geëvalueerd.
            "signal": None,
            "reject_reason": "koers verouderd: geen verse koers van de broker",
            # Noodstop en levenscyclus actueel houden: die veranderen ook
            # zonder koers (handmatig hervatten, afwikkelen).
            "risk": self.risk.as_dict(),
            "lifecycle": {
                **self.lifecycle.as_dict(),
                "safe_to_restart": veilig_herstarten(
                    vorige.get("open_positions"), self.lifecycle
                ),
                "levenscyclus_afgewikkeld": self.lifecycle.safe_to_restart,
            },
            "reconciliation": self.reconciliation,
            "enabled": self._enabled,
        })
        return data

    @property
    def koers_verouderd(self) -> bool:
        """Waar zolang de laatste koersopvraging mislukte (1.7.0)."""
        return self._koers_mislukt > 0

    def _append_candle(self, fresh: Candles, index: int) -> None:
        """Voeg één candle toe en kap de reeks af.

        De zes kolommen worden hier als één geheel behandeld. De vorige versie
        deed het afkappen binnen de lus over de kolommen en toetste daarbij
        steeds op de lengte van ``close``. Gevolg: alleen ``close`` werd
        afgekapt en de andere vijf groeiden door, zodat de kolommen na verloop
        van tijd honderden posities uit de pas liepen. Elke indicator die
        ``close`` met ``high`` of ``low`` combineert - ATR, Bollinger,
        Stochastic, MFI - rekende vanaf dat moment op verschoven data, zonder
        dat er iets zichtbaar misging.

        Daarom staat de afkapstap nu ná het toevoegen van álle kolommen, en
        wordt de uitkomst gecontroleerd.
        """
        if self._candles is None:
            return

        columns = ("timestamp", "open", "high", "low", "close", "volume")
        for field in columns:
            getattr(self._candles, field).append(getattr(fresh, field)[index])

        limit = STRATEGY_WINDOW_BARS
        overflow = len(self._candles.close) - limit
        if overflow > 0:
            for field in columns:
                del getattr(self._candles, field)[:overflow]

        lengths = {len(getattr(self._candles, field)) for field in columns}
        if len(lengths) != 1:
            # Mag niet kunnen na bovenstaande, maar als het toch gebeurt is
            # stil doorrekenen op scheve data erger dan opnieuw beginnen.
            _LOGGER.error(
                "OHLCV-kolommen liepen uit de pas (%s); historie wordt opnieuw "
                "opgehaald bij de volgende cyclus", lengths,
            )
            self._candles = None
            self._last_bar_ts = 0

    def _bar_due(self) -> bool:
        """Kan er sinds de vorige bar een nieuwe zijn afgesloten?

        Zonder deze controle vroeg elke cyclus candles op, ook als er niets
        nieuws kon zijn: bij een verversing van twintig seconden op M5 is dat
        98% verspilling. Brokers rekenen historische koersen per datapunt af,
        en IG's demo-quotum was daardoor binnen een dag op.
        """
        if self._last_bar_ts <= 0:
            return True
        length = BAR_SECONDS.get(self.timeframe, 60)
        elapsed = datetime.now(timezone.utc).timestamp() - self._last_bar_ts
        # ``_last_bar_ts`` is het begin van de laatste AFGESLOTEN bar. De
        # volgende sluit dus twee barlengtes na dat begin. Eén barlengte - zoals
        # eerst - klopte alleen zolang er een lopende bar werd meegenomen; na
        # het weglaten daarvan zou elke cyclus een kwartier lang opnieuw
        # historie opvragen. Marge van een paar seconden: brokers publiceren
        # een bar niet altijd exact op het hele moment.
        return elapsed >= (2 * length + 3)

    async def _update_from_quote(self, quote: VenueQuote) -> None:
        """Voeg de koers toe aan de zelfgebouwde reeks."""
        self._new_bars_this_cycle = 0
        if self._aggregator is None:
            self._aggregator = QuoteAggregator(self.timeframe)

        # Op de mid werken: bid of ask zou elke indicator een halve spread
        # laten schuiven.
        # Bij een gesloten markt niets toevoegen: een weekend levert anders
        # honderden bars met dezelfde prijs op, en die drukken de ATR naar nul.
        closed = self._aggregator.add(quote.mid, quote.time, quote.tradeable)

        # Een afgesloten bar meteen bewaren. Er gaat geen extra verzoek naar de
        # broker: dit is de bar die er toch al was, en zonder dit archief werd
        # hij bij de volgende herstart weggegooid.
        if closed:
            # 1.7.5: een bar die door een herstart onvolledig is, niet als
            # volwaardige bar archiveren; het sentiment hoort wel bij de bar
            # die net sloot.
            await self._on_bars_closed(
                self._aggregator.candles(2), "quotes",
                archief=self._aggregator.archiveerbaar(2),
            )
        if not closed:
            return

        self._new_bars_this_cycle = 1
        if self._aggregator.bar_count < MIN_WARMUP_CANDLES:
            return

        fresh = self._aggregator.candles(STRATEGY_WINDOW_BARS)
        if self._candles is None:
            self._candles = fresh
            self.state = StreamState()
            await self.hass.async_add_executor_job(self.state.warm_up, fresh)
            _LOGGER.info(
                "Opwarmen voltooid: %d zelfgebouwde bars", len(fresh)
            )
        else:
            index = len(fresh) - 1
            self.state.push_candle(
                fresh.open[index], fresh.high[index], fresh.low[index],
                fresh.close[index], fresh.volume[index],
            )
            self._candles = fresh
        self._last_bar_ts = fresh.timestamp[-1]

    async def _on_bars_closed(self, candles, bron: str, archief=_ZELFDE) -> None:
        """Verwerk afgesloten bars: archiveren en sentiment vastleggen.

        Eerst gebeurde het archiveren alleen in het pad voor zelfgebouwde
        bars. Wie de historie van de broker gebruikt - nauwkeuriger en direct
        beschikbaar - kreeg een archief dat stilstond. Nu komen beide paden
        hier samen.

        Niets hiervan mag de handelslus slopen: dit is meting, geen beslissing.
        """
        if self.archive is None or candles is None or not len(candles):
            return
        # ``archief``: welke bars het archief in gaan, als dat er minder zijn
        # dan ``candles`` (1.7.5); None is geen enkele.
        te_bewaren = candles if archief is _ZELFDE else archief
        if te_bewaren is not None and len(te_bewaren):
            try:
                await self.hass.async_add_executor_job(
                    self.archive.store, self.symbol, self.timeframe, te_bewaren,
                    bron,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Bar niet gearchiveerd: %s", err)

        haal = getattr(self.venue, "client_sentiment", None)
        if haal is None:
            return
        try:
            stand = await haal()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Sentiment niet opgehaald: %s", err)
            return
        if not stand:
            return
        self.sentiment = stand
        try:
            await self.hass.async_add_executor_job(
                self.archive.store_sentiment, self.symbol,
                int(candles.timestamp[-1]), stand["long"], stand["short"],
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Sentiment niet bewaard: %s", err)

    async def _maybe_update_candles(self) -> None:
        """Haal nieuwe candles op als er een bar afgesloten kan zijn."""
        self._new_bars_this_cycle = 0
        if self._candles is not None and not self._bar_due():
            return
        try:
            fresh = await self.venue.candles(self.symbol, self.timeframe, 3)
        except VenueError as err:
            _LOGGER.debug("Kon candles niet verversen: %s", err)
            return
        # Alleen bars die al afgesloten zijn: de broker geeft ook de lopende.
        fresh = closed_only(
            fresh, datetime.now(timezone.utc).timestamp(), self.timeframe,
        )

        # Historie kwijt na een integriteitsprobleem: opnieuw opwarmen.
        if self._candles is None:
            try:
                self._candles = await self._fetch_warmup()
                self.state = StreamState()
                await self.hass.async_add_executor_job(
                    self.state.warm_up, self._candles
                )
                self._last_bar_ts = self._candles.timestamp[-1]
                _LOGGER.info("Historie opnieuw opgewarmd met %d candles",
                             len(self._candles))
            except VenueError as err:
                _LOGGER.warning("Opnieuw opwarmen mislukt: %s", err)
            return

        for i, ts in enumerate(fresh.timestamp):
            if ts <= self._last_bar_ts:
                continue
            self.state.push_candle(
                fresh.open[i], fresh.high[i], fresh.low[i],
                fresh.close[i], fresh.volume[i],
            )
            self._last_bar_ts = ts
            self._new_bars_this_cycle += 1
            self._append_candle(fresh, i)
            if self._candles is None:
                break

        if self._new_bars_this_cycle:
            # Historie van de broker ook bewaren: nauwkeuriger dan
            # zelfgebouwde bars, en tot nu toe verloren.
            await self._on_bars_closed(fresh, "broker")

    async def _manage_open_positions(self, quote: VenueQuote, now: datetime) -> None:
        """Break-even, gedeeltelijk sluiten, trailing en tijdstops."""
        atr = self.state.atr.value or 0.0
        if atr <= 0:
            return
        cost = quote.spread + 0.04  # spread plus geschatte slippage beide zijden

        for position in await self._open_positions():
            ticket = str(getattr(position, "ticket", None) or getattr(position, "id", ""))
            opened = await self._position_opened_at(position, ticket, now)
            # Paper-trades bewaren volume in lots, venue-posities in ounces.
            size = getattr(position, "units", None)
            if size is None:
                size = (getattr(position, "volume", 0) or 0) * CONTRACT_SIZE
            action = self.exits.evaluate(
                side=position.side,
                volume=size,
                open_price=position.open_price,
                current_stop=getattr(position, "stop_loss", None),
                bid=quote.bid, ask=quote.ask, atr=atr,
                opened_at=opened, now=now,
                round_trip_cost_per_oz=cost,
                partial_taken=ticket in self._partial_taken,
            )
            # Uitersten bijhouden zolang de positie leeft, vóór de
            # noop-controle: bij 'hold' gebeurt er verder niets, en dat is
            # juist het grootste deel van de tijd. Achteraf zijn ze niet meer
            # te achterhalen.
            self._track_excursion(position, quote, ticket)

            # Wisselkoers afleiden uit wat de broker zelf meldt: hij geeft de
            # onrealiseerde winst in accountvaluta terwijl de prijsbeweging in
            # instrumentvaluta staat. De verhouding is de koers, en dat is
            # degene waarmee hij ook afrekent.
            if self.conversion.needed:
                koers = derive_rate_from_position(
                    getattr(position, "unrealised_pnl", None),
                    float(getattr(position, "open_price", 0) or 0),
                    getattr(position, "current_price", None),
                    float(getattr(position, "units", 0) or 0),
                    getattr(position, "side", "buy"),
                )
                if koers and koers != self.conversion.rate and \
                        self._apply_rate(koers, "broker_position"):
                    _LOGGER.info(
                        "Wisselkoers %s/%s afgeleid uit een open positie: "
                        "%.4f", self.conversion.instrument,
                        self.conversion.account, koers,
                    )

            # Pyramiden vóór de exitacties: bijkopen bij bevestiging is een
            # aparte beslissing van de vraag of je moet sluiten.
            if self.pyramid.enabled and action.kind in ("hold", "modify_stop"):
                await self._consider_pyramid(position, quote, ticket)

            if action.is_noop:
                continue

            try:
                if action.kind == "close":
                    await self._close_position(position, action.reason[:60])
                elif action.kind == "modify_stop" and self.mode.places_orders:
                    # Het doel meegeven: het PUT-endpoint vervangt beide
                    # niveaus, dus zonder deze waarde wist elke stopverplaatsing
                    # je take-profit. Meegeven scheelt bovendien een extra
                    # verzoek om hem eerst op te halen.
                    resultaat = await self.venue.modify_stop(
                        ticket, action.new_stop,
                        take_profit=getattr(position, "take_profit", None),
                    )
                    # De nieuwe stop ook in de eigen administratie zetten.
                    #
                    # Zolang het exitbeheer niet werkte - de posities waren
                    # onzichtbaar - viel dit niet op. Nu het wel werkt, meldde
                    # de brokercontrole bij elke verplaatsing een verschil, en
                    # leidde de afwikkeling de sluitreden af van een stop die
                    # al lang niet meer gold.
                    if getattr(resultaat, "success", False):
                        await self._sync_trade_stop(ticket, action.new_stop)
                elif action.kind == "modify_stop":
                    position.stop_loss = action.new_stop
                elif action.kind == "partial_close":
                    units = (getattr(position, "units", 0) or 0) * action.close_fraction
                    if self.mode.places_orders and units > 0:
                        await self.venue.close(ticket, units)
                        self._positions_cache = None
                        # Vastleggen: anders wordt de winst wél genomen maar
                        # verschijnt hij nergens in je resultaten, en telt hij
                        # niet mee in de bewijsfase.
                        await self._record_partial(
                            ticket, units, action.reason,
                            datetime.now(timezone.utc),
                        )
                    self._partial_taken.add(ticket)
            except VenueError as err:
                _LOGGER.error("Exitactie %s mislukte: %s", action.kind, err)

    async def _open_position(self, signal, quote: VenueQuote, now: datetime) -> None:
        # 1.7.0: nooit instappen op een vastgehouden koers. De lus slaat zo'n
        # cyclus al over; dit is de tweede grendel.
        if self.koers_verouderd:
            _LOGGER.warning("Instap overgeslagen: koers verouderd.")
            return
        side = "buy" if signal.direction == 1 else "sell"
        try:
            # Grootte bepalen vóór de order. Bij risicogestuurde schaling
            # volgt hij uit de stopafstand, zodat elke trade hetzelfde bedrag
            # riskeert ongeacht de volatiliteit.
            # ``equity`` is bij de papersimulatie een methode die de koers
            # nodig heeft; zonder aanroep kwam hier de methode zelf binnen en
            # faalde risicogestuurde grootte in papermodus (1.7.5).
            equity = (
                self.paper.equity(self._paper_quote(quote))
                if self.paper else self.starting_balance
            )
            entry_price = quote.ask if side == "buy" else quote.bid
            sized = position_size(
                self.sizing, equity, entry_price, signal.stop_loss,
                signal.score, self.strategy_cfg.entry_threshold,
            )
            units = sized.units
            self.last_sizing = sized.as_dict()
            _LOGGER.debug("Ordergrootte: %s", sized.reason)

            if self.mode.places_orders:
                # De poort geldt alleen voor echt geld. Op demo is er niets te
                # beschermen behalve de kwaliteit van je meting, en juist die
                # meting is het doel.
                # Het dict rechtstreeks doorgeven; de controle kent beide
                # vormen. Er hoeft geen klasse uit gefabriceerd te worden.
                require_live_unlocked(self.mode, self.gate)
                # Via de veiligheidslaag: garandeert een stop, voorkomt een
                # tweede order na een verbroken verbinding.
                result, notes = await self.executor.open_protected(
                    self.symbol, side, units, quote.mid,
                    stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                    context=(signal, quote, side, now),
                )
                self.executor_notes = notes[-10:]
                # Na het plaatsen is de gecachte lijst verouderd.
                self._positions_cache = None
                for note in notes:
                    _LOGGER.info("Uitvoering: %s", note)
                if result.unconfirmed:
                    # Onbekend, niet mislukt. De order kan uitgevoerd zijn; tot
                    # hij is teruggevonden gaat er geen nieuwe uit. Op 30-09
                    # werd dit als "niet geplaatst" behandeld: elf orders in
                    # twee minuten, alle elf uitgevoerd, geen enkele bewaakt.
                    _LOGGER.warning(
                        "Order onbevestigd: %s Nieuwe orders wachten.", result.error,
                    )
                    self._last_entry_ts = now.timestamp()
                    return
                if not result.success:
                    _LOGGER.warning("Order niet geplaatst: %s", result.error)
                    return

                # Vastleggen in de database. Zonder dit verdwijnen orders die
                # naar de broker gaan uit je eigen administratie: geen
                # resultaat, geen kosten, geen verliesanalyse, en een
                # bewijsfase die nooit vordert. Dat maakte de demomodus
                # zinloos, want juist het meten was het doel.
                await self._record_broker_open(result, signal, quote, side, now)
            elif self.paper:
                self.paper.open_position(
                    side, units / CONTRACT_SIZE, self._paper_quote(quote),
                    signal.stop_loss, signal.take_profit,
                    signal.score, signal.confidence, None, signal.reason,
                )
            self.risk.record_open()
            self._last_entry_ts = now.timestamp()
        except (ModeLockedError, VenueError) as err:
            _LOGGER.error("Openen mislukt: %s", err)

    async def async_reconcile(self, dagen: float = 3.0) -> dict:
        """Leg de gesloten trades van de laatste dagen naast de broker.

        Zes keer werd een fout in de koppeling gevonden door een schermafdruk
        van het brokeroverzicht naast het rapport te leggen. Dit doet dat werk,
        elke dag, met dezelfde koppelregel als de correctie.
        """
        from .learning.afstemming import stem_af

        haal = getattr(self.venue, "transactions", None)
        if haal is None or self.run_id is None:
            return {}
        nu = datetime.now(timezone.utc)
        transacties = await haal(nu - timedelta(days=dagen), nu)
        trades = await self.hass.async_add_executor_job(
            self.db.closed_trades, self.run_id
        )
        grens = nu - timedelta(days=dagen)
        recent = [
            t for t in trades
            if t.close_time and _as_datetime(t.close_time, nu) >= grens
        ]
        uitslag = await self.hass.async_add_executor_job(
            stem_af, recent, transacties, self.conversion.rate, nu,
            CONTRACT_SIZE,
        )
        # Wat de broker exact noemt, overnemen: bedrag, koers, omvang. Daarna
        # klopt de administratie op de cent met zijn overzicht.
        if uitslag.overnames:
            per_id = {t.id: t for t in recent}
            bijgewerkt = []
            for overname in uitslag.overnames:
                trade = per_id.get(overname["trade_id"])
                if trade is None:
                    continue
                for veld, waarde in overname["velden"].items():
                    setattr(trade, veld, waarde)
                trade.account_currency = self.conversion.account
                trade.fx_timestamp = nu.isoformat()
                bijgewerkt.append(trade)
            for trade in bijgewerkt:
                await self.hass.async_add_executor_job(self.db.update_trade, trade)
            _LOGGER.info(
                "Afstemming: %d trade(s) bijgewerkt naar de broker (%d met "
                "slippage op de uitstap, %d met gemeten kosten).",
                len(bijgewerkt), uitslag.slippage_overgenomen,
                uitslag.kosten_gemeten,
            )
        self.reconciliation = {**uitslag.as_dict(), "moment": nu.isoformat()}
        if uitslag.afwijkingen:
            regels = "; ".join(a.uitleg for a in uitslag.afwijkingen[:5])
            _LOGGER.warning(
                "Afstemming met de broker: %s %s", uitslag.samenvatting(), regels
            )
            await self.notifier.alert(
                "afstemming", "Gold Scalper: administratie wijkt af",
                uitslag.samenvatting() + " " + regels,
            )
        return self.reconciliation

    def _record_account_amount(self, trade) -> None:
        """Resultaat in accountvaluta vastleggen met de koers van nu.

        Eén bron voor dit bedrag: bij gelijke valuta het bedrag zelf, anders
        omgerekend met de middenkoers en met bron en tijdstip erbij. Zonder
        bruikbare koers blijft het leeg - geen geschat getal.
        """
        conv = self.conversion
        trade.account_currency = conv.account
        if not conv.needed:
            trade.net_pnl_account = trade.net_pnl
            trade.fx_rate, trade.fx_source = 1.0, "same_currency"
            return
        if conv.rate and trade.net_pnl is not None:
            trade.net_pnl_account = round(trade.net_pnl * conv.rate, 4)
            trade.fx_rate = conv.rate
            trade.fx_source = conv.rate_source
            trade.fx_timestamp = (
                conv.rate_timestamp.isoformat() if conv.rate_timestamp else None
            )

    async def _record_opening_equity(self) -> None:
        """Equity bij de start van de run, in accountvaluta, één keer vastgelegd.

        Bij de broker opgehaald; in papermodus de startbalans van de simulatie.
        Mislukt het ophalen, dan blijft het leeg - en telt alleen de vloer op de
        ingestelde balans. Nooit geschat.
        """
        self.opening_equity = None
        valuta = self.conversion.account
        if self.mode.places_orders:
            try:
                account = await self.venue.account()
                self.opening_equity = float(account.equity)
                valuta = getattr(account, "currency", None) or valuta
                # 1.7.7: geen run-opening (en dus geen vloer) op een
                # onverklaarde saldosprong; de vorige referentie geldt.
                if self.saldosprong.actief:
                    _LOGGER.warning(
                        "Run-opening op de vorige referentie in plaats van "
                        "%.2f: %s", self.opening_equity, self.saldosprong.reden,
                    )
                    self.opening_equity = self.saldosprong.betrouwbaar(
                        self.opening_equity
                    )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Equity bij de start van run %s niet op te halen: %s. De "
                    "vloer rekent dan alleen op de ingestelde startbalans.",
                    self.run_id, err,
                )
        else:
            self.opening_equity = float(self.starting_balance)
        await self.hass.async_add_executor_job(
            self.db.set_run_opening, self.run_id, self.opening_equity, valuta,
        )

    def _apply_rate(
        self, koers: float, bron: str, now: datetime | None = None,
        risk_rate: float | None = None, market_closed: bool | None = None,
    ) -> bool:
        """Eén plek waar een wisselkoers wordt gezet.

        De marktkoers van de broker gaat voor: een koers die uit een afgerekende
        trade is afgeleid, overschrijft een verse marktkoers niet. Alles wat
        hier gezet wordt, gaat met bron en tijdstip de toestand in.

        ``risk_rate`` is de voorzichtige koers voor de positiegrootte. Zonder
        bied/laat - bij een afgeleide koers - is dat de koers zelf.
        """
        now = now or datetime.now(timezone.utc)
        huidig = self.conversion
        if (
            bron not in MARKT_BRONNEN and huidig.rate_source in MARKT_BRONNEN
            and huidig.rate_timestamp is not None
            and now - huidig.rate_timestamp < timedelta(hours=1)
        ):
            return False
        huidig.rate = koers
        huidig.risk_rate = risk_rate or koers
        huidig.rate_source = bron
        huidig.rate_timestamp = now
        if market_closed is not None:
            huidig.market_closed = market_closed
        self.sizing.account_to_instrument = 1.0 / huidig.risk_rate
        self._state.conversion_rate = koers
        self._state.conversion_risk_rate = huidig.risk_rate
        self._state.conversion_rate_at = now.isoformat()
        self._state.conversion_market_closed = huidig.market_closed
        return True

    async def _refresh_fx(self, now: datetime) -> None:
        """De wisselkoers verversen.

        Eerste bron: de omrekenkoers die de broker bij de goudkoers meestuurt
        (``baseExchangeRate``). Die komt met elke koers mee, kost geen extra
        verzoek en is precies de koers waarmee de broker rekent. Het apart
        ophalen van EUR/USD leverde bij dit account voor alle drie de epics
        een instrument zonder bied- en laatkoers op.

        Voor de positiegrootte telt de **verlieskoers** van de broker als die
        hoger is dan het midden: de broker rekent verlies 0,56% boven het
        midden om, dus een verlies kost in euro's meer dan het midden zegt.
        """
        if not self.conversion.needed:
            return

        haal_instrument = getattr(self.venue, "instrument_fx", None)
        fx = haal_instrument() if haal_instrument else None
        if fx and fx.get("code") == self.conversion.instrument.upper() and fx.get("base_rate"):
            midden = 1.0 / fx["base_rate"]

            # Controle op de richting: de broker rekent resultaten om binnen
            # ongeveer een procent van het midden. Wijkt dit er meer dan 3%
            # van af, dan is het veld anders dan gedacht - niet gebruiken.
            ref = self._broker_fx_ref
            if ref and abs(midden / ref - 1.0) > 0.03:
                if not self._fx_richting_gemeld:
                    self._fx_richting_gemeld = True
                    _LOGGER.warning(
                        "Omrekenkoers uit het instrument (%.5f) wijkt meer dan "
                        "3%% af van de laatste conversie van de broker (%.5f); "
                        "niet gebruikt.", midden, ref,
                    )
                return

            risico, basis = midden, "middenkoers (nog geen verlieskoers van de broker bekend)"
            verlies = self._loss_fx_rate
            if verlies and self._loss_fx_at and now - self._loss_fx_at <= timedelta(hours=24):
                if verlies > midden:
                    risico = verlies
                    basis = "verlieskoers van de broker, hoger dan het midden"
                else:
                    basis = "middenkoers (hoger dan de recente verlieskoers)"
            self._apply_rate(midden, "ig_instrument", now, risk_rate=risico)
            self.conversion.risk_basis = basis
            return

        # Terugval: EUR/USD apart ophalen, hooguit elke vijf minuten.
        haal = getattr(self.venue, "fx_quote", None)
        if haal is None:
            return
        if self._fx_checked and now - self._fx_checked < timedelta(minutes=5):
            return
        self._fx_checked = now
        try:
            q = await haal()
        except Exception as err:  # noqa: BLE001 - een koers ophalen mag niets slopen
            _LOGGER.debug("EUR/USD niet opgehaald: %s", err)
            return
        if not q:
            return
        if q.get("status") not in (None, "TRADEABLE"):
            self.conversion.market_closed = True
            self._state.conversion_market_closed = True
            return
        self._apply_rate(
            1.0 / q["mid"], "ig_market", now,
            risk_rate=1.0 / q["bid"], market_closed=False,
        )
        self.conversion.risk_basis = "biedkoers van EUR/USD"

    async def _resolve_pending_orders(self) -> None:
        """Zoek onbevestigde orders terug en leg gevonden posities vast.

        Een teruggevonden positie wordt vastgelegd met het signaal en de koers
        van het moment van versturen, precies alsof de bevestiging op tijd was
        gekomen. Zo telt hij mee, wordt hij bewaakt en afgerekend.
        """
        try:
            posities = await self._open_positions(refresh=True)
            beheerd = await self._managed_open_trades(
                [str(getattr(p, "ticket", "")) for p in posities]
            )
            bekend = {str(t.broker_ticket) for t in beheerd if t.broker_ticket}
            gevonden, notes = await self.executor.resolve_pending(bekend)
        except VenueError as err:
            _LOGGER.debug("Onbevestigde order nog niet na te kijken: %s", err)
            return
        for note in notes:
            _LOGGER.warning("Uitvoering: %s", note)
        for order, positie in gevonden:
            if not order.context:
                _LOGGER.error(
                    "Positie %s teruggevonden zonder ordergegevens; niet "
                    "vastgelegd. De afstemming met de broker meldt hem.",
                    positie.ticket,
                )
                continue
            signal, quote, side, verstuurd = order.context
            result = OrderResult(
                success=True, ticket=str(positie.ticket),
                fill_price=positie.open_price or None, units=positie.units,
                client_ref=order.client_id,
            )
            await self._record_broker_open(result, signal, quote, side, verstuurd)
            self.risk.record_open()
        if gevonden or notes:
            self.executor_notes = (self.executor_notes + notes)[-10:]
            self._positions_cache = None

    async def _managed_open_trades(self, live_tickets=None) -> list:
        """Open trades die deze integratie beheert.

        De actieve run, plus trades uit een eerdere run waarvan de positie bij
        de broker nog openstaat. Zonder die tweede groep zag een nieuwe run
        een positie uit de vorige als "onbekend" en ging de noodstop aan - wat
        bij de overstap naar 5.4.0 gebeurde, omdat die bewust een nieuwe run
        start.

        Alleen trades waarvan de positie **live** is gezien, niet elke oude
        trade die ooit open is blijven staan: die afrekenen tegen de koers van
        vandaag zou een oude run vervuilen. Een meegenomen trade wordt in zijn
        eigen run afgerekend, niet in de actieve.
        """
        eigen = await self.hass.async_add_executor_job(
            self.db.open_trades, self.run_id
        )
        if live_tickets:
            bekend = {str(t.broker_ticket) for t in eigen}
            elders = [str(t) for t in live_tickets if str(t) not in bekend]
            if elders:
                gevonden = await self.hass.async_add_executor_job(
                    self.db.open_trades_by_tickets, elders
                )
                for t in gevonden:
                    if str(t.broker_ticket) not in self._carried_tickets:
                        _LOGGER.info(
                            "Positie %s uit run %s staat nog open; die wordt "
                            "beheerd tot hij sluit en in run %s afgerekend.",
                            t.broker_ticket, t.run_id, t.run_id,
                        )
                    self._carried_tickets.add(str(t.broker_ticket))
        if not self._carried_tickets:
            return eigen
        meegenomen = await self.hass.async_add_executor_job(
            self.db.open_trades_by_tickets, list(self._carried_tickets)
        )
        self._carried_tickets &= {str(t.broker_ticket) for t in meegenomen}
        return eigen + [t for t in meegenomen if t.run_id != self.run_id]

    async def _position_opened_at(self, position, ticket: str, now: datetime) -> datetime:
        """Openingstijd van een positie, voor tijdstop en maximale duur.

        1.7.4 (L-GS-005): IG gaf de positie zonder openingstijd door, waardoor
        de leeftijd altijd nul was en de tijdstops nooit vuurden. Eerst wat de
        broker meldt; ontbreekt dat, dan de openingstijd van de eigen trade op
        hetzelfde ticket. Die wordt per ticket onthouden, zodat er niet elke
        cyclus een database-opvraging bij komt.
        """
        eigen = getattr(position, "open_time", None)
        if eigen is not None:
            return _as_datetime(eigen, now)
        cache = self._open_time_cache
        if ticket in cache:
            return cache[ticket]
        if not ticket or not self.mode.places_orders:
            return now
        trade = await self._open_trade_by_ticket(ticket)
        if trade is None or not getattr(trade, "open_time", None):
            return now
        opened = _as_datetime(trade.open_time, now)
        if len(cache) > 50:
            cache.clear()
        cache[ticket] = opened
        return opened

    async def _open_trade_by_ticket(self, ticket):
        """Een open trade op ticket, in welke run ook."""
        gevonden = await self.hass.async_add_executor_job(
            self.db.open_trades_by_tickets, [str(ticket)]
        )
        return gevonden[0] if gevonden else None

    def _stop_trusted(self, trade) -> bool:
        """Is de stop in de database die van de broker?

        Pas sinds uitvoeringsversie 2 worden verplaatste stops teruggeschreven.
        Voor trades van daarvóór - of zonder vastgelegde versie - kan de stop
        in de database verouderd zijn, en dan is een uitstapprijs op dat niveau
        geen bewijs van een stoptreffer.
        """
        return (getattr(trade, "execution_semantics", None) or 0) >= 2

    def _apply_reconciliation(
        self, trade, exit_price, now: datetime,
        bron: str = "broker_transactions",
    ) -> None:
        """Afstemming met de broker vastleggen, zonder de oorspronkelijke
        sluitreden te raken."""
        from .learning.exit_stats import derive_close_reason

        afgeleid = derive_close_reason(
            exit_price, trade.take_profit, trade.stop_loss,
            self._stop_trusted(trade),
        )
        trade.reconciled_close_reason = afgeleid.reden
        trade.close_reason_source = afgeleid.bron
        trade.close_reason_evidence = afgeleid.bewijs
        trade.reconciliation_status = "reconciled"
        trade.reconciled_at = now.isoformat()
        trade.reconciliation_source = bron

    async def _ledger_cost(self) -> float:
        """Cumulatieve kosten uit het tradeledger - ook in demomodus.

        Eerst uit de papersimulatie, die in demo niet bestaat: de kostenlijn in
        het rapport stond daar altijd op nul. Alleen herberekend als het aantal
        gesloten trades veranderde.
        """
        if self.run_id is None:
            return 0.0
        # Het aantal van de vorige cyclus: hooguit één cyclus vertraging.
        aantal = self._gate_trade_count
        if aantal == self._ledger_cost_count and self._ledger_cost_value is not None:
            return self._ledger_cost_value
        kosten = await self.hass.async_add_executor_job(
            self.db.ledger_costs, self.run_id
        )
        self._ledger_cost_value = kosten["total"]
        self._ledger_cost_count = aantal
        self.ledger_cost_info = kosten
        return self._ledger_cost_value

    async def _sync_trade_stop(self, ticket, nieuwe_stop: float) -> None:
        """Zet een bij de broker verplaatste stop ook in de database."""
        if self.run_id is None:
            return
        # In welke run ook: een positie uit een eerdere run wordt ook beheerd.
        trade = await self._open_trade_by_ticket(ticket)
        if trade is not None:
            trade.stop_loss = round(float(nieuwe_stop), 5)
            await self.hass.async_add_executor_job(self.db.update_trade, trade)

    async def _correct_estimated_settlements(self, now: datetime) -> None:
        """Werk eerder geschatte afwikkelingen bij zodra de prijs beschikbaar is.

        Het transactieoverzicht van de broker loopt achter - in de praktijk
        uren. Op het moment dat de lus een positie afwikkelt, staat de
        werkelijke uitstapprijs er nog niet in, en dan valt de afwikkeling
        terug op een schatting die tien dollar mis kan zijn.

        Eén keer proberen is dus niet genoeg. Hier wordt elke trade die als
        schatting is geboekt later opnieuw opgezocht en gecorrigeerd. Dat is de
        enige manier om zowel snel af te wikkelen als juist te boeken.
        """
        zoek = getattr(self.venue, "closed_deal", None)
        if zoek is None or self.run_id is None:
            return

        geschat = await self.hass.async_add_executor_job(
            self.db.estimated_trades, self.run_id
        )

        # De stand uit de database halen, niet uit een losse teller.
        #
        # Die teller begon bij elke herstart op nul en werd alleen verhoogd bij
        # nieuwe schattingen. Gevolg: het rapport meldde nul te corrigeren
        # trades terwijl er nog één stond - een getal dat verkeerd kan staan is
        # erger dan geen getal, want je vertrouwt erop.
        self._geschatte_afwikkelingen = len(geschat)

        if not geschat:
            return

        # 1.7.2: de eigen sluitmomenten meegeven, zodat de broker een te klein
        # transactieoverzicht vergelijkt met wat er werkelijk gesloten is in
        # plaats van met een vaste drempel. Alleen voor de logging.
        try:
            eigen_sluitingen = await self.hass.async_add_executor_job(
                self.db.recent_close_times
            )
        except Exception:  # noqa: BLE001 - diagnose mag de correctie niet stoppen
            eigen_sluitingen = None

        for trade in geschat[:5]:      # hoogstens vijf per cyclus
            try:
                # Het sluitmoment meegeven zodat het zoekvenster erom heen
                # ligt. Zonder dat ligt het venster rond nu, en is een trade
                # van gisteren onvindbaar - precies waardoor een
                # herzoekopdracht correcte cijfers als schatting liet staan.
                werkelijk = await zoek(
                    str(trade.broker_ticket), trade.open_price, trade.side,
                    _as_datetime(trade.close_time, None),
                    trade.volume * CONTRACT_SIZE,
                    trade.open_time,
                    own_close_times=eigen_sluitingen,
                )
            except VenueError:
                return

            if not werkelijk or not werkelijk.get("exit_price"):
                # Opgeven op LEEFTIJD, niet op aantal pogingen.
                #
                # De vorige regel gaf op na drie pogingen, oftewel ruim tien
                # minuten. Maar het transactieoverzicht van de broker loopt
                # uren achter - gemeten: nieuwste transactie 10:51 bij een
                # opvraging om 14:22. Elke nieuwe trade werd dus drie keer
                # tevergeefs gezocht en daarna definitief opgegeven, uren
                # voordat de prijs beschikbaar kwam.
                #
                # Gevolg: zesentwintig van zestig trades hielden hun geschatte
                # prijs, en die comprimeert naar nul. De gemiddelde winst zakte
                # daardoor van 14,51 naar 10,61 - een meetfout die eruitzag als
                # een verslechterende strategie.
                #
                # Twee dagen is ruim: langer dan de vertraging die ooit gemeten
                # is, en kort genoeg om een trade niet eeuwig op te zoeken.
                gesloten = _as_datetime(trade.close_time, None)
                leeftijd = (
                    (now - gesloten).total_seconds() / 86400
                    if gesloten else 0.0
                )
                if leeftijd > 2.0:
                    trade.close_reason = "broker_gesloten_onvindbaar"
                    trade.reconciliation_status = "unfindable"
                    await self.hass.async_add_executor_job(
                        self.db.update_trade, trade
                    )
                    _LOGGER.info(
                        "Uitstapprijs van %s is na %.1f dagen nog niet bij de "
                        "broker te vinden; de geboekte prijs blijft staan.",
                        trade.broker_ticket, leeftijd,
                    )
                continue

            oud = trade.net_pnl or 0.0
            exit_price = float(werkelijk["exit_price"])
            await self._boek_brokerprijs(trade, werkelijk, now)
            self._herkansingen.pop(str(trade.broker_ticket), None)

            _LOGGER.info(
                "Trade %s gecorrigeerd: netto van %.2f naar %.2f "
                "(uitstapprijs %.2f in plaats van een schatting).",
                trade.broker_ticket, oud, trade.net_pnl, exit_price,
            )

    async def _boek_brokerprijs(
        self, trade, werkelijk: dict, now: datetime,
        bron: str = "broker_transactions",
    ) -> None:
        """Boek een voorlopig afgerekende trade om naar de prijs van de broker.

        Eén plek voor de correctie uit het transactieoverzicht én de
        herkansing uit het activiteitenoverzicht (1.7.3), zodat beide hetzelfde
        bijwerken: uitstapprijs, sluitreden, kosten en bedrag.
        """
        exit_price = float(werkelijk["exit_price"])
        long = trade.side == "buy"
        richting = 1.0 if long else -1.0
        units = trade.volume * CONTRACT_SIZE
        half = (trade.close_spread or 0.6) / 2.0

        trade.close_price = exit_price
        trade.close_mid = exit_price + (half if long else -half)
        trade.close_reason = "broker_gesloten_gecorrigeerd"
        # Niet-destructief: de oorspronkelijke reden blijft staan, de
        # afgeleide reden komt er alleen met bewijs bij.
        self._apply_reconciliation(trade, exit_price, now, bron)
        # De omrekenkoers van de broker onthouden: als controle op de
        # richting, en bij verlies als voorzichtige koers voor de grootte.
        broker_koers = werkelijk.get("conversion_rate")
        if broker_koers:
            self._broker_fx_ref = broker_koers
            if (werkelijk.get("profit_account") or 0) < 0:
                self._loss_fx_rate, self._loss_fx_at = broker_koers, now
                self._state.conversion_loss_rate = broker_koers
                self._state.conversion_loss_rate_at = now.isoformat()

        # Het bedrag in accountvaluta van de broker zelf: geen omrekening.
        if werkelijk.get("profit_account") is not None:
            trade.net_pnl_account = float(werkelijk["profit_account"])
            trade.account_currency = self.conversion.account
            trade.fx_source = "broker_settlement"
            # De koers die de broker zelf noemt; anders afgeleid.
            trade.fx_rate = broker_koers or (
                round(trade.net_pnl_account / trade.net_pnl, 6)
                if trade.net_pnl else self.conversion.rate
            )
            trade.fx_timestamp = now.isoformat()
        # De kosten volgen hier uit de spread en de omvang, niet uit een
        # fill: berekend - tenzij ze hieronder met de brokerprijs te meten
        # zijn (1.7.3).
        trade.cost_source = "calculated"

        # Het resultaat van de broker overnemen, niet zelf narekenen.
        #
        # De broker meldt het bedrag waarmee hij werkelijk heeft
        # afgerekend. Zelf narekenen uit prijzen leverde steeds weer
        # afwijkingen op - bij één trade 7,46 tegen de 10,48 die de broker
        # boekte - en elke keer was de oorzaak een detail dat ik niet kon
        # controleren: afronding, een halve spread, een gedeeltelijke
        # sluiting.
        #
        # Het bedrag van de broker is per definitie juist: dat is wat er op
        # de rekening gebeurde. Alles wat ik eruit afleid kan dat alleen
        # benaderen.
        # Het sluitmoment van de broker overnemen.
        #
        # Het eigen tijdstempel is het moment waarop de beheerlus de
        # positie afwikkelde, en dat liep tot negentig minuten uit de pas
        # met wat de broker meldt. Naast het overzicht van de broker was
        # het rapport daardoor niet te lezen: je vergelijkt rijen op
        # tijdstip en koppelt dan de verkeerde trades aan elkaar.
        #
        # De broker bepaalt wanneer een positie sloot, dus zijn tijdstip is
        # het juiste.
        gemeld = werkelijk.get("closed_at")
        if gemeld:
            try:
                moment = datetime.fromisoformat(str(gemeld))
            except (TypeError, ValueError):
                moment = None
            # Alleen overnemen als er een tijd in zit; een datum zonder
            # tijd zou het sluitmoment op middernacht zetten.
            if moment is not None and (
                moment.hour or moment.minute or moment.second
            ):
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=timezone.utc)
                trade.close_time = moment.isoformat()
                # De looptijd volgt eruit en moet meeschuiven.
                opende = _as_datetime(trade.open_time, moment)
                trade.duration_seconds = max(
                    0, int((moment - opende).total_seconds())
                )

        winst_account = werkelijk.get("profit_account")
        # De koers van de broker zelf, niet de middenkoers. De broker
        # rekent verlies tegen een hogere koers om dan winst; terugrekenen
        # met het midden maakte elk verlies 0,5 tot 1 procent te groot en
        # elke winst te klein (30-09: -11,38 in plaats van -11,30).
        koers = broker_koers or self.conversion.rate

        if winst_account is not None and koers and koers > 0:
            # Van accountvaluta naar instrumentvaluta, want de hele
            # administratie rekent in die laatste.
            trade.net_pnl = round(winst_account / koers, 4)
            trade.total_cost = round(
                abs(trade.close_spread or 0.6) * units, 4
            )
            trade.gross_pnl = round(
                (trade.net_pnl or 0) + (trade.total_cost or 0), 4
            )
        else:
            # Zonder koers of zonder bedrag terugvallen op de berekening.
            trade.gross_pnl = round(
                (trade.close_mid - trade.open_mid) * richting * units, 4
            )
            trade.net_pnl = round(
                (exit_price - trade.open_price) * richting * units, 4
            )
            trade.total_cost = round(
                (trade.gross_pnl or 0) - (trade.net_pnl or 0), 4
            )
            # Zonder bedrag van de broker het bedrag in accountvaluta opnieuw
            # omrekenen: anders bleef het eurobedrag van de schatting staan.
            if winst_account is None:
                self._record_account_amount(trade)

        # 1.7.3: met een uitstapprijs van de broker en een bewezen sluitreden
        # zijn de kosten te meten, net als in de afstemming. Anders bleef een
        # gecorrigeerde schatting op "berekend" staan tot de volgende
        # afstemmingsronde, en telde hij zolang niet mee in kosten_gemeten.
        from .learning.kosten import meet_kosten

        gemeten = meet_kosten(trade, exit_price, CONTRACT_SIZE)
        if gemeten is not None:
            trade.total_cost = gemeten["total_cost"]
            trade.spread_cost = gemeten["spread_cost"]
            trade.slippage_cost = gemeten["slippage_cost"]
            trade.gross_pnl = round((trade.net_pnl or 0) + gemeten["total_cost"], 4)
            trade.cost_source = "measured"

        await self.hass.async_add_executor_job(self.db.update_trade, trade)
        # De wisselkoers uit dezelfde gegevens halen.
        #
        # De correctie heeft de winst in accountvaluta al in handen; die
        # niet gebruiken zou betekenen dat de koers onbekend blijft
        # terwijl hij op tafel ligt - en dan blijft de positiegrootte acht
        # procent naast de bedoeling.
        winst = werkelijk.get("profit_account")
        if winst and self.conversion.needed and trade.net_pnl:
            koers = winst / trade.net_pnl
            if 0.1 < koers < 10.0 and koers != self.conversion.rate and \
                    self._apply_rate(koers, "broker_settlement"):
                _LOGGER.info(
                    "Wisselkoers %s/%s uit een gecorrigeerde trade: %.4f",
                    self.conversion.instrument, self.conversion.account,
                    koers,
                )

        # Narekenen en melden bij afwijking.
        #
        # Als de prijs die de broker meldt en het bedrag dat hij boekt niet
        # met elkaar rijmen, is er iets aan de hand dat ik niet ken - een
        # gedeeltelijke sluiting, een aanpassing, een fout van mijn kant.
        # Die afwijking hoort zichtbaar te zijn en niet weggerekend.
        if winst_account is not None and koers:
            verwacht = (exit_price - trade.open_price) * richting * units
            afwijking = abs(verwacht - (trade.net_pnl or 0))
            if afwijking > max(1.0, abs(verwacht) * 0.25):
                _LOGGER.warning(
                    "Trade %s: het bedrag van de broker (%.2f) en de "
                    "prijsbeweging (%.2f) verschillen %.2f. Het bedrag "
                    "van de broker is aangehouden; het verschil wijst op "
                    "een gedeeltelijke sluiting of een aanpassing.",
                    trade.broker_ticket, trade.net_pnl, verwacht,
                    afwijking,
                )

    async def _settle_vanished_positions(
        self, quote: VenueQuote, now: datetime
    ) -> None:
        """Sluit trades af die bij de broker niet meer bestaan."""
        try:
            live = await self._open_positions()
        except VenueError as err:
            _LOGGER.debug("Kon posities niet nakijken: %s", err)
            return

        # Posities van nul ounce tellen als gesloten: de broker laat ze nog
        # even in de lijst staan, maar er staat niets meer open. Ze als "nog
        # levend" beschouwen zou de trade eeuwig open houden in de database.
        live_tickets = {
            str(getattr(p, "ticket", "")) for p in live
            if not size_says_closed(getattr(p, "units", None))
        }
        open_trades = await self._managed_open_trades(live_tickets)

        for trade in open_trades:
            if not trade.broker_ticket:
                continue
            if str(trade.broker_ticket) in live_tickets:
                continue

            # De reden is niet met zekerheid vast te stellen; de broker vertelt
            # niet waarom hij sloot. Afleiden uit waar de koers staat ten
            # opzichte van stop en doel is het beste dat mogelijk is, en dat
            # wordt als zodanig gemarkeerd.
            reason = "broker_gesloten"
            long = trade.side == "buy"
            price = quote.bid if long else quote.ask
            level: float | None = None

            if trade.stop_loss and (
                (long and price <= trade.stop_loss)
                or (not long and price >= trade.stop_loss)
            ):
                reason, level = "stop_loss", trade.stop_loss
            elif trade.take_profit and (
                (long and price >= trade.take_profit)
                or (not long and price <= trade.take_profit)
            ):
                reason, level = "take_profit", trade.take_profit

            # Afrekenen op het niveau waarop de broker sloot, niet op de koers
            # van het moment waarop wij het ontdekken.
            #
            # Die twee lopen uiteen: de lus draait elke twintig seconden, en in
            # die tijd zakt de koers verder door. Op de latere koers afrekenen
            # boekt dat extra stuk als "kosten", waardoor de kostprijs per trade
            # opliep tot ruim het dubbele van de spread - een meetfout die
            # eruitziet als slippage.
            # Eerst de broker vragen wat de werkelijke uitstapprijs was.
            #
            # Afrekenen op de ontdekkingskoers werkt niet: de lus merkt pas na
            # een cyclus dat een positie weg is, en in die tijd loopt de koers
            # verder. Bij shorts die op hun doel sloten gaf dat verschillen van
            # tien dollar per trade - de eigen administratie meldde een verlies
            # van 4,83 waar de broker een winst van 28,58 euro boekte.
            werkelijk = None
            zoek = getattr(self.venue, "closed_deal", None)
            if zoek is not None:
                try:
                    # De instapprijs meegeven: daarop wordt gezocht, want het
                    # ticketnummer komt niet overeen met de verwijzing in het
                    # transactieoverzicht van de broker.
                    # Richting meegeven: twee transacties met bijna dezelfde
                    # instapprijs zijn alleen op hun richting te scheiden.
                    # Hier is het sluitmoment nu, dus het standaardvenster
                    # rond het huidige tijdstip is juist.
                    werkelijk = await zoek(
                        str(trade.broker_ticket), trade.open_price, trade.side,
                        None, trade.volume * CONTRACT_SIZE, trade.open_time,
                    )
                except VenueError as err:
                    _LOGGER.debug(
                        "Uitstapprijs van %s niet op te halen: %s",
                        trade.broker_ticket, err,
                    )

            # 1.7.3: staat hij (nog) niet in het transactieoverzicht, dan het
            # activiteitenoverzicht en de bevestiging proberen. Dat overzicht
            # loopt uren achter; de activiteit van een sluiting op stop of doel
            # staat er binnen seconden. Op 8 oktober werden zo vier trades op
            # een schatting afgerekend die de broker allang kende.
            bron = "broker_transactions"
            if not (werkelijk and werkelijk.get("exit_price")):
                activiteit = await self._zoek_activiteit(trade)
                if activiteit:
                    werkelijk = activiteit
                    bron = activiteit.get("source") or "broker_activity"

            if werkelijk and werkelijk.get("exit_price"):
                exit_price = float(werkelijk["exit_price"])
                half = quote.spread / 2.0
                settle = VenueQuote(
                    bid=exit_price if long else exit_price - 2 * half,
                    ask=exit_price + 2 * half if long else exit_price,
                    time=quote.time, tradeable=quote.tradeable,
                )
                if reason == "broker_gesloten":
                    reason = "broker_gesloten_gemeten"

                # De winst in accountvaluta die de broker meldt, geeft ook de
                # wisselkoers - preciezer dan de afleiding uit een open positie.
                winst = werkelijk.get("profit_account")
                if winst and self.conversion.needed:
                    beweging = (
                        (exit_price - trade.open_price)
                        * (1.0 if long else -1.0)
                        * trade.volume * CONTRACT_SIZE
                    )
                    if abs(beweging) > 1.0:
                        koers = winst / beweging
                        if 0.1 < koers < 10.0 and \
                                self._apply_rate(koers, "broker_settlement"):
                            _LOGGER.info(
                                "Wisselkoers %s/%s uit een afgerekende trade: "
                                "%.4f", self.conversion.instrument,
                                self.conversion.account, koers,
                            )
            elif level is not None:
                half = quote.spread / 2.0
                settle = VenueQuote(
                    bid=level if long else level - 2 * half,
                    ask=level + 2 * half if long else level,
                    time=quote.time, tradeable=quote.tradeable,
                )
            else:
                # Geen gemeten prijs en geen niveau: de ontdekkingskoers is het
                # beste dat er is, maar dan wél als schatting gemarkeerd.
                settle = quote
                reason = "broker_gesloten_geschat"
                # 1.7.3: voorlopig. De komende minuten wordt de uitstapprijs
                # nog een paar keer bij de broker nagevraagd
                # (:meth:`_herkans_voorlopige_afwikkelingen`); daarna neemt de
                # gewone correctie en de afstemming het over.
                self._herkansingen[str(trade.broker_ticket)] = {
                    "pogingen": 0, "sinds": now,
                }

                # En luid melden. Een schatting die stil doorgaat, produceert
                # cijfers die eruitzien als metingen - dat is precies hoe de
                # fout van 28 euro per middag onopgemerkt bleef.
                self._geschatte_afwikkelingen += 1
                if self._geschatte_afwikkelingen in (1, 5, 20, 50):
                    _LOGGER.warning(
                        "%d trade(s) afgerekend op een geschatte uitstapprijs "
                        "omdat de werkelijke niet bij de broker op te halen "
                        "was. Die cijfers zijn onbetrouwbaar: bij een trade "
                        "die op zijn doel sloot en daarna terugveerde, kan het "
                        "verschil tien dollar per trade zijn.",
                        self._geschatte_afwikkelingen,
                    )

            await self._record_broker_close(
                _TicketOnly(str(trade.broker_ticket)), settle, reason, now,
                bron=bron,
            )

    async def _zoek_activiteit(self, trade) -> dict | None:
        """Uitstapprijs uit het activiteitenoverzicht van de broker (1.7.3).

        None als de venue dat niet kent, de broker faalt of er nog niets
        staat. Raakt niets aan; alleen opvragen.
        """
        zoek = getattr(self.venue, "closed_deal_activity", None)
        if zoek is None or not trade.broker_ticket:
            return None
        try:
            gevonden = await zoek(
                str(trade.broker_ticket), trade.side, trade.open_price,
                _as_datetime(trade.open_time, None),
            )
        except VenueError as err:
            _LOGGER.debug(
                "Activiteit van %s niet op te halen: %s", trade.broker_ticket, err
            )
            return None
        if gevonden and gevonden.get("exit_price"):
            return gevonden
        return None

    async def _herkans_voorlopige_afwikkelingen(self, now: datetime) -> None:
        """Vraag de uitstapprijs van verse schattingen nog een paar keer na.

        1.7.3. Een sluiting op stop of doel staat soms pas na enkele seconden
        in het activiteitenoverzicht; bij het ontdekken was hij er dan net
        niet. Begrensd: hooguit :data:`HERKANSING_SCHEMA` pogingen, op vaste
        momenten na het afwikkelen (samen een paar minuten), één verzoek per
        poging. Daarna blijft de trade voorlopig en zoekt de gewone correctie
        hem in het transactieoverzicht, zoals voorheen.
        """
        if not self._herkansingen or self.run_id is None:
            return
        geschat = None
        for ticket, staat in list(self._herkansingen.items()):
            pogingen = staat["pogingen"]
            if pogingen >= len(HERKANSING_SCHEMA):
                self._herkansingen.pop(ticket, None)
                continue
            if (now - staat["sinds"]).total_seconds() < HERKANSING_SCHEMA[pogingen]:
                continue
            staat["pogingen"] = pogingen + 1
            if geschat is None:
                geschat = {
                    str(t.broker_ticket): t
                    for t in await self.hass.async_add_executor_job(
                        self.db.estimated_trades, self.run_id
                    )
                }
            trade = geschat.get(ticket)
            if trade is None:
                # Al gecorrigeerd (of uit een andere run): klaar.
                self._herkansingen.pop(ticket, None)
                continue
            gevonden = await self._zoek_activiteit(trade)
            if not gevonden:
                if staat["pogingen"] >= len(HERKANSING_SCHEMA):
                    self._herkansingen.pop(ticket, None)
                    _LOGGER.info(
                        "Uitstapprijs van %s na %d herkansingen nog niet bij de "
                        "broker; blijft voorlopig tot het transactieoverzicht "
                        "hem heeft.", ticket, staat["pogingen"],
                    )
                continue
            self._herkansingen.pop(ticket, None)
            oud = trade.net_pnl or 0.0
            await self._boek_brokerprijs(
                trade, gevonden, now, gevonden.get("source") or "broker_activity"
            )
            self._geschatte_afwikkelingen = max(0, self._geschatte_afwikkelingen - 1)
            _LOGGER.info(
                "Trade %s alsnog op de brokerprijs afgerekend bij herkansing %d: "
                "netto van %.2f naar %.2f (uitstapprijs %.2f).",
                ticket, staat["pogingen"], oud, trade.net_pnl or 0.0,
                trade.close_price,
            )

    async def _audit_against_broker(self) -> None:
        """Leg de brokerposities naast de eigen administratie.

        Tests toetsen of de code doet wat de bedoeling was; ze weten niet of
        die bedoeling klopt met hoe de broker zich gedraagt. Deze vergelijking
        vangt dat verschil - en daar zaten de ernstigste fouten: een
        deelsluiting die alles sloot, een stopverplaatsing die het doel wiste.

        De aanroep hiervan stond er wel, deze methode niet: een tekstvervanging
        die stil faalde. De vergelijking heeft daardoor nooit gedraaid, en elke
        cyclus waarin hij aan de beurt was, viel de hele lus om.
        """
        try:
            positions = await self._open_positions(refresh=True)
            account = await self.venue.account()
        except VenueError as err:
            _LOGGER.debug("Kon niet vergelijken met de broker: %s", err)
            return

        open_trades = await self._managed_open_trades(
            [str(getattr(p, "ticket", "")) for p in positions]
        )
        # De accountvaluta pas hier bekend; hem vastleggen zodat de omrekening
        # weet of er iets om te rekenen valt.
        valuta = getattr(account, "currency", None)
        if valuta:
            # 1.7.5: nu door de broker bevestigd; vanaf hier wordt hij bewaard.
            self._valuta_onzeker = False
        if valuta and valuta != self.conversion.account:
            self.conversion.account = valuta
            note = self.conversion.note()
            if note:
                _LOGGER.warning("Valuta: %s", note)

        # 1.7.8: sluitverzoeken die de broker verwerkt heeft (positie weg)
        # vergeten; de rest gaat mee naar de vergelijking.
        live = {str(getattr(p, "ticket", "")) for p in positions}
        self._sluitverzoeken = {
            t: m for t, m in self._sluitverzoeken.items() if t in live
        }
        audit = compare_positions(
            positions, open_trades,
            expected_currency=self.conversion.instrument,
            account_currency=valuta,
            conversion_known=self.conversion.usable,
            sluitingen=self._sluit_leeftijden(),
        )
        self.audit = audit.as_dict()

        # Eén melding per bevinding, niet per controle.
        #
        # De vergelijking draait elke tiende cyclus, en dezelfde toestand duurt
        # vaak veel langer dan dat. Zonder onderdrukking staat het logboek vol
        # met dezelfde regel - precies wat ik bij de roosterwaarschuwing wél
        # had opgelost en hier vergat.
        #
        # De sleutel bevat het ticket, zodat een nieuwe positie met hetzelfde
        # probleem wel weer meldt.
        nieuw = {
            f"{f.code}:{f.ticket or ''}": f for f in audit.findings
        }
        for sleutel, finding in nieuw.items():
            if sleutel in self._audit_gemeld:
                continue
            log = _LOGGER.error if finding.severity == "kritiek" else _LOGGER.warning
            log("Controle: %s", finding.message)
        self._audit_gemeld = set(nieuw)

        if audit.critical:
            self.executor_notes = [f.message for f in audit.critical][:3]
            self.risk.halt(
                "administratie en broker lopen uiteen: "
                + audit.critical[0].message
            )
            await self.notifier.alert(
                "audit", "Gold Scalper: administratie klopt niet",
                audit.critical[0].message,
            )

    def _sluit_leeftijden(self) -> dict[str, float]:
        """Seconden sinds elk eigen sluitverzoek dat nog niet verwerkt is."""
        nu = time.monotonic()
        return {t: nu - m for t, m in self._sluitverzoeken.items()}

    def _track_excursion(self, position, quote: VenueQuote, ticket: str) -> None:
        """Werk de uiterste mee- en tegenbeweging van een open positie bij."""
        entry = float(getattr(position, "open_price", 0) or 0)
        if entry <= 0:
            return
        long = getattr(position, "side", "buy") == "buy"
        direction = 1.0 if long else -1.0
        # Op de prijs waarop je zou uitstappen, niet op de mid: dat is de
        # beweging die je werkelijk had kunnen realiseren.
        exit_price = quote.bid if long else quote.ask
        excursion = (exit_price - entry) * direction

        record = self._excursions.setdefault(ticket, {"mfe": 0.0, "mae": 0.0})
        record["mfe"] = max(record["mfe"], excursion)
        record["mae"] = min(record["mae"], excursion)

    async def _consider_pyramid(self, position, quote: VenueQuote, ticket: str) -> None:
        """Koop bij als de markt de richting bevestigt.

        Het spiegelbeeld van middelen: bij middelen vergroot je een positie die
        ongelijk krijgt, hier alleen een die gelijk krijgt. De stop schuift bij
        elke toevoeging mee, zodat het totale risico niet groeit.
        """
        state = self._pyramid_state.setdefault(
            ticket, {"additions": 0, "last_price": None, "original": None}
        )
        units_now = float(getattr(position, "units", 0) or 0)
        if state["original"] is None:
            state["original"] = units_now
        if units_now <= 0:
            return

        long = getattr(position, "side", "buy") == "buy"
        price = quote.bid if long else quote.ask
        costs = self.strategy_cfg.expected_slippage * 2 + quote.spread

        decision = consider_addition(
            self.pyramid,
            side=getattr(position, "side", "buy"),
            entry_price=float(getattr(position, "open_price", price)),
            current_price=price,
            current_stop=getattr(position, "stop_loss", None),
            original_units=state["original"],
            total_units=units_now,
            additions_done=state["additions"],
            last_addition_price=state["last_price"],
            atr=self.state.atr.value or 0.0,
            round_trip_cost_per_oz=costs,
        )
        if not decision.add:
            return

        try:
            # Eerst de stop verplaatsen, dan pas bijkopen. Andersom sta je
            # kortstondig met een grotere positie achter een te ruime stop, en
            # precies dan kan de verbinding wegvallen.
            await self.venue.modify_stop(
                ticket, decision.new_stop,
                take_profit=getattr(position, "take_profit", None),
            )
            result, notes = await self.executor.open_protected(
                self.symbol,
                getattr(position, "side", "buy"),
                decision.units,
                quote.mid,
                stop_loss=decision.new_stop,
                take_profit=getattr(position, "take_profit", None),
            )
        except VenueError as err:
            _LOGGER.warning("Bijkopen mislukte: %s", err)
            return

        if not result.success:
            _LOGGER.warning("Bijkopen niet geplaatst: %s", result.error)
            return

        state["additions"] += 1
        state["last_price"] = price
        self._positions_cache = None
        _LOGGER.info("Bijgekocht: %s", decision.reason)

    async def _record_partial(
        self, ticket: str, units: float, reason: str, now: datetime
    ) -> None:
        """Boek een gedeeltelijke sluiting als aparte gesloten trade.

        De resterende positie blijft open met de overgebleven omvang. Zo telt
        de genomen winst mee in het resultaat en in de bewijsfase, en blijft
        het spoor van wat er gebeurd is intact.
        """
        if self._last_quote is None:
            return

        trade = await self._open_trade_by_ticket(ticket)
        if trade is None:
            _LOGGER.debug("Deelsluiting van %s niet in de database gevonden", ticket)
            return

        quote = self._last_quote
        long = trade.side == "buy"
        exit_price = quote.bid if long else quote.ask
        direction = 1.0 if long else -1.0
        closed_lots = units / CONTRACT_SIZE

        # Het gesloten deel als eigen rij, met de rest van de gegevens van de
        # oorspronkelijke trade.
        part = Trade(
            run_id=trade.run_id, mode=self.mode.value, symbol=trade.symbol,
            side=trade.side, volume=closed_lots,
            open_time=trade.open_time, open_price=trade.open_price,
            open_mid=trade.open_mid, open_spread=trade.open_spread,
            open_slippage=trade.open_slippage,
            close_time=now.isoformat(), close_price=exit_price,
            close_mid=quote.mid, close_spread=quote.spread,
            close_reason="partial_close",
            stop_loss=trade.stop_loss, take_profit=trade.take_profit,
            signal_score=trade.signal_score, regime=trade.regime,
            broker_ticket=f"{ticket}-deel",
            execution_semantics=trade.execution_semantics,
            exit_regime=trade.exit_regime,
            mfe=(self._excursions.get(str(ticket), {}).get("mfe", 0.0)) * units,
            mae=(self._excursions.get(str(ticket), {}).get("mae", 0.0)) * units,
            gross_pnl=round((quote.mid - trade.open_mid) * direction * units, 4),
            net_pnl=round((exit_price - trade.open_price) * direction * units, 4),
        )
        part.total_cost = round((part.gross_pnl or 0) - (part.net_pnl or 0), 4)
        part.cost_source = "measured"
        part.duration_seconds = int(
            (now - _as_datetime(trade.open_time, now)).total_seconds()
        )
        await self.hass.async_add_executor_job(self.db.insert_trade, part)

        # De oorspronkelijke rij krimpt tot wat er nog openstaat.
        trade.volume = max(0.0, trade.volume - closed_lots)
        await self.hass.async_add_executor_job(self.db.update_trade, trade)

        self.risk.record_close(part.net_pnl or 0.0, now)
        _LOGGER.info(
            "Deel genomen: %.2f oz, netto %.2f. %s",
            units, part.net_pnl or 0.0, reason,
        )

    async def _record_broker_open(
        self, result, signal, quote: VenueQuote, side: str, now: datetime
    ) -> None:
        """Leg een order bij de broker vast als open trade."""
        fill = result.fill_price or (quote.ask if side == "buy" else quote.bid)
        mid = quote.mid
        # Slippage meten in plaats van modelleren: dat is het hele punt van
        # handelen op een demo-account.
        expected = quote.ask if side == "buy" else quote.bid
        slippage = abs(fill - expected)

        trade = Trade(
            run_id=self.run_id,
            mode=self.mode.value,
            symbol=self.symbol,
            side=side,
            volume=(result.units or self.units) / CONTRACT_SIZE,
            open_time=now.isoformat(),
            open_price=fill,
            open_mid=mid,
            open_spread=quote.spread,
            open_slippage=round(slippage, 5),
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            signal_score=signal.score,
            signal_confidence=signal.confidence,
            execution_semantics=EXECUTION_SEMANTICS_VERSION,
            # 1.7.6: alleen statistiek, zit niet in de vingerafdruk.
            exit_regime=EXIT_REGIME_HUIDIG,
            regime=(signal.components or {}).get("regime"),
            # Indicatorwaarden op het instapmoment vastleggen.
            #
            # Deze werden berekend, gebruikt voor de beslissing en weggegooid.
            # Zonder ze is geen correlatieanalyse mogelijk: er is niets om de
            # uitkomst tegen af te zetten, en dan is een vraag als "welke
            # marktomstandigheden zijn winstgevend" onbeantwoordbaar - niet
            # vanwege te weinig trades maar omdat de gegevens ontbreken.
            #
            # Puur observatie: ze veranderen geen enkele beslissing.
            entry_atr=(signal.components or {}).get("atr"),
            entry_adx=(signal.components or {}).get("adx"),
            entry_rsi=(signal.components or {}).get("rsi_reversion"),
            entry_ema_dist=(signal.components or {}).get("ema_dist"),
            entry_trend=(signal.components or {}).get("trend"),
            entry_momentum=(signal.components or {}).get("momentum"),
            entry_sentiment_long=(self.sentiment or {}).get("long"),
            entry_williams_r=(signal.components or {}).get("williams_r"),
            entry_cci=(signal.components or {}).get("cci"),
            broker_ticket=str(result.ticket) if result.ticket else None,
        )
        await self.hass.async_add_executor_job(self.db.insert_trade, trade)

        # Meteen een beginwaarde zetten. Een positie die tussen twee cycli
        # opent en sluit, of die de broker sluit voordat de lus hem ziet, werd
        # anders nooit gemeten - en dan blijft mfe leeg en slaat de
        # verliesanalyse die trade over. Zeventien van drieëndertig trades
        # kwamen zo nooit in de ontleding terecht, terwijl de teller ze wel
        # meerekende.
        if result.ticket:
            self._excursions.setdefault(
                str(result.ticket), {"mfe": 0.0, "mae": 0.0}
            )

        _LOGGER.info(
            "Trade vastgelegd: %s %s @ %.2f (ticket %s, slippage %.3f)",
            side, self.symbol, fill, result.ticket, slippage,
        )

    async def _record_broker_close(
        self, position, quote: VenueQuote, reason: str, now: datetime,
        bron: str = "broker_transactions",
    ) -> None:
        """Werk de open trade bij tot een gesloten trade.

        Zonder dit blijft de rij eeuwig open staan en telt hij nergens in mee:
        de bewijsfase kijkt naar gesloten trades.
        """
        ticket = str(getattr(position, "ticket", "") or "")
        if not ticket:
            return

        # In welke run ook; de trade wordt in zijn eigen run afgerekend.
        trade = await self._open_trade_by_ticket(ticket)
        if trade is None:
            _LOGGER.debug(
                "Positie %s gesloten maar niet in de database gevonden", ticket
            )
            return

        long = trade.side == "buy"
        exit_price = quote.bid if long else quote.ask
        direction = 1.0 if long else -1.0
        units = trade.volume * CONTRACT_SIZE

        trade.close_time = now.isoformat()
        trade.close_price = exit_price
        trade.close_mid = quote.mid
        trade.close_spread = quote.spread
        trade.close_reason = reason
        trade.duration_seconds = int(
            (now - _as_datetime(trade.open_time, now)).total_seconds()
        )
        # Bruto op de mids: dat is de beweging die de strategie ving.
        # Uitersten meenemen. Zonder deze twee kan de verliesanalyse niet
        # vaststellen of een verlies aan het ontwerp lag of aan de markt.
        excursion = self._excursions.pop(ticket, None)

        # Ook terugvallen als de meting nog op nul staat.
        #
        # Bij het openen wordt {0,0} gezet zodat de sleutel bestaat. Sluit de
        # positie voordat de beheerlus hem heeft gezien - en dat gebeurt bij
        # ruim zestig procent van de trades - dan blijven beide nul. De
        # verliesanalyse leest dat als "nauwelijks beweging in beide
        # richtingen" en stempelt de trade als 'geen_vervolg'.
        #
        # Dat leverde 94% 'geen_vervolg' op: geen bevinding maar een artefact
        # van deze code. Een niet-gemeten trade hoort als onbekend te gelden,
        # niet als bewijs voor een conclusie.
        if excursion is not None and excursion["mfe"] == 0.0 and excursion["mae"] == 0.0:
            excursion = None

        if excursion is None:
            # Nooit door de beheerlus gezien. Dan is het beste dat we hebben de
            # uitkomst zelf: die begrenst de beweging aan minstens één kant.
            # Dat is minder nauwkeurig dan een gemeten uiterste, maar veel beter
            # dan de trade helemaal buiten de verliesanalyse laten.
            beweging = (exit_price - trade.open_price) * direction
            excursion = {
                "mfe": max(0.0, beweging), "mae": min(0.0, beweging),
            }
        trade.mfe = round(excursion["mfe"] * units, 4)
        trade.mae = round(excursion["mae"] * units, 4)

        trade.gross_pnl = round(
            (quote.mid - trade.open_mid) * direction * units, 4
        )
        # Netto op de werkelijke prijzen: daar zit de spread en de slippage in.
        trade.net_pnl = round(
            (exit_price - trade.open_price) * direction * units, 4
        )
        trade.total_cost = round(trade.gross_pnl - trade.net_pnl, 4)
        # Alleen een eigen sluitorder levert gemeten kosten. Een positie die de
        # broker sloot, wordt afgerekend op prijzen van verschillende momenten;
        # die kosten zijn berekend, niet gemeten.
        afwikkeling = reason in (
            "stop_loss", "take_profit", "broker_gesloten",
            "broker_gesloten_geschat", "broker_gesloten_gemeten",
        )
        trade.cost_source = "calculated" if afwikkeling else "measured"

        self._record_account_amount(trade)

        # De oorspronkelijke sluitreden: één keer gezet, nooit overschreven.
        trade.original_close_reason = reason
        if reason == "broker_gesloten_geschat":
            # Uitstapprijs nog niet van de broker: later opzoeken.
            trade.reconciliation_status = "pending"
            trade.close_reason_source = "estimated"
        elif reason == "broker_gesloten_gemeten":
            # Uitstapprijs direct van de broker: meteen afleiden, met bewijs.
            self._apply_reconciliation(trade, exit_price, now, bron)
        elif reason in ("stop_loss", "take_profit") and afwikkeling:
            # Afgeleid uit de koers op het moment van ontdekken: de koers stond
            # voorbij het niveau. Een aanwijzing, geen bevestiging van de broker.
            trade.close_reason_source = "inferred_from_quote"
        else:
            trade.close_reason_source = "own_order"

        await self.hass.async_add_executor_job(self.db.update_trade, trade)
        self.risk.record_close(trade.net_pnl, now)
        _LOGGER.info(
            "Trade gesloten: %s, bruto %.2f, kosten %.2f, netto %.2f",
            reason, trade.gross_pnl, trade.total_cost, trade.net_pnl,
        )

    # -- afsluiten ---------------------------------------------------------- #

    async def async_shutdown_hook(self) -> None:
        """Bij het HA-stop-event en bij het ontladen: administratie veiligstellen.

        1.7.5: wacht eerst (begrensd) op een lopende cyclus, bewaart dan de
        toestand en de uitkomsten, en sluit pas daarna de bestanden - buiten de
        eventloop. Eerst werd de toestand hier niet bewaard, gingen flush en
        sluiten in de eventloop zelf, en bleef het archief open. Wordt hij
        twee keer aangeroepen (stop-event én ontladen), dan doet de tweede
        keer niets.
        """
        if self._afgesloten:
            return
        verkregen = False
        try:
            await asyncio.wait_for(
                self._cyclus_slot.acquire(), timeout=self.AFSLUITEN_WACHT_S
            )
            verkregen = True
        except (asyncio.TimeoutError, TimeoutError):
            _LOGGER.warning(
                "Lopende cyclus na %.0f s niet klaar; er wordt toch afgesloten.",
                self.AFSLUITEN_WACHT_S,
            )
        try:
            if self._afgesloten:
                return
            self._afgesloten = True
            try:
                await self._persist()
            except Exception:  # noqa: BLE001 - afsluiten gaat altijd door
                _LOGGER.exception("Toestand bewaren bij afsluiten mislukt")
            await self._bewaar_resultaten(direct=True)

            # De run bewust NIET afsluiten bij een herstart.
            #
            # end_run zet ended_at, en find_matching_run zoekt alleen naar runs
            # zonder ended_at. Elke herstart sloot de run dus af en de volgende
            # start herkende hem niet meer - precies het gedrag dat de
            # adoptiefunctie moest voorkomen. Vijf herstarts leverden vijf
            # runs op, elk met een handvol trades, en een bewijsfase van
            # dertig dagen wordt dan nooit gehaald.
            #
            # Een run hoort alleen te eindigen als de opzet wijzigt of als je
            # er zelf een nieuwe begint.
            await self.hass.async_add_executor_job(self._sluit_bestanden)
            await self.lifecycle.emergency_shutdown([])
        finally:
            if verkregen:
                self._cyclus_slot.release()

    def _sluit_bestanden(self) -> None:
        """Signalen wegschrijven, dan database en archief sluiten (in een thread).

        Eerst wegschrijven, dan sluiten: anders vielen de gebufferde
        evaluaties weg. Elk onderdeel apart, zodat een fout in het ene het
        andere niet tegenhoudt.
        """
        if self.db is not None:
            flush = getattr(self.db, "flush_signals", None)
            if flush is not None:
                try:
                    flush()
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Signalen wegschrijven bij afsluiten mislukt")
            try:
                self.db.close()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Database sluiten mislukt")
        if self.archive is not None:
            try:
                self.archive.close()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Archief sluiten mislukt")
