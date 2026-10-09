"""Live koers voor het broker-dashboard via IG Lightstreamer (1.8.1, 1.8.2).

Alleen weergave. Deze module voedt niets in de handelslogica: geen import
vanuit de coordinator of de strategie, geen schrijfacties, geen orders. De
handel blijft op REST en op de bestaande cyclus. De stroom bestaat alleen
zolang er een paneel kijkt en kost geen IG-REST-verzoek: hij gebruikt de
tokens van de sessie die de cyclus toch al heeft.

Protocol: een eigen, minimale TLCP-client (Lightstreamer TLCP-2.1.0) over
**HTTP-streaming** met aiohttp, dat al in Home Assistant zit. Geen extra
afhankelijkheid. (1.8.1 gebruikte een websocket; IG sloot die zonder
antwoord, terwijl HTTP wel werkt. Daarom sinds 1.8.2 alleen HTTP.)

* ``POST /lightstreamer/create_session.txt?LS_protocol=TLCP-2.1.0`` met
  ``LS_user`` (account-ID) en ``LS_password`` (``CST-<cst>|XST-<xst>``) als
  formulier. Het antwoord is een stroom regels:
  ``CONOK,<sessie>,<limiet>,<keepalive>,<control-link>``, daarna ``PROBE``,
  ``SUBOK``, ``U``-regels enzovoort.
* ``POST /lightstreamer/control.txt?LS_protocol=TLCP-2.1.0`` met
  ``LS_session`` en ``LS_op=add`` voor één item ``MARKET:<epic>`` in
  MERGE-modus; het antwoord (``REQOK`` of ``REQERR``) staat in de body van
  dat verzoek, ``SUBOK`` komt op de stroom.
* ``LOOP``: de stroom is op (inhoudslengte bereikt); verder met
  ``POST /lightstreamer/bind_session.txt`` op dezelfde sessie. Het
  abonnement blijft bestaan.
* Updates ``U,<sub>,<item>,<v1>|<v2>|...`` met de TLCP-codering: leeg =
  ongewijzigd, ``#`` = null, ``$`` = lege tekst, ``^N`` = N velden
  ongewijzigd, verder procent-gecodeerd.
* ``CONERR``, ``REQERR``, ``ERROR`` en ``END``: fout of einde.

Wachtwoord en tokens komen nooit in een logregel: alleen serverregels en
HTTP-statussen worden gelogd.

Zuiver Python plus asyncio en (bij gebruik) aiohttp: geen Home
Assistant-imports, zodat parser, smoorklep en start/stop los te testen zijn.
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
#: Client-ID voor clients die niet van Lightstreamer zelf zijn, zoals de
#: TLCP-specificatie hem noemt.
LS_CID = "mgQkwtwdysogQz2BJ4Ji kOj2Bg"
#: Velden van het IG-item ``MARKET:<epic>``; volgorde = volgorde in elke update.
LS_MARKET_FIELDS = (
    "BID", "OFFER", "UPDATE_TIME", "CHANGE", "CHANGE_PCT", "HIGH", "LOW",
    "MARKET_STATE",
)
#: Te proberen IG-items, in volgorde (1.9.1). IG's live server antwoordde op
#: ``MARKET:<epic>`` met alle velden "REQERR 21 Invalid group"; dan volgen
#: minimale MARKET-velden, het chart-tick-item en de lopende 1-minuutcandle.
#: ``velden`` koppelt elk schemaveld aan een rol in het tickbericht.
LS_VARIANTEN: tuple[dict, ...] = (
    {"naam": "MARKET", "group": "MARKET:{epic}", "mode": "MERGE",
     "schema": LS_MARKET_FIELDS},
    {"naam": "MARKET-minimaal", "group": "MARKET:{epic}", "mode": "MERGE",
     "schema": ("BID", "OFFER", "UPDATE_TIME", "MARKET_STATE")},
    {"naam": "CHART-TICK", "group": "CHART:{epic}:TICK", "mode": "DISTINCT",
     "schema": ("BID", "OFR", "LTP", "UTM")},
    {"naam": "CHART-1MINUTE", "group": "CHART:{epic}:1MINUTE", "mode": "MERGE",
     "schema": ("BID_CLOSE", "OFR_CLOSE", "UTM", "CONS_END")},
)
#: REQERR-codes waarop de volgende variant geprobeerd wordt: 21 bad group,
#: 22 group niet bij dit schema, 23 bad schema, 24 modus niet toegestaan.
LS_VARIANT_CODES = frozenset({"21", "22", "23", "24"})
#: Rollen per veldnaam, over alle varianten heen.
_ROL = {
    "BID": "bied", "BID_CLOSE": "bied",
    "OFFER": "laat", "OFR": "laat", "OFR_CLOSE": "laat",
    "UPDATE_TIME": "tijdtekst", "UTM": "utm",
    "CHANGE": "verandering", "CHANGE_PCT": "pct", "HIGH": "hoog", "LOW": "laag",
    "MARKET_STATE": "markt",
}
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
#: Na een geweigerde inlog met dezelfde tokens toch weer eens proberen.
LS_AUTH_RETRY_SECONDS = 600
#: Hoe lang op verbinding, CONOK of SUBOK gewacht wordt.
LS_CONNECT_TIMEOUT = 15.0


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
    """Leesbare vorm van een verzoek (voor tests en nepservers)."""
    return f"{naam}\r\n{encode_params(params)}"


def base_url(endpoint: str) -> str:
    """``https://host[/]`` wordt ``https://host/lightstreamer``."""
    e = str(endpoint).strip().rstrip("/")
    if not e.startswith(("https://", "http://")):
        e = "https://" + e
    if not e.endswith("/lightstreamer"):
        e += "/lightstreamer"
    return e


