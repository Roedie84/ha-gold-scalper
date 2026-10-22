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
import contextvars
import functools
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
from .analysis.volatility import atr as _atr_reeks
from .broker.adapter import (
    ExecutionVenue, OrderResult, VenueError, VenueQuote, size_says_closed, size_is_known,
)
from .broker.execution_safety import BrokerLimits, SafeExecutor
from .broker.currency import Conversion, derive_rate_from_position
from .broker.reconcile_audit import SLUIT_GENADE_SECONDEN, compare_positions

#: 1.7.9: hoe vaak een afgewezen sluiting automatisch opnieuw mag, en de
#: wachttijd (s) na de eerste, tweede, ... weigering. Geen sluitstorm.
SLUIT_MAX_POGINGEN = 5
SLUIT_BACKOFF = (10, 30, 60, 120)
from .broker.schedule import (
    SPOT_GOLD, ClosureObservation, bij_roostergrens, cross_check, minutes_until_close,
)
from .broker.exits import ExitConfig, ExitManager, omkeer_actie, scalp_exit_config
from .broker import uitvoering as uitvoering_mod
from .learning import onderzoek as onderzoek_mod
from .broker.ig_capital import CapitalVenue, IgVenue
from .broker.oanda import OandaVenue
from .broker.public_data import PublicDataVenue
from .broker.stooq import StooqVenue
from .broker.simulator import SimulatorVenue
from .broker.paper import CONTRACT_SIZE, BrokerCosts, InsufficientMargin, PaperBroker
from .broker.paper import Quote as PaperQuote
from .broker.risk import RiskLimits, RiskManager, TradingState
from .broker.saldosprong import SaldoSprongBewaker
from .const import (
    CONF_SCALP_TURBO,
    CONF_SCALP_UIT,
    CONF_VP_TIJDVAKKEN_UIT,
    CONF_SCALP_TURBO_ORDERS,
    DEFAULT_SCALP_TURBO,
    DEFAULT_SCALP_TURBO_ORDERS,
    TURBO_MIN_INTERVAL_S,
    CONF_SCALP_REEKS,
    CONF_SCALP_REEKS_STAP,
    CONF_SCALP_REEKS_MAX,
    CONF_SCALP_REEKS_DOEL,
    DEFAULT_SCALP_REEKS,
    DEFAULT_SCALP_REEKS_STAP,
    DEFAULT_SCALP_REEKS_MAX,
    DEFAULT_SCALP_REEKS_DOEL,
    STRATEGY_WINDOW_BARS,
    EXECUTION_SEMANTICS_VERSION,
    EXIT_REGIME_HUIDIG,
    INTEGRATION_VERSION,
    ARCHIVE_FILENAME,
    CONF_ACCOUNT_ID, CONF_API_KEY, CONF_ASSUMED_SPREAD, CONF_BUILD_FROM_QUOTES,
    CONF_NOTIFY_CRITICAL, CONF_NOTIFY_HOURLY, CONF_NOTIFY_SERVICE,
    CONF_CLOSE_BUFFER_MINUTES, CONF_USE_SCHEDULE,
    CONF_NOTIFY_SKIP_QUIET, CONF_PYRAMID_ENABLED, CONF_PYRAMID_MAX_ADDITIONS,
    CONF_MAX_POSITIONS_PER_RICHTING, DEFAULT_MAX_POSITIONS_PER_RICHTING,
    MAX_POSITIONS_PER_RICHTING_GRENS,
    CONF_PYRAMID_TRIGGER_ATR, CONF_RISK_BASED_SIZING, CONF_RISK_PER_TRADE_PCT,
    CONF_SCALE_WITH_CONFIDENCE, CONF_STOP_LOSS_ATR, CONF_STOP_LOSS_USD,
    CONF_TAKE_PROFIT_ATR, CONF_TAKE_PROFIT_USD, NOTIFY_NONE,
    CONF_ENFORCE_TRADING_HOURS,
    CONF_EPIC, CONF_IDENTIFIER, CONF_PASSWORD, DEFAULT_EPIC, VENUE_CAPITAL, VENUE_IG,
    VENUE_CTRADER, CONF_CT_CLIENT_ID, CONF_CT_CLIENT_SECRET,
    VENUE_BITVAVO, CONF_BV_KEY, CONF_BV_GEHEIM, CONF_BV_MARKT, CONF_BV_MAX_INZET,
    DEFAULT_BV_MAX_INZET,
    CONF_CT_ACCESS_TOKEN, CONF_CT_REFRESH_TOKEN, CONF_CT_TRADER_LOGIN, CONF_CT_CTID,
    CONF_REGIME_SWITCHING, DEFAULT_ASSUMED_SPREAD, VENUE_PUBLIC,
    VENUE_STOOQ,
    CONF_SIM_SEED, CONF_SIM_SPREAD, CONF_VENUE,
    CONF_STRATEGIE, DEFAULT_STRATEGIE, STRATEGIE_DAGHANDEL, STRATEGIE_SCALP, STRATEGIE_COMBINATIE,
    STRATEGIE_ALLES,
    CONF_SCALP_UNITS, DEFAULT_SCALP_UNITS, DEFAULT_SIM_SEED, DEFAULT_SIM_SPREAD, DEFAULT_VENUE, VENUE_SIMULATOR, CONF_ENTRY_THRESHOLD, CONF_ENVIRONMENT, CONF_EQUITY_FLOOR_PCT,
    CONF_MAX_CONSECUTIVE_LOSSES, CONF_MAX_DAILY_LOSS_PCT, CONF_MAX_RESUMES_PER_DAY, CONF_MAX_SPREAD, CONF_MAX_SPREAD_ATR,
    CONF_MAX_TRADES_PER_DAY, CONF_MAX_UNITS, CONF_MIN_EDGE_MULTIPLE, CONF_MODE,
    CONF_STARTING_BALANCE, CONF_SYMBOL, CONF_TIMEFRAME, CONF_TOKEN,
    CONF_TRADING_END_HOUR, CONF_TRADING_START_HOUR, CONF_UNITS, CONF_UPDATE_SECONDS,
    DATABASE_FILENAME, DEFAULT_ENVIRONMENT, DEFAULT_MAX_UNITS, DEFAULT_MODE,
    DEFAULT_STARTING_BALANCE, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME, DEFAULT_UNITS,
    DEFAULT_UPDATE_SECONDS, DOMAIN, MIN_UPDATE_SECONDS, MIN_WARMUP_CANDLES,
    WARMUP_CANDLES, KOERS_HOUD_MAX_MISLUKT, KOERS_HOUD_MAX_SECONDEN,
    AFWIKKELFOUT_MELDING,
    WEES_INTERVAL_S,
    WEES_PER_RONDE,
    WEES_MAX_LEEFTIJD_H,
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
from .strategy.scalping import STRATEGY_VERSION, ScalpConfig, ScalpSignal, evaluate
from .strategy import combinatie as combinatie_mod
from .strategy import daghandel as daghandel_mod
from .strategy.aggregator import BAR_SECONDS
from .strategy.posities import (
    MAX_RISICO_PER_ORDER_USD, marge_en_vloer_ok, netting_uit_posities, richting_van,
    risico_plafond, risicolimieten_ok, spreiding_ok,
    tel_per_richting,
)
from .strategy.tijdstopvarianten import VariantenBoek, VariantTrade
from .strategy.schaduw import (
    SCHADUW_REDENEN, SchaduwBoek, SchaduwKosten, SchaduwTrade,
)
from .learning.robustness import evaluate_robustness
from .learning.sessions import build_news_impact, build_sessions
from .strategy.aggregator import BAR_SECONDS, QuoteAggregator, closed_only
from .strategy import veldproef as veldproef_mod
from .strategy import schaal as schaal_mod
from .strategy import uitgezet_schaduw as uitgezet_mod
from .strategy import bevestiging as bevestiging_mod
from .strategy import turbo as turbo_mod
from .strategy.pyramid import PyramidConfig, consider_addition
from .strategy.scalp_reeks import ReeksConfig, stukken_nu
from .strategy.sizing import SizingConfig, position_size
from .strategy.streaming import StreamState

#: 2.7.0: de afstemming kijkt hooguit zo ver terug voor nog niet afgestemde trades.
AFSTEMMING_MAX_DAGEN = 10.0
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


def _per_richting(value) -> int:
    """1.9.0: posities per richting, begrensd op 1..3."""
    n = _as_int(value, DEFAULT_MAX_POSITIONS_PER_RICHTING)
    return max(1, min(MAX_POSITIONS_PER_RICHTING_GRENS, n))


#: 1.7.3: na zoveel seconden na een afwikkeling op een schatting wordt de
#: uitstapprijs opnieuw bij de broker nagevraagd (activiteitenoverzicht en
#: bevestiging). Vier pogingen in vier minuten, één verzoek per poging; daarna
#: neemt de gewone correctie het over. De lus draait elke twintig seconden, dus
#: een poging valt hooguit een cyclus later dan gepland.
HERKANSING_SCHEMA = (20, 60, 120, 240)


def _leeg_accountantwoord(balance, equity, laatst) -> bool:
    """2.19.1: saldo en equity precies 0 na een gemeten positieve equity."""
    try:
        return (float(balance) == 0.0 and float(equity) == 0.0
                and float(laatst or 0.0) > 0.0)
    except (TypeError, ValueError):
        return False


@dataclass(slots=True)
class _TicketOnly:
    """Minimale positieverwijzing voor het afsluiten van een verdwenen trade.

    Alleen het ticketnummer is nodig; de rest staat al in de database. Een
    klasse in plaats van een dict-truc, zodat de attribuutnaam vastligt.
    """

    ticket: str



def scalp_handmatig(netto: list[float]) -> dict:
    """2.9.3: scalp met de hand uit; zelfde vorm als ``groep_uitgezet``."""
    t = veldproef_mod.t_statistiek(netto) if len(netto) >= 2 else None
    return {"n": len(netto), "netto": round(sum(netto), 2),
            "t": round(t, 2) if t is not None else None, "handmatig": True}


def _commissie_venue(venue) -> float:
    """USD per lot per zijde van de venue; 0 als hij er geen opgeeft (2.9.3)."""
    waarde = getattr(venue, "commissie_per_lot_per_zijde", 0.0)
    return float(waarde) if isinstance(waarde, (int, float)) and waarde > 0 else 0.0


def deel_units(gevraagd: float, bevestigd) -> float:
    """Hoeveel er bij een deelsluiting echt dicht ging (2.9.2).

    De broker bevestigt soms minder dan gevraagd (afronding op de volumestap);
    nooit meer dan gevraagd boeken, en zonder bevestigd aantal het gevraagde.
    """
    try:
        b = float(bevestigd)
    except (TypeError, ValueError):
        return gevraagd
    if b <= 0 or b > gevraagd + 1e-9:
        return gevraagd
    return b


def _met_schaal(func):
    """2.17.0: zet de prijs-/eenheidsschaal van deze coordinator voor de duur
    van de aanroep en zet daarna de vorige terug. Zonder dat erft een
    volgende coordinator in dezelfde taak (de diensten lopen over alle
    entries) de schaal van deze."""
    @functools.wraps(func)
    async def omhulsel(self, *args, **kwargs):
        token = schaal_mod.zet(self._schaal_nu())
        try:
            return await func(self, *args, **kwargs)
        finally:
            schaal_mod.terug(token)
    return omhulsel


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
        # 2.17.0: Bitvavo heeft geen demo-account; demo betekent daar papier.
        if (options.get(CONF_VENUE) == VENUE_BITVAVO
                and self.requested_mode is TradingMode.DEMO):
            self.requested_mode = TradingMode.PAPER
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
        elif venue_name == VENUE_CTRADER:
            # 2.8.0: Pepperstone via de cTrader Open API. De tokens staan in
            # de entry (bij het instellen uit secrets.yaml gelezen); een
            # ververst token wordt teruggeschreven.
            from .broker.ctrader import CTraderVenue

            self.venue = CTraderVenue(
                session=async_get_clientsession(hass),
                client_id=options.get(CONF_CT_CLIENT_ID) or "",
                client_secret=options.get(CONF_CT_CLIENT_SECRET) or "",
                access_token=options.get(CONF_CT_ACCESS_TOKEN) or "",
                refresh_token=options.get(CONF_CT_REFRESH_TOKEN),
                trader_login=options.get(CONF_CT_TRADER_LOGIN) or None,
                ctid_account_id=options.get(CONF_CT_CTID),
                environment=options.get(CONF_ENVIRONMENT, "demo"),
                symbol_name=self.symbol,
                trading_enabled=False,
                max_units=options.get(CONF_MAX_UNITS, DEFAULT_MAX_UNITS),
                tokens_bewaren=self._bewaar_ctrader_tokens,
            )
        elif venue_name == VENUE_BITVAVO:
            # 2.17.0: Bitvavo (crypto spot). Papier: live koersen, uitvoering
            # gesimuleerd met de echte tarieven. Live: echte orders, pas na de
            # bewijsfase (zie _refresh_gate).
            from .broker.bitvavo import STAND_LIVE, STAND_PAPER, BitvavoVenue

            self.symbol = options.get(CONF_BV_MARKT) or self.symbol
            self.venue = BitvavoVenue(
                session=async_get_clientsession(hass),
                market=self.symbol,
                api_key=options.get(CONF_BV_KEY) or None,
                api_secret=options.get(CONF_BV_GEHEIM) or None,
                stand=STAND_LIVE if self.mode.uses_real_money else STAND_PAPER,
                trading_enabled=False,
                max_inzet=options.get(CONF_BV_MAX_INZET, DEFAULT_BV_MAX_INZET),
                bewaren=self._bewaar_bitvavo_posities,
            )
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

        #: 2.0.0 (L-GS-014): daghandel of scalpen.
        self._strategie: str = options.get(CONF_STRATEGIE, DEFAULT_STRATEGIE)
        #: 2.1.0: vaste grootte van scalptrades bij de combinatie.
        self._scalp_units: float = float(options.get(CONF_SCALP_UNITS, DEFAULT_SCALP_UNITS))
        #: 2.1.0: laatste instap per strategie (cooldown per strategie).
        self._laatste_instap: dict[str, float] = {}
        #: 2.1.0: strategie per ticket (cache van trades.strategie).
        self._strategie_per_ticket: dict[str, str] = {}
        #: 2.1.0: laatste signaal per strategie en resultaat per strategie.
        self._signalen: dict[str, object] = {}
        self._per_strategie: dict = {}
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
            # IG/OANDA rekenen in de spread; cTrader (Pepperstone Razor) rekent
            # commissie per lot per zijde (2.9.3).
            commission_per_lot_per_side=_commissie_venue(self.venue),
            # 2.17.0: crypto: geen aangenomen slippage in USD/oz; de spread en
            # het tarief staan apart.
            expected_slippage=0.0 if self._is_spot else 0.02,
            volume=self.units / CONTRACT_SIZE,
            # 1.9.0: tot zoveel posities per richting (besluit eigenaar).
            max_positions_per_richting=_per_richting(
                options.get(CONF_MAX_POSITIONS_PER_RICHTING)
            ),
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
                # 1.9.0: de limiet per richting staat in de strategie; hier
                # het totaal als vangnet (long en short samen).
                # 2.1.0: bij de combinatie komt er één daghandelpositie bij.
                max_open_positions=2 * self.strategy_cfg.max_positions_per_richting
                + (1 if options.get(CONF_STRATEGIE) == STRATEGIE_COMBINATIE else 0)
                # 2.4.0: bij 'alles' één positie per veldproefopzet erbij.
                + ((1 + len(veldproef_mod.namen()))
                   if options.get(CONF_STRATEGIE) == STRATEGIE_ALLES else 0),
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
        if self._is_spot:
            # 2.17.0: bij crypto zegt een aantal munten niets (5 BTC of 5 SHIB);
            # de grens is de inzet per koop (venue) en het risico tot de stop.
            self.sizing.max_units = 1e12
            self.risk.limits.max_volume = 1e12
            self.executor.limits.max_volume = 1e12
        self.pyramid = PyramidConfig(
            enabled=options.get(CONF_PYRAMID_ENABLED, False),
            trigger_atr=options.get(CONF_PYRAMID_TRIGGER_ATR, 1.0),
            max_additions=_as_int(options.get(CONF_PYRAMID_MAX_ADDITIONS), 2),
        )
        # 2.4.9: scalpreeks; vervangt voor scalp de ATR-piramide als hij aan staat.
        self.reeks = ReeksConfig(
            enabled=bool(options.get(CONF_SCALP_REEKS, DEFAULT_SCALP_REEKS)),
            stap_usd=float(options.get(CONF_SCALP_REEKS_STAP, DEFAULT_SCALP_REEKS_STAP)
                           or DEFAULT_SCALP_REEKS_STAP),
            max_stukken=_as_int(options.get(CONF_SCALP_REEKS_MAX), DEFAULT_SCALP_REEKS_MAX),
            doel_usd=float(options.get(CONF_SCALP_REEKS_DOEL, DEFAULT_SCALP_REEKS_DOEL)
                           or DEFAULT_SCALP_REEKS_DOEL),
        )
        # 2.5.0: turbo-scalp op de live koers (zie _turbo_tick).
        self.turbo_aan = bool(options.get(CONF_SCALP_TURBO, DEFAULT_SCALP_TURBO))
        self.turbo_orders_pm = max(1, _as_int(
            options.get(CONF_SCALP_TURBO_ORDERS), DEFAULT_SCALP_TURBO_ORDERS))
        self._turbo_orders: list[float] = []
        self._turbo_laatst = 0.0
        self._turbo_bezig = False
        self._turbo_afmelden = None
        self._turbo_ctx: dict | None = None
        self._turbo_stream = None
        #: 2.5.2: eigen uitbraaksignaal op de live ticks (zie strategy/turbo.py).
        self.turbo_signaal = turbo_mod.TickUitbraak()
        #: 2.5.5: laatste signaalrichting per strategie (omkeer-exit).
        self._richting_per_strategie: dict[str, int] = {}
        #: 2.13.3 (Ruud 16-10): de laatst geopende positie bepaalt de richting
        #: voor ALLE setups en tijdvakken: oudere posities de andere kant op
        #: worden gesloten (verlies) of hun winst wordt vastgezet.
        self._omkeer_alle: dict | None = None
        self._turbo_sig_instap = 0.0
        self.turbo_stats: dict = {"ticks": 0, "rondes": 0, "orders": 0,
                                  "bijkopen": 0, "laatste_order": None}
        #: Per ticket: hoeveel toevoegingen en op welke prijs de laatste.
        self._pyramid_state: dict[str, dict] = {}
        #: 2.2.0: tickets die zelf een bijkoop zijn (die piramiden niet verder).
        self._bijkopen: set[str] = set()
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
        # 2.4.7: afwikkeling van verweesde trades (zie _wikkel_wezen_af).
        self._wees_laatst: datetime | None = None
        self._wees_pogingen: dict[str, int] = {}
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
        #: 1.10.0: loopt er een afstemming (na de herstart en in de lus
        #: tegelijk zou dubbel opvragen zijn), en waarom de laatste mislukte.
        self._afstemming_bezig = False
        self._afstemming_fout: str | None = None
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
        #: 1.7.9: sluitverzoeken zonder bevestiging van de broker. Niet
        #: geboekt; de trade blijft open en bewaakt. ``{"sinds", "reden"}``.
        self._sluit_onderweg: dict[str, dict] = {}
        #: 1.7.9: afgewezen sluitingen per ticket, voor de herhaallimiet.
        #: ``{"weigeringen", "volgende", "opgegeven"}``.
        self._sluit_pogingen: dict[str, dict] = {}
        #: Aantal trades dat op een geschatte uitstapprijs is afgerekend.
        self._geschatte_afwikkelingen = 0
        #: Cyclusteller voor het bijwerken van geschatte afwikkelingen.
        self._correctie_teller = 0
        #: 1.7.3: verse schattingen die nog kort bij de broker worden
        #: nagevraagd: ``ticket -> {"pogingen", "sinds"}``.
        self._herkansingen: dict = {}
        # 1.11.0 (L-GS-012): afwikkelfouten per ticket (cycli op rij) en of
        # de afwikkeling in deze cyclus faalde (dan geen instap).
        self._afwikkelfouten: dict[str, int] = {}
        self._afwikkeling_mislukt = False
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
        # 2.17.0: crypto noteert in de valuta van de markt (BTC-EUR: EUR) en
        # het saldo staat in diezelfde valuta: dan is er niets om te rekenen.
        _valuta = getattr(self.venue, "instrument_currency", None)
        self.conversion = (Conversion(instrument=_valuta, account=_valuta)
                           if self._is_spot and _valuta else Conversion(instrument="USD"))
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
        self.exits = ExitManager(
            daghandel_mod.exit_config()
            if self._strategie in (STRATEGIE_DAGHANDEL, STRATEGIE_COMBINATIE)
            or self._strategie == STRATEGIE_ALLES
            else scalp_exit_config()
        )
        #: 2.1.0: het scalpexitbeheer voor scalpposities bij de combinatie.
        #: 2.5.1: met snelle break-even (stop naar instap bij +0,6 USD/oz).
        self._exits_scalp = ExitManager(scalp_exit_config())
        #: 2.4.0: veldproef - bars op 1m-30m, exitbeheer per opzet, laatste
        #: gebruikte signaalbar per opzet.
        self.veldproef = veldproef_mod.MeerTijdvakken()
        self._exits_vp: dict[str, ExitManager] = {}
        self._vp_laatste_bar: dict[str, int] = {}
        #: 2.5.6: bewezen verliezende opzetten (n >= 100, t < -2) en wanneer
        #: die lijst weer uit de database gelezen wordt.
        self._vp_uitgezet: dict[str, dict] = {}
        #: 2.6.1: scalp (incl. turbo) als groep uitgezet; None = aan.
        self._scalp_uitgezet: dict | None = None
        #: 2.9.3: met de hand uitgezet (optie); geldt meteen, ook vóór de
        #: eerste telling uit de database.
        self.scalp_handmatig_uit = bool(options.get(CONF_SCALP_UIT, False))
        #: 2.10.0: veldproef-tijdvakken met de hand uit; geldt meteen.
        self.vp_tijdvakken_uit = tuple(
            str(x) for x in (options.get(CONF_VP_TIJDVAKKEN_UIT) or ())
            if str(x) in veldproef_mod.TIJDVAKKEN)
        if self.vp_tijdvakken_uit:
            self._vp_uitgezet = veldproef_mod.handmatig_uitgezet({}, self.vp_tijdvakken_uit)
        if self.scalp_handmatig_uit:
            self._scalp_uitgezet = {"n": 0, "netto": 0.0, "t": None, "handmatig": True}
        #: 2.7.1 (H-GS-003): schaduwtrades van uitgezette groepen.
        self.uitgezet_schaduw = uitgezet_mod.UitgezetBoek()
        #: 2.11.0: schaduwmeting instap met bevestiging (15m), paarvergelijking.
        self.bevestiging = bevestiging_mod.BevestigingBoek(
            kosten=SchaduwKosten(slippage=uitgezet_mod.SLIPPAGE_PER_ZIJDE,
                                 commissie_per_lot=_commissie_venue(self.venue)))
        self._bevestiging_stats: dict = self.bevestiging.statistiek([])
        #: 2.12.0: kostenfilter veldproef (overgeslagen signalen).
        self._kostenfilter: dict = {"overgeslagen": 0, "per_opzet": {}, "laatste": None}
        self._laatste_weigering: str | None = None
        self._bevestiging_geladen = False
        self._vp_uitgezet_volgende = 0.0
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
        #: 2.7.0: (tijd, bid, ask) van de laatste live tick.
        self._laatste_tick: tuple | None = None
        #: 2.7.0: onderzoeksrapport (learning/onderzoek.py).
        self.onderzoek: dict = {}
        self._onderzoek_volgende = 0.0
        #: 2.7.0: (tijdstempel, richting) van recente instappen; risico-info.
        self._recente_instappen: list[tuple[float, int]] = []
        self.risico_info: dict = {}
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
        #: 1.9.0: posities geopend in de lopende cyclus (hooguit één).
        self._geopend_in_cyclus = 0
        #: 1.9.0: vrije marge zoals de broker hem deze cyclus meldde
        #: (accountvaluta); None = niet gemeld.
        self._marge_vrij: float | None = None
        #: 1.9.0: gedetecteerde verrekening van tegengestelde posities. Zolang
        #: dit gezet is, wordt er niet gehedged (geen positie tegen een open
        #: positie in).
        self.netting: dict | None = None
        #: 1.9.0: schaduwtrades (gesimuleerd, eigen tabel).
        self.schaduw = SchaduwBoek(
            exits=self.exits,
            kosten=SchaduwKosten(
                slippage=self.strategy_cfg.expected_slippage,
                commissie_per_lot=self.strategy_cfg.commission_per_lot_per_side,
            ),
            bar_seconden=BAR_SECONDS.get(self.timeframe, 60),
        )
        self._schaduw_stats: dict = self.schaduw.statistiek()
        #: 1.9.5: tijdstopvarianten (L-GS-008). Alleen meting: leest de
        #: configuratie van ``self.exits`` en kopieert die; wijzigt niets.
        self.varianten = VariantenBoek(
            exits=self.exits,
            kosten=SchaduwKosten(
                slippage=self.strategy_cfg.expected_slippage,
                commissie_per_lot=self.strategy_cfg.commission_per_lot_per_side,
            ),
        )
        self._varianten_stats: dict = self.varianten.statistiek()
        self._varianten_vuil = False
        self._varianten_teller = 0
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
        #: 2.18.0: de Bitvavo-mand waar deze lus bij hoort (zie mand.py).
        self._mand = None
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

    @_met_schaal
    async def async_setup(self) -> None:
        """Toestand herstellen, database openen, historie ophalen, afstemmen."""
        # 2.17.0: Bitvavo: grootboek terug en marktgegevens ophalen; daarna de
        # schaal voor alles wat bij het opstarten rekent.
        await self._laad_bitvavo_posities()
        self._zet_schaal()
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

        # 2.8.0: een eigen database per broker naast IG. Eén gedeelde database
        # zou de trades van twee brokers in dezelfde afstemming, hetzelfde
        # onderzoek en dezelfde statistiek laten lopen.
        bestand = DATABASE_FILENAME
        if getattr(self.venue, "name", None) == VENUE_CTRADER:
            bestand = "gold_scalper_ctrader.db"
        elif getattr(self.venue, "name", None) == VENUE_BITVAVO:
            # 2.17.0: per markt een eigen database (eigen runs en statistiek).
            bestand = f"gold_scalper_bitvavo_{self.symbol.lower().replace('-', '_')}.db"
        path = self.hass.config.path(bestand)
        self.db = TradeDatabase(path)
        await self.hass.async_add_executor_job(self.db.connect)
        # 2.13.2: posities met een geboekte deelsluiting nooit opnieuw delen,
        # ook als de bewaarde toestand dat niet meer weet.
        try:
            self._partial_taken |= await self.hass.async_add_executor_job(
                self.db.deel_tickets_open)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Deelsluitingen niet uit de database te lezen", exc_info=True)
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
                self.db.start_run, self.mode.value, self.strategie_versie,
                self.symbol, config, self.starting_balance, None, fingerprint,
            )
            await self._record_opening_equity()
            await self.hass.async_add_executor_job(
                self.db.annotate_run, self.run_id, "meerdere_posities",
                f"Vanaf {INTEGRATION_VERSION} (uitvoeringsversie "
                f"{EXECUTION_SEMANTICS_VERSION}): tot "
                f"{self.strategy_cfg.max_positions_per_richting} posities per "
                "richting, long en short naast elkaar. Besluit van de eigenaar "
                "(09-10-2026) om sneller data te verzamelen. Trades die "
                "tegelijk openstaan zijn geen onafhankelijke waarnemingen: de "
                "clustertoets voegt ze samen in één cluster. Per trade staat "
                "in 'gelijktijdig_open' hoeveel andere posities er bij de "
                "instap openstonden. Niet vergelijkbaar met runs van vóór "
                "1.9.0.",
            )
            _LOGGER.info(
                "Nieuwe bewijsfase gestart (run %s): de opzet is gewijzigd. "
                "Eerdere runs blijven bewaard en staan onderaan het rapport.",
                self.run_id,
            )

        if not self.mode.places_orders:
            # Slippage volgt de aangenomen spread: staat die op nul, dan is de
            # hele kostenkant uitgeschakeld en moet dat consistent zijn.
            spread = getattr(self.venue, "assumed_spread", 0.0)
            if self._is_spot:
                # 2.17.0: Bitvavo op papier: de echte spread uit het orderboek,
                # het echte tarief per zijde, geen hefboom en geen swap.
                kosten = BrokerCosts(
                    commission_per_lot_per_side=0.0,
                    commission_rate=float(getattr(self.venue, "tarief_per_zijde", 0.0025)),
                    base_slippage=0.0,
                    volatility_slippage_factor=0.02,
                    size_slippage_per_lot=0.0,
                    swap_long_per_lot=0.0,
                    swap_short_per_lot=0.0,
                    leverage=1.0,
                )
            else:
                kosten = BrokerCosts(
                    commission_per_lot_per_side=0.0,
                    base_slippage=0.0 if spread <= 0 else 0.02,
                    volatility_slippage_factor=0.0 if spread <= 0 else 0.05,
                    size_slippage_per_lot=0.0,
                )
            self.paper = PaperBroker(
                self.db, self.run_id, self.symbol, self.starting_balance, kosten,
            )

        # 1.7.5: wat uit de run zelf volgt terugzetten (papersaldo, laatste
        # instap, beginstand van het uurbericht), en wat bewaard was.
        await self._herstel_uit_run()
        await self._laad_schaduw()
        await self._laad_varianten()
        await self._vp_opwarmen()

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
            # 2.0.1: een andere strategie (scalp -> daghandel) ook: in 2.0.0
            # werd run 101 na de overstap gewoon voortgezet.
            structural = differences & {
                "venue", "symbol", "timeframe", "simulated",
                "execution_semantics", "candle_source", "strategy",
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
        "strategy": CONF_STRATEGIE,
        "scalp_units": CONF_SCALP_UNITS,
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
        "positielimiet": CONF_MAX_POSITIONS_PER_RICHTING,
        "scalp_reeks": CONF_SCALP_REEKS,
        "scalp_turbo": CONF_SCALP_TURBO,
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
            "strategy": self.strategie_versie,
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
                # 1.9.0: limiet per richting, long en short naast elkaar.
                # Aanwezigheid van dit veld betekent: overlap is opzet (zie
                # TradeDatabase.detect_mixed_runs).
                "max_positions_per_richting": (
                    self.strategy_cfg.max_positions_per_richting
                ),
                "hedge": True,
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

    # -- 2.0.0: strategiekeuze ------------------------------------------------ #

    @property
    def daghandel(self) -> bool:
        return self._strategie == STRATEGIE_DAGHANDEL

    @property
    def combinatie(self) -> bool:
        """Meerdere strategieën tegelijk (2.1.0), ook bij 'alles' (2.4.0)."""
        return self._strategie in (STRATEGIE_COMBINATIE, STRATEGIE_ALLES)

    @property
    def alles(self) -> bool:
        return self._strategie == STRATEGIE_ALLES

    @property
    def _max_per_cyclus(self) -> int:
        """2.4.0: nieuwe posities per cyclus; bij 'alles' meer, anders 1."""
        return 6 if self.alles else 1

    async def _vp_bijwerken(self, quote, now: datetime) -> None:
        """2.4.0: koers in de bars van alle veldproeftijdvakken."""
        try:
            klaar = self.veldproef.voeg_toe(quote.mid, now, bool(quote.tradeable))
        except Exception as err:  # noqa: BLE001 - meting, nooit de lus slopen
            _LOGGER.debug("Veldproefbars niet bijgewerkt: %s", err)
            return
        if not klaar or self.archive is None:
            return
        for tf in klaar:
            if tf == self.timeframe:
                continue  # dat tijdvak archiveert de bestaande lus al
            try:
                c = self.veldproef.candles(tf)
                if c is None:
                    continue
                laatste = Candles(
                    timestamp=c.timestamp[-1:], open=c.open[-1:], high=c.high[-1:],
                    low=c.low[-1:], close=c.close[-1:], volume=c.volume[-1:],
                )
                await self.hass.async_add_executor_job(
                    self.archive.store, self.symbol, tf, laatste, "quotes")
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Veldproefbar %s niet gearchiveerd: %s", tf, err)

    def _bewaar_ctrader_tokens(self, access: str, refresh: str) -> None:
        """2.8.0: een ververst cTrader-token in de entry bewaren, zodat een
        herstart niet met het verlopen token begint."""
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, CONF_CT_ACCESS_TOKEN: access, CONF_CT_REFRESH_TOKEN: refresh},
        )

    @property
    def _is_spot(self) -> bool:
        """2.17.0: een spot-venue (Bitvavo): alleen kopen, geen hefboom."""
        return bool(getattr(getattr(self, "venue", None), "alleen_long", False))

    def _schaal_nu(self, quote=None):
        """2.17.0: de prijs- en eenheidsschaal van deze coordinator.

        Goud: neutraal (alle vaste afstanden zoals ze waren). Crypto: de vaste
        koersafstanden schalen met de koers mee, de eenheden komen van de
        exchange en het tarief is een percentage. Zie strategy/schaal.py.
        """
        if not self._is_spot:
            return schaal_mod.GOUD
        koers = getattr(quote, "mid", None) or getattr(getattr(self, "_last_quote", None), "mid", None)
        grenzen = None
        f = getattr(self.venue, "broker_limits", None)
        if callable(f):
            try:
                grenzen = f()
            except Exception:  # noqa: BLE001
                grenzen = None
        if grenzen is not None and getattr(self.venue, "_markt", None) and getattr(self, "executor", None):
            # De grenzen van de exchange, ook als de marktgegevens pas na het
            # opstarten binnenkwamen.
            self.executor.limits = grenzen
        return schaal_mod.voor_markt(
            koers or schaal_mod.REF_PRIJS,
            getattr(grenzen, "volume_step", None),
            getattr(grenzen, "min_volume", None),
            float(getattr(self.venue, "tarief_per_zijde", 0.0) or 0.0),
            spot=True,
        )

    def _zet_schaal(self, quote=None) -> None:
        """2.17.0: de schaal voor de rest van deze cyclus (zie ``_async_refresh``)."""
        schaal_mod.zet(self._schaal_nu(quote))

    async def _async_refresh(self, *args, **kwargs):
        """2.17.0: elke verversing met de eigen schaal, en daarna de vorige terug."""
        token = schaal_mod.zet(self._schaal_nu())
        try:
            return await super()._async_refresh(*args, **kwargs)
        finally:
            schaal_mod.terug(token)

    async def _bewaar_bitvavo_posities(self, inhoud) -> None:
        """2.17.0: het grootboek van de Bitvavo-venue bewaren (overleeft een herstart)."""
        store = getattr(self, "_bv_store", None)
        if store is None:
            from homeassistant.helpers.storage import Store

            store = self._bv_store = Store(self.hass, 1, f"{DOMAIN}_bitvavo_{self.entry.entry_id}")
        if isinstance(inhoud, list):
            inhoud = {"posities": inhoud}
        await store.async_save(inhoud)

    async def _laad_bitvavo_posities(self) -> None:
        if getattr(self.venue, "name", None) != VENUE_BITVAVO:
            return
        from homeassistant.helpers.storage import Store

        self._bv_store = Store(self.hass, 1, f"{DOMAIN}_bitvavo_{self.entry.entry_id}")
        try:
            data = await self._bv_store.async_load() or {}
        except Exception:  # noqa: BLE001 - een onleesbaar bestand is een leeg grootboek
            _LOGGER.exception("Bitvavo-grootboek onleesbaar; leeg begonnen")
            data = {}
        for regel in data.get("posities") or []:
            if regel.get("ticket"):
                self.venue._grootboek[str(regel["ticket"])] = dict(regel)
        for sleutel, regel in (data.get("gesloten") or {}).items():
            self.venue._gesloten[str(sleutel)] = dict(regel)
        try:
            await self.venue.markt()
            # Volumestap en minimum van de exchange voor de veiligheidslaag.
            self.executor.limits = self.venue.broker_limits()
            # Een koers vóór de afstemming bij het opstarten: die rekent al met
            # de schaal van deze markt.
            self._last_quote = await self.venue.quote(self.symbol)
            self._zet_schaal(self._last_quote)
        except VenueError as err:
            _LOGGER.warning("Bitvavo-marktgegevens niet op te halen: %s", err)

    async def _vp_opwarmen(self) -> None:
        """2.4.0: veldproefbars opwarmen uit het archief, en waar dat te weinig
        heeft uit de koersgeschiedenis van Home Assistant (10-secondenkoersen)."""
        nodig = veldproef_mod.MIN_BARS + 5
        for tf in veldproef_mod.TIJDVAKKEN:
            if self.archive is None:
                break
            try:
                c = await self.hass.async_add_executor_job(
                    functools.partial(self.archive.load, self.symbol, tf,
                                      limit=veldproef_mod.MAX_BARS))
                self.veldproef.vul(tf, c)
            except Exception:  # noqa: BLE001 - leeg archief voor dit tijdvak
                pass
        # 30m uit de 15m van IG als het archief nog geen 30m heeft.
        if self.veldproef.aantal().get("30m", 0) < nodig and self.archive is not None:
            try:
                c15 = await self.hass.async_add_executor_job(
                    functools.partial(self.archive.load, self.symbol, "15m",
                                      limit=2 * veldproef_mod.MAX_BARS))
                self.veldproef.vul("30m", veldproef_mod.hersample(c15, 1800))
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("30m niet uit 15m op te bouwen: %s", err)
        tekort = [tf for tf, n in self.veldproef.aantal().items() if n < nodig]
        # 2.8.0: een broker met trendbars (cTrader) vult elk tijdvak zelf.
        if tekort and getattr(self.venue, "name", None) in (VENUE_CTRADER, VENUE_BITVAVO):
            for tf in tekort:
                try:
                    if tf == "3m" and getattr(self.venue, "name", None) == VENUE_BITVAVO:
                        # 2.17.0: Bitvavo kent geen 3m; uit 1m opbouwen.
                        c1 = await self.venue.candles(self.symbol, "1m", 3 * veldproef_mod.MAX_BARS)
                        c1 = closed_only(c1, datetime.now(timezone.utc).timestamp(), "1m")
                        self.veldproef.vul(tf, veldproef_mod.hersample(c1, 180))
                        continue
                    c = await self.venue.candles(self.symbol, tf, veldproef_mod.MAX_BARS)
                    c = closed_only(c, datetime.now(timezone.utc).timestamp(), tf)
                    self.veldproef.vul(tf, c)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Veldproef %s niet bij cTrader op te halen: %s", tf, err)
            tekort = [tf for tf, n in self.veldproef.aantal().items() if n < nodig]
        if tekort:
            await self._vp_uit_recorder(tekort)
        _LOGGER.info("Veldproefbars na opwarmen: %s", self.veldproef.aantal())

    async def _vp_uit_recorder(self, tijdvakken: list[str]) -> None:
        try:
            from homeassistant.components.recorder import get_instance, history
            from homeassistant.helpers import entity_registry as er

            entity_id = er.async_get(self.hass).async_get_entity_id(
                "sensor", DOMAIN, f"{self.entry.entry_id}_price")
            if not entity_id:
                return
            start = datetime.now(timezone.utc) - timedelta(days=10)
            uit = await get_instance(self.hass).async_add_executor_job(
                history.state_changes_during_period, self.hass, start, None, entity_id)
            punten = []
            for st in uit.get(entity_id, []):
                try:
                    punten.append((st.last_changed.timestamp(), float(st.state)))
                except (TypeError, ValueError):
                    continue
        except Exception as err:  # noqa: BLE001 - opwarmen is een gemak
            _LOGGER.debug("Koersgeschiedenis niet te lezen: %s", err)
            return
        for tf in tijdvakken:
            c = veldproef_mod.bars_uit_koersen(punten, BAR_SECONDS[tf])
            if c is not None:
                self.veldproef.vul(tf, c)

    def _vp_bar_gebruikt(self, strategie: str, signal) -> None:
        """2.4.0: een veldproefopzet stapt maar één keer per signaalbar in."""
        if veldproef_mod.is_veldproef(strategie):
            bar = (getattr(signal, "components", None) or {}).get("bar")
            if bar is not None:
                self._vp_laatste_bar[strategie] = int(bar)

    @property
    def primaire_strategie(self) -> str:
        """Bij de combinatie en daghandel: daghandel; anders scalp."""
        return STRATEGIE_SCALP if self._strategie == STRATEGIE_SCALP else STRATEGIE_DAGHANDEL

    def _telt_voor_reeks(self, trade) -> bool:
        """2.1.0: bij de combinatie telt alleen de daghandel voor de
        verliesreeks."""
        if not self.combinatie:
            return True
        # 2.4.0: ook de veldproef telt niet mee (alleen de daghandel).
        return combinatie_mod.strategie_van_trade(
            trade, None, self.primaire_strategie) == STRATEGIE_DAGHANDEL

    def _exits_voor(self, strategie: str | None) -> ExitManager:
        if self.combinatie and strategie == STRATEGIE_SCALP:
            return self._exits_scalp
        if veldproef_mod.is_veldproef(strategie):
            if strategie not in self._exits_vp:
                self._exits_vp[strategie] = ExitManager(veldproef_mod.exit_config(strategie))
            return self._exits_vp[strategie]
        return self.exits

    async def _strategie_van(self, position) -> str:
        """2.1.0: welke strategie opende deze positie? Eigen veld (paper),
        cache, database; anders de primaire strategie."""
        if not self.combinatie:
            return self.primaire_strategie
        eigen = getattr(position, "strategie", None)
        if eigen in (STRATEGIE_DAGHANDEL, STRATEGIE_SCALP) or veldproef_mod.is_veldproef(eigen):
            return eigen
        ticket = str(getattr(position, "ticket", None) or getattr(position, "id", ""))
        if ticket in self._strategie_per_ticket:
            return self._strategie_per_ticket[ticket]
        gevonden = None
        if self.db is not None and ticket:
            try:
                trades = await self.hass.async_add_executor_job(
                    self.db.open_trades_by_tickets, [ticket]
                )
                if trades:
                    gevonden = getattr(trades[0], "strategie", None)
            except Exception as err:  # noqa: BLE001 - alleen een opzoeking
                _LOGGER.debug("Strategie van %s niet op te zoeken: %s", ticket, err)
        strategie = gevonden if (gevonden in (STRATEGIE_DAGHANDEL, STRATEGIE_SCALP)
                                 or veldproef_mod.is_veldproef(gevonden)) \
            else self.primaire_strategie
        self._strategie_per_ticket[ticket] = strategie
        return strategie

    @property
    def strategie_versie(self) -> str:
        """Komt in runs.strategy_version en in de vingerafdruk: een andere
        strategie is altijd een nieuwe run."""
        if self.alles:
            return veldproef_mod.VELDPROEF_VERSIE
        if self.combinatie:
            return combinatie_mod.COMBINATIE_VERSIE
        return daghandel_mod.STRATEGIE_VERSIE if self.daghandel else STRATEGY_VERSION

    async def _ververs_vp_uitgezet(self) -> None:
        """2.5.6: lijst van uitgezette veldproefopzetten, elke 5 minuten uit de
        database. Een fout laat de vorige lijst staan."""
        nu = time.monotonic()
        if nu < self._vp_uitgezet_volgende or self.db is None:
            return
        self._vp_uitgezet_volgende = nu + 300.0
        try:
            per_opzet = await self.hass.async_add_executor_job(
                self.db.netto_per_strategie, veldproef_mod.PREFIX)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Uitgezette veldproefopzetten niet te lezen: %s", err)
            return
        nieuw = veldproef_mod.uitgezette_opzetten(per_opzet)
        # 2.14.0: kostenregel (bruto dekt de kosten niet).
        try:
            for naam, info in veldproef_mod.kosten_uitgezet(await self.hass.async_add_executor_job(
                    self.db.bruto_kosten_per_strategie, veldproef_mod.PREFIX)).items():
                nieuw.setdefault(naam, info)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kostenregel veldproef niet te bepalen: %s", err)
        for naam, info in veldproef_mod.handmatig_uitgezet(
                per_opzet, self.vp_tijdvakken_uit).items():
            nieuw.setdefault(naam, info)
        for naam in sorted(set(nieuw) - set(self._vp_uitgezet)):
            _LOGGER.warning("Veldproefopzet %s uitgezet: n=%s, netto %s, t=%s",
                            naam, nieuw[naam]["n"], nieuw[naam]["netto"], nieuw[naam]["t"])
        self._vp_uitgezet = nieuw
        # 2.6.1: scalp en turbo als groep.
        try:
            scalp = await self.hass.async_add_executor_job(
                self.db.netto_per_strategie, STRATEGIE_SCALP)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Scalpresultaten niet te lezen: %s", err)
            return
        reeks = scalp.get(STRATEGIE_SCALP, [])
        groep = veldproef_mod.groep_uitgezet(reeks)
        if groep is None and self.scalp_handmatig_uit:
            groep = scalp_handmatig(reeks)
        if groep and not self._scalp_uitgezet:
            _LOGGER.warning("Scalp (incl. turbo) uitgezet: n=%s, netto %s, t=%s",
                            groep["n"], groep["netto"], groep["t"])
        self._scalp_uitgezet = groep

    def _beslisser(self, now: datetime, strategie: str | None = None):
        strategie = strategie or self.primaire_strategie
        if strategie == STRATEGIE_SCALP:
            return evaluate
        if veldproef_mod.is_veldproef(strategie):
            bars, laatste = self.veldproef, self._vp_laatste_bar

            def vp(candles, bid, ask, cfg, hour, eigen_open, sinds, *_a, **_k):
                return veldproef_mod.evalueer(
                    strategie, bars, bid, ask, cfg, eigen_open, sinds, laatste,
                    uitgezet=self._vp_uitgezet)
            return vp
        return functools.partial(
            daghandel_mod.evaluate_daghandel, minuut_utc=now.astimezone(timezone.utc).minute,
        )

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
            # 2.1.0: de scalpgrootte hoort bij de opzet van de combinatie.
            "scalp_units": (
                getattr(self, "_scalp_units", None)
                if getattr(self, "_strategie", None) in (STRATEGIE_COMBINATIE, STRATEGIE_ALLES) else None
            ),
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
            # 1.9.0: het aantal posities per richting bepaalt hoeveel trades
            # er tegelijk openstaan; andere waarde = andere populatie trades.
            "positielimiet": {
                "per_richting": getattr(
                    self.strategy_cfg, "max_positions_per_richting",
                    DEFAULT_MAX_POSITIONS_PER_RICHTING,
                ),
                "hedge": True,
            },
            # De modus hoort erbij: papertrades hebben gemodelleerde kosten,
            # demotrades gemeten. Die in één bewijsfase mengen zou de hele
            # uitkomst waardeloos maken - juist het verschil tussen die twee
            # is wat je wilt meten.
            "mode": self.mode.value,
            # 2.4.9: de scalpreeks bepaalt hoeveel scalptrades er openen.
            "scalp_reeks": (
                {"stap": self.reeks.stap_usd, "max": self.reeks.max_stukken,
                 "doel": self.reeks.doel_usd}
                if getattr(self, "reeks", None) is not None and self.reeks.enabled
                else None
            ),
            # 2.5.0: turbo-scalp verandert hoeveel en wanneer scalptrades openen.
            "scalp_turbo": (
                {"orders_pm": getattr(self, "turbo_orders_pm", None),
                 "signaal": turbo_mod.TURBO_SIGNAAL_VERSIE}
                if getattr(self, "turbo_aan", False) else None
            ),
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

    def _laatste_papieren_run(self) -> int | None:
        """2.17.0: de meest recente papieren run in deze database, met dezelfde
        strategie en dezelfde markt. Een bewijs van een andere opzet telt niet."""
        versie = self.strategie_versie
        for run in self.db.list_runs(limit=50):
            if str(run.get("mode")) != TradingMode.PAPER.value:
                continue
            if str(run.get("strategy_version")) != str(versie):
                continue
            if str(run.get("symbol") or "").upper() != str(self.symbol or "").upper():
                continue
            return int(run["id"])
        return None

    async def _bereken_eigen_poort(self) -> bool:
        """De poort op het bewijs van deze lus. False: geen bewijs, dicht."""
        bewijs_run = self.run_id
        if self._is_spot and self.mode.uses_real_money:
            # 2.17.0: Bitvavo heeft geen demo. Live gaat pas open als de
            # laatste papieren run van deze markt de bewijsfase haalde; zolang
            # niet, gaat er geen enkele order uit.
            bewijs_run = await self.hass.async_add_executor_job(self._laatste_papieren_run)
            if bewijs_run is None:
                self.gate = {
                    "unlocked": False, "checks": {},
                    "blocking_reasons": ["Nog geen papieren run voor deze markt: eerst op papier "
                                         "de bewijsfase doorlopen (modus paper)."],
                    "summary": "Live gesloten: geen papieren bewijsfase.",
                }
                return False
        trades = await self.hass.async_add_executor_job(
            self.db.closed_trades, bewijs_run
        )
        stats = await self.hass.async_add_executor_job(
            performance.compute_for_run, self.db, bewijs_run, trades
        )
        run = await self.hass.async_add_executor_job(self.db.get_run, bewijs_run)
        daily = performance.daily_breakdown(trades)
        self.gate = LiveGate().evaluate(
            stats, run or {}, daily, self.robustness, self._boekhouding_status(),
        ).as_dict()
        return True

    async def _refresh_gate(self) -> None:
        """Herbereken of live handel vrijgegeven mag worden."""
        if self.run_id is None:
            return
        mand = getattr(self, "_mand", None)
        if self._is_spot and self.mode.uses_real_money and mand is not None:
            # 2.18.0: de mand gaat samen open, op het bewijs van alle markten.
            self.gate = await mand.poort()
        elif not await self._bereken_eigen_poort():
            self.venue.supports_trading = False
            return

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

    @_met_schaal
    async def async_set_enabled(self, value: bool) -> None:
        self._enabled = value
        await self._persist()
        await self._refresh_gate()
        await self.async_request_refresh()
        mand = getattr(self, "_mand", None)
        if mand is not None and mand.hoofd is self:
            # 2.18.0: de schakelaar geldt voor de hele mand.
            await mand.zet_aan(value)

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
            # 1.10.0: de laatste afstemming met de broker. Zonder dit stond
            # de sensor na elke herstart op "nog niet", en in het weekend
            # bleef dat zo tot de markt weer openging.
            "afstemming": self.reconciliation or {},
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

    @_met_schaal
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
        # 1.10.0: de bewaarde afstemming, gemarkeerd als bewaard. Een nieuwe
        # afstemming vervangt hem (zonder die markering).
        afstemming = data.get("afstemming")
        if isinstance(afstemming, dict) and afstemming and not self.reconciliation:
            self.reconciliation = {**afstemming, "hersteld": True}

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

    @_met_schaal
    async def async_prepare_shutdown(self) -> dict:
        """Wikkel af zodat HA veilig herstart kan worden."""
        result = await self.lifecycle.drain(self._open_positions, self._close_position)
        await self.async_request_refresh()
        return result.as_dict()

    @_met_schaal
    async def async_close_all(self) -> None:
        for position in await self._open_positions():
            await self._close_position(position, "handmatig")
        await self.async_request_refresh()

    @_met_schaal
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
            self.db.start_run, self.mode.value, self.strategie_versie,
            self.symbol, config, self.starting_balance,
            note or "handmatig gestart", fingerprint,
        )
        await self._record_opening_equity()
        # 1.9.0: schaduwtrades horen bij een run.
        await self._laad_schaduw()
        # 1.9.5: tijdstopvarianten ook.
        await self._laad_varianten()
        _LOGGER.warning(
            "Nieuwe bewijsfase gestart (run %s), de vorige (%s) is afgesloten. "
            "Reden: %s. Eerdere runs blijven bewaard en staan onderaan het "
            "rapport.",
            self.run_id, vorige, note or "handmatig gestart",
        )
        await self.async_request_refresh()
        return self.run_id

    @_met_schaal
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

    @_met_schaal
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
            # 1.7.9: onbekend is niet mislukt en niet gelukt. Niet boeken;
            # de positielijst van de broker beslist (zie _bewaak_sluitingen).
            if getattr(resultaat, "unconfirmed", False):
                self._sluit_onderweg.setdefault(ticket, {
                    "sinds": time.monotonic(), "reden": reason,
                })
                _LOGGER.warning(
                    "Sluiten van %s (%s): geen bevestiging van de broker (%s). "
                    "Niet geboekt; de positie blijft bewaakt tot de broker "
                    "hem niet meer toont.", ticket, reason,
                    getattr(resultaat, "error", None) or "onbekend",
                )
                return
            # 1.7.8/1.7.9: alleen als gesloten boeken wat de broker bevestigde.
            # Een geweigerd verzoek werd tot 1.7.8 toch afgeboekt: dan stond de
            # positie open bij de broker en dicht in de database - onbewaakt.
            if not getattr(resultaat, "success", False):
                self._registreer_weigering(
                    ticket, reason,
                    getattr(resultaat, "error", None) or "geen bevestiging",
                )
                return
            self._sluit_pogingen.pop(ticket, None)
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

    def _registreer_weigering(self, ticket: str, reason: str, fout: str) -> None:
        """Een niet uitgevoerde sluiting: loggen en de herhaling afremmen."""
        staat = self._sluit_pogingen.setdefault(
            ticket, {"weigeringen": 0, "volgende": 0.0, "opgegeven": False},
        )
        staat["weigeringen"] += 1
        n = staat["weigeringen"]
        if n >= SLUIT_MAX_POGINGEN:
            staat["opgegeven"] = True
            _LOGGER.error(
                "Sluiten van %s (%s) niet uitgevoerd: %s. Na %d pogingen "
                "probeert de bot het niet meer automatisch; de positie blijft "
                "open, bewaakt en met zijn stop bij de broker. Sluit hem zo "
                "nodig handmatig.", ticket, reason, fout, n,
            )
            return
        wacht = SLUIT_BACKOFF[min(n, len(SLUIT_BACKOFF)) - 1]
        staat["volgende"] = time.monotonic() + wacht
        _LOGGER.error(
            "Sluiten van %s (%s) niet uitgevoerd: %s. De positie blijft open "
            "en bewaakt; nieuwe poging over %ds (%d/%d).", ticket, reason,
            fout, wacht, n, SLUIT_MAX_POGINGEN,
        )

    def _sluiten_toegestaan(self, ticket: str) -> bool:
        """Mag de exitlogica nu een sluitverzoek voor dit ticket sturen?

        Niet als er al een verzoek loopt (bevestigd of onbekend): dat zou een
        tweede verzoek op dezelfde positie zijn. Niet tijdens de wachttijd na
        een weigering, en niet meer na de limiet.
        """
        if ticket in self._sluitverzoeken or ticket in self._sluit_onderweg:
            return False
        staat = self._sluit_pogingen.get(ticket)
        if staat is None:
            return True
        if staat["opgegeven"]:
            return False
        return time.monotonic() >= staat["volgende"]

    async def _bewaak_sluitingen(self) -> None:
        """Lopende sluitverzoeken elke cyclus tegen de positielijst houden.

        1.7.9: de volledige controle draait elke tiende cyclus; "sluiting niet
        uitgevoerd" kwam daardoor pas na minuten. Dit gebruikt de positielijst
        die deze cyclus al is opgehaald - geen extra verzoek bij de broker.
        """
        if not (self._sluitverzoeken or self._sluit_onderweg
                or self._sluit_pogingen):
            return
        try:
            live_lijst = await self._open_positions()
        except VenueError as err:
            _LOGGER.debug("Sluitingen niet na te kijken: %s", err)
            return
        live = {
            str(getattr(p, "ticket", "")) for p in live_lijst
            if not size_says_closed(getattr(p, "units", None))
        }
        # Weigeringen vergeten zodra de positie weg is.
        self._sluit_pogingen = {
            t: v for t, v in self._sluit_pogingen.items() if t in live
        }
        leeftijden = self._sluit_leeftijden()
        for ticket in list(self._sluitverzoeken):
            if ticket not in live:
                del self._sluitverzoeken[ticket]
                continue
            if leeftijden[ticket] <= SLUIT_GENADE_SECONDEN:
                continue
            # Geboekt als gesloten, maar de broker toont hem nog: onbewaakt.
            del self._sluitverzoeken[ticket]
            melding = (
                f"Positie {ticket} staat {leeftijden[ticket]:.0f}s na een "
                "bevestigd sluitverzoek nog open bij de broker. De sluiting "
                "is niet uitgevoerd; de positie staat niet meer in de "
                "database en wordt door niemand bewaakt."
            )
            _LOGGER.error("Controle: %s", melding)
            self.risk.halt("administratie en broker lopen uiteen: " + melding)
            await self.notifier.alert(
                "audit", "Gold Scalper: administratie klopt niet", melding,
            )
        nu = time.monotonic()
        for ticket, info in list(self._sluit_onderweg.items()):
            if ticket not in live:
                # Weg bij de broker: de gewone afwikkeling van verdwenen
                # posities boekt hem (met gemeten of als geschat gemarkeerde
                # uitstapprijs).
                del self._sluit_onderweg[ticket]
                continue
            if nu - info["sinds"] <= SLUIT_GENADE_SECONDEN:
                continue
            del self._sluit_onderweg[ticket]
            self._registreer_weigering(
                ticket, info["reden"],
                f"onbevestigd en na {nu - info['sinds']:.0f}s nog open bij de "
                "broker",
            )

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
        self._afwikkeling_mislukt = False  # 1.11.0 (L-GS-012)
        self._geopend_in_cyclus = 0

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
        self._zet_schaal(quote)
        budget.mark("quote")

        now = datetime.now(timezone.utc)
        self._laatste_verse_koers_om = now
        tick_age = (now - quote.time).total_seconds()

        # -- bars bijwerken --------------------------------------------------- #
        if self._build_from_quotes:
            await self._update_from_quote(quote)
        else:
            await self._maybe_update_candles()
        self._bars_since_last_check = max(1, self._new_bars_this_cycle)
        budget.mark("candles")

        open_positions_precheck = await self._voorcheck_posities()
        if isinstance(open_positions_precheck, dict):
            return open_positions_precheck  # 1.10.2: vastgehouden beeld

        # Posities die de broker zélf sloot - op de server-side stop of het
        # doel - verdwijnen zonder dat wij er iets van merken. Zonder deze
        # afstemming blijft de rij eeuwig open in de database en telt hij
        # nergens in mee, want de bewijsfase kijkt naar gesloten trades.
        if self.mode.places_orders and quote.tradeable:
            await self._settle_vanished_positions(quote, now)
            # 1.7.9: lopende sluitverzoeken elke cyclus nakijken.
            await self._bewaak_sluitingen()
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

        # 2.4.0: bars op 1m-30m voor de veldproef (15m ook in het archief).
        await self._vp_bijwerken(quote, now)

        # -- open posities beheren, vóór alles anders ------------------------ #
        # Bij een gesloten markt niet ingrijpen: een stop verplaatsen of een
        # positie sluiten op een koers van uren geleden is erger dan wachten.
        if quote.tradeable:
            await self._manage_open_positions(quote, now)
            # 1.9.0: schaduwtrades met dezelfde koers en bars; geen extra
            # verzoek bij de broker.
            await self._werk_schaduw_bij(quote, now)
            # 2.7.1: schaduwtrades van uitgezette groepen (H-GS-003).
            await self._werk_uitgezet_bij(quote, now)
            # 2.11.0: bevestigingsmeting (15m), alleen schaduw.
            await self._werk_bevestiging_bij(quote, now)
            # 1.9.5: tijdstopvarianten, idem. Alleen meting.
            await self._werk_varianten_bij(quote, now)

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

        # 2.9.5: een venue met een eigen rooster (cTrader) heeft dat al in
        # quote.tradeable verwerkt; het IG-rooster ernaast gaf alleen ruis
        # (Pepperstone pauzeert 22:59-00:01, IG 23:00-24:00).
        if self._use_schedule and self._venue_rooster(now) is None:
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
                #
                # 1.7.10: binnen 15 s van een roostergrens is het een klokrand
                # (broker al/nog dicht), geen feestdag: dan DEBUG in plaats
                # van WARNING. Wat er gehandeld mag worden verandert niet.
                if note != self._last_schedule_note:
                    self._last_schedule_note = note
                    melden = (
                        _LOGGER.debug if bij_roostergrens(SPOT_GOLD, now)
                        else _LOGGER.warning
                    )
                    melden("Handelstijden: %s", note)
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
        #: 2.4.4: reden als het saldo deze cyclus niet op te vragen was.
        saldo_onbekend: str | None = None
        self._marge_vrij = None
        if self.paper:
            self.paper.update_positions(self._paper_quote(quote))
            balance, equity = self.paper.balance, self.paper.equity(self._paper_quote(quote))
            gemeten_equity = equity
            self._marge_vrij = self.paper.free_margin(self._paper_quote(quote))
        else:
            try:
                snapshot = await self.venue.account()
                if _leeg_accountantwoord(
                    snapshot.balance, snapshot.equity, self.current_equity
                ):
                    # 2.19.1: saldo én equity precies 0 terwijl er eerder een
                    # positieve equity gemeten was: een leeg antwoord, geen
                    # meting (IG 21-10 13:14 -> valse NOODSTOP en 100 %
                    # drawdown). Zelfde pad als een mislukte opvraging.
                    raise VenueError("saldo en equity 0 in het antwoord (leeg)")
                balance, equity = snapshot.balance, snapshot.equity
                self.current_equity = equity
                gemeten_equity = equity
                # 1.9.0: voor de margetoets bij een extra positie.
                vrij = getattr(snapshot, "margin_available", None)
                self._marge_vrij = float(vrij) if vrij else None
            except VenueError as err:
                # 2.4.4: geen saldo van de broker is geen verlies. Eerst werd
                # hier de startbalans ingevuld (1.000.000) en die viel onder de
                # verliesvloer van het echte account (~10 mln): NOODSTOP op
                # 13-10 02:16 en 06:43, telkens bij een IG-limiet of DNS-fout.
                # Nu: laatst gemeten waarde voor de weergave, en geen
                # risicotoets en geen nieuwe positie deze cyclus.
                laatst = self.current_equity or self.starting_balance
                balance = equity = laatst
                saldo_onbekend = str(err)[:120] or "geen antwoord"

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

        # 1.9.0: telling per richting (onbevestigde orders inbegrepen). De
        # limiet geldt per richting; een tegengesteld signaal blokkeert niets
        # en sluit ook niets.
        pending = (
            list(self.executor.pending.values())
            if self.mode.places_orders else []
        )
        # 2.1.0: per strategie beslissen. Bij één strategie is dit één ronde
        # met alle posities, precies als voorheen.
        if self.combinatie:
            posities_per_strategie: dict[str, list] = {}
            for p in open_positions:
                posities_per_strategie.setdefault(
                    await self._strategie_van(p), []).append(p)
        else:
            posities_per_strategie = {self.primaire_strategie: list(open_positions)}
        signal = None
        reject_reason = None
        # 2.4.9: de reden per strategie (bij alles/combinatie toonde het paneel
        # alleen die van de daghandel, ook als scalp en veldproef handelden).
        redenen: dict[str, str | None] = {}
        vp_signalen = vp_ingestapt = 0
        if self.alles:
            await self._ververs_vp_uitgezet()
        await self._ververs_onderzoek()
        per_richting = tel_per_richting(open_positions, pending)
        for ronde, strategie in enumerate(combinatie_mod.strategieen(self._strategie)):
            eigen = posities_per_strategie.get(strategie, [])
            eigen_richting = tel_per_richting(eigen, pending)
            eigen_open = len(eigen) + (len(pending) if self.mode.places_orders else 0)
            laatste_instap = (
                self._laatste_instap.get(strategie, 0.0) if self.combinatie
                else self._last_entry_ts
            )
            r_signal = None
            # 2.19.0: de daghandel rekent op kwartierbars (zie _daghandel_candles)
            invoer = self._daghandel_candles() if strategie == STRATEGIE_DAGHANDEL else self._candles
            if invoer is not None and len(invoer) >= 60:
                # 2.17.0: met de context mee, anders rekent de strategie in de
                # werkthread met de neutrale (goud)schaal.
                r_signal = await self.hass.async_add_executor_job(
                    contextvars.copy_context().run,
                    self._beslisser(now, strategie), invoer, quote.bid, quote.ask,
                    self.strategy_cfg, now.hour, eigen_open,
                    now.timestamp() - laatste_instap, 0, eigen_richting,
                )
                if r_signal is not None and self.combinatie:
                    r_signal.components = {**(r_signal.components or {}), "strategie": strategie}
                self._signalen[strategie] = r_signal
            if ronde == 0:
                signal = r_signal
                self._last_signal = r_signal
                budget.mark("signal")
            r_reject = None
            #: 1.9.0: categorie voor de schaduwtrade als een geldig signaal niet
            #: wordt uitgevoerd (zie strategy/schaduw.SCHADUW_REDENEN). None: geen
            #: schaduwtrade (signaalfilter, markt dicht, koers verouderd ...).
            schaduw_reden: str | None = None
            uitgevoerd = False
            if r_signal is not None:
                if not self.lifecycle.accepts_new_positions:
                    r_reject = f"levenscyclus: {self.lifecycle.state.value}"
                    schaduw_reden = "levenscyclus"
                elif not self._enabled:
                    r_reject = "handel staat uit"
                    schaduw_reden = "handel_uit"
                elif self._afwikkeling_mislukt:
                    # 1.11.0 (L-GS-012): conservatief; eerst de boekhouding rond.
                    r_reject = "afwikkeling van een trade mislukt: geen instap deze cyclus"
                elif self.mode.places_orders and self.executor.has_pending:
                    r_reject = "onbevestigde order: eerst terugvinden"
                    schaduw_reden = "onbevestigde_order"
                elif strategie == STRATEGIE_SCALP and self._scalp_uitgezet and self.alles:
                    # 2.6.1: scalp bewezen verliezend als groep.
                    r_reject = (f"scalp uitgezet{' (handmatig)' if self._scalp_uitgezet.get('handmatig') else ''} "
                                f"(n={self._scalp_uitgezet['n']}, t={self._scalp_uitgezet['t']})")
                elif not r_signal.should_trade:
                    r_reject = r_signal.reject_reason
                    if r_signal.reject_reason == "max_positions_zelfde_richting":
                        schaduw_reden = "positielimiet"
                    elif r_signal.reject_reason == "cooldown":
                        schaduw_reden = "cooldown"
                elif saldo_onbekend:
                    # 2.4.4: zonder gemeten saldo geen risicotoets (die zou
                    # op een ingevulde waarde een valse noodstop geven) en dus
                    # geen nieuwe positie. Exitbeheer loopt gewoon door.
                    r_reject = f"saldo van de broker niet op te vragen: {saldo_onbekend}"
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
                    r_reject = None if allowed else f"risico: {why}"
                    if not allowed:
                        # Markt dicht of dode data: geen betrouwbare instapprijs,
                        # dus ook geen schaduwtrade.
                        schaduw_reden = (
                            None if why in ("markt gesloten", "dataverbinding dood")
                            else "risico"
                        )

                    # Geen nieuwe positie zonder bruikbare wisselkoers wanneer er
                    # omgerekend moet worden: de positiegrootte is dan niet te
                    # garanderen. Alleen nieuwe posities - exitbeheer, afstemming
                    # en veiligheid lopen gewoon door.
                    if allowed and not fx_ok:
                        allowed = False
                        r_reject = f"wisselkoers: {fx_reden}"
                        schaduw_reden = "wisselkoers"
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
                        resterend = self._minuten_tot_sluiting(now)
                        if resterend is not None and resterend <= self._close_buffer:
                            allowed = False
                            schaduw_reden = None
                            r_reject = (
                                f"nog {resterend:.0f} minuten tot sluiting; een "
                                "nieuwe positie zou door de sluiting worden "
                                "overvallen"
                            )

                    # 1.9.0: extra posities. Netting, spreiding, marge en vloer.
                    if allowed:
                        blok, blok_reden = await self._toets_extra_positie(
                            r_signal, quote, now, open_positions, equity,
                            eigen=eigen,
                        )
                        if blok:
                            allowed = False
                            r_reject = blok_reden
                            schaduw_reden = blok if blok in SCHADUW_REDENEN else None

                if r_reject is None and r_signal.should_trade:
                    if self._geopend_in_cyclus >= self._max_per_cyclus:
                        # 1.9.0: hooguit één nieuwe positie per cyclus (2.4.0: bij 'alles' meer).
                        r_reject = "al een positie geopend in deze cyclus"
                        schaduw_reden = "per_cyclus"
                    else:
                        self._laatste_weigering = None
                        uitgevoerd = await self._open_position(
                            r_signal, quote, now, gelijktijdig_open=aantal_open,
                        )
                        if not uitgevoerd and getattr(self, "_mand", None) is not None:
                            # 2.18.2: niets geopend: de toegezegde plek terug.
                            self._mand.vrijgeven(self)
                        # 2.13.0: waarom niet geopend (kostenfilter), voor het
                        # signalenlog en de grafiek.
                        if not uitgevoerd and self._laatste_weigering:
                            r_reject = self._laatste_weigering
                        if uitgevoerd and r_signal.direction:
                            self._omkeer_alle = {
                                "richting": 1 if r_signal.direction > 0 else -1,
                                "sinds": now, "strategie": strategie,
                            }
                        # 2.11.0: 15m-signaal dat echt gehandeld wordt: ook als
                        # paar (direct / met bevestiging) in de schaduw volgen.
                        if uitgevoerd and bevestiging_mod.BevestigingBoek.hoort_erbij(strategie):
                            try:
                                self.bevestiging.aanmelden(
                                    strategie=strategie, signal=r_signal,
                                    bid=quote.bid, ask=quote.ask, nu=now)
                            except Exception:  # noqa: BLE001 - meting raakt de handel niet
                                _LOGGER.debug("Bevestigingsmeting niet gestart", exc_info=True)

                # 1.9.0: geldig signaal, niet uitgevoerd: schaduwtrade.
                # 2.4.0: geen schaduwtrades voor de veldproef (die handelt echt).
                if (schaduw_reden and not uitgevoerd and quote.tradeable
                        and not self.koers_verouderd
                        and not veldproef_mod.is_veldproef(strategie)):
                    await self._open_schaduw(
                        r_signal, quote, now, schaduw_reden, r_reject,
                        open_positions, equity,
                    )

                # 2.7.1 (H-GS-003): een geldig signaal van een uitgezette groep
                # als schaduwtrade volgen; nooit een echte order.
                if (quote.tradeable and not self.koers_verouderd and not uitgevoerd
                        and getattr(r_signal, "geldig", False) and (
                            r_signal.reject_reason == "opzet_uitgezet"
                            or (strategie == STRATEGIE_SCALP and self._scalp_uitgezet
                                and self.alles and r_signal.should_trade))):
                    await self._open_uitgezet(strategie, r_signal, quote, now, equity)

                # 2.4.0: van de veldproef alleen signalen met een richting
                # (anders 47 rijen per cyclus).
                if not (veldproef_mod.is_veldproef(strategie) and not r_signal.direction):
                    await self.hass.async_add_executor_job(
                        self.db.log_signal, self.run_id, r_signal.score, r_signal.confidence,
                        "buy" if r_signal.direction > 0 else "sell" if r_signal.direction < 0 else "flat",
                        None, quote.spread, r_reject is None and r_signal.should_trade,
                        r_reject, r_signal.components,
                    )

            if ronde == 0:
                reject_reason = r_reject
            if r_signal is not None:
                # 2.5.5: richting per strategie, voor sluiten/vastzetten bij omkeer.
                self._richting_per_strategie[strategie] = int(r_signal.direction or 0)
                if veldproef_mod.is_veldproef(strategie):
                    if r_signal.direction:
                        vp_signalen += 1
                        if r_reject is None and r_signal.should_trade:
                            vp_ingestapt += 1
                else:
                    redenen[strategie] = r_reject or (
                        "ingestapt" if r_signal.should_trade else None)
        if vp_signalen or self.alles:
            redenen["veldproef"] = (
                f"{vp_ingestapt} van {vp_signalen} signalen ingestapt"
                if vp_signalen else "geen signaal deze cyclus"
            )
            if self._vp_uitgezet:
                # 2.6.1: een uitgezet tijdvak als één regel.
                groepen = {v["groep"]: v for v in self._vp_uitgezet.values() if v.get("groep")}
                losse = [f"{n[len(veldproef_mod.PREFIX):]} (n={v['n']}, "
                         + (f"bruto {v['bruto']:.0f} < kosten {v['kosten']:.0f})" if v.get("regel") == "kosten"
                            else f"t={v['t']})")
                         for n, v in sorted(self._vp_uitgezet.items()) if not v.get("groep")
                         and n.split(":")[-1] not in groepen]
                redenen["veldproef"] += " · uitgezet: " + ", ".join(
                    [f"alle {tf} (n={v['n']}, t={v['t']})" for tf, v in sorted(groepen.items())]
                    + losse)
        # 2.5.0: wat de turbo-scalp tussen twee cycli nodig heeft.
        self._turbo_ctx = {
            "balance": balance, "equity": equity,
            "saldo_onbekend": saldo_onbekend, "tradeable": bool(tradeable),
        }
        if self.turbo_aan and self._turbo_afmelden is None:
            self._turbo_start()
        if self._turbo_afmelden is not None:
            recent = self._turbo_recent(time.monotonic())
            redenen["turbo"] = (
                f"{recent}/{self.turbo_orders_pm} orders deze minuut, "
                f"{self.turbo_stats['orders']} totaal "
                f"({self.turbo_stats.get('uitbraak_orders', 0)} op uitbraak), "
                f"uitbraak: {self.turbo_stats.get('laatste_signaal', '-')}, stream "
                f"{getattr(self._turbo_stream, 'status', '?')}"
            )
        self._redenen_per_strategie = redenen

        # 1.10.1: alleen een gemeten equity in de equitycurve. De terugval op
        # de startbalans (opvraging mislukt) is geen meting; hij gaf op 10-10
        # een drawdown van 99,9 % (10.000 tegen ~10 mln demo-equity).
        if gemeten_equity is not None:
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
            # 2.1.0: resultaat per strategie (alleen zinvol bij de combinatie).
            self._per_strategie = (
                combinatie_mod.per_strategie(closed, self.primaire_strategie)
                if self.combinatie else {}
            )

        # 1.9.5: statistiek van de tijdstopvarianten.
        await self._ververs_varianten_stats()

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
            "redenen_per_strategie": getattr(self, "_redenen_per_strategie", None) or {},
            "balance": balance,
            "equity": equity,
            # 1.7.7: onverklaarde saldosprong (dataprobleem).
            "saldosprong": self.saldosprong.as_dict(),
            "open_positions": open_positions,
            # 1.9.0: telling per richting, limiet, netting en schaduwtrades.
            "posities_per_richting": {
                "long": per_richting.get(1, 0),
                "short": per_richting.get(-1, 0),
                "limiet": self.strategy_cfg.max_positions_per_richting,
            },
            "netting": self.netting,
            "schaduw": self._schaduw_stats,
            # 1.9.5: tijdstopvarianten (gesimuleerd, alleen meting).
            "tijdstopvarianten": self._varianten_stats,
            "stats": {**stats, "per_strategie": self._per_strategie} if self.combinatie else stats,
            # 2.1.0: strategiekeuze (paneel: markers, uitstap per positie).
            "strategie_keuze": self._strategie,
            "primaire_strategie": self.primaire_strategie,
            # 2.1.0: laatste signaal per strategie (bij de combinatie).
            "signalen": {
                k: {"richting": getattr(v, "direction", 0), "score": getattr(v, "score", None),
                    "reden": getattr(v, "reject_reason", None),
                    "uitleg": getattr(v, "reason", None)}
                for k, v in self._signalen.items() if v is not None
            } if self.combinatie else {},
            "gate": self.gate,
            # 2.18.0: de Bitvavo-mand (alleen bij de hoofdlus).
            "mand": (self._mand.overzicht()
                     if getattr(self, "_mand", None) is not None and self._mand.hoofd is self
                     else None),
            # 2.7.0: onderzoeksrapport (samenvatting), risicolimieten.
            "onderzoek": onderzoek_mod.samenvatting(self.onderzoek) if self.onderzoek else None,
            "risico_limieten": self.risico_info,
            # 2.11.0: schaduwmeting instap met bevestiging (15m).
            # 2.12.0: kostenfilter veldproef
            "kostenfilter": {
                **self._kostenfilter,
                "factor": veldproef_mod.KOSTEN_STOP_FACTOR,
                "min_stop_usd": veldproef_mod.KOSTEN_MIN_STOP_USD,
            },
            "bevestiging_15m": {**self._bevestiging_stats,
                                "open": len(self.bevestiging.open_paren)},
            "uitgezet_schaduw": {
                "open": len(self.uitgezet_schaduw.open_trades),
                "gesloten_sinds_start": len(self.uitgezet_schaduw.gesloten),
                "vervallen": self.uitgezet_schaduw.vervallen,
                "herkomst": uitgezet_mod.HERKOMST,
            },
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
            "afstemming_fout": self._afstemming_fout,
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

    async def _voorcheck_posities(self) -> bool | dict:
        """Zijn er open posities? (voorcheck van de cyclus, 1.10.2)

        Live op 10-10 19:27: "IG antwoordde niet binnen 15s op GET
        /positions". Die fout liet de hele cyclus vallen als onverwachte fout
        met traceback. Nu net als bij een mislukte koers (1.7.0): het laatste
        beeld vasthouden (dict terug) en in deze cyclus niets beslissen - geen
        instap, geen stop verplaatsen, geen sluiting. Na de drempel een gewone
        ``UpdateFailed``.

        De teller van mislukte opvragingen gaat pas hier terug naar nul, als
        koers én positie-overzicht binnen zijn; anders zou een aanhoudende
        time-out op /positions elke cyclus als de eerste tellen.
        """
        try:
            heeft_posities = bool(await self._open_positions())
        except VenueError as err:
            vastgehouden = self._houd_laatste_data(err, wat="Positie-opvraging")
            if vastgehouden is not None:
                return vastgehouden
            raise UpdateFailed(
                f"Geen positie-overzicht van de broker: {err}"
            ) from err
        if self._koers_mislukt:
            _LOGGER.info(
                "Brokergegevens weer beschikbaar na %d mislukte opvraging(en).",
                self._koers_mislukt,
            )
            self._koers_mislukt = 0
        return heeft_posities

    def _houd_laatste_data(
        self, err: Exception, wat: str = "Koersopvraging"
    ) -> dict | None:
        """Laatste gegevens aanhouden na een mislukte koersopvraging (1.7.0).

        Live op 7 oktober: de koersopvraging bij IG liep zes keer in
        anderhalf uur tegen de time-out van 6 s aan, steeds één cyclus. Elke
        keer werd álles onbeschikbaar, ook de noodstop - precies de indicator
        die je bij een storing wilt blijven zien.

        Geeft een kopie van de laatste gegevens terug met ``koers_verouderd``
        aan, of None als de drempel voorbij is (dan de oude storing). De
        cyclus beslist niets: geen signaal, geen instap, geen exitbeheer op
        een oude koers. Stops en doelen staan bij de broker en werken door.

        1.10.2: ook voor een mislukt positie-overzicht (``wat``); de teller
        is gedeeld, dus ook dan geen instap tot de broker weer antwoordt.
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
                "%s %d keer op rij mislukt (laatste verse koers "
                "%.0f s oud); entiteiten worden onbeschikbaar tot de broker "
                "weer antwoordt.", wat, self._koers_mislukt, leeftijd,
            )
            return None

        _LOGGER.warning(
            "%s mislukt (%d van max. %d op rij): %s. Laatste "
            "gegevens aangehouden (koers %.0f s oud); geen nieuwe posities "
            "en geen exitbeheer tot de broker weer antwoordt.",
            wat, self._koers_mislukt, KOERS_HOUD_MAX_MISLUKT, err, leeftijd,
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
            "mislukte_opvraging": wat,
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
            "afstemming_fout": self._afstemming_fout,
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

    def _omkeer_richting(self, side: str, opened, eigen: int | None) -> int | None:
        """2.13.3: tegenrichting van de laatst geopende positie (alle setups,
        alle tijdvakken) voor posities die daarvóór opengingen; anders de
        richting van de eigen strategie (2.5.5)."""
        g = self._omkeer_alle
        d = 1 if side == "buy" else -1
        if g and g.get("richting") == -d:
            sinds = g.get("sinds")
            if opened is None or sinds is None or opened < sinds:
                return g["richting"]
        return eigen

    def _daghandel_candles(self):
        """2.19.0: kwartierbars voor de daghandel.

        De daghandel is gebouwd en getoetst op kwartierbars: een kanaal van 80
        bars (20 uur), uur-EMA's 20/50 (minstens 51 afgesloten uren) en stops in
        ATR(15m). Hij kreeg de bars van het tijdvak van de entry - bij XAUUSD
        en de Bitvavo-mand 1m, hooguit 800 stuks (13 uur): de uur-EMA's kwamen
        nooit rond ("Nog geen 50 afgesloten uren") en de daghandel handelde
        nooit. De veldproef houdt al 400 kwartierbars bij (100 uur, bij het
        opstarten uit het archief of de broker); die krijgt hij nu.
        """
        kandidaten = []
        try:
            c15 = self.veldproef.candles("15m")
            if c15 is not None:
                kandidaten.append(c15)
        except Exception:  # noqa: BLE001 - nog geen kwartierbars
            pass
        if self.timeframe == "15m" and self._candles is not None:
            kandidaten.append(self._candles)
        return max(kandidaten, key=len) if kandidaten else None

    def _atr15(self) -> float | None:
        """2.19.0: ATR(14) op kwartierbars, voor de exits van de daghandel."""
        c = self._daghandel_candles()
        if c is None or len(c) < 15:
            return None
        sleutel = (len(c), c.timestamp[-1])
        if getattr(self, "_atr15_cache", (None, None))[0] != sleutel:
            try:
                waarde = float(_atr_reeks(c, 14)[-1])
            except Exception:  # noqa: BLE001
                waarde = None
            self._atr15_cache = (sleutel, waarde if waarde and waarde > 0 else None)
        return self._atr15_cache[1]

    async def _manage_open_positions(self, quote: VenueQuote, now: datetime) -> None:
        """Break-even, gedeeltelijk sluiten, trailing en tijdstops."""
        atr = self.state.atr.value or 0.0
        if atr <= 0:
            return
        # spread plus geschatte slippage beide zijden (2.17.0: geschaald, plus
        # procentuele kosten bij crypto)
        cost = (quote.spread + schaal_mod.usd(0.04)
                + schaal_mod.commissie_rondreis_per_unit(quote.mid))

        for position in await self._open_positions():
            ticket = str(getattr(position, "ticket", None) or getattr(position, "id", ""))
            opened = await self._position_opened_at(position, ticket, now)
            # Paper-trades bewaren volume in lots, venue-posities in ounces.
            size = getattr(position, "units", None)
            if size is None:
                size = (getattr(position, "volume", 0) or 0) * CONTRACT_SIZE
            # 2.1.0: de uitstapregels van de strategie die de positie opende.
            strategie = await self._strategie_van(position)
            # 2.4.10: de veldproef rekent break-even en volgstop in R.
            maat = (
                veldproef_mod.r_van(position.open_price, getattr(position, "take_profit", None))
                if veldproef_mod.is_veldproef(strategie)
                # 2.19.0: de volgstop van de daghandel staat in ATR(15m)
                else (self._atr15() or atr) if strategie == STRATEGIE_DAGHANDEL
                else atr
            )
            action = self._exits_voor(strategie).evaluate(
                side=position.side,
                volume=size,
                open_price=position.open_price,
                current_stop=getattr(position, "stop_loss", None),
                bid=quote.bid, ask=quote.ask, atr=maat,
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

            # 2.5.5 (Ruud 13-10): signaal/trend van de eigen strategie gedraaid:
            # verlies sluiten, winst vastzetten. Gaat voor 'hold'/stopverplaatsing.
            if action.kind != "close":
                omkeer = omkeer_actie(
                    position.side, position.open_price, quote.bid, quote.ask,
                    getattr(position, "stop_loss", None),
                    self._omkeer_richting(position.side, opened,
                                          self._richting_per_strategie.get(strategie)),
                )
                if omkeer is not None and self._omkeer_alle and \
                        self._omkeer_alle.get("strategie") != strategie:
                    omkeer.reason = f"omkeer door {self._omkeer_alle.get('strategie')}: {omkeer.reason}"
                if omkeer is not None and (
                        omkeer.kind == "close" or action.kind != "modify_stop"
                        or (omkeer.new_stop - (action.new_stop or 0))
                        * (1 if position.side == "buy" else -1) > 0):
                    action = omkeer

            # Pyramiden vóór de exitacties: bijkopen bij bevestiging is een
            # aparte beslissing van de vraag of je moet sluiten.
            if (strategie == STRATEGIE_SCALP
                    and (self.reeks.enabled or self.pyramid.enabled)
                    and action.kind in ("hold", "modify_stop")
                    and not await self._is_bijkoop(ticket)):
                if self.reeks.enabled:
                    await self._consider_reeks(position, quote, ticket)
                else:
                    await self._consider_pyramid(position, quote, ticket)

            if action.is_noop:
                continue

            try:
                if action.kind == "close":
                    # 1.7.9: geen tweede verzoek op een lopende sluiting, en
                    # na een weigering met wachttijd en limiet.
                    if self.mode.places_orders and \
                            not self._sluiten_toegestaan(ticket):
                        continue
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
                        await self._sync_trade_stop(ticket, action.new_stop, action.reason)
                elif action.kind == "modify_stop":
                    position.stop_loss = action.new_stop
                elif action.kind == "partial_close":
                    units = (getattr(position, "units", 0) or 0) * action.close_fraction
                    if self.mode.places_orders and units > 0:
                        deel = await self.venue.close(ticket, units)
                        self._positions_cache = None
                        # 2.13.2: direct vastleggen dat het deel genomen is.
                        # Viel het boeken hierna om, dan werd het elke ronde
                        # (en na elke herstart) opnieuw gesloten - Pepperstone
                        # 16-10: setup_error en elke herstart een halvering.
                        self._partial_taken.add(ticket)
                        # Vastleggen: anders wordt de winst wél genomen maar
                        # verschijnt hij nergens in je resultaten, en telt hij
                        # niet mee in de bewijsfase.
                        # 1.7.9: alleen wat de broker bevestigde.
                        if getattr(deel, "success", False):
                            # 2.9.2: boek wat de broker werkelijk sloot. cTrader
                            # sluit in hele ounces (24,5 -> 24); de gevraagde
                            # helft boeken liet database en broker uiteenlopen
                            # (NOODSTOP 14-10, 25,0 tegen 24,50).
                            gesloten = deel_units(units, getattr(deel, "units", None))
                            try:
                                await self._record_partial(
                                    ticket, gesloten, action.reason,
                                    datetime.now(timezone.utc),
                                )
                            except Exception:  # noqa: BLE001
                                # 2.13.2: een boekfout mag het exitbeheer en
                                # de setup niet stilleggen; de afstemming met
                                # de broker zet de omvang daarna recht.
                                _LOGGER.exception(
                                    "Deelsluiting van %s gedaan bij de broker, "
                                    "maar niet geboekt", ticket)
                        else:
                            _LOGGER.error(
                                "Deelsluiting van %s niet bevestigd: %s. Niet "
                                "geboekt.", ticket,
                                getattr(deel, "error", None) or "onbekend",
                            )
                    self._partial_taken.add(ticket)
            except VenueError as err:
                _LOGGER.error("Exitactie %s mislukte: %s", action.kind, err)

    async def _open_position(
        self, signal, quote: VenueQuote, now: datetime,
        gelijktijdig_open: int | None = None,
    ) -> bool:
        """Open een positie. True als er een order is uitgegaan die (mogelijk)
        een positie werd; False als er niets geopend is."""
        # 1.7.0: nooit instappen op een vastgehouden koers. De lus slaat zo'n
        # cyclus al over; dit is de tweede grendel.
        if self.koers_verouderd:
            _LOGGER.warning("Instap overgeslagen: koers verouderd.")
            return False
        # 1.9.0: hooguit één nieuwe positie per cyclus (tweede grendel).
        if self._geopend_in_cyclus >= self._max_per_cyclus:
            _LOGGER.debug("Instap overgeslagen: al een positie in deze cyclus.")
            return False
        side = "buy" if signal.direction == 1 else "sell"
        richting = 1 if side == "buy" else -1
        # 2.17.0: spot (Bitvavo) kan niet short. Het signaal blijft bestaan
        # (het voedt de omkeer-exit van een lopende long), maar er gaat geen
        # order uit - ook niet op papier, anders meet de bewijsfase iets wat
        # live nooit kan.
        spot = bool(getattr(getattr(self, "venue", None), "alleen_long", False))
        if spot and self.mode.uses_real_money and not (self.gate or {}).get("unlocked"):
            # 2.17.0: live staat aan maar de poort is dicht: geen order, geen fout.
            self._laatste_weigering = "live: poort nog dicht (eerst de papieren bewijsfase)"
            return False
        if side == "sell" and spot:
            self._laatste_weigering = "spot: geen short mogelijk"
            self._vp_bar_gebruikt(
                (getattr(signal, "components", None) or {}).get("strategie", ""), signal)
            return False
        if getattr(self, "_mand", None) is not None:
            # 2.18.0: hooguit zoveel posities over de hele mand samen.
            mag, waarom = self._mand.mag_openen(self)
            if not mag:
                self._laatste_weigering = waarom
                return False
        # 2.12.0: kostenfilter voor de veldproef - geen trade als de kosten
        # een te groot deel van het risico tot de stop zijn.
        vp_naam = (getattr(signal, "components", None) or {}).get("strategie")
        if veldproef_mod.is_veldproef(vp_naam):
            instap = quote.ask if side == "buy" else quote.bid
            kosten = self._kosten_per_oz(quote)
            if veldproef_mod.stop_te_krap(instap, signal.stop_loss, kosten):
                self._noteer_kostenfilter(vp_naam, instap, signal.stop_loss, kosten)
                self._laatste_weigering = (
                    f"kostenfilter: stop {abs(instap - signal.stop_loss):.4g}, minimaal "
                    f"{veldproef_mod.min_stopafstand(kosten):.4g}")
                self._vp_bar_gebruikt(vp_naam, signal)
                return False
        if gelijktijdig_open is None:
            gelijktijdig_open = len(await self._open_positions())
        # Voor de nettingcontrole: welke posities stonden er vlak vóór de
        # order, en staat er een tegengestelde tussen?
        voor = list(await self._open_positions()) if self.mode.places_orders else []
        tegengesteld = [
            p for p in voor
            if richting_van(getattr(p, "side", "buy")) != richting
        ]
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
            if self._scalp_vast(signal):
                units = self._vaste_grootte(signal, entry_price)
                self.last_sizing = {
                    "units": units, "reason": "combinatie: vaste scalpgrootte (veldproef: op risico)",
                    "risk_amount": round(units * abs(entry_price - (signal.stop_loss or entry_price)), 2),
                }
            else:
                sized = position_size(
                    self.sizing, equity, entry_price, signal.stop_loss,
                    signal.score, self.strategy_cfg.entry_threshold,
                )
                units = sized.units
                self.last_sizing = sized.as_dict()
            # 2.7.3: hard plafond per order, voor elke strategie.
            units, begrensd = risico_plafond(units, entry_price, signal.stop_loss)
            if begrensd:
                self.last_sizing = {
                    **(self.last_sizing or {}), "units": units,
                    "risk_amount": round(units * abs(entry_price - signal.stop_loss), 2),
                    "capped_by": "max_risico_per_order",
                    "reason": (f"{(self.last_sizing or {}).get('reason', '')} Begrensd op "
                               f"{MAX_RISICO_PER_ORDER_USD:.0f} USD risico tot de stop: {units} oz.").strip(),
                }
            # 2.17.0: Bitvavo: hooguit de ingestelde inzet per koop, op papier
            # net zo als live.
            max_inzet = getattr(self.venue, "max_inzet", None)
            if spot and max_inzet and entry_price > 0:
                hooguit = schaal_mod.omlaag(float(max_inzet) / entry_price, 0.1)
                if units > hooguit:
                    units = hooguit
                    self.last_sizing = {
                        **(self.last_sizing or {}), "units": units, "capped_by": "max_inzet",
                        "reason": (f"{(self.last_sizing or {}).get('reason', '')} Begrensd op de "
                                   f"maximale inzet van {float(max_inzet):.2f} per koop.").strip(),
                    }
            if units <= 0:
                self._laatste_weigering = "ordergrootte 0 na begrenzing"
                return False
            _LOGGER.debug("Ordergrootte: %s", self.last_sizing.get("reason"))
            strategie = (getattr(signal, "components", None) or {}).get(
                "strategie", self.primaire_strategie)

            if self.mode.places_orders:
                # De poort geldt alleen voor echt geld. Op demo is er niets te
                # beschermen behalve de kwaliteit van je meting, en juist die
                # meting is het doel.
                # Het dict rechtstreeks doorgeven; de controle kent beide
                # vormen. Er hoeft geen klasse uit gefabriceerd te worden.
                require_live_unlocked(self.mode, self.gate)
                # 2.7.0: execution ledger - verzendmoment.
                verzend_ts = datetime.now(timezone.utc)
                # Via de veiligheidslaag: garandeert een stop, voorkomt een
                # tweede order na een verbroken verbinding.
                result, notes = await self.executor.open_protected(
                    self.symbol, side, units, quote.mid,
                    stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                    context=(signal, quote, side, now),
                )
                self.executor_notes = notes[-10:]
                await self._log_uitvoering(
                    signal, quote, side, units, now, verzend_ts,
                    datetime.now(timezone.utc), result, strategie,
                )
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
                    self._laatste_instap[strategie] = now.timestamp()
                    self._geopend_in_cyclus += 1
                    self._vp_bar_gebruikt(strategie, signal)
                    return True
                if not result.success:
                    _LOGGER.warning("Order niet geplaatst: %s", result.error)
                    # 2.4.1: een afgewezen veldproefsignaal niet elke cyclus
                    # opnieuw proberen; de volgende bar telt weer.
                    self._vp_bar_gebruikt(strategie, signal)
                    return False

                # Vastleggen in de database. Zonder dit verdwijnen orders die
                # naar de broker gaan uit je eigen administratie: geen
                # resultaat, geen kosten, geen verliesanalyse, en een
                # bewijsfase die nooit vordert. Dat maakte de demomodus
                # zinloos, want juist het meten was het doel.
                await self._record_broker_open(
                    result, signal, quote, side, now,
                    gelijktijdig_open=gelijktijdig_open,
                )
                # 1.9.0: verrekende de broker de order met een tegengestelde
                # positie? Nooit stil laten gebeuren.
                await self._controleer_netting(
                    result, richting, voor, tegengesteld, units=units,
                )
                # 1.9.5: tijdstopvarianten van deze positie (alleen meting).
                await self._open_varianten(
                    str(result.ticket) if result.ticket else None, side,
                    result.fill_price or entry_price, quote,
                    result.units or units, signal, now,
                )
            elif self.paper:
                trade = self.paper.open_position(
                    side, units / CONTRACT_SIZE, self._paper_quote(quote),
                    signal.stop_loss, signal.take_profit,
                    signal.score, signal.confidence, None, signal.reason,
                )
                trade.gelijktijdig_open = gelijktijdig_open
                trade.strategie = strategie if self.combinatie else None
                await self.hass.async_add_executor_job(self.db.update_trade, trade)
                # 1.9.5: tijdstopvarianten van deze positie (alleen meting).
                await self._open_varianten(
                    f"id:{trade.id}" if getattr(trade, "id", None) else None,
                    side, trade.open_price, quote,
                    (trade.volume or 0) * CONTRACT_SIZE, signal, now,
                )
            self.risk.record_open()
            # 2.7.0: voor de clusterlimiet.
            self._recente_instappen = [
                x for x in self._recente_instappen if now.timestamp() - x[0] <= 3600
            ] + [(now.timestamp(), richting)]
            self._last_entry_ts = now.timestamp()
            self._laatste_instap[strategie] = now.timestamp()
            self._geopend_in_cyclus += 1
            self._vp_bar_gebruikt(strategie, signal)
            return True
        except (ModeLockedError, VenueError) as err:
            _LOGGER.error("Openen mislukt: %s", err)
        except InsufficientMargin as err:
            # 1.9.0: met meerdere posities kan de papermarge op raken. Geen
            # crash van de cyclus; gewoon niet openen.
            _LOGGER.warning("Openen geweigerd (papermarge): %s", err)
        return False

    # -- 1.9.0: meerdere posities en schaduwtrades --------------------------- #

    def _naar_account(self, bedrag: float) -> float:
        """Instrumentvaluta naar accountvaluta, aan de voorzichtige kant."""
        if not self.conversion.needed:
            return bedrag
        koers = self.conversion.risk_rate or self.conversion.rate
        return bedrag * koers if koers else bedrag

    async def _ververs_onderzoek(self) -> None:
        """2.7.0: onderzoeksrapport (learning/onderzoek.py) elke 30 minuten,
        over de gesloten trades van de laatste 30 dagen. Alleen meten."""
        nu = time.monotonic()
        if nu < self._onderzoek_volgende or self.db is None:
            return
        self._onderzoek_volgende = nu + 1800.0
        try:
            sinds = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            rijen = await self.hass.async_add_executor_job(
                self.db.gesloten_als_dict, self.mode.value, sinds)
            schaduw = []
            try:
                # 2.10.0: vertekende schaduwrijen van vóór de correctie niet.
                schaduw_sinds = max(sinds, uitgezet_mod.GELDIG_VANAF)
                schaduw = [uitgezet_mod.als_onderzoeksrij(r) for r in
                           await self.hass.async_add_executor_job(
                               self.db.uitgezet_gesloten, schaduw_sinds)]
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Uitgezette schaduwtrades niet te lezen: %s", err)
            self.onderzoek = await self.hass.async_add_executor_job(
                onderzoek_mod.rapport, rijen, schaduw)
        except Exception as err:  # noqa: BLE001 - onderzoek mag de handel niet raken
            _LOGGER.debug("Onderzoeksrapport niet bijgewerkt: %s", err)

    def _boekhouding_status(self) -> dict | None:
        """2.7.0: stand van de afstemming voor de live-poort. None = nog niet
        afgestemd (de poort blijft dan dicht)."""
        rec = getattr(self, "reconciliation", None) or {}
        audit = getattr(self, "audit", None) or {}
        if not rec and not audit:
            return None
        afw = rec.get("afwijkingen")
        if isinstance(afw, list):
            afw = len(afw)
        kritiek = audit.get("critical") if isinstance(audit, dict) else None
        if isinstance(kritiek, list):
            kritiek = len(kritiek)
        return {
            "afwijkingen": int(afw or 0) if rec else None,
            "kritiek_open": int(kritiek or 0) if audit else 0,
        }

    async def _log_uitvoering(self, signal, quote, side, units, signaal_ts,
                              verzend_ts, bevestiging_ts, result, strategie) -> None:
        """2.7.0: één rij in de execution ledger; mag de handel nooit raken."""
        if self.db is None:
            return
        try:
            candle_ts = (
                datetime.fromtimestamp(self._last_bar_ts, timezone.utc)
                if self._last_bar_ts else None
            )
            rij = uitvoering_mod.ledger_rij(
                run_id=self.run_id, strategie=strategie, side=side,
                units_gevraagd=units, signaal_ts=signaal_ts,
                signaal_bid=quote.bid, signaal_ask=quote.ask,
                koers_ts=getattr(quote, "time", None), candle_ts=candle_ts,
                verzend_ts=verzend_ts, tick=self._laatste_tick,
                bevestiging_ts=bevestiging_ts, result=result,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            )
            await self.hass.async_add_executor_job(self.db.log_uitvoering, rij)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Execution ledger niet bijgewerkt: %s", err)

    def _vaste_grootte(self, signal, entry_price: float) -> float:
        """2.6.2: vaste scalpgrootte; veldproef op risico (zie
        ``veldproef.grootte_op_risico``)."""
        units = float(min(self._scalp_units, self.sizing.max_units))
        naam = (getattr(signal, "components", None) or {}).get("strategie")
        if veldproef_mod.is_veldproef(naam):
            return veldproef_mod.grootte_op_risico(units, entry_price, signal.stop_loss)
        return units

    def _scalp_vast(self, signal) -> bool:
        """2.1.0: bij de combinatie krijgen scalptrades een vaste grootte.

        2.18.4: niet bij spot (Bitvavo). De vaste grootte is 1 oz (de
        scalpgrootte), bij crypto werd dat de kleinste order van de exchange
        (live gezien 20-10: 1.271 PUMP, ruim 5 euro). Daar geldt de gewone
        grootte op risico, begrensd door de inzet per koop."""
        if self._is_spot:
            return False
        naam = (getattr(signal, "components", None) or {}).get("strategie")
        return self.combinatie and (
            naam == STRATEGIE_SCALP or veldproef_mod.is_veldproef(naam)
        )

    def _grootte(self, signal, quote: VenueQuote, equity: float | None) -> float:
        """Ordergrootte zoals ``_open_position`` hem zou bepalen (ounces).

        1.9.2: met precies dezelfde equity als ``_open_position``: de
        papersimulatie bij paper, anders het startsaldo. Hier stond eerst de
        equity van het brokeraccount; op de IG-demo is dat ~10 miljoen, zodat
        schaduwtrades op de maximale grootte openden en hun resultaat en kosten
        tientallen keren groter waren dan bij een echte trade. ``equity``
        blijft als argument bestaan maar bepaalt de grootte niet meer.
        """
        side = "buy" if signal.direction == 1 else "sell"
        entry_price = quote.ask if side == "buy" else quote.bid
        if self._scalp_vast(signal):
            return self._vaste_grootte(signal, entry_price)
        try:
            basis = (
                self.paper.equity(self._paper_quote(quote))
                if self.paper else self.starting_balance
            )
            sized = position_size(
                self.sizing, basis, entry_price,
                signal.stop_loss, signal.score, self.strategy_cfg.entry_threshold,
            )
            max_inzet = getattr(self.venue, "max_inzet", None) if self._is_spot else None
            if max_inzet and entry_price > 0:
                # 2.18.4: schaduwtrades net zo groot als een echte instap.
                return min(float(risico_plafond(sized.units, entry_price, signal.stop_loss)[0]),
                           schaal_mod.omlaag(float(max_inzet) / entry_price, 0.1))
            return float(risico_plafond(sized.units, entry_price, signal.stop_loss)[0])
        except Exception:  # noqa: BLE001 - een schatting mag niets breken
            return float(self.units)

    async def _toets_extra_positie(
        self, signal, quote: VenueQuote, now: datetime, open_positions: list,
        equity: float | None, eigen: list | None = None,
    ) -> tuple[str | None, str | None]:
        """Mag dit signaal naast de open posities een positie openen?

        Geeft (categorie, reden) bij weigering, anders (None, None). De
        categorie bepaalt of er een schaduwtrade komt (zie
        strategy/schaduw.SCHADUW_REDENEN); 'spreiding' hoort daar niet bij.
        """
        richting = 1 if signal.direction == 1 else -1
        # 2.1.0: spreiding alleen tegen posities van dezelfde strategie; marge
        # en vloer hieronder over alles samen.
        zelfde = [
            p for p in (open_positions if eigen is None else eigen)
            if richting_van(getattr(p, "side", "buy")) == richting
        ]
        tegen = [
            p for p in open_positions
            if richting_van(getattr(p, "side", "buy")) != richting
        ]
        if self.netting and tegen:
            return "netting", (
                "netting: de broker verrekende eerder tegengestelde posities; "
                "hedgen staat uit tot een herstart"
            )
        instap = quote.ask if richting == 1 else quote.bid
        # 2.7.0: risicolimieten over alle posities samen (verbeterplan).
        units_nieuw = self._grootte(signal, quote, equity)
        ok, reden, self.risico_info = risicolimieten_ok(
            richting=richting,
            nieuw_risico=abs(instap - (signal.stop_loss or instap)) * units_nieuw,
            nieuw_notional=units_nieuw * quote.mid,
            open_posities=open_positions, koers=quote.mid,
            equity_ref=self.starting_balance, naar_account=self._naar_account,
            recente_instappen=self._recente_instappen, nu_ts=now.timestamp(),
            per_trade_pct=getattr(self.sizing, "risk_per_trade_pct", None),
        )
        if not ok:
            return "risicolimiet", reden
        # 2.6.2: niet te veel veldproefposities met risico in één richting.
        naam = (getattr(signal, "components", None) or {}).get("strategie")
        if veldproef_mod.is_veldproef(naam):
            met_risico = 0
            for p in open_positions:
                if richting_van(getattr(p, "side", "buy")) != richting:
                    continue
                if not veldproef_mod.is_veldproef(await self._strategie_van(p)):
                    continue
                if veldproef_mod.loopt_risico(getattr(p, "side", "buy"),
                                              getattr(p, "open_price", None),
                                              getattr(p, "stop_loss", None)):
                    met_risico += 1
            if met_risico >= veldproef_mod.MAX_POSITIES_MET_RISICO:
                return "cluster", (
                    f"al {met_risico} veldproefposities met risico in deze richting "
                    f"(max {veldproef_mod.MAX_POSITIES_MET_RISICO})"
                )
        if zelfde:
            bestaand = []
            for p in zelfde:
                ticket = str(getattr(p, "ticket", None) or getattr(p, "id", ""))
                geopend = getattr(p, "open_time", None)
                if geopend is None:
                    geopend = await self._position_opened_at(p, ticket, now)
                bestaand.append((getattr(p, "open_price", None), geopend))
            ok, reden = spreiding_ok(
                richting, instap, self.state.atr.value, bestaand, now,
                BAR_SECONDS.get(self.timeframe, 60),
            )
            if not ok:
                return "spreiding", reden
        if open_positions:
            vloer = self.risk.floor_breakdown(
                self.starting_balance, self.opening_equity, equity,
            ).get("effective_equity_floor")
            ok, reden, info = marge_en_vloer_ok(
                units=self._grootte(signal, quote, equity), prijs=quote.mid,
                instap=instap, stop=signal.stop_loss, equity=equity,
                vloer=vloer, marge_vrij=self._marge_vrij,
                open_posities=open_positions, naar_account=self._naar_account,
            )
            if not ok:
                _LOGGER.info("Extra positie geweigerd: %s (%s)", reden, info)
                return ("marge" if reden.startswith("marge") else "vloer"), reden
        return None, None

    async def _controleer_netting(
        self, result, richting: int, voor: list, tegengesteld: list,
        units: float | None = None,
    ) -> None:
        """Verrekende de broker de order met een tegengestelde positie?

        Twee bronnen: de bevestiging zelf (IG ``affectedDeals``) en, als er
        een tegengestelde positie openstond, de positielijst vlak na de order
        (één extra opvraging, alleen bij hedgen). Gevonden: luid melden en
        hedgen uitzetten. Nooit een stille verrekening.
        """
        verrekend = list(getattr(result, "verrekend", None) or [])
        # 2.14.3: zegt de broker zelf dat het account hedged is (cTrader
        # accountType), dan kan een order niets verrekenen. Een tegengestelde
        # positie die tegelijk verdwijnt, sloot op haar eigen stop of doel:
        # op 19-10 01:30:06 de stop van 58459739, 4 ms voor de nieuwe short.
        if not verrekend and getattr(self.venue, "account_hedged", None) is True:
            return
        if tegengesteld and not verrekend:
            try:
                na = await self._open_positions(refresh=True)
            except VenueError as err:
                _LOGGER.debug("Nettingcontrole niet mogelijk: %s", err)
                na = None
            if na is not None:
                onderweg = set(self._sluitverzoeken) | set(self._sluit_onderweg)
                verrekend = [
                    t for t in netting_uit_posities(
                        voor, na, richting, result.ticket, nieuw_units=units,
                    )
                    if t not in onderweg
                ]
        if not verrekend:
            return
        self.netting = {
            "sinds": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "order": str(result.ticket),
            "verrekend": verrekend,
        }
        melding = (
            f"De broker heeft order {result.ticket} verrekend met bestaande "
            f"positie(s) {', '.join(verrekend)} in plaats van een aparte "
            "positie te openen (netting). Hedgen (long en short tegelijk) staat "
            "uit tot een herstart; de verdwenen posities worden als door de "
            "broker gesloten afgerekend. Controleer de accountinstelling."
        )
        _LOGGER.error("Netting: %s", melding)
        await self.notifier.alert("audit", "Gold Scalper: broker verrekent posities", melding)

    async def _open_schaduw(
        self, signal, quote: VenueQuote, now: datetime, reden: str,
        tekst: str | None, open_positions: list, equity: float | None,
    ) -> None:
        """Leg een geldig, niet uitgevoerd signaal vast als schaduwtrade."""
        if self.db is None or reden not in SCHADUW_REDENEN:
            return
        if not getattr(signal, "geldig", False):
            return
        trade = self.schaduw.openen(
            run_id=self.run_id, signal=signal, bid=quote.bid, ask=quote.ask,
            nu=now, units=self._grootte(signal, quote, equity), reden=reden,
            reden_tekst=tekst, atr=self.state.atr.value,
            echte_posities=open_positions,
        )
        if trade is None:
            return
        await self.hass.async_add_executor_job(self.db.bewaar_schaduw, trade)
        self._schaduw_stats = self.schaduw.statistiek()
        _LOGGER.debug(
            "Schaduwtrade %s %s @ %.2f (%s)", reden, trade.side,
            trade.open_price, tekst,
        )

    async def _werk_schaduw_bij(self, quote: VenueQuote, now: datetime) -> None:
        """Open schaduwtrades een cyclus verder, op de koers die er al is."""
        if not self.schaduw.open_trades or self.db is None or self.koers_verouderd:
            return
        atr = self.state.atr.value or 0.0
        if atr <= 0:
            return
        # 2.10.0: zie _werk_uitgezet_bij.
        hoog, laag, vanaf = self._uitersten_voor_varianten(quote)
        voor = len(self.schaduw.gesloten) + self.schaduw.vervallen
        gewijzigd = self.schaduw.bijwerken(
            bid=quote.bid, ask=quote.ask, hoog=hoog, laag=laag,
            atr=atr, nu=now, uitersten_vanaf=vanaf,
        )
        for t in gewijzigd:
            await self.hass.async_add_executor_job(self.db.bewaar_schaduw, t)
        if len(self.schaduw.gesloten) + self.schaduw.vervallen != voor:
            self._schaduw_stats = self.schaduw.statistiek()

    async def _open_uitgezet(self, strategie: str, signal, quote: VenueQuote,
                             now: datetime, equity: float | None) -> None:
        """2.7.1: schaduwtrade voor een uitgezette groep (H-GS-003)."""
        if self.db is None:
            return
        try:
            trade = self.uitgezet_schaduw.openen(
                strategie=strategie, signal=signal, bid=quote.bid, ask=quote.ask,
                nu=now, units=self._grootte(signal, quote, equity), run_id=self.run_id,
            )
            if trade is not None:
                await self.hass.async_add_executor_job(self.db.bewaar_uitgezet, trade)
        except Exception as err:  # noqa: BLE001 - meting mag de handel niet raken
            _LOGGER.debug("Schaduwtrade uitgezette groep niet vastgelegd: %s", err)

    async def _werk_bevestiging_bij(self, quote: VenueQuote, now: datetime) -> None:
        """2.11.0: paren direct/bevestigd een cyclus verder; afgeronde paren
        naar de database en de statistiek."""
        if self.db is None:
            return
        try:
            if not self._bevestiging_geladen:
                self._bevestiging_geladen = True
                rijen = await self.hass.async_add_executor_job(self.db.bevestiging_paren, "")
                self._bevestiging_stats = self.bevestiging.statistiek(rijen)
            if not self.bevestiging.open_paren or self.koers_verouderd:
                return
            hoog, laag, vanaf = self._uitersten_voor_varianten(quote)
            agg = self.veldproef.agg.get("1m")
            bar = agg._closed[-1] if agg is not None and agg._closed else None
            klaar = self.bevestiging.bijwerken(
                bid=quote.bid, ask=quote.ask, hoog=hoog, laag=laag,
                uitersten_vanaf=vanaf, nu=now, bar_1m=bar,
                exits_voor=self._exits_voor, maat_voor=self._maat_uitgezet)
            if klaar:
                for paar in klaar:
                    if paar.status != "vervallen":
                        await self.hass.async_add_executor_job(
                            self.db.bewaar_bevestiging, paar.als_rij())
                rijen = await self.hass.async_add_executor_job(self.db.bevestiging_paren, "")
                self._bevestiging_stats = self.bevestiging.statistiek(rijen)
        except Exception as err:  # noqa: BLE001 - meting raakt de handel niet
            _LOGGER.debug("Bevestigingsmeting niet bijgewerkt: %s", err)

    def _maat_uitgezet(self, t) -> float:
        if veldproef_mod.is_veldproef(t.strategie):
            return veldproef_mod.r_van(t.open_price, t.take_profit) or 0.0
        return self.state.atr.value or 0.0

    async def _werk_uitgezet_bij(self, quote: VenueQuote, now: datetime) -> None:
        if not self.uitgezet_schaduw.open_trades or self.db is None or self.koers_verouderd:
            return
        try:
            # 2.10.0: alleen uitersten van nieuwe bars, en alleen voor trades
            # die vóór die bars opengingen (zoals de tijdstopvarianten).
            hoog, laag, vanaf = self._uitersten_voor_varianten(quote)
            gewijzigd = self.uitgezet_schaduw.bijwerken(
                bid=quote.bid, ask=quote.ask, hoog=hoog, laag=laag, nu=now,
                exits_voor=self._exits_voor, maat_voor=self._maat_uitgezet,
                uitersten_vanaf=vanaf,
            )
            for t in gewijzigd:
                await self.hass.async_add_executor_job(self.db.bewaar_uitgezet, t)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Schaduwtrades uitgezette groepen niet bijgewerkt: %s", err)

    async def _laad_schaduw(self) -> None:
        """Schaduwtrades van de actieve run uit de eigen tabel."""
        self.schaduw.open_trades = []
        self.schaduw.gesloten = []
        self.schaduw.vervallen = 0
        # 2.7.1: open schaduwtrades van uitgezette groepen zijn na een
        # herstart of runwissel niet eerlijk verder te volgen.
        self.uitgezet_schaduw = uitgezet_mod.UitgezetBoek()
        if self.db is not None:
            try:
                await self.hass.async_add_executor_job(self.db.uitgezet_open_laten_vervallen)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Uitgezette schaduwtrades niet afgesloten: %s", err)
        if self.db is None or self.run_id is None:
            self._schaduw_stats = self.schaduw.statistiek()
            return
        rijen = await self.hass.async_add_executor_job(
            self.db.schaduw_trades, self.run_id
        )
        velden = set(SchaduwTrade.__dataclass_fields__)
        for rij in rijen:
            t = SchaduwTrade(**{k: v for k, v in rij.items() if k in velden})
            if t.status == "open":
                self.schaduw.open_trades.append(t)
            elif t.status == "gesloten":
                # 2.10.0: gesloten vóór de correctie van de simulatie telt
                # niet mee in de statistiek (vertekend, zie schaduw.uitersten_voor).
                if (t.open_time or "") >= uitgezet_mod.GELDIG_VANAF:
                    self.schaduw.gesloten.append(t)
            else:
                self.schaduw.vervallen += 1
        self._schaduw_stats = self.schaduw.statistiek()

    # -- 1.9.5: tijdstopvarianten (L-GS-008, alleen meting) ----------------- #
    #
    # Niets hieronder raakt het echte exitbeheer, de orders of de echte
    # administratie: eigen tabel, eigen ExitManagers op een kopie van de
    # configuratie. Elke fout wordt gevangen en gelogd; de handel loopt door.

    async def _open_varianten(
        self, ref: str | None, side: str, open_price, quote: VenueQuote,
        units, signal, now: datetime,
    ) -> None:
        """Vier tijdstopvarianten voor een zojuist geopende echte positie."""
        strategie = (getattr(signal, "components", None) or {}).get(
            "strategie", self.primaire_strategie)
        if self.db is None or not ref or strategie != STRATEGIE_SCALP:
            # 2.0.0: daghandel heeft geen tijdstop; de varianten meten niets.
            return
        self.varianten.exits = self._exits_voor(STRATEGIE_SCALP)
        try:
            nieuw = self.varianten.openen(
                run_id=self.run_id, trade_ref=ref, side=side,
                open_price=float(open_price), open_mid=quote.mid,
                spread=quote.spread, units=float(units or 0.0),
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                nu=now,
            )
            if nieuw:
                await self.hass.async_add_executor_job(
                    self.db.bewaar_varianten, nieuw
                )
                self._varianten_vuil = True
        except Exception as err:  # noqa: BLE001 - meting mag de handel niet raken
            _LOGGER.debug("Tijdstopvarianten niet geopend: %s", err)

    def _uitersten_voor_varianten(self, quote: VenueQuote):
        """Uitersten van de bars die déze cyclus afsloten, en hun begin.

        Geen nieuwe bar: geen uitersten (alleen de actuele koers), zodat een
        al getoetste candle niet cyclus na cyclus opnieuw telt.
        """
        if not self._new_bars_this_cycle or self._candles is None \
                or not self._candles.high:
            return None, None, None
        bars = max(1, min(self._new_bars_this_cycle, len(self._candles.high)))
        pq = self._paper_quote(quote)
        try:
            ts = float(self._candles.timestamp[-bars])
            if ts > 1e11:           # milliseconden
                ts /= 1000.0
            vanaf = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (IndexError, TypeError, ValueError, OverflowError):
            return None, None, None
        return pq.high, pq.low, vanaf

    async def _werk_varianten_bij(self, quote: VenueQuote, now: datetime) -> None:
        """Open varianten een cyclus verder, op de koers die er al is."""
        if not self.varianten.open_trades or self.db is None or self.koers_verouderd:
            return
        # Alleen een verwijzing: de configuratie wordt gelezen, nooit gewijzigd.
        self.varianten.exits = self._exits_voor(STRATEGIE_SCALP)
        try:
            atr = self.state.atr.value or 0.0
            if atr <= 0:
                return
            hoog, laag, vanaf = self._uitersten_voor_varianten(quote)
            voor = len(self.varianten.gesloten) + self.varianten.vervallen
            gewijzigd = self.varianten.bijwerken(
                bid=quote.bid, ask=quote.ask, hoog=hoog, laag=laag, atr=atr,
                nu=now, uitersten_vanaf=vanaf,
            )
            if gewijzigd:
                await self.hass.async_add_executor_job(
                    self.db.bewaar_varianten, gewijzigd
                )
            if len(self.varianten.gesloten) + self.varianten.vervallen != voor:
                self._varianten_vuil = True
        except Exception as err:  # noqa: BLE001 - meting mag de handel niet raken
            _LOGGER.debug("Tijdstopvarianten niet bijgewerkt: %s", err)

    async def _ververs_varianten_stats(self, forceer: bool = False) -> None:
        """Na een gesloten variant, en elke 30 cycli (latere correcties van
        echte afrekeningen meenemen)."""
        self._varianten_teller += 1
        if not (forceer or self._varianten_vuil or self._varianten_teller >= 30):
            return
        self._varianten_teller = 0
        self._varianten_vuil = False
        if self.db is None or self.run_id is None:
            return
        if not self.varianten.gesloten and not forceer:
            self._varianten_stats = self.varianten.statistiek()
            return
        try:
            echte = await self.hass.async_add_executor_job(
                self.db.echte_uitkomsten, self.run_id
            )
            self._varianten_stats = self.varianten.statistiek(echte)
        except Exception as err:  # noqa: BLE001 - meting mag de handel niet raken
            _LOGGER.debug("Statistiek tijdstopvarianten mislukt: %s", err)

    async def _laad_varianten(self) -> None:
        """Varianten van de actieve run uit de eigen tabel.

        Open varianten van een vórige run (nieuwe bewijsfase) vervallen.
        Open varianten van deze run lopen door; was het gat sinds hun laatste
        bijwerking te groot (herstart), dan vervallen ze bij de volgende
        cyclus vanzelf, zoals schaduwtrades.
        """
        try:
            oud = [t for t in self.varianten.open_trades if t.run_id != self.run_id]
            if oud and self.db is not None:
                for t in oud:
                    self.varianten.open_trades.remove(t)
                    t.status = "vervallen"
                    t.close_reason = "nieuwe run"
                    t.close_time = datetime.now(timezone.utc).isoformat(
                        timespec="seconds")
                await self.hass.async_add_executor_job(
                    self.db.bewaar_varianten, oud
                )
            self.varianten.open_trades = []
            self.varianten.gesloten = []
            self.varianten.vervallen = 0
            if self.db is None or self.run_id is None:
                self._varianten_stats = self.varianten.statistiek()
                return
            rijen = await self.hass.async_add_executor_job(
                self.db.tijdstop_varianten, self.run_id
            )
            velden = set(VariantTrade.__dataclass_fields__)
            for rij in rijen:
                t = VariantTrade(**{k: v for k, v in rij.items() if k in velden})
                if t.status == "open":
                    self.varianten.open_trades.append(t)
                elif t.status == "gesloten":
                    self.varianten.gesloten.append(t)
                else:
                    self.varianten.vervallen += 1
            await self._ververs_varianten_stats(forceer=True)
        except Exception as err:  # noqa: BLE001 - meting mag de handel niet raken
            _LOGGER.debug("Tijdstopvarianten niet geladen: %s", err)

    @_met_schaal
    async def async_afstemming_na_herstart(self) -> dict | None:
        """1.10.0: één keer afstemmen na het opstarten, ook bij een gesloten markt.

        De lus stemt alleen af als de markt handelbaar is; in het weekend bleef
        de sensor daardoor na een herstart op "nog niet". Dit is alleen lezen
        bij de broker - transactie- en activiteitenoverzicht - en plaatst,
        sluit of wijzigt niets. Faalt de broker, dan blijft de bewaarde
        uitkomst staan en probeert de lus het later opnieuw.
        """
        if not self.mode.places_orders or self.run_id is None:
            return None
        if getattr(self.venue, "transactions", None) is None:
            return None
        try:
            uitslag = await self.async_reconcile()
        except Exception as err:  # noqa: BLE001 - mag het opstarten nooit raken
            self._afstemming_fout = f"{type(err).__name__}: {err}"[:200]
            _LOGGER.warning(
                "Afstemming na de herstart niet gelukt (%s); de bewaarde "
                "uitkomst blijft staan en de lus probeert het later opnieuw.",
                err,
            )
            self._meld_afstemming()
            return None
        if uitslag:
            self._afgestemd_om = datetime.now(timezone.utc)
        self._meld_afstemming()
        return uitslag

    def _meld_afstemming(self) -> None:
        """Sensoren meteen bijwerken, zonder op de volgende cyclus te wachten."""
        try:
            if isinstance(self.data, dict):
                self.data["reconciliation"] = self.reconciliation
                self.data["afstemming_fout"] = self._afstemming_fout
                self.async_update_listeners()
        except Exception as err:  # noqa: BLE001 - alleen weergave
            _LOGGER.debug("Afstemming niet doorgegeven aan de sensoren: %s", err)

    @_met_schaal
    async def async_reconcile(self, dagen: float = 3.0) -> dict:
        """Leg de gesloten trades van de laatste dagen naast de broker.

        Zes keer werd een fout in de koppeling gevonden door een schermafdruk
        van het brokeroverzicht naast het rapport te leggen. Dit doet dat werk,
        elke dag, met dezelfde koppelregel als de correctie.

        1.10.0: nooit twee tegelijk (na de herstart en in de lus); de uitkomst
        wordt bewaard, en onbekende sluitredenen worden waar mogelijk uit de
        broker ingevuld.
        """
        if self._afstemming_bezig:
            return self.reconciliation
        self._afstemming_bezig = True
        try:
            uitslag = await self._stem_af_met_broker(dagen)
        finally:
            self._afstemming_bezig = False
        if uitslag:
            self._afstemming_fout = None
        return uitslag

    async def _stem_af_met_broker(self, dagen: float) -> dict:
        from .learning.afstemming import stem_af

        haal = getattr(self.venue, "transactions", None)
        if haal is None or self.run_id is None:
            return {}
        nu = datetime.now(timezone.utc)
        # 2.7.0: staat er een oudere trade nog niet afgestemd, dan het venster
        # tot daar verruimen (hooguit AFSTEMMING_MAX_DAGEN).
        try:
            oudste = await self.hass.async_add_executor_job(
                self.db.oudste_niet_afgestemd, self.mode.value,
                (nu - timedelta(days=AFSTEMMING_MAX_DAGEN)).isoformat(),
            )
        except Exception:  # noqa: BLE001
            oudste = None
        if oudste:
            try:
                leeftijd = (nu - datetime.fromisoformat(oudste)).total_seconds() / 86400 + 0.1
                dagen = min(AFSTEMMING_MAX_DAGEN, max(dagen, leeftijd))
            except ValueError:
                pass
        transacties = await haal(nu - timedelta(days=dagen), nu)
        grens = nu - timedelta(days=dagen)
        # 2.4.3: over alle runs, niet alleen de lopende. Na een runwissel
        # (nieuwe opzet) bleven de laatste dagen van de vorige run anders
        # ongecontroleerd: op 13-10 06:03 meldde de afstemming "geen gesloten
        # trades" omdat run 110 net begonnen was.
        trades = await self.hass.async_add_executor_job(
            self.db.closed_trades_since,
            (grens - timedelta(hours=1)).isoformat(), self.mode.value,
        )
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
        # 1.10.0: onbekende sluitredenen uit de broker invullen.
        # 2.19.5: bij een venue die per positie kan nazoeken (cTrader) ook de
        # oudere onbekende trades tot AFSTEMMING_MAX_DAGEN terug; die vielen
        # buiten het venster van drie dagen en bleven anders voor altijd
        # onbekend (22-10: 433 van 1.681 bij Pepperstone).
        kandidaten = recent
        if getattr(self.venue, "sluitkanaal", None) is not None:
            try:
                ouder = await self.hass.async_add_executor_job(
                    self.db.closed_trades_since,
                    (nu - timedelta(days=AFSTEMMING_MAX_DAGEN)).isoformat(),
                    self.mode.value,
                )
            except Exception:  # noqa: BLE001 - alleen een ruimer venster
                ouder = []
            bekend = {t.id for t in recent}
            kandidaten = [t for t in ouder if t.id not in bekend] + list(recent)
        try:
            ingevuld = await self._vul_sluitredenen_in(kandidaten, transacties, nu)
        except Exception as err:  # noqa: BLE001 - invullen mag de afstemming niet slopen
            _LOGGER.debug("Sluitredenen niet ingevuld: %s", err)
            ingevuld = 0
        self.reconciliation = {
            **uitslag.as_dict(), "moment": nu.isoformat(),
            "sluitreden_ingevuld": ingevuld,
        }
        await self._bewaar_resultaten(direct=True)
        if uitslag.afwijkingen:
            # 2.18.5: alleen nieuwe afwijkingen melden. Dezelfde oude
            # afwijkingen kwamen elke vier uur opnieuw binnen, per broker; ze
            # blijven zichtbaar in het dashboard (meetkwaliteit).
            # Overgang: wat de oude melding al meldde, telt als gemeld.
            sleutels = self.notifier._sent.keys
            overgang = "afstemming" in sleutels and not any(
                k.startswith("afstemming:") for k in sleutels)
            nieuw = set(self.notifier.nieuw(
                "afstemming:", [f"{a.ticket}:{a.soort}" for a in uitslag.afwijkingen]))
            nieuwe = [] if overgang else [
                a for a in uitslag.afwijkingen if f"{a.ticket}:{a.soort}" in nieuw]
            regels = "; ".join(a.uitleg for a in (nieuwe or uitslag.afwijkingen)[:5])
            if nieuwe:
                _LOGGER.warning(
                    "Afstemming met de broker: %s Nieuw: %s", uitslag.samenvatting(), regels
                )
                await self.notifier._send(
                    "Gold Scalper: administratie wijkt af",
                    f"{len(nieuwe)} nieuwe afwijking(en). {regels}",
                    critical=True, tag="afstemming",
                )
            else:
                _LOGGER.debug("Afstemming met de broker: %s (al gemeld) %s",
                              uitslag.samenvatting(), regels)
        return self.reconciliation

    #: Hooguit zoveel onbekende sluitredenen per afstemming bij de broker
    #: nazoeken (één verzoek per trade).
    SLUITREDEN_MAX_PER_RONDE = 10
    #: 2.19.5: bij nazoeken per positie (cTrader, twee verzoeken per trade).
    SLUITREDEN_MAX_PER_RONDE_POSITIE = 25
    #: 2.19.5: voorvoegsel van het bewijsveld als nazoeken niets opleverde;
    #: zo'n trade wordt niet elke ronde opnieuw nagevraagd.
    NAGEVRAAGD = "nagevraagd"

    async def _vul_sluitredenen_in(self, recent: list, transacties: list,
                                   nu: datetime) -> int:
        """1.10.0: trades met sluitreden onbekend achteraf een reden geven.

        Uit het transactieoverzicht de uitstap en het sluitmoment, uit het
        activiteitenoverzicht wie sloot (zie ``learning/sluitreden.py``). Alleen
        opvragen; de reden komt in de afstemmingsvelden met bron
        ``afstemming``, de oorspronkelijke reden blijft staan.
        """
        from .broker.ig_capital import match_transaction
        from .learning.exit_stats import effective_reason, exit_stats
        from .learning.sluitreden import BRON_AFSTEMMING, looptijd_van, reden_uit_broker

        zoek = getattr(self.venue, "closed_deal_activity", None)
        # 2.19.5: cTrader kent geen activiteitenoverzicht; daar zegt de
        # sluitende order wie sloot (``CTraderVenue.sluitkanaal``).
        per_positie = zoek is None and getattr(self.venue, "sluitkanaal", None) is not None
        if per_positie:
            zoek = self.venue.sluitkanaal
        maximum = (self.SLUITREDEN_MAX_PER_RONDE_POSITIE if per_positie
                   else self.SLUITREDEN_MAX_PER_RONDE)
        onbekend = [
            t for t in recent
            if t.close_time and t.broker_ticket and effective_reason(t) == "unknown"
            and not str(getattr(t, "close_reason_evidence", None) or "").startswith(
                self.NAGEVRAAGD)
        ][:maximum]
        if not onbekend:
            return 0
        cfg = self.exits.config
        ingevuld = 0
        for trade in onbekend:
            units = (trade.volume or 0) * CONTRACT_SIZE
            match = match_transaction(
                transacties, trade.broker_ticket, trade.open_price,
                trade.side, units or None, trade.open_time, trade.close_time,
            )
            uitstap = (match or {}).get("exit_price")
            gesloten = (match or {}).get("closed_at")
            activiteit = None
            gevraagd = False
            if zoek is not None:
                try:
                    activiteit = await zoek(
                        str(trade.broker_ticket), trade.side, trade.open_price,
                        _as_datetime(trade.open_time, None),
                    )
                    gevraagd = True
                except Exception as err:  # noqa: BLE001 - alleen lezen; falen mag
                    _LOGGER.debug(
                        "Activiteit van %s niet op te halen: %s",
                        trade.broker_ticket, err,
                    )
            if uitstap is None and activiteit:
                uitstap = activiteit.get("exit_price")
            if uitstap is None:
                uitstap = trade.close_price
            # 2.1.0: de uitstapregels van de strategie van deze trade.
            cfg = self._exits_voor(combinatie_mod.strategie_van_trade(
                trade, None, self.primaire_strategie)).config
            # Zonder tijdstop (uitstapregime van vóór 1.7.6) is een sluiting
            # na de tijdstopduur geen tijdslimiet.
            tijdstop = (
                None if trade.exit_regime == "zonder_tijdstop"
                else cfg.time_stop_seconds
            )
            reden = reden_uit_broker(
                trade, uitstap, activiteit,
                tijdstop, cfg.max_hold_seconds, gesloten,
            )
            if reden is None:
                # 2.19.5: per positie nagevraagd en de broker gaf antwoord,
                # maar zonder bewijs: vastleggen, niet elke ronde opnieuw.
                # Alleen als de sluiting al een uur oud is (de deal kan nog
                # onderweg zijn).
                oud = (nu - _as_datetime(trade.close_time, nu)).total_seconds() > 3600
                if per_positie and gevraagd and oud:
                    soort = (activiteit or {}).get("order_type")
                    trade.close_reason_evidence = (
                        f"{self.NAGEVRAAGD} {nu.strftime('%d-%m %H:%M')}: "
                        + ("geen sluitende deal gevonden" if not activiteit else
                           f"sluitende order {soort} geeft geen bewijs")
                    )
                    await self.hass.async_add_executor_job(self.db.update_trade, trade)
                continue
            trade.reconciled_close_reason = reden.reden
            trade.close_reason_source = BRON_AFSTEMMING
            trade.close_reason_evidence = reden.bewijs
            trade.reconciliation_status = "reconciled"
            trade.reconciled_at = nu.isoformat()
            trade.reconciliation_source = (
                ("ctrader_order" if per_positie else "broker_activity")
                if activiteit else "broker_transactions"
            )
            if trade.looptijd_s is None:
                trade.looptijd_s = looptijd_van(
                    trade, gesloten or (activiteit or {}).get("activity_date"),
                )
            await self.hass.async_add_executor_job(self.db.update_trade, trade)
            ingevuld += 1
            _LOGGER.info(
                "Sluitreden van %s achteraf ingevuld uit de afstemming: %s (%s).",
                trade.broker_ticket, reden.reden, reden.bewijs,
            )
        if ingevuld and self.run_id is not None:
            # Doel geraakt, stop geraakt en onbekend meteen bijwerken.
            alle = await self.hass.async_add_executor_job(
                self.db.closed_trades, self.run_id
            )
            self.exit_stats = exit_stats(alle)
        return ingevuld

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

    async def _sync_trade_stop(self, ticket, nieuwe_stop: float,
                               reden: str | None = None) -> None:
        """Zet een bij de broker verplaatste stop ook in de database."""
        if self.run_id is None:
            return
        # In welke run ook: een positie uit een eerdere run wordt ook beheerd.
        trade = await self._open_trade_by_ticket(ticket)
        if trade is not None:
            trade.stop_loss = round(float(nieuwe_stop), 5)
            await self.hass.async_add_executor_job(self.db.update_trade, trade)
            # 2.4.11: moment en reden, zodat de volgstop te controleren is.
            try:
                await self.hass.async_add_executor_job(
                    self.db.stop_gewijzigd, str(ticket),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"), reden,
                )
            except Exception:  # noqa: BLE001 - alleen administratie
                _LOGGER.debug("Stopmoment niet vastgelegd", exc_info=True)

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
        half = (trade.close_spread or schaal_mod.usd(0.6)) / 2.0

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
                abs(trade.close_spread or schaal_mod.usd(0.6)) * units + self._commissie(units), 4
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
                (exit_price - trade.open_price) * richting * units - self._commissie(units), 4
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
            # 2.9.3: commissie hoort bij de kosten (zit al in het nettobedrag).
            trade.total_cost = round(gemeten["total_cost"] + self._commissie(units), 4)
            trade.spread_cost = gemeten["spread_cost"]
            trade.slippage_cost = gemeten["slippage_cost"]
            trade.gross_pnl = round((trade.net_pnl or 0) + trade.total_cost, 4)
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

        fout_nu: set[str] = set()
        for trade in open_trades:
            # 1.11.0 (L-GS-012): een onverwachte fout bij één trade mag de
            # cyclus niet stilleggen. Op 12-10 02:21-03:21 faalde zo elke
            # cyclus een uur lang (360x) op één verdwenen trade, en stond het
            # exitbeheer van eventuele andere posities stil. Nu: die trade
            # blijft staan (herkansing volgende cyclus), de rest loopt door,
            # en in deze cyclus geen nieuwe instap.
            try:
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
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - zie hierboven
                self._afwikkelfout(str(trade.broker_ticket), err)
                fout_nu.add(str(trade.broker_ticket))
            else:
                self._afwikkeling_gelukt(str(trade.broker_ticket or ""))
        # Tickets die niet meer fout gaan (of niet meer open staan) vrijgeven
        for ticket in list(self._afwikkelfouten):
            if ticket not in fout_nu:
                self._afwikkeling_gelukt(ticket)
        try:
            await self._wikkel_wezen_af(live_tickets, quote, now)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - mag de cyclus nooit stilleggen
            _LOGGER.debug("Afwikkelen verweesde trades mislukt", exc_info=True)

    async def _wikkel_wezen_af(self, live_tickets, quote: VenueQuote,
                               now: datetime) -> int:
        """2.4.7: verweesde trades uit eerdere runs afwikkelen.

        Een positie uit een eerdere run die al dicht was voordat deze run hem
        zag (runwissel, herstart), werd nooit meegenomen en bleef eeuwig open
        in de database: op 13-10 23 veldproeftrades uit run 110/111, die in
        geen enkel resultaat meetelden. Alleen afwikkelen op de uitstapprijs
        en het sluitmoment uit het activiteitenoverzicht van de broker - nooit
        op de koers van nu, dat zou de oude run vervuilen. Niet gevonden: de
        trade blijft staan voor een volgende ronde. Telt niet mee voor de
        daglimiet of de verliesreeks: dat verlies is niet van vandaag.
        """
        if not self.mode.places_orders or self.run_id is None:
            return 0
        laatst = self._wees_laatst
        if laatst is not None and (now - laatst).total_seconds() < WEES_INTERVAL_S:
            return 0
        self._wees_laatst = now
        kandidaten = await self.hass.async_add_executor_job(
            self.db.wees_trades, self.mode.value, self.run_id
        )
        live = {str(t) for t in (live_tickets or ())}
        grens = now - timedelta(hours=WEES_MAX_LEEFTIJD_H)
        wezen = [
            t for t in kandidaten
            if str(t.broker_ticket) not in live
            and str(t.broker_ticket) not in self._carried_tickets
            and _as_datetime(t.open_time, now) >= grens
        ]
        # Wie het vaakst vergeefs is nagevraagd, achteraan: één onvindbare
        # trade mag de rest niet blokkeren.
        wezen.sort(key=lambda t: self._wees_pogingen.get(str(t.broker_ticket), 0))
        wezen = wezen[:WEES_PER_RONDE]
        afgewikkeld = 0
        for trade in wezen:
            activiteit = await self._zoek_activiteit(trade)
            if not activiteit or not activiteit.get("exit_price"):
                ticket = str(trade.broker_ticket)
                self._wees_pogingen[ticket] = self._wees_pogingen.get(ticket, 0) + 1
                continue
            exit_price = float(activiteit["exit_price"])
            long = trade.side == "buy"
            settle = VenueQuote(
                bid=exit_price if long else exit_price - quote.spread,
                ask=exit_price + quote.spread if long else exit_price,
                time=quote.time, tradeable=quote.tradeable,
            )
            datum = activiteit.get("activity_date")
            if isinstance(datum, str):
                datum = datum.replace("/", "-").replace(" ", "T", 1)
            moment = _as_datetime(datum, now)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            if moment > now:
                moment = now
            await self._record_broker_close(
                _TicketOnly(str(trade.broker_ticket)), settle,
                "broker_gesloten_gemeten", moment,
                bron=activiteit.get("source") or "broker_activity",
                risico=False,
            )
            # 2.4.10: de afstemming neemt de prijs uit het transactieoverzicht
            # over zodra die er is (13-10: acht weesjes kregen allemaal 4190,33
            # uit één activiteit; de broker rekende 2L69KAS af op 4185,13).
            await self.hass.async_add_executor_job(
                self.db.markeer_voorlopig, str(trade.broker_ticket)
            )
            afgewikkeld += 1
            _LOGGER.warning(
                "Verweesde trade %s uit run %s afgewikkeld op %.2f (broker, %s).",
                trade.broker_ticket, trade.run_id, exit_price, moment.isoformat(),
            )
        return afgewikkeld

    def _afwikkelfout(self, ticket: str, err: Exception) -> None:
        """Een afwikkelfout voor één trade noteren (1.11.0, L-GS-012).

        De eerste keer met traceback, daarna stil tot de herstelmelding. Na
        AFWIKKELFOUT_MELDING cycli op rij voor hetzelfde ticket komt er een
        reparatiemelding in Home Assistant.
        """
        self._afwikkeling_mislukt = True
        keer = self._afwikkelfouten.get(ticket, 0) + 1
        self._afwikkelfouten[ticket] = keer
        if keer == 1:
            _LOGGER.error(
                "Afwikkeling van trade %s mislukt; die trade blijft staan en "
                "wordt volgende cyclus opnieuw geprobeerd, de rest van de "
                "cyclus loopt door (geen nieuwe instap)",
                ticket, exc_info=err,
            )
        else:
            _LOGGER.debug("Afwikkeling van trade %s mislukt (%dx op rij): %s",
                          ticket, keer, err)
        if keer == AFWIKKELFOUT_MELDING:
            self._afwikkel_melding(ticket, keer, err)

    def _afwikkeling_gelukt(self, ticket: str) -> None:
        if self._afwikkelfouten.pop(ticket, None) is None:
            return
        _LOGGER.info("Afwikkeling van trade %s lukt weer", ticket)
        try:
            import homeassistant.helpers.issue_registry as ir

            ir.async_delete_issue(self.hass, DOMAIN, f"afwikkeling_vast_{ticket}")
        except Exception:  # noqa: BLE001 - melding opruimen is bijzaak
            pass

    def _afwikkel_melding(self, ticket: str, keer: int, err: Exception) -> None:
        try:
            import homeassistant.helpers.issue_registry as ir

            ir.async_create_issue(
                self.hass, DOMAIN, f"afwikkeling_vast_{ticket}",
                is_fixable=False, is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="afwikkeling_vast",
                translation_placeholders={
                    "ticket": ticket, "keer": str(keer),
                    "fout": f"{type(err).__name__}: {err}"[:200],
                },
            )
        except Exception as fout:  # noqa: BLE001 - melden mag de lus niet slopen
            _LOGGER.warning("Reparatiemelding voor trade %s niet gemaakt: %s",
                            ticket, fout)

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
        # 2.11.1: afrondingsverschil van een deelsluiting rechtzetten in de
        # administratie (broker leidend) in plaats van een noodstop.
        await self._herstel_afronding(positions, open_trades)
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

    async def _herstel_afronding(self, positions, open_trades) -> int:
        """Neem de brokeromvang over bij een verschil van hooguit 0,01 (2.11.1).

        Ontstond door een deelsluiting bij IG: 2,675 gevraagd, 2,67 gesloten,
        2,675 geboekt. Elke controle gaf daarna een noodstop (15-10, twee
        posities, broker 2,68 tegen database 2,67).
        """
        from .broker.reconcile_audit import afrondingsverschil

        per_ticket = {str(getattr(p, "ticket", "")): p for p in positions}
        hersteld = 0
        for trade in open_trades:
            positie = per_ticket.get(str(trade.broker_ticket or ""))
            if positie is None or not size_is_known(getattr(positie, "units", None)):
                continue
            verwacht = trade.volume * CONTRACT_SIZE
            if not afrondingsverschil(positie.units, verwacht):
                continue
            _LOGGER.warning(
                "Omvang van %s rechtgezet naar de broker: %.4f -> %s "
                "(afronding van een deelsluiting).",
                trade.broker_ticket, verwacht, positie.units,
            )
            trade.volume = float(positie.units) / CONTRACT_SIZE
            if self.db is not None:
                await self.hass.async_add_executor_job(self.db.update_trade, trade)
            hersteld += 1
        return hersteld

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
        if ticket not in self._pyramid_state and self.db is not None:
            # 2.2.0: na een herstart de toevoegingen uit de administratie halen,
            # anders begint de telling opnieuw en wordt er te veel bijgekocht.
            eerder = await self.hass.async_add_executor_job(
                self.db.bijkopen_van, str(ticket)
            )
            self._pyramid_state[ticket] = {
                "additions": len(eerder),
                "last_price": eerder[-1].open_price if eerder else None,
                "original": None,
            }
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
        costs = (self.strategy_cfg.expected_slippage * 2 + quote.spread
                 + schaal_mod.commissie_rondreis_per_unit(quote.mid))

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

        if not self.mode.places_orders:
            return
        side = getattr(position, "side", "buy")
        now = datetime.now(timezone.utc)
        strategie = await self._strategie_van(position)
        # 2.2.0: een signaal voor de administratie: zelfde strategie, de
        # nieuwe stop, en herkenbaar als bijkoop van de oorspronkelijke positie.
        bijkoop_signaal = ScalpSignal(
            direction=1 if long else -1, score=0.0, confidence=0.0,
            should_trade=True, reject_reason=None,
            reason=f"bijkoop van {ticket}: {decision.reason}"[:200],
            stop_loss=decision.new_stop,
            take_profit=getattr(position, "take_profit", None),
            components={"strategie": strategie, "open_reason": f"pyramide van {ticket}"},
            geldig=True,
        )
        try:
            # Eerst de stop verplaatsen, dan pas bijkopen. Andersom sta je
            # kortstondig met een grotere positie achter een te ruime stop, en
            # precies dan kan de verbinding wegvallen.
            verplaatst = await self.venue.modify_stop(
                ticket, decision.new_stop,
                take_profit=getattr(position, "take_profit", None),
            )
            if getattr(verplaatst, "success", False):
                await self._sync_trade_stop(ticket, decision.new_stop)
            # 2.7.3: ook een bijkoop valt onder het plafond per order.
            bijkoop_units, _ = risico_plafond(
                decision.units, quote.ask if long else quote.bid, decision.new_stop)
            result, notes = await self.executor.open_protected(
                self.symbol, side, bijkoop_units, quote.mid,
                stop_loss=decision.new_stop,
                take_profit=getattr(position, "take_profit", None),
                context=(bijkoop_signaal, quote, side, now),
            )
        except VenueError as err:
            _LOGGER.warning("Bijkopen mislukte: %s", err)
            return

        self._positions_cache = None
        if result.unconfirmed:
            # Wordt teruggezocht en dan vastgelegd met dezelfde context.
            state["additions"] += 1
            state["last_price"] = price
            _LOGGER.warning("Bijkoop onbevestigd: %s", result.error)
            return
        if not result.success:
            _LOGGER.warning("Bijkopen niet geplaatst: %s", result.error)
            return

        # 2.2.0: vastleggen als eigen trade, zodat resultaat, kosten en de
        # afstemming met de broker kloppen.
        await self._record_broker_open(result, bijkoop_signaal, quote, side, now)
        if result.ticket:
            self._bijkopen.add(str(result.ticket))
        self.risk.record_open()
        state["additions"] += 1
        state["last_price"] = price
        _LOGGER.info("Bijgekocht: %s", decision.reason)

    async def _consider_reeks(self, position, quote: VenueQuote, ticket: str) -> int:
        """2.4.9: scalpreeks - bij elke stap in de goede richting een stuk erbij.

        Elk stuk: dezelfde grootte als de eerste positie, de stop van de
        eerste positie (gedeeld), een eigen doel van ``doel_usd``. Vastgelegd
        als eigen trade ("pyramide van <ticket>"). Geeft het aantal stukken.
        """
        if not self.mode.places_orders or getattr(self, "koers_verouderd", False):
            return 0
        if ticket not in self._pyramid_state and self.db is not None:
            eerder = await self.hass.async_add_executor_job(
                self.db.bijkopen_van, str(ticket)
            )
            self._pyramid_state[ticket] = {
                "additions": len(eerder),
                "last_price": eerder[-1].open_price if eerder else None,
                "original": None,
            }
        state = self._pyramid_state.setdefault(
            ticket, {"additions": 0, "last_price": None, "original": None}
        )
        units_now = float(getattr(position, "units", 0) or 0)
        if state["original"] is None:
            state["original"] = units_now
        stop = getattr(position, "stop_loss", None)
        if units_now <= 0 or not stop:
            return 0
        side = getattr(position, "side", "buy")
        long = side == "buy"
        richting = 1 if long else -1
        price = quote.bid if long else quote.ask
        n = stukken_nu(
            self.reeks, side=side,
            entry_price=float(getattr(position, "open_price", price) or price),
            current_price=price, last_price=state["last_price"],
            done=state["additions"],
        )
        if n <= 0:
            return 0
        strategie = await self._strategie_van(position)
        geplaatst = 0
        for _ in range(n):
            now = datetime.now(timezone.utc)
            instap = quote.ask if long else quote.bid
            doel = schaal_mod.rond_prijs(instap + richting * schaal_mod.usd(self.reeks.doel_usd), 2)
            signaal = ScalpSignal(
                direction=richting, score=0.0, confidence=0.0,
                should_trade=True, reject_reason=None,
                reason=(f"scalpreeks: stuk {state['additions'] + 1} van "
                        f"{self.reeks.max_stukken} op {ticket}, doel "
                        f"{self.reeks.doel_usd:.2f} USD, gedeelde stop {stop}")[:200],
                stop_loss=stop, take_profit=doel,
                components={"strategie": strategie, "open_reason": f"pyramide van {ticket}"},
                geldig=True,
            )
            try:
                result, _notes = await self.executor.open_protected(
                    self.symbol, side, state["original"], quote.mid,
                    stop_loss=stop, take_profit=doel,
                    context=(signaal, quote, side, now),
                )
            except VenueError as err:
                _LOGGER.warning("Scalpreeks: stuk niet geplaatst: %s", err)
                break
            self._positions_cache = None
            if result.unconfirmed:
                state["additions"] += 1
                state["last_price"] = price
                _LOGGER.warning("Scalpreeks: stuk onbevestigd: %s", result.error)
                break
            if not result.success:
                _LOGGER.warning("Scalpreeks: stuk niet geplaatst: %s", result.error)
                break
            await self._record_broker_open(result, signaal, quote, side, now)
            if result.ticket:
                self._bijkopen.add(str(result.ticket))
            self.risk.record_open()
            state["additions"] += 1
            state["last_price"] = price
            geplaatst += 1
        return geplaatst

    # -- 2.5.0: turbo-scalp ------------------------------------------------- #

    def _venue_rooster(self, now: datetime):
        """2.9.5: open/dicht volgens het rooster van de venue; None = onbekend."""
        f = getattr(self.venue, "markt_open", None)
        if not callable(f):
            return None
        try:
            uit = f(now)
        except Exception:  # noqa: BLE001
            return None
        return uit if isinstance(uit, bool) else None

    def _minuten_tot_sluiting(self, now: datetime) -> float | None:
        """2.9.5: eerst het rooster van de venue, anders het eigen (IG) rooster."""
        if self._venue_rooster(now) is not None:
            f = getattr(self.venue, "minuten_tot_sluiting", None)
            try:
                uit = f(now) if callable(f) else None
            except Exception:  # noqa: BLE001
                uit = None
            return uit if isinstance(uit, (int, float)) else None
        return minutes_until_close(SPOT_GOLD, now)

    def _kosten_per_oz(self, quote) -> float:
        """2.12.0: geschatte rondreiskosten per oz: spread + commissie + slippage."""
        spread = float(getattr(quote, "spread", None) or 0.0)
        if not spread:
            try:
                spread = float(quote.ask) - float(quote.bid)
            except (TypeError, ValueError, AttributeError):
                spread = 0.0
        totaal = (max(0.0, spread) + self._commissie(1.0)
                  + schaal_mod.usd(veldproef_mod.SLIP_PER_OZ))
        return schaal_mod.rond_prijs(totaal, 4)

    def _noteer_kostenfilter(self, strategie: str, instap: float, stop, kosten: float) -> None:
        """2.12.0: tel overgeslagen veldproefsignalen per opzet."""
        stats = self._kostenfilter
        stats["overgeslagen"] = stats.get("overgeslagen", 0) + 1
        per = stats.setdefault("per_opzet", {})
        per[strategie] = per.get(strategie, 0) + 1
        afstand = abs(float(instap) - float(stop))
        stats["laatste"] = (
            f"{strategie}: stop {afstand:.2f} USD, minimaal "
            f"{veldproef_mod.min_stopafstand(kosten):.2f} (kosten {kosten:.2f} USD/oz)"
        )
        _LOGGER.debug("Kostenfilter: %s", stats["laatste"])

    def _commissie(self, units: float | None) -> float:
        """2.9.3: commissie rondreis (open + dicht) in USD voor ``units`` oz."""
        per_lot = _commissie_venue(self.venue)
        vast = 2 * per_lot * abs(float(units or 0)) / CONTRACT_SIZE
        # 2.17.0: procentuele kosten (Bitvavo) tegen de laatste koers.
        laatste = getattr(self, "_last_quote", None)
        koers = getattr(laatste, "mid", None) if laatste else None
        # Rechtstreeks uit de venue, niet uit de schaal: een boeking hoort het
        # tarief van zijn eigen broker te gebruiken.
        tarief = float(getattr(getattr(self, "venue", None), "tarief_per_zijde", 0.0) or 0.0) \
            if getattr(getattr(self, "venue", None), "alleen_long", False) else 0.0
        procent = 2.0 * tarief * float(koers or 0.0) * abs(float(units or 0))
        return round(vast + procent, 4)

    def _turbo_start(self) -> None:
        """Abonneer op de IG-koersstroom (dezelfde als het paneel)."""
        if not (self.mode.places_orders and self._strategie in (
                STRATEGIE_SCALP, STRATEGIE_COMBINATIE, STRATEGIE_ALLES)):
            return
        try:
            from .broker_stream import _get_stream, stream_eligibility

            ok, reden = stream_eligibility(self)
            if not ok:
                _LOGGER.debug("Turbo-scalp niet mogelijk: %s", reden)
                self._turbo_afmelden = False  # niet elke cyclus opnieuw
                return
            self._turbo_stream = _get_stream(self.hass, self)
            self._turbo_afmelden = self._turbo_stream.subscribe(self._turbo_op_tick)
            _LOGGER.info("Turbo-scalp actief: max %s orders per minuut op de live koers.",
                         self.turbo_orders_pm)
        except Exception:  # noqa: BLE001 - de cyclus loopt altijd door
            _LOGGER.warning("Turbo-scalp kon niet starten", exc_info=True)
            self._turbo_afmelden = False

    def _turbo_stop(self) -> None:
        afmelden = self._turbo_afmelden
        self._turbo_afmelden = None
        if callable(afmelden):
            try:
                afmelden()
            except Exception:  # noqa: BLE001
                pass

    def _turbo_recent(self, nu_m: float) -> int:
        self._turbo_orders = [t for t in self._turbo_orders if nu_m - t < 60.0]
        return len(self._turbo_orders)

    def _turbo_op_tick(self, bericht: dict) -> None:
        """Callback van de stroom (synchroon): hooguit één ronde tegelijk."""
        if not isinstance(bericht, dict) or bericht.get("soort") != "tick":
            return
        # 2.5.2: elke tick naar het uitbraaksignaal, ook als er een ronde loopt.
        try:
            t = bericht.get("tijd")
            self.turbo_signaal.voeg_toe(
                float(t) if isinstance(t, (int, float)) else time.time(),
                bericht.get("bied"), bericht.get("laat"))
        except (TypeError, ValueError):
            pass
        # 2.7.0: laatste live koers, voor de verzendkoers in de execution ledger.
        if bericht.get("bied") and bericht.get("laat"):
            t = bericht.get("tijd")
            self._laatste_tick = (
                float(t) if isinstance(t, (int, float)) else time.time(),
                bericht.get("bied"), bericht.get("laat"),
            )
        if self._turbo_bezig or self._afgesloten:
            return
        self.turbo_stats["ticks"] += 1
        self.hass.async_create_task(self._turbo_tick(bericht))

    async def _turbo_tick(self, tick: dict) -> int:
        """Eén turboronde op een live koers. Geeft het aantal orders."""
        if self._turbo_bezig or self._cyclus_slot.locked():
            return 0
        nu_m = time.monotonic()
        if nu_m - self._turbo_laatst < TURBO_MIN_INTERVAL_S:
            return 0
        bid, ask = tick.get("bied"), tick.get("laat")
        if not bid or not ask or ask < bid:
            return 0
        markt = tick.get("markt")
        if markt and str(markt).upper() not in ("TRADEABLE", "EDITS_ONLY_TRADEABLE"):
            return 0
        ctx = self._turbo_ctx
        if (ctx is None or ctx.get("saldo_onbekend") or not ctx.get("tradeable")
                or not self.mode.places_orders or not self._enabled
                or not self.lifecycle.accepts_new_positions or self.koers_verouderd
                or self._afwikkeling_mislukt or self.executor.has_pending):
            return 0
        budget = self.turbo_orders_pm - self._turbo_recent(nu_m)
        if budget <= 0:
            return 0
        self._turbo_laatst = nu_m
        self._turbo_bezig = True
        try:
            async with self._cyclus_slot:
                return await self._turbo_ronde(float(bid), float(ask), budget, ctx)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - nooit de handel laten struikelen
            _LOGGER.debug("Turboronde mislukt", exc_info=True)
            return 0
        finally:
            self._turbo_bezig = False

    async def _turbo_ronde(self, bid: float, ask: float, budget: int, ctx: dict) -> int:
        now = datetime.now(timezone.utc)
        quote = VenueQuote(bid=bid, ask=ask, time=now, tradeable=True)
        self.turbo_stats["rondes"] += 1
        open_positions = await self._open_positions()
        geplaatst = 0

        # 1. Scalpreeks: bijkopen op de live koers.
        if self.reeks.enabled:
            eigen_per_cyclus = self.reeks.per_cyclus
            try:
                for p in list(open_positions):
                    if budget - geplaatst <= 0:
                        break
                    ticket = str(getattr(p, "ticket", None) or getattr(p, "id", ""))
                    if await self._strategie_van(p) != STRATEGIE_SCALP:
                        continue
                    if await self._is_bijkoop(ticket):
                        continue
                    self.reeks.per_cyclus = min(eigen_per_cyclus, budget - geplaatst)
                    n = await self._consider_reeks(p, quote, ticket)
                    geplaatst += n
                    self.turbo_stats["bijkopen"] += n
            finally:
                self.reeks.per_cyclus = eigen_per_cyclus

        # 2. Nieuwe scalppositie (2.6.1: niet als scalp als groep uitgezet is).
        if (budget - geplaatst > 0 and self._candles is not None and len(self._candles) >= 60
                and not (self._scalp_uitgezet and self.alles)):
            if geplaatst:
                open_positions = await self._open_positions()
            eigen = [p for p in open_positions
                     if await self._strategie_van(p) == STRATEGIE_SCALP]
            pending = list(self.executor.pending.values())
            laatste = (self._laatste_instap.get(STRATEGIE_SCALP, 0.0)
                       if self.combinatie else self._last_entry_ts)
            sig = await self.hass.async_add_executor_job(
                contextvars.copy_context().run,
                self._beslisser(now, STRATEGIE_SCALP), self._candles, bid, ask,
                self.strategy_cfg, now.hour, len(eigen) + len(pending),
                now.timestamp() - laatste, 0, tel_per_richting(eigen, pending),
            )
            uitbraak = False
            if sig is None or not sig.should_trade:
                # 2.5.2: geen scalpsignaal -> het eigen uitbraaksignaal op de ticks.
                nu_s = time.time()
                sig = self.turbo_signaal.evalueer(
                    nu_s, bid, ask, self.strategy_cfg,
                    self.state.atr.value, nu_s - self._turbo_sig_instap)
                uitbraak = bool(sig.should_trade)
                self.turbo_stats["laatste_signaal"] = sig.reject_reason or "instap"
            if sig is not None and sig.should_trade and await self._turbo_mag_openen(
                    sig, quote, now, open_positions, eigen, ctx):
                sig.components = {**(sig.components or {}),
                                  "strategie": STRATEGIE_SCALP, "turbo": True,
                                  # 2.5.3: herkenbaar in paneel en database.
                                  "open_reason": "turbo uitbraak" if uitbraak else "turbo scalp"}
                if uitbraak:
                    self._turbo_sig_instap = time.time()
                oud = self._geopend_in_cyclus
                self._geopend_in_cyclus = 0
                try:
                    gelukt = await self._open_position(
                        sig, quote, now, gelijktijdig_open=len(open_positions))
                    if not gelukt and getattr(self, "_mand", None) is not None:
                        self._mand.vrijgeven(self)
                    if gelukt:
                        geplaatst += 1
                        if uitbraak:
                            self.turbo_stats["uitbraak_orders"] = (
                                self.turbo_stats.get("uitbraak_orders", 0) + 1)
                finally:
                    self._geopend_in_cyclus = oud

        if geplaatst:
            nu_m = time.monotonic()
            self._turbo_orders.extend([nu_m] * geplaatst)
            self.turbo_stats["orders"] += geplaatst
            self.turbo_stats["laatste_order"] = now.isoformat(timespec="seconds")
        return geplaatst

    async def _turbo_mag_openen(self, sig, quote, now, open_positions, eigen, ctx) -> bool:
        """Dezelfde grendels als in de cyclus: risico, wisselkoers, sluiting,
        netting, spreiding, marge en vloer."""
        allowed, _why = self.risk.can_open(
            now=now, balance=ctx["balance"], equity=ctx["equity"],
            starting_balance=self.starting_balance,
            open_positions=len(open_positions) + len(self.executor.pending),
            volume=self.units / CONTRACT_SIZE, spread=quote.spread,
            last_tick_age=0.0, market_open=True, atr=self.state.atr.value,
            opening_equity=self.opening_equity,
        )
        if not allowed:
            return False
        fx_ok, _ = self.conversion.usable_for_entry(now)
        if not fx_ok:
            return False
        if self._use_schedule and self._close_buffer > 0:
            resterend = self._minuten_tot_sluiting(now)
            if resterend is not None and resterend <= self._close_buffer:
                return False
        blok, _reden = await self._toets_extra_positie(
            sig, quote, now, open_positions, ctx["equity"], eigen=eigen)
        return not blok

    async def _is_bijkoop(self, ticket: str) -> bool:
        """2.2.0: is deze positie zelf een bijkoop? Die piramidet niet verder."""
        if ticket in self._bijkopen:
            return True
        if self.db is None:
            return False
        trade = await self._open_trade_by_ticket(ticket)
        if trade is not None and str(trade.open_reason or "").startswith("pyramide van "):
            self._bijkopen.add(ticket)
            return True
        return False

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
            strategie=trade.strategie,
            execution_semantics=trade.execution_semantics,
            exit_regime=trade.exit_regime,
            mfe=(self._excursions.get(str(ticket), {}).get("mfe", 0.0)) * units,
            mae=(self._excursions.get(str(ticket), {}).get("mae", 0.0)) * units,
            gross_pnl=round((quote.mid - trade.open_mid) * direction * units, 4),
            net_pnl=round((exit_price - trade.open_price) * direction * units
                          - self._commissie(units), 4),
        )
        part.total_cost = round((part.gross_pnl or 0) - (part.net_pnl or 0), 4)
        part.cost_source = "measured"
        part.duration_seconds = int(
            (now - _as_datetime(trade.open_time, now)).total_seconds()
        )
        # 2.13.2: bestaat er al een deel-rij (tweede deelsluiting, of een
        # herhaling na een herstart), dan dat deel erbij optellen. Een tweede
        # insert brak op UNIQUE(broker_ticket, mode) en legde de hele entry
        # stil (Pepperstone 16-10 09:53 en 12:58).
        bestaand = await self.hass.async_add_executor_job(self.db.deel_van, ticket)
        if bestaand is None:
            await self.hass.async_add_executor_job(self.db.insert_trade, part)
        else:
            bestaand.volume = (bestaand.volume or 0.0) + part.volume
            for veld in ("gross_pnl", "net_pnl", "total_cost", "mfe", "mae"):
                setattr(bestaand, veld, round((getattr(bestaand, veld) or 0.0)
                                              + (getattr(part, veld) or 0.0), 4))
            bestaand.close_time = part.close_time
            bestaand.close_price = part.close_price
            bestaand.close_mid = part.close_mid
            bestaand.duration_seconds = part.duration_seconds
            await self.hass.async_add_executor_job(self.db.update_trade, bestaand)

        # De oorspronkelijke rij krimpt tot wat er nog openstaat.
        trade.volume = max(0.0, trade.volume - closed_lots)
        await self.hass.async_add_executor_job(self.db.update_trade, trade)

        self.risk.record_close(part.net_pnl or 0.0, now,
                               telt_voor_reeks=self._telt_voor_reeks(trade))
        _LOGGER.info(
            "Deel genomen: %.2f oz, netto %.2f. %s",
            units, part.net_pnl or 0.0, reason,
        )

    async def _record_broker_open(
        self, result, signal, quote: VenueQuote, side: str, now: datetime,
        gelijktijdig_open: int | None = None,
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
            gelijktijdig_open=gelijktijdig_open,
            # 2.1.0: welke strategie opende de positie (alleen bij de
            # combinatie; anders volgt het uit de run).
            strategie=(
                (signal.components or {}).get("strategie") if self.combinatie else None
            ),
            # 2.2.0: "pyramide van <ticket>" bij een bijkoop.
            open_reason=(signal.components or {}).get("open_reason"),
        )
        await self.hass.async_add_executor_job(self.db.insert_trade, trade)
        if result.ticket and trade.strategie:
            self._strategie_per_ticket[str(result.ticket)] = trade.strategie

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
        bron: str = "broker_transactions", risico: bool = True,
    ) -> None:
        """Werk de open trade bij tot een gesloten trade.

        ``risico`` (2.4.7): False voor een verweesde trade uit een eerdere
        run; die telt niet voor de daglimiet of de verliesreeks van nu.

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
        # 2.9.3: plus de commissie van de broker (cTrader; IG: 0).
        trade.net_pnl = round(
            (exit_price - trade.open_price) * direction * units - self._commissie(units), 4
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
        if risico:
            self.risk.record_close(trade.net_pnl, now,
                                   telt_voor_reeks=self._telt_voor_reeks(trade))
        _LOGGER.info(
            "Trade gesloten: %s, bruto %.2f, kosten %.2f, netto %.2f",
            reason, trade.gross_pnl, trade.total_cost, trade.net_pnl,
        )

    # -- afsluiten ---------------------------------------------------------- #

    @_met_schaal
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
            self._turbo_stop()
            # 2.8.0: een blijvende brokerverbinding (cTrader) netjes sluiten.
            sluit = getattr(self.venue, "sluit_verbinding", None)
            if sluit is not None:
                try:
                    await sluit()
                except Exception:  # noqa: BLE001
                    pass
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
