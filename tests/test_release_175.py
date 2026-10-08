"""1.7.5: een herstart van Home Assistant verandert niets.

De eigenaar herstart vaak. Elke herstart liet tot nu toe sporen na: het
papersaldo terug op de startbalans, uitersten van open posities op nul, een
pauze na een verliesreeks opgeheven, de live-poort dicht tot de volgende
trade, een vingerafdruk die op een terugvalvaluta werd herschreven, een
onbevestigde order die als onbekende positie de handel stillegde, dezelfde
melding opnieuw, een halve bar als volwaardige bar in het archief.

Deze tests draaien waar het kan een échte herstart: coordinator A start op,
doet iets, sluit af; coordinator B start op dezelfde database en dezelfde
opslag. Daarna moet B zijn waar A was.

Wat hier nadrukkelijk níet verandert: strategie, in- en uitstap, risicolimieten,
parameters, standaardwaarden en positiegrootte.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))
sys.path.insert(0, HIER)

from gold_scalper.broker.adapter import VenueError, VenuePosition, VenueQuote  # noqa: E402
from gold_scalper.broker.execution_safety import PendingOrder, SafeExecutor  # noqa: E402
from gold_scalper.broker.risk import TradingState  # noqa: E402
from gold_scalper.storage.database import Trade  # noqa: E402
from gold_scalper.storage.state import ResultsStore, RuntimeState, StateStore  # noqa: E402
from gold_scalper.strategy.aggregator import QuoteAggregator  # noqa: E402
from gold_scalper.strategy.scalping import ScalpSignal  # noqa: E402

from test_broker_cycle import NOW, FakeHass, ScriptedVenue, _coordinator  # noqa: E402

PKG = os.path.join(HIER, "..", "custom_components", "gold_scalper")


# --------------------------------------------------------------------------
# Hulpmiddelen: een herstart nabootsen
# --------------------------------------------------------------------------


class Entry:
    entry_id = "test"
    data = {"venue": "simulator", "timeframe": "5m", "mode": "demo"}
    options = {
        "mode": "demo", "units": 10.0, "starting_balance": 10000.0,
        "update_seconds": 20,
    }


class ZonderAccount(ScriptedVenue):
    """Broker waarvan de accountopvraging bij het opstarten faalt."""

    async def account(self):
        raise VenueError("time-out")


def _bouw(hass, venue, vorige=None):
    """Een coordinator zoals Home Assistant hem maakt, op een gescripte broker.

    Met ``vorige`` deelt hij de opslag van een eerdere coordinator: dat is wat
    een herstart is - nieuw proces, zelfde bestanden.
    """
    from gold_scalper.coordinator import GoldScalperCoordinator
    from gold_scalper.modes import TradingMode

    c = GoldScalperCoordinator(hass, Entry())
    c.venue = venue
    c.executor.venue = venue
    c.mode = TradingMode.DEMO
    if vorige is not None:
        c._store = vorige._store
        c._results_store = vorige._results_store
    return c


def _start(c):
    asyncio.run(c.async_setup())
    return c


def _stop(c):
    asyncio.run(c.async_shutdown_hook())


def _trade(run, ticket, **kw):
    velden = dict(
        run_id=run, mode="demo", symbol="GOLD", side="buy", volume=0.10,
        open_time=(NOW - timedelta(hours=1)).isoformat(), open_price=4400.3,
        open_mid=4400.0, open_spread=0.6, stop_loss=4393.0, take_profit=4411.0,
        broker_ticket=ticket,
    )
    velden.update(kw)
    return Trade(**velden)


@pytest.fixture
def hass():
    return FakeHass()


# --------------------------------------------------------------------------
# 1. Papersaldo
# --------------------------------------------------------------------------


def test_paper_balance_and_costs_follow_the_closed_trades(tmp_path, monkeypatch):
    from gold_scalper.broker.paper import BrokerCosts, PaperBroker

    c, _ = _coordinator(ScriptedVenue(), tmp_path, monkeypatch)
    for netto, kosten in ((12.5, 1.5), (-4.0, 1.25)):
        c.db.insert_trade(_trade(
            c.run_id, None, close_time=NOW.isoformat(), close_price=4401.0,
            net_pnl=netto, total_cost=kosten,
        ))
    c.paper = PaperBroker(c.db, c.run_id, c.symbol, 10000.0, BrokerCosts())
    assert c.paper.balance == 10000.0          # zoals de broker begint

    asyncio.run(c._herstel_uit_run())

    assert c.paper.balance == pytest.approx(10000.0 + 12.5 - 4.0)
    assert c.paper.cumulative_cost == pytest.approx(2.75)


def test_paper_excursions_of_open_trades_survive(tmp_path, monkeypatch):
    from gold_scalper.broker.paper import BrokerCosts, PaperBroker

    c, _ = _coordinator(ScriptedVenue(), tmp_path, monkeypatch)
    c.db.insert_trade(_trade(c.run_id, None, mfe=0.0, mae=0.0))
    c.paper = PaperBroker(c.db, c.run_id, c.symbol, 10000.0, BrokerCosts())
    open_id = c.paper.open_positions[0].id
    c._state.paper_excursions = {str(open_id): {"mfe": 3.2, "mae": -1.4}}

    asyncio.run(c._herstel_uit_run())

    trade = c.paper.open_positions[0]
    assert (trade.mfe, trade.mae) == (pytest.approx(3.2), pytest.approx(-1.4))


# --------------------------------------------------------------------------
# 2. Uitersten van open brokerposities
# --------------------------------------------------------------------------


def test_excursions_survive_and_closed_tickets_are_pruned(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    asyncio.run(venue.place_order(a.symbol, "buy", 10.0, stop_loss=4393.0))
    a.db.insert_trade(_trade(a.run_id, "T1"))
    a._excursions = {"T1": {"mfe": 4.5, "mae": -2.25},
                     "WEG": {"mfe": 1.0, "mae": -1.0}}
    _stop(a)

    b = _start(_bouw(hass, venue, a))
    assert b._excursions == {"T1": {"mfe": 4.5, "mae": -2.25}}


# --------------------------------------------------------------------------
# 3. Live-poort: eerst leren, dan de poort
# --------------------------------------------------------------------------


def _volg(c, volgorde, robuustheid):
    leer, poort = c._relearn, c._refresh_gate

    async def relearn(trades):
        volgorde.append("leren")
        await leer(trades)

    async def gate():
        volgorde.append("poort")
        robuustheid.append(dict(c.robustness))
        await poort()

    c._relearn, c._refresh_gate = relearn, gate


def test_setup_learns_before_the_gate_is_computed(hass):
    c = _bouw(hass, ScriptedVenue())
    volgorde, robuustheid = [], []
    _volg(c, volgorde, robuustheid)
    _start(c)
    assert volgorde == ["leren", "poort"]
    assert robuustheid[0], "de poort zag een lege robuustheid"


def test_the_cycle_learns_before_the_gate_is_computed(hass):
    c = _start(_bouw(hass, ScriptedVenue()))
    volgorde, robuustheid = [], []
    _volg(c, volgorde, robuustheid)
    asyncio.run(c._async_update_data())
    assert volgorde.index("leren") < volgorde.index("poort")


# --------------------------------------------------------------------------
# 4. Pauze na een verliesreeks
# --------------------------------------------------------------------------


def test_a_pause_survives_a_restart(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    nu = datetime.now(timezone.utc)
    a.risk.pause(nu, "5 verliezers achter elkaar")
    tot = a.risk.state.paused_until
    _stop(a)

    b = _start(_bouw(hass, venue, a))
    assert b.risk.state.state is TradingState.PAUSED
    assert b.risk.state.paused_until == tot
    assert b.risk.state.triggered == a.risk.state.triggered
    toegestaan, reden = b.risk.can_open(
        now=nu + timedelta(minutes=1), balance=10000.0, equity=10000.0,
        starting_balance=10000.0, open_positions=0, volume=0.01, spread=0.6,
        last_tick_age=1.0,
    )
    assert not toegestaan and "pauze" in reden


def test_an_expired_pause_resumes_as_without_restart(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    a.risk.pause(datetime.now(timezone.utc) - timedelta(hours=3), "reeks")
    _stop(a)

    b = _start(_bouw(hass, venue, a))
    toegestaan, _ = b.risk.can_open(
        now=datetime.now(timezone.utc), balance=10000.0, equity=10000.0,
        starting_balance=10000.0, open_positions=0, volume=0.01, spread=0.6,
        last_tick_age=1.0,
    )
    assert toegestaan
    assert b.risk.state.state is TradingState.RUNNING


# --------------------------------------------------------------------------
# 5. Accountvaluta en vingerafdruk
# --------------------------------------------------------------------------


def test_a_failed_currency_lookup_keeps_the_known_currency(hass):
    a = _start(_bouw(hass, ScriptedVenue()))
    assert a.conversion.account == "EUR"
    run, vingerafdruk = a.run_id, a.db.get_run(a.run_id)["fingerprint"]
    _stop(a)

    b = _start(_bouw(hass, ZonderAccount(), a))
    assert b.conversion.account == "EUR"
    assert b.run_id == run, "een terugvalvaluta begon een nieuwe bewijsfase"
    assert b.db.get_run(run)["fingerprint"] == vingerafdruk
    assert b.adopted_defaults == []


def test_without_stored_state_the_run_supplies_the_currency(hass):
    a = _start(_bouw(hass, ScriptedVenue()))
    run = a.run_id
    _stop(a)

    # Toestand van een oudere versie: geen bewaarde valuta.
    b = _bouw(hass, ZonderAccount())
    _start(b)
    assert b.conversion.account == "EUR"
    assert b.run_id == run


def test_a_fallback_currency_never_rewrites_the_fingerprint(tmp_path, monkeypatch):
    c, _ = _coordinator(ScriptedVenue(), tmp_path, monkeypatch)
    c.conversion.account = "EUR"
    materiaal = c._fingerprint_material(c._run_config())
    import json
    c.db.conn.execute(
        "UPDATE runs SET config_json=? WHERE id=?",
        (json.dumps({"fingerprint_material": materiaal}), c.run_id),
    )
    c.db.conn.commit()

    herschreven = []
    c.db.update_run_fingerprint = lambda *a: herschreven.append(a)
    c.conversion.account = "USD"            # terugval, niet van de broker
    c._valuta_onzeker = True
    nieuw = c._fingerprint_material(c._run_config())

    run = asyncio.run(c._adoptable_run(nieuw, c._hash_material(nieuw)))
    assert run is not None and run["id"] == c.run_id
    assert herschreven == []
    assert "account_currency" not in c.adopted_defaults


# --------------------------------------------------------------------------
# 6. Afsluiten
# --------------------------------------------------------------------------


def test_shutdown_persists_flushes_and_closes(hass):
    c = _start(_bouw(hass, ScriptedVenue()))
    for _ in range(3):
        c.db.log_signal(c.run_id, 0.1, 0.2, "flat", None, 0.6, False, "test")
    c._audit_gemeld = {"x:T1"}
    _stop(c)

    assert c.db._conn is None, "database niet gesloten"
    assert c.archive._conn is None, "archief niet gesloten"
    bewaard = c._store._all["test"]
    assert bewaard["audit_gemeld"] == ["x:T1"]

    # Tweede aanroep (stop-event én ontladen): doet niets, faalt niet.
    _stop(c)

    from gold_scalper.storage.database import TradeDatabase
    db = TradeDatabase(hass.config.path("gold_scalper.db"))
    db.connect()
    assert db.signal_stats(c.run_id)["evaluations"] >= 3
    db.close()


def test_shutdown_waits_for_a_running_cycle(hass):
    c = _start(_bouw(hass, ScriptedVenue()))

    async def scenario():
        await c._cyclus_slot.acquire()
        taak = asyncio.create_task(c.async_shutdown_hook())
        await asyncio.sleep(0.05)
        assert not taak.done(), "afgesloten midden in een cyclus"
        assert c.db._conn is not None
        c._cyclus_slot.release()
        await taak

    asyncio.run(scenario())
    assert c.db._conn is None


def test_no_cycle_runs_after_shutdown(hass):
    c = _start(_bouw(hass, ScriptedVenue()))
    _stop(c)
    asyncio.run(c._async_refresh())       # mag niets doen en niet falen


def test_the_stop_event_is_wired():
    bron = open(os.path.join(PKG, "__init__.py"), encoding="utf-8").read()
    setup = bron.split("async def async_setup_entry", 1)[1].split("\nasync def ", 1)[0]
    assert "EVENT_HOMEASSISTANT_STOP" in setup
    assert "async_shutdown_hook" in setup


# --------------------------------------------------------------------------
# 7. Laatste instap
# --------------------------------------------------------------------------


def test_last_entry_comes_from_the_latest_trade(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    laatste = NOW - timedelta(minutes=7)
    a.db.insert_trade(_trade(a.run_id, "X1", open_time=(NOW - timedelta(hours=2)).isoformat(),
                             close_time=NOW.isoformat(), net_pnl=1.0))
    a.db.insert_trade(_trade(a.run_id, "X2", open_time=laatste.isoformat(),
                             close_time=NOW.isoformat(), net_pnl=1.0))
    _stop(a)

    b = _start(_bouw(hass, venue))            # ook zonder bewaarde toestand
    assert b._last_entry_ts == pytest.approx(laatste.timestamp())


# --------------------------------------------------------------------------
# 8. Onbevestigde orders
# --------------------------------------------------------------------------


def _signaal():
    return ScalpSignal(
        direction=1, score=0.62, confidence=0.7, should_trade=True,
        reject_reason=None, reason="test", stop_loss=4393.0,
        take_profit=4411.0,
        components={"regime": "trend", "atr": 2.1, "adx": float("nan"),
                    "ander": [1, 2]},
    )


def _wachtend(c, client_id="gold_scalper-abc123"):
    quote = VenueQuote(bid=4399.7, ask=4400.3, time=NOW)
    c.executor.pending[client_id] = PendingOrder(
        client_id, c.symbol, "buy", datetime.now(timezone.utc), 4393.0,
        (_signaal(), quote, "buy", NOW),
    )
    return client_id


def test_an_order_filled_during_the_restart_is_recognised(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    client_id = _wachtend(a)
    _stop(a)

    # Tijdens de herstart uitgevoerd: de broker toont hem met ons ordernummer.
    venue._positions.append(VenuePosition(
        ticket="T5", symbol=a.symbol, side="buy", units=10.0,
        open_price=4400.3, current_price=4399.7, stop_loss=4393.0,
        take_profit=4411.0, unrealised_pnl=0.0, comment=client_id,
    ))

    b = _start(_bouw(hass, venue, a))
    assert venue.orders == [], "er is een order verstuurd"
    assert not b.executor.has_pending
    open_ = b.db.open_trades(b.run_id)
    assert [t.broker_ticket for t in open_] == ["T5"]
    assert open_[0].regime == "trend" and open_[0].entry_atr == pytest.approx(2.1)
    assert b.lifecycle.state.value != "diverged"
    assert b.risk.state.state is not TradingState.HALTED


def test_an_unresolved_order_keeps_blocking_new_orders(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    client_id = _wachtend(a)
    gemaakt = a.executor.pending[client_id].created
    _stop(a)

    b = _start(_bouw(hass, venue, a))
    assert b.executor.has_pending
    assert b.executor.pending[client_id].created == gemaakt
    assert venue.orders == []


def test_pending_rows_never_send_anything():
    class Verboden(ScriptedVenue):
        async def place_order(self, *a, **kw):  # pragma: no cover - mag niet
            raise AssertionError("order verstuurd")

    venue = Verboden()
    ex = SafeExecutor(venue)
    rijen = [
        {"client_id": "a", "symbol": "G", "side": "buy",
         "created": NOW.isoformat(), "stop_loss": 1.0},
        {"client_id": "b", "side": "zijwaarts", "created": NOW.isoformat()},
        {"kapot": True},
    ]
    assert ex.restore_pending(rijen) == 1
    assert list(ex.pending) == ["a"]
    gevonden, notes = asyncio.run(ex.resolve_pending(set()))
    assert gevonden == [] and venue.orders == []


def test_pending_export_round_trips():
    ex = SafeExecutor(ScriptedVenue())
    ex.pending["c1"] = PendingOrder("c1", "G", "sell", NOW, 4410.0, {"x": 1})
    rijen = ex.export_pending(lambda ctx: dict(ctx))
    nieuw = SafeExecutor(ScriptedVenue())
    nieuw.restore_pending(rijen, lambda d: d)
    order = nieuw.pending["c1"]
    assert (order.side, order.created, order.stop_loss, order.context) == (
        "sell", NOW, 4410.0, {"x": 1})


# --------------------------------------------------------------------------
# 9. Meldingen
# --------------------------------------------------------------------------


def test_a_restored_halt_does_not_alert_again(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    a.risk.halt("dagverlies")
    _stop(a)

    b = _start(_bouw(hass, venue, a))
    b.notifier.config.service = "telefoon"
    assert b._previous_risk_state == "halted"
    asyncio.run(b._notify({}))
    titels = [d.get("title") for (dom, _, d) in hass.calls if dom == "notify"]
    assert not any("NOODSTOP" in (t or "") for t in titels)


def test_alert_suppression_survives(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    a.notifier.config.service = "telefoon"
    asyncio.run(a.notifier.alert("audit", "Gold Scalper: x", "y"))
    _stop(a)

    b = _start(_bouw(hass, venue, a))
    b.notifier.config.service = "telefoon"
    voor = len(hass.calls)
    asyncio.run(b.notifier.alert("audit", "Gold Scalper: x", "y"))
    assert len(hass.calls) == voor, "dezelfde melding opnieuw na een herstart"


def test_hourly_baseline_is_seeded_from_the_run(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    for i in range(3):
        a.db.insert_trade(_trade(a.run_id, f"S{i}", close_time=NOW.isoformat(),
                                 net_pnl=2.0, gross_pnl=2.5, total_cost=0.5))
    _stop(a)

    b = _start(_bouw(hass, venue))            # oudere toestand: niets bewaard
    assert b.notifier._sent.last_trade_count == 3
    assert b.notifier._sent.last_net == pytest.approx(6.0)


# --------------------------------------------------------------------------
# 10. De lopende zelfgebouwde bar
# --------------------------------------------------------------------------


def _t(seconden):
    return datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc) + timedelta(seconds=seconden)


def _agg_met_bars():
    agg = QuoteAggregator("5m")
    for i in range(0, 900, 20):              # drie bars van vijf minuten
        agg.add(4400.0 + i / 100, _t(i))
    agg.add(4410.0, _t(905))                 # lopende bar begint om 900
    agg.add(4412.0, _t(925))
    return agg


def test_the_forming_bar_continues_in_the_same_interval():
    agg = _agg_met_bars()
    terug = QuoteAggregator.from_dict(agg.to_dict(), "5m")
    terug.add(4408.0, _t(960))
    agg.add(4408.0, _t(960))
    terug.add(4409.0, _t(1205))              # sluit de bar van 900
    agg.add(4409.0, _t(1205))
    assert terug.candles().high == agg.candles().high
    assert terug.candles().low == agg.candles().low
    assert not terug.is_onvolledig(int(_t(900).timestamp()))
    assert terug.archiveerbaar(1) is not None


def test_a_bar_cut_by_the_restart_is_not_archived_as_complete():
    agg = _agg_met_bars()
    terug = QuoteAggregator.from_dict(agg.to_dict(), "5m")
    terug.add(4420.0, _t(1290))              # na de herstart: volgende interval
    afgebroken = int(_t(900).timestamp())
    assert terug.is_onvolledig(afgebroken), "bewaarde bar mist zijn eind"
    terug.add(4421.0, _t(1505))              # sluit de eerste bar na de herstart
    eerste = int(_t(1200).timestamp())
    assert terug.is_onvolledig(eerste), "eerste bar na herstart mist zijn begin"
    # In de reeks blijven ze - een gat is erger - maar niet in het archief.
    assert afgebroken in terug.candles().timestamp
    assert terug.archiveerbaar(2) is None
    # Ook over een tweede herstart heen.
    nog = QuoteAggregator.from_dict(terug.to_dict(), "5m")
    assert nog.is_onvolledig(eerste) and nog.is_onvolledig(afgebroken)


def test_without_a_stored_bar_the_first_bar_is_incomplete():
    oud = _agg_met_bars().to_dict()
    oud.pop("current")                       # opgeslagen door 1.7.4
    terug = QuoteAggregator.from_dict(oud, "5m")
    assert terug.bar_count == 3
    terug.add(4410.0, _t(1000))
    terug.add(4411.0, _t(1210))
    assert terug.is_onvolledig(int(_t(900).timestamp()))


def test_the_coordinator_does_not_archive_an_incomplete_bar(tmp_path, monkeypatch):
    c, _ = _coordinator(ScriptedVenue(), tmp_path, monkeypatch)

    class Archief:
        def __init__(self):
            self.opgeslagen = []

        def store(self, symbol, timeframe, candles, bron):
            self.opgeslagen.extend(candles.timestamp)

        def stats(self, *a):  # pragma: no cover
            return None

    c.archive = Archief()
    c._aggregator = QuoteAggregator.from_dict(_agg_met_bars().to_dict(), "5m")
    asyncio.run(c._update_from_quote(VenueQuote(4419.7, 4420.3, _t(1290))))
    assert int(_t(900).timestamp()) not in c.archive.opgeslagen


# --------------------------------------------------------------------------
# 11. Uitkomsten en sluitingswaarneming
# --------------------------------------------------------------------------


def test_service_results_and_closures_survive(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    a.backtest = {"trades": 5, "net_pnl": 1.5}
    a.validation = {"verdict": "ok"}
    a.lab = {"conclusie": "niets"}
    for _ in range(25):
        a.closures.record(NOW, False)
    _stop(a)

    b = _start(_bouw(hass, venue, a))
    assert b.backtest == {"trades": 5, "net_pnl": 1.5}
    assert b.validation == {"verdict": "ok"} and b.lab == {"conclusie": "niets"}
    assert b.closures.as_dict() == a.closures.as_dict()


def test_services_store_their_result():
    bron = open(os.path.join(PKG, "__init__.py"), encoding="utf-8").read()
    for veld in ("coordinator.backtest = summary",
                 "coordinator.validation = validatie.as_dict()",
                 "coordinator.lab = rapport.as_dict()"):
        na = bron.split(veld, 1)[1][:300]
        assert "async_bewaar_resultaten()" in na, veld


# --------------------------------------------------------------------------
# 12. Drawdown op de equity in de herberekening
# --------------------------------------------------------------------------


def test_the_first_cycle_keeps_the_account_drawdown(hass):
    c = _start(_bouw(hass, ScriptedVenue()))
    data = asyncio.run(c._async_update_data())
    assert data["stats"].get("drawdown_basis") == "account_equity"


# --------------------------------------------------------------------------
# 13. Herkansingen, gemelde bevindingen, evaluaties
# --------------------------------------------------------------------------


def test_retries_and_reported_findings_survive(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    sinds = datetime.now(timezone.utc) - timedelta(seconds=30)
    a._herkansingen = {"T7": {"pogingen": 1, "sinds": sinds}}
    a._audit_gemeld = {"zonder_stop:T7"}
    _stop(a)

    b = _start(_bouw(hass, venue, a))
    assert b._herkansingen == {"T7": {"pogingen": 1, "sinds": sinds}}
    assert b._audit_gemeld == {"zonder_stop:T7"}


def test_evaluations_never_drop_across_a_restart(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    voor = asyncio.run(a._async_update_data())["stats"]["signals"]["evaluations"]
    a.db.log_signal(a.run_id, 0.1, 0.2, "flat", None, 0.6, False, "test")
    _stop(a)

    b = _start(_bouw(hass, venue, a))
    na = asyncio.run(b._async_update_data())["stats"]["signals"]["evaluations"]
    assert na >= voor + 1


# --------------------------------------------------------------------------
# Overig: equity van de papersimulatie, dubbele init, compatibiliteit
# --------------------------------------------------------------------------


def test_paper_equity_is_called_for_risk_based_sizing(tmp_path, monkeypatch):
    from gold_scalper.broker.paper import BrokerCosts, PaperBroker
    from gold_scalper.modes import TradingMode

    c, _ = _coordinator(ScriptedVenue(), tmp_path, monkeypatch)
    c.mode = TradingMode.PAPER
    c.paper = PaperBroker(c.db, c.run_id, c.symbol, 10000.0, BrokerCosts())
    c.sizing.risk_based = True
    quote = VenueQuote(bid=4399.7, ask=4400.3, time=NOW)
    asyncio.run(c._open_position(_signaal(), quote, NOW))
    assert len(c.paper.open_positions) == 1
    # Het budget komt uit de equity van de simulatie: 0,5% van 10.000.
    assert "budget 50.00" in c.last_sizing["reason"]


def test_init_block_is_not_duplicated():
    bron = open(os.path.join(PKG, "coordinator.py"), encoding="utf-8").read()
    init = bron.split("def __init__(self, hass: HomeAssistant", 1)[1].split(
        "\n    async def ", 1)[0]
    for regel in ("self.sizing = SizingConfig(", "self.notifier = Notifier(",
                  "self._excursions: dict[str, dict] = {}",
                  "self._previous_risk_state: str | None = None"):
        assert init.count(regel) == 1, regel


def test_old_stored_state_loads_with_defaults():
    oud = {"enabled": True, "halted": False, "consecutive_losses": 2,
           "day": "2026-10-07", "day_start_balance": 9000.0, "bars": None}
    store = StateStore(None, "e")
    store._store._data = {"e": oud}
    state = asyncio.run(store.async_load())
    assert state.enabled and state.consecutive_losses == 2
    assert state.paused_until is None and state.pending_orders is None
    assert state.excursions is None and state.notify_sent is None
    assert RuntimeState(**state.as_dict()) == state


def test_a_restart_from_old_state_works(hass):
    venue = ScriptedVenue()
    a = _start(_bouw(hass, venue))
    run = a.run_id
    _stop(a)

    b = _bouw(hass, venue)
    b._store._store._data = {"test": {"enabled": True, "consecutive_losses": 1,
                                      "run_id": run}}
    _start(b)
    assert b.run_id == run and b.enabled
    assert b.risk.state.consecutive_losses == 1
    asyncio.run(b._async_update_data())


def test_results_store_without_file_is_empty():
    assert asyncio.run(ResultsStore(None, "e").async_load()) == {}
