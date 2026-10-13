"""2.4.3: afstemming met de broker over alle runs binnen het venster."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _trade(run, ticket, sluit, mode="demo"):
    return Trade(run_id=run, mode=mode, symbol="GOLD", side="buy", volume=0.01,
                 open_time="2026-10-12T10:00:00+00:00", open_price=4100.0,
                 open_mid=4100.0, open_spread=0.6, close_time=sluit,
                 close_price=4101.0, net_pnl=0.4, broker_ticket=ticket)


def test_gesloten_trades_sinds_over_alle_runs(tmp_path):
    db = TradeDatabase(tmp_path / "t.db")
    db.connect()
    r1 = db.start_run("demo", "v", "GOLD", {}, 1.0, None, "a")
    r2 = db.start_run("demo", "v", "GOLD", {}, 1.0, None, "b")
    db.insert_trade(_trade(r1, "A", "2026-10-12T20:00:00+00:00"))
    db.insert_trade(_trade(r2, "B", "2026-10-13T05:00:00+00:00"))
    db.insert_trade(_trade(r1, "OUD", "2026-10-01T05:00:00+00:00"))
    db.insert_trade(_trade(r1, "PAPIER", "2026-10-12T21:00:00+00:00", mode="paper"))
    gevonden = [t.broker_ticket for t in db.closed_trades_since("2026-10-10T00:00:00+00:00", "demo")]
    assert gevonden == ["A", "B"]


def test_afstemming_gebruikt_alle_runs():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    i = bron.index("async def _stem_af_met_broker")
    stuk = bron[i:i + 1500]
    assert "self.db.closed_trades_since" in stuk
    assert "self.db.closed_trades, self.run_id" not in stuk