def control_base(endpoint_base: str, link: str | None) -> str:
    """Adres voor control/bind: zelfde server, of de control-link uit CONOK."""
    if not link or link == "*":
        return endpoint_base
    schema = endpoint_base.split("://", 1)[0]
    return f"{schema}://{link.strip().rstrip('/')}/lightstreamer"


def create_session_params(creds: dict) -> dict[str, Any]:
    return {
        "LS_cid": LS_CID,
        "LS_user": creds["user"],
        "LS_password": creds["password"],
        "LS_keepalive_millis": LS_KEEPALIVE_MS,
        "LS_polling": "false",
    }


def subscribe_params(epic: str, req_id: int = 1, sub_id: int = 1,
                     variant: dict | None = None) -> dict[str, Any]:
    """Control-parameters voor een abonnement.

    Geen ``LS_data_adapter``: IG gebruikt de standaardadapter van de
    adapterset. ``:`` in de groep wordt bij het formulier-coderen ``%3A``;
    de server decodeert dat terug (TLCP: parameters zijn URL-gecodeerd).
    """
    v = variant or LS_VARIANTEN[0]
    return {
        "LS_reqId": req_id,
        "LS_op": "add",
        "LS_subId": sub_id,
        "LS_mode": v["mode"],
        "LS_group": v["group"].format(epic=epic),
        "LS_schema": " ".join(v["schema"]),
        "LS_snapshot": "true",
    }


def create_session_request(creds: dict) -> str:
    return build_request("create_session", create_session_params(creds))


def subscribe_request(epic: str, req_id: int = 1, sub_id: int = 1) -> str:
    return build_request("control", subscribe_params(epic, req_id, sub_id))


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


def _utm_tekst(ms) -> str | None:
    """IG-chartveld UTM (epoch in milliseconden) naar ``HH:MM:SS`` UTC."""
    f = _getal(ms)
    if f is None:
        return None
    try:
        return time.strftime("%H:%M:%S", time.gmtime(f / 1000.0))
    except (OverflowError, OSError, ValueError):
        return None


