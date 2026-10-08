"""1.7.3: uitstapprijs navragen voordat een schatting blijft staan.

Op 8 oktober werden vier trades afgerekend op een geschatte uitstapprijs
(03:35, 04:55, 06:22, 09:21), drie terwijl HA gewoon draaide. De broker had
die posities zelf gesloten (stop of doel); het transactieoverzicht - de enige
bron die werd gevraagd - liep uren achter ("Slechts 1 transactie(s)"), en de
koers was op het moment van ontdekken al terug van het niveau, dus ook dat
viel af. Gevolg: sluitreden onbekend, kosten berekend, tot ~$10 per trade mis.

Wat hier vastligt:

* het activiteitenoverzicht wordt gevraagd als het transactieoverzicht niets
  heeft, en de bevestiging als de activiteit geen niveau noemt;
* de openingsactiviteit (zelfde dealId, instapprijs als niveau) telt nooit als
  sluiting;
* een vertraagde activiteit wordt een paar keer binnen enkele minuten
  nagevraagd, begrensd, en daarna niet meer;
* een voorlopige schatting krijgt bij correctie of afstemming meteen zijn
  sluitreden en gemeten kosten.
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import timedelta

import pytest

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))
sys.path.insert(0, HIER)

from gold_scalper.broker.ig_capital import IgVenue, match_activity  # noqa: E402
from gold_scalper.learning.afstemming import stem_af  # noqa: E402
from gold_scalper.storage.database import Trade  # noqa: E402

from test_broker_cycle import NOW, ScriptedVenue, _coordinator  # noqa: E402
from test_ig_capital import FakeSession  # noqa: E402


TICKET = "DIAAAAWZX1"


def _sluit_activiteit(level=4411.0, richting="SELL", ticket=TICKET, **extra):
    details = {
        "actions": [{"actionType": "POSITION_CLOSED", "affectedDealId": ticket}],
        "direction": richting, "dealReference": "SLUITREF1", "size": 0.1,
        "marketName": "Spot Gold",
    }
    if level is not None:
        details["level"] = level
    act = {
        "date": "2026-09-15T12:00:05", "dealId": "DIAAAACLOSE",
        "status": "ACCEPTED", "type": "POSITION", "channel": "SYSTEM",
        "details": details,
    }
    act.update(extra)
    return act


def _open_activiteit(ticket=TICKET, level=4400.30):
    return {
        "date": "2026-09-15T11:00:00", "dealId": ticket, "status": "ACCEPTED",
        "type": "POSITION", "channel": "PUBLIC_WEB_API",
        "details": {
            "actions": [{"actionType": "POSITION_OPENED", "affectedDealId": ticket}],
            "direction": "BUY", "level": level, "dealReference": "OPENREF",
        },
    }


# --------------------------------------------------------------------------
# De koppeling in het activiteitenoverzicht
# --------------------------------------------------------------------------


def test_the_closing_activity_gives_the_exit_price():
    m = match_activity([_open_activiteit(), _sluit_activiteit()], TICKET,
                       "buy", 4400.30)
    assert m["exit_price"] == pytest.approx(4411.0)
    assert m["source"] == "broker_activity"
    assert m["deal_reference"] == "SLUITREF1"


def test_the_opening_activity_is_never_a_close():
    """Zelfde dealId, maar het niveau is de instap: dat zou elke trade op nul
    zetten."""
    assert match_activity([_open_activiteit()], TICKET, "buy", 4400.30) is None


def test_a_close_in_the_same_direction_is_not_ours():
    act = _sluit_activiteit(richting="BUY")
    assert match_activity([act], TICKET, "buy", 4400.30) is None


def test_other_positions_do_not_match():
    act = _sluit_activiteit(ticket="DIAAAAANDERS")
    assert match_activity([act], TICKET, "buy", 4400.30) is None


def test_rejected_activities_do_not_count():
    act = _sluit_activiteit(status="REJECTED")
    assert match_activity([act], TICKET, "buy", 4400.30) is None


def test_a_nonsense_level_is_dropped():
    m = match_activity([_sluit_activiteit(level=1.2345)], TICKET, "buy", 4400.30)
    assert m is not None and m["exit_price"] is None


def test_capital_style_action_key_is_accepted():
    act = _sluit_activiteit()
    act["details"]["actions"] = [{"actionType": "POSITION_CLOSED", "dealId": TICKET}]
    assert match_activity([act], TICKET, "buy", 4400.30)["exit_price"] == 4411.0


# --------------------------------------------------------------------------
# De broker: activiteit, en de bevestiging als de activiteit geen niveau heeft
# --------------------------------------------------------------------------


def _ig(routes):
    return IgVenue(FakeSession(routes), "key", "user", "pass",
                   environment="demo", epic="GOLD", trading_enabled=True)


def test_venue_reads_the_activity_overview():
    venue = _ig({"/history/activity": ({"activities": [_sluit_activiteit()]}, 200)})
    m = asyncio.run(venue.closed_deal_activity(TICKET, "buy", 4400.30, NOW))
    assert m["exit_price"] == pytest.approx(4411.0)
    oproep = [c for c in venue._session.calls if "/history/activity" in c["url"]][0]
    assert oproep["params"]["detailed"] == "true"
    assert oproep["headers"]["Version"] == "3"


def test_activity_without_level_asks_the_confirmation():
    venue = _ig({
        "/history/activity": ({"activities": [_sluit_activiteit(level=None)]}, 200),
        "/confirms/SLUITREF1": ({"dealStatus": "ACCEPTED", "level": 4410.85}, 200),
    })
    m = asyncio.run(venue.closed_deal_activity(TICKET, "buy", 4400.30, NOW))
    assert m["exit_price"] == pytest.approx(4410.85)
    assert m["source"] == "broker_confirm"


def test_confirmation_without_level_stays_unknown():
    """Het scenario van 8 oktober in zijn kaalste vorm: de broker bevestigt de
    sluiting maar noemt (nog) geen niveau. Dan geen prijs verzinnen."""
    venue = _ig({
        "/history/activity": ({"activities": [_sluit_activiteit(level=None)]}, 200),
        "/confirms/SLUITREF1": ({"dealStatus": "ACCEPTED"}, 200),
    })
    assert asyncio.run(
        venue.closed_deal_activity(TICKET, "buy", 4400.30, NOW)
    ) is None


def test_no_closing_activity_yet_is_none():
    venue = _ig({"/history/activity": ({"activities": [_open_activiteit()]}, 200)})
    assert asyncio.run(
        venue.closed_deal_activity(TICKET, "buy", 4400.30, NOW)
    ) is None


# --------------------------------------------------------------------------
# De lus: schatting, herkansing, begrenzing
# --------------------------------------------------------------------------


@dataclass
class TraagOverzicht(ScriptedVenue):
    """Broker waarvan het transactieoverzicht achterloopt en waarvan het
    activiteitenoverzicht de sluiting pas na ``vertraging`` opvragingen kent."""

    vertraging: int = 0
    niveau: float | None = 4411.0
    activiteit_vragen: int = 0
    transactie_vragen: int = 0
    transactie: dict | None = None
    _log: list = field(default_factory=list)

    async def closed_deal(self, *args, **kwargs):
        self.transactie_vragen += 1
        return self.transactie

    async def closed_deal_activity(self, ticket, side=None, open_price=None,
                                   since=None):
        self.activiteit_vragen += 1
        if self.activiteit_vragen <= self.vertraging or self.niveau is None:
            return None
        return {"exit_price": self.niveau, "source": "broker_activity"}


def _open_trade(coordinator, ticket="T99"):
    coordinator.db.insert_trade(Trade(
        run_id=coordinator.run_id, mode="demo", symbol="GOLD", side="buy",
        volume=0.10, open_time=(NOW - timedelta(minutes=30)).isoformat(),
        open_price=4400.30, open_mid=4400.0, open_spread=0.60,
        stop_loss=4393.0, take_profit=4411.0, broker_ticket=ticket,
        execution_semantics=2,
    ))


def _gesloten(coordinator):
    return coordinator.db.closed_trades(coordinator.run_id)[0]


def _quote(venue):
    return asyncio.run(venue.quote())


def test_inline_activity_avoids_the_estimate(tmp_path, monkeypatch):
    """Transactieoverzicht leeg, koers terug tussen stop en doel: vroeger een
    schatting. Nu levert de activiteit meteen de prijs."""
    venue = TraagOverzicht()
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    _open_trade(coordinator)

    asyncio.run(coordinator._settle_vanished_positions(_quote(venue), NOW))

    t = _gesloten(coordinator)
    assert t.close_reason == "broker_gesloten_gemeten"
    assert t.close_price == pytest.approx(4411.0)
    assert t.reconciled_close_reason == "take_profit"
    assert t.reconciliation_source == "broker_activity"
    assert coordinator._geschatte_afwikkelingen == 0
    assert not coordinator._herkansingen


def test_a_delayed_activity_is_retried_and_corrects_everything(tmp_path,
                                                                monkeypatch):
    """De activiteit staat er pas bij de tweede herkansing: de trade wordt
    dan alsnog op de brokerprijs afgerekend, met sluitreden en gemeten
    kosten."""
    venue = TraagOverzicht(vertraging=2)
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    _open_trade(coordinator)

    asyncio.run(coordinator._settle_vanished_positions(_quote(venue), NOW))
    t = _gesloten(coordinator)
    assert t.close_reason == "broker_gesloten_geschat"
    assert t.reconciliation_status == "pending"
    assert venue.activiteit_vragen == 1

    # Te vroeg voor de eerste herkansing: geen verzoek.
    asyncio.run(coordinator._herkans_voorlopige_afwikkelingen(NOW + timedelta(seconds=5)))
    assert venue.activiteit_vragen == 1

    asyncio.run(coordinator._herkans_voorlopige_afwikkelingen(NOW + timedelta(seconds=25)))
    assert venue.activiteit_vragen == 2
    assert _gesloten(coordinator).reconciliation_status == "pending"

    asyncio.run(coordinator._herkans_voorlopige_afwikkelingen(NOW + timedelta(seconds=65)))
    t = _gesloten(coordinator)
    assert venue.activiteit_vragen == 3
    assert t.close_price == pytest.approx(4411.0)
    assert t.close_reason == "broker_gesloten_gecorrigeerd"
    assert t.original_close_reason == "broker_gesloten_geschat"
    assert t.reconciliation_status == "reconciled"
    assert t.reconciled_close_reason == "take_profit"
    assert t.reconciliation_source == "broker_activity"
    assert t.cost_source == "measured"
    # Netto op de brokerprijs: (4411.00 - 4400.30) * 10 oz.
    assert t.net_pnl == pytest.approx(107.0)
    assert not coordinator._herkansingen
    assert coordinator.db.estimated_trades(coordinator.run_id) == []


def test_retries_are_bounded(tmp_path, monkeypatch):
    """Hooguit vier herkansingen, ook als de lus nog uren doordraait."""
    from gold_scalper.coordinator import HERKANSING_SCHEMA

    venue = TraagOverzicht(niveau=None)
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    _open_trade(coordinator)
    asyncio.run(coordinator._settle_vanished_positions(_quote(venue), NOW))

    for s in range(0, 3600, 20):
        asyncio.run(coordinator._herkans_voorlopige_afwikkelingen(
            NOW + timedelta(seconds=s)))

    assert venue.activiteit_vragen == 1 + len(HERKANSING_SCHEMA)
    assert max(HERKANSING_SCHEMA) <= 300, "herkansen hoort binnen minuten klaar"
    assert not coordinator._herkansingen
    # Blijft voorlopig: de gewone correctie en afstemming nemen het over.
    t = _gesloten(coordinator)
    assert t.reconciliation_status == "pending"
    assert t.close_reason == "broker_gesloten_geschat"


def test_correction_from_transactions_measures_costs(tmp_path, monkeypatch):
    """Als het transactieoverzicht de trade later heeft, gaan sluitreden én
    kostenbron in één keer goed - niet eerst terug naar 'berekend'."""
    venue = TraagOverzicht(niveau=None)
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    _open_trade(coordinator)
    asyncio.run(coordinator._settle_vanished_positions(_quote(venue), NOW))
    assert _gesloten(coordinator).reconciliation_status == "pending"

    venue.transactie = {"exit_price": 4411.0, "profit_account": None}
    asyncio.run(coordinator._correct_estimated_settlements(NOW + timedelta(hours=3)))

    t = _gesloten(coordinator)
    assert t.reconciled_close_reason == "take_profit"
    assert t.reconciliation_status == "reconciled"
    assert t.cost_source == "measured"
    assert not coordinator._herkansingen


def test_the_retry_is_part_of_the_cycle():
    from pathlib import Path

    bron = (Path(HIER).parent / "custom_components" / "gold_scalper"
            / "coordinator.py").read_text(encoding="utf-8")
    lus = bron.split("async def _async_update_data")[1].split("\n    async def ")[0]
    assert "_herkans_voorlopige_afwikkelingen" in lus


# --------------------------------------------------------------------------
# Afstemming: een voorlopige schatting werkt sluitreden en kosten bij
# --------------------------------------------------------------------------


def _voorlopige_trade():
    t = Trade(
        run_id=1, mode="demo", symbol="GOLD", side="buy", volume=0.10,
        open_time=(NOW - timedelta(hours=1)).isoformat(), open_price=4400.30,
        open_mid=4400.0, open_spread=0.6,
        close_time=(NOW - timedelta(minutes=20)).isoformat(),
        close_price=4401.20, close_mid=4401.50, close_spread=0.6,
        net_pnl=9.0, close_reason="broker_gesloten_geschat",
        original_close_reason="broker_gesloten_geschat",
        reconciliation_status="pending", close_reason_source="estimated",
        broker_ticket=TICKET, cost_source="calculated", stop_loss=4393.0,
        take_profit=4411.0, execution_semantics=2,
    )
    t.id = 7
    return t


def _tx(close_level=4411.0):
    # Zonder openDateUtc: een zwakke koppeling (alleen instapprijs).
    return {
        "openLevel": "4400.30", "closeLevel": str(close_level),
        "profitAndLoss": "E94.16", "size": "10",
        "reference": "REF173",
        "instrumentName": "Spot Gold ($1) converted at 0.88",
        "dateUtc": (NOW - timedelta(minutes=19)).strftime("%Y-%m-%dT%H:%M:%S"),
    }


def test_reconciliation_adopts_the_broker_price_for_an_estimate():
    uitslag = stem_af([_voorlopige_trade()], [_tx()], 0.88, NOW)
    assert not uitslag.afwijkingen, "een schatting die verschilt is geen afwijking"
    velden = uitslag.overnames[0]["velden"]
    assert velden["close_price"] == pytest.approx(4411.0)
    assert velden["reconciled_close_reason"] == "take_profit"
    assert velden["reconciliation_status"] == "reconciled"
    assert velden["close_reason"] == "broker_gesloten_gecorrigeerd"
    assert velden["cost_source"] == "measured"
    assert uitslag.kosten_gemeten == 1
    assert uitslag.voorlopig_bijgewerkt == 1


def test_reconciliation_leaves_settled_trades_alone():
    """Voor een gewone trade blijft een groot verschil bij een zwakke
    koppeling een afwijking, zoals voorheen."""
    t = _voorlopige_trade()
    t.reconciliation_status = "reconciled"
    t.close_reason = "trailing_exit"
    t.original_close_reason = "trailing_exit"
    uitslag = stem_af([t], [_tx()], 0.88, NOW)
    assert uitslag.afwijkingen
    assert uitslag.voorlopig_bijgewerkt == 0
