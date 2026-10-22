"""2.20.3 - het nazoeken per positie (2.20.2) werkte live niet.

Live 22-10 na de herstart: nog steeds 3 afwijkingen en ``niet_bij_broker``
leeg. Oorzaak: 2.20.2 noemde een positie alleen "niet bij de broker" als de
broker per positie *geen enkele* deal teruggaf. Voor 58312111 gaf hij de
opening wel, alleen geen sluitende deal; voor 58383755 alleen de
deelsluiting, waarna deel en rest dezelfde deal claimden ("uitstap 4181.94
tegen 4184.55"). Nu telt het per sluitende deal, loopt het venster tot nu,
en houdt bij een dubbele claim alleen de trade met het dichtstbijzijnde
sluitmoment de deal.

Daarnaast: "Positie 58727864 heeft geen doel bij de broker" was ruis -
daghandel opent bewust zonder doel.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))

from gold_scalper.broker import ctrader  # noqa: E402
from gold_scalper.broker.adapter import VenueError, VenuePosition  # noqa: E402
from gold_scalper.broker.reconcile_audit import compare_positions  # noqa: E402
from gold_scalper.const import CONTRACT_SIZE  # noqa: E402
from gold_scalper.learning.afstemming import stem_af  # noqa: E402
from gold_scalper.storage.database import Trade  # noqa: E402

NU = datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc)
OPEN = NU - timedelta(days=6, hours=2)
DEEL = NU - timedelta(days=6, hours=1)
REST = NU - timedelta(days=6)


def _ms(d):
    return int(d.timestamp() * 1000)


def _venue(antwoorden):
    v = object.__new__(ctrader.CTraderVenue)
    v.ctid, v.symbol_id, v.valuta = 1, 41, "USD"
    v.verzoeken = []

    async def verzoek(soort, payload, verwacht=None, timeout=None):
        v.verzoeken.append((soort, payload))
        return antwoorden(soort, payload)

    async def klaar():
        return None

    v._verzoek = verzoek
    v._klaar = klaar
    return v


def _opening(pid):
    return {"dealId": f"o{pid}", "positionId": int(pid), "symbolId": 41,
            "tradeSide": "BUY", "executionPrice": 4174.32,
            "executionTimestamp": _ms(OPEN), "filledVolume": 1000}


def _sluiting(pid, prijs=4184.55, ts=DEEL, oz=5):
    return {"dealId": f"s{pid}{prijs}", "positionId": int(pid), "symbolId": 41,
            "tradeSide": "SELL", "executionPrice": prijs,
            "executionTimestamp": _ms(ts), "filledVolume": oz * 100,
            "closePositionDetail": {"entryPrice": 4174.32, "closedVolume": oz * 100,
                                    "grossProfit": 5115, "swap": 0, "commission": 0,
                                    "moneyDigits": 2}}


def _trade(i, ticket, close_time, close_price, volume=0.05):
    t = Trade(run_id=1, mode="demo", symbol="XAUUSD", side="buy", volume=volume,
              open_time=OPEN.isoformat(), open_price=4174.32, open_mid=4174.3,
              open_spread=0.1, close_time=close_time.isoformat(),
              close_price=close_price, net_pnl=51.15, broker_ticket=ticket,
              close_reason="partial_close", cost_source="measured")
    t.id = i
    return t


# Venue -------------------------------------------------------------------


def test_status_per_positie_met_opening_zonder_sluiting_en_fout():
    def broker(soort, p):
        if p["positionId"] == 58312111:
            return {"deal": [_opening(58312111)]}          # alleen de opening
        raise VenueError("cTrader: POSITION_NOT_FOUND")

    v = _venue(broker)
    tx, status = asyncio.run(v.transacties_van_posities({
        "58312111": (OPEN, NU), "58383755": (OPEN, NU)}))
    assert tx == []
    assert status["58312111"] == {"deals": 1, "sluitend": 0}
    assert "POSITION_NOT_FOUND" in status["58383755"]["fout"]
    # Venster tot nu, in stukken van hooguit een week.
    assert all(p["toTimestamp"] - p["fromTimestamp"] <= 7 * 86_400_000
               for _, p in v.verzoeken)


# Coordinator -------------------------------------------------------------


def _coord(zoek):
    return SimpleNamespace(venue=SimpleNamespace(transacties_van_posities=zoek),
                           POSITIES_NAZOEKEN_MAX=20)


def test_opening_zonder_sluitende_deal_telt_als_afwezig():
    from gold_scalper.coordinator import GoldScalperCoordinator as C

    gevraagd = {}

    async def zoek(posities):
        gevraagd.update(posities)
        return [], {"58312111": {"deals": 1, "sluitend": 0},
                    "58383755": {"deals": 2, "sluitend": 1},
                    "58400000": {"fout": "time-out"}}

    c = _coord(zoek)
    recent = [
        _trade(1, "58312111-deel", DEEL, 4184.55), _trade(2, "58312111", REST, 4181.94),
        _trade(3, "58383755-deel", DEEL, 4184.55), _trade(4, "58383755", REST, 4181.94),
        _trade(5, "58400000", REST, 4181.94),
    ]
    tx = [{"reference": "a", "dealId": "58383755"}]
    uit, afwezig = asyncio.run(C._vul_transacties_aan(c, recent, tx, NU))
    assert uit == tx
    assert afwezig == {"58312111", "58383755"}           # fout telt niet
    # Venster: van de opening tot nu, niet tot het eigen sluitmoment.
    assert all(eind == NU for _, eind in gevraagd.values())
    per = {r["positie"]: r for r in c._nagezocht}
    assert per["58400000"]["fout"] == "time-out"
    assert per["58383755"]["sluitend"] == 1 and per["58383755"]["eigen"] == 2


def test_aangevulde_sluitende_deal_maakt_positie_compleet():
    from gold_scalper.coordinator import GoldScalperCoordinator as C

    async def zoek(posities):
        return [{"reference": "a", "dealId": "58383755"},       # al bekend
                {"reference": "b", "dealId": "58383755"}], {
            "58383755": {"deals": 3, "sluitend": 2}}

    c = _coord(zoek)
    recent = [_trade(3, "58383755-deel", DEEL, 4184.55), _trade(4, "58383755", REST, 4181.94)]
    uit, afwezig = asyncio.run(C._vul_transacties_aan(
        c, recent, [{"reference": "a", "dealId": "58383755"}], NU))
    assert [t["reference"] for t in uit] == ["a", "b"]
    assert afwezig == set()


# Afstemming --------------------------------------------------------------


def _tx_deel():
    return ctrader.deal_naar_transactie(_sluiting(58383755), _opening(58383755), "USD")


def test_dubbele_claim_bij_nagezochte_positie_geen_afwijking():
    trades = [_trade(3, "58383755-deel", DEEL, 4184.55), _trade(4, "58383755", REST, 4181.94, 0.04)]
    u = stem_af(trades, [_tx_deel()], 1.0, NU, CONTRACT_SIZE, {"58383755"})
    assert u.afwijkingen == []
    assert [a.ticket for a in u.niet_bij_broker] == ["58383755"]
    assert u.gevonden == 1


def test_dubbele_claim_zonder_bevestiging_ongewijzigd():
    trades = [_trade(3, "58383755-deel", DEEL, 4184.55), _trade(4, "58383755", REST, 4181.94, 0.04)]
    u = stem_af(trades, [_tx_deel()], 1.0, NU, CONTRACT_SIZE)
    assert u.niet_bij_broker == []
    assert any("4181.94" in a.uitleg for a in u.afwijkingen)


def test_opening_zonder_sluiting_niet_bij_broker():
    trades = [_trade(1, "58312111-deel", DEEL, 4184.55), _trade(2, "58312111", REST, 4181.94)]
    u = stem_af(trades, [], 1.0, NU, CONTRACT_SIZE, {"58312111"})
    assert u.afwijkingen == [] and len(u.niet_bij_broker) == 2


# Geen doel ---------------------------------------------------------------


def _positie(tp):
    return VenuePosition(ticket="58727864", symbol="XAUUSD", side="sell", units=3.0,
                         open_price=4041.76, stop_loss=4073.48, take_profit=tp)


def _eigen(tp):
    return Trade(run_id=1, mode="demo", symbol="XAUUSD", side="sell",
                 volume=3.0 / CONTRACT_SIZE, open_time=NU.isoformat(),
                 open_price=4041.76, open_mid=4041.7, open_spread=0.1,
                 stop_loss=4073.48, take_profit=tp, broker_ticket="58727864")


def test_daghandel_zonder_doel_geen_waarschuwing():
    audit = compare_positions([_positie(None)], [_eigen(None)])
    assert not any(f.code == "geen_doel" for f in audit.findings)


def test_eigen_doel_ontbreekt_bij_broker_blijft_waarschuwing():
    audit = compare_positions([_positie(None)], [_eigen(4019.77)])
    assert any(f.code == "geen_doel" for f in audit.findings)

