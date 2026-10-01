"""Experiment Lab, fase 8: reference tegenover challenger, zonder winnaar."""
import ast
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
import test_lab_walk_forward as T  # noqa: E402
from vaste_bars import vaste_bars  # noqa: E402

from gold_scalper.analysis.signals import Candles  # noqa: E402
from gold_scalper.const import STRATEGY_WINDOW_BARS  # noqa: E402
from gold_scalper.experiment_lab import comparison as C  # noqa: E402
from gold_scalper.experiment_lab.storage import LabDatabase  # noqa: E402
from gold_scalper.experiment_lab.wf_runner import WalkForwardRunner  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
N = STRATEGY_WINDOW_BARS + 6 * 96


@pytest.fixture(scope="module")
def drie(tmp_path_factory):
    pad = tmp_path_factory.mktemp("cmp") / "gold_scalper_lab.db"
    c = vaste_bars(N)
    anders = Candles(c.timestamp, *[[round(x + 1.0, 2) for x in r] for r in (c.open, c.high, c.low, c.close)],
                     c.volume)
    lab = LabDatabase(pad).open()
    ds, ds2 = T._snapshot(lab, c), T._snapshot(lab, anders)
    ref = T._wf(lab, ds, c, vensters=3, naam="ref")
    ch = T._wf(lab, ds, c, vensters=3, naam="ch", kandidaten=T.KANDIDATEN[:2])
    elders = T._wf(lab, ds2, anders, vensters=3, naam="elders")
    lab.close()
    runner = WalkForwardRunner(pad)
    for e in (ref, ch, elders):
        h = runner.submit_walk_forward(e)
        assert h.wait(600) and h.final_status == "completed", h.error
    lab = LabDatabase(pad).open()
    for e in (ref, ch, elders):
        lab.create_assessment(e, "fase8")
    lab.close()
    return pad, ref, ch, elders


def _open(pad):
    return LabDatabase(pad).open()


def _toegang(lab):
    return lab.conn.execute("SELECT COUNT(*) FROM wf_test_access_log").fetchone()[0]


def test_assessment_comparison_opens_no_test(drie):
    pad, ref, ch, _ = drie
    lab = _open(pad)
    try:
        voor = _toegang(lab)
        cid = lab.create_comparison(ref, ch)
        assert lab.comparison(cid)["status"] == "COMPLETED" and _toegang(lab) == voor
    finally:
        lab.close()


def test_deep_comparison_logs_first_and_links_to_the_comparison(drie):
    pad, ref, ch, _ = drie
    lab = _open(pad)
    try:
        cid = lab.create_comparison(ref, ch, mode=C.DEEP_RESULT_COMPARISON, accessor_context="fase8")
        log = lab.conn.execute("SELECT purpose, comparison_id FROM wf_test_access_log WHERE comparison_id=?",
                               (cid,)).fetchall()
        assert log and all(r[0] == "COMPARISON" for r in log)
        assert sum(1 for i in lab.comparison(cid)["items"] if i["section"] == "metric") == 38
    finally:
        lab.close()


def test_a_failed_log_gives_no_comparison(drie):
    pad, ref, ch, _ = drie
    lab = _open(pad)
    try:
        voor = _toegang(lab)
        cid = lab.create_comparison(ref, ch, mode=C.DEEP_RESULT_COMPARISON, accessor_context="  ")
        v = lab.comparison(cid)
        assert v["status"] == "FAILED" and "niets gelezen" in v["error"] and not v["items"]
        assert _toegang(lab) == voor
    finally:
        lab.close()


def test_another_dataset_is_not_comparable(drie):
    """Zelfde symbool en periode, andere inhoud: de hash beslist."""
    pad, ref, _, elders = drie
    lab = _open(pad)
    try:
        v = lab.comparison(lab.create_comparison(ref, elders))
        assert v["comparability_status"] == C.NOT_COMPARABLE and v["result"] == C.INSUFFICIENT_COMPARABILITY
        assert v["checks"]["dataset_hash"]["status"] == C.DIFFERENT
        assert v["checks"]["symbol"]["status"] == C.SAME
        vensters = [i for i in v["items"] if i["section"] == "window"]
        assert vensters and all(i["status"] == C.NOT_COMPARABLE for i in vensters)
    finally:
        lab.close()


