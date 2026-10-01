"""Experiment Lab, fase 4: meetbaarheid, kostenintegriteit, metriekdefinities
en herleidbaarheid. Er wordt gemeten, niet vergeleken of beoordeeld."""
import os
import sqlite3
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))
from gold_scalper.analysis.backtest import BACKTEST_ENGINE_VERSION
from gold_scalper.experiment_lab import metrics as M
from gold_scalper.experiment_lab.costs import (
    COST_MODEL_VERSION, CostModelError, build_cost_model,
)
from gold_scalper.experiment_lab.runner import ExperimentRunner
from gold_scalper.experiment_lab.storage import LEGACY, NORMALIZED, LabDatabase
from gold_scalper.experiment_lab.worker import RESULT_SCHEMA_VERSION, result_hash
from test_lab_runner import CFG, _dataset, _experiment, _lees

KM = build_cost_model({"instrument_currency": "USD", "spread": 0.7, "slippage": 0.02})
FX = {"account_currency": "EUR", "rate": 0.88, "rate_source": "ingesteld voor test",
      "profit_markup_pct": 1.0, "loss_markup_pct": 0.5, "origin": "ASSUMED"}
KM_FX = build_cost_model({"instrument_currency": "USD", "fx_conversion": FX})


def _bt(opened, closed, net, gross=None, units=2.0, reason="stop_loss", regime="trend",
        ambiguous=False):
    spread, slip = 0.7 * units, 0.02 * units
    gross = net + spread + slip if gross is None else gross
    return {"opened_at": opened, "closed_at": closed, "side": "buy", "units": units,
            "entry": 4300.0, "exit": 4301.0, "entry_mid": 4299.6, "exit_mid": 4301.3,
            "gross": gross, "net": gross - spread - slip, "reason": reason,
            "regime": regime, "mae": -1.0, "mfe": 2.0, "spread_cost": spread,
            "slippage_cost": slip, "stop_price": 4290.0, "target_price": 4310.0,
            "ambiguous_exit": ambiguous}


T = int(datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc).timestamp())      # zomer


def _trades(km=KM, netten=(5.0, -3.0, 0.0, 8.0, -1.0)):
    return [M.normalize_trade(i, _bt(T + i * 3600, T + i * 3600 + 900, n), km)
            for i, n in enumerate(netten, start=1)]


def _m(trades, dagen=("2026-07-14",), km=KM, summary=None):
    rec = M.compute_metrics(trades, summary or {"evaluations": 100, "rejections": {"edge_below_cost": 90}},
                            list(dagen), 2, km)
    return {r["metric_name"]: r for r in rec}


# ---------------- kosten ----------------

def test_cost_components_add_up_exactly_per_trade():
    for t in _trades():
        comps = (t["spread_cost_instrument"] + t["slippage_cost_instrument"]
                 + t["commission_cost_instrument"] + t["other_cost_instrument"])
        assert comps == pytest.approx(t["total_cost_instrument"], abs=1e-12)
        assert t["gross_pnl_instrument"] - t["total_cost_instrument"] == \
            pytest.approx(t["net_pnl_instrument"], abs=1e-9)


def test_gross_minus_costs_is_net_for_the_population():
    m = _m(_trades())
    assert m["gross_pnl"]["value"] - m["total_costs"]["value"] == \
        pytest.approx(m["net_pnl"]["value"], abs=1e-9)


def test_every_component_has_a_source_and_the_model_a_version():
    assert KM["cost_model_version"] == COST_MODEL_VERSION == 1
    for deel in ("spread_model", "slippage_model", "commission_model", "other_model", "fx_model"):
        assert KM[deel]["source"] in ("MEASURED", "CALCULATED", "ASSUMED", "UNKNOWN")
    assert "instap" in KM["slippage_model"]["applied"]


