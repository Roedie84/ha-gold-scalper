"""Websocket-abonnement voor de live koers op het broker-dashboard (1.8.1).

Het paneel abonneert zich met ``gold_scalper/broker_stream`` via de bestaande
websocket van de Home Assistant-frontend. Alleen beheerders, net als de
route ``/api/gold_scalper/broker``. Er is geen schrijfactie: het commando geeft
alleen koersen en een status door.

Alleen weergave. De koersstroom (``dashboard/stream.py``) wordt hier per
configuratie bewaard in ``hass.data`` en door niets in de coordinator of de
strategie gelezen. De handel blijft op REST en op de bestaande cyclus.

Beschikbaar met IG als broker in demo- of live-modus. In papiermodus, of met
een andere databron, antwoordt het commando met ``not_supported`` en blijft
het paneel op de 5-s-poll.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STREAM_COMMAND = "gold_scalper/broker_stream"
STREAMS_KEY = f"{DOMAIN}_streams"
_WS_REGISTERED_KEY = f"{DOMAIN}_ws_registered"


def stream_eligibility(coordinator) -> tuple[bool, str]:
    """(beschikbaar, reden). Alleen IG, alleen demo of live."""
    venue = getattr(coordinator, "venue", None)
    if getattr(venue, "name", None) != "ig" or not hasattr(venue, "streaming_credentials"):
        return False, "live koers alleen met IG als broker"
    mode = getattr(getattr(coordinator, "mode", None), "value", None)
    if mode not in ("demo", "live"):
        return False, "live koers alleen in demo- of live-modus, niet op papier"
    return True, ""


def _get_stream(hass: HomeAssistant, coordinator):
    from .dashboard.stream import HttpStreamTransport, PriceStream

    streams = hass.data.setdefault(STREAMS_KEY, {})
    entry_id = coordinator.entry.entry_id
    stream = streams.get(entry_id)
    if stream is not None:
        return stream

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    venue = coordinator.venue

    async def _open(endpoint: str):
        # 1.8.2: HTTP-streaming; IG sloot de websocket zonder antwoord.
        return HttpStreamTransport(session, endpoint)

    def _taak(coro):
        return hass.async_create_background_task(
            coro, f"{DOMAIN} koersstroom {entry_id}")

    stream = PriceStream(venue.streaming_credentials, _open, create_task=_taak)
    streams[entry_id] = stream
    return stream


def handle_broker_stream(hass: HomeAssistant, connection, msg: dict) -> None:
    """Websocket-commando; synchroon, zoals HA een ``callback`` aanroept."""
    msg_id = msg["id"]
    user = getattr(connection, "user", None)
    if user is None or not getattr(user, "is_admin", False):
        connection.send_error(msg_id, "unauthorized", "Alleen voor beheerders")
        return

    from .http import _pick_coordinator

    coordinator = _pick_coordinator(hass, msg.get("entry"))
    if coordinator is None:
        connection.send_error(msg_id, "not_found", "Geen actieve Gold Scalper-configuratie")
        return
    beschikbaar, reden = stream_eligibility(coordinator)
    if not beschikbaar:
        connection.send_error(msg_id, "not_supported", reden)
        return

    stream = _get_stream(hass, coordinator)

    def doorgeven(bericht: dict) -> None:
        connection.send_message({"id": msg_id, "type": "event", "event": bericht})

    connection.subscriptions[msg_id] = stream.subscribe(doorgeven)
    connection.send_result(msg_id)
    stream.replay(doorgeven)


def async_register_websocket(hass: HomeAssistant) -> None:
    """Registreer het commando eenmaal per Home Assistant."""
    if hass.data.get(_WS_REGISTERED_KEY):
        return
    import voluptuous as vol
    from homeassistant.components import websocket_api
    from homeassistant.core import callback

    schema = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend({
        vol.Required("type"): STREAM_COMMAND,
        vol.Optional("entry"): str,
    })
    websocket_api.async_register_command(
        hass, STREAM_COMMAND, callback(handle_broker_stream), schema)
    hass.data[_WS_REGISTERED_KEY] = True


async def async_stop_stream(hass: HomeAssistant, entry_id: str) -> None:
    """Stop en vergeet de koersstroom van één configuratie (unload/afsluiten)."""
    stream = hass.data.get(STREAMS_KEY, {}).pop(entry_id, None)
    if stream is None:
        return
    try:
        await stream.async_stop()
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Koersstroom stoppen mislukte", exc_info=True)
