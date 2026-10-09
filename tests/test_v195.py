"""1.9.5: tijdstopvarianten (L-GS-008) en toets per uurblok (L-GS-007).

Alleen meting, geen strategiewijziging (akkoord Ruud 09-10-2026). Elke echte
positie wordt nagespeeld met tijdstop 240, 480, 720 s en zonder tijdstop,
verder identiek aan het echte exitbeheer. Het echte exitbeheer, de orders en
de echte administratie mogen daardoor op geen enkele manier veranderen.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.broker.exits import ExitConfig, ExitManager  # noqa: E402
from gold_scalper.storage import performance  # noqa: E402
from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402
from gold_scalper.strategy.schaduw import SchaduwBoek, SchaduwKosten  # noqa: E402
from gold_scalper.strategy.tijdstopvarianten import (  # noqa: E402
    BASIS, MIN_BLOKKEN, VARIANTEN, VariantenBoek, VariantTrade,
    echte_sluitcode, varianten_statistiek,
)

from test_v190 import (  # noqa: E402,F401
    T0, _cyclus, _klok, _nu, _opzet, _richting, _sig, vaste_klok,
)

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
KOSTEN = SchaduwKosten(slippage=0.02, commissie_per_lot=0.0)


def _boek(**kw) -> VariantenBoek:
    return VariantenBoek(exits=ExitManager(ExitConfig(**kw)), kosten=KOSTEN)


def _open(boek, side="buy", nu=T0, ref="T1", stop=4390.0, doel=4420.0):
    prijs = 4400.3 if side == "buy" else 4399.7
    return boek.openen(run_id=1, trade_ref=ref, side=side, open_price=prijs,
                       open_mid=4400.0, spread=0.6, units=10.0, stop_loss=stop,
                       take_profit=doel, nu=nu)


def _per(boek_of_lijst):
    lijst = boek_of_lijst if isinstance(boek_of_lijst, list) else (
        boek_of_lijst.open_trades + boek_of_lijst.gesloten)
    return {t.variant: t for t in lijst}


# ======================================================================= #
# Simulatie                                                               #
# ======================================================================= #

def test_vier_varianten_per_echte_trade_en_geen_dubbele():
    boek = _boek()
    nieuw = _open(boek)
    assert [t.variant for t in nieuw] == list(VARIANTEN) == [
        "240", "480", "720", "geen_tijdstop"]
    assert all(t.units == 10.0 and t.open_price == 4400.3 for t in nieuw)
    assert all(t.max_hold_seconds == 900 for t in nieuw)
    assert _open(boek) == [], "zelfde ticket: geen tweede set"
    assert _open(boek, ref="") == []


def test_variantconfig_is_een_kopie_en_raakt_de_echte_niet():
    echt = ExitManager(ExitConfig())
    boek = VariantenBoek(exits=echt, kosten=KOSTEN)
    for v, (ts, _) in VARIANTEN.items():
        m = boek.manager(v)
        assert m.config is not echt.config
        assert m.config.time_stop_seconds == (ts if ts is not None else 10 ** 9)
        assert m.config.max_hold_seconds == 900
        # Alles behalve de tijdstop identiek aan de echte configuratie.
        assert m.config.breakeven_trigger_atr == echt.config.breakeven_trigger_atr
        assert m.config.trailing_distance_atr == echt.config.trailing_distance_atr
        assert m.config.time_stop_deadzone_atr == echt.config.time_stop_deadzone_atr
    assert echt.config == ExitConfig()


def test_variant_240_gelijk_aan_schaduwlogica():
    """Zelfde invoer, zelfde uitkomst als een schaduwtrade (gedeelde stap)."""
    paden = [
        # tijdstop
        [(20, 4399.9, 4400.5, None, None), (245, 4399.9, 4400.5, None, None)],
        # trailing en daarna de verplaatste stop
        [(20, 4404.0, 4404.6, None, None), (60, 4401.0, 4401.6, 4402.0, 4400.0)],
        # stop en doel in één interval: de stop
        [(20, 4400.0, 4400.6, 4425.0, 4385.0)],
        # doel
        [(20, 4419.7, 4420.3, 4421.0, 4419.0)],
    ]
    for pad in paden:
        schaduw = SchaduwBoek(exits=ExitManager(ExitConfig()), kosten=KOSTEN)
        s = schaduw.openen(run_id=1, signal=_sig(1, 4390.0, 4420.0), bid=4399.7,
                           ask=4400.3, nu=T0, units=10.0, reden="cooldown",
                           reden_tekst=None, atr=2.0)
        boek = _boek()
        v = _per(_open(boek))["240"]
        for sec, bid, ask, hoog, laag in pad:
            nu = T0 + timedelta(seconds=sec)
            schaduw.bijwerken(bid=bid, ask=ask, hoog=hoog, laag=laag, atr=2.0, nu=nu)
            boek.bijwerken(bid=bid, ask=ask, hoog=hoog, laag=laag, atr=2.0, nu=nu)
        for veld in ("status", "close_reason", "close_price", "bruto",
                     "kosten", "netto", "stop_loss", "mfe", "mae"):
            assert getattr(v, veld) == getattr(s, veld), (pad, veld)


def test_langere_varianten_lopen_door_na_de_240():
    boek = _boek()
    _open(boek)
    for s in range(60, 961, 60):
        boek.bijwerken(bid=4399.9, ask=4400.5, hoog=None, laag=None, atr=2.0,
                       nu=T0 + timedelta(seconds=s))
    v = _per(boek)
    assert v["240"].close_reason == "tijdstop" and v["240"].close_time.endswith("10:04:00+00:00")
    assert v["480"].close_reason == "tijdstop" and v["480"].close_time.endswith("10:08:00+00:00")
    assert v["720"].close_reason == "tijdstop" and v["720"].close_time.endswith("10:12:00+00:00")
    assert v["geen_tijdstop"].close_reason == "max_duur"
    assert v["geen_tijdstop"].close_time.endswith("10:15:00+00:00")
    assert not boek.open_trades


def test_uitersten_van_voor_de_instap_tellen_niet():
    boek = _boek()
    _open(boek, nu=T0 + timedelta(seconds=150))
    # De bar 10:00-10:05 sloot; zijn laagste punt lag vóór de instap onder de stop.
    boek.bijwerken(bid=4399.9, ask=4400.5, hoog=4401.0, laag=4385.0, atr=2.0,
                   nu=T0 + timedelta(seconds=300), uitersten_vanaf=T0)
    assert all(t.status == "open" for t in boek.open_trades)
    # Een bar die ná de instap begon telt wél.
    boek.bijwerken(bid=4399.9, ask=4400.5, hoog=4401.0, laag=4385.0, atr=2.0,
                   nu=T0 + timedelta(seconds=600),
                   uitersten_vanaf=T0 + timedelta(seconds=300))
    assert {t.close_reason for t in boek.gesloten} == {"stop_loss"}
    assert len(boek.gesloten) == 4


def test_gat_in_de_data_laat_varianten_vervallen():
    boek = _boek()
    _open(boek)
    gewijzigd = boek.bijwerken(bid=4400.0, ask=4400.6, hoog=None, laag=None,
                               atr=2.0, nu=T0 + timedelta(seconds=900))
    assert len(gewijzigd) == 4 and {t.status for t in gewijzigd} == {"vervallen"}
    assert boek.vervallen == 4 and boek.statistiek()["per_variant"]["240"]["trades"] == 0


def test_short_rekent_op_de_laat():
    boek = _boek()
    _open(boek, side="sell", stop=4410.0, doel=4380.0)
    boek.bijwerken(bid=4399.9, ask=4400.5, hoog=None, laag=None, atr=4.0,
                   nu=T0 + timedelta(seconds=60))
    boek.bijwerken(bid=4399.9, ask=4400.5, hoog=None, laag=None, atr=4.0,
                   nu=T0 + timedelta(seconds=250))
    v = _per(boek)["240"]
    assert v.close_reason == "tijdstop" and v.close_price == 4400.5
    assert v.netto == pytest.approx((4399.7 - 4400.5) * 10 - 0.4)


# ======================================================================= #
# Statistiek                                                              #
# ======================================================================= #

def _vt(ref, variant, open_t, netto, reden="tijdstop", duur=240):
    sluit = open_t + timedelta(seconds=duur)
    return VariantTrade(
        run_id=1, trade_ref=ref, variant=variant, richting=1,
        open_time=open_t.isoformat(), open_price=4400.0, open_mid=4400.0,
        open_spread=0.6, units=10.0, stop_loss=None, take_profit=None,
        status="gesloten", close_time=sluit.isoformat(), close_reason=reden,
        bruto=netto + 1.0, kosten=1.0, netto=netto,
    )


def _reeks(blokken, verschil, ruis=0.3):
    rijen = []
    for b in range(blokken):
        for k in range(2):
            t = T0 + timedelta(hours=b, minutes=10 * k)
            ref = f"R{b}-{k}"
            basis = -1.0 + (k - 0.5)
            r = ruis * ((b * 7 + k * 3) % 5 - 2)
            rijen.append(_vt(ref, "240", t, basis))
            rijen.append(_vt(ref, "480", t, basis + verschil + r, duur=480))
            rijen.append(_vt(ref, "720", t, basis + r, duur=720))
            rijen.append(_vt(ref, "geen_tijdstop", t, basis - verschil + r,
                             reden="max_duur", duur=900))
    return rijen


def test_statistiek_per_variant_en_gepaard_per_blok():
    rijen = _reeks(5, 1.0)
    s = varianten_statistiek(rijen, {})
    assert s["blokken"] == 5 and s["volledige_trades"] == 10
    pv = s["per_variant"]["240"]
    assert pv["trades"] == 10 and pv["tijdstop_pct"] == 100.0
    assert pv["netto"] == pytest.approx(-10.0) and pv["kosten"] == 10.0
    assert pv["gem_duur_s"] == 240.0
    assert s["per_variant"]["geen_tijdstop"]["max_duur_pct"] == 100.0
    g = s["gepaard_tegen_240"]["480"]
    assert g["trades"] == 10 and g["blokken"] == 5
    # Per blok de som van twee verschillen van gemiddeld ~1.
    assert g["verschil_per_blok"] == pytest.approx(2.0, abs=0.7)
    assert g["t_blokken"] > 2 and g["lag1"] is not None
    assert s["gepaard_tegen_240"]["geen_tijdstop"]["t_blokken"] < -2
    assert "te weinig blokken (5 van 20" in s["oordeel"]


def test_onvolledige_trades_tellen_niet_gepaard():
    rijen = _reeks(3, 1.0)
    rijen = [r for r in rijen if not (r.trade_ref == "R0-0" and r.variant == "720")]
    s = varianten_statistiek(rijen, {})
    assert s["volledige_trades"] == 5
    assert all(g["trades"] == 5 for g in s["gepaard_tegen_240"].values())


def test_oordeel_na_20_blokken():
    s = varianten_statistiek(_reeks(MIN_BLOKKEN, 1.0), {})
    assert s["blokken"] == 20
    assert s["oordeel"].startswith("variant 480 beter dan 240 s")
    assert "Ruud" in s["oordeel"]
    s = varianten_statistiek(_reeks(MIN_BLOKKEN, 0.0, ruis=1.0), {})
    assert s["oordeel"].startswith("geen duidelijk verschil")


def test_t_en_lag1_over_blokken():
    toets = performance.blok_toets([1.0, 2.0, 3.0, 4.0])
    assert toets["n"] == 4 and toets["gemiddeld"] == 2.5
    assert toets["t"] == pytest.approx(2.5 / (1.290994 / 2), abs=1e-3)
    assert performance.lag1([1.0, 2.0, 3.0, 4.0]) == pytest.approx(0.25)
    assert performance.lag1([1.0, -1.0, 1.0, -1.0]) == pytest.approx(-0.75)
    assert performance.lag1([1.0, 2.0]) is None
    assert performance.blok_sleutel("2026-10-09T13:59:59+00:00") == "2026-10-09T13"
    assert performance.blok_sleutel("2026-10-09T15:10:00+02:00") == "2026-10-09T13"


def test_overeenkomst_met_de_echte_trade():
    rijen = _reeks(2, 0.5)
    echte = {
        "R0-0": SimpleNamespace(close_reason="na 251s nog binnen 0.3xATR van het "
                                "instappunt; geen sca", net_pnl=-1.3),
        "R0-1": SimpleNamespace(close_reason="stop_loss", net_pnl=-0.5),
        "R1-0": SimpleNamespace(close_reason="na 245s nog binnen 0.3xATR", net_pnl=-2.0),
        "R1-1": SimpleNamespace(close_reason="na 245s nog binnen 0.3xATR", net_pnl=None),
    }
    ov = varianten_statistiek(rijen, echte)["overeenkomst"]
    # R0-0: zelfde reden, verschil 0.2 -> overeenkomst; R0-1: andere reden;
    # R1-0: zelfde reden, verschil 0.5 -> geen; R1-1: nog geen netto.
    assert ov["vergeleken"] == 3
    assert ov["zelfde_sluitreden_pct"] == pytest.approx(66.7)
    assert ov["overeenkomst_pct"] == pytest.approx(33.3)


def test_echte_sluitcodes():
    assert echte_sluitcode("maximale positieduur van 900s bereikt bij +0.1") == "max_duur"
    assert echte_sluitcode("na 240s nog binnen 0.3xATR van het instappunt") == "tijdstop"
    assert echte_sluitcode("take_profit") == "take_profit"
    assert echte_sluitcode(None) == "unknown"


# ======================================================================= #
# L-GS-007: per tijdblok                                                  #
# ======================================================================= #

def _trade(open_t, net, bruto, regime="tijdstop", duur=200):
    return Trade(run_id=1, mode="demo", symbol="GOLD", side="buy", volume=0.1,
                 open_time=open_t.isoformat(), open_price=4400.0, open_mid=4400.0,
                 open_spread=0.6,
                 close_time=(open_t + timedelta(seconds=duur)).isoformat(),
                 net_pnl=net, gross_pnl=bruto, total_cost=bruto - net,
                 exit_regime=regime)


def test_per_tijdblok_t_regime_sessie_en_clusterwaarschuwing():
    trades = []
    # Elke 5 min een trade gedurende 3 uur: één cluster van ~3 uur.
    for i in range(36):
        t = T0 + timedelta(minutes=5 * i)
        trades.append(_trade(t, 1.0 + (i % 5) * 0.5, 2.0 + (i % 2),
                             regime="tijdstop" if i >= 12 else "geen_tijdstop"))
    stats = performance.compute(trades)
    blok = performance.per_tijdblok(trades)
    assert blok["blokken"] == 3 and blok["trades"] == 36
    assert blok["netto_usd"] == pytest.approx(sum(t.net_pnl for t in trades))
    assert blok["t_netto"] is not None and blok["lag1_netto"] is not None
    assert set(blok["per_exitregime"]) == {"tijdstop", "geen_tijdstop"}
    assert blok["per_exitregime"]["tijdstop"]["blokken"] == 2
    assert blok["per_sessie"]["londen"]["blokken"] == 3
    assert blok["cluster_langer_dan_120_min"] is True
    assert blok["langste_cluster_min"] > 120
    assert [b["blok"] for b in blok["laatste_blokken"]] == [
        "2026-10-07T10", "2026-10-07T11", "2026-10-07T12"]
    # De cluster-t en het oordeel zijn ongewijzigd.
    assert stats["clusters"] == 1 and "per_tijdblok" not in stats


def test_per_tijdblok_in_compute_for_run_en_oordeel_ongewijzigd(tmp_path):
    db = TradeDatabase(tmp_path / "b.db")
    db.connect()
    run = db.start_run("demo", "v", "GOLD", {}, 10000.0, None, "fp")
    for i in range(4):
        tr = _trade(T0 + timedelta(hours=i), 1.0, 2.0, duur=100)
        tr.run_id = run
        db.insert_trade(tr)
    stats = performance.compute_for_run(db, run)
    assert stats["per_tijdblok"]["blokken"] == 4
    assert stats["per_tijdblok"]["cluster_langer_dan_120_min"] is False
    zonder = performance.compute(db.closed_trades(run), 10000.0)
    for k in ("verdict", "verdict_text", "t_statistic", "clusters", "ready_for_live"):
        assert stats.get(k) == zonder.get(k)


# ======================================================================= #
# Opslag                                                                  #
# ======================================================================= #

def test_tabel_bewaren_en_herladen(tmp_path):
    db = TradeDatabase(tmp_path / "v.db")
    db.connect()
    boek = _boek()
    nieuw = _open(boek)
    db.bewaar_varianten(nieuw)
    assert all(t.id for t in nieuw)
    boek.bijwerken(bid=4399.9, ask=4400.5, hoog=None, laag=None, atr=2.0,
                   nu=T0 + timedelta(seconds=250))
    db.bewaar_varianten(nieuw)
    rijen = db.tijdstop_varianten(1)
    assert len(rijen) == 4
    assert {r["variant"]: r["status"] for r in rijen}["240"] == "gesloten"
    assert db.tijdstop_varianten(1, status="open").__len__() == 3
    assert db.closed_trades(1) == [], "de echte tabel blijft leeg"
    # Opnieuw openen (migratie) is veilig.
    db.close()
    db2 = TradeDatabase(tmp_path / "v.db")
    db2.connect()
    assert len(db2.tijdstop_varianten(1)) == 4


# ======================================================================= #
# In de lus: echte trades ongewijzigd, varianten erbij                    #
# ======================================================================= #

def _scenario(tmp_path, monkeypatch, met_varianten=True):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch, houd_exits=False)
    if not met_varianten:
        async def _niets(*a, **k):
            return None
        coordinator._open_varianten = _niets
    _richting["d"] = 1
    coordinator.state.atr._rma._value = 20.0          # alles in de dode zone
    _cyclus(coordinator)                               # echte long om T0
    coordinator._enabled = False                       # verder geen instappen
    for _ in range(16):                                # tot T0 + 960 s
        coordinator.state.atr._rma._value = 20.0
        _cyclus(coordinator, stap=60)
    return coordinator, venue


def test_varianten_in_de_lus_240_spiegelt_de_echte_tijdstop(tmp_path, monkeypatch):
    coordinator, venue = _scenario(tmp_path, monkeypatch)
    echte = coordinator.db.closed_trades(coordinator.run_id)
    assert len(echte) == 1 and "binnen" in echte[0].close_reason
    rijen = {r["variant"]: r for r in coordinator.db.tijdstop_varianten(coordinator.run_id)}
    assert set(rijen) == set(VARIANTEN)
    assert all(r["trade_ref"] == echte[0].broker_ticket for r in rijen.values())
    assert rijen["240"]["close_time"] == echte[0].close_time[:19] + "+00:00"
    assert rijen["240"]["close_reason"] == "tijdstop"
    # Langere varianten liepen door na de echte sluiting.
    assert rijen["480"]["close_time"] > rijen["240"]["close_time"]
    assert rijen["720"]["close_time"] > rijen["480"]["close_time"]
    assert rijen["geen_tijdstop"]["close_reason"] == "max_duur"
    s = coordinator._varianten_stats
    assert s["overeenkomst"]["vergeleken"] == 1
    assert s["overeenkomst"]["zelfde_sluitreden_pct"] == 100.0
    assert s["blokken"] == 1 and s["volledige_trades"] == 1
    data = _cyclus(coordinator, stap=20)
    assert data["tijdstopvarianten"]["blokken"] == 1


def test_echte_handel_identiek_met_en_zonder_varianten(tmp_path, monkeypatch):
    a, va = _scenario(tmp_path / "a", monkeypatch, met_varianten=True)
    _klok["extra"] = 0.0
    b, vb = _scenario(tmp_path / "b", monkeypatch, met_varianten=False)
    assert va.orders == vb.orders and va.gesloten == vb.gesloten

    def kern(c):
        return [(t.side, t.open_price, t.close_time, t.close_price, t.close_reason,
                 t.net_pnl, t.stop_loss, t.take_profit)
                for t in c.db.closed_trades(c.run_id)]
    assert kern(a) == kern(b)
    assert a.db.tijdstop_varianten(a.run_id) and not b.db.tijdstop_varianten(b.run_id)
    # De echte exitconfiguratie is onaangeroerd.
    assert a.exits.config == ExitConfig()
    assert a.exits.config.time_stop_seconds == 240
    assert a.exits.config.max_hold_seconds == 900
    assert a.varianten.exits is a.exits


def test_fout_in_de_varianten_raakt_de_handel_niet(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)

    def kapot(*a, **k):
        raise RuntimeError("stuk")
    coordinator.varianten.openen = kapot
    coordinator.varianten.bijwerken = kapot
    _richting["d"] = 1
    _cyclus(coordinator)
    assert len(venue.orders) == 1 and len(venue._positions) == 1
    _cyclus(coordinator, stap=60)


def test_herstart_herlaadt_en_vervalt_bij_een_gat(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)
    assert len(coordinator.varianten.open_trades) == 4
    # Herstart: geheugen leeg, opnieuw laden uit de tabel.
    coordinator.varianten.open_trades = []
    asyncio.run(coordinator._laad_varianten())
    assert len(coordinator.varianten.open_trades) == 4
    assert all(t.id for t in coordinator.varianten.open_trades)
    # Kort gat: lopen door.
    coordinator.state.atr._rma._value = 20.0
    _cyclus(coordinator, stap=60)
    assert len(coordinator.varianten.open_trades) == 4
    # Lang gat (HA lag stil): vervallen.
    coordinator._enabled = False
    coordinator.state.atr._rma._value = 20.0
    _cyclus(coordinator, stap=400)
    rijen = coordinator.db.tijdstop_varianten(coordinator.run_id)
    assert {r["status"] for r in rijen} == {"vervallen"}
    assert coordinator._varianten_stats["vervallen"] == 4


def test_nieuwe_run_laat_open_varianten_vervallen(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    _richting["d"] = 1
    _cyclus(coordinator)
    oud = coordinator.run_id
    coordinator.run_id = coordinator.db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp2")
    asyncio.run(coordinator._laad_varianten())
    assert coordinator.varianten.open_trades == []
    assert {r["status"] for r in coordinator.db.tijdstop_varianten(oud)} == {"vervallen"}


# ======================================================================= #
# Sensor, dashboard, versie                                               #
# ======================================================================= #

def _sensorbron() -> str:
    return (PKG / "sensor.py").read_text(encoding="utf-8")


def test_sensor_tijdstopvarianten_en_omvang():
    bron = _sensorbron()
    assert 'key="tijdstopvarianten", name="Tijdstopvarianten"' in bron
    blok = bron.split('key="tijdstopvarianten"')[1].split("ScalperSensor(")[0]
    assert '.get("blokken")' in blok
    for k in ("oordeel", "per_variant", "gepaard_tegen_240", "overeenkomst"):
        assert f'"{k}"' in blok
    stats = varianten_statistiek(_reeks(60, 0.4), {
        f"R{b}-{k}": SimpleNamespace(close_reason="na 240s nog binnen 0.3xATR",
                                     net_pnl=-1.0)
        for b in range(60) for k in range(2)
    })
    assert stats["blokken"] == 60
    assert set(stats["per_variant"]) == set(VARIANTEN)
    assert set(stats["gepaard_tegen_240"]) == set(VARIANTEN) - {BASIS}
    assert stats["overeenkomst"]["vergeleken"] == 120
    # De attributen zijn een deel van dit dict.
    assert len(json.dumps(stats, ensure_ascii=False).encode()) < 16_000


def test_oordeelsensor_toont_per_tijdblok_binnen_16_kb():
    bron = _sensorbron()
    blok = bron.split('key="verdict"')[1].split("ScalperSensor(")[0]
    assert '"per_tijdblok": _stats(d).get("per_tijdblok")' in blok
    trades = [
        _trade(T0 + timedelta(minutes=17 * i), (i % 5) - 2.0, (i % 4) - 1.0,
               regime=("tijdstop", "geen_tijdstop", "onbekend")[i % 3])
        for i in range(2000)
    ]
    stats = performance.compute(trades)
    attrs = {
        "text": stats.get("verdict_text"),
        "blocking_reasons": stats.get("blocking_reasons", []),
        "checks": {f"check_{i}": {"ok": False, "detail": "x" * 80} for i in range(12)},
        "gate_unlocked": False,
        "per_exitregime": performance.per_exitregime(trades),
        "per_tijdblok": performance.per_tijdblok(trades),
    }
    assert attrs["per_tijdblok"]["blokken"] > 500
    assert len(attrs["per_tijdblok"]["laatste_blokken"]) == 24
    assert len(json.dumps(attrs, ensure_ascii=False).encode()) < 16_000


def test_dashboard_en_paneel_tonen_varianten():
    from gold_scalper.dashboard import broker as B
    m = B._varianten(varianten_statistiek(_reeks(3, 1.0), {}))
    assert m["blokken"] == 3 and [r["variant"] for r in m["rijen"]] == list(VARIANTEN)
    assert m["rijen"][1]["t_blok"] is not None
    assert B._varianten(None) is None
    js = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
    assert "_renderVarianten(d)" in js and 'id="varianten"' in js


def test_versie_195():
    from gold_scalper import const
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION == "1.9.5"
    log = (PKG.parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert log.split("\n## ")[1].startswith("1.9.5")
    assert "Geen strategiewijziging" in log.split("## 1.9.4")[0]
