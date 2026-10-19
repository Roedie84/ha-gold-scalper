"""2.14.3: geen valse netting op een account dat de broker als hedged opgeeft.

19-10 01:30:06.324 sloot de stop van long 58459739; 4 ms later opende de
nieuwe short 58460015. De positievergelijking zag de long verdwijnen en
zette hedgen uit. Het account is volgens cTrader HEDGED (accountType 0).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from gold_scalper.broker import ctrader as ct
from gold_scalper.coordinator import GoldScalperCoordinator as G


def test_account_hedged_property():
    v = ct.CTraderVenue.__new__(ct.CTraderVenue)
    v.account_type = None
    assert v.account_hedged is None
    v.account_type = 0
    assert v.account_hedged is True
    v.account_type = "HEDGED"
    assert v.account_hedged is True
    v.account_type = 1
    assert v.account_hedged is False


@pytest.mark.asyncio
async def test_hedged_account_slaat_positievergelijking_over():
    gevraagd = []

    async def _open_positions(refresh=False):
        gevraagd.append(refresh)
        return []

    nep = SimpleNamespace(
        venue=SimpleNamespace(account_hedged=True), netting=None,
        _open_positions=_open_positions, _sluitverzoeken={}, _sluit_onderweg={},
    )
    voor = [SimpleNamespace(ticket="58459739", side="buy", units=30.0)]
    result = SimpleNamespace(ticket="58460015", verrekend=None)
    await G._controleer_netting(nep, result, -1, voor, voor, units=8.0)
    assert nep.netting is None and gevraagd == []


@pytest.mark.asyncio
async def test_bevestigde_verrekening_telt_ook_bij_hedged():
    meldingen = []

    async def alert(*a):
        meldingen.append(a)

    nep = SimpleNamespace(
        venue=SimpleNamespace(account_hedged=True), netting=None,
        notifier=SimpleNamespace(alert=alert),
    )
    result = SimpleNamespace(ticket="S1", verrekend=["L1"])
    await G._controleer_netting(nep, result, -1, [], [], units=8.0)
    assert nep.netting and nep.netting["verrekend"] == ["L1"] and meldingen
