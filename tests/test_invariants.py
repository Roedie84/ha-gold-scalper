"""Invarianten over de hele keten: ledger -> prestaties -> dagen -> perioden ->
leerlaag -> live-poort.

Elke invariant hieronder was op enig moment niet waar, of is dat alleen
geworden doordat drie onderdelen elk hun eigen definitie volgden. Ze worden
getoetst op één en dezelfde tradepopulatie, zodat een verschil nooit kan
schuilen achter "dat is een andere selectie".
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.analysis.signals import Candles
from gold_scalper.broker.currency import Conversion
from gold_scalper.learning.exit_stats import exit_stats
from gold_scalper.learning.robustness import evaluate_robustness
from gold_scalper.metrics_meta import METRICS, VELDEN
from gold_scalper.storage import performance
from gold_scalper.storage.database import Trade, TradeDatabase
from gold_scalper.storage.periods import build_periods
from gold_scalper.strategy.aggregator import BAR_SECONDS, QuoteAggregator, closed_only

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
BEGIN = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)


def _populatie():
    """Veertig trades over vier dagen, met sluitingen tussen 22:00 en 24:00
    UTC, alle kostenbronnen, correcties en een deelsluiting."""
    trades = []
    bronnen = ("measured", "calculated", "assumed", "unknown")
    for i in range(40):
        open_ = BEGIN + timedelta(hours=2.4 * i)
        close = open_ + timedelta(minutes=35)
        kosten = round(0.8 + (i % 5) * 0.1, 4)
        netto = round((7.5 if i % 3 else -5.0) - kosten * 0.1, 4)
        t = Trade(
            run_id=0, mode="demo", symbol="GOLD",
            side="buy" if i % 2 else "sell", volume=0.0176,
            open_time=open_.isoformat(), open_price=4300.0 + i,
            open_mid=4300.3 + i, open_spread=0.6,
            close_time=close.isoformat(), close_price=4305.0 + i,
            net_pnl=netto, gross_pnl=round(netto + kosten, 4), total_cost=kosten,
            cost_source=bronnen[i % 4],
            close_reason="broker_gesloten_gecorrigeerd" if i % 4 == 0 else "stop_loss",
            original_close_reason="unknown" if i % 4 == 0 else "stop_loss",
            reconciliation_status="reconciled" if i % 4 == 0 else None,
            reconciled_close_reason="take_profit" if i % 8 == 0 else None,
            broker_ticket=f"T{i}" if i != 7 else "T6-deel",
        )
        trades.append(t)
    return trades


@pytest.fixture
def db(tmp_path):
    d = TradeDatabase(tmp_path / "inv.db")
    d.connect()
    run = d.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    for t in _populatie():
        t.run_id = run
        d.insert_trade(t)
    d.run_id = run
    return d


# I1 -----------------------------------------------------------------------

def test_I1_ledger_sum_equals_performance(db):
    trades = db.closed_trades(db.run_id)
    stats = performance.compute_for_run(db, db.run_id)
    assert stats["net_pnl"] == pytest.approx(sum(t.net_pnl for t in trades), abs=0.01)


# I2 -----------------------------------------------------------------------

def test_I2_gross_minus_cost_is_net(db):
    trades = db.closed_trades(db.run_id)
    for t in trades:
        assert t.gross_pnl - t.total_cost == pytest.approx(t.net_pnl, abs=1e-4)
    stats = performance.compute_for_run(db, db.run_id)
    assert stats["gross_pnl"] - stats["total_costs"] == pytest.approx(
        stats["net_pnl"], abs=0.02
    )


# I3 -----------------------------------------------------------------------

def test_I3_every_view_gives_the_same_totals(db):
    """Ledger, dagcijfers (ook de invoer van de live-poort), perioden,
    robuustheid en exitstatistiek: dezelfde populatie, dezelfde totalen."""
    trades = db.closed_trades(db.run_id)
    totaal, aantal = sum(t.net_pnl for t in trades), len(trades)

    dagen = performance.daily_breakdown(trades)
    per = build_periods(trades)
    robuust = evaluate_robustness(trades)

    assert sum(d["net_pnl"] for d in dagen) == pytest.approx(totaal, abs=0.01)
    assert sum(d["trades"] for d in dagen) == aantal
    for reeks in (per.daily, per.weekly, per.monthly):
        assert sum(b.net for b in reeks) == pytest.approx(totaal, abs=0.01)
        assert sum(b.trades for b in reeks) == aantal
    # Onder 90 trades geeft de robuustheidstoets bewust geen periodes.
    assert robuust.periods == [] or sum(p.trades for p in robuust.periods) == aantal
    assert exit_stats(trades)["noemer"] == aantal


def test_I3_robustness_periods_cover_the_whole_population():
    trades = []
    for blok in range(4):
        for t in _populatie():
            t.close_time = (datetime.fromisoformat(t.close_time)
                            + timedelta(days=5 * blok)).isoformat()
            trades.append(t)
    robuust = evaluate_robustness(trades)
    assert robuust.periods, robuust.explanation
    assert sum(p.trades for p in robuust.periods) == len(trades)
    assert sum(p.net_pnl for p in robuust.periods) == pytest.approx(
        sum(t.net_pnl for t in trades), abs=0.05
    )


def test_I3_daily_views_agree_day_by_day(db):
    trades = db.closed_trades(db.run_id)
    dagen = {d["date"]: (d["trades"], round(d["net_pnl"], 4))
             for d in performance.daily_breakdown(trades)}
    per = {b.start: (b.trades, round(b.net, 4)) for b in build_periods(trades).daily}
    assert dagen == per


# I4 -----------------------------------------------------------------------

def test_I4_no_trade_counted_twice(db):
    trades = db.closed_trades(db.run_id)
    assert len({t.id for t in trades}) == len(trades)
    assert sum(d["trades"] for d in performance.daily_breakdown(trades)) == len(trades)


# I5 -----------------------------------------------------------------------

def test_I5_conversion_round_trips():
    c = Conversion("USD", "EUR", 0.8697)
    for bedrag in (-10.0, 0.0, 13.41):
        assert c.to_instrument(c.to_account(bedrag)) == pytest.approx(bedrag)


def test_I5_account_amount_uses_the_current_rate():
    from gold_scalper.coordinator import GoldScalperCoordinator

    class Stub:
        conversion = Conversion(
            "USD", "EUR", 0.8697,
            rate_timestamp=datetime(2026, 9, 28, tzinfo=timezone.utc),
            rate_source="ig_market",
        )

    t = Trade(run_id=1, mode="demo", symbol="GOLD", side="buy", volume=0.01,
              open_time="x", open_price=1, open_mid=1, open_spread=0.6, net_pnl=10.0)
    GoldScalperCoordinator._record_account_amount(Stub(), t)
    assert t.net_pnl_account == pytest.approx(8.697)
    assert (t.account_currency, t.fx_source) == ("EUR", "ig_market")


def test_I5_sizing_uses_the_conservative_rate():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    blok = bron.split("def _apply_rate")[1].split("\n    async def ")[0]
    assert "self.sizing.account_to_instrument = 1.0 / huidig.risk_rate" in blok


# I6 -----------------------------------------------------------------------

def test_I6_restart_duplicates_nothing(db, tmp_path):
    voor = db.ledger_costs(db.run_id)
    pad = db.path
    db.close()
    for _ in range(3):
        d = TradeDatabase(pad)
        d.connect()
        assert d.ledger_costs(d.list_runs(1)[0]["id"]) == voor
        d.close()


def test_I6_reconciliation_duplicates_nothing(db):
    voor = (len(db.closed_trades(db.run_id)), db.ledger_costs(db.run_id)["total"])
    for _ in range(3):
        db.mark_for_recheck(db.run_id)
        db.detect_mixed_runs()
    na = (len(db.closed_trades(db.run_id)), db.ledger_costs(db.run_id)["total"])
    assert voor == na


# I7 -----------------------------------------------------------------------

def test_I7_the_aggregator_never_hands_out_the_forming_bar():
    agg = QuoteAggregator("15m")
    t0 = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
    for sec in range(0, 900 * 3, 30):
        agg.add(4300.0 + sec / 100, t0 + timedelta(seconds=sec))
    c = agg.candles()
    assert c.timestamp[-1] + 900 <= int((t0 + timedelta(seconds=900 * 3)).timestamp())


def test_I7_a_forming_broker_bar_is_dropped():
    """IG geeft de lopende bar mee. Die ging erin, en de afgeronde versie werd
    daarna overgeslagen omdat die tijdstempel al gezien was."""
    nu = 1_790_000_000
    begin = (nu // 900) * 900
    c = Candles(
        [begin - 1800, begin - 900, begin],
        [1, 2, 3], [1, 2, 3], [1, 2, 3], [1, 2, 3], [1, 1, 1],
    )
    gesloten = closed_only(c, nu, "15m")
    assert gesloten.timestamp == [begin - 1800, begin - 900]
    assert closed_only(c, begin + 900, "15m").timestamp == c.timestamp


def test_I7_the_broker_path_and_warm_up_use_closed_only():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    pad = bron.split("async def _maybe_update_candles")[1].split("\n    async def ")[0]
    opwarmen = bron.split("async def _fetch_warmup")[1].split("\n    async def ")[0]
    assert "closed_only(" in pad and "closed_only(" in opwarmen


def test_I7_the_next_bar_is_due_after_two_lengths():
    """Zonder dit vroeg de lus na de reparatie een kwartier lang elke cyclus
    historie op - het quotum van de broker loopt dan leeg."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    blok = bron.split("def _bar_due")[1].split("\n    async def ")[0]
    assert "2 * length + 3" in blok
    assert BAR_SECONDS["15m"] == 900