def test_without_fx_the_account_side_is_unknown_not_zero():
    t = _trades()[0]
    assert t["conversion_status"] == "UNKNOWN"
    for veld in ("fx_rate", "fx_cost_account", "gross_pnl_account",
                 "total_cost_account", "net_pnl_account"):
        assert t[veld] is None, veld
    m = _m(_trades())
    for naam in ("net_pnl_account", "fx_cost_account", "maximum_drawdown_account"):
        assert m[naam]["value"] is None and m[naam]["calculation_status"] == "UNKNOWN_INPUT"


def test_an_incomplete_fx_setting_is_unusable():
    km = build_cost_model({"instrument_currency": "USD",
                           "fx_conversion": {**FX, "loss_markup_pct": None}})
    t = M.normalize_trade(1, _bt(T, T + 900, -3.0), km)
    assert t["conversion_status"] == "UNUSABLE" and t["net_pnl_account"] is None


def test_the_fx_markup_is_never_built_in():
    """Zonder opgave geen opslag - ook niet de ooit gemeten 0,56%."""
    assert KM["fx_model"]["status"] == "UNKNOWN"
    bron = open(os.path.join(os.path.dirname(M.__file__), "costs.py"), encoding="utf-8").read()
    assert "0.56" not in bron and "0.98" not in bron


def test_account_formula_per_trade_and_population():
    trades = _trades(KM_FX)
    for t in trades:
        omgerekend = t["net_pnl_instrument"] * 0.88
        opslag = 1.0 if omgerekend > 0 else 0.5
        assert t["fx_cost_account"] == pytest.approx(abs(omgerekend) * opslag / 100)
        assert t["net_pnl_account"] == pytest.approx(omgerekend - t["fx_cost_account"])
        assert t["gross_pnl_account"] - t["total_cost_account"] == pytest.approx(t["net_pnl_account"])
    m = _m(trades, km=KM_FX)
    assert m["net_pnl_account"]["value"] == pytest.approx(sum(t["net_pnl_account"] for t in trades))
    assert m["net_pnl_account"]["currency"] == "EUR" and m["net_pnl"]["currency"] == "USD"


def test_currencies_are_never_mixed():
    """De wisselkoersopslag zit nooit in de instrumentkosten."""
    for a, b in zip(_trades(KM), _trades(KM_FX)):
        assert a["total_cost_instrument"] == b["total_cost_instrument"]
        assert a["net_pnl_instrument"] == b["net_pnl_instrument"]


@pytest.mark.parametrize("fout", [
    {}, {"instrument_currency": ""},
    {"instrument_currency": "USD", "spread": -1},
    {"instrument_currency": "USD", "fx_conversion": {**FX, "rate": 0}},
    {"instrument_currency": "USD", "fx_conversion": {**FX, "profit_markup_pct": 12}},
    {"instrument_currency": "USD", "fx_conversion": {**FX, "account_currency": None}},
    {"instrument_currency": "USD", "fx_conversion": {**FX, "origin": "GEGOKT"}},
])
def test_an_ambiguous_cost_model_is_refused(fout):
    with pytest.raises(CostModelError):
        build_cost_model(fout)


# ---------------- metrieken ----------------

def test_every_metric_has_one_versioned_definition():
    rec = M.compute_metrics(_trades(), {"evaluations": 1, "rejections": {}}, ["2026-07-14"], 2, KM)
    namen = [r["metric_name"] for r in rec]
    assert len(namen) == len(set(namen)) and set(namen) == set(M.DEFINITIONS)
    for r in rec:
        assert r["metric_version"] == M.METRICS_VERSION
        assert r["unit"] and r["population"] and r["calculation_status"]


def test_identical_trades_identical_metrics():
    assert M.compute_metrics(_trades(), {}, ["d"], 2, KM) == M.compute_metrics(_trades(), {}, ["d"], 2, KM)


def test_win_rate_carries_numerator_and_denominator():
    w = _m(_trades())["win_rate"]
    assert (w["numerator"], w["denominator"]) == (2, 5) and w["value"] == 40.0


def test_breakeven_is_separate():
    m = _m(_trades())
    assert (m["wins"]["value"], m["losses"]["value"], m["breakeven"]["value"]) == (2, 2, 1)


