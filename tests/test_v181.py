"""1.8.1 - live koers op het broker-dashboard via IG-streaming (Lightstreamer).

Bewaakt: de TLCP-parser en de handshake, de smoorklep (hooguit 4 per seconde,
laatste koers wint), start bij de eerste en stop na de laatste kijker,
terugval met één WARNING, het websocket-commando alleen voor beheerders en
alleen met IG in demo/live, geen extra REST-verzoek, geen invloed op de handel,
en een frontend zonder externe bronnen.
"""
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
import gold_scalper.broker_stream as bs  # noqa: E402
from gold_scalper.broker.ig_capital import CapitalVenue, IgVenue  # noqa: E402
from gold_scalper.const import DOMAIN  # noqa: E402
from gold_scalper.dashboard import broker as B  # noqa: E402
from gold_scalper.dashboard import stream as S  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
JS = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
CREDS = {"endpoint": "https://demo-apd.marketdatasystems.com", "user": "ACC1",
         "password": "CST-abc|XST-def", "epic": "CS.D.CFEGOLD.CEA.IP", "generatie": 1}


# ------------------------------------------------------------ nephulp -- #

class FakeTransport:
    """Speelt serverregels af. ``None`` = verbinding dicht; ``hold`` = stil."""

    def __init__(self, regels=(), hold=False):
        self.regels = list(regels)
        self.hold = hold
        self.sent = []
        self.closed = False

    async def send(self, tekst):
        self.sent.append(tekst)

    async def receive(self, timeout):
        await asyncio.sleep(0)
        if self.regels:
            return self.regels.pop(0)
        if self.hold:
            await asyncio.sleep(3600)
        return None

    async def close(self):
        self.closed = True


HANDSHAKE = [
    "WSOK",
    "CONOK,S1a2b3,50000,5000,*",
    "SERVNAME,Lightstreamer HTTP Server",
    "CLIENTIP,10.0.0.1",
    "CONS,unlimited",
    "REQOK,1",
    "SUBOK,1,1,8",
]


def U(bied, laat, rest="||||||"):
    return f"U,1,1,{bied}|{laat}{rest}"


# -------------------------------------------------------- versie/docs -- #

def test_version_is_consistent():
    from gold_scalper import const

    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION == "1.8.1"
    assert manifest["requirements"] == []          # eigen TLCP-client
    assert "websocket_api" in manifest["dependencies"]
    root = PKG.parent.parent
    assert "Huidige versie: **1.8.1**" in (root / "README.md").read_text(encoding="utf-8")
    eerste = (root / "CHANGELOG.md").read_text(encoding="utf-8").split("## ")[1]
    assert eerste.startswith("1.8.1")
    laag = eerste.lower()
    assert "browser verversen" in laag and "paper" in laag and "demo" in laag
    assert "1.8.1" in (root / "DASHBOARD.md").read_text(encoding="utf-8")


# ------------------------------------------------------------- parser -- #

def test_request_encoding():
    tekst = S.create_session_request(CREDS)
    naam, params = tekst.split("\r\n")
    assert naam == "create_session"
    delen = dict(p.split("=", 1) for p in params.split("&"))
    assert delen["LS_user"] == "ACC1"
    assert delen["LS_password"] == "CST-abc%7CXST-def"
    assert delen["LS_cid"] == "mgQkwtwdysogQz2BJ4Ji%20kOj2Bg"
    sub = S.subscribe_request("CS.D.CFEGOLD.CEA.IP")
    assert sub.startswith("control\r\n")
    assert "LS_op=add" in sub and "LS_mode=MERGE" in sub and "LS_reqId=1" in sub
    assert "LS_group=MARKET%3ACS.D.CFEGOLD.CEA.IP" in sub
    assert "LS_schema=BID%20OFFER%20UPDATE_TIME%20CHANGE%20CHANGE_PCT%20HIGH%20LOW%20MARKET_STATE" in sub
    assert "+" not in sub


