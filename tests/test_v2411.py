"""2.4.11: het paneel kent ook open trades uit een vorige run."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.dashboard import broker as B  # noqa: E402
from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402


def _trade(run, ticket, strategie, open_time):
    return Trade(run_id=run, mode="demo", symbol="GOLD", side="buy", volume=0.5,
                 open_time=open_time, open_price=4192.56, open_mid=4192.5,
                 open_spread=0.6, stop_loss=4189.88, take_profit=4199.83,
                 broker_ticket=ticket, strategie=strategie)


def test_open_trades_uit_vorige_run(tmp_path):
    db = TradeDatabase(tmp_path / "p.db")
    db.connect()
    oud = db.start_run("demo", "v1", "GOLD", {}, 1.0)
    nu = datetime.now(timezone.utc)
    db.insert_trade(_trade(oud, "VORIG", "vp:momentum:5m", nu.isoformat()))
    db.insert_trade(_trade(oud, "STOKOUD", "scalp", (nu - timedelta(days=30)).isoformat()))
    run = db.start_run("demo", "v2", "GOLD", {}, 1.0)
    db.insert_trade(_trade(run, "EIGEN", "scalp", nu.isoformat()))
    uit = B.read_database(db.path, run)
    tickets = {r["broker_ticket"]: r["strategie"] for r in uit["open"]}
    assert tickets == {"VORIG": "vp:momentum:5m", "EIGEN": "scalp"}
    assert B._strategie({"strategie": tickets["VORIG"]}, {"primaire_strategie": "daghandel"}) \
        == "vp:momentum:5m"


def test_stopverplaatsing_vastgelegd_en_in_paneel(tmp_path):
    from types import SimpleNamespace
    db = TradeDatabase(tmp_path / "s.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 1.0)
    nu = datetime.now(timezone.utc)
    db.insert_trade(_trade(run, "T1", "vp:momentum:5m", nu.isoformat()))
    db.stop_gewijzigd("T1", "2026-10-13T08:40:00+00:00", "stop naar break-even")
    db.stop_gewijzigd("T1", "2026-10-13T08:42:00+00:00", "trailing stop op 1.0xATR")
    uit = B.read_database(db.path, run)
    rij = uit["open"][0]
    assert rij["stop_wijzigingen"] == 2 and rij["stop_reden"].startswith("trailing")
    p = SimpleNamespace(ticket="T1", side="buy", units=50.0, open_price=4192.56,
                        stop_loss=4193.0, take_profit=4199.83, open_time=None)
    rows = B._position_rows({"open_positions": [p]}, uit["open"], {},
                            SimpleNamespace(bid=4194.0, ask=4194.6))
    assert rows[0]["sl_wijzigingen"] == 2
    assert rows[0]["sl_gewijzigd"] == int(datetime(2026, 10, 13, 8, 42, tzinfo=timezone.utc).timestamp())


def test_paneel_toont_stopmoment():
    pad = os.path.join(os.path.dirname(__file__), "..", "custom_components",
                       "gold_scalper", "frontend", "broker-panel.js")
    assert "p.sl_gewijzigd" in open(pad, encoding="utf-8").read()
