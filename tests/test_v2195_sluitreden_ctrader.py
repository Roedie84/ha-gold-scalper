"""2.19.5: onbekende sluitreden bij Pepperstone (cTrader) achteraf invullen.

Gemeten 22-10: bij XAUUSD (Pepperstone) was de sluitreden van 433 van de
1.681 trades onbekend (25,8 %), en ``achteraf_ingevuld`` stond op 0 terwijl
1.795 trades bij de broker gevonden waren. Het invullen werkte alleen met het
activiteitenoverzicht van IG (``channel``); cTrader heeft dat niet. Nu zegt de
sluitende order van cTrader wie sloot.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))

from gold_scalper.broker import ctrader as ct  # noqa: E402
from gold_scalper.learning.exit_stats import exit_stats  # noqa: E402
from gold_scalper.learning.sluitreden import reden_uit_broker  # noqa: E402

import test_v280_ctrader as basis  # noqa: E402
from test_v1100 import AlleenLezenVenue, GeheugenOpslag, _trade  # noqa: E402
from test_broker_cycle import _coordinator  # noqa: E402


# --- 1. de soort van de sluitende order ------------------------------------ #

def test_kanaal_van_order():
    assert ct.kanaal_van_order({"orderType": "STOP_LOSS_TAKE_PROFIT", "closingOrder": True}) == "SYSTEM"
    assert ct.kanaal_van_order({"orderType": 4}) == "SYSTEM"
    assert ct.kanaal_van_order({"orderType": "MARKET", "isStopOut": True}) == "SYSTEM"
    eigen = {"orderType": "MARKET", "closingOrder": True, "tradeData": {"label": "gold_scalper"}}
    assert ct.kanaal_van_order(eigen) == "OPEN_API"
    # Marktorder zonder ons label: kan met de hand zijn geweest - geen bewijs.
    assert ct.kanaal_van_order({"orderType": 1, "closingOrder": True, "tradeData": {}}) is None
    assert ct.kanaal_van_order(None) is None


# --- 2. reden uit het kanaal ------------------------------------------------ #

class T:
    def __init__(self, side="buy", doel=4415.0, stop=4390.0):
        self.side, self.take_profit, self.stop_loss = side, doel, stop
        self.open_time = "2026-10-22T08:00:00+00:00"
        self.close_time = "2026-10-22T08:05:00+00:00"


def test_doelorder_voorbij_het_doel_is_doel():
    # Long, doel 4415, gevuld op 4415,30 (beter dan het doel): doel, geen stop.
    r = reden_uit_broker(T("buy"), 4415.30, {"channel": "SYSTEM"}, None, None)
    assert r.reden == "take_profit"
    r = reden_uit_broker(T("sell", doel=4385.0, stop=4410.0), 4384.8, {"channel": "SYSTEM"}, None, None)
    assert r.reden == "take_profit"


def test_systeem_onder_het_doel_is_stop():
    # Verplaatste stop (break-even/volgstop) met slippage: stop.
    r = reden_uit_broker(T("buy"), 4401.37, {"channel": "SYSTEM"}, None, None)
    assert r.reden == "stop_loss"


def test_eigen_marktorder_is_eigen_exit():
    r = reden_uit_broker(T("buy"), 4401.0, {"channel": "OPEN_API"}, None, None)
    assert r.reden == "eigen_exit"


# --- 3. de venue: deal -> order -> kanaal ----------------------------------- #

def _broker_met_order(soort):
    def broker(bericht):
        t, mid = bericht["payloadType"], bericht.get("clientMsgId")
        if t == ct.DEALS_BY_POSITION_REQ:
            sluit = basis._sluitdeal()
            sluit["orderId"] = 555
            return [{"clientMsgId": mid, "payloadType": ct.DEALS_BY_POSITION_RES, "payload": {"deal": [
                {"dealId": 1, "positionId": 7, "tradeSide": "BUY",
                 "executionTimestamp": 1791999000000, "executionPrice": 4095.0, "orderId": 554},
                sluit]}}]
        if t == ct.ORDER_DETAILS_REQ:
            assert bericht["payload"]["orderId"] == 555
            return [{"clientMsgId": mid, "payloadType": ct.ORDER_DETAILS_RES, "payload": {
                "order": {"orderId": 555, "orderType": soort, "closingOrder": True,
                          "tradeData": {"label": "gold_scalper"}}}}]
        return basis._broker(bericht)
    return broker


@pytest.mark.asyncio
async def test_sluitkanaal_van_de_venue():
    v, ws = basis._venue()
    ws._antwoorden = _broker_met_order("STOP_LOSS_TAKE_PROFIT")
    open_t = datetime.fromtimestamp(1791999000, tz=timezone.utc)
    r = await v.sluitkanaal("7", "buy", 4095.0, open_t)
    assert r["channel"] == "SYSTEM" and r["exit_price"] == 4100.5
    assert r["order_type"] == "STOP_LOSS_TAKE_PROFIT" and r["activity_date"]
    # Alleen lezen: geen order, sluiting of wijziging verstuurd.
    soorten = {b["payloadType"] for b in ws.verstuurd}
    assert not soorten & {ct.NEW_ORDER_REQ, ct.CLOSE_POSITION_REQ, ct.AMEND_SLTP_REQ}
    await v.sluit_verbinding()


# --- 4. de afstemming vult ook oudere trades in, en vraagt niet eindeloos --- #

class CTraderAchtig(AlleenLezenVenue):
    """Venue zonder activiteitenoverzicht, met nazoeken per positie."""

    closed_deal_activity = None

    def __init__(self, kanalen):
        super().__init__()
        self.kanalen = kanalen
        self.gevraagd: list = []

    async def sluitkanaal(self, ticket, side=None, open_price=None, since=None):
        self.gevraagd.append(ticket)
        kanaal = self.kanalen.get(ticket)
        return {"exit_price": 4389.6, "channel": kanaal, "activity_date": None,
                "order_type": "STOP_LOSS_TAKE_PROFIT" if kanaal else "MARKET"}


def _oud_onbekend(coordinator, ticket, dagen):
    nu = datetime.now(timezone.utc)
    open_t = nu - timedelta(days=dagen)
    t = _trade(
        coordinator.run_id, ticket=ticket,
        open_time=open_t.isoformat(),
        close_time=(open_t + timedelta(seconds=300)).isoformat(),
        close_price=4389.6, close_reason="broker_gesloten_gemeten",
        original_close_reason="broker_gesloten_gemeten",
        reconciled_close_reason="unknown", reconciliation_status="reconciled",
        execution_semantics=2,
    )
    coordinator.db.insert_trade(t)


def test_oudere_onbekende_trades_ingevuld_en_niet_eindeloos_nagevraagd(tmp_path, monkeypatch):
    venue = CTraderAchtig({"OUD1": "SYSTEM", "OUD2": None})
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator._results_store = GeheugenOpslag()
    _oud_onbekend(coordinator, "OUD1", 8)    # buiten het venster van 3 dagen
    _oud_onbekend(coordinator, "OUD2", 6)
    assert exit_stats(coordinator.db.closed_trades(coordinator.run_id))["unknown"]["n"] == 2

    uitslag = asyncio.run(coordinator.async_reconcile())
    assert uitslag["sluitreden_ingevuld"] == 1
    per = {t.broker_ticket: t for t in coordinator.db.closed_trades(coordinator.run_id)}
    assert per["OUD1"].reconciled_close_reason == "stop_loss"
    assert per["OUD1"].close_reason_source == "afstemming"
    assert per["OUD1"].reconciliation_source == "ctrader_order"
    assert per["OUD1"].original_close_reason == "broker_gesloten_gemeten"   # blijft staan
    assert per["OUD2"].reconciled_close_reason == "unknown"
    assert per["OUD2"].close_reason_evidence.startswith("nagevraagd")
    assert coordinator.exit_stats["achteraf_ingevuld"] == 1

    # Volgende ronde: geen van beide opnieuw nagevraagd.
    venue.gevraagd.clear()
    asyncio.run(coordinator.async_reconcile())
    assert venue.gevraagd == []


def test_ig_houdt_het_venster_van_drie_dagen(tmp_path, monkeypatch):
    """Bij IG (activiteitenoverzicht) verandert er niets: geen oudere trades."""
    venue = AlleenLezenVenue(activiteit={"exit_price": 4389.6, "channel": "SYSTEM",
                                         "activity_date": None})
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator._results_store = GeheugenOpslag()
    _oud_onbekend(coordinator, "OUD1", 8)
    uitslag = asyncio.run(coordinator.async_reconcile())
    assert uitslag["sluitreden_ingevuld"] == 0
    assert "activity" not in venue.gelezen
