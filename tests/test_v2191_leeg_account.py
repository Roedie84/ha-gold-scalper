"""2.19.1: een leeg accountantwoord (saldo en equity 0) is geen meting.

Gemeten 21-10 13:14:07: IG gaf één keer saldo 0 en equity 0 (ervoor en erna
~10,03 mln). De vloertoets zag 0 < 9,53 mln: NOODSTOP om 13:15, en de
*Max. drawdown* van de run bleef daarna op 100 % staan.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))
sys.path.insert(0, HIER)

from gold_scalper.broker.adapter import AccountSnapshot, VenueError  # noqa: E402
from gold_scalper.broker.risk import TradingState  # noqa: E402
from gold_scalper.coordinator import _leeg_accountantwoord  # noqa: E402
from gold_scalper.storage.database import TradeDatabase  # noqa: E402

from test_broker_cycle import FakeHass, ScriptedVenue  # noqa: E402
from test_ig_capital import ig  # noqa: E402
from test_release_175 import _bouw, _start  # noqa: E402


# ---------------- IG: ontbrekend saldo ----------------

def test_ig_zonder_saldo_in_het_antwoord_is_een_fout():
    venue = ig({"/accounts": ({"accounts": [
        {"accountId": "ACC1", "currency": "EUR", "balance": {}}]}, 200)})
    with pytest.raises(VenueError):
        asyncio.run(venue.account())


def test_ig_met_saldo_blijft_gewoon_werken():
    venue = ig({"/accounts": ({"accounts": [
        {"accountId": "ACC1", "currency": "EUR", "balance": {
            "balance": 10_030_425.0, "profitLoss": -7.0,
            "deposit": 1000.0, "available": 10_029_000.0}}]}, 200)})
    snap = asyncio.run(venue.account())
    assert snap.balance == pytest.approx(10_030_425.0)
    assert snap.equity == pytest.approx(10_030_418.0)


# ---------------- herkenning ----------------

def test_herkenning_leeg_antwoord():
    assert _leeg_accountantwoord(0.0, 0.0, 10_030_000.0)
    assert not _leeg_accountantwoord(0.0, 0.0, None)  # nooit iets gemeten
    assert not _leeg_accountantwoord(0.0, 0.0, 0.0)
    assert not _leeg_accountantwoord(10.0, 0.0, 10_030_000.0)
    assert not _leeg_accountantwoord(9_000_000.0, 9_000_000.0, 10_030_000.0)


# ---------------- cyclus ----------------

class EenKeerLeeg(ScriptedVenue):
    """Eerst een normaal saldo, dan één keer 0/0."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.leeg = False

    async def account(self):
        if self.leeg:
            return AccountSnapshot(balance=0.0, equity=0.0, margin_used=0.0,
                                   margin_available=0.0, currency="EUR",
                                   open_position_count=0)
        return await super().account()


def _equitypunten(c):
    return c.db.conn.execute(
        "SELECT COUNT(*) AS n FROM equity WHERE run_id=? AND equity=0",
        (c.run_id,),
    ).fetchone()["n"]


def test_cyclus_met_leeg_antwoord_geeft_geen_noodstop_en_geen_nulpunt():
    venue = EenKeerLeeg()
    c = _start(_bouw(FakeHass(), venue))
    asyncio.run(c._async_update_data())  # gemeten: 10.000
    assert c.current_equity == pytest.approx(10000.0)

    venue.leeg = True
    asyncio.run(c._async_update_data())

    assert c.risk.state.state is not TradingState.HALTED
    assert _equitypunten(c) == 0
    assert c.current_equity == pytest.approx(10000.0)


# ---------------- drawdown ----------------

def test_nulpunt_telt_niet_in_de_drawdown(tmp_path):
    db = TradeDatabase(tmp_path / "dd.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 1_000_000.0, None, "fp")
    db.set_run_opening(run, 10_030_000.0, "EUR")
    for eq in (10_030_000.0, 10_030_400.0, 0.0, 10_030_300.0):
        db.record_equity(run, eq, eq, 0, 0.0)

    dd = db.account_drawdown(run)

    assert dd["max_drawdown_pct"] < 0.01
    assert dd["max_drawdown"] == pytest.approx(100.0)
    assert dd["terugvalpunten_overgeslagen"] == 1


def test_zonder_opening_telt_alles_mee(tmp_path):
    """Zonder gemeten opening (NULL) mag de uitzondering niets wegfilteren."""
    db = TradeDatabase(tmp_path / "dd.db")
    db.connect()
    run = db.start_run("paper", "v1", "GOLD", {}, 10000.0, None, "fp")
    for eq in (10000.0, 10100.0, 9900.0):
        db.record_equity(run, eq, eq, 0, 0.0)

    dd = db.account_drawdown(run)

    assert dd["points"] == 3
    assert dd["max_drawdown"] == pytest.approx(200.0)
