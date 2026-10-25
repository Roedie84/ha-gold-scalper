"""2.22.2 - het grootboek van de Bitvavo-mand.

Live 23-25 oktober: de sensoren van de mand (BTC-EUR) stonden op 0 trades en
equity 10000, terwijl PEPE-EUR (163 trades, -1242,87), PUMP-EUR (221, -2941,44),
BILL-EUR (152, -1807,21) en PTB-EUR (4, -44,63) wel gehandeld hadden. Die trades
stonden gewoon in de eigen database van elk mandlid, maar de sensoren lazen
alleen de hoofdlus, en een markt die de mand verliet (spreadgrens 0,03 %)
verdween helemaal uit beeld.

Deze tests volgen de hele keten voor een mand met meerdere leden: openen,
sluiten, opslaan, herstarten (andere samenstelling) en de sensorwaarde.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.broker.paper import BrokerCosts, PaperBroker, Quote  # noqa: E402
from gold_scalper.const import INTEGRATION_VERSION  # noqa: E402
from gold_scalper.storage import performance  # noqa: E402
from gold_scalper.storage.database import TradeDatabase  # noqa: E402
from test_broker_cycle import FakeHass  # noqa: E402

VERSIE = "test-strategie"
T0 = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def _versie(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def test_versie_minstens_2_22_2():
    assert _versie(INTEGRATION_VERSION) >= (2, 22, 2)


def _q(mid: float, t: datetime) -> Quote:
    spread = mid * 0.0002          # 0,02 %, onder de spreadgrens van de mand
    return Quote(bid=mid - spread / 2, ask=mid + spread / 2, time=t, atr=0.0)


class Lid:
    """Een mandlid zoals de mand hem ziet: eigen database, run en papierbroker
    (de echte TradeDatabase en PaperBroker, geen nabootsing)."""

    def __init__(self, hass, markt: str) -> None:
        self.symbol = markt
        self.strategie_versie = VERSIE
        self.starting_balance = 10_000.0
        self.mode = SimpleNamespace(places_orders=False)
        self.venue = SimpleNamespace()
        self.db = TradeDatabase(hass.config.path(mand_mod.db_bestand(markt)))
        self.db.connect()
        bestaand = [r for r in self.db.list_runs() if r["symbol"] == markt]
        self.run_id = (int(bestaand[0]["id"]) if bestaand else
                       self.db.start_run("paper", VERSIE, markt, {}, self.starting_balance))
        kosten = BrokerCosts(commission_per_lot_per_side=0.0, commission_rate=0.0025,
                             base_slippage=0.0, volatility_slippage_factor=0.0,
                             size_slippage_per_lot=0.0, leverage=1.0)
        self.paper = PaperBroker(self.db, self.run_id, markt, self.starting_balance,
                                 kosten, seed=1)
        gesloten = self.db.closed_trades(self.run_id)
        self.paper.balance = self.starting_balance + sum(t.net_pnl or 0 for t in gesloten)
        self.data: dict = {}
        self.ververs()

    def _laatste_papieren_run(self):
        return self.run_id

    def handel(self, n: int, prijs: float, stap: float, units: float) -> None:
        """n round trips: koop op ``prijs``, sluit op ``prijs + stap``."""
        for i in range(n):
            t = T0 + timedelta(minutes=10 * i)
            trade = self.paper.open_position("buy", units, _q(prijs, t))
            self.paper.close_position(trade, _q(prijs + stap, t + timedelta(minutes=5)), "test")
        self.ververs()

    def ververs(self, quote: Quote | None = None) -> None:
        """Wat de coordinator elke cyclus in ``data`` zet."""
        stats = performance.compute_for_run(self.db, self.run_id)
        equity = self.paper.equity(quote) if quote else self.paper.balance
        self.data = {"stats": stats, "equity": equity, "balance": self.paper.balance}

    def sluit(self) -> None:
        self.db.close()


def _entry():
    return SimpleNamespace(entry_id="ENTRY", data={}, options={})


def _mand(hass, hoofd, leden) -> mand_mod.BitvavoMand:
    m = mand_mod.BitvavoMand(hass, _entry(), hoofd)
    m.leden = {c.symbol: c for c in leden}
    m._gereed = True
    return m


class _Sensor:
    """De waarde zoals sensor.py hem berekent (sensor.py zelf importeert Home
    Assistant; de rekenregels staan los in mand.py, zie de statische toets)."""

    def __init__(self, key):
        self.key = key

    def value_fn(self, d):
        if self.key == "equity":
            return mand_mod.sensor_equity(d)
        return mand_mod.sensor_stats(d).get({"trades": "trades",
                                             "net_pnl": "net_pnl"}[self.key])

    def attrs_fn(self, d):
        if self.key == "equity":
            return mand_mod.sensor_equity_attrs(d)
        return mand_mod.sensor_trades_extra(d)


def _sensor(key: str):
    return _Sensor(key)


def test_sensor_py_gebruikt_de_mandregels():
    from pathlib import Path

    bron = (Path(__file__).parent.parent / "custom_components" / "gold_scalper"
            / "sensor.py").read_text()
    assert "return sensor_stats(d)" in bron           # trades, netto, oordeel, ...
    assert "value_fn=sensor_equity," in bron
    assert "attrs_fn=sensor_equity_attrs," in bron
    assert "**sensor_trades_extra(d)," in bron
    for key in ("trades", "net_pnl", "verdict", "win_rate", "profit_factor"):
        blok = bron[bron.index(f'key="{key}"'):]
        blok = blok[:blok.index("ScalperSensor(") if "ScalperSensor(" in blok else None]
        assert "_stats(d)" in blok, key


async def _sensordata(m) -> dict:
    """Zoals de hoofdlus zijn data opbouwt (coordinator, 2.22.2)."""
    h = m.hoofd
    return {**h.data, "mand_boek": m.grootboek(), "mand_stats": await m.statistiek()}


def test_bestandsnaam_heen_en_terug(tmp_path):
    assert mand_mod.db_bestand("PEPE-EUR") == "gold_scalper_bitvavo_pepe_eur.db"
    assert mand_mod.markt_uit_bestand("gold_scalper_bitvavo_pepe_eur.db") == "PEPE-EUR"
    assert mand_mod.markt_uit_bestand("/config/gold_scalper_bitvavo_1inch_eur.db") == "1INCH-EUR"
    assert mand_mod.markt_uit_bestand("gold_scalper_ctrader.db") is None
    for naam in ("gold_scalper_bitvavo_btc_eur.db", "gold_scalper_bitvavo_pump_eur.db",
                 "gold_scalper.db", "gold_scalper_ctrader.db"):
        (tmp_path / naam).write_bytes(b"")
    assert mand_mod.ontdek_markten(str(tmp_path)) == ["BTC-EUR", "PUMP-EUR"]


def test_hele_keten_openen_sluiten_opslaan_herstart_sensor():
    hass = FakeHass()

    async def scenario():
        # --- sessie 1: BTC-EUR (hoofd, handelt niet), PEPE-EUR en PUMP-EUR ---
        hoofd = Lid(hass, "BTC-EUR")
        pepe = Lid(hass, "PEPE-EUR")
        pump = Lid(hass, "PUMP-EUR")
        pepe.handel(3, 0.000004, -0.0000001, 1_000_000.0)   # verlies
        pump.handel(5, 0.004, 0.0001, 1_000.0)               # winst
        m = _mand(hass, hoofd, [pepe, pump])

        boek = m.grootboek()
        assert boek["trades"] == 8
        pepe_netto = pepe.data["stats"]["net_pnl"]
        pump_netto = pump.data["stats"]["net_pnl"]
        assert pepe_netto < 0 < pump_netto
        assert boek["netto"] == pytest.approx(round(pepe_netto + pump_netto, 2), abs=0.01)
        assert boek["equity"] == pytest.approx(10_000 + pepe_netto + pump_netto, abs=0.01)
        per_markt = {r["markt"]: r for r in boek["per_markt"]}
        assert per_markt["PEPE-EUR"]["trades"] == 3
        assert per_markt["PUMP-EUR"]["trades"] == 5
        assert "BTC-EUR" not in per_markt          # geen trades, draait wel

        data = await _sensordata(m)
        assert _sensor("trades").value_fn(data) == 8
        assert _sensor("net_pnl").value_fn(data) == pytest.approx(pepe_netto + pump_netto,
                                                                  abs=0.01)
        assert _sensor("equity").value_fn(data) == pytest.approx(boek["equity"])
        attrs = _sensor("trades").attrs_fn(data)
        assert attrs["eigen_markt"] == 0
        assert {r["markt"] for r in attrs["per_markt"]} == {"PEPE-EUR", "PUMP-EUR"}
        assert _sensor("equity").attrs_fn(data)["equity_eigen_markt"] == 10_000.0

        # De poort/het oordeel gebruiken dezelfde trades.
        assert len(await m.alle_gesloten_trades()) == 8

        # Een open positie telt mee in de equity van de mand (niet in netto).
        q_open = _q(0.004, T0 + timedelta(hours=5))
        pump.paper.open_position("buy", 1_000.0, q_open)
        pump.ververs(_q(0.0041, T0 + timedelta(hours=5, minutes=1)))
        boek_open = m.grootboek()
        assert boek_open["trades"] == 8
        assert boek_open["netto"] == boek["netto"]
        assert boek_open["equity"] > boek["equity"]
        pump.paper.close_position(pump.paper.open_positions[0],
                                  _q(0.0041, T0 + timedelta(hours=5, minutes=2)), "test")
        pump.ververs()
        totaal_voor = m.grootboek()
        assert totaal_voor["trades"] == 9

        # --- herstart: alles dicht, PEPE en PUMP zitten niet meer in de mand ---
        for c in (hoofd, pepe, pump):
            c.sluit()
        hoofd2 = Lid(hass, "BTC-EUR")
        eth = Lid(hass, "ETH-EUR")
        m2 = _mand(hass, hoofd2, [eth])
        assert m2.grootboek()["trades"] == 0        # nog niet ingelezen
        await m2._laad_archief()
        boek2 = m2.grootboek()
        assert boek2["trades"] == totaal_voor["trades"] == 9
        assert boek2["netto"] == pytest.approx(totaal_voor["netto"], abs=0.01)
        assert boek2["equity"] == pytest.approx(totaal_voor["netto"] + 10_000, abs=0.01)
        buiten = {r["markt"]: r for r in boek2["per_markt"] if r["bron"] == "database"}
        assert buiten["PEPE-EUR"]["trades"] == 3
        assert buiten["PUMP-EUR"]["trades"] == 6

        data2 = await _sensordata(m2)
        assert _sensor("trades").value_fn(data2) == 9
        assert _sensor("net_pnl").value_fn(data2) == pytest.approx(totaal_voor["netto"],
                                                                   abs=0.01)
        assert _sensor("equity").value_fn(data2) == pytest.approx(boek2["equity"])
        overzicht = m2.overzicht()
        assert overzicht["totaal"]["trades"] == 9
        assert {r["markt"] for r in overzicht["buiten_mand"]} == {"PEPE-EUR", "PUMP-EUR"}
        assert len(await m2.alle_gesloten_trades()) == 9

        # --- PUMP-EUR komt terug in de mand: telt via zijn lus, niet dubbel ---
        pump2 = Lid(hass, "PUMP-EUR")
        assert pump2.paper.balance == pytest.approx(10_000 + buiten["PUMP-EUR"]["netto"],
                                                    abs=0.01)
        m2.leden["PUMP-EUR"] = pump2
        await m2._laad_archief()
        assert "PUMP-EUR" not in m2._archief
        assert m2.grootboek()["trades"] == 9
        pump2.handel(2, 0.004, 0.0001, 1_000.0)
        assert m2.grootboek()["trades"] == 11
        data3 = await _sensordata(m2)
        assert _sensor("trades").value_fn(data3) == 11   # statistiek ververst meteen
        for c in (hoofd2, eth, pump2):
            c.sluit()

    asyncio.run(scenario())


def test_gestopt_lid_wordt_opnieuw_uit_de_database_gelezen():
    hass = FakeHass()

    async def scenario():
        hoofd = Lid(hass, "BTC-EUR")
        bill = Lid(hass, "BILL-EUR")
        bill.handel(4, 0.0055, -0.0001, 1_000.0)
        m = _mand(hass, hoofd, [bill])
        await m._laad_archief()
        assert m._archief == {}
        # Het lid valt uit de mand (zoals _stop_als_plat -> _stop_lid).
        m.leden.pop("BILL-EUR")

        async def _niets(*a, **k):
            return None

        bill.async_shutdown = _niets
        bill.async_shutdown_hook = _niets
        bill.entry = SimpleNamespace(entry_id="ENTRY_bill-eur")
        await m._stop_lid("BILL-EUR", al_weg=bill)
        bill.sluit()
        assert "BILL-EUR" in m.ooit
        await m._laad_archief()
        assert m.grootboek()["trades"] == 4
        assert m.overzicht()["buiten_mand"][0]["markt"] == "BILL-EUR"
        hoofd.sluit()

    asyncio.run(scenario())


def test_ooit_wordt_bewaard():
    hass = FakeHass()

    class Store:
        def __init__(self):
            self.opgeslagen = None

        async def async_save(self, data):
            self.opgeslagen = data

    async def scenario():
        hoofd = Lid(hass, "BTC-EUR")
        pepe = Lid(hass, "PEPE-EUR")
        m = _mand(hass, hoofd, [pepe])
        m._store = Store()
        m.ooit.add("PTB-EUR")
        await m._bewaar()
        assert m._store.opgeslagen["ooit"] == ["BTC-EUR", "PEPE-EUR", "PTB-EUR"]
        hoofd.sluit()
        pepe.sluit()

    asyncio.run(scenario())


def test_andere_strategie_telt_niet_mee():
    hass = FakeHass()

    async def scenario():
        hoofd = Lid(hass, "BTC-EUR")
        oud = Lid(hass, "XLM-EUR")
        oud.handel(2, 0.15, 0.001, 10.0)
        oud.db.conn.execute("UPDATE runs SET strategy_version='oud'")
        oud.db.conn.commit()
        oud.sluit()
        m = _mand(hass, hoofd, [])
        await m._laad_archief()
        assert m.grootboek()["trades"] == 0
        hoofd.sluit()

    asyncio.run(scenario())


def test_sensor_zonder_mand_ongewijzigd():
    data = {"stats": {"trades": 7, "net_pnl": 12.5}, "equity": 10012.5, "balance": 10012.5}
    assert _sensor("trades").value_fn(data) == 7
    assert _sensor("equity").value_fn(data) == 10012.5
    assert "per_markt" not in _sensor("trades").attrs_fn(data)
    assert _sensor("equity").attrs_fn(data) == {"balance": 10012.5}
