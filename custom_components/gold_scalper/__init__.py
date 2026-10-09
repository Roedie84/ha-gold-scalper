"""Gold Scalper: XAU/USD-analyse en handel, volledig binnen Home Assistant."""

from __future__ import annotations

import functools
import json
import logging
from datetime import datetime

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    SERVICE_LAB_ASSESS,
    SERVICE_LAB_CANCEL,
    SERVICE_LAB_COMPARE,
    SERVICE_LAB_CREATE_WALK_FORWARD,
    SERVICE_LAB_REGISTER,
    SERVICE_LAB_SNAPSHOT,
    SERVICE_LAB_START,
    SERVICE_WRITE_DASHBOARD,
    SERVICE_RECONCILE,
    SERVICE_CAPTURE_RESPONSES,
    SERVICE_INDICATOR_LAB,
    SERVICE_RECHECK_EXITS,
    SERVICE_NEW_RUN,
    CONF_SHOW_PANEL, DOMAIN, PLATFORMS, REPORT_FILENAME, SERVICE_BACKTEST,
    SERVICE_CLOSE_ALL, SERVICE_GENERATE_REPORT, SERVICE_IMPORT_HISTORY,
    SERVICE_PREPARE_SHUTDOWN, SERVICE_RESET_DAY, SERVICE_RESUME,
    SERVICE_VALIDATE_BACKTEST,
)
from .coordinator import GoldScalperCoordinator
from .http import async_register_frontend, async_unregister_frontend

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

#: Velden die een persoon of rekening aanwijzen en niet in testmateriaal horen.
_PRIVE = {"accountId", "accountName", "accountAlias", "clientId", "dealingEnabled"}


def _anonimiseer(waarde):
    """Haal rekeningnummers en namen uit een antwoord van de broker."""
    if isinstance(waarde, dict):
        return {
            k: ("VERWIJDERD" if k in _PRIVE else _anonimiseer(v))
            for k, v in waarde.items()
        }
    if isinstance(waarde, list):
        return [_anonimiseer(v) for v in waarde]
    return waarde


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = GoldScalperCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Zijbalk-item en rapportadres. Gebeurt automatisch: het dashboard hoort
    # er te zijn zonder dat je eerst een knop indrukt of YAML plakt.
    options = {**entry.data, **entry.options}
    await async_register_frontend(hass, options.get(CONF_SHOW_PANEL, True))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    async def _on_stop(event) -> None:
        await _stop_koersstroom(hass, entry.entry_id)
        await coordinator.async_shutdown_hook()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)
    )
    _register_services(hass)

    # Experiment Lab (fase 9A): na de handel, en omhuld. Een fout hier wordt
    # gelogd en blokkeert niets. Eén Lab per Home Assistant, niet per entry.
    await _async_lab(hass, "async_setup_lab")
    return True


