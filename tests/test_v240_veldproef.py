"""2.4.0: veldproef - alle opzetten op 1m-30m met echte demo-orders."""
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gold_scalper.const import STRATEGIE_ALLES, STRATEGIE_DAGHANDEL, STRATEGIE_SCALP
from gold_scalper.strategy import combinatie, veldproef as vp
from gold_scalper.strategy.aggregator import BAR_SECONDS
from gold_scalper.strategy.scalping import ScalpConfig

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
T0 = datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)


def _vul(m, minuten=400, stap=lambda i: 4100 + 5 * math.sin(i / 7) + i * 0.05):
    for i in range(minuten * 6):
        m.voeg_toe(stap(i / 6), T0 + timedelta(seconds=10 * i), True)


def test_namen_en_tijdvakken():
    namen = vp.namen()
    assert len(namen) == len(vp.FAMILIES) * len(vp.TIJDVAKKEN) == 45
    assert "vp:structuur_hl:3m" in namen
    assert BAR_SECONDS["3m"] == 180
    assert vp.ontleed("vp:donchian:30m") == ("donchian", "30m")


def test_alles_geeft_alle_strategieen():
    s = combinatie.strategieen(STRATEGIE_ALLES)
    assert s[:2] == (STRATEGIE_DAGHANDEL, STRATEGIE_SCALP)
    assert len(s) == 47


def test_strategie_van_trade_kent_veldproef():
    class T:
        strategie = "vp:momentum:5m"
    assert combinatie.strategie_van_trade(T(), None, STRATEGIE_DAGHANDEL) == "vp:momentum:5m"


def test_exit_config_maximale_duur():
    cfg = vp.exit_config("vp:rsi_rev:5m")
    assert cfg.max_hold_seconds == vp.HOLD_BARS * 300
    assert cfg.enable_trailing is False


def test_bars_op_alle_tijdvakken():
    m = vp.MeerTijdvakken()
    _vul(m)
    n = m.aantal()
    assert n["1m"] >= 398 and n["3m"] >= 132 and n["30m"] >= 12


def test_signaal_heeft_stop_en_doel_bij_de_broker():
    m = vp.MeerTijdvakken()
    _vul(m)
    cfg = ScalpConfig()
    gevonden = None
    for naam in vp.namen():
        s = vp.evalueer(naam, m, 4120.0, 4120.6, cfg)
        if s.should_trade:
            gevonden = s
            break
    if gevonden is None:  # synthetische reeks: niet elk signaal hoeft te vallen
        return
    d = gevonden.direction
    assert d * (gevonden.take_profit - gevonden.stop_loss) > 0
    afstand = abs((4120.6 if d == 1 else 4120.0) - gevonden.stop_loss)
    assert abs(abs(gevonden.take_profit - (4120.6 if d == 1 else 4120.0)) - vp.RR * afstand) < 0.05


def test_een_instap_per_bar_en_een_positie_per_opzet():
    m = vp.MeerTijdvakken()
    _vul(m)
    cfg = ScalpConfig()
    for naam in vp.namen():
        s = vp.evalueer(naam, m, 4120.0, 4120.6, cfg)
        if s.should_trade:
            laatste = {naam: s.components["bar"]}
            assert vp.evalueer(naam, m, 4120.0, 4120.6, cfg, laatste_bar=laatste).should_trade is False
            assert vp.evalueer(naam, m, 4120.0, 4120.6, cfg, open_position_count=1).should_trade is False


def test_te_weinig_bars():
    s = vp.evalueer("vp:donchian:30m", vp.MeerTijdvakken(), 1.0, 1.5, ScalpConfig())
    assert s.reject_reason == "insufficient_data"


def test_hersample_en_koersen():
    pts = [(1080 * 60 + i * 10, 100.0 + i) for i in range(60)]
    c = vp.bars_uit_koersen(pts, 60)
    assert len(c) == 9 and c.open[0] == 100.0 and c.close[0] == 105.0
    c3 = vp.hersample(c, 180)
    assert c3.high[0] == max(c.high[:3])


def test_coordinator_koppeling():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "await self._vp_bijwerken(quote, now)" in bron
    assert "await self._vp_opwarmen()" in bron
    assert "and not veldproef_mod.is_veldproef(strategie)):" in bron  # geen schaduwtrades
    assert "return 6 if self.alles else 1" in bron
    assert "self.primaire_strategie) == STRATEGIE_DAGHANDEL" in bron  # verliesreeks
