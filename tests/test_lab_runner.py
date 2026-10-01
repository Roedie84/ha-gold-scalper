"""Experiment Lab, fase 3: de runner.

Eén experiment tegelijk, in een apart werkproces dat de Lab-modules laadt
zonder het pakket (en dus zonder coordinator of Home Assistant). De controller
is de enige schrijver; het werkproces leest de dataset alleen-lezend.
"""
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.simulator import SimulatorVenue
from gold_scalper.experiment_lab import datasets as D
from gold_scalper.experiment_lab.models import Experiment, config_hash
from gold_scalper.experiment_lab.runner import (
    ExperimentRunner, RunRefused, RunnerBusy,
)
from gold_scalper.experiment_lab.storage import LabDatabase
from gold_scalper.experiment_lab.worker import RunRequest, execute

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
CFG = {"strategy": {"entry_threshold": 0.45, "take_profit_atr": 1.5, "stop_loss_atr": 1.0,
                    "volume": 0.02, "max_spread_atr_ratio": 0.75},
       "exits": {}, "execution": {"spread": 0.7, "slippage": 0.02, "units": 2.0,
                                  "instrument_currency": "USD"}}

VERBODEN_GELADEN = {
    "gold_scalper.coordinator", "gold_scalper.modes", "gold_scalper.lifecycle",
    "gold_scalper.broker.ig_capital", "gold_scalper.broker.adapter",
    "gold_scalper.broker.paper", "gold_scalper.broker.risk",
    "gold_scalper.broker.execution_safety", "gold_scalper.storage.database",
    "gold_scalper.storage.state", "gold_scalper.storage.bar_archive",
    "gold_scalper.switch", "gold_scalper.button", "gold_scalper.lab_bridge",
}


def _bars(n, **extra):
    c = asyncio.run(SimulatorVenue(seed=11).candles("XAU_USD", "15m", n))
    return [D.BarInput(t, round(o, 2), round(h, 2), round(l, 2), round(cl, 2), v,
                       extra.get("source", "quotes"), "closed")
            for t, o, h, l, cl, v in zip(c.timestamp, c.open, c.high, c.low, c.close, c.volume)]


def _dataset(lab, n=420, bars=None):
    bars = bars or _bars(n)
    spec = D.DatasetSpec("GOLD", "15m", 2, "instrument_metadata", "test")
    ds, _ = lab.create_snapshot(D.prepare(spec, bars, None, bars[-1].ts + 10**7), "test")
    return ds


def _experiment(lab, ds, cfg=CFG, registreren=True):
    eid = lab.create(Experiment(
        name="baseline", type="baseline", hypothesis="h", expected_effect="e",
        primary_metric="net_pnl", evaluation_method="technisch",
        hypothesis_family_id="fase3", software_version="5.5.0",
        strategy_version="scalp-0.2.0", execution_semantics_version=3,
        config_hash=config_hash(cfg), dataset_id=ds,
    ))
    lab.add_parameters(eid, "baseline", cfg)
    if registreren:
        lab.transition(eid, "registered")
    return eid


@pytest.fixture
def omgeving(tmp_path):
    pad = tmp_path / "gold_scalper_lab.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab)
    eid = _experiment(lab, ds)
    lab.close()
    return pad, ds, eid


def _lees(pad, eid):
    db = LabDatabase(pad).open()
    try:
        return db.get(eid), db.run_state(eid), db.result(eid)
    finally:
        db.close()


# ---------------- de gewone cyclus ----------------

def test_registered_queued_running_completed(omgeving):
    pad, ds, eid = omgeving
    h = ExperimentRunner(pad, progress_write_seconds=0).submit(eid, ds, CFG)
    assert h.wait(120) and h.final_status == "completed", h.error
    exp, run, res = _lees(pad, eid)
    assert exp.status == "completed" and exp.started_at and exp.finished_at
    assert run["progress_pct"] == 100 and run["executor"] == "process"
    assert res["summary"]["trades"] == len(res["trades"])


def test_fidelity_and_provenance_are_kept(omgeving):
    pad, ds, eid = omgeving
    ExperimentRunner(pad).submit(eid, ds, CFG).wait(120)
    _, _, res = _lees(pad, eid)
    f = res["summary"]["fidelity"]
    assert f["simulation_model"] == "BAR_ONLY" and f["known_limitations"]
    assert "ambiguous_exits" in f and f["intrabar_assumption"] == "stop eerst"
    assert res["summary"]["provenance"]["strategy_window_bars"] == 800
    assert res["provenance"]["dataset_quality_status"] in ("OK", "WARNING")


