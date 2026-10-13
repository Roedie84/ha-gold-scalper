"""2.5.0: turbo-scalp - scalp handelt op de live koers, met een orderbudget."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from test_v190 import _cyclus, _klok, _opzet, _richting, vaste_klok  # noqa: E402,F401


def _tick(venue, markt="TRADEABLE"):
    half = venue.spread / 2
    return {"soort": "tick", "bied": venue.price - half, "laat": venue.price + half,
            "markt": markt, "tijd": 0}


def _klaar(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    coordinator.reeks.enabled = False
    _richting["d"] = 1
    _cyclus(coordinator)                       # opwarmen, context voor de turbo
    assert coordinator._turbo_ctx is not None
    coordinator._turbo_laatst = 0.0
    return coordinator, venue


def test_turbo_opent_tussen_de_cycli(tmp_path, monkeypatch):
    coordinator, venue = _klaar(tmp_path, monkeypatch)
    voor = len(venue._positions)
    _klok["extra"] += 400                      # buiten de cooldown en de candle
    venue.move(3.0)
    n = asyncio.run(coordinator._turbo_tick(_tick(venue)))
    assert n == 1 and len(venue._positions) == voor + 1
    assert coordinator.turbo_stats["orders"] == 1
    rij = coordinator.db.conn.execute(
        "SELECT strategie FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    assert rij[0] in ("scalp", None)


def test_orderbudget_per_minuut(tmp_path, monkeypatch):
    coordinator, venue = _klaar(tmp_path, monkeypatch)
    coordinator.turbo_orders_pm = 1
    coordinator._turbo_orders = [__import__("time").monotonic()]
    _klok["extra"] += 400
    venue.move(3.0)
    assert asyncio.run(coordinator._turbo_tick(_tick(venue))) == 0


def test_geen_ronde_tijdens_cyclus_of_bij_dichte_markt(tmp_path, monkeypatch):
    coordinator, venue = _klaar(tmp_path, monkeypatch)
    _klok["extra"] += 400
    venue.move(3.0)
    assert asyncio.run(coordinator._turbo_tick(_tick(venue, markt="CLOSED"))) == 0

    async def met_slot():
        async with coordinator._cyclus_slot:
            return await coordinator._turbo_tick(_tick(venue))
    assert asyncio.run(met_slot()) == 0
    coordinator._turbo_ctx = dict(coordinator._turbo_ctx, saldo_onbekend="403")
    assert asyncio.run(coordinator._turbo_tick(_tick(venue))) == 0


def test_hooguit_een_ronde_per_seconde(tmp_path, monkeypatch):
    coordinator, venue = _klaar(tmp_path, monkeypatch)
    import time
    coordinator._turbo_laatst = time.monotonic()
    _klok["extra"] += 400
    venue.move(3.0)
    assert asyncio.run(coordinator._turbo_tick(_tick(venue))) == 0


def test_niet_ig_dan_geen_stream(tmp_path, monkeypatch):
    coordinator, venue = _klaar(tmp_path, monkeypatch)
    assert coordinator._turbo_afmelden is False


def test_instellingen_en_vertalingen():
    import json
    basis = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")
    for taal in ("nl", "en"):
        data = json.load(open(os.path.join(basis, "translations", f"{taal}.json"),
                               encoding="utf-8"))["options"]["step"]["init"]["data"]
        assert "scalp_turbo" in data and "scalp_turbo_orders_per_min" in data
