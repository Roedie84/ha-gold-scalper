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
#: 1.9.0: maximaal aantal open posities per richting (1..3). Long en short
#: mogen naast elkaar bestaan.
CONF_MAX_POSITIONS_PER_RICHTING: Final = "max_positions_per_richting"
DEFAULT_MAX_POSITIONS_PER_RICHTING: Final = 3
#: 2.5.4 (Ruud 13-10: "max posities mocht veel hoger"): 100 (was 20).
MAX_POSITIONS_PER_RICHTING_GRENS: Final = 100
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
#: 2.0.0 (L-GS-014): welke strategie beslist over instappen.
CONF_STRATEGIE: Final = "strategie"
STRATEGIE_DAGHANDEL: Final = "daghandel"
STRATEGIE_SCALP: Final = "scalp"
#: 2.1.0: beide tegelijk, elke positie met haar eigen strategie.
STRATEGIE_COMBINATIE: Final = "combinatie"
#: 2.4.0: daghandel + scalp + de veldproef (alle opzetten op 1m-30m, echte demo-orders).
STRATEGIE_ALLES: Final = "alles"
STRATEGIEEN: Final = (STRATEGIE_DAGHANDEL, STRATEGIE_SCALP, STRATEGIE_COMBINATIE, STRATEGIE_ALLES)
#: 2.1.0: vaste grootte van scalptrades bij de combinatie (ounce).
CONF_SCALP_UNITS: Final = "scalp_units"
DEFAULT_SCALP_UNITS: Final = 1.0
#: Besluit Ruud 12-10-2026: van scalpen naar daghandel.
DEFAULT_STRATEGIE: Final = STRATEGIE_DAGHANDEL
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
#: 2.8.0: Pepperstone (cTrader Open API).
VENUE_CTRADER: Final = "ctrader"
#: 2.17.0: Bitvavo (crypto spot).
VENUE_BITVAVO: Final = "bitvavo"
VENUES: Final = [
    VENUE_PUBLIC, VENUE_STOOQ, VENUE_SIMULATOR,
    VENUE_IG, VENUE_CAPITAL, VENUE_OANDA, VENUE_CTRADER, VENUE_BITVAVO,
]

#: Brokers die echt kunnen handelen; die krijgen live-modus aangeboden.
TRADING_VENUES: Final = [VENUE_IG, VENUE_CAPITAL, VENUE_OANDA, VENUE_CTRADER]

#: 2.17.0: Bitvavo. Net als bij cTrader staan de geheimen in secrets.yaml; de
#: entry bewaart de sleutelnamen en een kopie van de waarden.
CONF_BV_KEY_SECRET: Final = "bitvavo_key_secret"
CONF_BV_GEHEIM_SECRET: Final = "bitvavo_geheim_secret"
CONF_BV_KEY: Final = "bitvavo_api_key"
CONF_BV_GEHEIM: Final = "bitvavo_api_secret"
CONF_BV_MARKT: Final = "bitvavo_markt"
#: Hard plafond per koop in de quote-valuta (euro's bij EUR-markten).
CONF_BV_MAX_INZET: Final = "bitvavo_max_inzet"
DEFAULT_BV_MAX_INZET: Final = 250.0
DEFAULT_BV_MARKT: Final = "BTC-EUR"
#: Startsaldo op papier voor een nieuwe Bitvavo-entry (euro's).
DEFAULT_BV_STARTSALDO: Final = 10000.0
#: Spreadgrens bij crypto, als goud-equivalent (USD bij 4000): 8 = 0,2 %.
DEFAULT_BV_MAX_SPREAD: Final = 8.0

#: 2.18.0: de mand. Eén Bitvavo-entry handelt op de meest liquide markten in
#: plaats van op één. ``een`` = alleen de gekozen markt (zoals 2.17.0).
CONF_BV_MARKTEN: Final = "bitvavo_markten"
BV_MARKTEN_MAND: Final = "mand"
BV_MARKTEN_EEN: Final = "een"
#: Hoeveel markten tegelijk in de mand (de gekozen markt telt mee).
CONF_BV_AANTAL: Final = "bitvavo_aantal_markten"
DEFAULT_BV_AANTAL: Final = 20
#: Hooguit zoveel open posities over de hele mand samen.
CONF_BV_MAX_POSITIES: Final = "bitvavo_max_posities"
DEFAULT_BV_MAX_POSITIES: Final = 5
#: Minimale handel in 24 uur (quote-valuta) om in de mand te mogen.
CONF_BV_MIN_VOLUME: Final = "bitvavo_min_volume"
DEFAULT_BV_MIN_VOLUME: Final = 250000.0
#: Hoogste spread (procent van de koers) om in de mand te mogen.
#: 2.22.0: was 0,2 %. De twee verliezers van de mand hadden een typische spread
#: van ~0,06 % (PEPE) en ~0,04 % (PUMP); BTC/ETH/XRP zitten onder 0,002 %.
#: Boven 0,03 % eten de kosten het verwachte resultaat van een scalp op.
BV_MAND_MAX_SPREAD_PCT: Final = 0.03
#: Zo vaak wordt de mand opnieuw samengesteld.
BV_MAND_HERZIEN_MINUTEN: Final = 60
#: 2.24.0 (L-GS-025): zo vaak een waarneming van de spreads voor de mediaan
#: over 24 uur waarop de mand toelaat.
BV_MAND_SPREAD_MONSTER_MINUTEN: Final = 15

