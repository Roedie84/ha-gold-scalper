"""2.4.2: tot 20 posities per richting."""
from pathlib import Path

from gold_scalper import const

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def test_grens_twintig():
    assert const.MAX_POSITIONS_PER_RICHTING_GRENS == 20
    assert "_number(1, 20, 1, slider=True)" in (PKG / "config_flow.py").read_text()