# ---------------- startcontroles ----------------

def test_a_blocked_dataset_does_not_start(tmp_path):
    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    bars = _bars(420)
    bars.append(D.BarInput(bars[10].ts, 1.0, 2.0, 0.5, 1.5, 1.0, "quotes", "closed"))
    ds = _dataset(lab, bars=bars)
    assert lab.dataset(ds)["quality_status"] == "BLOCKED"
    eid = _experiment(lab, ds)
    lab.close()
    with pytest.raises(RunRefused):
        ExperimentRunner(pad).submit(eid, ds, CFG)
    assert _lees(pad, eid)[0].status == "registered"


def test_a_warning_dataset_starts_and_keeps_its_warnings(tmp_path):
    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    bars = _bars(420)
    bars[5] = D.BarInput(bars[5].ts, bars[5].open, bars[5].high, bars[5].low,
                         bars[5].close, bars[5].volume, "broker", "closed")
    ds = _dataset(lab, bars=bars)
    assert lab.dataset(ds)["quality_status"] == "WARNING"
    eid = _experiment(lab, ds)
    lab.close()
    h = ExperimentRunner(pad).submit(eid, ds, CFG)
    assert h.wait(120) and h.final_status == "completed"
    herkomst = _lees(pad, eid)[2]["provenance"]
    assert herkomst["dataset_quality_status"] == "WARNING"
    assert "mixed_source" in herkomst["dataset_quality"]


def test_a_wrong_dataset_is_refused(tmp_path):
    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab)
    ander = _dataset(lab, n=430)
    eid = _experiment(lab, ds)
    lab.close()
    with pytest.raises(RunRefused):
        ExperimentRunner(pad).submit(eid, ander, CFG)


def test_a_wrong_config_is_refused(omgeving):
    pad, ds, eid = omgeving
    anders = json.loads(json.dumps(CFG))
    anders["strategy"]["entry_threshold"] = 0.5
    with pytest.raises(RunRefused):
        ExperimentRunner(pad).submit(eid, ds, anders)


def test_an_unregistered_experiment_does_not_start(tmp_path):
    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab)
    eid = _experiment(lab, ds, registreren=False)
    lab.close()
    with pytest.raises(RunRefused):
        ExperimentRunner(pad).submit(eid, ds, CFG)


def test_a_tampered_dataset_is_refused(omgeving):
    """Buiten de triggers om geknoeid: de hashcontrole vóór de start vangt het."""
    pad, ds, eid = omgeving
    conn = sqlite3.connect(pad)
    conn.execute("DROP TRIGGER bars_no_update")
    conn.execute("UPDATE dataset_bars SET close = close + 1 WHERE dataset_id=? AND ts = "
                 "(SELECT MIN(ts) FROM dataset_bars WHERE dataset_id=?)", (ds, ds))
    conn.commit()
    conn.close()
    with pytest.raises(RunRefused):
        ExperimentRunner(pad).submit(eid, ds, CFG)


def test_the_worker_checks_the_dataset_again():
    """Ook de kern zelf controleert: een verkeerde hash in de aanvraag stopt alles."""
    from gold_scalper.experiment_lab.worker import RunError, read_sealed_dataset
    with pytest.raises(Exception):
        read_sealed_dataset("/bestaat/niet.db", 1, "x")
    assert issubclass(RunError, ValueError)


# ---------------- één tegelijk ----------------

def test_one_experiment_at_a_time(tmp_path):
    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab, n=900)
    a, b = _experiment(lab, ds), _experiment(lab, ds)
    lab.close()
    runner = ExperimentRunner(pad)
    h = runner.submit(a, ds, CFG)
    with pytest.raises(RunnerBusy):
        runner.submit(b, ds, CFG)
    with pytest.raises(RunnerBusy):                       # ook een tweede runner niet
        ExperimentRunner(pad).submit(b, ds, CFG)
    h.cancel()
    h.wait(60)
    assert _lees(pad, b)[0].status == "registered"


# ---------------- annuleren, falen, onderbreken ----------------

