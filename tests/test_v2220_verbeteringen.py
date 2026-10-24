"""2.22.0 - vier verbeteringen, elk door Ruud goedgekeurd (24-10).

A. Vrijdag afsluiten vóór de weekendsluiting (XAUUSD ging 23-10 met een open
   short het weekend in).
B. Spreadgrens 0,03 % in de mandkeuze (PEPE ~0,06 %, PUMP ~0,04 %).
C. Noodstop per markt in plaats van per mand (PEPE-EUR legde de hele mand
   stil).
D. Oordeel 'failed'/'passed' pas bij genoeg clusters (XAUUSD: 138 trades in 8
   clusters stond op 'failed').
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.broker import bitvavo as bv  # noqa: E402
from gold_scalper.broker import schedule  # noqa: E402
from gold_scalper.broker.risk import TradingState  # noqa: E402
from gold_scalper.storage import performance  # noqa: E402
from test_broker_cycle import FakeHass  # noqa: E402

AMS = ZoneInfo("Europe/Amsterdam")


def _ams(jaar, maand, dag, uur, minuut=0):
    return datetime(jaar, maand, dag, uur, minuut, tzinfo=AMS)


# --------------------------------------------------------------------------- #
# A. Weekendsluiting
# --------------------------------------------------------------------------- #

def test_rooster_ig_minuten_tot_weekendsluiting():
    # Vrijdag 23-10-2026; IG sluit spot goud vrijdag 23:00.
    assert schedule.minuten_tot_weekendsluiting(
        schedule.SPOT_GOLD, _ams(2026, 10, 23, 22, 10)) == pytest.approx(50)
    assert schedule.minuten_tot_weekendsluiting(
        schedule.SPOT_GOLD, _ams(2026, 10, 23, 21, 0)) == pytest.approx(120)
    # Na de sluiting, op donderdag (dagpauze) en in het weekend: geen.
    assert schedule.minuten_tot_weekendsluiting(
        schedule.SPOT_GOLD, _ams(2026, 10, 23, 23, 30)) is None
    assert schedule.minuten_tot_weekendsluiting(
        schedule.SPOT_GOLD, _ams(2026, 10, 22, 22, 30)) is None
    assert schedule.minuten_tot_weekendsluiting(
        schedule.SPOT_GOLD, _ams(2026, 10, 24, 12, 0)) is None
    # Weekendgoud sluit zijn eigen week zondag 23:40.
    assert schedule.minuten_tot_weekendsluiting(
        schedule.WEEKEND_GOLD, _ams(2026, 10, 25, 23, 0)) == pytest.approx(40)


def _ctrader():
    from gold_scalper.broker.ctrader import CTraderVenue

    v = CTraderVenue.__new__(CTraderVenue)
    dag = 86400
    blokken = []
    # Week begint zondag 00:00 (cTrader). Maandag t/m donderdag 00:01-22:59,
    # vrijdag 00:01-22:55 (Pepperstone sloot 23-10 om 22:55).
    for d in range(1, 5):
        blokken.append({"startSecond": d * dag + 60, "endSecond": d * dag + 22 * 3600 + 59 * 60})
    blokken.append({"startSecond": 5 * dag + 60, "endSecond": 5 * dag + 22 * 3600 + 55 * 60})
    v.symbool = {"schedule": blokken, "scheduleTimeZone": "Europe/Amsterdam"}
    return v


def test_ctrader_herkent_de_weekendsluiting_niet_de_dagpauze():
    v = _ctrader()
    assert v.minuten_tot_weekendsluiting(_ams(2026, 10, 23, 22, 30)) == pytest.approx(25)
    assert v.minuten_tot_weekendsluiting(_ams(2026, 10, 23, 21, 57)) == pytest.approx(58)
    # Donderdag 22:40: dagpauze van twee minuten, geen weekend.
    assert v.minuten_tot_weekendsluiting(_ams(2026, 10, 22, 22, 40)) is None
    # Vrijdag na sluiting en zaterdag: dicht, dus None.
    assert v.minuten_tot_weekendsluiting(_ams(2026, 10, 23, 23, 0)) is None
    assert v.minuten_tot_weekendsluiting(_ams(2026, 10, 24, 12, 0)) is None


def test_ctrader_aaneengesloten_blokken_tellen_als_een():
    from gold_scalper.broker.ctrader import CTraderVenue

    v = CTraderVenue.__new__(CTraderVenue)
    dag = 86400
    # Maandag 00:00 tot vrijdag 23:00 in losse dagblokken die op elkaar aansluiten.
    blokken = [{"startSecond": d * dag, "endSecond": (d + 1) * dag} for d in range(1, 5)]
    blokken.append({"startSecond": 5 * dag, "endSecond": 5 * dag + 23 * 3600})
    v.symbool = {"schedule": blokken, "scheduleTimeZone": "Europe/Amsterdam"}
    # Donderdag 23:30: het blok loopt door tot vrijdag 23:00 -> geen weekend binnen het uur,
    # wel een weekendsluiting (23,5 uur verder).
    assert v.minuten_tot_weekendsluiting(_ams(2026, 10, 22, 23, 30)) == pytest.approx(23.5 * 60)
    assert v.minuten_tot_weekendsluiting(_ams(2026, 10, 23, 22, 40)) == pytest.approx(20)


def _coord(venue, use_schedule=True):
    from gold_scalper.coordinator import GoldScalperCoordinator

    c = GoldScalperCoordinator.__new__(GoldScalperCoordinator)
    c.venue = venue
    c._use_schedule = use_schedule
    return c


def test_coordinator_crypto_heeft_geen_weekendsluiting():
    venue = SimpleNamespace(altijd_open=True, markt_open=lambda now: True,
                            minuten_tot_weekendsluiting=lambda now: 5.0)
    c = _coord(venue)
    assert c._minuten_tot_weekendsluiting(_ams(2026, 10, 23, 22, 50)) is None
    assert c._weekend_instap_reden(_ams(2026, 10, 23, 22, 50)) is None
    assert bv.BitvavoVenue.minuten_tot_weekendsluiting(None, datetime.now(timezone.utc)) is None


def test_coordinator_ig_rooster_laatste_uur_geen_instap():
    venue = SimpleNamespace()   # geen eigen rooster: IG-rooster
    c = _coord(venue)
    assert c._weekend_instap_reden(_ams(2026, 10, 23, 21, 30)) is None
    reden = c._weekend_instap_reden(_ams(2026, 10, 23, 22, 10))
    assert reden and "weekendsluiting over 50 min" in reden
    # Rooster uitgezet: het eigen IG-rooster telt dan niet.
    assert _coord(venue, use_schedule=False)._weekend_instap_reden(
        _ams(2026, 10, 23, 22, 10)) is None


def test_coordinator_ctrader_rooster_gaat_voor():
    v = _ctrader()
    c = _coord(v)
    assert c._minuten_tot_weekendsluiting(_ams(2026, 10, 23, 22, 30)) == pytest.approx(25)
    assert c._minuten_tot_weekendsluiting(_ams(2026, 10, 22, 22, 40)) is None


def _lus(tmp_path, monkeypatch, naam):
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

    class GoudVenue(SpotVenue):
        # Een markt die in het weekend dicht is.
        altijd_open = False

    class Entry:
        entry_id = naam
        data = {"venue": "simulator", "timeframe": "1m", "mode": "paper"}
        options = {"mode": "paper", "starting_balance": 10000.0, "update_seconds": 20,
                   "strategie": "scalp", "scalp_reeks": False, "risk_based_sizing": True,
                   "risk_per_trade_pct": 0.5, "entry_threshold": 0.05, "min_edge_multiple": 0.1}

    c = GoldScalperCoordinator(FakeHass(), Entry())
    c.venue = GoudVenue()
    c.mode = TradingMode.PAPER
    c.db = TradeDatabase(tmp_path / f"{naam}.db")
    c.db.connect()
    c.run_id = c.db.start_run("paper", "v1", "XAUUSD", {}, 10000.0, None, "fp")
    c.paper = PaperBroker(c.db, c.run_id, "XAUUSD", 10000.0, BrokerCosts(
        commission_per_lot_per_side=0.0, commission_rate=0.0025, base_slippage=0.0,
        volatility_slippage_factor=0.0, size_slippage_per_lot=0.0, leverage=1.0))
    c._enabled = True
    c._use_schedule = False
    c.lifecycle._transition(LifecycleState.RUNNING, "test")
    return c


def _trades(c):
    return c.db.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]


def test_lus_opent_niets_in_het_laatste_uur(tmp_path, monkeypatch):
    c = _lus(tmp_path, monkeypatch, "geen_instap")
    c._minuten_tot_weekendsluiting = lambda now: 45.0
    for _ in range(6):
        c.venue.prijs *= 1.003
        asyncio.run(c._async_update_data())
    assert _trades(c) == 0
    # Controle: zonder weekend opent dezelfde lus wel.
    c2 = _lus(tmp_path, monkeypatch, "wel_instap")
    c2._minuten_tot_weekendsluiting = lambda now: None
    for _ in range(6):
        c2.venue.prijs *= 1.003
        asyncio.run(c2._async_update_data())
    assert _trades(c2) >= 1


def test_lus_sluit_open_posities_voor_het_weekend(tmp_path, monkeypatch):
    c = _lus(tmp_path, monkeypatch, "sluiten")
    c._minuten_tot_weekendsluiting = lambda now: None
    for _ in range(6):
        c.venue.prijs *= 1.003
        asyncio.run(c._async_update_data())
        if c.paper.open_positions:
            break
    assert c.paper.open_positions, "eerst een open positie, anders bewijst de test niets"
    c._minuten_tot_weekendsluiting = lambda now: 20.0
    asyncio.run(c._async_update_data())
    assert not c.paper.open_positions
    redenen = [r[0] for r in c.db.conn.execute(
        "SELECT close_reason FROM trades WHERE close_reason IS NOT NULL")]
    assert any("weekendsluiting" in (r or "") for r in redenen)


def test_open_position_tweede_grendel():
    from gold_scalper.coordinator import GoldScalperCoordinator

    zelf = SimpleNamespace(
        koers_verouderd=False,
        _weekend_instap_reden=lambda now: "weekendsluiting over 30 min: geen nieuwe posities",
        _laatste_weigering=None,
    )
    signaal = SimpleNamespace(direction=1, components={})
    uit = asyncio.run(GoldScalperCoordinator._open_position(
        zelf, signaal, SimpleNamespace(bid=1.0, ask=1.1), datetime.now(timezone.utc)))
    assert uit is False
    assert "weekendsluiting" in zelf._laatste_weigering


# --------------------------------------------------------------------------- #
# B. Spreadgrens in de mandkeuze
# --------------------------------------------------------------------------- #

def _markt(naam):
    return {"market": naam, "status": "trading", "orderTypes": ["market", "limit", "stopLoss"]}


def _ticker(naam, volume, bid, ask):
    return {"market": naam, "volumeQuote": str(volume), "bid": str(bid), "ask": str(ask)}


def test_spreadgrens_is_003_procent():
    from gold_scalper.const import BV_MAND_MAX_SPREAD_PCT

    assert BV_MAND_MAX_SPREAD_PCT == pytest.approx(0.03)


def test_mandkeuze_weert_brede_spread_en_noemt_ze():
    markten = [_markt(m) for m in ("BTC-EUR", "ETH-EUR", "PEPE-EUR", "PUMP-EUR", "XRP-EUR")]
    tickers = [
        _ticker("BTC-EUR", 28e6, 72108.0, 72109.0),          # 0,0014 %
        _ticker("ETH-EUR", 9e6, 2122.6, 2122.61),             # 0,0005 %
        _ticker("PEPE-EUR", 8e6, 0.0000040442, 0.0000040464),  # ~0,054 %
        _ticker("PUMP-EUR", 1.1e6, 0.0037955, 0.0037967),     # ~0,032 %
        _ticker("XRP-EUR", 13e6, 1.1507, 1.15078),            # ~0,007 %
    ]
    geweerd: list = []
    uit = bv.kies_markten(markten, tickers, "EUR", 20, 250_000, 0.03,
                          verplicht=["BTC-EUR"], geweerd=geweerd)
    namen = [r["market"] for r in uit]
    assert namen == ["BTC-EUR", "XRP-EUR", "ETH-EUR"]
    assert [r["market"] for r in geweerd] == ["PEPE-EUR", "PUMP-EUR"]


class _Lid:
    def __init__(self, symbol, halted=False, bid=100.0, ask=100.001):
        self.symbol = symbol
        self.enabled = True
        self.entry = SimpleNamespace(entry_id=f"E1_{symbol}")
        self.mode = SimpleNamespace(places_orders=False)
        self.paper = SimpleNamespace(open_positions=[])
        self.venue = SimpleNamespace(_grootboek={})
        self.data = {"price": 1.0, "stats": {}, "equity": 10000}
        self._last_quote = SimpleNamespace(bid=bid, ask=ask)
        self.risk = SimpleNamespace(state=SimpleNamespace(
            state=TradingState.HALTED if halted else TradingState.RUNNING))


def _mand(hoofd):
    entry = SimpleNamespace(entry_id="E1", data={"venue": "bitvavo"}, options={})
    m = mand_mod.BitvavoMand(FakeHass(), entry, hoofd)
    m._gereed = True
    return m


def test_lid_met_brede_actuele_spread_opent_niets():
    m = _mand(_Lid("BTC-EUR"))
    breed = _Lid("WLD-EUR", bid=100.0, ask=100.05)   # 0,05 %
    smal = _Lid("ETH-EUR", bid=100.0, ask=100.001)    # 0,001 %
    m.leden = {"WLD-EUR": breed, "ETH-EUR": smal}
    mag, waarom = m.mag_openen(breed)
    assert not mag and "spread" in waarom and "0.03" in waarom
    assert m.mag_openen(smal)[0] is True


def test_mandkeuze_toont_de_grens(monkeypatch):
    hoofd = _Lid("BTC-EUR")
    hoofd.venue = SimpleNamespace(_grootboek={})
    m = _mand(hoofd)

    async def toppers(venue, aantal, min_volume, max_spread, verplicht=None, geweerd=None):
        assert max_spread == pytest.approx(0.03)
        geweerd.append({"market": "PEPE-EUR", "volume": 8e6, "spread_pct": 0.0544})
        return [{"market": "BTC-EUR", "volume": 28e6, "spread_pct": 0.0014}]

    monkeypatch.setattr(bv, "mand_toppers", toppers)
    asyncio.run(m._herzien_kern())
    o = m.overzicht()
    assert o["max_spread_pct"] == pytest.approx(0.03)
    assert o["geweerd_op_spread"] == [{"markt": "PEPE-EUR", "spread_pct": 0.0544}]


def test_mandkeuze_logt_de_grens():
    bron = open(os.path.join(os.path.dirname(__file__), "..", "custom_components",
                             "gold_scalper", "mand.py"), encoding="utf-8").read()
    assert "spreadgrens" in bron and "geweerd op spread" in bron


# --------------------------------------------------------------------------- #
# C. Noodstop per markt
# --------------------------------------------------------------------------- #

def test_noodstop_van_pepe_stopt_alleen_pepe():
    m = _mand(_Lid("BTC-EUR"))
    pepe = _Lid("PEPE-EUR", halted=True)
    xrp = _Lid("XRP-EUR")
    m.leden = {"PEPE-EUR": pepe, "XRP-EUR": xrp}
    mag, waarom = m.mag_openen(pepe)
    assert not mag and "noodstop bij PEPE-EUR" in waarom
    assert m.mag_openen(xrp)[0] is True
    assert m.mag_openen(m.hoofd)[0] is True
    o = m.overzicht()
    assert o["noodstop_markten"] == ["PEPE-EUR"]
    assert {r["markt"]: r["noodstop"] for r in o["per_markt"]}["PEPE-EUR"] is True


def test_noodstop_sensor_noemt_de_markt_en_dat_de_rest_doorgaat():
    from gold_scalper.binary_sensor import RiskHalted

    lid = SimpleNamespace(symbol="PEPE-EUR", risk=SimpleNamespace(
        as_dict=lambda: {"state": "halted", "halt_reason": "dagverlies 10.05%"}))
    risk = SimpleNamespace(as_dict=lambda: {"state": "running", "halt_reason": None})
    coordinator = SimpleNamespace(data=None, risk=risk, symbol="BTC-EUR")
    coordinator._mand = SimpleNamespace(leden={"PEPE-EUR": lid}, hoofd=coordinator)
    nep = SimpleNamespace(coordinator=coordinator)
    nep._risk = lambda: RiskHalted._risk(nep)
    attrs = RiskHalted.extra_state_attributes.fget(nep)
    assert attrs["markten"] == ["PEPE-EUR"]
    assert "rest van de mand" in attrs["geldt_voor"]


class _Coord:
    def __init__(self, symbol):
        self.symbol = symbol
        self.hervat = 0

    async def async_resume(self):
        self.hervat += 1
        return True


def _resume_dienst(coords):
    """Registreer de diensten op een nep-hass en geef de resume-handler."""
    import gold_scalper as gs

    geregistreerd = {}

    class Services:
        def has_service(self, domein, naam):
            return False

        def async_register(self, domein, naam, handler, schema=None, **kw):
            geregistreerd[naam] = (handler, schema)

    hass = SimpleNamespace(services=Services(), data={gs.DOMAIN: dict(coords)})
    gs._register_services(hass)
    return geregistreerd["resume"]


def test_resume_per_markt_of_alles():
    pepe, btc = _Coord("PEPE-EUR"), _Coord("BTC-EUR")
    handler, schema = _resume_dienst({"a": btc, "b": pepe})
    assert schema({"markt": "pepe-eur"}) == {"markt": "pepe-eur"}
    asyncio.run(handler(SimpleNamespace(data={"markt": "pepe-eur"})))
    assert (pepe.hervat, btc.hervat) == (1, 0)
    asyncio.run(handler(SimpleNamespace(data={})))
    assert (pepe.hervat, btc.hervat) == (2, 1)


def test_resume_onbekende_markt_geeft_fout(monkeypatch):
    import gold_scalper as gs

    class Fout(Exception):
        pass

    monkeypatch.setattr(gs, "HomeAssistantError", Fout)
    handler, _ = _resume_dienst({"a": _Coord("BTC-EUR")})
    with pytest.raises(Fout, match="DOGE-EUR"):
        asyncio.run(handler(SimpleNamespace(data={"markt": "DOGE-EUR"})))


def test_resume_dienst_beschrijft_markt():
    import yaml

    pad = os.path.join(os.path.dirname(__file__), "..", "custom_components",
                       "gold_scalper", "services.yaml")
    diensten = yaml.safe_load(open(pad, encoding="utf-8"))
    assert "markt" in diensten["resume"]["fields"]


# --------------------------------------------------------------------------- #
# D. Oordeel pas bij genoeg clusters
# --------------------------------------------------------------------------- #

def _trade(i, net, start, gat_min):
    from gold_scalper.storage.database import Trade

    open_t = start + timedelta(minutes=i * gat_min)
    return Trade(run_id=1, mode="paper", symbol="XAUUSD", side="buy", volume=0.01,
                 open_time=open_t.isoformat(), open_price=4000.0, open_mid=4000.0,
                 open_spread=0.3, close_time=(open_t + timedelta(minutes=2)).isoformat(),
                 gross_pnl=net + 0.5, net_pnl=net, total_cost=0.5)


def test_138_trades_in_8_clusters_is_insufficient_data():
    from gold_scalper.learning.onderzoek import MIN_CLUSTERS

    start = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
    trades = []
    for cluster in range(8):
        begin = start + timedelta(hours=12 * cluster)
        for j in range(18 if cluster < 2 else 17):
            trades.append(_trade(j, -1.0 if j % 2 else 0.9, begin, 3))
    stats = performance.compute(trades, 10000.0)
    assert stats["trades"] == 138
    assert stats["clusters"] == 8 < MIN_CLUSTERS
    assert stats["verdict"] == "insufficient_data"
    assert "clusters" in stats["verdict_text"]


def test_genoeg_clusters_maar_te_weinig_handelsdagen():
    start = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
    # 40 clusters op 2 dagen (elk 40 min uit elkaar).
    trades = [_trade(i, -1.0, start, 40) for i in range(40)]
    stats = performance.compute(trades * 3, 10000.0)
    assert stats["clusters"] >= 30
    assert stats["handelsdagen"] < performance.MIN_HANDELSDAGEN_OORDEEL
    assert stats["verdict"] == "insufficient_data"


def test_genoeg_clusters_en_dagen_geeft_failed():
    start = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
    trades = []
    for dag in range(7):
        for k in range(6):
            for j in range(3):
                t0 = start + timedelta(days=dag, hours=2 * k)
                trades.append(_trade(j, -1.0 if (j + k) % 2 else 0.8, t0, 3))
    stats = performance.compute(trades, 10000.0)
    assert stats["clusters"] >= 30 and stats["handelsdagen"] >= 5
    assert stats["verdict"] == "failed"


def test_passed_heeft_dezelfde_poort():
    stats = {"trades": 500, "clusters": 12, "handelsdagen": 20, "net_pnl": 500.0,
             "cost_ratio": 0.2, "total_costs": 50.0, "gross_pnl": 550.0,
             "edge_surplus_per_oz": 1.0, "avg_excursion_per_oz": 2.0,
             "breakeven_edge_per_oz": 1.0, "t_statistic": 3.0,
             "profit_factor": 1.8, "losses": 100, "max_drawdown_pct": 3.0}
    assert performance.verdict(stats)["verdict"] == "insufficient_data"
    stats["clusters"] = 40
    assert performance.verdict(stats)["verdict"] == "passed"


def test_harde_grens_blijft_failed_onder_de_clustergrens():
    stats = {"trades": 500, "clusters": 5, "handelsdagen": 2, "net_pnl": 500.0,
             "cost_ratio": 0.2, "total_costs": 50.0, "gross_pnl": 550.0,
             "edge_surplus_per_oz": 1.0, "avg_excursion_per_oz": 2.0,
             "breakeven_edge_per_oz": 1.0, "t_statistic": 3.0,
             "profit_factor": 1.8, "losses": 100, "max_drawdown_pct": 30.0}
    uit = performance.verdict(stats)
    assert uit["verdict"] == "failed"
    assert any("drawdown" in r for r in uit["blocking_reasons"])


def test_versie():
    from gold_scalper.const import INTEGRATION_VERSION

    assert tuple(map(int, INTEGRATION_VERSION.split("."))) >= (2, 22, 0)
