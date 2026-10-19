"""2.15.0: marktomstandigheden bij de instap van een veldproeftrade vastleggen."""
import math
from datetime import datetime, timedelta, timezone

from gold_scalper.strategy import veldproef as vp
from gold_scalper.strategy.scalping import ScalpConfig

T0 = datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)


def _vul(m, minuten=2400, stap=lambda i: 4100 + 5 * math.sin(i / 7) + i * 0.05):
    for i in range(minuten * 2):
        m.voeg_toe(stap(i / 2), T0 + timedelta(seconds=30 * i), True)


def test_kenmerken_hebben_context():
    m = vp.MeerTijdvakken()
    _vul(m)
    k = m.kenmerken("5m")
    c = k.context
    assert set(c) == {"trend", "ema_dist", "momentum", "rsi", "adx"}
    assert c["trend"] == 1            # stijgende reeks: EMA50 loopt op
    assert 0 <= c["rsi"] <= 100 and c["adx"] >= 0


def test_signaal_draagt_de_context_en_de_hogere_trend():
    m = vp.MeerTijdvakken()
    _vul(m)
    cfg = ScalpConfig()
    gezien = 0
    for naam in vp.namen():
        s = vp.evalueer(naam, m, 4300.0, 4300.3, cfg)
        if s.components.get("tijdvak") is None:
            continue
        gezien += 1
        assert s.components["trend"] == m.kenmerken("30m").context["trend"]
        assert "adx" in s.components and "rsi_reversion" in s.components
    assert gezien > 0


def test_context_beslist_niets():
    m = vp.MeerTijdvakken()
    _vul(m)
    cfg = ScalpConfig()
    voor = {n: (s.should_trade, s.direction, s.stop_loss, s.take_profit)
            for n in vp.namen() for s in [vp.evalueer(n, m, 4300.0, 4300.3, cfg)]}
    for tf in vp.TIJDVAKKEN:
        k = m.kenmerken(tf)
        if k is not None:
            k.context = {}
    na = {n: (s.should_trade, s.direction, s.stop_loss, s.take_profit)
          for n in vp.namen() for s in [vp.evalueer(n, m, 4300.0, 4300.3, cfg)]}
    assert voor == na
    assert vp.VELDPROEF_VERSIE == "veldproef-2.1.0"   # geen nieuwe run


def test_context_bij_een_fout_leeg():
    assert vp._context(None, [1.0] * 5, [1.0] * 5, 1.0, 0.0) == {}
