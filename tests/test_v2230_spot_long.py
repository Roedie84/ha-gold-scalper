"""2.23.0 - de Bitvavo-mand (spot) handelt long op tijdvakken waar het
kostenfilter een trade toelaat.

Live 22-25/10 (BTC-EUR, hoofdlus van de mand): 0 trades in 3 dagen. Van de
handelbare signalen: 2.737 x "spot: geen short mogelijk" en ruim 1.000
kostenfilterweigeringen (stops van 50-380 euro tegen een minimum van ~2.900,
~4 % van de koers). De shorts kwamen in de cyclus vóór het kostenfilter en
werden als laatste weigering getoond; de longs stierven allemaal op het filter.
"""
from __future__ import annotations

import math
import os
import random
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper import coordinator as coord_mod  # noqa: E402
from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.analysis.signals import Candles  # noqa: E402
from gold_scalper.strategy import combinatie as combinatie_mod  # noqa: E402
from gold_scalper.strategy import schaal as schaal_mod  # noqa: E402
from gold_scalper.strategy import veldproef as vp  # noqa: E402
from gold_scalper.strategy.scalping import ScalpConfig  # noqa: E402

from test_v2213_mandlid_en_noodstop import _Lid, _mand  # noqa: E402


# -- welke opzetten ------------------------------------------------------------ #

def test_goud_ongewijzigd():
    assert vp.TIJDVAKKEN == ("1m", "3m", "5m", "15m", "30m")
    assert vp.tijdvakken_voor(False) == vp.TIJDVAKKEN
    assert vp.namen() == vp.namen(vp.TIJDVAKKEN)
    assert len(vp.namen()) == 45
    assert vp.bar_tijdvakken(False) == vp.TIJDVAKKEN
    assert combinatie_mod.strategieen(combinatie_mod.STRATEGIE_ALLES)[2:] == vp.namen()


def test_spot_opzetten_op_1h_4h_1d():
    tv = vp.tijdvakken_voor(True)
    assert tv == ("1h", "4h", "1d")
    namen = vp.namen(tv)
    assert len(namen) == len(vp.FAMILIES) * 3
    assert "vp:rsi_rev:1d" in namen and not any(n.endswith(":5m") for n in namen)
    # Zelfde families, geen nieuwe of omgekeerde.
    assert {vp.ontleed(n)[0] for n in namen} == set(vp.FAMILIES)
    alles = combinatie_mod.strategieen(combinatie_mod.STRATEGIE_ALLES, namen)
    assert alles[:2] == (combinatie_mod.STRATEGIE_DAGHANDEL, combinatie_mod.STRATEGIE_SCALP)
    assert alles[2:] == namen


def test_spot_houdt_15m_bars_voor_de_daghandel():
    bars = vp.MeerTijdvakken(vp.bar_tijdvakken(True), hoger=vp.SPOT_HOGER_TIJDVAK)
    assert {"15m", "1h", "4h", "1d"} <= set(bars.agg)
    assert bars.hoger == "1d"
    # Onbekend tijdvak: geen KeyError.
    assert bars.candles("2h") is None
    bars.vul("2h", _candles([1.0] * 5, 7200))
    assert vp.MeerTijdvakken().hoger == vp.HOGER_TIJDVAK


def test_exitduur_volgt_het_tijdvak():
    assert vp.exit_config("vp:donchian:1d").max_hold_seconds == vp.HOLD_BARS * 86400
    assert vp.exit_config("vp:donchian:4h").max_hold_seconds == vp.HOLD_BARS * 14400


# -- het kostenfilter blijft gelijk -------------------------------------------- #

def _bitvavo_kosten(koers: float) -> float:
    """Rondreis per eenheid zoals _kosten_per_oz: spread + 2 x taker + slip."""
    spread = koers * 0.00002
    return spread + 2 * 0.0025 * koers + schaal_mod.usd(vp.SLIP_PER_OZ)


def test_kostenregel_niet_versoepeld():
    assert vp.KOSTEN_STOP_FACTOR == 8.0
    assert vp.KOSTEN_MIN_STOP_USD == 2.0


def test_intraday_stop_haalt_het_filter_niet_dagstop_wel():
    koers = 71500.0
    token = schaal_mod.zet(schaal_mod.voor_markt(koers, 1e-8, 1e-5, 0.0025))
    try:
        kosten = _bitvavo_kosten(koers)
        minimum = vp.min_stopafstand(kosten)
        # ~4 % van de koers (live: "minimaal 2949").
        assert 0.039 < minimum / koers < 0.043
        # 30m: ATR ~0,35 % -> stop 1,5 x ATR ~0,5 %: altijd te krap.
        assert vp.stop_te_krap(koers, koers - 1.5 * 0.0035 * koers, kosten)
        # 1d: ATR ~3,5 % -> stop ~5,3 %: mag.
        assert not vp.stop_te_krap(koers, koers - 1.5 * 0.035 * koers, kosten)
    finally:
        schaal_mod.terug(token)


