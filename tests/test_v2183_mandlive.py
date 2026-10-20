"""2.18.3 - de mand: markt kiezen voor de grafiek en live koersen.

Gemeld 20-10: "Waar kan ik nu bijvoorbeeld een andere crypto munt voor de
grafiek selecteren? Alles zit in een mand maar heb nergens een dropdown
keuze menu" en "En data is niet live, refreshed elke 5 seconden, graag live".
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

import gold_scalper.broker_stream as bs  # noqa: E402
from gold_scalper.dashboard import stream as S  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
JS = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")


def test_een_ticker_vult_aan_met_de_laatst_bekende_waarden():
    laatste: dict = {}
    assert S.bitvavo_ticker({"event": "ticker", "market": "BTC-EUR", "bestBid": "90000",
                             "bestAsk": "90010"}, laatste) == ("BTC-EUR", 90000.0, 90010.0)
    # Alleen de bieding veranderde.
    assert S.bitvavo_ticker({"event": "ticker", "market": "BTC-EUR", "bestBid": "90005"},
                            laatste) == ("BTC-EUR", 90005.0, 90010.0)
    assert S.bitvavo_ticker({"event": "subscribed"}, laatste) is None
    assert S.bitvavo_ticker({"event": "ticker", "market": "X-EUR", "bestBid": "2", "bestAsk": "1"},
                            laatste) is None


class _Msg:
    def __init__(self, data):
        self.type = SimpleNamespace(name="TEXT")
        self.data = data


class _Ws:
    def __init__(self, berichten):
        self.verstuurd: list = []
        self._berichten = list(berichten)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send_str(self, tekst):
        self.verstuurd.append(json.loads(tekst))

    async def receive(self, timeout=None):
        if self._berichten:
            return _Msg(json.dumps(self._berichten.pop(0)))
        await asyncio.sleep(3600)


def test_de_stroom_geeft_de_grafiekmarkt_en_de_hele_mand_live_door():
    ws = _Ws([
        {"event": "ticker", "market": "ETH-EUR", "bestBid": "3000", "bestAsk": "3000.5"},
        {"event": "ticker", "market": "BTC-EUR", "bestBid": "90000", "bestAsk": "90010"},
    ])
    ontvangen: list = []

    async def draai():
        stroom = S.BitvavoTickStream(lambda: ws, "btc-eur", lambda: ["BTC-EUR", "ETH-EUR", "SOL-EUR"])
        stroom.subscribe(ontvangen.append)
        await asyncio.sleep(0.8)
        await stroom.async_stop()

    asyncio.run(draai())
    abonnement = ws.verstuurd[0]
    assert abonnement["action"] == "subscribe"
    assert abonnement["channels"][0]["markets"] == ["BTC-EUR", "ETH-EUR", "SOL-EUR"]
    ticks = [m for m in ontvangen if m.get("soort") == "tick"]
    assert ticks and ticks[-1]["bied"] == 90000.0 and ticks[-1]["mid"] == 90005.0
    mand = [m for m in ontvangen if m.get("soort") == "mand"]
    assert mand and set(mand[-1]["koersen"]) == {"BTC-EUR", "ETH-EUR"}
    assert any(m.get("status") == "live" for m in ontvangen if m.get("soort") == "status")


def test_bitvavo_mag_live_ook_op_papier():
    coord = SimpleNamespace(venue=SimpleNamespace(name="bitvavo"), mode=SimpleNamespace(value="paper"))
    assert bs.stream_eligibility(coord) == (True, "")


def test_een_verdwenen_markt_valt_terug_op_de_mand():
    from gold_scalper import http as h

    hoofd = SimpleNamespace(entry=SimpleNamespace(entry_id="E1"))
    ig = SimpleNamespace(entry=SimpleNamespace(entry_id="IG"))
    hass = SimpleNamespace(data={"gold_scalper": {"IG": ig, "E1": hoofd}})
    assert h._pick_coordinator(hass, "E1_doge-eur") is hoofd
    assert h._pick_coordinator(hass, "IG") is ig


def test_het_paneel_heeft_een_keuzelijst_en_klikbare_kaarten():
    assert 'id="mandkeuze"' in JS and "this._kiesBroker(e.target.value)" in JS
    assert '.mm[data-entry]' in JS and "data-entry=" in JS
    assert 'm.soort === "mand"' in JS and "_effMand(" in JS
