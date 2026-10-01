"""Experiment Lab, fase 5: chronologische segmenten, testbescherming en
hergebruik binnen een hypothesefamilie.

Alle marktdata hier is vast (``vaste_bars``): morgen exact dezelfde bars en
segmentgrenzen als vandaag. Geen enkele test hier gebruikt de klok.
"""
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from vaste_bars import vaste_bars  # noqa: E402

from gold_scalper.analysis.backtest import WARMUP_BARS, run_backtest  # noqa: E402
from gold_scalper.analysis.signals import Candles  # noqa: E402
from gold_scalper.broker.exits import ExitConfig  # noqa: E402
from gold_scalper.const import STRATEGY_WINDOW_BARS  # noqa: E402
from gold_scalper.experiment_lab import datasets as D  # noqa: E402
from gold_scalper.experiment_lab.metrics import REQUIRED_METRICS  # noqa: E402
from gold_scalper.experiment_lab.models import Experiment, config_hash  # noqa: E402
from gold_scalper.experiment_lab.runner import ExperimentRunner, RunRefused  # noqa: E402
from gold_scalper.experiment_lab.segments import (  # noqa: E402
    FULL, PARTIAL, SegmentPlanError, build_plan, normalize_family_id,
)
from gold_scalper.experiment_lab.storage import LabDatabase, SealedTestError  # noqa: E402
from gold_scalper.experiment_lab.worker import _plak  # noqa: E402
from gold_scalper.strategy.scalping import ScalpConfig  # noqa: E402

BAR = 900
CFG = {"strategy": {"entry_threshold": 0.45, "take_profit_atr": 1.5, "stop_loss_atr": 1.0,
                    "volume": 0.02, "max_spread_atr_ratio": 0.75},
       "exits": {"max_hold_seconds": 900},
       "execution": {"spread": 0.7, "slippage": 0.02, "units": 2.0, "instrument_currency": "USD"}}
N_OPWARM, N_SEG = STRATEGY_WINDOW_BARS, 150
N = N_OPWARM + 3 * N_SEG


def _grenzen(c):
    t = c.timestamp
    a = N_OPWARM
    return {"TRAIN": (t[a], t[a + N_SEG]),
            "VALIDATION": (t[a + N_SEG], t[a + 2 * N_SEG]),
            "TEST": (t[a + 2 * N_SEG], t[-1] + BAR)}


def _snapshot(lab, c):
    bars = [D.BarInput(t, o, h, l, cl, v, "vast", "closed")
            for t, o, h, l, cl, v in zip(c.timestamp, c.open, c.high, c.low, c.close, c.volume)]
    spec = D.DatasetSpec("GOLD", "15m", 2, "instrument_metadata", "vast")
    ds, _ = lab.create_snapshot(D.prepare(spec, bars, None, c.timestamp[-1] + 10 * BAR), "test")
    return ds


def _experiment(lab, ds, c, naam="segmenten", familie="Tijdslimiet  2 bars", cfg=CFG,
                registreren=True, plan_grenzen=None):
    eid = lab.create(Experiment(
        name=naam, type="out_of_sample", hypothesis="h", expected_effect="e",
        primary_metric="net_pnl", evaluation_method="train/validation/test",
        hypothesis_family_id=familie, software_version="5.5.0",
        strategy_version="scalp-0.2.0", execution_semantics_version=3,
        config_hash=config_hash(cfg), dataset_id=ds))
    lab.add_parameters(eid, "baseline", cfg)
    plan = build_plan(ds, lab.dataset(ds)["hash"], "15m", list(c.timestamp),
                      plan_grenzen or _grenzen(c), 900)
    lab.save_segment_plan(eid, plan)
    if registreren:
        lab.transition(eid, "registered")
    return eid


