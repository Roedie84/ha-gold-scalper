"""1.9.0: tot 3 posities per richting (long en short tegelijk) en schaduwtrades.

Besluit van de eigenaar (09-10-2026): meer posities om sneller data te
verzamelen; long en short mogen naast elkaar. Alles wat per positie werkt
(tijdstop, sluiten na bevestiging, afstemming) moet per ticket blijven
werken, en geldige signalen die niet worden uitgevoerd worden als
schaduwtrade gesimuleerd - buiten het echte resultaat.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.analysis.signals import Candles  # noqa: E402
from gold_scalper.broker.adapter import OrderResult, VenuePosition, VenueQuote  # noqa: E402
from gold_scalper.broker.exits import ExitAction, ExitConfig, ExitManager  # noqa: E402
from gold_scalper.broker.risk import TradingState  # noqa: E402
from gold_scalper.broker.simulator import SimulatorVenue  # noqa: E402
from gold_scalper.storage import performance  # noqa: E402
from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402
from gold_scalper.strategy import posities as P  # noqa: E402
from gold_scalper.strategy.scalping import ScalpConfig, ScalpSignal, evaluate  # noqa: E402
from gold_scalper.strategy.schaduw import (  # noqa: E402
    SCHADUW_REDENEN, SchaduwBoek, SchaduwKosten, schaduw_statistiek,
)

from test_broker_cycle import ScriptedVenue, _coordinator  # noqa: E402
from test_ig_capital import MARKET, ig  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
T0 = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)   # woensdag, markt open


# ======================================================================= #
# Strategie: limiet per richting                                          #
# ======================================================================= #

class _VasteKlok(datetime):
    """1.9.5: de simulator rekent zijn candles vanaf 'nu'; op een vast moment
    zijn deze tests niet meer afhankelijk van het tijdstip waarop ze draaien
    (op 09-10 15:xx UTC was de spread daar te breed voor de ATR)."""

    @classmethod
    def now(cls, tz=None):
        return T0 if tz is not None else T0.replace(tzinfo=None)


@pytest.fixture(scope="module")
def market():
    import gold_scalper.broker.simulator as sim

    echt = sim.datetime
    sim.datetime = _VasteKlok
    try:
        venue = SimulatorVenue(seed=20260825)
        candles = asyncio.run(venue.candles("XAU_USD", "5m", 900))
    finally:
        sim.datetime = echt
    w = slice(300, 700)
    return Candles(candles.timestamp[w], candles.open[w], candles.high[w],
                   candles.low[w], candles.close[w], candles.volume[w])


def _cfg(**kw):
    basis = dict(commission_per_lot_per_side=0.0, volume=0.10, max_spread=9.0,
                 max_spread_atr_ratio=1.0, quiet_floor=0.0,
                 min_edge_multiple=0.01, entry_threshold=0.0)
    basis.update(kw)
    return ScalpConfig(**basis)


def _eval(market, per_richting, sinds=1e9, **kw):
    prijs = market.close[-1]
    return evaluate(market, prijs - 0.41, prijs + 0.41, _cfg(**kw), 12, 0,
                    sinds, 0, per_richting)


def test_default_is_drie_per_richting():
    assert ScalpConfig().max_positions_per_richting == 3


def test_onder_de_limiet_wordt_gehandeld(market):
    s = _eval(market, {1: 0, -1: 0})
    assert s.should_trade and s.geldig
    d = s.direction
    s2 = _eval(market, {d: 2, -d: 3})
    assert s2.should_trade, "2 van 3 in deze richting: er mag er nog één bij"


def test_limiet_per_richting_bereikt_maar_signaal_blijft_geldig(market):
    d = _eval(market, {1: 0, -1: 0}).direction
    s = _eval(market, {d: 3, -d: 0})
    assert not s.should_trade
    assert s.reject_reason == "max_positions_zelfde_richting"
    assert s.geldig and s.stop_loss is not None and s.take_profit is not None


def test_tegengestelde_posities_blokkeren_niet(market):
    """Hedge: drie posities in de andere richting houden niets tegen."""
    d = _eval(market, {1: 0, -1: 0}).direction
    s = _eval(market, {d: 0, -d: 3})
    assert s.should_trade and s.reject_reason is None


def test_cooldown_houdt_het_signaal_geldig(market):
    s = _eval(market, {1: 0, -1: 0}, sinds=5.0)
    assert not s.should_trade and s.reject_reason == "cooldown"
    assert s.geldig and s.stop_loss is not None


def test_limiet_is_instelbaar(market):
    d = _eval(market, {1: 0, -1: 0}).direction
    assert not _eval(market, {d: 1, -d: 0}, max_positions_per_richting=1).should_trade
    assert _eval(market, {d: 1, -d: 0}, max_positions_per_richting=2).should_trade


def test_signaalfilter_is_geen_geldig_signaal(market):
    s = _eval(market, {1: 0, -1: 0}, entry_threshold=0.99)
    assert not s.should_trade and not s.geldig


# ======================================================================= #
# Spreiding, marge, netting (zuiver)                                      #
# ======================================================================= #

def test_spreiding_zelfde_candle_is_een_kopie():
    ok, reden = P.spreiding_ok(1, 4410.0, 2.0, [(4400.0, T0)],
                               T0 + timedelta(seconds=30), 300)
    assert not ok and "candle" in reden


def test_spreiding_volgende_candle_maar_te_dichtbij():
    ok, reden = P.spreiding_ok(1, 4400.5, 2.0, [(4400.0, T0)],
                               T0 + timedelta(seconds=301), 300)
    assert not ok and "0.3 x ATR" in reden


def test_spreiding_volgende_candle_en_ver_genoeg():
    ok, _ = P.spreiding_ok(1, 4400.6, 2.0, [(4400.0, T0)],
                           T0 + timedelta(seconds=301), 300)
    assert ok
    assert P.MIN_SPREIDING_ATR == pytest.approx(0.3)


def test_spreiding_zonder_bestaande_positie_altijd_goed():
    assert P.spreiding_ok(1, 4400.0, None, [], T0, 300) == (True, None)


def _pos(ticket, side, prijs, stop, units=10.0, open_time=None):
    return VenuePosition(ticket=ticket, symbol="GOLD", side=side, units=units,
                         open_price=prijs, stop_loss=stop, open_time=open_time)


def test_marge_weigert_extra_positie():
    ok, reden, info = P.marge_en_vloer_ok(
        units=10.0, prijs=4400.0, instap=4400.3, stop=4397.0, equity=10_000.0,
        vloer=8_000.0, marge_vrij=2_000.0,
        open_posities=[_pos("A", "buy", 4390.0, 4387.0)],
    )
    # 10 oz x 4400 x 5% = 2200 > 90% van 2000
    assert not ok and reden.startswith("marge") and info["marge_nodig"] == 2200.0


def test_vloer_weigert_als_alle_stops_samen_te_veel_kosten():
    open_ = [_pos(str(i), "buy", 4400.0, 4300.0) for i in range(2)]   # 2 x 1000
    ok, reden, _ = P.marge_en_vloer_ok(
        units=10.0, prijs=4400.0, instap=4400.0, stop=4300.0, equity=10_000.0,
        vloer=7_500.0, marge_vrij=None, open_posities=open_,
    )
    assert not ok and reden.startswith("vloer")


def test_eerste_positie_valt_niet_onder_de_extra_toets():
    ok, _, _ = P.marge_en_vloer_ok(
        units=10.0, prijs=4400.0, instap=4400.0, stop=4300.0, equity=8_100.0,
        vloer=8_000.0, marge_vrij=1.0, open_posities=[],
    )
    assert ok


def test_marge_en_vloer_in_orde():
    ok, reden, _ = P.marge_en_vloer_ok(
        units=10.0, prijs=4400.0, instap=4400.3, stop=4397.0, equity=10_000.0,
        vloer=8_000.0, marge_vrij=9_000.0,
        open_posities=[_pos("A", "sell", 4410.0, 4413.0)],
    )
    assert ok and reden is None


def test_netting_uit_bevestiging_en_uit_posities():
    assert P.netting_uit_bevestiging([
        {"dealId": "A", "status": "OPENED"},
        {"dealId": "B", "status": "FULLY_CLOSED"},
    ]) == ["B"]
    voor = [_pos("L1", "buy", 4400.0, 4397.0)]
    na_hedge = [_pos("L1", "buy", 4400.0, 4397.0), _pos("S1", "sell", 4401.0, 4404.0)]
    assert P.netting_uit_posities(voor, na_hedge, -1, "S1") == []
    assert P.netting_uit_posities(voor, [], -1, "S1") == ["L1", "nieuw:S1"]


def test_ig_order_stuurt_force_open_en_meldt_verrekening():
    routes = {
        "/markets/": MARKET,
        "/positions/otc": ({"dealReference": "REF1"}, 200),
        "/confirms/": ({"dealStatus": "ACCEPTED", "dealId": "D2", "level": 3300.4,
                        "size": 1.0, "affectedDeals": [
                            {"dealId": "D1", "status": "FULLY_CLOSED"}]}, 200),
    }
    venue = ig(routes)
    r = asyncio.run(venue.place_order("GOLD", "sell", 1.0, stop_loss=3303.0))
    order = next(c for c in venue._session.calls if "/positions/otc" in c["url"])
    assert order["json"]["forceOpen"] is True
    assert r.success and r.verrekend == ["D1"]


def test_ig_order_zonder_verrekening():
    routes = {
        "/markets/": MARKET,
        "/positions/otc": ({"dealReference": "REF1"}, 200),
        "/confirms/": ({"dealStatus": "ACCEPTED", "dealId": "D2", "level": 3300.4,
                        "size": 1.0, "affectedDeals": [
                            {"dealId": "D2", "status": "OPENED"}]}, 200),
    }
    r = asyncio.run(ig(routes).place_order("GOLD", "sell", 1.0, stop_loss=3303.0))
    assert r.success and not r.verrekend


# ======================================================================= #
# Coordinator: meerdere posities in de lus                                #
# ======================================================================= #

_klok = {"extra": 0.0}


@pytest.fixture(autouse=True)
def vaste_klok(monkeypatch):
    """Klok van de integratie op T0 + ``_klok['extra']`` seconden."""
    import datetime as _dt
    import gold_scalper.coordinator  # noqa: F401

    echt = _dt.datetime

    class Klok(echt):
        @classmethod
        def now(cls, tz=None):
            nu = T0 + timedelta(seconds=_klok["extra"])
            return nu.astimezone(tz) if tz is not None else nu.replace(tzinfo=None)

    for naam, module in list(sys.modules.items()):
        if (naam == "gold_scalper" or naam.startswith("gold_scalper.")) and \
                getattr(module, "datetime", None) is echt:
            monkeypatch.setattr(module, "datetime", Klok)
    _klok["extra"] = 0.0
    yield
    _klok["extra"] = 0.0


def _nu():
    return T0 + timedelta(seconds=_klok["extra"])


class KlokVenue(ScriptedVenue):
    """ScriptedVenue op de testklok, met sluitverzoeken bijgehouden."""

    gesloten: list = None
    netting: bool = False

    async def quote(self, symbol=None):
        half = self.spread / 2
        return VenueQuote(bid=self.price - half, ask=self.price + half,
                          time=_nu(), tradeable=True)

    async def place_order(self, symbol, side, units, stop_loss=None,
                          take_profit=None, comment=""):
        if self.netting:
            tegen = [p for p in self._positions if p.side != side]
            if tegen:
                # Een nettend account: de order sluit de tegengestelde positie.
                self._positions.remove(tegen[0])
                self.orders.append((side, units, stop_loss, take_profit))
                return OrderResult(success=True, ticket=f"N{len(self.orders)}",
                                   fill_price=self.price, units=units)
        return await ScriptedVenue.place_order(
            self, symbol, side, units, stop_loss, take_profit, comment)

    async def close(self, ticket, units=None):
        self.gesloten = (self.gesloten or []) + [ticket]
        return await ScriptedVenue.close(self, ticket, units)


_richting = {"d": 1}


def _nep_evaluate(candles, bid, ask, cfg, uur, aantal, sinds, kant, per_richting=None):
    """Spiegelt de 1.9.0-logica van ``evaluate`` met een gekozen richting."""
    d = _richting["d"]
    instap = ask if d == 1 else bid
    s = ScalpSignal(direction=d, score=0.6 * d, confidence=0.8, should_trade=True,
                    reject_reason=None, reason="test", stop_loss=instap - 3.0 * d,
                    take_profit=instap + 4.0 * d, geldig=True)
    if (per_richting or {}).get(d, 0) >= cfg.max_positions_per_richting:
        s.should_trade, s.reject_reason = False, "max_positions_zelfde_richting"
    elif sinds < cfg.cooldown_seconds:
        s.should_trade, s.reject_reason = False, "cooldown"
    return s


def _opzet(tmp_path, monkeypatch, venue=None, houd_exits=True):
    import gold_scalper.coordinator as co
    from gold_scalper.lifecycle import LifecycleState

    monkeypatch.setattr(co, "evaluate", _nep_evaluate)
    venue = venue or KlokVenue()
    coordinator, hass = _coordinator(venue, tmp_path, monkeypatch)
    coordinator.executor.venue = venue
    coordinator.executor.lookup_delays = (0.0,)
    coordinator._enabled = True
    coordinator.units = 1.3
    coordinator._use_schedule = False
    coordinator.lifecycle._transition(LifecycleState.RUNNING, "test")
    if houd_exits:
        coordinator.exits.evaluate = lambda **kw: ExitAction("hold", reason="test")
    return coordinator, venue, hass


def _cyclus(coordinator, stap=0.0, beweeg=0.0):
    _klok["extra"] += stap
    if beweeg:
        coordinator.venue.move(beweeg)
    return asyncio.run(coordinator._async_update_data())


def test_drie_long_en_drie_short_tegelijk(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)                                  # opwarmen + long 1
    for _ in range(3):                                    # long 2, 3, dan limiet
        data = _cyclus(coordinator, stap=400, beweeg=3.0)
    longs = [p for p in venue._positions if p.side == "buy"]
    assert len(longs) == 3
    assert data["reject_reason"] == "max_positions_zelfde_richting"

    _richting["d"] = -1
    for _ in range(4):
        data = _cyclus(coordinator, stap=400, beweeg=3.0)
    shorts = [p for p in venue._positions if p.side == "sell"]
    assert len(shorts) == 3 and len(venue._positions) == 6
    assert not venue.gesloten, "een tegengesteld signaal mag niets sluiten"
    assert data["posities_per_richting"] == {"long": 3, "short": 3, "limiet": 3}

    open_trades = coordinator.db.open_trades(coordinator.run_id)
    assert len(open_trades) == 6
    assert sorted(t.gelijktijdig_open for t in open_trades) == [0, 1, 2, 3, 4, 5]
    assert coordinator.risk.state.state is not TradingState.HALTED


def test_hooguit_een_nieuwe_positie_per_cyclus(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)
    assert len(venue.orders) == 1
    q = asyncio.run(venue.quote())
    sig = _nep_evaluate(None, q.bid, q.ask, coordinator.strategy_cfg, 12, 0, 1e9, 0, {})
    assert asyncio.run(coordinator._open_position(sig, q, _nu())) is False
    assert len(venue.orders) == 1
    coordinator._geopend_in_cyclus = 0
    assert asyncio.run(coordinator._open_position(sig, q, _nu())) is True


def test_spreiding_in_de_lus_en_geen_schaduw_voor_een_kopie(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)
    data = _cyclus(coordinator, stap=70)                  # zelfde candle (5m)
    assert len(venue._positions) == 1
    assert data["reject_reason"].startswith("spreiding")
    assert coordinator.db.schaduw_trades(coordinator.run_id) == []
    data = _cyclus(coordinator, stap=400, beweeg=0.2)     # nieuwe candle, te dichtbij
    assert len(venue._positions) == 1 and "ATR" in data["reject_reason"]
    _cyclus(coordinator, stap=0, beweeg=3.0)              # ver genoeg
    assert len(venue._positions) == 2


def test_per_ticket_tijdstop_sluit_elke_verlopen_positie(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)                                   # A om T0
    _cyclus(coordinator, stap=400, beweeg=3.0)             # B om T0+400
    eerste, tweede = [p.ticket for p in venue._positions]
    coordinator.exits = ExitManager(ExitConfig())          # echte exitregels
    coordinator.schaduw.exits = coordinator.exits
    coordinator.state.atr._rma._value = 20.0               # alles in de dode zone
    _klok["extra"] += 450                                  # A 850 s, B 450 s
    coordinator._positions_cache = None
    asyncio.run(coordinator._manage_open_positions(asyncio.run(venue.quote()), _nu()))
    # Tijdstop 240 s: beide in de dode zone en ouder dan 240 s -> beide dicht.
    assert set(venue.gesloten) == {eerste, tweede}


def test_per_ticket_alleen_de_oude_haalt_de_tijdstop(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)                                   # A om T0
    _cyclus(coordinator, stap=400, beweeg=3.0)             # B om T0+400
    eerste, tweede = [p.ticket for p in venue._positions]
    coordinator.exits = ExitManager(ExitConfig())
    coordinator.state.atr._rma._value = 20.0
    _klok["extra"] += 100                                  # A 500 s, B 100 s
    coordinator._positions_cache = None
    asyncio.run(coordinator._manage_open_positions(asyncio.run(venue.quote()), _nu()))
    assert venue.gesloten == [eerste]
    assert [p.ticket for p in venue._positions] == [tweede]
    assert [t.broker_ticket for t in coordinator.db.open_trades(coordinator.run_id)] == [tweede]


def test_afgewezen_sluiting_raakt_alleen_dat_ticket(tmp_path, monkeypatch):
    """1.7.9 per ticket: een weigering voor A remt B niet af."""

    class Weigerend(KlokVenue):
        async def close(self, ticket, units=None):
            if ticket == self.weiger:
                return OrderResult(success=False, ticket=ticket, error="REJECT_X")
            return await KlokVenue.close(self, ticket, units)

    venue = Weigerend()
    coordinator, _, _ = _opzet(tmp_path, monkeypatch, venue=venue)
    _richting["d"] = 1
    _cyclus(coordinator)
    _cyclus(coordinator, stap=400, beweeg=3.0)
    a, b = [p.ticket for p in venue._positions]
    venue.weiger = a
    coordinator.exits.evaluate = lambda **kw: ExitAction("close", reason="tijdstop")
    coordinator._positions_cache = None
    asyncio.run(coordinator._manage_open_positions(asyncio.run(venue.quote()), _nu()))
    assert a in coordinator._sluit_pogingen and b not in coordinator._sluit_pogingen
    assert [p.ticket for p in venue._positions] == [a]
    assert [t.broker_ticket for t in coordinator.db.open_trades(coordinator.run_id)] == [a]


def test_reconcile_bij_opstart_met_meerdere_posities(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    for i, side in enumerate(("buy", "buy", "sell", "sell")):
        asyncio.run(venue.place_order("GOLD", side, 1.3, stop_loss=4390.0 if side == "buy" else 4410.0))
        coordinator.db.insert_trade(Trade(
            run_id=coordinator.run_id, mode="demo", symbol="GOLD", side=side,
            volume=0.013, open_time=T0.isoformat(), open_price=4400.0,
            open_mid=4400.0, open_spread=0.6, broker_ticket=venue._positions[-1].ticket,
        ))
    asyncio.run(coordinator._reconcile())
    assert coordinator.risk.state.state is not TradingState.HALTED, \
        coordinator.risk.state.halt_reason
    # Een vijfde, onbekende positie wordt nog steeds gevonden.
    asyncio.run(venue.place_order("GOLD", "sell", 1.3, stop_loss=4410.0))
    asyncio.run(coordinator._reconcile())
    assert coordinator.risk.state.state is TradingState.HALTED


def test_marge_weigering_in_de_lus_geeft_schaduwtrade(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)
    assert len(venue._positions) == 1

    async def krap():
        from gold_scalper.broker.adapter import AccountSnapshot
        return AccountSnapshot(balance=10000.0, equity=10000.0, margin_used=0.0,
                               margin_available=50.0, currency="EUR",
                               open_position_count=1)
    venue.account = krap
    data = _cyclus(coordinator, stap=400, beweeg=3.0)
    assert len(venue._positions) == 1
    assert data["reject_reason"].startswith("marge")
    rijen = coordinator.db.schaduw_trades(coordinator.run_id)
    assert [r["reden"] for r in rijen] == ["marge"]


def test_netting_wordt_gedetecteerd_en_hedgen_gaat_uit(tmp_path, monkeypatch, caplog):
    venue = KlokVenue()
    venue.netting = True
    coordinator, _, _ = _opzet(tmp_path, monkeypatch, venue=venue)
    _richting["d"] = 1
    _cyclus(coordinator)                                   # long
    _richting["d"] = -1
    with caplog.at_level("ERROR"):
        _cyclus(coordinator, stap=400)                     # short: broker verrekent
    assert coordinator.netting and coordinator.netting["verrekend"]
    assert any("Netting" in r.message for r in caplog.records)
    # Een volgende tegengestelde instap wordt geweigerd zolang er een positie
    # in de andere richting staat.
    _richting["d"] = 1
    asyncio.run(venue.place_order("GOLD", "sell", 1.3, stop_loss=4410.0))
    data = _cyclus(coordinator, stap=400, beweeg=5.0)
    assert data["reject_reason"].startswith("netting")
    assert data["netting"]["verrekend"]


def test_geen_netting_bij_gewone_hedge(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)
    _richting["d"] = -1
    _cyclus(coordinator, stap=400)
    assert coordinator.netting is None
    assert {p.side for p in venue._positions} == {"buy", "sell"}


# ======================================================================= #
# Schaduwtrades                                                           #
# ======================================================================= #

def _boek(**kw):
    return SchaduwBoek(exits=ExitManager(ExitConfig(**kw)),
                       kosten=SchaduwKosten(slippage=0.02, commissie_per_lot=0.0),
                       bar_seconden=60)


def _sig(d=1, stop=4397.0, doel=4405.0):
    return ScalpSignal(direction=d, score=0.6 * d, confidence=0.8, should_trade=False,
                       reject_reason="max_positions_zelfde_richting", reason="x",
                       stop_loss=stop, take_profit=doel, geldig=True)


def _open(boek, d=1, stop=4397.0, doel=4405.0, nu=T0, reden="positielimiet"):
    return boek.openen(run_id=1, signal=_sig(d, stop, doel), bid=4399.7, ask=4400.3,
                       nu=nu, units=10.0, reden=reden, reden_tekst="limiet",
                       atr=2.0)


def test_schaduw_instap_op_laat_en_stop_op_het_niveau():
    boek = _boek()
    t = _open(boek)
    assert t.open_price == 4400.3 and t.open_spread == pytest.approx(0.6)
    boek.bijwerken(bid=4398.7, ask=4399.3, hoog=4399.5, laag=4396.0, atr=2.0,
                   nu=T0 + timedelta(seconds=20))
    assert t.status == "gesloten" and t.close_reason == "stop_loss"
    assert t.close_price == 4397.0
    # (4397 - 4400.3) x 10 - 2 x 0.02 x 10
    assert t.netto == pytest.approx(-33.4)
    assert t.kosten > 0


def test_schaduw_doel_geraakt():
    boek = _boek()
    t = _open(boek)
    boek.bijwerken(bid=4404.7, ask=4405.3, hoog=4406.0, laag=4404.0, atr=2.0,
                   nu=T0 + timedelta(seconds=20))
    assert t.close_reason == "take_profit" and t.netto == pytest.approx(46.6)


def test_schaduw_stop_en_doel_in_hetzelfde_interval_telt_de_stop():
    boek = _boek()
    t = _open(boek)
    boek.bijwerken(bid=4400.0, ask=4400.6, hoog=4407.0, laag=4395.0, atr=2.0,
                   nu=T0 + timedelta(seconds=20))
    assert t.close_reason == "stop_loss"


def test_schaduw_tijdstop_en_max_duur_zoals_echte_posities():
    boek = _boek()
    t = _open(boek, stop=4390.0, doel=4420.0)
    for s in (20, 120, 239):
        boek.bijwerken(bid=4399.9, ask=4400.5, hoog=None, laag=None, atr=2.0,
                       nu=T0 + timedelta(seconds=s))
        assert t.status == "open"
    boek.bijwerken(bid=4399.9, ask=4400.5, hoog=None, laag=None, atr=2.0,
                   nu=T0 + timedelta(seconds=245))
    assert t.status == "gesloten" and t.close_reason == "tijdstop"
    assert t.close_price == 4399.9          # op de bied, zoals een echte long

    boek2 = _boek(time_stop_seconds=10_000)
    t2 = _open(boek2, stop=4390.0, doel=4420.0)
    for s in range(60, 901, 60):
        boek2.bijwerken(bid=4400.1, ask=4400.7, hoog=None, laag=None, atr=0.2,
                        nu=T0 + timedelta(seconds=s))
    assert t2.close_reason == "max_duur"


def test_schaduw_trailing_verplaatst_de_stop():
    boek = _boek()
    t = _open(boek, stop=4397.0, doel=4450.0)
    boek.bijwerken(bid=4404.0, ask=4404.6, hoog=None, laag=None, atr=2.0,
                   nu=T0 + timedelta(seconds=20))
    assert t.status == "open" and t.stop_loss == pytest.approx(4404.0 - 2.4)


def test_schaduw_vervalt_na_een_gat_in_de_data():
    boek = _boek()
    t = _open(boek)
    boek.bijwerken(bid=4400.0, ask=4400.6, hoog=None, laag=None, atr=2.0,
                   nu=T0 + timedelta(seconds=900))
    assert t.status == "vervallen" and boek.vervallen == 1
    assert boek.statistiek()["trades"] == 0


def test_schaduw_ontdubbeling_per_candle_en_spreiding():
    boek = _boek()
    assert _open(boek) is not None
    assert _open(boek, nu=T0 + timedelta(seconds=20)) is None      # zelfde candle
    assert _open(boek, nu=T0 + timedelta(seconds=70)) is None      # te dichtbij
    assert _open(boek, d=-1, stop=4403.0, doel=4395.0,
                 nu=T0 + timedelta(seconds=20)) is not None        # andere richting


def test_schaduw_alleen_voor_vastgelegde_redenen():
    boek = _boek()
    assert _open(boek, reden="spreiding") is None
    assert "spreiding" not in SCHADUW_REDENEN
    assert {"positielimiet", "cooldown", "marge"} <= set(SCHADUW_REDENEN)
    ongeldig = _sig()
    ongeldig.geldig = False
    assert boek.openen(run_id=1, signal=ongeldig, bid=4399.7, ask=4400.3, nu=T0,
                       units=10.0, reden="positielimiet", reden_tekst=None,
                       atr=2.0) is None


def test_schaduw_statistiek_op_clusters():
    rijen = []
    for i, netto in enumerate((10.0, -5.0, 8.0, -2.0)):
        open_t = T0 + timedelta(hours=i)
        rijen.append(SimpleNamespace(
            open_time=open_t.isoformat(), close_time=(open_t + timedelta(minutes=3)).isoformat(),
            netto=netto, bruto=netto + 1.0, kosten=1.0, reden="cooldown", close_reason="tijdstop",
        ))
    # Twee gelijktijdige: zelfde cluster.
    rijen.append(SimpleNamespace(
        open_time=(T0 + timedelta(hours=3, minutes=1)).isoformat(),
        close_time=(T0 + timedelta(hours=3, minutes=2)).isoformat(),
        netto=1.0, bruto=2.0, kosten=1.0, reden="positielimiet", close_reason="take_profit",
    ))
    s = schaduw_statistiek(rijen)
    assert s["trades"] == 5 and s["clusters"] == 4
    assert s["winst_pct"] == 60.0
    assert s["profit_factor"] == pytest.approx(19.0 / 7.0, abs=1e-3)
    assert s["netto"] == 12.0 and s["t_statistiek"] is not None


def test_schaduw_in_de_lus_en_niet_in_de_echte_statistiek(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)                                    # echte long
    data = _cyclus(coordinator, stap=30, beweeg=3.0)         # cooldown -> schaduw
    assert data["reject_reason"] == "cooldown"
    rijen = coordinator.db.schaduw_trades(coordinator.run_id)
    assert [r["reden"] for r in rijen] == ["cooldown"]
    # Schaduwtrade loopt op zijn stop.
    coordinator.state.atr._rma._value = 2.0
    _cyclus(coordinator, stap=20, beweeg=-10.0)
    rijen = coordinator.db.schaduw_trades(coordinator.run_id)
    assert rijen[0]["status"] == "gesloten" and rijen[0]["close_reason"] == "stop_loss"
    # Niets in de echte tabel of de echte statistiek.
    assert coordinator.db.closed_trades(coordinator.run_id) == []
    stats = performance.compute_for_run(coordinator.db, coordinator.run_id)
    assert stats.get("trades", 0) == 0
    data = _cyclus(coordinator, stap=20)
    assert data["schaduw"]["trades"] == 1
    assert data["stats"].get("trades", 0) == 0


def test_schaduw_overleeft_herladen(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)
    _cyclus(coordinator, stap=30, beweeg=3.0)
    asyncio.run(coordinator._laad_schaduw())
    assert len(coordinator.schaduw.open_trades) == 1
    assert coordinator.schaduw.open_trades[0].id is not None


# ======================================================================= #
# Statistiek, run, opslag                                                 #
# ======================================================================= #

def _trade(run, side, open_t, close_t, net, ticket):
    return Trade(run_id=run, mode="demo", symbol="GOLD", side=side, volume=0.01,
                 open_time=open_t.isoformat(), open_price=4400.0, open_mid=4400.0,
                 open_spread=0.6, close_time=close_t.isoformat(), net_pnl=net,
                 broker_ticket=ticket)


def test_gelijktijdige_trades_vormen_een_cluster():
    a = _trade(1, "buy", T0, T0 + timedelta(minutes=5), 10.0, "A")
    b = _trade(1, "sell", T0 + timedelta(minutes=1), T0 + timedelta(minutes=3), -4.0, "B")
    c = _trade(1, "buy", T0 + timedelta(hours=2), T0 + timedelta(hours=2, minutes=1), 3.0, "C")
    assert performance.cluster_resultaten([a, b, c]) == [6.0, 3.0]


def test_gelijktijdig_open_wordt_bewaard(tmp_path):
    db = TradeDatabase(tmp_path / "t.db")
    db.connect()
    run = db.start_run("demo", "v", "GOLD", {}, 1000.0, None, "fp")
    t = Trade(run_id=run, mode="demo", symbol="GOLD", side="buy", volume=0.01,
              open_time=T0.isoformat(), open_price=1.0, open_mid=1.0,
              open_spread=0.1, broker_ticket="X", gelijktijdig_open=2)
    db.insert_trade(t)
    assert db.open_trades(run)[0].gelijktijdig_open == 2


def test_overlap_in_een_run_met_limiet_per_richting_is_geen_fout(tmp_path):
    db = TradeDatabase(tmp_path / "m.db")
    db.connect()
    oud = db.start_run("demo", "v", "GOLD", {"risk": {"max_positions": 1}}, 1000.0, None, "a")
    nieuw = db.start_run("demo", "v", "GOLD",
                         {"risk": {"max_positions": 1, "max_positions_per_richting": 3}},
                         1000.0, None, "b")
    for run in (oud, nieuw):
        db.insert_trade(_trade(run, "buy", T0, T0 + timedelta(minutes=5), 1.0, f"A{run}"))
        db.insert_trade(_trade(run, "sell", T0 + timedelta(minutes=1),
                               T0 + timedelta(minutes=3), 1.0, f"B{run}"))
    assert db.detect_mixed_runs() == 1
    assert db.run_annotations(oud) and not db.run_annotations(nieuw)


def test_vingerafdruk_en_uitvoeringsversie(tmp_path, monkeypatch):
    from gold_scalper.const import EXECUTION_SEMANTICS_VERSION, INTEGRATION_VERSION
    assert EXECUTION_SEMANTICS_VERSION == 4
    assert INTEGRATION_VERSION.startswith("1.9.")
    coordinator, _, _ = _opzet(tmp_path, monkeypatch)
    config = coordinator._run_config()
    assert config["risk"]["max_positions_per_richting"] == 3 and config["risk"]["hedge"]
    materiaal = coordinator._fingerprint_material(config)
    assert materiaal["positielimiet"] == {"per_richting": 3, "hedge": True}
    assert materiaal["execution_semantics"] == 4
    assert coordinator._OPTION_FOR["positielimiet"] == "max_positions_per_richting"
    assert coordinator.risk.limits.max_open_positions == 6


def test_optie_is_begrensd_op_1_tot_3():
    from gold_scalper.coordinator import _per_richting
    assert [_per_richting(v) for v in (None, 0, 1, 2.0, 3, 7)] == [3, 1, 1, 2, 3, 3]


def test_optie_in_options_flow_en_vertalingen():
    bron = (PKG / "config_flow.py").read_text(encoding="utf-8")
    assert "CONF_MAX_POSITIONS_PER_RICHTING" in bron
    for taal in ("nl", "en"):
        d = json.loads((PKG / "translations" / f"{taal}.json").read_text(encoding="utf-8"))
        assert "max_positions_per_richting" in d["options"]["step"]["init"]["data"]


# ======================================================================= #
# Dashboard                                                               #
# ======================================================================= #

def test_dashboard_toont_alle_posities_en_schaduw():
    from gold_scalper.dashboard import broker as B

    posities = [
        _pos("L1", "buy", 4400.0, 4397.0, open_time=T0),
        _pos("L2", "buy", 4403.0, 4400.0, open_time=T0),
        _pos("S1", "sell", 4401.0, 4404.0, open_time=T0),
    ]
    quote = VenueQuote(bid=4402.0, ask=4402.6, time=T0, tradeable=True)
    schaduw = schaduw_statistiek([])
    schaduw.update(trades=4, winst_pct=50.0, profit_factor=1.3, netto=12.5,
                   kosten=3.0, verwachting=3.1, clusters=3, t_statistiek=0.8,
                   per_reden={"positielimiet": 3, "cooldown": 1})
    data = {"quote": quote, "price": 4402.3, "open_positions": posities,
            "posities_per_richting": {"long": 2, "short": 1, "limiet": 3},
            "schaduw": schaduw, "stats": {}, "balances": {}, "conversion": {}}
    payload = B.build_payload(
        data, symbol="GOLD", timeframe="1m", candles=None, db=None,
        exit_cfg={}, version="1.9.0", status=("positie_open", ""),
        places_orders=True, uses_real_money=False,
    )
    assert [p["ticket"] for p in payload["posities"]] == ["L1", "L2", "S1"]
    assert all(p["pnl"] is not None for p in payload["posities"])
    assert payload["posities_telling"] == {"long": 2, "short": 1, "limiet": 3}
    sch = payload["schaduw"]
    assert sch["trades"] == 4 and sch["pf"] == 1.3 and sch["t"] == 0.8
    assert sch["per_reden"] == {"positielimiet": 3, "cooldown": 1}
    # De echte statistiek blijft leeg: schaduw zit er niet in.
    assert payload["stats"]["trades"] == 0


def test_paneel_heeft_schaduwpaneel_en_lijnen_per_positie():
    js = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
    assert "Schaduwtrades (gesimuleerd)" in js and "_renderSchaduw(d)" in js
    assert "for (const p of d.posities || [])" in js       # lijnen per positie
    assert "posities_telling" in js


def test_sensor_schaduwtrades_bestaat():
    bron = (PKG / "sensor.py").read_text(encoding="utf-8")
    assert 'key="schaduw_trades"' in bron and '"t_statistiek"' in bron
