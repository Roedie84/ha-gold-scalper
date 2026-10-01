"""Experiment Lab, fase 1: eigen database, toestandsmachine, vergrendeling,
onveranderlijkheid, aantekeningen, reproductie en herstel.

De regels worden twee keer afgedwongen: in Python en in de database. De tests
hieronder die met ``_sql`` werken, gaan rechtstreeks naar SQLite en bewijzen
dat de database het ook zonder de Python-laag weigert.
"""
import hashlib
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.experiment_lab.models import (
    ALLOWED, LOCKED_AT_REGISTRATION, Experiment, IllegalTransition, Status,
    TERMINAL, canonical_json, config_hash,
)
from gold_scalper.experiment_lab.storage import (
    LAB_SCHEMA_VERSION, LabDatabase, LabDatabaseError, try_open,
)


def _volledig(**extra):
    velden = dict(
        name="Kortere tijdslimiet", type="challenger",
        hypothesis="Een tijdslimiet van 2 bars verandert de verdeling van resultaten",
        expected_effect="minder verliezers door stilstand", primary_metric="net_pnl",
        secondary_metrics=["trades", "median_hold"], evaluation_method="out_of_sample",
        hypothesis_family_id="tijdslimiet", software_version="5.5.0",
        strategy_version="scalp-0.2.0", execution_semantics_version=3,
        config_hash="abc",
    )
    velden.update(extra)
    return Experiment(**velden)


@pytest.fixture
def lab(tmp_path):
    db = LabDatabase(tmp_path / "gold_scalper_lab.db").open()
    yield db
    db.close()


def _sql(lab, query, *args):
    return lab.conn.execute(query, args)


#: Sinds fase 3 kan een experiment alleen voltooien mét opgeslagen resultaat;
#: sinds fase 4 met alle verplichte metrieken erbij.
from gold_scalper.experiment_lab.costs import build_cost_model  # noqa: E402
from gold_scalper.experiment_lab.metrics import compute_metrics  # noqa: E402

_KM = build_cost_model({"instrument_currency": "USD"})
_RESULTAAT = {
    "result_hash": "0" * 64, "summary": {"trades": 0}, "trades": [],
    "metrics": compute_metrics([], {"evaluations": 0, "rejections": {}}, [], 2, _KM),
    "breakdowns": [], "rejections": [], "cost_model": _KM, "provenance": {},
    "versions": {"result_schema_version": 2, "backtest_engine_version": 3,
                 "cost_model_version": 1, "metrics_version": 1},
}


def _door(lab, eid, *statussen):
    for s in statussen:
        if s == "completed":
            lab.complete_with_result(eid, _RESULTAAT)
        else:
            lab.transition(eid, s)


# ---------------- database ----------------

def test_the_lab_database_is_its_own_file(tmp_path):
    pad = tmp_path / "gold_scalper_lab.db"
    LabDatabase(pad).open().close()
    assert pad.exists()
    namen = {p.name for p in tmp_path.iterdir()}
    assert namen <= {"gold_scalper_lab.db", "gold_scalper_lab.db-journal"}


def test_the_trade_database_is_untouched(tmp_path):
    """Het Lab raakt de tradedatabase niet, ook niet bij een fout in het Lab."""
    from gold_scalper.storage.database import TradeDatabase

    trade_pad = tmp_path / "gold_scalper.db"
    tdb = TradeDatabase(trade_pad)
    tdb.connect()
    tdb.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    tdb.close()
    voor = hashlib.sha256(trade_pad.read_bytes()).hexdigest()

    lab = LabDatabase(tmp_path / "gold_scalper_lab.db").open()
    eid = lab.create(_volledig())
    with pytest.raises(sqlite3.DatabaseError):
        _sql(lab, "UPDATE experiments SET status='completed' WHERE id=?", eid)
    lab.close()
    assert hashlib.sha256(trade_pad.read_bytes()).hexdigest() == voor


