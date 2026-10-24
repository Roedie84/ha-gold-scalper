"""2.22.1: kostenfilter rekende de taker-fee niet mee bij munten met een kleine koers.

Live 24-10: PUMP-EUR (koers 0,0037) haalde het kostenfilter met een stop van
0,3 %, terwijl BTC/ETH/XRP met dezelfde 0,25 %/zijde een stop van ~4 % moesten
hebben. ``_commissie(1.0)`` rondt af op 4 decimalen; de fee per eenheid
(2 x 0,0025 x 0,0037 = 0,0000186) werd 0. PUMP n=384, netto -5.124 EUR,
kosten 4.100.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.strategy import schaal, veldproef as vp  # noqa: E402


def _zelf(koers):
    from gold_scalper.coordinator import GoldScalperCoordinator as C
    venue = SimpleNamespace(alleen_long=True, tarief_per_zijde=0.0025,
                            commissie_per_lot_per_zijde=0)
    zelf = SimpleNamespace(venue=venue, _last_quote=SimpleNamespace(mid=koers))
    zelf._commissie_ruw = lambda u: C._commissie_ruw(zelf, u)
    zelf._commissie = lambda u: C._commissie(zelf, u)
    return C, zelf


def _kosten(koers, spread_pct):
    C, zelf = _zelf(koers)
    s = schaal.Schaal(prijs=koers / schaal.REF_PRIJS, eenheid_stap=1e-8,
                      min_eenheden=1, tarief=0.0025, spot=True)
    tok = schaal.zet(s)
    try:
        q = SimpleNamespace(spread=koers * spread_pct / 100, bid=koers,
                            ask=koers * (1 + spread_pct / 100))
        k = C._kosten_per_oz(zelf, q)
        return k, vp.min_stopafstand(k)
    finally:
        schaal.terug(tok)


def test_fee_telt_mee_bij_kleine_koers():
    koers = 0.003726
    k, minimaal = _kosten(koers, 0.0295)
    assert k >= 2 * 0.0025 * koers            # de fee zit erin
    assert minimaal / koers > 0.03            # ~4 %, zoals bij BTC/ETH


def test_pump_stop_van_een_half_procent_is_te_krap():
    koers = 0.003726
    k, _ = _kosten(koers, 0.0295)
    assert vp.stop_te_krap(koers, koers * 0.995, k)


def test_grote_koers_ongewijzigd():
    # ETH: 2 x 0,0025 x 2072,1 = 10,36 + spread + slip -> 8x ~ 83,6 (live gelogd 83,55)
    k, minimaal = _kosten(2072.1, 0.0005)
    assert abs(minimaal - 83.59) < 0.1


def test_commissie_bedrag_blijft_afgerond():
    C, zelf = _zelf(0.003726)
    assert C._commissie(zelf, 1.0) == 0.0       # bedrag in euro: afgerond zoals altijd
    assert C._commissie_ruw(zelf, 1.0) > 0
    assert C._commissie(zelf, 5000.0) == round(2 * 0.0025 * 0.003726 * 5000, 4)


def test_goud_ongewijzigd():
    from gold_scalper.coordinator import GoldScalperCoordinator as C
    zelf = SimpleNamespace(venue=SimpleNamespace(commissie_per_lot_per_zijde=3.5),
                           _last_quote=None)
    zelf._commissie_ruw = lambda u: C._commissie_ruw(zelf, u)
    k = C._kosten_per_oz(zelf, SimpleNamespace(spread=0.12, bid=1, ask=1.12))
    assert abs(k - (0.12 + 0.07 + vp.SLIP_PER_OZ)) < 1e-9
