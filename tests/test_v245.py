"""2.4.5: 'Netto sinds start' over alle runs van de strategie; fijne candles."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.dashboard.broker import read_database  # noqa: E402
from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _trade(run, netto, sluit="2026-10-13T05:00:00+00:00"):
    return Trade(run_id=run, mode="demo", symbol="GOLD", side="buy", volume=0.5,
                 open_time="2026-10-13T04:00:00+00:00", open_price=4100.0,
                 open_mid=4100.0, open_spread=0.6, close_time=sluit,
                 close_price=4101.0, gross_pnl=netto + 10, total_cost=10.0, net_pnl=netto)


def test_reeks_over_runs_van_dezelfde_strategie(tmp_path):
    db = TradeDatabase(tmp_path / "t.db")
    db.connect()
    r0 = db.start_run("demo", "combinatie-1.0.0", "GOLD", {}, 1.0)
    r1 = db.start_run("demo", "veldproef-1.0.0", "GOLD", {}, 1.0)
    r2 = db.start_run("demo", "veldproef-1.0.0", "GOLD", {}, 1.0)
    db.insert_trade(_trade(r0, -500.0))                    # andere strategie: telt niet
    db.insert_trade(_trade(r1, 2448.0))                    # oude run, sloot later
    db.insert_trade(_trade(r2, -841.0))
    db.insert_trade(_trade(r2, 0.0, sluit=None))           # open
    db.record_equity(r1, 9999744.0, 9999744.0, 0, 0.0)
    db.record_equity(r2, 10001070.0, 10001255.0, 1, 0.0)
    uit = read_database(db.path, r2)["reeks"]
    assert uit["runs"] == 2 and uit["strategie"] == "veldproef-1.0.0"
    assert uit["trades"] == 2 and uit["netto"] == 1607.0
    assert uit["kosten"] == 20.0 and uit["bruto"] == 1627.0
    assert uit["open"] == 1
    assert uit["saldo_verschil"] == 1326.0


def test_paneel_en_server():
    js = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
    assert "Netto sinds start" in js and "[60, 180, 300, 900, 1800, 3600, 14400]" in js
    assert "_tfMul" not in js
    http = (PKG / "http.py").read_text(encoding="utf-8")
    assert "candles_fijn=candles_fijn" in http
    for tf in ('"1m"', '"3m"', '"5m"', '"30m"'):
        assert tf in http
