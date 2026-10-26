"""2.24.1 - *Open posities* telt bij de Bitvavo-mand de hele mand.

Live 26-10 15:40: ``sensor.gold_scalper_btc_eur_open_posities`` stond op 0
(``positions: []``) terwijl *Mand* 20 open posities over 17 markten had. De
sensor las alleen de posities van de hoofdlus (BTC-EUR).
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.const import INTEGRATION_VERSION  # noqa: E402
from gold_scalper.posities import positie_regels  # noqa: E402
from gold_scalper.sensor import SENSORS  # noqa: E402
from test_v2213_mandlid_en_noodstop import _Lid, _mand  # noqa: E402


def _pos(i, side="buy"):
    return SimpleNamespace(id=f"5f0c2a7e-1b2c-4d5e-9f00-{i:012d}", side=side,
                           units=1234.56789123, open_price=0.000123456789,
                           stop_loss=0.000120001234, take_profit=0.000130009876)


def _sensor():
    return next(s for s in SENSORS if s.key == "open_positions")


def test_versie():
    assert tuple(int(x) for x in INTEGRATION_VERSION.split(".")) >= (2, 24, 1)


def test_buiten_mand_ongewijzigd():
    s = _sensor()
    d = {"open_positions": [_pos(1), _pos(2, "sell")],
         "strategie_per_positie": {},
         "posities_per_richting": {"long": 1, "short": 1, "limiet": 3}, "netting": None}
    assert s.value_fn(d) == 2
    a = s.attrs_fn(d)
    assert len(a["positions"]) == 2 and a["long"] == 1 and a["short"] == 1
    assert a["limiet_per_richting"] == 3 and "bereik" not in a


def test_mand_telt_alle_leden():
    hoofd, eth, sol = _Lid("BTC-EUR"), _Lid("ETH-EUR"), _Lid("SOL-EUR")
    m = _mand(hoofd)
    m.leden = {"ETH-EUR": eth, "SOL-EUR": sol}
    eth.data = {"open_positions": [_pos(1), _pos(2)], "strategie_per_positie": {}}
    sol.data = {"open_positions": [_pos(3)],
                "strategie_per_positie": {_pos(3).id: "vp:inside:1h"}}
    hoofd.data = {"open_positions": [_pos(9)]}  # oud: de vorige cyclus
    regels = m.posities(eigen=[], eigen_strategie={})
    assert [r["markt"] for r in regels] == ["ETH-EUR", "ETH-EUR", "SOL-EUR"]
    assert regels[2]["strategie"] == "vp:inside:1h"

    s = _sensor()
    d = {"open_positions": [], "mand_posities": regels, "mand_wacht": False,
         "posities_per_richting": {"long": 0, "short": 0, "limiet": 3}}
    assert s.value_fn(d) == 3
    a = s.attrs_fn(d)
    assert a["bereik"] == "mand" and a["long"] == 3 and a["short"] == 0
    assert a["per_markt"] == {"ETH-EUR": 2, "SOL-EUR": 1}
    assert a["eigen_markt"] == 0 and a["markten"] == 2


def test_eigen_posities_vers_van_de_hoofdlus():
    hoofd = _Lid("BTC-EUR")
    m = _mand(hoofd)
    hoofd.data = {"open_positions": [_pos(1)]}
    assert len(m.posities(eigen=[], eigen_strategie={})) == 0
    assert len(m.posities(eigen=[_pos(2), _pos(3)], eigen_strategie={})) == 2


def test_geen_waarde_tijdens_opstarten():
    s = _sensor()
    d = {"open_positions": [], "mand_posities": [], "mand_wacht": True}
    assert s.value_fn(d) is None
    assert s.attrs_fn(d)["mand_start"] is True


def test_volle_mand_onder_16_kb():
    regels = [{"markt": f"MARKT{i % 25:02d}-EUR", **r}
              for i, r in enumerate(positie_regels([_pos(i) for i in range(50)],
                                                   {f"5f0c2a7e-1b2c-4d5e-9f00-{i:012d}":
                                                    "vp:inside:15m" for i in range(50)}))]
    d = {"open_positions": [], "mand_posities": regels, "mand_wacht": False,
         "posities_per_richting": {"long": 0, "short": 0, "limiet": 3}, "netting": None}
    a = _sensor().attrs_fn(d)
    assert _sensor().value_fn(d) == 50
    assert len(a["positions"]) == mand_mod._MAX_POSITIES_SENSOR
    assert a["posities_overig"] == 10
    assert len(json.dumps(a)) < 14_000