@pytest.fixture(scope="module")
def uitgevoerd(tmp_path_factory):
    """Eén volledig uitgevoerd gesegmenteerd experiment, voor de leestests."""
    pad = tmp_path_factory.mktemp("seg") / "gold_scalper_lab.db"
    c = vaste_bars(N)
    lab = LabDatabase(pad).open()
    ds = _snapshot(lab, c)
    eid = _experiment(lab, ds, c)
    lab.close()
    h = ExperimentRunner(pad, progress_write_seconds=0).submit(eid, ds, CFG)
    assert h.wait(300) and h.final_status == "completed", h.error
    return pad, ds, eid, c, h


def _open(pad):
    return LabDatabase(pad).open()


# ---------------- plan: chronologie, grenzen, opwarmen, afkap ----------------

def test_segments_are_chronological_and_do_not_overlap():
    c = vaste_bars(N)
    g = _grenzen(c)
    for kapot in (
        {**g, "VALIDATION": (g["TRAIN"][1] - BAR, g["VALIDATION"][1])},    # overlap
        {**g, "TEST": (g["TRAIN"][0], g["TRAIN"][1])},                      # TEST vóór VALIDATION
    ):
        with pytest.raises(SegmentPlanError):
            build_plan(1, "h", "15m", list(c.timestamp), kapot, 900)


def test_the_database_refuses_overlap_directly(tmp_path):
    c = vaste_bars(N)
    lab = _open(tmp_path / "l.db")
    eid = _experiment(lab, _snapshot(lab, c), c, registreren=False)
    train = lab.segment_plan(eid)["segments"][0]
    lab.conn.execute("DELETE FROM experiment_segments WHERE experiment_id=? AND kind='TEST'", (eid,))
    with pytest.raises(sqlite3.DatabaseError):
        lab.conn.execute(
            "INSERT INTO experiment_segments (experiment_id, kind, sequence_number, start_ts, "
            "end_ts, warmup_start_ts, open_cutoff_ts, warmup_bars, warmup_status, created_at) "
            "VALUES (?, 'TEST', 3, ?, ?, ?, ?, 800, 'FULL_WARMUP', 'nu')",
            (eid, train["start_ts"], train["end_ts"], train["warmup_start_ts"],
             train["open_cutoff_ts"]))
    lab.close()


def test_half_open_boundaries_are_exact():
    """Een bar op het einde van TRAIN is de eerste van VALIDATION - nooit beide."""
    c = vaste_bars(N)
    plan = build_plan(1, "h", "15m", list(c.timestamp), _grenzen(c), 900)
    train, val, test = plan.segments
    assert train.end_ts == val.start_ts and val.end_ts == test.start_ts
    tr = _plak(c, train.start_ts, train.end_ts)
    va = _plak(c, val.start_ts, val.end_ts)
    te = _plak(c, test.start_ts, test.end_ts)
    assert tr.timestamp[0] == train.start_ts and tr.timestamp[-1] == train.end_ts - BAR
    assert va.timestamp[0] == train.end_ts                      # de grensbar
    assert te.timestamp[0] == val.end_ts and te.timestamp[-1] == test.end_ts - BAR
    evaluatie = [set(p.timestamp) for p in (tr, va, te)]
    assert not (evaluatie[0] & evaluatie[1] or evaluatie[1] & evaluatie[2] or evaluatie[0] & evaluatie[2])
    assert sum(len(e) for e in evaluatie) == 3 * N_SEG


def test_warmup_is_the_live_window_and_may_overlap_earlier_segments():
    c = vaste_bars(N)
    plan = build_plan(1, "h", "15m", list(c.timestamp), _grenzen(c), 900)
    train, val, _ = plan.segments
    assert train.warmup_bars == STRATEGY_WINDOW_BARS and train.warmup_status == FULL
    assert train.warmup_start_ts == c.timestamp[0]
    # VALIDATION warmt op met bars die ook TRAIN-evaluatiebars zijn: toegestaan
    assert val.warmup_start_ts < train.end_ts


