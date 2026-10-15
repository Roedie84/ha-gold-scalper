"""2.5.6: bewezen verliezende veldproefopzetten (n >= 100, t < -2) gaan uit."""
from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.const import INTEGRATION_VERSION  # noqa: E402
from gold_scalper.strategy import veldproef as V  # noqa: E402
from gold_scalper.strategy.scalping import ScalpConfig  # noqa: E402


def test_versie():
    assert tuple(map(int, INTEGRATION_VERSION.split("."))) >= tuple(map(int, "2.5.6".split(".")))
    assert V.VELDPROEF_VERSIE >= "veldproef-1.6.0"


def _reeks(n, gem, spreiding=30.0):
    return [gem + (spreiding if i % 2 else -spreiding) for i in range(n)]


def test_t_statistiek():
    assert V.t_statistiek([]) == 0.0
    assert V.t_statistiek([5.0]) == 0.0
    assert V.t_statistiek([1.0, 1.0, 1.0]) == 0.0
    assert V.t_statistiek(_reeks(100, -10.0)) < -2


def test_uitzetten_alleen_bij_genoeg_trades_en_t_onder_grens():
    per = {
        "vp:rsi_rev:1m": _reeks(100, -10.0),     # n=100, t ~ -3,3: uit
        "vp:momentum:1m": _reeks(99, -20.0),     # te weinig trades
        "vp:donchian:15m": _reeks(150, -1.0),    # t ~ -0,4: blijft
        "vp:pullback:15m": _reeks(150, 10.0),    # winst: blijft
        "scalp": _reeks(500, -50.0),             # geen veldproef
    }
    uit = V.uitgezette_opzetten(per)
    assert set(uit) == {"vp:rsi_rev:1m"}
    assert uit["vp:rsi_rev:1m"]["n"] == 100
    assert uit["vp:rsi_rev:1m"]["t"] < -2


def test_evalueer_weigert_uitgezette_opzet():
    bars = V.MeerTijdvakken()
    uit = {"vp:rsi_rev:1m": {"n": 100, "t": -2.72}}
    sig = V.evalueer("vp:rsi_rev:1m", bars, 4186.0, 4186.4, ScalpConfig(), uitgezet=uit)
    assert not sig.should_trade
    assert sig.reject_reason == "opzet_uitgezet"
    assert sig.direction == 0
    # Andere opzetten gaan gewoon door naar hun eigen controles.
    sig2 = V.evalueer("vp:rsi_rev:3m", bars, 4186.0, 4186.4, ScalpConfig(), uitgezet=uit)
    assert sig2.reject_reason != "opzet_uitgezet"


def test_database_netto_per_strategie(tmp_path):
    from gold_scalper.storage.database import TradeDatabase
    db = TradeDatabase(str(tmp_path / "t.db"))
    db.connect()
    conn = db.conn
    conn.execute("INSERT INTO runs (started_at, mode, strategy_version, symbol, config_json, "
                 "starting_balance) VALUES ('2026-10-13', 'demo', 'x', 'G', '{}', 1)")
    rid = conn.execute("SELECT max(id) FROM runs").fetchone()[0]
    for i, (strat, pnl, dicht) in enumerate([
        ("vp:rsi_rev:1m", -5.0, "t1"), ("vp:rsi_rev:1m", 2.0, "t2"),
        ("vp:momentum:1m", -1.0, "t3"), ("scalp", -9.0, "t4"),
        ("vp:rsi_rev:1m", -7.0, None),
    ]):
        conn.execute(
            "INSERT INTO trades (run_id, mode, symbol, side, volume, open_time, open_price, "
            "open_mid, open_spread, close_time, net_pnl, strategie) "
            "VALUES (?, 'demo', 'G', 'buy', 0.5, ?, 1, 1, 0.3, ?, ?, ?)",
            (rid, f"2026-10-13T10:0{i}", dicht, pnl, strat))
    conn.commit()
    uit = db.netto_per_strategie("vp:")
    assert uit == {"vp:rsi_rev:1m": [-5.0, 2.0], "vp:momentum:1m": [-1.0]}
