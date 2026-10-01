"""Leesmodellen van het Experiment Lab voor Home Assistant (5.7).

**EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING**

Staat buiten ``experiment_lab`` en kent Home Assistant niet: elke functie
krijgt een open ``LabDatabase`` en geeft een gewoon dict terug. Elk model
wordt veld voor veld opgebouwd; er gaat nooit een databaserij of een
JSON-kolom ongefilterd naar buiten. ``MODEL_KEYS`` legt per model de
toegestane sleutels vast; een test vergelijkt ze exact.

Wat geen enkel model doet:

* TEST openen. Er wordt geen enkele methode aangeroepen die TEST leest of een
  toegang logt (``open_*``, ``create_*``); een test bewaakt dat.
* TEST-prestaties tonen zolang TEST verzegeld is. Prestaties staan alleen in
  een beoordeling of vergelijking - die heeft TEST zelf geopend en gelogd.
* Een rangorde, een "beste" strategie, een winnaar of een advies geven.
* Paden, geheimen of volledige tradelijsten teruggeven.
"""

from __future__ import annotations

import json

from .experiment_lab import INVARIANT
from .experiment_lab.storage import LAB_SCHEMA_VERSION

#: Versie van de vorm van deze modellen. Omhoog bij elke sleutelwijziging.
READ_MODEL_VERSION = 1

DISCLAIMER = (
    "Onderzoeksclassificatie op historische backtest- of paperdata. Geen advies, "
    "winstgarantie of toestemming voor live trading."
)

#: Neutrale omschrijving per kwaliteitscode. Beschrijft wat de code betekent,
#: niet wat ervan te vinden is.
QUALITY_LABELS = {
    "missing_during_expected_market_hours": "ontbrekende bar terwijl de markt volgens het rooster open was",
    "expected_market_closure": "geen bar tijdens een geplande sluiting",
    "unknown_market_expectation": "gat zonder bekende marktverwachting",
    "unexpected_bar": "bar terwijl de markt volgens het rooster dicht was",
    "mixed_source": "bars uit meer dan één bron",
    "off_grid": "tijdstip niet op het raster van het tijdvak",
    "precision_loss": "prijs had meer decimalen dan de instrumentprecisie",
    "precision_fallback": "instrumentprecisie onbekend; terugvalwaarde gebruikt",
    "flat_bar": "bar met open = hoog = laag = slot",
    "incomplete_last_bar": "laatste bar nog niet afgesloten",
    "exact_duplicate": "dubbele bar met gelijke waarden",
    "conflicting_duplicate": "dubbele bar met afwijkende waarden",
    "invalid_ohlc": "ongeldige OHLC-verhouding",
    "invalid_volume": "ongeldig volume",
    "out_of_order_input": "invoer niet op volgorde",
}

STATUS_GROUPS = ("draft", "registered", "queued", "running", "completed",
                 "failed", "interrupted", "cancelled")

