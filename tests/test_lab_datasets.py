"""Experiment Lab, fase 2: onveranderlijke datasetsnapshots, canonieke hash,
datakwaliteit, provenance, en de alleen-lezende brug naar het barsarchief."""
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.experiment_lab.datasets import (
    BLOCKED, HASH_VERSION, INFO, OK, WARNING, BarInput, DatasetError, DatasetSpec,
    MarketWindow, canonical_price, canonical_text, dataset_hash, prepare,
)
from gold_scalper.experiment_lab.models import Experiment
from gold_scalper.experiment_lab.storage import (
    DatasetIntegrityError, LabDatabase,
)

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
T0 = 1_790_000_100 - (1_790_000_100 % 900)      # op het M15-raster
NU = T0 + 900 * 1000
SPEC = DatasetSpec("CS.D.CFEGOLD.CEA.IP", "15m", 2, "instrument_metadata", "bar_archive")


def _bar(i, prijs=4300.0, **extra):
    velden = dict(ts=T0 + 900 * i, open=prijs, high=round(prijs + 1.5, 2),
                  low=round(prijs - 1.2, 2), close=round(prijs + 0.3, 2),
                  volume=120.0, source="quotes", bar_status="closed")
    velden.update(extra)
    return BarInput(**velden)


def _reeks(n=20, **extra):
    return [_bar(i, round(4300.0 + i * 0.37, 2), **extra) for i in range(n)]


def _codes(prepared):
    return {f.code: f for f in prepared.findings}


@pytest.fixture
def lab(tmp_path):
    db = LabDatabase(tmp_path / "gold_scalper_lab.db").open()
    yield db
    db.close()


# ---------------- hash ----------------

def test_same_input_same_hash():
    assert prepare(SPEC, _reeks(), None, NU).hash == prepare(SPEC, _reeks(), None, NU).hash


def test_the_hash_is_pinned():
    """Vastgepind op een bekende waarde: verandert de canonieke vorm ooit
    onbedoeld, dan valt deze test - en dan hoort HASH_VERSION omhoog."""
    bars = [BarInput(T0, 4300.12, 4301.5, 4299.0, 4300.5, 10.0, "broker", "closed")]
    tekst = canonical_text(SPEC, prepare(SPEC, bars, None, NU).bars)
    assert tekst == (
        f"GSLAB-DATASET|1|CS.D.CFEGOLD.CEA.IP|15m|UTC|2|1\n"
        f"{T0}|4300.12|4301.50|4299.00|4300.50|10.000000|broker|closed\n"
    )


@pytest.mark.parametrize("wijziging", [
    {"close": 4300.31}, {"source": "broker"}, {"bar_status": "incomplete"},
    {"volume": 121.0}, {"volume": None},
])
def test_any_relevant_difference_changes_the_hash(wijziging):
    basis = _reeks()
    ander = list(basis)
    ander[5] = BarInput(**{**{f: getattr(basis[5], f) for f in
                             ("ts", "open", "high", "low", "close", "volume",
                              "source", "bar_status")}, **wijziging})
    assert prepare(SPEC, basis, None, NU).hash != prepare(SPEC, ander, None, NU).hash


@pytest.mark.parametrize("veld,waarde", [("timeframe", "5m"), ("symbol", "GOLD"),
                                         ("instrument_precision", 3)])
def test_metadata_is_part_of_the_identity(veld, waarde):
    ander = DatasetSpec(**{**SPEC.__dict__, veld: waarde}) if hasattr(SPEC, "__dict__") \
        else DatasetSpec(**{f: getattr(SPEC, f) for f in SPEC.__slots__} | {veld: waarde})
    bars = _reeks() if veld != "timeframe" else [
        BarInput(T0 + 300 * i, 4300, 4301, 4299, 4300, 1.0, "quotes", "closed") for i in range(20)
    ]
    basis_bars = _reeks() if veld != "timeframe" else bars
    basis = prepare(SPEC if veld != "timeframe" else DatasetSpec(**{
        f: getattr(SPEC, f) for f in SPEC.__slots__}), basis_bars, None, NU)
    assert prepare(ander, bars, None, NU).hash != basis.hash


