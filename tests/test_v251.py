"""2.5.1: bij alle strategieën snel de stop naar de instap (Ruud 13-10)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker.exits import (  # noqa: E402
    ExitManager, scalp_exit_config, BREAKEVEN_MIN_AFSTAND_USD,
)
from gold_scalper.strategy import daghandel as D  # noqa: E402
from gold_scalper.strategy import veldproef as V  # noqa: E402

NU = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)


def _eval(m, bid, stop=3998.0, kosten=0.8):
    return m.evaluate("buy", 0.5, 4000.0, stop, bid, bid + 0.3, 5.0,
                      NU - timedelta(seconds=30), NU, kosten)


def test_scalp_stop_naar_instap_bij_06():
    m = ExitManager(scalp_exit_config())
    assert _eval(m, 4000.4).kind == "hold"
    a = _eval(m, 4000.6)
    assert a.kind == "modify_stop" and a.new_stop == 4000.0


def test_stop_nooit_tegen_de_koers():
    m = ExitManager(V.exit_config("vp:momentum:1m"))
    # R = 1 (atr-plek), winst 0,6 = 0,6R: instap + 1,2 x kosten (0,96) past niet -> instap
    a = m.evaluate("buy", 0.5, 4000.0, 3999.0, 4000.6, 4000.9, 1.0,
                   NU - timedelta(seconds=30), NU, 0.8)
    assert a.kind == "modify_stop" and a.new_stop == 4000.0
    assert BREAKEVEN_MIN_AFSTAND_USD == 0.6


def test_veldproef_en_daghandel_sneller():
    assert V.BREAKEVEN_R == 0.5
    assert D.exit_config().breakeven_trigger_atr == 1.0
    m = ExitManager(D.exit_config())
    a = m.evaluate("buy", 0.5, 4000.0, 3980.0, 4005.5, 4005.8, 5.0,
                   NU - timedelta(seconds=300), NU, 0.8)
    assert a.kind == "modify_stop" and a.new_stop == round(4000.0 + 0.96, 3)
