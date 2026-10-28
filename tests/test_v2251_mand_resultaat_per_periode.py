"""2.25.1 - *Resultaat per periode* van de Bitvavo-mand over de hele mand (L-GS-033).

Gemeten 27-10 (stilstandcontrole): ``sensor.gold_scalper_btc_eur_resultaat_per_periode``
stond sinds 20-10 op onbekend terwijl de mand 573 trades had. De sensor las de
``periods`` van de hoofdlus (BTC-EUR zelf, 0 trades); 2.22.2 maakte *Trades*,
*Nettoresultaat* en *Equity* al mandbreed, de periodes niet.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.const import INTEGRATION_VERSION  # noqa: E402
from test_broker_cycle import FakeHass  # noqa: E402
from gold_scalper.sensor import SENSORS  # noqa: E402
from test_v2222_mand_grootboek import T0, Lid, _mand, _q  # noqa: E402
from test_v2222_mand_grootboek import _sensor as _mandregel  # noqa: E402


def _sensor(key: str):
    if key == "net_pnl":
        return _mandregel(key)
    return next(s for s in SENSORS if s.key == key)


def test_versie_2_25_1():
    assert tuple(int(x) for x in INTEGRATION_VERSION.split(".")) >= (2, 25, 1)


def _handel_op(lid: Lid, dag: int, n: int, prijs: float, stap: float, units: float) -> None:
    for i in range(n):
        t = T0 + timedelta(days=dag, minutes=10 * i)
        trade = lid.paper.open_position("buy", units, _q(prijs, t))
        lid.paper.close_position(trade, _q(prijs + stap, t + timedelta(minutes=5)), "test")
    lid.ververs()


def test_mand_periodes_tellen_alle_leden_per_dag():
    hass = FakeHass()

    async def scenario():
        hoofd = Lid(hass, "BTC-EUR")            # handelt niet (zoals live)
        pepe = Lid(hass, "PEPE-EUR")
        pump = Lid(hass, "PUMP-EUR")
        _handel_op(pepe, 0, 2, 0.000004, -0.0000001, 1_000_000.0)   # dag 1 verlies
        _handel_op(pump, 0, 3, 0.004, 0.0001, 1_000.0)               # dag 1 winst
        _handel_op(pump, 1, 2, 0.004, -0.0001, 1_000.0)              # dag 2 verlies
        m = _mand(hass, hoofd, [pepe, pump])

        stats = await m.statistiek()
        perioden = m.perioden()
        assert perioden is not None
        data = {**hoofd.data, "mand_boek": m.grootboek(), "mand_stats": stats,
                "mand_periods": perioden, "periods": {}}

        attrs = _sensor("periods").attrs_fn(data)
        dagen = attrs["dagen"]
        assert [d["trades"] for d in dagen] == [5, 2]
        # De som van de dagen = het nettoresultaat van de mand.
        totaal = sum(d["net"] for d in dagen)
        assert totaal == pytest.approx(_sensor("net_pnl").value_fn(data), abs=0.02)
        # De waarde is 'vandaag' (laatste dag) en niet meer onbekend.
        assert _sensor("periods").value_fn(data) == pytest.approx(dagen[-1]["net"])
        assert attrs["deze_maand"]["trades"] == 7
        for c in (hoofd, pepe, pump):
            c.sluit()

    asyncio.run(scenario())


def test_tijdens_opstarten_geen_periodes():
    d = {"mand_wacht": True, "mand_periods": {"daily": [{"net": 5.0}]},
         "periods": {"daily": [{"net": 0.0}]}}
    assert mand_mod.sensor_periods(d) == {}
    assert _sensor("periods").value_fn(d) is None


def test_losse_markt_houdt_eigen_periodes():
    eigen = {"daily": [{"net": -1.5, "trades": 3}], "weekly": [], "monthly": []}
    d = {"periods": eigen, "mand_periods": None}
    assert mand_mod.sensor_periods(d) is eigen
    assert _sensor("periods").value_fn(d) == -1.5


def test_coordinator_geeft_mand_periods_door():
    from pathlib import Path
    bron = (Path(mand_mod.__file__).parent / "coordinator.py").read_text(encoding="utf-8")
    assert '"mand_periods": (self._mand.perioden() if mand_stats is not None else None)' in bron
