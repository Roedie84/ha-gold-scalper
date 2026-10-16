"""2.12.0: kostenfilter veldproef - stop minstens 8x de rondreiskosten en 2 USD."""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.strategy import veldproef as vp  # noqa: E402


def test_min_stopafstand():
    assert vp.min_stopafstand(0.0) == vp.KOSTEN_MIN_STOP_USD
    assert vp.min_stopafstand(None) == vp.KOSTEN_MIN_STOP_USD
    assert abs(vp.min_stopafstand(0.86) - 6.88) < 1e-9      # IG
    assert vp.min_stopafstand(0.2) == vp.KOSTEN_MIN_STOP_USD       # Pepperstone


def test_stop_te_krap():
    assert vp.stop_te_krap(4200.0, 4198.5, 0.2)              # 1,5 < 2
    assert not vp.stop_te_krap(4200.0, 4197.0, 0.2)          # 3 >= 2
    assert vp.stop_te_krap(4200.0, 4204.0, 0.86)             # 4 < 6,88 (short)
    assert not vp.stop_te_krap(4200.0, 4192.0, 0.86)
    assert not vp.stop_te_krap(4200.0, None, 0.86)


def _zelf(spread, per_lot):
    from gold_scalper.coordinator import GoldScalperCoordinator as C
    zelf = SimpleNamespace(venue=SimpleNamespace(), _kostenfilter={"overgeslagen": 0, "per_opzet": {}})
    zelf._commissie = lambda u: round(2 * per_lot * abs(u) / 100.0, 4)
    zelf._kosten_per_oz = lambda q: C._kosten_per_oz(zelf, q)
    return C, zelf


def test_kosten_per_oz_pepperstone():
    C, zelf = _zelf(0.12, 3.5)
    k = C._kosten_per_oz(zelf, SimpleNamespace(spread=0.12, bid=1, ask=1.12))
    assert abs(k - (0.12 + 0.07 + vp.SLIP_PER_OZ)) < 1e-9


def test_kosten_per_oz_zonder_spreadveld():
    C, zelf = _zelf(None, 0.0)
    k = C._kosten_per_oz(zelf, SimpleNamespace(spread=None, bid=4200.0, ask=4200.7))
    assert abs(k - (0.7 + vp.SLIP_PER_OZ)) < 1e-6


def test_noteer_telt_per_opzet():
    C, zelf = _zelf(0.7, 0.0)
    C._noteer_kostenfilter(zelf, "vp:rsi_rev:15m", 4200.0, 4196.0, 0.86)
    C._noteer_kostenfilter(zelf, "vp:rsi_rev:15m", 4200.0, 4197.0, 0.86)
    assert zelf._kostenfilter["overgeslagen"] == 2
    assert zelf._kostenfilter["per_opzet"]["vp:rsi_rev:15m"] == 2
    assert "minimaal 6.88" in zelf._kostenfilter["laatste"]


def test_open_position_slaat_krappe_veldproefstop_over():
    from gold_scalper.coordinator import GoldScalperCoordinator as C
    gebruikt = []
    zelf = SimpleNamespace(
        koers_verouderd=False, _geopend_in_cyclus=0, _max_per_cyclus=1,
        _kostenfilter={"overgeslagen": 0, "per_opzet": {}},
    )
    zelf._kosten_per_oz = lambda q: 0.86
    zelf._noteer_kostenfilter = lambda *a: C._noteer_kostenfilter(zelf, *a)
    zelf._vp_bar_gebruikt = lambda s, sig: gebruikt.append(s)

    async def geen_posities():
        raise AssertionError("mag niet verder dan het filter")
    zelf._open_positions = geen_posities
    signaal = SimpleNamespace(direction=1, stop_loss=4196.0, take_profit=4210.0,
                              components={"strategie": "vp:momentum:15m", "bar": 1})
    quote = SimpleNamespace(bid=4199.3, ask=4200.0, spread=0.7)
    from datetime import datetime, timezone
    assert asyncio.run(C._open_position(zelf, signaal, quote, datetime.now(timezone.utc))) is False
    assert gebruikt == ["vp:momentum:15m"]
    assert zelf._kostenfilter["overgeslagen"] == 1
