"""2.4.6: het winstdoel uit de instellingen geldt voor alle strategieën."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.strategy import daghandel as D  # noqa: E402
from gold_scalper.strategy import veldproef as V  # noqa: E402
from gold_scalper.strategy.scalping import ScalpConfig  # noqa: E402


class _Bars:
    def kenmerken(self, tf):
        return SimpleNamespace(atr=2.0, richting={"momentum": 1}, ts=123)


def test_veldproef_neemt_instelling_over():
    cfg = ScalpConfig(take_profit_usd=3.0)
    s = V.evalueer("vp:momentum:1m", _Bars(), 4000.0, 4000.3, cfg)
    assert s.should_trade and s.take_profit == 4003.3
    assert "doel 3.00 USD" in s.reason


def test_veldproef_zonder_instelling_2r():
    cfg = ScalpConfig(take_profit_usd=0.0)
    s = V.evalueer("vp:momentum:1m", _Bars(), 4000.0, 4000.3, cfg)
    assert s.take_profit == round(4000.3 + V.RR * V.STOP_ATR * 2.0, 2)


def test_daghandel_neemt_instelling_over(monkeypatch):
    monkeypatch.setattr(D, "stand", lambda c, cfg: D.DaghandelStand(10.0, 5.0, 3990.0, 3900.0, 2.0))

    class C(list):
        close = [4000.0] * 100
    cs = C([0] * 100)
    cfg = ScalpConfig(take_profit_usd=3.0)
    s = D.evaluate_daghandel(cs, 4000.0, 4000.3, cfg, 10)
    assert s.should_trade and s.take_profit == 4003.3
    s = D.evaluate_daghandel(cs, 4000.0, 4000.3, ScalpConfig(take_profit_usd=0.0), 10)
    assert s.take_profit is None


def test_nieuwe_strategieversies():
    assert V.VELDPROEF_VERSIE == "veldproef-1.1.0"
    assert D.STRATEGIE_VERSIE == "daghandel-1.1.0"
