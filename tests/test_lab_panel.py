"""Fase 9A: de Home Assistant-koppeling van het Experiment Lab.

EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING

Wat hier bewezen wordt zonder echte Home Assistant of browser: lifecycle,
herstel precies één keer, geen automatische start, een statusmodel met alleen
toegestane waarden, authenticatie in de route zelf, en een frontend zonder
externe bronnen. Wat alleen in een echte installatie te zien is, staat in
``docs/experiment-lab-fase9a.md`` als NOT_TESTED.
"""
import ast
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
import gold_scalper.lab_panel as lp  # noqa: E402
from gold_scalper.const import INTEGRATION_VERSION, LAB_DATABASE_FILENAME  # noqa: E402
from gold_scalper.experiment_lab import INVARIANT  # noqa: E402
from gold_scalper.experiment_lab.models import Experiment  # noqa: E402
from gold_scalper.experiment_lab.storage import LAB_SCHEMA_VERSION, LabDatabase  # noqa: E402
from gold_scalper.http import PANEL_URL_PATH  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
BRON = (PKG / "lab_panel.py").read_text(encoding="utf-8")
JS = (PKG / "frontend" / "lab-panel.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------- nephulp --

class FakeHttp:
    def __init__(self):
        self.views, self.static = [], []

    def register_view(self, view):
        self.views.append(view)

    async def async_register_static_paths(self, configs):
        self.static.extend(configs)


class FakeHass:
    def __init__(self, map_):
        self.data = {}
        self.paden = []
        self.http = FakeHttp()
        self.config = SimpleNamespace(path=self._pad)
        self._map = Path(map_)

    def _pad(self, *delen):
        self.paden.append(delen)
        return str(self._map.joinpath(*delen))

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class Panelen:
    """Nep voor ``frontend`` en ``panel_custom``: houdt de zijbalk bij."""

    def __init__(self):
        self.zijbalk: dict[str, dict] = {}
        self.registraties = 0
        self.verwijderd = 0

    async def async_register_panel(self, hass, **kwargs):
        pad = kwargs["frontend_url_path"]
        if pad in self.zijbalk:
            raise ValueError(f"Overwriting panel {pad}")
        self.zijbalk[pad] = kwargs
        self.registraties += 1

    def async_remove_panel(self, hass, pad, **_):
        self.zijbalk.pop(pad, None)
        self.verwijderd += 1


@pytest.fixture
def panelen(monkeypatch):
    import homeassistant.components as hc

    p = Panelen()
    pc = ModuleType("panel_custom")
    pc.async_register_panel = p.async_register_panel
    fe = ModuleType("frontend")
    fe.async_remove_panel = p.async_remove_panel
    monkeypatch.setattr(hc, "panel_custom", pc, raising=False)
    monkeypatch.setattr(hc, "frontend", fe, raising=False)
    monkeypatch.setattr(lp, "StaticPathConfig",
                        lambda url, pad, cache: SimpleNamespace(url_path=url, path=pad, cache=cache))
    return p


@pytest.fixture
def hass(tmp_path):
    return FakeHass(tmp_path)


def _run(coro):
    return asyncio.run(coro)


def _experiment():
    return Experiment(
        name="9A", type="challenger", hypothesis="h", expected_effect="e",
        primary_metric="net_pnl", secondary_metrics=["trades"],
        evaluation_method="out_of_sample", hypothesis_family_id="fase9a",
        software_version=INTEGRATION_VERSION, strategy_version="scalp-0.2.0",
        execution_semantics_version=3, config_hash="abc",
    )


def _met_status(pad, *statussen):
    db = LabDatabase(pad).open()
    eid = db.create(_experiment())
    for s in statussen:
        db.transition(eid, s)
    db.close()
    return eid


def _status_van(pad, eid):
    db = LabDatabase(pad).open()
    try:
        return db.get(eid).status
    finally:
        db.close()


def _lab_pad(hass):
    return Path(hass.config.path(LAB_DATABASE_FILENAME))


class Gebruiker:
    def __init__(self, admin):
        self.is_admin = admin


def _get(hass, gebruiker):
    view = next(v for v in hass.http.views if isinstance(v, lp.LabStatusView))
    request = {} if gebruiker is None else {"hass_user": gebruiker}
    antwoord = _run(view.get(request))
    return antwoord.status, json.loads(antwoord.text)


# -------------------------------------------------------------- lifecycle --

def test_setup_registers_view_static_and_panel_once(hass, panelen):
    _run(lp.async_setup_lab(hass))
    _run(lp.async_setup_lab(hass))
    # 5.7: naast de status een route voor de leesmodellen.
    assert sorted(type(v).__name__ for v in hass.http.views) == ["LabModelView", "LabStatusView"]
    assert len(hass.http.static) == 1
    assert panelen.registraties == 1
    assert list(panelen.zijbalk) == [lp.LAB_PANEL_URL_PATH]


def test_database_lives_at_a_fixed_internal_path(hass, panelen):
    _run(lp.async_setup_lab(hass))
    assert (LAB_DATABASE_FILENAME,) in hass.paden
    assert _lab_pad(hass).exists()
    assert LAB_DATABASE_FILENAME == "gold_scalper_lab.db"


def test_database_path_is_not_configurable():
    """Geen optie, geen dienstveld: het pad komt alleen uit de constante."""
    assert "options" not in BRON and "call.data" not in BRON
    boom = ast.parse(BRON)
    aanroepen = [n for n in ast.walk(boom) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "path"]
    # De Lab-database en (5.7, alleen lezend via de brug) het barsarchief.
    assert sorted(a.args[0].id for a in aanroepen) == ["ARCHIVE_FILENAME", "LAB_DATABASE_FILENAME"]


def test_panel_registration_parameters(hass, panelen):
    _run(lp.async_setup_lab(hass))
    p = panelen.zijbalk[lp.LAB_PANEL_URL_PATH]
    assert p["sidebar_title"] == "Gold Scalper Lab"
    assert p["webcomponent_name"] == "gold-scalper-lab-panel"
    assert p["embed_iframe"] is False and p["trust_external"] is False
    assert p["require_admin"] is True
    assert p["module_url"].startswith(lp.LAB_STATIC_URL + "?v=" + INTEGRATION_VERSION + "-")
    assert p["config"] == {}


def test_lab_panel_does_not_replace_the_existing_panel():
    assert lp.LAB_PANEL_URL_PATH != PANEL_URL_PATH == "gold-scalper"


def test_static_path_serves_exactly_the_local_module(hass, panelen):
    _run(lp.async_setup_lab(hass))
    (cfg,) = hass.http.static
    assert cfg.url_path == lp.LAB_STATIC_URL
    assert Path(cfg.path) == lp.LAB_JS_FILE and lp.LAB_JS_FILE.is_file()


def test_unload_removes_panel_and_closes_database(hass, panelen):
    _run(lp.async_setup_lab(hass))
    state = hass.data[lp.LAB_STATE_KEY]
    _run(lp.async_unload_lab(hass))
    assert lp.LAB_STATE_KEY not in hass.data
    assert panelen.zijbalk == {}
    assert state.db is None


def test_reload_registers_nothing_twice(hass, panelen):
    for _ in range(3):
        _run(lp.async_setup_lab(hass))
        _run(lp.async_unload_lab(hass))
    _run(lp.async_setup_lab(hass))
    assert len(hass.http.views) == 2 and len(hass.http.static) == 1
    assert list(panelen.zijbalk) == [lp.LAB_PANEL_URL_PATH]
    assert panelen.registraties == 4 and panelen.verwijderd == 3


def test_a_stale_panel_is_replaced_not_duplicated(hass, panelen):
    panelen.zijbalk[lp.LAB_PANEL_URL_PATH] = {"module_url": "oud"}
    _run(lp.async_setup_lab(hass))
    assert list(panelen.zijbalk) == [lp.LAB_PANEL_URL_PATH]
    assert panelen.zijbalk[lp.LAB_PANEL_URL_PATH]["module_url"] != "oud"


def test_unload_without_setup_is_harmless(hass, panelen):
    _run(lp.async_unload_lab(hass))
    assert panelen.verwijderd == 0


def test_lab_failure_never_raises(hass, panelen):
    _lab_pad(hass).mkdir()                    # een map waar een bestand hoort
    _run(lp.async_setup_lab(hass))
    state = hass.data[lp.LAB_STATE_KEY]
    assert state.db is None and state.error == "open_failed"
    assert lp.LAB_RECOVERY_KEY not in hass.data


def test_registration_failure_never_raises(hass, panelen, monkeypatch):
    def kapot(view):
        raise RuntimeError("route kapot")
    monkeypatch.setattr(hass.http, "register_view", kapot)
    _run(lp.async_setup_lab(hass))            # geen uitzondering


def test_integration_calls_the_lab_guarded_and_after_trading():
    bron = (PKG / "__init__.py").read_text(encoding="utf-8")
    setup = bron.split("async def async_setup_entry", 1)[1].split("\nasync def ", 1)[0]
    assert setup.index("async_forward_entry_setups") < setup.index('_async_lab(hass, "async_setup_lab")')
    unload = bron.split("async def async_unload_entry", 1)[1].split("\nasync def ", 1)[0]
    assert '_async_lab(hass, "async_unload_lab")' in unload
    helper = bron.split("async def _async_lab", 1)[1].split("\nasync def ", 1)[0].split("\ndef ", 1)[0]
    assert "from . import lab_panel" in helper and "except Exception" in helper
    # Nergens anders een import van de Lab-koppeling op moduleniveau.
    assert "from .lab_panel import" not in bron


# ---------------------------------------------------------------- herstel --

def test_recovery_runs_exactly_once_per_process(hass, panelen):
    pad = _lab_pad(hass)
    eerste = _met_status(pad, "registered", "queued", "running")
    _run(lp.async_setup_lab(hass))
    assert _status_van(pad, eerste) == "interrupted"
    assert hass.data[lp.LAB_RECOVERY_KEY] == {"interrupted": 1}

    _run(lp.async_unload_lab(hass))
    tweede = _met_status(pad, "registered", "queued", "running")
    _run(lp.async_setup_lab(hass))            # herladen: geen tweede herstel
    assert _status_van(pad, tweede) == "running"
    assert hass.data[lp.LAB_RECOVERY_KEY] == {"interrupted": 1}


def test_a_fresh_process_recovers_again(tmp_path, panelen):
    eerste = FakeHass(tmp_path)
    _run(lp.async_setup_lab(eerste))
    eid = _met_status(_lab_pad(eerste), "registered", "queued", "running")
    tweede = FakeHass(tmp_path)               # Home Assistant herstart
    _run(lp.async_setup_lab(tweede))
    assert _status_van(_lab_pad(tweede), eid) == "interrupted"


def test_an_ordinary_open_does_not_recover(tmp_path):
    pad = tmp_path / LAB_DATABASE_FILENAME
    eid = _met_status(pad, "registered", "queued", "running")
    db, fout, onderbroken = lp.open_lab(pad, recover=False)
    assert fout is None and onderbroken is None
    db.close()
    assert _status_van(pad, eid) == "running"


def test_queued_experiments_are_not_started(hass, panelen):
    pad = _lab_pad(hass)
    eid = _met_status(pad, "registered", "queued")
    _run(lp.async_setup_lab(hass))
    _get(hass, Gebruiker(True))
    _run(lp.async_unload_lab(hass))
    assert _status_van(pad, eid) == "queued"


def test_failed_open_leaves_recovery_for_a_later_attempt(hass, panelen):
    pad = _lab_pad(hass)
    pad.mkdir()
    _run(lp.async_setup_lab(hass))
    _run(lp.async_unload_lab(hass))
    pad.rmdir()
    eid = _met_status(pad, "registered", "queued", "running")
    _run(lp.async_setup_lab(hass))
    assert _status_van(pad, eid) == "interrupted"


# ------------------------------------------------------ status en toegang --

def test_route_requires_authentication():
    assert lp.LabStatusView.requires_auth is True
    assert lp.LabStatusView.url == "/api/gold_scalper/lab/status"


def test_unauthenticated_request_is_refused(hass, panelen):
    _run(lp.async_setup_lab(hass))
    status, body = _get(hass, None)
    assert status == 401 and body == {"error": "unauthorized"}


def test_non_admin_is_refused(hass, panelen):
    _run(lp.async_setup_lab(hass))
    status, body = _get(hass, Gebruiker(False))
    assert status == 403 and body == {"error": "forbidden"}


def test_admin_gets_the_read_only_status(hass, panelen):
    _met_status(_lab_pad(hass), "registered", "queued", "running")
    _run(lp.async_setup_lab(hass))
    status, body = _get(hass, Gebruiker(True))
    assert status == 200
    assert body == {
        "api_version": 1, "authenticated": True, "backend": "reachable",
        "gold_scalper_version": INTEGRATION_VERSION, "invariant": INVARIANT,
        "lab_available": True, "lab_error": None,
        "lab_schema_version": LAB_SCHEMA_VERSION, "lab_schema_expected": LAB_SCHEMA_VERSION,
        "recovery_performed": True, "recovery_interrupted": 1, "experiment_count": 1,
    }


def test_status_contains_only_allowlisted_keys_and_plain_values(hass, panelen):
    _run(lp.async_setup_lab(hass))
    _, body = _get(hass, Gebruiker(True))
    assert set(body) == lp.STATUS_KEYS
    assert all(v is None or isinstance(v, (bool, int, str)) for v in body.values())


@pytest.mark.parametrize("kapot", [False, True])
def test_status_never_contains_paths_or_secrets(hass, panelen, kapot):
    if kapot:
        _lab_pad(hass).mkdir()
    _run(lp.async_setup_lab(hass))
    _, body = _get(hass, Gebruiker(True))
    tekst = json.dumps(body).lower()
    assert str(hass._map).lower() not in tekst
    assert LAB_DATABASE_FILENAME not in tekst and ".db" not in tekst and "/" not in tekst
    for verboden in ("token", "password", "wachtwoord", "api_key", "bearer", "secret",
                     "account", "epic", "balance", "position", "order"):
        assert verboden not in tekst
    if kapot:
        assert body["lab_available"] is False and body["lab_error"] == "open_failed"


def test_status_after_unload_says_not_loaded(hass, panelen):
    _run(lp.async_setup_lab(hass))
    _run(lp.async_unload_lab(hass))
    status, body = _get(hass, Gebruiker(True))
    assert status == 200 and body["lab_available"] is False and body["lab_error"] == "not_loaded"


def test_responses_are_not_cached(hass, panelen):
    _run(lp.async_setup_lab(hass))
    view = hass.http.views[0]
    for gebruiker in (None, Gebruiker(False), Gebruiker(True)):
        antwoord = _run(view.get({} if gebruiker is None else {"hass_user": gebruiker}))
        assert "no-store" in antwoord.headers["Cache-Control"]


# ------------------------------------------------ niets muterends in 9A ----

MUTEREND = {
    "create", "transition", "update_draft", "delete_draft", "add_parameters",
    "annotate", "reproduce", "begin_run", "update_progress", "complete_with_result",
    "save_segment_plan", "complete_segmented", "update_segment_progress",
    "save_walk_forward", "set_window_status", "store_wf_result", "store_selection",
    "store_validation_decision", "update_wf_progress", "end_run", "create_snapshot",
    # TEST-toegang, beoordeling, vergelijking:
    "open_test_result", "open_wf_test_result", "open_oos_aggregate",
    "create_assessment", "create_comparison",
}


def test_view_only_answers_get():
    for methode in ("post", "put", "patch", "delete"):
        assert not hasattr(lp.LabStatusView, methode)


def test_adapter_calls_no_mutating_lab_method():
    boom = ast.parse(BRON)
    aangeroepen = {n.func.attr for n in ast.walk(boom)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    # 5.7: de enige mutatie hier is ``end_run`` naar interrupted bij unload;
    # alle andere loopt via lab_actions.
    assert aangeroepen & MUTEREND == {"end_run"}
    assert BRON.count(".end_run(") == 1 and "INTERRUPT_REASON" in BRON


def test_adapter_imports_no_runner_worker_assessment_or_comparison():
    boom = ast.parse(BRON)
    modules = set()
    for n in ast.walk(boom):
        if isinstance(n, ast.ImportFrom):
            modules.add(("." * n.level) + (n.module or ""))
            modules.update(f"{n.module}.{a.name}" for a in n.names if n.module)
        elif isinstance(n, ast.Import):
            modules.update(a.name for a in n.names)
    for verboden in ("worker", "worker_entry", "assessment",
                     "comparison", "walk_forward", "datasets", "subprocess",
                     "multiprocessing", "coordinator", "broker", "lab_bridge",
                     "storage.database", "bar_archive", "config_entries"):
        assert not any(verboden in m.split(".") or m.endswith(verboden) for m in modules), verboden
    toegestaan_lab = {".experiment_lab", ".experiment_lab.storage", ".experiment_lab.wf_runner"}
    assert {m for m in modules if "experiment_lab" in m and m.startswith(".")} <= toegestaan_lab


class Spion:
    """Vervangt LabDatabase en legt elke aanroep met zijn argumenten vast."""

    log: list = []

    def __init__(self, *args, **kwargs):
        Spion.log.append(("__init__", args, kwargs))
        self._echt = LabDatabase(*args, **kwargs)

    def __getattr__(self, naam):
        doel = getattr(self._echt, naam)
        if not callable(doel):
            return doel

        def aanroep(*args, **kwargs):
            Spion.log.append((naam, args, kwargs))
            return doel(*args, **kwargs)
        return aanroep


def test_the_lab_receives_only_a_path_and_plain_values(hass, panelen, monkeypatch):
    Spion.log = []
    monkeypatch.setattr(lp, "LabDatabase", Spion)
    _met_status(_lab_pad(hass), "registered", "queued", "running")
    _run(lp.async_setup_lab(hass))
    _get(hass, Gebruiker(True))
    _run(lp.async_unload_lab(hass))
    namen = {naam for naam, _, _ in Spion.log}
    assert namen <= {"__init__", "open", "recover_interrupted", "schema_version",
                     "experiment_count", "close"}
    for _, args, kwargs in Spion.log:
        for waarde in (*args, *kwargs.values()):
            assert isinstance(waarde, (str, Path, bool, int)), type(waarde)


def test_no_worker_or_trading_reference_in_the_adapter():
    code = re.sub(r'""".*?"""', "", BRON, flags=re.S)
    code = "\n".join(r.split("#", 1)[0] for r in code.splitlines())
    for verboden in ("coordinator", "venue", "broker", "place_order", "close_position",
                     "config_entry", "async_update_entry", "hass.data[DOMAIN]",
                     ".get(DOMAIN", "Popen", "create_subprocess", "Thread(",
                     "run_walk_forward", "start_worker"):
        assert verboden not in code, verboden


def test_invariant_is_intact():
    assert INVARIANT == "EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING"
    assert "EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING" in BRON


def test_version_is_semver():
    # ha-gold-scalper begon op 1.0.0 (voortzetting van Goldscalper 5.7.0).
    assert len(INTEGRATION_VERSION.split(".")) == 3
    assert all(x.isdigit() for x in INTEGRATION_VERSION.split("."))
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == INTEGRATION_VERSION


# ---------------------------------------------------------------- frontend --

def _js_code():
    """De module zonder commentaar, zodat de controles de code zelf raken."""
    zonder_blok = re.sub(r"/\*.*?\*/", "", JS, flags=re.S)
    return "\n".join(r for r in zonder_blok.splitlines() if not r.strip().startswith("//"))


@pytest.mark.parametrize("verboden", [
    "http://", "https://", "//cdn", "<script", "import(", "import ", "require(",
    "eval(", "Function(", "setTimeout(\"", "setInterval(\"",
    "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
    "localStorage", "sessionStorage", "indexedDB", "document.cookie",
    "access_token", "token", "fetch(", "XMLHttpRequest", "WebSocket(",
    "window.open", "location.href", "postMessage",
])
def test_frontend_has_no_forbidden_construct(verboden):
    assert verboden not in _js_code()


def test_frontend_uses_text_content_and_the_status_route():
    code = _js_code()
    assert "textContent" in code
    assert 'callApi("GET", STATUS_PATH)' in code
    assert f'const STATUS_PATH = "{lp.LAB_STATUS_URL.removeprefix("/api/")}"' in code
    assert f'"{lp.LAB_WEBCOMPONENT}"' in code
    assert "customElements.get(ELEMENT_NAME)" in code      # geen dubbele define


def test_frontend_has_no_buttons_or_actions():
    code = _js_code()
    for verboden in ("<button", '"button"', "mwc-button", "ha-button", "onclick",
                     "addEventListener", "callService", "callWS", '"POST"', '"DELETE"'):
        assert verboden not in code, verboden


def test_frontend_shows_the_required_lines():
    for tekst in ("GOLD SCALPER LAB", "FASE 9A PANEL SPIKE", "Authenticatie", "Backend",
                  "API-versie", "Lab-database", "Gold Scalper-versie", "Lab-schema",
                  "Experimenten"):
        assert tekst in JS


def test_frontend_api_version_matches_backend():
    assert f"EXPECTED_API_VERSION = {lp.LAB_API_VERSION};" in JS


def test_cache_busting_follows_file_content(tmp_path):
    a = tmp_path / "a.js"
    a.write_text("const x = 1;", encoding="utf-8")
    eerste = lp.frontend_version(a)
    a.write_text("const x = 2;", encoding="utf-8")
    assert lp.frontend_version(a) != eerste
    assert eerste.startswith(INTEGRATION_VERSION + "-")
    assert lp.frontend_version() == lp.frontend_version(lp.LAB_JS_FILE)
