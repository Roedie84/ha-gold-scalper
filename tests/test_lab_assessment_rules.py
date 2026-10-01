"""Experiment Lab, fase 7: het regelboek en de classificatie, als pure logica.

Invoer wordt hier met de hand opgebouwd, zodat elke regel en elke grens
afzonderlijk te toetsen is. De koppeling met de database en de gelogde
TEST-toegang staat in test_lab_assessment.py.
"""
import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.experiment_lab import assessment as A  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
BAR_ONLY = {"simulation_model": "BAR_ONLY", "ambiguous_exits": 0, "known_limitations": ["x"]}


def _trade(net, dag="2026-09-07", regime="trend", sessie="london", reden="take_profit"):
    return {"net": net, "trading_day": dag, "regime": regime, "session": sessie, "close_reason": reden}


def _venster(i, nets, train=None, warm="FULL_WARMUP", fid=BAR_ONLY, versies=(2, 4, 1, 1, 1, 1)):
    return {"window_id": i, "window_index": i, "status": "COMPLETED", "selected_candidate_id": None,
            "train_selected": train,
            "test": {"result_id": 100 + i, "trades": [_trade(n, dag=f"2026-09-{7 + i:02d}") for n in nets],
                     "metrics": {"net_pnl": {"value": sum(nets), "calculation_status": "VALID"}},
                     "metrics_complete": True, "warmup_status": warm, "segment_end_close_count": 0,
                     "cross_boundary_count": 0, "fidelity": fid, "versions": versies,
                     "cost_currency": "USD"}}


def _inp(vensters, configs=1, toegang=None, kwaliteit="OK"):
    return {"windows": vensters, "candidates": [],
            "dataset": {"quality_status": kwaliteit, "findings": []},
            "family": {"evaluated_configurations": configs},
            "access": toegang if toegang is not None else
            [{"window_id": w["window_id"], "prior_access_count": 0, "data_reused": False,
              "overlapping_prior_count": 0} for w in vensters]}


STERK = [[5.0 + (j % 3) for j in range(12)] for _ in range(4)]           # 48 trades, duidelijk positief


def test_no_test_gives_needs_out_of_sample():
    w = _venster(0, [1.0])
    w["test"] = None
    assert A.assess(_inp([w]))["final_classification"] == A.NEEDS_OOS


def test_too_few_trades_gives_insufficient_data():
    uit = A.assess(_inp([_venster(i, [5.0, 6.0]) for i in range(4)]))
    assert uit["final_classification"] == A.INSUFF


