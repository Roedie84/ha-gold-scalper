"""2.6.1: bewezen verliezende groepen (tijdvak, scalp) gaan uit."""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.strategy import veldproef as V  # noqa: E402

BASIS = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")


def _reeks(n, gem, sd=40.0, zaad=1):
    rnd = random.Random(zaad)
    return [rnd.gauss(gem, sd) for _ in range(n)]


def test_tijdvak_als_groep_uit():
    per = {f"vp:{f}:1m": _reeks(30, -40.0, zaad=i) for i, f in enumerate(V.FAMILIES)}
    per["vp:momentum:5m"] = _reeks(80, 5.0)
    uit = V.uitgezette_opzetten(per)
    for f in V.FAMILIES:
        assert uit[f"vp:{f}:1m"]["groep"] == "1m"
    assert "vp:momentum:5m" not in uit


def test_kleine_groep_blijft_aan():
    per = {"vp:momentum:3m": _reeks(150, -40.0)}
    uit = V.uitgezette_opzetten(per)
    assert "vp:momentum:3m" in uit and "groep" not in uit["vp:momentum:3m"]  # eigen regel 2.5.6
    assert "vp:rsi_rev:3m" not in uit                                     # groep < 200


def test_groepsregel():
    assert V.GROEP_MIN_N == 200 and V.GROEP_MAX_T == -3.0
    assert V.groep_uitgezet(_reeks(199, -40.0)) is None
    assert V.groep_uitgezet(_reeks(250, -40.0))["n"] == 250
    assert V.groep_uitgezet(_reeks(250, 5.0)) is None


def test_scalp_en_turbo_volgen_de_groep():
    py = open(os.path.join(BASIS, "coordinator.py"), encoding="utf-8").read()
    assert "self.db.netto_per_strategie, STRATEGIE_SCALP" in py
    assert "strategie == STRATEGIE_SCALP and self._scalp_uitgezet and self.alles" in py
    assert "and not (self._scalp_uitgezet and self.alles)" in py
    assert 'f"alle {tf} (n=' in py


def test_versies():
    from gold_scalper.const import INTEGRATION_VERSION
    from gold_scalper.strategy import combinatie as C
    assert INTEGRATION_VERSION >= "2.6.1"
    assert V.VELDPROEF_VERSIE >= "veldproef-1.9.0"
    assert C.COMBINATIE_VERSIE >= "combinatie-1.7.0"
