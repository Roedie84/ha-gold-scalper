"""1.11.0 (L-GS-012): een afwikkelfout bij één trade legt de cyclus niet stil.

Op 12-10 02:21-03:21 gooide de uitstapprijs-zoektocht voor één verdwenen trade
een TypeError; elke cyclus faalde (360x) en de integratie was een uur
onbeschikbaar, zonder exitbeheer voor andere posities. Nu wordt de fout per
trade afgevangen: die trade blijft staan (herkansing volgende cyclus), de rest
van de cyclus loopt door, en in die cyclus komt er geen nieuwe instap.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper import coordinator as coord_mod  # noqa: E402
from gold_scalper.const import AFWIKKELFOUT_MELDING  # noqa: E402

from test_broker_cycle import NOW, ScriptedVenue, _coordinator, _open_trade  # noqa: E402


def _twee_verdwenen(tmp_path, monkeypatch):
    venue = ScriptedVenue()
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    for ticket in ("KAPOT", "GOED"):
        _open_trade(coordinator.db, coordinator.run_id, ticket)
    # Geen van beide staat nog bij de broker: allebei verdwenen.
    venue._positions.clear()
    coordinator._positions_cache = None

    async def zoek(trade):
        if str(trade.broker_ticket) == "KAPOT":
            raise TypeError("'<' not supported between instances of 'dict' and 'dict'")
        return None

    monkeypatch.setattr(coordinator, "_zoek_activiteit", zoek)
    meldingen: list = []
    import homeassistant.helpers.issue_registry as ir

    monkeypatch.setattr(ir, "async_create_issue",
                        lambda hass, domein, issue_id, **kw: meldingen.append((issue_id, kw)))
    monkeypatch.setattr(ir, "async_delete_issue",
                        lambda hass, domein, issue_id: meldingen.append(("weg", issue_id)))
    return coordinator, venue, meldingen


def _ronde(coordinator, venue):
    coordinator._afwikkeling_mislukt = False  # zoals aan het begin van de cyclus
    coordinator._positions_cache = None
    quote = asyncio.run(venue.quote())
    asyncio.run(coordinator._settle_vanished_positions(quote, NOW))


def _open(coordinator):
    return sorted(t.broker_ticket for t in coordinator.db.open_trades(coordinator.run_id))


def test_een_fout_raakt_alleen_die_trade(tmp_path, monkeypatch, caplog):
    coordinator, venue, _ = _twee_verdwenen(tmp_path, monkeypatch)
    with caplog.at_level("ERROR"):
        _ronde(coordinator, venue)  # geen uitzondering naar boven
    assert _open(coordinator) == ["KAPOT"], "de goede trade is wel afgewikkeld"
    assert coordinator._afwikkeling_mislukt is True
    assert coordinator._afwikkelfouten == {"KAPOT": 1}
    fouten = [r for r in caplog.records if "KAPOT" in r.getMessage()]
    assert len(fouten) == 1 and fouten[0].exc_info, "eenmaal, met traceback"


def test_herhaling_logt_niet_opnieuw_en_meldt_na_n_cycli(tmp_path, monkeypatch, caplog):
    coordinator, venue, meldingen = _twee_verdwenen(tmp_path, monkeypatch)
    with caplog.at_level("ERROR"):
        for _ in range(AFWIKKELFOUT_MELDING + 3):
            _ronde(coordinator, venue)
    assert coordinator._afwikkelfouten["KAPOT"] == AFWIKKELFOUT_MELDING + 3
    assert len([r for r in caplog.records if "KAPOT" in r.getMessage()]) == 1
    aangemaakt = [m for m in meldingen if m[0] != "weg"]
    assert len(aangemaakt) == 1, "precies één reparatiemelding"
    issue_id, kw = aangemaakt[0]
    assert issue_id == "afwikkeling_vast_KAPOT"
    assert kw["translation_key"] == "afwikkeling_vast"
    assert kw["translation_placeholders"]["ticket"] == "KAPOT"


def test_herstel_ruimt_teller_en_melding_op(tmp_path, monkeypatch):
    coordinator, venue, meldingen = _twee_verdwenen(tmp_path, monkeypatch)
    for _ in range(AFWIKKELFOUT_MELDING):
        _ronde(coordinator, venue)

    async def geen(trade):
        return None

    monkeypatch.setattr(coordinator, "_zoek_activiteit", geen)
    _ronde(coordinator, venue)
    assert _open(coordinator) == []
    assert coordinator._afwikkelfouten == {}
    assert coordinator._afwikkeling_mislukt is False
    assert ("weg", "afwikkeling_vast_KAPOT") in meldingen


def test_annuleren_wordt_niet_ingeslikt(tmp_path, monkeypatch):
    coordinator, venue, _ = _twee_verdwenen(tmp_path, monkeypatch)

    async def stop(trade):
        raise asyncio.CancelledError

    monkeypatch.setattr(coordinator, "_zoek_activiteit", stop)
    import pytest

    with pytest.raises(asyncio.CancelledError):
        _ronde(coordinator, venue)


BRON = Path(coord_mod.__file__).read_text(encoding="utf-8")


def test_geen_instap_in_een_cyclus_met_afwikkelfout():
    i = BRON.index('reject_reason = "handel staat uit"')
    stuk = BRON[i:i + 600]
    assert "elif self._afwikkeling_mislukt:" in stuk
    assert "geen instap deze cyclus" in stuk


def test_vlag_wordt_elke_cyclus_teruggezet():
    i = BRON.index("self._afwikkeling_mislukt = False  # 1.11.0")
    j = BRON.index("await self._settle_vanished_positions(quote, now)\n")
    assert i < j


def test_vertalingen_en_versie():
    import json

    basis = Path(coord_mod.__file__).parent
    for taal in ("nl", "en"):
        d = json.loads((basis / "translations" / f"{taal}.json").read_text(encoding="utf-8"))
        tekst = d["issues"]["afwikkeling_vast"]
        assert "{ticket}" in tekst["title"] and "{keer}" in tekst["description"]
    manifest = json.loads((basis / "manifest.json").read_text(encoding="utf-8"))
    assert tuple(map(int, manifest["version"].split("."))) >= (1, 11, 0)
    from gold_scalper.const import INTEGRATION_VERSION

    assert tuple(map(int, INTEGRATION_VERSION.split("."))) >= (1, 11, 0)