def test_partial_and_insufficient_warmup_are_explicit():
    c = vaste_bars(N)
    g = _grenzen(c)
    kort = {**g, "TRAIN": (c.timestamp[WARMUP_BARS + 10], g["TRAIN"][1])}
    assert build_plan(1, "h", "15m", list(c.timestamp), kort, 900).segments[0].warmup_status == PARTIAL
    te_kort = {**g, "TRAIN": (c.timestamp[WARMUP_BARS - 10], g["TRAIN"][1])}
    with pytest.raises(SegmentPlanError, match="opwarmdata"):
        build_plan(1, "h", "15m", list(c.timestamp), te_kort, 900)


def test_the_open_cutoff_is_fixed_in_advance():
    """end - max_hold - één bar, uit geregistreerde waarden; niet uit resultaten."""
    c = vaste_bars(N)
    for houd in (900, 3600):
        seg = build_plan(1, "h", "15m", list(c.timestamp), _grenzen(c), houd).segments[0]
        assert seg.open_cutoff_ts == seg.end_ts - houd - BAR


def test_the_family_id_is_normalized():
    assert normalize_family_id("Tijdslimiet  2 bars") == normalize_family_id("tijdslimiet-2-bars")
    assert normalize_family_id("Élan_Test") == "elan-test"
    with pytest.raises(ValueError):
        normalize_family_id("  --  ")


# ---------------- motor: opwarmen, afkap, segmenteinde ----------------

def test_warmup_opens_nothing_and_is_not_evaluated():
    c = vaste_bars(1100)
    s = ScalpConfig(**CFG["strategy"])
    begin = c.timestamp[900]
    r = run_backtest(c, s, ExitConfig(), spread=0.7, units=2.0, evaluate_from_ts=begin)
    assert r.trades and min(t.opened_at for t in r.trades) >= begin
    assert r.evaluations <= sum(1 for t in c.timestamp[:-1] if t >= begin)


def test_no_entry_at_or_after_the_cutoff():
    c = vaste_bars(1100)
    s = ScalpConfig(**CFG["strategy"])
    afkap = c.timestamp[1000]
    r = run_backtest(c, s, ExitConfig(), spread=0.7, units=2.0, no_entries_from_ts=afkap)
    assert r.trades and max(t.opened_at for t in r.trades) < afkap


def test_a_position_open_at_the_end_is_closed_on_the_last_bar():
    """Geen bar van na het segment: de positie sluit op de laatste segmentbar,
    met reden segment_end - de cross-boundary-trade blijft bij zijn opening."""
    c = vaste_bars(1100)
    s = ScalpConfig(**CFG["strategy"])
    vrij = run_backtest(c, s, ExitConfig(), spread=0.7, units=2.0)
    index = {t: i for i, t in enumerate(c.timestamp)}
    # Een trade die op bar k opent, wordt pas vanaf bar k+1 op exits getoetst.
    # Eindigt de data na bar k+1, dan staat hij aan het einde nog open.
    # De motor rekent pas vanaf 310 bars in totaal; neem een trade ruim daarna.
    lang = next(t for t in vrij.trades if index[t.opened_at] >= 400)
    einde = index[lang.opened_at] + 2
    kort = Candles(c.timestamp[:einde], c.open[:einde], c.high[:einde], c.low[:einde],
                   c.close[:einde], c.volume[:einde])
    zonder = run_backtest(kort, s, ExitConfig(), spread=0.7, units=2.0)
    met = run_backtest(kort, s, ExitConfig(), spread=0.7, units=2.0, close_open_at_end=True)
    laatste = met.trades[-1]
    assert laatste.reason == "segment_end" and laatste.opened_at == lang.opened_at
    assert laatste.closed_at == kort.timestamp[-1]
    assert len(met.trades) == len(zonder.trades) + 1       # anders zou hij weggevallen zijn
    assert abs((laatste.gross - laatste.net) - (laatste.spread_cost + laatste.slippage_cost)) < 1e-9


def test_without_segment_options_the_engine_is_unchanged():
    c = vaste_bars(1000)
    s = ScalpConfig(**CFG["strategy"])
    a = run_backtest(c, s, ExitConfig(), spread=0.7, units=2.0).summary()
    b = run_backtest(c, s, ExitConfig(), spread=0.7, units=2.0, evaluate_from_ts=None,
                     no_entries_from_ts=None, close_open_at_end=False).summary()
    assert a == b


