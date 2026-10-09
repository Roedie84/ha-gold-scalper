"""1.9.2: schaduwtrades krijgen dezelfde grootte als een echte order."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.broker.adapter import VenueQuote  # noqa: E402
from gold_scalper.storage.database import TradeDatabase  # noqa: E402
from gold_scalper.strategy.sizing import position_size  # noqa: E402

from test_broker_cycle import ScriptedVenue, _coordinator  # noqa: E402


def _quote():
    return VenueQuote(bid=2400.0, ask=2400.4, time=datetime.now(timezone.utc))


def test_schaduwgrootte_negeert_brokerequity(tmp_path, monkeypatch):
    coordinator = _coordinator(ScriptedVenue(), tmp_path, monkeypatch)[0]
    coordinator.paper = None  # brokerpad: echte orders op het startsaldo
    coordinator.sizing = replace(
        coordinator.sizing, risk_based=True, risk_per_trade_pct=0.5,
        max_units=1000.0, min_units=0.01, account_to_instrument=None,
    )
    signaal = SimpleNamespace(direction=1, stop_loss=2396.4, score=0.6)
    q = _quote()
    verwacht = position_size(
        coordinator.sizing, coordinator.starting_balance, q.ask,
        signaal.stop_loss, signaal.score, coordinator.strategy_cfg.entry_threshold,
    ).units
    # IG-demo: ~10 miljoen equity mag de grootte niet opblazen.
    assert coordinator._grootte(signaal, q, 9_999_922.0) == float(verwacht)
    assert coordinator._grootte(signaal, q, None) == float(verwacht)


def test_oude_schaduwtrades_vervallen_eenmalig(tmp_path):
    pad = tmp_path / "s.db"
    db = TradeDatabase(pad)
    db.connect()
    db._conn.execute("DELETE FROM meta WHERE key='schaduw_grootte_192'")
    for status in ("gesloten", "open"):
        db._conn.execute(
            "INSERT INTO schaduw_trades (run_id, richting, open_time, open_price,"
            " open_mid, open_spread, units, reden, status) VALUES"
            " (1, 1, '2026-10-09T10:00:00+00:00', 1, 1, 0.4, 100, 'cooldown', ?)",
            (status,),
        )
    db._conn.commit()
    db._conn.close()

    db = TradeDatabase(pad)
    db.connect()
    rijen = db.schaduw_trades(1)
    assert {r["status"] for r in rijen} == {"vervallen"}
    # Nieuwe schaduwtrades na de vlag blijven staan.
    db._conn.execute(
        "INSERT INTO schaduw_trades (run_id, richting, open_time, open_price,"
        " open_mid, open_spread, units, reden, status) VALUES"
        " (1, 1, '2026-10-09T11:00:00+00:00', 1, 1, 0.4, 1, 'cooldown', 'gesloten')"
    )
    db._conn.commit()
    db._conn.close()
    db = TradeDatabase(pad)
    db.connect()
    assert sorted(r["status"] for r in db.schaduw_trades(1)) == [
        "gesloten", "vervallen", "vervallen"]
