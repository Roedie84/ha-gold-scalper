"""1.8.0 - broker-dashboard in dezelfde stijl als Stormchase en EMS.

Bewaakt: de nieuwe route is alleen-lezend en geauthenticeerd, het model heeft
de afgesproken vorm en blijft begrensd, de frontend laadt niets van buiten en
heeft geen handelsacties, en de zijbalk-ingang toont het nieuwe paneel.
"""
import asyncio
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
import gold_scalper.http as gh  # noqa: E402
from gold_scalper.broker.adapter import VenuePosition, VenueQuote  # noqa: E402
from gold_scalper.const import DOMAIN  # noqa: E402
from gold_scalper.dashboard import broker as B  # noqa: E402
from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
JS = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
NU = datetime.now(timezone.utc)


def _run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------- versie -- #

def test_version_is_consistent():
    from gold_scalper import const

    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION == "1.8.0"
    readme = (PKG.parent.parent / "README.md").read_text(encoding="utf-8")
    assert "Huidige versie: **1.8.0**" in readme
    changelog = (PKG.parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    eerste = changelog.split("## ")[1]
    assert eerste.startswith("1.8.0")
    assert "browser verversen" in eerste.lower()


# ------------------------------------------------------------- nephulp -- #

def _db(tmp_path, trades=30, equity=1500):
    db = TradeDatabase(tmp_path / "t.db")
    db.connect()
    run = db.start_run("demo", "v1", "CS.D.CFEGOLD.CEA.IP", {"venue": "ig"}, 10000.0)
    for i in range(trades):
        moment = NU - timedelta(minutes=10 * (trades - i))
        db.insert_trade(Trade(
            run_id=run, mode="demo", symbol="CS.D.CFEGOLD.CEA.IP",
            side="buy" if i % 2 else "sell", volume=0.0146,
            open_time=(moment - timedelta(minutes=3)).isoformat(),
            open_price=4120.0 + i, open_mid=4120.0 + i, open_spread=0.3,
            close_time=moment.isoformat(), close_price=4121.0 + i,
            close_reason="take_profit" if i % 3 else "na 240s nog binnen 0.3xATR",
            net_pnl=1.0 if i % 3 else -2.0, total_cost=0.42,
            cost_source="measured", duration_seconds=180, broker_ticket=f"T{i}",
        ))
    db.insert_trade(Trade(
        run_id=run, mode="demo", symbol="CS.D.CFEGOLD.CEA.IP", side="buy",
        volume=0.0146, open_time=(NU - timedelta(seconds=90)).isoformat(),
        open_price=4128.4, open_mid=4128.4, open_spread=0.3,
        stop_loss=4122.9, take_profit=4136.6, exit_regime="tijdstop",
        broker_ticket="OPEN1",
    ))
    rijen = [(run, (NU - timedelta(seconds=20 * (equity - i))).isoformat(),
              10000.0 - i * 0.01, 10000.0 - i * 0.01, 0, 0.0) for i in range(equity)]
    db.conn.executemany(
        "INSERT INTO equity (run_id, ts, balance, equity, open_positions, cumulative_cost)"
        " VALUES (?,?,?,?,?,?)", rijen)
    db.conn.commit()
    return db, run


class _Candles:
    def __init__(self, n=494):
        start = int(NU.timestamp()) // 60 * 60 - (n - 1) * 60
        self.timestamp = [start + 60 * i for i in range(n)]
        self.open = [4120.0 + i * 0.01 for i in range(n)]
        self.close = [x + 0.2 for x in self.open]
        self.high = [x + 0.5 for x in self.open]
        self.low = [x - 0.5 for x in self.open]
        self.volume = [0.0] * n


def _data():
    quote = VenueQuote(bid=4129.85, ask=4130.15, time=NU, tradeable=True)
    pos = VenuePosition(
        ticket="OPEN1", symbol="CS.D.CFEGOLD.CEA.IP", side="buy", units=1.46,
        open_price=4128.4, stop_loss=4122.9, take_profit=4136.6,
        unrealised_pnl=1.82, open_time=NU - timedelta(seconds=90),
    )
    return {
        "quote": quote, "price": quote.mid, "spread": quote.spread, "atr": 2.4,
        "candles": 494, "candles_consistent": True, "market_open": True,
        "quote_age_seconds": 1.2, "balance": 9831.0, "equity": 9832.8,
        "enabled": True, "open_positions": [pos], "signal": None,
        "reject_reason": None, "mode": "demo",
        "stats": {"trades": 105, "wins": 44, "losses": 61, "clusters": 14,
                  "win_rate": 41.9, "profit_factor": 0.63, "t_statistic": -2.7,
                  "net_pnl": -195.4, "gross_pnl": -150.3, "total_costs": 45.1,
                  "verdict": "failed", "verdict_text": "voldoet niet", "run_id": 7},
        "risk": {"state": "normal", "day_start_balance": 9828.0},
        "lifecycle": {"state": "running"},
        "balances": {"effective_equity_floor": 9000.0, "account_currency": "EUR"},
        "conversion": {"instrument": "USD", "account": "EUR"},
        "latency": {"total": {"samples": 820, "median": 182.0, "p90": 400.0, "p99": 640.0}},
        "exit_stats": {"noemer": 105, "take_profit": {"pct": 28},
                       "stop_loss": {"pct": 51}, "unknown": {"pct": 6}},
        "reconciliation": {"in_orde": True, "afwijkingen": [], "samenvatting": "ok"},
        "gate": {"checks": {"genoeg_trades": True}, "unlocked": False},
        "saldosprong": {"actief": False},
    }


class _Coordinator:
    def __init__(self, db, run):
        self.entry = SimpleNamespace(entry_id="e1")
        self.data = _data()
        self.symbol = "CS.D.CFEGOLD.CEA.IP"
        self.timeframe = "1m"
        self.mode = SimpleNamespace(places_orders=True, uses_real_money=False)
        self.enabled = True
        self.venue = SimpleNamespace(supports_trading=True)
        self.gate = {"unlocked": False}
        self._candles = _Candles()
        self.db = db
        self.run_id = run
        self.exits = SimpleNamespace(config=SimpleNamespace(
            time_stop_seconds=240, time_stop_deadzone_atr=0.3, max_hold_seconds=900))


class _Hass:
    def __init__(self, coordinator=None):
        self.data = {DOMAIN: {"e1": coordinator}} if coordinator else {DOMAIN: {}}
        self.jobs = 0

    async def async_add_executor_job(self, fn, *args):
        self.jobs += 1
        return fn(*args)


class _Gebruiker:
    def __init__(self, admin=True):
        self.is_admin = admin


class _Request(dict):
    def __init__(self, user, query=None):
        super().__init__()
        if user is not None:
            self["hass_user"] = user
        self.query = query or {}


def _get(view, user=_Gebruiker(), **query):
    antwoord = _run(view.get(_Request(user, query)))
    return antwoord.status, json.loads(antwoord.text)


# --------------------------------------------------------------- route -- #

def test_route_is_authenticated_and_read_only():
    view = gh.GoldScalperBrokerView
    assert view.requires_auth is True
    assert view.url == "/api/gold_scalper/broker"
    for methode in ("post", "put", "patch", "delete"):
        assert not hasattr(view, methode)


def test_route_refuses_without_login_or_admin(tmp_path):
    db, run = _db(tmp_path)
    view = gh.GoldScalperBrokerView(_Hass(_Coordinator(db, run)))
    assert _get(view, None)[0] == 401
    assert _get(view, _Gebruiker(admin=False))[0] == 403


def test_route_without_entry_or_data(tmp_path):
    assert _get(gh.GoldScalperBrokerView(_Hass()))[1] == {"error": "no_entry"}
    db, run = _db(tmp_path)
    c = _Coordinator(db, run)
    c.data = None
    status, body = _get(gh.GoldScalperBrokerView(_Hass(c)))
    assert status == 503 and body["error"] == "starting"


def test_route_payload_shape_and_cache(tmp_path):
    db, run = _db(tmp_path)
    hass = _Hass(_Coordinator(db, run))
    view = gh.GoldScalperBrokerView(hass)
    status, body = _get(view)
    assert status == 200
    for sleutel in ("api", "versie", "sleutel", "instrument", "koers", "status",
                    "alarm", "candles", "posities", "account", "equity", "trades",
                    "markers", "stats"):
        assert sleutel in body, sleutel
    assert body["api"] == B.BROKER_API_VERSION
    assert body["versie"] == "1.8.0"
    assert body["status"]["geld"] == "demo"
    assert len(body["candles"]["t"]) == 494 and body["instrument"]["tf_s"] == 60
    p = body["posities"][0]
    assert p["richting"] == "long" and p["units"] == 1.46
    assert p["sl"] == 4122.9 and p["tp"] == 4136.6
    assert p["pnl"] == pytest.approx((4129.85 - 4128.4) * 1.46, abs=0.01)
    assert p["tijdstop_s"] == 240 and p["max_duur_s"] == 900
    assert len(body["trades"]) == B.RECENT_TRADES
    assert body["trades"][0]["sluit_t"] >= body["trades"][-1]["sluit_t"]
    assert {t["reden"] for t in body["trades"]} <= {"Doel", "Tijdstop"}
    assert len(body["equity"]["t"]) <= B.MAX_EQUITY_POINTS + 1
    assert body["equity"]["rijen"] == 1500
    assert body["stats"]["clusters"] == 14 and body["stats"]["clusters_richtgetal"] == 30
    assert body["stats"]["oordeel_label"] == "Geen edge aantoonbaar"
    assert body["account"]["vloer_afstand"] == pytest.approx(832.8)

    # Zelfde cyclus: niet opnieuw bouwen, en met since een klein antwoord.
    jobs = hass.jobs
    status, klein = _get(view, since=body["sleutel"])
    assert klein == {"api": 1, "sleutel": body["sleutel"], "ongewijzigd": True}
    assert hass.jobs == jobs
    # Nieuwe cyclus: nieuwe sleutel.
    hass.data[DOMAIN]["e1"].data = _data()
    _, nieuw = _get(view, since=body["sleutel"])
    assert nieuw["sleutel"] != body["sleutel"] and "posities" in nieuw


def test_payload_is_strict_json():
    data = _data()
    data["atr"] = float("nan")
    body = B.build_payload(
        data, symbol="X", timeframe="1m", candles=None, db=None, exit_cfg={},
        version="1.8.0", status=("wachtend", ""), places_orders=False,
        uses_real_money=False,
    )
    json.dumps(body, allow_nan=False)
    assert body["koers"]["atr"] is None
    assert body["status"]["geld"] == "papier"


def test_database_connection_is_read_only(tmp_path):
    db, run = _db(tmp_path)
    conn = B.open_readonly(db.path)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM trades")
    conn.close()
    voor = db.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    B.read_database(db.path, run)
    assert db.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == voor


def test_candles_are_bounded():
    c = _Candles(2000)
    uit = B.candles_slice(c)
    assert len(uit["t"]) == B.MAX_CANDLES and uit["t"][-1] == c.timestamp[-1]
    assert B.candles_slice(None) is None


def test_close_reason_labels():
    assert B.sluitreden("take_profit")[0] == "Doel"
    assert B.sluitreden("stop_loss")[0] == "Stop"
    assert B.sluitreden("na 241s nog binnen 0.3xATR van het instappunt")[0] == "Tijdstop"
    assert B.sluitreden("maximale positieduur van 900s bereikt")[0] == "Max. duur"
    assert B.sluitreden("x", "take_profit")[0] == "Doel"
    assert B.sluitreden(None)[0] == "onbekend"


# ------------------------------------------------------------ frontend -- #

def test_frontend_has_no_external_sources():
    assert not re.search(r"https?://", JS)
    assert "//cdn" not in JS and "@import" not in JS
    assert not re.search(r"^\s*import\s", JS, re.M)
    assert "fetch(" not in JS and "XMLHttpRequest" not in JS


def test_frontend_is_display_only():
    # Uitsluitend GET via callApi; geen diensten, geen websocket-commando's.
    assert 'callApi("GET"' in JS
    for verboden in ("callService", "callWS", "sendMessage", '"POST"', "'POST'",
                     "close_all", "resume", "trading_enabled"):
        assert verboden not in JS, verboden
    assert "customElements.define(ELEMENT_NAME" in JS
    assert 'const ELEMENT_NAME = "gold-scalper-broker-panel"' in JS


def test_frontend_version_busts_cache():
    v = gh.broker_frontend_version()
    assert v.startswith("1.8.0-") and len(v) == len("1.8.0-") + 12


# ------------------------------------------------------------ zijbalk --- #

class _Panelen:
    def __init__(self):
        self.zijbalk = {}

    async def async_register_panel(self, hass, **kw):
        if kw["frontend_url_path"] in self.zijbalk:
            raise ValueError("bestaat al")
        self.zijbalk[kw["frontend_url_path"]] = kw

    def async_remove_panel(self, hass, pad, **_):
        self.zijbalk.pop(pad, None)


class _Http:
    def __init__(self):
        self.views, self.static = [], []

    def register_view(self, v):
        self.views.append(v)

    async def async_register_static_paths(self, c):
        self.static.extend(c)


def test_sidebar_entry_shows_broker_panel(monkeypatch):
    import homeassistant.components as hc

    p = _Panelen()
    pc = ModuleType("panel_custom")
    pc.async_register_panel = p.async_register_panel
    fe = ModuleType("frontend")
    fe.async_remove_panel = p.async_remove_panel
    monkeypatch.setattr(hc, "panel_custom", pc, raising=False)
    monkeypatch.setattr(hc, "frontend", fe, raising=False)
    monkeypatch.setattr(gh, "StaticPathConfig",
                        lambda url, pad, cache: SimpleNamespace(url_path=url, path=pad))
    # Een achtergebleven registratie (de oude iframe) wordt vervangen.
    p.zijbalk[gh.PANEL_URL_PATH] = {"component_name": "iframe"}
    hass = _Hass()
    hass.http = _Http()
    _run(gh.async_register_frontend(hass, True))
    _run(gh.async_register_frontend(hass, True))
    paneel = p.zijbalk[gh.PANEL_URL_PATH]
    assert gh.PANEL_URL_PATH == "gold-scalper"
    assert paneel["webcomponent_name"] == "gold-scalper-broker-panel"
    assert paneel["module_url"].startswith("/gold_scalper_static/broker-panel.js?v=1.8.0-")
    assert paneel["require_admin"] is True and paneel["embed_iframe"] is False
    assert paneel["trust_external"] is False
    names = sorted(type(v).__name__ for v in hass.http.views)
    assert names == ["GoldScalperBrokerView", "GoldScalperOverviewView", "GoldScalperReportView"]
    assert [s.path for s in hass.http.static] == [str(gh.BROKER_JS_FILE)]