MODEL_KEYS: dict[str, frozenset] = {
    "LabOverview": frozenset({
        "read_model_version", "backend", "lab_schema_version", "database",
        "datasets", "experiments", "assessments", "comparisons", "active_experiment",
        "invariant",
    }),
    "ExperimentListItem": frozenset({
        "id", "name", "type", "status", "hypothesis_family_id", "dataset_id",
        "created_at", "registered_at", "finished_at",
    }),
    "ExperimentDetail": frozenset({
        "id", "name", "description", "type", "status", "hypothesis", "expected_effect",
        "primary_metric", "hypothesis_family_id", "dataset", "config_hash", "versions",
        "provenance", "walk_forward", "progress", "fidelity", "annotations", "error",
        "test_status", "timestamps",
    }),
    "ExperimentProgress": frozenset({
        "experiment_id", "status", "progress_pct", "windows_total", "current_window",
        "windows_completed", "candidates_total", "current_candidate", "current_segment",
        "bars_total", "bars_processed", "last_progress_at",
    }),
    "DatasetListItem": frozenset({
        "id", "symbol", "timeframe", "start_ts", "end_ts", "bar_count", "quality_status",
        "created_at",
    }),
    "DatasetDetail": frozenset({
        "id", "hash", "hash_version", "symbol", "timeframe", "start_ts", "end_ts",
        "bar_count", "source", "precision", "precision_origin", "quality_status",
        "findings", "created_at", "requests",
    }),
    "AssessmentListItem": frozenset({
        "id", "experiment_id", "status", "final_classification", "data_reused",
        "created_at",
    }),
    "AssessmentDetail": frozenset({
        "id", "experiment_id", "status", "raw_classification", "classification_ceiling",
        "fidelity_ceiling", "final_classification", "explanation", "components",
        "blocking_reasons", "warnings", "test_independence", "data_reused",
        "overlapping_test_data", "thresholds", "rules_version", "schema_version",
        "input_versions", "sources", "trace", "error", "created_at", "completed_at",
        "disclaimer",
    }),
    "ComparisonListItem": frozenset({
        "id", "mode", "status", "comparability_status", "reference_experiment_id",
        "challenger_experiment_id", "result", "created_at",
    }),
    "ComparisonDetail": frozenset({
        "id", "mode", "status", "comparability_status", "comparability_reasons",
        "same_dataset", "reference", "challenger", "checks", "sections",
        "metric_comparison_available", "metric_deltas", "warnings", "result",
        "explanation", "rules_version", "error", "created_at", "completed_at",
        "disclaimer",
    }),
    "TestStatus": frozenset({
        "experiment_id", "test_exists", "test_executed", "test_opened",
        "prior_access_count", "data_reused", "overlapping_test_data",
        "hypothesis_family_id", "test_windows", "test_windows_opened",
        "test_windows_unopened",
    }),
    "FamilySummary": frozenset({
        "hypothesis_family_id", "registered_experiments", "reproductions",
        "unique_candidates", "train_runs", "unique_evaluated_configurations",
        "test_executions", "test_accesses", "data_reused_count",
        "overlapping_test_count", "first_test_access", "last_test_access",
    }),
}


