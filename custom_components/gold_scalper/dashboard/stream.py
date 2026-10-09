"""Live koers voor het broker-dashboard via IG Lightstreamer (1.8.1).

Alleen weergave. Deze module voedt niets in de handelslogica: geen import
vanuit de coordinator of de strategie, geen schrijfacties, geen orders. De
handel blijft op REST en op de bestaande cyclus. De stroom bestaat alleen
zolang er een paneel kijkt en kost geen REST-verzoek: hij gebruikt de tokens
van de sessie die de cyclus toch al heeft.

Protocol: een eigen, minimale TLCP-client (Lightstreamer TLCP-2.1.0) over een
websocket van aiohttp, dat al in Home Assistant zit. Geen extra afhankelijkheid.
Wat er gebruikt wordt, is klein:

* ``wsok`` en het antwoord ``WSOK`` (controle dat de websocket TLCP spreekt);
* ``create_session`` met ``LS_user`` (account-ID) en ``LS_password``
  (``CST-<cst>|XST-<xst>``), antwoord ``CONOK,<sessie>,<limiet>,<keepalive>,<link>``;
* ``control`` met ``LS_op=add`` voor één item ``MARKET:<epic>`` in MERGE-modus,
  antwoord ``REQOK`` en ``SUBOK``;
* updates ``U,<sub>,<item>,<v1>|<v2>|...`` met de TLCP-codering: leeg =
  ongewijzigd, ``#`` = null, ``$`` = lege tekst, ``^N`` = N velden ongewijzigd,
  verder procent-gecodeerd;
* ``PROBE`` (keepalive), ``LOOP`` (opnieuw verbinden), ``CONERR``, ``REQERR``,
  ``ERROR`` en ``END`` (fout of einde).

Zuiver Python plus asyncio en (optioneel) aiohttp: geen Home Assistant-imports,
zodat de parser, de smoorklep en het start/stop-gedrag los te testen zijn.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, unquote

_LOGGER = logging.getLogger(__name__)

LS_PROTOCOL = "TLCP-2.1.0"
LS_WS_SUBPROTOCOL = f"{LS_PROTOCOL}.lightstreamer.com"
#: Client-ID voor clients die niet van Lightstreamer zelf zijn, zoals de
#: TLCP-specificatie hem noemt.
LS_CID = "mgQkwtwdysogQz2BJ4Ji kOj2Bg"
#: Velden van het IG-item ``MARKET:<epic>``; volgorde = volgorde in elke update.
LS_MARKET_FIELDS = (
    "BID", "OFFER", "UPDATE_TIME", "CHANGE", "CHANGE_PCT", "HIGH", "LOW",
    "MARKET_STATE",
)
#: Gevraagde keepalive; de server mag een andere kiezen (staat in CONOK).
LS_KEEPALIVE_MS = 5000
#: Maximaal zoveel koersen per seconde naar het paneel (smoren).
LS_MAX_PER_SECOND = 4
#: Zo lang blijft de stroom open nadat het laatste paneel sloot.
LS_LINGER_SECONDS = 60
#: Wachttijden tussen pogingen na een fout, oplopend.
LS_BACKOFF_SECONDS = (2, 5, 15, 30, 60, 120)
#: Na een geweigerde inlog: wachten tot de cyclus nieuwe tokens heeft, maar
#: minstens zo lang.
LS_AUTH_WAIT_SECONDS = 120
#: Hoe lang op CONOK of SUBOK gewacht wordt.
LS_CONNECT_TIMEOUT = 15.0

#: Na een geweigerde inlog met dezelfde tokens toch weer eens proberen.
LS_AUTH_RETRY_SECONDS = 600


class TlcpError(Exception):
    """Fout gemeld door de Lightstreamer-server, of een protocolfout."""

    def __init__(self, soort: str, code: str = "", tekst: str = "") -> None:
        super().__init__(f"{soort} {code} {tekst}".strip())
        self.soort = soort
        self.code = code
        self.tekst = tekst

    @property
    def auth(self) -> bool:
        """Weigering op de inloggegevens.

        TLCP-code 1 is "user/password check failed"; codes van 0 en lager
        komen van de metadata-adapter van IG (bijv. een verlopen token).
        """
        if self.soort != "CONERR":
            return False
        try:
            return int(self.code) <= 1
        except ValueError:
            return False


# ------------------------------------------------------------ protocol -- #

def encode_params(params: dict[str, Any]) -> str:
    """``k=v&k=v`` met procent-codering; spatie wordt ``%20``, niet ``+``."""
    return "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())


def build_request(naam: str, params: dict[str, Any]) -> str:
    """Eén TLCP-verzoek zoals het over een websocket gaat."""
    return f"{naam}\r\n{encode_params(params)}"


def ws_url(endpoint: str) -> str:
    """``https://host`` wordt ``wss://host/lightstreamer``."""
    e = str(endpoint).strip().rstrip("/")
    if e.startswith("https://"):
        e = "wss://" + e[len("https://"):]
    elif e.startswith("http://"):
        e = "ws://" + e[len("http://"):]
    elif not e.startswith(("ws://", "wss://")):
        e = "wss://" + e
    return e + "/lightstreamer"


