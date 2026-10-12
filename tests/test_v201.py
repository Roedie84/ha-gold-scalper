"""2.0.1: een andere strategie start altijd een nieuwe run.

In 2.0.0 werd run 101 (scalpen) na de overstap op daghandel voortgezet: de
strategie stond op de standaardwaarde, niet zelf ingesteld, en telde daardoor
niet als wijziging van de opzet.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from test_broker_cycle import ScriptedVenue, _coordinator  # noqa: E402


def _met_opgeslagen_run(tmp_path, monkeypatch, strategie):
    c, _ = _coordinator(ScriptedVenue(), tmp_path, monkeypatch)
    c._strategie = strategie
    materiaal = c._fingerprint_material(c._run_config())
    c.db.conn.execute(
        "UPDATE runs SET config_json=? WHERE id=?",
        (json.dumps({"fingerprint_material": materiaal}), c.run_id),
    )
    c.db.conn.commit()
    return c


def test_scalp_naar_daghandel_is_een_nieuwe_run(tmp_path, monkeypatch):
    c = _met_opgeslagen_run(tmp_path, monkeypatch, "scalp")
    c._strategie = "daghandel"
    nieuw = c._fingerprint_material(c._run_config())
    assert asyncio.run(c._adoptable_run(nieuw, c._hash_material(nieuw))) is None
    assert "strategy" in c.run_changed_because


def test_zelfde_strategie_loopt_door(tmp_path, monkeypatch):
    c = _met_opgeslagen_run(tmp_path, monkeypatch, "daghandel")
    nieuw = c._fingerprint_material(c._run_config())
    run = asyncio.run(c._adoptable_run(nieuw, c._hash_material(nieuw)))
    # zelfde materiaal: geen verschillen, dus ook geen adoptie nodig
    assert run is None or run["id"] == c.run_id
    assert "strategy" not in (getattr(c, "run_changed_because", None) or [])