class ReadModelError(LookupError):
    """Een gevraagd object bestaat niet."""

    def __init__(self, code: str, object_id: int | str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.object_id = object_id


def _json(waarde, standaard):
    if waarde in (None, ""):
        return standaard
    try:
        return json.loads(waarde)
    except (TypeError, ValueError):
        return standaard


def _check(naam: str, model: dict) -> dict:
    if set(model) != MODEL_KEYS[naam]:
        raise RuntimeError(f"{naam} wijkt af van de allowlist")
    return model


def _tel(db, sql: str, *args) -> int:
    return int(db.conn.execute(sql, args).fetchone()[0])


# ------------------------------------------------------------- overzicht --

def lab_overview(db, active_experiment_id: int | None = None) -> dict:
    per_status = {s: 0 for s in STATUS_GROUPS}
    for rij in db.conn.execute("SELECT status, COUNT(*) FROM experiments GROUP BY status"):
        per_status[rij[0]] = int(rij[1])
    actief = None
    if active_experiment_id is None:
        rij = db.conn.execute("SELECT id FROM experiments WHERE status='running' LIMIT 1").fetchone()
        active_experiment_id = rij[0] if rij else None
    if active_experiment_id is not None:
        actief = experiment_progress(db, active_experiment_id)
    return _check("LabOverview", {
        "read_model_version": READ_MODEL_VERSION,
        "backend": "reachable",
        "lab_schema_version": int(db.schema_version()),
        "database": "available",
        "datasets": _tel(db, "SELECT COUNT(*) FROM datasets"),
        "experiments": per_status,
        "assessments": _tel(db, "SELECT COUNT(*) FROM assessments"),
        "comparisons": _tel(db, "SELECT COUNT(*) FROM comparisons"),
        "active_experiment": actief,
        "invariant": INVARIANT,
    })


# ----------------------------------------------------------- experimenten --

def experiment_list(db, limit: int = 100) -> list[dict]:
    rijen = db.conn.execute(
        "SELECT e.id, e.name, e.type, e.status, e.hypothesis_family_id, e.dataset_id, "
        "e.created_at, e.registered_at, r.finished_at FROM experiments e "
        "LEFT JOIN experiment_runs r ON r.experiment_id = e.id "
        "ORDER BY e.id DESC LIMIT ?", (int(limit),)).fetchall()
    return [_check("ExperimentListItem", {
        "id": r["id"], "name": r["name"], "type": r["type"], "status": r["status"],
        "hypothesis_family_id": r["hypothesis_family_id"], "dataset_id": r["dataset_id"],
        "created_at": r["created_at"], "registered_at": r["registered_at"],
        "finished_at": r["finished_at"],
    }) for r in rijen]


def experiment_progress(db, experiment_id: int) -> dict:
    exp = db.get(experiment_id)
    if exp is None:
        raise ReadModelError("experiment_not_found", experiment_id)
    st = db.run_state(experiment_id) or {}
    return _check("ExperimentProgress", {
        "experiment_id": experiment_id,
        "status": exp.status,
        "progress_pct": float(st.get("progress_pct") or 0.0),
        "windows_total": int(st.get("windows_total") or 0),
        "current_window": st.get("current_window"),
        "windows_completed": int(st.get("windows_completed") or 0),
        "candidates_total": int(st.get("candidates_total") or 0),
        "current_candidate": st.get("current_candidate"),
        "current_segment": st.get("current_segment"),
        "bars_total": int(st.get("bars_total") or 0),
        "bars_processed": int(st.get("bars_processed") or 0),
        "last_progress_at": st.get("last_progress_at"),
    })


def _dataset_kort(db, dataset_id: int | None) -> dict | None:
    if dataset_id is None:
        return None
    ds = db.dataset(dataset_id)
    if ds is None:
        return None
    return {"id": ds["id"], "symbol": ds["symbol"], "timeframe": ds["timeframe"],
            "start_ts": ds["start_ts"], "end_ts": ds["end_ts"], "bar_count": ds["bar_count"],
            "hash": ds["hash"], "quality_status": ds["quality_status"]}


def _walk_forward(db, experiment_id: int) -> dict | None:
    plan = db.wf_plan(experiment_id)
    if plan is None:
        return None
    ov = db.wf_overview(experiment_id)
    regel = _json(plan.get("selection_rule_json"), {})
    validatie = {
        r["window_id"]: {"status": r["status"], "reason": r["reason"]}
        for r in db.conn.execute(
            "SELECT window_id, status, reason FROM wf_validation_decisions WHERE experiment_id=?",
            (experiment_id,))}
    venster_ids = {
        r["window_index"]: r["id"] for r in db.conn.execute(
            "SELECT id, window_index FROM wf_windows WHERE experiment_id=?", (experiment_id,))}
    vensters = []
    for w in ov.get("windows", []):
        vid = venster_ids.get(w["window_index"])
        vensters.append({
            "window_index": w["window_index"], "status": w["status"],
            "status_reason": w.get("status_reason"),
            "selection_status": w.get("selection_status"),
            "selected_candidate_id": w.get("selected_candidate_id"),
            "validation": validatie.get(vid),
            "test": w.get("test"),
        })
    return {
        "mode": plan["mode"], "window_type": plan["window_type"],
        "first_train_start": plan["first_train_start"], "train_length": plan["train_length"],
        "validation_length": plan["validation_length"], "test_length": plan["test_length"],
        "step_size": plan["step_size"], "window_count": plan["window_count"],
        "primary_metric": plan.get("primary_metric"),
        "selection_direction": regel.get("direction"),
        "validation_policy": regel.get("validation_policy"),
        "candidate_set_hash": plan["candidate_set_hash"],
        "candidates": [
            {"id": k.get("id") or k.get("candidate_id"), "label": k.get("candidate_label"),
             "config_hash": k.get("config_hash")}
            for k in plan.get("candidates", [])
        ],
        "windows": vensters,
        "windows_completed": ov.get("windows_completed"),
        "windows_no_selection": ov.get("windows_no_selection"),
        "windows_validation_rejected": ov.get("windows_validation_rejected"),
    }


def experiment_detail(db, experiment_id: int) -> dict:
    exp = db.get(experiment_id)
    if exp is None:
        raise ReadModelError("experiment_not_found", experiment_id)
    st = db.run_state(experiment_id) or {}
    resultaat_rij = db.conn.execute(
        "SELECT fidelity_status FROM experiment_results WHERE experiment_id=?",
        (experiment_id,)).fetchone() if _heeft_kolom(db, "experiment_results", "fidelity_status") else None
    return _check("ExperimentDetail", {
        "id": exp.id, "name": exp.name, "description": exp.description, "type": exp.type,
        "status": exp.status, "hypothesis": exp.hypothesis, "expected_effect": exp.expected_effect,
        "primary_metric": exp.primary_metric, "hypothesis_family_id": exp.hypothesis_family_id,
        "dataset": _dataset_kort(db, exp.dataset_id),
        "config_hash": exp.config_hash,
        "versions": {"software": exp.software_version, "strategy": exp.strategy_version,
                     "execution_semantics": exp.execution_semantics_version},
        "provenance": {"reproduced_from": exp.reproduced_from},
        "walk_forward": _walk_forward(db, experiment_id),
        "progress": experiment_progress(db, experiment_id) if st else None,
        "fidelity": resultaat_rij[0] if resultaat_rij else None,
        "annotations": [{"kind": a.get("kind"), "text": a.get("text"),
                         "created_at": a.get("created_at")} for a in db.annotations(experiment_id)],
        "error": _veilige_fout(exp.error),
        "test_status": test_status(db, experiment_id),
        "timestamps": {"created_at": exp.created_at, "registered_at": exp.registered_at,
                       "started_at": getattr(exp, "started_at", None),
                       "finished_at": st.get("finished_at")},
    })


def _heeft_kolom(db, tabel: str, kolom: str) -> bool:
    return any(r[1] == kolom for r in db.conn.execute(f"PRAGMA table_info({tabel})"))


def _veilige_fout(tekst: str | None) -> str | None:
    """Een foutmelding zonder paden of tracebacks, begrensd."""
    if not tekst:
        return None
    regel = str(tekst).splitlines()[0]
    for teken in ("/", "\\"):
        if teken in regel:
            regel = regel.split(teken, 1)[0].rstrip(" :'\"(") + " (pad weggelaten)"
    return regel[:300]


def test_status(db, experiment_id: int) -> dict:
    """Of TEST bestaat, gedraaid en geopend is. Nooit een prestatiecijfer."""
    exp = db.get(experiment_id)
    if exp is None:
        raise ReadModelError("experiment_not_found", experiment_id)
    plan = db.wf_plan(experiment_id)
    if plan is not None:
        totaal = _tel(db, "SELECT COUNT(*) FROM wf_segments WHERE experiment_id=? AND kind='TEST'",
                      experiment_id)
        geopend = _tel(db, "SELECT COUNT(DISTINCT window_id) FROM wf_test_access_log "
                           "WHERE experiment_id=?", experiment_id)
        log = db.conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(data_reused),0), "
            "COALESCE(SUM(overlapping_prior_count > 0),0) FROM wf_test_access_log "
            "WHERE experiment_id=?", (experiment_id,)).fetchone()
        uitgevoerd = _tel(db, "SELECT COUNT(*) FROM wf_results WHERE experiment_id=? AND kind='TEST'",
                          experiment_id) > 0
    else:
        totaal = _tel(db, "SELECT COUNT(*) FROM experiment_segments WHERE experiment_id=? "
                          "AND kind='TEST'", experiment_id)
        geopend = _tel(db, "SELECT COUNT(DISTINCT segment_id) FROM test_access_log "
                           "WHERE experiment_id=?", experiment_id)
        log = db.conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(data_reused),0), 0 FROM test_access_log "
            "WHERE experiment_id=?", (experiment_id,)).fetchone()
        uitgevoerd = totaal > 0 and exp.status == "completed"
    return _check("TestStatus", {
        "experiment_id": experiment_id,
        "test_exists": totaal > 0,
        "test_executed": bool(uitgevoerd),
        "test_opened": geopend > 0,
        "prior_access_count": int(log[0]),
        "data_reused": bool(log[1]),
        "overlapping_test_data": int(log[2]) > 0,
        "hypothesis_family_id": exp.hypothesis_family_id,
        "test_windows": totaal,
        "test_windows_opened": geopend,
        "test_windows_unopened": max(totaal - geopend, 0),
    })