def test_other_candidates_make_it_partial_and_visible(drie):
    pad, ref, ch, _ = drie
    lab = _open(pad)
    try:
        v = lab.comparison(lab.create_comparison(ref, ch))
        assert v["comparability_status"] == C.PARTIAL
        assert v["checks"]["candidate_set_hash"]["status"] == C.DIFFERENT
        sel = next(i for i in v["items"] if i["section"] == "selection" and i["item_key"] == "candidate_set_hash")
        assert sel["status"] == C.DIFFERENT
    finally:
        lab.close()


def test_all_compatible_windows_and_components_are_included(drie):
    pad, ref, ch, _ = drie
    lab = _open(pad)
    try:
        v = lab.comparison(lab.create_comparison(ref, ch))
        assert len([i for i in v["items"] if i["section"] == "window"]) == 3
        codes = {i["item_key"] for i in v["items"] if i["section"] == "component"}
        assert len(codes) == 14 and "TEST_INDEPENDENCE" in codes
        klassen = {i["item_key"] for i in v["items"] if i["section"] == "classification"}
        assert klassen == {"raw_classification", "classification_ceiling", "final_classification"}
    finally:
        lab.close()


def _cs(**afwijking):
    basis = {c: 1 for c in C.HARD + C.SOFT}
    return C.checks(basis, {**basis, **afwijking})


def test_metric_deltas_are_guarded():
    a = {"value": 10.0, "calculation_status": "VALID", "unit": "bedrag", "currency": "instrument", "sample_size": 5}
    b = {"value": 12.0, "calculation_status": "VALID", "unit": "bedrag", "currency": "instrument", "sample_size": 6}
    ok = C.metric_delta("net_pnl", a, b, _cs())
    assert ok["status"] == "COMPARED" and ok["absolute_delta"] == 2.0 and ok["relative_delta"] == 0.2
    assert C.metric_delta("net_pnl", a, b, _cs(metrics_version=2))["status"] == C.NOT_COMPARABLE
    assert C.metric_delta("net_pnl", a, b, _cs(cost_model=2))["status"] == C.NOT_COMPARABLE
    assert C.metric_delta("gross_pnl", a, b, _cs(cost_model=2))["status"] == "COMPARED"   # bruto wel
    assert C.metric_delta("net_pnl", a, b, _cs(instrument_currency=2))["status"] == C.NOT_COMPARABLE
    assert C.metric_delta("net_pnl", a, b, _cs(window_intervals=2))["status"] == C.NOT_COMPARABLE
    nul = C.metric_delta("net_pnl", {**a, "value": 0.0}, b, _cs())
    assert nul["relative_delta"] is None and nul["absolute_delta"] == 12.0
    ongeldig = C.metric_delta("profit_factor", {**a, "calculation_status": "NOT_APPLICABLE", "value": None}, b, _cs())
    assert ongeldig["status"] == "NOT_APPLICABLE" and ongeldig["relative_delta"] is None


def test_lower_fidelity_with_a_better_result_is_flagged():
    ref = {"execution_fidelity": "HIGH_EXECUTION_FIDELITY", "final_rank": 1, "assessment_rules_version": 1}
    ch = {"execution_fidelity": "LIMITED_EXECUTION_FIDELITY", "final_rank": 2, "assessment_rules_version": 1}
    assert any("RESULT_WITH_LOWER_FIDELITY" in f for f in C.flags(ref, ch, []))
    ch2 = {**ch, "test_independence": "REUSED", "assessment_rules_version": 2}
    vl = C.flags(ref, ch2, [])
    assert any("TEST_REUSED" in f for f in vl) and any("ASSESSMENT_RULES_DIFFER" in f for f in vl)


def test_component_semantics_are_not_forced():
    same = C.component_delta("EXECUTION_FIDELITY", {"status": "WARNING"}, {"status": "WARNING"})
    assert same["explanation"] == "geen verschil"
    lager = C.component_delta("TEST_INDEPENDENCE", {"status": "INDEPENDENT"}, {"status": "REUSED"})
    assert "lagere TEST-onafhankelijkheid bij challenger" in lager["explanation"]


