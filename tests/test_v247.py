"""2.4.7: verweesde trades uit eerdere runs worden afgewikkeld op brokerdata."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from test_broker_cycle import NOW, ScriptedVenue, _coordinator, _open_trade  # noqa: E402


def _opzet(tmp_path, monkeypatch, gevonden):
    venue = ScriptedVenue()
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    oude_run = coordinator.run_id
    _open_trade(coordinator.db, oude_run, "WEES")
    # Heel oud: buiten het venster, blijft staan.
    _open_trade(coordinator.db, oude_run, "OUD",
                open_iso=(NOW - timedelta(days=5)).isoformat())
    coordinator.run_id = coordinator.db.start_run(
        "demo", "v1", "GOLD", {}, 10000.0, None, "fp2")
    venue._positions.clear()
    coordinator._positions_cache = None
    vragen: list = []

    async def zoek(trade):
        vragen.append(str(trade.broker_ticket))
        return gevonden

    monkeypatch.setattr(coordinator, "_zoek_activiteit", zoek)
    geboekt: list = []
    monkeypatch.setattr(coordinator.risk, "record_close",
                        lambda *a, **k: geboekt.append(a))
    return coordinator, venue, oude_run, vragen, geboekt


def _ronde(coordinator, venue, moment=NOW):
    coordinator._positions_cache = None
    quote = asyncio.run(venue.quote())
    asyncio.run(coordinator._settle_vanished_positions(quote, moment))


def _rij(coordinator, ticket):
    return coordinator.db.conn.execute(
        "SELECT run_id, close_time, close_price, close_reason FROM trades "
        "WHERE broker_ticket=?", (ticket,)).fetchone()


def test_wees_afgewikkeld_in_eigen_run_op_brokerprijs(tmp_path, monkeypatch):
    coordinator, venue, oude_run, vragen, geboekt = _opzet(
        tmp_path, monkeypatch,
        {"exit_price": 4390.0, "activity_date": "2026-09-15T11:30:00",
         "source": "broker_activity"})
    _ronde(coordinator, venue)
    run_id, close_time, close_price, reden = _rij(coordinator, "WEES")
    assert run_id == oude_run
    assert close_time.startswith("2026-09-15T11:30:00")
    # Short: de uitstap is de ask = brokerprijs.
    assert close_price == 4390.0
    assert reden == "broker_gesloten_gemeten"
    assert geboekt == [], "telt niet voor daglimiet of verliesreeks"
    assert vragen == ["WEES"], "trades buiten het venster worden niet nagevraagd"
    assert _rij(coordinator, "OUD")[1] is None


def test_niet_gevonden_blijft_open_en_begrensd(tmp_path, monkeypatch):
    coordinator, venue, _, vragen, _ = _opzet(tmp_path, monkeypatch, None)
    _ronde(coordinator, venue)
    _ronde(coordinator, venue, NOW + timedelta(seconds=20))  # binnen interval
    assert vragen == ["WEES"]
    assert _rij(coordinator, "WEES")[1] is None, "nooit op een schatting"
    _ronde(coordinator, venue, NOW + timedelta(minutes=6))
    assert vragen == ["WEES", "WEES"]


def test_live_positie_is_geen_wees(tmp_path, monkeypatch):
    coordinator, venue, _, vragen, _ = _opzet(
        tmp_path, monkeypatch, {"exit_price": 4390.0})
    n = asyncio.run(coordinator._wikkel_wezen_af({"WEES"}, asyncio.run(venue.quote()), NOW))
    assert n == 0 and vragen == []


def test_versie():
    import json
    from gold_scalper.const import INTEGRATION_VERSION
    pad = os.path.join(os.path.dirname(__file__), "..", "custom_components",
                       "gold_scalper", "manifest.json")
    assert json.load(open(pad))["version"] == INTEGRATION_VERSION
