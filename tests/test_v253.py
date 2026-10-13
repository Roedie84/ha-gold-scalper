"""2.5.3: eigen turbosignaal - uitbraak op de live ticks."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.strategy import turbo as T  # noqa: E402
from gold_scalper.strategy.scalping import ScalpConfig  # noqa: E402
from test_v190 import vaste_klok  # noqa: E402,F401

CFG = ScalpConfig(take_profit_usd=1.0, stop_loss_usd=2.0, max_spread=3.0)


def _band(tr, t0=0.0, n=20, laag=4000.0, hoog=4001.0):
    for i in range(n):
        m = laag if i % 2 else hoog
        tr.voeg_toe(t0 + i * 2.0, m - 0.2, m + 0.2)


def test_uitbraak_long():
    tr = T.TickUitbraak()
    _band(tr)                                   # t 0..38, band 4000-4001
    tr.voeg_toe(40.0, 4001.0, 4001.4)           # 4001,2
    tr.voeg_toe(44.0, 4001.4, 4001.8)           # 4001,6: door de band en doorgezet
    s = tr.evalueer(44.0, 4001.4, 4001.8, CFG, 5.0)
    assert s.should_trade and s.direction == 1
    assert s.take_profit == 4002.8 and s.stop_loss == 3999.8


def test_binnen_de_band_niets():
    tr = T.TickUitbraak()
    _band(tr)
    s = tr.evalueer(40.0, 4000.3, 4000.7, CFG, 5.0)
    assert not s.should_trade and s.reject_reason == "geen_uitbraak"


def test_te_stil_en_cooldown():
    tr = T.TickUitbraak()
    _band(tr, hoog=4000.1)
    assert tr.evalueer(40.0, 4000.5, 4000.9, CFG, 5.0).reject_reason == "te_stil"
    tr = T.TickUitbraak()
    _band(tr)
    tr.voeg_toe(40.0, 4001.0, 4001.4)
    tr.voeg_toe(44.0, 4001.4, 4001.8)
    assert tr.evalueer(44.0, 4001.4, 4001.8, CFG, 5.0, sinds_instap=5).reject_reason == "cooldown"


def test_in_de_turboronde(tmp_path, monkeypatch):
    from test_v250 import _klaar, _tick
    from test_v190 import _klok
    coordinator, venue = _klaar(tmp_path, monkeypatch)
    # scalp zegt nee; het uitbraaksignaal ja
    import gold_scalper.coordinator as C
    from gold_scalper.strategy.scalping import ScalpSignal
    monkeypatch.setattr(coordinator, "_beslisser", lambda now, s=None: (
        lambda *a, **k: ScalpSignal(direction=0, score=0.1, confidence=0, should_trade=False,
                                    reject_reason="score_below_threshold", reason="")))
    monkeypatch.setattr(coordinator.turbo_signaal, "evalueer", lambda *a, **k: ScalpSignal(
        direction=1, score=1.0, confidence=1.0, should_trade=True, reject_reason=None,
        reason="turbo test", stop_loss=venue.price - 2, take_profit=venue.price + 1,
        geldig=True, components={"turbo_signaal": "uitbraak"}))
    _klok["extra"] += 400
    venue.move(3.0)                             # buiten de spreiding van de eerste positie
    voor = len(venue._positions)
    assert asyncio.run(coordinator._turbo_tick(_tick(venue))) == 1
    assert len(venue._positions) == voor + 1
    assert coordinator.turbo_stats["uitbraak_orders"] == 1
    rij = coordinator.db.conn.execute(
        "SELECT open_reason FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    assert rij[0] == "turbo uitbraak"
    assert C.turbo_mod.TURBO_SIGNAAL_VERSIE in str(coordinator._fingerprint_material(coordinator._run_config()))


def test_turbo_herkenbaar_in_paneel():
    from pathlib import Path
    pkg = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
    js = (pkg / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
    assert 'if (turbo) return "Turbo scalp"' in js and "stratLabel(p.strategie, p.turbo)" in js
    py = (pkg / "dashboard" / "broker.py").read_text(encoding="utf-8")
    assert '"turbo": str(db.get("open_reason") or "").startswith("turbo")' in py
