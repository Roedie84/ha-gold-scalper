"""2.19.0 - de daghandel op kwartierbars, en wat de controle van 21-10 vond.

Gevraagd 21-10 06:13: "Gold scalper helemaal controleren en waar mogelijk de
strategie verbeteren". Gevonden:

* De daghandel (de enige opzet met een backtest over 2011-2018) handelde
  nooit: hij kreeg 1m-bars (hooguit 800, 13 uur) en wachtte eindeloos op
  "50 afgesloten uren voor de uur-EMA's". Zijn volgstop rekende bovendien in
  ATR(1m) in plaats van ATR(15m).
* De sensor Evaluaties schreef meer dan 16 KB aan weigeringsredenen.
* export_data gaf de eerste Gold Scalper terug (de Bitvavo-mand, 0 trades).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.analysis.signals import Candles  # noqa: E402
from gold_scalper.strategy import daghandel as dh  # noqa: E402
from gold_scalper.strategy import veldproef as vp  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _bars(n: int, stap: int, begin: int = 1_760_000_400, prijs: float = 4000.0, trend: float = 0.05):
    t = [begin + i * stap for i in range(n)]
    c = [prijs + i * trend for i in range(n)]
    return Candles(timestamp=t, open=c, high=[x + 1 for x in c], low=[x - 1 for x in c],
                   close=c, volume=[1.0] * n)


def _coord(timeframe="1m", eigen=None, kwartier=None):
    from gold_scalper.coordinator import GoldScalperCoordinator as C

    mt = vp.MeerTijdvakken()
    if kwartier is not None:
        mt.vul("15m", kwartier)
    c = SimpleNamespace(veldproef=mt, timeframe=timeframe, _candles=eigen)
    c._daghandel_candles = lambda: C._daghandel_candles(c)
    c._atr15 = lambda: C._atr15(c)
    return C, c


def test_daghandel_krijgt_kwartierbars_in_plaats_van_1m():
    C, c = _coord("1m", eigen=_bars(800, 60), kwartier=_bars(400, 900))
    gekozen = C._daghandel_candles(c)
    assert len(gekozen) == 400 and gekozen.timestamp[1] - gekozen.timestamp[0] == 900


def test_met_kwartierbars_komen_de_uur_emas_rond():
    kw = _bars(400, 900)
    snel, traag = dh.uur_emas(kw)
    assert snel is not None and traag is not None
    # met 800 x 1m (13 uur) nooit
    assert dh.uur_emas(_bars(800, 60))[1] is None


def test_zonder_kwartierbars_niet_op_1m():
    C, c = _coord("1m", eigen=_bars(800, 60), kwartier=None)
    assert C._daghandel_candles(c) is None
    C, c = _coord("15m", eigen=_bars(500, 900), kwartier=_bars(200, 900))
    assert len(C._daghandel_candles(c)) == 500     # de langste kwartierreeks


def test_atr15_voor_de_volgstop():
    C, c = _coord("1m", eigen=_bars(800, 60), kwartier=_bars(400, 900))
    a = C._atr15(c)
    assert a is not None and 1.9 < a < 2.2           # bars van 2 USD hoog-laag
    C, c = _coord("1m", eigen=_bars(800, 60), kwartier=None)
    assert C._atr15(c) is None


def test_coordinator_gebruikt_ze():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "invoer = self._daghandel_candles() if strategie == STRATEGIE_DAGHANDEL else self._candles" in bron
    assert "else (self._atr15() or atr) if strategie == STRATEGIE_DAGHANDEL" in bron
    # vingerafdruk ongewijzigd: geen nieuwe run, de bewijsfase loopt door
    assert dh.STRATEGIE_VERSIE == "daghandel-1.6.0"


def test_evaluaties_houdt_de_attributen_klein():
    bron = (PKG / "sensor.py").read_text(encoding="utf-8")
    deel = bron[bron.index('key="evaluations"'):bron.index('key="latency"')]
    assert ".items())[:30])" in deel and '"rejections_soorten"' in deel
    # dezelfde uitdrukking op een grote lijst
    redenen = {f"kostenfilter: stop {i}.123, minimaal 9.5": 1000 - i for i in range(500)}
    assert len(dict(list(redenen.items())[:30])) == 30


def test_export_per_entry():
    init = (PKG / "__init__.py").read_text(encoding="utf-8")
    assert 'vol.Optional("entry_id"): str' in init
    assert '"strategie", "mode", "id", "broker_ticket"' in init
    assert "entry_id:" in (PKG / "services.yaml").read_text(encoding="utf-8")
