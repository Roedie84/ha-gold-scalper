"""5.7 (fase 9B deel 1): Lab-acties, leesmodellen, lifecycle en administratie.

EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING
"""
import ast
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
import gold_scalper.lab_panel as lp  # noqa: E402
import gold_scalper.lab_read_models as R  # noqa: E402
from gold_scalper.const import STRATEGY_WINDOW_BARS  # noqa: E402
from gold_scalper.experiment_lab import storage as S  # noqa: E402
from gold_scalper.experiment_lab.storage import LabDatabase  # noqa: E402
from gold_scalper.experiment_lab.wf_runner import WalkForwardRunner  # noqa: E402
from gold_scalper.lab_actions import ACTION_FIELDS, LabActions  # noqa: E402
from vaste_bars import vaste_bars  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
TEST_METRIEKEN = {"net_pnl", "gross_pnl", "expectancy", "profit_factor", "win_rate",
                  "maximum_drawdown", "max_drawdown", "trades", "trade_count", "average_trade"}


def _cfg(drempel=0.45, **execution):
    return {"strategy": {"entry_threshold": drempel, "take_profit_atr": 1.5, "stop_loss_atr": 1.0,
                         "volume": 0.02, "max_spread_atr_ratio": 0.75},
            "exits": {"max_hold_seconds": 900},
            "execution": {"spread": 0.7, "slippage": 0.02, "units": 2.0,
                          "instrument_currency": "USD", **execution}}


def _wf_params(ds, **extra):
    p = {"name": "basis", "hypothesis": "bruto OOS per trade is niet nul",
         "expected_effect": "onbekend", "hypothesis_family_id": "bruto-oos",
         "dataset_id": ds, "train_days": 2, "test_days": 1, "window_count": 3,
         "mode": "SEQUENTIAL_OOS", "candidates": [{"label": "basis", "config": _cfg()}]}
    p.update(extra)
    return p


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    from gold_scalper.storage.bar_archive import BarArchive

    map_ = tmp_path_factory.mktemp("lab57")
    archief = BarArchive(map_ / "bars.db")
    archief.connect()
    archief.store("GOLD", "15m", vaste_bars(STRATEGY_WINDOW_BARS + 6 * 96), "quotes")
    pad = map_ / "gold_scalper_lab.db"
    LabDatabase(pad).open().close()
    acties = LabActions(pad, map_ / "bars.db", WalkForwardRunner(pad))
    snap = acties.run("snapshot", {"symbol": "GOLD", "timeframe": "15m"})
    assert snap["ok"], snap
    ds = snap["object_id"]
    eid = acties.run("create_walk_forward", _wf_params(ds))["object_id"]
    assert acties.run("register", {"experiment_id": eid})["ok"]
    assert acties.run("start", {"experiment_id": eid})["ok"]
    h = acties._runner.active
    assert h.wait(600) and h.final_status == "completed", h.error
    return SimpleNamespace(pad=pad, map=map_, acties=acties, ds=ds, eid=eid)


def _db(lab):
    return LabDatabase(lab.pad).open()


