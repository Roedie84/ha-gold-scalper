"""2.7.0: verbeterplan fase 1 - execution ledger, afstemming, risicolimieten."""
from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker import uitvoering as U  # noqa: E402
from gold_scalper.broker.adapter import OrderResult  # noqa: E402
from gold_scalper.broker.reconcile_audit import compare_positions  # noqa: E402
from gold_scalper.modes import LiveGate  # noqa: E402
from gold_scalper.strategy import posities as P  # noqa: E402

T0 = datetime(2026, 10, 14, 7, 0, 0, tzinfo=timezone.utc)
BASIS = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")


# --- execution ledger ------------------------------------------------------ #

def _rij(tick=None, result=None):
    return U.ledger_rij(
        run_id=7, strategie="vp:pullback:15m", side="buy", units_gevraagd=12.0,
        signaal_ts=T0, signaal_bid=4150.0, signaal_ask=4150.6,
        koers_ts=T0 - timedelta(seconds=2), candle_ts=T0 - timedelta(seconds=40),
        verzend_ts=T0 + timedelta(milliseconds=120), tick=tick,
        bevestiging_ts=T0 + timedelta(milliseconds=620), result=result,
        stop_loss=4142.0, take_profit=4166.0,
    )


def test_ledger_gemeten_met_live_tick():
    res = OrderResult(success=True, ticket="DIAAA1", fill_price=4150.9,
                      requested_price=4150.7, units=12.0, latency_ms=480.0)
    rij = _rij(tick=(T0.timestamp() + 0.1, 4150.1, 4150.7), result=res)
    h = rij["herkomst"]
    assert rij["verzend_ask"] == 4150.7 and h["verzend_ask"] == U.GEMETEN
    assert rij["latentie_signaal_order_ms"] == 120.0
    assert rij["latentie_order_fill_ms"] == 500.0
    assert rij["koers_leeftijd_s"] == 2.0 and rij["candle_leeftijd_s"] == 40.0
    assert abs(rij["slippage_usd"] - 0.2) < 1e-9 and h["slippage_usd"] == U.BEREKEND
    assert rij["fill_prijs"] == 4150.9 and h["fill_prijs"] == U.BROKER
    assert rij["resultaat"] == "gevuld" and rij["broker_ticket"] == "DIAAA1"


def test_ledger_zonder_tick_is_geschat_niet_gemeten():
    res = OrderResult(success=True, ticket="X", fill_price=4150.9, units=12.0)
    rij = _rij(tick=None, result=res)
    assert rij["herkomst"]["verzend_ask"] == U.GESCHAT
    assert rij["gevraagde_prijs"] == 4150.6
    assert rij["herkomst"]["gevraagde_prijs"] == U.GESCHAT


def test_ledger_oude_tick_telt_niet():
    rij = _rij(tick=(T0.timestamp() - 30, 4140.0, 4140.6), result=None)
    assert rij["verzend_bid"] == 4150.0 and rij["herkomst"]["verzend_bid"] == U.GESCHAT


def test_ledger_ontbrekend_expliciet():
    rij = U.ledger_rij(run_id=1, strategie=None, side="sell", units_gevraagd=None,
                       signaal_ts=T0, signaal_bid=None, signaal_ask=None, koers_ts=None,
                       candle_ts=None, verzend_ts=None, tick=None, bevestiging_ts=None,
                       result=OrderResult(success=False, error="afgewezen"))
    h = rij["herkomst"]
    assert h["signaal_bid"] == U.ONTBREEKT and h["latentie_order_fill_ms"] == U.ONTBREEKT
    assert rij["resultaat"] == "afgewezen"


def test_ledger_in_database(tmp_path):
    from gold_scalper.storage.database import TradeDatabase
    db = TradeDatabase(str(tmp_path / "gs.db"))
    db.connect()
    res = OrderResult(success=True, ticket="T1", fill_price=4150.9, units=12.0)
    db.log_uitvoering(_rij(result=res))
    rijen = db.uitvoeringen(7)
    assert len(rijen) == 1 and rijen[0]["broker_ticket"] == "T1"
    assert '"fill_prijs": "broker"' in rijen[0]["herkomst"]


# --- afstemming ------------------------------------------------------------ #

@dataclass
class _Pos:
    ticket: str
    side: str
    units: float
    open_price: float
    stop_loss: float = 4100.0
    take_profit: float = 4200.0