def test_profit_factor_without_losses_does_not_exist():
    pf = _m(_trades(netten=(4.0, 2.0)))["profit_factor"]
    assert pf["value"] is None and pf["calculation_status"] == "NOT_APPLICABLE"
    assert pf["denominator"] == 0.0


def test_an_empty_population_gives_no_misleading_zeros():
    m = _m([])
    for naam in ("win_rate", "average_trade", "median_trade", "profit_factor", "expectancy",
                 "maximum_drawdown", "average_holding_seconds", "p90_holding_seconds",
                 "gross_per_trade", "net_per_trade"):
        assert m[naam]["value"] is None, naam
        assert m[naam]["calculation_status"] == "INSUFFICIENT_DATA", naam
    assert m["trade_count"]["value"] == 0 and m["trade_count"]["calculation_status"] == "VALID"


def test_expectancy_equals_average_trade():
    m = _m(_trades())
    assert m["expectancy"]["value"] == pytest.approx(m["average_trade"]["value"])


def test_drawdown_uses_an_explicit_basis():
    m = _m(_trades(netten=(5.0, -3.0, -4.0, 8.0)))
    assert m["maximum_drawdown"]["value"] == pytest.approx(7.0)
    assert m["maximum_drawdown"]["currency"] == "USD"
    assert "vanaf 0" in m["maximum_drawdown"]["numerator_definition"]
    pct = m["maximum_drawdown_pct"]
    assert pct["value"] is None and pct["calculation_status"] == "NOT_APPLICABLE"
    assert "geen expliciete kapitaalbasis" in pct["population"]


def test_account_drawdown_only_when_every_trade_is_converted():
    gemengd = _trades(KM_FX)[:3] + _trades(KM)[3:]
    m = _m(gemengd, km=KM_FX)
    assert m["maximum_drawdown_account"]["value"] is None
    assert m["maximum_drawdown_account"]["calculation_status"] == "PARTIAL"
    assert _m(_trades(KM_FX), km=KM_FX)["maximum_drawdown_account"]["value"] is not None


def test_median_and_p90():
    assert M._p90(list(range(1, 11))) == 9          # nearest rank: ceil(0.9*10)=9
    assert M._p90([5]) == 5
    assert M._p90(list(range(1, 101))) == 90
    m = _m(_trades())
    assert m["median_holding_seconds"]["value"] == 900


def test_ambiguous_exits_stay_visible():
    trades = [M.normalize_trade(1, _bt(T, T + 900, 1.0, ambiguous=True), KM),
              M.normalize_trade(2, _bt(T + 900, T + 1800, 1.0), KM)]
    m = _m(trades)
    assert m["ambiguous_exit_count"]["value"] == 1 and m["ambiguous_exit_share"]["value"] == 50.0


# ---------------- handelsdag, sessie, uitsplitsingen, frequentie ----------------

def test_trading_day_is_europe_amsterdam():
    """22:30 UTC in de zomer is 00:30 in Amsterdam: de volgende handelsdag."""
    laat = int(datetime(2026, 7, 14, 22, 30, tzinfo=timezone.utc).timestamp())
    t = M.normalize_trade(1, _bt(laat - 900, laat, 1.0), KM)
    assert t["trading_day"] == "2026-07-15" and t["timezone"] == "Europe/Amsterdam"


def test_sessions_keep_their_utc_definition():
    from gold_scalper.learning import sessions as leer
    from gold_scalper import session_rules
    assert leer.session_of is session_rules.session_of              # één definitie
    t = M.normalize_trade(1, _bt(int(datetime(2026, 7, 14, 23, 30, tzinfo=timezone.utc)
                                     .timestamp()), T + 10**5, 1.0), KM)
    assert t["session"] == "azie"                                   # 23:30 UTC