def create_session_request(creds: dict) -> str:
    return build_request("create_session", {
        "LS_cid": LS_CID,
        "LS_user": creds["user"],
        "LS_password": creds["password"],
        "LS_keepalive_millis": LS_KEEPALIVE_MS,
    })


def subscribe_request(epic: str, req_id: int = 1, sub_id: int = 1) -> str:
    return build_request("control", {
        "LS_reqId": req_id,
        "LS_op": "add",
        "LS_subId": sub_id,
        "LS_mode": "MERGE",
        "LS_group": f"MARKET:{epic}",
        "LS_schema": " ".join(LS_MARKET_FIELDS),
        "LS_snapshot": "true",
    })


def parse_message(regel: str) -> tuple[str, list[str]]:
    """Splits een serverregel in soort en argumenten.

    Bij ``U`` blijft het laatste argument (de waarden) heel; bij foutberichten
    blijft de tekst heel, ook als er komma's in staan.
    """
    regel = regel.rstrip("\r\n")
    soort, _, rest = regel.partition(",")
    if not rest:
        return soort, []
    maxdelen = {"U": 2, "CONERR": 1, "END": 1, "REQERR": 2, "ERROR": 1}.get(soort)
    if maxdelen is None:
        return soort, rest.split(",")
    return soort, rest.split(",", maxdelen)


def decode_value(raw: str) -> str | None:
    """Eén veldwaarde (zonder de 'ongewijzigd'-gevallen)."""
    if raw == "#":
        return None
    if raw == "$":
        return ""
    return unquote(raw)


class ItemState:
    """Huidige veldwaarden van één item; past updates toe."""

    def __init__(self, aantal: int) -> None:
        self.waarden: list[str | None] = [None] * aantal

    def apply(self, raw: str) -> list[str | None]:
        i = 0
        for deel in raw.split("|"):
            if i >= len(self.waarden):
                break
            if deel == "":
                i += 1                      # ongewijzigd
            elif deel.startswith("^") and deel[1:].isdigit():
                i += int(deel[1:])          # N velden ongewijzigd
            elif deel.startswith("^"):
                i += 1                      # diff-formaat: niet gevraagd, negeren
            else:
                self.waarden[i] = decode_value(deel)
                i += 1
        return list(self.waarden)


