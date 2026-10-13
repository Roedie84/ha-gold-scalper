"""2.4.8: vast winstdoel alleen voor scalp; veldproef met eigen label in het paneel."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.dashboard import broker as B  # noqa: E402
from gold_scalper.strategy import combinatie as C  # noqa: E402
from gold_scalper.strategy import veldproef as V  # noqa: E402


def test_strategie_veldproef_niet_als_daghandel():
    data = {"primaire_strategie": "daghandel"}
    assert B._strategie({"strategie": "vp:momentum:30m"}, data) == "vp:momentum:30m"
    assert B._strategie({"strategie": "scalp"}, data) == "scalp"
    assert B._strategie({}, data) == "daghandel"


def test_vp_max_duur_uit_exitconfig():
    assert B._vp_max_duur_s("vp:momentum:30m") == V.HOLD_BARS * 1800
    assert B._vp_max_duur_s("daghandel") is None


def test_open_positie_veldproef_zonder_tijdstop():
    p = SimpleNamespace(ticket="T1", side="buy", units=50.0, open_price=4194.25,
                        stop_loss=4182.4, take_profit=4220.0, open_time=None)
    data = {"open_positions": [p], "primaire_strategie": "daghandel"}
    db_open = [{"broker_ticket": "T1", "strategie": "vp:momentum:30m"}]
    uit = B._position_rows(data, db_open,
                           {"time_stop_seconds": 240, "max_hold_seconds": 900},
                           SimpleNamespace(bid=4190.0, ask=4190.6))
    assert uit[0]["strategie"] == "vp:momentum:30m"
    assert uit[0]["tijdstop_s"] is None
    assert uit[0]["max_duur_s"] == V.HOLD_BARS * 1800


def test_versies():
    assert C.COMBINATIE_VERSIE >= "combinatie-1.2.0"
    assert V.VELDPROEF_VERSIE >= "veldproef-1.2.0"  # 2.6.2: ook 2.x


def test_paneel_label():
    pad = os.path.join(os.path.dirname(__file__), "..", "custom_components",
                       "gold_scalper", "frontend", "broker-panel.js")
    js = open(pad, encoding="utf-8").read()
    assert "stratLabel(p.strategie" in js and 'startsWith("vp:")' in js
