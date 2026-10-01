"""Experiment Lab, fase 6: walk-forward van begin tot eind, op vaste data.

Drie experimenten in één database (gedeeld door de tests, één keer gedraaid):
A kandidaatselectie op TRAIN; B met een validatievoorwaarde die niet te halen
is; C opeenvolgende OOS met TEST-vensters die A half overlappen.
"""
import json
import os
import sqlite3
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from vaste_bars import vaste_bars  # noqa: E402

from gold_scalper.analysis.signals import Candles  # noqa: E402
from gold_scalper.const import STRATEGY_WINDOW_BARS  # noqa: E402
from gold_scalper.experiment_lab import datasets as D  # noqa: E402
from gold_scalper.experiment_lab import walk_forward as W  # noqa: E402
from gold_scalper.experiment_lab.metrics import REQUIRED_METRICS  # noqa: E402
from gold_scalper.experiment_lab.models import Experiment, IllegalTransition, config_hash  # noqa: E402
from gold_scalper.experiment_lab.storage import LabDatabase  # noqa: E402
from gold_scalper.experiment_lab.wf_runner import WalkForwardRunner  # noqa: E402

BAR, DAG = 900, 96 * 900
N = STRATEGY_WINDOW_BARS + 600
FAMILIE = "wf drempel"


def _cfg(drempel):
    return {"strategy": {"entry_threshold": drempel, "take_profit_atr": 1.5, "stop_loss_atr": 1.0,
                         "volume": 0.02, "max_spread_atr_ratio": 0.75},
            "exits": {"max_hold_seconds": 900},
            "execution": {"spread": 0.7, "slippage": 0.02, "units": 2.0, "instrument_currency": "USD"}}


KANDIDATEN = [("laag", _cfg(0.40)), ("midden", _cfg(0.45)), ("hoog", _cfg(0.50))]


def _snapshot(lab, c):
    bars = [D.BarInput(t, o, h, l, cl, v, "vast", "closed")
            for t, o, h, l, cl, v in zip(c.timestamp, c.open, c.high, c.low, c.close, c.volume)]
    spec = D.DatasetSpec("GOLD", "15m", 2, "instrument_metadata", "vast")
    return lab.create_snapshot(D.prepare(spec, bars, None, c.timestamp[-1] + 10 * BAR), "test")[0]


def _wf(lab, ds, c, *, modus=W.CANDIDATE_SELECTION, regel=None, kandidaten=KANDIDATEN,
        val=0, verschuiving=0, vensters=2, registreren=True, naam="wf"):
    eid = lab.create(Experiment(
        name=naam, type="walk_forward", hypothesis="h", expected_effect="e", primary_metric="net_pnl",
        evaluation_method="walk-forward", hypothesis_family_id=FAMILIE, software_version="5.5.0",
        strategy_version="scalp-0.2.0", execution_semantics_version=3,
        config_hash=config_hash({"kandidaten": [k[0] for k in kandidaten]}), dataset_id=ds))
    ids = [(label, lab.add_parameters(eid, "candidate", cfg)) for label, cfg in kandidaten]
    regel = regel or W.SelectionRule("net_pnl", W.MAXIMIZE,
                                     tie_break=(("maximum_drawdown", W.MINIMIZE), W.CONFIG_HASH_TIEBREAK))
    start = c.timestamp[STRATEGY_WINDOW_BARS] + verschuiving
    args = dict(first_train_start=start, train_length=2 * DAG, validation_length=val,
                test_length=DAG, step_size=DAG + val, window_count=vensters, max_hold_seconds=900)
    ramen = W.build_windows(modus, W.ROLLING, list(c.timestamp), BAR, **args)
    lab.save_walk_forward(eid, mode=modus, window_type=W.ROLLING, windows=ramen, rule=regel,
                          bar_seconds=BAR, candidates=ids,
                          **{k: v for k, v in args.items() if k != "window_count"})
    if registreren:
        lab.transition(eid, "registered")
    return eid


