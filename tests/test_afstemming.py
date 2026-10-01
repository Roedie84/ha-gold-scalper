"""Dagelijkse afstemming met de broker, en tests op echte brokerantwoorden.

Zes keer werd een fout in de koppeling gevonden door een schermafdruk van het
brokeroverzicht naast het rapport te leggen. De afstemming doet dat nu zelf.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.learning.afstemming import stem_af
from gold_scalper.storage.database import Trade

NU = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)
KOERS = 0.8698


def _trade(open_price, close_price, net, side="sell", volume=0.0176,
           uur=12, ticket="T1"):
    moment = NU.replace(hour=uur)
    return Trade(
        run_id=1, mode="demo", symbol="GOLD", side=side, volume=volume,
        open_time=(moment - timedelta(minutes=30)).isoformat(),
        open_price=open_price, open_mid=open_price, open_spread=0.6,
        close_time=moment.isoformat(), close_price=close_price,
        net_pnl=net, close_reason="broker_gesloten_gecorrigeerd",
        broker_ticket=ticket,
    )


def _tx(open_level, close_level, pnl_eur, size="-1.76"):
    return {"openLevel": str(open_level), "closeLevel": str(close_level),
            "profitAndLoss": f"E{pnl_eur}", "size": size,
            "dateUtc": "2026-09-28T12:00:00"}


def test_a_matching_trade_is_fine():
    uitslag = stem_af([_trade(4319.64, 4310.88, 15.42)],
                      [_tx(4319.64, 4310.88, 13.41)], KOERS, NU)
    assert uitslag.kloppend == 1 and uitslag.in_orde


def test_a_wrong_exit_is_reported():
    """Precies de fout die met schermafdrukken werd gevonden: een uitstapprijs
    die vlak bij de instap lag terwijl de broker tien dollar verder sloot."""
    uitslag = stem_af([_trade(4319.64, 4320.27, -1.11)],
                      [_tx(4319.64, 4310.88, 13.41)], KOERS, NU)
    assert len(uitslag.afwijkingen) == 1
    assert "uitstap" in uitslag.afwijkingen[0].uitleg


def test_a_wrong_amount_is_reported():
    uitslag = stem_af([_trade(4319.64, 4310.88, 5.00)],
                      [_tx(4319.64, 4310.88, 13.41)], KOERS, NU)
    assert "bedrag" in uitslag.afwijkingen[0].uitleg


def test_a_small_currency_difference_is_not_an_error():
    """De broker rekent winst en verlies tegen verschillende koersen om; één
    koers voor beide geeft kleine verschillen die geen fout zijn."""
    uitslag = stem_af([_trade(4319.64, 4310.88, 15.50)],
                      [_tx(4319.64, 4310.88, 13.41)], KOERS, NU)
    assert uitslag.in_orde


def test_a_recent_missing_trade_is_patience_not_an_error():
    """Het overzicht loopt uren achter."""
    uitslag = stem_af([_trade(4319.64, 4310.88, 15.42, uur=19)], [], KOERS, NU)
    assert uitslag.in_orde and uitslag.nog_niet_verwerkt == 1


def test_an_old_missing_trade_is_reported():
    oud = _trade(4319.64, 4310.88, 15.42)
    oud.close_time = (NU - timedelta(days=3)).isoformat()
    uitslag = stem_af([oud], [], KOERS, NU)
    assert uitslag.afwijkingen[0].soort == "ontbreekt"


def test_the_same_matching_rule_as_the_correction():
    """Afstemming en correctie mogen nooit tot een ander oordeel komen over
    welke transactie bij welke trade hoort."""
    bron = (Path(__file__).resolve().parent.parent / "custom_components"
            / "gold_scalper" / "learning" / "afstemming.py").read_text(encoding="utf-8")
    assert "match_transaction" in bron
    ig = (Path(__file__).resolve().parent.parent / "custom_components"
          / "gold_scalper" / "broker" / "ig_capital.py").read_text(encoding="utf-8")
    closed = ig.split("async def closed_deal")[1].split("\n    async def ")[0]
    assert "match_transaction(" in closed


def test_private_fields_are_removed():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from custom_components.gold_scalper import _anonimiseer

    ruw = {"accounts": [{"accountId": "ABC123", "accountName": "Ruud",
                         "balance": {"balance": 7266.09}}]}
    schoon = _anonimiseer(ruw)
    assert schoon["accounts"][0]["accountId"] == "VERWIJDERD"
    assert schoon["accounts"][0]["accountName"] == "VERWIJDERD"
    assert schoon["accounts"][0]["balance"]["balance"] == 7266.09


# ---------------- echte brokerantwoorden ----------------

ANTWOORDEN = Path(__file__).parent / "fixtures" / "ig_antwoorden.json"


@pytest.mark.skipif(not ANTWOORDEN.exists(), reason="nog geen echte antwoorden aangeleverd")
def test_real_positions_parse():
    """Tegen wat de broker werkelijk stuurt, niet tegen wat ik verwacht."""
    import asyncio
    from test_ig_capital import ig
    from gold_scalper.broker.adapter import size_says_closed

    data = json.loads(ANTWOORDEN.read_text(encoding="utf-8"))
    venue = ig({"/positions": (data["positions_v2"], 200)})
    for pos in asyncio.run(venue.positions()):
        assert not size_says_closed(pos.units), "open positie leest als gesloten"
        assert pos.open_price > 0


@pytest.mark.skipif(not ANTWOORDEN.exists(), reason="nog geen echte antwoorden aangeleverd")
def test_real_transactions_have_the_fields_we_read():
    data = json.loads(ANTWOORDEN.read_text(encoding="utf-8"))
    for tx in data["transactions_v2"].get("transactions", []):
        for veld in ("openLevel", "closeLevel", "profitAndLoss", "size"):
            assert veld in tx, f"veld {veld} ontbreekt in een echt antwoord"
