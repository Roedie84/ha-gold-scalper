"""Bitvavo: crypto spot, rechtstreeks vanuit Home Assistant (2.17.0).

Gevraagd 20-10: "Kunnen we bitvavo ook integreren? Om ook in crypto te
handelen?" en daarna "Direct compleet maken, zodat met alles gehandeld kan
worden en dat ik eventueel zou kunnen overstappen naar echt geld".

Wat anders is dan bij IG, Pepperstone en OANDA, en waarom het hier staat:

**Geen demo-account.** Bitvavo heeft geen oefenomgeving. Daarom twee standen:
``paper`` (live koersen en orderboek van Bitvavo, uitvoering gesimuleerd met de
echte Bitvavo-tarieven; er gaat nooit een order uit) en ``live`` (echte
orders, echt geld). Live loopt via dezelfde poort als elders: pas open als de
bewijsfase geslaagd is.

**Spot: alleen kopen.** Je kunt alleen verkopen wat je hebt. Een short is hier
geen positie maar een fout; ``place_order`` weigert ``sell`` daarom altijd.
Sluiten gebeurt met een marktverkoop van precies wat de bot kocht.

**Geen posities bij de exchange.** Bitvavo kent saldi, geen posities. Wat de
bot kocht, houdt hij zelf bij (het grootboek); elke regel is één koop, met de
order-ID als ticket. Het grootboek wordt na elke wijziging bewaard via
``bewaren`` en bij het opstarten teruggezet. Andere munten of eerder gekochte
munten van jezelf raakt de bot nooit aan: hij verkoopt nooit meer dan hij zelf
kocht en nooit meer dan er vrij is.

**Stop bij de exchange.** Na elke koop gaat er een ``stopLoss``-order naar
Bitvavo (verkopen zodra de beste bieding de stop raakt). Die blijft staan als
Home Assistant uitvalt. Een doel kan er niet tegelijk bij: Bitvavo reserveert
de munten voor de eerste verkooporder, een tweede zou geweigerd worden. Het
doel bewaakt de bot zelf.

**Kosten als percentage.** 0,25% (taker) in de laagste staffel op EUR-markten;
het werkelijke tarief komt uit ``/account/fees`` zodra er een sleutel is.

**Eenheden.** Eén unit is één munt. De rest van Gold Scalper rekent in units
(bij goud ounces); de lotfactor 100 is intern en rekent hier net zo door.

Sleutels: de API-sleutel en het geheim komen uit ``secrets.yaml`` (zie
config_flow). Maak in Bitvavo een sleutel met alleen **handelen** (en lezen),
nooit **opnemen**.
"""

from __future__ import annotations

import hashlib
import asyncio
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from urllib.parse import urlencode

from aiohttp import ClientError, ClientSession, ClientTimeout

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
from .execution_safety import BrokerLimits

_LOGGER = logging.getLogger(__name__)

BV_URL = "https://api.bitvavo.com/v2"
TIMEOUT = ClientTimeout(total=15)
#: Toegangsvenster van een ondertekend verzoek (ms); Bitvavo staat tot 60000 toe.
VENSTER_MS = 10000
#: Verplicht bij handelsverzoeken (sinds de nieuwe cryptoregels): een eigen
#: nummer per bot. Vast, zodat alle orders van Gold Scalper herkenbaar zijn.
OPERATOR_ID = 20261020
#: Naamruimte voor de clientOrderId: Bitvavo wil een UUID, de veiligheidslaag
#: geeft een eigen kenmerk mee. Deterministisch afgeleid, zodat een order na
#: een verbroken verbinding op datzelfde kenmerk terug te vinden is.
_NAAMRUIMTE = uuid.UUID("6f1d8c2e-6b0c-4f7a-9a52-3b1e2c0d9a17")

#: Standaardtarief (taker, laagste staffel, categorie A = crypto/EUR) tot het
#: werkelijke tarief bekend is.
TAKER_STANDAARD = 0.0025

#: Onze tijdsframes naar Bitvavo-intervallen. 3m bestaat bij Bitvavo niet; dat
#: bouwt de rest van Gold Scalper zelf uit 1m-bars.
INTERVAL = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "2h": "2h",
    "4h": "4h", "6h": "6h", "8h": "8h", "12h": "12h", "1d": "1d",
}
_SECONDEN = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
    "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200, "1d": 86400,
}
#: Bitvavo geeft hooguit zoveel candles per verzoek.
BV_MAX_CANDLES = 1440

class BitvavoOnzeker(VenueError):
    """Geen antwoord of een onleesbaar antwoord: het verzoek kan wel of niet
    zijn uitgevoerd. Een order wordt dan teruggezocht, nooit blind herhaald."""


#: Statussen van een order die niet meer kan uitvoeren.
_WEG = ("canceled", "expired", "rejected", "cancelled")

#: 2.18.0: saldi per API-sleutel, kort gedeeld tussen de markten van een mand
#: (``/balance`` weegt 5 bij de verzoeklimiet; twintig markten vroegen het
#: elk elke cyclus op).
_SALDI: dict[str, tuple[float, dict]] = {}
SALDI_GELDIG_S = 5.0

STAND_PAPER = "paper"
STAND_LIVE = "live"


def onderteken(geheim: str, tijdstip_ms: int, methode: str, pad_met_query: str,
               lichaam: str = "") -> str:
    """De handtekening van Bitvavo: HMAC-SHA256 (hex) over
    ``tijdstip + METHODE + /v2/pad?query + lichaam``, zonder scheidingstekens."""
    tekst = f"{tijdstip_ms}{methode.upper()}/v2{pad_met_query}{lichaam}"
    return hmac.new(geheim.encode(), tekst.encode(), hashlib.sha256).hexdigest()


def _dec(waarde) -> Decimal:
    return Decimal(str(waarde))


def naar_tekst(waarde: Decimal) -> str:
    """Een getal als gewone decimale tekst, zonder exponent (1E-7 weigert Bitvavo)."""
    tekst = format(waarde, "f")
    if "." in tekst:
        tekst = tekst.rstrip("0").rstrip(".")
    return tekst or "0"


def rond_af_omlaag(hoeveelheid: float, decimalen: int) -> Decimal:
    """Hoeveelheid naar beneden afronden op het toegestane aantal decimalen.

    Naar beneden: wie meer verkoopt dan hij heeft of meer koopt dan bedoeld,
    krijgt een weigering of een te grote positie.
    """
    stap = Decimal(1).scaleb(-max(0, int(decimalen)))
    return _dec(hoeveelheid).quantize(stap, rounding=ROUND_DOWN)


