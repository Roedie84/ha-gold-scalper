"""1.3.0: namen met komma's, voortgangstellers bij walk-forward, componentdetails."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
import gold_scalper.lab_read_models as R  # noqa: E402
from gold_scalper.const import STRATEGY_WINDOW_BARS  # noqa: E402
from gold_scalper.experiment_lab.storage import LabDatabase  # noqa: E402
from gold_scalper.experiment_lab.wf_runner import WalkForwardRunner  # noqa: E402
from gold_scalper.lab_actions import NAAM, NAAM_UITLEG, LabActions  # noqa: E402
from vaste_bars import vaste_bars  # noqa: E402


@pytest.mark.parametrize("naam", ["bruto OOS huidige strategie, juni-augustus",
                                  "drempel 0.45 (trend & range)", "één"])
def test_names_with_commas_and_accents_are_allowed(naam):
    assert NAAM.match(naam)


@pytest.mark.parametrize("naam", ['met "aanhaling"', "regel\neinde", "x" * 81, ""])
def test_unsafe_names_are_refused(naam):
    assert not NAAM.match(naam)


def test_the_error_says_which_characters(tmp_path):
    acties = LabActions(tmp_path / "l.db", None, None)
    LabDatabase(tmp_path / "l.db").open().close()
    r = acties.run("create_walk_forward", {"name": 'met "aanhaling"', "dataset_id": 1})
    assert r["error"]["message"] == f"name: {NAAM_UITLEG}"
    assert "," in NAAM_UITLEG


@pytest.fixture(scope="module")
def wf(tmp_path_factory):
    import test_lab_walk_forward as T

    pad = tmp_path_factory.mktemp("r130") / "lab.db"
    c = vaste_bars(STRATEGY_WINDOW_BARS + 5 * 96)
    db = LabDatabase(pad).open()
    eid = T._wf(db, T._snapshot(db, c), c, kandidaten=[T.KANDIDATEN[1]], modus=T.W.SEQUENTIAL_OOS)
    db.close()
    h = WalkForwardRunner(pad).submit_walk_forward(eid)
    assert h.wait(600) and h.final_status == "completed", h.error
    db = LabDatabase(pad).open()
    yield db, eid
    db.close()


def test_walk_forward_fills_the_bar_counters(wf):
    db, eid = wf
    p = R.experiment_progress(db, eid)
    assert p["bars_total"] > 0
    assert p["bars_processed"] == p["bars_total"]


def test_assessment_detail_carries_component_details(wf):
    db, eid = wf
    a = R.assessment_detail(db, db.create_assessment(eid, "test130"))
    bruto = next(c for c in a["components"] if c["code"] == "GROSS_EVIDENCE")
    assert {"mean_gross", "mean_net", "mean_cost", "standard_error"} <= set(bruto["details"])
    assert all("details" in c for c in a["components"])
    assert R.READ_MODEL_VERSION == 2


def test_details_are_plain_and_bounded():
    uit = R._gewoon({"a": [1, 2.5, "x" * 400, None, True], "b": {"c": object()}})
    assert uit["a"][2] == "x" * 300 and uit["b"]["c"] is None