def test_cancellation_never_completes(tmp_path):
    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab, n=1500)
    eid = _experiment(lab, ds)
    lab.close()
    h = ExperimentRunner(pad, progress_write_seconds=0).submit(eid, ds, CFG)
    time.sleep(1.5)
    h.cancel()
    assert h.wait(60)
    exp, run, res = _lees(pad, eid)
    assert exp.status == "cancelled" and res is None
    assert run["progress_pct"] < 100 and run["finished_at"]
    assert h.stopped_at - h.cancel_requested_at < 5, "annuleren duurde te lang"


def test_cancel_before_running(omgeving):
    pad, ds, eid = omgeving
    ExperimentRunner(pad).cancel_pending(eid)
    assert _lees(pad, eid)[0].status == "cancelled"


def test_a_worker_error_fails(omgeving):
    pad, ds, eid = omgeving
    kapot = [sys.executable, "-I", "-c",
             "import json,sys; sys.stdin.readline(); "
             "print(json.dumps({'type':'error','message':'kapot'}), flush=True)"]
    h = ExperimentRunner(pad, worker_command=kapot).submit(eid, ds, CFG)
    assert h.wait(30) and h.final_status == "failed"
    exp, _, res = _lees(pad, eid)
    assert exp.status == "failed" and "kapot" in exp.error and res is None


def test_a_storage_failure_fails(omgeving, monkeypatch):
    pad, ds, eid = omgeving

    def mislukt(self, *_):
        raise sqlite3.OperationalError("schijf vol")

    monkeypatch.setattr(LabDatabase, "complete_with_result", mislukt)
    h = ExperimentRunner(pad).submit(eid, ds, CFG)
    assert h.wait(120) and h.final_status == "failed"
    exp, _, res = _lees(pad, eid)
    assert exp.status == "failed" and "niet opgeslagen" in exp.error and res is None


def test_a_vanishing_worker_is_interrupted(omgeving):
    pad, ds, eid = omgeving
    verdwijnt = [sys.executable, "-I", "-c", "import sys; sys.stdin.readline()"]
    h = ExperimentRunner(pad, worker_command=verdwijnt).submit(eid, ds, CFG)
    assert h.wait(30) and h.final_status == "interrupted"
    assert _lees(pad, eid)[0].status == "interrupted"


def test_a_stalled_worker_is_stopped_and_fails(omgeving):
    pad, ds, eid = omgeving
    hangt = [sys.executable, "-I", "-c", "import sys,time; sys.stdin.readline(); time.sleep(60)"]
    h = ExperimentRunner(pad, worker_command=hangt, stall_timeout=1.0).submit(eid, ds, CFG)
    assert h.wait(30) and h.final_status == "failed"
    assert "geen teken van leven" in _lees(pad, eid)[0].error


def test_a_worker_that_ignores_cancel_is_ended(omgeving):
    pad, ds, eid = omgeving
    doof = [sys.executable, "-I", "-c",
            "import json,sys,time; sys.stdin.readline()\n"
            "while True:\n print(json.dumps({'type':'progress','done':1,'total':9}),flush=True); time.sleep(0.2)"]
    h = ExperimentRunner(pad, worker_command=doof, cancel_grace=1.0).submit(eid, ds, CFG)
    time.sleep(0.5)
    h.cancel()
    assert h.wait(30) and h.final_status == "cancelled"


def test_a_forged_result_is_not_stored(omgeving):
    """Een resultaat dat niet klopt met zijn eigen hash wordt geweigerd."""
    pad, ds, eid = omgeving
    vals = [sys.executable, "-I", "-c",
            "import json,sys; sys.stdin.readline(); print(json.dumps({'type':'result','result':"
            "{'summary':{'fidelity':{},'provenance':{}},'trades':[],'result_hash':'x','provenance':{}}}),flush=True)"]
    h = ExperimentRunner(pad, worker_command=vals).submit(eid, ds, CFG)
    assert h.wait(30) and h.final_status == "failed"
    assert _lees(pad, eid)[2] is None


# ---------------- herstel ----------------

def test_restart_marks_running_as_interrupted(omgeving):
    pad, ds, eid = omgeving
    db = LabDatabase(pad).open()
    db.transition(eid, "queued")
    db.begin_run(eid, "process")
    db.update_progress(eid, 50, 100)
    db.conn.close()                                 # HA-herstart
    db = LabDatabase(pad).open(recover=True)
    exp, run = db.get(eid), db.run_state(eid)
    db.close()
    assert exp.status == "interrupted" and run["progress_pct"] == 50 and run["finished_at"]


