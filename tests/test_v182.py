"""1.8.2 - live koers via HTTP-streaming (IG sloot de websocket).

Een lokale aiohttp-server speelt Lightstreamer (TLCP-2.1.0 over HTTP):
create_session.txt als stroom, control.txt als los verzoek, LOOP en
bind_session.txt, CONERR,1 als weigering, HTTP-fouten en een verbroken
stroom. Bewaakt ook dat wachtwoord en tokens nooit in een logregel staan en
dat de WARNING de diagnose (transport, HTTP-status, eerste serverregel) geeft.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.dashboard import stream as S  # noqa: E402

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
GEHEIM = "CST-geheimcst|XST-geheimxst"


def _creds(endpoint, user="ACC1"):
    return {"endpoint": endpoint, "user": user, "password": GEHEIM,
            "epic": "CS.D.CFEGOLD.CEA.IP", "generatie": 1}


class NepLightstreamer:
    """Minimale TLCP-2.1.0-server over HTTP-streaming."""

    def __init__(self, scenario="loop"):
        self.scenario = scenario
        self.verzoeken = []          # (pad, query, formulier)
        self.geabonneerd = asyncio.Event()
        self.creates = 0

    async def _form(self, request):
        body = await request.text()
        form = {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}
        self.verzoeken.append((request.path, dict(request.query), form))
        return form

    async def _stroom(self, request, regels, *, open_houden=False, wacht_op_abonnement=False):
        resp = web.StreamResponse(status=200, headers={"Content-Type": "text/enriched; charset=UTF-8"})
        await resp.prepare(request)
        for i, r in enumerate(regels):
            if wacht_op_abonnement and i == 1:
                await asyncio.wait_for(self.geabonneerd.wait(), 5)
            await resp.write((r + "\r\n").encode())
        if open_houden:
            await asyncio.sleep(3600)
        return resp

    async def create(self, request):
        form = await self._form(request)
        self.creates += 1
        if self.scenario == "http503":
            return web.Response(status=503, text="Service Unavailable\r\nmeer")
        if form.get("LS_user") == "fout":
            return await self._stroom(request, ["CONERR,1,User%2Fpassword check failed"])
        if self.scenario == "breuk":
            # Stroom breekt af na CONOK, zonder LOOP.
            return await self._stroom(request, ["CONOK,S9,50000,5000,*"])
        regels = ["CONOK,S9,50000,5000,*", "SERVNAME,Lightstreamer HTTP Server",
                  "CLIENTIP,127.0.0.1", "SUBOK,1,1,8",
                  "U,1,1,2650.1|2650.4|12%3A00%3A01|1.5|0.06|2660|2640|TRADEABLE",
                  "PROBE", "U,1,1,2650.2||12%3A00%3A02|||||"]
        if self.scenario == "loop":
            regels.append("LOOP,0")
        return await self._stroom(request, regels, wacht_op_abonnement=True,
                                  open_houden=self.scenario == "houden")

    async def control(self, request):
        form = await self._form(request)
        if form.get("LS_session") != "S9":
            return web.Response(text="REQERR,1,20,Session not found\r\n")
        if self.scenario == "reqerr":
            self.geabonneerd.set()
            return web.Response(text="REQERR,1,21,Bad%20item\r\n")
        self.geabonneerd.set()
        return web.Response(text="REQOK,1\r\n")

    async def bind(self, request):
        form = await self._form(request)
        assert form.get("LS_session") == "S9"
        return await self._stroom(request, [
            "CONOK,S9,50000,5000,*",
            "U,1,1,2651.0|2651.3||||||",
        ])  # en dan dicht: GESLOTEN


async def _server(nep):
    app = web.Application()
    app.router.add_post("/lightstreamer/create_session.txt", nep.create)
    app.router.add_post("/lightstreamer/control.txt", nep.control)
    app.router.add_post("/lightstreamer/bind_session.txt", nep.bind)
    runner = web.AppRunner(app, shutdown_timeout=0.2)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    poort = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{poort}"


def _run(nep, user="ACC1"):
    """Eén run_connection tegen de nepserver; geeft (ticks, live, fout, transport)."""
    async def go():
        runner, url = await _server(nep)
        ticks, live = [], []
        fout = None
        async with aiohttp.ClientSession() as sessie:
            tr = S.HttpStreamTransport(sessie, url)
            try:
                await S.run_connection(tr, _creds(url, user), ticks.append, lambda: live.append(1))
            except S.TlcpError as err:
                fout = err
            finally:
                await tr.close()
        await runner.cleanup()
        return ticks, live, fout, tr

    return asyncio.run(go())


def test_http_stream_handshake_subscribe_updates_loop_and_bind(caplog):
    nep = NepLightstreamer("loop")
    with caplog.at_level(logging.DEBUG, logger=S.__name__):
        ticks, live, fout, tr = _run(nep)
    paden = [v[0] for v in nep.verzoeken]
    assert paden == ["/lightstreamer/create_session.txt", "/lightstreamer/control.txt",
                     "/lightstreamer/bind_session.txt"]
    for _pad, query, _form in nep.verzoeken:
        assert query == {"LS_protocol": "TLCP-2.1.0"}
    create = nep.verzoeken[0][2]
    assert create["LS_user"] == "ACC1" and create["LS_password"] == GEHEIM
    assert create["LS_cid"] == S.LS_CID and create["LS_polling"] == "false"
    ctrl = nep.verzoeken[1][2]
    assert ctrl["LS_session"] == "S9" and ctrl["LS_op"] == "add" and ctrl["LS_mode"] == "MERGE"
    assert ctrl["LS_group"] == "MARKET:CS.D.CFEGOLD.CEA.IP"
    assert ctrl["LS_schema"].split() == list(S.LS_MARKET_FIELDS)
    assert live == [1]
    assert [t["bied"] for t in ticks] == [2650.1, 2650.2, 2651.0]
    assert ticks[1]["laat"] == 2650.4 and ticks[1]["broker_tijd"] == "12:00:02"
    assert ticks[2]["laat"] == 2651.3                 # na bind_session verder
    assert fout is not None and fout.soort == "GESLOTEN"
    assert tr.http_status == 200 and tr.eerste_regel.startswith("CONOK,S9")
    # elke serverregel op DEBUG, maar nooit wachtwoord of tokens
    alles = "\n".join(r.getMessage() for r in caplog.records)
    assert "SUBOK,1,1,8" in alles
    assert "geheimcst" not in alles and "geheimxst" not in alles


def test_http_conerr_1_is_auth_refusal():
    ticks, live, fout, tr = _run(NepLightstreamer("loop"), user="fout")
    assert fout.soort == "CONERR" and fout.code == "1" and fout.auth
    assert "password check failed" in fout.tekst
    assert live == [] and ticks == []
    assert "CONERR,1" in tr.diagnose() and "HTTP 200" in tr.diagnose()


def test_http_status_error_has_diagnosis():
    ticks, live, fout, tr = _run(NepLightstreamer("http503"))
    assert fout.soort == "HTTP" and fout.code == "503" and fout.tekst == "Service Unavailable"
    d = tr.diagnose()
    assert "transport http-streaming" in d and "HTTP 503" in d and "Service Unavailable" in d


def test_http_reqerr_on_control_response():
    ticks, live, fout, tr = _run(NepLightstreamer("reqerr"))
    assert fout.soort == "REQERR" and fout.code == "21" and fout.tekst == "Bad item"


def test_broken_stream_backs_off_with_one_diagnostic_warning(monkeypatch, caplog):
    monkeypatch.setattr(S, "LS_BACKOFF_SECONDS", (0.05,))
    monkeypatch.setattr(S, "LS_CONNECT_TIMEOUT", 2.0)
    nep = NepLightstreamer("breuk")

    async def go():
        runner, url = await _server(nep)
        async with aiohttp.ClientSession() as sessie:
            async def open_transport(endpoint):
                return S.HttpStreamTransport(sessie, endpoint)

            ps = S.PriceStream(lambda: _creds(url), open_transport)
            ontvangen = []
            ps.subscribe(ontvangen.append)
            await asyncio.sleep(0.6)
            await ps.async_stop()
        await runner.cleanup()
        return ontvangen

    with caplog.at_level(logging.DEBUG, logger=S.__name__):
        ontvangen = asyncio.run(go())
    assert nep.creates >= 2                            # blijft proberen
    w = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(w) == 1
    assert "transport http-streaming" in w[0] and "HTTP 200" in w[0]
    assert "eerste serverregel: 'CONOK,S9" in w[0] and "elke 5 s" in w[0]
    alles = "\n".join(r.getMessage() for r in caplog.records)
    assert "geheim" not in alles
    statussen = [m for m in ontvangen if m["soort"] == "status"]
    assert any(m["status"] == "terugval" and "http-streaming" in (m["reden"] or "") for m in statussen)


def test_live_stream_via_pricestream_and_throttle():
    nep = NepLightstreamer("houden")

    async def go():
        runner, url = await _server(nep)
        async with aiohttp.ClientSession() as sessie:
            async def open_transport(endpoint):
                return S.HttpStreamTransport(sessie, endpoint)

            ps = S.PriceStream(lambda: _creds(url), open_transport)
            ontvangen = []
            afmelden = ps.subscribe(ontvangen.append)
            await asyncio.sleep(0.6)
            status = ps.status
            afmelden()
            await ps.async_stop()
        await runner.cleanup()
        return status, ontvangen

    status, ontvangen = asyncio.run(go())
    assert status == "live"
    ticks = [m for m in ontvangen if m["soort"] == "tick"]
    assert ticks and ticks[-1]["bied"] == 2650.2       # laatste koers wint


def test_no_websocket_left_and_version():
    from gold_scalper import const

    code = (PKG / "dashboard" / "stream.py").read_text(encoding="utf-8")
    assert "ws_connect" not in code and "AiohttpWsTransport" not in code
    assert "HttpStreamTransport" in (PKG / "broker_stream.py").read_text(encoding="utf-8")
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION  # 1.9.0: niet meer vastgepind
    assert manifest["requirements"] == []
    root = PKG.parent.parent
    assert f"Huidige versie: **{const.INTEGRATION_VERSION}**" in (
        root / "README.md").read_text(encoding="utf-8")
    eerste = next(
        d for d in (root / "CHANGELOG.md").read_text(encoding="utf-8").split("## ")
        if d.startswith("1.8.2")
    )
    assert "http-streaming" in eerste.lower() and "browser verversen" in eerste.lower()
