"""2.25.2 (L-GS-011): een verdwenen positie krijgt het sluitmoment van de broker.

Tot nu toe boekte de afwikkeling van een positie die de broker zelf sloot
(stop, doel) altijd ``now`` als sluitmoment - het moment waarop de lus het
merkte - ook als het transactie- of activiteitenoverzicht het echte moment al
noemde. Daardoor waren looptijd en de tijdsanalyses per uur/sessie scheef.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.coordinator import _broker_sluitmoment  # noqa: E402

from test_broker_cycle import NOW, ScriptedVenue, _coordinator, _open_trade  # noqa: E402

OPEN = datetime(2026, 9, 15, 11, 0, tzinfo=timezone.utc)


def _afwikkelen(tmp_path, monkeypatch, *, deal=None, activiteit=None):
    venue = ScriptedVenue()
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    _open_trade(coordinator.db, coordinator.run_id, "VERDWENEN")
    venue._positions.clear()
    coordinator._positions_cache = None

    async def closed_deal(*args, **kwargs):
        return deal

    venue.closed_deal = closed_deal

    async def zoek(trade):
        return activiteit

    monkeypatch.setattr(coordinator, "_zoek_activiteit", zoek)
    momenten: list = []
    echt = coordinator.risk.record_close
    monkeypatch.setattr(
        coordinator.risk, "record_close",
        lambda pnl, moment, **kw: (momenten.append(moment), echt(pnl, moment, **kw)),
    )
    quote = asyncio.run(venue.quote())
    asyncio.run(coordinator._settle_vanished_positions(quote, NOW))
    gesloten = [t for t in coordinator.db.closed_trades(coordinator.run_id)
                if t.broker_ticket == "VERDWENEN"]
    assert gesloten and gesloten[0].close_time, "trade is afgewikkeld"
    return gesloten[0], momenten


def test_sluitmoment_uit_het_transactieoverzicht(tmp_path, monkeypatch):
    trade, momenten = _afwikkelen(
        tmp_path, monkeypatch,
        deal={"exit_price": 4390.0, "closed_at": "2026-09-15T11:42:10"},
    )
    assert datetime.fromisoformat(trade.close_time) == datetime(
        2026, 9, 15, 11, 42, 10, tzinfo=timezone.utc)
    assert trade.duration_seconds == 42 * 60 + 10
    assert trade.close_reason == "broker_gesloten_gemeten"
    # De risicoadministratie blijft op het moment van afwikkelen.
    assert momenten == [NOW]


def test_sluitmoment_uit_de_activiteit_in_ig_vorm(tmp_path, monkeypatch):
    trade, _ = _afwikkelen(
        tmp_path, monkeypatch, deal=None,
        activiteit={"exit_price": 4390.0, "activity_date": "2026/09/15 11:55:01",
                    "source": "broker_activity"},
    )
    assert datetime.fromisoformat(trade.close_time) == datetime(
        2026, 9, 15, 11, 55, 1, tzinfo=timezone.utc)


def test_zonder_brokertijd_blijft_het_nu(tmp_path, monkeypatch):
    trade, _ = _afwikkelen(tmp_path, monkeypatch,
                           deal={"exit_price": 4390.0})
    assert datetime.fromisoformat(trade.close_time) == NOW
    assert trade.duration_seconds == 3600


def test_geschatte_afwikkeling_houdt_nu(tmp_path, monkeypatch):
    trade, _ = _afwikkelen(tmp_path, monkeypatch, deal=None, activiteit=None)
    assert datetime.fromisoformat(trade.close_time) == NOW


def test_parser_grenzen():
    assert _broker_sluitmoment("2026-09-15T13:00:00", OPEN, NOW) == NOW, "niet in de toekomst"
    assert _broker_sluitmoment("2026-09-15T10:00:00", OPEN, NOW) == OPEN, "niet voor de opening"
    assert _broker_sluitmoment("2026-09-15T00:00:00", OPEN, NOW) is None, "datum zonder tijd"
    assert _broker_sluitmoment("onzin", OPEN, NOW) is None
    assert _broker_sluitmoment(None, OPEN, NOW) is None
    assert _broker_sluitmoment("2026-09-15T11:30:00Z", OPEN, NOW) == datetime(
        2026, 9, 15, 11, 30, tzinfo=timezone.utc)
    assert _broker_sluitmoment("2026-09-15T13:30:00+02:00", None, NOW) == datetime(
        2026, 9, 15, 11, 30, tzinfo=timezone.utc)
