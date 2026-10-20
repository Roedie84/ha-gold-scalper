"""2.18.0 - de Bitvavo-mand: handelen op de meest liquide markten.

Gevraagd 20-10: "Ik wil dat de integratie op alle markten analyseert en zelf
handelt, niet op alleen BTC". Gekozen: de toppers op volume en spread (elk uur
herzien), hooguit een aantal posities over de hele mand, per koop de maximale
inzet.
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.broker import bitvavo as bv  # noqa: E402
from test_broker_cycle import FakeHass  # noqa: E402


def _markt(naam, status="trading", soorten=("market", "limit", "stopLoss")):
    return {"market": naam, "status": status, "orderTypes": list(soorten)}


def _ticker(naam, volume, bid, ask):
    return {"market": naam, "volumeQuote": str(volume), "bid": str(bid), "ask": str(ask)}


# --------------------------------------------------------------------------- #
# Samenstelling
# --------------------------------------------------------------------------- #

def test_de_toppers_op_volume_zonder_stablecoins_dunne_of_dure_markten():
    markten = [_markt("BTC-EUR"), _markt("ETH-EUR"), _markt("SOL-EUR"), _markt("USDC-EUR"),
               _markt("DUN-EUR"), _markt("WIJD-EUR"), _markt("ETH-BTC"),
               _markt("HALT-EUR", status="halted"), _markt("NOSTOP-EUR", soorten=("market",))]
    tickers = [
        _ticker("BTC-EUR", 50_000_000, 90000, 90010),
        _ticker("ETH-EUR", 20_000_000, 3000, 3000.5),
        _ticker("SOL-EUR", 5_000_000, 150, 150.05),
        _ticker("USDC-EUR", 90_000_000, 0.92, 0.9201),        # stablecoin
        _ticker("DUN-EUR", 1_000, 1.0, 1.001),                # te weinig handel
        _ticker("WIJD-EUR", 9_000_000, 1.0, 1.01),            # 1 % spread
        _ticker("ETH-BTC", 9_000_000, 0.03, 0.03001),         # geen EUR
        _ticker("HALT-EUR", 9_000_000, 1.0, 1.0001),
        _ticker("NOSTOP-EUR", 9_000_000, 1.0, 1.0001),
    ]
    uit = bv.kies_markten(markten, tickers, "EUR", 20, 250_000, 0.2)
    assert [r["market"] for r in uit] == ["BTC-EUR", "ETH-EUR", "SOL-EUR"]


def test_de_gekozen_markt_staat_altijd_vooraan_en_het_aantal_klopt():
    markten = [_markt(f"M{i}-EUR") for i in range(10)] + [_markt("KLEIN-EUR")]
    tickers = [_ticker(f"M{i}-EUR", 1_000_000 * (i + 1), 10, 10.001) for i in range(10)]
    tickers.append(_ticker("KLEIN-EUR", 10, 10, 10.001))
    uit = bv.kies_markten(markten, tickers, "EUR", 4, 250_000, 0.2, verplicht=["klein-eur"])
    assert [r["market"] for r in uit] == ["KLEIN-EUR", "M9-EUR", "M8-EUR", "M7-EUR"]


# --------------------------------------------------------------------------- #
# Gedeeld: posities en schakelaar
# --------------------------------------------------------------------------- #

def _lid(symbol, open_=0, live=False, grootboek=None):
    return SimpleNamespace(
        symbol=symbol, enabled=True,
        mode=SimpleNamespace(places_orders=live),
        paper=SimpleNamespace(open_positions=[object()] * open_),
        venue=SimpleNamespace(_grootboek=grootboek or {}),
    )


def _mand(hoofd, **opties):
    entry = SimpleNamespace(entry_id="E1", data={"venue": "bitvavo", **opties}, options={})
    return mand_mod.BitvavoMand(FakeHass(), entry, hoofd)


def test_hooguit_het_maximum_aantal_posities_over_de_hele_mand():
    hoofd = _lid("BTC-EUR", open_=1)
    m = _mand(hoofd, bitvavo_max_posities=3)
    m.leden = {"ETH-EUR": _lid("ETH-EUR", open_=1), "SOL-EUR": _lid("SOL-EUR")}
    assert m.mag_openen(m.leden["SOL-EUR"]) == (True, None)
    m.leden["XRP-EUR"] = _lid("XRP-EUR", live=True, grootboek={"t1": {}})
    mag, waarom = m.mag_openen(m.leden["SOL-EUR"])
    assert not mag and "3 van hooguit 3" in waarom


def test_een_toegezegde_plek_telt_mee_tot_de_positie_er_is():
    hoofd = _lid("BTC-EUR")
    m = _mand(hoofd, bitvavo_max_posities=1)
    m.leden = {"ETH-EUR": _lid("ETH-EUR"), "SOL-EUR": _lid("SOL-EUR")}
    assert m.mag_openen(m.leden["ETH-EUR"])[0] is True
    # ETH is nog bezig met de order; SOL mag niet ook.
    assert m.mag_openen(m.leden["SOL-EUR"])[0] is False
    m.leden["ETH-EUR"].paper.open_positions = [object()]
    assert m.aantal_open() == 1                        # niet dubbel geteld
    m.leden["ETH-EUR"].paper.open_positions = []
    m._toegezegd["ETH-EUR"] = (m._toegezegd["ETH-EUR"][0] - 31, 0)
    assert m.mag_openen(m.leden["SOL-EUR"])[0] is True  # mislukte order: plek vrij


def test_een_uitgefaseerde_markt_opent_niets_nieuws():
    hoofd = _lid("BTC-EUR")
    m = _mand(hoofd)
    m.leden = {"OUD-EUR": _lid("OUD-EUR", open_=1)}
    m.uitfaseren.add("OUD-EUR")
    assert m.mag_openen(m.leden["OUD-EUR"])[0] is False


def test_herzien_start_nieuwe_markten_en_stopt_of_faseert_uit(monkeypatch):
    hoofd = _lid("BTC-EUR")
    m = _mand(hoofd, bitvavo_aantal_markten=3)
    gestart, gestopt = [], []

    async def start(markt):
        gestart.append(markt)
        m.leden[markt] = _lid(markt, open_=1 if markt == "ETH-EUR" else 0)

    async def stop(markt):
        gestopt.append(markt)
        m.leden.pop(markt, None)

    monkeypatch.setattr(m, "_start_lid", start)
    monkeypatch.setattr(m, "_stop_lid", stop)
    selecties = iter([
        [{"market": "BTC-EUR"}, {"market": "ETH-EUR"}, {"market": "SOL-EUR"}],
        [{"market": "BTC-EUR"}, {"market": "XRP-EUR"}, {"market": "ADA-EUR"}],
    ])

    async def toppers(*a, **k):
        return next(selecties)

    monkeypatch.setattr(bv, "mand_toppers", toppers)
    asyncio.run(m._herzien())
    assert gestart == ["ETH-EUR", "SOL-EUR"]
    asyncio.run(m._herzien())
    # SOL zonder positie: gestopt. ETH met positie: blijft, maar opent niets.
    assert "SOL-EUR" in gestopt and "ETH-EUR" not in gestopt
    assert "ETH-EUR" in m.uitfaseren and set(m.leden) == {"ETH-EUR", "XRP-EUR", "ADA-EUR"}
    # ETH is plat: bij de volgende herziening gestopt.
    m.leden["ETH-EUR"].paper.open_positions = []
    selecties = iter([[{"market": "BTC-EUR"}, {"market": "XRP-EUR"}, {"market": "ADA-EUR"}]])
    monkeypatch.setattr(bv, "mand_toppers", lambda *a, **k: _als(next(selecties)))
    asyncio.run(m._herzien())
    assert "ETH-EUR" in gestopt and not m.uitfaseren


async def _als(waarde):
    return waarde


def test_markten_met_een_positie_komen_terug_na_een_herstart(monkeypatch):
    hoofd = _lid("BTC-EUR")
    m = _mand(hoofd)
    gestart = []

    async def start(markt):
        gestart.append(markt)
        m.leden[markt] = _lid(markt, open_=1)

    monkeypatch.setattr(m, "_start_lid", start)
    monkeypatch.setattr(bv, "mand_toppers", lambda *a, **k: _als([{"market": "BTC-EUR"}]))
    asyncio.run(m._herzien(extra=["DOGE-EUR"]))
    assert gestart == ["DOGE-EUR"]
    # Geen topper: alleen nog afbouwen, niets nieuws openen.
    assert "DOGE-EUR" in m.uitfaseren
    assert m.mag_openen(m.leden["DOGE-EUR"])[0] is False


def test_de_schakelaar_geldt_voor_de_hele_mand():
    hoofd = _lid("BTC-EUR")
    m = _mand(hoofd)
    gezet = []

    class Lid:
        enabled = True

        async def async_set_enabled(self, waarde):
            gezet.append(waarde)
            self.enabled = waarde

    m.leden = {"ETH-EUR": Lid(), "SOL-EUR": Lid()}
    asyncio.run(m.zet_aan(False))
    assert gezet == [False, False]


def test_een_lid_heeft_een_eigen_opslag_en_markt():
    entry = SimpleNamespace(entry_id="E1", data={"venue": "bitvavo", "bitvavo_markt": "BTC-EUR",
                                                 "symbol": "BTC-EUR"},
                            options={"mode": "paper"}, title="mand")
    lid = mand_mod.LidEntry(entry, "eth-eur")
    assert lid.entry_id == "E1_eth-eur" and lid.hoofd_entry_id == "E1"
    assert lid.data["bitvavo_markt"] == "ETH-EUR" and lid.data["symbol"] == "ETH-EUR"
    assert lid.options == {"mode": "paper"}
    assert lid.title.startswith("ETH-EUR")


def test_mand_of_een_markt():
    assert mand_mod.is_mand({"venue": "bitvavo"})
    assert not mand_mod.is_mand({"venue": "bitvavo", "bitvavo_markten": "een"})
    assert not mand_mod.is_mand({"venue": "ig"})


# --------------------------------------------------------------------------- #
# De poort op het bewijs van de hele mand
# --------------------------------------------------------------------------- #

def test_de_poort_telt_de_trades_van_alle_markten(tmp_path, monkeypatch):
    from gold_scalper.storage.database import Trade, TradeDatabase

    def db_met(naam, n):
        db = TradeDatabase(tmp_path / f"{naam}.db")
        db.connect()
        run = db.start_run("paper", "v1", naam, {}, 10000.0, None, "fp")
        for i in range(n):
            db.insert_trade(Trade(
                run_id=run, mode="paper", symbol=naam, side="buy", volume=0.01,
                open_time=f"2026-10-20T10:{i:02d}:00+00:00", open_price=100.0,
                open_mid=100.0, open_spread=0.1,
                close_time=f"2026-10-20T10:{i:02d}:30+00:00", close_price=101.0,
                gross_pnl=1.0, net_pnl=0.5, total_cost=0.5))
        return db

    def lid(naam, n):
        c = SimpleNamespace(symbol=naam, db=db_met(naam, n), strategie_versie="v1",
                            robustness=None, _boekhouding_status=lambda: {})
        c._laatste_papieren_run = lambda c=c: \
            mand_mod_coord._laatste_papieren_run(c)
        return c

    from gold_scalper.coordinator import GoldScalperCoordinator
    global mand_mod_coord
    mand_mod_coord = GoldScalperCoordinator
    hoofd = lid("BTC-EUR", 3)
    m = _mand(hoofd)
    m.leden = {"ETH-EUR": lid("ETH-EUR", 4)}
    gezien = {}

    class Poort:
        def evaluate(self, stats, run, daily, robustness, boekhouding):
            gezien["trades"] = stats.get("trades")
            return SimpleNamespace(as_dict=lambda: {"unlocked": False})

    import gold_scalper.modes as modes
    monkeypatch.setattr(modes, "LiveGate", Poort)
    gate = asyncio.run(m.poort())
    assert gezien["trades"] == 7
    assert gate["mand"] == {"markten": 2, "trades": 7}


# --------------------------------------------------------------------------- #
# Gedeelde opslag: entries overschrijven elkaar niet meer
# --------------------------------------------------------------------------- #

def test_twee_entries_overschrijven_elkaars_toestand_niet():
    from gold_scalper.storage.state import RuntimeState, StateStore

    hass = FakeHass()
    bewaard = {}

    class Opslag:
        def __init__(self, *a, **k):
            pass

        async def async_load(self):
            return dict(bewaard.get("x") or {})

        async def async_save(self, data):
            bewaard["x"] = {k: dict(v) for k, v in data.items()}

    import gold_scalper.storage.state as st
    oud = st.Store
    st.Store = Opslag
    try:
        a, b = StateStore(hass, "A"), StateStore(hass, "B")
        asyncio.run(a.async_load())
        asyncio.run(b.async_load())
        asyncio.run(a.async_save(RuntimeState(enabled=True, halted=True, halt_reason="noodstop")))
        asyncio.run(b.async_save(RuntimeState(enabled=False)))
    finally:
        st.Store = oud
    assert bewaard["x"]["A"]["halted"] is True            # B wiste de noodstop van A niet
    assert bewaard["x"]["B"]["enabled"] is False


# --------------------------------------------------------------------------- #
# In de handelslus: de mand houdt een nieuwe positie tegen
# --------------------------------------------------------------------------- #

def test_de_lus_opent_niets_als_de_mand_vol_zit(tmp_path, monkeypatch):
    import gold_scalper.coordinator as co
    from gold_scalper.broker.paper import BrokerCosts, PaperBroker
    from gold_scalper.coordinator import GoldScalperCoordinator
    from gold_scalper.lifecycle import LifecycleState
    from gold_scalper.modes import TradingMode
    from gold_scalper.storage.database import TradeDatabase
    from gold_scalper.strategy.scalping import ScalpSignal
    from test_v2170_bitvavo import SpotVenue

    def nep(candles, bid, ask, cfg, uur, aantal, sinds, kant, per_richting=None):
        afstand = ask * 0.01
        return ScalpSignal(direction=1, score=0.6, confidence=0.8, should_trade=True,
                           reject_reason=None, reason="test", stop_loss=ask - afstand,
                           take_profit=ask + 2 * afstand, geldig=True)

    monkeypatch.setattr(co, "evaluate", nep)

    class Entry:
        entry_id = "bv"
        data = {"venue": "simulator", "timeframe": "1m", "mode": "paper"}
        options = {"mode": "paper", "starting_balance": 10000.0, "update_seconds": 20,
                   "strategie": "scalp", "scalp_reeks": False, "risk_based_sizing": True,
                   "risk_per_trade_pct": 0.5, "entry_threshold": 0.05, "min_edge_multiple": 0.1}

    def lus(vol):
        c = GoldScalperCoordinator(FakeHass(), Entry())
        c.venue = SpotVenue()
        c.mode = TradingMode.PAPER
        c.db = TradeDatabase(tmp_path / f"bv{vol}.db")
        c.db.connect()
        c.run_id = c.db.start_run("paper", "v1", "BTC-EUR", {}, 10000.0, None, "fp")
        c.paper = PaperBroker(c.db, c.run_id, "BTC-EUR", 10000.0, BrokerCosts(
            commission_per_lot_per_side=0.0, commission_rate=0.0025, base_slippage=0.0,
            volatility_slippage_factor=0.0, size_slippage_per_lot=0.0, leverage=1.0))
        c._enabled = True
        c._use_schedule = False
        c.lifecycle._transition(LifecycleState.RUNNING, "test")
        m = _mand(c, bitvavo_max_posities=1)
        m.leden = {"ETH-EUR": _lid("ETH-EUR", open_=1 if vol else 0)}
        c._mand = m
        for _ in range(6):
            c.venue.prijs *= 1.003
            asyncio.run(c._async_update_data())
        return c, c.db.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    _, zonder = lus(False)
    assert zonder >= 1, "zonder volle mand opent de lus wel; anders bewijst de test niets"
    c, met = lus(True)
    assert met == 0
    assert "mand" in (c._laatste_weigering or "")


# --------------------------------------------------------------------------- #
# Review 2.18.0: noodstop, onbevestigd, vermogen, opslag, afstemming
# --------------------------------------------------------------------------- #

def test_een_noodstop_bij_een_markt_houdt_de_hele_mand_tegen():
    from gold_scalper.broker.risk import TradingState

    hoofd = _lid("BTC-EUR")
    m = _mand(hoofd)
    eth = _lid("ETH-EUR")
    eth.risk = SimpleNamespace(state=SimpleNamespace(state=TradingState.HALTED))
    m.leden = {"ETH-EUR": eth, "SOL-EUR": _lid("SOL-EUR")}
    mag, waarom = m.mag_openen(m.leden["SOL-EUR"])
    assert not mag and "noodstop bij ETH-EUR" in waarom


def test_een_koop_zonder_antwoord_bezet_een_plek():
    hoofd = _lid("BTC-EUR")
    m = _mand(hoofd, bitvavo_max_posities=1)
    eth = _lid("ETH-EUR", live=True)
    eth.venue._onbevestigd = {"gs-1": "uuid"}
    m.leden = {"ETH-EUR": eth, "SOL-EUR": _lid("SOL-EUR")}
    assert m.mag_openen(m.leden["SOL-EUR"])[0] is False
    eth.venue._onbevestigd = {"gs-1": "afgewezen:uuid"}
    assert m.mag_openen(m.leden["SOL-EUR"])[0] is True


def test_het_vermogen_is_dat_van_de_hele_mand():
    from test_v2170_bitvavo import venue

    v, fake = venue()
    m = _mand(_lid("BTC-EUR"))
    eth = _lid("ETH-EUR")
    eth.venue = SimpleNamespace(_grootboek={"t": {"units": 2.0}})
    eth._last_quote = SimpleNamespace(bid=3000.0)
    m.hoofd.venue = v
    m.leden = {"ETH-EUR": eth}
    v.mand_waarde = m.waarde_elders
    acc = asyncio.run(v.account())
    assert acc.equity == pytest.approx(acc.balance + 6000.0)


def test_een_entry_verwijderen_wist_de_andere_entries_niet():
    from gold_scalper.storage.state import RuntimeState, StateStore

    hass = FakeHass()
    a = StateStore(hass, "A")
    asyncio.run(a.async_load())
    asyncio.run(a.async_save(RuntimeState(halted=True, halt_reason="noodstop")))
    asyncio.run(StateStore(hass, "B").async_save(RuntimeState(enabled=True)))
    asyncio.run(StateStore(hass, "B_eth-eur").async_save(RuntimeState(enabled=True)))
    # Verwijderen met een nieuw, nooit geladen object (zoals async_remove_entry).
    asyncio.run(StateStore(hass, "B").async_remove())
    asyncio.run(StateStore(hass, "X").async_load())
    gedeeld = hass.data["gold_scalper_gedeelde_stores"]
    inhoud = next(iter(gedeeld.values()))["all"]
    assert "A" in inhoud and inhoud["A"]["halted"] is True
    assert "B" not in inhoud and "B_eth-eur" not in inhoud


def test_de_mand_poort_blijft_dicht_bij_een_afwijking_in_een_lid(monkeypatch):
    hoofd = _lid("BTC-EUR")
    hoofd._laatste_papieren_run = lambda: 1
    hoofd.db = SimpleNamespace(closed_trades=lambda run: [], get_run=lambda run: {})
    hoofd.robustness = None
    hoofd._boekhouding_status = lambda: {"afwijkingen": 0, "kritiek_open": 0}
    eth = _lid("ETH-EUR")
    eth._laatste_papieren_run = lambda: None
    eth._boekhouding_status = lambda: {"afwijkingen": 2, "kritiek_open": 0}
    m = _mand(hoofd)
    m.leden = {"ETH-EUR": eth}

    class Poort:
        def evaluate(self, *a):
            return SimpleNamespace(as_dict=lambda: {"unlocked": True, "blocking_reasons": []})

    import gold_scalper.modes as modes
    import gold_scalper.storage.performance as perf
    monkeypatch.setattr(modes, "LiveGate", Poort)
    monkeypatch.setattr(perf, "compute_for_run", lambda db, run, trades: {"trades": 0})
    gate = asyncio.run(m.poort())
    assert gate["unlocked"] is False
    assert any("ETH-EUR" in r for r in gate["blocking_reasons"])


def test_stoppen_is_veilig_twee_keer_en_bewaart_eerst():
    m = _mand(_lid("BTC-EUR"))
    gestopt = []

    async def stop(markt, al_weg=None):
        gestopt.append(markt)
        m.leden.pop(markt, None)

    m._stop_lid = stop
    m.leden = {"ETH-EUR": _lid("ETH-EUR", open_=1)}
    bewaard = {}

    class Opslag:
        async def async_save(self, data):
            bewaard.update(data)

    m._store = Opslag()
    asyncio.run(m.async_stop())
    asyncio.run(m.async_stop())
    assert gestopt == ["ETH-EUR"]
    assert bewaard["met_positie"] == ["ETH-EUR"]
    assert m.mag_openen(_lid("BTC-EUR"))[0] is False