def test_queued_is_not_started_after_restart(omgeving):
    pad, ds, eid = omgeving
    db = LabDatabase(pad).open()
    db.transition(eid, "queued")
    db.close()
    ExperimentRunner(pad)                           # een nieuwe runner na herstart
    time.sleep(1)
    assert _lees(pad, eid)[0].status == "queued"


# ---------------- voortgang ----------------

def test_progress_is_monotone_and_capped(tmp_path):
    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab, n=1000)
    eid = _experiment(lab, ds)
    lab.close()
    h = ExperimentRunner(pad, progress_write_seconds=0).submit(eid, ds, CFG)
    assert h.wait(120)
    assert h.progress_log == sorted(h.progress_log) and len(h.progress_log) >= 2
    assert max(h.progress_log) < 100
    assert _lees(pad, eid)[1]["progress_pct"] == 100


def test_progress_cannot_go_back_or_exceed_100(omgeving):
    pad, ds, eid = omgeving
    db = LabDatabase(pad).open()
    db.transition(eid, "queued")
    db.begin_run(eid, "process")
    db.update_progress(eid, 60, 100)
    db.update_progress(eid, 30, 100)
    assert db.run_state(eid)["progress_pct"] == 60
    with pytest.raises(sqlite3.DatabaseError):
        db.conn.execute("UPDATE experiment_runs SET progress_pct = 20 WHERE experiment_id=?", (eid,))
    with pytest.raises(sqlite3.DatabaseError):
        db.conn.execute("UPDATE experiment_runs SET progress_pct = 101 WHERE experiment_id=?", (eid,))
    db.close()


# ---------------- de database dwingt af ----------------

def test_completed_is_impossible_without_a_result(omgeving):
    pad, ds, eid = omgeving
    db = LabDatabase(pad).open()
    db.transition(eid, "queued")
    db.begin_run(eid, "process")
    with pytest.raises(sqlite3.DatabaseError):
        db.transition(eid, "completed")
    db.close()


def test_a_result_is_immutable(omgeving):
    pad, ds, eid = omgeving
    ExperimentRunner(pad).submit(eid, ds, CFG).wait(120)
    conn = sqlite3.connect(pad)
    for sql in ("UPDATE experiment_results SET result_hash='x'",
                "DELETE FROM experiment_results"):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)
    conn.close()


# ---------------- determinisme ----------------

def test_identical_input_identical_outcome(tmp_path):
    """Drie keer: twee keer via het werkproces, één keer in-process."""
    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab, n=600)
    a, b = _experiment(lab, ds), _experiment(lab, ds)
    ds_hash = lab.dataset(ds)["hash"]
    lab.close()
    runner = ExperimentRunner(pad)
    runner.submit(a, ds, CFG).wait(120)
    runner.submit(b, ds, CFG).wait(120)
    ra, rb = _lees(pad, a)[2], _lees(pad, b)[2]
    direct = execute(RunRequest(a, ds, ds_hash, str(pad), CFG, config_hash(CFG)),
                     lambda: False, lambda *_: None)
    assert ra["result_hash"] == rb["result_hash"] == direct["result_hash"]


def test_a_reproduction_gives_the_same_outcome(omgeving):
    pad, ds, eid = omgeving
    runner = ExperimentRunner(pad)
    runner.submit(eid, ds, CFG).wait(120)
    db = LabDatabase(pad).open()
    kopie = db.reproduce(eid, {"software_version": "5.5.0", "strategy_version": "scalp-0.2.0",
                               "execution_semantics_version": 3})
    db.transition(kopie, "registered")
    db.close()
    runner.submit(kopie, ds, CFG).wait(120)
    assert _lees(pad, kopie)[2]["result_hash"] == _lees(pad, eid)[2]["result_hash"]


def test_the_progress_hook_does_not_change_the_backtest():
    from gold_scalper.analysis.backtest import run_backtest
    from gold_scalper.broker.exits import ExitConfig
    from gold_scalper.strategy.scalping import ScalpConfig

    c = asyncio.run(SimulatorVenue(seed=11).candles("XAU_USD", "15m", 500))
    s = ScalpConfig(**CFG["strategy"])
    zonder = run_backtest(c, s, ExitConfig(), spread=0.7, units=2.0).summary()
    met = run_backtest(c, s, ExitConfig(), spread=0.7, units=2.0,
                       progress=lambda *_: None).summary()
    assert zonder == met


# ---------------- grens ----------------