def tick_from_values(waarden: list[str | None], ontvangen: float,
                     schema: tuple[str, ...] = LS_MARKET_FIELDS) -> dict:
    """Veldwaarden van een IG-item naar het tickbericht voor het paneel.

    Werkt voor MARKET (BID/OFFER/UPDATE_TIME) en CHART (BID/OFR/UTM in
    epoch-ms, of BID_CLOSE/OFR_CLOSE).
    """
    v: dict[str, Any] = {}
    for naam, waarde in zip(schema, waarden):
        rol = _ROL.get(naam)
        if rol is not None:
            v[rol] = waarde
    bied, laat = _getal(v.get("bied")), _getal(v.get("laat"))
    mid = (bied + laat) / 2 if bied is not None and laat is not None else None
    return {
        "soort": "tick",
        "bied": bied,
        "laat": laat,
        "mid": round(mid, 4) if mid is not None else None,
        "spread": round(laat - bied, 4) if mid is not None else None,
        "verandering": _getal(v.get("verandering")),
        "pct": _getal(v.get("pct")),
        "hoog": _getal(v.get("hoog")),
        "laag": _getal(v.get("laag")),
        "markt": v.get("markt"),
        "broker_tijd": v.get("tijdtekst") or _utm_tekst(v.get("utm")),
        "tijd": round(ontvangen, 3),
    }


# ----------------------------------------------------------- transport -- #

class HttpStreamTransport:
    """TLCP over HTTP-streaming via een bestaande aiohttp-sessie (die van HA).

    ``create_session`` en ``rebind`` openen een stroom-antwoord dat regel
    voor regel gelezen wordt; ``control`` is een los, kort verzoek. Houdt de
    gegevens voor de diagnose bij: HTTP-status en de eerste serverregel.
    """

    naam = "http-streaming"

    def __init__(self, session, endpoint: str) -> None:
        self._session = session
        self._base = base_url(endpoint)
        self._control = self._base
        self._resp = None
        self._sessie: str | None = None
        self.http_status: int | None = None
        self.eerste_regel: str | None = None

    @staticmethod
    def _timeout():
        import aiohttp

        # Geen totale limiet: de stroom loopt lang. De stilte bewaakt
        # run_connection zelf (keepalive).
        return aiohttp.ClientTimeout(total=None, connect=LS_CONNECT_TIMEOUT,
                                     sock_connect=LS_CONNECT_TIMEOUT, sock_read=None)

    async def _post(self, url: str, params: dict[str, Any], *, stroom: bool):
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = await asyncio.wait_for(
            self._session.post(f"{url}?LS_protocol={LS_PROTOCOL}",
                               data=encode_params(params), headers=headers,
                               timeout=self._timeout()),
            LS_CONNECT_TIMEOUT,
        )
        if stroom:
            self.http_status = resp.status
        if resp.status != 200:
            try:
                tekst = (await asyncio.wait_for(resp.text(), 5))[:200]
            except Exception:  # noqa: BLE001
                tekst = ""
            resp.release()
            regel = tekst.strip().splitlines()[0] if tekst.strip() else ""
            if stroom and self.eerste_regel is None:
                self.eerste_regel = regel or None
            raise TlcpError("HTTP", str(resp.status), regel)
        return resp

    async def _sluit_stroom(self) -> None:
        resp, self._resp = self._resp, None
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Koersstroom: sluiten mislukte", exc_info=True)

    async def create_session(self, params: dict[str, Any]) -> None:
        self._resp = await self._post(f"{self._base}/create_session.txt", params, stroom=True)

    def bound(self, sessie: str, link: str | None) -> None:
        """CONOK ontvangen: sessie-ID en control-adres onthouden."""
        self._sessie = sessie
        self._control = control_base(self._base, link)

    async def control(self, params: dict[str, Any]) -> str | None:
        """Control-verzoek op de sessie; geeft de antwoordregel (REQOK/REQERR)."""
        resp = await self._post(f"{self._control}/control.txt",
                                {**params, "LS_session": self._sessie}, stroom=False)
        try:
            tekst = await asyncio.wait_for(resp.text(), LS_CONNECT_TIMEOUT)
        finally:
            resp.release()
        regels = [r for r in tekst.splitlines() if r.strip()]
        return regels[0] if regels else None

    async def rebind(self) -> None:
        """Na LOOP: nieuwe stroom op dezelfde sessie."""
        await self._sluit_stroom()
        self._resp = await self._post(
            f"{self._control}/bind_session.txt",
            {"LS_session": self._sessie, "LS_keepalive_millis": LS_KEEPALIVE_MS,
             "LS_polling": "false"},
            stroom=True,
        )

    async def receive(self, timeout: float) -> str | None:
        """Eén regel, of None als de stroom op is. TimeoutError bij stilte."""
        if self._resp is None:
            return None
        while True:
            ruw = await asyncio.wait_for(self._resp.content.readline(), timeout)
            if not ruw:
                return None
            regel = ruw.decode("utf-8", "replace").rstrip("\r\n")
            if not regel:
                continue
            if self.eerste_regel is None:
                self.eerste_regel = regel[:200]
            return regel

    def diagnose(self) -> str:
        delen = [f"transport {self.naam}"]
        if self.http_status is not None:
            delen.append(f"HTTP {self.http_status}")
        delen.append(f"eerste serverregel: {self.eerste_regel!r}"
                     if self.eerste_regel else "geen serverregel ontvangen")
        return ", ".join(delen)

    async def close(self) -> None:
        await self._sluit_stroom()


