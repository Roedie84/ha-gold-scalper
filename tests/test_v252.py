"""2.5.2: geen valse netting als een tegengestelde positie op haar eigen stop sloot."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker.adapter import VenuePosition  # noqa: E402
from gold_scalper.const import INTEGRATION_VERSION  # noqa: E402
from gold_scalper.strategy import posities as P  # noqa: E402


def _pos(ticket, side, units=50.0):
    return VenuePosition(ticket=ticket, symbol="GOLD", side=side, units=units,
                         open_price=4186.0, stop_loss=4184.0)


def test_versie():
    assert INTEGRATION_VERSION == "2.5.2"


def test_tegengestelde_op_eigen_stop_is_geen_netting():
    # 13-10 10:02: long 286ATAG sloot op zijn stop terwijl short 28VDTA7
    # opende; de short stond er daarna gewoon (50 oz).
    voor = [_pos("L1", "buy")]
    na = [_pos("S1", "sell")]
    assert P.netting_uit_posities(voor, na, -1, "S1", nieuw_units=50.0) == []
    # Zonder bekende grootte: aanwezig is genoeg.
    assert P.netting_uit_posities(voor, na, -1, "S1") == []


def test_echte_netting_blijft_gemeld():
    voor = [_pos("L1", "buy", units=50.0)]
    # Volledig verrekend: oude weg, nieuwe niet te zien.
    assert P.netting_uit_posities(voor, [], -1, "S1", nieuw_units=50.0) == ["L1", "nieuw:S1"]
    # Deels verrekend: nieuwe order 80 oz, alleen 30 oz staat open.
    na = [_pos("S1", "sell", units=30.0)]
    assert P.netting_uit_posities(voor, na, -1, "S1", nieuw_units=80.0) == ["L1"]
    # Oude positie kromp terwijl de nieuwe kleiner bleef dan besteld.
    na = [_pos("L1", "buy", units=20.0), _pos("S1", "sell", units=0.0)]
    assert P.netting_uit_posities(voor, na, -1, "S1", nieuw_units=30.0) == ["L1"]


def test_hedge_zonder_verdwijnen_blijft_leeg():
    voor = [_pos("L1", "buy")]
    na = [_pos("L1", "buy"), _pos("S1", "sell")]
    assert P.netting_uit_posities(voor, na, -1, "S1", nieuw_units=50.0) == []
