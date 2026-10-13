"""2.4.4: een mislukte accountopvraging geeft geen valse noodstop."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.broker.adapter import VenueError  # noqa: E402
from gold_scalper.broker.risk import TradingState  # noqa: E402

from test_v190 import _klok, _opzet, _richting, vaste_klok  # noqa: E402,F401


def test_geen_saldo_geen_noodstop_en_geen_instap(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    asyncio.run(coordinator._async_update_data())       # opwarmen, meet saldo
    # Zoals op 13-10: startbalans 1 mln, account ~10 mln, opening ~10 mln.
    coordinator.starting_balance = 1_000_000.0
    coordinator.opening_equity = 10_000_000.0
    coordinator.current_equity = 10_000_000.0
    orders_voor = len(venue.orders)

    async def kapot():
        raise VenueError("HTTP 403: error.public-api.exceeded-account-allowance")

    monkeypatch.setattr(venue, "account", kapot)
    _klok["extra"] += 3600                              # buiten de cooldown
    data = asyncio.run(coordinator._async_update_data())
    assert coordinator.risk.state.state is not TradingState.HALTED
    assert len(venue.orders) == orders_voor, "geen instap zonder saldo"
    assert "saldo van de broker niet op te vragen" in (data.get("reject_reason") or "")
    assert data.get("equity") == 10_000_000.0
