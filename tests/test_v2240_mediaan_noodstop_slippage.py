"""2.24.0 - drie verbeteringen, door Ruud goedgekeurd (26-10).

7. L-GS-025: de mand laat toe op de mediane spread over 24 uur (PUMP/PEPE
   wisselden elk uur in en uit op een momentopname).
8. L-GS-029: een dagverlies-noodstop van een eerdere handelsdag komt na een
   herstart niet terug (PEPE-EUR 10,05 %, BILL-EUR 10,11 % "uit een eerdere
   sessie"); een gewiste noodstop wordt nooit opnieuw geladen.
9. Slippage-melding van de papierbroker in significante cijfers en bp.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.broker import bitvavo as bv  # noqa: E402
from gold_scalper.broker.paper import BrokerCosts, PaperBroker, Quote, prijs_en_bp  # noqa: E402
from gold_scalper.broker.risk import RiskLimits, RiskManager, TradingState  # noqa: E402
from gold_scalper.spreadhistorie import MIN_WAARNEMINGEN, SPREAD_VENSTER_S, SpreadHistorie  # noqa: E402
from gold_scalper.storage import state as state_mod  # noqa: E402
from gold_scalper.storage.state import RuntimeState, StateStore  # noqa: E402
from gold_scalper.timeutil import trading_day  # noqa: E402
from test_broker_cycle import FakeHass  # noqa: E402

PKG = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")
T0 = 1_800_000_000.0


# --------------------------------------------------------------------------- #
# 7. Mediane spread over 24 uur
# --------------------------------------------------------------------------- #

def _vul(h, markt, waarden, start=T0, stap=900):
    for i, w in enumerate(waarden):
        h.waarneem(start + i * stap, {markt: w})
    return start + (len(waarden) - 1) * stap


def test_mediaan_pas_bij_genoeg_waarnemingen():
    h = SpreadHistorie()
    nu = _vul(h, "PEPE-EUR", [0.02] * (MIN_WAARNEMINGEN - 1))
    assert h.mediaan("PEPE-EUR", nu) is None          # te weinig: momentopname
    nu = _vul(h, "PEPE-EUR", [0.05], start=nu + 900)
    assert h.aantal("PEPE-EUR", nu) == MIN_WAARNEMINGEN
    assert h.mediaan("PEPE-EUR", nu) == pytest.approx(0.02)


def test_mediaan_negeert_een_uitschieter_en_kijkt_24_uur_terug():
    h = SpreadHistorie()
    nu = _vul(h, "PUMP-EUR", [0.05] * 20 + [0.02] * 30)
    assert h.mediaan("PUMP-EUR", nu) == pytest.approx(0.02)
    # Na 24 uur zijn de oude waarnemingen weg.
    later = nu + SPREAD_VENSTER_S + 1
    assert h.mediaan("PUMP-EUR", later) is None
    h.snoei(later)
    assert len(h) == 0


def test_waarnemingen_dicht_op_elkaar_tellen_als_een():
    h = SpreadHistorie()
    h.waarneem(T0, {"X-EUR": 0.01})
    h.waarneem(T0 + 60, {"X-EUR": 0.02})              # herziening en kwartier samen
    assert h.aantal("X-EUR", T0 + 60) == 1
    assert h.mediaan("X-EUR", T0 + 60, minimum=1) == pytest.approx(0.02)


def test_historie_overleeft_export_en_herstel():
    h = SpreadHistorie()
    nu = _vul(h, "PEPE-EUR", [0.04] * 15)
    data = json.loads(json.dumps(h.export()))         # zoals het bestand
    h2 = SpreadHistorie()
    h2.herstel(data, nu)
    assert h2.mediaan("PEPE-EUR", nu) == pytest.approx(0.04)
    h3 = SpreadHistorie()
    h3.herstel({"X": [["kapot"], [1, "nan?"]], "Y": None}, nu)
    assert len(h3) == 0
    h3.herstel("geen dict", nu)
    assert len(h3) == 0


def _markten(*namen):
    return [{"market": n, "status": "trading", "orderTypes": ["market", "stopLoss"]}
            for n in namen]


def _ticker(markt, spread_pct, volume=5e6, mid=1.0):
    half = mid * spread_pct / 100 / 2
    return {"market": markt, "bid": str(mid - half), "ask": str(mid + half),
            "volumeQuote": str(volume)}


def test_kies_markten_toetst_de_mediaan_niet_het_moment():
    markten = _markten("BTC-EUR", "PEPE-EUR", "PUMP-EUR", "NIEUW-EUR")
    tickers = [_ticker("BTC-EUR", 0.001, 3e7),
               _ticker("PEPE-EUR", 0.02, 8e6),    # nu smal, typisch breed
               _ticker("PUMP-EUR", 0.04, 6e6),    # nu breed, typisch smal
               _ticker("NIEUW-EUR", 0.02, 4e6)]   # geen historie: moment
    mediaan = {"PEPE-EUR": 0.055, "PUMP-EUR": 0.025, "BTC-EUR": 0.0012}.get
    geweerd: list = []
    uit = bv.kies_markten(markten, tickers, "EUR", 20, 250_000, 0.03,
                          verplicht=["BTC-EUR"], geweerd=geweerd, mediaan=mediaan)
    namen = [r["market"] for r in uit]
    assert namen == ["BTC-EUR", "PUMP-EUR", "NIEUW-EUR"]
    pump = next(r for r in uit if r["market"] == "PUMP-EUR")
    assert pump["spread_bron"] == "mediaan_24u" and pump["spread_mediaan_pct"] == 0.025
    assert pump["spread_pct"] == pytest.approx(0.04, abs=1e-4)   # actueel blijft zichtbaar
    nieuw = next(r for r in uit if r["market"] == "NIEUW-EUR")
    assert nieuw["spread_bron"] == "moment"
    assert [r["market"] for r in geweerd] == ["PEPE-EUR"]
    assert geweerd[0]["spread_mediaan_pct"] == 0.055


def test_kies_markten_zonder_mediaan_werkt_als_voorheen():
    markten = _markten("PEPE-EUR", "ETH-EUR")
    tickers = [_ticker("PEPE-EUR", 0.05, 8e6), _ticker("ETH-EUR", 0.002, 9e6)]
    geweerd: list = []
    uit = bv.kies_markten(markten, tickers, "EUR", 20, 250_000, 0.03, geweerd=geweerd)
    assert [r["market"] for r in uit] == ["ETH-EUR"]
    assert [r["market"] for r in geweerd] == ["PEPE-EUR"]
    # Een kapotte mediaanbron valt terug op het moment.
    def kapot(_m):
        raise RuntimeError("x")
    uit = bv.kies_markten(markten, tickers, "EUR", 20, 250_000, 0.03, mediaan=kapot)
    assert [r["market"] for r in uit] == ["ETH-EUR"]


class _Venue:
    quote_valuta = "EUR"

    def __init__(self, spreads):
        self.spreads = spreads
        self.verzoeken = 0

    async def markten(self):
        return _markten(*self.spreads)

    async def _request(self, methode, pad, **kw):
        self.verzoeken += 1
        return [_ticker(m, s, 5e6) for m, s in self.spreads.items()]


def test_mand_toppers_legt_vast_en_gebruikt_de_mediaan(monkeypatch):
    venue = _Venue({"BTC-EUR": 0.001, "PEPE-EUR": 0.02})
    h = SpreadHistorie()
    # 23 uur lang breed (0,05 %), elk kwartier.
    nu = T0
    for i in range(90):
        h.waarneem(nu - (90 - i) * 900, {"PEPE-EUR": 0.05})
    venue.spread_historie = h
    monkeypatch.setattr(bv, "time", bv.time, raising=False)
    import time as _time
    monkeypatch.setattr(_time, "time", lambda: nu)
    geweerd: list = []
    uit = asyncio.run(bv.mand_toppers(venue, 20, 250_000, 0.03, ["BTC-EUR"], geweerd))
    assert [r["market"] for r in uit] == ["BTC-EUR"]          # PEPE nu smal, maar geweerd
    assert geweerd and geweerd[0]["market"] == "PEPE-EUR"
    assert h.aantal("PEPE-EUR", nu) == 91                      # momentopname vastgelegd
    # Zonder historie op de venue: de momentopname (oud gedrag).
    venue2 = _Venue({"BTC-EUR": 0.001, "PEPE-EUR": 0.02})
    uit = asyncio.run(bv.mand_toppers(venue2, 20, 250_000, 0.03, ["BTC-EUR"]))
    assert [r["market"] for r in uit] == ["BTC-EUR", "PEPE-EUR"]


def test_spread_monster_alleen_markten_met_genoeg_volume():
    venue = _Venue({"BTC-EUR": 0.001, "USDC-EUR": 0.001})
    uit = asyncio.run(bv.spread_monster(venue, 250_000))
    assert set(uit) == {"BTC-EUR"}                            # geen stablecoin
    klein = bv.spreads_uit_tickers(_markten("A-EUR"), [_ticker("A-EUR", 0.01, 100_000)],
                                   "EUR", 250_000)
    assert klein == {}


class _Lid:
    def __init__(self, symbol, bid=100.0, ask=100.001):
        self.symbol = symbol
        self.enabled = True
        self.entry = SimpleNamespace(entry_id=f"E1_{symbol}")
        self.mode = SimpleNamespace(places_orders=False)
        self.paper = SimpleNamespace(open_positions=[])
        self.venue = SimpleNamespace(_grootboek={})
        self.data = {"price": 1.0, "stats": {}, "equity": 10000}
        self._last_quote = SimpleNamespace(bid=bid, ask=ask)
        self.risk = SimpleNamespace(state=SimpleNamespace(state=TradingState.RUNNING))


def _mand(hoofd):
    entry = SimpleNamespace(entry_id="E1", data={"venue": "bitvavo"}, options={})
    m = mand_mod.BitvavoMand(FakeHass(), entry, hoofd)
    m._gereed = True
    return m


def test_mand_bewaart_en_herstelt_de_historie():
    from homeassistant.helpers.storage import Store

    m = _mand(_Lid("BTC-EUR"))
    nu = __import__("time").time()
    for i in range(14):
        m.spread_historie.waarneem(nu - 3600 + i * 300, {"PUMP-EUR": 0.02})
    m._store = Store(None, 1, "x")
    asyncio.run(m._bewaar())
    opgeslagen = m._store._data
    assert "PUMP-EUR" in opgeslagen["spread_historie"]

    m2 = _mand(_Lid("BTC-EUR"))
    gedeeld = m._store

    class _Zelfde:
        def __init__(self, *a, **k):
            pass

        async def async_load(self):
            return gedeeld._data

    import homeassistant.helpers.storage as ha_storage
    oud = ha_storage.Store
    ha_storage.Store = _Zelfde
    try:
        asyncio.run(m2._bewaarde_markten())
    finally:
        ha_storage.Store = oud
    assert m2.spread_historie.mediaan("PUMP-EUR", nu) == pytest.approx(0.02)
    assert m2.spread_info("PUMP-EUR")["spread_waarnemingen_24u"] >= 12


def test_mand_koppelt_historie_aan_de_venue_en_neemt_monsters(monkeypatch):
    hoofd = _Lid("BTC-EUR")
    m = _mand(hoofd)
    m._koppel_historie()
    assert hoofd.venue.spread_historie is m.spread_historie

    async def monster(venue, min_volume):
        return {"PEPE-EUR": 0.05}

    bewaard = []

    async def bewaar():
        bewaard.append(True)

    monkeypatch.setattr(bv, "spread_monster", monster)
    monkeypatch.setattr(m, "_bewaar", bewaar)
    asyncio.run(m._neem_monster())
    assert m.spread_historie.aantal("PEPE-EUR", __import__("time").time()) == 1
    assert bewaard

    async def faalt(venue, min_volume):
        raise RuntimeError("geen netwerk")

    monkeypatch.setattr(bv, "spread_monster", faalt)
    asyncio.run(m._neem_monster())                      # geen uitzondering


def test_lid_opent_nog_steeds_niets_boven_de_actuele_spread():
    """Toelaten op de mediaan, openen op de actuele spread (wat het nu kost)."""
    m = _mand(_Lid("BTC-EUR"))
    pump = _Lid("PUMP-EUR", bid=100.0, ask=100.05)      # nu 0,05 %
    m.leden = {"PUMP-EUR": pump}
    nu = __import__("time").time()
    for i in range(20):
        m.spread_historie.waarneem(nu - 20 * 900 + i * 900, {"PUMP-EUR": 0.01})
    mag, waarom = m.mag_openen(pump)
    assert not mag and "spread" in waarom


def test_overzicht_toont_mediaan_en_bron(monkeypatch):
    hoofd = _Lid("BTC-EUR")
    m = _mand(hoofd)

    async def toppers(venue, aantal, min_volume, max_spread, verplicht=None, geweerd=None):
        geweerd.append({"market": "PEPE-EUR", "volume": 8e6, "spread_pct": 0.02,
                        "spread_mediaan_pct": 0.055, "spread_toelating_pct": 0.055,
                        "spread_bron": "mediaan_24u"})
        return [{"market": "BTC-EUR", "volume": 28e6, "spread_pct": 0.0014}]

    monkeypatch.setattr(bv, "mand_toppers", toppers)
    asyncio.run(m._herzien_kern())
    o = m.overzicht()
    assert o["spread_toelating"] == "mediaan_24u"
    assert o["geweerd_op_spread"] == [{"markt": "PEPE-EUR", "spread_pct": 0.02,
                                       "spread_mediaan_24u_pct": 0.055}]
    assert o["spread_mediaan_24u"] == {}                 # nog geen waarnemingen
    nu = __import__("time").time()
    for i in range(12):
        m.spread_historie.waarneem(nu - 12 * 900 + i * 900, {"BTC-EUR": 0.0012})
    assert m.overzicht()["spread_mediaan_24u"] == {"BTC-EUR": 0.0012}


# --------------------------------------------------------------------------- #
# 8. Oude dagverlies-noodstops niet terugzetten
# --------------------------------------------------------------------------- #

DAGVERLIES = "dagverlies 10.05% bereikt de limiet van 10.00% (waarvan -39.12 nog niet gerealiseerd)"


def _laad(raw, nu=None, entry="e"):
    store = StateStore(None, entry)
    store._store._data = {entry: raw}
    if nu is not None:
        store._nu = lambda: nu
    state = asyncio.run(store.async_load())
    return store, state


def _vandaag():
    return trading_day(datetime.now(timezone.utc))


def test_dagverlies_noodstop_van_gisteren_komt_niet_terug(caplog):
    gisteren = (_vandaag() - timedelta(days=1)).isoformat()
    with caplog.at_level(logging.INFO):
        store, state = _laad({"halted": True, "halt_reason": DAGVERLIES,
                              "halt_day": gisteren, "day": gisteren})
    assert not state.halted and state.halt_reason is None and state.halt_day is None
    assert store.vervallen_noodstop == DAGVERLIES
    assert "eerdere sessie blijft actief" not in caplog.text
    assert "niet teruggezet" in caplog.text
    # Meteen gewist in het bestand: nooit opnieuw geladen.
    assert store._store._data["e"]["halted"] is False
    _, opnieuw = _laad(store._store._data["e"])
    assert not opnieuw.halted


def test_dagverlies_noodstop_van_vandaag_blijft():
    vandaag = _vandaag().isoformat()
    store, state = _laad({"halted": True, "halt_reason": DAGVERLIES,
                          "halt_day": vandaag, "day": vandaag})
    assert state.halted and state.halt_reason == DAGVERLIES
    assert store.vervallen_noodstop is None


def test_andere_noodstops_blijven_altijd():
    lang_geleden = (_vandaag() - timedelta(days=5)).isoformat()
    for reden in ("equity 4000.00 onder de ondergrens van 5000.00 (configured)",
                  "geen tickdata gedurende 900s tijdens handelsuren",
                  "40 trades vandaag; limiet bereikt"):
        _, state = _laad({"halted": True, "halt_reason": reden,
                          "halt_day": lang_geleden, "day": lang_geleden})
        assert state.halted and state.halt_reason == reden


def test_oude_toestand_zonder_halt_day_leest_de_dag_uit_de_gebeurtenissen():
    """Een toestand van vóór 2.24.0: de dag uit de bewaarde NOODSTOP-regel."""
    gisteren_moment = datetime.now(timezone.utc) - timedelta(days=1, hours=1)
    regel = f"{gisteren_moment.isoformat(timespec='seconds')} NOODSTOP: {DAGVERLIES}"
    # state.day rolt door terwijl de noodstop staat: zegt niets.
    store, state = _laad({"halted": True, "halt_reason": DAGVERLIES,
                          "day": _vandaag().isoformat(), "risk_triggered": [regel]})
    assert not state.halted

    vandaag_regel = (f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
                     f"NOODSTOP: {DAGVERLIES}")
    _, state = _laad({"halted": True, "halt_reason": DAGVERLIES,
                      "day": _vandaag().isoformat(), "risk_triggered": [vandaag_regel]})
    assert state.halted and state.halt_day == _vandaag().isoformat()


def test_oude_toestand_zonder_enig_tijdstip():
    # Bewaarde handelsdag vandaag: voorzichtig laten staan.
    _, state = _laad({"halted": True, "halt_reason": DAGVERLIES,
                      "day": _vandaag().isoformat()})
    assert state.halted
    # Bewaarde handelsdag eerder: vervalt.
    _, state = _laad({"halted": True, "halt_reason": DAGVERLIES,
                      "day": (_vandaag() - timedelta(days=2)).isoformat()})
    assert not state.halted


def test_handelsdag_in_de_handelstijdzone():
    """De grens is de handelsdag (Europe/Amsterdam), niet 00:00 UTC."""
    dag = date(2026, 10, 25)
    nu = datetime(2026, 10, 25, 23, 30, tzinfo=timezone.utc)  # 00:30 Amsterdam op 26-10
    assert trading_day(nu) == date(2026, 10, 26)
    _, state = _laad({"halted": True, "halt_reason": DAGVERLIES,
                      "halt_day": dag.isoformat()}, nu=nu)
    assert not state.halted
    nu2 = datetime(2026, 10, 25, 21, 30, tzinfo=timezone.utc)  # 23:30 Amsterdam op 25-10
    _, state = _laad({"halted": True, "halt_reason": DAGVERLIES,
                      "halt_day": dag.isoformat()}, nu=nu2)
    assert state.halted


def test_risk_houdt_de_dag_van_de_noodstop_bij():
    r = RiskManager(RiskLimits(), 10000.0)
    r.halt("dagverlies 11.00% bereikt de limiet van 10.00%")
    assert r.state.halt_day == _vandaag()
    r.manual_resume(9000.0)
    assert r.state.halt_day is None
    r.restore_halt("x", date(2026, 10, 1))
    assert r.state.halt_day == date(2026, 10, 1)
    r.reset_day(9000.0)
    assert r.state.halt_day is None


def test_coordinator_bewaart_en_herstelt_de_dag(monkeypatch):
    from test_release_175 import _bouw, _start, _stop
    from test_broker_cycle import ScriptedVenue

    hass = FakeHass()
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    a.risk.halt("dagverlies 12.00% bereikt de limiet van 10.00%")
    asyncio.run(a._persist())
    bewaard = a._store._store._data["test"]
    assert bewaard["halted"] and bewaard["halt_day"] == _vandaag().isoformat()
    _stop(a)

    b = _bouw(hass, venue)
    b._store._store._data = {"test": dict(bewaard)}
    _start(b)
    assert b.risk.state.state is TradingState.HALTED
    assert b.risk.state.halt_day == _vandaag()

    # Dezelfde noodstop, maar van gisteren: niet terug, en na het bewaren weg.
    oud = dict(bewaard, halt_day=(_vandaag() - timedelta(days=1)).isoformat())
    c = _bouw(hass, venue)
    c._store._store._data = {"test": oud}
    _start(c)
    assert c.risk.state.state is not TradingState.HALTED
    asyncio.run(c._persist())
    assert c._store._store._data["test"]["halted"] is False
    assert c._store._store._data["test"]["halt_day"] is None


def test_is_dagverlies_noodstop():
    assert state_mod.is_dagverlies_noodstop(DAGVERLIES)
    assert not state_mod.is_dagverlies_noodstop("equity onder de ondergrens")
    assert not state_mod.is_dagverlies_noodstop(None)
    assert not state_mod.verlopen_dagverlies_noodstop(RuntimeState(), _vandaag())


# --------------------------------------------------------------------------- #
# 9. Slippage-melding
# --------------------------------------------------------------------------- #

def test_prijs_en_bp():
    assert prijs_en_bp(4.2e-08, 4.9e-06) == "4.2e-08 (85.71 bp)"
    assert prijs_en_bp(0.35, 4000.0) == "0.35 (0.88 bp)"
    assert prijs_en_bp(0.001, None) == "0.001"
    assert prijs_en_bp("x", 1.0) == "x"


def test_slippage_melding_bij_een_goedkope_munt(caplog):
    costs = BrokerCosts(base_slippage=1.0)       # absurd voor een munt van 0,0000049
    import random

    broker = PaperBroker.__new__(PaperBroker)
    broker.costs = costs
    broker._rng = random.Random(1)
    q = Quote(bid=0.0000049, ask=0.00000491, time=datetime.now(timezone.utc))
    with caplog.at_level(logging.WARNING):
        broker._slippage(q, 0.1)
    tekst = caplog.text
    assert "begrensd op" in tekst and "0.000 begrensd op 0.000" not in tekst
    assert "bp)" in tekst and "2e-08" in tekst


def test_logregels_niet_meer_in_vaste_decimalen():
    bron = open(os.path.join(PKG, "broker", "paper.py"), encoding="utf-8").read()
    assert "%.3f begrensd" not in bron and "%.6g begrensd" not in bron
    co = open(os.path.join(PKG, "coordinator.py"), encoding="utf-8").read()
    assert "slippage %.3f)" not in co and "Gemeten slippage %.3f" not in co


def test_versie():
    from gold_scalper.const import INTEGRATION_VERSION

    manifest = json.load(open(os.path.join(PKG, "manifest.json"), encoding="utf-8"))
    assert manifest["version"] == INTEGRATION_VERSION
    assert tuple(int(x) for x in INTEGRATION_VERSION.split(".")) >= (2, 24, 0)


def test_attributen_met_mediaan_blijven_onder_de_recordergrens():
    """Volle mand (20 leden, 40+40 vertrokken) mét mediaan per lid en per
    geweerde markt: onder de 16 kB van de recorder (met marge)."""
    import time as _time

    from test_v2231_mand_opstart_en_attributen import _mand_vol

    m = _mand_vol(20, 40, 40)
    m.geweerd_spread = [{"market": f"G{i}-EUR", "spread_pct": 0.1234,
                         "spread_mediaan_pct": 0.0567} for i in range(30)]
    nu = _time.time()
    for i in range(20):
        m.spread_historie.waarneem(nu - 20 * 900 + i * 900,
                                   {c.symbol: 0.01234 for c in m.alle()})
    o = m.overzicht()
    assert len(o["spread_mediaan_24u"]) == 20
    attrs = {k: v for k, v in o.items() if k != "markten"}
    grootte = len(json.dumps(attrs, default=str).encode())
    assert grootte < 15_500, grootte
