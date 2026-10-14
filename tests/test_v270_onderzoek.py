"""2.7.0: onderzoeksrapport op echte trades (P4-P6 verbeterplan)."""
from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.learning import onderzoek as O  # noqa: E402

T0 = datetime(2026, 10, 14, 4, 40, tzinfo=timezone.utc)


def _trade(i, minuut, side="buy", netto=10.0, strat="vp:pullback:15m", deel=False, **kw):
    t = T0 + timedelta(minutes=minuut)
    return {
        "id": i, "strategie": strat, "side": side, "open_time": t.isoformat(),
        "close_time": (t + timedelta(minutes=5)).isoformat(), "net_pnl": netto / 0.9,
        "net_pnl_account": netto, "gross_pnl": (netto + 5) / 0.9, "total_cost": 5 / 0.9,
        "fx_rate": 0.9, "broker_ticket": f"T{i}" + ("-deel" if deel else ""),
        "reconciliation_status": "reconciled", "open_spread": 0.6, "entry_atr": 5.0, **kw,
    }


def test_clusters_per_richting_binnen_10_minuten():
    trades = [_trade(1, 0), _trade(2, 3), _trade(3, 5, side="sell"), _trade(4, 30)]
    cl = O.clusters(trades)
    assert sorted(len(c) for c in cl) == [1, 1, 2]


def test_deelsluiting_telt_in_resultaat_niet_als_trade():
    k = O.kengetallen([_trade(1, 0, netto=20), _trade(1, 0, netto=15, deel=True)])
    assert k["trades"] == 1 and k["netto"] == 35.0 and k["clusters"] == 1


def test_kengetallen():
    trades = [_trade(i, 20 * i, netto=(30 if i % 2 else -10)) for i in range(10)]
    k = O.kengetallen(trades)
    assert k["trades"] == 10 and k["clusters"] == 10
    assert k["netto_per_trade"] == 10.0
    assert k["payoff"] == 3.0 and k["profit_factor"] == 3.0
    assert k["kosten_per_trade"] == 5.0
    assert k["afgestemd_pct"] == 100.0


def test_oordeel_eerlijk():
    assert O.oordeel({"clusters": 5}) == "te weinig data"
    assert O.oordeel({"clusters": 40, "netto_per_cluster": 3, "t_clusters": 2.5}) == "aantoonbare edge"
    assert O.oordeel({"clusters": 40, "netto_per_cluster": 3, "t_clusters": 1.2}) == "geen aantoonbare edge"
    assert O.oordeel({"clusters": 40, "netto_per_cluster": -3, "t_clusters": -2.5}) == "aantoonbaar verliesgevend"


def test_hypothese_alleen_op_bevestiging():
    h = O.HYPOTHESEN[0]
    rnd = random.Random(3)
    voor = [_trade(i, -2000 + 20 * i, netto=100.0) for i in range(40)]           # discovery: top
    na = [_trade(100 + i, 20 * i, netto=rnd.gauss(-5, 20)) for i in range(40)]    # confirmation: slecht
    uit = O.toets(h, voor + na)
    assert uit["discovery"]["netto_per_trade"] == 100.0
    assert uit["uitslag"] == "verworpen"


def test_hypothese_loopt_bij_te_weinig_clusters():
    uit = O.toets(O.HYPOTHESEN[0], [_trade(1, 0)])
    assert uit["uitslag"].startswith("loopt")


def test_andere_tijdvakken_horen_er_niet_bij():
    uit = O.toets(O.HYPOTHESEN[0], [_trade(1, 0, strat="vp:pullback:1m")])
    assert uit["confirmation"]["trades"] == 0


def test_segmenten_zijn_metingen():
    trades = [_trade(i, 20 * i, side=("buy" if i % 2 else "sell"), entry_atr=float(i + 1))
              for i in range(12)]
    s = O.segmenten(trades)
    assert set(s["richting"]) == {"long", "short"}
    assert set(s["volatiliteit"]) <= {"laag", "normaal", "hoog"}
    assert "sessie" in s and "spread" in s


def test_sessies():
    assert O.sessie(datetime(2026, 10, 14, 3, tzinfo=timezone.utc)) == "Azie"
    assert O.sessie(datetime(2026, 10, 14, 13, tzinfo=timezone.utc)) == "Londen/New York"
    assert O.sessie(datetime(2026, 10, 14, 18, tzinfo=timezone.utc)) == "New York"


def test_rapport_en_samenvatting():
    r = O.rapport([_trade(i, 20 * i) for i in range(5)])
    s = O.samenvatting(r)
    assert s["oordeel"] == "te weinig data" and "H-GS-001" in s["hypotheses"]


def test_hypotheses_vooraf_vastgelegd():
    ids = [h.hypothesis_id for h in O.HYPOTHESEN]
    assert len(ids) == len(set(ids))
    for h in O.HYPOTHESEN:
        assert h.discovery_tot and h.confirmation_vanaf and h.rejection_rule
        assert h.discovery_tot <= h.confirmation_vanaf