@pytest.fixture(scope="module")
def drie(tmp_path_factory):
    pad = tmp_path_factory.mktemp("wf") / "gold_scalper_lab.db"
    c = vaste_bars(N)
    lab = LabDatabase(pad).open()
    ds = _snapshot(lab, c)
    a = _wf(lab, ds, c, naam="A")
    b = _wf(lab, ds, c, naam="B", val=DAG, regel=W.SelectionRule(
        "net_pnl", W.MAXIMIZE, tie_break=(W.CONFIG_HASH_TIEBREAK,),
        validation_policy=W.TRAIN_THEN_VALIDATION,
        validation_condition={"metric": "net_pnl", "operator": ">", "threshold": 1e9}))
    cc = _wf(lab, ds, c, naam="C", modus=W.SEQUENTIAL_OOS, kandidaten=[KANDIDATEN[1]],
             verschuiving=DAG // 2)
    lab.close()
    runner = WalkForwardRunner(pad)
    handles = {}
    for naam, eid in (("A", a), ("B", b), ("C", cc)):
        h = runner.submit_walk_forward(eid)
        assert h.wait(600) and h.final_status == "completed", (naam, h.error)
        handles[naam] = h
    return pad, ds, c, {"A": a, "B": b, "C": cc}, handles


def _open(pad):
    return LabDatabase(pad).open()


# ---------------- plan en vergrendeling ----------------

def test_the_plan_and_candidates_are_locked(drie):
    pad, _, _, ids, _ = drie
    lab = _open(pad)
    try:
        for sql in ("UPDATE wf_plans SET primary_metric='win_rate' WHERE experiment_id=?",
                    "DELETE FROM wf_candidates WHERE experiment_id=?",
                    "UPDATE wf_segments SET end_ts = end_ts + 900 WHERE experiment_id=?"):
            with pytest.raises(sqlite3.DatabaseError):
                lab.conn.execute(sql, (ids["A"],))
        with pytest.raises(sqlite3.DatabaseError):
            lab.add_parameters(ids["A"], "candidate", _cfg(0.6))
    finally:
        lab.close()


def test_candidate_set_hash_is_stored_and_order_independent(tmp_path):
    c = vaste_bars(N)
    hashes = []
    for volgorde in (KANDIDATEN, list(reversed(KANDIDATEN))):
        lab = _open(tmp_path / f"h{len(hashes)}.db")
        eid = _wf(lab, _snapshot(lab, c), c, kandidaten=volgorde, registreren=False)
        hashes.append(lab.wf_plan(eid)["candidate_set_hash"])
        lab.close()
    assert hashes[0] == hashes[1]


# ---------------- selectie en volgorde ----------------

def test_selection_uses_only_train_and_is_recorded(drie):
    pad, _, _, ids, _ = drie
    lab = _open(pad)
    try:
        for w in lab.wf_plan(ids["A"])["windows"]:
            sel = lab.conn.execute("SELECT * FROM wf_selections WHERE window_id=?", (w["id"],)).fetchone()
            evals = lab.conn.execute("SELECT * FROM wf_candidate_evaluations WHERE window_id=?",
                                     (w["id"],)).fetchall()
            assert sel is not None and len(evals) == 3
            for e in evals:
                bron = lab.conn.execute("SELECT kind FROM wf_results WHERE id=?",
                                        (e["train_result_id"],)).fetchone()[0]
                assert bron == "TRAIN"
            testen = lab.conn.execute("SELECT candidate_id FROM wf_results WHERE window_id=? "
                                      "AND kind='TEST'", (w["id"],)).fetchall()
            if sel["selection_status"] == "SELECTED":
                assert [t[0] for t in testen] == [sel["selected_candidate_id"]]
            else:
                assert testen == []
    finally:
        lab.close()


def test_a_failed_validation_never_tries_another_candidate(drie):
    pad, _, _, ids, _ = drie
    lab = _open(pad)
    try:
        for w in lab.wf_plan(ids["B"])["windows"]:
            assert w["status"] in ("VALIDATION_REJECTED", "NO_SELECTION")
            val = lab.conn.execute("SELECT candidate_id FROM wf_results WHERE window_id=? "
                                   "AND kind='VALIDATION'", (w["id"],)).fetchall()
            assert len(val) <= 1
            assert lab.conn.execute("SELECT COUNT(*) FROM wf_results WHERE window_id=? "
                                    "AND kind='TEST'", (w["id"],)).fetchone()[0] == 0
    finally:
        lab.close()


def test_sequential_oos_selects_nothing(drie):
    pad, _, _, ids, _ = drie
    lab = _open(pad)
    try:
        assert lab.conn.execute("SELECT COUNT(*) FROM wf_results WHERE experiment_id=? "
                                "AND kind<>'TEST'", (ids["C"],)).fetchone()[0] == 0
        assert lab.conn.execute("SELECT COUNT(*) FROM wf_selections WHERE experiment_id=?",
                                (ids["C"],)).fetchone()[0] == 0
        assert all(w["status"] == "COMPLETED" for w in lab.wf_plan(ids["C"])["windows"])
    finally:
        lab.close()


def test_test_needs_a_recorded_selection_in_the_database(tmp_path):
    """TEST zonder vastgelegde keuze: de database weigert, ook bij rechtstreekse SQL."""
    c = vaste_bars(N)
    lab = _open(tmp_path / "l.db")
    eid = _wf(lab, _snapshot(lab, c), c)
    lab.transition(eid, "queued")
    lab.begin_run(eid, "test")
    w = lab.wf_plan(eid)["windows"][0]
    with pytest.raises(IllegalTransition):
        lab.set_window_status(w["id"], "TESTING" if False else "COMPLETED")
    with pytest.raises(sqlite3.DatabaseError):                       # PENDING -> TESTING bij selectie
        lab.conn.execute("UPDATE wf_windows SET status='TESTING' WHERE id=?", (w["id"],))
    lab.set_window_status(w["id"], "TRAINING")
    lab.set_window_status(w["id"], "SELECTING")
    lab.set_window_status(w["id"], "TESTING")
    seg = w["segments"]["TEST"]["id"]
    kand = lab.wf_plan(eid)["candidates"][0]["id"]
    with pytest.raises(sqlite3.DatabaseError, match="vastgelegde"):
        lab.conn.execute(
            "INSERT INTO wf_results (wf_segment_id, window_id, experiment_id, candidate_id, kind, "
            "result_hash, summary_json, cost_model_json, result_schema_version, "
            "backtest_engine_version, cost_model_version, metrics_version, segment_schema_version, "
            "walk_forward_schema_version, trade_count, cross_boundary_count, "
            "segment_end_close_count, forced_exit_json, warmup_status, created_at) "
            "VALUES (?,?,?,?,'TEST','x','{}','{}',2,4,1,1,1,1,0,0,0,'{}','FULL_WARMUP','nu')",
            (seg, w["id"], eid, kand))
    lab.close()


def test_test_data_does_not_change_the_selection(tmp_path):
    """Twee datasets die alleen in de TEST-periode verschillen: dezelfde keuze,
    dezelfde TRAIN-uitkomsten."""
    basis = vaste_bars(N)
    test_start = basis.timestamp[STRATEGY_WINDOW_BARS] + 2 * DAG
    anders = Candles(basis.timestamp, *[[round(x + (30.0 if t >= test_start else 0.0), 2)
                                         for t, x in zip(basis.timestamp, r)]
                                        for r in (basis.open, basis.high, basis.low, basis.close)],
                     basis.volume)
    uitkomst = []
    for i, c in enumerate((basis, anders)):
        pad = tmp_path / f"l{i}.db"
        lab = _open(pad)
        eid = _wf(lab, _snapshot(lab, c), c, vensters=1)
        lab.close()
        assert WalkForwardRunner(pad).submit_walk_forward(eid).wait(600)
        lab = _open(pad)
        sel = lab.conn.execute("SELECT selection_status, selected_config_hash FROM wf_selections "
                               "WHERE experiment_id=?", (eid,)).fetchone()
        train = sorted(r[0] for r in lab.conn.execute(
            "SELECT result_hash FROM wf_results WHERE experiment_id=? AND kind='TRAIN'", (eid,)))
        uitkomst.append((tuple(sel), train))
        lab.close()
    assert uitkomst[0] == uitkomst[1]


# ---------------- afscherming en toegang ----------------

def test_the_overview_leaks_no_test_values(drie):
    pad, _, _, ids, _ = drie
    lab = _open(pad)
    try:
        o = lab.wf_overview(ids["A"])
        tekst = json.dumps(o)
        for verboden in ("net_pnl", "win_rate", "profit_factor", "expectancy", "drawdown"):
            assert verboden not in tekst
        assert o["windows_total"] == 2 and o["test_unopened"] + o["test_opened"] >= 0
    finally:
        lab.close()


def test_opening_a_window_logs_first_and_reuse_is_detected(drie):
    pad, _, _, ids, _ = drie
    lab = _open(pad)
    try:
        klaar = [w for w in lab.wf_plan(ids["A"])["windows"] if w["status"] == "COMPLETED"]
        assert klaar, "geen voltooid venster in A"
        idx = klaar[0]["window_index"]
        eerst = lab.open_wf_test_result(ids["A"], idx, "FINAL_EVALUATION", "test")
        assert len(eerst["metrics"]) == len(REQUIRED_METRICS)
        tweede = lab.open_wf_test_result(ids["A"], idx, "AUDIT", "test")
        assert tweede["data_reused"] and tweede["prior_access_count"] >= 1
        with pytest.raises(sqlite3.IntegrityError):
            lab.open_wf_test_result(ids["A"], idx, "AUDIT", "  ")
        for sql in ("UPDATE wf_test_access_log SET purpose='AUDIT'", "DELETE FROM wf_test_access_log"):
            with pytest.raises(sqlite3.DatabaseError):
                lab.conn.execute(sql)
    finally:
        lab.close()


def test_overlapping_test_intervals_between_experiments_are_recorded(drie):
    pad, _, _, ids, _ = drie
    lab = _open(pad)
    try:
        for w in lab.wf_plan(ids["A"])["windows"]:
            if w["status"] == "COMPLETED":
                lab.open_wf_test_result(ids["A"], w["window_index"], "FINAL_EVALUATION", "test")
        uit = lab.open_wf_test_result(ids["C"], 0, "FINAL_EVALUATION", "test")
        assert uit["overlapping_prior_count"] >= 1
        rij = lab.conn.execute("SELECT overlap_seconds, overlap_bars FROM wf_test_access_log "
                               "WHERE experiment_id=? ORDER BY id DESC LIMIT 1", (ids["C"],)).fetchone()
        assert rij["overlap_seconds"] > 0 and rij["overlap_bars"] > 0
        assert any(n["kind"] == "OVERLAPPING_TEST_DATA" for n in lab.annotations(ids["C"]))
    finally:
        lab.close()


def test_the_oos_aggregate_is_sealed_and_counts_no_window_twice(drie):
    pad, _, _, ids, _ = drie
    lab = _open(pad)
    try:
        voor = lab.conn.execute("SELECT COUNT(*) FROM wf_test_access_log WHERE experiment_id=?",
                                (ids["C"],)).fetchone()[0]
        agg = lab.open_oos_aggregate(ids["C"], "FINAL_EVALUATION", "test")
        na = lab.conn.execute("SELECT COUNT(*) FROM wf_test_access_log WHERE experiment_id=?",
                              (ids["C"],)).fetchone()[0]
        assert na - voor == len(agg["included_window_ids"]) == 2
        los = sum(lab.conn.execute("SELECT trade_count FROM wf_results WHERE window_id=? AND kind='TEST'",
                                   (w,)).fetchone()[0] for w in agg["included_window_ids"])
        assert agg["trade_count"] == los
        assert agg["metrics"]["trade_count"]["value"] == los
        assert agg["currency"] == "USD" and agg["versions"]["walk_forward_schema_version"] == 1
        assert "segment_end_close_count" in agg["forced_exits"]
    finally:
        lab.close()


# ---------------- tellers, voortgang, gedwongen sluitingen ----------------

def test_family_counters(drie):
    pad, _, _, _, _ = drie
    lab = _open(pad)
    try:
        f = lab.family_summary(FAMILIE)
        assert f["candidates_registered"] == 3 + 3 + 1
        assert f["train_runs"] == 2 * 3 + 2 * 3            # A en B: 2 vensters x 3 kandidaten
        assert f["unique_train_configurations"] == 6       # zelfde configs, maar ander plan per experiment
        assert f["test_executions"] >= 2
    finally:
        lab.close()


def test_progress_is_monotone_and_complete(drie):
    pad, _, _, ids, _ = drie
    lab = _open(pad)
    try:
        run = lab.run_state(ids["A"])
        assert run["progress_pct"] == 100 and run["windows_completed"] == 2
    finally:
        lab.close()


def test_forced_exits_are_visible_per_window(drie):
    pad, _, _, ids, _ = drie
    lab = _open(pad)
    try:
        for r in lab.conn.execute("SELECT forced_exit_json, segment_end_close_count FROM wf_results "
                                  "WHERE experiment_id=?", (ids["A"],)):
            f = json.loads(r[0])
            assert f["segment_end_close_count"] == r[1] and f["forced_exit_policy"]
    finally:
        lab.close()


# ---------------- annuleren, falen, onderbreken ----------------

def test_cancelling_starts_no_next_unit(tmp_path):
    c = vaste_bars(N)
    pad = tmp_path / "l.db"
    lab = _open(pad)
    eid = _wf(lab, _snapshot(lab, c), c)
    lab.close()
    h = WalkForwardRunner(pad).submit_walk_forward(eid)
    time.sleep(2.0)
    h.cancel()
    assert h.wait(120) and h.final_status == "cancelled"
    lab = _open(pad)
    try:
        assert lab.get(eid).status == "cancelled"
        assert lab.conn.execute("SELECT COUNT(*) FROM wf_results WHERE experiment_id=? AND kind='TEST'",
                                (eid,)).fetchone()[0] == 0
        assert all(w["status"] == "CANCELLED" for w in lab.wf_plan(eid)["windows"])
        from gold_scalper.experiment_lab.storage import LabDatabaseError
        with pytest.raises((sqlite3.DatabaseError, LabDatabaseError)):
            lab.open_oos_aggregate(eid, "AUDIT", "test")
    finally:
        lab.close()


def test_a_failing_worker_fails_the_whole_experiment(tmp_path):
    c = vaste_bars(N)
    pad = tmp_path / "l.db"
    lab = _open(pad)
    eid = _wf(lab, _snapshot(lab, c), c)
    lab.close()
    kapot = [sys.executable, "-I", "-c",
             "import json,sys; sys.stdin.readline(); print(json.dumps({'type':'error','message':'kapot'}),flush=True)"]
    h = WalkForwardRunner(pad, worker_command=kapot).submit_walk_forward(eid)
    assert h.wait(60) and h.final_status == "failed"
    lab = _open(pad)
    try:
        assert lab.get(eid).status == "failed"
        assert lab.conn.execute("SELECT COUNT(*) FROM wf_selections WHERE experiment_id=?",
                                (eid,)).fetchone()[0] == 0
    finally:
        lab.close()


def test_a_vanishing_worker_interrupts(tmp_path):
    c = vaste_bars(N)
    pad = tmp_path / "l.db"
    lab = _open(pad)
    eid = _wf(lab, _snapshot(lab, c), c)
    lab.close()
    weg = [sys.executable, "-I", "-c", "import sys; sys.stdin.readline()"]
    h = WalkForwardRunner(pad, worker_command=weg).submit_walk_forward(eid)
    assert h.wait(60) and h.final_status == "interrupted"
    lab = _open(pad)
    try:
        assert lab.get(eid).status == "interrupted"
        assert all(w["status"] == "INTERRUPTED" for w in lab.wf_plan(eid)["windows"])
    finally:
        lab.close()


def test_the_worker_stays_free_of_trading_modules(drie):
    _, _, _, _, handles = drie
    geladen = set(handles["A"].loaded_modules)
    assert geladen and not {m for m in geladen if m.split(".")[0] == "homeassistant"}
    assert "gold_scalper.coordinator" not in geladen and "gold_scalper.broker.ig_capital" not in geladen
