"""1.7.2: het transactieoverzicht alleen 'onvolledig' noemen als eigen trades
die al lang genoeg dicht zijn er aantoonbaar in ontbreken, en hooguit eens per
uur als waarschuwing.

Op 8 oktober gaf de oude regel (vaste drempel "< 3") tussen 03:15 en 04:03
tweeëntwintig valse waarschuwingen: na de avondpauze is het venster bijna
leeg en direct na een sluiting loopt het overzicht van de broker achter.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from test_ig_capital import ig

from gold_scalper.broker.ig_capital import ontbrekende_transacties

NU = datetime(2026, 10, 8, 3, 30, tzinfo=timezone.utc)


def _tx(n):
    return ({"transactions": [
        {"openLevel": "4000.00", "closeLevel": "4001.00", "size": "1.0",
         "dateUtc": "2026-10-08T03:00:00"} for _ in range(n)
    ]}, 200)


def _waarschuwingen(caplog):
    return [
        r for r in caplog.records
        if r.levelno >= logging.WARNING
        and ("Transactieoverzicht" in r.getMessage()
             or "datumbereik" in r.getMessage())
    ]


def test_recent_closes_do_not_count_as_missing():
    van, tot = NU - timedelta(hours=6), NU
    eigen = [NU - timedelta(minutes=m) for m in (5, 20, 40)]
    assert ontbrekende_transacties(1, eigen, van, tot, NU) == (0, 0)


def test_old_closes_outside_the_window_do_not_count():
    van, tot = NU - timedelta(hours=6), NU
    eigen = [NU - timedelta(hours=8), "2026-10-07T20:00:00+00:00"]
    assert ontbrekende_transacties(0, eigen, van, tot, NU) == (0, 0)


def test_ripe_closes_missing_from_the_overview_are_counted():
    van, tot = NU - timedelta(hours=18), NU
    eigen = [NU - timedelta(hours=h) for h in (7, 8, 9)] + [
        NU - timedelta(minutes=10)]
    assert ontbrekende_transacties(1, eigen, van, tot, NU) == (3, 2)
    assert ontbrekende_transacties(3, eigen, van, tot, NU) == (3, 0)


def test_no_warning_without_own_trades_to_compare(caplog):
    venue = ig({"/history/transactions": _tx(1)})
    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            asyncio.run(venue.closed_deal("T1", 4319.64, "sell"))
    assert _waarschuwingen(caplog) == []
    assert not any("vierentwintig" in r.getMessage() for r in caplog.records)


def test_no_warning_when_only_fresh_trades_are_missing(caplog):
    venue = ig({"/history/transactions": _tx(1)})
    nu = datetime.now(timezone.utc)
    eigen = [nu - timedelta(minutes=m) for m in (10, 25, 50)]
    with caplog.at_level(logging.DEBUG):
        asyncio.run(venue.closed_deal(
            "T1", 4319.64, "sell", own_close_times=eigen))
    assert _waarschuwingen(caplog) == []


def test_missing_ripe_trades_warn_once_per_hour(caplog):
    venue = ig({"/history/transactions": _tx(1)})
    nu = datetime.now(timezone.utc)
    eigen = [nu - timedelta(hours=h) for h in (7, 8, 9)]
    with caplog.at_level(logging.DEBUG):
        for _ in range(22):
            asyncio.run(venue.closed_deal(
                "T1", 4319.64, "sell", nu - timedelta(hours=8),
                own_close_times=eigen))
    waarschuwingen = _waarschuwingen(caplog)
    assert len(waarschuwingen) == 1
    tekst = waarschuwingen[0].getMessage()
    assert "onvolledig" in tekst and "UTC" in tekst
    assert "vierentwintig" not in tekst


def test_enough_transactions_give_no_warning(caplog):
    venue = ig({"/history/transactions": _tx(3)})
    nu = datetime.now(timezone.utc)
    eigen = [nu - timedelta(hours=h) for h in (7, 8, 9)]
    with caplog.at_level(logging.DEBUG):
        asyncio.run(venue.closed_deal(
            "T1", 4319.64, "sell", nu - timedelta(hours=8),
            own_close_times=eigen))
    assert _waarschuwingen(caplog) == []
