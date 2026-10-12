"""2.2.0: pyramiden volwaardig - elke bijkoop vastgelegd als eigen trade."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.const import STRATEGIE_COMBINATIE  # noqa: E402
from gold_scalper.storage.database import Trade  # noqa: E402
from gold_scalper.strategy.pyramid import PyramidConfig  # noqa: E402

from test_v190 import _opzet, vaste_klok  # noqa: E402,F401


def _met_positie(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    coordinator.pyramid = PyramidConfig(enabled=True, trigger_atr=1.0, max_additions=2)
    coordinator.state.atr = SimpleNamespace(value=2.0)
    asyncio.run(venue.place_order("GOLD", "buy", 2.0, stop_loss=venue.price - 4.0))
    pos = venue._positions[-1]
    coordinator.db.insert_trade(Trade(
        run_id=coordinator.run_id, mode="demo", symbol="GOLD", side="buy",
        volume=0.02, open_time="2026-10-07T10:00:00+00:00",
        open_price=pos.open_price, open_mid=pos.open_price, open_spread=0.6,
        stop_loss=pos.stop_loss, broker_ticket=pos.ticket, strategie="scalp",
    ))
    return coordinator, venue, pos


def test_bijkoop_wordt_een_eigen_trade(tmp_path, monkeypatch):
    coordinator, venue, pos = _met_positie(tmp_path, monkeypatch)
    venue.move(5.0)                                   # ~2,3 x ATR winst
    quote = asyncio.run(venue.quote())
    asyncio.run(coordinator._consider_pyramid(pos, quote, pos.ticket))
    assert len(venue._positions) == 2, "er is bijgekocht"
    bij = coordinator.db.bijkopen_van(pos.ticket)
    assert len(bij) == 1
    assert bij[0].open_reason == f"pyramide van {pos.ticket}"
    assert abs(bij[0].stop_loss - venue._positions[-1].stop_loss) < 0.01
    # de verplaatste stop ook in de administratie
    oud = coordinator.db.open_trades_by_tickets([pos.ticket])[0]
    assert oud.stop_loss == pos.stop_loss and oud.stop_loss > pos.open_price - 4.0
    # een bijkoop piramidet zelf niet verder
    assert asyncio.run(coordinator._is_bijkoop(bij[0].broker_ticket))
    assert not asyncio.run(coordinator._is_bijkoop(pos.ticket))


def test_telling_overleeft_een_herstart(tmp_path, monkeypatch):
    coordinator, venue, pos = _met_positie(tmp_path, monkeypatch)
    venue.move(5.0)
    asyncio.run(coordinator._consider_pyramid(pos, asyncio.run(venue.quote()), pos.ticket))
    coordinator._pyramid_state.clear()                 # "herstart"
    venue.move(0.5)                                    # te weinig afstand
    asyncio.run(coordinator._consider_pyramid(pos, asyncio.run(venue.quote()), pos.ticket))
    assert len(coordinator.db.bijkopen_van(pos.ticket)) == 1
    assert coordinator._pyramid_state[pos.ticket]["additions"] == 1


def test_bij_combinatie_draagt_de_bijkoop_de_strategie(tmp_path, monkeypatch):
    coordinator, venue, pos = _met_positie(tmp_path, monkeypatch)
    coordinator._strategie = STRATEGIE_COMBINATIE
    venue.move(5.0)
    asyncio.run(coordinator._consider_pyramid(pos, asyncio.run(venue.quote()), pos.ticket))
    assert coordinator.db.bijkopen_van(pos.ticket)[0].strategie == "scalp"