def test_every_breakdown_adds_up_to_the_population():
    trades = _trades() + [M.normalize_trade(9, _bt(T + 86400, T + 86400 + 900, 2.0,
                                                   reason="take_profit", regime="range"), KM)]
    delen = M.breakdowns(trades, 2, "USD")
    for dim in ("trading_day", "session", "regime", "close_reason"):
        rijen = [d for d in delen if d["dimension"] == dim]
        assert sum(d["trade_count"] for d in rijen) == len(trades), dim
        assert sum(d["net"] for d in rijen) == pytest.approx(sum(t["net_pnl_instrument"] for t in trades))
        assert sum(d["costs"] for d in rijen) == pytest.approx(sum(t["total_cost_instrument"] for t in trades))
    dag = [d for d in delen if d["dimension"] == "trading_day"]
    assert all(d["timezone"] == "Europe/Amsterdam" for d in dag)
    assert M.check_invariants(trades, M.compute_metrics(trades, {}, ["x"], 2, KM), delen) == []


def test_breakdowns_carry_no_judgement():
    for rij in M.breakdowns(_trades(), 2, "USD"):
        assert not {"significant", "verdict", "score", "goed", "slecht"} & set(rij)


def test_frequency_counts_days_without_trades():
    """Drie handelsdagen in de dataset, trades op één: 5/3 per dag, mediaan 0."""
    m = _m(_trades(), dagen=("2026-07-13", "2026-07-14", "2026-07-15"))
    assert m["trading_days"]["value"] == 3
    assert m["trades_per_day_mean"]["value"] == pytest.approx(5 / 3)
    assert m["trades_per_day_median"]["value"] == 0
    assert m["cost_per_day"]["value"] == pytest.approx(m["total_costs"]["value"] / 3)
    assert m["trades_per_day_mean"]["timezone"] == "Europe/Amsterdam"


def test_rejections_are_codes_with_share_and_denominator():
    rij = M.rejection_breakdown({"evaluations": 200, "rejections": {"edge_below_cost": 150,
                                                                    "spread_te_hoog": 30}})
    assert rij[0] == {"code": "edge_below_cost", "count": 150, "share": 75.0, "denominator": 200}


# ---------------- invarianten vangen fouten ----------------

def test_the_invariant_check_catches_a_broken_trade():
    trades = _trades()
    trades[1]["net_pnl_instrument"] += 0.5
    fouten = M.check_invariants(trades, M.compute_metrics(trades, {}, ["x"], 2, KM),
                                M.breakdowns(trades, 2, "USD"))
    assert any("bruto - kosten != netto" in f for f in fouten)


def test_the_invariant_check_catches_an_account_amount_without_conversion():
    trades = _trades()
    trades[0]["net_pnl_account"] = 1.0
    assert any("zonder omrekening" in f for f in M.check_invariants(
        trades, M.compute_metrics(trades, {}, ["x"], 2, KM), M.breakdowns(trades, 2, "USD")))


# ---------------- via de runner: opslag, versies, herleidbaarheid ----------------

@pytest.fixture
def voltooid(tmp_path):
    pad = tmp_path / "gold_scalper_lab.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab, n=900)
    eid = _experiment(lab, ds)
    lab.close()
    h = ExperimentRunner(pad).submit(eid, ds, CFG)
    assert h.wait(120) and h.final_status == "completed", h.error
    return pad, eid


def test_versions_are_stored(voltooid):
    res = _lees(*voltooid)[2]
    assert res["result_kind"] == NORMALIZED
    assert res["versions"] == {"result_schema_version": RESULT_SCHEMA_VERSION,
                               "backtest_engine_version": BACKTEST_ENGINE_VERSION,
                               "cost_model_version": COST_MODEL_VERSION,
                               "metrics_version": M.METRICS_VERSION}
    # Motor 4 sinds fase 5 (segmentopties); het resultaatschema is ongewijzigd.
    assert BACKTEST_ENGINE_VERSION == 4 and RESULT_SCHEMA_VERSION == 2


def test_stored_trades_reproduce_the_result_hash(voltooid):
    """De opgeslagen rijen geven exact de hash die de worker berekende: de
    genormaliseerde trades zíjn het technische bronresultaat."""
    res = _lees(*voltooid)[2]
    assert res["trade_count"] == len(res["trades"]) == res["summary"]["trades"]
    assert result_hash(res["summary"], res["trades"]) == res["result_hash"]


