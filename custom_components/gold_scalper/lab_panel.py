"""Home Assistant-koppeling van het Experiment Lab, fase 9A: de paneeltoets.

**EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING**

Deze module staat bewust **buiten** ``experiment_lab``. Zij kent Home
Assistant; het Lab niet. Wat zij aan het Lab doorgeeft, is uitsluitend een
bestandspad en een ja/nee voor herstel. Nooit ``hass``, een coordinator, een
config entry, een broker, opties of handelsstatus.

Wat fase 9A doet, en niet meer:

* de Lab-database openen op een vaste plek in de configuratiemap;
* herstel (``running`` wordt ``interrupted``) precies één keer per
  Home Assistant-proces - ook als de integratie tussendoor herladen wordt;
* één alleen-lezende, geauthenticeerde statusroute;
* één lokaal JavaScript-bestand als statisch pad;
* één ``panel_custom``-paneel in de zijbalk.

Wat fase 9A bewust níet doet: experimenten starten (ook niet wat ``queued``
staat), een werkproces aanmaken, TEST-resultaten openen, beoordelingen of
vergelijkingen maken, snapshots maken. Deze module importeert de runner, het
werkproces, de beoordeling en de vergelijking niet eens; een test bewaakt dat.

Foutdomein: alles hier is omhuld. Een fout in de Lab-koppeling wordt gelogd
en laat de handel ongemoeid.

Afmelden, eerlijk benoemd: Home Assistant kan een geregistreerde HTTP-route of
een statisch pad niet meer verwijderen. Die worden daarom één keer per proces
geregistreerd. Na het afmelden van het Lab blijft de statusroute bestaan maar
antwoordt ze ``not_loaded``; het paneel zelf verdwijnt wel.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN, INTEGRATION_VERSION, LAB_DATABASE_FILENAME
from .experiment_lab import INVARIANT
from .experiment_lab.storage import LAB_SCHEMA_VERSION, LabDatabase, LabDatabaseError

_LOGGER = logging.getLogger(__name__)

#: Versie van het antwoord van de statusroute. Omhoog bij elke wijziging van
#: de sleutels, zodat de frontend een oud antwoord herkent.
LAB_API_VERSION = 1

LAB_STATUS_URL = "/api/gold_scalper/lab/status"
LAB_STATIC_URL = "/gold_scalper_lab/lab-panel.js"
LAB_PANEL_URL_PATH = "gold-scalper-lab"
LAB_WEBCOMPONENT = "gold-scalper-lab-panel"
LAB_SIDEBAR_TITLE = "Gold Scalper Lab"
LAB_JS_FILE = Path(__file__).resolve().parent / "frontend" / "lab-panel.js"

#: Sleutels in ``hass.data``. Nooit onder ``hass.data[DOMAIN]``: daar staan
#: uitsluitend coordinators, en de diensten lopen die lijst af.
LAB_STATE_KEY = f"{DOMAIN}_lab"
LAB_RECOVERY_KEY = f"{DOMAIN}_lab_recovery"
LAB_VIEW_KEY = f"{DOMAIN}_lab_view_registered"
LAB_STATIC_KEY = f"{DOMAIN}_lab_static_registered"
LAB_MODEL_VIEW_KEY = f"{DOMAIN}_lab_model_view_registered"

LAB_MODEL_URL = "/api/gold_scalper/lab/v1/{model}"
EVENT_LAB_PROGRESS = f"{DOMAIN}_lab_progress"
EVENT_LAB_FINISHED = f"{DOMAIN}_lab_finished"
EVENT_LAB_ACTION = f"{DOMAIN}_lab_action"

#: Voortgang: hoe vaak er gekeken wordt, en hoe vaak er hooguit een event uit
#: mag. Geen event per bar of trade; alleen bij verandering, gedempt.
PROGRESS_POLL_SECONDS = 5
PROGRESS_MIN_INTERVAL_SECONDS = 10
#: Zo lang wacht een unload op een lopend werkproces.
UNLOAD_WORKER_TIMEOUT_SECONDS = 30.0
INTERRUPT_REASON = "onderbroken: Gold Scalper werd afgemeld of herladen"

#: Het volledige antwoord van de statusroute. Niets anders mag erin; een test
#: vergelijkt de sleutels exact.
STATUS_KEYS = frozenset({
    "api_version", "authenticated", "backend", "gold_scalper_version",
    "invariant", "lab_available", "lab_error", "lab_schema_version",
    "lab_schema_expected", "recovery_performed", "recovery_interrupted",
    "experiment_count",
})

#: Foutcodes in plaats van foutteksten: een OSError-tekst bevat het pad.
LAB_ERROR_CODES = frozenset({"open_failed", "recovery_failed", "read_failed", "not_loaded"})

_NO_STORE = {"Cache-Control": "no-store, must-revalidate"}


@dataclass
class LabState:
    """Wat het Lab tussen setup en unload vasthoudt."""

    db: LabDatabase | None
    error: str | None
    lock: threading.Lock = field(default_factory=threading.Lock)
    panel_registered: bool = False
    #: 5.7: de runner, de acties en de voortgangsbewaking.
    runner: object = None
    actions: object = None
    unsub_progress: object = None
    last_progress: dict | None = None
    last_progress_sent: float = 0.0
    watched_experiment: int | None = None

    def close(self) -> None:
        with self.lock:
            if self.db is not None:
                self.db.close()
                self.db = None


# -- database (draait in de executor) --------------------------------------- #

def open_lab(path: str | Path, recover: bool) -> tuple[LabDatabase | None, str | None, int | None]:
    """Open de Lab-database; herstel alleen als daarom gevraagd wordt.

    Geeft ``(db, foutcode, aantal onderbroken)``. Het aantal is ``None`` als er
    geen herstel is uitgevoerd. Gooit nooit.
    """
    db = LabDatabase(path)
    try:
        db.open()
    except (LabDatabaseError, OSError, sqlite3.Error):
        _LOGGER.exception("Lab-database kon niet worden geopend")
        db.close()                      # ``open`` sluit niet bij elke fout zelf
        return None, "open_failed", None
    if not recover:
        return db, None, None
    try:
        return db, None, db.recover_interrupted()
    except (LabDatabaseError, OSError, sqlite3.Error):
        _LOGGER.exception("Herstel van de Lab-database mislukte")
        db.close()
        return None, "recovery_failed", None


def frontend_version(js_file: Path = LAB_JS_FILE) -> str:
    """Versieparameter voor de module-URL: integratieversie plus inhoudshash.

    Elke wijziging van het bestand geeft een andere URL, dus de browser kan
    geen oude JavaScript blijven draaien achter een nieuwe integratieversie.
    """
    inhoud = Path(js_file).read_bytes()
    return f"{INTEGRATION_VERSION}-{hashlib.sha256(inhoud).hexdigest()[:12]}"


def build_status(state: LabState | None, recovery: dict | None) -> dict:
    """Het alleen-lezende statusmodel. Uitsluitend waarden uit de allowlist."""
    status = {
        "api_version": LAB_API_VERSION,
        "authenticated": True,          # alleen bereikbaar na de auth-controle
        "backend": "reachable",
        "gold_scalper_version": INTEGRATION_VERSION,
        "invariant": INVARIANT,
        "lab_available": False,
        "lab_error": None,
        "lab_schema_version": None,
        "lab_schema_expected": LAB_SCHEMA_VERSION,
        "recovery_performed": recovery is not None,
        "recovery_interrupted": None if recovery is None else int(recovery["interrupted"]),
        "experiment_count": None,
    }
    if state is None:
        status["lab_error"] = "not_loaded"
    elif state.db is None:
        status["lab_error"] = state.error if state.error in LAB_ERROR_CODES else "open_failed"
    else:
        with state.lock:
            try:
                status["lab_schema_version"] = int(state.db.schema_version())
                status["experiment_count"] = int(state.db.experiment_count())
                status["lab_available"] = True
            except (LabDatabaseError, sqlite3.Error, AttributeError):
                _LOGGER.exception("Lab-status kon niet worden gelezen")
                status["lab_error"] = "read_failed"
    if set(status) != STATUS_KEYS:     # nooit stilzwijgend een extra veld
        raise RuntimeError("statusmodel wijkt af van de allowlist")
    return status


# -- HTTP ------------------------------------------------------------------- #

class LabStatusView(HomeAssistantView):
    """Alleen-lezende status. Authenticatie en beheerdersrecht server-side."""

    url = LAB_STATUS_URL
    name = "api:gold_scalper:lab_status"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        # Vast bij registratie: één proces, één hass. Niet via request.app.
        self._hass = hass

    async def get(self, request: web.Request) -> web.Response:
        # Tweede slot achter requires_auth: ook als die ooit uit zou staan,
        # geeft deze route niets zonder ingelogde beheerder.
        user = request.get("hass_user")
        if user is None:
            return web.json_response({"error": "unauthorized"}, status=401, headers=_NO_STORE)
        if not getattr(user, "is_admin", False):
            return web.json_response({"error": "forbidden"}, status=403, headers=_NO_STORE)
        hass = self._hass
        status = await hass.async_add_executor_job(
            build_status, hass.data.get(LAB_STATE_KEY), hass.data.get(LAB_RECOVERY_KEY),
        )
        return web.json_response(status, headers=_NO_STORE)


# -- lifecycle -------------------------------------------------------------- #

async def async_setup_lab(hass: HomeAssistant) -> None:
    """Start de Lab-koppeling. Gooit nooit; de handel gaat altijd voor."""
    try:
        await _async_setup_lab(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Gold Scalper Lab kon niet starten; de handel draait door")


async def async_unload_lab(hass: HomeAssistant) -> None:
    """Ruim de Lab-koppeling op. Gooit nooit."""
    try:
        await _async_unload_lab(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Gold Scalper Lab kon niet netjes worden afgemeld")


async def _async_setup_lab(hass: HomeAssistant) -> None:
    if LAB_STATE_KEY in hass.data:
        return                          # al actief: niets dubbel
    path = hass.config.path(LAB_DATABASE_FILENAME)
    herstel_nodig = LAB_RECOVERY_KEY not in hass.data
    db, fout, onderbroken = await hass.async_add_executor_job(open_lab, path, herstel_nodig)
    if herstel_nodig and onderbroken is not None:
        hass.data[LAB_RECOVERY_KEY] = {"interrupted": onderbroken}
        if onderbroken:
            _LOGGER.warning("Lab-herstel: %d experiment(en) als onderbroken gemarkeerd", onderbroken)
    state = LabState(db=db, error=fout)
    if db is not None:
        from .const import ARCHIVE_FILENAME
        from .experiment_lab.wf_runner import WalkForwardRunner
        from .lab_actions import LabActions

        state.runner = WalkForwardRunner(path)
        state.actions = LabActions(path, hass.config.path(ARCHIVE_FILENAME), state.runner)
        state.unsub_progress = _async_track_progress(hass, state)
    hass.data[LAB_STATE_KEY] = state
    await _async_register_routes(hass)
    await _async_register_panel(hass, state)


async def _async_register_routes(hass: HomeAssistant) -> None:
    """Route en statisch pad: één keer per proces. HA kan ze niet verwijderen."""
    if not hass.data.get(LAB_VIEW_KEY):
        hass.http.register_view(LabStatusView(hass))
        hass.data[LAB_VIEW_KEY] = True
    if not hass.data.get(LAB_MODEL_VIEW_KEY):
        hass.http.register_view(LabModelView(hass))
        hass.data[LAB_MODEL_VIEW_KEY] = True
    if not hass.data.get(LAB_STATIC_KEY):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(LAB_STATIC_URL, str(LAB_JS_FILE), True)]
        )
        hass.data[LAB_STATIC_KEY] = True


async def _async_register_panel(hass: HomeAssistant, state: LabState) -> None:
    from homeassistant.components import frontend, panel_custom

    versie = await hass.async_add_executor_job(frontend_version)
    kwargs = dict(
        frontend_url_path=LAB_PANEL_URL_PATH,
        webcomponent_name=LAB_WEBCOMPONENT,
        sidebar_title=LAB_SIDEBAR_TITLE,
        sidebar_icon="mdi:flask-outline",
        module_url=f"{LAB_STATIC_URL}?v={versie}",
        embed_iframe=False,
        trust_external=False,
        require_admin=True,
        config={},
    )
    try:
        await panel_custom.async_register_panel(hass, **kwargs)
    except ValueError:
        # Een achtergebleven registratie, bijvoorbeeld met een oude
        # module-URL. Vervangen, niet naast elkaar laten staan.
        frontend.async_remove_panel(hass, LAB_PANEL_URL_PATH)
        await panel_custom.async_register_panel(hass, **kwargs)
    state.panel_registered = True


async def _async_unload_lab(hass: HomeAssistant) -> None:
    state: LabState | None = hass.data.pop(LAB_STATE_KEY, None)
    if state is None:
        return
    if state.unsub_progress is not None:
        state.unsub_progress()
        state.unsub_progress = None
    if state.actions is not None:
        state.actions.stop_accepting_starts()
    if state.runner is not None:
        await hass.async_add_executor_job(stop_worker, state.runner, state.db and state.db.path)
    try:
        if state.panel_registered:
            from homeassistant.components import frontend

            frontend.async_remove_panel(hass, LAB_PANEL_URL_PATH)
            state.panel_registered = False
    finally:
        # Er draait in 9A geen werkproces; alleen de verbinding gaat dicht.
        await hass.async_add_executor_job(state.close)



# -- 5.7: werkproces bij unload --------------------------------------------- #

def stop_worker(runner, lab_path, timeout: float = UNLOAD_WORKER_TIMEOUT_SECONDS) -> int | None:
    """Stop een lopend experiment bij unload en zet het op ``interrupted``.

    1. de runner krijgt een onderbrekingssignaal (geen gewone annulering);
    2. de runner stopt zijn werkproces zelf, en beëindigt het na zijn
       bestaande wachttijd als het niet reageert;
    3. wacht hooguit ``timeout`` seconden;
    4. staat het experiment daarna nog op ``running``, dan zet deze functie
       het zelf op ``interrupted``. Een eindstatus start nooit vanzelf opnieuw.

    Wachtende experimenten (``queued``) worden niet aangeraakt en niet gestart.
    Geeft het onderbroken experiment-id, of None.
    """
    handle = runner.active
    if handle is None:
        return None
    eid = handle.experiment_id
    handle.interrupt(INTERRUPT_REASON)
    if not handle.wait(timeout) and lab_path:
        db = LabDatabase(lab_path).open()
        try:
            exp = db.get(eid)
            if exp is not None and exp.status == "running":
                db.end_run(eid, "interrupted", INTERRUPT_REASON)
        finally:
            db.close()
    return eid


# -- 5.7: voortgang als gedempt event --------------------------------------- #

PROGRESS_EVENT_KEYS = (
    "experiment_id", "status", "progress_pct", "windows_total", "current_window",
    "windows_completed", "candidates_total", "current_candidate", "current_segment",
    "bars_total", "bars_processed",
)


def progress_event(model: dict) -> dict:
    """Alleen de toegestane voortgangsvelden; nooit trades of metrieken."""
    return {k: model.get(k) for k in PROGRESS_EVENT_KEYS}


def progress_changed(vorige: dict | None, nieuw: dict) -> bool:
    if vorige is None:
        return True
    if vorige.get("status") != nieuw.get("status"):
        return True
    for k in ("current_window", "current_candidate", "current_segment", "windows_completed"):
        if vorige.get(k) != nieuw.get(k):
            return True
    return abs((nieuw.get("progress_pct") or 0) - (vorige.get("progress_pct") or 0)) >= 1.0


def _async_track_progress(hass: HomeAssistant, state: LabState):
    import time

    from homeassistant.helpers.event import async_track_time_interval
    from datetime import timedelta

    async def _tick(_now) -> None:
        handle = state.runner.active if state.runner else None
        eid = handle.experiment_id if handle else state.watched_experiment
        if eid is None:
            return
        try:
            model = await hass.async_add_executor_job(_read_progress, state, eid)
        except Exception:  # noqa: BLE001
            return
        nu = time.monotonic()
        if handle is not None:
            state.watched_experiment = eid
            if (progress_changed(state.last_progress, model)
                    and nu - state.last_progress_sent >= PROGRESS_MIN_INTERVAL_SECONDS):
                hass.bus.async_fire(EVENT_LAB_PROGRESS, progress_event(model))
                state.last_progress, state.last_progress_sent = model, nu
            return
        # Run afgelopen: één klein eindbericht en een melding.
        state.watched_experiment = None
        state.last_progress = None
        hass.bus.async_fire(EVENT_LAB_FINISHED, {"experiment_id": eid, "status": model["status"]})
        _notify(hass, f"Experiment {eid}: {model['status']}",
                f"Experiment {eid} is geëindigd met status {model['status']}. "
                f"{model['windows_completed']} van {model['windows_total']} vensters voltooid.")

    return async_track_time_interval(hass, _tick, timedelta(seconds=PROGRESS_POLL_SECONDS))


def _read_progress(state: LabState, eid: int) -> dict:
    from .lab_read_models import experiment_progress

    with state.lock:
        return experiment_progress(state.db, eid)


def _notify(hass: HomeAssistant, titel: str, tekst: str) -> None:
    try:
        from homeassistant.components import persistent_notification

        persistent_notification.async_create(
            hass, tekst, title=f"Gold Scalper Lab: {titel}", notification_id=f"{DOMAIN}_lab")
    except Exception:  # noqa: BLE001
        _LOGGER.info("Gold Scalper Lab: %s - %s", titel, tekst)


# -- 5.7: acties ------------------------------------------------------------ #

async def async_handle_action(hass: HomeAssistant, actie: str, data: dict,
                              user_id: str | None) -> dict:
    """Een Lab-actie uit Home Assistant. Beheerder vereist, server-side.

    Een aanroep zonder gebruiker (een automatisering) wordt geweigerd: wie een
    experiment start of TEST opent, is altijd te herleiden tot een beheerder.
    """
    user = await hass.auth.async_get_user(user_id) if user_id else None
    if user is None or not getattr(user, "is_admin", False):
        return {"ok": False, "action": actie, "object_id": None, "replayed": False,
                "message": "Niet gelukt (forbidden): Lab-acties vragen een ingelogde beheerder.",
                "error": {"code": "forbidden",
                          "message": "Lab-acties vragen een ingelogde beheerder.",
                          "object_id": None}}
    state: LabState | None = hass.data.get(LAB_STATE_KEY)
    if state is None or state.actions is None:
        return {"ok": False, "action": actie, "object_id": None, "replayed": False,
                "message": "Niet gelukt (lab_not_loaded): het Lab is niet geladen.",
                "error": {"code": "lab_not_loaded", "message": "het Lab is niet geladen",
                          "object_id": None}}
    antwoord = await hass.async_add_executor_job(state.actions.run, actie, dict(data))
    hass.bus.async_fire(EVENT_LAB_ACTION, {"action": actie, "ok": antwoord["ok"],
                                           "object_id": antwoord.get("object_id")})
    if actie == "start" and antwoord["ok"]:
        state.watched_experiment = antwoord["object_id"]
        state.last_progress = None
    return antwoord


# -- 5.7: leesmodellen ------------------------------------------------------ #

MODELS = {
    # naam: (functie, id-parameter of None)
    "overview": ("lab_overview", None),
    "experiments": ("experiment_list", None),
    "experiment": ("experiment_detail", "id"),
    "progress": ("experiment_progress", "id"),
    "test_status": ("test_status", "id"),
    "datasets": ("dataset_list", None),
    "dataset": ("dataset_detail", "id"),
    "assessments": ("assessment_list", None),
    "assessment": ("assessment_detail", "id"),
    "comparisons": ("comparison_list", None),
    "comparison": ("comparison_detail", "id"),
    "family": ("family_summary", "family"),
}


def read_model(state: LabState | None, model: str, ident: str | None) -> tuple[int, dict]:
    """``(http-status, antwoord)``. Leest, opent nooit TEST."""
    from . import lab_read_models as R

    if model not in MODELS:
        return 404, {"error": "unknown_model"}
    if state is None or state.db is None:
        return 503, {"error": "lab_not_loaded"}
    functie, param = MODELS[model]
    args = []
    if param == "id":
        if not ident or not str(ident).isdigit():
            return 400, {"error": "id_required"}
        args.append(int(ident))
    elif param == "family":
        if not ident or len(ident) > 80:
            return 400, {"error": "family_required"}
        args.append(ident)
    with state.lock:
        try:
            uit = getattr(R, functie)(state.db, *args)
        except R.ReadModelError as err:
            return 404, {"error": err.code}
    return 200, {"model": model, "read_model_version": R.READ_MODEL_VERSION, "data": uit}


class LabModelView(HomeAssistantView):
    """Alleen-lezende leesmodellen. Zelfde toegang als de status: beheerder."""

    url = LAB_MODEL_URL
    name = "api:gold_scalper:lab_model"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, model: str) -> web.Response:
        user = request.get("hass_user")
        if user is None:
            return web.json_response({"error": "unauthorized"}, status=401, headers=_NO_STORE)
        if not getattr(user, "is_admin", False):
            return web.json_response({"error": "forbidden"}, status=403, headers=_NO_STORE)
        ident = request.query.get("id") or request.query.get("family")
        status, body = await self._hass.async_add_executor_job(
            read_model, self._hass.data.get(LAB_STATE_KEY), model, ident)
        return web.json_response(body, status=status, headers=_NO_STORE)
