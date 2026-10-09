"""1.9.4: daglimiet en vermogensvloer rekenen over de startbalans.

Op de IG-demo staat ~10 miljoen bij een startbalans van 10.000. De daglimiet
(10%) en de vloer (50%) rekenden over de equity en gingen nooit af.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.risk import (  # noqa: E402
    RiskLimits, RiskManager, TradingState, risicobasis,
)

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
NU = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
DEMO = 10_000_000.0
START = 10_000.0


def _rm(dagstart: float) -> RiskManager:
    rm = RiskManager(
        RiskLimits(max_daily_loss_pct=10.0, equity_floor_pct=50.0,
                   max_open_positions=10, max_volume=100.0),
        START, now=NU,
    )
    rm.state.day_start_balance = dagstart
    return rm


def _open(rm, balance, equity, opening):
    return rm.can_open(
        NU, balance=balance, equity=equity, starting_balance=START,
        open_positions=0, volume=0.01, spread=0.3, last_tick_age=1.0,
        atr=2.0, opening_equity=opening,
    )


# ---------------- risicobasis ---------------- #

def test_risicobasis_kleinste_positieve():
    assert risicobasis(10000.0, DEMO) == 10000.0
    assert risicobasis(10000.0, 7266.0) == 7266.0


@pytest.mark.parametrize("start,ref,verwacht", [
    (None, 5000.0, 5000.0),
    (0.0, 5000.0, 5000.0),
    (10000.0, None, 10000.0),
    (10000.0, 0.0, 10000.0),
    (None, None, 0.0),
    (0.0, 0.0, 0.0),
    (-5.0, 3000.0, 3000.0),
])
def test_risicobasis_randgevallen(start, ref, verwacht):
    assert risicobasis(start, ref) == verwacht


def test_geen_basis_geen_deling_door_nul():
    rm = _rm(0.0)
    assert rm.dagverlies_pct(100.0, 100.0, None) == 0.0


# ---------------- demo: 10 miljoen ---------------- #

def test_demo_daglimiet_bij_1000_verlies():
    rm = _rm(DEMO)
    ok, reden = _open(rm, DEMO - 999.0, DEMO - 999.0, DEMO)
    assert ok, reden
    ok, reden = _open(rm, DEMO - 1000.0, DEMO - 1000.0, DEMO)
    assert not ok and reden == "daglimiet bereikt"
    assert rm.state.state is TradingState.HALTED
    assert "10.00%" in rm.state.halt_reason


def test_demo_daglimiet_ook_op_open_verlies():
    rm = _rm(DEMO)
    ok, reden = _open(rm, DEMO, DEMO - 1200.0, DEMO)
    assert not ok and reden == "daglimiet bereikt"


def test_demo_vloer_op_opening_min_5000():
    rm = _rm(DEMO)
    v = rm.floor_breakdown(START, DEMO, DEMO)
    assert v["verliesvloer"] == DEMO - 5000.0
    assert v["max_verlies_run"] == 5000.0
    assert v["effective_equity_floor"] == DEMO - 5000.0
    assert v["applied"] == "verliesvloer"
    # Vloer gaat vóór de daglimiet af als het dagstartsaldo hoger ligt.
    rm = _rm(DEMO + 10000.0)
    ok, reden = _open(rm, DEMO - 5001.0, DEMO - 5001.0, DEMO)
    assert not ok and reden == "equity onder de ondergrens"
    assert "verliesvloer" in rm.state.halt_reason


def test_demo_as_dict_toont_basis():
    rm = _rm(DEMO)
    _open(rm, DEMO, DEMO, DEMO)
    d = rm.as_dict()
    assert d["risicobasis"] == START
    assert d["daglimiet_bedrag"] == 1000.0
    assert d["max_daily_loss_pct"] == 10.0


# ---------------- echt account rond de startbalans ---------------- #

def test_live_achtig_ongewijzigd():
    rm = _rm(7266.0)
    v = rm.floor_breakdown(START, 7266.0, 7300.0)
    assert v["effective_equity_floor"] == 5000.0
    assert v["applied"] == "configured_floor"
    assert v["verliesvloer"] == pytest.approx(3633.0)
    # Daglimiet: 10% van 7.266 (kleinste), zoals vóór 1.9.4.
    ok, _ = _open(rm, 6600.0, 6600.0, 7266.0)
    assert ok
    ok, reden = _open(rm, 6539.0, 6539.0, 7266.0)
    assert not ok and reden == "daglimiet bereikt"


def test_live_achtig_vloer_5000_blijft():
    rm = _rm(5100.0)
    ok, reden = _open(rm, 4999.0, 4999.0, 7266.0)
    assert not ok and reden == "equity onder de ondergrens"
    assert "configured_floor" in rm.state.halt_reason


# ---------------- saldosprong ---------------- #

def _sprong():
    return SimpleNamespace(actief=True, reden="test", betrouwbaar=lambda w: w)


def test_saldosprong_vloer_geen_noodstop():
    rm = _rm(DEMO)
    rm.saldosprong = _sprong()
    # Demo gereset naar 100.000: ver onder de vloer van 9.995.000.
    ok, reden = _open(rm, 100000.0, 100000.0, DEMO)
    assert not ok and reden.startswith("saldosprong")
    assert "vloer" in reden
    assert rm.state.state is TradingState.RUNNING


def test_saldosprong_daglimiet_geen_noodstop():
    rm = _rm(DEMO + 3000.0)
    rm.saldosprong = _sprong()
    # Boven de vloer, maar 3.000 onder de dagstart: daglimiet overschreden.
    ok, reden = _open(rm, DEMO, DEMO, DEMO)
    assert not ok and reden.startswith("saldosprong")
    assert "daglimiet" in reden
    assert rm.state.state is TradingState.RUNNING


def test_zonder_saldosprong_wel_noodstop():
    rm = _rm(DEMO)
    rm.saldosprong = SimpleNamespace(actief=False)
    ok, _ = _open(rm, 100000.0, 100000.0, DEMO)
    assert not ok and rm.state.state is TradingState.HALTED


# ---------------- versie ---------------- #

def test_versie_194():
    from gold_scalper import const

    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION == "1.9.4"
    changelog = (PKG.parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.split("\n## ")[1].startswith("1.9.4")
