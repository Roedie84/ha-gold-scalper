"""Uitvoering van een walk-forward: venster na venster, kandidaat na kandidaat.

Elke eenheid - één kandidaat op één segment - draait in een eigen werkproces
(dezelfde isolatie als fase 3) en wordt in een eigen transactie opgeslagen. De
volgorde per venster ligt vast en wordt ook door de database afgedwongen:

1. TRAIN voor alle vooraf geregistreerde kandidaten;
2. de vooraf vastgelegde selectieregel, uitsluitend op TRAIN-metrieken;
3. de selectie onveranderlijk vastleggen;
4. bij TRAIN_THEN_VALIDATION: alleen de gekozen kandidaat op VALIDATION, dan
   de beslissing - bij FAILED geen andere kandidaat;
5. alleen de gekozen kandidaat op TEST, verzegeld opgeslagen.

Bij ``SEQUENTIAL_OOS``: alleen stap 5, met de ene configuratie.

Eén werkproces tegelijk, alles na elkaar. Faalt één venster, dan faalt het hele
experiment; er wordt nooit een alternatieve kandidaat gekozen. Wat al veilig is
opgeslagen, blijft als diagnose bewaard. Hervatten bestaat niet.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from pathlib import Path

from .metrics import check_invariants
from .models import Status, canonical_json, config_hash
from .runner import (
    ExperimentRunner, RunHandle, RunRefused, RunnerBusy, MAX_QUEUED, _beeindig, _pad,
)
from .storage import LabDatabase
from .walk_forward import (
    CANDIDATE_SELECTION, NO_SELECTION, TRAIN_THEN_VALIDATION, SelectionRule,
    FAILED as VALIDATIE_MISLUKT, select, validation_decision,
)
from .worker import RunRequest


class _Einde(Exception):
    """Een eenheid eindigde niet voltooid: annuleren, fout of onderbreking."""

    def __init__(self, status: str, reden: str) -> None:
        super().__init__(reden)
        self.status, self.reden = status, reden


def _regel(plan: dict) -> SelectionRule:
    r = json.loads(plan["selection_rule_json"])
    return SelectionRule(
        primary_metric=r["primary_metric"], direction=r["direction"],
        tie_break=tuple(t if isinstance(t, str) else tuple(t) for t in r["tie_break"]),
        validation_policy=r["validation_policy"],
        missing_metric_policy=r["missing_metric_policy"],
        minimum_required_status=r["minimum_required_status"],
        validation_condition=r["validation_condition"],
    )


class WalkForwardRunner(ExperimentRunner):
    """Start en bewaakt één walk-forwardexperiment tegelijk."""

    def submit_walk_forward(self, experiment_id: int) -> RunHandle:
        with self._lock:
            if self._actief is not None and not self._actief.done:
                raise RunnerBusy("er loopt al een experiment in deze runner")
            db = LabDatabase(self.lab_db_path).open()
            try:
                exp = db.get(experiment_id)
                plan = db.wf_plan(experiment_id)
                if exp is None or plan is None:
                    raise RunRefused("geen walk-forwardexperiment")
                if exp.status != Status.REGISTERED.value:
                    raise RunRefused(f"experiment staat op {exp.status}, niet op registered")
                ds = db.dataset(exp.dataset_id)
                if ds is None or not db.verify_dataset(exp.dataset_id)["ok"]:
                    raise RunRefused("de dataset ontbreekt of klopt niet met zichzelf")
                if ds["quality_status"] == "BLOCKED":
                    raise RunRefused("de dataset is BLOCKED")
                for k in plan["candidates"]:
                    houd = (json.loads(k["config_json"]).get("exits") or {}).get("max_hold_seconds", 900)
                    if houd > plan["max_hold_seconds"]:
                        raise RunRefused(f"kandidaat {k['candidate_label']}: houdtijd langer dan het plan")
                if db.conn.execute("SELECT COUNT(*) FROM experiments WHERE status='running'").fetchone()[0]:
                    raise RunnerBusy("er loopt al een experiment in deze Lab-database")
                if db.conn.execute("SELECT COUNT(*) FROM experiments WHERE status='queued'").fetchone()[0] >= MAX_QUEUED:
                    raise RunRefused("de wachtrij is vol")
                db.transition(experiment_id, Status.QUEUED)
                db.begin_run(experiment_id, executor="process")
            finally:
                db.close()
            handle = RunHandle(experiment_id)
            self._actief = handle
        threading.Thread(target=self._wf_uitvoeren, args=(handle, experiment_id),
                         name=f"gold-scalper-wf-{experiment_id}", daemon=True).start()
        return handle

    # ------------------------------------------------------------------ #

    def _wf_uitvoeren(self, handle: RunHandle, eid: int) -> None:
        db = LabDatabase(self.lab_db_path).open()
        try:
            plan = db.wf_plan(eid)
            exp = db.get(eid)
            ds_hash = plan["dataset_hash"]
            regel = _regel(plan)
            kandidaten = plan["candidates"]
            selectie = plan["mode"] == CANDIDATE_SELECTION
            per_venster = (len(kandidaten) + (1 if regel.validation_policy == TRAIN_THEN_VALIDATION
                                              else 0) + 1) if selectie else 1
            totaal = per_venster * len(plan["windows"])
            teller = {"eenheid": 0, "vensters": 0}
            t_start = time.monotonic()
            handle.timings = []                                     # type: ignore[attr-defined]

            def eenheid(venster, soort, kandidaat):
                if handle._stop.is_set():
                    raise _Einde("cancelled", "geannuleerd tussen twee eenheden")
                seg = dict(venster["segments"][soort])
                seg["max_hold_seconds"] = plan["max_hold_seconds"]
                config = json.loads(kandidaat["config_json"])
                request = RunRequest(eid, exp.dataset_id, ds_hash, self.lab_db_path, config,
                                     config_hash(config), single_segment=seg)
                nr = teller["eenheid"]

                def voortgang(bericht):
                    deel = bericht["done"] / bericht["total"] if bericht.get("total") else 0
                    db.update_wf_progress(
                        eid, pct=(nr + min(1.0, deel)) / totaal * 100,
                        windows_total=len(plan["windows"]), windows_completed=teller["vensters"],
                        current_window=venster["window_index"], candidates_total=len(kandidaten),
                        current_candidate=kandidaat["candidate_label"], segment=soort)

                t0 = time.monotonic()
                proces = subprocess.Popen(
                    self._worker_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, bufsize=1,
                    env={"PATH": _pad()}, cwd=str(Path(self.lab_db_path).parent))
                try:
                    proces.stdin.write(json.dumps(request.as_dict()) + "\n")
                    proces.stdin.flush()
                    status, reden, resultaat = self._volg(handle, proces, db, request,
                                                          bij_voortgang=voortgang)
                finally:
                    _beeindig(proces)
                if status != "completed":
                    raise _Einde(status, reden or status)
                self._controleer_eenheid(resultaat, request, seg)
                rid = db.store_wf_result(venster["id"], soort, kandidaat["id"], resultaat)
                handle.timings.append({"window": venster["window_index"], "kind": soort,  # type: ignore[attr-defined]
                                       "candidate": kandidaat["candidate_label"],
                                       "seconds": round(time.monotonic() - t0, 2),
                                       "bars": resultaat["segment"]["bars_in_slice"],
                                       "payload_bytes": len(json.dumps(resultaat))})
                teller["eenheid"] += 1
                return rid

            for venster in plan["windows"]:
                wid = venster["id"]
                if selectie:
                    db.set_window_status(wid, "TRAINING")
                    for k in kandidaten:
                        eenheid(venster, "TRAIN", k)
                    db.set_window_status(wid, "SELECTING")
                    train = db.wf_train_metrics(wid)
                    sleutels = {str(k["id"]): (k["id"], k["config_hash"]) for k in kandidaten}
                    keuze = select(regel, {str(c): v["metrics"] for c, v in train.items()},
                                   {s: h for s, (_, h) in sleutels.items()})
                    db.store_selection(wid, keuze, regel, sleutels, train)
                    if keuze.status == NO_SELECTION:
                        db.set_window_status(wid, "NO_SELECTION", keuze.reason)
                        teller["eenheid"] += per_venster - len(kandidaten)
                        teller["vensters"] += 1
                        continue
                    gekozen = next(k for k in kandidaten if str(k["id"]) == keuze.selected)
                    if regel.validation_policy == TRAIN_THEN_VALIDATION:
                        db.set_window_status(wid, "VALIDATING")
                        eenheid(venster, "VALIDATION", gekozen)
                        besluit, reden = validation_decision(regel, db.wf_validation_metrics(wid))
                        db.store_validation_decision(wid, besluit, reden)
                        if besluit == VALIDATIE_MISLUKT:
                            db.set_window_status(wid, "VALIDATION_REJECTED", reden)
                            teller["eenheid"] += 1
                            teller["vensters"] += 1
                            continue
                else:
                    gekozen = kandidaten[0]
                db.set_window_status(wid, "TESTING")
                eenheid(venster, "TEST", gekozen)
                db.set_window_status(wid, "COMPLETED")
                teller["vensters"] += 1

            def afronden():
                db.conn.execute(
                    "UPDATE experiment_runs SET progress_pct = 100, windows_completed = ?, "
                    "current_window = NULL, current_candidate = NULL, current_segment = NULL, "
                    "finished_at = datetime('now') WHERE experiment_id = ?",
                    (len(plan["windows"]), eid))
                db.transition(eid, Status.COMPLETED)
            db._in_transactie(afronden)
            handle.final_status = "completed"
            handle.total_seconds = round(time.monotonic() - t_start, 2)  # type: ignore[attr-defined]
        except _Einde as einde:
            status, reden = handle.eind_status(einde.status, einde.reden)
            handle.final_status, handle.error = status, reden
            self._beeindig_experiment(db, eid, status, reden)
        except Exception as err:  # noqa: BLE001 - een fout in het Lab blijft in het Lab
            handle.final_status, handle.error = "failed", f"{type(err).__name__}: {err}"
            self._beeindig_experiment(db, eid, "failed", handle.error)
        finally:
            handle.stopped_at = time.monotonic()
            db.close()
            handle._klaar.set()

    @staticmethod
    def _beeindig_experiment(db, eid: int, status: str, reden: str) -> None:
        try:
            exp = db.get(eid)
            if exp is not None and exp.status in ("queued", "running"):
                db.end_run(eid, Status(status), reden)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _controleer_eenheid(resultaat: dict, request: RunRequest, seg: dict) -> None:
        """Onafhankelijke controle van één eenheid tegen het vergrendelde segment."""
        s = resultaat.get("segment") or {}
        herberekend = hashlib.sha256(canonical_json(
            {"summary": s["summary"], "trades": s["trades"]}).encode("utf-8")).hexdigest()
        if herberekend != s.get("result_hash") or resultaat.get("result_hash") != herberekend:
            raise ValueError("resultaathash klopt niet")
        herkomst = resultaat.get("provenance", {})
        if herkomst.get("dataset_hash") != request.dataset_hash or \
                herkomst.get("config_hash") != request.config_hash:
            raise ValueError("resultaat hoort bij andere data of configuratie")
        if s.get("kind") != seg["kind"]:
            raise ValueError("resultaat hoort bij een ander segment")
        for t in s["trades"]:
            if not seg["start_ts"] <= t["opened_ts"] < seg["open_cutoff_ts"] or t["closed_ts"] >= seg["end_ts"]:
                raise ValueError(f"{seg['kind']}: trade buiten het segment")
        fouten = check_invariants(s["trades"], s["metrics"], s["breakdowns"])
        if fouten:
            raise ValueError("invarianten geschonden: " + "; ".join(fouten[:3]))
