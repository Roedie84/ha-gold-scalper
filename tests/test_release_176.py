"""1.7.6: alleen statistiek en rapportage.

1. Uitstapregime per trade. Sinds 1.7.4 vuren de tijdstops op IG; binnen
   dezelfde run zijn er dus twee uitstapgedragingen. Elke trade krijgt het
   regime waaronder hij opende, bestaande trades worden aangevuld, en de
   kerncijfers per regime staan als attribuut op het oordeel - zonder dat het
   oordeel zelf verandert.
2. Latency p99. De steekproef begon na elke herstart opnieuw, waardoor één
   uitschieter de p99 bepaalde. Nu bewaard (begrensd) en onder de 1000
   metingen als indicatief gemarkeerd. Wat er gemeten wordt, verandert niet.

Strategie, in- en uitstap, risicolimieten, parameters, standaardwaarden,
positiegrootte en vingerafdruk zijn niet aangeraakt.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))
sys.path.insert(0, HIER)

from gold_scalper import const  # noqa: E402
from gold_scalper.storage import performance  # noqa: E402
from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402
from gold_scalper.storage.latency import (  # noqa: E402
    LATENCY_VENSTER, P99_BETROUWBAAR_VANAF, LatencyBudget, LatencyTracker,
)

from test_broker_cycle import FakeHass, ScriptedVenue  # noqa: E402
from test_release_175 import _bouw, _start, _stop  # noqa: E402

PKG = Path(HIER).parent / "custom_components" / "gold_scalper"
GRENS = datetime.fromisoformat(const.EXIT_REGIME_GRENS_UTC)


def _trade(run, open_time, mode="demo", net=1.0, close_offset_s=60, **kw):
    velden = dict(
        run_id=run, mode=mode, symbol="GOLD", side="buy", volume=0.10,
        open_time=open_time.isoformat(), open_price=4400.3, open_mid=4400.0,
        open_spread=0.6,
        close_time=(open_time + timedelta(seconds=close_offset_s)).isoformat(),
        close_price=4401.0, net_pnl=net,
        gross_pnl=None if net is None else net + 0.5, total_cost=0.5,
    )
    velden.update(kw)
    return Trade(**velden)


# --------------------------------------------------------------------------
# Versie
# --------------------------------------------------------------------------


def test_grens_is_the_174_install_moment():
    assert GRENS == datetime(2026, 10, 8, 10, 16, tzinfo=timezone.utc)
    assert const.EXIT_REGIME_HUIDIG == const.EXIT_REGIME_TIJDSTOP == "tijdstop"
    assert const.EXIT_REGIME_ZONDER_TIJDSTOP == "zonder_tijdstop"


# --------------------------------------------------------------------------
# 1. Uitstapregime: kolom, migratie, aanvulling
# --------------------------------------------------------------------------


def _oude_database(pad: Path) -> None:
    """Een database zoals 1.7.5 hem achterliet: zonder exit_regime."""
    db = TradeDatabase(pad)
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    db.conn.execute("ALTER TABLE trades DROP COLUMN exit_regime")
    db.conn.commit()
    voor = GRENS - timedelta(hours=1)
    na = GRENS + timedelta(minutes=5)
    rijen = [
        # brokertrade vóór de grens, met microseconden zoals IG ze geeft
        ("demo", (voor + timedelta(microseconds=123456)).isoformat(), "T1"),
        # brokertrade één seconde vóór de grens
        ("demo", (GRENS - timedelta(seconds=1)).isoformat(), "T2"),
        # brokertrade precies op en na de grens
        ("demo", GRENS.isoformat(), "T3"),
        ("live", na.isoformat(), "T4"),
        # papertrade vóór de grens: had altijd een openingstijd
        ("paper", voor.isoformat(timespec="seconds"), None),
        # brokertrade zonder leesbare openingstijd
        ("demo", "onleesbaar", "T6"),
    ]
    for mode, open_time, ticket in rijen:
        db.conn.execute(
            "INSERT INTO trades (run_id, mode, symbol, side, volume, open_time, "
            "open_price, open_mid, open_spread, broker_ticket) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run, mode, "GOLD", "buy", 0.1, open_time, 4400.0, 4400.0, 0.6, ticket),
        )
    db.conn.commit()
    db.close()


def _regimes(pad: Path) -> dict:
    conn = sqlite3.connect(pad)
    uit = {
        (mode, ticket): regime
        for mode, ticket, regime in conn.execute(
            "SELECT mode, broker_ticket, exit_regime FROM trades"
        )
    }
    conn.close()
    return uit


def test_migration_adds_the_column_and_backfills(tmp_path):
    pad = tmp_path / "oud.db"
    _oude_database(pad)
    db = TradeDatabase(pad)
    db.connect()
    kolommen = {r["name"] for r in db.conn.execute("PRAGMA table_info(trades)")}
    assert "exit_regime" in kolommen
    db.close()

    assert _regimes(pad) == {
        ("demo", "T1"): "zonder_tijdstop",
        ("demo", "T2"): "zonder_tijdstop",
        ("demo", "T3"): "tijdstop",
        ("live", "T4"): "tijdstop",
        ("paper", None): "tijdstop",
        ("demo", "T6"): None,
    }


def test_backfill_is_idempotent_and_never_overwrites(tmp_path):
    pad = tmp_path / "oud.db"
    _oude_database(pad)
    db = TradeDatabase(pad)
    db.connect()
    # Een al vastgelegd regime blijft staan, ook als het "fout" lijkt.
    db.conn.execute("UPDATE trades SET exit_regime='tijdstop' WHERE broker_ticket='T1'")
    db.conn.commit()
    db.close()
    for _ in range(2):
        db = TradeDatabase(pad)
        db.connect()
        db.close()
    regimes = _regimes(pad)
    assert regimes[("demo", "T1")] == "tijdstop"
    assert regimes[("demo", "T2")] == "zonder_tijdstop"


def test_a_new_database_round_trips_the_field(tmp_path):
    db = TradeDatabase(tmp_path / "nieuw.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    t = _trade(run, GRENS + timedelta(hours=1), exit_regime="tijdstop")
    db.insert_trade(t)
    assert db.closed_trades(run)[0].exit_regime == "tijdstop"
    db.close()


def test_paper_trades_get_the_current_regime(tmp_path):
    from gold_scalper.broker.paper import PaperBroker, Quote

    db = TradeDatabase(tmp_path / "paper.db")
    db.connect()
    run = db.start_run("paper", "v1", "GOLD", {}, 10000.0, None, "fp")
    broker = PaperBroker(db, run, "GOLD", seed=1)
    quote = Quote(bid=4400.0, ask=4400.3, time=datetime.now(timezone.utc))
    trade = broker.open_position("buy", 0.01, quote, stop_loss=4390.0)
    assert trade.exit_regime == "tijdstop"
    rij = db.conn.execute(
        "SELECT exit_regime FROM trades WHERE id=?", (trade.id,)
    ).fetchone()
    assert rij[0] == "tijdstop"
    db.close()


def test_broker_opens_and_partials_carry_the_regime():
    """Broker-instap zet het huidige regime; een deelsluiting erft het."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    boom = ast.parse(bron)
    gevonden = {}
    for node in ast.walk(boom):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in (
            "_record_broker_open", "_record_partial_close",
        ) or (isinstance(node, ast.AsyncFunctionDef) and "part = Trade(" in (
            ast.get_source_segment(bron, node) or ""
        )):
            gevonden[node.name] = ast.get_source_segment(bron, node)
    assert "exit_regime=EXIT_REGIME_HUIDIG" in gevonden["_record_broker_open"]
    deel = [s for s in gevonden.values() if "part = Trade(" in s]
    assert deel and "exit_regime=trade.exit_regime" in deel[0]


