"""2.24.3 - mandsensoren ook in de allereerste verversing leeg (L-GS-030) en
tijdstopvarianten/exitregime bij de veldproef (L-GS-032).

L-GS-030 (gemeten 26-10, n=8 herstarts): *Trades* van de mand stond na elke
herstart 12-30 s op 0 (de eigen BTC-EUR-stats) vóór onbekend en daarna 573.
De eerste verversing liep vóór ``coordinator._mand = mand`` (``__init__.py``).

L-GS-032 (gemeten 26-10, ≥ 10 dagen): *Tijdstopvarianten* IG en Pepperstone op
0 met "te weinig blokken", terwijl alle trades veldproef zijn (geen tijdstop);
``per_exitregime.tijdstop`` bevatte de hele veldproefrun.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.const import (  # noqa: E402
    EXIT_REGIME_HUIDIG,
    EXIT_REGIME_VELDPROEF,
    INTEGRATION_VERSION,
    exit_regime_voor,
)
from gold_scalper.sensor import SENSORS  # noqa: E402
from gold_scalper.strategy import tijdstopvarianten as tv  # noqa: E402

_BRON = os.path.join(os.path.dirname(mand_mod.__file__))


def _lees(naam: str) -> str:
    with open(os.path.join(_BRON, naam), encoding="utf-8") as f:
        return f.read()


def test_versie_2_24_3():
    assert tuple(int(x) for x in INTEGRATION_VERSION.split(".")) >= (2, 24, 3)


# -- L-GS-030 ------------------------------------------------------------------ #

def test_eerste_verversing_zonder_mand_maar_mand_verwacht_wacht():
    c = SimpleNamespace(_mand=None, _mand_verwacht=True)
    assert mand_mod.mand_wacht_voor(c) is True


def test_gewone_lus_zonder_mand_wacht_niet():
    assert mand_mod.mand_wacht_voor(SimpleNamespace(_mand=None)) is False
    assert mand_mod.mand_wacht_voor(SimpleNamespace(_mand=None, _mand_verwacht=False)) is False


def test_hoofd_wacht_tot_het_boek_gereed_is():
    c = SimpleNamespace(_mand_verwacht=True)
    c._mand = SimpleNamespace(hoofd=c, boek_gereed=False)
    assert mand_mod.mand_wacht_voor(c) is True
    c._mand.boek_gereed = True
    assert mand_mod.mand_wacht_voor(c) is False


def test_lid_van_de_mand_wacht_nooit():
    hoofd = SimpleNamespace()
    lid = SimpleNamespace()
    lid._mand = SimpleNamespace(hoofd=hoofd, boek_gereed=False)
    assert mand_mod.mand_wacht_voor(lid) is False


def test_eerste_verversing_geeft_geen_nul_trades_en_geen_nul_posities():
    # Precies de situatie van 26-10: eigen stats 0 trades, mand nog niet
    # gekoppeld (mand_stats/mand_posities None), maar wel mand verwacht.
    d = {"stats": {"trades": 0, "net_pnl": 0.0}, "mand_stats": None,
         "mand_boek": None, "mand_posities": None, "open_positions": [],
         "mand_wacht": True, "posities_per_richting": {}}
    assert mand_mod.sensor_stats(d) == {}
    assert mand_mod.sensor_equity(d) is None
    assert mand_mod.sensor_open_posities(d) is None
    attrs = mand_mod.sensor_open_posities_attrs(d, [])
    assert attrs["mand_start"] is True and attrs["positions"] == []


def test_buiten_een_mand_open_posities_ongewijzigd():
    d = {"open_positions": [object(), object()], "mand_posities": None,
         "mand_wacht": False, "posities_per_richting": {"long": 1, "short": 1}}
    assert mand_mod.sensor_open_posities(d) == 2


def test_init_zet_de_verwachting_voor_de_eerste_verversing():
    bron = _lees("__init__.py")
    zet = bron.index("coordinator._mand_verwacht = is_mand(")
    eerste = bron.index("await coordinator.async_config_entry_first_refresh()")
    assert zet < eerste
    assert "mand_wacht = mand_wacht_voor(self)" in _lees("coordinator.py")


# -- L-GS-032 ------------------------------------------------------------------ #

def test_niet_van_toepassing_zonder_scalp_trades():
    stats = {"blokken": 0, "volledige_trades": 0,
             "oordeel": "te weinig blokken (0 van 20 uurblokken); nog geen oordeel"}
    uit = tv.weergave(stats, scalp_trades=0, run_trades=220)
    assert uit["oordeel"].startswith("niet van toepassing")
    assert uit["van_toepassing"] is False
    assert uit["blokken"] == 0
    # het origineel blijft onaangeroerd
    assert stats["oordeel"].startswith("te weinig")


def test_met_scalp_trades_ongewijzigd():
    stats = {"blokken": 0, "oordeel": "te weinig blokken (0 van 20 uurblokken); nog geen oordeel"}
    uit = tv.weergave(stats, scalp_trades=3, run_trades=10)
    assert uit["oordeel"].startswith("te weinig")
    assert uit["van_toepassing"] is True


def test_met_blokken_ongewijzigd():
    stats = {"blokken": 4, "oordeel": "te weinig blokken (4 van 20 uurblokken); nog geen oordeel"}
    assert tv.weergave(stats, 0, 50)["oordeel"].startswith("te weinig")


def test_lege_run_blijft_te_weinig():
    stats = {"blokken": 0, "oordeel": "te weinig blokken (0 van 20 uurblokken); nog geen oordeel"}
    assert tv.weergave(stats, 0, 0)["oordeel"].startswith("te weinig")
    assert tv.weergave(None, 0, None) == {"van_toepassing": True}


def test_sensor_toont_van_toepassing():
    s = next(x for x in SENSORS if x.key == "tijdstopvarianten")
    d = {"tijdstopvarianten": tv.weergave({"blokken": 0}, 0, 120)}
    attrs = s.attrs_fn(d)
    assert attrs["van_toepassing"] is False
    assert attrs["oordeel"].startswith("niet van toepassing")
    assert s.value_fn(d) == 0


def test_exitregime_veldproef_voor_vp_opzetten():
    assert exit_regime_voor("vp:bb_fade:15m") == EXIT_REGIME_VELDPROEF == "veldproef"
    assert exit_regime_voor("vp:rsi_rev:15m") == "veldproef"


def test_exitregime_ongewijzigd_voor_scalp_daghandel_en_onbekend():
    for s in ("scalp", "daghandel", None, ""):
        assert exit_regime_voor(s) == EXIT_REGIME_HUIDIG == "tijdstop"


def test_coordinator_gebruikt_het_regime_bij_broker_en_papier():
    bron = _lees("coordinator.py")
    assert "exit_regime=exit_regime_voor(" in bron
    assert "trade.exit_regime = exit_regime_voor(trade.strategie)" in bron
    # de tijdstop bij de afwikkeling kijkt alleen naar "zonder_tijdstop"
    assert 'trade.exit_regime == "zonder_tijdstop"' in bron