def test_prices_are_normalised_deterministically():
    """Geen binaire float als identiteit: 0.1 + 0.2 en 0.3 geven dezelfde prijs."""
    assert canonical_price(0.1 + 0.2, 2) == ("0.30", True)
    assert canonical_price(0.3, 2) == ("0.30", False)
    assert canonical_price(4300.125, 2)[0] == "4300.12"      # half-even
    assert canonical_price(4300.135, 2)[0] == "4300.14"


def test_timestamps_are_normalised_to_utc():
    cet = timezone(timedelta(hours=2))
    lokaal = datetime.fromtimestamp(T0, timezone.utc).astimezone(cet)
    a = prepare(SPEC, [_bar(0)], None, NU).hash
    b = prepare(SPEC, [_bar(0, ts=lokaal)], None, NU).hash
    assert a == b


def test_naive_timestamps_are_refused():
    with pytest.raises(DatasetError):
        prepare(SPEC, [_bar(0, ts=datetime(2026, 9, 29, 10, 0))], None, NU)


def test_out_of_order_input_is_sorted_and_reported():
    reeks = _reeks()
    geschud = reeks[10:] + reeks[:10]
    p = prepare(SPEC, geschud, None, NU)
    assert p.hash == prepare(SPEC, reeks, None, NU).hash
    assert _codes(p)["out_of_order_input"].severity == WARNING


# ---------------- kwaliteit ----------------

def test_exact_duplicates_are_kept_once_with_a_warning():
    p = prepare(SPEC, _reeks() + [_reeks()[3]], None, NU)
    assert len(p.bars) == 20 and _codes(p)["exact_duplicate"].severity == WARNING


def test_conflicting_duplicates_block():
    reeks = _reeks() + [_bar(3, 4400.0)]
    p = prepare(SPEC, reeks, None, NU)
    assert p.quality_status == BLOCKED and "conflicting_duplicate" in _codes(p)


@pytest.mark.parametrize("bar", [
    dict(open=4300, high=4299, low=4298, close=4298.5),     # open boven hoog
    dict(open=4300, high=4301, low=4299, close=4302),       # slot boven hoog
    dict(open=4300, high=4299, low=4301, close=4300),       # laag boven hoog
    dict(open=float("nan"), high=4301, low=4299, close=4300),
    dict(open=0.0, high=0.0, low=0.0, close=0.0),
])
def test_invalid_ohlc_blocks(bar):
    reeks = _reeks()
    reeks[4] = _bar(4, **bar)
    p = prepare(SPEC, reeks, None, NU)
    assert p.quality_status == BLOCKED and "invalid_ohlc" in _codes(p)


def test_a_flat_bar_is_kept_and_only_informational():
    reeks = _reeks()
    reeks[6] = _bar(6, open=4300, high=4300, low=4300, close=4300)
    p = prepare(SPEC, reeks, None, NU)
    assert len(p.bars) == 20
    assert _codes(p)["flat_bar"].severity == INFO
    assert p.quality_status == OK


def test_mixed_source_is_visible():
    reeks = _reeks()
    reeks[2] = _bar(2, 4300.74, source="broker")
    f = _codes(prepare(SPEC, reeks, None, NU))["mixed_source"]
    assert f.severity == WARNING and f.examples == [{"broker": 1, "quotes": 19}]


def test_invalid_volume_warns_but_does_not_block():
    reeks = _reeks()
    reeks[1] = _bar(1, 4300.37, volume=-5.0)
    p = prepare(SPEC, reeks, None, NU)
    assert p.quality_status == WARNING and "invalid_volume" in _codes(p)


def test_off_grid_timestamps_warn():
    reeks = _reeks()
    reeks[7] = _bar(7, 4302.59, ts=T0 + 900 * 7 + 17)
    assert _codes(prepare(SPEC, reeks, None, NU))["off_grid"].severity == WARNING


def test_an_incomplete_last_bar_is_flagged_not_removed():
    reeks = _reeks()
    p = prepare(SPEC, reeks, None, reeks[-1].ts + 100)     # laatste bar liep nog
    assert len(p.bars) == 20 and "incomplete_last_bar" in _codes(p)


def test_precision_loss_is_reported():
    reeks = _reeks()
    reeks[0] = _bar(0, 4300.123)
    assert "precision_loss" in _codes(prepare(SPEC, reeks, None, NU))


def test_a_fallback_precision_is_recorded():
    spec = DatasetSpec("X", "15m", 2, "fallback", "bar_archive")
    assert "precision_fallback" in _codes(prepare(spec, _reeks(), None, NU))