def test_ws_url():
    assert S.ws_url("https://demo-apd.marketdatasystems.com") == "wss://demo-apd.marketdatasystems.com/lightstreamer"
    assert S.ws_url("https://x.y/") == "wss://x.y/lightstreamer"
    assert S.ws_url("http://x.y") == "ws://x.y/lightstreamer"
    assert S.LS_WS_SUBPROTOCOL == "TLCP-2.1.0.lightstreamer.com"


def test_parse_message():
    assert S.parse_message("PROBE") == ("PROBE", [])
    assert S.parse_message("CONOK,S1,50000,5000,*\r\n") == ("CONOK", ["S1", "50000", "5000", "*"])
    assert S.parse_message("U,1,1,a|b,c|d") == ("U", ["1", "1", "a|b,c|d"])
    assert S.parse_message("CONERR,1,User/password check failed, really") == (
        "CONERR", ["1", "User/password check failed, really"])
    assert S.parse_message("REQERR,1,19,Specified subscription not found") == (
        "REQERR", ["1", "19", "Specified subscription not found"])


def test_value_decoding_and_merge():
    assert S.decode_value("#") is None
    assert S.decode_value("$") == ""
    assert S.decode_value("12%3A00%3A01") == "12:00:01"
    item = S.ItemState(8)
    assert item.apply("2650.1|2650.4|12%3A00%3A01|1.5|0.06|2660|2640|TRADEABLE") == [
        "2650.1", "2650.4", "12:00:01", "1.5", "0.06", "2660", "2640", "TRADEABLE"]
    # leeg = ongewijzigd
    assert item.apply("2650.2||||||")[:3] == ["2650.2", "2650.4", "12:00:01"]
    # ^N = N velden ongewijzigd
    w = item.apply("^2|12%3A00%3A02|^4|EDIT")
    assert w == ["2650.2", "2650.4", "12:00:02", "1.5", "0.06", "2660", "2640", "EDIT"]
    # null
    assert item.apply("#|$")[:2] == [None, ""]


def test_tick_from_values():
    t = S.tick_from_values(["2650.1", "2650.5", "12:00:01", "-1.5", "-0.06", "2660", "2640", "TRADEABLE"], 1000.0)
    assert t["soort"] == "tick" and t["bied"] == 2650.1 and t["laat"] == 2650.5
    assert t["mid"] == pytest.approx(2650.3) and t["spread"] == pytest.approx(0.4)
    assert t["verandering"] == -1.5 and t["hoog"] == 2660 and t["markt"] == "TRADEABLE"
    assert t["tijd"] == 1000.0
    leeg = S.tick_from_values([None] * 8, 1.0)
    assert leeg["mid"] is None and leeg["bied"] is None


# ----------------------------------------------------------- handshake -- #

def test_handshake_and_updates():
    tr = FakeTransport(HANDSHAKE + [
        "PROBE",
        "U,1,1,2650.1|2650.4|12%3A00%3A01|1.5|0.06|2660|2640|TRADEABLE",
        "U,1,1,2650.2||||||",
        None,
    ])
    ticks, live = [], []

    async def go():
        return await S.run_connection(tr, CREDS, ticks.append, lambda: live.append(1), clock=lambda: 5.0)

    with pytest.raises(S.TlcpError) as err:
        asyncio.run(go())
    assert err.value.soort == "GESLOTEN"
    assert tr.sent[0] == "wsok"
    assert tr.sent[1].startswith("create_session\r\n")
    assert tr.sent[2].startswith("control\r\n")      # pas na CONOK
    assert len(tr.sent) == 3
    assert live == [1]
    assert [t["bied"] for t in ticks] == [2650.1, 2650.2]
    assert ticks[1]["laat"] == 2650.4                  # ongewijzigd veld blijft


def test_control_waits_for_conok():
    tr = FakeTransport(["WSOK", None])
    with pytest.raises(S.TlcpError):
        asyncio.run(S.run_connection(tr, CREDS, lambda t: None, lambda: None))
    assert len(tr.sent) == 2 and not any(s.startswith("control") for s in tr.sent)