# ---------------- uitvoering en opslag ----------------

def test_each_segment_has_its_full_result(uitgevoerd):
    pad, _, eid, c, _ = uitgevoerd
    lab = _open(pad)
    try:
        plan = lab.segment_plan(eid)
        assert lab.get(eid).status == "completed"
        for seg in plan["segments"]:
            sid = seg["id"]
            n = lab.conn.execute("SELECT COUNT(*) FROM segment_metrics WHERE segment_id=?", (sid,)).fetchone()[0]
            assert n == len(REQUIRED_METRICS)
            for tabel in ("segment_trades", "segment_breakdowns", "segment_rejections"):
                rijen = lab.conn.execute(f"SELECT segment_id FROM {tabel} WHERE experiment_id=? "
                                         "AND segment_id=?", (eid, sid)).fetchall()
                assert all(r[0] == sid for r in rijen)
            for t in lab.conn.execute("SELECT opened_ts, closed_ts, close_reason, cross_boundary "
                                      "FROM segment_trades WHERE segment_id=?", (sid,)):
                assert seg["start_ts"] <= t[0] < seg["open_cutoff_ts"]
                assert t[1] < seg["end_ts"]
                assert t[3] == int(t[2] == "segment_end")
    finally:
        lab.close()


def test_trading_day_stays_the_closing_day(uitgevoerd):
    from datetime import datetime, timezone
    from gold_scalper.timeutil import trading_day

    pad, _, eid, _, _ = uitgevoerd
    lab = _open(pad)
    rijen = lab.conn.execute("SELECT closed_ts, trading_day FROM segment_trades "
                             "WHERE experiment_id=? LIMIT 50", (eid,)).fetchall()
    lab.close()
    assert rijen
    for gesloten, dag in rijen:
        assert dag == trading_day(datetime.fromtimestamp(gesloten, timezone.utc)).isoformat()


def test_progress_is_monotone_across_segments(uitgevoerd):
    pad, _, eid, _, h = uitgevoerd
    assert h.progress_log == sorted(h.progress_log)
    lab = _open(pad)
    run = lab.run_state(eid)
    lab.close()
    assert run["progress_pct"] == 100 and run["segments_completed"] == run["segments_total"] == 3


def test_test_data_cannot_leak_into_train_or_validation(tmp_path):
    """Twee datasets die alleen in de TEST-periode verschillen: TRAIN en
    VALIDATION moeten exact dezelfde uitkomst geven. Eén gelekte TEST-bar en
    deze hashes verschillen."""
    c = vaste_bars(N)
    test_start = _grenzen(c)["TEST"][0]
    anders = Candles(c.timestamp,
                     *[[round(x + (25.0 if t >= test_start else 0.0), 2)
                        for t, x in zip(c.timestamp, reeks)]
                       for reeks in (c.open, c.high, c.low, c.close)],
                     c.volume)
    uitkomst = []
    for i, reeks in enumerate((c, anders)):
        pad = tmp_path / f"l{i}.db"
        lab = _open(pad)
        ds = _snapshot(lab, reeks)
        eid = _experiment(lab, ds, reeks)
        lab.close()
        assert ExperimentRunner(pad).submit(eid, ds, CFG).wait(300)
        lab = _open(pad)
        uitkomst.append({r["kind"]: r["result_hash"] for r in lab.conn.execute(
            "SELECT kind, result_hash FROM segment_results WHERE experiment_id=?", (eid,))})
        lab.close()
    assert uitkomst[0]["TRAIN"] == uitkomst[1]["TRAIN"]
    assert uitkomst[0]["VALIDATION"] == uitkomst[1]["VALIDATION"]
    assert uitkomst[0]["TEST"] != uitkomst[1]["TEST"]


