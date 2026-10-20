"""2.18.4 - posities op de mand op risico, niet op de kleinste order.

Gemeld 20-10 13:21 (screenshot): "Nog steeds mini posities?" Een
veldproefpositie op PUMP-EUR van 1.271 units (ruim 5 euro), instap/koers/
stop/doel als 0,00 en als strategie "Daghandel".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.dashboard.broker import _position_rows  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
JS = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")


def test_spot_kent_geen_vaste_scalpgrootte():
    from gold_scalper.coordinator import GoldScalperCoordinator as C

    signaal = SimpleNamespace(components={"strategie": "vp:momentum:15m"})
    spot = SimpleNamespace(_is_spot=True, combinatie=True)
    goud = SimpleNamespace(_is_spot=False, combinatie=True)
    assert C._scalp_vast(spot, signaal) is False
    assert C._scalp_vast(goud, signaal) is True


def test_papieren_positie_houdt_haar_strategie():
    p = SimpleNamespace(ticket=None, id=7, side="buy", units=500000.0, open_price=0.0039,
                        stop_loss=0.00385, take_profit=0.0041, open_time=None,
                        unrealised_pnl=None, current_price=None)
    db = [{"id": 7, "broker_ticket": None, "strategie": "vp:momentum:15m", "open_time": None}]
    rij = _position_rows({"open_positions": [p], "primaire_strategie": "daghandel"}, db, {},
                         SimpleNamespace(bid=0.0039, ask=0.00391))[0]
    assert rij["strategie"] == "vp:momentum:15m"


def test_koersen_met_decimalen_naar_grootte():
    for veld in ("p.instap", "p.koers", "p.sl", "p.tp", "k.mid", "k.bied", "k.laat"):
        assert f"fmt({veld})" not in JS, veld
    assert "fmtSA(p.punten)" in JS
