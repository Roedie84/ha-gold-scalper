"""1.1.0: brutotoets, telling van configuraties, groottemethode in de vingerafdruk.

EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.const import STRATEGY_WINDOW_BARS  # noqa: E402
from gold_scalper.experiment_lab import assessment as A  # noqa: E402
from gold_scalper.experiment_lab.storage import LabDatabase  # noqa: E402
from gold_scalper.experiment_lab.wf_runner import WalkForwardRunner  # noqa: E402
from vaste_bars import vaste_bars  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _inp(paren):
    return {"windows": [{"window_id": 1, "status": "COMPLETED",
                         "test": {"trades": [{"gross": g, "net": n} for g, n in paren]}}]}


# ------------------------------------------------------------- brutotoets --

def test_rules_version_is_2():
    assert A.ASSESSMENT_RULES_VERSION == 2


def test_gross_positive_while_net_negative():
    """Signaal vóór kosten, verlies erna: precies wat de opzet moet scheiden."""
    paren = [(1.0 + (0.3 if i % 2 else -0.3), -0.2 + (0.3 if i % 2 else -0.3)) for i in range(200)]
    c = A.c_gross(_inp(paren), 2.0)
    assert c["component_code"] == "GROSS_EVIDENCE" and c["status"] == A.PASS
    assert c["details"]["hypothesis"] == "H_GROSS_OOS_PER_TRADE"
    assert c["details"]["mean_cost"] == pytest.approx(1.2)
    assert c["blocking"] is False


def test_gross_never_changes_the_classification():
    bron = (PKG / "experiment_lab" / "assessment.py").read_text(encoding="utf-8")
    beslissing = bron.split("def assess(")[1].split("plafond = ROBUST")[0]
    assert "GROSS_EVIDENCE" not in beslissing.split("c_gross(")[1].split("\n", 1)[1]


@pytest.mark.parametrize("paren,status", [
    ([(-1.0 + (0.2 if i % 2 else -0.2), -1.5) for i in range(100)], A.FAIL),
    ([(0.1 if i % 2 else -0.1, -0.8) for i in range(100)], A.WARNING),
    ([(1.0, -0.5)], A.INSUFFICIENT_DATA),
])
def test_gross_outcomes(paren, status):
    assert A.c_gross(_inp(paren), 2.0)["status"] == status


# ---------------------------------------------- walk-forward van begin tot eind --

@pytest.fixture(scope="module")
def wf(tmp_path_factory):
    import test_lab_walk_forward as T

    pad = tmp_path_factory.mktemp("r110") / "lab.db"
    c = vaste_bars(STRATEGY_WINDOW_BARS + 5 * 96)
    db = LabDatabase(pad).open()
    eid = T._wf(db, T._snapshot(db, c), c, kandidaten=[T.KANDIDATEN[1]], modus=T.W.SEQUENTIAL_OOS)
    db.close()
    h = WalkForwardRunner(pad).submit_walk_forward(eid)
    assert h.wait(600) and h.final_status == "completed", h.error
    db = LabDatabase(pad).open()
    yield db, eid
    db.close()


def test_one_candidate_counts_as_one_configuration(wf):
    db, eid = wf
    familie = db.get(eid).hypothesis_family_id
    assert db.family_summary(familie)["evaluated_configurations"] == 1


def test_assessment_carries_gross_with_threshold_for_one_test(wf):
    from gold_scalper.analysis.indicator_lab import drempel_t

    db, eid = wf
    a = db.assessment(db.create_assessment(eid, "test110"))
    comp = a["components"]
    assert "GROSS_EVIDENCE" in comp and "STATISTICAL_EVIDENCE" in comp
    assert float(comp["MULTIPLE_TESTING"]["measured_value"]) == pytest.approx(drempel_t(1, 0.05))
    assert a["assessment_rules_version"] == 2


# ------------------------------------------------------------ vingerafdruk --

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
