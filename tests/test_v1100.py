"""1.10.0 - afstemming bewaard, sluitreden achteraf, sluitredenen gegroepeerd.

* De laatste afstemming met de broker overleeft een herstart, en na een
  herstart wordt één keer afgestemd - ook bij een gesloten markt. Alleen lezen
  bij de broker; een onbereikbare broker laat de bewaarde uitkomst staan.
* Een trade met sluitreden onbekend krijgt zijn reden achteraf uit de
  afstemming (doel, stop, tijdslimiet, handmatig), gemarkeerd met bron
  ``afstemming``.
* "na 243s nog binnen 0.3xATR ..." is voortaan de soort ``tijdslimiet`` met
  ``looptijd_s`` 243; de historie wordt bij het openen genormaliseerd.

Geen strategie- of handelslogica gewijzigd.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))
sys.path.insert(0, HIER)

from gold_scalper.broker.adapter import VenueError  # noqa: E402
from gold_scalper.broker.ig_capital import match_activity  # noqa: E402
from gold_scalper.learning.exit_stats import exit_stats  # noqa: E402
from gold_scalper.learning.sluitreden import (  # noqa: E402
    MAX_DUUR, TIJDSLIMIET, normaliseer, reden_uit_broker,
)
from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402

from test_broker_cycle import ScriptedVenue, _coordinator  # noqa: E402

PKG = Path(HIER).parent / "custom_components" / "gold_scalper"
OUD_TIJDSTOP = "na 243s nog binnen 0.3xATR van het instappunt; geen scalp me"


# --------------------------------------------------------------------------
# 7. Sluitredenen groeperen
# --------------------------------------------------------------------------


@pytest.mark.parametrize("tekst, soort, s", [
    (OUD_TIJDSTOP, TIJDSLIMIET, 243),
    ("na 661s nog binnen 0.3xATR van het instappunt; geen scalp meer maar een kostenpost",
     TIJDSLIMIET, 661),
    ("maximale positieduur van 900s bereikt bij +0.123 USD/oz", MAX_DUUR, 900),
    ("stop_loss", "stop_loss", None),
    ("broker_gesloten_gemeten", "broker_gesloten_gemeten", None),
    ("handmatig", "handmatig", None),
    (TIJDSLIMIET, TIJDSLIMIET, None),
])
def test_normaliseer_maakt_een_vaste_soort(tekst, soort, s):
    assert normaliseer(tekst) == (soort, s)
    # Idempotent.
    assert normaliseer(normaliseer(tekst)[0])[0] == soort


def _trade(run, ticket="T1", **kw):
    nu = datetime.now(timezone.utc)
    velden = dict(
        run_id=run, mode="demo", symbol="GOLD", side="buy", volume=0.05,
        open_time=(nu - timedelta(hours=2)).isoformat(), open_price=4400.0,
        open_mid=4399.7, open_spread=0.6, stop_loss=4390.0, take_profit=4415.0,
        close_time=(nu - timedelta(hours=2) + timedelta(seconds=243)).isoformat(),
        close_price=4400.5, net_pnl=2.5, total_cost=0.3, broker_ticket=ticket,
    )
    velden.update(kw)
    return Trade(**velden)


def test_nieuwe_trade_krijgt_soort_en_looptijd(tmp_path):
    db = TradeDatabase(tmp_path / "t.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    t = _trade(run, close_reason=OUD_TIJDSTOP, original_close_reason=OUD_TIJDSTOP)
    db.insert_trade(t)
    (opgeslagen,) = db.closed_trades(run)
    assert opgeslagen.close_reason == TIJDSLIMIET
    assert opgeslagen.original_close_reason == TIJDSLIMIET
    assert opgeslagen.looptijd_s == 243

    # Ook bij bijwerken.
    opgeslagen.close_reason = "na 250s nog binnen 0.3xATR van het instappunt"
    db.update_trade(opgeslagen)
    (opnieuw,) = db.closed_trades(run)
    assert opnieuw.close_reason == TIJDSLIMIET


def test_historie_wordt_bij_openen_genormaliseerd(tmp_path):
    pad = tmp_path / "oud.db"
    db = TradeDatabase(pad)
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    for i, s in enumerate((240, 241, 241, 661)):
        db.insert_trade(_trade(run, ticket=f"T{i}", close_reason="stop_loss"))
    db.insert_trade(_trade(run, ticket="T9", close_reason="stop_loss"))
    db.close() if hasattr(db, "close") else None

    # Zoals een oudere versie ze schreef: tekst met looptijd, geen looptijd_s.
    conn = sqlite3.connect(pad)
    for i, s in enumerate((240, 241, 241, 661)):
        tekst = f"na {s}s nog binnen 0.3xATR van het instappunt; geen scalp me"
        conn.execute(
            "UPDATE trades SET close_reason=?, original_close_reason=?, "
            "looptijd_s=NULL WHERE broker_ticket=?", (tekst, tekst, f"T{i}"),
        )
    conn.commit()
    conn.close()

    db = TradeDatabase(pad)
    db.connect()
    trades = {t.broker_ticket: t for t in db.closed_trades(run)}
    assert {t.close_reason for t in trades.values()} == {TIJDSLIMIET, "stop_loss"}
    assert trades["T3"].looptijd_s == 661
    assert trades["T0"].original_close_reason == TIJDSLIMIET
    assert trades["T9"].looptijd_s is None
    # Idempotent.
    assert db._normaliseer_sluitredenen() == 0

    from gold_scalper.storage import performance
    stats = performance.compute_for_run(db, run, db.closed_trades(run))
    assert stats["close_reasons"] == {TIJDSLIMIET: 4, "stop_loss": 1}


def test_paneel_toont_soort_met_looptijd_en_bron(tmp_path):
    from gold_scalper.dashboard import broker as paneel

    db = TradeDatabase(tmp_path / "p.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    db.insert_trade(_trade(run, close_reason=OUD_TIJDSTOP))
    t = _trade(run, ticket="T2", close_reason="broker_gesloten_gemeten",
               reconciled_close_reason="take_profit",
               close_reason_source="afstemming")
    db.insert_trade(t)
    data = paneel.read_database(tmp_path / "p.db", run)
    rijen = {r["ticket"]: r for r in paneel._trade_rows(data["gesloten"])}
    assert rijen["T1"]["reden"] == "Tijdstop"
    assert rijen["T1"]["looptijd_s"] == 243
    assert "na 243s" in rijen["T1"]["reden_lang"]
    assert rijen["T1"]["reden_bron"] is None
    assert rijen["T2"]["reden"] == "Doel"
    assert rijen["T2"]["reden_bron"] == "afstemming"
    assert "achteraf" in rijen["T2"]["reden_lang"]


def test_paneel_leest_ook_een_database_zonder_nieuwe_kolommen(tmp_path):
    from gold_scalper.dashboard import broker as paneel

    pad = tmp_path / "kaal.db"
    conn = sqlite3.connect(pad)
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, run_id INTEGER, "
        "broker_ticket TEXT, side TEXT, volume REAL, open_time TEXT, "
        "open_price REAL, close_time TEXT, close_price REAL, close_reason TEXT, "
        "reconciled_close_reason TEXT, net_pnl REAL, net_pnl_account REAL, "
        "account_currency TEXT, total_cost REAL, cost_source TEXT, "
        "duration_seconds INTEGER, stop_loss REAL, take_profit REAL, exit_regime TEXT)"
    )
    conn.execute("CREATE TABLE equity (run_id INTEGER, ts TEXT, balance REAL, equity REAL)")
    conn.execute(
        "INSERT INTO trades (run_id, broker_ticket, side, volume, close_time, "
        "close_reason) VALUES (1, 'X', 'buy', 0.1, '2026-10-09T10:00:00+00:00', 'stop_loss')"
    )
    conn.commit()
    conn.close()
    data = paneel.read_database(pad, 1)
    (rij,) = paneel._trade_rows(data["gesloten"])
    assert rij["reden"] == "Stop" and rij["looptijd_s"] is None


def test_varianten_herkennen_de_soort_als_tijdstop():
    from gold_scalper.strategy.tijdstopvarianten import echte_sluitcode

    assert echte_sluitcode(TIJDSLIMIET) == "tijdstop"
    assert echte_sluitcode(MAX_DUUR) == "max_duur"
    assert echte_sluitcode(OUD_TIJDSTOP) == "tijdstop"


# --------------------------------------------------------------------------
# 6. Sluitreden achteraf uit de broker
# --------------------------------------------------------------------------


def _act(channel, date=None):
    return {"channel": channel, "activity_date": date, "exit_price": None}


def test_reden_uit_broker_volgt_het_bewijs():
    t = _trade(1)
    # Doel: de prijs volstaat, ook zonder activiteit.
    r = reden_uit_broker(t, 4415.0, None, 240, 900)
    assert r.reden == "take_profit" and r.bron == "afstemming"
    # Op de stop zonder kanaal: geen bewijs.
    assert reden_uit_broker(t, 4390.0, None, 240, 900) is None
    # Door het systeem van de broker op de stop.
    assert reden_uit_broker(t, 4390.0, _act("SYSTEM"), 240, 900).reden == "stop_loss"
    # Door het systeem, niet op het doel: een (verplaatste) stop.
    assert reden_uit_broker(t, 4402.0, _act("SYSTEM"), 240, 900).reden == "stop_loss"
    # Via de API na 243 s: tijdslimiet.
    assert reden_uit_broker(t, 4400.5, _act("PUBLIC_WEB_API"), 240, 900).reden == TIJDSLIMIET
    # Via de API na 950 s: maximale duur.
    lang = _trade(1, close_time=(datetime.fromisoformat(t.open_time)
                                 + timedelta(seconds=950)).isoformat())
    assert reden_uit_broker(lang, 4400.5, _act("PUBLIC_WEB_API"), 240, 900).reden == MAX_DUUR
    # Via de API na 100 s: eigen exit, geen tijdslimiet.
    kort = _trade(1, close_time=(datetime.fromisoformat(t.open_time)
                                 + timedelta(seconds=100)).isoformat())
    assert reden_uit_broker(kort, 4400.5, _act("PUBLIC_WEB_API"), 240, 900).reden == "eigen_exit"
    # Zonder tijdstop (oud regime): geen tijdslimiet.
    assert reden_uit_broker(t, 4400.5, _act("PUBLIC_WEB_API"), None, 900).reden == "eigen_exit"
    # Met de hand.
    assert reden_uit_broker(t, 4400.5, _act("WEB"), 240, 900).reden == "handmatig"
    # Onbekend kanaal: niets verzinnen.
    assert reden_uit_broker(t, 4400.5, _act("IETS"), 240, 900) is None
    assert reden_uit_broker(t, 4400.5, {}, 240, 900) is None


def test_activiteit_noemt_het_kanaal():
    act = {
        "date": "2026-10-09T11:53:20", "dealId": "DIAAAACLOSE", "status": "ACCEPTED",
        "type": "POSITION", "channel": "PUBLIC_WEB_API",
        "details": {
            "actions": [{"actionType": "POSITION_CLOSED", "affectedDealId": "T1"}],
            "direction": "SELL", "level": 4400.5, "dealReference": "REF",
        },
    }
    m = match_activity([act], "T1", "buy", 4400.0)
    assert m["channel"] == "PUBLIC_WEB_API"
    assert m["exit_price"] == pytest.approx(4400.5)


class AlleenLezenVenue(ScriptedVenue):
    """Broker die faalt op alles wat iets zou doen: plaatsen, sluiten, wijzigen."""

    def __init__(self, transacties=None, activiteit=None, fout=None):
        super().__init__()
        self._tx = transacties or []
        self._act = activiteit
        self._fout = fout
        self.gelezen: list = []

    async def transactions(self, van, tot):
        self.gelezen.append("transactions")
        if self._fout:
            raise self._fout
        return self._tx

    async def closed_deal_activity(self, ticket, side=None, open_price=None, since=None):
        self.gelezen.append("activity")
        return self._act

    async def place_order(self, *a, **kw):
        raise AssertionError("afstemming mag geen order plaatsen")

    async def close(self, *a, **kw):
        raise AssertionError("afstemming mag niets sluiten")

    async def modify_stop(self, *a, **kw):
        raise AssertionError("afstemming mag niets wijzigen")


class GeheugenOpslag:
    """De ResultsStore zonder bestand: wat een herstart overleeft."""

    def __init__(self):
        self.data: dict = {}

    async def async_load(self):
        return json.loads(json.dumps(self.data))

    async def async_save(self, data):
        self.data = json.loads(json.dumps(data))


def _onbekende_trade(coordinator):
    nu = datetime.now(timezone.utc)
    t = _trade(
        coordinator.run_id, ticket="DIAAAAONB",
        open_time=(nu - timedelta(hours=20)).isoformat(),
        close_time=(nu - timedelta(hours=20) + timedelta(seconds=241)).isoformat(),
        close_reason="broker_gesloten_gemeten",
        original_close_reason="broker_gesloten_gemeten",
        reconciled_close_reason="unknown", reconciliation_status="reconciled",
    )
    coordinator.db.insert_trade(t)
    return t


def test_afstemming_vult_onbekende_sluitreden_in(tmp_path, monkeypatch):
    venue = AlleenLezenVenue(activiteit={
        "exit_price": 4400.5, "channel": "PUBLIC_WEB_API",
        "activity_date": None, "source": "broker_activity",
    })
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator._results_store = GeheugenOpslag()
    _onbekende_trade(coordinator)
    assert exit_stats(coordinator.db.closed_trades(coordinator.run_id))["unknown"]["n"] == 1

    uitslag = asyncio.run(coordinator.async_reconcile())
    assert uitslag["sluitreden_ingevuld"] == 1
    (t,) = coordinator.db.closed_trades(coordinator.run_id)
    assert t.reconciled_close_reason == TIJDSLIMIET
    assert t.close_reason_source == "afstemming"
    assert t.original_close_reason == "broker_gesloten_gemeten"      # blijft staan
    assert t.looptijd_s == 241
    assert coordinator.exit_stats["unknown"]["n"] == 0
    assert coordinator.exit_stats["eigen_exit"]["n"] == 1
    assert coordinator.exit_stats["achteraf_ingevuld"] == 1

    # Een tweede ronde vraagt hem niet opnieuw na.
    venue.gelezen.clear()
    asyncio.run(coordinator.async_reconcile())
    assert "activity" not in venue.gelezen


def test_zonder_bewijs_blijft_de_reden_onbekend(tmp_path, monkeypatch):
    venue = AlleenLezenVenue(activiteit=None)
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator._results_store = GeheugenOpslag()
    _onbekende_trade(coordinator)
    uitslag = asyncio.run(coordinator.async_reconcile())
    assert uitslag["sluitreden_ingevuld"] == 0
    (t,) = coordinator.db.closed_trades(coordinator.run_id)
    assert t.reconciled_close_reason == "unknown"
    assert t.close_reason_source != "afstemming"


# --------------------------------------------------------------------------
# 5. Afstemming bewaren en na een herstart één keer afstemmen
# --------------------------------------------------------------------------


def test_afstemming_overleeft_een_herstart(tmp_path, monkeypatch):
    opslag = GeheugenOpslag()
    venue = AlleenLezenVenue()
    a, _ = _coordinator(venue, tmp_path, monkeypatch)
    a._results_store = opslag
    uitslag = asyncio.run(a.async_reconcile())
    assert uitslag["moment"]
    assert opslag.data["afstemming"]["moment"] == uitslag["moment"]

    # Herstart: nieuwe coordinator, zelfde opslag.
    b, _ = _coordinator(AlleenLezenVenue(), tmp_path / "b", monkeypatch)
    b._results_store = opslag
    asyncio.run(b._herstel_resultaten())
    assert b.reconciliation["moment"] == uitslag["moment"]
    assert b.reconciliation["hersteld"] is True

    from gold_scalper.meetkwaliteit import _afstemming
    assert _afstemming({"reconciliation": b.reconciliation}) == "in_orde"


def test_afstemming_na_herstart_ook_bij_gesloten_markt(tmp_path, monkeypatch):
    venue = AlleenLezenVenue()
    venue.tradeable = False                        # weekend
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator._results_store = GeheugenOpslag()
    uitslag = asyncio.run(coordinator.async_afstemming_na_herstart())
    assert uitslag and uitslag["moment"]
    assert venue.gelezen == ["transactions"]       # alleen lezen
    assert venue.orders == []
    assert coordinator._afgestemd_om is not None
    assert coordinator._afstemming_fout is None


def test_afstemming_na_herstart_faalt_veilig(tmp_path, monkeypatch):
    venue = AlleenLezenVenue(fout=VenueError("broker niet bereikbaar"))
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator._results_store = GeheugenOpslag()
    bewaard = {"in_orde": True, "moment": "2026-10-09T10:00:00+00:00",
               "samenvatting": "x", "hersteld": True}
    coordinator.reconciliation = dict(bewaard)
    assert asyncio.run(coordinator.async_afstemming_na_herstart()) is None
    assert coordinator.reconciliation == bewaard
    assert "niet bereikbaar" in coordinator._afstemming_fout
    assert venue.orders == []


def test_afstemming_na_herstart_niet_op_papier(tmp_path, monkeypatch):
    from gold_scalper.modes import TradingMode

    venue = AlleenLezenVenue()
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator.mode = TradingMode.PAPER
    assert asyncio.run(coordinator.async_afstemming_na_herstart()) is None
    assert venue.gelezen == []


def test_geen_twee_afstemmingen_tegelijk(tmp_path, monkeypatch):
    venue = AlleenLezenVenue()
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator._results_store = GeheugenOpslag()
    coordinator.reconciliation = {"moment": "eerder"}
    coordinator._afstemming_bezig = True
    assert asyncio.run(coordinator.async_reconcile()) == {"moment": "eerder"}
    assert venue.gelezen == []


def test_opstarten_plant_de_afstemming():
    tekst = (PKG / "__init__.py").read_text(encoding="utf-8")
    assert "_plan_afstemming_na_herstart(hass, entry, coordinator)" in tekst
    code = (PKG / "coordinator.py").read_text(encoding="utf-8")
    deel = code.split("async def async_afstemming_na_herstart", 1)[1].split("\n    def ", 1)[0]
    for verboden in ("place_order", ".close(", "modify_stop", "close_all"):
        assert verboden not in deel


def test_sensor_toont_bewaarde_uitkomst_met_tijdstip():
    from gold_scalper.meetkwaliteit import SPECS as SENSOREN

    sensor = next(s for s in SENSOREN if s["key"] == "reconciliation")
    d = {"reconciliation": {
        "in_orde": False, "moment": "2026-10-09T10:00:00+00:00", "hersteld": True,
        "trades": 5, "gevonden": 4, "kloppend": 3, "nog_niet_verwerkt": 1,
        "afwijkingen": [{"ticket": "X", "soort": "verschilt", "uitleg": "bedrag"}],
        "samenvatting": "s", "sluitreden_ingevuld": 2,
    }, "afstemming_fout": None}
    assert sensor["value_fn"](d) == "afwijkingen"
    attrs = sensor["attrs_fn"](d)
    assert attrs["moment"] == "2026-10-09T10:00:00+00:00"
    assert attrs["hersteld"] is True
    assert attrs["verschillen"] == ["bedrag"]
    assert attrs["sluitreden_ingevuld"] == 2


def test_paneel_markeert_achteraf_ingevulde_reden():
    js = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
    assert 't.reden_bron === "afstemming"' in js
    assert "bewaard van vóór de herstart" in js


# --------------------------------------------------------------------------
# Versie
# --------------------------------------------------------------------------


def test_versie_1100():
    from gold_scalper import const

    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION == "1.10.0"
    root = PKG.parent.parent
    assert "Huidige versie: **1.10.0**" in (root / "README.md").read_text(encoding="utf-8")
    log = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert log.split("\n## ")[1].startswith("1.10.0")