# I8 -----------------------------------------------------------------------

def test_I8_reconciliation_keeps_the_original_reason(db):
    t = db.closed_trades(db.run_id)[1]
    oorspronkelijk = t.original_close_reason
    t.original_close_reason = None
    t.reconciled_close_reason = "take_profit"
    t.reconciliation_status = "reconciled"
    db.update_trade(t)
    db.mark_for_recheck(db.run_id)
    assert db.closed_trades(db.run_id)[1].original_close_reason == oorspronkelijk


# I9 -----------------------------------------------------------------------

def test_I9_every_metric_has_population_currency_timezone_denominator():
    for naam, meta in METRICS.items():
        for veld in VELDEN:
            assert meta.get(veld), f"{naam} mist {veld}"


def test_I9_reported_metrics_are_defined():
    """Elke kernmetriek die de diagnostiek meldt, heeft een definitie."""
    for naam in ("net_pnl", "gross_pnl", "total_costs", "win_rate",
                 "t_statistic", "max_drawdown_pct", "daily", "periods",
                 "exit_stats", "ledger_costs", "effective_equity_floor",
                 "sessions"):
        assert naam in METRICS, naam


def test_I9_daily_metrics_name_the_trading_timezone():
    assert "Europe/Amsterdam" in METRICS["daily"]["tijdzone"]
    assert "UTC" in METRICS["sessions"]["tijdzone"]
