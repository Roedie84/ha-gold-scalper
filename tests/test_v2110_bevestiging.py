"""2.11.0: schaduwmeting instap met bevestiging (15m)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from gold_scalper.strategy import bevestiging as B

T0 = datetime(2026, 10, 15, 9, 15, 5, tzinfo=timezone.utc)


def _sig(richting=1, stop=4090.0, doel=4120.0, bar="b1"):
    return SimpleNamespace(direction=richting, stop_loss=stop, take_profit=doel,
                           components={"bar": bar})


HOLD = SimpleNamespace(evaluate=lambda **k: SimpleNamespace(kind="hold", new_stop=None))


def _stap(boek, nu, bid, ask, bar=None, hoog=None, laag=None, vanaf=None):
    return boek.bijwerken(bid=bid, ask=ask, hoog=hoog, laag=laag, uitersten_vanaf=vanaf,
                          nu=nu, bar_1m=bar, exits_voor=lambda n: HOLD,
                          maat_voor=lambda t: 5.0)


def test_alleen_15m_en_een_per_bar():
    b = B.BevestigingBoek()
    assert b.aanmelden(strategie="vp:rsi_rev:5m", signal=_sig(), bid=4100, ask=4100.2, nu=T0) is None
    assert b.aanmelden(strategie="vp:rsi_rev:15m", signal=_sig(), bid=4100, ask=4100.2, nu=T0)
    assert b.aanmelden(strategie="vp:rsi_rev:15m", signal=_sig(), bid=4100, ask=4100.2, nu=T0) is None


def test_bevestigd_en_beide_naar_het_doel():
    b = B.BevestigingBoek()
    p = b.aanmelden(strategie="vp:rsi_rev:15m", signal=_sig(), bid=4100.0, ask=4100.2, nu=T0)
    start = (T0 + timedelta(seconds=55)).replace(second=0).timestamp()      # 9:16:00
    bar = [start, 4100.1, 4101.5, 4099.8, 4101.2, 1]                       # sluit omhoog
    _stap(b, T0 + timedelta(seconds=65), 4101.2, 4101.4, bar=bar)
    assert p.status == "bevestigd" and p.bevestigd.open_price == 4101.4
    klaar = _stap(b, T0 + timedelta(minutes=5), 4120.5, 4120.7,
                  hoog=4121.0, laag=4119.0, vanaf=T0 + timedelta(minutes=4))
    assert klaar and p.direct.close_reason == "take_profit"
    assert p.bevestigd.close_reason == "take_profit"
    rij = p.als_rij()
    assert rij["direct_r"] > rij["bevestigd_r"] > 0       # later in, dus minder R


def test_niet_bevestigd_telt_als_nul():
    b = B.BevestigingBoek()
    p = b.aanmelden(strategie="vp:rsi_rev:15m", signal=_sig(), bid=4100.0, ask=4100.2, nu=T0)
    start = (T0 + timedelta(seconds=55)).replace(second=0).timestamp()
    _stap(b, T0 + timedelta(seconds=65), 4099.0, 4099.2,
          bar=[start, 4100.1, 4100.3, 4098.9, 4099.1, 1])                   # sluit omlaag
    assert p.status == "niet_bevestigd"
    _stap(b, T0 + timedelta(minutes=3), 4089.0, 4089.2, hoog=4092.0, laag=4088.0,
          vanaf=T0 + timedelta(minutes=2))
    assert p.direct.close_reason == "stop_loss"
    assert p.r_bevestigd() == 0.0 and p.r_direct() < -0.9


def test_bar_van_voor_het_signaal_telt_niet_en_vervalt():
    b = B.BevestigingBoek()
    p = b.aanmelden(strategie="vp:rsi_rev:15m", signal=_sig(), bid=4100.0, ask=4100.2, nu=T0)
    oud = [T0.replace(second=0).timestamp(), 4099, 4101, 4098, 4101, 1]   # begon vóór het signaal
    _stap(b, T0 + timedelta(seconds=30), 4100, 4100.2, bar=oud)
    assert p.status == "wacht"
    _stap(b, T0 + timedelta(seconds=B.MAX_WACHT_S + 10), 4100, 4100.2, bar=oud)
    assert p.status == "vervallen"


def test_statistiek_en_oordeel():
    rijen = [{"status": "bevestigd", "direct_r": -0.5, "bevestigd_r": 0.4} for _ in range(20)]
    rijen += [{"status": "niet_bevestigd", "direct_r": -1.0, "bevestigd_r": 0.0} for _ in range(10)]
    rijen.append({"status": "bevestigd", "direct_r": 0.1, "bevestigd_r": 0.3})
    s = B.BevestigingBoek().statistiek(rijen)
    assert s["paren"] == 31 and s["bevestigd"] == 21 and s["niet_bevestigd"] == 10
    assert s["verschil_r_per_trade"] > 0 and s["oordeel"].startswith("bevestiging beter")
    assert B.BevestigingBoek().statistiek([])["oordeel"].startswith("te weinig")


def test_koppelingen():
    from pathlib import Path
    pkg = Path(__file__).resolve().parents[1] / "custom_components" / "gold_scalper"
    co = (pkg / "coordinator.py").read_text(encoding="utf-8")
    assert "self.bevestiging.aanmelden(" in co and "_werk_bevestiging_bij" in co
    assert '"bevestiging_15m"' in co
    db = (pkg / "storage" / "database.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS bevestiging_schaduw" in db
    assert 'key="bevestiging_15m"' in (pkg / "sensor.py").read_text(encoding="utf-8")
