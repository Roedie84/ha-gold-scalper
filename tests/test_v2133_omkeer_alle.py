"""2.13.3 (Ruud 16-10): een nieuwe positie keert alle oudere de andere kant op.

"Wel extra shorts openen, maar de longs niet sluiten" -> "Omkeren: komt er een
short-signaal, dan sluiten alle longs, met verlies of met vastgezette winst.
Op alle timeframes."
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker.exits import omkeer_actie  # noqa: E402

NU = datetime(2026, 10, 16, 11, 30, tzinfo=timezone.utc)


def _zelf(g):
    from gold_scalper.coordinator import GoldScalperCoordinator as C
    return C, SimpleNamespace(_omkeer_alle=g)


def test_oudere_long_krijgt_short_richting():
    C, z = _zelf({"richting": -1, "sinds": NU, "strategie": "vp:rsi_rev:3m"})
    assert C._omkeer_richting(z, "buy", NU - timedelta(minutes=5), None) == -1


def test_nieuwere_long_niet():
    C, z = _zelf({"richting": -1, "sinds": NU, "strategie": "vp:rsi_rev:3m"})
    assert C._omkeer_richting(z, "buy", NU + timedelta(minutes=1), 1) == 1


def test_zelfde_kant_houdt_eigen_richting():
    C, z = _zelf({"richting": -1, "sinds": NU, "strategie": "x"})
    assert C._omkeer_richting(z, "sell", NU - timedelta(minutes=5), None) is None


def test_zonder_omkeer_eigen_richting():
    C, z = _zelf(None)
    assert C._omkeer_richting(z, "buy", NU, -1) == -1


def test_verlies_sluiten_winst_vastzetten():
    a = omkeer_actie("buy", 4181.0, 4178.0, 4178.2, 4170.0, -1)
    assert a.kind == "close"
    b = omkeer_actie("buy", 4170.0, 4180.0, 4180.2, 4165.0, -1)
    assert b.kind == "modify_stop" and b.new_stop > 4170.0


def test_gekoppeld_na_openen():
    src = (Path(__file__).parent.parent / "custom_components" / "gold_scalper" / "coordinator.py").read_text()
    assert "if uitgevoerd and r_signal.direction:" in src
    assert "self._omkeer_richting(position.side, opened" in src