def test_conerr_auth_and_loop():
    tr = FakeTransport(["CONERR,1,User%2Fpassword check failed"])
    with pytest.raises(S.TlcpError) as err:
        asyncio.run(S.run_connection(tr, CREDS, lambda t: None, lambda: None))
    assert err.value.auth and "password" in err.value.tekst
    tr = FakeTransport(["CONERR,7,Licensed maximum number of sessions reached"])
    with pytest.raises(S.TlcpError) as err:
        asyncio.run(S.run_connection(tr, CREDS, lambda t: None, lambda: None))
    assert not err.value.auth
    tr = FakeTransport(HANDSHAKE + ["LOOP,0"])
    assert asyncio.run(S.run_connection(tr, CREDS, lambda t: None, lambda: None)) == "loop"
    tr = FakeTransport(["CONOK,S1,50000,5000,*", "REQERR,1,21,Bad item"])
    with pytest.raises(S.TlcpError) as err:
        asyncio.run(S.run_connection(tr, CREDS, lambda t: None, lambda: None))
    assert err.value.soort == "REQERR" and err.value.code == "21"


def test_silence_is_a_timeout(monkeypatch):
    monkeypatch.setattr(S, "LS_CONNECT_TIMEOUT", 0.01)
    tr = FakeTransport()
    tr.receive = lambda timeout: asyncio.wait_for(asyncio.sleep(1), timeout)
    with pytest.raises(S.TlcpError) as err:
        asyncio.run(S.run_connection(tr, CREDS, lambda t: None, lambda: None))
    assert err.value.soort == "TIMEOUT"


# ------------------------------------------------------------- beheer -- #

def _stream(transports, creds=CREDS):
    geopend = []

    async def open_transport(url):
        geopend.append(url)
        t = transports.pop(0) if transports else FakeTransport(hold=True)
        if isinstance(t, Exception):
            raise t
        return t

    return S.PriceStream(lambda: creds, open_transport), geopend


def test_throttle_max_four_per_second():
    regels = HANDSHAKE + [U(2650 + i / 10, 2651 + i / 10) for i in range(20)]
    tr = FakeTransport(regels, hold=True)

    async def go():
        ps, _ = _stream([tr])
        ontvangen = []
        afmelden = ps.subscribe(ontvangen.append)
        await asyncio.sleep(0.15)
        vroeg = [m for m in ontvangen if m["soort"] == "tick"]
        await asyncio.sleep(0.4)
        laat = [m for m in ontvangen if m["soort"] == "tick"]
        afmelden()
        await ps.async_stop()
        return vroeg, laat, ontvangen

    vroeg, laat, alles = asyncio.run(go())
    assert len(vroeg) == 1                    # 20 ticks binnen, 1 doorgegeven
    assert len(laat) == 2                     # na 0,25 s de laatste
    assert laat[-1]["bied"] == pytest.approx(2651.9)
    statussen = [m["status"] for m in alles if m["soort"] == "status"]
    assert statussen[:2] == ["verbinden", "live"]
    assert S.LS_MAX_PER_SECOND == 4


def test_start_on_first_and_stop_after_last_subscriber(monkeypatch):
    monkeypatch.setattr(S, "LS_LINGER_SECONDS", 0.05)
    tr = FakeTransport(HANDSHAKE, hold=True)

    async def go():
        ps, geopend = _stream([tr])
        assert not ps.actief and ps.status == "uit"
        a = ps.subscribe(lambda m: None)
        b = ps.subscribe(lambda m: None)
        await asyncio.sleep(0.02)
        assert ps.actief and ps.status == "live" and len(geopend) == 1
        a()
        await asyncio.sleep(0.08)
        assert ps.actief                       # er kijkt nog iemand
        b()
        await asyncio.sleep(0.02)
        assert ps.actief                       # nog binnen de nalooptijd
        c = ps.subscribe(lambda m: None)       # terug binnen de nalooptijd
        await asyncio.sleep(0.08)
        assert ps.actief and len(geopend) == 1 # zelfde verbinding
        c()
        await asyncio.sleep(0.12)
        assert not ps.actief and ps.status == "uit"
        assert tr.closed
        return geopend

    geopend = asyncio.run(go())
    assert geopend == ["wss://demo-apd.marketdatasystems.com/lightstreamer"]
    assert S.LS_LINGER_SECONDS == 0.05