# ------------------------------------------------------------ verbinding -- #

def _fout_uit(soort: str, args: list[str]) -> TlcpError:
    if soort == "REQERR":
        return TlcpError(soort, args[1] if len(args) > 1 else "",
                         unquote(args[2]) if len(args) > 2 else "")
    return TlcpError(soort, args[0] if args else "",
                     unquote(args[1]) if len(args) > 1 else "")


def _variant_volgorde(start: int) -> list[int]:
    """Eerst de variant die eerder werkte, daarna de rest in vaste volgorde."""
    start = start if 0 <= start < len(LS_VARIANTEN) else 0
    return [start] + [i for i in range(len(LS_VARIANTEN)) if i != start]


async def run_connection(
    transport, creds: dict, on_tick: Callable[[dict], None],
    on_live: Callable[[], None], *, clock: Callable[[], float] = time.time,
    verouderd: Callable[[], bool] | None = None,
    variant: int = 0, on_variant: Callable[[int], None] | None = None,
) -> str:
    """Eén TLCP-sessie over een transport, tot die eindigt.

    Abonneert op de IG-items uit ``LS_VARIANTEN``, te beginnen bij
    ``variant``; bij REQERR 21-24 volgt de volgende. ``on_variant(i)`` meldt
    welke werd geaccepteerd (REQOK). Weigert IG ze allemaal, dan een
    ``TlcpError`` met de code per variant.

    ``LOOP`` wordt binnen de sessie afgehandeld (``rebind``). Geeft
    ``"vernieuwd"`` terug als de IG-sessie intussen nieuwe tokens heeft
    (``verouderd()`` is waar; bekeken bij elke serverregel, dus minstens elke
    keepalive). Elke andere afloop is een uitzondering.
    """
    await transport.create_session(create_session_params(creds))
    wacht = LS_CONNECT_TIMEOUT
    live = False
    geabonneerd = False
    volgorde = _variant_volgorde(variant)
    poging = -1                 # index in volgorde
    req_id = 0
    sub_id = 0
    actief: dict | None = None
    item: ItemState | None = None
    geweigerd: list[str] = []

    async def abonneer_volgende() -> None:
        """Volgende variant proberen; REQERR 21-24 in het antwoord: door."""
        nonlocal poging, req_id, sub_id, actief, item
        while True:
            poging += 1
            if poging >= len(volgorde):
                raise TlcpError("REQERR", "alle",
                                "geen IG-item geaccepteerd: " + "; ".join(geweigerd))
            v = LS_VARIANTEN[volgorde[poging]]
            req_id += 1
            sub_id += 1
            actief = v
            item = ItemState(len(v["schema"]))
            antwoord = await transport.control(
                subscribe_params(creds["epic"], req_id, sub_id, v))
            if not antwoord:
                return              # antwoord komt op de stroom
            _LOGGER.debug("Koersstroom control (%s) <- %s", v["naam"], antwoord[:200])
            a_soort, a_args = parse_message(antwoord)
            if a_soort == "REQERR":
                fout = _fout_uit(a_soort, a_args)
                if fout.code in LS_VARIANT_CODES:
                    geweigerd.append(f"{v['naam']} REQERR {fout.code} {fout.tekst}".strip())
                    continue
                raise fout
            if a_soort in ("ERROR", "CONERR"):
                raise _fout_uit(a_soort, a_args)
            if a_soort == "REQOK" and on_variant is not None:
                on_variant(volgorde[poging])
            return

    while True:
        try:
            regel = await transport.receive(wacht)
        except (TimeoutError, asyncio.TimeoutError) as err:
            raise TlcpError("TIMEOUT", "", f"{wacht:.0f} s niets ontvangen") from err
        if regel is None:
            raise TlcpError("GESLOTEN", "", "verbinding verbroken door de server")
        _LOGGER.debug("Koersstroom <- %s", regel[:200])
        if live and verouderd is not None and verouderd():
            return "vernieuwd"
        soort, args = parse_message(regel)
        if soort == "CONOK":
            try:
                keepalive = int(args[2]) / 1000.0
            except (IndexError, ValueError):
                keepalive = LS_KEEPALIVE_MS / 1000.0
            wacht = max(LS_CONNECT_TIMEOUT, keepalive * 2 + 5)
            transport.bound(args[0] if args else "", args[3] if len(args) > 3 else None)
            if not geabonneerd:
                geabonneerd = True
                await abonneer_volgende()
        elif soort == "SUBOK":
            if args and args[0] == str(sub_id) and not live:
                live = True
                if on_variant is not None:
                    on_variant(volgorde[poging])
                on_live()
        elif soort == "U":
            if (len(args) == 3 and args[0] == str(sub_id) and args[1] == "1"
                    and item is not None and actief is not None):
                waarden = item.apply(args[2])
                on_tick(tick_from_values(waarden, clock(), actief["schema"]))
        elif soort == "LOOP":
            await transport.rebind()
            wacht = LS_CONNECT_TIMEOUT
        elif soort == "REQERR":
            fout = _fout_uit(soort, args)
            # REQERR op de stroom (niet via HTTP-control): zelfde terugval.
            if (not live and args and args[0] == str(req_id)
                    and fout.code in LS_VARIANT_CODES and actief is not None):
                geweigerd.append(f"{actief['naam']} REQERR {fout.code} {fout.tekst}".strip())
                await abonneer_volgende()
                continue
            raise fout
        elif soort in ("CONERR", "END", "ERROR"):
            raise _fout_uit(soort, args)
        elif soort == "UNSUB":
            if args and args[0] != str(sub_id):
                continue
            raise TlcpError(soort, "", "abonnement door de server beëindigd")
        # SERVNAME, CLIENTIP, CONS, PROBE, NOOP, SYNC, PROG, REQOK, CONF,
        # MSGDONE, EOS, CS, OV: geen actie nodig.


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
        #: Index in LS_VARIANTEN die IG het laatst accepteerde (1.9.1).
        self.variant = 0

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
                transport = await self._open_transport(creds["endpoint"])
                uitkomst = await run_connection(
                    transport, creds, self._op_tick, self._bij_live,
                    clock=self._clock, verouderd=verouderd,
                    variant=self.variant, on_variant=self._zet_variant)
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
            tekst = (
                f"{type(fout).__name__}: {fout}" if fout is not None
                else "verbinding beëindigd"
            )
            diagnose = getattr(transport, "diagnose", None)
            if callable(diagnose):
                try:
                    tekst = f"{tekst}; {diagnose()}"
                except Exception:  # noqa: BLE001
                    pass
            self._waarschuw(tekst)
            self._zet_status("terugval", tekst[:200])
            wacht = LS_BACKOFF_SECONDS[min(pogingen, len(LS_BACKOFF_SECONDS) - 1)]
            if geweigerd is not None:
                wacht = max(wacht, LS_AUTH_WAIT_SECONDS)
            pogingen += 1
            await asyncio.sleep(wacht)

    def _zet_variant(self, index: int) -> None:
        if index != self.variant:
            _LOGGER.debug("%s: koersstroom gebruikt IG-item %s", self._naam,
                          LS_VARIANTEN[index]["naam"])
        self.variant = index

    def _bij_live(self) -> None:
        self._zet_status("live", None)
