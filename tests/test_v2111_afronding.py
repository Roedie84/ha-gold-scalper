"""2.11.1: noodstop door afronding van een IG-deelsluiting (15-10).

IG kreeg round(2.675, 2) = 2.67 te sluiten, de database boekte 2.675; daarna
gaf elke controle "broker meldt 2.68, database 2.67" en een noodstop.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker.adapter import VenuePosition  # noqa: E402
from gold_scalper.broker.reconcile_audit import afrondingsverschil  # noqa: E402
from gold_scalper.const import CONTRACT_SIZE  # noqa: E402


def _venue(confirm):
    import gold_scalper.broker.ig_capital as ig

    venue = ig.IgVenue.__new__(ig.IgVenue)
    venue.supports_trading = True
    verstuurd = {}

    async def posities(symbol=None):
        return [VenuePosition(ticket="D1", symbol="XAUUSD", side="buy", units=5.35, open_price=4200.0)]

    async def vraag(methode, pad, **k):
        if methode == "POST":
            verstuurd.update(k.get("json") or {})
            return {"dealReference": "ref"}
        return confirm
    venue.positions = posities
    venue._request = vraag
    return venue, verstuurd


def test_ig_geeft_de_afgeronde_omvang_terug(monkeypatch):
    import gold_scalper.broker.ig_capital as ig
    monkeypatch.setattr(ig, "CLOSE_CONFIRM_DELAYS", (0.0,))
    venue, verstuurd = _venue({"dealStatus": "ACCEPTED", "level": 4210.0})
    res = asyncio.run(venue.close("D1", 2.675))
    assert verstuurd["size"] == round(2.675, 2)
    assert res.success and res.units == verstuurd["size"]


def test_ig_neemt_de_bevestigde_omvang(monkeypatch):
    import gold_scalper.broker.ig_capital as ig
    monkeypatch.setattr(ig, "CLOSE_CONFIRM_DELAYS", (0.0,))
    venue, _ = _venue({"dealStatus": "ACCEPTED", "level": 4210.0, "size": 2.68})
    assert asyncio.run(venue.close("D1", 2.675)).units == 2.68


def test_afrondingsverschil():
    assert afrondingsverschil(2.68, 2.675)
    assert afrondingsverschil(2.68, 2.67)
    assert not afrondingsverschil(2.68, 2.68)
    assert not afrondingsverschil(2.68, 2.66)
    assert not afrondingsverschil(None, 2.67)


def test_herstel_zet_de_database_naar_de_broker_en_geen_noodstop():
    from gold_scalper.coordinator import GoldScalperCoordinator as C

    trade = SimpleNamespace(broker_ticket="D1", volume=2.675 / CONTRACT_SIZE)
    bijgewerkt = []

    async def uitvoeren(fn, *a):
        return fn(*a)
    zelf = SimpleNamespace(
        db=SimpleNamespace(update_trade=bijgewerkt.append),
        hass=SimpleNamespace(async_add_executor_job=uitvoeren),
    )
    positie = VenuePosition(ticket="D1", symbol="XAUUSD", side="buy", units=2.68, open_price=4200.0)
    assert asyncio.run(C._herstel_afronding(zelf, [positie], [trade])) == 1
    assert abs(trade.volume * CONTRACT_SIZE - 2.68) < 1e-9
    assert bijgewerkt == [trade]


def test_echt_verschil_blijft_een_noodstop():
    from gold_scalper.coordinator import GoldScalperCoordinator as C

    trade = SimpleNamespace(broker_ticket="D1", volume=2.5 / CONTRACT_SIZE)

    async def uitvoeren(fn, *a):
        return fn(*a)
    zelf = SimpleNamespace(db=None, hass=SimpleNamespace(async_add_executor_job=uitvoeren))
    positie = VenuePosition(ticket="D1", symbol="XAUUSD", side="buy", units=2.68, open_price=4200.0)
    assert asyncio.run(C._herstel_afronding(zelf, [positie], [trade])) == 0
    assert trade.volume == 2.5 / CONTRACT_SIZE