async def _async_lab(hass: HomeAssistant, actie: str) -> None:
    """Roep de Lab-koppeling aan, zonder dat die de handel kan tegenhouden.

    Ook de import zit hierbinnen: een importfout in het Lab mag het laden van
    Gold Scalper niet breken.
    """
    try:
        from . import lab_panel

        await getattr(lab_panel, actie)(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Gold Scalper Lab: %s mislukte; de handel draait door", actie)


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_CLOSE_ALL):
        return

    def _coordinators() -> list[GoldScalperCoordinator]:
        return list(hass.data.get(DOMAIN, {}).values())

    async def prepare_shutdown(call: ServiceCall) -> None:
        for coordinator in _coordinators():
            result = await coordinator.async_prepare_shutdown()
            _LOGGER.info("Afwikkelen: %s", result.get("message"))

    async def close_all(call: ServiceCall) -> None:
        for coordinator in _coordinators():
            await coordinator.async_close_all()

    async def resume(call: ServiceCall) -> None:
        for coordinator in _coordinators():
            if not await coordinator.async_resume():
                raise HomeAssistantError(
                    "Hervatten geweigerd: de daglimiet is vandaag al te vaak "
                    "opnieuw gezet.\n\nWacht tot morgen, of roep "
                    "gold_scalper.reset_day aan om de dag opnieuw te beginnen."
                )

    async def generate_report(call: ServiceCall) -> None:
        from .dashboard.report import write_report

        for coordinator in _coordinators():
            path = hass.config.path(call.data.get("path") or REPORT_FILENAME)
            from homeassistant.util import dt as dt_util

            written = await hass.async_add_executor_job(
                write_report, coordinator.db, coordinator.run_id, path,
                coordinator.gate, dt_util.DEFAULT_TIME_ZONE,
                coordinator.conversion.as_dict(),
            )
            _LOGGER.info("Keuringsrapport geschreven naar %s", written)

    async def reset_day(call: ServiceCall) -> None:
        """Begin de handelsdag opnieuw zonder op middernacht te wachten."""
        for coordinator in _coordinators():
            bericht = await coordinator.async_reset_day()
            _LOGGER.warning("Handmatige dagreset: %s", bericht)

    def _toon(titel: str, tekst: str, sleutel: str) -> None:
        """Zet de uitslag van een actie als melding in Home Assistant.

        Geslaagde acties logden op informatieniveau, en het logboek toont
        alleen waarschuwingen en fouten. Een geslaagde actie gaf daardoor geen
        enkel zichtbaar resultaat, en leek mislukt.
        """
        hass.async_create_task(hass.services.async_call(
            "persistent_notification", "create",
            {"title": titel, "message": tekst,
             "notification_id": f"{DOMAIN}_{sleutel}"},
        ))

    def _zeg_wat_er_misging(naam: str):
        """Maak van een onverwachte fout een leesbare melding.

        Home Assistant toont bij een fout die geen HomeAssistantError is
        alleen "Unknown error", zonder bestand of regel. De traceback belandt
        dan in het logboek van de WebSocket-laag in plaats van bij deze
        integratie, en dan is niet te zien wat er stukging.

        Dat kostte twee ronden gissen. Nu komt de oorzaak in de melding zelf
        te staan, en de volledige traceback onder deze logger.
        """
        def omhullen(functie):
            @functools.wraps(functie)
            async def uitvoeren(call: ServiceCall):
                try:
                    return await functie(call)
                except HomeAssistantError:
                    raise
                except Exception as err:  # noqa: BLE001
                    _LOGGER.exception("Actie %s liep vast", naam)
                    raise HomeAssistantError(
                        f"{naam} liep vast op {type(err).__name__}: {err}. "
                        "De volledige traceback staat in het logboek onder "
                        "custom_components.gold_scalper."
                    ) from err
            return uitvoeren
        return omhullen

    async def backtest(call: ServiceCall) -> None:
        """Draai de strategie over de opgebouwde historie."""
        from .analysis.backtest import run_backtest

        for coordinator in _coordinators():
            # Eerst het archief: dat groeit over herstarts heen en bevat
            # doorgaans veel meer dan wat er in het geheugen staat. Zonder
            # historie is een hypothese pas na weken te toetsen; met historie
            # in een minuut.
            candles = None
            if coordinator.archive is not None:
                try:
                    candles = await hass.async_add_executor_job(
                        coordinator.archive.load,
                        coordinator.symbol, coordinator.timeframe,
                    )
                except (ValueError, RuntimeError):
                    candles = None

            if candles is None or len(candles) < 310:
                # Terugvallen op wat er in het geheugen zit.
                candles = coordinator._candles

            if candles is None or len(candles) < 310:
                raise HomeAssistantError(
                    f"Er zijn {0 if candles is None else len(candles)} bars "
                    "beschikbaar; een backtest heeft er minstens 310 nodig. "
                    "Het archief vult zich vanaf nu vanzelf."
                )

            spread = call.data.get("spread")
            if spread is None:
                quote = coordinator._last_quote
                spread = quote.spread if quote else 0.60

            # Beide richtingen doorrekenen wanneer daarom wordt gevraagd.
            #
            # De gemeten trefkans ligt ver onder wat willekeurig instappen zou
            # opleveren bij dezelfde exits. Een signaal dat structureel
            # slechter is dan toeval bevat informatie met het verkeerde teken -
            # of dat zo is, valt alleen te zien door het om te draaien.
            #
            # Er valt niets aan af te stellen: het werkt of het werkt niet.
            # Daarom mag deze toets waar parameteroptimalisatie niet mag.
            omgekeerd = bool(call.data.get("invert", False))

            result = await hass.async_add_executor_job(
                functools.partial(
                    run_backtest, candles, coordinator.strategy_cfg,
                    coordinator.exits.config, spread=spread,
                    slippage=call.data.get("slippage", 0.02),
                    units=call.data.get("units", coordinator.units),
                    invert=omgekeerd,
                )
            )
            summary = result.summary()
            summary["invert"] = omgekeerd
            coordinator.backtest = summary
            # 1.7.5: bewaren, zodat de uitkomst een herstart overleeft.
            await coordinator.async_bewaar_resultaten()
            _LOGGER.warning(
                "Backtest%s over %d bars: %d trades, trefkans %.1f%%, "
                "netto %.2f, bruto %.2f, kosten %.2f",
                " (omgekeerd)" if omgekeerd else "",
                summary["bars"], summary["trades"], summary["win_rate"],
                summary["net_pnl"], summary["gross_pnl"],
                summary["total_costs"],
            )
            _toon(
                "Gold Scalper: backtest" + (" (omgekeerd)" if omgekeerd else ""),
                f"{summary['bars']} bars, {summary['trades']} trades, trefkans "
                f"{summary['win_rate']:.1f}%.\nNetto {summary['net_pnl']:+.2f}, "
                f"bruto {summary['gross_pnl']:+.2f}, kosten "
                f"{summary['total_costs']:.2f}.",
                "backtest_omgekeerd" if omgekeerd else "backtest",
            )
            hass.bus.async_fire(f"{DOMAIN}_backtest_done", summary)
            await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_PREPARE_SHUTDOWN, _zeg_wat_er_misging("prepare_shutdown")(prepare_shutdown))
    hass.services.async_register(DOMAIN, SERVICE_CLOSE_ALL, _zeg_wat_er_misging("close_all")(close_all))
    hass.services.async_register(DOMAIN, SERVICE_RESUME, _zeg_wat_er_misging("resume")(resume))
    hass.services.async_register(DOMAIN, SERVICE_GENERATE_REPORT, _zeg_wat_er_misging("generate_report")(generate_report))
    _register_lab_services(hass)
    async def import_history(call: ServiceCall) -> ServiceResponse:
        """Vul het archief met historie van de broker.

        Twee manieren:

        * ``days`` (1.2): zoveel dagen terug vanaf de oudste bar in het
          archief, per blok opgehaald, begrensd door ``max_points``. Zo groeit
          het archief naar het verleden; elke keer dat je dit aanroept, gaat
          het verder terug.
        * ``bars``: de laatste bars in één stap (hooguit 1000 bij IG). Vult
          alleen recente gaten.

        Bewust handmatig: elk datapunt telt tegen het weekquotum.
        """
        dagen = call.data.get("days")
        budget = int(call.data.get("max_points", 5000))
        gevraagd = int(call.data.get("bars", 1000))
        antwoord: dict = {}

        for coordinator in _coordinators():
            if coordinator.archive is None:
                raise HomeAssistantError("Het archief is niet geopend.")
            voor = await hass.async_add_executor_job(
                coordinator.archive.stats, coordinator.symbol, coordinator.timeframe,
            )
            info: dict = {}
            try:
                if dagen is not None:
                    if not hasattr(coordinator.venue, "history"):
                        raise HomeAssistantError(
                            "Deze databron kan geen historie per periode leveren; "
                            "gebruik 'bars'.")
                    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

                    eind = (_dt.fromisoformat(voor.first) if voor.first
                            else _dt.now(_tz.utc))
                    begin = eind - _td(days=int(dagen))
                    candles, info = await coordinator.venue.history(
                        coordinator.symbol, coordinator.timeframe, begin, eind, budget,
                    )
                else:
                    candles = await coordinator.venue.candles(
                        coordinator.symbol, coordinator.timeframe, gevraagd
                    )
                    info = {"points": len(candles), "stopped": "complete"}
            except HomeAssistantError:
                raise
            except Exception as err:  # noqa: BLE001
                raise HomeAssistantError(
                    f"Historie ophalen mislukte: {err}. Bij IG telt elk "
                    "datapunt tegen het weekquotum; is dat op, probeer het "
                    "volgende week opnieuw of vraag minder."
                ) from err

            nieuw = 0
            if candles is not None and len(candles):
                nieuw = await hass.async_add_executor_job(
                    coordinator.archive.store, coordinator.symbol,
                    coordinator.timeframe, candles, "import",
                )
            stats = await hass.async_add_executor_job(
                coordinator.archive.stats, coordinator.symbol,
                coordinator.timeframe,
            )
            reden = {
                "complete": "volledige periode opgehaald",
                "budget": "gestopt bij het puntenbudget; roep opnieuw aan om verder terug te gaan",
                "allowance": "gestopt: het IG-quotum is bijna op",
                "error": "gestopt na een fout van IG; wat binnen was, is bewaard",
            }.get(info.get("stopped"), info.get("stopped"))
            # Informatief, geen waarschuwing: een geslaagde import hoort niet
            # als rood item in het logboek te staan.
            _LOGGER.info(
                "Historie ingelezen: %d bars opgehaald, %d nieuw. Archief nu "
                "%d bars over %.1f dagen, %d gaten, dekking %.0f%%.",
                0 if candles is None else len(candles), nieuw, stats.bars,
                stats.span_days, stats.gaps, stats.coverage * 100,
            )
            antwoord = {
                "message": (
                    f"{0 if candles is None else len(candles)} bars opgehaald, {nieuw} nieuw. "
                    f"Archief: {stats.bars} bars, van {stats.first} tot {stats.last}. "
                    f"{reden}."),
                "fetched": 0 if candles is None else len(candles),
                "new": nieuw,
                "points_used": info.get("points"),
                "chunks": info.get("chunks"),
                "stopped": info.get("stopped"),
                "reached": info.get("reached"),
                "ig_error": info.get("error"),
                "ig_allowance": info.get("allowance"),
                "archive": {"bars": stats.bars, "first": stats.first, "last": stats.last,
                            "span_days": round(stats.span_days, 1), "gaps": stats.gaps,
                            "coverage": round(stats.coverage, 3)},
            }
            await coordinator.async_request_refresh()
        return antwoord

    hass.services.async_register(
        DOMAIN, SERVICE_IMPORT_HISTORY, _zeg_wat_er_misging("import_history")(import_history),
        schema=vol.Schema({
            vol.Exclusive("bars", "manier"): vol.All(vol.Coerce(int), vol.Range(100, 5000)),
            vol.Exclusive("days", "manier"): vol.All(vol.Coerce(int), vol.Range(1, 180)),
            vol.Optional("max_points"): vol.All(vol.Coerce(int), vol.Range(100, 10000)),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def validate_backtest(call: ServiceCall) -> None:
        """Draai de backtest over de periode waarin de bot werkelijk handelde.

        Alle hypothesen die je op historische data toetst, rusten op de aanname
        dat de backtest de werkelijkheid nabootst. Die aanname is zelden
        gecontroleerd, en als hij niet klopt is elke toets erop waardeloos.
        """
        from .analysis.backtest import run_backtest
        from .analysis.validation import compare

        for coordinator in _coordinators():
            if coordinator.archive is None:
                raise HomeAssistantError("Het archief is niet geopend.")

            trades = await hass.async_add_executor_job(
                coordinator.db.closed_trades, coordinator.run_id
            )
            if not trades:
                raise HomeAssistantError(
                    "Geen gesloten trades in deze run om tegen te vergelijken."
                )

            # Precies de periode waarin gehandeld is, met wat aanloop voor de
            # indicatoren. Zonder die aanloop begint de backtest blind.
            eerste = min(t.open_time for t in trades)
            laatste = max(t.close_time or t.open_time for t in trades)
            start = int(
                datetime.fromisoformat(eerste).timestamp()
            ) - 400 * 900
            eind = int(datetime.fromisoformat(laatste).timestamp())

            try:
                candles = await hass.async_add_executor_job(
                    lambda: coordinator.archive.load(
                        coordinator.symbol, coordinator.timeframe, start, eind
                    )
                )
            except (ValueError, RuntimeError) as err:
                raise HomeAssistantError(
                    f"Het archief heeft geen bars over deze periode: {err}. "
                    "Vul het eerst met gold_scalper.import_history."
                ) from err

            quote = coordinator._last_quote
            # Met sleutelwoorden: `run_backtest` heeft keyword-only
            # argumenten, en positioneel doorgeven faalt altijd.
            result = await hass.async_add_executor_job(
                functools.partial(
                    run_backtest, candles, coordinator.strategy_cfg,
                    coordinator.exits.config,
                    spread=quote.spread if quote else 0.60,
                    slippage=coordinator.strategy_cfg.expected_slippage,
                    units=coordinator.units,
                )
            )
            validatie = await hass.async_add_executor_job(
                compare, trades, result
            )
            coordinator.validation = validatie.as_dict()
            # 1.7.5: bewaren, zodat de uitkomst een herstart overleeft.
            await coordinator.async_bewaar_resultaten()

            _LOGGER.info(
                "Backtestvalidatie: %s. %s",
                validatie.verdict, validatie.explanation.split("\n")[0],
            )
            regels = "\n".join(
                f"- {c['maat']}: live {c['live']}, backtest {c['backtest']}"
                f" ({c['richting']})"
                for c in coordinator.validation.get("vergelijkingen", [])
            )
            _toon(
                "Gold Scalper: backtest tegen live",
                f"{validatie.verdict}\n\n{validatie.explanation}"
                + (f"\n\n{regels}" if regels else ""),
                "validatie",
            )
            hass.bus.async_fire(
                f"{DOMAIN}_validation_done", coordinator.validation
            )
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_VALIDATE_BACKTEST,
        _zeg_wat_er_misging("validate_backtest")(validate_backtest),
    )

    async def new_run(call: ServiceCall) -> None:
        """Begin bewust een nieuwe bewijsfase.

        Nodig wanneer blijkt dat de meting fout was: dan wil je opnieuw
        beginnen zonder iets aan de strategie te veranderen. Zonder deze dienst
        zou je een instelling moeten verzinnen om aan te passen, en dan meet je
        twee dingen tegelijk.
        """
        reden = call.data.get("note")
        for coordinator in _coordinators():
            nieuw = await coordinator.async_new_run(reden)
            _LOGGER.warning("Nieuwe bewijsfase: run %s", nieuw)

    hass.services.async_register(
        DOMAIN, SERVICE_NEW_RUN, _zeg_wat_er_misging("new_run")(new_run),
        schema=vol.Schema({vol.Optional("note"): cv.string}),
    )

    async def recheck_exits(call: ServiceCall) -> None:
        """Laat alle uitstapprijzen opnieuw bij de broker opzoeken.

        Nodig omdat een eerdere versie de verkeerde transactie kon koppelen:
        twee posities met bijna dezelfde instapprijs maar tegengestelde
        richting waren niet te scheiden. Die trades staan als gecorrigeerd in
        de database terwijl hun uitstapprijs van een andere trade komt.
        """
        for coordinator in _coordinators():
            aantal = await hass.async_add_executor_job(
                coordinator.db.mark_for_recheck, coordinator.run_id
            )
            _LOGGER.warning(
                "%d trade(s) worden opnieuw opgezocht bij de broker. Dat "
                "gebeurt in stappen van vijf, elke paar minuten.", aantal,
            )
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_RECHECK_EXITS,
        _zeg_wat_er_misging("recheck_exits")(recheck_exits),
    )

    hass.services.async_register(
        DOMAIN, SERVICE_RESET_DAY, _zeg_wat_er_misging("reset_day")(reset_day),
    )
    async def indicator_lab(call: ServiceCall) -> None:
        """Toets elke indicator op het barsarchief.

        Ontdekken en bevestigen zijn gescheiden, en de lat stijgt met het
        aantal indicatoren. Wie twintig indicatoren op dezelfde data toetst,
        vindt er anders altijd een paar die door toeval lijken te werken.
        """
        from .analysis.indicator_lab import run_lab

        for coordinator in _coordinators():
            if coordinator.archive is None:
                raise HomeAssistantError("Het archief is niet geopend.")
            try:
                candles = await hass.async_add_executor_job(
                    coordinator.archive.load,
                    coordinator.symbol, coordinator.timeframe,
                )
            except (ValueError, RuntimeError) as err:
                raise HomeAssistantError(
                    f"Geen bars in het archief: {err}"
                ) from err

            rapport = await hass.async_add_executor_job(
                functools.partial(
                    run_lab, candles,
                    doel=coordinator.strategy_cfg.take_profit_atr,
                    stop=coordinator.strategy_cfg.stop_loss_atr,
                    kosten=call.data.get("kosten", 0.75),
                )
            )
            coordinator.lab = rapport.as_dict()
            # 1.7.5: bewaren, zodat de uitkomst een herstart overleeft.
            await coordinator.async_bewaar_resultaten()
            _LOGGER.warning("Indicatorlab: %s", rapport.conclusie)
            _toon("Gold Scalper: indicatorlab", rapport.conclusie, "lab")
            hass.bus.async_fire(f"{DOMAIN}_indicator_lab", coordinator.lab)
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_INDICATOR_LAB,
        _zeg_wat_er_misging("indicator_lab")(indicator_lab),
        schema=vol.Schema({vol.Optional("kosten"): vol.Coerce(float)}),
    )

    async def reconcile(call: ServiceCall) -> None:
        """Leg de trades van de laatste dagen naast het brokeroverzicht."""
        dagen = float(call.data.get("dagen", 3))
        for coordinator in _coordinators():
            uitslag = await coordinator.async_reconcile(dagen)
            if not uitslag:
                raise HomeAssistantError(
                    "Afstemmen kan alleen met een broker die zijn "
                    "transacties teruggeeft."
                )
            regels = "\n".join(
                f"- {a['uitleg']}" for a in uitslag.get("afwijkingen", [])[:10]
            )
            _toon(
                "Gold Scalper: afstemming met de broker",
                uitslag["samenvatting"] + (f"\n\n{regels}" if regels else ""),
                "afstemming",
            )
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_RECONCILE, _zeg_wat_er_misging("reconcile")(reconcile),
        schema=vol.Schema({vol.Optional("dagen"): vol.Coerce(float)}),
    )

    async def capture_responses(call: ServiceCall) -> None:
        """Leg de werkelijke antwoorden van de broker vast, voor tests.

        Rekeningnummers en namen worden eruit gehaald. Tokens en sleutels
        zitten in de headers, niet in deze antwoorden.
        """
        for coordinator in _coordinators():
            haal = getattr(coordinator.venue, "raw_responses", None)
            if haal is None:
                raise HomeAssistantError("Deze broker kan dat niet.")
            ruw = await haal()
            schoon = _anonimiseer(ruw)
            pad = hass.config.path("gold_scalper_ig_antwoorden.json")
            await hass.async_add_executor_job(
                lambda: open(pad, "w", encoding="utf-8").write(
                    json.dumps(schoon, indent=2, ensure_ascii=False)
                )
            )
            _toon(
                "Gold Scalper: brokerantwoorden vastgelegd",
                f"Opgeslagen in {pad}. Stuur dit bestand op; de tests toetsen "
                "daarna tegen wat de broker werkelijk stuurt.",
                "antwoorden",
            )

    hass.services.async_register(
        DOMAIN, SERVICE_CAPTURE_RESPONSES,
        _zeg_wat_er_misging("capture_responses")(capture_responses),
    )

    async def write_dashboard(call: ServiceCall) -> None:
        """Schrijf een Lovelace-dashboard met de werkelijke entiteit-id's.

        Het meegeleverde voorbeeld verwees naar gegokte id's die Home Assistant
        niet aanmaakt. Deze versie leest ze uit het entiteitenregister.
        """
        from homeassistant.helpers import entity_registry as er

        from .dashboard.lovelace import build_dashboard

        register = er.async_get(hass)
        for coordinator in _coordinators():
            entry_id = coordinator.entry.entry_id
            voorvoegsel = f"{entry_id}_"
            ids = {
                e.unique_id[len(voorvoegsel):]: e.entity_id
                for e in er.async_entries_for_config_entry(register, entry_id)
                if e.unique_id and e.unique_id.startswith(voorvoegsel)
            }
            tekst = build_dashboard(ids, coordinator.symbol)
            pad = hass.config.path("gold_scalper_dashboard.yaml")
            await hass.async_add_executor_job(
                lambda: open(pad, "w", encoding="utf-8").write(tekst)
            )
            _toon(
                "Gold Scalper: dashboard geschreven",
                f"{len(ids)} entiteiten verwerkt. Opgeslagen in {pad}. Open dat "
                "bestand en plak de inhoud in de ruwe configuratie-editor van "
                "een dashboard.",
                "dashboard",
            )

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_DASHBOARD,
        _zeg_wat_er_misging("write_dashboard")(write_dashboard),
    )

    hass.services.async_register(
        DOMAIN, SERVICE_BACKTEST, _zeg_wat_er_misging("backtest")(backtest),
        # Elk veld uit services.yaml moet hier staan. Ontbreekt er een, dan
        # weigert de validatie zodra de interface dat veld meestuurt, en ziet
        # de gebruiker alleen "Unknown error" - zonder aanwijzing welk veld.
        # Er staat een test op die beide lijsten vergelijkt.
        schema=vol.Schema({
            vol.Optional("spread"): vol.Coerce(float),
            vol.Optional("slippage"): vol.Coerce(float),
            vol.Optional("units"): vol.Coerce(float),
            vol.Optional("invert"): cv.boolean,
        }),
    )


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Bewaarde toestand opruimen als de entry verdwijnt.

    Anders blijft een noodstop van een verwijderde configuratie in
    .storage staan en duikt hij op bij een gelijknamige nieuwe entry.
    """
    from .storage.state import ResultsStore, StateStore

    await StateStore(hass, entry.entry_id).async_remove()
    await ResultsStore(hass, entry.entry_id).async_remove()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: GoldScalperCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await _stop_koersstroom(hass, entry.entry_id)
        await coordinator.async_shutdown_hook()
        await async_unregister_frontend(hass)
        if not hass.data.get(DOMAIN):
            # De laatste entry: het Lab-paneel gaat mee. Bij herladen zet de
            # nieuwe setup het terug, zonder tweede herstel.
            await _async_lab(hass, "async_unload_lab")
    return unloaded


async def _stop_koersstroom(hass: HomeAssistant, entry_id: str) -> None:
    """Live koers van het dashboard stoppen (1.8.1). Raakt de handel niet."""
    try:
        from .broker_stream import async_stop_stream

        await async_stop_stream(hass, entry_id)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Koersstroom stoppen mislukte", exc_info=True)


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _register_lab_services(hass: HomeAssistant) -> None:
    """De Lab-acties (5.7). Antwoord altijd als response; nooit een order.

    De afhandeling zit in ``lab_panel`` en wordt pas bij aanroep geladen: een
    fout in het Lab mag het laden van Gold Scalper niet breken.
    """
    from .lab_actions import ACTION_FIELDS

    def _schema(actie: str) -> vol.Schema:
        return vol.Schema(
            {vol.Optional("request_id"): str,
             **{vol.Optional(veld): vol.Any(str, int, float, bool, list, dict, None)
                for veld in ACTION_FIELDS[actie]}},
            extra=vol.PREVENT_EXTRA,
        )

    def _handler(actie: str):
        async def _lab_actie(call: ServiceCall) -> ServiceResponse:
            from . import lab_panel

            return await lab_panel.async_handle_action(
                hass, actie, dict(call.data), call.context.user_id)
        return _lab_actie

    # Elke dienst op een eigen regel: zo controleert de statische test dat
    # alles uit services.yaml echt geregistreerd is.
    antwoord = SupportsResponse.ONLY
    hass.services.async_register(DOMAIN, SERVICE_LAB_SNAPSHOT, _handler("snapshot"), schema=_schema("snapshot"), supports_response=antwoord)
    hass.services.async_register(DOMAIN, SERVICE_LAB_CREATE_WALK_FORWARD, _handler("create_walk_forward"), schema=_schema("create_walk_forward"), supports_response=antwoord)
    hass.services.async_register(DOMAIN, SERVICE_LAB_REGISTER, _handler("register"), schema=_schema("register"), supports_response=antwoord)
    hass.services.async_register(DOMAIN, SERVICE_LAB_START, _handler("start"), schema=_schema("start"), supports_response=antwoord)
    hass.services.async_register(DOMAIN, SERVICE_LAB_CANCEL, _handler("cancel"), schema=_schema("cancel"), supports_response=antwoord)
    hass.services.async_register(DOMAIN, SERVICE_LAB_ASSESS, _handler("assess"), schema=_schema("assess"), supports_response=antwoord)
    hass.services.async_register(DOMAIN, SERVICE_LAB_COMPARE, _handler("compare"), schema=_schema("compare"), supports_response=antwoord)