# -- de signalen zijn symmetrisch ---------------------------------------------- #

def _candles(close, stap=86400, start=1_700_006_400, spreid=None):
    rnd = random.Random(7)
    h, lo, o = [], [], []
    vorig = close[0]
    for c in close:
        s = spreid if spreid is not None else abs(c) * 0.01
        o.append(vorig)
        h.append(max(vorig, c) + s * rnd.random())
        lo.append(min(vorig, c) - s * rnd.random())
        vorig = c
    return Candles(timestamp=[start + i * stap for i in range(len(close))],
                   open=o, high=h, low=lo, close=list(close), volume=[1.0] * len(close))


def _gespiegeld(c: Candles, as_: float) -> Candles:
    return Candles(timestamp=list(c.timestamp), open=[2 * as_ - x for x in c.open],
                   high=[2 * as_ - x for x in c.low], low=[2 * as_ - x for x in c.high],
                   close=[2 * as_ - x for x in c.close], volume=list(c.volume))


def test_families_geven_long_en_short_symmetrisch():
    """Spiegel de koers: elke familie moet precies de andere richting geven.
    Er zit dus geen ingebouwde voorkeur voor short in de signalen; dat de
    mand vooral shorts zag, kwam van de markt (dalend) en de volgorde van de
    weigeringen, niet van de strategie."""
    rnd = random.Random(42)
    p, close = 1000.0, []
    for _ in range(260):
        p += rnd.gauss(0, 12)
        close.append(p)
    c = _candles(close, spreid=6.0)
    m = _gespiegeld(c, 1000.0)
    getoetst = {f: 0 for f in vp.FAMILIES}
    for eind in range(vp.MIN_BARS + 5, len(close) + 1):
        sub = Candles(c.timestamp[:eind], c.open[:eind], c.high[:eind], c.low[:eind],
                      c.close[:eind], c.volume[:eind])
        subm = Candles(m.timestamp[:eind], m.open[:eind], m.high[:eind], m.low[:eind],
                       m.close[:eind], m.volume[:eind])
        k, km = vp.kenmerken(sub), vp.kenmerken(subm)
        for f in vp.FAMILIES:
            assert k.richting[f] == -km.richting[f], (f, eind)
            if k.richting[f]:
                getoetst[f] += 1
    assert sum(getoetst.values()) > 20


def test_daling_geeft_long_op_daggrafiek():
    """Een opzet op 1d geeft een long met stop 1,5 x ATR(1d) - groot genoeg
    voor het kostenfilter bij een munt met ~3 % dagbeweging."""
    rnd = random.Random(3)
    p, close = 100.0, []
    for _ in range(120):
        p *= 1 + rnd.gauss(0, 0.03)
        close.append(p)
    # Drie harde daldagen: RSI(2) onder 10 -> rsi_rev long.
    for _ in range(3):
        p *= 0.9
        close.append(p)
    bars = vp.MeerTijdvakken(vp.bar_tijdvakken(True), hoger="1d")
    bars.vul("1d", _candles(close))
    k = bars.kenmerken("1d")
    assert k is not None and k.richting["rsi_rev"] == 1
    koers = close[-1]
    token = schaal_mod.zet(schaal_mod.voor_markt(koers, 1e-8, 1e-5, 0.0025))
    try:
        sig = vp.evalueer("vp:rsi_rev:1d", bars, koers * 0.99999, koers * 1.00001,
                          ScalpConfig(), 0, 1e9, {}, None)
        assert sig.direction == 1 and sig.should_trade
        afstand = sig.components["atr"] * vp.STOP_ATR
        assert math.isclose(koers * 1.00001 - sig.stop_loss, afstand, rel_tol=1e-3)
        assert not vp.stop_te_krap(koers * 1.00001, sig.stop_loss, _bitvavo_kosten(koers))
    finally:
        schaal_mod.terug(token)


def test_trendcontext_op_het_hogere_spottijdvak():
    bars = vp.MeerTijdvakken(vp.bar_tijdvakken(True), hoger="1d")
    rnd = random.Random(5)
    p, dag, uur = 100.0, [], []
    for _ in range(100):
        p *= 1 + rnd.gauss(0.004, 0.02)
        dag.append(p)
    for _ in range(100):
        p *= 1 + rnd.gauss(0, 0.004)
        uur.append(p)
    bars.vul("1d", _candles(dag))
    bars.vul("4h", _candles(uur, 14400))
    k4 = bars.kenmerken("4h")
    kd = bars.kenmerken("1d")
    ctx = vp.instap_context(bars, "4h", k4)
    assert ctx.get("trend") == kd.context.get("trend")


# -- uitzetregels kennen de spotnamen ------------------------------------------ #