def test_no_raw_trade_json_is_duplicated(voltooid):
    conn = sqlite3.connect(voltooid[0])
    assert conn.execute("SELECT trades_json FROM experiment_results").fetchone()[0] is None


def test_the_full_metric_set_is_stored_and_consistent(voltooid):
    res = _lees(*voltooid)[2]
    assert set(res["metrics"]) == set(M.REQUIRED_METRICS)
    trades = res["trades"]
    assert res["metrics"]["net_pnl"]["value"] == pytest.approx(sum(t["net_pnl_instrument"] for t in trades))
    for t in trades:
        assert t["gross_pnl_instrument"] - t["total_cost_instrument"] == \
            pytest.approx(t["net_pnl_instrument"], abs=1e-9)
    for dim in M.DIMENSIONS:
        assert sum(b["trade_count"] for b in res["breakdowns"] if b["dimension"] == dim) == len(trades)


@pytest.mark.parametrize("sql", [
    "UPDATE experiment_trades SET net_pnl_instrument = 0",
    "DELETE FROM experiment_trades",
    "UPDATE experiment_metrics SET value = 1",
    "DELETE FROM experiment_metrics",
    "UPDATE experiment_breakdowns SET net = 0",
    "DELETE FROM experiment_rejections",
    "UPDATE experiment_results SET cost_model_version = 9",
])
def test_everything_is_immutable_after_completed(voltooid, sql):
    conn = sqlite3.connect(voltooid[0])
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(sql)


def test_a_valid_metric_cannot_be_null_and_vice_versa(voltooid):
    conn = sqlite3.connect(voltooid[0])
    telling = conn.execute(
        "SELECT COUNT(*) FROM experiment_metrics WHERE "
        "(calculation_status='VALID') <> (value IS NOT NULL)").fetchone()[0]
    assert telling == 0


# ---------------- transactie ----------------

def _lopend(tmp_path):
    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab)
    eid = _experiment(lab, ds)
    lab.transition(eid, "queued")
    lab.begin_run(eid, "process")
    return lab, eid


def _resultaat(trades=None, metrics=None):
    trades = _trades() if trades is None else trades
    return {"result_hash": result_hash({"trades": len(trades)}, trades),
            "summary": {"trades": len(trades)}, "trades": trades,
            "metrics": M.compute_metrics(trades, {}, ["x"], 2, KM) if metrics is None else metrics,
            "breakdowns": M.breakdowns(trades, 2, "USD"), "rejections": [],
            "cost_model": KM, "provenance": {},
            "versions": {"result_schema_version": 2, "backtest_engine_version": 3,
                         "cost_model_version": 1, "metrics_version": 1}}


def test_a_failure_halfway_rolls_everything_back(tmp_path):
    lab, eid = _lopend(tmp_path)
    kapot = _resultaat()
    kapot["metrics"][3] = {**kapot["metrics"][3], "value": None, "calculation_status": "VALID"}
    with pytest.raises(sqlite3.IntegrityError):
        lab.complete_with_result(eid, kapot)
    for tabel in ("experiment_results", "experiment_trades", "experiment_metrics",
                  "experiment_breakdowns"):
        assert lab.conn.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0] == 0, tabel
    assert lab.get(eid).status == "running"


def test_completed_requires_the_minimum_metric_set(tmp_path):
    lab, eid = _lopend(tmp_path)
    onvolledig = _resultaat()
    onvolledig["metrics"] = onvolledig["metrics"][:-1]
    with pytest.raises(sqlite3.DatabaseError):
        lab.complete_with_result(eid, onvolledig)
    assert lab.get(eid).status == "running"


