"""2.23.1 - mandsensoren tijdens het opstarten en de omvang van *Mand*.

L-GS-027 (gemeten 25-10, 5 starts): in de eerste ~25 s na een start toonden
*Trades* en *Nettoresultaat* van de mand eerst 0 (de eigen BTC-EUR-stats), dan
een deelsom (152/163/376/316 trades) en pas daarna 564; *Noodstop* flapte 10 s
aan. Oorzaak: het grootboek en de statistiek liepen al vóór ``_gereed`` en vóór
het inlezen van het archief.

L-GS-028 (gemeten 25-10 23:00): de attributen van ``sensor..._mand`` waren
18,0 kB; de recorder bewaart er hooguit 16 kB en sloeg ze elke 10 s over.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.binary_sensor import RiskHalted  # noqa: E402
from gold_scalper.const import INTEGRATION_VERSION  # noqa: E402
from test_v2213_mandlid_en_noodstop import _Lid, _mand  # noqa: E402

_REDENEN = [
    "long: mand: markt valt uit de mand, alleen nog sluiten",
    "long: risico in deze richting # boven #% (#)",
    "long: risico: spread # is #% van de ATR (#); vangnetgrens ligt op #%",
    "short: spot: geen short mogelijk",
    "long: dubbele order: al een long op # (instap #, marge #)",
    "long: mand: spread # % boven de grens van # %",
    "long: kostenfilter: stop #, minimaal #",
    "long: mand: start nog op (eerst alle markten met hun posities)",
]


def test_versie_2_23_1_of_hoger():
    assert tuple(int(x) for x in INTEGRATION_VERSION.split(".")) >= (2, 23, 1)


# -- L-GS-027 ------------------------------------------------------------------ #

def test_geen_waarde_zolang_de_mand_opstart():
    eigen = {"trades": 0, "net_pnl": 0.0}
    deelsom = {"trades": 152, "net_pnl": -1807.21}
    d = {"stats": eigen, "mand_stats": deelsom, "equity": 10000.0,
         "mand_boek": {"equity": 8192.79, "per_markt": []}, "mand_wacht": True}
    assert mand_mod.sensor_stats(d) == {}
    assert mand_mod.sensor_stats(d).get("trades") is None
    assert mand_mod.sensor_equity(d) is None
    assert mand_mod.sensor_trades_extra(d) == {"mand_start": True}


def test_na_het_opstarten_de_hele_mand():
    d = {"stats": {"trades": 0}, "mand_stats": {"trades": 564}, "mand_wacht": False,
         "mand_boek": {"equity": 3660.0, "per_markt": [{"markt": "PUMP-EUR"}]}}
    assert mand_mod.sensor_stats(d)["trades"] == 564
    assert mand_mod.sensor_equity(d) == 3660.0
    # Buiten een mand (geen vlag) ongewijzigd: de eigen markt.
    assert mand_mod.sensor_stats({"stats": {"trades": 7}})["trades"] == 7


def test_boek_gereed_pas_na_leden_en_archief():
    m = _mand(_Lid("BTC-EUR"))
    m._gereed = False
    assert m.boek_gereed is False
    m._gereed = True
    assert m.boek_gereed is False          # archief nog niet ingelezen
    asyncio.run(m._laad_archief())          # lege map: niets te lezen, wel klaar
    assert m.boek_gereed is True


def test_async_start_zet_gereed_pas_na_het_archief(monkeypatch):
    """De volgorde in ``async_start``: herzien -> _gereed -> archief. Tussen
    _gereed en het archief (de deelsom van 25-10) is het boek nog niet gereed."""
    m = _mand(_Lid("BTC-EUR"))
    m._gereed = False
    gezien = []

    async def _bewaard():
        return []

    async def _herzien(extra=None):
        gezien.append(("herzien", m.boek_gereed))

    echte_laad = m._laad_archief

    async def _laad():
        gezien.append(("archief", m.boek_gereed, m._gereed))
        await echte_laad()

    m._bewaarde_markten = _bewaard
    m._herzien = _herzien
    m._laad_archief = _laad
    monkeypatch.setattr(mand_mod, "async_track_time_interval", lambda *a, **k: (lambda: None))
    asyncio.run(m.async_start())
    assert gezien == [("herzien", False), ("archief", False, True)]
    assert m.boek_gereed is True


def _nep(leden, gereed):
    risk = SimpleNamespace(as_dict=lambda: {"state": "running", "halt_reason": None})
    coordinator = SimpleNamespace(data=None, risk=risk, symbol="BTC-EUR")
    mand = SimpleNamespace(leden={l.symbol: l for l in leden}, boek_gereed=gereed)
    mand.hoofd = coordinator
    coordinator._mand = mand
    nep = SimpleNamespace(coordinator=coordinator)
    nep._risk = lambda: RiskHalted._risk(nep)
    return nep


def _lid(symbol, state):
    return SimpleNamespace(symbol=symbol, risk=SimpleNamespace(
        as_dict=lambda: {"state": state, "halt_reason": "dagverlies 10.05%"}))


def test_noodstop_flapt_niet_tijdens_het_opstarten():
    nep = _nep([_lid("PEPE-EUR", "halted")], gereed=False)
    assert RiskHalted.is_on.fget(nep) is False
    assert "markten" not in RiskHalted.extra_state_attributes.fget(nep)
    # Daarna wel: een lid dat in de mand blijft en gestopt is, telt.
    nep = _nep([_lid("PEPE-EUR", "halted")], gereed=True)
    assert RiskHalted.is_on.fget(nep) is True


def test_eigen_noodstop_van_de_hoofdlus_telt_ook_tijdens_het_opstarten():
    nep = _nep([], gereed=False)
    nep.coordinator.risk = SimpleNamespace(
        as_dict=lambda: {"state": "halted", "halt_reason": "x"})
    assert RiskHalted.is_on.fget(nep) is True


def test_coordinator_zet_de_vlag_en_slaat_het_boek_over():
    bron = open(os.path.join(os.path.dirname(mand_mod.__file__), "coordinator.py"),
                encoding="utf-8").read()
    assert '"mand_wacht": mand_wacht' in bron
    # 2.24.3 (L-GS-030): de vlag komt uit ``mand.mand_wacht_voor``.
    assert "mand_wacht = mand_wacht_voor(self)" in bron


# -- L-GS-028 ------------------------------------------------------------------ #

def _vol_lid(i: int) -> _Lid:
    c = _Lid(f"M{i:02d}-EUR")
    c.data = {"price": 0.0025549500000000003 * (i + 1), "equity": 9993.96650004555,
              "stats": {"net_pnl": -8.63, "trades": 1}}
    c.weigeringen = {r: 1000 - 10 * k for k, r in enumerate(_REDENEN)}
    c.vp_tijdvakken = ("1h", "4h", "1d")
    c._laatste_weigering = "mand: markt valt uit de mand, alleen nog sluiten"
    return c


def _archief(n_met: int, n_zonder: int) -> dict:
    uit = {}
    for i in range(n_met + n_zonder):
        trades = (n_met - i) * 3 if i < n_met else 0
        uit[f"OUD{i:02d}-EUR"] = ({
            "markt": f"OUD{i:02d}-EUR", "trades": trades, "wins": trades // 3,
            "losses": trades - trades // 3, "netto": -12.345 * trades, "kosten": 1.0,
            "startbalans": 10000.0, "run_id": 2, "runs": 1,
            "laatste_trade": "2026-10-25T05:34:25+00:00" if trades else None,
            "bron": "database", "eerdere_runs_trades": 7}, [])
    return uit


def _mand_vol(leden: int, buiten_met: int, buiten_zonder: int):
    m = _mand(_vol_lid(0))
    m.leden = {c.symbol: c for c in (_vol_lid(i) for i in range(1, leden))}
    m.uitfaseren = set(m.leden)
    m._archief = _archief(buiten_met, buiten_zonder)
    m._archief_geladen = True
    m.geweerd_spread = [{"market": f"G{i}-EUR", "spread_pct": 0.1234} for i in range(30)]
    return m


def test_attributen_van_de_mand_blijven_onder_de_recordergrens():
    """Zoals 25-10 23:00 (19 leden, 30 markten buiten de mand waarvan 21 zonder
    trades) en ruim daarboven (het doel_aantal 20 vol plus 40 vertrokken)."""
    for leden, met, zonder in ((19, 9, 21), (20, 40, 40)):
        o = _mand_vol(leden, met, zonder).overzicht()
        attrs = {k: v for k, v in o.items() if k != "markten"}
        grootte = len(json.dumps(attrs, default=str).encode())
        assert grootte < 14_000, (leden, met, zonder, grootte)


def test_buiten_mand_alleen_markten_met_trades_en_begrensd():
    o = _mand_vol(3, 20, 25).overzicht()
    assert len(o["buiten_mand"]) == mand_mod._MAX_BUITEN_MAND == 15
    assert all(r["trades"] > 0 for r in o["buiten_mand"])
    assert set(o["buiten_mand"][0]) == {"markt", "trades", "netto", "laatste_trade"}
    trades = [r["trades"] for r in o["buiten_mand"]]
    assert trades == sorted(trades, reverse=True)
    assert o["buiten_mand_zonder_trades"] == 25
    overig = o["buiten_mand_overig"]
    assert overig["markten"] == 5
    # Niets verloren: getoond + overig = alle trades buiten de mand.
    totaal = sum(s["trades"] for s, _ in _archief(20, 25).values())
    assert sum(trades) + overig["trades"] == totaal
    # Het totaal van de mand blijft over alle markten.
    assert o["totaal"]["trades"] == totaal + 3


def test_per_lid_top_3_weigeringen_en_afgeronde_getallen():
    o = _mand_vol(2, 0, 0).overzicht()
    rij = o["per_markt"][1]
    assert len(rij["weigeringen"]) == 3
    assert list(rij["weigeringen"]) == _REDENEN[:3]       # de grootste drie
    assert rij["equity"] == 9993.97
    assert rij["koers"] == 0.00510990
    # De mand als geheel houdt alle redenen (top 12).
    assert len(o["weigeringen"]) == len(_REDENEN)
    assert "buiten_mand_overig" not in o


def test_volledige_tabel_blijft_op_trades():
    m = _mand_vol(2, 3, 4)
    boek = m.grootboek()
    database = [r for r in boek["per_markt"] if r.get("bron") == "database"]
    assert len(database) == 7                  # ook de markten zonder trades
    assert {"wins", "losses", "equity", "run_id"} <= set(database[0])


def test_rond():
    assert mand_mod._rond(None, 2) is None
    assert mand_mod._rond(True, 2) is True
    assert mand_mod._rond(19320760.68210604, 0) == 19320761
    assert mand_mod._rond(70765.5, 6) == 70765.5
    assert mand_mod._rond(0.0, 6) == 0.0