def test_the_fixed_fixture_gives_the_same_outcome_every_time(uitgevoerd, tmp_path):
    pad, ds, eid, c, _ = uitgevoerd
    lab = _open(pad)
    eerste = {r[0]: r[1] for r in lab.conn.execute(
        "SELECT kind, result_hash FROM segment_results WHERE experiment_id=?", (eid,))}
    lab.close()
    pad2 = tmp_path / "opnieuw.db"
    lab = _open(pad2)
    ds2 = _snapshot(lab, vaste_bars(N))
    eid2 = _experiment(lab, ds2, vaste_bars(N))
    lab.close()
    assert ExperimentRunner(pad2).submit(eid2, ds2, CFG).wait(300)
    lab = _open(pad2)
    tweede = {r[0]: r[1] for r in lab.conn.execute(
        "SELECT kind, result_hash FROM segment_results WHERE experiment_id=?", (eid2,))}
    lab.close()
    assert eerste == tweede


def test_completed_is_refused_when_one_segment_is_incomplete(uitgevoerd, tmp_path):
    """Rechtstreeks in de database: zonder de metrieken van één segment geen completed."""
    import json
    pad, _, eid, _, _ = uitgevoerd
    lab = _open(pad)
    rijen = {r["kind"]: dict(r) for r in lab.conn.execute(
        "SELECT * FROM segment_results WHERE experiment_id=?", (eid,))}
    lab.close()
    c = vaste_bars(N)
    lab = _open(tmp_path / "l.db")
    ds = _snapshot(lab, c)
    nieuw = _experiment(lab, ds, c)
    lab.transition(nieuw, "queued")
    lab.begin_run(nieuw, "test")
    ids = {s["kind"]: s["id"] for s in lab.segment_plan(nieuw)["segments"]}
    for soort, rij in rijen.items():
        lab.conn.execute(
            "INSERT INTO segment_results (segment_id, experiment_id, kind, result_kind, result_hash, "
            "summary_json, cost_model_json, result_schema_version, backtest_engine_version, "
            "cost_model_version, metrics_version, segment_schema_version, trade_count, "
            "cross_boundary_count, warmup_status, created_at) VALUES "
            "(?,?,?,'SEGMENT_RESULT',?,?,?,?,?,?,?,?,0,0,?,'nu')",
            (ids[soort], nieuw, soort, rij["result_hash"], rij["summary_json"],
             rij["cost_model_json"], rij["result_schema_version"], rij["backtest_engine_version"],
             rij["cost_model_version"], rij["metrics_version"], rij["segment_schema_version"],
             rij["warmup_status"]))
    with pytest.raises(sqlite3.DatabaseError):
        lab.transition(nieuw, "completed")
    lab.close()
    assert json  # gebruikt voor leesbaarheid van de rijen hierboven


def test_cancelling_never_completes_and_releases_no_test(tmp_path):
    c = vaste_bars(N)
    pad = tmp_path / "l.db"
    lab = _open(pad)
    ds = _snapshot(lab, c)
    eid = _experiment(lab, ds, c)
    lab.close()
    h = ExperimentRunner(pad, progress_write_seconds=0).submit(eid, ds, CFG)
    import time
    time.sleep(1.0)
    h.cancel()
    assert h.wait(120) and h.final_status == "cancelled"
    lab = _open(pad)
    try:
        assert lab.get(eid).status == "cancelled"
        assert lab.conn.execute("SELECT COUNT(*) FROM segment_results WHERE experiment_id=?",
                                (eid,)).fetchone()[0] == 0
        assert lab.test_status(eid)["status"] == "TEST_NOT_EXECUTED"
        with pytest.raises(sqlite3.DatabaseError):
            lab.open_test_result(eid, "AUDIT", "test")
    finally:
        lab.close()


def test_a_config_holding_longer_than_the_plan_is_refused(tmp_path):
    c = vaste_bars(N)
    lang = {**CFG, "exits": {"max_hold_seconds": 3600}}
    pad = tmp_path / "l.db"
    lab = _open(pad)
    ds = _snapshot(lab, c)
    eid = _experiment(lab, ds, c, cfg=lang)
    lab.close()
    with pytest.raises(RunRefused, match="houdtijd"):
        ExperimentRunner(pad).submit(eid, ds, lang)