@pytest.mark.parametrize("kapot", [
    dict(symbol=""), dict(timeframe="7m"), dict(instrument_precision=-1),
    dict(timezone="Europe/Amsterdam"),
])
def test_missing_or_invalid_metadata_is_refused(kapot):
    velden = {f: getattr(SPEC, f) for f in SPEC.__slots__} | kapot
    with pytest.raises(DatasetError):
        prepare(DatasetSpec(**velden), _reeks(), None, NU)


def test_an_empty_dataset_does_not_exist():
    with pytest.raises(DatasetError):
        prepare(SPEC, [], None, NU)


# ---------------- gaten: ontbrekend, gesloten of onbekend ----------------

def _met_gat():
    return [b for i, b in enumerate(_reeks(20)) if i not in (8, 9, 10)]


def test_without_a_schedule_a_gap_is_unknown_not_missing():
    c = _codes(prepare(SPEC, _met_gat(), None, NU))
    assert c["unknown_market_expectation"].count == 3
    assert "missing_during_expected_market_hours" not in c
    assert prepare(SPEC, _met_gat(), None, NU).quality_status == OK


def test_a_gap_during_market_hours_is_missing():
    open_ = [MarketWindow(T0, T0 + 900 * 20)]
    c = _codes(prepare(SPEC, _met_gat(), open_, NU))
    assert c["missing_during_expected_market_hours"].count == 3


def test_a_gap_during_a_closure_is_expected():
    open_ = [MarketWindow(T0, T0 + 900 * 8), MarketWindow(T0 + 900 * 11, T0 + 900 * 20)]
    c = _codes(prepare(SPEC, _met_gat(), open_, NU))
    assert c["expected_market_closure"].count == 3
    assert "missing_during_expected_market_hours" not in c


def test_a_bar_during_a_closure_is_unexpected():
    open_ = [MarketWindow(T0, T0 + 900 * 5)]
    assert "unexpected_bar" in _codes(prepare(SPEC, _reeks(), open_, NU))


# ---------------- opslaan ----------------

def test_a_snapshot_satisfies_its_invariants(lab):
    p = prepare(SPEC, _reeks(50), None, NU)
    ds_id, hergebruikt = lab.create_snapshot(p, "test")
    assert not hergebruikt
    ds = lab.dataset(ds_id)
    telling = lab.conn.execute(
        "SELECT COUNT(*), MIN(ts), MAX(ts) FROM dataset_bars WHERE dataset_id=?", (ds_id,)
    ).fetchone()
    assert telling[0] == ds["bar_count"] == 50
    assert telling[1] == ds["start_ts"] and telling[2] == ds["end_ts"]
    assert dataset_hash(SPEC, lab.dataset_bars(ds_id)) == ds["hash"]
    assert lab.verify_dataset(ds_id)["ok"]
    assert ds["hash_version"] == HASH_VERSION and ds["sealed"] == 1


def test_a_failure_halfway_leaves_nothing(lab):
    """Een fout bij bar 12.000 van 20.000 mag geen half bruikbare dataset
    achterlaten: alles wordt teruggedraaid."""
    p = prepare(SPEC, _reeks(30), None, NU)
    p.bars.append(p.bars[10])          # dubbele sleutel halverwege de invoeging
    p.hash = dataset_hash(SPEC, p.bars)
    with pytest.raises(sqlite3.IntegrityError):
        lab.create_snapshot(p, "test")
    assert lab.conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 0
    assert lab.conn.execute("SELECT COUNT(*) FROM dataset_bars").fetchone()[0] == 0


def test_a_tampered_hash_is_refused_before_storing(lab):
    p = prepare(SPEC, _reeks(), None, NU)
    p.hash = "0" * 64
    with pytest.raises(DatasetIntegrityError):
        lab.create_snapshot(p, "test")


def test_an_identical_snapshot_is_not_stored_twice(lab):
    a, _ = lab.create_snapshot(prepare(SPEC, _reeks(), None, NU), "eerste")
    b, hergebruikt = lab.create_snapshot(prepare(SPEC, _reeks(), None, NU), "tweede")
    assert a == b and hergebruikt
    assert lab.conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 1
    assert lab.conn.execute("SELECT COUNT(*) FROM dataset_bars").fetchone()[0] == 20
    aanvragen = lab.conn.execute(
        "SELECT reused FROM dataset_requests ORDER BY id").fetchall()
    assert [r[0] for r in aanvragen] == [0, 1]


