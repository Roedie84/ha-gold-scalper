"""1.6.0: t-statistiek over clusters van op elkaar volgende trades.

Live op 7 oktober: vier trades tussen 13:55 en 13:59, herinstap telkens ~10 s
na sluiten. Die zijn niet onafhankelijk; per trade tellen maakt de toets te
zeker over de steekproefgrootte.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.storage.performance import (  # noqa: E402
    CLUSTER_MINUTEN,
    cluster_resultaten,
    compute,
)
from gold_scalper.storage.database import Trade  # noqa: E402

T0 = datetime(2026, 10, 7, 13, 55, tzinfo=timezone.utc)


def _trade(i, open_dt, minuten, pnl):
    t = Trade(
        run_id=1, mode="demo", symbol="GOLD", side="sell", volume=0.01,
        open_time=open_dt.isoformat(), open_price=4123.0, open_mid=4122.7, open_spread=0.6,
        close_time=(open_dt + timedelta(minutes=minuten)).isoformat(),
        close_price=4124.0, net_pnl=pnl, gross_pnl=pnl, total_cost=0.5,
    )
    t.id = i
    return t


def test_herinstap_binnen_tien_minuten_is_een_cluster():
    a = _trade(1, T0, 1, -8.55)
    b = _trade(2, T0 + timedelta(minutes=1, seconds=10), 1, -11.86)
    c = _trade(3, T0 + timedelta(minutes=2, seconds=20), 1, -3.36)
    assert cluster_resultaten([a, b, c]) == [-8.55 + -11.86 + -3.36]


def test_een_lange_pauze_begint_een_nieuw_cluster():
    a = _trade(1, T0, 1, 2.0)
    b = _trade(2, T0 + timedelta(minutes=CLUSTER_MINUTEN + 5), 1, 3.0)
    assert cluster_resultaten([a, b]) == [2.0, 3.0]


def test_compute_geeft_beide_t_waarden():
    trades = []
    for i in range(6):
        start = T0 + timedelta(hours=i)
        trades.append(_trade(2 * i, start, 1, -2.0 - i))
        trades.append(_trade(2 * i + 1, start + timedelta(minutes=2), 1, -1.0))
    s = compute(trades)
    assert s["clusters"] == 6
    assert s["t_statistic_per_trade"] != s["t_statistic"]
    assert "6 clusters uit 12 trades" in s["t_basis"]
