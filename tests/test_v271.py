"""2.7.1: H-GS-003 (uitsluiting 1m/3m/scalp) met schaduwtrades, en 'Bij TP'."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from gold_scalper.broker.exits import ExitManager
from gold_scalper.learning import onderzoek as O
from gold_scalper.strategy import uitgezet_schaduw as U
from gold_scalper.strategy import veldproef as vp
from gold_scalper.strategy.scalping import ScalpConfig

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
T0 = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)


def _sig(d=1, stop=4100.0, tp=4106.0, bar="b1", geldig=True):
    return SimpleNamespace(direction=d, stop_loss=stop, take_profit=tp, score=1.0,
                           geldig=geldig, components={"bar": bar})


def test_hypothese_geregistreerd_en_negatief():
    h = {x.hypothesis_id: x for x in O.HYPOTHESEN}["H-GS-003"]
    assert h.verwachting == "negatief" and h.bron_bevestiging == "schaduw_uitgezet"
    assert h.discovery_tot < h.confirmation_vanaf
    assert O._hoort_bij(h, {"strategie": "scalp"})
    assert O._hoort_bij(h, {"strategie": "vp:pullback:1m"})
    assert O._hoort_bij(h, {"strategie": "vp:pullback:3m"})
    assert not O._hoort_bij(h, {"strategie": "vp:pullback:5m"})
    assert "achteraf" in h.extra["eerlijk"]


def _rij(i, netto, strat="vp:ema_cross:1m", side="buy"):
    t = T0 + timedelta(minutes=20 * i)
    return U.als_onderzoeksrij({"id": i, "strategie": strat, "richting": 1 if side == "buy" else -1,
                                "open_time": t.isoformat(), "close_time": (t + timedelta(minutes=3)).isoformat(),
                                "open_spread": 0.7, "bruto": netto + 1, "kosten": 1.0, "netto": netto})


def test_uitslag_uit_schaduw_niet_uit_echte_trades():
    h = {x.hypothesis_id: x for x in O.HYPOTHESEN}["H-GS-003"]
    echt = [dict(_rij(i, 50.0), net_pnl_account=50.0) for i in range(40)]  # zou "verworpen" geven
    schaduw = [_rij(i, -10.0 + (i % 3)) for i in range(40)]
    r = O.toets(h, echt, schaduw)
    assert r["bron_bevestiging"] == "schaduw_uitgezet"
    assert r["uitslag"] == "bevestigd"
    assert O.toets(h, echt, [])["uitslag"].startswith("loopt")


def test_negatieve_hypothese_verworpen_bij_winst():
    h = {x.hypothesis_id: x for x in O.HYPOTHESEN}["H-GS-003"]
    schaduw = [_rij(i, 5.0 + (i % 3)) for i in range(40)]
    assert O.toets(h, [], schaduw)["uitslag"] == "verworpen"


def test_positieve_hypotheses_ongewijzigd():
    h = {x.hypothesis_id: x for x in O.HYPOTHESEN}["H-GS-001"]
    assert h.verwachting == "positief" and h.bron_bevestiging == "trades"


def test_boek_een_per_opzet_en_per_bar():
    b = U.UitgezetBoek()
    t = b.openen(strategie="vp:ema_cross:1m", signal=_sig(), bid=4101.0, ask=4101.7, nu=T0, units=10)
    assert t is not None and t.open_price == 4101.7 and t.reden == "uitgezet"
    assert b.openen(strategie="vp:ema_cross:1m", signal=_sig(bar="b2"), bid=4101.0, ask=4101.7,
                    nu=T0, units=10) is None  # al open
    assert b.openen(strategie="vp:ema_cross:3m", signal=_sig(geldig=False), bid=4101.0, ask=4101.7,
                    nu=T0, units=10) is None


def test_boek_sluit_op_doel_met_kosten():
    b = U.UitgezetBoek()
    naam = "vp:ema_cross:1m"
    b.openen(strategie=naam, signal=_sig(), bid=4101.0, ask=4101.7, nu=T0, units=10)
    ex = ExitManager(vp.exit_config(naam))
    gew = b.bijwerken(bid=4106.5, ask=4107.2, hoog=4107.0, laag=4101.0, nu=T0 + timedelta(seconds=60),
                      exits_voor=lambda n: ex, maat_voor=lambda t: vp.r_van(t.open_price, t.take_profit))
    assert gew and not b.open_trades
    t = b.gesloten[0]
    assert t.close_reason == "take_profit"
    assert math.isclose(t.netto, (4106.0 - 4101.7) * 10 - 2 * U.SLIPPAGE_PER_ZIJDE * 10, abs_tol=1e-6)
    # zelfde bar mag niet opnieuw
    assert b.openen(strategie=naam, signal=_sig(), bid=4101.0, ask=4101.7, nu=T0, units=10) is None


def test_veldproef_uitgezet_geeft_signaal_zonder_order():
    m = vp.MeerTijdvakken()
    for i in range(400 * 6):
        m.voeg_toe(4100 + 5 * math.sin(i / 42) + i / 120, T0 + timedelta(seconds=10 * i), True)
    cfg = ScalpConfig()
    for naam in vp.namen():
        s = vp.evalueer(naam, m, 4120.0, 4120.6, cfg)
        if s.should_trade:
            u = vp.evalueer(naam, m, 4120.0, 4120.6, cfg, uitgezet={naam: {"n": 300, "t": -5}})
            assert u.should_trade is False and u.reject_reason == "opzet_uitgezet"
            assert u.geldig and u.stop_loss == s.stop_loss and u.direction == s.direction
            return
    raise AssertionError("geen enkel signaal in de testreeks")


def test_database(tmp_path):
    from gold_scalper.storage.database import TradeDatabase
    db = TradeDatabase(str(tmp_path / "gs.db"))
    db.connect()
    b = U.UitgezetBoek()
    t = b.openen(strategie="scalp", signal=_sig(), bid=4101.0, ask=4101.7, nu=T0, units=10)
    db.bewaar_uitgezet(t)
    assert db.uitgezet_open_laten_vervallen() == 1
    t2 = b.openen(strategie="vp:inside:3m", signal=_sig(), bid=4101.0, ask=4101.7, nu=T0, units=5)
    t2.status, t2.netto = "gesloten", -3.0
    db.bewaar_uitgezet(t2)
    rijen = db.uitgezet_gesloten("2026-10-01")
    assert len(rijen) == 1 and rijen[0]["strategie"] == "vp:inside:3m"
    assert U.als_onderzoeksrij(rijen[0])["net_pnl"] == -3.0


def test_coordinator_en_paneel():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "await self._werk_uitgezet_bij(quote, now)" in bron
    assert 'r_signal.reject_reason == "opzet_uitgezet"' in bron
    assert "onderzoek_mod.rapport, rijen, schaduw" in bron
    js = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
    assert 'cel("Bij TP"' in js and ">Bij TP</th>" in js
