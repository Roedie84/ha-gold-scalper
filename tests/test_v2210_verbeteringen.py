"""2.21.0 - vijf goedgekeurde verbeteringen (Ruud 23-10).

7. Pepperstone-afstemming: deel en rest van één positie claimden dezelfde
   deal (58383755: rest 4181,94 tegen 4184,55); nu één deal per trade, in de
   volgorde van sluiten, en de uitstap van de broker wordt overgenomen.
8. Limiet per richting over alle strategieën samen, met beschermde posities,
   orders onderweg en orders van dezelfde cyclus; geen dubbele order op één
   prijs over strategieën heen.
9. Saldosprong op papier: een nieuwe run zet het papiersaldo op de
   startbalans - geen sprong; tijdens een sprong verklaart een positie of
   sluiting de verandering.
10. cTrader: een algemeen verzoek wacht niet meer achter de 0,4 s-afstand van
    historische verzoeken; deelstappen van de latency apart gemeten.
11. 'Openen geweigerd (papermarge)' noemt de markt.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))

from gold_scalper.broker import ctrader  # noqa: E402
from gold_scalper.broker.saldosprong import SaldoSprongBewaker  # noqa: E402
from gold_scalper.coordinator import GoldScalperCoordinator  # noqa: E402
from gold_scalper.learning.afstemming import stem_af  # noqa: E402
from gold_scalper.storage.database import Trade  # noqa: E402

BRON = os.path.join(HIER, "..", "custom_components", "gold_scalper")


def _lees(naam: str) -> str:
    with open(os.path.join(BRON, naam), encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------- #
# 7. Afstemming: één deal per trade binnen een positie
# --------------------------------------------------------------------------- #

NU = datetime(2026, 10, 23, 5, 0, tzinfo=timezone.utc)
OPEN = datetime(2026, 10, 16, 5, 3, 13, tzinfo=timezone.utc)
DEEL = datetime(2026, 10, 16, 7, 9, 43, tzinfo=timezone.utc)
REST = datetime(2026, 10, 16, 8, 16, 55, tzinfo=timezone.utc)
PID = 58383755


def _ms(d):
    return int(d.timestamp() * 1000)


def _opening():
    return {"dealId": "o1", "positionId": PID, "symbolId": 41, "tradeSide": "BUY",
            "executionPrice": 4174.32, "executionTimestamp": _ms(OPEN), "filledVolume": 900}


def _sluit(prijs, ts, oz, bruto):
    return {"dealId": f"s{prijs}", "positionId": PID, "symbolId": 41,
            "tradeSide": "SELL", "executionPrice": prijs, "executionTimestamp": _ms(ts),
            "filledVolume": oz * 100,
            "closePositionDetail": {"entryPrice": 4174.32, "closedVolume": oz * 100,
                                    "grossProfit": bruto, "swap": 0, "commission": 0,
                                    "moneyDigits": 2}}


def _trade(i, ticket, sluit, prijs, volume, netto):
    t = Trade(run_id=4, mode="demo", symbol="XAUUSD", side="buy", volume=volume,
              open_time=OPEN.isoformat(), open_price=4174.32, open_mid=4174.23,
              open_spread=0.14, close_time=sluit.isoformat(), close_price=prijs,
              net_pnl=netto, broker_ticket=ticket, close_reason="stop_loss",
              cost_source="measured")
    t.id = i
    return t


def _scenario(rest_oz=3, rest_prijs=4181.97):
    tx = [ctrader.deal_naar_transactie(d, _opening(), "USD") for d in (
        _sluit(4184.55, DEEL, 4, 4092),
        _sluit(rest_prijs, REST, rest_oz, int((rest_prijs - 4174.32) * rest_oz * 100)),
    )]
    trades = [
        _trade(763, f"{PID}-deel", DEEL, 4184.55, 0.04, 40.92),
        # 0,05 lot zoals live: 0.049999999999999996.
        _trade(720, str(PID), REST, 4181.94, 0.049999999999999996, 38.10),
    ]
    return trades, tx


def test_deel_en_rest_claimen_niet_meer_dezelfde_deal():
    trades, tx = _scenario()
    u = stem_af(trades, tx, None, NU, 100.0)
    assert u.afwijkingen == [], [a.uitleg for a in u.afwijkingen]
    assert u.gevonden == 2 and u.kloppend == 2


def test_uitstap_van_de_broker_overgenomen_voor_de_rest():
    trades, tx = _scenario()
    u = stem_af(trades, tx, None, NU, 100.0)
    rest = next(o for o in u.overnames if o["trade_id"] == 720)
    assert rest["velden"]["close_price"] == 4181.97
    assert "ADOPTED_BROKER_SETTLEMENT" in rest["velden"]["exit_price_provenance"]
    # De deelsluiting houdt haar eigen deal (4184,55) en verandert niet van prijs.
    deel = [o for o in u.overnames if o["trade_id"] == 763]
    assert not deel or "close_price" not in deel[0]["velden"]


def test_volgorde_van_sluiten_beslist_ook_bij_gelijke_omvang():
    # De broker sloot beide in hele ounces die niets over deel/rest zeggen.
    trades, tx = _scenario(rest_oz=4, rest_prijs=4182.10)
    u = stem_af(trades, tx, None, NU, 100.0)
    assert u.afwijkingen == []
    rest = next(o for o in u.overnames if o["trade_id"] == 720)
    assert rest["velden"]["close_price"] == 4182.10


def test_te_weinig_deals_blijft_zoals_het_was():
    trades, tx = _scenario()
    alleen_deel = tx[:1]
    u = stem_af(trades, alleen_deel, None, NU, 100.0)
    # Zonder nagezochte bevestiging blijft het een zichtbare afwijking; er wordt
    # niets overgenomen voor de rest.
    assert any("4181.94" in a.uitleg for a in u.afwijkingen)
    assert not any(o["trade_id"] == 720 and "close_price" in o["velden"]
                   for o in u.overnames)


# --------------------------------------------------------------------------- #
# 8. Limiet per richting over alle strategieën samen
# --------------------------------------------------------------------------- #

def _lus(limiet=1, atr=2.0):
    c = object.__new__(GoldScalperCoordinator)
    c.strategy_cfg = SimpleNamespace(max_positions_per_richting=limiet)
    c.state = SimpleNamespace(atr=SimpleNamespace(value=atr))
    c._geopend_deze_cyclus = []
    return c


def _pos(ticket, side, prijs, stop):
    return SimpleNamespace(ticket=ticket, side=side, open_price=prijs, stop_loss=stop)


def test_beschermde_positie_telt_mee_voor_de_limiet():
    c = _lus(limiet=1)
    # Live 23-10 06:10: short 4017,38 met de stop op 4017,13 (voorbij de
    # instap: beschermd). Een tweede short van een andere opzet mag niet.
    beschermd = _pos("58763992", "sell", 4017.38, 4017.13)
    reden = c._grendel_richting(-1, 4016.51, [beschermd], [])
    assert reden and reden.startswith("limiet per richting: 1 van 1 short")
    assert c._grendel_richting(1, 4016.80, [beschermd], []) is None


def test_orders_onderweg_en_van_deze_cyclus_tellen_mee():
    c = _lus(limiet=3)
    pending = [SimpleNamespace(side="sell")]
    c._geopend_deze_cyclus = [(-1, "111", 4017.0), (-1, None, 4016.0)]
    assert c._telling_richting([], pending)[-1] == 3
    assert c._grendel_richting(-1, None, [], pending)
    # Staat de order van deze cyclus al in de lijst, dan niet dubbel tellen.
    c._geopend_deze_cyclus = [(-1, "111", 4017.0)]
    telling = c._telling_richting([_pos("111", "sell", 4017.0, 4020.0)], [])
    assert telling[-1] == 1


def test_tien_shorts_van_tien_opzetten_kan_niet_meer():
    c = _lus(limiet=1)
    open_ = []
    geopend = 0
    for i in range(10):
        # Elke opzet heeft zijn eigen lijst leeg (2.1.0 telde per strategie);
        # de grendel kijkt naar alles samen plus wat deze cyclus uitging.
        if c._grendel_richting(-1, 4017.0 + i, open_, [], eigen=[]) is None:
            c._geopend_deze_cyclus.append((-1, str(i), 4017.0 + i))
            geopend += 1
    assert geopend == 1


def test_geen_dubbele_order_op_dezelfde_prijs_van_een_andere_strategie():
    c = _lus(limiet=5, atr=2.0)
    ander = _pos("1", "sell", 4171.43, 4175.0)
    reden = c._grendel_richting(-1, 4171.43, [ander], [], eigen=[])
    assert reden and reden.startswith("dubbele order")
    # Een positie van de eigen strategie laat de grendel aan de spreiding over.
    assert c._grendel_richting(-1, 4171.43, [ander], [], eigen=[ander]) is None
    # Ver genoeg weg: geen dubbele order.
    assert c._grendel_richting(-1, 4175.0, [ander], [], eigen=[]) is None
    # Een order van deze cyclus (nog niet in de lijst) telt ook als prijs.
    c._geopend_deze_cyclus = [(-1, "9", 4180.00)]
    assert c._grendel_richting(-1, 4180.05, [ander], [], eigen=[]).startswith("dubbele")


def test_lus_en_open_position_gebruiken_de_grendel():
    bron = _lees("coordinator.py")
    assert "eigen_richting = self._telling_richting(open_positions, pending)" in bron
    assert "limiet_reden := self._grendel_richting(" in bron
    assert "reden = self._grendel_richting(richting, None, verse, verse_pending)" in bron
    assert "self._geopend_deze_cyclus.append((richting, geopend_ticket, entry_price))" in bron


# --------------------------------------------------------------------------- #
# 9. Saldosprong op papier
# --------------------------------------------------------------------------- #

T0 = datetime(2026, 10, 22, 23, 0, tzinfo=timezone.utc)


def test_nieuwe_run_op_papier_is_geen_saldosprong():
    b = SaldoSprongBewaker(naam="BILL-EUR")
    b.referentie = 7634.71          # bewaard uit de vorige run
    b.meet(T0, 10000.0, positie_open=False, sluitingen=0, papier=True)
    assert not b.actief and b.referentie == 10000.0
    b.meet(T0 + timedelta(minutes=47), 8994.99, positie_open=False, sluitingen=0,
           papier=True)
    assert not b.actief and b.referentie == 8994.99
    assert b.betrouwbaar(9024.77) == 9024.77


def test_bewaarde_sprong_vervalt_op_papier():
    b = SaldoSprongBewaker(naam="BILL-EUR")
    b.herstel({"referentie": 7634.71, "sprong_waarde": 10000.0,
               "sprong_sinds": T0.isoformat(), "reden": "oud"})
    assert b.actief
    b.meet(T0 + timedelta(minutes=5), 9024.77, positie_open=True, sluitingen=3,
           papier=True)
    assert not b.actief and b.referentie == 9024.77


def test_verklaarde_verandering_tijdens_sprong_is_geen_nieuwe_sprong():
    b = SaldoSprongBewaker(naam="X")
    b.referentie = 7634.71
    b.meet(T0, 10000.0, positie_open=False, sluitingen=0)
    assert b.actief and b.sprong_waarde == 10000.0
    sinds = b.sprong_sinds
    # Gewone handel: positie open, equity zakt 10,1 %.
    b.meet(T0 + timedelta(minutes=47), 8994.99, positie_open=True, sluitingen=0)
    assert b.actief and b.sprong_waarde == 8994.99 and b.sprong_sinds == sinds
    # Zonder verklaring is het wel een nieuwe gebeurtenis (zoals voorheen).
    b.meet(T0 + timedelta(hours=2), 5000.0, positie_open=False, sluitingen=0)
    assert b.sprong_waarde == 5000.0 and b.sprong_sinds != sinds


def test_saldosprong_noemt_de_markt():
    b = SaldoSprongBewaker(naam="PUMP-EUR")
    b.referentie = 10000.0
    b.meet(T0, 8000.0, positie_open=False, sluitingen=0)
    assert b.reden.startswith("PUMP-EUR: saldosprong zonder trade")


def test_lus_meldt_papier_en_mand_toont_saldosprong():
    bron = _lees("coordinator.py")
    assert "papier=self.paper is not None and not self.mode.places_orders" in bron
    mand = _lees("mand.py")
    assert '"saldosprong": [r["markt"] for r in rijen if r.get("saldosprong")]' in mand
    assert "def saldosprongen(self)" in mand
    assert "_mand_sprongen(self.coordinator)" in _lees("binary_sensor.py")


def test_mand_saldosprongen_van_leden():
    from gold_scalper.mand import BitvavoMand

    mand = object.__new__(BitvavoMand)
    actief = SaldoSprongBewaker(naam="BILL-EUR")
    actief.referentie = 10000.0
    actief.meet(T0, 8000.0, positie_open=False, sluitingen=0)
    rustig = SaldoSprongBewaker(naam="PEPE-EUR")
    mand.leden = {
        "BILL-EUR": SimpleNamespace(symbol="BILL-EUR", saldosprong=actief),
        "PEPE-EUR": SimpleNamespace(symbol="PEPE-EUR", saldosprong=rustig),
    }
    redenen = mand.saldosprongen()
    assert len(redenen) == 1 and redenen[0].startswith("BILL-EUR:")


# --------------------------------------------------------------------------- #
# 10. cTrader-tempo en deelstappen van de latency
# --------------------------------------------------------------------------- #

def _venue():
    v = object.__new__(ctrader.CTraderVenue)
    v._tempo_lock = asyncio.Lock()
    v._tempo_hist_lock = asyncio.Lock()
    v._laatst_verzoek = 0.0
    v._laatst_historisch = 0.0
    return v


def test_algemeen_verzoek_wacht_niet_achter_historische():
    async def run():
        v = _venue()
        momenten: dict = {}

        async def hist(i):
            await v._tempo(ctrader.DEAL_LIST_REQ)
            momenten[f"h{i}"] = time.monotonic()

        async def algemeen():
            await asyncio.sleep(0.01)
            start = time.monotonic()
            await v._tempo(ctrader.RECONCILE_REQ)
            momenten["alg"] = time.monotonic() - start

        begin = time.monotonic()
        await asyncio.gather(*(hist(i) for i in range(4)), algemeen())
        return begin, momenten

    begin, m = asyncio.run(run())
    # Vroeger: achter drie historische wachttijden (~1,2 s). Nu hooguit de
    # algemene afstand.
    assert m["alg"] < 0.2, m
    # De historische afstand blijft 0,4 s.
    h = sorted(m[f"h{i}"] for i in range(4))
    assert all(b - a >= ctrader.HISTORISCH_INTERVAL_S - 0.02 for a, b in zip(h, h[1:])), h


def test_deelstappen_gemeten_en_zichtbaar():
    bron = _lees("coordinator.py")
    for stap in ("posities", "afwikkelen", "correctie", "veldproefbars", "beheer",
                 "schaduw", "rooster_audit", "saldo", "onbevestigd_posities",
                 "voorbereiding", "signal"):
        assert f'self._deel.mark("{stap}")' in bron, stap
    assert "self.latency_deel.record(self._deel)" in bron
    assert '"latency_deelstappen": self.latency_deel.stats()' in bron
    assert '"deelstappen": d.get("latency_deelstappen") or {}' in _lees("sensor.py")


# --------------------------------------------------------------------------- #
# 11. Markt bij 'Openen geweigerd (papermarge)'
# --------------------------------------------------------------------------- #

def test_papermarge_noemt_de_markt():
    bron = _lees("coordinator.py")
    assert ('_LOGGER.warning("Openen geweigerd (papermarge) op %s: %s", '
            'self.symbol, err)') in bron
    assert 'self._laatste_weigering = f"papermarge: {err}"' in bron