def _sleutels(obj, pad=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _sleutels(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _sleutels(v)


# ----------------------------------------------------------------- acties --

def test_snapshot_response_is_complete_and_readable(lab):
    r = lab.acties.run("snapshot", {"symbol": "GOLD", "timeframe": "15m"})
    assert r["ok"] and r["data"]["reused"] is True and r["object_id"] == lab.ds
    for k in ("dataset_id", "reused", "symbol", "timeframe", "start", "end", "bar_count",
              "dataset_hash", "quality_status", "quality_findings"):
        assert k in r["data"]
    assert r["message"].startswith(f"Dataset {lab.ds} hergebruikt")


def test_register_and_start_responses(lab):
    db = _db(lab)
    try:
        exp = db.get(lab.eid)
        assert exp.status == "completed"
    finally:
        db.close()
    d = lab.acties.run("create_walk_forward", _wf_params(lab.ds, name="tweede"))
    r = lab.acties.run("register", {"experiment_id": d["object_id"]})
    for k in ("experiment_id", "status", "hypothesis_family_id", "dataset", "windows",
              "candidates", "mode", "plan_hash", "candidate_set_hash"):
        assert k in r["data"]
    assert "TEST blijft verzegeld." in r["message"]
    assert lab.acties.run("cancel", {"experiment_id": d["object_id"]})["data"]["new_status"] == "cancelled"


def test_start_and_cancel_a_running_experiment(lab):
    d = lab.acties.run("create_walk_forward", _wf_params(lab.ds, name="annuleren"))
    eid = d["object_id"]
    lab.acties.run("register", {"experiment_id": eid})
    s = lab.acties.run("start", {"experiment_id": eid})
    assert s["data"]["progress_started"] is True
    c = lab.acties.run("cancel", {"experiment_id": eid})
    assert c["ok"] and c["data"]["active_worker"] is True
    assert c["data"]["new_status"] in ("cancelled", "completed")


def test_assessment_is_the_first_test_access(lab):
    db = _db(lab)
    try:
        voor = R.test_status(db, lab.eid)
    finally:
        db.close()
    assert voor["test_executed"] and not voor["test_opened"] and voor["prior_access_count"] == 0
    a = lab.acties.run("assess", {"experiment_id": lab.eid})
    assert a["ok"], a
    for k in ("assessment_id", "raw_classification", "fidelity_ceiling", "final_classification",
              "blocking_reasons", "warnings", "test_independence", "data_reused",
              "rules_version", "disclaimer"):
        assert k in a["data"]
    assert a["data"]["test_independence"] == "INDEPENDENT"
    assert R.DISCLAIMER in a["message"]
    db = _db(lab)
    try:
        na = R.test_status(db, lab.eid)
    finally:
        db.close()
    assert na["test_opened"] and na["prior_access_count"] > 0


def test_comparison_defaults_to_assessment_mode_and_opens_nothing(lab):
    tweede = lab.acties.run("create_walk_forward", _wf_params(lab.ds, name="uitdager"))["object_id"]
    lab.acties.run("register", {"experiment_id": tweede})
    lab.acties.run("start", {"experiment_id": tweede})
    lab.acties._runner.active.wait(600)
    lab.acties.run("assess", {"experiment_id": lab.eid})
    lab.acties.run("assess", {"experiment_id": tweede})
    db = _db(lab)
    voor = db.conn.execute("SELECT COUNT(*) FROM wf_test_access_log").fetchone()[0]
    db.close()
    c = lab.acties.run("compare", {"reference_experiment_id": lab.eid,
                                   "challenger_experiment_id": tweede})
    assert c["ok"] and c["data"]["mode"] == "ASSESSMENT_COMPARISON"
    assert c["data"]["metric_comparison_available"] is False
    assert "Geen winnaar" in c["message"]
    db = _db(lab)
    try:
        assert db.conn.execute("SELECT COUNT(*) FROM wf_test_access_log").fetchone()[0] == voor
        detail = R.comparison_detail(db, c["object_id"])
        assert db.conn.execute("SELECT COUNT(*) FROM wf_test_access_log").fetchone()[0] == voor
    finally:
        db.close()
    assert detail["metric_comparison_available"] is False and detail["metric_deltas"] == []
    lab.tweede = tweede


def test_deep_comparison_only_when_explicitly_confirmed(lab):
    zonder = lab.acties.run("compare", {"reference_experiment_id": lab.eid,
                                        "challenger_experiment_id": lab.tweede,
                                        "mode": "DEEP_RESULT_COMPARISON"})
    assert zonder["error"]["code"] == "confirmation_required"
    assert "DATA_REUSED" in zonder["error"]["message"]
    db = _db(lab)
    voor = db.conn.execute("SELECT COUNT(*) FROM wf_test_access_log WHERE purpose='COMPARISON'").fetchone()[0]
    db.close()
    met = lab.acties.run("compare", {"reference_experiment_id": lab.eid,
                                     "challenger_experiment_id": lab.tweede,
                                     "mode": "DEEP_RESULT_COMPARISON", "confirm_test_reuse": True})
    assert met["ok"] and met["data"]["mode"] == "DEEP_RESULT_COMPARISON"
    db = _db(lab)
    try:
        na = db.conn.execute("SELECT COUNT(*) FROM wf_test_access_log WHERE purpose='COMPARISON'").fetchone()[0]
    finally:
        db.close()
    assert na > voor


def test_every_response_has_the_same_shape(lab):
    for actie, params in (("register", {"experiment_id": 999999}),
                          ("snapshot", {"symbol": "GOLD", "timeframe": "15m"}),
                          ("cancel", {"experiment_id": lab.eid})):
        r = lab.acties.run(actie, params)
        assert {"ok", "action", "object_id", "replayed", "message"} <= set(r)
        assert isinstance(r["message"], str) and r["message"]
        assert ("data" in r) == r["ok"] and ("error" in r) != r["ok"]
        tekst = json.dumps(r)
        assert str(lab.map) not in tekst and "Traceback" not in tekst


# ---------------------------------------------------------- idempotentie --

def test_same_request_id_returns_the_same_object(lab):
    p = _wf_params(lab.ds, name="idempotent", request_id="wf-idem-0001")
    a = lab.acties.run("create_walk_forward", p)
    b = lab.acties.run("create_walk_forward", p)
    assert a["object_id"] == b["object_id"] and b["replayed"] is True
    db = _db(lab)
    try:
        assert db.conn.execute("SELECT COUNT(*) FROM experiments WHERE name='idempotent'").fetchone()[0] == 1
    finally:
        db.close()


def test_request_id_with_other_payload_or_action_is_refused(lab):
    lab.acties.run("snapshot", {"symbol": "GOLD", "timeframe": "15m", "request_id": "snap-idem-01"})
    anders = lab.acties.run("snapshot", {"symbol": "GOLD", "timeframe": "5m", "request_id": "snap-idem-01"})
    assert anders["error"]["code"] == "request_id_conflict"
    actie = lab.acties.run("register", {"experiment_id": lab.eid, "request_id": "snap-idem-01"})
    assert actie["error"]["code"] == "request_id_conflict"


def test_idempotency_storage_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LAB_REQUEST_MAX", 3)
    db = LabDatabase(tmp_path / "l.db").open()
    try:
        for i in range(6):
            db.request_store(f"verzoek-{i:04d}", "snapshot", "h", None, "{}")
        assert db.conn.execute("SELECT COUNT(*) FROM lab_requests").fetchone()[0] <= 3
    finally:
        db.close()


# -------------------------------------------------------------- invoer --

def test_paths_and_unknown_parameters_are_refused(lab):
    assert lab.acties.run("snapshot", {"symbol": "GOLD", "timeframe": "15m",
                                       "start": "/config/x"})["error"]["code"] == "path_not_allowed"
    assert lab.acties.run("snapshot", {"symbol": "GOLD", "timeframe": "15m",
                                       "path": "x"})["error"]["code"] == "unknown_parameter"


def test_unknown_config_keys_are_refused(lab):
    slecht = _wf_params(lab.ds, name="slecht",
                        candidates=[{"label": "x", "config": {"strategy": {"bogus": 1}}}])
    assert lab.acties.run("create_walk_forward", slecht)["error"]["code"] == "invalid_config"


def test_service_schemas_use_the_same_fields():
    bron = (PKG / "__init__.py").read_text(encoding="utf-8")
    assert "ACTION_FIELDS[actie]" in bron and "extra=vol.PREVENT_EXTRA" in bron
    assert set(ACTION_FIELDS) == {"snapshot", "create_walk_forward", "register", "start",
                                  "cancel", "assess", "compare"}


# ---------------------------------------------------------- autorisatie --

class _Auth:
    def __init__(self, admin):
        self.admin = admin

    async def async_get_user(self, uid):
        return SimpleNamespace(is_admin=self.admin)


def test_mutations_require_an_admin(lab):
    hass = SimpleNamespace(auth=_Auth(False), data={}, bus=None)
    r = asyncio.run(lp.async_handle_action(hass, "start", {"experiment_id": lab.eid}, "u1"))
    assert r["error"]["code"] == "forbidden"
    r = asyncio.run(lp.async_handle_action(hass, "start", {"experiment_id": lab.eid}, None))
    assert r["error"]["code"] == "forbidden"


def test_read_models_require_authentication():
    assert lp.LabModelView.requires_auth is True
    view = lp.LabModelView(SimpleNamespace(data={}))
    for gebruiker, status in ((None, 401), (SimpleNamespace(is_admin=False), 403)):
        verzoek = SimpleNamespace(get=lambda k, g=gebruiker: g, query={})
        assert asyncio.run(view.get(verzoek, "overview")).status == status


# ------------------------------------------------------------ lifecycle --

def test_unload_interrupts_the_worker_and_leaves_no_process(lab):
    eid = lab.acties.run("create_walk_forward", _wf_params(lab.ds, name="unload"))["object_id"]
    lab.acties.run("register", {"experiment_id": eid})
    lab.acties.run("start", {"experiment_id": eid})
    gestopt = lp.stop_worker(lab.acties._runner, lab.pad)
    assert gestopt == eid
    db = _db(lab)
    try:
        exp = db.get(eid)
    finally:
        db.close()
    assert exp.status in ("interrupted", "completed")
    if exp.status == "interrupted":
        assert "afgemeld" in (exp.error or "")
    assert lab.acties._runner.active is None
    lopend = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    assert "worker_entry" not in lopend


def test_no_new_start_while_unloading(lab):
    acties = LabActions(lab.pad, None, WalkForwardRunner(lab.pad))
    acties.stop_accepting_starts()
    assert acties.run("start", {"experiment_id": lab.eid})["error"]["code"] == "lab_unloading"


def test_queued_and_interrupted_do_not_restart_after_reload(tmp_path, monkeypatch):
    from test_lab_panel import FakeHass, Panelen, _experiment

    import homeassistant.components as hc
    from types import ModuleType

    p = Panelen()
    pc, fe = ModuleType("pc"), ModuleType("fe")
    pc.async_register_panel, fe.async_remove_panel = p.async_register_panel, p.async_remove_panel
    monkeypatch.setattr(hc, "panel_custom", pc, raising=False)
    monkeypatch.setattr(hc, "frontend", fe, raising=False)
    monkeypatch.setattr(lp, "StaticPathConfig", lambda *a: SimpleNamespace())
    hass = FakeHass(tmp_path)
    db = LabDatabase(hass.config.path("gold_scalper_lab.db")).open()
    wacht = db.create(_experiment())
    for s in ("registered", "queued"):
        db.transition(wacht, s)
    onderbroken = db.create(_experiment())
    for s in ("registered", "queued", "running"):
        db.transition(onderbroken, s)
    db.close()
    for _ in range(2):
        asyncio.run(lp.async_setup_lab(hass))
        asyncio.run(lp.async_unload_lab(hass))
    db = LabDatabase(hass.config.path("gold_scalper_lab.db")).open()
    try:
        assert db.get(wacht).status == "queued"
        assert db.get(onderbroken).status == "interrupted"
    finally:
        db.close()


# ------------------------------------------------------------- events --

def test_progress_events_are_damped_and_allowlisted():
    a = {"status": "running", "progress_pct": 10.0, "current_window": 1, "current_candidate": "x",
         "current_segment": "TRAIN", "windows_completed": 0, "bars_total": 9, "bars_processed": 1}
    assert lp.progress_changed(None, a)
    assert not lp.progress_changed(a, {**a, "progress_pct": 10.5, "bars_processed": 2})
    assert lp.progress_changed(a, {**a, "progress_pct": 11.0})
    assert lp.progress_changed(a, {**a, "current_window": 2})
    ev = lp.progress_event({**a, "experiment_id": 1, "trades": [1], "path": "/config"})
    assert set(ev) == set(lp.PROGRESS_EVENT_KEYS)
    assert "trades" not in ev and "path" not in ev
    assert lp.PROGRESS_MIN_INTERVAL_SECONDS >= lp.PROGRESS_POLL_SECONDS


# ---------------------------------------------------------- leesmodellen --

def test_every_read_model_matches_its_allowlist(lab):
    db = _db(lab)
    try:
        a = db.conn.execute("SELECT MAX(id) FROM assessments").fetchone()[0]
        c = db.conn.execute("SELECT MAX(id) FROM comparisons").fetchone()[0]
        modellen = {
            "LabOverview": [R.lab_overview(db)],
            "ExperimentListItem": R.experiment_list(db),
            "ExperimentDetail": [R.experiment_detail(db, lab.eid)],
            "ExperimentProgress": [R.experiment_progress(db, lab.eid)],
            "DatasetListItem": R.dataset_list(db),
            "DatasetDetail": [R.dataset_detail(db, lab.ds)],
            "AssessmentListItem": R.assessment_list(db),
            "AssessmentDetail": [R.assessment_detail(db, a)],
            "ComparisonListItem": R.comparison_list(db),
            "ComparisonDetail": [R.comparison_detail(db, c)],
            "TestStatus": [R.test_status(db, lab.eid)],
            "FamilySummary": [R.family_summary(db, "bruto-oos")],
        }
    finally:
        db.close()
    for naam, lijst in modellen.items():
        assert lijst, naam
        for m in lijst:
            assert set(m) == R.MODEL_KEYS[naam], naam
            tekst = json.dumps(m, default=str)
            assert str(lab.map) not in tekst and ".db" not in tekst, naam


def test_overview_experiment_detail_and_test_status_carry_no_test_metrics(lab):
    db = _db(lab)
    try:
        for model in (R.lab_overview(db), R.experiment_detail(db, lab.eid),
                      R.test_status(db, lab.eid)):
            assert not (set(_sleutels(model)) & TEST_METRIEKEN)
    finally:
        db.close()


def test_read_models_never_open_test():
    boom = ast.parse((PKG / "lab_read_models.py").read_text(encoding="utf-8"))
    namen = {n.func.attr for n in ast.walk(boom)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not {n for n in namen if n.startswith(("open_", "create_", "store_", "transition",
                                                   "end_run", "begin_run"))}


def test_dataset_detail_keeps_quality_as_stored(lab):
    db = _db(lab)
    try:
        opgeslagen = db.dataset(lab.ds)["quality"]
        detail = R.dataset_detail(db, lab.ds)
    finally:
        db.close()
    assert [f["code"] for f in detail["findings"]] == [f["code"] for f in opgeslagen]
    assert [f["count"] for f in detail["findings"]] == [f["count"] for f in opgeslagen]
    for f in detail["findings"]:
        assert f["label"] == R.QUALITY_LABELS.get(f["code"], f["code"])


def test_assessment_detail_has_the_disclaimer_and_fourteen_components(lab):
    db = _db(lab)
    try:
        a = R.assessment_detail(db, db.conn.execute("SELECT MIN(id) FROM assessments").fetchone()[0])
    finally:
        db.close()
    assert a["disclaimer"] == R.DISCLAIMER
    assert len(a["components"]) == 14


def test_family_summary_matches_storage(lab):
    db = _db(lab)
    try:
        f = R.family_summary(db, "bruto-oos")
        bron = db.family_summary("bruto-oos")
    finally:
        db.close()
    assert f["test_accesses"] == bron["test_accesses"]
    assert f["registered_experiments"] == bron["registered_experiments"]
    assert f["data_reused_count"] == bron["reused_test_accesses"]


# ------------------------------------------------------------ doelen ----

def test_access_purposes_are_a_reference_table(tmp_path):
    db = LabDatabase(tmp_path / "l.db").open()
    try:
        codes = {p["code"] for p in db.access_purposes()}
        assert codes == {c for c, _, _ in S.ACCESS_PURPOSES}
        assert "OOS_AGGREGATE_READ" not in codes          # een access_type, geen doel
        with pytest.raises(sqlite3.DatabaseError):
            db.conn.execute("DELETE FROM access_purposes")
        with pytest.raises(sqlite3.DatabaseError):
            db.conn.execute("UPDATE access_purposes SET segment_log=0")
        # Een toekomstig doel: één INSERT, geen herbouw.
        db.conn.execute("INSERT INTO access_purposes VALUES ('FUTURE_REVIEW', 0, 1, 10)")
        assert "FUTURE_REVIEW" in {p["code"] for p in db.access_purposes()}
        fk = db.conn.execute("PRAGMA foreign_key_list(wf_test_access_log)").fetchall()
        assert any(r["table"] == "access_purposes" for r in fk)
    finally:
        db.close()


def test_no_user_path_creates_a_purpose():
    for bestand in ("lab_actions.py", "lab_panel.py", "lab_read_models.py", "__init__.py"):
        assert "access_purposes" not in (PKG / bestand).read_text(encoding="utf-8").replace(
            "db.access_purposes()", "")


def test_access_logs_stay_immutable(lab):
    db = _db(lab)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            db.conn.execute("UPDATE wf_test_access_log SET purpose='AUDIT'")
        with pytest.raises(sqlite3.DatabaseError):
            db.conn.execute("DELETE FROM wf_test_access_log")
    finally:
        db.close()


def test_migration_from_8_keeps_every_log(tmp_path, monkeypatch):
    """Echte gegevens op schema 8, dan migreren: elke logregel blijft gelijk."""
    import test_lab_walk_forward as T

    negen = S.MIGRATIONS.pop(9)
    try:
        pad = tmp_path / "gold_scalper_lab.db"
        c = vaste_bars(STRATEGY_WINDOW_BARS + 5 * 96)
        db = LabDatabase(pad).open()
        assert db.schema_version() == 8
        eid = T._wf(db, T._snapshot(db, c), c, kandidaten=[T.KANDIDATEN[1]],
                    modus=T.W.SEQUENTIAL_OOS)
        db.close()
        h = WalkForwardRunner(pad).submit_walk_forward(eid)
        assert h.wait(600) and h.final_status == "completed", h.error
        db = LabDatabase(pad).open()
        db.create_assessment(eid, "migratietest")
        db.open_wf_test_result(eid, 0, "AUDIT", "migratietest")
        voor = [tuple(r) for r in db.conn.execute("SELECT * FROM wf_test_access_log ORDER BY id")]
        db.close()
    finally:
        S.MIGRATIONS[9] = negen
    db = LabDatabase(pad).open()
    try:
        assert db.schema_version() == 9
        na = [tuple(r) for r in db.conn.execute("SELECT * FROM wf_test_access_log ORDER BY id")]
        assert na == voor and len(na) >= 2
        assert db.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


# ------------------------------------------------- handel blijft onaangeroerd --

@pytest.mark.parametrize("bestand", ["lab_actions.py", "lab_read_models.py", "lab_panel.py"])
def test_lab_modules_cannot_touch_trading(bestand):
    code = (PKG / bestand).read_text(encoding="utf-8")
    boom = ast.parse(code)
    namen = {n.attr for n in ast.walk(boom) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(boom) if isinstance(n, ast.Name)}
    for verboden in ("async_update_entry", "config_entry", "coordinator", "venue",
                     "place_order", "close_position", "set_mode", "live_gate", "options"):
        assert verboden not in namen, (bestand, verboden)
    for imp in [n for n in ast.walk(boom) if isinstance(n, ast.ImportFrom)]:
        assert not (imp.module or "").startswith(("broker", "coordinator", "storage.database",
                                                  "config_flow")), (bestand, imp.module)


# ------------------------------------------------------- administratie --

NU = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _trade(close_price):
    from gold_scalper.storage.database import Trade

    return Trade(id=1, run_id=98, mode="demo", symbol="GOLD", side="buy", volume=0.0196,
                 open_time="2026-10-01T09:00:00+00:00", open_price=4183.78, open_mid=4183.78,
                 open_spread=0.6, close_time="2026-10-01T11:00:00+00:00",
                 close_price=close_price, net_pnl=-11.2504, total_cost=1.37,
                 net_pnl_account=-10.00, fx_rate=0.888974856, fx_source="broker_settlement",
                 close_reason="stop_loss", broker_ticket="DIAAA")


def _tx(close_level):
    return {"openLevel": "4183.78", "closeLevel": str(close_level), "profitAndLoss": "E-10.00",
            "size": "+1.96", "instrumentName": "Spot Gold ($1) converted at 0.888974856",
            "dateUtc": "2026-10-01T11:00:00+00:00"}


def test_exit_within_a_cent_is_adopted_with_provenance():
    from gold_scalper.learning.afstemming import stem_af

    uitslag = stem_af([_trade(4178.03)], [_tx(4178.04)], 0.882, NU)
    (o,) = uitslag.overnames
    assert o["velden"]["close_price"] == 4178.04
    herkomst = json.loads(o["velden"]["exit_price_provenance"])
    assert herkomst["original_local"] == 4178.03 and herkomst["broker"] == 4178.04
    assert herkomst["difference"] == pytest.approx(0.01)
    assert herkomst["status"] == "ADOPTED_BROKER_SETTLEMENT" and herkomst["at"]
    assert uitslag.kloppend == 1


def test_a_larger_exit_difference_is_not_silently_adopted():
    from gold_scalper.learning.afstemming import stem_af

    uitslag = stem_af([_trade(4178.00)], [_tx(4178.04)], 0.882, NU)
    assert uitslag.overnames == [] and uitslag.afwijkingen


def test_the_report_shows_ounces_from_stored_lots():
    from gold_scalper.const import CONTRACT_SIZE
    from gold_scalper.dashboard.report import _ounces

    assert _ounces(0.0196) == f"{0.0196 * CONTRACT_SIZE:.2f}" == "1.96"
    bron = (PKG / "dashboard" / "report.py").read_text(encoding="utf-8")
    assert '<th class="num">Ounces</th>' in bron and '<th class="num">Lots</th>' not in bron


# ------------------------------------------------------- onderzoeksopzet --

def test_research_design_orders_gross_before_net_and_labels_the_inverse():
    from gold_scalper.experiment_lab import research_design as RD

    assert [h.code for h in RD.DESIGN][:2] == ["H_GROSS_OOS_PER_TRADE", "H_NET_OOS_PER_TRADE"]
    assert RD.GROSS.order < RD.NET.order and RD.NET.costs == "all_registered_costs"
    assert RD.INVERSE_SANITY_CHECK.role == "SANITY_CHECK"
    assert RD.INVERSE_SANITY_CHECK.independent_evidence is False
    assert RD.as_dict()["changes_assessment_rules"] is False


# ------------------------------------------------------------ IG-quotum --

def test_ig_request_counts_never_invent_an_allowance():
    from gold_scalper.broker.ig_capital import IgVenue

    v = IgVenue.__new__(IgVenue)
    assert v.request_stats()["historical_allowance"] is None
    v._tel_verzoek("/markets/X", {})
    v._tel_verzoek("/prices/X", {"prices": []})
    s = v.request_stats()
    assert s["live_quotes"] == 1 and s["historical_prices"] == 1
    assert s["historical_allowance"] is None
    v._tel_verzoek("/prices/X", {"metadata": {"allowance": {"remainingAllowance": 9000,
                                                            "totalAllowance": 10000}}})
    assert v.request_stats()["historical_allowance"] == {"remainingAllowance": 9000,
                                                         "totalAllowance": 10000}


def test_pyramiding_warning_is_documented_and_setting_untouched():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "Piramide staat aan, maar bijkopen wordt nog niet vastgelegd" in bron
    assert "CONF_PYRAMID_ENABLED, False" in bron.replace("options.get(", "")