# --------------------------------------------------------------- datasets --

def dataset_list(db, limit: int = 100) -> list[dict]:
    return [_check("DatasetListItem", {
        "id": r["id"], "symbol": r["symbol"], "timeframe": r["timeframe"],
        "start_ts": r["start_ts"], "end_ts": r["end_ts"], "bar_count": r["bar_count"],
        "quality_status": r["quality_status"], "created_at": r["created_at"],
    }) for r in db.conn.execute(
        "SELECT id, symbol, timeframe, start_ts, end_ts, bar_count, quality_status, created_at "
        "FROM datasets ORDER BY id DESC LIMIT ?", (int(limit),))]


def dataset_detail(db, dataset_id: int) -> dict:
    ds = db.dataset(dataset_id)
    if ds is None:
        raise ReadModelError("dataset_not_found", dataset_id)
    bevindingen = [{
        "code": f.get("code"), "label": QUALITY_LABELS.get(f.get("code"), f.get("code")),
        "severity": f.get("severity"), "count": f.get("count"), "detail": f.get("detail"),
        "examples": list(f.get("examples") or []),
    } for f in ds.get("quality") or []]
    verzoeken = [{"requested_at": r["requested_at"], "origin": r["origin"], "reused": bool(r["reused"])}
                 for r in db.conn.execute(
                     "SELECT requested_at, origin, reused FROM dataset_requests WHERE dataset_id=? "
                     "ORDER BY id DESC LIMIT 20", (dataset_id,))]
    return _check("DatasetDetail", {
        "id": ds["id"], "hash": ds["hash"], "hash_version": ds["hash_version"],
        "symbol": ds["symbol"], "timeframe": ds["timeframe"], "start_ts": ds["start_ts"],
        "end_ts": ds["end_ts"], "bar_count": ds["bar_count"], "source": ds["source"],
        "precision": ds["instrument_precision"], "precision_origin": ds["precision_origin"],
        "quality_status": ds["quality_status"], "findings": bevindingen,
        "created_at": ds["created_at"], "requests": verzoeken,
    })


