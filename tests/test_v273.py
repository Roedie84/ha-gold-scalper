"""2.7.3: hard risicoplafond per order (100 USD tot de stop), elke strategie."""
from __future__ import annotations

from pathlib import Path

from gold_scalper.strategy.posities import MAX_RISICO_PER_ORDER_USD, risico_plafond

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def test_daghandel_500_oz_wordt_begrensd():
    units, begrensd = risico_plafond(500.0, 4137.96, 4159.095)
    assert begrensd and units == 4.7
    assert units * (4159.095 - 4137.96) <= MAX_RISICO_PER_ORDER_USD


def test_kleine_order_ongewijzigd():
    assert risico_plafond(3.0, 4100.0, 4090.0) == (3.0, False)


def test_minstens_een_ounce():
    assert risico_plafond(10.0, 4100.0, 3900.0) == (1.0, True)


def test_zonder_stop_ongewijzigd():
    assert risico_plafond(50.0, 4100.0, None) == (50.0, False)
    assert risico_plafond(50.0, 4100.0, 4100.0) == (50.0, False)


def test_coordinator_past_plafond_overal_toe():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "units, begrensd = risico_plafond(units, entry_price, signal.stop_loss)" in bron
    assert "return float(risico_plafond(sized.units, entry_price, signal.stop_loss)[0])" in bron
    assert "bijkoop_units, _ = risico_plafond(" in bron