#: 2.8.0: cTrader. De geheimen zelf staan in secrets.yaml; de entry bewaart
#: de SLEUTELNAMEN plus een kopie van de tokens (die ververst de koppeling).
CONF_CT_CLIENT_ID_SECRET: Final = "ctrader_client_id_secret"
CONF_CT_CLIENT_SECRET_SECRET: Final = "ctrader_client_secret_secret"
CONF_CT_ACCESS_SECRET: Final = "ctrader_access_token_secret"
CONF_CT_REFRESH_SECRET: Final = "ctrader_refresh_token_secret"
CONF_CT_ACCESS_TOKEN: Final = "ctrader_access_token"
CONF_CT_REFRESH_TOKEN: Final = "ctrader_refresh_token"
CONF_CT_TRADER_LOGIN: Final = "ctrader_trader_login"
CONF_CT_CLIENT_ID: Final = "ctrader_client_id"
CONF_CT_CLIENT_SECRET: Final = "ctrader_client_secret"
CONF_CT_CTID: Final = "ctrader_ctid"
DEFAULT_CT_SYMBOL: Final = "XAUUSD"

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
SERVICE_EXPORT_DATA: Final = "export_data"

DISCLAIMER: Final = (
    "Technische indicatoranalyse, geen financieel advies. "
    "Papermodus simuleert geen requotes of spreadverbreding rond nieuws."
)


#: Versie van deze integratie. Gelijk aan manifest.json; een test bewaakt dat.
INTEGRATION_VERSION: Final = "2.24.3"

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
#: 4  1.9.0: tot ``max_positions_per_richting`` posities per richting, long
#:    en short naast elkaar (hedge); een tegengesteld signaal sluit niets.
#:    Trades die tegelijk openstaan zijn geen onafhankelijke waarnemingen;
#:    de clustertoets voegt ze samen. Start daarom een nieuwe run.
EXECUTION_SEMANTICS_VERSION: Final = 4


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
#: 2.24.3 (L-GS-032): veldproeftrades (``vp:*``) hebben geen tijdstop (eigen
#: maximale duur per opzet). Ze kregen toch "tijdstop" mee, waardoor
#: ``per_exitregime.tijdstop`` de hele veldproefrun bevatte.
EXIT_REGIME_VELDPROEF: Final = "veldproef"


def exit_regime_voor(strategie: str | None) -> str:
    """Het uitstapregime van een nieuw geopende trade (2.24.3, L-GS-032).

    Alleen statistiek: het regime zit niet in de vingerafdruk en verandert
    geen beslissing (de tijdstop hangt aan de uitstapregels van de strategie).
    """
    if isinstance(strategie, str) and strategie.startswith("vp:"):
        return EXIT_REGIME_VELDPROEF
    return EXIT_REGIME_HUIDIG
#: Moment waarop 1.7.4 (samen met 1.7.5) is geïnstalleerd: de herstart van
#: Home Assistant op 8 oktober 2026 om 12:16 lokale tijd. Brokertrades die
#: daarvóór openden, liepen zonder werkende tijdstop. Papertrades hadden
#: altijd een openingstijd; voor hen werkte de tijdstop al.
EXIT_REGIME_GRENS_UTC: Final = "2026-10-08T10:16:00+00:00"

# 1.11.0 (L-GS-012): na zoveel cycli op rij met een afwikkelfout voor dezelfde
# trade komt er een reparatiemelding (bij 20 s per cyclus ruim 3 minuten).
AFWIKKELFOUT_MELDING: Final = 10

# 2.4.7: verweesde trades. Een trade uit een eerdere run waarvan de positie
# bij de broker al dicht was voordat deze run hem kon meenemen (runwissel of
# herstart), bleef eeuwig open in de database en telde nergens mee (13-10:
# 23 veldproeftrades uit run 110/111). Ze worden afgewikkeld op de
# uitstapprijs uit het activiteitenoverzicht van de broker, nooit op een
# schatting. Begrensd om de IG-limieten te sparen.
WEES_INTERVAL_S: Final = 300
WEES_PER_RONDE: Final = 3
WEES_MAX_LEEFTIJD_H: Final = 46

# 2.4.9: scalpreeks (zie strategy/scalp_reeks.py).
CONF_SCALP_REEKS: Final = "scalp_reeks"
CONF_SCALP_REEKS_STAP: Final = "scalp_reeks_stap_usd"
CONF_SCALP_REEKS_MAX: Final = "scalp_reeks_max"
CONF_SCALP_REEKS_DOEL: Final = "scalp_reeks_doel_usd"
DEFAULT_SCALP_REEKS: Final = True
DEFAULT_SCALP_REEKS_STAP: Final = 0.3
DEFAULT_SCALP_REEKS_MAX: Final = 100
DEFAULT_SCALP_REEKS_DOEL: Final = 1.0

# 2.5.0: turbo-scalp - scalp reageert op de live koers (IG-stream) in plaats
# van alleen op de cyclus van 10 s, met een orderbudget per minuut.
CONF_SCALP_TURBO: Final = "scalp_turbo"
CONF_SCALP_TURBO_ORDERS: Final = "scalp_turbo_orders_per_min"
#: 2.9.3: scalp (incl. turbo) met de hand uitzetten, los van de groepsregel
#: (n >= 200, t < -3). De schaduwtrades van H-GS-003 lopen gewoon door.
CONF_SCALP_UIT: Final = "scalp_uit"
#: 2.10.0: veldproef-tijdvakken met de hand uitzetten (bv. 1m bij Pepperstone).
#: Werkt als de groepsregel; de schaduwtrades lopen door.
CONF_VP_TIJDVAKKEN_UIT: Final = "vp_tijdvakken_uit"
DEFAULT_SCALP_TURBO: Final = True
DEFAULT_SCALP_TURBO_ORDERS: Final = 20
#: Hooguit één turboronde per zoveel seconden (de stream levert vaker).
TURBO_MIN_INTERVAL_S: Final = 1.0
