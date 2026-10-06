"""Acties op het Experiment Lab, zonder Home Assistant (5.7).

**EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING**

Elke actie roept uitsluitend bestaande Lab-logica aan: snapshot, registratie,
walk-forwardrunner, beoordeling, vergelijking. Hier staat geen tweede versie
van die regels - alleen invoercontrole, idempotentie en een leesbaar antwoord.

Wat deze module nooit doet: een config entry, de actieve strategie, de broker,
de modus, de live-gate of risico-instellingen raken; een order plaatsen; een
bestandspad aannemen; een pad, geheim of traceback teruggeven.

Elk antwoord heeft dezelfde vorm::

    {"ok": bool, "action": str, "object_id": int | None, "replayed": bool,
     "message": str, "data": {...}}            # bij succes
    {"ok": False, "action": str, "object_id": ..., "replayed": False,
     "message": str, "error": {"code", "message", "object_id"}}

``message`` is een korte Nederlandse samenvatting zonder databasekennis.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .const import EXECUTION_SEMANTICS_VERSION, INTEGRATION_VERSION, STRATEGY_WINDOW_BARS
from .experiment_lab import walk_forward as W
from .experiment_lab.models import Experiment, config_hash
from .experiment_lab.runner import RunRefused
from .experiment_lab.storage import LabDatabase
from .lab_read_models import DISCLAIMER, ReadModelError, assessment_detail, comparison_detail

ACTIONS = ("snapshot", "create_walk_forward", "register", "start", "cancel", "assess", "compare")
#: Toegestane velden per actie - ook het schema van de Home Assistant-dienst.
ACTION_FIELDS: dict[str, frozenset] = {
    "snapshot": frozenset({"symbol", "timeframe", "start", "end", "precision"}),
    "create_walk_forward": frozenset({
        "name", "description", "hypothesis", "expected_effect", "hypothesis_family_id",
        "dataset_id", "mode", "window_type", "first_train_start", "train_days",
        "validation_days", "test_days", "step_days", "window_count", "max_hold_seconds",
        "primary_metric", "selection_direction", "validation_condition", "candidates"}),
    "register": frozenset({"experiment_id"}),
    "start": frozenset({"experiment_id"}),
    "cancel": frozenset({"experiment_id"}),
    "assess": frozenset({"experiment_id"}),
    "compare": frozenset({"reference_experiment_id", "challenger_experiment_id", "mode",
                          "reference_assessment_id", "challenger_assessment_id",
                          "confirm_test_reuse"}),
}
IDEMPOTENT_ACTIONS = frozenset({"snapshot", "create_walk_forward", "register", "start",
                                "assess", "compare"})

#: Wat op een bestandspad lijkt, wordt geweigerd - ook als het een tekstveld is.
PAD = re.compile(r"(^\s*/|\\|\.\./|\.db\b|/config\b)")
REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{8,64}$")
#: Namen en labels: letters (ook met accenten), cijfers, spaties en
#: _ . , : / ( ) + - &. Geen aanhalingstekens of regeleinden.
NAAM = re.compile(r"^[\w ,.:/()+&-]{1,80}$")
NAAM_UITLEG = "hooguit 80 tekens: letters, cijfers, spaties en _ . , : / ( ) + - &"
SYMBOOL = re.compile(r"^[A-Z0-9._]{1,32}$")
#: Tijdvakken die het archief bijhoudt.
TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h")
ORIGIN = "home_assistant"
ACCESSOR = "home_assistant"
COMPARISON_MODES = ("ASSESSMENT_COMPARISON", "DEEP_RESULT_COMPARISON")
DAG = 86400


class LabActionError(Exception):
    """Een actie die niet kan. ``code`` is stabiel; ``message`` is voor mensen."""

    def __init__(self, code: str, message: str, object_id: int | str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.object_id = object_id


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def _veilig(tekst: str) -> str:
    """Eén regel, zonder pad."""
    regel = str(tekst).splitlines()[0] if tekst else ""
    if "/" in regel or "\\" in regel:
        regel = re.split(r"[/\\]", regel, 1)[0].rstrip(" :'\"(") + " (pad weggelaten)"
    return regel[:300]


def _ts(waarde, veld: str) -> int | None:
    if waarde in (None, ""):
        return None
    if isinstance(waarde, bool):
        raise LabActionError("invalid_parameter", f"{veld}: geen tijdstip")
    if isinstance(waarde, (int, float)):
        return int(waarde)
    try:
        moment = datetime.fromisoformat(str(waarde).replace("Z", "+00:00"))
    except ValueError as err:
        raise LabActionError("invalid_parameter", f"{veld}: geen geldig tijdstip") from err
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def _iso(ts: int | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(int(ts), timezone.utc).isoformat()


def _int(params: dict, veld: str, standaard=None, minimum=None, maximum=None) -> int | None:
    waarde = params.get(veld, standaard)
    if waarde is None:
        return None
    if isinstance(waarde, bool) or not isinstance(waarde, (int, float)) or int(waarde) != waarde:
        raise LabActionError("invalid_parameter", f"{veld}: geheel getal verwacht")
    waarde = int(waarde)
    if (minimum is not None and waarde < minimum) or (maximum is not None and waarde > maximum):
        raise LabActionError("invalid_parameter", f"{veld}: buiten het toegestane bereik")
    return waarde


def _tekst(params: dict, veld: str, verplicht=True, maximum=500) -> str:
    waarde = params.get(veld)
    if waarde in (None, ""):
        if verplicht:
            raise LabActionError("invalid_parameter", f"{veld} ontbreekt")
        return ""
    if not isinstance(waarde, str) or len(waarde) > maximum:
        raise LabActionError("invalid_parameter", f"{veld}: tekst van hooguit {maximum} tekens")
    return waarde.strip()


def _alleen(params: dict, toegestaan: set, actie: str) -> None:
    onbekend = set(params) - toegestaan - {"request_id"}
    if onbekend:
        raise LabActionError("unknown_parameter",
                             f"{actie}: onbekende parameter(s) {', '.join(sorted(onbekend))}")
    for sleutel, waarde in params.items():
        if isinstance(waarde, str) and PAD.search(waarde):
            raise LabActionError("path_not_allowed", f"{sleutel}: een pad is niet toegestaan")


class LabActions:
    """De zeven acties. Synchroon: Home Assistant roept ze in de executor aan."""

    def __init__(self, lab_path: str | Path, archive_path: str | Path | None, runner) -> None:
        self._lab_path = str(lab_path)
        self._archive_path = str(archive_path) if archive_path else None
        self._runner = runner
        self._starts_allowed = True

    # -- lifecycle ------------------------------------------------------ #

    def stop_accepting_starts(self) -> None:
        """Vanaf nu geen nieuwe start (unload)."""
        self._starts_allowed = False

    # -- toegang -------------------------------------------------------- #

    def run(self, action: str, params: dict) -> dict:
        """Voer een actie uit en geef altijd een antwoord, nooit een uitzondering."""
        if action not in ACTIONS:
            return self._fout(action, LabActionError("unknown_action", f"onbekende actie {action}"))
        params = dict(params or {})
        request_id = params.get("request_id")
        db = LabDatabase(self._lab_path).open()
        try:
            if request_id is not None:
                if action not in IDEMPOTENT_ACTIONS:
                    raise LabActionError("request_id_not_supported",
                                         f"{action} kent geen request_id")
                if not isinstance(request_id, str) or not REQUEST_ID.match(request_id):
                    raise LabActionError("invalid_request_id",
                                         "request_id: 8 tot 64 tekens, letters, cijfers, _ . : -")
                payload = {k: v for k, v in params.items() if k != "request_id"}
                eerder = db.request_lookup(request_id)
                if eerder is not None:
                    if eerder["action"] != action or eerder["payload_hash"] != _hash(payload):
                        raise LabActionError(
                            "request_id_conflict",
                            "deze request_id is al gebruikt voor een andere actie of andere invoer",
                            eerder["object_id"])
                    antwoord = json.loads(eerder["response"])
                    antwoord["replayed"] = True
                    return antwoord
            antwoord = getattr(self, f"_{action}")(db, params)
            antwoord = {"ok": True, "action": action, "replayed": False, **antwoord}
            if request_id is not None:
                db.request_store(request_id, action,
                                 _hash({k: v for k, v in params.items() if k != "request_id"}),
                                 antwoord.get("object_id"), json.dumps(antwoord, default=str))
            return antwoord
        except LabActionError as err:
            return self._fout(action, err)
        except ReadModelError as err:
            return self._fout(action, LabActionError(err.code, err.code.replace("_", " "),
                                                     err.object_id))
        except (W.WalkForwardError, RunRefused, ValueError) as err:
            return self._fout(action, LabActionError("rejected", _veilig(err),
                                                     params.get("experiment_id")))
        except Exception as err:  # noqa: BLE001 - nooit een traceback naar buiten
            return self._fout(action, LabActionError(
                "internal_error", f"{type(err).__name__}: {_veilig(err)}",
                params.get("experiment_id")))
        finally:
            db.close()

    @staticmethod
    def _fout(action: str, err: LabActionError) -> dict:
        return {"ok": False, "action": action, "object_id": err.object_id, "replayed": False,
                "message": f"Niet gelukt ({err.code}): {err.message}",
                "error": {"code": err.code, "message": err.message, "object_id": err.object_id}}

    # -- A: snapshot ---------------------------------------------------- #

    def _snapshot(self, db, p: dict) -> dict:
        from .experiment_lab.datasets import prepare
        from .lab_bridge import ArchiveReader, dataset_spec, market_windows

        _alleen(p, ACTION_FIELDS["snapshot"], "snapshot")
        symbool = _tekst(p, "symbol", maximum=32).upper()
        if not SYMBOOL.match(symbool):
            raise LabActionError("invalid_parameter", "symbol: alleen hoofdletters, cijfers, . en _")
        tijdvak = _tekst(p, "timeframe", maximum=4)
        if tijdvak not in TIMEFRAMES:
            raise LabActionError("invalid_parameter", f"timeframe: een van {', '.join(TIMEFRAMES)}")
        start, einde = _ts(p.get("start"), "start"), _ts(p.get("end"), "end")
        if start is not None and einde is not None and einde <= start:
            raise LabActionError("invalid_parameter", "end ligt niet na start")
        precisie = _int(p, "precision", None, 0, 6)
        if not self._archive_path or not Path(self._archive_path).exists():
            raise LabActionError("archive_unavailable", "het barsarchief is niet beschikbaar")
        nu = int(time.time())
        lezer = ArchiveReader(self._archive_path)
        try:
            bars = list(lezer.read_bars(symbool, tijdvak, nu, start, einde))
        finally:
            lezer.close()
        if not bars:
            raise LabActionError("no_bars", "geen bars in het archief voor deze selectie")
        vensters = list(market_windows(bars[0].ts, bars[-1].ts, tijdvak))
        voorbereid = prepare(dataset_spec(symbool, tijdvak, precisie), bars, vensters, nu)
        ds_id, hergebruikt = db.create_snapshot(voorbereid, ORIGIN)
        ds = db.dataset(ds_id)
        bevindingen = [f"{f.get('code')} ({f.get('count')})" for f in ds.get("quality") or []]
        data = {
            "dataset_id": ds_id, "reused": bool(hergebruikt), "symbol": ds["symbol"],
            "timeframe": ds["timeframe"], "start": _iso(ds["start_ts"]), "end": _iso(ds["end_ts"]),
            "bar_count": ds["bar_count"], "dataset_hash": ds["hash"],
            "quality_status": ds["quality_status"], "quality_findings": bevindingen,
            "precision_origin": ds["precision_origin"],
        }
        regels = [
            f"Dataset {ds_id} {'hergebruikt' if hergebruikt else 'aangemaakt'}.",
            f"{ds['symbol']} {ds['timeframe']}, {ds['bar_count']} bars",
            f"Van {data['start']} tot {data['end']}",
            f"Kwaliteit: {ds['quality_status']}"
            + (f" ({'; '.join(bevindingen[:4])})" if bevindingen else ""),
        ]
        if ds["quality_status"] == "BLOCKED":
            regels.append("BLOCKED: opgeslagen als onderzoeksgegeven, niet te gebruiken voor een run.")
        return {"object_id": ds_id, "message": "\n".join(regels), "data": data}

    # -- concept walk-forward ------------------------------------------- #

    def _create_walk_forward(self, db, p: dict) -> dict:
        from .experiment_lab.worker import RunError, build_configs

        _alleen(p, ACTION_FIELDS["create_walk_forward"], "create_walk_forward")
        naam = _tekst(p, "name", maximum=80)
        if not NAAM.match(naam):
            raise LabActionError("invalid_parameter", f"name: {NAAM_UITLEG}")
        familie = _tekst(p, "hypothesis_family_id", maximum=80)
        ds_id = _int(p, "dataset_id", minimum=1)
        ds = db.dataset(ds_id)
        if ds is None:
            raise LabActionError("dataset_not_found", f"dataset {ds_id} bestaat niet", ds_id)
        modus = p.get("mode", W.CANDIDATE_SELECTION)
        if modus not in W.MODES:
            raise LabActionError("invalid_parameter", f"mode: een van {', '.join(W.MODES)}")
        venster = p.get("window_type", W.ROLLING)
        kandidaten = p.get("candidates")
        if not isinstance(kandidaten, list) or not kandidaten or len(kandidaten) > 20:
            raise LabActionError("invalid_parameter", "candidates: lijst van 1 tot 20 kandidaten")
        if modus == W.SEQUENTIAL_OOS and len(kandidaten) != 1:
            raise LabActionError("invalid_parameter", "SEQUENTIAL_OOS heeft precies één kandidaat")
        labels = set()
        for k in kandidaten:
            if not isinstance(k, dict) or set(k) - {"label", "config"} or "label" not in k:
                raise LabActionError("invalid_parameter", "kandidaat: {label, config}")
            if not isinstance(k["label"], str) or not NAAM.match(k["label"]) or k["label"] in labels:
                raise LabActionError("invalid_parameter", f"kandidaatlabel moet uniek zijn, {NAAM_UITLEG}")
            labels.add(k["label"])
            try:
                build_configs(k.get("config") or {})
            except (RunError, TypeError) as err:
                raise LabActionError("invalid_config", f"{k['label']}: {_veilig(err)}") from err
        dag = DAG
        train = _int(p, "train_days", None, 1, 365)
        test = _int(p, "test_days", None, 1, 365)
        if train is None or test is None:
            raise LabActionError("invalid_parameter", "train_days en test_days zijn verplicht")
        val = _int(p, "validation_days", 0, 0, 365)
        stap = _int(p, "step_days", test + val, 1, 365)
        aantal = _int(p, "window_count", None, 1, 52)
        if aantal is None:
            raise LabActionError("invalid_parameter", "window_count is verplicht")
        houd = _int(p, "max_hold_seconds", 900, 60, 7 * dag)
        voorwaarde = p.get("validation_condition")
        if val and not isinstance(voorwaarde, dict):
            raise LabActionError("invalid_parameter",
                                 "validation_days > 0 vraagt een validation_condition "
                                 "{metric, operator, threshold}")
        regel = W.SelectionRule(
            p.get("primary_metric", "net_pnl"), p.get("selection_direction", W.MAXIMIZE),
            tie_break=((("maximum_drawdown", W.MINIMIZE),) if modus == W.CANDIDATE_SELECTION else ())
            + (W.CONFIG_HASH_TIEBREAK,),
            validation_policy=W.TRAIN_THEN_VALIDATION if val else W.TRAIN_ONLY,
            validation_condition=voorwaarde if val else None)
        regel.check()
        bar_ts = [b.ts for b in db.dataset_bars(ds_id)]
        bar_s = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}.get(ds["timeframe"])
        if bar_s is None or len(bar_ts) <= STRATEGY_WINDOW_BARS:
            raise LabActionError("dataset_too_short",
                                 f"dataset heeft minder dan {STRATEGY_WINDOW_BARS} opwarmbars", ds_id)
        eerste = _ts(p.get("first_train_start"), "first_train_start") or bar_ts[STRATEGY_WINDOW_BARS]
        args = dict(first_train_start=eerste, train_length=train * dag, validation_length=val * dag,
                    test_length=test * dag, step_size=stap * dag, window_count=aantal,
                    max_hold_seconds=houd)
        ramen = W.build_windows(modus, venster, bar_ts, bar_s, **args)
        from .strategy.scalping import STRATEGY_VERSION

        eid = db.create(Experiment(
            name=naam, description=_tekst(p, "description", verplicht=False),
            type="walk_forward", hypothesis=_tekst(p, "hypothesis"),
            expected_effect=_tekst(p, "expected_effect"),
            primary_metric=regel.primary_metric, evaluation_method="walk-forward",
            hypothesis_family_id=familie, software_version=INTEGRATION_VERSION,
            strategy_version=STRATEGY_VERSION,
            execution_semantics_version=EXECUTION_SEMANTICS_VERSION,
            config_hash=config_hash({"kandidaten": sorted(labels)}), dataset_id=ds_id))
        ids = [(k["label"], db.add_parameters(eid, "candidate", k.get("config") or {}))
               for k in kandidaten]
        db.save_walk_forward(eid, mode=modus, window_type=venster, windows=ramen, rule=regel,
                             bar_seconds=bar_s, candidates=ids,
                             **{k: v for k, v in args.items() if k != "window_count"})
        plan = db.wf_plan(eid)
        data = {"experiment_id": eid, "status": "draft", "hypothesis_family_id": familie,
                "dataset_id": ds_id, "windows": len(ramen), "candidates": len(ids),
                "mode": modus, "window_type": venster, "candidate_set_hash": plan["candidate_set_hash"]}
        return {"object_id": eid, "data": data, "message": "\n".join([
            f"Experiment {eid} aangemaakt als concept.",
            f"Dataset: {ds['symbol']} {ds['timeframe']} (dataset {ds_id})",
            f"Vensters: {len(ramen)}", f"Kandidaten: {len(ids)}", f"Plan: {modus} / {venster}",
            "Volgende stap: registreren."])}

    # -- B: registreren ------------------------------------------------- #

    def _register(self, db, p: dict) -> dict:
        _alleen(p, ACTION_FIELDS["register"], "register")
        eid = _int(p, "experiment_id", minimum=1)
        exp = db.get(eid)
        if exp is None:
            raise LabActionError("experiment_not_found", f"experiment {eid} bestaat niet", eid)
        if exp.status != "draft":
            raise LabActionError("invalid_state", f"experiment staat op {exp.status}, niet op draft", eid)
        plan = db.wf_plan(eid)
        if plan is None:
            raise LabActionError("not_walk_forward", "geen walk-forwardexperiment", eid)
        db.transition(eid, "registered")
        ds = db.dataset(exp.dataset_id)
        data = {"experiment_id": eid, "status": "registered",
                "hypothesis_family_id": exp.hypothesis_family_id,
                "dataset": {"id": ds["id"], "symbol": ds["symbol"], "timeframe": ds["timeframe"],
                            "hash": ds["hash"], "quality_status": ds["quality_status"]},
                "windows": plan["window_count"], "candidates": len(plan["candidates"]),
                "mode": plan["mode"], "window_type": plan["window_type"],
                "plan_hash": _hash({k: plan[k] for k in sorted(plan) if k != "candidates"}),
                "candidate_set_hash": plan["candidate_set_hash"]}
        return {"object_id": eid, "data": data, "message": "\n".join([
            f"Experiment {eid} geregistreerd.",
            f"Dataset: {ds['symbol']} {ds['timeframe']}",
            f"Vensters: {plan['window_count']}", f"Kandidaten: {len(plan['candidates'])}",
            "Status: registered", f"Plan: {plan['window_type'].lower()}",
            "TEST blijft verzegeld."])}

    # -- C: starten ----------------------------------------------------- #

    def _start(self, db, p: dict) -> dict:
        _alleen(p, ACTION_FIELDS["start"], "start")
        eid = _int(p, "experiment_id", minimum=1)
        if not self._starts_allowed:
            raise LabActionError("lab_unloading", "het Lab wordt afgemeld; geen nieuwe start", eid)
        exp = db.get(eid)
        if exp is None:
            raise LabActionError("experiment_not_found", f"experiment {eid} bestaat niet", eid)
        plan = db.wf_plan(eid)
        if plan is None:
            raise LabActionError("not_walk_forward", "geen walk-forwardexperiment", eid)
        try:
            self._runner.submit_walk_forward(eid)
        except RunRefused as err:
            raise LabActionError("start_refused", _veilig(err), eid) from err
        data = {"experiment_id": eid, "status": "running", "windows": plan["window_count"],
                "candidates": len(plan["candidates"]), "progress_started": True}
        return {"object_id": eid, "data": data, "message": "\n".join([
            f"Experiment {eid} gestart.", f"Vensters: {plan['window_count']}",
            f"Kandidaten: {len(plan['candidates'])}",
            "Voortgang volgt als melding; de actie wacht niet op het einde."])}

    # -- D: annuleren --------------------------------------------------- #

    def _cancel(self, db, p: dict) -> dict:
        _alleen(p, ACTION_FIELDS["cancel"], "cancel")
        eid = _int(p, "experiment_id", minimum=1)
        exp = db.get(eid)
        if exp is None:
            raise LabActionError("experiment_not_found", f"experiment {eid} bestaat niet", eid)
        oud = exp.status
        actief = self._runner.active
        worker = actief is not None and actief.experiment_id == eid
        if worker:
            actief.cancel()
            actief.wait(30)
        elif oud in ("draft", "registered", "queued"):
            db.transition(eid, "cancelled", "geannuleerd vanuit Home Assistant")
        elif oud == "running":
            raise LabActionError("not_owned", "het experiment loopt niet in deze runner", eid)
        else:
            raise LabActionError("invalid_state", f"experiment staat al op {oud}", eid)
        nieuw = db.get(eid).status
        return {"object_id": eid, "data": {"experiment_id": eid, "old_status": oud,
                                           "new_status": nieuw, "active_worker": worker},
                "message": f"Experiment {eid}: {oud} -> {nieuw}."
                + (" Werkproces gestopt." if worker else "")}

    # -- E: beoordelen -------------------------------------------------- #

    def _assess(self, db, p: dict) -> dict:
        _alleen(p, ACTION_FIELDS["assess"], "assess")
        eid = _int(p, "experiment_id", minimum=1)
        exp = db.get(eid)
        if exp is None:
            raise LabActionError("experiment_not_found", f"experiment {eid} bestaat niet", eid)
        if exp.status != "completed":
            raise LabActionError("invalid_state", f"experiment staat op {exp.status}, niet completed", eid)
        aid = db.create_assessment(eid, ACCESSOR)
        a = assessment_detail(db, aid)
        data = {k: a[k] for k in ("raw_classification", "fidelity_ceiling", "final_classification",
                                  "blocking_reasons", "warnings", "test_independence",
                                  "data_reused", "rules_version", "status")}
        data.update(assessment_id=aid, experiment_id=eid, disclaimer=DISCLAIMER)
        return {"object_id": aid, "data": data, "message": "\n".join([
            f"Beoordeling {aid} voor experiment {eid}: {a['final_classification']}.",
            f"Ruw: {a['raw_classification']}; plafond getrouwheid: {a['fidelity_ceiling']}.",
            f"TEST: {a['test_independence']}"
            + (" (DATA_REUSED)" if a["data_reused"] else ""),
            *(f"Blokkade: {b}" for b in a["blocking_reasons"][:3]),
            DISCLAIMER])}

    # -- F: vergelijken ------------------------------------------------- #

    def _compare(self, db, p: dict) -> dict:
        _alleen(p, ACTION_FIELDS["compare"], "compare")
        ref = _int(p, "reference_experiment_id", minimum=1)
        uit = _int(p, "challenger_experiment_id", minimum=1)
        modus = p.get("mode", "ASSESSMENT_COMPARISON")
        if modus not in COMPARISON_MODES:
            raise LabActionError("invalid_parameter", f"mode: een van {', '.join(COMPARISON_MODES)}")
        if modus == "DEEP_RESULT_COMPARISON" and p.get("confirm_test_reuse") is not True:
            raise LabActionError(
                "confirmation_required",
                "DEEP_RESULT_COMPARISON opent TEST opnieuw en telt als hergebruik "
                "(DATA_REUSED). Bevestig met confirm_test_reuse: true.")
        cid = db.create_comparison(
            ref, uit, mode=modus,
            reference_assessment_id=_int(p, "reference_assessment_id", None, 1),
            challenger_assessment_id=_int(p, "challenger_assessment_id", None, 1),
            accessor_context=ACCESSOR if modus == "DEEP_RESULT_COMPARISON" else None)
        c = comparison_detail(db, cid)
        data = {"comparison_id": cid, "mode": c["mode"], "status": c["status"],
                "comparability_status": c["comparability_status"],
                "same_dataset": c["same_dataset"], "warnings": c["warnings"],
                "reference_assessment_id": c["reference"]["assessment_id"],
                "challenger_assessment_id": c["challenger"]["assessment_id"],
                "result": c["result"], "metric_comparison_available": c["metric_comparison_available"]}
        return {"object_id": cid, "data": data, "message": "\n".join([
            f"Vergelijking {cid} ({c['mode']}): {c['result']}.",
            f"Vergelijkbaarheid: {c['comparability_status']}; zelfde dataset: "
            f"{'ja' if c['same_dataset'] else 'nee'}.",
            *(f"Let op: {w}" for w in c["warnings"][:3]),
            "Geen winnaar, geen promotie, geen advies."])}