def test_the_worker_process_loads_no_trading_module(omgeving):
    """Het bewijs uit het werkproces zelf: wat het werkelijk laadde."""
    pad, ds, eid = omgeving
    h = ExperimentRunner(pad).submit(eid, ds, CFG)
    assert h.wait(120) and h.final_status == "completed"
    geladen = set(h.loaded_modules)
    assert geladen, "het werkproces meldde niets"
    assert not geladen & VERBODEN_GELADEN, geladen & VERBODEN_GELADEN
    assert not {m for m in geladen if m.split(".")[0] in ("homeassistant", "aiohttp", "voluptuous")}


def test_the_worker_gets_no_credentials_or_environment():
    """Geïsoleerde modus en een omgeving met alleen PATH."""
    bron = (PKG / "experiment_lab" / "runner.py").read_text(encoding="utf-8")
    assert '[sys.executable, "-I", str(WORKER_ENTRY)]' in bron
    assert 'env={"PATH": _pad()}' in bron


def test_the_request_is_plain_data():
    from dataclasses import fields
    for f in fields(RunRequest):
        assert f.name in {"experiment_id", "dataset_id", "dataset_hash",
                          "lab_db_path", "config", "config_hash", "segment_plan",
                          "single_segment"}


def test_the_worker_never_writes():
    """Alleen-lezend op databaseniveau, en geen schrijfopdracht in de code."""
    bron = (PKG / "experiment_lab" / "worker.py").read_text(encoding="utf-8")
    assert "mode=ro" in bron
    for verboden in ("INSERT", "UPDATE ", "DELETE", "commit()"):
        assert verboden not in bron


def test_the_entry_does_not_run_the_package_init():
    bron = (PKG / "experiment_lab" / "worker_entry.py").read_text(encoding="utf-8")
    assert 'types.ModuleType("gold_scalper")' in bron
    assert bron.index("_pakket_zonder_init()") < bron.index("from gold_scalper.experiment_lab.worker")


# ---------------- isolatie ----------------

def test_a_lab_failure_leaves_the_trading_files_alone(tmp_path):
    from gold_scalper.storage.database import TradeDatabase

    trade = tmp_path / "gold_scalper.db"
    tdb = TradeDatabase(trade)
    tdb.connect()
    tdb.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    tdb.close()
    voor = hashlib.sha256(trade.read_bytes()).hexdigest()

    pad = tmp_path / "gold_scalper_lab.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab)
    eid = _experiment(lab, ds)
    lab.close()
    kapot = [sys.executable, "-I", "-c", "raise SystemExit(3)"]
    ExperimentRunner(pad, worker_command=kapot).submit(eid, ds, CFG).wait(30)
    assert hashlib.sha256(trade.read_bytes()).hexdigest() == voor
    assert {p.name for p in tmp_path.iterdir()} <= {
        "gold_scalper.db", "gold_scalper_lab.db", "gold_scalper_lab.db-journal"}


def test_an_exception_in_the_controller_stays_in_the_lab(omgeving, monkeypatch):
    """Een fout in de controller maakt het experiment failed - meer niet."""
    pad, ds, eid = omgeving

    def kapot(self, *a, **k):
        raise RuntimeError("onverwacht")

    monkeypatch.setattr(ExperimentRunner, "_volg", kapot)
    h = ExperimentRunner(pad).submit(eid, ds, CFG)
    assert h.wait(30) and h.final_status == "failed"
    assert _lees(pad, eid)[0].status == "failed"


def test_cancel_after_the_final_message_is_not_a_failure(omgeving):
    """Wedloop, gevonden in de volledige suite van fase 6: het werkproces
    stuurt zijn eindbericht, de controller sluit de invoer, en een annulering
    vlak daarna probeerde nog naar die gesloten invoer te schrijven. Gevolg:
    ValueError en ``failed`` in plaats van ``cancelled``."""
    pad, ds, eid = omgeving
    traag = [sys.executable, "-I", "-c",
             "import json,sys,time; sys.stdin.readline()\n"
             "print(json.dumps({'type':'cancelled'}), flush=True)\n"
             "time.sleep(1.0)\n"
             "print(json.dumps({'type':'modules','loaded':[]}), flush=True)"]
    h = ExperimentRunner(pad, worker_command=traag).submit(eid, ds, CFG)
    time.sleep(0.5)                         # na het eindbericht, vóór 'modules'
    h.cancel()
    assert h.wait(30)
    assert h.final_status == "cancelled", h.error
    assert "I/O operation" not in (h.error or "")
