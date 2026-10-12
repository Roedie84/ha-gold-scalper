"""2.4.1: minimale stopafstand veldproef, afgewezen order niet herhalen."""
from pathlib import Path

from gold_scalper.strategy import veldproef as vp

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def test_minimale_stop():
    assert vp.MIN_STOP_USD == 1.0
    assert "afstand = max(STOP_ATR * k.atr, MIN_STOP_USD)" in (PKG / "strategy" / "veldproef.py").read_text()


def test_afgewezen_niet_opnieuw():
    bron = (PKG / "coordinator.py").read_text()
    blok = bron.split('_LOGGER.warning("Order niet geplaatst: %s", result.error)')[1][:400]
    assert "self._vp_bar_gebruikt(strategie, signal)" in blok
