"""2.6.3: veldproef-uitstap in R in plaats van vaste USD-drempels."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker.exits import ExitManager, winstslot_stop  # noqa: E402
from gold_scalper.strategy import veldproef as V  # noqa: E402

NU = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)
OPEN = NU - timedelta(minutes=10)
R = 8.0  # 15m: stop 8 USD/oz


def _eval(bid, deel=False, stop=4000.0 - R):
    m = ExitManager(V.exit_config("vp:pullback:15m"))
    return m.evaluate("buy", 12, 4000.0, stop, bid, bid + 0.6, R, OPEN, NU, 0.8,
                      partial_taken=deel)


def test_geen_vaste_usd_drempels_meer():
    c = V.exit_config("vp:pullback:15m")
    assert c.breakeven_trigger_usd is None
    assert c.partial_close_trigger_usd is None
    assert c.partial_close_trigger_atr == V.DEELWINST_R == 1.0
    assert c.winstslot_in_atr and c.winstslot_treden == V.WINSTSLOT_R


def test_bij_3_usd_nog_geen_deelwinst_of_winstslot():
    a = _eval(4003.0)          # 0,375R: onder de break-even van 0,5R
    assert a.kind == "hold"


def test_break_even_op_een_halve_r():
    a = _eval(4004.2)          # 0,525R
    assert a.kind == "modify_stop" and 4000.0 <= a.new_stop < 4002.0


def test_deelwinst_op_1r():
    a = _eval(4008.1)
    assert a.kind == "partial_close" and a.close_fraction == 0.5


def test_winstslot_na_deelwinst_in_r():
    a = _eval(4012.0, deel=True, stop=4000.0)   # 1,5R: 50 % vast = +6
    assert a.kind == "modify_stop" and abs(a.new_stop - 4006.0) < 1e-6


def test_winstslot_schaal():
    stop, _ = winstslot_stop("buy", 4000.0, 4016.0, treden=V.WINSTSLOT_R, schaal=R)  # 2R
    assert abs(stop - (4000.0 + 0.7 * 16.0)) < 1e-6
    assert winstslot_stop("buy", 4000.0, 4007.0, treden=V.WINSTSLOT_R, schaal=R) is None


def test_versies():
    from gold_scalper.const import INTEGRATION_VERSION
    from gold_scalper.strategy import combinatie as C
    assert INTEGRATION_VERSION == "2.6.3"
    assert V.VELDPROEF_VERSIE == "veldproef-2.1.0"
    assert C.COMBINATIE_VERSIE == "combinatie-1.9.0"