def test_instapprijs_wordt_vergeleken():
    trade = SimpleNamespace(broker_ticket="A", volume=0.1, stop_loss=4100.0,
                            take_profit=4200.0, side="buy", open_price=4150.0)
    audit = compare_positions([_Pos("A", "buy", 10.0, 4150.4)], [trade])
    assert any(f.code == "instap_verschilt" for f in audit.findings)
    audit = compare_positions([_Pos("A", "buy", 10.0, 4150.0)], [trade])
    assert not any(f.code == "instap_verschilt" for f in audit.findings)


def _geslaagde_poort(boekhouding):
    from datetime import date
    stats = {"trades": 600, "ready_for_live": True, "costs_included": True, "total_pnl": 100}
    run = {"started_at": "2026-08-01T00:00:00+00:00", "config_json": "{}"}
    daily = [{"day": str(date(2026, 8, 1) + timedelta(days=i)), "trades": 20, "pnl": 5.0}
             for i in range(40)]
    return LiveGate().evaluate(stats, run, daily, {"verdict": "houdbaar"}, boekhouding)


def test_live_poort_eist_kloppende_boekhouding():
    assert not _geslaagde_poort(None).checks["boekhouding_klopt_met_broker"]
    assert not _geslaagde_poort({"afwijkingen": 2, "kritiek_open": 0}).checks[
        "boekhouding_klopt_met_broker"]
    assert _geslaagde_poort({"afwijkingen": 0, "kritiek_open": 0}).checks[
        "boekhouding_klopt_met_broker"]


# --- risicolimieten -------------------------------------------------------- #

def _p(side, units, instap, stop):
    return SimpleNamespace(side=side, units=units, open_price=instap, stop_loss=stop)


def test_cluster_limiet():
    ok, reden, info = P.risicolimieten_ok(
        richting=-1, nieuw_risico=100, nieuw_notional=1000, open_posities=[],
        koers=4150, equity_ref=1_000_000,
        recente_instappen=[(1000.0, -1), (1060.0, -1), (1100.0, -1)], nu_ts=1200.0)
    assert not ok and reden.startswith("cluster") and info["cluster"] == 3
    ok, _r, _i = P.risicolimieten_ok(
        richting=1, nieuw_risico=100, nieuw_notional=1000, open_posities=[],
        koers=4150, equity_ref=1_000_000,
        recente_instappen=[(1000.0, -1), (1060.0, -1), (1100.0, -1)], nu_ts=1200.0)
    assert ok


def test_risico_per_richting_en_totaal():
    open_ = [_p("sell", 100, 4150.0, 4160.0)] * 2   # 2 x 1000 USD risico short
    ok, reden, _i = P.risicolimieten_ok(
        richting=-1, nieuw_risico=1500, nieuw_notional=1000, open_posities=open_,
        koers=4150, equity_ref=1_000_000)
    assert not ok and "richting" in reden            # 3500 > 3000
    ok, _r, _i = P.risicolimieten_ok(
        richting=1, nieuw_risico=1500, nieuw_notional=1000, open_posities=open_,
        koers=4150, equity_ref=1_000_000)
    assert ok                                         # long: 1500 < 3000, totaal 3500 < 5000


def test_break_even_telt_niet_als_risico():
    open_ = [_p("sell", 10, 4150.0, 4150.0)] * 10
    ok, _r, info = P.risicolimieten_ok(
        richting=-1, nieuw_risico=100, nieuw_notional=1000, open_posities=open_,
        koers=4150, equity_ref=1_000_000)
    assert ok and info["richting_risico"] == 0


def test_notional():
    open_ = [_p("buy", 2000, 4150.0, 4150.0)]          # 8,3 mln
    ok, reden, _i = P.risicolimieten_ok(
        richting=1, nieuw_risico=10, nieuw_notional=2_000_000, open_posities=open_,
        koers=4150, equity_ref=1_000_000)
    assert not ok and reden.startswith("notional in deze richting")


def test_coordinator_gebruikt_alles():
    py = open(os.path.join(BASIS, "coordinator.py"), encoding="utf-8").read()
    assert 'return "risicolimiet", reden' in py
    assert "await self._log_uitvoering(" in py
    assert "self._boekhouding_status()" in py


def test_versie():
    from gold_scalper.const import INTEGRATION_VERSION
    assert tuple(map(int, INTEGRATION_VERSION.split("."))) >= tuple(map(int, "2.7.0".split(".")))


# --- P0: afstemming over alle pagina's ------------------------------------- #