# ------------------------------------------------------------ beoordeling --

def assessment_list(db, limit: int = 100) -> list[dict]:
    return [_check("AssessmentListItem", {
        "id": r["id"], "experiment_id": r["experiment_id"], "status": r["status"],
        "final_classification": r["final_classification"], "data_reused": bool(r["data_reused"]),
        "created_at": r["created_at"],
    }) for r in db.conn.execute(
        "SELECT id, experiment_id, status, final_classification, data_reused, created_at "
        "FROM assessments ORDER BY id DESC LIMIT ?", (int(limit),))]


def assessment_detail(db, assessment_id: int) -> dict:
    a = db.assessment(assessment_id)
    if a is None:
        raise ReadModelError("assessment_not_found", assessment_id)
    componenten, blokkades, waarschuwingen, drempels = [], [], [], {}
    for code, c in (a.get("components") or {}).items():
        componenten.append({
            "code": code, "status": c.get("status"), "measured_value": c.get("measured_value"),
            "unit": c.get("unit"), "sample_size": c.get("sample_size"),
            "required_condition": c.get("required_condition"), "blocking": bool(c.get("blocking")),
            "explanation": c.get("explanation"),
            "source_window_ids": _json(c.get("source_window_ids_json"), []),
        })
        drempels[code] = c.get("required_condition")
        if c.get("blocking") and c.get("status") not in ("PASS", "NOT_APPLICABLE"):
            blokkades.append(f"{code}: {c.get('explanation')}")
        elif c.get("status") in ("WARNING", "WARN"):
            waarschuwingen.append(f"{code}: {c.get('explanation')}")
    invoer = _json(a.get("input_json"), {})
    trace = _json(a.get("trace_json"), [])
    if a.get("data_reused"):
        waarschuwingen.append("TEST-data eerder geopend (DATA_REUSED): geen onafhankelijke toets.")
    if a.get("overlapping_test_data"):
        waarschuwingen.append("TEST-periode overlapt eerdere toegang (OVERLAPPING_TEST_DATA).")
    return _check("AssessmentDetail", {
        "id": a["id"], "experiment_id": a["experiment_id"], "status": a["status"],
        "raw_classification": a["raw_classification"],
        "classification_ceiling": a["classification_ceiling"],
        "fidelity_ceiling": a["fidelity_ceiling"],
        "final_classification": a["final_classification"],
        "explanation": a["classification_explanation"],
        "components": componenten,
        "blocking_reasons": blokkades,
        "warnings": waarschuwingen,
        "test_independence": "REUSED" if a.get("data_reused") else "INDEPENDENT",
        "data_reused": bool(a.get("data_reused")),
        "overlapping_test_data": bool(a.get("overlapping_test_data")),
        "thresholds": drempels,
        "rules_version": a["assessment_rules_version"],
        "schema_version": a["assessment_schema_version"],
        "input_versions": _json(a.get("versions_json"), {}),
        "sources": {"dataset_id": a["dataset_id"], "dataset_hash": a["dataset_hash"],
                    "candidate_set_hash": invoer.get("candidate_set_hash"),
                    "access_log_ids": list(invoer.get("access_log_ids") or [])},
        "trace": trace if isinstance(trace, list) else [],
        "error": _veilige_fout(a.get("error")),
        "created_at": a["created_at"], "completed_at": a["completed_at"],
        "disclaimer": DISCLAIMER,
    })


