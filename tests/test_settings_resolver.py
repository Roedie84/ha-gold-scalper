"""Eén bron voor build_from_quotes.

De waarde stond in de basisconfiguratie én in de opties, en de opties wonnen
stilzwijgend. Wie het verbindingsformulier opnieuw invulde en de schakelaar
uitzette, veranderde niets: de bars werden zelf opgebouwd terwijl je dacht dat
ze van de broker kwamen.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.settings import candle_source, resolve

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
KEY = "build_from_quotes"


@pytest.mark.parametrize("data,options,effectief,herkomst", [
    ({}, {}, False, "default"),                          # nergens
    ({KEY: True}, {}, True, "data"),                     # alleen basis (oud)
    ({}, {KEY: False}, False, "options"),                # alleen opties
    ({KEY: False}, {KEY: True}, True, "options"),        # beide: jouw situatie
    ({KEY: True}, {KEY: False}, False, "options"),
])
def test_precedence(data, options, effectief, herkomst):
    r = resolve(data, options, KEY, False)
    assert r.effective is effectief and r.origin == herkomst


def test_your_situation_is_flagged_as_conflicting():
    """Basisconfiguratie uit, opties aan: de opties gelden, en dat verschil
    moet zichtbaar zijn in plaats van stil."""
    r = resolve({KEY: False}, {KEY: True}, KEY, False)
    assert r.conflicting and r.effective is True
    assert r.as_dict() == {
        "key": KEY, "configured": False, "override": True,
        "effective": True, "origin": "options", "conflicting": True,
    }


@pytest.mark.parametrize("data,options", [
    ({}, {}), ({KEY: True}, {}), ({}, {KEY: True}),
    ({KEY: False}, {KEY: True}), ({KEY: True}, {KEY: False}),
])
def test_resolver_and_options_form_agree(data, options):
    """Het optieformulier toont de waarde uit {**data, **options}. Dat moet
    altijd de effectieve waarde van de resolver zijn."""
    formulier = {**data, **options}.get(KEY, False)
    assert resolve(data, options, KEY, False).effective == formulier


def test_the_effective_value_does_not_change_without_a_user_action():
    """Er is geen migratie die schrijft: die zou de integratie herladen en kan
    de actieve waarde alleen veranderen, nooit verbeteren."""
    init = (PKG / "__init__.py").read_text(encoding="utf-8")
    coord = (PKG / "coordinator.py").read_text(encoding="utf-8")
    for bron in (init, coord):
        assert "async_update_entry" not in bron or KEY not in bron.split("async_update_entry")[1][:300]


def test_the_connection_form_writes_to_options():
    flow = (PKG / "config_flow.py").read_text(encoding="utf-8")
    blok = flow.split("# build_from_quotes hoort in de opties")[1][:1400]
    assert "options={**entry.options, **bars}" in blok
    assert "data=data, options=bars" in blok
    assert "k != CONF_BUILD_FROM_QUOTES" in blok


def test_the_coordinator_uses_the_resolver():
    coord = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "options.get(CONF_BUILD_FROM_QUOTES" not in coord
    assert "resolve(\n            entry.data, entry.options, CONF_BUILD_FROM_QUOTES" in coord


def test_one_name_for_the_candle_source_everywhere():
    coord = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert '"quotes" if self._build_from_quotes else "broker"' not in coord
    assert candle_source(True) == "quotes" and candle_source(False) == "broker"


def test_changing_the_candle_source_starts_a_new_run():
    coord = (PKG / "coordinator.py").read_text(encoding="utf-8")
    materiaal = coord.split("def _fingerprint_material")[1].split("\n    @staticmethod")[0]
    assert '"candle_source": candle_source(self._build_from_quotes)' in materiaal