def test_transacties_alle_paginas():
    import asyncio
    from gold_scalper.broker import ig_capital as IG

    venue = IG.IgVenue.__new__(IG.IgVenue)
    gevraagd = []

    async def _request(method, path, version=None, params=None, **_k):
        gevraagd.append(params["pageNumber"])
        n = params["pageNumber"]
        tx = [{"reference": f"{n}-{i}"} for i in range(IG.TRANSACTIE_PAGINA if n < 3 else 7)]
        return {"transactions": tx, "metadata": {"pageData": {"pageNumber": n, "totalPages": 3}}}

    venue._request = _request
    t = asyncio.run(venue.transactions(T0 - timedelta(days=3), T0))
    assert gevraagd == [1, 2, 3]
    assert len(t) == 2 * IG.TRANSACTIE_PAGINA + 7


def test_transacties_zonder_metadata_stopt_bij_korte_pagina():
    import asyncio
    from gold_scalper.broker import ig_capital as IG

    venue = IG.IgVenue.__new__(IG.IgVenue)
    gevraagd = []

    async def _request(method, path, version=None, params=None, **_k):
        gevraagd.append(params["pageNumber"])
        return {"transactions": [{"reference": "x"}] * 3}

    venue._request = _request
    assert len(asyncio.run(venue.transactions(T0 - timedelta(days=1), T0))) == 3
    assert gevraagd == [1]


def test_oudste_niet_afgestemd(tmp_path):
    from gold_scalper.storage.database import TradeDatabase
    db = TradeDatabase(str(tmp_path / "gs.db"))
    db.connect()
    db.conn.execute("PRAGMA foreign_keys=OFF")
    db.conn.execute(
        "INSERT INTO trades (run_id, mode, symbol, side, volume, open_time, open_price, "
        "open_mid, open_spread, close_time, close_price, broker_ticket) VALUES "
        "(1,'demo','X','buy',0.1,'2026-10-08T10:00:00+00:00',4000,4000,0.6,"
        "'2026-10-08T10:05:00+00:00',4001,'T1')")
    db.conn.commit()
    assert db.oudste_niet_afgestemd("demo", "2026-10-04T00:00:00+00:00").startswith("2026-10-08")
    assert db.oudste_niet_afgestemd("demo", "2026-10-09T00:00:00+00:00") is None


# --- P0: afstemming over alle pagina's ------------------------------------- #

def test_transacties_alle_paginas():
    import asyncio
    from gold_scalper.broker import ig_capital as IG

    venue = IG.IgVenue.__new__(IG.IgVenue)
    gevraagd = []

    async def _request(method, path, version=None, params=None, **_k):
        gevraagd.append(params["pageNumber"])
        n = params["pageNumber"]
        tx = [{"reference": f"{n}-{i}"} for i in range(IG.TRANSACTIE_PAGINA if n < 3 else 7)]
        return {"transactions": tx, "metadata": {"pageData": {"pageNumber": n, "totalPages": 3}}}

    venue._request = _request
    t = asyncio.run(venue.transactions(T0 - timedelta(days=3), T0))
    assert gevraagd == [1, 2, 3]
    assert len(t) == 2 * IG.TRANSACTIE_PAGINA + 7


def test_transacties_zonder_metadata_stopt_bij_korte_pagina():
    import asyncio
    from gold_scalper.broker import ig_capital as IG

    venue = IG.IgVenue.__new__(IG.IgVenue)
    gevraagd = []

    async def _request(method, path, version=None, params=None, **_k):
        gevraagd.append(params["pageNumber"])
        return {"transactions": [{"reference": "x"}] * 3}

    venue._request = _request
    assert len(asyncio.run(venue.transactions(T0 - timedelta(days=1), T0))) == 3
    assert gevraagd == [1]


def test_oudste_niet_afgestemd(tmp_path):
    from gold_scalper.storage.database import TradeDatabase
    db = TradeDatabase(str(tmp_path / "gs.db"))
    db.connect()
    db.conn.execute("PRAGMA foreign_keys=OFF")
    db.conn.execute(
        "INSERT INTO trades (run_id, mode, symbol, side, volume, open_time, open_price, "
        "open_mid, open_spread, close_time, close_price, broker_ticket) VALUES "
        "(1,'demo','X','buy',0.1,'2026-10-08T10:00:00+00:00',4000,4000,0.6,"
        "'2026-10-08T10:05:00+00:00',4001,'T1')")
    db.conn.commit()
    assert db.oudste_niet_afgestemd("demo", "2026-10-04T00:00:00+00:00").startswith("2026-10-08")
    assert db.oudste_niet_afgestemd("demo", "2026-10-09T00:00:00+00:00") is None
