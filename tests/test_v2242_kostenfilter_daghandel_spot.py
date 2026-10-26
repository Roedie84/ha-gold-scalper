"""2.24.2: op een spot-venue (Bitvavo) geldt het kostenfilter ook voor de
daghandel. Live 26-10: HYPE-EUR 2 daghandeltrades, bruto +0,70, kosten 12,39
(0,51 % rondreis), netto -11,70. Goud: ongewijzigd (alleen de veldproef)."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))


class _Gestopt(Exception):
    pass


def _zelf(spot: bool, kosten: float):
    from gold_scalper.coordinator import GoldScalperCoordinator as C
    zelf = SimpleNamespace(
        koers_verouderd=False, _geopend_in_cyclus=0, _max_per_cyclus=1,
        _kostenfilter={"overgeslagen": 0, "per_opzet": {}},
        venue=SimpleNamespace(alleen_long=spot),
        mode=SimpleNamespace(uses_real_money=False, places_orders=False),
        gate={}, _laatste_weigering=None, primaire_strategie="daghandel",
    )
    zelf._kosten_per_oz = lambda q: kosten
    zelf._noteer_kostenfilter = lambda *a: C._noteer_kostenfilter(zelf, *a)
    zelf._vp_bar_gebruikt = lambda s, sig: None

    async def verder():
        raise _Gestopt  # voorbij het filter
    zelf._open_positions = verder
    return C, zelf


def _signaal(strategie, stop, richting=1):
    comp = {"strategie": strategie} if strategie else {}
    return SimpleNamespace(direction=richting, stop_loss=stop, take_profit=None, components=comp)


def _run(C, zelf, sig, quote):
    try:
        return asyncio.run(C._open_position(zelf, sig, quote, datetime.now(timezone.utc)))
    except _Gestopt:
        return "verder"


def test_daghandel_spot_krappe_stop_geweigerd():
    # HYPE-EUR 26-10 15:00: instap 69,84, kosten ~0,36/eenheid -> minimaal ~2,9.
    C, zelf = _zelf(True, 0.36)
    q = SimpleNamespace(bid=69.83, ask=69.84, spread=0.01)
    assert _run(C, zelf, _signaal("daghandel", 69.60), q) is False
    assert zelf._laatste_weigering.startswith("kostenfilter: stop")
    assert zelf._kostenfilter["per_opzet"] == {"daghandel": 1}


def test_daghandel_spot_zonder_naam_telt_als_primaire_strategie():
    C, zelf = _zelf(True, 0.36)
    q = SimpleNamespace(bid=69.83, ask=69.84, spread=0.01)
    assert _run(C, zelf, _signaal(None, 69.60), q) is False
    assert zelf._kostenfilter["per_opzet"] == {"daghandel": 1}


def test_daghandel_spot_ruime_stop_mag_door():
    C, zelf = _zelf(True, 0.36)
    q = SimpleNamespace(bid=69.83, ask=69.84, spread=0.01)
    assert _run(C, zelf, _signaal("daghandel", 66.00), q) == "verder"
    assert zelf._kostenfilter["overgeslagen"] == 0


def test_daghandel_goud_ongewijzigd():
    # Goud: zelfde krappe verhouding, maar daghandel valt niet onder het filter.
    C, zelf = _zelf(False, 0.86)
    q = SimpleNamespace(bid=4199.3, ask=4200.0, spread=0.7)
    assert _run(C, zelf, _signaal("daghandel", 4198.0), q) == "verder"
    assert zelf._kostenfilter["overgeslagen"] == 0


def test_veldproef_goud_blijft_gefilterd():
    C, zelf = _zelf(False, 0.86)
    q = SimpleNamespace(bid=4199.3, ask=4200.0, spread=0.7)
    assert _run(C, zelf, _signaal("vp:momentum:15m", 4196.0), q) is False
    assert zelf._kostenfilter["per_opzet"] == {"vp:momentum:15m": 1}


def test_spot_short_blijft_eerder_geweigerd():
    C, zelf = _zelf(True, 0.36)
    q = SimpleNamespace(bid=69.83, ask=69.84, spread=0.01)
    assert _run(C, zelf, _signaal("daghandel", 70.10, richting=-1), q) is False
    assert zelf._laatste_weigering == "spot: geen short mogelijk"
    assert zelf._kostenfilter["overgeslagen"] == 0


def test_spot_zonder_stop_niet_gefilterd():
    C, zelf = _zelf(True, 0.36)
    q = SimpleNamespace(bid=69.83, ask=69.84, spread=0.01)
    assert _run(C, zelf, _signaal("daghandel", None), q) == "verder"


def test_scalp_op_spot_ongewijzigd():
    # Alleen de daghandel komt erbij; scalp (op de mand uit) blijft zoals hij was.
    C, zelf = _zelf(True, 0.36)
    zelf.primaire_strategie = "scalp"
    q = SimpleNamespace(bid=69.83, ask=69.84, spread=0.01)
    assert _run(C, zelf, _signaal(None, 69.60), q) == "verder"