def test_the_data_threshold_boundary():
    """Precies MIN_OOS_TRADES is genoeg, één minder niet."""
    grens = A.RULEBOOK["MIN_OOS_TRADES"]["value"]
    for n, verwacht in ((grens - 1, A.INSUFFICIENT_DATA), (grens, A.PASS)):
        per = [n // 3 + (1 if i < n % 3 else 0) for i in range(3)]
        vensters = [_venster(i, [1.0 + (k % 2) for k in range(per[i])]) for i in range(3)]
        assert A.c_data_sufficiency(_inp(vensters))["status"] == verwacht, n


def test_bar_only_caps_a_positive_result_at_possible_edge():
    uit = A.assess(_inp([_venster(i, n) for i, n in enumerate(STERK)]))
    assert uit["raw_classification"] == A.ROBUST
    assert uit["final_classification"] == A.POSSIBLE
    assert uit["fidelity_ceiling"] == A.LIMITED_FID


def test_high_fidelity_allows_robust():
    hoog = {"simulation_model": "QUOTE_REPLAY", "ambiguous_exits": 0, "known_limitations": []}
    uit = A.assess(_inp([_venster(i, n, fid=hoog) for i, n in enumerate(STERK)]))
    assert uit["final_classification"] == A.ROBUST


def test_insufficient_fidelity_blocks_any_positive_class():
    uit = A.assess(_inp([_venster(i, n, fid={}) for i, n in enumerate(STERK)]))
    assert uit["final_classification"] not in (A.POSSIBLE, A.ROBUST)


def test_data_reuse_caps_at_possible_edge():
    hoog = {"simulation_model": "QUOTE_REPLAY", "ambiguous_exits": 0, "known_limitations": []}
    vensters = [_venster(i, n, fid=hoog) for i, n in enumerate(STERK)]
    toegang = [{"window_id": w["window_id"], "prior_access_count": 1, "data_reused": True,
                "overlapping_prior_count": 0} for w in vensters]
    uit = A.assess(_inp(vensters, toegang=toegang))
    assert uit["final_classification"] == A.POSSIBLE
    assert next(c for c in uit["components"] if c["component_code"] == "TEST_INDEPENDENCE")["status"] == "REUSED"


def test_partial_warmup_caps_and_stays_visible():
    hoog = {"simulation_model": "QUOTE_REPLAY", "ambiguous_exits": 0, "known_limitations": []}
    vensters = [_venster(i, n, fid=hoog, warm="PARTIAL_WARMUP" if i == 0 else "FULL_WARMUP")
                for i, n in enumerate(STERK)]
    uit = A.assess(_inp(vensters))
    assert uit["final_classification"] == A.POSSIBLE and "WARMUP_QUALITY" in uit["warnings"]


def test_no_effect_gives_no_evidence():
    ruis = [[(1.0 if j % 2 else -1.0) for j in range(12)] for _ in range(4)]
    assert A.assess(_inp([_venster(i, n) for i, n in enumerate(ruis)]))["final_classification"] == A.NO_EVIDENCE


def test_clearly_negative_gives_likely_no_edge():
    neg = [[-5.0 - (j % 3) for j in range(12)] for _ in range(4)]
    assert A.assess(_inp([_venster(i, n) for i, n in enumerate(neg)]))["final_classification"] == A.NO_EDGE


def test_good_train_bad_test_is_never_possible_edge():
    neg = [[-5.0 - (j % 3) for j in range(12)] for _ in range(4)]
    uit = A.assess(_inp([_venster(i, n, train=50.0) for i, n in enumerate(neg)]))
    assert uit["final_classification"] not in (A.POSSIBLE, A.ROBUST)


def test_one_overfit_signal_alone_is_not_overfit():
    """Alleen het verval van TRAIN naar TEST, verder niets: geen LIKELY_OVERFIT."""
    neg = [[-5.0 - (j % 3) for j in range(12)] for _ in range(4)]
    uit = A.assess(_inp([_venster(i, n, train=50.0) for i, n in enumerate(neg)], configs=1))
    assert uit["raw_classification"] != A.OVERFIT


def test_several_overfit_signals_give_a_traceable_overfit():
    neg = [[-5.0 - (j % 3) for j in range(12)] for _ in range(4)]
    uit = A.assess(_inp([_venster(i, n, train=50.0) for i, n in enumerate(neg)], configs=6))
    assert uit["raw_classification"] == A.OVERFIT
    regel = next(s for s in uit["trace"] if s["rule"] == "overfitsignalen")
    assert "TRAIN_TEST_DEGRADATION" in regel["result"] and "MULTIPLE_TESTING" in regel["result"]


def test_more_configurations_raise_the_threshold():
    een = A.c_multiple_testing(_inp([], configs=1))["measured_value"]
    twintig = A.c_multiple_testing(_inp([], configs=20))["measured_value"]
    assert twintig > een


def test_windows_are_counted_correctly():
    nets = [[3.0] * 10, [-2.0] * 10, [0.0] * 10, [1.0] * 10]
    c = A.c_window_consistency(_inp([_venster(i, n) for i, n in enumerate(nets)]))
    assert (c["details"]["positive"], c["details"]["negative"], c["details"]["breakeven"]) == (2, 1, 1)


def test_concentration_and_an_unusable_denominator():
    c = A.c_concentration(_inp([_venster(0, [10.0] * 3), _venster(1, [1.0] * 3), _venster(2, [1.0] * 3)]))
    assert c["status"] == A.WARNING and abs(c["measured_value"] - 30 / 36) < 1e-9
    nul = A.c_concentration(_inp([_venster(0, [1.0, -1.0])]))
    assert nul["status"] == A.NOT_APPLICABLE and nul["measured_value"] is None


def test_cost_sensitivity_is_never_invented():
    assert A.c_cost_sensitivity(_inp([]))["status"] == A.NOT_APPLICABLE


def test_parameter_sensitivity_only_for_a_local_neighbourhood():
    kand = [{"id": i, "config": {"strategy": {"entry_threshold": d, "x": 1}},
             "train_nets": {0: v}} for i, (d, v) in enumerate(((0.4, -1.0), (0.45, 9.0), (0.5, -2.0)))]
    inp = _inp([dict(_venster(0, [1.0] * 30), selected_candidate_id=1)])
    inp["candidates"] = kand
    assert A.c_parameter_sensitivity(inp)["status"] == "VERY_SENSITIVE"
    kand[2]["config"] = {"strategy": {"entry_threshold": 0.5, "x": 2}}          # twee verschillen
    assert A.c_parameter_sensitivity(inp)["status"] == A.NOT_APPLICABLE


def test_a_blocked_dataset_blocks_a_positive_classification():
    uit = A.assess(_inp([_venster(i, n) for i, n in enumerate(STERK)], kwaliteit="BLOCKED"))
    assert uit["final_classification"] == A.INSUFF


def test_incompatible_versions_are_not_merged():
    vensters = [_venster(i, n, versies=(2, 4, 1, 1, 1, i)) for i, n in enumerate(STERK)]
    uit = A.assess(_inp(vensters))
    assert uit["final_classification"] == A.INSUFF and "COMPATIBILITY" in uit["blocking"]


def test_raw_and_final_and_trace_are_all_present():
    uit = A.assess(_inp([_venster(i, n) for i, n in enumerate(STERK)]))
    assert {"raw_classification", "final_classification", "classification_ceiling",
            "fidelity_ceiling", "trace", "components"} <= set(uit)
    assert "geen toestemming voor live handel" in uit["explanation"]


def test_there_is_no_hidden_total_score():
    uit = A.assess(_inp([_venster(i, n) for i, n in enumerate(STERK)]))
    assert not {k for k in uit if "score" in k.lower()}
    for c in uit["components"]:
        for veld in ("component_code", "component_version", "status", "required_condition",
                     "blocking", "explanation", "source_result_ids", "source_window_ids"):
            assert veld in c


def test_every_threshold_lives_in_the_rulebook():
    """Geen magische getallen: elk getal in de beoordeling komt uit RULEBOOK,
    behalve structurele constanten (0, 1, 2 en 3 voor 'minstens twee waarden voor
    een spreiding' en 'een punt met twee buren'), en 100 niet eens."""
    boom = ast.parse((PKG / "experiment_lab" / "assessment.py").read_text(encoding="utf-8"))
    rulebook = next(n for n in boom.body if isinstance(n, ast.AnnAssign)
                    and getattr(n.target, "id", "") == "RULEBOOK")
    binnen = {id(n) for n in ast.walk(rulebook)}
    getallen = {n.value for n in ast.walk(boom)
                if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                and not isinstance(n.value, bool) and id(n) not in binnen}
    assert getallen <= {0, 1, 2, 3, 0.0}, sorted(getallen)
    for naam, regel in A.RULEBOOK.items():
        assert regel["reason"] and "value" in regel, naam
