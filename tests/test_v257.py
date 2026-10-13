"""2.5.7: winstslot - winst sneller vastzetten, ook bij hoge volatiliteit."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker.exits import ExitConfig, ExitManager, scalp_exit_config, winstslot_stop  # noqa: E402
from gold_scalper.strategy import daghandel as D  # noqa: E402
from gold_scalper.strategy import veldproef as V  # noqa: E402

NU = datetime(2026, 10, 13, 13, 0, tzinfo=timezone.utc)
OPEN = NU - timedelta(minutes=5)
ATR = 5.4  # 13-10 15:00


def _eval(cfg, side, instap, stop, bid, ask):
    return ExitManager(cfg).evaluate(side, 0.5, instap, stop, bid, ask, ATR, OPEN, NU, 0.8)


def test_onder_2_usd_geen_winstslot():
    assert winstslot_stop("buy", 4000.0, 4001.9) is None


def test_vanaf_2_usd_helft_vast():
    stop, reden = winstslot_stop("buy", 4000.0, 4002.0)
    assert abs(stop - 4001.0) < 1e-9 and "50%" in reden


def test_vanaf_5_usd_70_procent_vast_short():
    stop, _ = winstslot_stop("sell", 4000.0, 3994.0)
    assert abs(stop - (4000.0 - 4.2)) < 1e-9


def test_scalp_bij_hoge_atr_zet_winst_vast_voor_de_trailing():
    # +4 USD bij ATR 5,4: trailing (1,5 x ATR = 8,1) nog niet actief.
    a = _eval(scalp_exit_config(), "buy", 4000.0, 4000.0, 4004.0, 4004.6)
    assert a.kind == "modify_stop" and abs(a.new_stop - 4002.0) < 1e-6
    assert "winstslot" in a.reason


def test_veldproef_en_daghandel_ook():
    for cfg in (V.exit_config("vp:rsi_rev:15m"), D.exit_config()):
        a = _eval(cfg, "sell", 4000.0, 4000.0, 3994.4, 3995.0)
        assert a.kind == "modify_stop" and a.new_stop < 4000.0


def test_stop_gaat_nooit_terug():
    a = _eval(scalp_exit_config(), "buy", 4000.0, 4003.0, 4004.0, 4004.6)
    assert a.kind == "hold"


def test_strakste_van_trailing_en_winstslot():
    # +10 USD: trailing 10 - 1,2 x 5,4 = 3,52 vast; winstslot 70% = 7 vast.
    a = _eval(ExitConfig(), "buy", 4000.0, 4000.0, 4010.0, 4010.6)
    assert abs(a.new_stop - 4007.0) < 1e-6
    a = _eval(ExitConfig(winstslot=False), "buy", 4000.0, 4000.0, 4010.0, 4010.6)
    assert abs(a.new_stop - 4003.52) < 1e-6


def test_altijd_minimale_afstand_tot_de_koers():
    stop, _ = winstslot_stop("buy", 4000.0, 4002.0, min_afstand=1.5)
    assert abs(stop - 4000.5) < 1e-9


def test_strategieversies_omhoog():
    from gold_scalper.strategy import combinatie as C
    from gold_scalper.strategy.scalping import STRATEGY_VERSION
    assert V.VELDPROEF_VERSIE == "veldproef-1.7.0"
    assert D.STRATEGIE_VERSIE == "daghandel-1.5.0"
    assert C.COMBINATIE_VERSIE == "combinatie-1.5.0"
    assert STRATEGY_VERSION == "scalp-0.3.0"
