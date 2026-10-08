"""Constanten voor Gold Scalper."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "gold_scalper"
MANUFACTURER: Final = "Gold Scalper"

PLATFORMS: Final = ["sensor", "binary_sensor", "switch", "button"]

# -- configuratie ----------------------------------------------------------- #

CONF_VENUE: Final = "venue"
CONF_TOKEN: Final = "token"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_ENVIRONMENT: Final = "environment"
CONF_SYMBOL: Final = "symbol"
CONF_TIMEFRAME: Final = "timeframe"
CONF_MODE: Final = "mode"
CONF_UPDATE_SECONDS: Final = "update_seconds"

CONF_UNITS: Final = "units"
CONF_RISK_BASED_SIZING: Final = "risk_based_sizing"
CONF_RISK_PER_TRADE_PCT: Final = "risk_per_trade_pct"
CONF_SCALE_WITH_CONFIDENCE: Final = "scale_with_confidence"

#: Pyramiden: bijkopen bij bevestiging, nooit bij tegenslag.
CONF_PYRAMID_ENABLED: Final = "pyramid_enabled"
CONF_PYRAMID_TRIGGER_ATR: Final = "pyramid_trigger_atr"
CONF_PYRAMID_MAX_ADDITIONS: Final = "pyramid_max_additions"
CONF_MAX_UNITS: Final = "max_units"
CONF_MAX_SPREAD: Final = "max_spread"
CONF_MAX_SPREAD_ATR: Final = "max_spread_atr_ratio"
CONF_MIN_EDGE_MULTIPLE: Final = "min_edge_multiple"

#: Doel en stop als vast bedrag in USD per ounce; nul = meeschalen met de ATR.
CONF_TAKE_PROFIT_USD: Final = "take_profit_usd"
CONF_STOP_LOSS_USD: Final = "stop_loss_usd"
CONF_TAKE_PROFIT_ATR: Final = "take_profit_atr"
CONF_STOP_LOSS_ATR: Final = "stop_loss_atr"
CONF_ENTRY_THRESHOLD: Final = "entry_threshold"
CONF_REGIME_SWITCHING: Final = "regime_switching"
#: Bars opbouwen uit live koersen in plaats van historie opvragen.
#:
#: Brokers rekenen historische koersen per datapunt af; op een demo-account is
#: dat quotum binnen een dag op. Met deze stand wordt er nooit historie
#: opgevraagd, ten koste van een opwarmperiode en iets minder nauwkeurige bars.
CONF_BUILD_FROM_QUOTES: Final = "build_from_quotes"

#: Kruiscontrole op de handelstijden: vertrouw niet alleen op de broker.
CONF_USE_SCHEDULE: Final = "use_schedule"
#: Geen nieuwe posities in de laatste minuten voor sluiting.
CONF_CLOSE_BUFFER_MINUTES: Final = "close_buffer_minutes"

CONF_ENFORCE_TRADING_HOURS: Final = "enforce_trading_hours"
CONF_TRADING_START_HOUR: Final = "trading_start_hour"
CONF_TRADING_END_HOUR: Final = "trading_end_hour"

CONF_MAX_DAILY_LOSS_PCT: Final = "max_daily_loss_pct"
CONF_MAX_TRADES_PER_DAY: Final = "max_trades_per_day"
CONF_MAX_CONSECUTIVE_LOSSES: Final = "max_consecutive_losses"
CONF_MAX_RESUMES_PER_DAY: Final = "max_resumes_per_day"
CONF_EQUITY_FLOOR_PCT: Final = "equity_floor_pct"

CONF_SHOW_PANEL: Final = "show_panel"

#: Naar welke notify-dienst meldingen gaan, bijvoorbeeld
#: "mobile_app_iphone_van_ruud". Leeg betekent geen meldingen.
CONF_NOTIFY_SERVICE: Final = "notify_service"
CONF_NOTIFY_HOURLY: Final = "notify_hourly"
CONF_NOTIFY_CRITICAL: Final = "notify_critical"
CONF_NOTIFY_SKIP_QUIET: Final = "notify_skip_quiet"
NOTIFY_NONE: Final = "geen"
CONF_DRAIN_POLICY: Final = "drain_policy"
CONF_STARTING_BALANCE: Final = "starting_balance"

# -- standaardwaarden ------------------------------------------------------- #

VENUE_SIMULATOR: Final = "simulator"
VENUE_PUBLIC: Final = "public_data"
VENUE_OANDA: Final = "oanda"
VENUE_STOOQ: Final = "stooq"
VENUE_IG: Final = "ig"
VENUE_CAPITAL: Final = "capital"
VENUES: Final = [
    VENUE_PUBLIC, VENUE_STOOQ, VENUE_SIMULATOR,
    VENUE_IG, VENUE_CAPITAL, VENUE_OANDA,
]

#: Brokers die echt kunnen handelen; die krijgen live-modus aangeboden.
TRADING_VENUES: Final = [VENUE_IG, VENUE_CAPITAL, VENUE_OANDA]

CONF_IDENTIFIER: Final = "identifier"
CONF_PASSWORD: Final = "password"
CONF_API_KEY: Final = "api_key"
CONF_EPIC: Final = "epic"
DEFAULT_EPIC: Final = "GOLD"
STOOQ_SYMBOLS: Final = ["xauusd", "xaueur"]
STOOQ_TIMEFRAMES: Final = ["1d", "1w"]

CONF_ASSUMED_SPREAD: Final = "assumed_spread"
#: Nul betekent: transactiekosten uitgeschakeld. Handig om de machinerie te
#: zien draaien, maar het resultaat is dan fictief en de poort blijft dicht.
DEFAULT_ASSUMED_SPREAD: Final = 0.0
PUBLIC_SYMBOLS: Final = ["GC=F", "XAUUSD=X"]

CONF_SIM_SEED: Final = "sim_seed"
CONF_SIM_SPREAD: Final = "sim_spread"
DEFAULT_SIM_SEED: Final = 20260823
DEFAULT_SIM_SPREAD: Final = 0.20

#: Simulator als standaard: je kunt de integratie zo installeren en zien of
#: alles werkt, zonder je ergens aan te melden.
#: Echte goudkoersen met papierhandel: geen account nodig, wél echte data.
DEFAULT_VENUE: Final = VENUE_PUBLIC
DEFAULT_ENVIRONMENT: Final = "practice"
DEFAULT_SYMBOL: Final = "XAU_USD"
DEFAULT_TIMEFRAME: Final = "1m"
DEFAULT_MODE: Final = "paper"

#: Minimaal 10 seconden. Sneller pollen levert bij een REST-API vooral
#: rate limits op, en de strategie mikt op signalen die minuten geldig blijven.
DEFAULT_UPDATE_SECONDS: Final = 20
MIN_UPDATE_SECONDS: Final = 10

#: Een mislukte koersopvraging (time-out na 6 s, haperende DNS of verbinding)
#: maakt niet meteen alles onbeschikbaar (1.7.0). Tot zoveel opvragingen op
#: rij, en zolang de laatste verse koers niet ouder is dan KOERS_HOUD_MAX_SECONDEN,
#: blijven de laatste gegevens staan met *Dataprobleem* aan. Daarna de oude
#: storing (UpdateFailed). Op 7 oktober zes losse time-outs in anderhalf uur,
#: telkens één cyclus.
KOERS_HOUD_MAX_MISLUKT: Final = 3
KOERS_HOUD_MAX_SECONDEN: Final = 180

DEFAULT_UNITS: Final = 1.0        # ounces
#: Ounces per lot bij XAU/USD. Stond eerder in twee modules apart gedefinieerd;
#: twee kopieën van hetzelfde getal kunnen uit elkaar lopen, en dan reken je in
#: de ene helft van de code met een andere eenheid dan in de andere.
CONTRACT_SIZE: Final = 100.0

DEFAULT_MAX_UNITS: Final = 5.0
DEFAULT_STARTING_BALANCE: Final = 10_000.0

TIMEFRAMES: Final = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

#: Aantal candles dat bij het opwarmen wordt gevraagd.
WARMUP_CANDLES: Final = 400
#: Ondergrens. Hoeveel een broker werkelijk levert verschilt per instrument,
#: tijdsframe en omgeving, dus wordt er afgebouwd tot dit aantal.
MIN_WARMUP_CANDLES: Final = 60

#: Hoeveel afgesloten bars de strategie per beslissing te zien krijgt.
#:
#: Eén definitie voor live én backtest. De live-lus gebruikte al een begrensd
#: venster; de backtest gaf de strategie de volledige historie tot dan toe.
#: Daardoor startten EMA's en ATR op een ander punt dan live, en groeide de
#: looptijd kwadratisch met de lengte van de dataset.
STRATEGY_WINDOW_BARS: Final = WARMUP_CANDLES * 2

ARCHIVE_FILENAME: Final = "gold_scalper_bars.db"
DATABASE_FILENAME: Final = "gold_scalper.db"
#: Het Experiment Lab: een eigen bestand naast de tradedatabase en het
#: archief. Vaste plek in de configuratiemap, niet instelbaar: een pad dat de
#: gebruiker kan kiezen, is een pad dat per ongeluk naar de tradedatabase kan
#: wijzen.
LAB_DATABASE_FILENAME: Final = "gold_scalper_lab.db"
#: Bewust in www/: alles daarin serveert Home Assistant op /local/, wat de
#: enige manier is om een eigen HTML-bestand in de UI te tonen zonder extra
#: add-on of webserver.
REPORT_FILENAME: Final = "www/gold_scalper_rapport.html"
REPORT_URL: Final = "/local/gold_scalper_rapport.html"

# -- services --------------------------------------------------------------- #

SERVICE_PREPARE_SHUTDOWN: Final = "prepare_shutdown"
SERVICE_CLOSE_ALL: Final = "close_all"
SERVICE_RESUME: Final = "resume"
SERVICE_GENERATE_REPORT: Final = "generate_report"
SERVICE_NEW_RUN: Final = "new_run"
SERVICE_WRITE_DASHBOARD: Final = "write_dashboard"
SERVICE_CAPTURE_RESPONSES: Final = "capture_responses"
SERVICE_RECONCILE: Final = "reconcile"
SERVICE_INDICATOR_LAB: Final = "indicator_lab"
SERVICE_RECHECK_EXITS: Final = "recheck_exits"
SERVICE_BACKTEST: Final = "backtest"
SERVICE_RESET_DAY: Final = "reset_day"
SERVICE_IMPORT_HISTORY: Final = "import_history"
SERVICE_VALIDATE_BACKTEST: Final = "validate_backtest"
# Experiment Lab (5.7). Alleen onderzoek: geen enkele raakt de handel.
SERVICE_LAB_SNAPSHOT: Final = "lab_snapshot"
SERVICE_LAB_CREATE_WALK_FORWARD: Final = "lab_create_walk_forward"
SERVICE_LAB_REGISTER: Final = "lab_register"
SERVICE_LAB_START: Final = "lab_start"
SERVICE_LAB_CANCEL: Final = "lab_cancel"
SERVICE_LAB_ASSESS: Final = "lab_assess"
SERVICE_LAB_COMPARE: Final = "lab_compare"

DISCLAIMER: Final = (
    "Technische indicatoranalyse, geen financieel advies. "
    "Papermodus simuleert geen requotes of spreadverbreding rond nieuws."
)


#: Versie van deze integratie. Gelijk aan manifest.json; een test bewaakt dat.
INTEGRATION_VERSION: Final = "1.7.8"

#: Versie van het uitvoeringsgedrag: hoe posities worden gevolgd, afgerekend
#: en beheerd. Gaat omhoog bij elke wijziging die dat gedrag verandert, ook als
#: de strategie gelijk blijft - en zit in de vingerafdruk, zodat er dan een
#: nieuwe run begint.
#:
#: 1  tot en met 5.3.1: open posities werden als gesloten gezien; geen
#:    exitbeheer, de positielimiet hield niet.
#: 2  5.3.2-5.3.3: posities zichtbaar, verplaatste stops teruggeschreven.
#: 3  5.4.0: één handelsdag, kosten uit het ledger, sluitredenen op bewijs,
#:    geen nieuwe positie zonder bruikbare wisselkoers.
EXECUTION_SEMANTICS_VERSION: Final = 3


#: Uitstapregime van een trade (1.7.6). Alleen voor de statistiek: het zit
#: niet in de vingerafdruk en verandert geen enkele beslissing.
#:
#: Tot 1.7.4 kwamen IG-posities binnen zonder openingstijd, waardoor tijdstop
#: en maximale duur bij de broker nooit vuurden. Sinds 1.7.4 wel. Binnen
#: dezelfde run zijn dat twee uitstapgedragingen; per trade vastleggen onder
#: welk regime hij opende, maakt ze apart te beoordelen.
EXIT_REGIME_ZONDER_TIJDSTOP: Final = "zonder_tijdstop"
EXIT_REGIME_TIJDSTOP: Final = "tijdstop"
#: Het regime waaronder nu geopende trades vallen.
EXIT_REGIME_HUIDIG: Final = EXIT_REGIME_TIJDSTOP
#: Moment waarop 1.7.4 (samen met 1.7.5) is geïnstalleerd: de herstart van
#: Home Assistant op 8 oktober 2026 om 12:16 lokale tijd. Brokertrades die
#: daarvóór openden, liepen zonder werkende tijdstop. Papertrades hadden
#: altijd een openingstijd; voor hen werkte de tijdstop al.
EXIT_REGIME_GRENS_UTC: Final = "2026-10-08T10:16:00+00:00"
