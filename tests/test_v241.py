"""2.4.1: 20 posities per richting, minimale stopafstand veldproef."""
from pathlib import Path

from gold_scalper import const
from gold_scalper.strategy import veldproef as vp

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def test_grens_twintig():
    assert const.MAX_POSITIONS_PER_RICHTING_GRENS == 20
    assert "_number(1, 20, 1, slider=True)" in (PKG / "config_flow.py").read_text()


def test_minimale_stop():
    assert vp.MIN_STOP_USD == 1.0
    assert "afstand = max(STOP_ATR * k.atr, MIN_STOP_USD)" in (PKG / "strategy" / "veldproef.py").read_text()


def test_afgewezen_niet_opnieuw():
    bron = (PKG / "coordinator.py").read_text()
    blok = bron.split('_LOGGER.warning("Order niet geplaatst: %s", result.error)')[1][:400]
    assert "self._vp_bar_gebruikt(strategie, signal)" in blok
