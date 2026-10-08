"""1.7.8: geen noodstop op een positie die we net zelf sloten.

Op 08-10 om 21:20:07 sloot de tijdstop DIAAAAYMFVR7YAY. De trade werd direct
als gesloten geboekt; in dezelfde cyclus draaide de brokercontrole en IG
toonde de positie nog. Gevolg: "staat open bij de broker maar niet in de
database" en een noodstop op een positie die al dicht was.

* Binnen de genadetermijn na een eigen sluitverzoek: geen noodstop.
* Na de termijn nog open: noodstop, met de melding dat de sluiting niet is
  uitgevoerd.
* Een positie die wij niet sloten: direct noodstop, zoals altijd.
* Een sluitverzoek dat de broker niet aanneemt, wordt niet als gesloten
  geboekt; de positie blijft bewaakt.
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

from gold_scalper.broker.adapter import OrderResult, VenuePosition  # noqa: E402
from gold_scalper.broker.reconcile_audit import (  # noqa: E402
    SLUIT_GENADE_SECONDEN, compare_positions,
)
from gold_scalper.broker.risk import TradingState  # noqa: E402

from test_broker_cycle import ScriptedVenue, _coordinator, _open_trade  # noqa: E402

TICKET = "DIAAAAYMFVR7YAY"


def _positie(ticket=TICKET):
    return VenuePosition(
        ticket=ticket, symbol="GOLD", side="buy", units=1.46,
        open_price=4130.45, current_price=4131.0, stop_loss=4122.77,
        take_profit=4140.0, unrealised_pnl=0.0,
    )


# ---------------- de vergelijking zelf ---------------- #

def test_binnen_termijn_geen_kritieke_bevinding():
    audit = compare_positions([_positie()], [], sluitingen={TICKET: 0.7})
    assert not audit.critical
    assert [f.code for f in audit.findings] == ["sluiting_onderweg"]


def test_na_termijn_kritiek_sluiting_niet_uitgevoerd():
    audit = compare_positions(
        [_positie()], [], sluitingen={TICKET: SLUIT_GENADE_SECONDEN + 1},
    )
    assert [f.code for f in audit.critical] == ["sluiting_niet_uitgevoerd"]
    assert "niet uitgevoerd" in audit.critical[0].message


def test_vreemde_positie_blijft_direct_kritiek():
    audit = compare_positions(
        [_positie("VREEMD")], [], sluitingen={TICKET: 1.0},
    )
    assert [f.code for f in audit.critical] == ["onbekende_positie"]


def test_genadetermijn_tussen_60_en_90_seconden():
    assert 60 <= SLUIT_GENADE_SECONDEN <= 90


# ---------------- de coordinator ---------------- #

class TraagSluitendeVenue(ScriptedVenue):
    """Neemt het sluitverzoek aan, maar toont de positie nog een tijd."""

    async def close(self, ticket, units=None):
        return OrderResult(success=True, ticket=ticket)


class WeigerendeVenue(ScriptedVenue):
    async def close(self, ticket, units=None):
        return OrderResult(success=False, ticket=ticket, error="REJECTED")


def _met_open_positie(venue, tmp_path, monkeypatch):
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    # Zelfde omvang, richting en niveaus als de trade uit _open_trade.
    asyncio.run(venue.place_order("GOLD", "sell", 1.76, stop_loss=4410.0,
                                  take_profit=4385.0))
    ticket = venue._positions[0].ticket
    _open_trade(coordinator.db, coordinator.run_id, ticket)
    coordinator._last_quote = asyncio.run(venue.quote())
    return coordinator, ticket


def _sluit_en_controleer(coordinator, ticket):
    positie = asyncio.run(coordinator._open_positions(refresh=True))[0]
    asyncio.run(coordinator._close_position(positie, "tijdstop"))
    asyncio.run(coordinator._audit_against_broker())


def test_race_binnen_termijn_geen_noodstop(tmp_path, monkeypatch):
    venue = TraagSluitendeVenue()
    coordinator, ticket = _met_open_positie(venue, tmp_path, monkeypatch)
    _sluit_en_controleer(coordinator, ticket)
    assert coordinator.db.open_trades(coordinator.run_id) == []
    assert coordinator.risk.state.state is not TradingState.HALTED, \
        coordinator.risk.state.halt_reason
    # Ook herstel (resume) binnen de termijn ziet hem niet als onbekend.
    asyncio.run(coordinator._reconcile())
    assert coordinator.risk.state.state is not TradingState.HALTED

    # De broker verwerkt de sluiting: het verzoek wordt vergeten.
    venue._positions.clear()
    asyncio.run(coordinator._audit_against_broker())
    assert coordinator._sluitverzoeken == {}


def test_na_termijn_nog_open_noodstop(tmp_path, monkeypatch, caplog):
    venue = TraagSluitendeVenue()
    coordinator, ticket = _met_open_positie(venue, tmp_path, monkeypatch)
    _sluit_en_controleer(coordinator, ticket)
    assert coordinator.risk.state.state is not TradingState.HALTED

    coordinator._sluitverzoeken[ticket] = (
        time.monotonic() - SLUIT_GENADE_SECONDEN - 5
    )
    with caplog.at_level("ERROR"):
        asyncio.run(coordinator._audit_against_broker())
    assert coordinator.risk.state.state is TradingState.HALTED
    assert "niet uitgevoerd" in coordinator.risk.state.halt_reason
    assert any("niet uitgevoerd" in r.getMessage() for r in caplog.records)


def test_vreemde_positie_direct_noodstop(tmp_path, monkeypatch):
    venue = TraagSluitendeVenue()
    coordinator, ticket = _met_open_positie(venue, tmp_path, monkeypatch)
    _sluit_en_controleer(coordinator, ticket)
    # Een positie die wij niet openden en niet sloten.
    asyncio.run(venue.place_order("GOLD", "buy", 1.0, stop_loss=4300.0,
                                  take_profit=4500.0))
    asyncio.run(coordinator._audit_against_broker())
    assert coordinator.risk.state.state is TradingState.HALTED
    assert "niet in de database" in coordinator.risk.state.halt_reason


def test_geweigerde_sluiting_niet_geboekt(tmp_path, monkeypatch):
    venue = WeigerendeVenue()
    coordinator, ticket = _met_open_positie(venue, tmp_path, monkeypatch)
    _sluit_en_controleer(coordinator, ticket)
    open_trades = coordinator.db.open_trades(coordinator.run_id)
    assert [t.broker_ticket for t in open_trades] == [ticket]
    assert ticket not in coordinator._sluitverzoeken
    assert coordinator.risk.state.state is not TradingState.HALTED


# ---------------- app-icoon ---------------- #

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _png_maat(pad: Path) -> tuple[int, int]:
    kop = pad.read_bytes()[:24]
    assert kop[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(kop[16:20], "big"), int.from_bytes(kop[20:24], "big")


def test_brand_iconen_aanwezig_en_juiste_maat():
    assert _png_maat(PKG / "brand" / "icon.png") == (256, 256)
    assert _png_maat(PKG / "brand" / "icon@2x.png") == (512, 512)


# ---------------- release ---------------- #

def test_version_is_consistent():
    from gold_scalper import const

    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION == "1.7.8"
    readme = (PKG.parent.parent / "README.md").read_text(encoding="utf-8")
    assert "Huidige versie: **1.7.8**" in readme
    changelog = (PKG.parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.split("## ")[1].startswith("1.7.8")
