"""Kostenbron: uit het ledger, met herkomst.

De kostenlijn in het rapport kwam uit de papersimulatie. In demomodus bestaat
die niet, en stond de lijn altijd op nul - terwijl de grafiek belooft dat je
eraan ziet of de broker meer verdient dan jij.
"""
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.storage.database import Trade, TradeDatabase

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _db(tmp_path):
    db = TradeDatabase(tmp_path / "k.db")
    db.connect()
    return db, db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")


def _trade(run, cost, bron, n=0):
    return Trade(
        run_id=run, mode="demo", symbol="GOLD", side="sell", volume=0.0176,
        open_time=f"2026-09-28T1{n}:00:00+00:00", open_price=4300.0,
        open_mid=4300.3, open_spread=0.6,
        close_time=f"2026-09-28T1{n}:20:00+00:00", net_pnl=5.0,
        gross_pnl=None if cost is None else 5.0 + cost,
        total_cost=cost, cost_source=bron,
    )


def test_ledger_costs_in_demo_are_not_zero(tmp_path):
    db, run = _db(tmp_path)
    db.insert_trade(_trade(run, 1.20, "measured", 1))
    db.insert_trade(_trade(run, 0.90, "calculated", 2))
    kosten = db.ledger_costs(run)
    assert kosten["total"] == pytest.approx(2.10)
    assert kosten["measured"] == 1


def test_the_provenance_is_counted(tmp_path):
    """Hoeveel van de kosten werkelijk gemeten zijn, staat naast het totaal."""
    db, run = _db(tmp_path)
    for n, (kosten, bron) in enumerate([(1.2, "measured"), (0.9, "calculated"),
                                         (0.5, "assumed"), (0.7, "unknown")]):
        db.insert_trade(_trade(run, kosten, bron, n))
    telling = db.ledger_costs(run)
    assert (telling["measured"], telling["calculated"],
            telling["assumed"], telling["unknown"]) == (1, 1, 1, 1)
    assert telling["total"] == pytest.approx(3.3)


def test_the_equity_line_uses_the_ledger():
    """Niet de paperbroker: die bestaat in demo niet."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "self.paper.cumulative_cost if self.paper else 0.0" not in bron
    assert "await self._ledger_cost()" in bron


def test_a_settlement_is_calculated_not_measured():
    """Een positie die de broker sloot, wordt afgerekend op prijzen van
    verschillende momenten. Die kosten zijn berekend."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    blok = bron.split("async def _record_broker_close")[1].split("\n    async def ")[0]
    assert '"calculated" if afwikkeling else "measured"' in blok


def test_old_trades_become_unknown(tmp_path):
    """Migratie: van oude trades is niet meer vast te stellen of hun kosten
    gemeten waren. Idempotent - een tweede keer verbinden verandert niets."""
    pad = tmp_path / "oud.db"
    db = TradeDatabase(pad)
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    db.insert_trade(_trade(run, 1.0, None, 1))
    db.close()

    conn = sqlite3.connect(pad)
    conn.execute("UPDATE trades SET cost_source=NULL")
    conn.commit()
    conn.close()

    for _ in range(2):
        db = TradeDatabase(pad)
        db.connect()
        assert db.closed_trades(run)[0].cost_source == "unknown"
        db.close()


def test_the_report_does_not_show_unknown_as_zero():
    from gold_scalper.dashboard.report import _fmt_kosten

    assert _fmt_kosten(None, "unknown") == "onbekend"
    assert _fmt_kosten(1.2, "measured") == "1.20"
    assert _fmt_kosten(1.2, "calculated") == "1.20*"
    assert _fmt_kosten(1.2, "unknown") == "1.20?"
