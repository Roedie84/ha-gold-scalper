"""2.6.2: veldproef op risico (max 100 USD tot de stop) en geen clusters."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.strategy import veldproef as V  # noqa: E402

BASIS = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")


def test_grootte_volgt_de_stop():
    assert V.MAX_RISICO_PER_TRADE_USD == 100.0
    assert V.grootte_op_risico(50, 4148.52, 4156.98) == 11.8   # 13-10 18:06, stop 8,46
    assert V.grootte_op_risico(50, 4000.0, 3999.0) == 50       # kleine stop: bovengrens
    assert V.grootte_op_risico(50, 4000.0, 3800.0) == 1.0      # minstens 1 oz
    assert V.grootte_op_risico(50, 4000.0, None) == 50


def test_verlies_tot_de_stop_hooguit_100():
    for stop in (4003.0, 4006.5, 4013.0):
        u = V.grootte_op_risico(50, 4000.0, stop)
        assert u * (stop - 4000.0) <= 100.0 + 1e-6


def test_loopt_risico():
    assert V.loopt_risico("sell", 4148.0, 4153.0)
    assert not V.loopt_risico("sell", 4148.0, 4148.0)        # break-even
    assert not V.loopt_risico("buy", 4000.0, 4001.0)         # winst vast
    assert V.loopt_risico("buy", 4000.0, None)
    assert V.MAX_POSITIES_MET_RISICO == 3


def test_coordinator_gebruikt_het():
    py = open(os.path.join(BASIS, "coordinator.py"), encoding="utf-8").read()
    assert "veldproef_mod.grootte_op_risico(units, entry_price, signal.stop_loss)" in py
    assert py.count("self._vaste_grootte(signal, entry_price)") == 2
    assert 'return "cluster", (' in py


def test_versies():
    from gold_scalper.const import INTEGRATION_VERSION
    from gold_scalper.strategy import combinatie as C
    assert INTEGRATION_VERSION == "2.6.2"
    assert V.VELDPROEF_VERSIE == "veldproef-2.0.0"
    assert C.COMBINATIE_VERSIE == "combinatie-1.8.0"
