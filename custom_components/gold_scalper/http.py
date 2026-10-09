"""Het rapport rechtstreeks serveren vanuit de integratie.

De eerdere opzet vroeg te veel van de gebruiker: knop indrukken, wachten op een
bestand in ``www/``, een herstart omdat die map nieuw was, en dan zelf een
iframe-kaart aanmaken. Vier stappen voordat je iets ziet, en elke stap kon
stilletjes misgaan.

Dit is de vervanging. De integratie registreert een eigen adres en zet een
menu-item in de zijbalk. Bij het openen wordt het rapport ter plekke gebouwd
uit de database, dus wat je ziet is altijd actueel. Geen bestand, geen
``www/``, geen herstart.

Beveiliging, eerlijk benoemd: ``requires_auth`` staat uit. Dat moet, want een
iframe in de Home Assistant-frontend stuurt geen bearer-token mee, dus met
authenticatie aan zou het paneel simpelweg leeg blijven. Gevolg is dat iedereen
die je Home Assistant kan bereiken dit rapport kan lezen.

Wat daar wel of niet in staat: handelsresultaten, posities en statistieken.
Géén API-tokens, géén account-ID, géén inloggegevens - die komen in de
rapportgenerator niet voor. Wie meeleest ziet dus wat je strategie deed, niet
hoe hij bij je geld komt. Vind je dat alsnog te veel, dan zet je het paneel uit
met ``show_panel: false`` in de opties.

1.8.1: daarnaast een websocket-abonnement ``gold_scalper/broker_stream``
(``broker_stream.py``) voor de live koers; ook alleen voor beheerders.

1.8.0: de zijbalk-ingang toont nu het broker-dashboard, een eigen webcomponent
(``frontend/broker-panel.js``). Dat haalt zijn gegevens via ``hass.callApi``
bij ``/api/gold_scalper/broker``; díe route vraagt wél authenticatie en
beheerdersrecht, want een webcomponent stuurt de sessie van de frontend mee.
Het overzicht en het rapport hierboven blijven ongewijzigd bereikbaar.
"""

from __future__ import annotations

import logging

import hashlib
import time
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN, INTEGRATION_VERSION

_LOGGER = logging.getLogger(__name__)

OVERVIEW_URL = "/api/gold_scalper/overview"
REPORT_URL = "/api/gold_scalper/report"
PANEL_URL_PATH = "gold-scalper"

#: 1.8.0: broker-dashboard. Eigen webcomponent op dezelfde zijbalk-ingang.
BROKER_DATA_URL = "/api/gold_scalper/broker"
BROKER_STATIC_URL = "/gold_scalper_static/broker-panel.js"
BROKER_WEBCOMPONENT = "gold-scalper-broker-panel"
BROKER_JS_FILE = Path(__file__).resolve().parent / "frontend" / "broker-panel.js"
#: Hoe lang een gebouwd model hooguit hergebruikt wordt als de coordinator
#: geen nieuwe cyclus heeft gedraaid. Binnen een cyclus verandert er niets.
BROKER_CACHE_MAX_SECONDS = 60
_GEEN_CACHE = {"Cache-Control": "no-store, must-revalidate"}

#: Hoe vaak het rapport zichzelf ververst, in seconden.
#:
#: Zestig is een compromis. De onderliggende data ververst elke twintig
#: seconden, maar het rapport opnieuw opbouwen kost bij duizenden trades
#: honderden milliseconden; drie keer per minuut zou dat verdrievoudigen
#: zonder dat je meer ziet. Aan te passen met ?refresh=N, en 0 zet het uit.
DEFAULT_REFRESH_SECONDS = 60
MIN_REFRESH_SECONDS = 15


