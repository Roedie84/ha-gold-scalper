"""2.1.0 (L-GS-015): daghandel en scalpen tegelijk, beide met echte orders.

Besluit Ruud 12-10-2026. Elke positie draagt haar strategie en houdt haar
eigen uitstapregels, grootte, limiet en cooldown; marge, vloer, daglimiet en
het totaal gaan over alles samen; de verliesreeks telt alleen de daghandel.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.broker.exits import ExitAction, ExitManager  # noqa: E402
from gold_scalper.broker.risk import RiskLimits, RiskManager  # noqa: E402
from gold_scalper.const import (  # noqa: E402
    CONF_SCALP_UNITS, STRATEGIE_COMBINATIE, STRATEGIE_DAGHANDEL, STRATEGIE_SCALP, STRATEGIEEN,
)
from gold_scalper.strategy import combinatie as C  # noqa: E402
from gold_scalper.strategy import daghandel as D  # noqa: E402
from gold_scalper.strategy.scalping import ScalpSignal  # noqa: E402

from test_v190 import _klok, _nep_evaluate, _opzet, _richting, vaste_klok  # noqa: E402,F401

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


# --- zuiver ------------------------------------------------------------------ #

def test_volgorde_en_keuzes():
    assert C.strategieen(STRATEGIE_COMBINATIE) == (STRATEGIE_DAGHANDEL, STRATEGIE_SCALP)
    assert C.strategieen(STRATEGIE_SCALP) == (STRATEGIE_SCALP,)
    assert C.strategieen(STRATEGIE_DAGHANDEL) == (STRATEGIE_DAGHANDEL,)
    assert STRATEGIE_COMBINATIE in STRATEGIEEN


def test_strategie_van_trade():
    t = SimpleNamespace(strategie="scalp")
    assert C.strategie_van_trade(t, None, "daghandel") == "scalp"
    t = SimpleNamespace(strategie=None)
    assert C.strategie_van_trade(t, "daghandel-1.0.0", "scalp") == "daghandel"
    assert C.strategie_van_trade(t, "scalp-0.2.0", "daghandel") == "scalp"
    assert C.strategie_van_trade(t, None, "daghandel") == "daghandel"


def test_per_strategie():
    def tr(s, netto, bruto, kost):
        return SimpleNamespace(strategie=s, net_pnl=netto, gross_pnl=bruto, total_cost=kost)
    uit = C.per_strategie(
        [tr("scalp", -1.0, 0.5, 1.5), tr("scalp", 2.0, 3.0, 1.0),
         tr("daghandel", 10.0, 11.0, 1.0), tr("daghandel", None, 0, 0)],
        "daghandel",
    )
    assert uit["scalp"]["trades"] == 2 and uit["scalp"]["netto"] == 1.0
    assert uit["scalp"]["kosten"] == 2.5 and uit["scalp"]["winst_pct"] == 50.0
    assert uit["daghandel"]["trades"] == 1 and uit["daghandel"]["t_per_trade"] is None


def test_verliesreeks_alleen_voor_wat_meetelt():
    r = RiskManager(RiskLimits(max_consecutive_losses=2), 10000.0)
    nu = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
    for _ in range(5):
        r.record_close(-5.0, nu, telt_voor_reeks=False)
    assert r.state.consecutive_losses == 0 and r.sluitingen == 5
    r.record_close(-5.0, nu)
    r.record_close(-5.0, nu)
    assert r.state.paused_until is not None


# --- in de lus ------------------------------------------------------------- #

def _nep_daghandel(candles, bid, ask, cfg, uur, aantal=0, sinds=1e9, kant=0,
                   per_richting=None, minuut_utc=0):
    d = _richting["d"]
    instap = ask if d == 1 else bid
    s = ScalpSignal(direction=d, score=0.7 * d, confidence=1.0, should_trade=True,
                    reject_reason=None, reason="daghandel test",
                    stop_loss=instap - 20.0 * d, take_profit=None, geldig=True,
                    components={"strategie": "daghandel"})
    if aantal >= 1:
        s.should_trade, s.reject_reason = False, "max_positions_zelfde_richting"
    return s


def _combinatie(tmp_path, monkeypatch, scalp_units=0.5):
    monkeypatch.setattr(D, "evaluate_daghandel", _nep_daghandel)
    coordinator, venue, hass = _opzet(tmp_path, monkeypatch)
    coordinator._strategie = STRATEGIE_COMBINATIE
    coordinator._scalp_units = scalp_units
    coordinator.risk.limits.max_open_positions = 7
    houd = lambda **kw: ExitAction("hold", reason="test")  # noqa: E731
    coordinator.exits = ExitManager(D.exit_config())
    coordinator.exits.evaluate = houd
    coordinator._exits_scalp.evaluate = houd
    return coordinator, venue


def _cyclus(coordinator, stap=0.0, beweeg=0.0):
    _klok["extra"] += stap
    if beweeg:
        coordinator.venue.move(beweeg)
    return asyncio.run(coordinator._async_update_data())


def test_eerst_daghandel_dan_scalp_elk_met_eigen_grootte(tmp_path, monkeypatch):
    coordinator, venue = _combinatie(tmp_path, monkeypatch)
    _richting["d"] = 1
    data = _cyclus(coordinator)                       # daghandel opent
    assert len(venue.orders) == 1
    assert set(data["signalen"]) == {"daghandel", "scalp"}
    for _ in range(3):                                # daarna scalp, niet nog een daghandel
        data = _cyclus(coordinator, stap=400, beweeg=3.0)
    trades = coordinator.db.open_trades(coordinator.run_id)
    per = {}
    for t in trades:
        per.setdefault(t.strategie, []).append(t)
    assert len(per["daghandel"]) == 1, "hooguit één daghandelpositie"
    assert len(per["scalp"]) >= 2
    assert all(abs(t.volume * 100 - 0.5) < 1e-6 or abs(t.volume - 0.5) < 1e-6
               for t in per["scalp"]), "vaste scalpgrootte"
    assert data["signal"].components.get("strategie") == "daghandel"


def test_exits_per_strategie(tmp_path, monkeypatch):
    coordinator, venue = _combinatie(tmp_path, monkeypatch)
    assert coordinator._exits_voor("scalp") is coordinator._exits_scalp
    assert coordinator._exits_voor("daghandel") is coordinator.exits
    assert coordinator._exits_scalp.config.sluit_om_uur_utc is None
    assert coordinator.exits.config.sluit_om_uur_utc == D.SLUIT_OM_UUR


def test_strategie_van_positie(tmp_path, monkeypatch):
    coordinator, venue = _combinatie(tmp_path, monkeypatch)
    assert asyncio.run(coordinator._strategie_van(SimpleNamespace(strategie="scalp"))) == "scalp"
    coordinator._strategie_per_ticket["X1"] = "scalp"
    assert asyncio.run(coordinator._strategie_van(SimpleNamespace(ticket="X1"))) == "scalp"
    # onbekend: de primaire strategie
    assert asyncio.run(coordinator._strategie_van(SimpleNamespace(ticket="ONB"))) == "daghandel"


def test_reeks_telt_alleen_daghandel(tmp_path, monkeypatch):
    coordinator, venue = _combinatie(tmp_path, monkeypatch)
    assert coordinator._telt_voor_reeks(SimpleNamespace(strategie="daghandel"))
    assert not coordinator._telt_voor_reeks(SimpleNamespace(strategie="scalp"))
    coordinator._strategie = STRATEGIE_SCALP
    assert coordinator._telt_voor_reeks(SimpleNamespace(strategie="scalp"))


def test_nieuwe_run_bij_combinatie(tmp_path, monkeypatch):
    coordinator, venue = _combinatie(tmp_path, monkeypatch)
    assert coordinator.strategie_versie == C.COMBINATIE_VERSIE
    materiaal = coordinator._fingerprint_material(coordinator._run_config())
    assert materiaal["strategy"] == C.COMBINATIE_VERSIE
    assert materiaal["scalp_units"] == 0.5


def test_bron_en_vertalingen():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "eigen=eigen," in bron and "p for p in (open_positions if eigen is None else eigen)" in bron
    assert "telt_voor_reeks=self._telt_voor_reeks(trade)" in bron
    for taal in ("nl", "en"):
        d = json.loads((PKG / "translations" / f"{taal}.json").read_text(encoding="utf-8"))
        assert "combinatie" in d["selector"]["strategie"]["options"]
        assert d["options"]["step"]["init"]["data"][CONF_SCALP_UNITS]
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert tuple(map(int, manifest["version"].split("."))) >= (2, 1, 0)
    # 2.1.1: de telling per richting voor status en sensor gaat over alles.
    assert "per_richting = eigen_richting if self.combinatie" not in bron