# --------------------------------------------------------------------------
# 1b. Statistiek per regime, oordeel ongewijzigd
# --------------------------------------------------------------------------


def _reeks(run=1):
    """Twee regimes met elk eigen clusters."""
    trades = []
    start_oud = GRENS - timedelta(days=1)
    # zonder tijdstop: 3 clusters (ver uit elkaar), 2 trades per cluster
    for c, netten in enumerate(((5.0, -1.0), (-3.0, -2.0), (4.0, 1.0))):
        basis = start_oud + timedelta(hours=c * 2)
        for i, n in enumerate(netten):
            trades.append(_trade(
                run, basis + timedelta(minutes=2 * i), net=n,
                exit_regime="zonder_tijdstop",
            ))
    start_nieuw = GRENS + timedelta(hours=1)
    for c, n in enumerate((2.0, -1.0, 3.0, 1.5)):
        trades.append(_trade(
            run, start_nieuw + timedelta(hours=c), net=n, exit_regime="tijdstop",
        ))
    trades.append(_trade(run, start_nieuw + timedelta(days=1), net=-0.5))
    return trades


def test_per_exitregime_figures():
    uit = performance.per_exitregime(_reeks())
    assert set(uit) == {"zonder_tijdstop", "tijdstop", "onbekend"}

    oud = uit["zonder_tijdstop"]
    assert oud["trades"] == 6 and oud["clusters"] == 3
    assert oud["netto_usd"] == 4.0
    assert oud["netto_per_trade_usd"] == round(4.0 / 6, 4)
    assert oud["profit_factor"] == round(10.0 / 6.0, 3)
    assert oud["t_statistiek"] == round(performance._t([4.0, -5.0, 5.0]), 3)

    nieuw = uit["tijdstop"]
    assert nieuw["trades"] == 4 and nieuw["clusters"] == 4
    assert nieuw["profit_factor"] == round(6.5 / 1.0, 3)
    assert nieuw["t_statistiek"] == round(performance._t([2.0, -1.0, 3.0, 1.5]), 3)

    assert uit["onbekend"]["trades"] == 1
    assert uit["onbekend"]["profit_factor"] == 0.0      # alleen een verliezer