class GoldScalperOverviewView(HomeAssistantView):
    """Compacte samenvatting; het paneel opent hierop.

    Het keuringsrapport is bedoeld om te bestuderen, niet om even op je
    telefoon te bekijken. Deze pagina beantwoordt de vier vragen die je dan
    hebt en zet het rapport één klik verderop.
    """

    url = OVERVIEW_URL
    name = "api:gold_scalper:overview"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        coordinator = _pick_coordinator(hass, request.query.get("entry"))
        if coordinator is None:
            return web.Response(
                text=_placeholder(
                    "Nog geen actieve configuratie",
                    "Controleer Instellingen, Apparaten en diensten.",
                ),
                content_type="text/html",
            )
        if not coordinator.data:
            return web.Response(
                text=_placeholder(
                    "Aan het opstarten",
                    "Er is nog geen meting binnen. Ververs over een halve minuut.",
                ),
                content_type="text/html",
            )

        from homeassistant.util import dt as dt_util

        from .dashboard.overview import build_overview
        from .status import build_status

        payload = dict(coordinator.data)
        payload["status"] = build_status(payload)
        payload["symbol"] = coordinator.symbol
        # Eén bron van waarheid voor de vraag of er echt geld omgaat: live
        # modus én poort open én schakelaar aan én de venue mag handelen.
        # Drie standen, niet twee. 'Geen geld' is niet hetzelfde als 'geen
        # orders': op een demo-account gaan er werkelijke orders naar de
        # broker, met echte fills en gemeten kosten. Dat verzwijgen zou de
        # indruk wekken dat er niets gebeurt.
        places_orders = bool(
            coordinator.mode.places_orders
            and coordinator.enabled
            and getattr(coordinator.venue, "supports_trading", False)
        )
        payload["uses_real_money"] = bool(
            coordinator.mode.uses_real_money
            and (coordinator.gate or {}).get("unlocked")
            and places_orders
        )
        payload["places_orders"] = places_orders
        payload["mode"] = coordinator.mode.value

        try:
            refresh = int(request.query.get("refresh", DEFAULT_REFRESH_SECONDS))
        except (TypeError, ValueError):
            refresh = DEFAULT_REFRESH_SECONDS

        html = await hass.async_add_executor_job(
            build_overview, payload, REPORT_URL, dt_util.DEFAULT_TIME_ZONE, refresh
        )
        return web.Response(
            text=html, content_type="text/html",
            headers={"Cache-Control": "no-store, must-revalidate"},
        )


def _pick_coordinator(hass: HomeAssistant, wanted: str | None):
    coordinators = list(hass.data.get(DOMAIN, {}).values())
    if not coordinators:
        return None
    return next(
        (c for c in coordinators if c.entry.entry_id == wanted), coordinators[0]
    )