def _getal(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def tick_from_values(waarden: list[str | None], ontvangen: float) -> dict:
    """Veldwaarden van ``MARKET:<epic>`` naar het tickbericht voor het paneel."""
    v = dict(zip(LS_MARKET_FIELDS, waarden))
    bied, laat = _getal(v.get("BID")), _getal(v.get("OFFER"))
    mid = (bied + laat) / 2 if bied is not None and laat is not None else None
    return {
        "soort": "tick",
        "bied": bied,
        "laat": laat,
        "mid": round(mid, 4) if mid is not None else None,
        "spread": round(laat - bied, 4) if mid is not None else None,
        "verandering": _getal(v.get("CHANGE")),
        "pct": _getal(v.get("CHANGE_PCT")),
        "hoog": _getal(v.get("HIGH")),
        "laag": _getal(v.get("LOW")),
        "markt": v.get("MARKET_STATE"),
        "broker_tijd": v.get("UPDATE_TIME"),
        "tijd": round(ontvangen, 3),
    }


# ----------------------------------------------------------- transport -- #

class AiohttpWsTransport:
    """Websocket via een bestaande aiohttp-sessie (die van Home Assistant)."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self._buffer: list[str] = []

    @classmethod
    async def open(cls, session, url: str) -> AiohttpWsTransport:
        ws = await asyncio.wait_for(
            session.ws_connect(url, protocols=(LS_WS_SUBPROTOCOL,), autoping=True),
            LS_CONNECT_TIMEOUT,
        )
        if getattr(ws, "protocol", None) != LS_WS_SUBPROTOCOL:
            _LOGGER.debug("Koersstroom: server koos subprotocol %r",
                          getattr(ws, "protocol", None))
        return cls(ws)

    async def send(self, tekst: str) -> None:
        await self._ws.send_str(tekst)

    async def receive(self, timeout: float) -> str | None:
        """Eén regel, of None als de verbinding dicht is. TimeoutError bij stilte."""
        import aiohttp

        while not self._buffer:
            msg = await asyncio.wait_for(self._ws.receive(timeout), timeout + 1)
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._buffer.extend(r for r in msg.data.split("\r\n") if r)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                tekst = msg.data.decode("utf-8", "replace")
                self._buffer.extend(r for r in tekst.split("\r\n") if r)
            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING,
                              aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                return None
        return self._buffer.pop(0)

    async def close(self) -> None:
        try:
            await self._ws.close()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Koersstroom: sluiten mislukte", exc_info=True)


# ------------------------------------------------------------ verbinding -- #

async def run_connection(
    transport, creds: dict, on_tick: Callable[[dict], None],
    on_live: Callable[[], None], *, clock: Callable[[], float] = time.time,
    verouderd: Callable[[], bool] | None = None,
) -> str:
    """Eén TLCP-sessie over een open transport, tot die eindigt.

    Geeft ``"loop"`` terug als de server vraagt opnieuw te verbinden en
    ``"vernieuwd"`` als de IG-sessie intussen nieuwe tokens heeft
    (``verouderd()`` is waar; wordt bij elke serverregel bekeken, dus
    minstens elke keepalive). Elke andere afloop is een uitzondering.
    """
    await transport.send("wsok")
    await transport.send(create_session_request(creds))
    item = ItemState(len(LS_MARKET_FIELDS))
    wacht = LS_CONNECT_TIMEOUT
    live = False
    while True:
        try:
            regel = await transport.receive(wacht)
        except (TimeoutError, asyncio.TimeoutError) as err:
            raise TlcpError("TIMEOUT", "", f"{wacht:.0f} s niets ontvangen") from err
        if regel is None:
            raise TlcpError("GESLOTEN", "", "verbinding verbroken door de server")
        if live and verouderd is not None and verouderd():
            return "vernieuwd"
        soort, args = parse_message(regel)
        if soort == "CONOK":
            try:
                keepalive = int(args[2]) / 1000.0
            except (IndexError, ValueError):
                keepalive = LS_KEEPALIVE_MS / 1000.0
            wacht = max(LS_CONNECT_TIMEOUT, keepalive * 2 + 5)
            await transport.send(subscribe_request(creds["epic"]))
        elif soort == "SUBOK":
            if not live:
                live = True
                on_live()
        elif soort == "U":
            if len(args) == 3 and args[1] == "1":
                waarden = item.apply(args[2])
                on_tick(tick_from_values(waarden, clock()))
        elif soort == "LOOP":
            return "loop"
        elif soort in ("CONERR", "END", "ERROR"):
            raise TlcpError(soort, args[0] if args else "", unquote(args[1]) if len(args) > 1 else "")
        elif soort == "REQERR":
            raise TlcpError(soort, args[1] if len(args) > 1 else "", unquote(args[2]) if len(args) > 2 else "")
        elif soort == "UNSUB":
            raise TlcpError(soort, "", "abonnement door de server beëindigd")
        # WSOK, SERVNAME, CLIENTIP, CONS, PROBE, NOOP, SYNC, PROG, REQOK,
        # CONF, MSGDONE, EOS, CS, OV: geen actie nodig.


# --------------------------------------------------------------- beheer -- #

class PriceStream:
    """Beheert één koersstroom per configuratie, alleen zolang er kijkers zijn.

    * Eerste abonnee: de stroom start (achtergrondtaak).
    * Laatste abonnee weg: na ``LS_LINGER_SECONDS`` stopt hij.
    * Fout: status ``terugval`` naar de panelen (die blijven op de 5-s-poll),
      één WARNING per kijkperiode, opnieuw proberen met oplopende wachttijd.
    * Koersen naar de panelen hooguit ``LS_MAX_PER_SECOND`` per seconde; de
      laatste koers gaat altijd mee.
    """

    def __init__(
        self,
        credentials: Callable[[], dict | None],
        open_transport: Callable[[str], Any],
        *,
        create_task: Callable[[Any], asyncio.Task] | None = None,
        clock: Callable[[], float] = time.time,
        naam: str = "Gold Scalper",
    ) -> None:
        self._credentials = credentials
        self._open_transport = open_transport
        self._create_task = create_task or asyncio.ensure_future
        self._clock = clock
        self._naam = naam
        self._abonnees: dict[int, Callable[[dict], None]] = {}
        self._volgnummer = 0
        self._taak: asyncio.Task | None = None
        self._stop_handle: asyncio.TimerHandle | None = None
        self._emit_handle: asyncio.TimerHandle | None = None
        self._laatste_emit = 0.0
        self._laatste_tick: dict | None = None
        self._uitgezonden_tick: dict | None = None
        self._status: dict = {"soort": "status", "status": "uit", "reden": None}
        self._gewaarschuwd = False
        self.verbindingen = 0

    # -- abonnees ----------------------------------------------------------- #
    @property
    def status(self) -> str:
        return self._status["status"]

    @property
    def actief(self) -> bool:
        return self._taak is not None and not self._taak.done()

    def subscribe(self, callback: Callable[[dict], None]) -> Callable[[], None]:
        self._volgnummer += 1
        sleutel = self._volgnummer
        self._abonnees[sleutel] = callback
        if self._stop_handle is not None:
            self._stop_handle.cancel()
            self._stop_handle = None
        if not self.actief:
            self._gewaarschuwd = False
            self._zet_status("verbinden", None)
            self._taak = self._create_task(self._run())

        def afmelden() -> None:
            if self._abonnees.pop(sleutel, None) is not None and not self._abonnees:
                self._plan_stop()

        return afmelden

    def replay(self, callback: Callable[[dict], None]) -> None:
        """Huidige status en (verse) laatste koers naar één nieuwe kijker."""
        self._veilig(callback, dict(self._status))
        t = self._laatste_tick
        if t and self.status == "live" and self._clock() - (t.get("tijd") or 0) < 30:
            self._veilig(callback, dict(t))

    def _plan_stop(self) -> None:
        if self._stop_handle is not None:
            return
        loop = asyncio.get_running_loop()
        self._stop_handle = loop.call_later(LS_LINGER_SECONDS, self._stop_nu)

    def _stop_nu(self) -> None:
        self._stop_handle = None
        if self._abonnees:
            return
        self._annuleer()
        self._zet_status("uit", None)

    def _annuleer(self) -> None:
        if self._emit_handle is not None:
            self._emit_handle.cancel()
            self._emit_handle = None
        if self._taak is not None and not self._taak.done():
            self._taak.cancel()
        self._taak = None

    async def async_stop(self) -> None:
        """Netjes stoppen bij unload of afsluiten."""
        if self._stop_handle is not None:
            self._stop_handle.cancel()
            self._stop_handle = None
        taak = self._taak
        self._zet_status("uit", "gestopt")
        self._annuleer()
        self._abonnees.clear()
        if taak is not None:
            try:
                await taak
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # -- uitzenden ------------------------------------------------------------ #
    @staticmethod
    def _veilig(callback, bericht: dict) -> None:
        try:
            callback(bericht)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Koersstroom: doorgeven aan paneel mislukte", exc_info=True)

    def _zend(self, bericht: dict) -> None:
        for callback in list(self._abonnees.values()):
            self._veilig(callback, bericht)

    def _zet_status(self, status: str, reden: str | None) -> None:
        if self._status["status"] == status and self._status["reden"] == reden:
            return
        self._status = {"soort": "status", "status": status, "reden": reden}
        self._zend(dict(self._status))

    def _op_tick(self, tick: dict) -> None:
        """Smoorklep: hooguit LS_MAX_PER_SECOND per seconde, laatste wint."""
        self._laatste_tick = tick
        if self._emit_handle is not None:
            return
        loop = asyncio.get_running_loop()
        interval = 1.0 / LS_MAX_PER_SECOND
        wacht = self._laatste_emit + interval - loop.time()
        if wacht <= 0:
            self._emit()
        else:
            self._emit_handle = loop.call_later(wacht, self._emit)

    def _emit(self) -> None:
        self._emit_handle = None
        tick = self._laatste_tick
        if tick is None or tick is self._uitgezonden_tick:
            return
        self._laatste_emit = asyncio.get_running_loop().time()
        self._uitgezonden_tick = tick
        self._zend(dict(tick))

    # -- verbinding ----------------------------------------------------------- #
    def _waarschuw(self, tekst: str) -> None:
        if not self._gewaarschuwd:
            self._gewaarschuwd = True
            _LOGGER.warning(
                "%s: live koers via IG-streaming niet beschikbaar (%s); het "
                "dashboard ververst elke 5 s. Geen invloed op de handel.",
                self._naam, tekst,
            )
        else:
            _LOGGER.debug("%s: koersstroom opnieuw mislukt: %s", self._naam, tekst)

    async def _run(self) -> None:
        pogingen = 0
        geweigerd: tuple[Any, float] | None = None   # (generatie, moment)
        while True:
            creds = self._credentials()
            if not creds:
                # Nog geen IG-sessie: wachten op de gewone cyclus. Geen
                # eigen inlog, dus geen extra REST-verzoek.
                if self.status != "terugval":
                    self._zet_status("verbinden", "wacht op IG-sessie")
                await asyncio.sleep(10)
                continue
            generatie = creds.get("generatie")
            if geweigerd is not None:
                # Zelfde tokens als bij de weigering: wachten tot de cyclus
                # opnieuw heeft ingelogd (of heel lang niets veranderde).
                if (generatie == geweigerd[0]
                        and self._clock() - geweigerd[1] < LS_AUTH_RETRY_SECONDS):
                    await asyncio.sleep(15)
                    continue
                geweigerd = None
            transport = None
            uitkomst = None
            fout = None

            def verouderd(_gen=generatie) -> bool:
                nieuw = self._credentials()
                return bool(nieuw) and nieuw.get("generatie") != _gen

            try:
                self.verbindingen += 1
                transport = await self._open_transport(ws_url(creds["endpoint"]))
                uitkomst = await run_connection(
                    transport, creds, self._op_tick, self._bij_live,
                    clock=self._clock, verouderd=verouderd)
            except asyncio.CancelledError:
                raise
            except TlcpError as err:
                fout = err
                if err.auth:
                    geweigerd = (generatie, self._clock())
            except Exception as err:  # noqa: BLE001
                fout = err
            finally:
                if transport is not None:
                    await transport.close()
            if self.status == "live":
                pogingen = 0
            if fout is None and uitkomst == "vernieuwd":
                _LOGGER.debug("%s: koersstroom opnieuw met nieuwe IG-tokens", self._naam)
                continue
            if fout is None and uitkomst == "loop":
                await asyncio.sleep(1)
                continue
            tekst = (
                f"{type(fout).__name__}: {fout}" if fout is not None
                else "verbinding beëindigd"
            )
            self._waarschuw(tekst)
            self._zet_status("terugval", tekst[:160])
            wacht = LS_BACKOFF_SECONDS[min(pogingen, len(LS_BACKOFF_SECONDS) - 1)]
            if geweigerd is not None:
                wacht = max(wacht, LS_AUTH_WAIT_SECONDS)
            pogingen += 1
            await asyncio.sleep(wacht)

    def _bij_live(self) -> None:
        self._zet_status("live", None)
