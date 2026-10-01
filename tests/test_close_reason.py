"""Sluitredenen niet-destructief en op bewijs.

Een correctie overschreef de sluitreden met `broker_gesloten_gecorrigeerd`.
Of de positie op zijn stop of zijn doel sloot, ging verloren, en de gemelde
14,6% doeltreffers was een ondergrens zonder dat het rapport dat zei.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.learning.exit_stats import (
    derive_close_reason, effective_reason, exit_stats,
)
from gold_scalper.storage.database import Trade, TradeDatabase


def _trade(run, reason, close_price=4310.88, tp=4310.88, sl=4330.0, n=0):
    return Trade(
        run_id=run, mode="demo", symbol="GOLD", side="sell", volume=0.0176,
        open_time=f"2026-09-28T1{n}:00:00+00:00", open_price=4319.64,
        open_mid=4319.9, open_spread=0.6,
        close_time=f"2026-09-28T1{n}:30:00+00:00", close_price=close_price,
        net_pnl=5.0, gross_pnl=6.0, total_cost=1.0,
        take_profit=tp, stop_loss=sl, close_reason=reason,
    )


# ---------------- bewijs ----------------

def test_a_target_is_proven_by_the_exit_price():
    r = derive_close_reason(4310.88, 4310.88, 4330.0, stop_trusted=False)
    assert r.reden == "take_profit" and "doel" in r.bewijs


def test_an_untrusted_stop_is_not_proof():
    """Tot 5.3.3 werd een verplaatste stop niet teruggeschreven."""
    r = derive_close_reason(4330.0, 4310.88, 4330.0, stop_trusted=False)
    assert r.reden == "unknown" and "verouderd" in r.bewijs


def test_a_trusted_stop_is_proof():
    r = derive_close_reason(4330.0, 4310.88, 4330.0, stop_trusted=True)
    assert r.reden == "stop_loss"


def test_no_match_is_unknown_not_guessed():
    r = derive_close_reason(4318.0, 4310.88, 4330.0, stop_trusted=True)
    assert r.reden == "unknown"


# ---------------- niet-destructief ----------------

def test_update_never_overwrites_the_original(tmp_path):
    db = TradeDatabase(tmp_path / "c.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    t = _trade(run, "stop_loss")
    t.original_close_reason = "stop_loss"
    db.insert_trade(t)

    geladen = db.closed_trades(run)[0]
    geladen.original_close_reason = None          # object zonder waarde
    geladen.close_reason = "broker_gesloten_gecorrigeerd"
    db.update_trade(geladen)
    assert db.closed_trades(run)[0].original_close_reason == "stop_loss"

    geladen.original_close_reason = "iets anders"
    db.update_trade(geladen)
    assert db.closed_trades(run)[0].original_close_reason == "stop_loss"


def test_recheck_does_not_touch_the_original(tmp_path):
    db = TradeDatabase(tmp_path / "r.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    t = _trade(run, "broker_gesloten_gecorrigeerd")
    t.original_close_reason = "broker_gesloten_geschat"
    t.reconciliation_status = "reconciled"
    db.insert_trade(t)
    assert db.mark_for_recheck(run) == 1
    terug = db.closed_trades(run)[0]
    assert terug.reconciliation_status == "pending"
    assert terug.original_close_reason == "broker_gesloten_geschat"
    assert terug.close_reason == "broker_gesloten_gecorrigeerd"


# ---------------- migratie ----------------

def test_migration_of_historical_reasons(tmp_path):
    """Gecorrigeerd: oorspronkelijk onbekend, doeltreffer alleen met bewijs,
    stoptreffer nooit. Idempotent."""
    pad = tmp_path / "oud.db"
    db = TradeDatabase(pad)
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    db.insert_trade(_trade(run, "broker_gesloten_gecorrigeerd", 4310.88, n=1))  # op doel
    db.insert_trade(_trade(run, "broker_gesloten_gecorrigeerd", 4330.0, n=2))   # op stop
    db.insert_trade(_trade(run, "broker_gesloten_gecorrigeerd", 4318.0, n=3))   # nergens
    db.insert_trade(_trade(run, "take_profit", n=4))
    db.close()

    conn = sqlite3.connect(pad)
    conn.execute("UPDATE trades SET original_close_reason=NULL, reconciled_close_reason=NULL, "
                 "reconciliation_status=NULL, close_reason_source=NULL, close_reason_evidence=NULL")
    conn.commit()
    conn.close()

    for _ in range(2):
        db = TradeDatabase(pad)
        db.connect()
        trades = sorted(db.closed_trades(run), key=lambda t: t.open_time)
        assert [t.original_close_reason for t in trades] == ["unknown", "unknown", "unknown", "take_profit"]
        assert [t.reconciled_close_reason for t in trades[:3]] == ["take_profit", "unknown", "unknown"]
        assert all(t.close_reason == "broker_gesloten_gecorrigeerd" for t in trades[:3])
        db.close()


# ---------------- statistiek ----------------

def test_exit_stats_show_numerator_denominator_and_unknown():
    class T:
        def __init__(self, orig, rec=None, status=None):
            self.close_time = "x"
            self.original_close_reason = orig
            self.close_reason = orig
            self.reconciled_close_reason = rec
            self.reconciliation_status = status

    trades = ([T("take_profit")] * 2 + [T("stop_loss")] * 3 + [T("timeout")]
              + [T("unknown", "take_profit", "reconciled")]
              + [T("unknown", "unknown", "reconciled")] * 3)
    s = exit_stats(trades)
    assert s["noemer"] == 10
    assert s["take_profit"] == {"n": 3, "pct": 30.0}
    assert s["stop_loss"]["n"] == 3
    assert s["eigen_exit"]["n"] == 1
    assert s["unknown"]["n"] == 3
    assert s["afgestemd"] == 4
    assert "ondergrenzen" in s["toelichting"]


def test_a_broker_label_counts_as_unknown():
    """'De broker sloot' zegt wie, niet waarom."""
    class T:
        close_time = "x"
        original_close_reason = "broker_gesloten_geschat"
        close_reason = "broker_gesloten_geschat"
        reconciled_close_reason = None
    assert effective_reason(T()) == "unknown"
