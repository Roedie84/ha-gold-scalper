"""2.21.3 - logging en meetbaarheid (leerronde 24-10; geen strategie, risico of
orders geraakt).

L-GS-023: 23-10 16:18, 17:18, 18:18 en 19:18 "HA sluit af" zonder HA-herstart:
een mandlid dat de mand verlaat liep via emergency_shutdown. Nu een INFO-regel
met de markt; "HA sluit af" alleen bij een echte stop.

L-GS-022: 23-10 15:18 "Noodstop uit een eerdere sessie blijft actief" zonder
markt; de mand toonde per markt niet wie in noodstop stond.
"""
from __future__ import annotations

import logging
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper import lifecycle  # noqa: E402
from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.broker.risk import TradingState  # noqa: E402
from gold_scalper.lifecycle import LifecycleController, LifecycleState  # noqa: E402
from test_broker_cycle import FakeHass  # noqa: E402


@pytest.mark.asyncio
async def test_mandlid_gestopt_is_geen_ha_stop(caplog, monkeypatch):
    monkeypatch.setattr(lifecycle, "_laatste_afsluitmelding", None)
    caplog.set_level(logging.DEBUG, logger=lifecycle.__name__)
    c = LifecycleController()
    await c.emergency_shutdown([], mandlid="PUMP-EUR")
    teksten = [r.getMessage() for r in caplog.records]
    assert not any("HA sluit af" in t for t in teksten)
    info = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("PUMP-EUR gestopt" in r.getMessage() for r in info)
    assert c.state == LifecycleState.STOPPED


@pytest.mark.asyncio
async def test_echte_stop_meldt_nog_steeds(caplog, monkeypatch):
    monkeypatch.setattr(lifecycle, "_laatste_afsluitmelding", None)
    caplog.set_level(logging.DEBUG, logger=lifecycle.__name__)
    await LifecycleController().emergency_shutdown([])
    assert any(
        "HA sluit af" in r.getMessage() and r.levelno == logging.WARNING
        for r in caplog.records
    )


class _Lid:
    def __init__(self, symbol, halted=False):
        self.symbol = symbol
        self.entry = SimpleNamespace(entry_id=f"E1_{symbol}")
        self.enabled = True
        self.mode = SimpleNamespace(places_orders=False)
        self.paper = SimpleNamespace(open_positions=[])
        self.venue = SimpleNamespace(_grootboek={})
        self.data = {"price": 1.0, "stats": {}, "equity": 10000}
        self.risk = SimpleNamespace(state=SimpleNamespace(
            state=TradingState.HALTED if halted else TradingState.RUNNING))
        self.hooks = []

    async def async_shutdown(self):
        return None

    async def async_shutdown_hook(self, mandlid=False):
        self.hooks.append(mandlid)


def _mand(hoofd):
    entry = SimpleNamespace(entry_id="E1", data={"venue": "bitvavo"}, options={})
    m = mand_mod.BitvavoMand(FakeHass(), entry, hoofd)
    m._gereed = True
    return m


@pytest.mark.asyncio
async def test_stop_lid_tijdens_lopende_mand_is_mandlid():
    m = _mand(_Lid("BTC-EUR"))
    lid = _Lid("PUMP-EUR")
    m.leden = {"PUMP-EUR": lid}
    await m._stop_lid("PUMP-EUR")
    assert lid.hooks == [True]


@pytest.mark.asyncio
async def test_mand_stopt_dan_is_het_een_echte_stop():
    m = _mand(_Lid("BTC-EUR"))
    lid = _Lid("XRP-EUR")
    m.leden = {"XRP-EUR": lid}
    m._bewaar = _leeg
    await m.async_stop()
    assert lid.hooks == [False]


async def _leeg():
    return None


def test_overzicht_toont_noodstop_per_markt():
    m = _mand(_Lid("BTC-EUR"))
    m.leden = {"PEPE-EUR": _Lid("PEPE-EUR", halted=True), "XRP-EUR": _Lid("XRP-EUR")}
    rijen = {r["markt"]: r for r in m.overzicht()["per_markt"]}
    assert rijen["PEPE-EUR"]["noodstop"] is True
    assert rijen["XRP-EUR"]["noodstop"] is False
    assert rijen["BTC-EUR"]["noodstop"] is False


def test_noodstop_waarschuwing_noemt_de_entry():
    pad = os.path.join(os.path.dirname(__file__), "..", "custom_components",
                       "gold_scalper", "storage", "state.py")
    bron = open(pad, encoding="utf-8").read()
    assert "blijft actief (%s): %s" in bron
    assert "self._entry_id,\n                state.halt_reason," in bron


def test_versie():
    from gold_scalper.const import INTEGRATION_VERSION

    assert INTEGRATION_VERSION == "2.21.3"
