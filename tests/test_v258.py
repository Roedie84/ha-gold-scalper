"""2.5.8: kolom 'Bij SL' (vastgezet of risico) in de open posities."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
import json
import os

BASIS = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")


def test_kolom_bij_sl():
    js = open(os.path.join(BASIS, "frontend", "broker-panel.js"), encoding="utf-8").read()
    assert ">Bij SL</th>" in js
    assert 'cel("Bij SL"' in js
    assert '"vastgezet" : "risico"' in js
    assert 'p.richting === "long" ? p.sl - p.instap : p.instap - p.sl' in js


def test_versie():
    from gold_scalper.const import INTEGRATION_VERSION
    assert INTEGRATION_VERSION >= "2.5.8"
    assert json.load(open(os.path.join(BASIS, "manifest.json")))["version"] == INTEGRATION_VERSION
