"""cTrader Open API (Pepperstone) als uitvoeringslaag (2.8.0).

Besluit van Ruud (13-10-2026): Gold Scalper naar Pepperstone Razor (cTrader),
naast IG (14-10: "laat ze naast elkaar draaien, IG moet ook actief blijven").
Gemeten 13-10: spread XAUUSD bij Pepperstone ~0,10 USD/oz tegen ~0,76 bij IG.

Verbinding: JSON over WebSocket (``wss://demo.ctraderapi.com:5036``), één
blijvende verbinding met hartslag. Alles via ``aiohttp``, dat al in Home
Assistant zit: geen protobuf, geen extra afhankelijkheden.

Eenheden (verkend 14-10 op het demo-account):

* prijzen in koersberichten en trendbars zijn gehele getallen x 100.000
  (``408590000`` = 4085,90); in posities en deals gewone getallen;
* volume in honderdsten van een eenheid: XAUUSD ``lotSize`` 10000 = 100 oz,
  dus 1 oz = volume 100; ``minVolume`` en ``stepVolume`` 100 (1 oz);
* geldbedragen x 10^``moneyDigits``.

Naar buiten toe altijd ounces en gewone prijzen, net als de andere venues.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import aiohttp

from ..analysis.signals import Candles
from .adapter import (
    AccountSnapshot,
    ExecutionVenue,
    OrderResult,
    TradingDisabledError,
    VenueError,
    VenuePosition,
    VenueQuote,
)

_LOGGER = logging.getLogger(__name__)

HOSTS = {"demo": "demo.ctraderapi.com", "live": "live.ctraderapi.com"}
PORT = 5036

# --- berichtsoorten (ProtoOAPayloadType) ----------------------------------- #
HEARTBEAT = 51
COMMON_ERROR = 50
APP_AUTH_REQ, APP_AUTH_RES = 2100, 2101
ACCOUNT_AUTH_REQ, ACCOUNT_AUTH_RES = 2102, 2103
NEW_ORDER_REQ = 2106
AMEND_SLTP_REQ = 2110
CLOSE_POSITION_REQ = 2111
ASSET_LIST_REQ, ASSET_LIST_RES = 2112, 2113
SYMBOLS_LIST_REQ, SYMBOLS_LIST_RES = 2114, 2115
SYMBOL_BY_ID_REQ, SYMBOL_BY_ID_RES = 2116, 2117
TRADER_REQ, TRADER_RES = 2121, 2122
RECONCILE_REQ, RECONCILE_RES = 2124, 2125
EXECUTION_EVENT = 2126
SUBSCRIBE_SPOTS_REQ, SUBSCRIBE_SPOTS_RES = 2127, 2128
SPOT_EVENT = 2131
ORDER_ERROR_EVENT = 2132
DEAL_LIST_REQ, DEAL_LIST_RES = 2133, 2134
TRENDBARS_REQ, TRENDBARS_RES = 2137, 2138
ERROR_RES = 2142
TOKEN_INVALIDATED_EVENT = 2147
CLIENT_DISCONNECT_EVENT = 2148
ACCOUNTS_BY_TOKEN_REQ, ACCOUNTS_BY_TOKEN_RES = 2149, 2150
ACCOUNT_DISCONNECT_EVENT = 2164
REFRESH_TOKEN_REQ, REFRESH_TOKEN_RES = 2173, 2174
DEALS_BY_POSITION_REQ, DEALS_BY_POSITION_RES = 2179, 2180
UNREALIZED_PNL_REQ, UNREALIZED_PNL_RES = 2187, 2188

PRIJS_SCHAAL = 100_000.0
VOLUME_PER_OZ = 100
#: Na zoveel seconden zonder koers geldt de markt als dicht.
KOERS_OUD_S = 300.0
HARTSLAG_S = 10.0
VERZOEK_TIMEOUT_S = 10.0
ORDER_TIMEOUT_S = 15.0

#: Ons tijdvak naar de cTrader-periode (ProtoOATrendbarPeriod).
PERIODES = {"1m": 1, "2m": 2, "3m": 3, "4m": 4, "5m": 5, "10m": 6, "15m": 7,
            "30m": 8, "1h": 9, "4h": 10, "12h": 11, "1d": 12, "1w": 13}
TIJDVAK_S = {"1m": 60, "2m": 120, "3m": 180, "4m": 240, "5m": 300, "10m": 600,
             "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "12h": 43200,
             "1d": 86400, "1w": 604800}

GEVULD = {"ORDER_FILLED", 3}
GEDEELTELIJK = {"ORDER_PARTIAL_FILL", 11}
GEWEIGERD = {"ORDER_REJECTED", 7}
GEANNULEERD = {"ORDER_CANCELLED", 5, "ORDER_EXPIRED", 6, "ORDER_CANCEL_REJECTED", 9}


def prijs(waarde) -> float | None:
    """Geheel getal x 100.000 naar een prijs."""
    if waarde is None:
        return None
    return round(float(waarde) / PRIJS_SCHAAL, 5)


def naar_volume(ounces: float, stap: int = VOLUME_PER_OZ, minimum: int = VOLUME_PER_OZ) -> int:
    """Ounces naar cTrader-volume, naar BENEDEN afgerond op de stap: nooit
    meer risico dan gevraagd. Onder het minimum: 0 (niet handelen)."""
    ruw = int(math.floor(float(ounces) * VOLUME_PER_OZ + 1e-9))
    volume = (ruw // stap) * stap
    return volume if volume >= minimum else 0


def zijde(waarde) -> str:
    return "buy" if waarde in ("BUY", 1, "1") else "sell"


def _ms(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def _iso(ms) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def trendbars_naar_candles(bars: list[dict]) -> Candles:
    """Trendbars (laag + delta's, x 100.000; minuten sinds 1970) naar Candles
    (seconden). Bied-prijzen, zoals cTrader ze levert."""
    rijen = []
    for b in bars:
        laag = float(b.get("low") or 0)
        if not laag:
            continue
        rijen.append((
            int(b["utcTimestampInMinutes"]) * 60,
            (laag + float(b.get("deltaOpen") or 0)) / PRIJS_SCHAAL,
            (laag + float(b.get("deltaHigh") or 0)) / PRIJS_SCHAAL,
            laag / PRIJS_SCHAAL,
            (laag + float(b.get("deltaClose") or 0)) / PRIJS_SCHAAL,
            float(b.get("volume") or 0),
        ))
    rijen.sort(key=lambda r: r[0])
    uniek = []
    for r in rijen:
        if uniek and uniek[-1][0] == r[0]:
            uniek[-1] = r
        else:
            uniek.append(r)
    return Candles(
        timestamp=[r[0] for r in uniek], open=[r[1] for r in uniek],
        high=[r[2] for r in uniek], low=[r[3] for r in uniek],
        close=[r[4] for r in uniek], volume=[r[5] for r in uniek],
    )


def deal_naar_transactie(deal: dict, opening: dict | None, valuta: str | None) -> dict | None:
    """Een sluitende deal in de vorm van een IG-transactie, zodat de bestaande
    afstemming (``ig_capital.match_transaction``, ``learning/afstemming``) er
    ongewijzigd mee werkt. Geen sluitende deal: None.

    - ``size`` met het teken van de POSITIE (de sluitende deal staat andersom);
    - ``profitAndLoss`` netto in accountvaluta (bruto + swap + commissie);
    - ``instrumentName`` met "converted at 1" als de accountvaluta USD is: dan
      is er niets om te rekenen."""
    detail = deal.get("closePositionDetail")
    if not detail:
        return None
    digits = int(detail.get("moneyDigits") or deal.get("moneyDigits") or 2)
    schaal = 10 ** digits
    gesloten_oz = float(detail.get("closedVolume") or deal.get("filledVolume") or 0) / VOLUME_PER_OZ
    positie_long = zijde(deal.get("tradeSide")) == "sell"
    netto = (
        float(detail.get("grossProfit") or 0)
        + float(detail.get("swap") or 0)
        + float(detail.get("commission") or 0)
    ) / schaal
    return {
        "reference": str(deal.get("dealId")),
        "dealId": str(deal.get("positionId")),
        "openLevel": detail.get("entryPrice"),
        "closeLevel": deal.get("executionPrice"),
        "size": f"{'+' if positie_long else '-'}{gesloten_oz:g}",
        "openDateUtc": _iso((opening or {}).get("executionTimestamp")),
        "dateUtc": _iso(deal.get("executionTimestamp")),
        "profitAndLoss": round(netto, 2),
        "currency": valuta,
        "instrumentName": "XAUUSD" + (" converted at 1" if valuta == "USD" else ""),
        "bruto": round(float(detail.get("grossProfit") or 0) / schaal, 2),
        "commissie": round(float(detail.get("commission") or 0) / schaal, 2),
        "swap": round(float(detail.get("swap") or 0) / schaal, 2),
    }


class CTraderVenue(ExecutionVenue):
    """Pepperstone (en elke andere cTrader-broker) via de Open API."""

    name = "ctrader"
    runs_in_process = True
    has_real_spread = True

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        client_secret: str,
        access_token: str,
        refresh_token: str | None,
        trader_login: int | str | None = None,
        ctid_account_id: int | None = None,
        environment: str = "demo",
        symbol_name: str = "XAUUSD",
        trading_enabled: bool = False,
        max_units: float = 10.0,
        tokens_bewaren: Callable[[str, str], None] | None = None,
    ) -> None:
        if environment not in HOSTS:
            raise ValueError(f"Onbekende omgeving '{environment}'; kies demo of live")
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._access = access_token
        self._refresh = refresh_token
        self._login = str(trader_login) if trader_login else None
        self.ctid: int | None = int(ctid_account_id) if ctid_account_id else None
        self.environment = environment
        self.symbol_name = symbol_name
        self.supports_trading = trading_enabled
        self.max_units = max_units
        self._tokens_bewaren = tokens_bewaren

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._lezer: asyncio.Task | None = None
        self._hartslag: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._wachtend: dict[str, asyncio.Future] = {}
        self._uitvoeringen: asyncio.Queue | None = None
        #: Alleen uitvoeringen bewaren als er op gewacht wordt; anders loopt de
        #: rij vol met stop- en doeltreffers die niemand ophaalt.
        self._wachters = 0
        self._ids = itertools.count(1)
        self.symbol_id: int | None = None
        self.symbool: dict = {}
        self.valuta: str | None = None
        self._bid: float | None = None
        self._ask: float | None = None
        self._koers_t: float = 0.0
        self._koers_event = asyncio.Event()
        self._stats = {"verzoeken": 0, "fouten": 0, "herverbindingen": 0,
                       "tokens_ververst": 0, "laatste_fout": None}

    # -- verbinding ---------------------------------------------------------- #

    @property
    def verbonden(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def _verbind(self) -> None:
        async with self._lock:
            if self.verbonden:
                return
            url = f"wss://{HOSTS[self.environment]}:{PORT}"
            try:
                self._ws = await self._session.ws_connect(url, heartbeat=None, timeout=15)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise VenueError(f"cTrader niet bereikbaar: {err}") from err
            self._uitvoeringen = asyncio.Queue()
            self._lezer = asyncio.create_task(self._lees())
            self._hartslag = asyncio.create_task(self._klop())
            await self._aanmelden()

    async def _aanmelden(self) -> None:
        await self._verzoek(APP_AUTH_REQ, {"clientId": self._client_id,
                                           "clientSecret": self._client_secret}, APP_AUTH_RES)
        if self.ctid is None:
            antw = await self._verzoek(ACCOUNTS_BY_TOKEN_REQ, {"accessToken": self._access},
                                       ACCOUNTS_BY_TOKEN_RES)
            accounts = antw.get("ctidTraderAccount") or []
            gekozen = [a for a in accounts
                       if self._login is None or str(a.get("traderLogin")) == self._login]
            if not gekozen:
                raise VenueError(f"Account {self._login} hoort niet bij dit toegangstoken.")
            self.ctid = int(gekozen[0]["ctidTraderAccountId"])
            self._login = str(gekozen[0].get("traderLogin"))
        try:
            await self._verzoek(ACCOUNT_AUTH_REQ, {"ctidTraderAccountId": self.ctid,
                                                   "accessToken": self._access}, ACCOUNT_AUTH_RES)
        except VenueError as err:
            if "TOKEN" not in str(err).upper() or not self._refresh:
                raise
            await self._ververs_token()
            await self._verzoek(ACCOUNT_AUTH_REQ, {"ctidTraderAccountId": self.ctid,
                                                   "accessToken": self._access}, ACCOUNT_AUTH_RES)
        if self.symbol_id is None:
            await self._zoek_symbool()
        if self.valuta is None:
            antw = await self._verzoek(ASSET_LIST_REQ, {"ctidTraderAccountId": self.ctid},
                                       ASSET_LIST_RES)
            trader = await self._trader()
            asset = trader.get("depositAssetId")
            self.valuta = next((a.get("name") for a in antw.get("asset") or []
                                if a.get("assetId") == asset), None)
        self._koers_event.clear()
        await self._verzoek(SUBSCRIBE_SPOTS_REQ, {"ctidTraderAccountId": self.ctid,
                                                  "symbolId": [self.symbol_id]},
                            SUBSCRIBE_SPOTS_RES)

    async def _ververs_token(self) -> None:
        antw = await self._verzoek(REFRESH_TOKEN_REQ, {"refreshToken": self._refresh},
                                   REFRESH_TOKEN_RES)
        self._access = antw["accessToken"]
        self._refresh = antw.get("refreshToken") or self._refresh
        self._stats["tokens_ververst"] += 1
        if self._tokens_bewaren:
            try:
                self._tokens_bewaren(self._access, self._refresh)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Nieuwe cTrader-tokens niet bewaard: %s", err)

    async def _zoek_symbool(self) -> None:
        antw = await self._verzoek(SYMBOLS_LIST_REQ, {"ctidTraderAccountId": self.ctid},
                                   SYMBOLS_LIST_RES)
        for s in antw.get("symbol") or []:
            if s.get("symbolName") == self.symbol_name:
                self.symbol_id = int(s["symbolId"])
                break
        if self.symbol_id is None:
            raise VenueError(f"Symbool {self.symbol_name} niet gevonden bij cTrader.")
        antw = await self._verzoek(SYMBOL_BY_ID_REQ, {"ctidTraderAccountId": self.ctid,
                                                      "symbolId": [self.symbol_id]},
                                   SYMBOL_BY_ID_RES)
        self.symbool = (antw.get("symbol") or [{}])[0]

    async def _lees(self) -> None:
        ws = self._ws
        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    continue
                try:
                    bericht = msg.json()
                except ValueError:
                    continue
                self._verwerk(bericht)
        except Exception as err:  # noqa: BLE001 - de lezer mag nooit stil sterven
            _LOGGER.debug("cTrader-lezer gestopt: %s", err)
        finally:
            fout = VenueError("Verbinding met cTrader verbroken.")
            for f in self._wachtend.values():
                if not f.done():
                    f.set_exception(fout)
            self._wachtend.clear()

    def _verwerk(self, bericht: dict) -> None:
        soort = bericht.get("payloadType")
        payload = bericht.get("payload") or {}
        mid = bericht.get("clientMsgId")
        if soort == SPOT_EVENT:
            if payload.get("bid"):
                self._bid = prijs(payload["bid"])
            if payload.get("ask"):
                self._ask = prijs(payload["ask"])
            if self._bid and self._ask:
                self._koers_t = time.time()
                self._koers_event.set()
            return
        if (soort in (EXECUTION_EVENT, ORDER_ERROR_EVENT) and self._uitvoeringen is not None
                and self._wachters > 0):
            self._uitvoeringen.put_nowait((soort, payload, mid))
        if soort in (TOKEN_INVALIDATED_EVENT, CLIENT_DISCONNECT_EVENT, ACCOUNT_DISCONNECT_EVENT):
            _LOGGER.warning("cTrader meldt %s: %s", soort, payload.get("reason") or "")
            if self._ws is not None:
                asyncio.create_task(self._ws.close())
            return
        if mid and mid in self._wachtend:
            f = self._wachtend.pop(mid)
            if not f.done():
                if soort in (ERROR_RES, COMMON_ERROR, ORDER_ERROR_EVENT):
                    self._stats["fouten"] += 1
                    tekst = f"{payload.get('errorCode')}: {payload.get('description') or ''}".strip()
                    self._stats["laatste_fout"] = tekst[:200]
                    f.set_exception(VenueError(f"cTrader: {tekst}"))
                else:
                    f.set_result((soort, payload))

    async def _klop(self) -> None:
        while self.verbonden:
            await asyncio.sleep(HARTSLAG_S)
            try:
                await self._ws.send_json({"payloadType": HEARTBEAT, "payload": {}})
            except Exception:  # noqa: BLE001
                return

    async def _verzoek(self, soort: int, payload: dict, verwacht: int | None = None,
                       timeout: float = VERZOEK_TIMEOUT_S) -> dict:
        if self._ws is None or self._ws.closed:
            raise VenueError("Geen verbinding met cTrader.")
        mid = f"gs{next(self._ids)}"
        f = asyncio.get_running_loop().create_future()
        self._wachtend[mid] = f
        self._stats["verzoeken"] += 1
        await self._ws.send_json({"clientMsgId": mid, "payloadType": soort, "payload": payload})
        try:
            ontvangen, antw = await asyncio.wait_for(f, timeout)
        except asyncio.TimeoutError as err:
            self._wachtend.pop(mid, None)
            raise VenueError(f"cTrader antwoordde niet op {soort} binnen {timeout:.0f} s") from err
        if verwacht is not None and ontvangen != verwacht and ontvangen != EXECUTION_EVENT:
            raise VenueError(f"cTrader: onverwacht antwoord {ontvangen} op {soort}")
        return antw

    async def _klaar(self) -> None:
        if not self.verbonden:
            if self._lezer is not None:
                self._stats["herverbindingen"] += 1
            self._ws = None
            await self._verbind()

    async def sluit_verbinding(self) -> None:
        for taak in (self._hartslag, self._lezer):
            if taak is not None:
                taak.cancel()
        if self._ws is not None:
            await self._ws.close()
        self._ws = None

    # -- lezen --------------------------------------------------------------- #

    def request_stats(self) -> dict:
        return {**self._stats, "verbonden": self.verbonden, "ctid": self.ctid,
                "symbool_id": self.symbol_id,
                "koers_leeftijd_s": round(time.time() - self._koers_t, 1) if self._koers_t else None}

    async def quote(self, symbol: str) -> VenueQuote:
        await self._klaar()
        if not (self._bid and self._ask):
            try:
                await asyncio.wait_for(self._koers_event.wait(), 5)
            except asyncio.TimeoutError as err:
                raise VenueError("Nog geen koers van cTrader (markt gesloten?)") from err
        leeftijd = time.time() - self._koers_t
        return VenueQuote(
            bid=self._bid, ask=self._ask,
            time=datetime.fromtimestamp(self._koers_t, tz=timezone.utc),
            tradeable=leeftijd < KOERS_OUD_S,
        )

    async def candles(self, symbol: str, timeframe: str, count: int) -> Candles:
        await self._klaar()
        periode = PERIODES.get(timeframe)
        if periode is None:
            raise VenueError(f"cTrader kent tijdvak {timeframe} niet")
        nu = int(time.time() * 1000)
        # Ruim terug (weekend, dagpauze); daarna de laatste ``count``.
        terug = int(TIJDVAK_S[timeframe] * 1000 * max(count, 1) * 3 + 3 * 86400 * 1000)
        antw = await self._verzoek(TRENDBARS_REQ, {
            "ctidTraderAccountId": self.ctid, "symbolId": self.symbol_id,
            "period": periode, "fromTimestamp": nu - terug, "toTimestamp": nu,
            "count": int(count),
        }, TRENDBARS_RES)
        candles = trendbars_naar_candles(antw.get("trendbar") or [])
        if len(candles) > count:
            n = len(candles) - count
            candles = Candles(
                timestamp=candles.timestamp[n:], open=candles.open[n:],
                high=candles.high[n:], low=candles.low[n:], close=candles.close[n:],
                volume=candles.volume[n:],
            )
        return candles

    async def _trader(self) -> dict:
        antw = await self._verzoek(TRADER_REQ, {"ctidTraderAccountId": self.ctid}, TRADER_RES)
        return antw.get("trader") or {}

    async def _ruwe_posities(self) -> list[dict]:
        antw = await self._verzoek(RECONCILE_REQ, {"ctidTraderAccountId": self.ctid},
                                   RECONCILE_RES)
        return [p for p in antw.get("position") or []
                if int((p.get("tradeData") or {}).get("symbolId") or 0) == self.symbol_id]

    async def _ongerealiseerd(self) -> dict[str, float]:
        try:
            antw = await self._verzoek(UNREALIZED_PNL_REQ, {"ctidTraderAccountId": self.ctid},
                                       UNREALIZED_PNL_RES)
        except VenueError:
            return {}
        schaal = 10 ** int(antw.get("moneyDigits") or 2)
        return {str(p.get("positionId")): float(p.get("netUnrealizedPnL") or 0) / schaal
                for p in antw.get("positionUnrealizedPnL") or []}

    async def account(self) -> AccountSnapshot:
        await self._klaar()
        trader = await self._trader()
        schaal = 10 ** int(trader.get("moneyDigits") or 2)
        saldo = float(trader.get("balance") or 0) / schaal
        posities = await self._verzoek(RECONCILE_REQ, {"ctidTraderAccountId": self.ctid},
                                       RECONCILE_RES)
        alle = posities.get("position") or []
        marge = sum(float(p.get("usedMargin") or 0) / 10 ** int(p.get("moneyDigits") or 2)
                    for p in alle)
        open_pnl = sum((await self._ongerealiseerd()).values()) if alle else 0.0
        equity = saldo + open_pnl
        return AccountSnapshot(
            balance=round(saldo, 2), equity=round(equity, 2), margin_used=round(marge, 2),
            margin_available=round(equity - marge, 2), currency=self.valuta or "USD",
            open_position_count=len(alle),
        )

    def _naar_positie(self, p: dict, pnl: dict[str, float]) -> VenuePosition:
        td = p.get("tradeData") or {}
        kant = zijde(td.get("tradeSide"))
        huidig = (self._bid if kant == "buy" else self._ask) or None
        geopend = td.get("openTimestamp")
        return VenuePosition(
            ticket=str(p.get("positionId")), symbol=self.symbol_name, side=kant,
            units=float(td.get("volume") or 0) / VOLUME_PER_OZ,
            open_price=float(p.get("price") or 0), current_price=huidig,
            stop_loss=p.get("stopLoss"), take_profit=p.get("takeProfit"),
            unrealised_pnl=pnl.get(str(p.get("positionId"))),
            open_time=(datetime.fromtimestamp(int(geopend) / 1000, tz=timezone.utc)
                       if geopend else None),
            comment=td.get("comment") or td.get("label"),
        )

    async def positions(self, symbol: str | None = None) -> list[VenuePosition]:
        await self._klaar()
        ruw = await self._ruwe_posities()
        pnl = await self._ongerealiseerd() if ruw else {}
        return [self._naar_positie(p, pnl) for p in ruw]

    # -- handelen ------------------------------------------------------------ #

    def _bewaak(self, ounces: float) -> None:
        if not self.supports_trading:
            raise TradingDisabledError("Handel staat uit voor deze venue.")
        if ounces > self.max_units:
            raise VenueError(f"{ounces} oz boven het plafond van {self.max_units} oz")

    async def _wacht_uitvoering(self, mid: str | None, positie_id: str | None,
                                commentaar: str | None, timeout: float) -> tuple | None:
        """Wacht op de uitvoering die bij deze order hoort: zelfde berichtnummer,
        positie of commentaar. Geeft (soort, payload) of None bij een timeout."""
        eind = time.monotonic() + timeout
        try:
            return await self._wacht_lus(eind, mid, positie_id, commentaar)
        finally:
            self._wachters = max(0, self._wachters - 1)

    async def _wacht_lus(self, eind, mid, positie_id, commentaar):
        while True:
            rest = eind - time.monotonic()
            if rest <= 0 or self._uitvoeringen is None:
                return None
            try:
                soort, payload, bericht_mid = await asyncio.wait_for(self._uitvoeringen.get(), rest)
            except asyncio.TimeoutError:
                return None
            positie = payload.get("position") or {}
            order = payload.get("order") or {}
            td = positie.get("tradeData") or order.get("tradeData") or {}
            if (
                (mid and bericht_mid == mid)
                or (positie_id and str(positie.get("positionId") or order.get("positionId")) == positie_id)
                or (commentaar and td.get("comment") == commentaar)
            ):
                if soort == ORDER_ERROR_EVENT:
                    return soort, payload
                soort_uitv = payload.get("executionType")
                if soort_uitv in GEVULD or soort_uitv in GEWEIGERD or soort_uitv in GEANNULEERD:
                    return soort, payload

    async def _stuur_order(self, soort: int, payload: dict) -> str:
        if self._ws is None or self._ws.closed:
            self._wachters = max(0, self._wachters - 1)
            raise VenueError("Geen verbinding met cTrader.")
        # Eerst de rij leegmaken: oude uitvoeringen horen niet bij deze order.
        while self._uitvoeringen is not None and not self._uitvoeringen.empty():
            self._uitvoeringen.get_nowait()
        mid = f"gs{next(self._ids)}"
        self._stats["verzoeken"] += 1
        await self._ws.send_json({"clientMsgId": mid, "payloadType": soort, "payload": payload})
        return mid

    @staticmethod
    def _fout(payload: dict) -> str:
        return (f"{payload.get('errorCode') or payload.get('executionType')}: "
                f"{payload.get('description') or ''}").strip()

    async def place_order(self, symbol: str, side: str, units: float,
                          stop_loss: float | None = None, take_profit: float | None = None,
                          comment: str = "") -> OrderResult:
        if side not in ("buy", "sell"):
            raise VenueError(f"Ongeldige richting: {side}")
        self._bewaak(units)
        await self._klaar()
        q = await self.quote(symbol)
        if not q.tradeable:
            return OrderResult(success=False, error="Markt is momenteel niet verhandelbaar")
        gevraagd = q.ask if side == "buy" else q.bid
        volume = naar_volume(units, int(self.symbool.get("stepVolume") or VOLUME_PER_OZ),
                             int(self.symbool.get("minVolume") or VOLUME_PER_OZ))
        if volume <= 0:
            return OrderResult(success=False, requested_price=gevraagd,
                               error=f"{units} oz is minder dan de kleinste order (1 oz)")
        order = {
            "ctidTraderAccountId": self.ctid, "symbolId": self.symbol_id,
            "orderType": 1, "tradeSide": 1 if side == "buy" else 2, "volume": volume,
            "label": "gold_scalper", "comment": (comment or "")[:100],
        }
        # Bij een marktorder alleen RELATIEVE stop en doel (in 1/100.000),
        # gerekend vanaf de vulprijs - de afstand blijft wat de strategie vroeg.
        if stop_loss is not None:
            order["relativeStopLoss"] = max(1, int(round(abs(gevraagd - stop_loss) * PRIJS_SCHAAL)))
        if take_profit is not None:
            order["relativeTakeProfit"] = max(1, int(round(abs(take_profit - gevraagd) * PRIJS_SCHAAL)))
        start = time.perf_counter()
        self._wachters += 1
        mid = await self._stuur_order(NEW_ORDER_REQ, order)
        uitkomst = await self._wacht_uitvoering(mid, None, order["comment"] or None, ORDER_TIMEOUT_S)
        latentie = round((time.perf_counter() - start) * 1000, 2)
        if uitkomst is None:
            return OrderResult(success=False, requested_price=gevraagd, latency_ms=latentie,
                               unconfirmed=True, client_ref=comment or None,
                               error="Geen bevestiging van cTrader binnen de wachttijd")
        soort, payload = uitkomst
        if soort == ORDER_ERROR_EVENT or payload.get("executionType") not in GEVULD:
            return OrderResult(success=False, requested_price=gevraagd, latency_ms=latentie,
                               error=self._fout(payload))
        deal = payload.get("deal") or {}
        positie = payload.get("position") or {}
        return OrderResult(
            success=True, ticket=str(positie.get("positionId") or deal.get("positionId")),
            fill_price=float(deal.get("executionPrice") or positie.get("price") or gevraagd),
            requested_price=gevraagd,
            units=float(deal.get("filledVolume") or volume) / VOLUME_PER_OZ,
            latency_ms=latentie, client_ref=comment or None,
        )

    async def close(self, ticket: str, units: float | None = None) -> OrderResult:
        if not self.supports_trading:
            raise TradingDisabledError("Handel staat uit voor deze venue.")
        await self._klaar()
        posities = {str(p.get("positionId")): p for p in await self._ruwe_posities()}
        positie = posities.get(str(ticket))
        if positie is None:
            return OrderResult(success=False, ticket=ticket, error="Positie niet (meer) open")
        totaal = int((positie.get("tradeData") or {}).get("volume") or 0)
        volume = totaal if units is None else min(totaal, naar_volume(units))
        if volume <= 0:
            return OrderResult(success=False, ticket=ticket, error="Te klein om te sluiten")
        start = time.perf_counter()
        self._wachters += 1
        mid = await self._stuur_order(CLOSE_POSITION_REQ, {
            "ctidTraderAccountId": self.ctid, "positionId": int(ticket), "volume": volume})
        uitkomst = await self._wacht_uitvoering(mid, str(ticket), None, ORDER_TIMEOUT_S)
        latentie = round((time.perf_counter() - start) * 1000, 2)
        if uitkomst is None:
            return OrderResult(success=False, ticket=ticket, latency_ms=latentie,
                               unconfirmed=True, error="Geen bevestiging van het sluiten")
        soort, payload = uitkomst
        if soort == ORDER_ERROR_EVENT or payload.get("executionType") not in GEVULD:
            return OrderResult(success=False, ticket=ticket, latency_ms=latentie,
                               error=self._fout(payload))
        deal = payload.get("deal") or {}
        return OrderResult(success=True, ticket=ticket,
                           fill_price=float(deal.get("executionPrice") or 0) or None,
                           units=volume / VOLUME_PER_OZ, latency_ms=latentie)

    async def _wijzig(self, ticket: str, stop_loss: float | None,
                      take_profit: float | None) -> OrderResult:
        if not self.supports_trading:
            raise TradingDisabledError("Handel staat uit voor deze venue.")
        await self._klaar()
        payload = {"ctidTraderAccountId": self.ctid, "positionId": int(ticket)}
        if stop_loss is not None:
            payload["stopLoss"] = round(float(stop_loss), 2)
        if take_profit is not None:
            payload["takeProfit"] = round(float(take_profit), 2)
        try:
            await self._verzoek(AMEND_SLTP_REQ, payload, None)
        except VenueError as err:
            return OrderResult(success=False, ticket=ticket, error=str(err))
        return OrderResult(success=True, ticket=ticket)

    async def _huidig_niveau(self, ticket: str, veld: str):
        for p in await self._ruwe_posities():
            if str(p.get("positionId")) == str(ticket):
                return p.get(veld)
        return None

    async def modify_stop(self, ticket: str, stop_loss: float,
                          take_profit: float | None = None) -> OrderResult:
        # Stop en doel gaan samen: het doel niet meesturen haalt het weg.
        if take_profit is None:
            take_profit = await self._huidig_niveau(ticket, "takeProfit")
        return await self._wijzig(ticket, stop_loss, take_profit)

    async def modify_target(self, ticket: str, take_profit: float,
                            stop_loss: float | None = None) -> OrderResult:
        if stop_loss is None:
            stop_loss = await self._huidig_niveau(ticket, "stopLoss")
        return await self._wijzig(ticket, stop_loss, take_profit)

    # -- afstemming ---------------------------------------------------------- #

    async def _deals(self, van: datetime, tot: datetime) -> list[dict]:
        antw = await self._verzoek(DEAL_LIST_REQ, {
            "ctidTraderAccountId": self.ctid, "fromTimestamp": _ms(van),
            "toTimestamp": _ms(tot), "maxRows": 5000}, DEAL_LIST_RES, timeout=20)
        return [d for d in antw.get("deal") or [] if int(d.get("symbolId") or 0) == self.symbol_id]

    async def _deals_van_positie(self, positie_id: str, van: datetime, tot: datetime) -> list[dict]:
        antw = await self._verzoek(DEALS_BY_POSITION_REQ, {
            "ctidTraderAccountId": self.ctid, "positionId": int(positie_id),
            "fromTimestamp": _ms(van), "toTimestamp": _ms(tot)}, DEALS_BY_POSITION_RES)
        return antw.get("deal") or []

    async def transactions(self, van: datetime, tot: datetime) -> list:
        """Alle sluitende deals in het venster als IG-transacties (zie
        ``deal_naar_transactie``)."""
        await self._klaar()
        deals = await self._deals(van, tot)
        openingen = {str(d.get("positionId")): d for d in deals if not d.get("closePositionDetail")}
        ontbreekt = {str(d.get("positionId")) for d in deals
                     if d.get("closePositionDetail") and str(d.get("positionId")) not in openingen}
        for positie_id in list(ontbreekt)[:50]:
            try:
                eigen = await self._deals_van_positie(positie_id, van - timedelta(days=7), tot)
            except VenueError:
                continue
            for d in eigen:
                if not d.get("closePositionDetail"):
                    openingen[positie_id] = d
                    break
        uit = []
        for d in deals:
            t = deal_naar_transactie(d, openingen.get(str(d.get("positionId"))), self.valuta)
            if t is not None:
                uit.append(t)
        return uit

    async def closed_deal(self, ticket: str, open_price: float | None = None,
                          side: str | None = None, around: datetime | None = None,
                          units: float | None = None, open_time=None,
                          own_close_times=None) -> dict | None:
        """De werkelijke afwikkeling van een gesloten positie, rechtstreeks op
        positienummer (geen zoekwerk op prijs zoals bij IG)."""
        await self._klaar()
        nu = datetime.now(timezone.utc)
        midden = around or nu
        try:
            deals = await self._deals_van_positie(str(ticket).split("-")[0],
                                                  midden - timedelta(days=7), nu)
        except VenueError:
            return None
        # Terugval: de algemene dealslijst rond het sluitmoment (gemeten 14-10:
        # de lijst per positie gaf één deal terug waar er twee waren).
        if not any(d.get("closePositionDetail") for d in deals) or not any(
                not d.get("closePositionDetail") for d in deals):
            try:
                rond = await self._deals(midden - timedelta(days=2), nu)
            except VenueError:
                rond = []
            pid = str(ticket).split("-")[0]
            bekend = {d.get("dealId") for d in deals}
            deals = deals + [d for d in rond if str(d.get("positionId")) == pid
                             and d.get("dealId") not in bekend]
        opening = next((d for d in deals if not d.get("closePositionDetail")), None)
        sluitend = [d for d in deals if d.get("closePositionDetail")]
        if not sluitend:
            return None
        doel = _ms(midden)
        deal = min(sluitend, key=lambda d: abs(int(d.get("executionTimestamp") or 0) - doel))
        tx = deal_naar_transactie(deal, opening, self.valuta)
        return {
            "exit_price": float(tx["closeLevel"]),
            "matched_on": "ticket",
            "candidates": len(sluitend),
            "conversion_rate": 1.0 if self.valuta == "USD" else None,
            "profit_account": tx["profitAndLoss"],
            "currency": self.valuta,
            "size": float(tx["size"]),
            "open_price": float(tx["openLevel"]) if tx["openLevel"] is not None else None,
            "closed_at": tx["dateUtc"],
            "opened_at": tx["openDateUtc"],
            "reference": tx["reference"],
        }

    def describe(self) -> dict:
        return {**super().describe(), "omgeving": self.environment, "symbool": self.symbol_name}
