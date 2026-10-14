"""2.5.5: break-even uiterlijk vanaf +1,5 USD/oz bij veldproef en daghandel."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker.exits import ExitManager  # noqa: E402
from gold_scalper.strategy import daghandel as D  # noqa: E402
from gold_scalper.strategy import veldproef as V  # noqa: E402

NU = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)



def _zonder_deel(cfg):
    """2.5.9: deze test gaat over de stop, niet over de deelwinst."""
    cfg.enable_partial_close = False
    return cfg

def test_veldproef_15m_met_3_usd_winst():
    # Screenshot 13-10: rsi_rev 15m, instap 4180,59, stop 4173,68 (R 6,91), koers +3,04.
    m = ExitManager(_zonder_deel(V.exit_config("vp:rsi_rev:15m")))
    a = m.evaluate("buy", 0.5, 4180.59, 4173.68, 4183.63, 4184.03, 6.91,
                   NU - timedelta(minutes=30), NU, 0.8)
    # 2.6.3: in R; +3,04 is 0,44R, onder de break-even van 0,5R.
    assert a.kind == "hold"


def test_onder_15_usd_en_onder_halve_r_niets():
    m = ExitManager(V.exit_config("vp:rsi_rev:30m"))
    a = m.evaluate("buy", 0.5, 4180.90, 4171.30, 4182.30, 4182.70, 9.6,
                   NU - timedelta(minutes=30), NU, 0.8)
    assert a.kind == "hold"


def test_daghandel_ook():
    m = ExitManager(D.exit_config())
    a = m.evaluate("buy", 1.0, 4000.0, 3980.0, 4001.6, 4002.0, 5.0,
                   NU - timedelta(minutes=30), NU, 0.8)
    assert a.kind == "modify_stop" and abs(a.new_stop - 4000.96) < 1e-6  # instap + 1,2 x kosten


# --- omkeer: signaal of trend gedraaid ------------------------------------ #

from gold_scalper.broker.exits import omkeer_actie  # noqa: E402


def test_omkeer_verlies_sluiten():
    a = omkeer_actie("buy", 4000.0, 3999.0, 3999.4, 3995.0, -1)
    assert a.kind == "close" and "verlies" in a.reason


def test_omkeer_winst_vastzetten():
    a = omkeer_actie("buy", 4000.0, 4003.0, 4003.4, 3998.0, -1)
    assert a.kind == "modify_stop" and a.new_stop == 4002.4
    a = omkeer_actie("sell", 4000.0, 3996.6, 3997.0, 4002.0, 1)
    assert a.kind == "modify_stop" and a.new_stop == 3997.6


def test_omkeer_kleine_winst_nemen_en_geen_omkeer():
    assert omkeer_actie("buy", 4000.0, 4000.3, 4000.7, 3998.0, -1).kind == "close"
    assert omkeer_actie("buy", 4000.0, 3999.0, 3999.4, 3995.0, 1) is None
    assert omkeer_actie("buy", 4000.0, 3999.0, 3999.4, 3995.0, 0) is None
    # stop staat al strakker: niets
    assert omkeer_actie("buy", 4000.0, 4003.0, 4003.4, 4002.6, -1) is None


def test_omkeer_in_de_lus():
    from pathlib import Path
    bron = (Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
            / "coordinator.py").read_text(encoding="utf-8")
    assert "self._richting_per_strategie[strategie] = int(r_signal.direction or 0)" in bron
    assert "omkeer = omkeer_actie(" in bron