def test_per_exitregime_empty_and_open_trades():
    assert performance.per_exitregime([]) == {}
    open_trade = _trade(1, GRENS, net=None, exit_regime="tijdstop")
    assert performance.per_exitregime([open_trade]) == {}


def test_the_verdict_is_unchanged(tmp_path):
    db = TradeDatabase(tmp_path / "oordeel.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    for t in _reeks(run):
        db.insert_trade(t)
    trades = db.closed_trades(run)
    met = performance.compute_for_run(db, run, trades)
    zonder = performance.compute(trades, 10000.0)
    for sleutel in ("verdict", "verdict_text", "ready_for_live", "t_statistic",
                    "profit_factor", "net_pnl", "clusters", "trades"):
        assert met.get(sleutel) == zonder.get(sleutel), sleutel
    assert met["per_exitregime"] == performance.per_exitregime(trades)
    # Het oordeel kijkt niet naar het regime: zonder regimes dezelfde uitkomst.
    kaal = [Trade(**{**{f: getattr(t, f) for f in Trade.__dataclass_fields__},
                     "exit_regime": None}) for t in trades]
    assert performance.compute(kaal, 10000.0) == zonder
    db.close()


def test_verdict_sensor_exposes_per_exitregime():
    bron = (PKG / "sensor.py").read_text(encoding="utf-8")
    blok = bron[bron.index('key="verdict"'):bron.index('key="mode"')]
    assert '"per_exitregime": _stats(d).get("per_exitregime")' in blok
    # De waarde van de sensor blijft het oordeel zelf.
    assert 'value_fn=lambda d: _stats(d).get("verdict")' in blok


def test_exit_regime_is_not_in_the_fingerprint():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    boom = ast.parse(bron)
    for node in ast.walk(boom):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_fingerprint_material", "_run_config",
        ):
            segment = ast.get_source_segment(bron, node)
            assert "exit_regime" not in segment.lower()
            assert "EXIT_REGIME" not in segment
            assert "LATENCY" not in segment


def test_a_restart_keeps_the_run(tmp_path):
    hass = FakeHass()
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    run = a.run_id
    _stop(a)
    b = _start(_bouw(hass, venue, a))
    assert b.run_id == run
    _stop(b)


