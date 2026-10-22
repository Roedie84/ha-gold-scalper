"""2.20.0 - afstemming: broker-uitstap overnemen, sluitreden uit de prijs, latency.

Akkoord Ruud 22-10 16:45:

1. Een trade die eenduidig bij de broker gevonden is (positienummer, of instap
   op de cent met hetzelfde openingsmoment, en door geen andere eigen trade
   geclaimd) krijgt de uitstapprijs en het resultaat van de broker; de
   afstemming is daarna in orde. Niet gevonden trades blijven onaangeroerd.
2. Sluitreden onbekend wordt achteraf ingevuld door de uitstapprijs van de
   broker naast stop en doel te leggen (Pepperstone heeft geen
   activiteitenoverzicht: 433 van 1.681 onbekend, 0 ingevuld).
3. De periodieke afstemming loopt op de achtergrond in plaats van in de
   cyclus (p99 candles->exits 32 s).
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))
sys.path.insert(0, HIER)

from gold_scalper.learning.afstemming import stem_af  # noqa: E402
from gold_scalper.learning.exit_stats import exit_stats  # noqa: E402
from gold_scalper.learning.sluitreden import reden_uit_broker, reden_uit_prijs  # noqa: E402
from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402

PKG = Path(HIER).parent / "custom_components" / "gold_scalper"
NU = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)


def _trade(ticket="58720162", **kw):
    velden = dict(
        id=1, run_id=1, mode="demo", symbol="XAUUSD", side="buy", volume=0.03,
        open_time=(NU - timedelta(hours=3)).isoformat(), open_price=4095.82,
        open_mid=4095.8, open_spread=0.1, stop_loss=4090.0, take_profit=4110.0,
        close_time=(NU - timedelta(hours=2)).isoformat(), close_price=4100.28,
        net_pnl=13.38, total_cost=0.2, broker_ticket=ticket,
        close_reason="eigen_exit", cost_source="measured",
    )
    velden.update(kw)
    return Trade(**velden)


def _tx(deal="58720162", open_level=4095.82, close_level=4100.14, size="+3",
        open_dt=None, close_dt=None, pnl=12.96, ref="d1"):
    return {
        "reference": ref, "dealId": deal, "openLevel": open_level,
        "closeLevel": close_level, "size": size,
        "openDateUtc": open_dt or (NU - timedelta(hours=3)).isoformat(),
        "dateUtc": close_dt or (NU - timedelta(hours=2)).isoformat(),
        "profitAndLoss": pnl, "currency": "USD",
        "instrumentName": "XAUUSD converted at 1",
    }


# 1. Uitstapprijs van de broker overnemen -----------------------------------


def test_eenduidig_op_positienummer_neemt_uitstap_en_resultaat_over():
    # Omvang 3 oz bij de broker tegen 3,00 eigen... maar instap een tiende
    # anders: geen sterke koppeling, wel hetzelfde positienummer.
    t = _trade(open_price=4095.84)
    u = stem_af([t], [_tx(open_level=4095.82)], 1.0, NU, 100.0)
    assert u.in_orde and u.eenduidig_overgenomen == 1
    (o,) = u.overnames
    assert o["velden"]["close_price"] == 4100.14
    assert "UNIQUE_MATCH" in o["velden"]["exit_price_provenance"]
    assert o["velden"]["net_pnl_account"] == 12.96


def test_ig_deelsluiting_op_instap_en_opentijd_wordt_overgenomen():
    # Gemeten 22-10 (IG): rest van een deelsluiting, eigen uitstap gekopieerd
    # van de deelsluiting (4154.07), bij de broker op de stop 4150.96; de
    # broker sloot hele ounces (3 tegen 2,675) - daarom geen sterke koppeling.
    t = _trade(ticket="DIAAAAYNQ2B4TA8", open_price=4143.62, volume=0.02675,
               close_price=4154.07, net_pnl=27.9036, stop_loss=4150.96,
               take_profit=4162.48)
    tx = _tx(deal=None, ref="ABC", open_level=4143.62, close_level=4150.96,
             size="+3", pnl=17.39)
    tx["instrumentName"] = "Spot Gold converted at 0.8600"
    u = stem_af([t], [tx], 0.86, NU, 100.0)
    assert u.in_orde, u.as_dict()
    v = u.overnames[0]["velden"]
    assert v["close_price"] == 4150.96
    assert v["net_pnl_account"] == 17.39
    assert v["volume"] == 0.03


def test_twee_trades_op_een_transactie_blijven_een_afwijking():
    a = _trade(id=1, open_price=4095.84)
    b = _trade(id=2, open_price=4095.85, volume=0.03)
    u = stem_af([a, b], [_tx(open_level=4095.82)], 1.0, NU, 100.0)
    assert u.eenduidig_overgenomen == 0
    assert not u.in_orde
    assert all("close_price" not in o["velden"] for o in u.overnames)


def test_alleen_op_prijs_gekoppeld_is_niet_eenduidig():
    t = _trade(ticket="ANDERS", open_price=4095.84)
    tx = _tx(deal="99", open_level=4095.82)
    tx.pop("openDateUtc")
    u = stem_af([t], [tx], 1.0, NU, 100.0)
    assert u.eenduidig_overgenomen == 0 and not u.in_orde


def test_niet_gevonden_trade_blijft_onaangeroerd():
    oud = _trade(close_time=(NU - timedelta(days=7.8)).isoformat(),
                 open_time=(NU - timedelta(days=7.9)).isoformat(), open_price=4093.48)
    u = stem_af([oud], [_tx(deal="ander", open_level=4000.0)], 1.0, NU, 100.0)
    assert u.overnames == []
    assert [a.soort for a in u.afwijkingen] == ["ontbreekt"]


# 2. Sluitreden uit de prijs ------------------------------------------------


def _broker(**kw):
    return SimpleNamespace(**{**dict(
        side="buy", stop_loss=4090.0, take_profit=4110.0, entry_atr=2.5,
        close_reason="broker_gesloten_gemeten",
        original_close_reason="broker_gesloten_gemeten"), **kw})


def test_stop_met_slippage_is_stop():
    assert reden_uit_prijs(_broker(), 4089.23).reden == "stop_loss"     # 0,77 slechter
    assert reden_uit_prijs(_broker(side="sell", stop_loss=4100.0), 4100.3).reden == "stop_loss"


def test_doel_als_limietorder_op_of_voorbij():
    assert reden_uit_prijs(_broker(), 4110.0).reden == "take_profit"
    assert reden_uit_prijs(_broker(), 4110.2).reden == "take_profit"


def test_geen_bewijs_blijft_onbekend():
    assert reden_uit_prijs(_broker(), 4090.5) is None                   # gunstiger dan de stop
    assert reden_uit_prijs(_broker(), 4085.0) is None                   # te ver
    assert reden_uit_prijs(_broker(close_reason="eigen_exit",
                                   original_close_reason="eigen_exit"), 4090.0) is None


def test_zonder_brokerprijs_geen_reden():
    t = _broker()
    assert reden_uit_broker(t, 4090.0, None, 240, 900, None,
                            uitstap_van_broker=False) is None
    assert reden_uit_broker(t, 4090.0, None, 240, 900, None).reden == "stop_loss"


class _AlleenTransacties:
    """Broker zoals cTrader: transactieoverzicht, geen activiteitenoverzicht."""

    def __init__(self, tx):
        self.tx = tx

    async def transactions(self, van, tot):
        return self.tx


def test_coordinator_vult_alle_onbekende_in_zonder_activiteit(tmp_path, monkeypatch):
    from test_broker_cycle import _coordinator

    c, _ = _coordinator(_AlleenTransacties([]), tmp_path, monkeypatch)
    nu = datetime.now(timezone.utc)
    trades, tx = [], []
    for i in range(14):                                       # meer dan 10
        open_t = nu - timedelta(hours=5, minutes=i)
        t = Trade(run_id=c.run_id, mode="demo", symbol="XAUUSD", side="buy",
                  volume=0.01, open_time=open_t.isoformat(), open_price=4000.0 + i,
                  open_mid=4000.0 + i, open_spread=0.1,
                  stop_loss=3995.0 + i, take_profit=4010.0 + i,
                  close_time=(open_t + timedelta(minutes=3)).isoformat(),
                  close_price=3994.8 + i, net_pnl=-5.2, total_cost=0.1,
                  broker_ticket=str(1000 + i),
                  close_reason="broker_gesloten_gemeten",
                  original_close_reason="broker_gesloten_gemeten",
                  reconciled_close_reason="unknown", reconciliation_status="reconciled",
                  cost_source="measured")
        c.db.insert_trade(t)
        tx.append(_tx(deal=str(1000 + i), ref=f"r{i}", open_level=4000.0 + i,
                      close_level=3994.8 + i, size="+1",
                      open_dt=open_t.isoformat(),
                      close_dt=(open_t + timedelta(minutes=3)).isoformat(), pnl=-5.2))
    c.venue = _AlleenTransacties(tx)

    from test_v1100 import GeheugenOpslag
    c._results_store = GeheugenOpslag()
    uitslag = asyncio.run(c.async_reconcile())
    assert uitslag["sluitreden_ingevuld"] == 14
    stats = exit_stats(c.db.closed_trades(c.run_id))
    assert stats["unknown"]["n"] == 0 and stats["stop_loss"]["n"] == 14
    assert stats["achteraf_ingevuld"] == 14


def test_velden_bijwerken_raakt_de_rest_niet(tmp_path):
    db = TradeDatabase(tmp_path / "t.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    t = _trade(id=None, run_id=run, close_reason="broker_gesloten_gemeten",
               original_close_reason="broker_gesloten_gemeten")
    db.insert_trade(t)
    db.update_trade_velden(t.id, {"close_price": 4100.14, "onbekend_veld": 1,
                                  "original_close_reason": "iets_anders"})
    (o,) = db.closed_trades(run)
    assert o.close_price == 4100.14
    assert o.net_pnl == 13.38                                  # ongemoeid
    assert o.original_close_reason == "broker_gesloten_gemeten"  # nooit overschreven


# 3. Afstemming op de achtergrond ------------------------------------------


def test_cyclus_wacht_niet_op_de_afstemming():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    i = bron.index('budget.mark("candles")')
    j = bron.index('budget.mark("exits")')
    stuk = bron[i:j]
    assert "await self.async_reconcile()" not in stuk
    assert "self._start_afstemming_op_achtergrond()" in stuk


def test_achtergrond_afstemming_een_tegelijk_en_duur():
    from gold_scalper.coordinator import GoldScalperCoordinator as C

    async def scenario():
        klaar = asyncio.Event()
        c = SimpleNamespace(symbol="XAUUSD", reconciliation={},
                            _afstemming_bezig=False, _afstemming_taak=None)
        c.hass = SimpleNamespace(async_create_task=asyncio.ensure_future)
        c.entry = SimpleNamespace()

        async def reconcile():
            await klaar.wait()
            c.reconciliation = {"in_orde": True}
            return c.reconciliation

        c.async_reconcile = reconcile
        assert C._start_afstemming_op_achtergrond(c) is True
        assert C._start_afstemming_op_achtergrond(c) is False     # loopt al
        klaar.set()
        await c._afstemming_taak
        assert "duur_s" in c.reconciliation
        assert C._start_afstemming_op_achtergrond(c) is True
        await c._afstemming_taak

    asyncio.run(scenario())