def test_reuse_checks_more_than_the_hash(lab):
    """Een hash-match met afwijkende metadata wordt niet blind hergebruikt."""
    ds_id, _ = lab.create_snapshot(prepare(SPEC, _reeks(), None, NU), "eerste")
    # simuleer een corrupte opgeslagen rij buiten de triggers om
    lab.conn.execute("PRAGMA ignore_check_constraints = ON")
    lab.conn.execute("DROP TRIGGER ds_update")
    lab.conn.execute("UPDATE datasets SET bar_count = 21 WHERE id=?", (ds_id,))
    with pytest.raises(DatasetIntegrityError):
        lab.create_snapshot(prepare(SPEC, _reeks(), None, NU), "tweede")


# ---------------- onveranderlijkheid ----------------

@pytest.fixture
def snapshot(lab):
    ds_id, _ = lab.create_snapshot(prepare(SPEC, _reeks(), None, NU), "test")
    return ds_id


@pytest.mark.parametrize("sql", [
    "UPDATE dataset_bars SET close = close + 1 WHERE dataset_id = {id}",
    "DELETE FROM dataset_bars WHERE dataset_id = {id}",
    "INSERT INTO dataset_bars VALUES ({id}, 1, 1, 1, 1, 1, NULL, 'x', 'closed')",
    "UPDATE datasets SET hash = 'x' WHERE id = {id}",
    "UPDATE datasets SET bar_count = 99 WHERE id = {id}",
    "UPDATE datasets SET quality_json = '[]' WHERE id = {id}",
    "UPDATE datasets SET sealed = 0 WHERE id = {id}",
    "DELETE FROM datasets WHERE id = {id}",
])
def test_a_snapshot_is_immutable_in_the_database(lab, snapshot, sql):
    with pytest.raises(sqlite3.DatabaseError):
        lab.conn.execute(sql.format(id=snapshot))
    assert lab.verify_dataset(snapshot)["ok"]


def test_dataset_requests_are_append_only(lab, snapshot):
    with pytest.raises(sqlite3.DatabaseError):
        lab.conn.execute("DELETE FROM dataset_requests")


# ---------------- koppeling aan een experiment ----------------

def _exp(**extra):
    return Experiment(name="x", type="baseline", hypothesis="h", expected_effect="e",
                      primary_metric="net_pnl", evaluation_method="oos",
                      hypothesis_family_id="f", **extra)


def test_a_draft_can_change_its_dataset(lab, snapshot):
    ander, _ = lab.create_snapshot(prepare(SPEC, _reeks(21), None, NU), "test")
    eid = lab.create(_exp(dataset_id=snapshot))
    lab.update_draft(eid, dataset_id=ander)
    assert lab.get(eid).dataset_id == ander


def test_a_registered_experiment_cannot_be_moved_to_another_dataset(lab, snapshot):
    ander, _ = lab.create_snapshot(prepare(SPEC, _reeks(21), None, NU), "test")
    eid = lab.create(_exp(dataset_id=snapshot))
    lab.transition(eid, "registered")
    with pytest.raises(sqlite3.DatabaseError):
        lab.conn.execute("UPDATE experiments SET dataset_id=? WHERE id=?", (ander, eid))


def test_an_experiment_cannot_point_to_a_missing_dataset(lab):
    with pytest.raises(sqlite3.IntegrityError):
        lab.create(_exp(dataset_id=9999))


def test_a_reproduction_uses_the_same_snapshot(lab, snapshot):
    eid = lab.create(_exp(dataset_id=snapshot))
    assert lab.get(lab.reproduce(eid, {})).dataset_id == snapshot


