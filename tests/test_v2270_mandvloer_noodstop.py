"""2.27.0 - L-GS-035, akkoord Ruud 31-10.

FARTCOIN, LTC, NEAR en PUMP bleven na elke herstart in een noodstop
"equity van de mand 3653 onder de ondergrens van 5000", terwijl de vloer
sinds 29-10 500.000 is en de mand op 993.686 staat. Buiten de mand waren ze
niet met gold_scalper.resume te bereiken. Een lid zet een mandvloer-noodstop
niet meer terug: de vloer van de hele mand wordt elke cyclus opnieuw
getoetst tegen de huidige startbalans.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.storage.state import StateStore, is_mandvloer_noodstop  # noqa: E402

MAND = ("equity van de mand 3653.14 onder de ondergrens van 5000.00 "
        "(configured_floor; geldt voor de hele mand)")


def _laad(raw, mandlid, entry="e_fartcoin-eur"):
    store = StateStore(None, entry)
    store._store._data = {entry: raw}
    state = asyncio.run(store.async_load(mandlid=mandlid))
    return store, state


def test_herkent_een_mandvloer_noodstop():
    assert is_mandvloer_noodstop(MAND)
    assert not is_mandvloer_noodstop("equity 4000.00 onder de ondergrens van 5000.00")
    assert not is_mandvloer_noodstop("dagverlies 10.05% bereikt de limiet")
    assert not is_mandvloer_noodstop(None)


def test_lid_zet_een_mandvloer_noodstop_niet_terug(caplog):
    import logging

    with caplog.at_level(logging.INFO):
        store, state = _laad({"halted": True, "halt_reason": MAND}, mandlid=True)
    assert not state.halted and state.halt_reason is None
    assert store.vervallen_noodstop == MAND
    assert "eerdere sessie blijft actief" not in caplog.text
    assert store._store._data["e_fartcoin-eur"]["halted"] is False


def test_hoofdlus_houdt_zijn_mandvloer_noodstop():
    _, state = _laad({"halted": True, "halt_reason": MAND}, mandlid=False, entry="e")
    assert state.halted and state.halt_reason == MAND


def test_lid_houdt_andere_noodstops():
    for reden in ("equity 4000.00 onder de ondergrens van 5000.00 (configured)",
                  "geen tickdata gedurende 900s tijdens handelsuren"):
        _, state = _laad({"halted": True, "halt_reason": reden}, mandlid=True)
        assert state.halted and state.halt_reason == reden


def test_coordinator_geeft_door_of_hij_een_lid_is():
    bron = open(os.path.join(os.path.dirname(__file__), "..", "custom_components",
                             "gold_scalper", "coordinator.py"), encoding="utf-8").read()
    assert 'async_load(\n            mandlid=getattr(self.entry, "hoofd_entry_id", None) is not None' in bron
