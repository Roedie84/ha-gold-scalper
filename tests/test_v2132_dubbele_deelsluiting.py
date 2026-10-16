"""2.13.2: een tweede deelsluiting legde de Pepperstone-entry stil.

16-10 09:53 en 12:58: "UNIQUE constraint failed: trades.broker_ticket,
trades.mode" in _record_partial; setup_error, en omdat het deel pas na het
boeken als genomen telde, werd het na elke herstart opnieuw gesloten.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402

NU = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)


def _db(tmp_path):
    db = TradeDatabase(tmp_path / "t.db")
    db.connect()
    run = db.start_run("demo", "v1", "XAUUSD", {}, 10000.0, None, "fp")
    t = Trade(run_id=run, mode="demo", symbol="XAUUSD", side="buy", volume=0.5,
              open_time="2026-10-16T09:00:00+00:00", open_price=4180.0, open_mid=4179.9, open_spread=0.2,
              broker_ticket="58396925")
    db.insert_trade(t)
    return db, t


def _zelf(db):
    from gold_scalper.coordinator import GoldScalperCoordinator as C

    async def uitvoeren(fn, *a):
        return fn(*a)
    zelf = SimpleNamespace(
        db=db, hass=SimpleNamespace(async_add_executor_job=uitvoeren),
        _last_quote=SimpleNamespace(bid=4190.0, ask=4190.2, mid=4190.1, spread=0.2),
        mode=SimpleNamespace(value="demo"), _excursions={},
        risk=SimpleNamespace(record_close=lambda *a, **k: None),
        _commissie=lambda u: 0.0, _telt_voor_reeks=lambda t: True,
    )

    async def open_trade(ticket):
        rijen = db.open_trades_by_tickets([ticket])
        return rijen[0] if rijen else None
    zelf._open_trade_by_ticket = open_trade
    return C, zelf


def test_tweede_deel_wordt_opgeteld(tmp_path):
    db, t = _db(tmp_path)
    C, zelf = _zelf(db)
    asyncio.run(C._record_partial(zelf, "58396925", 25.0, "doel 1", NU))
    asyncio.run(C._record_partial(zelf, "58396925", 12.0, "herhaald", NU))
    deel = db.deel_van("58396925")
    assert abs(deel.volume * 100 - 37.0) < 1e-6
    assert abs(db.open_trades_by_tickets(["58396925"])[0].volume * 100 - 13.0) < 1e-6
    assert db.deel_tickets_open() == {"58396925"}


def test_deel_tickets_alleen_open_posities(tmp_path):
    db, t = _db(tmp_path)
    C, zelf = _zelf(db)
    asyncio.run(C._record_partial(zelf, "58396925", 25.0, "doel 1", NU))
    t2 = db.open_trades_by_tickets(["58396925"])[0]
    t2.close_time = NU.isoformat()
    db.update_trade(t2)
    assert db.deel_tickets_open() == set()


def test_deel_genomen_voor_het_boeken():
    from pathlib import Path
    src = (Path(__file__).parent.parent / "custom_components" / "gold_scalper" / "coordinator.py").read_text()
    i = src.index("deel = await self.venue.close(ticket, units)")
    j = src.index("await self._record_partial(", i)
    assert "self._partial_taken.add(ticket)" in src[i:j]


def test_mislukte_insert_laat_geen_vergrendeling_achter(tmp_path):
    import sqlite3
    import pytest
    db, t = _db(tmp_path)
    dubbel = Trade(run_id=t.run_id, mode="demo", symbol="XAUUSD", side="buy", volume=0.1,
                   open_time=t.open_time, open_price=1.0, open_mid=1.0, open_spread=0.1,
                   broker_ticket="58396925")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_trade(dubbel)
    ander = sqlite3.connect(tmp_path / "t.db", timeout=0.2)
    ander.execute("UPDATE trades SET symbol='XAUUSD'")
    ander.commit()