def test_schema_initialisation_is_idempotent(tmp_path):
    pad = tmp_path / "l.db"
    for _ in range(3):
        db = LabDatabase(pad).open()
        assert db.schema_version() == LAB_SCHEMA_VERSION
        db.close()
    db = LabDatabase(pad).open()
    triggers = db.conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
    ).fetchone()[0]
    assert triggers == 143       # schema 9: +2 doelentabel, +2 doelbereik
    db.close()


def test_foreign_keys_are_enforced(lab):
    assert _sql(lab, "PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        _sql(lab, "INSERT INTO experiment_parameters (experiment_id, role, config_json, "
                  "config_hash) VALUES (999, 'baseline', '{}', 'x')")


def test_a_damaged_database_does_not_raise(tmp_path):
    """Een onbruikbare Lab-database mag de integratie niet tegenhouden."""
    pad = tmp_path / "kapot.db"
    pad.write_bytes(b"dit is geen sqlite-bestand" * 100)
    db, reden = try_open(pad)
    assert db is None and reden


def test_a_damaged_database_raises_a_controlled_error(tmp_path):
    pad = tmp_path / "kapot.db"
    pad.write_bytes(b"x" * 4096)
    with pytest.raises(LabDatabaseError):
        LabDatabase(pad).open()


# ---------------- toestandsmachine ----------------

def test_the_happy_path(lab):
    eid = lab.create(_volledig())
    _door(lab, eid, "registered", "queued", "running", "completed")
    exp = lab.get(eid)
    assert exp.status == "completed"
    assert exp.registered_at and exp.locked_at and exp.started_at and exp.finished_at


@pytest.mark.parametrize("pad", [
    ("registered", "cancelled"),
    ("registered", "queued", "cancelled"),
    ("registered", "queued", "running", "failed"),
    ("registered", "queued", "running", "interrupted"),
    ("registered", "queued", "running", "cancelled"),
    ("cancelled",),
])
def test_every_valid_path(lab, pad):
    eid = lab.create(_volledig())
    _door(lab, eid, *pad)
    assert lab.get(eid).status == pad[-1]


ILLEGAAL = [
    (van, naar) for van in Status for naar in Status
    if naar is not van and naar not in ALLOWED[van]
]


@pytest.mark.parametrize("van,naar", ILLEGAAL)
def test_every_illegal_transition_is_refused_by_python(van, naar):
    from gold_scalper.experiment_lab.models import check_transition
    with pytest.raises(IllegalTransition):
        check_transition(van, naar)


def _breng_naar(lab, doel):
    eid = lab.create(_volledig())
    route = {
        "draft": [], "registered": ["registered"],
        "queued": ["registered", "queued"],
        "running": ["registered", "queued", "running"],
        "completed": ["registered", "queued", "running", "completed"],
        "failed": ["registered", "queued", "running", "failed"],
        "interrupted": ["registered", "queued", "running", "interrupted"],
        "cancelled": ["cancelled"],
    }[doel]
    _door(lab, eid, *route)
    return eid


@pytest.mark.parametrize("van,naar", ILLEGAAL)
def test_every_illegal_transition_is_refused_by_the_database(lab, van, naar):
    """Rechtstreekse SQL, buiten Python om."""
    eid = _breng_naar(lab, van.value)
    with pytest.raises(sqlite3.DatabaseError):
        _sql(lab, "UPDATE experiments SET status=? WHERE id=?", naar.value, eid)
    assert lab.get(eid).status == van.value


def test_an_experiment_cannot_be_inserted_as_completed(lab):
    with pytest.raises(sqlite3.DatabaseError):
        _sql(lab, "INSERT INTO experiments (name, type, status, created_at) "
                  "VALUES ('x', 'baseline', 'completed', 'nu')")


def test_registering_requires_a_complete_hypothesis(lab):
    eid = lab.create(_volledig(primary_metric=""))
    with pytest.raises(sqlite3.DatabaseError):
        lab.transition(eid, "registered")
    assert lab.get(eid).status == "draft"


# ---------------- hypothesevergrendeling ----------------

@pytest.mark.parametrize("veld", LOCKED_AT_REGISTRATION)
def test_hypothesis_and_provenance_are_locked_after_registration(lab, veld):
    eid = lab.create(_volledig())
    lab.transition(eid, "registered")
    waarde = 42 if veld in ("execution_semantics_version", "reproduced_from") else "anders"
    with pytest.raises(sqlite3.DatabaseError):
        _sql(lab, f"UPDATE experiments SET {veld}=? WHERE id=?", waarde, eid)


def test_a_draft_can_still_be_edited(lab):
    eid = lab.create(_volledig())
    lab.update_draft(eid, hypothesis="scherper geformuleerd")
    assert lab.get(eid).hypothesis == "scherper geformuleerd"


def test_status_only_changes_through_the_state_machine(lab):
    eid = lab.create(_volledig())
    with pytest.raises(ValueError):
        lab.update_draft(eid, status="registered")


def test_parameters_are_locked_after_registration(lab):
    eid = lab.create(_volledig())
    lab.add_parameters(eid, "baseline", {"entry_threshold": 0.45})
    lab.transition(eid, "registered")
    with pytest.raises(sqlite3.DatabaseError):
        lab.add_parameters(eid, "challenger", {"entry_threshold": 0.5})
    with pytest.raises(sqlite3.DatabaseError):
        _sql(lab, "UPDATE experiment_parameters SET config_json='{}' WHERE experiment_id=?", eid)
    with pytest.raises(sqlite3.DatabaseError):
        _sql(lab, "DELETE FROM experiment_parameters WHERE experiment_id=?", eid)


# ---------------- onveranderlijkheid ----------------

@pytest.mark.parametrize("eind", ["completed", "failed", "interrupted", "cancelled"])
def test_a_finished_experiment_is_immutable(lab, eind):
    eid = _breng_naar(lab, eind)
    for veld, waarde in (("description", "anders"), ("error", "anders"),
                         ("finished_at", "anders"), ("started_at", "anders")):
        with pytest.raises(sqlite3.DatabaseError):
            _sql(lab, f"UPDATE experiments SET {veld}=? WHERE id=?", waarde, eid)


@pytest.mark.parametrize("eind", ["registered", "completed", "failed", "interrupted", "cancelled"])
def test_only_a_draft_can_be_deleted(lab, eind):
    eid = _breng_naar(lab, eind)
    with pytest.raises(sqlite3.DatabaseError):
        _sql(lab, "DELETE FROM experiments WHERE id=?", eid)
    assert lab.get(eid) is not None


def test_a_draft_that_was_reproduced_cannot_be_deleted(lab):
    """Anders verdwijnt de herkomst van de reproductie."""
    eid = lab.create(_volledig())
    lab.reproduce(eid, {})
    with pytest.raises(sqlite3.IntegrityError):
        lab.delete_draft(eid)


def test_a_plain_draft_can_be_deleted(lab):
    eid = lab.create(_volledig())
    lab.add_parameters(eid, "baseline", {"x": 1})
    lab.delete_draft(eid)
    assert lab.get(eid) is None


# ---------------- aantekeningen ----------------

@pytest.mark.parametrize("eind", ["completed", "failed", "interrupted", "cancelled"])
def test_annotations_can_be_added_after_closing(lab, eind):
    eid = _breng_naar(lab, eind)
    lab.annotate(eid, "correctie", "De kostenaanname bleek te laag.")
    assert len(lab.annotations(eid)) == 1


def test_annotations_are_append_only(lab):
    eid = _breng_naar(lab, "completed")
    aid = lab.annotate(eid, "noot", "eerste")
    with pytest.raises(sqlite3.DatabaseError):
        _sql(lab, "UPDATE experiment_annotations SET text='anders' WHERE id=?", aid)
    with pytest.raises(sqlite3.DatabaseError):
        _sql(lab, "DELETE FROM experiment_annotations WHERE id=?", aid)


# ---------------- reproductie ----------------

def test_a_reproduction_is_a_new_experiment(lab):
    orig = _breng_naar(lab, "completed")
    nieuw = lab.reproduce(orig, {"software_version": "5.6.0",
                                 "strategy_version": "scalp-0.2.0",
                                 "execution_semantics_version": 3})
    assert nieuw != orig
    r = lab.get(nieuw)
    assert r.reproduced_from == orig and r.status == "draft"
    assert r.hypothesis == lab.get(orig).hypothesis
    assert r.hypothesis_family_id == lab.get(orig).hypothesis_family_id
    assert r.software_version == "5.6.0"


def test_the_original_is_unchanged_by_reproduction(lab):
    orig = _breng_naar(lab, "completed")
    lab.conn.execute("SELECT 1")
    voor = dict(lab.conn.execute("SELECT * FROM experiments WHERE id=?", (orig,)).fetchone())
    lab.reproduce(orig, {})
    na = dict(lab.conn.execute("SELECT * FROM experiments WHERE id=?", (orig,)).fetchone())
    assert voor == na


def test_reproduction_copies_the_parameters(lab):
    eid = lab.create(_volledig())
    lab.add_parameters(eid, "baseline", {"entry_threshold": 0.45, "tp": 1.5})
    _door(lab, eid, "registered", "queued", "running", "completed")
    nieuw = lab.reproduce(eid, {})
    assert [p["config"] for p in lab.parameters(nieuw)] == \
        [p["config"] for p in lab.parameters(eid)]


def test_reproduced_from_must_exist(lab):
    with pytest.raises(sqlite3.IntegrityError):
        lab.create(_volledig(reproduced_from=12345))
    with pytest.raises(LabDatabaseError):
        lab.reproduce(12345, {})


# ---------------- herstel ----------------

def test_running_becomes_interrupted_on_reopen(tmp_path):
    pad = tmp_path / "l.db"
    db = LabDatabase(pad).open()
    eid = _breng_naar(db, "running")
    db.close()

    db = LabDatabase(pad).open(recover=True)          # opstarten
    exp = db.get(eid)
    assert exp.status == "interrupted"
    assert exp.finished_at and "onderbroken" in exp.error
    db.close()


def test_queued_is_not_touched_on_reopen(tmp_path):
    """Alleen wat werkelijk liep, is onderbroken."""
    pad = tmp_path / "l.db"
    db = LabDatabase(pad).open()
    eid = _breng_naar(db, "queued")
    db.close()
    db = LabDatabase(pad).open(recover=True)
    assert db.get(eid).status == "queued"
    db.close()


# ---------------- canoniek ----------------

def test_canonical_json_and_hash_are_order_independent():
    a = {"b": 1, "a": [1, 2], "c": {"y": 0.5, "x": "é"}}
    b = {"c": {"x": "é", "y": 0.5}, "a": [1, 2], "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert config_hash(a) == config_hash(b)
    assert config_hash(a) != config_hash({**a, "b": 2})


def test_nan_has_no_canonical_form():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_terminal_set_matches_the_brief():
    assert {s.value for s in TERMINAL} == {"completed", "failed", "interrupted", "cancelled"}


def test_an_ordinary_open_does_not_interrupt_a_running_experiment(tmp_path):
    """Herstel hoort bij het opstarten. Een gewone opening - door de runner of
    wie dan ook - mag een lopend experiment niet onderbreken."""
    pad = tmp_path / "l.db"
    db = LabDatabase(pad).open()
    eid = _breng_naar(db, "running")
    tweede = LabDatabase(pad).open()
    assert tweede.get(eid).status == "running"
    tweede.close()
    db.close()
