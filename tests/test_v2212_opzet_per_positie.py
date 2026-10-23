"""2.21.2 - L-GS-019: opzet/strategie per open positie op de sensor.

Live 23-10 (2.21.0): Pepperstone 3x en IG 1x twee posities tegelijk open;
de sensor *Open posities* toonde alleen ticket/richting/prijzen, dus niet
welke opzet ze hield.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))

from gold_scalper.coordinator import GoldScalperCoordinator  # noqa: E402
from gold_scalper.posities import positie_regels  # noqa: E402


def _pos(ticket, side="sell", strategie=None):
    p = SimpleNamespace(ticket=ticket, side=side, units=33, open_price=3993.4,
                        stop_loss=3996.4, take_profit=3987.4)
    if strategie is not None:
        p.strategie = strategie
    return p


def _coord(strategie="alles", cache=None):
    c = object.__new__(GoldScalperCoordinator)
    c._strategie = strategie
    c._strategie_per_ticket = dict(cache or {})
    return c


def test_regel_toont_strategie_uit_de_kaart():
    regels = positie_regels([_pos("58807553")], {"58807553": "vp:inside:3m"})
    assert regels == [{
        "ticket": "58807553", "side": "sell", "units": 33, "open_price": 3993.4,
        "stop_loss": 3996.4, "take_profit": 3987.4, "strategie": "vp:inside:3m",
    }]


def test_regel_zonder_kaart_valt_terug_op_eigen_veld_of_none():
    assert positie_regels([_pos("1", strategie="daghandel")])[0]["strategie"] == "daghandel"
    assert positie_regels([_pos("2")])[0]["strategie"] is None
    assert positie_regels(None) == []


def test_coordinator_kaart_uit_cache_en_eigen_veld():
    c = _coord("alles", {"58807553": "vp:structuur_hl:3m"})
    kaart = c._strategie_per_positie(
        [_pos("58807553"), _pos("P1", strategie="vp:donchian:30m"), _pos("onbekend")])
    assert kaart == {"58807553": "vp:structuur_hl:3m", "P1": "vp:donchian:30m"}


def test_coordinator_een_strategie_is_de_primaire():
    c = _coord("scalp")
    assert c._strategie_per_positie([_pos("9")]) == {"9": "scalp"}


def test_sensor_gebruikt_positie_regels():
    with open(os.path.join(HIER, "..", "custom_components", "gold_scalper", "sensor.py"),
              encoding="utf-8") as f:
        bron = f.read()
    assert 'positie_regels(\n                d.get("open_positions"), d.get("strategie_per_positie"))' in bron
