"""1.10.2: time-out op het positie-overzicht is een tijdelijke brokerfout.

Live op 10-10 19:27: "IG antwoordde niet binnen 15s op GET /positions" vanuit
de positie-voorcheck in ``_async_update_data``. Die fout werd niet afgevangen,
HA logde "Unexpected error fetching gold_scalper" met traceback en alle
entiteiten waren 11 s onbeschikbaar. De koersopvraging vangt hetzelfde type al
af (1.7.0). Nu de voorcheck ook: laatste beeld vasthouden, niets beslissen.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.broker.adapter import VenueError, VenueQuote  # noqa: E402
from gold_scalper.const import KOERS_HOUD_MAX_MISLUKT  # noqa: E402

FOUT = "IG antwoordde niet binnen 15s op GET /positions."


def _opzet(tmp_path, monkeypatch):
    from test_broker_cycle import ScriptedVenue, _coordinator
    from test_unconfirmed_orders import _Signaal

    import gold_scalper.coordinator as co

    class TraagOverzicht(ScriptedVenue):
        faalt: bool = False

        async def quote(self, symbol=None):
            half = self.spread / 2
            return VenueQuote(bid=self.price - half, ask=self.price + half,
                              time=datetime.now(timezone.utc), tradeable=True)

        async def positions(self, symbol=None):
            if self.faalt:
                raise VenueError(FOUT)
            return await super().positions(symbol)

    aanroepen = []

    def altijd(*args):
        aanroepen.append(args)
        return _Signaal()

    monkeypatch.setattr(co, "evaluate", altijd)
    venue = TraagOverzicht()
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator.executor.venue = venue
    coordinator._enabled = True
    return coordinator, venue, aanroepen


def test_timeout_op_posities_houdt_het_laatste_beeld(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    vers = asyncio.run(coordinator._async_update_data())
    assert vers["koers_verouderd"] is False

    venue.faalt = True
    data = asyncio.run(coordinator._async_update_data())   # geen uitzondering

    assert data["koers_verouderd"] is True
    assert data["mislukte_opvraging"] == "Positie-opvraging"
    assert "/positions" in data["koers_fout"]
    assert data["signal"] is None
    assert data["risk"]["state"] == coordinator.risk.as_dict()["state"]


def test_bij_timeout_op_posities_wordt_niets_beslist(tmp_path, monkeypatch):
    coordinator, venue, aanroepen = _opzet(tmp_path, monkeypatch)
    asyncio.run(coordinator._async_update_data())
    orders, evaluaties = len(venue.orders), len(aanroepen)

    venue.faalt = True
    for _ in range(KOERS_HOUD_MAX_MISLUKT):
        asyncio.run(coordinator._async_update_data())

    assert len(venue.orders) == orders, "instap zonder positie-overzicht"
    assert len(aanroepen) == evaluaties, "strategie draaide zonder posities"


def test_aanhoudende_timeout_wordt_een_gewone_updatefout(tmp_path, monkeypatch):
    import gold_scalper.coordinator as co

    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    asyncio.run(coordinator._async_update_data())
    venue.faalt = True
    for _ in range(KOERS_HOUD_MAX_MISLUKT):
        asyncio.run(coordinator._async_update_data())
    # UpdateFailed logt HA als gewone storing, niet als "Unexpected error".
    with pytest.raises(co.UpdateFailed):
        asyncio.run(coordinator._async_update_data())


def test_zonder_eerder_beeld_meteen_updatefout(tmp_path, monkeypatch):
    import gold_scalper.coordinator as co

    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    venue.faalt = True
    with pytest.raises(co.UpdateFailed):
        asyncio.run(coordinator._async_update_data())


def test_herstel_na_timeout_op_posities(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    asyncio.run(coordinator._async_update_data())
    venue.faalt = True
    asyncio.run(coordinator._async_update_data())
    venue.faalt = False
    data = asyncio.run(coordinator._async_update_data())
    assert data["koers_verouderd"] is False
    assert coordinator.koers_verouderd is False


def test_versie_1102():
    import json
    from pathlib import Path

    from gold_scalper import const

    pkg = Path(os.path.dirname(__file__)).parent / "custom_components" / "gold_scalper"
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION == "1.10.2"
    root = pkg.parent.parent
    assert "Huidige versie: **1.10.2**" in (root / "README.md").read_text(encoding="utf-8")
    log = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert log.split("\n## ")[1].startswith("1.10.2")