def test_migration_from_schema_1(tmp_path):
    """Een database van fase 1 krijgt schema 2 zonder dat iets verloren gaat."""
    from gold_scalper.experiment_lab import storage as st

    pad = tmp_path / "v1.db"
    conn = sqlite3.connect(pad, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("BEGIN")
    for stap in st.MIGRATIONS[1]:
        conn.execute(stap)
    conn.execute("INSERT INTO lab_meta VALUES ('schema_version', '1')")
    conn.execute("INSERT INTO experiments (name, type, status, created_at) "
                 "VALUES ('oud', 'baseline', 'draft', 'nu')")
    conn.execute("COMMIT")
    conn.close()

    db = LabDatabase(pad).open()
    assert db.schema_version() == st.LAB_SCHEMA_VERSION == 9      # 5.7: doelentabel en idempotentie
    assert db.get(1).name == "oud" and db.get(1).dataset_id is None
    db.close()
    LabDatabase(pad).open().close()            # tweede keer: idempotent


# ---------------- brug ----------------

def _archief(tmp_path, bars):
    from gold_scalper.analysis.signals import Candles
    from gold_scalper.storage.bar_archive import BarArchive

    arch = BarArchive(tmp_path / "gold_scalper_bars.db")
    arch.connect()
    c = Candles([b.ts for b in bars], [b.open for b in bars], [b.high for b in bars],
                [b.low for b in bars], [b.close for b in bars], [b.volume for b in bars])
    arch.store(SPEC.symbol, "15m", c, "quotes")
    return arch


def test_the_bridge_delivers_only_plain_immutable_data(tmp_path):
    from dataclasses import FrozenInstanceError, fields
    from gold_scalper.lab_bridge import ArchiveReader

    arch = _archief(tmp_path, _reeks())
    lezer = ArchiveReader(arch.path)
    bars = lezer.read_bars(SPEC.symbol, "15m", NU)
    assert isinstance(bars, tuple) and len(bars) == 20
    for b in bars:
        assert type(b) is BarInput
        for f in fields(b):
            assert type(getattr(b, f.name)) in (int, float, str, type(None)), f.name
    with pytest.raises(FrozenInstanceError):
        bars[0].close = 1.0


def test_the_bridge_connection_cannot_write(tmp_path):
    """Niet afgesproken, maar afgedwongen: SQLite weigert schrijven."""
    from gold_scalper.lab_bridge import ArchiveReader

    arch = _archief(tmp_path, _reeks())
    lezer = ArchiveReader(arch.path)
    with pytest.raises(sqlite3.OperationalError):
        lezer._conn.execute("DELETE FROM bars")
    assert len(lezer.read_bars(SPEC.symbol, "15m", NU)) == 20


def test_the_bridge_has_no_write_path_in_its_code():
    tekst = (PKG / "lab_bridge.py").read_text(encoding="utf-8")
    code = "\n".join(r for r in tekst.splitlines() if not r.strip().startswith("#"))
    code = code.split('"""', 2)[-1]                     # modulebeschrijving overslaan
    for verboden in ("INSERT", "UPDATE", "DELETE", "REPLACE", ".store(",
                     "prune", "repair", "BarArchive(", "hass", "coordinator"):
        assert verboden not in code, verboden
    assert "mode=ro" in code


def test_a_changed_archive_does_not_change_an_existing_snapshot(tmp_path, lab):
    from gold_scalper.analysis.signals import Candles
    from gold_scalper.lab_bridge import ArchiveReader, dataset_spec

    arch = _archief(tmp_path, _reeks())
    spec = dataset_spec(SPEC.symbol, "15m", 2)
    lezer = ArchiveReader(arch.path)
    eerste, _ = lab.create_snapshot(
        prepare(spec, list(lezer.read_bars(SPEC.symbol, "15m", NU)), None, NU), "archief")
    voor = lab.dataset(eerste)["hash"]

    # het archief wordt gerepareerd: één bar krijgt een andere slotkoers
    b = _reeks()[5]
    arch.store(SPEC.symbol, "15m", Candles([b.ts], [b.open], [b.high], [b.low],
                                             [b.close + 0.5], [b.volume]), "quotes")

    assert lab.dataset(eerste)["hash"] == voor and lab.verify_dataset(eerste)["ok"]
    tweede, hergebruikt = lab.create_snapshot(
        prepare(spec, list(lezer.read_bars(SPEC.symbol, "15m", NU)), None, NU), "archief")
    assert tweede != eerste and not hergebruikt
    assert lab.dataset(tweede)["hash"] != voor


def test_market_windows_come_from_the_schedule_as_plain_data():
    from gold_scalper.lab_bridge import market_windows

    maandag = int(datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc).timestamp())
    vensters = market_windows(maandag, maandag + 7 * 86400, "15m")
    assert vensters and all(type(v) is MarketWindow for v in vensters)
    # de weekendsluiting valt buiten elk venster
    zaterdag = maandag + 5 * 86400 + 12 * 3600
    assert not any(v.start_ts <= zaterdag < v.end_ts for v in vensters)