def test_failure_falls_back_with_one_warning(monkeypatch, caplog):
    monkeypatch.setattr(S, "LS_BACKOFF_SECONDS", (0.01,))

    async def go():
        ps, geopend = _stream([OSError("geen route"), OSError("geen route"), OSError("x")])
        ontvangen = []
        ps.subscribe(ontvangen.append)
        await asyncio.sleep(0.15)
        await ps.async_stop()
        return ps, geopend, ontvangen

    with caplog.at_level(logging.DEBUG, logger=S.__name__):
        ps, geopend, ontvangen = asyncio.run(go())
    assert len(geopend) >= 3                   # blijft proberen
    waarschuwingen = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(waarschuwingen) == 1
    assert "elke 5 s" in waarschuwingen[0].getMessage()
    assert "terugval" in [m["status"] for m in ontvangen if m["soort"] == "status"]


def test_auth_refusal_waits_for_new_tokens(monkeypatch):
    monkeypatch.setattr(S, "LS_BACKOFF_SECONDS", (0.01,))
    monkeypatch.setattr(S, "LS_AUTH_WAIT_SECONDS", 0.01)
    slapen = []
    echte_sleep = asyncio.sleep

    async def snel(s):
        slapen.append(s)
        await echte_sleep(0.001)

    monkeypatch.setattr(S.asyncio, "sleep", snel)
    creds = dict(CREDS)

    async def go():
        ps, geopend = _stream([FakeTransport(["CONERR,1,User check failed"])], creds)
        ps.subscribe(lambda m: None)
        await echte_sleep(0.05)
        voor = len(geopend)
        creds["generatie"] = 2                 # de cyclus logde opnieuw in
        await echte_sleep(0.05)
        na = len(geopend)
        await ps.async_stop()
        return voor, na

    voor, na = asyncio.run(go())
    assert voor == 1                           # zelfde tokens: niet opnieuw
    assert na >= 2                             # nieuwe tokens: wel


def test_no_session_means_no_connection_and_no_rest():
    async def go():
        geopend = []

        async def open_transport(url):
            geopend.append(url)

        ps = S.PriceStream(lambda: None, open_transport)
        ontvangen = []
        ps.subscribe(ontvangen.append)
        await asyncio.sleep(0.02)
        await ps.async_stop()
        return geopend, ontvangen

    geopend, ontvangen = asyncio.run(go())
    assert geopend == []
    assert any(m.get("reden") == "wacht op IG-sessie" for m in ontvangen)


def test_replay_sends_status_and_fresh_tick():
    tr = FakeTransport(HANDSHAKE + [U(2650.1, 2650.4)], hold=True)

    async def go():
        ps, _ = _stream([tr])
        ps.subscribe(lambda m: None)
        await asyncio.sleep(0.05)
        nieuw = []
        ps.replay(nieuw.append)
        await ps.async_stop()
        return nieuw

    nieuw = asyncio.run(go())
    assert nieuw[0] == {"soort": "status", "status": "live", "reden": None}
    assert nieuw[1]["soort"] == "tick" and nieuw[1]["bied"] == 2650.1


# --------------------------------------------------- IG-sessiegegevens -- #

class _Resp:
    def __init__(self, payload, headers):
        self._p, self.status, self.headers = payload, 200, headers
    async def json(self, content_type=None): return self._p
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _Sessie:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kw):
        self.calls.append(url)
        return _Resp(self.payload, {"CST": "c1", "X-SECURITY-TOKEN": "x1"})

    def request(self, method, url, **kw):
        self.calls.append(url)
        return _Resp({"snapshot": {"bid": 1.0, "offer": 1.1, "marketStatus": "TRADEABLE"}}, {})