class GoldScalperReportView(HomeAssistantView):
    """Bouwt het keuringsrapport bij elke aanvraag opnieuw."""

    url = REPORT_URL
    name = "api:gold_scalper:report"
    # Zie de moduletoelichting: een iframe kan geen token meesturen.
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        coordinators = list(hass.data.get(DOMAIN, {}).values())

        if not coordinators:
            return web.Response(
                text=_placeholder(
                    "Nog geen actieve configuratie",
                    "De integratie is geladen maar er is geen actieve entry. "
                    "Controleer Instellingen, Apparaten en diensten.",
                ),
                content_type="text/html",
            )

        # Meerdere entries: kies met ?entry=... , anders de eerste.
        wanted = request.query.get("entry")
        coordinator = next(
            (c for c in coordinators if c.entry.entry_id == wanted), coordinators[0]
        )

        if coordinator.db is None or coordinator.run_id is None:
            return web.Response(
                text=_placeholder(
                    "Database nog niet gereed",
                    "De integratie is aan het opstarten. Ververs over een halve minuut.",
                ),
                content_type="text/html",
            )

        from .dashboard.report import build_report

        try:
            refresh = int(request.query.get("refresh", DEFAULT_REFRESH_SECONDS))
        except (TypeError, ValueError):
            refresh = DEFAULT_REFRESH_SECONDS
        if refresh:
            refresh = max(MIN_REFRESH_SECONDS, refresh)

        try:
            from homeassistant.util import dt as dt_util

            html = await hass.async_add_executor_job(
                build_report, coordinator.db, coordinator.run_id,
                coordinator.gate, "Gold Scalper", dt_util.DEFAULT_TIME_ZONE,
                refresh, coordinator.conversion.as_dict(),
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Kon rapport niet bouwen")
            return web.Response(
                text=_placeholder("Rapport kon niet worden gebouwd", str(err)),
                content_type="text/html",
                status=500,
            )

        # Terugknop naar het overzicht. In een iframe is er geen adresbalk,
        # dus zonder deze link zit je vast op het rapport.
        back = (
            '<div style="max-width:1080px;margin:0 auto;padding:14px 22px 0">'
            f'<a href="{OVERVIEW_URL}" style="font:12px ui-monospace,monospace;'
            'color:#5A6156;text-decoration:none">&larr; Overzicht</a></div>'
        )
        html = html.replace('<div class="wrap">', back + '<div class="wrap">', 1)

        return web.Response(
            text=html,
            content_type="text/html",
            # Niet cachen: het rapport verandert elke handelscyclus.
            headers={"Cache-Control": "no-store, must-revalidate"},
        )


def broker_frontend_version(js_file: Path = BROKER_JS_FILE) -> str:
    """Integratieversie plus inhoudshash: elke wijziging geeft een nieuwe URL."""
    inhoud = Path(js_file).read_bytes()
    return f"{INTEGRATION_VERSION}-{hashlib.sha256(inhoud).hexdigest()[:12]}"


class GoldScalperBrokerView(HomeAssistantView):
    """Alleen-lezend JSON-model voor het broker-dashboard (1.8.0).

    Geauthenticeerd (``requires_auth``) en alleen voor beheerders, net als het
    paneel zelf. Geen schrijfacties: alleen ``GET``, en de database gaat open
    met ``mode=ro``.

    Efficiënt: het model wordt per coordinatorcyclus één keer gebouwd en
    daarna hergebruikt. Met ``?since=<sleutel>`` antwoordt de route met
    ``{"ongewijzigd": true}`` zolang er geen nieuwe cyclus was, zodat een
    paneel dat elke paar seconden vraagt vrijwel niets kost.
    """

    url = BROKER_DATA_URL
    name = "api:gold_scalper:broker"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._cache: dict[str, dict] = {}
        self._teller = 0

    async def get(self, request: web.Request) -> web.Response:
        user = request.get("hass_user")
        if user is None:
            return web.json_response({"error": "unauthorized"}, status=401, headers=_GEEN_CACHE)
        if not getattr(user, "is_admin", False):
            return web.json_response({"error": "forbidden"}, status=403, headers=_GEEN_CACHE)

        coordinator = _pick_coordinator(self._hass, request.query.get("entry"))
        if coordinator is None:
            return web.json_response(
                {"error": "no_entry"}, status=503, headers=_GEEN_CACHE)
        if not coordinator.data:
            return web.json_response(
                {"error": "starting"}, status=503, headers=_GEEN_CACHE)

        entry_id = coordinator.entry.entry_id
        cache = self._cache.get(entry_id)
        if (cache is None or cache["data"] is not coordinator.data
                or time.monotonic() - cache["gebouwd"] > BROKER_CACHE_MAX_SECONDS):
            payload = await self._bouw(coordinator)
            self._teller += 1
            payload["sleutel"] = f"{self._teller}"
            payload["entry"] = entry_id
            cache = {"data": coordinator.data, "payload": payload,
                     "gebouwd": time.monotonic()}
            self._cache[entry_id] = cache

        payload = cache["payload"]
        if request.query.get("since") == payload["sleutel"]:
            return web.json_response(
                {"api": payload["api"], "sleutel": payload["sleutel"], "ongewijzigd": True},
                headers=_GEEN_CACHE,
            )
        return web.json_response(payload, headers=_GEEN_CACHE)

    async def _bouw(self, coordinator) -> dict:
        from homeassistant.util import dt as dt_util

        from .dashboard.broker import build_payload, candles_slice, read_database
        from .status import build_status

        data = coordinator.data
        # Candles kopiëren in de event-loop: de coordinator voegt ze daar toe.
        candles = candles_slice(getattr(coordinator, "_candles", None))
        db_deel = None
        db = getattr(coordinator, "db", None)
        run_id = getattr(coordinator, "run_id", None)
        if db is not None and run_id is not None and getattr(db, "path", None):
            try:
                db_deel = await self._hass.async_add_executor_job(
                    read_database, db.path, run_id)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Broker-dashboard: database niet te lezen", exc_info=True)
        places_orders = bool(
            coordinator.mode.places_orders
            and coordinator.enabled
            and getattr(coordinator.venue, "supports_trading", False)
        )
        uses_real_money = bool(
            coordinator.mode.uses_real_money
            and (coordinator.gate or {}).get("unlocked")
            and places_orders
        )
        exits = getattr(getattr(coordinator, "exits", None), "config", None)
        exit_cfg = {
            k: getattr(exits, k, None)
            for k in ("time_stop_seconds", "time_stop_deadzone_atr", "max_hold_seconds")
        } if exits is not None else {}
        return build_payload(
            data,
            symbol=coordinator.symbol,
            timeframe=getattr(coordinator, "timeframe", None),
            candles=candles,
            db=db_deel,
            exit_cfg=exit_cfg,
            version=INTEGRATION_VERSION,
            status=build_status(data),
            places_orders=places_orders,
            uses_real_money=uses_real_money,
            tz=dt_util.DEFAULT_TIME_ZONE,
        )


def _placeholder(title: str, message: str) -> str:
    """Nette pagina voor de gevallen waarin er nog niets te tonen valt.

    Beter dan een lege iframe of een stacktrace: de gebruiker moet kunnen zien
    dát er iets werkt en wát er nog ontbreekt.
    """
    return f"""<!DOCTYPE html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gold Scalper</title><style>
body{{margin:0;background:#E4E7E2;color:#22271F;display:flex;align-items:center;
justify-content:center;min-height:100vh;
font:15px/1.6 ui-monospace,"SF Mono",Menlo,monospace}}
.box{{max-width:460px;padding:32px;border-left:3px solid #8F7334;background:#D5DAD3}}
h1{{margin:0 0 10px;font-size:13px;letter-spacing:.18em;text-transform:uppercase}}
p{{margin:0;color:#5A6156;font-size:13px}}
</style></head><body><div class="box">
<h1>{title}</h1><p>{message}</p></div></body></html>"""


async def async_register_frontend(hass: HomeAssistant, show_panel: bool = True) -> None:
    """Registreer de adressen en het menu-item. Veilig om vaker aan te roepen.

    1.8.0: het menu-item 'Gold Scalper' toont het broker-dashboard, een eigen
    webcomponent (``panel_custom``) in plaats van de iframe met het overzicht.
    Dezelfde zijbalk-ingang (``/gold-scalper``), dus geen handwerk. Het
    klassieke overzicht en het keuringsrapport blijven bereikbaar op hun
    eigen adres en zijn vanuit het dashboard gelinkt.
    """
    if not hass.data.get(f"{DOMAIN}_view_registered"):
        hass.http.register_view(GoldScalperOverviewView())
        hass.http.register_view(GoldScalperReportView())
        hass.data[f"{DOMAIN}_view_registered"] = True
        _LOGGER.debug("Rapport bereikbaar op %s", REPORT_URL)
    if not hass.data.get(f"{DOMAIN}_broker_registered"):
        hass.http.register_view(GoldScalperBrokerView(hass))
        await hass.http.async_register_static_paths(
            [StaticPathConfig(BROKER_STATIC_URL, str(BROKER_JS_FILE), True)]
        )
        hass.data[f"{DOMAIN}_broker_registered"] = True
    # 1.8.1: live koers voor het paneel (websocket-abonnement, alleen lezen).
    try:
        from .broker_stream import async_register_websocket

        async_register_websocket(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Live koers voor het dashboard niet beschikbaar; "
                        "het dashboard ververst elke 5 s", exc_info=True)

    if not show_panel:
        return

    from homeassistant.components import frontend, panel_custom

    if hass.data.get(f"{DOMAIN}_panel_registered"):
        return
    versie = await hass.async_add_executor_job(broker_frontend_version)
    kwargs = dict(
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=BROKER_WEBCOMPONENT,
        sidebar_title="Gold Scalper",
        sidebar_icon="mdi:gold",
        module_url=f"{BROKER_STATIC_URL}?v={versie}",
        embed_iframe=False,
        trust_external=False,
        require_admin=True,
        config={},
    )
    try:
        await panel_custom.async_register_panel(hass, **kwargs)
    except ValueError:
        # Een achtergebleven registratie (bijvoorbeeld de oude iframe of een
        # oude module-URL): vervangen, niet naast elkaar laten staan.
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        await panel_custom.async_register_panel(hass, **kwargs)
    hass.data[f"{DOMAIN}_panel_registered"] = True
    _LOGGER.info("Menu-item 'Gold Scalper' (broker-dashboard) in de zijbalk")


async def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Haal het menu-item weg als de laatste entry verdwijnt."""
    if len(hass.data.get(DOMAIN, {})) > 0:
        return
    if not hass.data.get(f"{DOMAIN}_panel_registered"):
        return
    from homeassistant.components import frontend

    frontend.async_remove_panel(hass, PANEL_URL_PATH)
    hass.data[f"{DOMAIN}_panel_registered"] = False
