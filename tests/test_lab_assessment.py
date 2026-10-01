"""Experiment Lab, fase 7: de beoordeling op een echte walk-forward - gelogde
TEST-toegang, transactiegrens, onveranderlijkheid, herleidbaarheid."""
import hashlib
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
import test_lab_walk_forward as T  # noqa: E402
from vaste_bars import vaste_bars  # noqa: E402

from gold_scalper.const import STRATEGY_WINDOW_BARS  # noqa: E402
from gold_scalper.experiment_lab.storage import LabDatabase, LabDatabaseError  # noqa: E402
from gold_scalper.experiment_lab.wf_runner import WalkForwardRunner  # noqa: E402


@pytest.fixture(scope="module")
def klaar(tmp_path_factory):
    pad = tmp_path_factory.mktemp("ass") / "gold_scalper_lab.db"
    c = vaste_bars(STRATEGY_WINDOW_BARS + 6 * 96)
    lab = LabDatabase(pad).open()
    eid = T._wf(lab, T._snapshot(lab, c), c, vensters=3)
    lab.close()
    h = WalkForwardRunner(pad).submit_walk_forward(eid)
    assert h.wait(600) and h.final_status == "completed", h.error
    return pad, eid


def _open(pad):
    return LabDatabase(pad).open()


def _hash_resultaten(lab, eid):
    rijen = lab.conn.execute("SELECT id, result_hash FROM wf_results WHERE experiment_id=? ORDER BY id",
                             (eid,)).fetchall()
    return hashlib.sha256(json.dumps([tuple(r) for r in rijen]).encode()).hexdigest()


def test_an_assessment_logs_every_test_window_first(klaar):
    pad, eid = klaar
    lab = _open(pad)
    try:
        aid = lab.create_assessment(eid, "fase7-test")
        a = lab.assessment(aid)
        assert a["status"] == "COMPLETED"
        log = lab.conn.execute("SELECT purpose, assessment_id FROM wf_test_access_log "
                               "WHERE assessment_id=?", (aid,)).fetchall()
        assert len(log) == a["test_access_count"] >= 1
        assert all(r[0] == "ASSESSMENT" for r in log)
    finally:
        lab.close()


def test_sources_point_to_the_exact_results(klaar):
    pad, eid = klaar
    lab = _open(pad)
    try:
        aid = lab.create_assessment(eid, "fase7-test")
        for b in lab.conn.execute("SELECT wf_result_id, result_hash FROM assessment_sources "
                                  "WHERE assessment_id=?", (aid,)):
            assert lab.conn.execute("SELECT result_hash FROM wf_results WHERE id=?",
                                    (b[0],)).fetchone()[0] == b[1]
        snap = json.loads(lab.assessment(aid)["input_json"])
        assert snap["dataset_hash"] and snap["candidate_set_hash"] and snap["access_log_ids"]
    finally:
        lab.close()


def test_a_second_assessment_is_new_and_marks_reuse(klaar):
    """Opnieuw beoordelen is opnieuw TEST lezen: een nieuw assessment, en het
    telt als hergebruik. Het eerste blijft ongewijzigd."""
    pad, eid = klaar
    lab = _open(pad)
    try:
        a1 = lab.create_assessment(eid, "fase7-test")
        voor = dict(lab.conn.execute("SELECT * FROM assessments WHERE id=?", (a1,)).fetchone())
        a2 = lab.create_assessment(eid, "fase7-test")
        assert a2 != a1
        assert dict(lab.conn.execute("SELECT * FROM assessments WHERE id=?", (a1,)).fetchone()) == voor
        tweede = lab.assessment(a2)
        assert tweede["data_reused"] == 1
        assert tweede["components"]["TEST_INDEPENDENCE"]["status"] in ("REUSED", "HEAVILY_REUSED")
        assert tweede["final_classification"] not in ("ROBUST_OUT_OF_SAMPLE",)
    finally:
        lab.close()


def test_an_assessment_is_immutable(klaar):
    pad, eid = klaar
    lab = _open(pad)
    try:
        aid = lab.create_assessment(eid, "fase7-test")
        for sql in ("UPDATE assessments SET final_classification='ROBUST_OUT_OF_SAMPLE' WHERE id=?",
                    "DELETE FROM assessments WHERE id=?",
                    "UPDATE assessment_components SET status='PASS' WHERE assessment_id=?",
                    "DELETE FROM assessment_sources WHERE assessment_id=?"):
            with pytest.raises(sqlite3.DatabaseError):
                lab.conn.execute(sql, (aid,))
    finally:
        lab.close()


def test_a_failed_log_gives_no_assessment(klaar, monkeypatch):
    pad, eid = klaar
    lab = _open(pad)
    try:
        voor = lab.conn.execute("SELECT COUNT(*) FROM wf_test_access_log").fetchone()[0]
        aid = lab.create_assessment(eid, "   ")                  # lege context: log weigert
        a = lab.assessment(aid)
        assert a["status"] == "FAILED" and "niets gelezen" in a["error"]
        assert a["final_classification"] is None and not a["components"]
        assert lab.conn.execute("SELECT COUNT(*) FROM wf_test_access_log").fetchone()[0] == voor
    finally:
        lab.close()


def test_a_failure_after_access_keeps_the_log(klaar, monkeypatch):
    """TEST is gelezen; de beoordeling faalt daarna. De logregels blijven staan."""
    import gold_scalper.experiment_lab.assessment as A
    pad, eid = klaar
    lab = _open(pad)
    try:
        monkeypatch.setattr(A, "assess", lambda inp: (_ for _ in ()).throw(RuntimeError("stuk")))
        aid = lab.create_assessment(eid, "fase7-test")
        a = lab.assessment(aid)
        assert a["status"] == "FAILED" and "logregels blijven staan" in a["error"]
        assert lab.conn.execute("SELECT COUNT(*) FROM wf_test_access_log WHERE assessment_id=?",
                                (aid,)).fetchone()[0] >= 1
        assert not a["components"]
    finally:
        lab.close()


def test_the_assessment_changes_no_experiment_data(klaar):
    pad, eid = klaar
    lab = _open(pad)
    try:
        voor = (_hash_resultaten(lab, eid), lab.get(eid).status,
                [p["config_hash"] for p in lab.parameters(eid)])
        lab.create_assessment(eid, "fase7-test")
        assert (_hash_resultaten(lab, eid), lab.get(eid).status,
                [p["config_hash"] for p in lab.parameters(eid)]) == voor
    finally:
        lab.close()


def test_only_a_completed_walk_forward_can_be_assessed(tmp_path):
    c = vaste_bars(STRATEGY_WINDOW_BARS + 6 * 96)
    lab = _open(tmp_path / "l.db")
    eid = T._wf(lab, T._snapshot(lab, c), c, vensters=3)
    with pytest.raises(LabDatabaseError):
        lab.create_assessment(eid, "fase7-test")
    lab.close()


def test_assessment_purpose_requires_an_assessment(klaar):
    """Het doel ASSESSMENT kan niet los van een beoordeling worden gebruikt."""
    pad, eid = klaar
    lab = _open(pad)
    try:
        with pytest.raises(ValueError):
            lab.open_wf_test_result(eid, 0, "ASSESSMENT", "handmatig")
    finally:
        lab.close()


def test_the_lab_still_cannot_reach_trading():
    """De beoordeling importeert niets uit de handel; de grens blijft staan."""
    from test_lab_boundary import overtredingen, _lab_bestanden, PKG
    assert overtredingen(_lab_bestanden(), PKG) == []
