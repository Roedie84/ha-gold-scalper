"""Eén definitie van een handelsdag.

Er waren er drie: periodeoverzicht in Amsterdamse tijd, dagcijfers, rapport en
live-poort in UTC, risicodag in UTC. Trades die tussen 22:00 en 24:00 UTC
sloten, vielen in het ene overzicht op de ene dag en in het andere op de
volgende.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.risk import RiskLimits, RiskManager
from gold_scalper.storage.database import Trade
from gold_scalper.storage.performance import daily_breakdown
from gold_scalper.storage.periods import build_periods
from gold_scalper.timeutil import parse_utc, trading_day, trading_day_of


def _trade(close_iso: str, net: float = 1.0) -> Trade:
    return Trade(
        run_id=1, mode="demo", symbol="GOLD", side="buy", volume=0.01,
        open_time=close_iso, open_price=4300.0, open_mid=4300.0,
        open_spread=0.6, close_time=close_iso, net_pnl=net, gross_pnl=net,
        total_cost=0.0,
    )


@pytest.mark.parametrize("utc_tijd,verwacht", [
    ("2026-09-23T21:59:00+00:00", "2026-09-23"),   # zomertijd: 23:59 lokaal
    ("2026-09-23T22:00:00+00:00", "2026-09-24"),   # 00:00 lokaal
    ("2026-09-23T23:59:00+00:00", "2026-09-24"),
    ("2026-01-15T22:59:00+00:00", "2026-01-15"),   # wintertijd: 23:59 lokaal
    ("2026-01-15T23:00:00+00:00", "2026-01-16"),   # 00:00 lokaal
])
def test_the_boundary_between_22_and_24_utc(utc_tijd, verwacht):
    assert trading_day_of(utc_tijd).isoformat() == verwacht


@pytest.mark.parametrize("utc_tijd,verwacht", [
    # 29 maart 2026: klok gaat om 02:00 lokaal naar 03:00
    ("2026-03-28T22:30:00+00:00", "2026-03-28"),   # 23:30 CET
    ("2026-03-28T23:30:00+00:00", "2026-03-29"),   # 00:30 CET
    ("2026-03-29T00:30:00+00:00", "2026-03-29"),   # 01:30 CET
    ("2026-03-29T01:30:00+00:00", "2026-03-29"),   # 03:30 CEST
    # 25 oktober 2026: klok gaat om 03:00 lokaal terug naar 02:00
    ("2026-10-24T21:30:00+00:00", "2026-10-24"),   # 23:30 CEST
    ("2026-10-24T22:30:00+00:00", "2026-10-25"),   # 00:30 CEST
    ("2026-10-25T00:30:00+00:00", "2026-10-25"),   # 02:30 CEST
    ("2026-10-25T01:30:00+00:00", "2026-10-25"),   # 02:30 CET
])
def test_daylight_saving_transitions(utc_tijd, verwacht):
    assert trading_day_of(utc_tijd).isoformat() == verwacht


def test_a_naive_time_is_refused():
    with pytest.raises(ValueError):
        trading_day(datetime(2026, 9, 23, 22, 30))


def test_stored_utc_is_explicit():
    """De database schrijft UTC; een tijd zonder zone uit de database is UTC,
    en dat wordt op één plek expliciet gemaakt."""
    assert parse_utc("2026-09-23T22:30:00").tzinfo == timezone.utc


def test_every_aggregation_uses_the_same_day():
    """Een trade die om 22:30 UTC sluit, telt overal op dezelfde handelsdag."""
    trade = _trade("2026-09-23T22:30:00+00:00")
    verwacht = "2026-09-24"

    assert daily_breakdown([trade])[0]["date"] == verwacht
    assert build_periods([trade]).daily[0].start == verwacht


def test_the_risk_day_follows_the_trading_day():
    """Het dagverlies rolde om 00:00 UTC, twee uur later dan de dag in het
    periodeoverzicht."""
    voor = datetime(2026, 9, 23, 21, 30, tzinfo=timezone.utc)   # 23:30 lokaal
    na = datetime(2026, 9, 23, 22, 30, tzinfo=timezone.utc)     # 00:30 lokaal
    rm = RiskManager(RiskLimits(), 10000.0, now=voor)
    assert rm.state.day.isoformat() == "2026-09-23"
    rm._roll_day(na, 9999.0)
    assert rm.state.day.isoformat() == "2026-09-24"


def test_each_trade_has_one_utc_close_and_one_trading_day():
    """Uniek per trade: dezelfde invoer levert altijd dezelfde dag."""
    trades = [_trade(f"2026-09-2{d}T{h:02d}:15:00+00:00") for d in (3, 4) for h in range(24)]
    eerste = daily_breakdown(trades)
    tweede = daily_breakdown(list(reversed(trades)))
    assert sum(d["trades"] for d in eerste) == len(trades)
    assert eerste == tweede


def test_totals_survive_the_regrouping():
    """Anders verplaatsen trades niet maar verdwijnen ze."""
    trades = [_trade(f"2026-09-23T{h:02d}:10:00+00:00", net=h - 10) for h in range(24)]
    assert sum(d["net_pnl"] for d in daily_breakdown(trades)) == pytest.approx(
        sum(t.net_pnl for t in trades)
    )
    assert sum(b.net for b in build_periods(trades).daily) == pytest.approx(
        sum(t.net_pnl for t in trades)
    )


def test_no_caller_can_fall_back_to_utc():
    """De tijdzoneparameter is weg; wie hem toch meegeeft, krijgt een fout in
    plaats van een stille UTC-dag."""
    import inspect

    assert "tz" not in inspect.signature(daily_breakdown).parameters
    assert "tz" not in inspect.signature(build_periods).parameters
