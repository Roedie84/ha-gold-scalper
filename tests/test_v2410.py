"""2.4.10: veldproef met break-even (1R) en volgstop (vanaf 1,5R op 1R)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker.exits import ExitManager  # noqa: E402
from gold_scalper.strategy import veldproef as V  # noqa: E402

NU = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)



def _zonder_deel(cfg):
    """2.5.9: deze test gaat over de stop, niet over de deelwinst."""
    cfg.enable_partial_close = False
    return cfg

def _eval(prijs, stop, open_price=4189.0, tp=4197.0, kosten=0.64):
    r = V.r_van(open_price, tp)
    m = ExitManager(_zonder_deel(V.exit_config("vp:momentum:5m")))
    return m.evaluate(side="buy", volume=50, open_price=open_price, current_stop=stop,
                      bid=prijs, ask=prijs + 0.6, atr=r, opened_at=NU - timedelta(minutes=5),
                      now=NU, round_trip_cost_per_oz=kosten)


def test_r_uit_het_doel():
    assert V.r_van(4189.0, 4197.0) == 4.0
    assert V.r_van(4189.0, None) == V.MIN_STOP_USD


def test_onder_halve_r_niets():
    # 2.5.1: break-even vanaf 0,5R (R = 4 -> +2 USD).
    assert _eval(4190.4, 4185.0).kind == "hold"   # 2.5.5: ook onder +1,5 USD


def test_break_even_vanaf_1r():
    a = _eval(4193.0, 4185.0)
    assert a.kind == "modify_stop" and a.new_stop > 4189.0


def test_volgstop_vanaf_1_5r():
    a = _eval(4195.5, 4189.8)  # 1,625R winst
    assert a.kind == "modify_stop" and abs(a.new_stop - 4193.55) < 1e-6  # 2.5.7: winstslot strakker


def test_geen_tijdstop_wel_maximale_duur():
    cfg = V.exit_config("vp:momentum:1m")
    assert cfg.time_stop_seconds >= 10 ** 9 and cfg.max_hold_seconds == V.HOLD_BARS * 60


def test_versie_en_coordinator():
    assert V.VELDPROEF_VERSIE >= "veldproef-1.3.0"
    pad = os.path.join(os.path.dirname(__file__), "..", "custom_components",
                       "gold_scalper", "coordinator.py")
    assert "veldproef_mod.r_van(position.open_price" in open(pad, encoding="utf-8").read()


def test_wees_wordt_voorlopig_voor_de_afstemming(tmp_path, monkeypatch):
    import asyncio
    sys.path.insert(0, os.path.dirname(__file__))
    from test_v247 import _opzet, _ronde
    coordinator, venue, _, _, _ = _opzet(
        tmp_path, monkeypatch, {"exit_price": 4390.0, "activity_date": "2026-09-15T11:30:00"})
    _ronde(coordinator, venue)
    status = coordinator.db.conn.execute(
        "SELECT reconciliation_status FROM trades WHERE broker_ticket='WEES'").fetchone()[0]
    assert status == "pending"