# ------------------------------------------------------------ vergelijking --

def comparison_list(db, limit: int = 100) -> list[dict]:
    return [_check("ComparisonListItem", {
        "id": r["id"], "mode": r["mode"], "status": r["status"],
        "comparability_status": r["comparability_status"],
        "reference_experiment_id": r["reference_experiment_id"],
        "challenger_experiment_id": r["challenger_experiment_id"],
        "result": r["result"], "created_at": r["created_at"],
    }) for r in db.conn.execute(
        "SELECT id, mode, status, comparability_status, reference_experiment_id, "
        "challenger_experiment_id, result, created_at FROM comparisons ORDER BY id DESC LIMIT ?",
        (int(limit),))]


METRIC_SECTIONS = ("metrics", "metric", "results")


def comparison_detail(db, comparison_id: int) -> dict:
    c = db.comparison(comparison_id)
    if c is None:
        raise ReadModelError("comparison_not_found", comparison_id)
    secties: dict[str, list] = {}
    deltas = []
    for it in c.get("items") or []:
        rij = {"key": it.get("item_key"), "reference": it.get("reference"),
               "challenger": it.get("challenger"), "absolute_delta": it.get("absolute_delta"),
               "relative_delta": it.get("relative_delta"), "status": it.get("status"),
               "explanation": it.get("explanation")}
        sectie = it.get("section") or "overig"
        if sectie.lower() in METRIC_SECTIONS:
            deltas.append(rij)
        else:
            secties.setdefault(sectie, []).append(rij)
    checks = [{"code": code, "severity": ch.get("severity"), "reference": ch.get("reference"),
               "challenger": ch.get("challenger"), "status": ch.get("status")}
              for code, ch in (c.get("checks") or {}).items()]
    return _check("ComparisonDetail", {
        "id": c["id"], "mode": c["mode"], "status": c["status"],
        "comparability_status": c["comparability_status"],
        "comparability_reasons": _json(c.get("comparability_reasons_json"), []),
        "same_dataset": c["reference_dataset_hash"] == c["challenger_dataset_hash"],
        "reference": {"experiment_id": c["reference_experiment_id"],
                      "assessment_id": c["reference_assessment_id"],
                      "dataset_id": c["reference_dataset_id"]},
        "challenger": {"experiment_id": c["challenger_experiment_id"],
                       "assessment_id": c["challenger_assessment_id"],
                       "dataset_id": c["challenger_dataset_id"]},
        "checks": checks,
        "sections": secties,
        "metric_comparison_available": bool(deltas),
        "metric_deltas": deltas,
        "warnings": _json(c.get("flags_json"), []),
        "result": c["result"], "explanation": c.get("explanation"),
        "rules_version": c["comparison_rules_version"],
        "error": _veilige_fout(c.get("error")),
        "created_at": c["created_at"], "completed_at": c["completed_at"],
        "disclaimer": DISCLAIMER,
    })


# --------------------------------------------------------------- familie --

def family_summary(db, family_id: str) -> dict:
    f = db.family_summary(family_id)
    if not f or not f.get("registered_experiments") and not _tel(
            db, "SELECT COUNT(*) FROM experiments WHERE hypothesis_family_id=?", family_id):
        raise ReadModelError("family_not_found", family_id)
    return _check("FamilySummary", {
        "hypothesis_family_id": f.get("hypothesis_family_id", family_id),
        "registered_experiments": int(f.get("registered_experiments") or 0),
        "reproductions": int(f.get("reproductions") or 0),
        "unique_candidates": _tel(
            db, "SELECT COUNT(DISTINCT p.config_hash) FROM experiment_parameters p "
                "JOIN experiments e ON e.id = p.experiment_id "
                "WHERE e.hypothesis_family_id=? AND p.role='candidate'", family_id),
        "train_runs": int(f.get("train_runs") or 0),
        "unique_evaluated_configurations": int(f.get("evaluated_configurations") or 0),
        "test_executions": int(f.get("test_executions") or 0),
        "test_accesses": int(f.get("test_accesses") or 0),
        "data_reused_count": int(f.get("reused_test_accesses") or 0),
        "overlapping_test_count": int(f.get("overlapping_test_accesses") or 0),
        "first_test_access": f.get("first_test_access"),
        "last_test_access": f.get("last_test_access"),
    })


def lab_schema_expected() -> int:
    return LAB_SCHEMA_VERSION
