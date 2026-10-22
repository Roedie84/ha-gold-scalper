"""2.20.4 - Pepperstone: koppelen op het positienummer.

Live 22-10 (2.20.3 actief): positie 58312111 bleef "staat na 7.9 dagen niet in
het overzicht" (deel en rest, elk 0,095 lot = 9,5 oz) terwijl ``nagezocht``
leeg was - het overzicht had dus al evenveel sluitende deals als eigen
trades. De broker sluit hele hoeveelheden (9 en 10 oz): de omvang week meer
dan 0,25 oz af en de ruime omvangregel gold niet, dus geen koppeling. Het
positienummer van cTrader is exact het eigen ticket; daarmee koppelen.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))

from gold_scalper.broker import ctrader  # noqa: E402
from gold_scalper.broker.ig_capital import match_transaction  # noqa: E402
from gold_scalper.learning.afstemming import stem_af  # noqa: E402
from gold_scalper.storage.database import Trade  # noqa: E402

NU = datetime(2026, 10, 22, 17, 37, tzinfo=timezone.utc)
OPEN = datetime(2026, 10, 14, 19, 6, 43, tzinfo=timezone.utc)
DEEL = datetime(2026, 10, 14, 19, 15, 16, tzinfo=timezone.utc)
REST = datetime(2026, 10, 14, 19, 17, 28, tzinfo=timezone.utc)


def _ms(d):
    return int(d.timestamp() * 1000)


def _opening(pid=58312111, prijs=4093.51):
    return {"dealId": f"o{pid}", "positionId": pid, "symbolId": 41, "tradeSide": "BUY",
            "executionPrice": prijs, "executionTimestamp": _ms(OPEN) + 900, "filledVolume": 1900}


def _sluit(prijs, ts, oz, pid=58312111, instap=4093.51, bruto=5000):
    return {"dealId": f"s{pid}{prijs}", "positionId": pid, "symbolId": 41,
            "tradeSide": "SELL", "executionPrice": prijs, "executionTimestamp": _ms(ts),
            "filledVolume": oz * 100,
            "closePositionDetail": {"entryPrice": instap, "closedVolume": oz * 100,
                                    "grossProfit": bruto, "swap": 0, "commission": -50,
                                    "moneyDigits": 2}}


def _tx(*deals, opening=None):
    opening = opening or _opening()
    return [ctrader.deal_naar_transactie(d, opening, "USD") for d in deals]


def _trade(i, ticket, close_time, close_price, volume=0.095, open_price=4093.48):
    t = Trade(run_id=3, mode="demo", symbol="XAUUSD", side="buy", volume=volume,
              open_time=OPEN.isoformat(), open_price=open_price, open_mid=open_price,
              open_spread=0.1, close_time=close_time.isoformat(),
              close_price=close_price, net_pnl=50.0, broker_ticket=ticket,
              close_reason="partial_close", cost_source="measured")
    t.id = i
    return t


def test_hele_ounces_bij_broker_koppelen_op_positie():
    tx = _tx(_sluit(4098.80, DEEL, 9), _sluit(4104.25, REST, 10))
    deel = match_transaction(tx, "58312111-deel", 4093.48, "buy", 9.5,
                             OPEN.isoformat(), DEEL.isoformat())
    rest = match_transaction(tx, "58312111", 4093.48, "buy", 9.5,
                             OPEN.isoformat(), REST.isoformat())
    assert deel["matched_on"] == rest["matched_on"] == "positienummer"
    assert deel["exit_price"] == 4098.80 and rest["exit_price"] == 4104.25
    assert deel["tx_sleutel"] != rest["tx_sleutel"]


def test_afstemming_vindt_beide_en_neemt_broker_over():
    tx = _tx(_sluit(4098.80, DEEL, 9), _sluit(4104.25, REST, 10))
    trades = [_trade(28, "58312111-deel", DEEL, 4098.82), _trade(17, "58312111", REST, 4104.20)]
    u = stem_af(trades, tx, 1.0, NU, 100.0)
    assert u.gevonden == 2
    assert not [a for a in u.afwijkingen if a.soort == "ontbreekt"]


def test_deal_van_andere_positie_telt_niet():
    # Zelfde instap, richting en omvang, maar een andere positie: niet de onze
    # zodra de eigen positie in het overzicht staat.
    eigen = _sluit(4104.25, REST, 10)
    vreemd = _sluit(4099.00, REST, 9, pid=58312999, instap=4093.48)
    tx = _tx(vreemd, eigen)
    m = match_transaction(tx, "58312111", 4093.48, "buy", 9.5,
                          OPEN.isoformat(), REST.isoformat())
    assert m["exit_price"] == 4104.25


def test_zonder_eigen_positie_in_overzicht_oude_regel():
    # Geen deal met dit positienummer: de koppeling op prijs blijft werken
    # zoals voorheen (bijvoorbeeld een ticket dat geen positienummer is).
    tx = _tx(_sluit(4100.0, REST, 9, pid=1, instap=4093.48))
    m = match_transaction(tx, "58312111", 4093.48, "buy", 9.0,
                          OPEN.isoformat(), REST.isoformat())
    assert m["matched_on"] == "instapprijs+opentijd"


def test_ig_transacties_ongewijzigd():
    tx = [{"reference": "ABC", "openLevel": 4093.48, "closeLevel": 4100.0, "size": "+9",
           "openDateUtc": OPEN.isoformat(), "dateUtc": REST.isoformat(),
           "profitAndLoss": 58.0}]
    m = match_transaction(tx, "DIAAAAB", 4093.48, "buy", 9.0, OPEN.isoformat(), REST.isoformat())
    assert m["matched_on"] == "instapprijs+opentijd"


def test_deel_en_rest_kiezen_op_omvang_bij_verschil():
    # 58383755: deel 4 oz, rest 5 oz; de omvang beslist, ook als de eigen
    # rest-sluiting dichter bij de deelsluiting zou liggen.
    t_deel = datetime(2026, 10, 16, 7, 9, 43, tzinfo=timezone.utc)
    t_rest = datetime(2026, 10, 16, 8, 16, 55, tzinfo=timezone.utc)
    op = _opening(58383755, 4174.32)
    tx = _tx(_sluit(4184.55, t_deel, 4, pid=58383755, instap=4174.32),
             _sluit(4181.94, t_rest, 5, pid=58383755, instap=4174.32), opening=op)
    rest = match_transaction(tx, "58383755", 4174.32, "buy", 5.0,
                             op and OPEN.isoformat(), t_deel.isoformat())
    assert rest["exit_price"] == 4181.94
