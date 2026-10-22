"""2.8.0: Pepperstone via de cTrader Open API (JSON over WebSocket)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp
import pytest

from gold_scalper.broker import ctrader as ct
from gold_scalper.broker.ig_capital import match_transaction


# --- zuivere functies ----------------------------------------------------- #

def test_prijs_en_volume():
    assert ct.prijs(408590000) == 4085.9
    assert ct.naar_volume(4.7) == 400          # naar beneden: nooit meer risico
    assert ct.naar_volume(1.0) == 100
    assert ct.naar_volume(0.6) == 0            # onder 1 oz: niet handelen


def test_trendbars_zoals_cTrader_ze_levert():
    bars = [
        {"volume": 204, "low": 408479000, "deltaOpen": 0, "deltaClose": 46000,
         "deltaHigh": 126000, "utcTimestampInMinutes": 29866662},
        {"volume": 220, "low": 408426000, "deltaOpen": 102000, "deltaClose": 69000,
         "deltaHigh": 148000, "utcTimestampInMinutes": 29866661},
    ]
    c = ct.trendbars_naar_candles(bars)
    assert c.timestamp == [29866661 * 60, 29866662 * 60]
    assert c.open[0] == pytest.approx(4085.28) and c.high[0] == pytest.approx(4085.74)
    assert c.low[0] == pytest.approx(4084.26) and c.close[0] == pytest.approx(4084.95)


def _sluitdeal(positie=7, prijs_uit=4100.5, prijs_in=4095.0, oz=3, zijde="SELL", t=1792000000000):
    return {"dealId": 99, "positionId": positie, "tradeSide": zijde, "symbolId": 41,
            "executionPrice": prijs_uit, "executionTimestamp": t, "filledVolume": oz * 100,
            "closePositionDetail": {"entryPrice": prijs_in, "grossProfit": 1650, "swap": -10,
                                    "commission": -8, "closedVolume": oz * 100, "moneyDigits": 2}}


def test_deal_als_ig_transactie_en_koppeling():
    opening = {"positionId": 7, "executionTimestamp": 1791999000000, "tradeSide": "BUY"}
    tx = ct.deal_naar_transactie(_sluitdeal(), opening, "USD")
    assert tx["size"] == "+3"                  # long positie, sluitende deal is SELL
    assert tx["profitAndLoss"] == pytest.approx(16.32)
    assert "converted at 1" in tx["instrumentName"]
    m = match_transaction([tx], "7", 4095.0, "buy", 3.0, tx["openDateUtc"] + "+00:00",
                          tx["dateUtc"] + "+00:00")
    assert m["exit_price"] == 4100.5 and m["conversion_rate"] == 1.0
    # 2.20.4: het positienummer is de sleutel bij cTrader.
    assert m["matched_on"] == "positienummer"
    assert ct.deal_naar_transactie({"dealId": 1}, None, "USD") is None


# --- de venue met een nep-verbinding --------------------------------------- #

class NepWS:
    def __init__(self, antwoorden):
        self.closed = False
        self.verstuurd = []
        self._q: asyncio.Queue = asyncio.Queue()
        self._antwoorden = antwoorden

    async def send_json(self, bericht):
        self.verstuurd.append(bericht)
        t = bericht.get("payloadType")
        if t == ct.HEARTBEAT:
            return
        for antw in self._antwoorden(bericht):
            await self._q.put(antw)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        data = await self._q.get()
        if data is None:
            raise StopAsyncIteration

        class M:
            type = aiohttp.WSMsgType.TEXT

            def json(self_inner):
                return data
        return M()

    async def close(self):
        self.closed = True
        await self._q.put(None)


POSITIE = {"positionId": 7, "price": 4095.0, "stopLoss": 4090.0, "takeProfit": 4105.0,
           "usedMargin": 1500, "moneyDigits": 2,
           "tradeData": {"symbolId": 41, "volume": 300, "tradeSide": "BUY",
                         "openTimestamp": 1791999000000, "comment": "gs-abc"}}


def _broker(bericht):
    t, p, mid = bericht["payloadType"], bericht.get("payload") or {}, bericht.get("clientMsgId")
    def a(soort, payload):
        return {"clientMsgId": mid, "payloadType": soort, "payload": payload}
    if t == ct.APP_AUTH_REQ:
        return [a(ct.APP_AUTH_RES, {})]
    if t == ct.ACCOUNTS_BY_TOKEN_REQ:
        return [a(ct.ACCOUNTS_BY_TOKEN_RES, {"ctidTraderAccount": [
            {"ctidTraderAccountId": 49150034, "traderLogin": 4279676, "isLive": False}]})]
    if t == ct.ACCOUNT_AUTH_REQ:
        return [a(ct.ACCOUNT_AUTH_RES, {})]
    if t == ct.SYMBOLS_LIST_REQ:
        return [a(ct.SYMBOLS_LIST_RES, {"symbol": [{"symbolId": 41, "symbolName": "XAUUSD"}]})]
    if t == ct.SYMBOL_BY_ID_REQ:
        return [a(ct.SYMBOL_BY_ID_RES, {"symbol": [{"symbolId": 41, "minVolume": 100, "stepVolume": 100}]})]
    if t == ct.ASSET_LIST_REQ:
        return [a(ct.ASSET_LIST_RES, {"asset": [{"assetId": 15, "name": "USD"}]})]
    if t == ct.TRADER_REQ:
        return [a(ct.TRADER_RES, {"trader": {"balance": 5000000, "moneyDigits": 2, "depositAssetId": 15}})]
    if t == ct.SUBSCRIBE_SPOTS_REQ:
        return [a(ct.SUBSCRIBE_SPOTS_RES, {}),
                {"payloadType": ct.SPOT_EVENT, "payload": {"symbolId": 41, "bid": 409500000, "ask": 409508000}}]
    if t == ct.RECONCILE_REQ:
        return [a(ct.RECONCILE_RES, {"position": [POSITIE]})]
    if t == ct.UNREALIZED_PNL_REQ:
        return [a(ct.UNREALIZED_PNL_RES, {"moneyDigits": 2, "positionUnrealizedPnL": [
            {"positionId": 7, "netUnrealizedPnL": 1234}]})]
    if t == ct.NEW_ORDER_REQ:
        return [a(ct.EXECUTION_EVENT, {"executionType": "ORDER_ACCEPTED", "order": {}}),
                a(ct.EXECUTION_EVENT, {"executionType": "ORDER_FILLED",
                                       "position": {"positionId": 8, "price": 4095.1,
                                                    "tradeData": {"comment": p.get("comment")}},
                                       "deal": {"executionPrice": 4095.1, "filledVolume": p["volume"]}})]
    if t == ct.CLOSE_POSITION_REQ:
        return [a(ct.EXECUTION_EVENT, {"executionType": "ORDER_FILLED",
                                       "position": {"positionId": p["positionId"]},
                                       "deal": {"executionPrice": 4099.0, "filledVolume": p["volume"]}})]
    if t == ct.AMEND_SLTP_REQ:
        return [a(ct.EXECUTION_EVENT, {"executionType": "ORDER_REPLACED"})]
    if t == ct.DEALS_BY_POSITION_REQ:
        return [a(ct.DEALS_BY_POSITION_RES, {"deal": [
            {"dealId": 1, "positionId": 7, "tradeSide": "BUY", "executionTimestamp": 1791999000000,
             "executionPrice": 4095.0},
            _sluitdeal()]})]
    if t == ct.DEAL_LIST_REQ:
        return [a(ct.DEAL_LIST_RES, {"deal": [_sluitdeal()]})]
    if t == ct.TRENDBARS_REQ:
        return [a(ct.TRENDBARS_RES, {"trendbar": [
            {"low": 408479000, "deltaOpen": 0, "deltaClose": 46000, "deltaHigh": 126000,
             "utcTimestampInMinutes": 29866662 + i, "volume": 1} for i in range(5)]})]
    return [a(ct.ERROR_RES, {"errorCode": "ONBEKEND", "description": str(t)})]


class NepSessie:
    def __init__(self):
        self.ws = NepWS(_broker)

    async def ws_connect(self, url, **kw):
        assert url == "wss://demo.ctraderapi.com:5036"
        return self.ws


def _venue(**kw):
    sessie = NepSessie()
    v = ct.CTraderVenue(sessie, "id", "geheim", "tok", "ververs", trader_login=4279676, **kw)
    return v, sessie.ws


@pytest.mark.asyncio
async def test_aanmelden_account_en_koers():
    v, ws = _venue()
    acc = await v.account()
    assert v.ctid == 49150034 and v.symbol_id == 41 and v.valuta == "USD"
    assert acc.balance == 50000.0 and acc.equity == pytest.approx(50012.34)
    assert acc.margin_used == 15.0 and acc.currency == "USD"
    q = await v.quote("XAUUSD")
    assert q.bid == 4095.0 and q.ask == pytest.approx(4095.08) and q.tradeable
    pos = await v.positions()
    assert pos[0].ticket == "7" and pos[0].units == 3.0 and pos[0].side == "buy"
    assert pos[0].stop_loss == 4090.0 and pos[0].comment == "gs-abc"
    await v.sluit_verbinding()


@pytest.mark.asyncio
async def test_order_met_relatieve_stop_en_doel():
    v, ws = _venue(trading_enabled=True, max_units=50)
    uit = await v.place_order("XAUUSD", "buy", 4.7, stop_loss=4085.08, take_profit=4115.08,
                              comment="gs-1")
    assert uit.success and uit.ticket == "8" and uit.units == 4.0 and uit.fill_price == 4095.1
    order = next(b["payload"] for b in ws.verstuurd if b["payloadType"] == ct.NEW_ORDER_REQ)
    assert order["volume"] == 400 and order["tradeSide"] == 1
    assert order["relativeStopLoss"] == 1_000_000 and order["relativeTakeProfit"] == 2_000_000
    await v.sluit_verbinding()


@pytest.mark.asyncio
async def test_order_zonder_handel_geweigerd():
    v, _ = _venue()
    with pytest.raises(ct.TradingDisabledError):
        await v.place_order("XAUUSD", "buy", 2)
    await v.sluit_verbinding()


@pytest.mark.asyncio
async def test_te_klein_wordt_niet_verstuurd():
    v, ws = _venue(trading_enabled=True, max_units=50)
    uit = await v.place_order("XAUUSD", "sell", 0.5, stop_loss=4100, take_profit=4080)
    assert not uit.success and "1 oz" in uit.error
    assert not any(b["payloadType"] == ct.NEW_ORDER_REQ for b in ws.verstuurd)
    await v.sluit_verbinding()


@pytest.mark.asyncio
async def test_sluiten_en_stop_verplaatsen_houdt_het_doel():
    v, ws = _venue(trading_enabled=True, max_units=50)
    uit = await v.close("7", 1.0)
    assert uit.success and uit.fill_price == 4099.0 and uit.units == 1.0
    w = await v.modify_stop("7", 4095.5)
    assert w.success
    wijz = [b["payload"] for b in ws.verstuurd if b["payloadType"] == ct.AMEND_SLTP_REQ][-1]
    assert wijz["stopLoss"] == 4095.5 and wijz["takeProfit"] == 4105.0
    await v.sluit_verbinding()


@pytest.mark.asyncio
async def test_afwikkeling_en_transacties():
    v, _ = _venue()
    d = await v.closed_deal("7", 4095.0, "buy", datetime.fromtimestamp(1792000000, tz=timezone.utc))
    assert d["exit_price"] == 4100.5 and d["profit_account"] == pytest.approx(16.32)
    assert d["conversion_rate"] == 1.0 and d["matched_on"] == "ticket"
    nu = datetime.now(timezone.utc)
    txs = await v.transactions(nu - timedelta(days=1), nu)
    assert txs and txs[0]["openDateUtc"] is not None
    c = await v.candles("XAUUSD", "1m", 3)
    assert len(c) == 3
    await v.sluit_verbinding()


def test_koppelingen():
    from pathlib import Path
    pkg = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
    bron = (pkg / "coordinator.py").read_text(encoding="utf-8")
    assert "elif venue_name == VENUE_CTRADER:" in bron
    assert 'bestand = "gold_scalper_ctrader.db"' in bron
    flow = (pkg / "config_flow.py").read_text(encoding="utf-8")
    assert "async def async_step_ctrader" in flow and "async_lees_geheimen" in flow
    from gold_scalper.const import TRADING_VENUES, VENUE_CTRADER, VENUES
    assert VENUE_CTRADER in VENUES and VENUE_CTRADER in TRADING_VENUES


@pytest.mark.asyncio
async def test_remming_wordt_overgedaan_en_historie_gespreid(monkeypatch):
    """2.9.0: "You are being rate limited" opnieuw proberen; historie <= 5/s."""
    monkeypatch.setattr(ct, "REMMING_WACHT_S", 0.01)
    monkeypatch.setattr(ct, "HISTORISCH_INTERVAL_S", 0.05)
    geweigerd = {"n": 0}

    def broker(bericht):
        if bericht["payloadType"] == ct.TRENDBARS_REQ and geweigerd["n"] < 2:
            geweigerd["n"] += 1
            return [{"clientMsgId": bericht.get("clientMsgId"), "payloadType": ct.ERROR_RES,
                     "payload": {"errorCode": "BLOCKED_PAYLOAD_TYPE",
                                 "description": "You are being rate limited"}}]
        return _broker(bericht)

    sessie = NepSessie()
    sessie.ws = NepWS(broker)
    v = ct.CTraderVenue(sessie, "id", "geheim", "tok", "ververs", trader_login=4279676)
    c = await v.candles("XAUUSD", "1m", 3)
    assert len(c) == 3 and geweigerd["n"] == 2 and v._stats["geremd"] == 2
    t0 = asyncio.get_running_loop().time()
    for _ in range(3):
        await v.candles("XAUUSD", "1m", 3)
    assert asyncio.get_running_loop().time() - t0 >= 0.1
    await v.sluit_verbinding()


@pytest.mark.asyncio
async def test_andere_fout_niet_overgedaan():
    v, ws = _venue()
    await v.account()
    with pytest.raises(ct.VenueError):
        await v._verzoek(9999, {})
    assert sum(1 for b in ws.verstuurd if b["payloadType"] == 9999) == 1
    await v.sluit_verbinding()


def test_brokerkeuze_in_dashboard():
    """2.9.0: knop in het dashboard om tussen brokers (entries) te wisselen."""
    from types import SimpleNamespace
    from pathlib import Path
    from gold_scalper.http import broker_keuzes

    def coord(eid, venue, titel, mode):
        return SimpleNamespace(entry=SimpleNamespace(entry_id=eid, data={"venue": venue},
                                                     options={}, title=titel),
                               mode=SimpleNamespace(value=mode), data={"x": 1})
    hass = SimpleNamespace(data={"gold_scalper": {
        "a": coord("a", "ig", "CS.D.CFEGOLD.CEA.IP (ig demo)", "demo"),
        "b": coord("b", "ctrader", "XAUUSD (Pepperstone demo)", "demo")}})
    k = broker_keuzes(hass)
    assert [x["naam"] for x in k] == ["IG", "Pepperstone"]
    assert k[1]["entry"] == "b" and k[1]["modus"] == "demo" and k[1]["klaar"]
    js = (Path(__file__).resolve().parents[1] / "custom_components" / "gold_scalper"
          / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
    assert 'id="brokers"' in js and "_kiesBroker" in js and "entry=${encodeURIComponent(gevraagd)}" in js
    http = (Path(__file__).resolve().parents[1] / "custom_components" / "gold_scalper"
            / "http.py").read_text(encoding="utf-8")
    assert '"brokers": brokers' in http


@pytest.mark.asyncio
async def test_live_koers_van_ctrader_naar_dashboard(monkeypatch):
    """2.9.1: Pepperstone-koersen live naar het paneel, zoals bij IG."""
    from types import SimpleNamespace
    from gold_scalper.broker_stream import stream_eligibility
    from gold_scalper.dashboard.stream import VenueTickStream

    v, ws = _venue()
    await v.account()
    coord = SimpleNamespace(venue=v, mode=SimpleNamespace(value="demo"))
    assert stream_eligibility(coord) == (True, "")
    coord.mode = SimpleNamespace(value="paper")
    assert not stream_eligibility(coord)[0]

    stroom = VenueTickStream(v)
    ontvangen = []
    afmelden = stroom.subscribe(ontvangen.append)
    await asyncio.sleep(0)
    v._verwerk({"payloadType": ct.SPOT_EVENT, "payload": {"symbolId": 41, "bid": 409600000,
                                                          "ask": 409608000}})
    await asyncio.sleep(0.01)
    ticks = [m for m in ontvangen if m.get("soort") == "tick"]
    assert stroom.status == "live" and ticks
    assert ticks[-1]["bied"] == 4096.0 and ticks[-1]["spread"] == pytest.approx(0.08)
    afmelden()
    await stroom.async_stop()
    assert not v._koers_luisteraars
    await v.sluit_verbinding()


def test_deelsluiting_boekt_wat_de_broker_sloot():
    """2.9.2: NOODSTOP 14-10 - helft van 49 oz = 24,5 gevraagd, cTrader sloot 24."""
    from gold_scalper.coordinator import deel_units
    assert deel_units(24.5, 24.0) == 24.0
    assert deel_units(24.5, None) == 24.5
    assert deel_units(24.5, 0) == 24.5
    assert deel_units(24.5, 49.0) == 24.5   # nooit meer dan gevraagd
    assert ct.naar_volume(24.5) == 2400


def test_commissie_en_scalp_handmatig_uit():
    """2.9.3: commissie in de eigen kosten; scalp met de hand uit."""
    from types import SimpleNamespace
    from gold_scalper.coordinator import _commissie_venue, scalp_handmatig
    v, _ = _venue()
    assert v.commissie_per_lot_per_zijde == ct.COMMISSIE_STANDAARD
    v.symbool = {"commissionType": 2, "preciseTradingCommissionRate": 350000000}
    assert v.commissie_per_lot_per_zijde == 3.5
    v.symbool = {"commissionType": 1, "preciseTradingCommissionRate": 999}
    assert v.commissie_per_lot_per_zijde == ct.COMMISSIE_STANDAARD
    assert _commissie_venue(v) == 3.5
    assert _commissie_venue(SimpleNamespace()) == 0.0          # IG: geen commissie
    from unittest.mock import MagicMock
    assert _commissie_venue(MagicMock()) == 0.0
    # 50 oz rondreis = 2 x 3,50 x 0,5 lot = 3,50 USD (gemeten verschil 14-10)
    assert 2 * 3.5 * 50 / 100 == 3.5
    g = scalp_handmatig([-10.0, -20.0, 5.0])
    assert g["handmatig"] and g["n"] == 3 and g["netto"] == -25.0 and g["t"] < 0
    assert scalp_handmatig([])["t"] is None
    from pathlib import Path
    co = (Path(__file__).resolve().parents[1] / "custom_components" / "gold_scalper"
          / "coordinator.py").read_text(encoding="utf-8")
    assert "self.scalp_handmatig_uit" in co and "CONF_SCALP_UIT" in co


@pytest.mark.asyncio
async def test_niveaus_na_vulling_absoluut():
    """2.9.4: na de vulling stop en doel op de gevraagde niveaus (niet relatief)."""
    v, ws = _venue(trading_enabled=True, max_units=50)
    uit = await v.place_order("XAUUSD", "buy", 2, stop_loss=4085.08, take_profit=4115.08)
    assert uit.success
    wijz = [b["payload"] for b in ws.verstuurd if b["payloadType"] == ct.AMEND_SLTP_REQ]
    assert wijz and wijz[-1]["stopLoss"] == 4085.08 and wijz[-1]["takeProfit"] == 4115.08
    # Stop aan de verkeerde kant van de vulprijs: niet zetten (relatieve blijft).
    n = len(wijz)
    await v.place_order("XAUUSD", "buy", 2, stop_loss=4096.0, take_profit=None)
    assert len([b for b in ws.verstuurd if b["payloadType"] == ct.AMEND_SLTP_REQ]) == n
    await v.sluit_verbinding()


def test_recente_trades_ook_uit_vorige_run(tmp_path):
    """2.9.4: na een runwissel blijven sluitende trades zichtbaar, met runlabel."""
    import sqlite3
    from datetime import datetime, timezone
    from gold_scalper.dashboard.broker import read_database, _trade_rows, _TRADE_KOLOMMEN
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    kol = [k.strip() for k in _TRADE_KOLOMMEN.split(",")]
    c.execute(f"CREATE TABLE trades ({', '.join(kol)}, mode TEXT)")
    c.execute("CREATE TABLE equity (run_id, ts, balance, equity)")
    nu = datetime.now(timezone.utc).isoformat()
    for i, run in ((1, 3), (2, 4)):
        rij = {k: None for k in kol}
        rij.update(id=i, run_id=run, side="buy", volume=0.1, open_time=nu, close_time=nu,
                   open_price=1.0, close_price=2.0, net_pnl=1.0, broker_ticket=str(i))
        c.execute(f"INSERT INTO trades ({', '.join(kol)}) VALUES ({', '.join('?' * len(kol))})",
                  [rij[k] for k in kol])
    c.commit(); c.close()
    try:
        d = read_database(db, 4)
    except sqlite3.OperationalError as err:   # schema van _reeks e.d. ontbreekt
        pytest.skip(str(err))
    rijen = _trade_rows(d["gesloten"])
    assert {r["run"] for r in rijen} == {3, 4}
    assert [r["eerdere_run"] for r in rijen if r["run"] == 3] == [True]


ROOSTER = {"scheduleTimeZone": "America/New_York", "schedule": [
    {"startSecond": 64860, "endSecond": 147540}, {"startSecond": 151260, "endSecond": 233940},
    {"startSecond": 237660, "endSecond": 320340}, {"startSecond": 324060, "endSecond": 406740},
    {"startSecond": 410460, "endSecond": 492900}]}


def test_rooster_pepperstone():
    """2.9.5: dagpauze 16:59-18:01 New York = 22:59-00:01 Amsterdam (zomertijd)."""
    v, _ = _venue()
    v.symbool = dict(ROOSTER)
    wo = datetime(2026, 10, 14, tzinfo=timezone.utc)          # woensdag
    assert v.markt_open(wo.replace(hour=20, minute=58)) is True
    assert v.markt_open(wo.replace(hour=20, minute=59, second=30)) is False
    assert v.markt_open(wo.replace(hour=22, minute=0, second=30)) is False
    assert v.markt_open(wo.replace(hour=22, minute=1, second=30)) is True
    assert v.minuten_tot_sluiting(wo.replace(hour=20, minute=49)) == pytest.approx(10.0)
    za = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    assert v.markt_open(za) is False
    v.symbool = {}
    assert v.markt_open(wo) is None and v.minuten_tot_sluiting(wo) is None
    # Feestdag (eigen tijdzone, dagen sinds 1970).
    v.symbool = {**ROOSTER, "holiday": [{"scheduleTimeZone": "UTC", "holidayDate": 20740,
                                          "isRecurring": False, "startSecond": 0,
                                          "endSecond": 86399}]}
    assert v.markt_open(datetime(2026, 10, 14, 12, tzinfo=timezone.utc)) is False


@pytest.mark.asyncio
async def test_koers_volgt_rooster():
    v, _ = _venue()
    await v.account()
    v.symbool = {"scheduleTimeZone": "UTC", "schedule": []}
    assert (await v.quote("XAUUSD")).tradeable                  # geen rooster: leeftijd
    v.symbool = {"scheduleTimeZone": "UTC", "schedule": [{"startSecond": 0, "endSecond": 1}]}
    assert not (await v.quote("XAUUSD")).tradeable              # buiten rooster: dicht
    await v.sluit_verbinding()