def test_ig_session_exposes_streaming_credentials_without_requests():
    sessie = _Sessie({"currentAccountId": "ACC9",
                      "lightstreamerEndpoint": "https://demo-apd.marketdatasystems.com"})
    venue = IgVenue(sessie, "k", "u", "p", environment="demo", epic="CS.D.CFEGOLD.CEA.IP")
    assert venue.streaming_credentials() is None      # nog niet ingelogd
    assert sessie.calls == []                          # en dus ook niet ingelogd door de vraag
    asyncio.run(venue.quote())
    n = len(sessie.calls)
    c = venue.streaming_credentials()
    assert c == {"endpoint": "https://demo-apd.marketdatasystems.com", "user": "ACC9",
                 "password": "CST-c1|XST-x1", "epic": "CS.D.CFEGOLD.CEA.IP", "generatie": 1}
    assert len(sessie.calls) == n                      # geen extra verzoek


def test_capital_has_no_stream():
    sessie = _Sessie({"currentAccountId": "A"})
    venue = CapitalVenue(sessie, "k", "u", "p", environment="demo", epic="GOLD")
    asyncio.run(venue.quote())
    assert venue.streaming_credentials() is None


# ------------------------------------------------- websocket-commando -- #

class _Conn:
    def __init__(self, admin=True):
        self.user = SimpleNamespace(is_admin=admin) if admin is not None else None
        self.subscriptions = {}
        self.errors, self.results, self.messages = [], [], []

    def send_error(self, msg_id, code, message):
        self.errors.append((msg_id, code, message))

    def send_result(self, msg_id, result=None):
        self.results.append(msg_id)

    def send_message(self, message):
        self.messages.append(message)


def _hass(venue_name="ig", mode="demo"):
    venue = SimpleNamespace(name=venue_name, streaming_credentials=lambda: None)
    coord = SimpleNamespace(entry=SimpleNamespace(entry_id="e1"), venue=venue,
                            mode=SimpleNamespace(value=mode))
    return SimpleNamespace(data={DOMAIN: {"e1": coord}})


def test_ws_command_is_admin_only():
    for admin in (False, None):
        conn = _Conn(admin=admin)
        bs.handle_broker_stream(_hass(), conn, {"id": 5, "type": bs.STREAM_COMMAND})
        assert conn.errors and conn.errors[0][:2] == (5, "unauthorized")
        assert conn.subscriptions == {} and conn.results == []


def test_ws_command_not_in_paper_or_without_ig():
    for venue, mode in (("ig", "paper"), ("capital", "demo"), ("simulator", "paper"), ("oanda", "live")):
        conn = _Conn()
        bs.handle_broker_stream(_hass(venue, mode), conn, {"id": 1, "type": bs.STREAM_COMMAND})
        assert conn.errors[0][1] == "not_supported", (venue, mode)
        assert conn.subscriptions == {}
    conn = _Conn()
    bs.handle_broker_stream(SimpleNamespace(data={}), conn, {"id": 2, "type": bs.STREAM_COMMAND})
    assert conn.errors[0][1] == "not_found"


def test_ws_command_subscribes_and_forwards():
    hass = _hass("ig", "demo")
    tr = FakeTransport(HANDSHAKE + [U(2650.1, 2650.4)], hold=True)

    async def go():
        ps, _ = _stream([tr])
        hass.data[bs.STREAMS_KEY] = {"e1": ps}
        conn = _Conn()
        bs.handle_broker_stream(hass, conn, {"id": 9, "type": bs.STREAM_COMMAND})
        await asyncio.sleep(0.05)
        assert conn.results == [9] and 9 in conn.subscriptions
        conn.subscriptions[9]()                # HA meldt af bij sluiten
        await bs.async_stop_stream(hass, "e1")
        assert bs.STREAMS_KEY in hass.data and "e1" not in hass.data[bs.STREAMS_KEY]
        return conn, ps

    conn, ps = asyncio.run(go())
    soorten = [m["event"]["soort"] for m in conn.messages]
    assert all(m["id"] == 9 and m["type"] == "event" for m in conn.messages)
    assert "tick" in soorten and "status" in soorten
    assert not ps.actief and tr.closed


