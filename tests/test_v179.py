"""1.7.9: een sluiting pas boeken na bevestiging door IG.

* IG: na het sluitverzoek ``/confirms/{dealReference}``. ACCEPTED is gelukt,
  REJECTED is mislukt met de reden van IG, niets is onbekend.
* Coordinator: alleen ACCEPTED wordt geboekt. REJECTED niet, en de exitlogica
  mag het besluit opnieuw uitvoeren met wachttijd en limiet. Onbekend wordt
  "onderweg"; de positielijst beslist daarna.
* De 90-s-controle draait elke cyclus op de al opgehaalde positielijst, niet
  pas bij de volgende volledige controle.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper import coordinator as coord_mod  # noqa: E402
from gold_scalper.broker import ig_capital  # noqa: E402
from gold_scalper.broker.adapter import OrderResult  # noqa: E402
from gold_scalper.broker.exits import ExitAction  # noqa: E402
from gold_scalper.broker.reconcile_audit import SLUIT_GENADE_SECONDEN  # noqa: E402
from gold_scalper.broker.risk import TradingState  # noqa: E402

from test_broker_cycle import NOW, ScriptedVenue, _coordinator, _open_trade  # noqa: E402
from test_ig_capital import ig  # noqa: E402


# ---------------- IG: de bevestiging ---------------- #

POSITIES = ({"positions": [{
    "position": {"dealId": "T1", "direction": "BUY", "size": 10,
                 "level": 4663.0, "stopLevel": 4659.0},
    "market": {"epic": "GOLD", "bid": 4665.0},
}]}, 200)


def _ig_met_bevestiging(bevestiging, monkeypatch):
    wachttijden = []

    async def geen_wacht(s):
        wachttijden.append(s)

    monkeypatch.setattr(ig_capital.asyncio, "sleep", geen_wacht)
    routes = {"/positions/otc": ({"dealReference": "REF1"}, 200)}
    if bevestiging is not None:
        routes["/confirms/REF1"] = (bevestiging, 200)
    routes["/positions"] = POSITIES
    return ig(routes), wachttijden


def test_ig_accepted_is_gelukt(monkeypatch):
    venue, _ = _ig_met_bevestiging(
        {"dealStatus": "ACCEPTED", "dealId": "T1", "level": 4664.5}, monkeypatch,
    )
    r = asyncio.run(venue.close("T1"))
    assert r.success and not r.unconfirmed
    assert r.fill_price == 4664.5
    assert any("/confirms/REF1" in c["url"] for c in venue._session.calls)


def test_ig_rejected_is_mislukt_met_reden(monkeypatch):
    venue, _ = _ig_met_bevestiging(
        {"dealStatus": "REJECTED", "reason": "MARKET_CLOSED_WITH_EDITS"},
        monkeypatch,
    )
    r = asyncio.run(venue.close("T1"))
    assert not r.success and not r.unconfirmed
    assert "MARKET_CLOSED_WITH_EDITS" in r.error


def test_ig_geen_bevestiging_is_onbekend_na_herkansingen(monkeypatch):
    venue, wachttijden = _ig_met_bevestiging(None, monkeypatch)   # 404
    r = asyncio.run(venue.close("T1"))
    assert not r.success and r.unconfirmed
    assert wachttijden == [1.0, 3.0, 10.0]
    assert sum("/confirms/REF1" in c["url"] for c in venue._session.calls) == 4


# ---------------- coordinator ---------------- #

class BevestigendeVenue(ScriptedVenue):
    """Sluit naar keuze: geaccepteerd, afgewezen of onbekend."""

    uitkomst: str = "ACCEPTED"
    sluitverzoeken: int = 0

    async def close(self, ticket, units=None):
        self.sluitverzoeken += 1
        if self.uitkomst == "ACCEPTED":
            self._positions = [p for p in self._positions if p.ticket != ticket]
            return OrderResult(success=True, ticket=ticket)
        if self.uitkomst == "REJECTED":
            return OrderResult(success=False, ticket=ticket,
                               error="Sluiting afgewezen door IG: REJECT_X")
        return OrderResult(success=False, ticket=ticket, unconfirmed=True,
                           error="Geen bevestiging")


def _opzet(uitkomst, tmp_path, monkeypatch):
    venue = BevestigendeVenue()
    venue.uitkomst = uitkomst
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    asyncio.run(venue.place_order("GOLD", "sell", 1.76, stop_loss=4410.0,
                                  take_profit=4385.0))
    ticket = venue._positions[0].ticket
    _open_trade(coordinator.db, coordinator.run_id, ticket)
    coordinator._last_quote = asyncio.run(venue.quote())
    return coordinator, venue, ticket


def _sluit(coordinator):
    positie = asyncio.run(coordinator._open_positions(refresh=True))[0]
    asyncio.run(coordinator._close_position(positie, "tijdstop"))


def test_accepted_wordt_geboekt(tmp_path, monkeypatch):
    coordinator, _, ticket = _opzet("ACCEPTED", tmp_path, monkeypatch)
    _sluit(coordinator)
    assert coordinator.db.open_trades(coordinator.run_id) == []
    assert ticket in coordinator._sluitverzoeken


def _beheer(coordinator):
    """Eén beheerronde waarin de exitlogica 'sluiten' besluit."""
    coordinator.state.atr._rma._value = 2.0
    coordinator.exits.evaluate = lambda **kw: ExitAction("close", reason="tijdstop")
    coordinator._positions_cache = None
    asyncio.run(coordinator._manage_open_positions(
        asyncio.run(coordinator.venue.quote()), NOW,
    ))


def test_rejected_niet_geboekt_en_herhaald_met_limiet(tmp_path, monkeypatch, caplog):
    coordinator, venue, ticket = _opzet("REJECTED", tmp_path, monkeypatch)
    with caplog.at_level("ERROR"):
        _beheer(coordinator)
    assert venue.sluitverzoeken == 1
    assert [t.broker_ticket for t in coordinator.db.open_trades(coordinator.run_id)] == [ticket]
    assert any("REJECT_X" in r.getMessage() for r in caplog.records)
    assert ticket not in coordinator._sluitverzoeken

    # Binnen de wachttijd: geen nieuw verzoek, hoe vaak de lus ook draait.
    for _ in range(5):
        _beheer(coordinator)
    assert venue.sluitverzoeken == 1

    # Na de wachttijd hetzelfde besluit opnieuw, tot de limiet.
    for _ in range(20):
        staat = coordinator._sluit_pogingen[ticket]
        staat["volgende"] = 0.0
        _beheer(coordinator)
    assert venue.sluitverzoeken == coord_mod.SLUIT_MAX_POGINGEN
    assert coordinator._sluit_pogingen[ticket]["opgegeven"]
    assert coordinator.db.open_trades(coordinator.run_id)   # nog steeds bewaakt
    assert coordinator.risk.state.state is not TradingState.HALTED


def test_onbekend_onderweg_daarna_beslist_positielijst(tmp_path, monkeypatch):
    coordinator, venue, ticket = _opzet("UNKNOWN", tmp_path, monkeypatch)
    _sluit(coordinator)
    # Niet geboekt, wel onderweg; geen tweede verzoek zolang dat zo is.
    assert [t.broker_ticket for t in coordinator.db.open_trades(coordinator.run_id)] == [ticket]
    assert ticket in coordinator._sluit_onderweg
    _beheer(coordinator)
    assert venue.sluitverzoeken == 1

    # De broker blijkt hem wél gesloten te hebben: de positielijst beslist.
    venue._positions.clear()
    coordinator._positions_cache = None
    quote = asyncio.run(venue.quote())
    asyncio.run(coordinator._settle_vanished_positions(quote, NOW))
    asyncio.run(coordinator._bewaak_sluitingen())
    gesloten = coordinator.db.closed_trades(coordinator.run_id)
    assert len(gesloten) == 1
    assert coordinator._sluit_onderweg == {}


def test_onbekend_en_na_termijn_nog_open_blijft_bewaakt(tmp_path, monkeypatch):
    coordinator, venue, ticket = _opzet("UNKNOWN", tmp_path, monkeypatch)
    _sluit(coordinator)
    coordinator._sluit_onderweg[ticket]["sinds"] = (
        time.monotonic() - SLUIT_GENADE_SECONDEN - 5
    )
    coordinator._positions_cache = None
    asyncio.run(coordinator._bewaak_sluitingen())
    assert ticket not in coordinator._sluit_onderweg
    assert coordinator._sluit_pogingen[ticket]["weigeringen"] == 1
    assert coordinator.db.open_trades(coordinator.run_id)
    assert coordinator.risk.state.state is not TradingState.HALTED


class TellendeVenue(ScriptedVenue):
    """Neemt de sluiting aan maar toont de positie nog; telt ophalingen."""

    ophalingen: int = 0

    async def positions(self, symbol=None):
        self.ophalingen += 1
        return list(self._positions)

    async def close(self, ticket, units=None):
        return OrderResult(success=True, ticket=ticket)


def test_snelle_90s_controle_zonder_volledige_audit(tmp_path, monkeypatch, caplog):
    venue = TellendeVenue()
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    asyncio.run(venue.place_order("GOLD", "sell", 1.76, stop_loss=4410.0,
                                  take_profit=4385.0))
    ticket = venue._positions[0].ticket
    _open_trade(coordinator.db, coordinator.run_id, ticket)
    coordinator._last_quote = asyncio.run(venue.quote())
    _sluit(coordinator)

    # Binnen de termijn: niets.
    coordinator._positions_cache = None
    asyncio.run(coordinator._bewaak_sluitingen())
    assert coordinator.risk.state.state is not TradingState.HALTED

    # Na de termijn: direct noodstop, op de positielijst van deze cyclus.
    coordinator._sluitverzoeken[ticket] = time.monotonic() - SLUIT_GENADE_SECONDEN - 1
    asyncio.run(coordinator._open_positions(refresh=True))   # de cyclus haalt op
    voor = venue.ophalingen
    with caplog.at_level("ERROR"):
        asyncio.run(coordinator._bewaak_sluitingen())
    assert venue.ophalingen == voor, "geen extra verzoek bij de broker"
    assert coordinator.risk.state.state is TradingState.HALTED
    assert "niet uitgevoerd" in coordinator.risk.state.halt_reason
    assert any("niet uitgevoerd" in r.getMessage() for r in caplog.records)


def test_bewaking_zit_in_de_cyclus():
    bron = Path(coord_mod.__file__).read_text(encoding="utf-8")
    i = bron.index("await self._settle_vanished_positions(quote, now)\n")
    assert "await self._bewaak_sluitingen()" in bron[i:i + 300]
