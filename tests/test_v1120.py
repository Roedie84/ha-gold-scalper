"""1.12.0 (L-GS-013): strengere instapdrempel, met schaduwtrades eronder.

Besluit van Ruud (12-10): instapdrempel van 0,45 naar 0,70 als vooraf
vastgelegde toets. Signalen tussen 0,45 en de drempel worden volledig
berekend en als schaduwtrade gevolgd, zodat meetbaar blijft wat de oude
drempel had opgeleverd.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.const import INTEGRATION_VERSION, SCHADUW_DREMPEL  # noqa: E402
from gold_scalper.strategy.schaduw import SCHADUW_REDENEN, SchaduwBoek  # noqa: E402

from test_v190 import T0, _eval, market  # noqa: E402,F401

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _sterkte(market):
    return abs(_eval(market, {1: 0, -1: 0}).score)


def test_tussen_de_drempels_geldig_maar_niet_uitgevoerd(market):
    s0 = _sterkte(market)
    s = _eval(market, {1: 0, -1: 0}, entry_threshold=s0 + 0.01,
              schaduw_drempel=s0 - 0.01)
    assert not s.should_trade and s.geldig
    assert s.reject_reason == "score_below_threshold"
    assert s.stop_loss is not None and s.take_profit is not None
    assert "schaduwtrade" in s.reason


def test_zonder_schaduwdrempel_als_vroeger(market):
    s0 = _sterkte(market)
    s = _eval(market, {1: 0, -1: 0}, entry_threshold=s0 + 0.01)
    assert not s.should_trade and not s.geldig
    assert s.reject_reason == "score_below_threshold"


def test_onder_de_schaduwdrempel_geen_kandidaat(market):
    s0 = _sterkte(market)
    s = _eval(market, {1: 0, -1: 0}, entry_threshold=s0 + 0.02,
              schaduw_drempel=s0 + 0.01)
    assert not s.geldig


def test_boven_de_drempel_verandert_niets(market):
    s0 = _sterkte(market)
    s = _eval(market, {1: 0, -1: 0}, entry_threshold=s0 - 0.01,
              schaduw_drempel=SCHADUW_DREMPEL)
    assert s.should_trade and s.geldig and s.reject_reason is None
    # schaduwdrempel boven de drempel: geen effect
    s = _eval(market, {1: 0, -1: 0}, entry_threshold=s0 - 0.01,
              schaduw_drempel=s0 + 0.5)
    assert s.should_trade


def test_te_zwak_gaat_voor_cooldown(market):
    s0 = _sterkte(market)
    s = _eval(market, {1: 0, -1: 0}, sinds=5.0, entry_threshold=s0 + 0.01,
              schaduw_drempel=s0 - 0.01)
    assert s.reject_reason == "score_below_threshold" and s.geldig


def test_schaduwboek_neemt_de_reden_aan(market):
    s0 = _sterkte(market)
    s = _eval(market, {1: 0, -1: 0}, entry_threshold=s0 + 0.01,
              schaduw_drempel=s0 - 0.01)
    assert "onder_drempel" in SCHADUW_REDENEN
    from gold_scalper.broker.exits import ExitConfig, ExitManager

    boek = SchaduwBoek(exits=ExitManager(ExitConfig()), bar_seconden=300)
    prijs = market.close[-1]
    t = boek.openen(run_id=1, signal=s, bid=prijs - 0.41, ask=prijs + 0.41,
                    nu=T0, units=1.0, reden="onder_drempel",
                    reden_tekst=s.reason, atr=5.0)
    assert t is not None and t.reden == "onder_drempel"


def test_coordinator_koppelt_reden_en_drempel():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    i = bron.index('elif signal.reject_reason == "cooldown":')
    stuk = bron[i:i + 400]
    assert 'signal.reject_reason == "score_below_threshold"' in stuk
    assert "and signal.geldig" in stuk and 'schaduw_reden = "onder_drempel"' in stuk
    assert "schaduw_drempel=SCHADUW_DREMPEL," in bron
    assert SCHADUW_DREMPEL == 0.45


def test_label_en_versie():
    js = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
    assert 'onder_drempel: "onder drempel"' in js
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == INTEGRATION_VERSION == "1.12.0"