def rond_prijs(prijs: float, significant: int | None, tick: float | None = None) -> Decimal:
    """Prijs volgens de regels van de markt: een vaste tikgrootte als die er is,
    anders het toegestane aantal significante cijfers (``pricePrecision``)."""
    d = _dec(prijs)
    if tick and tick > 0:
        t = _dec(tick)
        return (d / t).quantize(Decimal(1)) * t
    sig = int(significant or 5)
    if d == 0:
        return d
    exponent = d.adjusted() - sig + 1
    return d.quantize(Decimal(1).scaleb(exponent))


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _vandaag_iso(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()


def _vul_uit_order(order: dict) -> tuple[float | None, float | None, float]:
    """(hoeveelheid, gemiddelde prijs, kosten in quote-valuta) van een (deels)
    uitgevoerde order. Kosten in de basisvaluta worden tegen de prijs omgerekend."""
    try:
        hoeveel = float(order.get("filledAmount") or 0)
        bedrag = float(order.get("filledAmountQuote") or 0)
    except (TypeError, ValueError):
        return None, None, 0.0
    if hoeveel <= 0:
        return 0.0, None, 0.0
    prijs = bedrag / hoeveel if bedrag > 0 else None
    kosten = 0.0
    for fill in order.get("fills") or []:
        try:
            fee = float(fill.get("fee") or 0)
        except (TypeError, ValueError):
            continue
        if fill.get("feeCurrency") and fill.get("feeCurrency") == order.get("market", "").split("-")[0]:
            fee *= float(fill.get("price") or prijs or 0)
        kosten += fee
    if not order.get("fills"):
        try:
            kosten = float(order.get("feePaid") or 0)
        except (TypeError, ValueError):
            kosten = 0.0
        basis = (order.get("market") or "").split("-")[0]
        if order.get("feeCurrency") == basis and prijs:
            kosten *= prijs
    return hoeveel, prijs, kosten


def _kosten_in_basis(order: dict) -> float:
    """Kosten die Bitvavo in de gekochte munt inhield: die munten heb je niet."""
    basis = (order.get("market") or "").split("-")[0]
    totaal = 0.0
    fills = order.get("fills") or []
    for fill in fills:
        if fill.get("feeCurrency") == basis:
            try:
                totaal += float(fill.get("fee") or 0)
            except (TypeError, ValueError):
                continue
    if not fills and order.get("feeCurrency") == basis:
        try:
            totaal = float(order.get("feePaid") or 0)
        except (TypeError, ValueError):
            totaal = 0.0
    return totaal


def _nieuwe_regel(markt: str, order: dict, kenmerk: str | None) -> dict:
    gevuld, prijs, kosten = _vul_uit_order(order)
    ticket = str(order.get("orderId"))
    return {
        "ticket": ticket, "market": markt,
        "units": max(0.0, float(gevuld or 0) - _kosten_in_basis(order)),
        "open_price": float(prijs or 0),
        "open_time": _vandaag_iso(order.get("created")) or datetime.now(timezone.utc).isoformat(),
        "open_fee": kosten, "comment": kenmerk, "client_order_id": order.get("clientOrderId"),
        "stop_order_id": None, "stop_loss": None, "take_profit": None,
    }


class BitvavoVenue(ExecutionVenue):
    """Bitvavo spot via de REST API v2, binnen het Home Assistant-proces."""

    name = "bitvavo"
    runs_in_process = True
    has_real_spread = True
    #: Spot: alleen kopen; zie de moduletekst.
    alleen_long = True
    #: Crypto handelt dag en nacht, ook in het weekend.
    altijd_open = True

    def __init__(
        self,
        session: ClientSession,
        market: str,
        api_key: str | None = None,
        api_secret: str | None = None,
        stand: str = STAND_PAPER,
        trading_enabled: bool = False,
        max_units: float = 1e12,
        max_inzet: float | None = None,
        posities: list[dict] | None = None,
        bewaren=None,
        operator_id: int = OPERATOR_ID,
    ) -> None:
        self._session = session
        self.market = (market or "").upper()
        if "-" not in self.market:
            raise ValueError(f"Bitvavo-markt '{market}' heeft de vorm BASIS-QUOTE, bijvoorbeeld BTC-EUR")
        self.basis, self.quote_valuta = self.market.split("-", 1)
        self._sleutel = api_key or ""
        self._geheim = api_secret or ""
        self.environment = stand if stand in (STAND_PAPER, STAND_LIVE) else STAND_PAPER
        self.supports_trading = bool(trading_enabled) and self.environment == STAND_LIVE
        self.max_units = float(max_units or 1e12)
        #: Hard plafond per koop in de quote-valuta (bijvoorbeeld euro's).
        self.max_inzet = float(max_inzet) if max_inzet else None
        self.operator_id = int(operator_id)
        self._bewaren = bewaren
        #: Het grootboek: ticket (order-ID van de koop) -> regel.
        self._grootboek: dict[str, dict] = {
            str(p["ticket"]): dict(p) for p in (posities or []) if p.get("ticket")
        }
        #: Gesloten posities (laatste 200), voor ``closed_deal``.
        self._gesloten: dict[str, dict] = {}
        self._markt: dict | None = None
        self._markt_tijd = 0.0
        self.taker = TAKER_STANDAARD
        self.maker: float | None = None
        self._tarief_bron = "standaard"
        self._tarief_tijd = 0.0
        self.ratelimit_resterend: int | None = None
        self._verzoeken = 0
        #: Kopen waarvan het antwoord uitbleef: ons kenmerk -> clientOrderId.
        self._onbevestigd: dict[str, str] = {}
        #: 2.18.0: de waarde van wat de andere markten van de mand kochten
        #: (callable, quote-valuta). Het vermogen is dan dat van de hele mand,
        #: zodat de daglimiet niet schrikt van een koop op een andere markt.
        self.mand_waarde = None

    # -- eigenschappen die de rest van Gold Scalper leest -------------------- #

    @property
    def instrument_currency(self) -> str:
        return self.quote_valuta

    @property
    def heeft_sleutel(self) -> bool:
        return bool(self._sleutel and self._geheim)

    @property
    def tarief_per_zijde(self) -> float:
        """Kosten per zijde als fractie van het bedrag (taker: marktorders)."""
        return float(self.taker)

    def markt_open(self, now: datetime) -> bool:   # noqa: ARG002 - zelfde vorm als elders
        return True

    def minuten_tot_sluiting(self, now: datetime) -> float:   # noqa: ARG002
        # Geen sluiting; groot genoeg dat geen enkele sluitregel ooit afgaat.
        return 10_000_000.0

    def minuten_tot_weekendsluiting(self, now: datetime) -> None:   # noqa: ARG002
        """2.22.0: crypto handelt 24/7; geen weekendsluiting."""
        return None

    def broker_limits(self) -> BrokerLimits:
        """Grenzen voor de veiligheidslaag, uit de marktgegevens."""
        m = self._markt or {}
        decimalen = int(m.get("quantityDecimals") or 8)
        try:
            minimum = float(m.get("minOrderInBaseAsset") or 0)
        except (TypeError, ValueError):
            minimum = 0.0
        return BrokerLimits(
            min_volume=minimum,
            max_volume=self.max_units,
            volume_step=10 ** -decimalen,
            min_stop_distance=0.0,
            # Prijzen rondt deze venue zelf af (significante cijfers); de
            # veiligheidslaag mag niets afronden.
            tick_size=0.0,
        )

    def posities_export(self) -> list[dict]:
        return [dict(r) for r in self._grootboek.values()]

    # -- verzoeken ------------------------------------------------------------ #

    async def _request(self, methode: str, pad: str, params: dict | None = None,
                       lichaam: dict | None = None, prive: bool = False):
        query = f"?{urlencode(params)}" if params else ""
        tekst = json.dumps(lichaam, separators=(",", ":")) if lichaam is not None else ""
        headers = {"Content-Type": "application/json"}
        if prive:
            if not self.heeft_sleutel:
                raise VenueError("Voor dit verzoek is een Bitvavo-API-sleutel nodig (secrets.yaml).")
            nu = int(time.time() * 1000)
            headers.update({
                "Bitvavo-Access-Key": self._sleutel,
                "Bitvavo-Access-Timestamp": str(nu),
                "Bitvavo-Access-Signature": onderteken(self._geheim, nu, methode, pad + query, tekst),
                "Bitvavo-Access-Window": str(VENSTER_MS),
            })
        url = f"{BV_URL}{pad}{query}"
        self._verzoeken += 1
        try:
            async with self._session.request(
                methode, url, headers=headers, timeout=TIMEOUT,
                data=tekst if lichaam is not None else None,
            ) as antwoord:
                try:
                    payload = await antwoord.json(content_type=None)
                except TypeError:
                    payload = await antwoord.json()
                rest = getattr(antwoord, "headers", {}) or {}
                try:
                    self.ratelimit_resterend = int(rest.get("bitvavo-ratelimit-remaining"))
                except (TypeError, ValueError):
                    pass
                if antwoord.status >= 400 or (isinstance(payload, dict) and payload.get("errorCode")):
                    code = payload.get("errorCode") if isinstance(payload, dict) else None
                    fout = payload.get("error") if isinstance(payload, dict) else str(payload)[:200]
                    soort = BitvavoOnzeker if antwoord.status >= 500 and code is None else VenueError
                    raise soort(_foutmelding(antwoord.status, code, fout))
                return payload
        except VenueError:
            raise
        except (ClientError, asyncio.TimeoutError, ValueError) as err:
            raise BitvavoOnzeker(f"Netwerkfout of time-out richting Bitvavo: {err!r}") from err

    def request_stats(self) -> dict:
        return {"verzoeken": self._verzoeken, "ratelimit_resterend": self.ratelimit_resterend}

    # -- marktgegevens -------------------------------------------------------- #

    async def markten(self) -> list[dict]:
        """Alle markten van Bitvavo (voor de keuzelijst)."""
        payload = await self._request("GET", "/markets")
        return [m for m in payload if isinstance(m, dict)] if isinstance(payload, list) else []

    async def markt(self, ververs: bool = False) -> dict:
        if self._markt is not None and not ververs and time.monotonic() - self._markt_tijd < 3600:
            return self._markt
        payload = await self._request("GET", "/markets", params={"market": self.market})
        rij = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(rij, dict) or rij.get("market", "").upper() != self.market:
            raise VenueError(f"Bitvavo kent markt {self.market} niet")
        self._markt, self._markt_tijd = rij, time.monotonic()
        return rij

    async def ververs_tarief(self) -> None:
        """Het werkelijke tarief van deze rekening, hooguit eens per uur."""
        if not self.heeft_sleutel or time.monotonic() - self._tarief_tijd < 3600:
            return
        self._tarief_tijd = time.monotonic()
        try:
            payload = await self._request("GET", "/account/fees", params={"market": self.market}, prive=True)
            taker = float(payload.get("taker"))
            if 0 <= taker < 0.05:
                self.taker = taker
                self.maker = float(payload.get("maker")) if payload.get("maker") is not None else None
                self._tarief_bron = "rekening"
        except (VenueError, TypeError, ValueError, AttributeError) as err:
            _LOGGER.debug("Bitvavo-tarief niet op te halen: %s", err)

    async def quote(self, symbol: str | None = None) -> VenueQuote:
        payload = await self._request("GET", "/ticker/book", params={"market": self.market})
        try:
            bid, ask = float(payload["bid"]), float(payload["ask"])
        except (KeyError, TypeError, ValueError) as err:
            raise VenueError(f"Bitvavo gaf geen bieding en laat voor {self.market}") from err
        if bid <= 0 or ask <= 0 or ask < bid:
            raise VenueError(f"Onbruikbaar orderboek voor {self.market}: {bid} / {ask}")
        status = (self._markt or {}).get("status", "trading")
        return VenueQuote(bid=bid, ask=ask, time=datetime.now(timezone.utc),
                          tradeable=status == "trading")

    async def candles(self, symbol: str | None, timeframe: str, count: int) -> Candles:
        if timeframe not in INTERVAL:
            raise VenueError(f"Bitvavo kent tijdsframe '{timeframe}' niet; kies uit {list(INTERVAL)}")
        stap = _SECONDEN[timeframe]
        rijen: dict[int, list] = {}
        nodig = max(1, int(count))
        einde: int | None = None
        for _ in range(10):                      # hooguit 14.400 bars terug
            params = {"interval": INTERVAL[timeframe], "limit": min(BV_MAX_CANDLES, nodig + 1)}
            if einde is not None:
                params["end"] = einde
            payload = await self._request("GET", f"/{self.market}/candles", params=params)
            if not isinstance(payload, list) or not payload:
                break
            for r in payload:
                try:
                    rijen[int(r[0]) // 1000] = [int(r[0]) // 1000, float(r[1]), float(r[2]),
                                                float(r[3]), float(r[4]), float(r[5])]
                except (TypeError, ValueError, IndexError):
                    continue
            oudste = min(int(r[0]) for r in payload)
            if len(rijen) >= nodig + 1 or len(payload) < params["limit"]:
                break
            einde = oudste - 1
        nu = time.time()
        # De lopende candle hoort er niet bij: handelen op een waarde die nog
        # verandert.
        klaar = sorted(r for t, r in rijen.items() if t + stap <= nu)
        klaar = klaar[-nodig:]
        if not klaar:
            raise VenueError(f"Geen voltooide candles voor {self.market} op {timeframe}")
        return Candles(
            timestamp=[r[0] for r in klaar], open=[r[1] for r in klaar],
            high=[r[2] for r in klaar], low=[r[3] for r in klaar],
            close=[r[4] for r in klaar], volume=[r[5] for r in klaar],
        )

    # -- rekening --------------------------------------------------------------- #

    async def saldi(self, vers: bool = False) -> dict[str, tuple[float, float]]:
        """symbool -> (vrij, in orders). ``vers``: niet uit de gedeelde cache
        (vóór een order)."""
        sleutel = f"{id(self._session)}:{hashlib.sha256(self._sleutel.encode()).hexdigest()[:16]}"
        bewaard = _SALDI.get(sleutel)
        if not vers and bewaard and time.monotonic() - bewaard[0] < SALDI_GELDIG_S:
            return dict(bewaard[1])
        uit = await self._haal_saldi()
        _SALDI[sleutel] = (time.monotonic(), dict(uit))
        return uit

    async def _haal_saldi(self) -> dict[str, tuple[float, float]]:
        payload = await self._request("GET", "/balance", prive=True)
        uit = {}
        for r in payload if isinstance(payload, list) else []:
            try:
                uit[str(r.get("symbol")).upper()] = (float(r.get("available") or 0),
                                                     float(r.get("inOrder") or 0))
            except (TypeError, ValueError):
                continue
        return uit

    async def account(self) -> AccountSnapshot:
        saldi = await self.saldi()
        await self.ververs_tarief()
        geld_vrij, geld_order = saldi.get(self.quote_valuta, (0.0, 0.0))
        try:
            bid = (await self.quote()).bid
        except VenueError:
            bid = 0.0
        # Alleen het geld van deze markt en wat de bot zelf kocht; eigen munten
        # van de gebruiker en andere munten tellen niet mee.
        waarde_munt = sum(float(r.get("units") or 0) for r in self._grootboek.values()) * bid
        if callable(self.mand_waarde):
            try:
                waarde_munt += float(self.mand_waarde(self) or 0.0)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Mandwaarde niet te bepalen", exc_info=True)
        return AccountSnapshot(
            balance=geld_vrij + geld_order,
            equity=geld_vrij + geld_order + waarde_munt,
            margin_used=0.0,
            margin_available=geld_vrij,
            currency=self.quote_valuta,
            open_position_count=len(self._grootboek),
        )

    # -- grootboek -------------------------------------------------------------- #

    async def _bewaar(self) -> None:
        if self._bewaren is None:
            return
        try:
            uit = self._bewaren({"posities": self.posities_export(),
                                 "gesloten": {k: dict(v) for k, v in self._gesloten.items()}})
            if hasattr(uit, "__await__"):
                await uit
        except Exception:  # noqa: BLE001 - bewaren mag de handel nooit breken
            _LOGGER.exception("Bitvavo-grootboek niet bewaard")

    async def _order(self, order_id: str | None = None, client_id: str | None = None) -> dict | None:
        params = {"market": self.market}
        if client_id:
            params["clientOrderId"] = client_id
        elif order_id:
            params["orderId"] = order_id
        else:
            return None
        try:
            payload = await self._request("GET", "/order", params=params, prive=True)
        except VenueError as err:
            if "niet gevonden" in str(err):
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def _noteer_gesloten(self, ticket: str, regel: dict, prijs: float | None,
                         hoeveel: float, kosten: float, reden: str) -> None:
        self._gesloten[ticket] = {
            "exit_price": prijs, "size": hoeveel, "fee": kosten, "reden": reden,
            "open_price": regel.get("open_price"), "opened_at": regel.get("open_time"),
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "open_fee": regel.get("open_fee", 0.0),
        }
        if len(self._gesloten) > 200:
            for oud in list(self._gesloten)[:-200]:
                self._gesloten.pop(oud, None)

    async def positions(self, symbol: str | None = None) -> list[VenuePosition]:
        """De open posities van de bot. Een stop die bij Bitvavo is afgegaan,
        sluit de regel in het grootboek."""
        if self._onbevestigd and self.heeft_sleutel:
            await self._herstel_onbevestigd()
        if not self._grootboek:
            return []
        gewijzigd = False
        for ticket, regel in list(self._grootboek.items()):
            stop_id = regel.get("stop_order_id")
            if not stop_id or not self.heeft_sleutel:
                continue
            try:
                stop = await self._order(order_id=stop_id)
            except VenueError:
                continue
            if stop is None:
                continue
            status = stop.get("status")
            if status in ("filled", "partiallyFilled"):
                hoeveel, prijs, kosten = _vul_uit_order(stop)
                if status == "filled" or (hoeveel or 0) >= float(regel["units"]) * 0.999:
                    self._noteer_gesloten(ticket, regel, prijs, hoeveel or 0.0, kosten, "stop")
                    self._grootboek.pop(ticket, None)
                    gewijzigd = True
            elif status in _WEG:
                regel["stop_order_id"] = None
                regel["stop_loss"] = None
                gewijzigd = True
        if gewijzigd:
            await self._bewaar()
        try:
            mid = (await self.quote()).bid
        except VenueError:
            mid = None
        uit = []
        for ticket, regel in self._grootboek.items():
            prijs = float(regel["open_price"])
            units = float(regel["units"])
            uit.append(VenuePosition(
                ticket=ticket, symbol=self.market, side="buy", units=units,
                open_price=prijs, current_price=mid,
                stop_loss=regel.get("stop_loss"), take_profit=regel.get("take_profit"),
                unrealised_pnl=(mid - prijs) * units if mid else None,
                open_time=datetime.fromisoformat(regel["open_time"]) if regel.get("open_time") else None,
                comment=regel.get("comment"),
            ))
        return uit

    # -- handelen ----------------------------------------------------------------- #

    def _guard(self) -> None:
        if not self.supports_trading or self.environment != STAND_LIVE:
            raise TradingDisabledError(
                "Handel staat uit voor Bitvavo. Alleen de stand 'live' plaatst orders, "
                "en pas nadat de bewijsfase geslaagd is."
            )

    def client_order_id(self, kenmerk: str) -> str:
        return str(uuid.uuid5(_NAAMRUIMTE, kenmerk)) if kenmerk else str(uuid.uuid4())

    async def place_order(
        self, symbol: str, side: str, units: float,
        stop_loss: float | None = None, take_profit: float | None = None, comment: str = "",
    ) -> OrderResult:
        if side != "buy":
            # Spot kent geen short. Hier stranden, niet bij Bitvavo.
            raise VenueError("Bitvavo spot: alleen kopen; een short kan niet.")
        self._guard()
        markt = await self.markt()
        if markt.get("status") != "trading":
            return OrderResult(success=False, error=f"Markt {self.market} handelt nu niet ({markt.get('status')})")
        hoeveel = rond_af_omlaag(min(float(units), self.max_units), int(markt.get("quantityDecimals") or 8))
        q = await self.quote()
        bedrag = float(hoeveel) * q.ask
        # Spot: niet meer kopen dan er vrij geld is (met ruimte voor het tarief).
        try:
            vrij_geld = (await self.saldi(vers=True)).get(self.quote_valuta, (0.0, 0.0))[0]
        except VenueError:
            vrij_geld = None
        if vrij_geld is not None and bedrag > vrij_geld * (1 - self.taker - 0.005):
            hoeveel = rond_af_omlaag(vrij_geld * (1 - self.taker - 0.005) / q.ask,
                                     int(markt.get("quantityDecimals") or 8))
            bedrag = float(hoeveel) * q.ask
        if self.max_inzet and bedrag > self.max_inzet:
            hoeveel = rond_af_omlaag(self.max_inzet / q.ask, int(markt.get("quantityDecimals") or 8))
            bedrag = float(hoeveel) * q.ask
        try:
            min_basis = float(markt.get("minOrderInBaseAsset") or 0)
            min_quote = float(markt.get("minOrderInQuoteAsset") or 0)
        except (TypeError, ValueError):
            min_basis = min_quote = 0.0
        if hoeveel <= 0 or float(hoeveel) < min_basis or bedrag < min_quote:
            return OrderResult(
                success=False, requested_price=q.ask,
                error=(f"Order te klein voor Bitvavo: {naar_tekst(hoeveel)} {self.basis} "
                       f"({bedrag:.2f} {self.quote_valuta}); minimaal {min_basis} {self.basis} "
                       f"en {min_quote} {self.quote_valuta}"),
            )
        client_id = self.client_order_id(comment)
        lichaam = {
            "market": self.market, "side": "buy", "orderType": "market",
            "amount": naar_tekst(hoeveel), "clientOrderId": client_id,
            "operatorId": self.operator_id, "responseRequired": True,
        }
        verzonden = time.perf_counter()
        try:
            order = await self._request("POST", "/order", lichaam=lichaam, prive=True)
        except BitvavoOnzeker as err:
            # Misschien wel uitgevoerd: terugzoeken op de clientOrderId.
            try:
                order = await self._order(client_id=client_id)
            except VenueError:
                order = None
            if order is None or not (_vul_uit_order(order)[0] or 0):
                if order is not None and order.get("status") in _WEG:
                    return OrderResult(success=False, requested_price=q.ask,
                                       error=f"Order afgewezen ({order.get('status')})")
                self._onbevestigd[comment] = client_id
                return OrderResult(success=False, unconfirmed=True, requested_price=q.ask,
                                   error=str(err), client_ref=comment)
        except VenueError as err:
            # Een duidelijk nee van Bitvavo (saldo, minimum, sleutel): niets gekocht.
            return OrderResult(success=False, requested_price=q.ask, error=str(err))
        latentie = round((time.perf_counter() - verzonden) * 1000, 2)
        gevuld, prijs, kosten = _vul_uit_order(order)
        if not gevuld:
            status = order.get("status")
            if status in ("new", "partiallyFilled", "awaitingTrigger"):
                self._onbevestigd[comment] = client_id
                return OrderResult(success=False, unconfirmed=True, requested_price=q.ask,
                                   latency_ms=latentie, client_ref=comment,
                                   error=f"Order {order.get('orderId')} nog niet uitgevoerd ({status})")
            return OrderResult(success=False, requested_price=q.ask, latency_ms=latentie,
                               error=f"Order niet uitgevoerd ({status})")
        ticket = str(order.get("orderId"))
        if ticket in self._grootboek:
            return OrderResult(success=True, ticket=ticket, fill_price=float(prijs or q.ask),
                               requested_price=q.ask, units=float(self._grootboek[ticket]["units"]),
                               latency_ms=latentie, client_ref=comment)
        # Kosten in de munt zelf: die munten zijn er niet.
        gevuld = max(0.0, float(gevuld) - _kosten_in_basis(order))
        regel = {
            "ticket": ticket, "market": self.market, "units": float(gevuld),
            "open_price": float(prijs or q.ask), "open_time": datetime.now(timezone.utc).isoformat(),
            "open_fee": kosten, "comment": comment, "client_order_id": client_id,
            "stop_order_id": None, "stop_loss": None, "take_profit": take_profit,
        }
        self._grootboek[ticket] = regel
        await self._bewaar()
        if stop_loss is not None:
            try:
                await self._zet_stop(regel, stop_loss)
            except VenueError as err:
                # De veiligheidslaag ziet de ontbrekende stop en probeert het
                # opnieuw, of sluit de positie.
                _LOGGER.warning("Bitvavo-stop na koop niet geplaatst: %s", err)
        return OrderResult(
            success=True, ticket=ticket, fill_price=float(prijs or q.ask), requested_price=q.ask,
            units=float(gevuld), latency_ms=latentie, client_ref=comment,
        )

    async def _zet_stop(self, regel: dict, stop_loss: float) -> None:
        markt = await self.markt()
        prijs = rond_prijs(stop_loss, markt.get("pricePrecision"), _tick(markt))
        hoeveel = rond_af_omlaag(float(regel["units"]), int(markt.get("quantityDecimals") or 8))
        lichaam = {
            "market": self.market, "side": "sell", "orderType": "stopLoss",
            "amount": naar_tekst(hoeveel), "triggerAmount": naar_tekst(prijs),
            "triggerType": "price", "triggerReference": "bestBid",
            "clientOrderId": str(uuid.uuid4()), "operatorId": self.operator_id,
            "responseRequired": True,
        }
        order = await self._request("POST", "/order", lichaam=lichaam, prive=True)
        regel["stop_order_id"] = str(order.get("orderId"))
        regel["stop_loss"] = float(prijs)
        await self._bewaar()

    async def _annuleer(self, order_id: str | None) -> None:
        if not order_id:
            return
        try:
            await self._request("DELETE", "/order", params={
                "market": self.market, "orderId": order_id, "operatorId": self.operator_id,
            }, prive=True)
        except VenueError as err:
            # Al uitgevoerd of al weg: dat zegt de statuscontrole erna.
            _LOGGER.debug("Annuleren van %s: %s", order_id, err)

    async def _haal_stop_weg(self, regel: dict) -> tuple[str, dict | None]:
        """De stop van een positie intrekken en controleren dat hij weg is.

        ``("weg", None)``: geen stop meer, de munten zijn vrij.
        ``("gevuld", order)``: de stop ging net af; de positie is al dicht.
        ``("onzeker", None)``: de stop staat er mogelijk nog; niet verkopen,
        anders kan er twee keer verkocht worden.
        """
        stop_id = regel.get("stop_order_id")
        if not stop_id:
            return "weg", None
        await self._annuleer(stop_id)
        try:
            stop = await self._order(order_id=stop_id)
        except VenueError:
            return "onzeker", None
        status = (stop or {}).get("status")
        if stop is None or status in _WEG:
            regel["stop_order_id"] = None
            return "weg", None
        if status == "filled":
            return "gevuld", stop
        return "onzeker", None

    def _sluit_regel_door_stop(self, ticket: str, regel: dict, stop: dict) -> OrderResult:
        hoeveel, prijs, kosten = _vul_uit_order(stop)
        self._noteer_gesloten(ticket, regel, prijs, hoeveel or 0.0, kosten, "stop")
        self._grootboek.pop(ticket, None)
        return OrderResult(success=True, ticket=ticket, fill_price=prijs, units=hoeveel)

    async def modify_stop(self, ticket: str, stop_loss: float,
                          take_profit: float | None = None) -> OrderResult:
        self._guard()
        ticket = str(ticket)
        regel = self._grootboek.get(ticket)
        if regel is None:
            return OrderResult(success=False, ticket=ticket, error="Positie niet (meer) open")
        if take_profit is not None:
            regel["take_profit"] = take_profit
        markt = await self.markt()
        prijs = rond_prijs(stop_loss, markt.get("pricePrecision"), _tick(markt))
        if regel.get("stop_order_id"):
            try:
                await self._request("PUT", "/order", lichaam={
                    "market": self.market, "orderId": regel["stop_order_id"],
                    "triggerAmount": naar_tekst(prijs), "operatorId": self.operator_id,
                }, prive=True)
                regel["stop_loss"] = float(prijs)
                await self._bewaar()
                return OrderResult(success=True, ticket=ticket)
            except VenueError as err:
                _LOGGER.info("Bitvavo-stop aanpassen ging niet (%s); status controleren", err)
            # Eerst weten hoe de oude stop ervoor staat; nooit blind een
            # tweede stop ernaast.
            stand, stop = await self._haal_stop_weg(regel)
            if stand == "gevuld":
                self._sluit_regel_door_stop(ticket, regel, stop)
                await self._bewaar()
                return OrderResult(success=False, ticket=ticket, error="Positie al gesloten door de stop")
            if stand == "onzeker":
                return OrderResult(success=False, ticket=ticket,
                                   error="Oude stop niet zeker weg; stop niet verplaatst")
            regel["stop_loss"] = None
        try:
            await self._zet_stop(regel, stop_loss)
        except VenueError as err:
            await self._bewaar()
            return OrderResult(success=False, ticket=ticket, error=f"Stop niet geplaatst: {err}")
        return OrderResult(success=True, ticket=ticket)

    async def close(self, ticket: str, units: float | None = None) -> OrderResult:
        self._guard()
        ticket = str(ticket)
        regel = self._grootboek.get(ticket)
        if regel is None:
            return OrderResult(success=False, ticket=ticket, error="Positie niet (meer) open")
        markt = await self.markt()
        oude_stop = regel.get("stop_loss")
        # Eerst de stop weg, anders zitten de munten vast in die order.
        stand, stop = await self._haal_stop_weg(regel)
        if stand == "gevuld":
            uit = self._sluit_regel_door_stop(ticket, regel, stop)
            await self._bewaar()
            return uit
        if stand == "onzeker":
            return OrderResult(success=False, ticket=ticket,
                               error="Stop bij Bitvavo niet zeker ingetrokken; niet verkocht")
        regel["stop_loss"] = None

        async def stop_terug() -> None:
            if oude_stop and ticket in self._grootboek and not regel.get("stop_order_id"):
                try:
                    await self._zet_stop(regel, float(oude_stop))
                except VenueError as err:
                    _LOGGER.warning("Stop na (deel)verkoop niet teruggezet: %s", err)
            await self._bewaar()

        await self._bewaar()
        try:
            vrij = (await self.saldi(vers=True)).get(self.basis, (0.0, 0.0))[0]
        except VenueError as err:
            await stop_terug()
            return OrderResult(success=False, ticket=ticket, error=f"Saldo niet op te halen: {err}")
        voor = float(regel["units"])
        gewenst = voor if units is None else min(float(units), voor)
        hoeveel = rond_af_omlaag(min(gewenst, vrij), int(markt.get("quantityDecimals") or 8))
        if hoeveel <= 0:
            await stop_terug()
            return OrderResult(success=False, ticket=ticket,
                               error=f"Geen vrije {self.basis} om te verkopen")
        poging = int(regel.get("sluit_poging") or 0) + 1
        regel["sluit_poging"] = poging
        client_id = self.client_order_id(f"sluit:{ticket}:{poging}")
        await self._bewaar()
        verzonden = time.perf_counter()
        try:
            order = await self._request("POST", "/order", lichaam={
                "market": self.market, "side": "sell", "orderType": "market",
                "amount": naar_tekst(hoeveel), "clientOrderId": client_id,
                "operatorId": self.operator_id, "responseRequired": True,
            }, prive=True)
        except BitvavoOnzeker as err:
            try:
                order = await self._order(client_id=client_id)
            except VenueError:
                order = None
            if order is None:
                # Niet bekend bij Bitvavo of niet na te gaan: de munten zijn er
                # nog; de stop moet terug.
                await stop_terug()
                return OrderResult(success=False, ticket=ticket, error=str(err))
        except VenueError as err:
            await stop_terug()
            return OrderResult(success=False, ticket=ticket, error=str(err))
        latentie = round((time.perf_counter() - verzonden) * 1000, 2)
        gevuld, prijs, kosten = _vul_uit_order(order)
        if not gevuld:
            await stop_terug()
            return OrderResult(success=False, ticket=ticket, latency_ms=latentie,
                               error=f"Verkoop niet uitgevoerd ({order.get('status')})")
        rest = voor - float(gevuld)
        if rest <= max(float(markt.get("minOrderInBaseAsset") or 0), 1e-12):
            self._noteer_gesloten(ticket, regel, prijs, float(gevuld), kosten, "bot")
            self._grootboek.pop(ticket, None)
            await self._bewaar()
        else:
            # Deelverkoop: de aankoopkosten gaan naar rato mee.
            regel["open_fee"] = float(regel.get("open_fee") or 0.0) * rest / voor
            regel["units"] = rest
            await stop_terug()
        return OrderResult(success=True, ticket=ticket, fill_price=prijs,
                           units=float(gevuld), latency_ms=latentie)

    async def close_all(self, symbol: str | None = None) -> list[OrderResult]:
        uit = []
        for ticket in list(self._grootboek):
            try:
                uit.append(await self.close(ticket))
            except VenueError as err:
                uit.append(OrderResult(success=False, ticket=ticket, error=str(err)))
        return uit

    async def closed_deal(self, ticket: str, open_price: float | None = None,
                          side: str | None = None, around: datetime | None = None,
                          units: float | None = None, open_time=None,
                          own_close_times=None) -> dict | None:
        """De werkelijke afwikkeling van een gesloten positie (prijs en kosten)."""
        g = self._gesloten.get(str(ticket))
        if not g or g.get("exit_price") is None:
            return None
        size = float(g.get("size") or 0)
        open_p = float(g.get("open_price") or open_price or 0)
        kosten = float(g.get("fee") or 0) + float(g.get("open_fee") or 0)
        return {
            "exit_price": float(g["exit_price"]), "matched_on": "ticket", "candidates": 1,
            "conversion_rate": 1.0, "currency": self.quote_valuta,
            "profit_account": (float(g["exit_price"]) - open_p) * size - kosten,
            "size": size, "open_price": open_p, "closed_at": g.get("closed_at"),
            "opened_at": g.get("opened_at"), "reference": str(ticket), "fee": kosten,
        }

    async def _herstel_onbevestigd(self) -> None:
        """Kopen zonder antwoord terugzoeken op hun clientOrderId."""
        for kenmerk in list(self._onbevestigd):
            if self._onbevestigd[kenmerk].startswith("afgewezen:"):
                continue
            await self._zoek_op_kenmerk(kenmerk)

    async def _zoek_op_kenmerk(self, kenmerk: str) -> tuple[str, str | None]:
        """Een koop bij Bitvavo opzoeken op de clientOrderId die uit ons
        kenmerk volgt; werkt ook na een herstart (het geheugen is dan leeg)."""
        client_id = self._onbevestigd.get(kenmerk) or self.client_order_id(kenmerk)
        try:
            order = await self._order(client_id=client_id)
        except VenueError:
            return "UNKNOWN", None
        if order is None:
            return "UNKNOWN", None
        gevuld = _vul_uit_order(order)[0]
        if gevuld and order.get("side", "buy") == "buy":
            regel = _nieuwe_regel(self.market, order, kenmerk)
            ticket = regel["ticket"]
            self._grootboek.setdefault(ticket, regel)
            self._onbevestigd.pop(kenmerk, None)
            await self._bewaar()
            return "ACCEPTED", ticket
        if order.get("status") in _WEG:
            self._onbevestigd[kenmerk] = "afgewezen:" + client_id
            return "REJECTED", None
        return "UNKNOWN", None

    async def confirm_status(self, kenmerk: str) -> tuple[str, str | None]:
        """Voor de veiligheidslaag: is een onbevestigde koop uitgevoerd?"""
        for ticket, regel in self._grootboek.items():
            if regel.get("comment") == kenmerk:
                return "ACCEPTED", ticket
        waarde = self._onbevestigd.get(kenmerk)
        if waarde and waarde.startswith("afgewezen:"):
            self._onbevestigd.pop(kenmerk, None)
            return "REJECTED", None
        if not self.heeft_sleutel or not kenmerk:
            return "UNKNOWN", None
        stand, ticket = await self._zoek_op_kenmerk(kenmerk)
        if stand == "REJECTED":
            self._onbevestigd.pop(kenmerk, None)
        return stand, ticket

    async def zoek_order(self, kenmerk: str) -> VenuePosition | None:
        """Een koop terugvinden op ons eigen kenmerk (na een verbroken verbinding)."""
        for p in await self.positions():
            if p.comment == kenmerk:
                return p
        if not self.heeft_sleutel:
            return None
        stand, ticket = await self._zoek_op_kenmerk(kenmerk)
        if stand != "ACCEPTED":
            return None
        return next((p for p in await self.positions() if p.ticket == ticket), None)

    async def health(self) -> dict:
        uit = {"ok": True, "venue": self.name, "stand": self.environment, "markt": self.market,
               "handel_aan": self.supports_trading, "sleutel": self.heeft_sleutel,
               "tarief_taker": self.taker, "tarief_bron": self._tarief_bron}
        try:
            await self.quote()
            if self.heeft_sleutel:
                snapshot = await self.account()
                uit["balance"] = snapshot.balance
        except VenueError as err:
            uit.update(ok=False, error=str(err))
        return uit

    def describe(self) -> dict:
        return {
            **super().describe(), "markt": self.market, "stand": self.environment,
            "alleen_long": True, "tarief_taker": self.taker, "tarief_maker": self.maker,
            "tarief_bron": self._tarief_bron, "max_inzet": self.max_inzet,
            "open_posities_grootboek": len(self._grootboek),
        }


#: 2.18.0: munten die aan een munteenheid vastzitten. Daarop valt niets te
#: verdienen behalve kosten; die komen nooit in de mand.
STABIEL = frozenset({
    "USDT", "USDC", "EURC", "EURS", "DAI", "PYUSD", "FDUSD", "TUSD", "USDP", "BUSD",
    "EURT", "EURI", "USDE", "USDS", "RLUSD", "GUSD", "LUSD", "FRAX", "USD1",
})


def _toegestane_markten(markten: list[dict], quote: str) -> dict:
    """Markten in ``quote`` die handelen, een stoporder kennen en geen
    stablecoin zijn."""
    toegestaan = {}
    for m in markten:
        naam = str(m.get("market") or "").upper()
        if not naam.endswith(f"-{quote.upper()}") or m.get("status") != "trading":
            continue
        soorten = m.get("orderTypes")
        if soorten and "stopLoss" not in soorten:
            continue
        if naam.split("-")[0] in STABIEL:
            continue
        toegestaan[naam] = m
    return toegestaan


def _ticker_rijen(toegestaan: dict, tickers: list[dict]) -> list[dict]:
    rijen = []
    for t in tickers:
        naam = str(t.get("market") or "").upper()
        if naam not in toegestaan:
            continue
        try:
            volume = float(t.get("volumeQuote") or 0)
            bid, ask = float(t.get("bid") or 0), float(t.get("ask") or 0)
        except (TypeError, ValueError):
            continue
        if bid <= 0 or ask <= 0 or ask < bid:
            continue
        spread = (ask - bid) / ((ask + bid) / 2) * 100
        rijen.append({"market": naam, "volume": volume, "spread_pct": round(spread, 4),
                      "_spread": spread})
    return rijen


def spreads_uit_tickers(markten: list[dict], tickers: list[dict], quote: str,
                        min_volume: float) -> dict[str, float]:
    """2.24.0 (L-GS-025): de actuele spread (%) van elke markt die in de mand
    zou kunnen (met de helft van het minimumvolume als marge: het volume
    schommelt ook)."""
    rijen = _ticker_rijen(_toegestane_markten(markten, quote), tickers)
    return {r["market"]: r["_spread"] for r in rijen
            if r["volume"] >= float(min_volume) / 2}


def kies_markten(markten: list[dict], tickers: list[dict], quote: str, aantal: int,
                 min_volume: float, max_spread_pct: float,
                 verplicht: list[str] | None = None,
                 geweerd: list | None = None, mediaan=None) -> list[dict]:
    """2.18.0: de meest liquide markten voor de mand.

    Alleen markten in ``quote`` (EUR) die nu handelen en een stoporder kennen,
    geen stablecoins, met minstens ``min_volume`` handel in 24 uur en een
    spread van hooguit ``max_spread_pct`` procent. Gesorteerd op volume, de
    ``verplicht``-markten (de gekozen markt) altijd vooraan.

    2.24.0 (L-GS-025): ``mediaan`` (markt -> mediane spread over 24 uur, of
    ``None``) bepaalt de toelating als er genoeg waarnemingen zijn; anders
    telt de momentopname, zoals voorheen. ``spread_pct`` blijft de actuele
    spread; ``spread_toelating_pct`` en ``spread_bron`` zeggen waarop getoetst
    is.
    """
    rijen = _ticker_rijen(_toegestane_markten(markten, quote), tickers)
    for r in rijen:
        r.pop("_spread", None)
        med = None
        if mediaan is not None:
            try:
                med = mediaan(r["market"])
            except Exception:  # noqa: BLE001 - dan de momentopname
                med = None
        if med is not None:
            r["spread_mediaan_pct"] = round(float(med), 4)
            r["spread_toelating_pct"] = r["spread_mediaan_pct"]
            r["spread_bron"] = "mediaan_24u"
        else:
            r["spread_toelating_pct"] = r["spread_pct"]
            r["spread_bron"] = "moment"
    verplicht = [v.upper() for v in (verplicht or [])]
    goed = [r for r in rijen if r["volume"] >= min_volume
            and r["spread_toelating_pct"] <= max_spread_pct
            and r["market"] not in verplicht]
    goed.sort(key=lambda r: r["volume"], reverse=True)
    if geweerd is not None:
        # 2.22.0: genoeg volume maar een te brede spread: zichtbaar maken.
        weg = [r for r in rijen if r["volume"] >= min_volume
               and r["spread_toelating_pct"] > max_spread_pct and r["market"] not in verplicht]
        weg.sort(key=lambda r: r["volume"], reverse=True)
        geweerd.extend(weg)
    vooraan = [next((r for r in rijen if r["market"] == v), {"market": v, "volume": None, "spread_pct": None})
               for v in verplicht]
    return (vooraan + goed)[:max(len(vooraan), int(aantal))]


async def mand_toppers(venue: "BitvavoVenue", aantal: int, min_volume: float,
                       max_spread_pct: float, verplicht: list[str] | None = None,
                       geweerd: list | None = None) -> list[dict]:
    """De mand ophalen: twee publieke verzoeken (alle markten, alle tickers).

    2.24.0 (L-GS-025): heeft de venue een ``spread_historie`` (door de mand
    gezet), dan wordt deze momentopname daarin vastgelegd en toetst de keuze
    op de mediaan over 24 uur.
    """
    import time as _time

    markten = await venue.markten()
    tickers = await venue._request("GET", "/ticker/24h")
    if not isinstance(tickers, list):
        raise VenueError("Bitvavo gaf geen 24-uurs tickers")
    historie = getattr(venue, "spread_historie", None)
    mediaan = None
    if historie is not None:
        nu = _time.time()
        historie.waarneem(nu, spreads_uit_tickers(markten, tickers, venue.quote_valuta,
                                                  min_volume))
        mediaan = lambda markt: historie.mediaan(markt, nu)  # noqa: E731
    return kies_markten(markten, tickers, venue.quote_valuta, aantal, min_volume,
                        max_spread_pct, verplicht, geweerd=geweerd, mediaan=mediaan)


async def spread_monster(venue: "BitvavoVenue", min_volume: float) -> dict[str, float]:
    """2.24.0 (L-GS-025): één momentopname van de spreads (publiek, twee
    verzoeken) voor de spreadhistorie van de mand."""
    markten = await venue.markten()
    tickers = await venue._request("GET", "/ticker/24h")
    if not isinstance(tickers, list):
        raise VenueError("Bitvavo gaf geen 24-uurs tickers")
    return spreads_uit_tickers(markten, tickers, venue.quote_valuta, min_volume)


def _tick(markt: dict) -> float | None:
    try:
        t = float(markt.get("tickSize")) if markt.get("tickSize") not in (None, "") else None
    except (TypeError, ValueError):
        t = None
    return t if t and t > 0 else None


def _foutmelding(status: int, code, fout) -> str:
    bekend = {
        105: "te veel verzoeken; Bitvavo blokkeert een minuut",
        216: "onvoldoende saldo",
        240: "order niet gevonden",
        300: "authenticatie vereist",
        304: "verzoek buiten het toegangsvenster (klok?)",
        305: "API-sleutel niet actief",
        308: "handtekening in verkeerd formaat",
        309: "ongeldige handtekening (geheim?)",
        310: "deze sleutel mag niet handelen",
        312: "deze sleutel mag niet handelen",
    }
    try:
        uitleg = bekend.get(int(code)) if code is not None else None
    except (TypeError, ValueError):
        uitleg = None
    if code is not None and int(code) == 240:
        uitleg = "niet gevonden"
    tekst = f"Bitvavo HTTP {status}"
    if code is not None:
        tekst += f" (fout {code}"
        tekst += f": {uitleg})" if uitleg else ")"
    if fout:
        tekst += f": {fout}"
    return tekst