def test_comparisons_are_immutable_and_do_not_touch_sources(drie):
    pad, ref, ch, _ = drie
    lab = _open(pad)
    try:
        ass_voor = [dict(r) for r in lab.conn.execute("SELECT * FROM assessments ORDER BY id")]
        res_voor = lab.conn.execute("SELECT group_concat(result_hash) FROM wf_results").fetchone()[0]
        cid = lab.create_comparison(ref, ch)
        for sql in ("UPDATE comparisons SET result='COMPARED' WHERE id=?",
                    "DELETE FROM comparisons WHERE id=?",
                    "UPDATE comparison_items SET status='X' WHERE comparison_id=?",
                    "DELETE FROM comparison_checks WHERE comparison_id=?"):
            with pytest.raises(sqlite3.DatabaseError):
                lab.conn.execute(sql, (cid,))
        assert [dict(r) for r in lab.conn.execute("SELECT * FROM assessments ORDER BY id")] == ass_voor
        assert lab.conn.execute("SELECT group_concat(result_hash) FROM wf_results").fetchone()[0] == res_voor
        assert lab.create_comparison(ref, ch) != cid                     # nieuwe rij, nooit overschreven
    finally:
        lab.close()


def test_the_input_snapshot_has_exact_hashes(drie):
    import json
    pad, ref, ch, _ = drie
    lab = _open(pad)
    try:
        inp = json.loads(lab.comparison(lab.create_comparison(ref, ch))["input_json"])
        for side in ("reference", "challenger"):
            assert inp[side]["dataset_hash"] and inp[side]["candidate_set_hash"]
            assert all(s["result_hash"] for s in inp[side]["assessment_sources"])
        assert inp["comparison_rules"]["version"] == C.COMPARISON_RULES_VERSION
    finally:
        lab.close()


def test_there_is_no_winner_or_promotion_path():
    bron = (PKG / "experiment_lab" / "comparison.py").read_text(encoding="utf-8")
    boom = ast.parse(bron)
    namen = {n.name for n in ast.walk(boom) if isinstance(n, (ast.FunctionDef, ast.ClassDef))} | \
            {t.id for n in ast.walk(boom) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    for verboden in ("winner", "best_strategy", "promote", "activate", "apply", "make_champion",
                     "enable_strategy", "set_live", "use_challenger", "copy_to_options"):
        assert not any(verboden in n.lower() for n in namen), verboden
    opslag = (PKG / "experiment_lab" / "storage.py").read_text(encoding="utf-8")
    assert "winner" not in opslag and "promote" not in opslag.lower()


def test_the_lab_still_cannot_reach_trading():
    from test_lab_boundary import overtredingen, _lab_bestanden, PKG as P
    assert overtredingen(_lab_bestanden(), P) == []


def test_the_rebuilt_cost_model_is_pinned_to_the_assessed_configuration(drie):
    """Kostenmodel alleen uit de onveranderlijke configuratie, met hash in de
    snapshot. Wijkt de configuratie af van wat de beoordeling zag, dan UNKNOWN."""
    import json
    pad, ref, ch, _ = drie
    lab = _open(pad)
    try:
        v = lab.comparison(lab.create_comparison(ref, ch))
        inp = json.loads(v["input_json"])
        assert inp["reference"]["cost_model_hash"] and inp["challenger"]["cost_model_hash"]
        kant = lab._comparison_side(ref, v["reference_assessment_id"])
        assert kant["cost_model"] is not None
        # Nabootsen dat de beoordeling een andere configuratie zag.
        a = lab.assessment(v["reference_assessment_id"])
        snap = json.loads(a["input_json"])
        snap["candidates"][0]["config_hash"] = "0" * 64
        origineel = lab.assessment
        lab.assessment = lambda aid: {**origineel(aid), "input_json": json.dumps(snap)}
        assert lab._comparison_side(ref, v["reference_assessment_id"])["cost_model"] is None
    finally:
        lab.close()