def test_an_incomplete_plan_cannot_be_registered(tmp_path):
    c = vaste_bars(N)
    lab = _open(tmp_path / "l.db")
    eid = _experiment(lab, _snapshot(lab, c), c, registreren=False)
    lab.conn.execute("DELETE FROM experiment_segments WHERE experiment_id=? AND kind='TEST'", (eid,))
    with pytest.raises(sqlite3.DatabaseError):
        lab.transition(eid, "registered")
    lab.close()


def test_the_plan_is_locked_after_registration(uitgevoerd):
    pad, _, eid, _, _ = uitgevoerd
    lab = _open(pad)
    try:
        for sql in ("UPDATE experiment_segments SET end_ts = end_ts + 900 WHERE experiment_id=?",
                    "DELETE FROM experiment_segments WHERE experiment_id=?",
                    "UPDATE segment_plans SET max_hold_seconds = 60 WHERE experiment_id=?"):
            with pytest.raises(sqlite3.DatabaseError):
                lab.conn.execute(sql, (eid,))
        assert all(s["locked_at"] for s in lab.segment_plan(eid)["segments"])
    finally:
        lab.close()


# ---------------- testbescherming ----------------

def test_test_results_are_sealed_until_explicitly_opened(uitgevoerd):
    pad, _, eid, _, _ = uitgevoerd
    lab = _open(pad)
    try:
        overzicht = lab.segment_overview(eid)
        test = next(s for s in overzicht if s["kind"] == "TEST")
        assert "metrics" not in test and test["test"]["executed"]
        assert {s["kind"] for s in overzicht if "metrics" in s} == {"TRAIN", "VALIDATION"}
        test_id = next(s["id"] for s in lab.segment_plan(eid)["segments"] if s["kind"] == "TEST")
        with pytest.raises(SealedTestError):
            lab.segment_metrics(test_id)
        # overzicht en status tellen niet als toegang
        assert lab.conn.execute("SELECT COUNT(*) FROM test_access_log").fetchone()[0] == 0
    finally:
        lab.close()


def test_opening_test_logs_first_and_reuse_is_visible(tmp_path):
    c = vaste_bars(N)
    pad = tmp_path / "l.db"
    lab = _open(pad)
    ds = _snapshot(lab, c)
    a = _experiment(lab, ds, c, naam="eerste naam")
    lab.close()
    runner = ExperimentRunner(pad)
    assert runner.submit(a, ds, CFG).wait(300)
    lab = _open(pad)
    assert lab.test_status(a)["status"] == "TEST_UNOPENED"
    eerste = lab.open_test_result(a, "FINAL_EVALUATION", "test")
    assert eerste["metrics"] and not eerste["data_reused"]
    assert lab.test_status(a)["status"] == "TEST_OPENED"

    # een ander experiment, andere naam, zelfde familie en zelfde TEST-data
    b = _experiment(lab, ds, c, naam="heel andere naam", familie="tijdslimiet-2-bars")
    lab.close()
    assert runner.submit(b, ds, CFG).wait(300)
    lab = _open(pad)
    try:
        tweede = lab.open_test_result(b, "REPRODUCTION_REVIEW", "test")
        assert tweede["data_reused"] and tweede["prior_access_count"] == 1
        assert any(n["kind"] == "DATA_REUSED" for n in lab.annotations(b))
        log = lab.conn.execute("SELECT prior_access_count, data_reused FROM test_access_log "
                               "ORDER BY id").fetchall()
        assert [tuple(r) for r in log] == [(0, 0), (1, 1)]
        for sql in ("UPDATE test_access_log SET purpose='AUDIT'", "DELETE FROM test_access_log"):
            with pytest.raises(sqlite3.DatabaseError):
                lab.conn.execute(sql)
        # parameters blijven vergrendeld, ook na testinzage
        with pytest.raises(sqlite3.DatabaseError):
            lab.add_parameters(a, "challenger", {"x": 1})
        # identieke reproductie is geen nieuwe configuratie; familieoverzicht
        fam = lab.family_summary("Tijdslimiet 2 bars")
        assert fam["evaluated_configurations"] == 1 and fam["test_accesses"] == 2
    finally:
        lab.close()


