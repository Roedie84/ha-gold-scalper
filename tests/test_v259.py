"""2.5.9: deelwinst - de helft dicht vanaf +3 USD/oz, gerealiseerd zichtbaar."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker.exits import (  # noqa: E402
    DEELWINST_USD, ExitManager, scalp_exit_config,
)
from gold_scalper.strategy import daghandel as D  # noqa: E402
from gold_scalper.strategy import veldproef as V  # noqa: E402

NU = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)
OPEN = NU - timedelta(seconds=60)
BASIS = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")


def _eval(cfg, bid, deel=False, side="buy", atr=5.4):
    return ExitManager(cfg).evaluate(side, 50, 4000.0, 3994.0, bid, bid + 0.6, atr,
                                     OPEN, NU, 0.8, partial_taken=deel)


def test_drempel():
    assert DEELWINST_USD == 3.0


def test_alle_strategieen_nemen_de_helft_vanaf_3_usd():
    for cfg in (scalp_exit_config(), V.exit_config("vp:pullback:15m"), D.exit_config()):
        a = _eval(cfg, 4003.0, atr=20.0)
        assert a.kind == "partial_close" and a.close_fraction == 0.5, cfg


def test_onder_3_usd_nog_geen_deelwinst():
    a = _eval(scalp_exit_config(), 4002.5, atr=20.0)
    assert a.kind != "partial_close"


def test_na_de_deelwinst_loopt_de_rest_met_winstslot():
    a = _eval(scalp_exit_config(), 4004.0, deel=True)
    assert a.kind == "modify_stop" and a.new_stop >= 4002.0 - 1e-9


def test_paneel_toont_gerealiseerd():
    js = open(os.path.join(BASIS, "frontend", "broker-panel.js"), encoding="utf-8").read()
    assert ">Gerealiseerd</th>" in js and 'cel("Gerealiseerd"' in js
    py = open(os.path.join(BASIS, "dashboard", "broker.py"), encoding="utf-8").read()
    assert "LIKE '%-deel'" in py and '"gerealiseerd"' in py


def test_versies():
    from gold_scalper.const import INTEGRATION_VERSION
    from gold_scalper.strategy import combinatie as C
    from gold_scalper.strategy.scalping import STRATEGY_VERSION
    assert INTEGRATION_VERSION >= "2.5.9"
    assert V.VELDPROEF_VERSIE >= "veldproef-1.8.0"
    assert D.STRATEGIE_VERSIE == "daghandel-1.6.0"
    assert C.COMBINATIE_VERSIE >= "combinatie-1.6.0"
    assert STRATEGY_VERSION == "scalp-0.4.0"
