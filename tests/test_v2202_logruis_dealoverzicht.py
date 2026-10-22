"""2.20.2 - logruis na een herstart (L-GS-021) en het dealoverzicht van cTrader.

Akkoord Ruud 22-10 18:05.

1. Na elke herstart ~22 waarschuwingen: "Veldproefopzet ... uitgezet" voor
   opzetten die al uit stonden, en "Opgewarmd met N candles in plaats van 400"
   per markt. Nu alleen de overgang aan -> uit als waarschuwing; de stand bij
   het opstarten en het opwarmen als één inforegel.
2. Pepperstone: de sluitende deals van positie 58312111 (14-10) en van de rest
   van 58383755 (16-10) kwamen niet terug uit één dealverzoek over tien dagen.
   Nu per dag (en bij ``hasMore`` gesplitst), en posities met minder sluitende
   deals dan eigen trades worden apart per positie nagezocht. Antwoordt de
   broker per positie zonder één deal, dan heet de trade "niet bij de
   broker" in plaats van een afwijking.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))

from gold_scalper.broker import ctrader  # noqa: E402
from gold_scalper.learning.afstemming import stem_af  # noqa: E402
from gold_scalper.storage.database import Trade  # noqa: E402

PKG = Path(HIER).parent / "custom_components" / "gold_scalper"
NU = datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc)


# 1. Logruis ----------------------------------------------------------------


def _vp_coord(monkeypatch, uitgezet):
    from gold_scalper import coordinator as cm

    toestand = {"uit": dict(uitgezet)}
    monkeypatch.setattr(cm.veldproef_mod, "uitgezette_opzetten", lambda _p: dict(toestand["uit"]))
    monkeypatch.setattr(cm.veldproef_mod, "kosten_uitgezet", lambda _p: {})
    monkeypatch.setattr(cm.veldproef_mod, "handmatig_uitgezet", lambda _p, _t: {})
    monkeypatch.setattr(cm.veldproef_mod, "groep_uitgezet", lambda _r: None)

    async def executor(fn, *a):
        return fn(*a)

    c = SimpleNamespace(
        _vp_uitgezet_volgende=0.0, _vp_uitgezet={}, _scalp_uitgezet=None,
        _vp_uitgezet_gelezen=False, _scalp_uitgezet_gelezen=False,
        scalp_handmatig_uit=False, vp_tijdvakken_uit=(),
        db=SimpleNamespace(netto_per_strategie=lambda *_: {},
                           bruto_kosten_per_strategie=lambda *_: {}),
        hass=SimpleNamespace(async_add_executor_job=executor),
    )
    return cm.GoldScalperCoordinator, c, toestand


def _info(n):
    return {"n": n, "netto": -100.0, "t": None}


def test_al_uitgezette_opzetten_na_herstart_geen_waarschuwing(monkeypatch, caplog):
    C, c, toestand = _vp_coord(monkeypatch, {f"vp:x:{i}m": _info(40) for i in range(20)})
    with caplog.at_level(logging.INFO):
        asyncio.run(C._ververs_vp_uitgezet(c))
    waarsch = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert waarsch == []
    info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(info) == 1 and "20 veldproefopzet(ten) staan uit" in info[0]

    # Een opzet die daarna uitgaat: wel een waarschuwing, één keer.
    caplog.clear()
    toestand["uit"]["vp:nieuw:5m"] = _info(41)
    c._vp_uitgezet_volgende = 0.0
    with caplog.at_level(logging.INFO):
        asyncio.run(C._ververs_vp_uitgezet(c))
    waarsch = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(waarsch) == 1 and "vp:nieuw:5m" in waarsch[0]


def test_opwarmen_is_geen_waarschuwing_meer():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    i = bron.index('"Opgewarmd met %d candles in plaats van %d. "')
    assert "_LOGGER.debug(" in bron[i - 120:i]
    assert "gewenst {WARMUP_CANDLES}" in bron


# 2. Dealoverzicht ----------------------------------------------------------


def _venue(antwoorden):
    """CTraderVenue zonder verbinding; ``antwoorden(soort, payload)`` speelt de broker."""
    v = object.__new__(ctrader.CTraderVenue)
    v.ctid, v.symbol_id, v.valuta = 1, 41, "USD"
    v.verzoeken = []

    async def verzoek(soort, payload, verwacht=None, timeout=None):
        v.verzoeken.append((soort, payload))
        return antwoorden(soort, payload)

    async def klaar():
        return None

    v._verzoek = verzoek
    v._klaar = klaar
    return v


def _ms(d):
    return int(d.timestamp() * 1000)


def test_dealoverzicht_per_dag_en_gesplitst_bij_hasmore():
    van = NU - timedelta(days=3)

    def broker(soort, p):
        breedte = p["toTimestamp"] - p["fromTimestamp"]
        if breedte > 12 * 3600 * 1000:          # een hele dag: te veel
            return {"deal": [{"dealId": "x", "symbolId": 41}], "hasMore": True}
        return {"deal": [{"dealId": str(p["fromTimestamp"]), "symbolId": 41},
                         {"dealId": "x", "symbolId": 41},
                         {"dealId": "ander", "symbolId": 7}], "hasMore": False}

    v = _venue(broker)
    deals = asyncio.run(v._deals(van, NU))
    assert all(p["toTimestamp"] - p["fromTimestamp"] <= 86_400_000 for _, p in v.verzoeken)
    ids = [d["dealId"] for d in deals]
    assert len(ids) == len(set(ids))                       # geen dubbelen
    assert "ander" not in ids                              # ander symbool
    assert len(ids) == 3 * 2 + 1                           # 6 halve dagen + "x"


def _deal(pid, sluit=True, prijs=4184.55, oz=5, ts=NU - timedelta(days=6)):
    d = {"dealId": f"d{pid}{'s' if sluit else 'o'}{prijs}", "positionId": int(pid),
         "symbolId": 41, "tradeSide": "SELL" if sluit else "BUY",
         "executionPrice": prijs, "executionTimestamp": _ms(ts), "filledVolume": oz * 100}
    if sluit:
        d["closePositionDetail"] = {"entryPrice": 4174.32, "closedVolume": oz * 100,
                                    "grossProfit": 1000, "swap": 0, "commission": 0,
                                    "moneyDigits": 2}
    return d


def test_per_positie_nazoeken_vindt_deals_en_bevestigt_afwezigheid():
    def broker(soort, p):
        if p["positionId"] == 58383755:
            return {"deal": [_deal(58383755, sluit=False), _deal(58383755, prijs=4181.94)]}
        return {"deal": []}

    v = _venue(broker)
    tx, afwezig = asyncio.run(v.transacties_van_posities({
        "58383755": (NU - timedelta(days=7), NU - timedelta(days=6)),
        "58312111": (NU - timedelta(days=8), NU - timedelta(days=7)),
    }))
    assert [t["closeLevel"] for t in tx] == [4181.94]
    assert afwezig == {"58312111"}


def _trade(i, ticket, **kw):
    v = dict(run_id=1, mode="demo", symbol="XAUUSD", side="buy", volume=0.05,
             open_time=(NU - timedelta(days=7.9)).isoformat(), open_price=4093.48,
             open_mid=4093.4, open_spread=0.1,
             close_time=(NU - timedelta(days=7.8)).isoformat(), close_price=4098.82,
             net_pnl=26.7, broker_ticket=ticket, close_reason="partial_close",
             cost_source="measured")
    v.update(kw)
    t = Trade(**v)
    t.id = i
    return t


def test_bevestigd_niet_bij_broker_is_geen_afwijking():
    trades = [_trade(28, "58312111-deel"), _trade(17, "58312111")]
    u = stem_af(trades, [], 1.0, NU, 100.0, {"58312111"})
    assert u.in_orde
    assert [a.soort for a in u.niet_bij_broker] == ["niet_bij_broker"] * 2
    assert "niet bij de broker" in u.samenvatting()
    d = u.as_dict()
    assert len(d["niet_bij_broker"]) == 2 and d["afwijkingen"] == []
    # Zonder bevestiging blijft het "ontbreekt".
    assert [a.soort for a in stem_af(trades, [], 1.0, NU, 100.0).afwijkingen] == ["ontbreekt"] * 2


def test_coordinator_zoekt_alleen_onvolledige_posities_na():
    from gold_scalper.coordinator import GoldScalperCoordinator as C

    gevraagd = {}

    async def zoek(posities):
        gevraagd.update(posities)
        return [{"reference": "nieuw", "dealId": "58383755"}], {"58312111"}

    c = SimpleNamespace(venue=SimpleNamespace(transacties_van_posities=zoek),
                        POSITIES_NAZOEKEN_MAX=20)
    recent = [
        _trade(1, "58383755-deel"), _trade(2, "58383755"),   # 1 van 2 deals
        _trade(3, "58312111-deel"), _trade(4, "58312111"),   # 0 van 2
        _trade(5, "58400000"),                               # compleet
    ]
    tx = [{"reference": "a", "dealId": "58383755"}, {"reference": "b", "dealId": "58400000"}]
    uit, afwezig = asyncio.run(C._vul_transacties_aan(c, recent, tx, NU))
    assert set(gevraagd) == {"58383755", "58312111"}
    assert [t["reference"] for t in uit] == ["a", "b", "nieuw"]
    assert afwezig == {"58312111"}


def test_ig_zonder_nazoeken_ongewijzigd():
    from gold_scalper.coordinator import GoldScalperCoordinator as C

    c = SimpleNamespace(venue=SimpleNamespace(), POSITIES_NAZOEKEN_MAX=20)
    tx = [{"reference": "a"}]
    assert asyncio.run(C._vul_transacties_aan(c, [_trade(1, "DIAAAA")], tx, NU)) == (tx, set())
