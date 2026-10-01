"""De runner: voert één experiment uit, in een apart werkproces.

Waarom een proces en geen thread - gemeten, niet aangenomen (fase-3-rapport):
Python-rekenwerk in een thread houdt de GIL vast en gaf een nagebootste event
loop zoals die van Home Assistant een vaste vertraging van ~5 ms per wekker,
met uitschieters tot 27 ms. Met een apart proces bleef de lus op het niveau
zonder experiment. Een crash van het werkproces raakt Home Assistant niet.

Het werkproces:

* wordt gestart via ``worker_entry.py`` als script, in Python's geïsoleerde
  modus (``-I``), met een omgeving die alleen ``PATH`` bevat;
* laadt de Lab-modules zonder ``gold_scalper/__init__.py`` - dus zonder
  coordinator, broker of Home Assistant - en meldt welke modules het laadde;
* opent de Lab-database zelf, alleen-lezend, en schrijft niets.

De controller is de enige schrijver in de Lab-database. Elke uitvoering heeft
haar eigen controllerdraad met haar eigen verbinding; verbindingen gaan nooit
over een draad- of procesgrens.

Eén experiment tegelijk. Starten is altijd een bewuste handeling: de runner
pakt nooit uit zichzelf een experiment uit de wachtrij op, ook niet na een
herstart.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .models import Status, canonical_json, config_hash
from .storage import LabDatabase
from .metrics import check_invariants
from .worker import RunRequest, result_hash

WORKER_ENTRY = Path(__file__).resolve().parent / "worker_entry.py"

#: Technische grenzen, geen handelsinhoudelijke. Elk ervan beschermt Home
#: Assistant tegen een ontspoorde uitvoering; zie het fase-3-rapport.
MAX_QUEUED = 10                 # een wachtrij zonder bodem groeit onbeheerst
PROGRESS_WRITE_SECONDS = 2.0    # voortgang schrijven, niet bij elke bar
STALL_TIMEOUT_SECONDS = 300.0   # geen enkel bericht meer: werkproces ontspoord
CANCEL_GRACE_SECONDS = 10.0     # coöperatief stoppen, daarna pas beëindigen

#: Eindberichten van het werkproces.
_EINDE = {"result", "cancelled", "error"}


class RunRefused(RuntimeError):
    """Een experiment voldoet niet aan de voorwaarden om te starten."""


class RunnerBusy(RunRefused):
    """Er loopt al een experiment."""


@dataclass
class RunHandle:
    experiment_id: int
    _stop: threading.Event = field(default_factory=threading.Event)
    _klaar: threading.Event = field(default_factory=threading.Event)
    final_status: str | None = None
    error: str | None = None
    #: Welke voortgang er is weggeschreven, in volgorde (voor controle).
    progress_log: list = field(default_factory=list)
    #: Welke modules het werkproces laadde (bewijs van de grens).
    loaded_modules: list = field(default_factory=list)
    cancel_requested_at: float | None = None
    stopped_at: float | None = None

    #: Gezet door :meth:`interrupt`: de stop komt van buiten het experiment
    #: (Home Assistant meldt de integratie af), niet van de gebruiker.
    interrupt_reason: str | None = None

    def cancel(self) -> None:
        if self.cancel_requested_at is None:
            self.cancel_requested_at = time.monotonic()
        self._stop.set()

    def interrupt(self, reason: str) -> None:
        """Stop zoals :meth:`cancel`, maar eindig als ``interrupted``.

        Voor een stop die niet de keuze van de gebruiker is - een unload van
        de integratie. Zo'n experiment start daarna niet vanzelf opnieuw: een
        eindstatus is eindig.
        """
        if self.interrupt_reason is None:
            self.interrupt_reason = reason
        self.cancel()

    def eind_status(self, status: str, reden: str) -> tuple[str, str]:
        """Een geannuleerde run wordt ``interrupted`` als de stop van buiten kwam."""
        if status == "cancelled" and self.interrupt_reason:
            return "interrupted", self.interrupt_reason
        return status, reden

    def wait(self, timeout: float | None = None) -> bool:
        return self._klaar.wait(timeout)

    @property
    def done(self) -> bool:
        return self._klaar.is_set()


class ExperimentRunner:
    """Start en bewaakt één experiment tegelijk."""

    def __init__(
        self, lab_db_path: str | Path, *,
        worker_command: list[str] | None = None,
        stall_timeout: float = STALL_TIMEOUT_SECONDS,
        cancel_grace: float = CANCEL_GRACE_SECONDS,
        progress_write_seconds: float = PROGRESS_WRITE_SECONDS,
    ) -> None:
        self.lab_db_path = str(Path(lab_db_path).resolve())
        self._worker_command = worker_command or [sys.executable, "-I", str(WORKER_ENTRY)]
        self._stall_timeout = stall_timeout
        self._cancel_grace = cancel_grace
        self._progress_write = progress_write_seconds
        self._lock = threading.Lock()
        self._actief: RunHandle | None = None

    # -- starten ------------------------------------------------------------ #

    @property
    def active(self) -> RunHandle | None:
        """De lopende run van deze runner, of None."""
        handle = self._actief
        return handle if handle is not None and not handle.done else None

    def submit(self, experiment_id: int, dataset_id: int, config: dict) -> RunHandle:
        """Controleer alles, zet het experiment in de wachtrij, en start het.

        Alle controles gebeuren vóór ``queued``. Wordt er één niet gehaald,
        dan verandert er niets aan het experiment.
        """
        with self._lock:
            if self._actief is not None and not self._actief.done:
                raise RunnerBusy("er loopt al een experiment in deze runner")
            db = LabDatabase(self.lab_db_path).open()
            try:
                self._valideer(db, experiment_id, dataset_id, config)
                db.transition(experiment_id, Status.QUEUED)
                # Meteen door naar running, nog binnen de vergrendeling: anders
                # ziet een tweede runner het experiment in het korte venster
                # tot de controllerdraad start nog als queued, en start hij er
                # een naast. Gevonden door de test op één-tegelijk.
                plan = db.segment_plan(experiment_id)
                db.begin_run(experiment_id, executor="process")
                ds_hash = db.dataset(dataset_id)["hash"]
            finally:
                db.close()
            handle = RunHandle(experiment_id)
            self._actief = handle
        request = RunRequest(
            experiment_id=experiment_id, dataset_id=dataset_id,
            dataset_hash=ds_hash, lab_db_path=self.lab_db_path,
            config=config, config_hash=config_hash(config),
            segment_plan=plan,
        )
        threading.Thread(
            target=self._uitvoeren, args=(handle, request),
            name=f"gold-scalper-lab-{experiment_id}", daemon=True,
        ).start()
        return handle

    def _valideer(self, db: LabDatabase, experiment_id: int,
                  dataset_id: int, config: dict) -> None:
        exp = db.get(experiment_id)
        if exp is None:
            raise RunRefused(f"experiment {experiment_id} bestaat niet")
        if exp.status != Status.REGISTERED.value:
            raise RunRefused(f"experiment staat op {exp.status}, niet op registered")
        if exp.dataset_id is None or exp.dataset_id != dataset_id:
            raise RunRefused("de dataset hoort niet bij dit experiment")
        berekend = config_hash(config)
        if not exp.config_hash or berekend != exp.config_hash:
            raise RunRefused("de configuratie hoort niet bij de geregistreerde configuratiehash")
        if berekend not in {p["config_hash"] for p in db.parameters(experiment_id)}:
            raise RunRefused("de configuratie staat niet bij de parameters van het experiment")

        plan = db.segment_plan(experiment_id)
        if plan is not None:
            houd = (config.get("exits") or {}).get("max_hold_seconds")
            if houd is None:
                from ..broker.exits import ExitConfig
                houd = ExitConfig().max_hold_seconds
            if houd > plan["max_hold_seconds"]:
                raise RunRefused("de maximale houdtijd van de configuratie is langer dan in "
                                 "het segmentplan; het afkapmoment zou niet beschermen")

        ds = db.dataset(dataset_id)
        if ds is None:
            raise RunRefused(f"dataset {dataset_id} bestaat niet")
        if ds["sealed"] != 1:
            raise RunRefused("de dataset is niet verzegeld")
        controle = db.verify_dataset(dataset_id)
        if not controle["ok"]:
            raise RunRefused(f"de dataset voldoet niet aan zijn invarianten: {controle}")
        if ds["quality_status"] == "BLOCKED":
            raise RunRefused("de dataset is BLOCKED; zie de kwaliteitsbevindingen")

        lopend = db.conn.execute(
            "SELECT COUNT(*) FROM experiments WHERE status='running'"
        ).fetchone()[0]
        if lopend:
            raise RunnerBusy("er loopt al een experiment in deze Lab-database")
        wachtend = db.conn.execute(
            "SELECT COUNT(*) FROM experiments WHERE status='queued'"
        ).fetchone()[0]
        if wachtend >= MAX_QUEUED:
            raise RunRefused(f"de wachtrij is vol ({MAX_QUEUED})")

    # -- annuleren buiten een lopende uitvoering --------------------------- #

    def cancel_pending(self, experiment_id: int) -> None:
        """Een experiment dat nog niet loopt, annuleren (registered of queued)."""
        db = LabDatabase(self.lab_db_path).open()
        try:
            db.transition(experiment_id, Status.CANCELLED,
                          error="geannuleerd voordat het liep")
        finally:
            db.close()

    # -- uitvoeren (controllerdraad) --------------------------------------- #

    def _uitvoeren(self, handle: RunHandle, request: RunRequest) -> None:
        db = LabDatabase(self.lab_db_path).open()     # eigen verbinding, eigen draad
        proces = None
        try:
            proces = subprocess.Popen(
                self._worker_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
                env={"PATH": _pad()}, cwd=str(Path(self.lab_db_path).parent),
            )
            proces.stdin.write(json.dumps(request.as_dict()) + "\n")
            proces.stdin.flush()
            status, reden, resultaat = self._volg(handle, proces, db, request)
            if status == "completed":
                try:
                    if resultaat.get("segmented"):
                        self._controleer_segmenten(resultaat, request, db)
                        db.complete_segmented(request.experiment_id, resultaat)
                    else:
                        self._controleer_resultaat(resultaat, request)
                        db.complete_with_result(request.experiment_id, resultaat)
                except Exception as err:  # noqa: BLE001 - opslaan mislukt: nooit completed
                    status, reden = "failed", f"resultaat niet opgeslagen: {err}"
                    db.end_run(request.experiment_id, Status.FAILED, reden)
            else:
                status, reden = handle.eind_status(status, reden)
                db.end_run(request.experiment_id, Status(status), reden)
            handle.final_status, handle.error = status, reden
        except Exception as err:  # noqa: BLE001 - een fout in het Lab blijft in het Lab
            handle.final_status, handle.error = "failed", f"{type(err).__name__}: {err}"
            try:
                exp = db.get(request.experiment_id)
                if exp is not None and exp.status in ("queued", "running"):
                    db.end_run(request.experiment_id, Status.FAILED, handle.error)
            except Exception:  # noqa: BLE001
                pass
        finally:
            if proces is not None:
                _beeindig(proces)
            handle.stopped_at = time.monotonic()
            db.close()
            handle._klaar.set()

    def _volg(self, handle, proces, db, request, bij_voortgang=None):
        """Lees de berichten van het werkproces tot het eindbericht."""
        berichten: queue.Queue = queue.Queue()

        def lees():
            for regel in proces.stdout:
                try:
                    berichten.put(json.loads(regel))
                except ValueError:
                    continue
            berichten.put(None)                       # einde van de uitvoer

        threading.Thread(target=lees, daemon=True).start()
        laatste_bericht = time.monotonic()
        laatst_geschreven = 0.0
        eind = None
        annuleer_gestuurd = None

        while True:
            # Na het eindbericht is het werkproces klaar en is zijn invoer al
            # gesloten: dan geen annuleersignaal meer sturen. Eerder gaf een
            # annulering in dat korte venster een ValueError (schrijven naar
            # een gesloten bestand) en werd het experiment ten onrechte failed.
            if handle._stop.is_set() and annuleer_gestuurd is None and eind is None:
                annuleer_gestuurd = time.monotonic()
                try:
                    proces.stdin.write('{"cancel": true}\n')
                    proces.stdin.flush()
                except (OSError, ValueError):
                    pass
            if annuleer_gestuurd and time.monotonic() - annuleer_gestuurd > self._cancel_grace:
                _beeindig(proces)
                return "cancelled", "geannuleerd; werkproces reageerde niet op tijd en is beëindigd", None
            if time.monotonic() - laatste_bericht > self._stall_timeout:
                _beeindig(proces)
                return "failed", "werkproces gaf geen teken van leven meer en is beëindigd", None

            try:
                bericht = berichten.get(timeout=0.2)
            except queue.Empty:
                continue
            laatste_bericht = time.monotonic()

            if bericht is None:                       # uitvoer gesloten
                if eind is not None:
                    return eind
                if handle._stop.is_set():
                    return "cancelled", "geannuleerd", None
                return "interrupted", "werkproces verdween zonder eindbericht", None

            soort = bericht.get("type")
            if soort == "progress" and bij_voortgang is not None:
                bij_voortgang(bericht)
            elif soort == "progress":
                nu = time.monotonic()
                if nu - laatst_geschreven >= self._progress_write:
                    laatst_geschreven = nu
                    if "segment" in bericht:
                        db.update_segment_progress(
                            request.experiment_id, bericht["segment"],
                            bericht.get("segments_completed", 0),
                            bericht.get("segments_total", 0),
                            bericht["done"], bericht["total"])
                    else:
                        db.update_progress(request.experiment_id, bericht["done"], bericht["total"])
                    handle.progress_log.append(db.run_state(request.experiment_id)["progress_pct"])
            elif soort == "modules":
                handle.loaded_modules = bericht.get("loaded", [])
                if eind is not None:
                    return eind
            elif soort in _EINDE:
                try:
                    proces.stdin.close()              # laat de luisteraar stoppen
                except OSError:
                    pass
                if soort == "result":
                    eind = ("completed", None, bericht["result"])
                elif soort == "cancelled":
                    eind = ("cancelled", "geannuleerd", None)
                else:
                    eind = ("failed", bericht.get("message", "onbekende fout"), None)

    @staticmethod
    def _controleer_segmenten(resultaat: dict, request: RunRequest, db) -> None:
        _controleer_segmenten_impl(resultaat, request, db)

    @staticmethod
    def _controleer_resultaat(resultaat: dict, request: RunRequest) -> None:
        """Onafhankelijke integriteitscontrole vóór het opslaan.

        De controller rekent geen handel opnieuw. Hij controleert of het
        resultaat klopt met zichzelf, met de aanvraag, en met de invarianten
        van kosten, metrieken en uitsplitsingen.
        """
        for sleutel in ("summary", "trades", "metrics", "breakdowns", "rejections",
                        "cost_model", "versions", "result_hash", "provenance"):
            if sleutel not in resultaat:
                raise ValueError(f"resultaat mist '{sleutel}'")
        if result_hash(resultaat["summary"], resultaat["trades"]) != resultaat["result_hash"]:
            raise ValueError("de resultaathash klopt niet met de inhoud")
        herkomst = resultaat["provenance"]
        if herkomst.get("dataset_hash") != request.dataset_hash:
            raise ValueError("het resultaat hoort bij een andere dataset")
        if herkomst.get("config_hash") != request.config_hash:
            raise ValueError("het resultaat hoort bij een andere configuratie")
        samenvatting = resultaat["summary"]
        if "fidelity" not in samenvatting or "provenance" not in samenvatting:
            raise ValueError("de getrouwheidsgegevens van de backtest ontbreken")
        if samenvatting.get("trades") != len(resultaat["trades"]):
            raise ValueError("het aantal trades verschilt tussen samenvatting en trades")
        versies = resultaat["versions"]
        for sleutel in ("backtest_engine_version", "result_schema_version",
                        "cost_model_version", "metrics_version"):
            if not isinstance(versies.get(sleutel), int):
                raise ValueError(f"versie ontbreekt: {sleutel}")
        fouten = check_invariants(resultaat["trades"], resultaat["metrics"],
                                  resultaat["breakdowns"])
        if fouten:
            raise ValueError("invarianten geschonden: " + "; ".join(fouten[:5]))


def _controleer_segmenten_impl(resultaat: dict, request: RunRequest, db) -> None:
    """Onafhankelijke controle van een gesegmenteerd resultaat.

    Het plan komt uit de database, niet uit het resultaat: de controller toetst
    tegen wat vóór de uitvoering is vergrendeld.
    """
    import hashlib as _h

    plan = db.segment_plan(request.experiment_id)
    if plan is None:
        raise ValueError("gesegmenteerd resultaat zonder segmentplan")
    herkomst = resultaat.get("provenance", {})
    if herkomst.get("dataset_hash") != request.dataset_hash:
        raise ValueError("het resultaat hoort bij een andere dataset")
    if herkomst.get("config_hash") != request.config_hash:
        raise ValueError("het resultaat hoort bij een andere configuratie")
    if herkomst.get("segment_plan_hash") != plan["plan_hash"]:
        raise ValueError("het resultaat hoort bij een ander segmentplan")
    versies = resultaat.get("versions", {})
    if versies.get("segment_schema_version") != plan["segment_schema_version"]:
        raise ValueError("segmentschemaversie wijkt af van het plan")
    segs = resultaat.get("segments", [])
    if [s["kind"] for s in segs] != [s["kind"] for s in plan["segments"]]:
        raise ValueError("de segmenten komen niet overeen met het plan")
    for seg, grens in zip(segs, plan["segments"]):
        if result_hash(seg["summary"], seg["trades"]) != seg["result_hash"]:
            raise ValueError(f"{seg['kind']}: resultaathash klopt niet")
        for t in seg["trades"]:
            if not grens["start_ts"] <= t["opened_ts"] < grens["open_cutoff_ts"]:
                raise ValueError(f"{seg['kind']}: trade opent buiten [start, afkapmoment)")
            if t["closed_ts"] >= grens["end_ts"]:
                raise ValueError(f"{seg['kind']}: trade sluit op of na het segmenteinde")
            if t["cross_boundary"] != (t["close_reason"] == "segment_end"):
                raise ValueError(f"{seg['kind']}: cross_boundary klopt niet met de sluitreden")
        fouten = check_invariants(seg["trades"], seg["metrics"], seg["breakdowns"])
        if fouten:
            raise ValueError(f"{seg['kind']}: invarianten geschonden: " + "; ".join(fouten[:3]))
    totaal = _h.sha256(canonical_json([s["result_hash"] for s in segs]).encode("utf-8")).hexdigest()
    if totaal != resultaat.get("result_hash"):
        raise ValueError("de totale resultaathash klopt niet")


def _pad() -> str:
    import os
    return os.environ.get("PATH", "")


def _beeindig(proces: subprocess.Popen) -> None:
    """Gecontroleerd beëindigen: eerst netjes, dan pas hard."""
    if proces.poll() is not None:
        return
    try:
        proces.terminate()
        proces.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proces.kill()
        proces.wait(timeout=5)
    except OSError:
        pass