# --------------------------------------------------------------------------
# 2. Latency: steekproef bewaard, p99 indicatief onder 1000
# --------------------------------------------------------------------------


def _meet(tracker, waarden):
    for w in waarden:
        b = LatencyBudget()
        b.mark("start", 0.0)
        b.mark("eind", w / 1000.0)
        tracker.record(b)


def test_export_restore_round_trip_and_bound():
    a = LatencyTracker(window=LATENCY_VENSTER)
    _meet(a, range(1, 2501))
    data = a.export()
    assert len(data["total"]) == LATENCY_VENSTER == 2000

    b = LatencyTracker(window=LATENCY_VENSTER)
    _meet(b, [9999.0])                 # al gemeten in de nieuwe sessie
    b.restore(data)
    stats = b.stats()["total"]
    assert stats["samples"] == 2000
    assert stats["max"] == 9999.0      # de nieuwe meting staat achteraan
    # Tweede keer terugzetten telt niet dubbel.
    assert b.restore(data) == 0
    assert b.stats()["total"]["samples"] == 2000


def test_restore_ignores_garbage():
    t = LatencyTracker()
    assert t.restore(None) == 0
    t2 = LatencyTracker()
    assert t2.restore({"total": "x", "a": [1.0, "b", None, float("nan"), 2.0]}) == 2
    assert t2.stats()["a"]["samples"] == 2
    assert "total" not in t2.stats()


def test_what_is_measured_is_unchanged():
    """Zelfde metingen, zelfde percentielen als vóór 1.7.6."""
    t = LatencyTracker()
    _meet(t, range(1, 201))
    s = t.stats()["total"]
    assert s["samples"] == 200 and s["p90"] == 181.0 and s["p99"] == 199.0


def test_the_sample_survives_a_restart():
    hass = FakeHass()
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    assert a.latency._window == LATENCY_VENSTER
    _meet(a.latency, [10.0] * 326 + [587.0])
    _stop(a)

    b = _start(_bouw(hass, venue, a))
    totaal = b.latency.stats()["total"]
    assert totaal["samples"] >= 327
    assert totaal["max"] == 587.0
    _stop(b)


def _sensorfuncties():
    """_staart_latency en _p99_indicatief uit sensor.py, zonder HA te laden."""
    bron = (PKG / "sensor.py").read_text(encoding="utf-8")
    boom = ast.parse(bron)
    ns: dict = {}
    for node in boom.body:
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_staart_latency", "_p99_indicatief",
        ):
            code = "from __future__ import annotations\n" + ast.get_source_segment(bron, node)
            exec(compile(code, "sensor.py", "exec"), ns)  # noqa: S102
    return ns["_staart_latency"], ns["_p99_indicatief"]


def test_p99_is_marked_indicative_below_1000():
    staart, indicatief = _sensorfuncties()
    d = {"latency": {"total": {"samples": 326, "p90": 40.0, "p99": 587.0}}}
    waarde, basis = staart(d)
    assert waarde == 587.0
    assert "indicatief" in basis and "n=326" in basis
    assert indicatief(d) is True

    d = {"latency": {"total": {"samples": P99_BETROUWBAAR_VANAF - 1, "p99": 90.0}}}
    assert indicatief(d) is True and "indicatief" in staart(d)[1]

    d = {"latency": {"total": {"samples": P99_BETROUWBAAR_VANAF, "p90": 40.0, "p99": 90.0}}}
    assert staart(d) == (90.0, "p99 (n=1000)")
    assert indicatief(d) is False

    d = {"latency": {"total": {"samples": 50, "p90": 40.0}}}
    assert staart(d)[0] == 40.0
    assert indicatief(d) is None


def test_latency_sensor_exposes_n():
    bron = (PKG / "sensor.py").read_text(encoding="utf-8")
    blok = bron[bron.index('key="latency"'):]
    blok = blok[:blok.index("),\n)")]
    assert '"n":' in blok and '"p99_indicatief": _p99_indicatief(d)' in blok