def test_ws_command_registration_uses_admin_check_and_no_write():
    src = (PKG / "broker_stream.py").read_text(encoding="utf-8")
    assert "is_admin" in src
    assert "async_register_command" in src
    for verboden in ("place_order", "close(", "modify_stop", "modify_target", "_login", "_request("):
        assert verboden not in src
    http = (PKG / "http.py").read_text(encoding="utf-8")
    assert "async_register_websocket(hass)" in http
    init = (PKG / "__init__.py").read_text(encoding="utf-8")
    assert init.count("_stop_koersstroom(hass, entry.entry_id)") == 2   # unload + afsluiten


# ------------------------------------------------- geen handelsinvloed -- #

def test_stream_never_feeds_decisions():
    verboden = re.compile(r"broker_stream|dashboard\.stream|dashboard import stream|PriceStream|streaming_credentials")
    for pad in [PKG / "coordinator.py", *(PKG / "strategy").rglob("*.py"),
                *(PKG / "analysis").rglob("*.py"), PKG / "broker" / "risk.py",
                PKG / "broker" / "exits.py", PKG / "broker" / "execution_safety.py"]:
        assert not verboden.search(pad.read_text(encoding="utf-8")), pad.name
    src = (PKG / "dashboard" / "stream.py").read_text(encoding="utf-8")
    assert "homeassistant" not in src.split('"""', 2)[2]
    for verboden_woord in ("place_order", "coordinator", "_request("):
        assert verboden_woord not in src.split('"""', 2)[2]


def test_payload_carries_conversion_rate():
    data = {"conversion": {"instrument": "USD", "account": "EUR", "rate": 0.86}}
    body = B.build_payload(
        data, symbol="X", timeframe="1m", candles=None, db=None, exit_cfg={},
        version="1.8.1", status=("wachtend", ""), places_orders=True, uses_real_money=False)
    assert body["instrument"]["omrekening"] == 0.86
    assert body["api"] == 1


# ------------------------------------------------------------ frontend -- #

def test_frontend_has_no_external_urls():
    assert not re.search(r"https?://", JS)
    assert "<script" not in JS and "import(" not in JS and "fetch(" not in JS


def test_frontend_uses_stream_with_fallback():
    assert 'const STREAM_TYPE = "gold_scalper/broker_stream"' in JS
    assert "subscribeMessage" in JS
    assert "requestAnimationFrame" in JS and "cancelAnimationFrame" in JS
    assert "const POLL_MS = 5000" in JS                 # de poll blijft
    assert "LIVE" in JS and "elke 5 s" in JS and "gsb-puls" in JS
    assert "live, indicatief" in JS
    assert "not_supported" in JS


def test_frontend_cleans_up_on_close():
    stop = JS.split("  _stop() {")[1].split("\n  }\n")[0]
    assert "this._afmelden()" in stop and "cancelAnimationFrame" in stop
    assert "clearTimeout(this._herTimer)" in stop
    afm = JS.split("  _afmelden() {")[1].split("\n  }\n")[0]
    assert "this._subGen++" in afm and "u()" in afm
    # een abonnement dat binnenkomt nadat het paneel sloot, wordt meteen opgezegd
    assert "if (gen !== this._subGen || !this._actief)" in JS


def test_frontend_live_pnl_direction_and_conversion():
    eff = JS.split("  _eff() {")[1].split("\n  }\n")[0]
    assert 'p.richting === "long" ? t.bied : t.laat' in eff
    assert 'p.richting === "long" ? koers - p.instap : p.instap - koers' in eff
    assert "punten * p.units" in eff
    assert "d.instrument.omrekening" in eff
    assert "pnl_broker: p.pnl_account" in eff        # officieel bedrag blijft zichtbaar
