"""Fase 0: de backtest geeft de strategie hetzelfde begrensde venster als live.

De backtest gaf de strategie bij elke bar de volledige historie tot dan toe.
Live kreeg een begrensd venster. Gevolg: kwadratische looptijd (2.000 bars 12
seconden, 4.000 bars 51), en een ander startpunt voor EMA's en ATR dan live.
"""
import asyncio
import inspect
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.analysis import backtest as bt
from gold_scalper.broker.exits import ExitConfig
from gold_scalper.broker.simulator import SimulatorVenue
from gold_scalper.const import STRATEGY_WINDOW_BARS, WARMUP_CANDLES
from gold_scalper.strategy.scalping import ScalpConfig

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _bars(n, seed=11):
    return asyncio.run(SimulatorVenue(seed=seed).candles("XAU_USD", "15m", n))


def _cfg():
    return ScalpConfig(entry_threshold=0.45, take_profit_atr=1.5,
                       stop_loss_atr=1.0, volume=0.02, max_spread_atr_ratio=0.75)


def _vensters(monkeypatch, candles):
    """Welke vensters kreeg de strategie, bij welke bar?"""
    gezien = []
    echt = bt.evaluate

    def opnemen(window, *args, **kwargs):
        gezien.append((len(window), window.timestamp[0], window.timestamp[-1]))
        return echt(window, *args, **kwargs)

    monkeypatch.setattr(bt, "evaluate", opnemen)
    bt.run_backtest(candles, _cfg(), ExitConfig(), spread=0.7, units=2.0)
    return gezien


def test_one_definition_for_live_and_backtest():
    """Geen losse WARMUP_CANDLES * 2 meer: live en backtest lezen dezelfde
    constante, en die heeft dezelfde waarde als voorheen."""
    assert STRATEGY_WINDOW_BARS == WARMUP_CANDLES * 2 == 800
    coord = (PKG / "coordinator.py").read_text(encoding="utf-8")
    back = (PKG / "analysis" / "backtest.py").read_text(encoding="utf-8")
    assert "WARMUP_CANDLES * 2" not in coord
    assert coord.count("STRATEGY_WINDOW_BARS") >= 3
    assert "STRATEGY_WINDOW_BARS" in back


def test_the_window_is_exactly_the_live_window(monkeypatch):
    """Bij bar i: de laatste STRATEGY_WINDOW_BARS bars t/m i - precies wat de
    live-lus uit zijn afgesloten bars geeft."""
    c = _bars(1400)
    index = {ts: i for i, ts in enumerate(c.timestamp)}
    for lengte, eerste, laatste in _vensters(monkeypatch, c):
        i = index[laatste]
        assert lengte == min(i + 1, STRATEGY_WINDOW_BARS)
        assert eerste == c.timestamp[max(0, i + 1 - STRATEGY_WINDOW_BARS)]


def test_never_unbounded(monkeypatch):
    c = _bars(1400)
    assert max(l for l, *_ in _vensters(monkeypatch, c)) <= STRATEGY_WINDOW_BARS


def test_no_information_from_after_the_decision(monkeypatch):
    """De laatste bar in het venster is de beslisbar; de volgende bestond nog
    niet."""
    c = _bars(900)
    index = {ts: i for i, ts in enumerate(c.timestamp)}
    for _, _, laatste in _vensters(monkeypatch, c):
        i = index[laatste]
        assert i < len(c) - 1
        assert laatste < c.timestamp[i + 1]


def test_runtime_grows_linearly():
    """Kwadratisch: verdubbelen kost vier keer zoveel. Lineair: twee keer."""
    klein, groot = _bars(1500), _bars(3000)
    t = time.perf_counter()
    bt.run_backtest(klein, _cfg(), ExitConfig(), spread=0.7, units=2.0)
    t_klein = time.perf_counter() - t
    t = time.perf_counter()
    bt.run_backtest(groot, _cfg(), ExitConfig(), spread=0.7, units=2.0)
    t_groot = time.perf_counter() - t
    # Van 1.500 naar 3.000 bars: van de 1.200 geëvalueerde bars naar 2.700.
    # Lineair ~2,3x; kwadratisch zou ~4x of meer zijn.
    assert t_groot / t_klein < 3.2, f"{t_groot / t_klein:.1f}x"


def test_warm_up_bars_open_no_trades():
    c = _bars(1200)
    r = bt.run_backtest(c, _cfg(), ExitConfig(), spread=0.7, units=2.0)
    assert r.trades
    assert min(t.opened_at for t in r.trades) >= c.timestamp[bt.WARMUP_BARS]


def test_the_dead_parameter_is_gone_loudly():
    """Wie bar_seconds nog meegeeft, krijgt een fout - geen stille negeerpost."""
    assert "bar_seconds" not in inspect.signature(bt.run_backtest).parameters
    with pytest.raises(TypeError):
        bt.run_backtest(_bars(400), _cfg(), bar_seconds=900)


def test_the_services_still_call_it_correctly():
    init = (PKG / "__init__.py").read_text(encoding="utf-8")
    assert "bar_seconds" not in init
    assert init.count("run_backtest, candles, coordinator.strategy_cfg,") == 2


def test_the_result_carries_provenance_and_fidelity():
    s = bt.run_backtest(_bars(1200), _cfg(), ExitConfig(), spread=0.7,
                        units=2.0).summary()
    assert s["provenance"]["engine_version"] == bt.BACKTEST_ENGINE_VERSION == 4
    assert s["provenance"]["strategy_window_bars"] == STRATEGY_WINDOW_BARS
    f = s["fidelity"]
    assert f["simulation_model"] == "BAR_ONLY"
    assert f["intrabar_data_available"] is False
    assert f["intrabar_assumption"] == "stop eerst"
    assert f["source_bar_seconds"] == 900
    assert "ambiguous_exits" in f and f["known_limitations"]


def test_ambiguous_exits_are_counted():
    """Raken stop en doel dezelfde bar, dan telt de stop - en dat wordt
    geteld, zodat zichtbaar is hoeveel trades op die aanname rusten."""
    from gold_scalper.analysis.signals import Candles

    c = _bars(900)
    # een reeks met enorme bars zodat stop en doel steeds in dezelfde bar vallen
    wild = Candles(
        list(c.timestamp), list(c.open),
        [h + 60 for h in c.high], [l - 60 for l in c.low],
        list(c.close), list(c.volume),
    )
    # Vaste afstanden, anders groeien stop en doel met de ATR van de brede
    # bars mee en raakt geen van beide.
    vast = ScalpConfig(entry_threshold=0.45, take_profit_usd=3.0,
                       stop_loss_usd=3.0, volume=0.02, max_spread_atr_ratio=0.75)
    r = bt.run_backtest(wild, vast, ExitConfig(), spread=0.7, units=2.0)
    assert r.trades and r.ambiguous_exits > 0
    assert all(t.reason == "stop_loss" for t in r.trades[:r.ambiguous_exits]) or \
        sum(t.reason == "stop_loss" for t in r.trades) >= r.ambiguous_exits


#: Simulatordata via venue.candles() met absolute toetsen: vaste klok, zodat de
#: uitkomst niet afhangt van het moment waarop de test draait.
pytestmark = pytest.mark.usefixtures("vaste_klok")
