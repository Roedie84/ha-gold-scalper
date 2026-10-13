"""2.4.9: scalpreeks - bij elke stap winst een stuk bijkopen."""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.strategy.scalp_reeks import ReeksConfig, stukken_nu  # noqa: E402

from test_v190 import _opzet, vaste_klok  # noqa: E402,F401

AAN = ReeksConfig(enabled=True, stap_usd=0.3, max_stukken=100, doel_usd=1.0, per_cyclus=3)


def test_alleen_bij_bevestiging():
    assert stukken_nu(AAN, side="buy", entry_price=100.0, current_price=100.29,
                      last_price=None, done=0) == 0
    assert stukken_nu(AAN, side="buy", entry_price=100.0, current_price=99.0,
                      last_price=None, done=0) == 0, "nooit bij tegenslag"
    assert stukken_nu(AAN, side="buy", entry_price=100.0, current_price=100.3,
                      last_price=None, done=0) == 1
    assert stukken_nu(AAN, side="sell", entry_price=100.0, current_price=99.4,
                      last_price=None, done=0) == 2


def test_vanaf_laatste_stuk_en_begrensd():
    assert stukken_nu(AAN, side="buy", entry_price=100.0, current_price=100.5,
                      last_price=100.3, done=1) == 0
    assert stukken_nu(AAN, side="buy", entry_price=100.0, current_price=105.0,
                      last_price=None, done=0) == 3, "hooguit 3 per cyclus"
    assert stukken_nu(AAN, side="buy", entry_price=100.0, current_price=105.0,
                      last_price=None, done=99) == 1, "hooguit max per reeks"
    assert stukken_nu(ReeksConfig(enabled=False), side="buy", entry_price=100.0,
                      current_price=105.0, last_price=None, done=0) == 0


def test_coordinator_plaatst_stukken_met_eigen_doel_en_gedeelde_stop(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    coordinator.reeks = AAN
    asyncio.run(venue.place_order("GOLD", "buy", 2.0, stop_loss=venue.price - 4.0))
    ouder = venue._positions[-1]
    voor = len(venue._positions)
    entry = ouder.open_price
    venue.move(entry + 0.65 - asyncio.run(venue.quote()).bid)  # bid = instap + 0,65
    quote = asyncio.run(venue.quote())
    geplaatst = asyncio.run(coordinator._consider_reeks(ouder, quote, ouder.ticket))
    assert geplaatst == 2
    stukken = venue._positions[voor:]
    assert len(stukken) == 2
    for p in stukken:
        assert p.side == "buy" and abs(p.stop_loss - ouder.stop_loss) < 1e-6
        assert abs(p.take_profit - round(quote.ask + 1.0, 2)) < 1e-6
    rijen = coordinator.db.bijkopen_van(ouder.ticket)
    assert len(rijen) == 2 and rijen[0].open_reason == f"pyramide van {ouder.ticket}"
    assert asyncio.run(coordinator._is_bijkoop(rijen[0].broker_ticket))
    # Zelfde koers: geen nieuwe stukken; na een "herstart" telt de administratie.
    assert asyncio.run(coordinator._consider_reeks(ouder, quote, ouder.ticket)) == 0
    coordinator._pyramid_state.clear()
    assert asyncio.run(coordinator._consider_reeks(ouder, quote, ouder.ticket)) == 0


def test_instellingen_en_vertalingen():
    basis = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")
    for taal in ("nl", "en"):
        data = json.load(open(os.path.join(basis, "translations", f"{taal}.json"),
                               encoding="utf-8"))["options"]["step"]["init"]["data"]
        for veld in ("scalp_reeks", "scalp_reeks_stap_usd", "scalp_reeks_max",
                     "scalp_reeks_doel_usd"):
            assert veld in data
    from gold_scalper.const import INTEGRATION_VERSION
    assert json.load(open(os.path.join(basis, "manifest.json")))["version"] == INTEGRATION_VERSION


def test_redenen_per_strategie_in_paneel():
    basis = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")
    js = open(os.path.join(basis, "frontend", "broker-panel.js"), encoding="utf-8").read()
    assert "st.redenen_per_strategie" in js
    py = open(os.path.join(basis, "dashboard", "broker.py"), encoding="utf-8").read()
    assert '"redenen_per_strategie": data.get("redenen_per_strategie")' in py
    co = open(os.path.join(basis, "coordinator.py"), encoding="utf-8").read()
    assert '"redenen_per_strategie": getattr(self, "_redenen_per_strategie", None)' in co