def test_a_failed_log_releases_no_test_data(uitgevoerd):
    pad, _, eid, _, _ = uitgevoerd
    lab = _open(pad)
    try:
        voor = lab.conn.execute("SELECT COUNT(*) FROM test_access_log").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            lab.open_test_result(eid, "AUDIT", "   ")            # lege context: log weigert
        with pytest.raises(ValueError):
            lab.open_test_result(eid, "GEWOON_KIJKEN", "test")    # onbekend doel
        assert lab.conn.execute("SELECT COUNT(*) FROM test_access_log").fetchone()[0] == voor
    finally:
        lab.close()


def test_a_different_config_counts_as_a_new_configuration(tmp_path):
    c = vaste_bars(N)
    pad = tmp_path / "l.db"
    lab = _open(pad)
    ds = _snapshot(lab, c)
    a = _experiment(lab, ds, c)
    ander = {**CFG, "strategy": {**CFG["strategy"], "entry_threshold": 0.5}}
    b = _experiment(lab, ds, c, naam="ander", cfg=ander)
    lab.close()
    runner = ExperimentRunner(pad)
    assert runner.submit(a, ds, CFG).wait(300)
    assert runner.submit(b, ds, ander).wait(300)
    lab = _open(pad)
    try:
        assert lab.family_summary("tijdslimiet 2 bars")["evaluated_configurations"] == 2
    finally:
        lab.close()


# ---------------- oude resultaten ----------------

def test_a_phase_4_result_stays_unsegmented(tmp_path):
    from test_lab_runner import CFG as CFG4, _dataset, _experiment as exp4
    pad = tmp_path / "l.db"
    lab = _open(pad)
    ds = _dataset(lab)
    eid = exp4(lab, ds)
    lab.close()
    assert ExperimentRunner(pad).submit(eid, ds, CFG4).wait(120)
    lab = _open(pad)
    try:
        assert lab.segment_plan(eid) is None
        assert lab.test_status(eid)["status"] == "NO_TEST_SEGMENT"
        assert lab.conn.execute("SELECT result_kind FROM experiment_results WHERE experiment_id=?",
                                (eid,)).fetchone()[0] == "NORMALIZED_METRICS_RESULT"
    finally:
        lab.close()


def test_no_phase_5_test_reads_the_clock_for_market_data():
    tekst = Path(__file__).read_text(encoding="utf-8")
    # Samengesteld, anders vangt de test zijn eigen zoektekst.
    assert "." + "candles(" not in tekst
    assert "datetime" + ".now" not in tekst


def test_forced_exits_are_recorded_per_segment(uitgevoerd):
    """Gedwongen sluitingen aan het segmenteinde zijn een simulatie-ingreep:
    per segment vastgelegd met aantal, aandeel, beleid en beperking."""
    import json
    pad, _, eid, _, _ = uitgevoerd
    lab = _open(pad)
    try:
        for r in lab.conn.execute("SELECT trade_count, cross_boundary_count, "
                                  "segment_end_close_count, forced_exit_json "
                                  "FROM segment_results WHERE experiment_id=?", (eid,)):
            f = json.loads(r["forced_exit_json"])
            assert f["segment_end_close_count"] == r["segment_end_close_count"]
            assert f["cross_boundary_count"] == r["cross_boundary_count"]
            assert f["forced_exit_policy"] == "CLOSE_AT_LAST_SEGMENT_BAR"
            assert f["forced_exit_price_rule"] and f["forced_exit_cost_rule"]
            assert "niet representatief" in f["execution_fidelity_limitation"]
            if r["trade_count"]:
                assert f["segment_end_close_share"] == round(f["segment_end_close_count"] / r["trade_count"], 6)
    finally:
        lab.close()
