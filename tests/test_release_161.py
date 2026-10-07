"""1.6.1: niet gevonden transacties alleen melden als de broker al bij is.

Live op 7 oktober 15:21: vijf waarschuwingen "Geen transactie gevonden" voor
trades van het laatste uur, terwijl de nieuwste transactie bij de broker van
12:20 UTC was. Die trades konden er nog niet in staan.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.ig_capital import broker_loopt_achter  # noqa: E402

LIJST = [
    {"dateUtc": "2026-10-07T12:20:10"},
    {"dateUtc": "2026-10-07T06:10:29"},
]


def test_trade_na_de_nieuwste_transactie_is_achterstand():
    sluit = datetime(2026, 10, 7, 13, 5, tzinfo=timezone.utc)
    assert broker_loopt_achter(LIJST, sluit) is True


def test_trade_van_voor_de_nieuwste_transactie_is_echt_onvindbaar():
    sluit = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)
    assert broker_loopt_achter(LIJST, sluit) is False


def test_zonder_datums_geldt_achterstand():
    assert broker_loopt_achter([{"openLevel": 4100}], datetime.now(timezone.utc))


def test_naieve_tijd_wordt_als_utc_gelezen():
    assert broker_loopt_achter(LIJST, datetime(2026, 10, 7, 13, 0)) is True


def test_veldenregel_is_geen_waarschuwing_meer():
    from pathlib import Path

    import gold_scalper.broker.ig_capital as mod

    bron = Path(mod.__file__).read_text()
    i = bron.index('"Transactieoverzicht van de broker: %d transacties')
    assert "_LOGGER.debug(" in bron[i - 120:i]
