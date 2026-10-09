"""Valuta, wisselkoersgeldigheid, vloer en drawdown.

EUR-account met een USD-instrument. De koers kwam alleen uit een gecorrigeerde
trade, zonder tijdstip; de vloer rekende op de ingestelde startbalans; de
drawdown telde dollars op bij die balans.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.currency import Conversion
from gold_scalper.broker.risk import RiskLimits, RiskManager
from gold_scalper.storage import performance
from gold_scalper.storage.database import TradeDatabase

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
NU = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _conv(uren_oud, gesloten=None, rate=0.87):
    return Conversion(
        instrument="USD", account="EUR", rate=rate, risk_rate=rate * 1.001,
        rate_timestamp=NU - timedelta(hours=uren_oud), rate_source="ig_market",
        market_closed=gesloten,
    )


# ---------------- geldigheid ----------------

@pytest.mark.parametrize("uren,gesloten,verwacht", [
    (1, None, True),        # vers
    (23.9, False, True),    # net binnen 24 uur
    (25, False, False),     # markt open: grens 24 uur
    (25, None, False),      # status onbekend: veilige grens 24 uur
    (25, True, True),       # markt aantoonbaar dicht: grens 72 uur
    (71, True, True),
    (73, True, False),      # na 72 uur altijd onbruikbaar
])
def test_rate_validity(uren, gesloten, verwacht):
    ok, reden = _conv(uren, gesloten).usable_for_entry(NU)
    assert ok is verwacht, reden


def test_no_rate_blocks_entry():
    ok, reden = Conversion("USD", "EUR", None).usable_for_entry(NU)
    assert not ok and "geen" in reden


def test_a_rate_without_timestamp_blocks_entry():
    """Een koers bewaard door een oudere versie heeft geen tijdstip."""
    c = Conversion("USD", "EUR", 0.87, rate_timestamp=None)
    assert c.usable_for_entry(NU)[0] is False


def test_same_currency_never_blocks():
    assert Conversion("USD", "USD", None).usable_for_entry(NU)[0] is True


def test_diagnostics_show_age_source_and_reason():
    d = _conv(2).as_dict()
    for k in ("rate", "risk_rate", "rate_source", "rate_timestamp",
              "rate_age_hours", "usable_for_entry", "entry_reason", "direction"):
        assert k in d
    assert d["direction"] == "EUR per USD"


# ---------------- voorzichtige koers ----------------

def test_the_risk_rate_is_the_conservative_side():
    """Budget in euro's naar dollars: het kleinste dollarbudget komt uit de
    biedkoers van EUR/USD."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "risk_rate=1.0 / q[\"bid\"]" in bron
    bid, offer = 1.1500, 1.1502
    mid = (bid + offer) / 2
    budget_eur = 10.0
    assert budget_eur * bid < budget_eur * mid


def test_an_expired_rate_blocks_only_new_positions():
    """Exitbeheer, afstemming en veiligheid lopen door."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    blok = bron.split("fx_ok, fx_reden = self.conversion.usable_for_entry(now)")[1][:2400]
    assert "if allowed and not fx_ok:" in blok
    lus = bron.split("async def _async_update_data")[1]
    # Het exitbeheer draait vóór en buiten de poort voor nieuwe posities.
    assert lus.index("await self._manage_open_positions(") < lus.index("usable_for_entry")


def test_a_derived_rate_does_not_override_a_fresh_market_rate():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    blok = bron.split("def _apply_rate")[1].split("\n    async def ")[0]
    assert "bron not in MARKT_BRONNEN and huidig.rate_source in MARKT_BRONNEN" in blok


def test_the_fx_quote_is_validated():
    """Een verkeerd instrument mag nooit als wisselkoers worden gebruikt."""
    from test_ig_capital import ig

    venue = ig({"/markets/CS.D.EURUSD.CFD.IP": ({
        "instrument": {"name": "Spot Gold"},
        "snapshot": {"bid": 4300.0, "offer": 4300.6, "marketStatus": "TRADEABLE"},
    }, 200)})
    assert asyncio.run(venue.fx_quote()) is None

    venue = ig({"/markets/CS.D.EURUSD.CFD.IP": ({
        "instrument": {"name": "EUR/USD"},
        "snapshot": {"bid": 11500.0, "offer": 11502.0, "marketStatus": "TRADEABLE"},
    }, 200)})
    q = asyncio.run(venue.fx_quote())
    assert q["bid"] == pytest.approx(1.15) and q["status"] == "TRADEABLE"


# ---------------- vloer ----------------

def test_the_floor_is_never_lowered():
    """50% van de ingestelde 10.000 is 5.000. 50% van een opening van 7.266
    is 3.633. Dat laatste als automatische migratie zou een stille
    versoepeling zijn."""
    rm = RiskManager(RiskLimits(equity_floor_pct=50.0), 10000.0, now=NU)
    v = rm.floor_breakdown(10000.0, 7266.09, 7300.0)
    assert v["configured_floor"] == 5000.0
    assert v["run_floor"] == pytest.approx(3633.05, abs=0.01)
    assert v["effective_equity_floor"] == 5000.0
    assert v["applied"] == "configured_floor"


def test_a_higher_opening_raises_the_floor():
    rm = RiskManager(RiskLimits(equity_floor_pct=50.0), 10000.0, now=NU)
    v = rm.floor_breakdown(10000.0, 14000.0)
    # 1.9.4: de run-vloer (7.000) ligt nog steeds boven de ingestelde
    # (5.000), maar de verliesvloer is strenger: vanaf 14.000 mag hooguit
    # 50% van de startbalans (5.000) verloren gaan, dus 9.000. Strengste wint.
    assert v["run_floor"] == 7000.0 and v["run_floor"] > v["configured_floor"]
    assert v["effective_equity_floor"] == 9000.0
    assert v["applied"] == "verliesvloer"


def test_a_missing_opening_keeps_todays_floor():
    rm = RiskManager(RiskLimits(equity_floor_pct=50.0), 10000.0, now=NU)
    assert rm.floor_breakdown(10000.0, None)["effective_equity_floor"] == 5000.0


def test_the_floor_blocks_below_the_effective_value():
    rm = RiskManager(RiskLimits(equity_floor_pct=50.0), 10000.0, now=NU)
    ok, reden = rm.can_open(
        now=NU, balance=4900.0, equity=4900.0, starting_balance=10000.0,
        open_positions=0, volume=0.01, spread=0.6, last_tick_age=1.0,
        opening_equity=7266.09,
    )
    assert not ok and "ondergrens" in reden


def test_the_opening_is_recorded_once(tmp_path):
    db = TradeDatabase(tmp_path / "o.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    db.set_run_opening(run, 7266.09, "EUR")
    db.set_run_opening(run, 9999.0, "EUR")
    r = db.get_run(run)
    assert r["opening_equity_account"] == pytest.approx(7266.09)
    assert r["account_currency"] == "EUR"


# ---------------- drawdown ----------------

def test_drawdown_on_account_equity(tmp_path):
    db = TradeDatabase(tmp_path / "d.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    for eq in (7300.0, 7400.0, 7250.0, 7350.0, 7200.0):
        db.record_equity(run, eq, eq, 0, 0.0)
    dd = db.account_drawdown(run)
    assert dd["max_drawdown"] == pytest.approx(200.0)
    assert dd["max_drawdown_pct"] == pytest.approx(200 / 7400 * 100, abs=0.01)


def test_a_new_basis_never_softens_the_verdict():
    """De live-poort keurt af boven 25% drawdown. Een andere berekening mag
    dat oordeel nooit milder maken: de strengste telt."""
    from gold_scalper.storage.database import Trade

    trades = [
        Trade(run_id=1, mode="demo", symbol="GOLD", side="buy", volume=0.01,
              open_time=f"2026-09-{1 + i % 28:02d}T10:00:00+00:00",
              open_price=4300.0, open_mid=4300.0, open_spread=0.6,
              close_time=f"2026-09-{1 + i % 28:02d}T10:20:00+00:00",
              net_pnl=3.0 if i % 2 else -2.0, gross_pnl=4.0 if i % 2 else -1.0,
              total_cost=1.0)
        for i in range(600)
    ]
    stats = performance.compute(trades, 10000.0)
    stats["max_drawdown_pct"] = 30.0          # zwaar op de oude basis
    performance.apply_account_drawdown(stats, {"max_drawdown": 50.0,
                                               "max_drawdown_pct": 1.0}, "EUR")
    assert stats["max_drawdown_pct"] == 1.0
    assert stats["max_drawdown_pct_trade_sequence"] == 30.0
    assert any("drawdown" in r for r in stats.get("blocking_reasons", []))


# ---------------- run 97 blijft niet stilletjes lopen ----------------

def test_semantics_and_candle_source_are_structural():
    """Zonder dit zou een run als 97 na de update worden voortgezet: de nieuwe
    sleutels zijn geen gebruikerskeuze."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    blok = bron.split("async def _adoptable_run")[1].split("\n    async def ")[0]
    assert '"execution_semantics", "candle_source"' in blok


# ---------------- grafiek ----------------

def test_the_chart_does_not_mix_currencies():
    from gold_scalper.dashboard.report import _cost_rate

    run = {"account_currency": "EUR", "config_json": '{"instrument_currency": "USD"}'}
    assert _cost_rate(run, {"rate": 0.87}) == (0.87, None)
    koers, melding = _cost_rate(run, None)
    assert koers is None and "niet getoond" in melding
    assert _cost_rate({"account_currency": "USD", "config_json": "{}"}, None) == (1.0, None)


def test_the_rate_is_refreshed_every_cycle_not_only_on_a_signal():
    """Eerst alleen vlak vóór een instap: de diagnostiek toonde "geblokkeerd"
    tot het eerste signaal, en een niet-werkend epic kostte dat signaal."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    lus = bron.split("async def _async_update_data")[1]
    verversen = lus.index("await self._refresh_fx(now)")
    assert verversen < lus.index("fx_ok, fx_reden = self.conversion.usable_for_entry(now)")
    assert lus.count("await self._refresh_fx(now)") == 1
    # Buiten de voorwaarde voor een handelbare goudkoers: op het niveau van de
    # lus zelf (acht spaties), niet ingesprongen onder "if quote.tradeable".
    regel = lus[:verversen].rsplit("\n", 1)[1]
    assert regel == " " * 8, repr(regel)


def test_a_restored_halt_is_not_logged_as_new(caplog):
    """De bewaarde noodstop logde bij terugzetten dezelfde NOODSTOP-regel als
    de oorspronkelijke. Dat leek na 5.4.1 een nieuwe detectie."""
    import logging
    from gold_scalper.broker.risk import TradingState

    rm = RiskManager(RiskLimits(), 10000.0, now=NU)
    with caplog.at_level(logging.DEBUG):
        rm.restore_halt("oude reden")
    assert rm.state.state is TradingState.HALTED
    assert not [r for r in caplog.records if "NOODSTOP" in r.getMessage()]


# ---------------- omrekenkoers uit het instrument (echt IG-antwoord) ----------------

ECHT = Path(__file__).parent / "fixtures" / "ig_antwoorden.json"


def _echt():
    import json
    return json.loads(ECHT.read_text(encoding="utf-8"))


def test_the_rate_is_read_from_the_gold_quote():
    """IG stuurt bij de goudkoers de omrekenkoers mee. Het apart ophalen van
    EUR/USD gaf bij dit account voor drie epics geen bied- of laatkoers."""
    from test_ig_capital import ig

    venue = ig({"/markets/CS.D.CFEGOLD.CEA.IP": (_echt()["markets"], 200)})
    asyncio.run(venue.quote("CS.D.CFEGOLD.CEA.IP"))
    fx = venue.instrument_fx()
    assert fx["code"] == "USD" and fx["base_rate"] == pytest.approx(1.134785)
    assert 1.0 / fx["base_rate"] == pytest.approx(0.88122, abs=1e-5)


def test_exchange_rate_field_is_not_the_conversion():
    """``exchangeRate`` (0,66) lag 25% naast elke conversie van de broker."""
    from test_ig_capital import ig

    venue = ig({"/markets/CS.D.CFEGOLD.CEA.IP": (_echt()["markets"], 200)})
    asyncio.run(venue.quote("CS.D.CFEGOLD.CEA.IP"))
    assert venue.instrument_fx()["base_rate"] != 0.66


def test_the_brokers_conversion_is_parsed_from_the_transaction():
    from gold_scalper.broker.ig_capital import match_transaction

    txs = _echt()["transactions_v2"]["transactions"]
    verlies = match_transaction(txs, "X", 4129.78, "sell", 1.56)
    winst = match_transaction(txs, "X", 4134.69, "sell", 1.53)
    assert verlies["profit_account"] < 0 and verlies["conversion_rate"] == pytest.approx(0.886687704)
    assert winst["profit_account"] > 0 and winst["conversion_rate"] == pytest.approx(0.8731281439999999)


def test_the_broker_converts_losses_above_and_profits_below_the_mid():
    """De verborgen kostenpost: winst ~1% onder, verlies ~0,56% boven het
    midden. Daarom is de verlieskoers de voorzichtige koers."""
    import re
    import statistics

    data = _echt()
    midden = 1.0 / data["markets"]["instrument"]["currencies"][0]["baseExchangeRate"]
    winst, verlies = [], []
    for t in data["transactions_v2"]["transactions"]:
        k = float(re.search(r"converted at ([0-9.]+)", t["instrumentName"]).group(1))
        (verlies if t["profitAndLoss"].startswith("E-") else winst).append(k)
    assert statistics.mean(verlies) > midden > statistics.mean(winst)


def test_sizing_uses_the_loss_rate_when_recent():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    blok = bron.split("async def _refresh_fx")[1].split("\n    async def ")[0]
    assert "now - self._loss_fx_at <= timedelta(hours=24)" in blok
    assert "if verlies > midden:" in blok
    assert '"ig_instrument"' in blok


def test_a_wrong_direction_is_refused():
    """Een koers die meer dan 3% van de laatste brokerconversie afwijkt, wordt
    niet gebruikt: dan betekent het veld iets anders dan gedacht."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    blok = bron.split("async def _refresh_fx")[1].split("\n    async def ")[0]
    assert "abs(midden / ref - 1.0) > 0.03" in blok
    assert 1.134785 / 0.8812 > 1.03      # de omgekeerde richting valt eruit