def test_completed_requires_every_trade_row(tmp_path):
    """trade_count zegt 5, maar er staan er 4: completed wordt geweigerd."""
    lab, eid = _lopend(tmp_path)
    r = _resultaat()
    lab.conn.execute("BEGIN")
    lab.conn.execute(
        "INSERT INTO experiment_results (experiment_id, result_kind, result_schema_version, "
        "backtest_engine_version, cost_model_version, metrics_version, result_hash, summary_json, "
        "provenance_json, cost_model_json, trade_count, created_at) "
        "VALUES (?, ?, 2, 3, 1, 1, 'x', '{}', '{}', '{}', 5, 'nu')", (eid, NORMALIZED))
    for t in r["trades"][:4]:
        lab.conn.execute(
            f"INSERT INTO experiment_trades (experiment_id, {', '.join(M.TRADE_FIELDS)}) "
            f"VALUES (?, {', '.join('?' * len(M.TRADE_FIELDS))})",
            (eid, *(t[v] for v in M.TRADE_FIELDS)))
    kol = ("metric_name", "metric_version", "value", "unit", "currency", "timezone", "population",
           "numerator", "denominator", "numerator_definition", "denominator_definition",
           "sample_size", "calculation_status")
    for m in r["metrics"]:
        lab.conn.execute(f"INSERT INTO experiment_metrics (experiment_id, {', '.join(kol)}) "
                         f"VALUES (?, {', '.join('?' * len(kol))})", (eid, *(m[k] for k in kol)))
    with pytest.raises(sqlite3.DatabaseError):
        lab.transition(eid, "completed")
    lab.conn.execute("ROLLBACK")


def test_negative_zero_survives_storage_as_the_same_hash():
    """SQLite bewaart het teken van nul niet; de normalisatie voorkomt -0.0."""
    bt = _bt(T, T + 900, 0.0)
    bt["gross"], bt["net"] = -0.0, -0.0 - bt["spread_cost"] - bt["slippage_cost"]
    t = M.normalize_trade(1, bt, KM)
    assert str(t["gross_pnl_instrument"]) == "0.0"


# ---------------- oude resultaten ----------------

def test_a_schema_3_result_stays_legacy_and_unchanged(tmp_path):
    from gold_scalper.experiment_lab import storage as st

    pad = tmp_path / "v3.db"
    conn = sqlite3.connect(pad, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("BEGIN")
    for versie in (1, 2, 3):
        for stap in st.MIGRATIONS[versie]:
            conn.execute(stap)
    conn.execute("INSERT INTO lab_meta VALUES ('schema_version', '3')")
    conn.execute("INSERT INTO experiments (name, type, status, created_at) VALUES ('oud','baseline','draft','nu')")
    conn.execute("UPDATE experiments SET hypothesis='h', expected_effect='e', primary_metric='p', "
                 "evaluation_method='m', hypothesis_family_id='f'")
    for s in ("registered", "queued", "running"):
        conn.execute("UPDATE experiments SET status=?", (s,))
    conn.execute("INSERT INTO experiment_results VALUES (1, 'oudehash', '{\"trades\":2}', "
                 "'[{\"net\":1},{\"net\":-1}]', '{\"backtest_engine_version\":2}', 'nu')")
    conn.execute("UPDATE experiments SET status='completed'")
    conn.execute("COMMIT")
    conn.close()

    db = LabDatabase(pad).open()
    res = db.result(1)
    assert res["result_kind"] == LEGACY
    assert res["result_hash"] == "oudehash" and res["trades"] == [{"net": 1}, {"net": -1}]
    assert res["trade_count"] == 2 and res["versions"]["backtest_engine_version"] == 2
    assert res["versions"]["metrics_version"] is None and "metrics" not in res
    assert db.conn.execute("SELECT COUNT(*) FROM experiment_metrics").fetchone()[0] == 0
    with pytest.raises(sqlite3.DatabaseError):
        db.conn.execute("UPDATE experiment_results SET result_hash='x'")
    db.close()
    LabDatabase(pad).open().close()                 # tweede keer: idempotent


# ---------------- grote resultaten ----------------

def test_a_large_payload_is_processed(tmp_path):
    """Ruim boven de 64 kB waarop de meetopzet in fase 3 vastliep."""
    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab, n=2000)
    eid = _experiment(lab, ds)
    lab.close()
    h = ExperimentRunner(pad).submit(eid, ds, CFG)
    assert h.wait(180) and h.final_status == "completed", h.error
    res = _lees(pad, eid)[2]
    import json
    assert len(json.dumps(res["trades"])) > 64 * 1024
    assert result_hash(res["summary"], res["trades"]) == res["result_hash"]


