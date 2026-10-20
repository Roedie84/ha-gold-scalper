"""2.17.0: Bitvavo (crypto spot) en de prijs-/eenheidsschaal.

Gevraagd 20-10: "Kunnen we bitvavo ook integreren? Om ook in crypto te
handelen?" en "Direct compleet maken, zodat met alles gehandeld kan worden en
dat ik eventueel zou kunnen overstappen naar echt geld, ik heb al een API".
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker import bitvavo as bv  # noqa: E402
from gold_scalper.broker.adapter import TradingDisabledError, VenueError, size_says_closed  # noqa: E402
from gold_scalper.strategy import schaal  # noqa: E402


# --------------------------------------------------------------------------- #
# Nagebootste Bitvavo
# --------------------------------------------------------------------------- #

class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status, self.headers = payload, status, {"bitvavo-ratelimit-remaining": "990"}

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Tijdsfout:
    async def __aenter__(self):
        raise asyncio.TimeoutError()

    async def __aexit__(self, *a):
        return False


MARKT = {"market": "BTC-EUR", "status": "trading", "base": "BTC", "quote": "EUR",
         "pricePrecision": 5, "minOrderInBaseAsset": "0.0001", "minOrderInQuoteAsset": "5",
         "quantityDecimals": 8, "orderTypes": ["market", "limit", "stopLoss"]}


class FakeBitvavo:
    """Houdt orders en saldi bij zoals Bitvavo dat doet (sterk vereenvoudigd)."""

    def __init__(self, bid=90000.0, ask=90010.0):
        self.storing = {}
        self.bid, self.ask = bid, ask
        self.calls: list[dict] = []
        self.orders: dict[str, dict] = {}
        self.saldo = {"EUR": [1000.0, 0.0], "BTC": [0.0, 0.0]}
        self._n = 0

    #: Storingen om na te bootsen: (methode, soort) -> aantal keer.
    storing: dict = {}

    def request(self, method, url, headers=None, timeout=None, data=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "data": data})
        lichaam_pre = json.loads(data) if data else {}
        sleutel = (method, lichaam_pre.get("side") or lichaam_pre.get("orderType"))
        soort = self.storing.get(sleutel) or self.storing.get((method, None))
        if soort:
            self.storing = {k: v for k, v in self.storing.items() if v is not soort}
            if soort == "time-out-na-uitvoeren":
                self._nieuw(lichaam_pre)
                return _Tijdsfout()
            if soort == "time-out":
                return _Tijdsfout()
            if soort == "saldo":
                return FakeResponse({"errorCode": 216, "error": "Insufficient balance"}, 400)
            if soort == "weigeren":
                return FakeResponse({"errorCode": 205, "error": "Invalid parameter"}, 400)
        pad = url.split("/v2", 1)[1]
        pad_zonder, _, query = pad.partition("?")
        q = dict(x.split("=", 1) for x in query.split("&") if x) if query else {}
        lichaam = json.loads(data) if data else {}
        if pad_zonder == "/markets":
            return FakeResponse([MARKT] if q.get("market") else [MARKT, {**MARKT, "market": "ETH-EUR"}])
        if pad_zonder == "/ticker/book":
            return FakeResponse({"market": "BTC-EUR", "bid": str(self.bid), "ask": str(self.ask)})
        if pad_zonder.endswith("/candles"):
            nu = int(time.time()) // 60 * 60
            rijen = [[(nu - i * 60) * 1000, "1", "2", "0.5", str(1.5 + i), "3"] for i in range(int(q.get("limit", 10)))]
            return FakeResponse(rijen)
        if pad_zonder == "/balance":
            return FakeResponse([{"symbol": k, "available": str(v[0]), "inOrder": str(v[1])}
                                 for k, v in self.saldo.items()])
        if pad_zonder == "/account/fees":
            return FakeResponse({"tier": 0, "volume": "0", "maker": "0.0015", "taker": "0.0025"})
        if pad_zonder == "/order" and method == "POST":
            return FakeResponse(self._nieuw(lichaam))
        if pad_zonder == "/order" and method == "GET":
            for o in self.orders.values():
                if o["orderId"] == q.get("orderId") or o.get("clientOrderId") == q.get("clientOrderId"):
                    return FakeResponse(o)
            return FakeResponse({"errorCode": 240, "error": "No order found"}, 404)
        if pad_zonder == "/order" and method == "DELETE":
            o = self.orders.get(q.get("orderId"))
            if o and o["status"] == "awaitingTrigger":
                o["status"] = "canceled"
                self.saldo["BTC"][0] += float(o["amount"])
                self.saldo["BTC"][1] -= float(o["amount"])
            return FakeResponse({"orderId": q.get("orderId")})
        if pad_zonder == "/order" and method == "PUT":
            o = self.orders[lichaam["orderId"]]
            o["triggerAmount"] = lichaam["triggerAmount"]
            return FakeResponse(o)
        return FakeResponse({"errorCode": 999, "error": "geen route"}, 404)

    def _nieuw(self, b):
        self._n += 1
        oid = f"O{self._n}"
        hoeveel = float(b["amount"])
        if b["orderType"] == "market":
            prijs = self.ask if b["side"] == "buy" else self.bid
            fee = hoeveel * prijs * 0.0025
            if b["side"] == "buy":
                self.saldo["EUR"][0] -= hoeveel * prijs + fee
                self.saldo["BTC"][0] += hoeveel
            else:
                self.saldo["BTC"][0] -= hoeveel
                self.saldo["EUR"][0] += hoeveel * prijs - fee
            o = {"orderId": oid, "clientOrderId": b.get("clientOrderId"), "market": b["market"],
                 "side": b["side"], "orderType": "market", "status": "filled", "amount": b["amount"],
                 "filledAmount": str(hoeveel), "filledAmountQuote": str(hoeveel * prijs),
                 "feePaid": str(fee), "feeCurrency": "EUR", "created": int(time.time() * 1000),
                 "fills": [{"amount": str(hoeveel), "price": str(prijs), "fee": str(fee),
                            "feeCurrency": "EUR"}]}
        else:
            self.saldo["BTC"][0] -= hoeveel
            self.saldo["BTC"][1] += hoeveel
            o = {"orderId": oid, "clientOrderId": b.get("clientOrderId"), "market": b["market"],
                 "side": b["side"], "orderType": b["orderType"], "status": "awaitingTrigger",
                 "amount": b["amount"], "filledAmount": "0", "filledAmountQuote": "0",
                 "triggerAmount": b["triggerAmount"], "fills": []}
        self.orders[oid] = o
        return o

    def stop_gaat_af(self, oid, prijs):
        o = self.orders[oid]
        hoeveel = float(o["amount"])
        o.update(status="filled", filledAmount=str(hoeveel), filledAmountQuote=str(hoeveel * prijs),
                 fills=[{"amount": str(hoeveel), "price": str(prijs), "fee": str(hoeveel * prijs * 0.0025),
                         "feeCurrency": "EUR"}])
        self.saldo["BTC"][1] -= hoeveel
        self.saldo["EUR"][0] += hoeveel * prijs


def venue(fake=None, live=True, bewaard=None, **kw):
    fake = fake or FakeBitvavo()
    v = bv.BitvavoVenue(fake, "btc-eur", api_key="k" * 64, api_secret="geheim",
                        stand=bv.STAND_LIVE if live else bv.STAND_PAPER,
                        trading_enabled=live, bewaren=(bewaard.append if bewaard is not None else None),
                        **kw)
    return v, fake


def laatste(fake, methode, pad):
    return [c for c in fake.calls if c["method"] == methode and pad in c["url"]][-1]


# --------------------------------------------------------------------------- #
# Ondertekening en afronding
# --------------------------------------------------------------------------- #

def test_handtekening_zoals_de_officiele_sdk():
    """De SDK ondertekent str(tijd) + methode + '/v2' + pad?query + compacte JSON."""
    lichaam = json.dumps({"market": "BTC-EUR", "side": "buy"}, separators=(",", ":"))
    tekst = "1548172481125POST/v2/order" + lichaam
    verwacht = hmac.new(b"geheim", tekst.encode(), hashlib.sha256).hexdigest()
    assert bv.onderteken("geheim", 1548172481125, "POST", "/order", lichaam) == verwacht


def test_een_ondertekend_verzoek_draagt_de_vier_kopregels():
    v, fake = venue()
    asyncio.run(v.saldi())
    kop = laatste(fake, "GET", "/balance")["headers"]
    assert {"Bitvavo-Access-Key", "Bitvavo-Access-Timestamp", "Bitvavo-Access-Signature",
            "Bitvavo-Access-Window"} <= set(kop)
    tekst = kop["Bitvavo-Access-Timestamp"] + "GET/v2/balance"
    assert kop["Bitvavo-Access-Signature"] == hmac.new(b"geheim", tekst.encode(), hashlib.sha256).hexdigest()


def test_publieke_gegevens_zonder_sleutel():
    fake = FakeBitvavo()
    v = bv.BitvavoVenue(fake, "BTC-EUR")
    q = asyncio.run(v.quote())
    assert q.bid == 90000.0 and q.spread == 10.0
    assert "Bitvavo-Access-Key" not in laatste(fake, "GET", "/ticker/book")["headers"]
    with pytest.raises(VenueError):
        asyncio.run(v.saldi())


def test_afronding_naar_beneden_en_zonder_exponent():
    assert bv.naar_tekst(bv.rond_af_omlaag(0.123456789, 8)) == "0.12345678"
    assert bv.naar_tekst(bv.rond_af_omlaag(1e-7, 8)) == "0.0000001"
    assert bv.naar_tekst(bv.rond_prijs(91234.567, 5)) == "91235"
    assert bv.naar_tekst(bv.rond_prijs(0.000012345678, 5)) == "0.000012346"


def test_candles_oplopend_zonder_de_lopende_candle():
    v, _ = venue(live=False)
    c = asyncio.run(v.candles(None, "1m", 50))
    assert len(c) == 50
    assert c.timestamp == sorted(c.timestamp)
    assert c.timestamp[-1] + 60 <= time.time()


def test_3m_bestaat_niet_bij_bitvavo():
    v, _ = venue(live=False)
    with pytest.raises(VenueError):
        asyncio.run(v.candles(None, "3m", 10))


def test_altijd_open():
    v, _ = venue(live=False)
    assert v.markt_open(datetime.now(timezone.utc)) is True
    assert v.minuten_tot_sluiting(datetime.now(timezone.utc)) > 1e6


# --------------------------------------------------------------------------- #
# Handelen
# --------------------------------------------------------------------------- #

def test_papier_plaatst_nooit_een_order():
    v, fake = venue(live=False)
    with pytest.raises(TradingDisabledError):
        asyncio.run(v.place_order("BTC-EUR", "buy", 0.001, stop_loss=89000))
    assert not any(c["method"] == "POST" for c in fake.calls)


def test_spot_weigert_een_short():
    v, fake = venue()
    with pytest.raises(VenueError):
        asyncio.run(v.place_order("BTC-EUR", "sell", 0.001, stop_loss=91000))
    assert not any(c["method"] == "POST" for c in fake.calls)


def test_kopen_zet_een_stop_bij_bitvavo_en_bewaart_het_grootboek():
    bewaard: list = []
    v, fake = venue(bewaard=bewaard)
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=88888.8, comment="gs-abc"))
    assert r.success and r.units == pytest.approx(0.002) and r.fill_price == pytest.approx(90010.0)
    koop = json.loads(fake.calls[[i for i, c in enumerate(fake.calls) if c["method"] == "POST"][0]]["data"])
    assert koop["orderType"] == "market" and koop["amount"] == "0.002"
    assert isinstance(koop["operatorId"], int)
    assert koop["clientOrderId"] == v.client_order_id("gs-abc")
    stop = json.loads(laatste(fake, "POST", "/order")["data"])
    assert stop["orderType"] == "stopLoss" and stop["side"] == "sell"
    assert stop["triggerAmount"] == "88889" and stop["triggerReference"] == "bestBid"
    pos = asyncio.run(v.positions())
    assert len(pos) == 1 and pos[0].side == "buy" and pos[0].stop_loss == 88889.0
    assert pos[0].comment == "gs-abc"
    assert bewaard and bewaard[-1]["posities"][0]["ticket"] == r.ticket


def test_te_kleine_order_wordt_niet_verstuurd():
    v, fake = venue()
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.00001, stop_loss=89000))
    assert not r.success and "te klein" in r.error
    assert not any(c["method"] == "POST" for c in fake.calls)


def test_nooit_meer_dan_de_maximale_inzet_of_het_vrije_geld():
    v, fake = venue(max_inzet=100.0)
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 1.0, stop_loss=89000))
    assert r.success and r.units * 90010 <= 100.0
    v2, fake2 = venue()
    fake2.saldo["EUR"] = [50.0, 0.0]
    r2 = asyncio.run(v2.place_order("BTC-EUR", "buy", 1.0, stop_loss=89000))
    assert r2.success and r2.units * 90010 <= 50.0


def test_sluiten_haalt_eerst_de_stop_weg_en_verkoopt_precies_de_positie():
    v, fake = venue()
    fake.saldo["BTC"] = [0.5, 0.0]                       # eigen munten van Ruud
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))
    stop_id = v._grootboek[r.ticket]["stop_order_id"]
    uit = asyncio.run(v.close(r.ticket))
    assert uit.success and uit.units == pytest.approx(0.002)
    assert fake.orders[stop_id]["status"] == "canceled"
    verkoop = json.loads(laatste(fake, "POST", "/order")["data"])
    assert verkoop["side"] == "sell" and verkoop["amount"] == "0.002"
    assert fake.saldo["BTC"][0] == pytest.approx(0.5)     # eigen munten onaangeroerd
    assert asyncio.run(v.positions()) == []
    deal = asyncio.run(v.closed_deal(r.ticket))
    assert deal["exit_price"] == pytest.approx(90000.0) and deal["fee"] > 0


def test_een_afgegane_stop_sluit_de_positie_in_het_grootboek():
    v, fake = venue()
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))
    fake.stop_gaat_af(v._grootboek[r.ticket]["stop_order_id"], 88990.0)
    assert asyncio.run(v.positions()) == []
    deal = asyncio.run(v.closed_deal(r.ticket))
    assert deal["exit_price"] == pytest.approx(88990.0)
    assert deal["profit_account"] < 0


def test_stop_verplaatsen():
    v, fake = venue()
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))
    asyncio.run(v.modify_stop(r.ticket, 89512.3))
    assert v._grootboek[r.ticket]["stop_loss"] == 89512.0
    assert json.loads(laatste(fake, "PUT", "/order")["data"])["triggerAmount"] == "89512"


def test_onbevestigde_koop_wordt_teruggevonden():
    v, fake = venue()
    asyncio.run(v.markt())
    kenmerk = "gs-zoek"
    # De koop kwam aan, het antwoord niet.
    fake._nieuw({"market": "BTC-EUR", "side": "buy", "orderType": "market", "amount": "0.002",
                 "clientOrderId": v.client_order_id(kenmerk)})
    v._onbevestigd[kenmerk] = v.client_order_id(kenmerk)
    pos = asyncio.run(v.positions())
    assert len(pos) == 1 and pos[0].comment == kenmerk
    assert asyncio.run(v.confirm_status(kenmerk))[0] == "ACCEPTED"


def test_het_grootboek_komt_terug_na_een_herstart():
    bewaard: list = []
    v, fake = venue(bewaard=bewaard)
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))
    v2 = bv.BitvavoVenue(fake, "BTC-EUR", api_key="k", api_secret="geheim",
                         stand=bv.STAND_LIVE, trading_enabled=True, posities=bewaard[-1]["posities"])
    assert [p.ticket for p in asyncio.run(v2.positions())] == [r.ticket]


# --------------------------------------------------------------------------- #
# De schaal
# --------------------------------------------------------------------------- #

def test_goud_blijft_precies_zoals_het_was():
    assert schaal.huidig().is_goud
    assert schaal.usd(0.6) == 0.6
    assert schaal.rond_prijs(4123.4567, 2) == round(4123.4567, 2)
    assert schaal.omlaag(3.37, 0.1) == 3.3
    assert schaal.rond_units(1.237, 2) == 1.24
    assert schaal.min_eenheden(1.0) == 1.0
    assert schaal.commissie_rondreis_per_unit(4000.0) == 0.0
    assert size_says_closed(0.004) and not size_says_closed(0.01)


def _met_schaal(s, f):
    async def run():
        schaal.zet(s)
        return f()
    return asyncio.run(run())


def test_crypto_schaal():
    s = schaal.voor_markt(90000.0, 1e-8, 0.0001, 0.0025)
    uit = _met_schaal(s, lambda: (
        schaal.usd(1.0), schaal.rond_prijs(88888.123456789, 2), schaal.omlaag(0.123456789123, 0.1),
        schaal.min_eenheden(1.0), schaal.commissie_rondreis_per_unit(90000.0),
        size_says_closed(0.003), size_says_closed(1e-9)))
    assert uit[0] == pytest.approx(22.5)
    assert uit[1] == pytest.approx(88888.123)
    assert uit[2] == pytest.approx(0.12345678)
    assert uit[3] == 0.0001
    assert uit[4] == pytest.approx(450.0)
    assert uit[5] is False                     # 0,003 BTC is een echte positie
    assert uit[6] is True
    # Na de taak geldt weer goud: de schaal lekt niet naar andere coordinators.
    assert schaal.huidig().is_goud


def test_kleine_munt_houdt_zijn_cijfers():
    s = schaal.voor_markt(0.00001234, 1.0, 1.0, 0.0025)
    assert _met_schaal(s, lambda: schaal.rond_prijs(0.0000123456789, 3)) == pytest.approx(0.000012345679)


def test_risicoplafond_en_veldproefgrootte_volgen_de_stap():
    from gold_scalper.strategy import posities, veldproef

    s = schaal.voor_markt(90000.0, 1e-8, 0.0001, 0.0025)
    units, begrensd = _met_schaal(s, lambda: posities.risico_plafond(1.0, 90000.0, 89000.0))
    assert begrensd and units == pytest.approx(0.1)          # 100 / 1000 euro afstand
    klein = _met_schaal(s, lambda: veldproef.grootte_op_risico(1.0, 90000.0, 89900.0))
    assert klein == pytest.approx(1.0)                        # 100/100 = 1, begrensd op units
    goud = veldproef.grootte_op_risico(50.0, 4000.0, 3990.0)
    assert goud == 10.0


def test_spot_kent_geen_hefboom():
    from gold_scalper.strategy import posities

    s = schaal.voor_markt(90000.0, 1e-8, 0.0001, 0.0025)
    ok, reden, _ = _met_schaal(s, lambda: posities.risicolimieten_ok(
        richting=1, nieuw_risico=10.0, nieuw_notional=15000.0, open_posities=[],
        koers=90000.0, equity_ref=10000.0))
    assert not ok and "1x equity" in reden


def test_papier_rekent_het_tarief_per_zijde():
    from gold_scalper.broker.paper import BrokerCosts, PaperBroker, Quote
    from gold_scalper.storage.database import TradeDatabase

    db = TradeDatabase(":memory:")
    db.connect()
    run = db.start_run("paper", "v1", "BTC-EUR", {}, 10000.0, None, "fp")
    pb = PaperBroker(db, run, "BTC-EUR", 10000.0, BrokerCosts(
        commission_per_lot_per_side=0.0, commission_rate=0.0025, base_slippage=0.0,
        volatility_slippage_factor=0.0, size_slippage_per_lot=0.0, leverage=1.0))
    nu = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    t = pb.open_position("buy", 0.01 / 100, Quote(bid=90000.0, ask=90010.0, time=nu))
    assert t.commission == pytest.approx(0.01 * 90010.0 * 0.0025)
    dicht = pb.close_position(t, Quote(bid=90000.0, ask=90010.0, time=nu), "test")
    assert dicht.commission == pytest.approx(0.01 * 90010.0 * 0.0025 + 0.01 * 90000.0 * 0.0025)
    assert dicht.net_pnl == pytest.approx(-0.1 - dicht.commission)


def test_een_strategie_rekent_in_crypto_zonder_kapotte_afronding():
    from gold_scalper.strategy import veldproef

    s = schaal.voor_markt(0.5, 0.01, 1.0, 0.0025)
    stop = _met_schaal(s, lambda: schaal.rond_prijs(0.5 - 0.0123456, 2))
    assert stop == pytest.approx(0.4876544)
    # De minimale stop schaalt mee: 1 USD bij 4000 is 0,000125 bij 0,5.
    assert _met_schaal(s, lambda: veldproef.r_van(0.5, None)) == pytest.approx(0.000125)


# --------------------------------------------------------------------------- #
# De handelslus met een spot-venue (op papier)
# --------------------------------------------------------------------------- #

class SpotVenue:
    """Bitvavo-achtige venue zonder netwerk: alleen koersen en bars."""

    name = "bitvavo"
    alleen_long = True
    altijd_open = True
    has_real_spread = True
    supports_trading = False
    instrument_currency = "EUR"
    tarief_per_zijde = 0.0025
    max_inzet = 250.0

    def __init__(self, prijs=90000.0):
        self.prijs = prijs
        self.stap = 0

    def broker_limits(self):
        from gold_scalper.broker.execution_safety import BrokerLimits
        return BrokerLimits(min_volume=0.0001, max_volume=1e12, volume_step=1e-8, tick_size=0.0)

    def markt_open(self, now):
        return True

    def minuten_tot_sluiting(self, now):
        return 1e7

    async def quote(self, symbol=None):
        from gold_scalper.broker.adapter import VenueQuote
        return VenueQuote(bid=self.prijs - 5, ask=self.prijs + 5, time=datetime.now(timezone.utc))

    async def candles(self, symbol=None, timeframe=None, count=300):
        from gold_scalper.analysis.signals import Candles
        n = count or 300
        nu = int(time.time()) // 60 * 60
        ts, o, h, l, c, v = [], [], [], [], [], []
        p = self.prijs * 0.97
        for i in range(n):
            p *= 1.0004 if i % 3 else 0.9996
            ts.append(nu - (n - i) * 60)
            o.append(p); h.append(p * 1.002); l.append(p * 0.998); c.append(p * 1.0005); v.append(1.0)
        return Candles(ts, o, h, l, c, v)

    async def account(self):
        raise AssertionError("papier vraagt geen saldo op")

    async def positions(self, symbol=None):
        return []


def test_de_lus_draait_op_papier_met_een_spot_venue_en_opent_nooit_short(tmp_path, monkeypatch):
    import gold_scalper.coordinator as co
    from gold_scalper.lifecycle import LifecycleState
    from gold_scalper.strategy.scalping import ScalpSignal
    from test_broker_cycle import FakeHass

    richting = {"d": 1}

    def nep(candles, bid, ask, cfg, uur, aantal, sinds, kant, per_richting=None):
        d = richting["d"]
        instap = ask if d == 1 else bid
        afstand = instap * 0.01
        return ScalpSignal(direction=d, score=0.6 * d, confidence=0.8, should_trade=True,
                           reject_reason=None, reason="test", stop_loss=instap - afstand * d,
                           take_profit=instap + 2 * afstand * d, geldig=True)

    monkeypatch.setattr(co, "evaluate", nep)
    from gold_scalper.broker.paper import BrokerCosts, PaperBroker
    from gold_scalper.coordinator import GoldScalperCoordinator
    from gold_scalper.modes import TradingMode
    from gold_scalper.storage.database import TradeDatabase

    class Entry:
        entry_id = "bv"
        data = {"venue": "simulator", "timeframe": "1m", "mode": "paper"}
        options = {"mode": "paper", "starting_balance": 10000.0, "update_seconds": 20,
                   "strategie": "scalp", "scalp_reeks": False, "risk_based_sizing": True,
                   "risk_per_trade_pct": 0.5, "entry_threshold": 0.05, "min_edge_multiple": 0.1}

    c = GoldScalperCoordinator(FakeHass(), Entry())
    c.venue = SpotVenue()
    c.mode = TradingMode.PAPER
    c.db = TradeDatabase(tmp_path / "bv.db")
    c.db.connect()
    c.run_id = c.db.start_run("paper", "v1", "BTC-EUR", {}, 10000.0, None, "fp")
    c.paper = PaperBroker(c.db, c.run_id, "BTC-EUR", 10000.0, BrokerCosts(
        commission_per_lot_per_side=0.0, commission_rate=0.0025, base_slippage=0.0,
        volatility_slippage_factor=0.0, size_slippage_per_lot=0.0, leverage=1.0))
    c._enabled = True
    c._use_schedule = False
    c.lifecycle._transition(LifecycleState.RUNNING, "test")
    for i in range(30):
        richting["d"] = -1 if i % 2 else 1
        c.venue.prijs *= 1.003 if i % 4 else 0.99
        asyncio.run(c._async_update_data())
    rijen = c.db.conn.execute("SELECT side, volume, open_price, commission FROM trades").fetchall()
    assert rijen, "er is niets geopend; de test bewijst dan niets"
    assert all(r[0] == "buy" for r in rijen)
    for side, volume, prijs, commissie in rijen:
        assert volume * 100 * prijs <= 250.0 + 1e-6          # maximale inzet
        assert commissie > 0                                   # het tarief telt
    assert schaal.huidig().is_goud                            # niets gelekt naar de test


# --------------------------------------------------------------------------- #
# 2.17.0 review: veilig sluiten, onzekere antwoorden, herstart
# --------------------------------------------------------------------------- #

def _verkopen(fake):
    return [json.loads(c["data"]) for c in fake.calls
            if c["method"] == "POST" and c["data"] and json.loads(c["data"]).get("orderType") == "market"
            and json.loads(c["data"]).get("side") == "sell"]


def test_niet_verkopen_als_de_stop_niet_zeker_weg_is():
    v, fake = venue()
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))
    fake.storing = {("DELETE", None): "weigeren"}      # annuleren mislukt, stop blijft staan
    uit = asyncio.run(v.close(r.ticket))
    assert not uit.success and "niet zeker" in uit.error
    assert _verkopen(fake) == []
    assert r.ticket in v._grootboek and v._grootboek[r.ticket]["stop_order_id"]


def test_mislukte_verkoop_zet_de_stop_terug():
    v, fake = venue()
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))
    oude = v._grootboek[r.ticket]["stop_order_id"]
    fake.storing = {("POST", "sell"): "saldo"}
    uit = asyncio.run(v.close(r.ticket))
    assert not uit.success
    regel = v._grootboek[r.ticket]
    assert regel["stop_order_id"] and regel["stop_order_id"] != oude
    assert fake.orders[regel["stop_order_id"]]["status"] == "awaitingTrigger"
    assert regel["stop_loss"] == 89000.0


def test_verkoop_zonder_antwoord_wordt_teruggevonden():
    v, fake = venue()
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))
    fake.storing = {("POST", "sell"): "time-out-na-uitvoeren"}
    uit = asyncio.run(v.close(r.ticket))
    assert uit.success and uit.units == pytest.approx(0.002)
    assert r.ticket not in v._grootboek
    assert len(_verkopen(fake)) == 1                   # niet twee keer verkocht


def test_stop_verplaatsen_na_een_afgegane_stop_zet_geen_tweede():
    v, fake = venue()
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))
    fake.stop_gaat_af(v._grootboek[r.ticket]["stop_order_id"], 88990.0)
    fake.storing = {("PUT", None): "weigeren"}
    uit = asyncio.run(v.modify_stop(r.ticket, 89500))
    assert not uit.success and r.ticket not in v._grootboek
    stops = [o for o in fake.orders.values() if o["orderType"] == "stopLoss"]
    assert len(stops) == 1


def test_koop_zonder_antwoord_wordt_teruggevonden_en_niet_herhaald():
    v, fake = venue()
    fake.storing = {("POST", "buy"): "time-out-na-uitvoeren"}
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000, comment="gs-t"))
    assert r.success and r.units == pytest.approx(0.002)
    kopen = [o for o in fake.orders.values() if o["side"] == "buy"]
    assert len(kopen) == 1


def test_koop_zonder_antwoord_en_zonder_order_is_onbevestigd():
    v, fake = venue()
    fake.storing = {("POST", "buy"): "time-out"}
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000, comment="gs-x"))
    assert not r.success and r.unconfirmed


def test_duidelijke_weigering_is_geen_uitzondering():
    v, fake = venue()
    fake.storing = {("POST", "buy"): "saldo"}
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))
    assert not r.success and not r.unconfirmed and "saldo" in r.error


def test_bevestigen_na_een_herstart():
    v, fake = venue()
    asyncio.run(v.markt())
    fake._nieuw({"market": "BTC-EUR", "side": "buy", "orderType": "market", "amount": "0.002",
                 "clientOrderId": v.client_order_id("gs-herstart")})
    vers, _ = venue(fake)                              # leeg geheugen
    stand, ticket = asyncio.run(vers.confirm_status("gs-herstart"))
    assert stand == "ACCEPTED" and ticket in vers._grootboek


def test_vermogen_telt_alleen_eigen_geld_en_wat_de_bot_kocht():
    v, fake = venue()
    fake.saldo["BTC"] = [1.0, 0.0]                     # eigen bitcoin van Ruud
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))
    acc = asyncio.run(v.account())
    assert acc.equity == pytest.approx(acc.balance + 0.002 * 90000.0)


def test_deelverkoop_neemt_de_aankoopkosten_naar_rato_mee_en_bewaart_gesloten():
    bewaard: list = []
    v, fake = venue(bewaard=bewaard)
    r = asyncio.run(v.place_order("BTC-EUR", "buy", 0.004, stop_loss=89000))
    fee = v._grootboek[r.ticket]["open_fee"]
    uit = asyncio.run(v.close(r.ticket, units=0.001))
    assert uit.success
    regel = v._grootboek[r.ticket]
    assert regel["units"] == pytest.approx(0.003)
    assert regel["open_fee"] == pytest.approx(fee * 0.75)
    assert regel["stop_order_id"] and regel["stop_loss"] == 89000.0
    asyncio.run(v.close(r.ticket))
    assert r.ticket in bewaard[-1]["gesloten"]


def test_papierstand_handelt_nooit_ook_niet_als_de_schakelaar_aan_staat():
    v, fake = venue(live=False)
    v.supports_trading = True
    with pytest.raises(TradingDisabledError):
        asyncio.run(v.place_order("BTC-EUR", "buy", 0.002, stop_loss=89000))


def test_kosten_in_de_munt_zelf_gaan_van_de_positie_af():
    order = {"market": "BTC-EUR", "orderId": "X", "filledAmount": "0.002", "filledAmountQuote": "180",
             "fills": [{"amount": "0.002", "price": "90000", "fee": "0.000005", "feeCurrency": "BTC"}]}
    assert bv._kosten_in_basis(order) == pytest.approx(0.000005)
    assert bv._nieuwe_regel("BTC-EUR", order, "k")["units"] == pytest.approx(0.001995)


def test_schaal_per_aanroep_en_daarna_terug():
    from gold_scalper import coordinator as co

    class Nep:
        def _schaal_nu(self):
            return schaal.voor_markt(90000.0, 1e-8, 1e-4, 0.0025)

        @co._met_schaal
        async def doe(self):
            return schaal.huidig()

    binnen = asyncio.run(Nep().doe())
    assert not binnen.is_goud and binnen.prijs == pytest.approx(22.5)
    assert schaal.huidig().is_goud


def test_bewijs_alleen_van_dezelfde_strategie_en_markt():
    from types import SimpleNamespace

    from gold_scalper import coordinator as co
    runs = [
        {"id": 5, "mode": "paper", "strategy_version": "andere", "symbol": "BTC-EUR"},
        {"id": 4, "mode": "paper", "strategy_version": "v1", "symbol": "ETH-EUR"},
        {"id": 3, "mode": "live", "strategy_version": "v1", "symbol": "BTC-EUR"},
        {"id": 2, "mode": "paper", "strategy_version": "v1", "symbol": "BTC-EUR"},
    ]
    nep = SimpleNamespace(strategie_versie="v1", symbol="BTC-EUR",
                          db=SimpleNamespace(list_runs=lambda limit=50: runs))
    assert co.GoldScalperCoordinator._laatste_papieren_run(nep) == 2
