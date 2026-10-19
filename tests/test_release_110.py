"""1.1.0: groottemethode in de vingerafdruk.

De Lab-delen van deze release (brutotoets, telling van configuraties) zijn
met het Experiment Lab verwijderd in 2.16.0.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _materiaal():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    return bron.split("def _fingerprint_material(")[1].split("\n    @staticmethod")[0], bron


def test_sizing_method_is_in_the_fingerprint():
    body, bron = _materiaal()
    assert '"sizing"' in body and "risk_based" in body and "risk_per_trade_pct" in body
    assert "max_units" not in body                 # een limiet, geen methode
    mapping = bron.split("_OPTION_FOR = {")[1].split("}")[0]
    assert '"sizing": "risk_based_sizing"' in mapping


def test_fingerprint_changes_with_sizing_method():
    from types import SimpleNamespace

    from gold_scalper.coordinator import GoldScalperCoordinator as G

    def materiaal(risk, pct):
        zelf = SimpleNamespace(
            strategy_cfg=SimpleNamespace(
                entry_threshold=0.45, regime_switching=True, min_edge_multiple=2.0,
                enforce_trading_hours=False, real_spread=True, trading_hours_utc=(7, 20),
                max_spread=3.0, max_spread_atr_ratio=0.75, take_profit_usd=0, take_profit_atr=1.5,
                stop_loss_usd=0, stop_loss_atr=1.0),
            conversion=SimpleNamespace(account="EUR"),
            _build_from_quotes=True, mode=SimpleNamespace(value="demo"),
            sizing=SimpleNamespace(risk_based=risk, risk_per_trade_pct=pct,
                                   scale_with_confidence=False))
        cfg = {"venue": "ig", "symbol": "X", "timeframe": "15m", "strategy": "s",
               "simulated": False, "assumed_spread": None, "units": 1.0}
        return G._hash_material(G._fingerprint_material(zelf, cfg))

    vast = materiaal(False, 0.5)
    assert vast == materiaal(False, 0.1)           # percentage telt niet bij vaste grootte
    assert vast != materiaal(True, 0.1)
    assert materiaal(True, 0.1) != materiaal(True, 0.5)