def test_groepsregel_en_handregel_op_spottijdvak():
    slecht = [-1.0 + 0.01 * (i % 3) for i in range(vp.GROEP_MIN_N)]
    uit = vp.uitgezette_opzetten({"vp:rsi_rev:1d": slecht})
    assert all(n.endswith(":1d") for n in uit)
    assert {n for n in uit} == {f"vp:{f}:1d" for f in vp.FAMILIES}
    # Een hand-uitgezet 1m raakt de spotopzetten niet.
    hand = vp.handmatig_uitgezet({}, ["1m", "3m", "5m"])
    assert not any(n.endswith((":1h", ":4h", ":1d")) for n in hand)


# -- weigeringen tellen per reden ---------------------------------------------- #

def test_weigering_sleutel_zonder_getallen():
    a = coord_mod.weigering_sleutel("kostenfilter: stop 141.6, minimaal 2949")
    b = coord_mod.weigering_sleutel("kostenfilter: stop 5.313e-05, minimaal 0.000157")
    assert a == b == "kostenfilter: stop #, minimaal #"
    assert coord_mod.weigering_sleutel("spot: geen short mogelijk") == "spot: geen short mogelijk"
    assert coord_mod.weigering_sleutel(None) == "onbekend"


def test_tel_weigering_per_richting():
    c = SimpleNamespace(weigeringen={})
    coord_mod.tel_weigering(c, "spot: geen short mogelijk", -1)
    coord_mod.tel_weigering(c, "spot: geen short mogelijk", -1)
    coord_mod.tel_weigering(c, "kostenfilter: stop 1, minimaal 9", 1)
    coord_mod.tel_weigering(c, "kostenfilter: stop 2, minimaal 8", 1)
    assert c.weigeringen == {"short: spot: geen short mogelijk": 2,
                             "long: kostenfilter: stop #, minimaal #": 2}
    coord_mod.tel_weigering(SimpleNamespace(), "x", 1)  # geen teller: geen fout


def test_mandoverzicht_toont_weigeringen_per_markt_en_samen():
    hoofd = _Lid("BTC-EUR")
    hoofd.weigeringen = {"short: spot: geen short mogelijk": 5, "long: kostenfilter: stop #, minimaal #": 2}
    hoofd.vp_tijdvakken = ("1h", "4h", "1d")
    lid = _Lid("XRP-EUR")
    lid.weigeringen = {"long: kostenfilter: stop #, minimaal #": 3}
    m = _mand(hoofd)
    m.leden = {"XRP-EUR": lid}
    o = m.overzicht()
    rijen = {r["markt"]: r for r in o["per_markt"]}
    assert rijen["BTC-EUR"]["weigeringen"]["short: spot: geen short mogelijk"] == 5
    assert rijen["BTC-EUR"]["opzet_tijdvakken"] == ["1h", "4h", "1d"]
    assert rijen["XRP-EUR"]["opzet_tijdvakken"] == []
    assert o["weigeringen"] == {"short: spot: geen short mogelijk": 5,
                                "long: kostenfilter: stop #, minimaal #": 5}
    assert list(mand_mod._top({"a": 1, "b": 3, "c": 2}, 2)) == ["b", "c"]


def test_spot_short_wordt_nog_steeds_niet_omgekeerd():
    """Geen truc: een short op spot blijft geweigerd en wordt geen long."""
    bron = open(coord_mod.__file__, encoding="utf-8").read()
    assert 'if side == "sell" and spot:' in bron
    assert 'self._laatste_weigering = "spot: geen short mogelijk"' in bron


# -- de coordinator kiest per venue -------------------------------------------- #

def _coordinator(venue: str):
    from gold_scalper.coordinator import GoldScalperCoordinator
    from test_broker_cycle import FakeHass

    class Entry:
        entry_id = f"t_{venue}"
        data = {"venue": venue, "timeframe": "1m", "mode": "paper",
                "bv_markt": "BTC-EUR", "symbol": "BTC-EUR"}
        options = {"mode": "paper", "starting_balance": 10000.0, "strategie": "alles",
                   "vp_tijdvakken_uit": ["1m", "3m", "5m"]}

    return GoldScalperCoordinator(FakeHass(), Entry())


def test_coordinator_bitvavo_opzetten_op_spottijdvakken():
    c = _coordinator("bitvavo")
    assert c._is_spot
    assert c.vp_tijdvakken == vp.SPOT_TIJDVAKKEN
    assert c.vp_namen == vp.namen(vp.SPOT_TIJDVAKKEN)
    assert {"15m", "1d"} <= set(c.veldproef.agg)
    assert c.veldproef.hoger == "1d"
    assert c.weigeringen == {}
    # De hand-uitgezette 1m-5m raken geen spotopzet.
    assert not any(n in c._vp_uitgezet for n in c.vp_namen)


def test_coordinator_goud_ongewijzigd():
    c = _coordinator("simulator")
    assert not c._is_spot
    assert c.vp_namen == vp.namen()
    assert set(c.veldproef.agg) == set(vp.TIJDVAKKEN)
    assert c.veldproef.hoger == "30m"
