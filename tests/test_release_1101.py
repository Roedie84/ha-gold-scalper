"""1.10.1: de terugval op de startbalans is geen equitymeting.

Gemeten in de leerronde van 10-10: na een herstart mislukte de
accountopvraging bij IG (weekend). De coordinator viel terug op de
startbalans (10.000) en schreef die als equitypunt weg, naast ~10 mln
demo-equity. `account_drawdown` gaf daarop 99,9 %.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))
sys.path.insert(0, HIER)

from gold_scalper.broker.adapter import VenueError  # noqa: E402
from gold_scalper.storage.database import TradeDatabase  # noqa: E402

from test_broker_cycle import FakeHass, ScriptedVenue  # noqa: E402
from test_release_175 import _bouw, _start  # noqa: E402


def _db(tmp_path):
    db = TradeDatabase(tmp_path / "dd.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    return db, run


def test_een_terugvalpunt_telt_niet_in_de_drawdown(tmp_path):
    db, run = _db(tmp_path)
    db.set_run_opening(run, 9_999_950.0, "EUR")
    for eq in (9_999_950.0, 9_999_990.0, 9_999_900.0):
        db.record_equity(run, eq, eq, 0, 0.0)
    db.record_equity(run, 10000.0, 10000.0, 0, 0.0)  # terugval, geen meting
    db.record_equity(run, 9_999_869.0, 9_999_869.0, 0, 0.0)

    dd = db.account_drawdown(run)

    assert dd["max_drawdown"] == pytest.approx(121.0)
    assert dd["max_drawdown_pct"] < 0.01
    assert dd["terugvalpunten_overgeslagen"] == 1
    assert dd["points"] == 4


def test_zonder_gemeten_opening_blijft_alles_staan(tmp_path):
    """Papier of een account rond de startbalans: niets wordt overgeslagen."""
    db, run = _db(tmp_path)
    for eq in (10000.0, 10100.0, 9900.0):
        db.record_equity(run, eq, eq, 0, 0.0)

    dd = db.account_drawdown(run)

    assert dd["max_drawdown"] == pytest.approx(200.0)
    assert dd["terugvalpunten_overgeslagen"] == 0


def test_opening_gelijk_aan_startbalans_slaat_niets_over(tmp_path):
    db, run = _db(tmp_path)
    db.set_run_opening(run, 10000.0, "EUR")
    for eq in (10050.0, 10000.0, 9950.0):
        db.record_equity(run, eq, eq, 0, 0.0)

    dd = db.account_drawdown(run)

    assert dd["terugvalpunten_overgeslagen"] == 0
    assert dd["max_drawdown"] == pytest.approx(100.0)


class ZonderAccount(ScriptedVenue):
    async def account(self):
        raise VenueError("time-out")


def _equitypunten(c):
    return c.db.conn.execute(
        "SELECT COUNT(*) AS n FROM equity WHERE run_id=?", (c.run_id,)
    ).fetchone()["n"]


def test_mislukte_opvraging_schrijft_geen_equitypunt():
    c = _start(_bouw(FakeHass(), ZonderAccount()))
    voor = _equitypunten(c)

    asyncio.run(c._async_update_data())

    assert _equitypunten(c) == voor


def test_gelukte_opvraging_schrijft_wel_een_equitypunt():
    c = _start(_bouw(FakeHass(), ScriptedVenue()))
    voor = _equitypunten(c)

    asyncio.run(c._async_update_data())

    assert _equitypunten(c) == voor + 1


def test_versie_1101():
    import json
    from pathlib import Path

    from gold_scalper import const

    pkg = Path(HIER).parent / "custom_components" / "gold_scalper"
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION == "1.10.1"
    root = pkg.parent.parent
    assert "Huidige versie: **1.10.1**" in (root / "README.md").read_text(encoding="utf-8")
    log = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert log.split("\n## ")[1].startswith("1.10.1")