def test_the_request_has_no_path_for_result_files():
    """Geen tijdelijke resultaatbestanden: er is geen pad in de aanvraag om te misbruiken."""
    from dataclasses import fields
    from gold_scalper.experiment_lab.worker import RunRequest
    assert {f.name for f in fields(RunRequest)} == {
        "experiment_id", "dataset_id", "dataset_hash", "lab_db_path", "config", "config_hash",
        # sinds fase 5: het vergrendelde plan als gewone gegevens - geen pad
        "segment_plan",
        # sinds fase 6: één segment als gewone gegevens - geen pad
        "single_segment"}


# ---------------- reproductie onder andere versies ----------------

def _reproductie(tmp_path, provenance):
    from test_lab_runner import CFG, _dataset, _experiment
    from gold_scalper.experiment_lab.runner import ExperimentRunner
    from gold_scalper.experiment_lab.storage import LabDatabase

    pad = tmp_path / "l.db"
    lab = LabDatabase(pad).open()
    ds = _dataset(lab)
    orig = _experiment(lab, ds)
    lab.close()
    runner = ExperimentRunner(pad)
    assert runner.submit(orig, ds, CFG).wait(120)
    lab = LabDatabase(pad).open()
    kopie = lab.reproduce(orig, provenance)
    lab.transition(kopie, "registered")
    lab.close()
    assert runner.submit(kopie, ds, CFG).wait(120)
    lab = LabDatabase(pad).open()
    try:
        return [a for a in lab.annotations(kopie) if a["kind"] == "uitvoeringsomgeving"]
    finally:
        lab.close()


def test_a_reproduction_in_the_same_environment_is_not_marked(tmp_path):
    zelfde = {"software_version": "5.5.0", "strategy_version": "scalp-0.2.0",
              "execution_semantics_version": 3}
    assert _reproductie(tmp_path, zelfde) == []


def test_a_reproduction_under_other_versions_is_marked(tmp_path):
    """Reproduceerbaar als nieuw experiment, maar gemarkeerd als niet exact
    dezelfde uitvoeringsomgeving."""
    anders = {"software_version": "5.6.0", "strategy_version": "scalp-0.2.0",
              "execution_semantics_version": 3}
    noten = _reproductie(tmp_path, anders)
    assert len(noten) == 1 and "software_version: 5.5.0 -> 5.6.0" in noten[0]["text"]


# ---------------- motorversie aan de uitvoer vastgepind ----------------

def test_the_engine_version_is_pinned_to_its_output():
    """Verandert de uitvoer van de backtestmotor - een veld erbij, eraf of
    hernoemd - dan faalt deze test tot BACKTEST_ENGINE_VERSION omhoog is en
    deze lijst is bijgewerkt. Zo kan de betekenis van een resultaat niet
    ongemerkt veranderen onder hetzelfde versienummer."""
    from gold_scalper.analysis.backtest import BACKTEST_ENGINE_VERSION, BacktestTrade

    per_versie = {
        3: {"opened_at", "closed_at", "side", "units", "entry", "exit", "entry_mid",
            "exit_mid", "gross", "cost", "net", "reason", "score", "regime", "mae",
            "mfe", "spread_cost", "slippage_cost", "stop_price", "target_price",
            "ambiguous_exit"},
    }
    # Versie 4 voegt segmentsemantiek toe via opties; de uitvoervelden zijn gelijk.
    per_versie[4] = per_versie[3]
    assert set(BacktestTrade.__dataclass_fields__) == per_versie[BACKTEST_ENGINE_VERSION]
