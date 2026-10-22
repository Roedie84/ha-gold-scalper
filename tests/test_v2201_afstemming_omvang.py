"""2.20.1 - de twee IG-restposities van 15-10 werden niet overgenomen.

Live na de herstart van 22-10 17:23 (2.20.0): IG nog steeds 2 afwijkingen,
instap 4143,62 (uitstap 4154,07 tegen 4150,96) en 4143,83 (4154,13 tegen
4151,06). Het waren de resten (2,675 oz) van twee posities die twee keer
gedeeltelijk sloten (5,35 en 2,675 oz). IG rondt de omvang op honderdsten af:
2,68. En 2,68 - 2,675 is in drijvende komma 0,0050000000000003, net boven de
omvangsgrens van 0,005. Daardoor was de koppeling niet sterk en niet
eenduidig. Hieronder dat scenario met de meldingen zoals ze live stonden.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.learning.afstemming import stem_af  # noqa: E402
from gold_scalper.storage.database import Trade  # noqa: E402

NU = datetime(2026, 10, 22, 15, 40, tzinfo=timezone.utc)
OPEN = "2026-10-15T07:15:05.351673+00:00"


def _t(i, ticket, instap, volume, dicht, uit, pnl, stop):
    t = Trade(run_id=1, mode="demo", symbol="GOLD", side="buy", volume=volume,
              open_time=OPEN, open_price=instap, open_mid=instap, open_spread=0.8,
              close_time=dicht, close_price=uit, net_pnl=pnl, broker_ticket=ticket,
              close_reason="stop_loss", cost_source="measured", stop_loss=stop,
              take_profit=4162.48)
    t.id = i
    return t


def _tx(ref, instap, uit, omvang, dicht, eur):
    return {"reference": ref, "openLevel": str(instap), "closeLevel": str(uit),
            "size": f"+{omvang}", "openDateUtc": "2026-10-15T07:15:05",
            "dateUtc": dicht, "profitAndLoss": f"E{eur:.2f}",
            "instrumentName": "Spot Gold ($1) converted at 0.8862"}


def _scenario(rest_omvang="2.68"):
    trades = [
        _t(3058, "A-deel", 4143.62, 0.0535, "2026-10-15T08:14:51.599+00:00", 4154.22, 56.71, 4144.6),
        _t(3063, "A-deel", 4143.62, 0.02675, "2026-10-15T08:18:29.844+00:00", 4154.07, 27.9036, 4148.7),
        _t(3052, "A", 4143.62, 0.02675, "2026-10-15T08:43:41.245+00:00", 4154.07, 27.9036, 4150.96),
        _t(3057, "B-deel", 4143.83, 0.0535, "2026-10-15T08:14:51.448+00:00", 4153.39, 51.146, 4144.8),
        _t(3062, "B-deel", 4143.83, 0.02675, "2026-10-15T08:18:28.642+00:00", 4154.13, 27.4962, 4148.9),
        _t(3053, "B", 4143.83, 0.02675, "2026-10-15T08:43:41.245+00:00", 4154.13, 27.4962, 4151.065),
    ]
    txs = [
        _tx("a1", 4143.62, 4154.22, "5.35", "2026-10-15T08:14:51", 50.26),
        _tx("a2", 4143.62, 4154.07, "2.67", "2026-10-15T08:18:29", 24.77),
        _tx("a3", 4143.62, 4150.96, rest_omvang, "2026-10-15T08:31:00", 17.39),
        _tx("b1", 4143.83, 4153.39, "5.35", "2026-10-15T08:14:51", 45.33),
        _tx("b2", 4143.83, 4154.13, "2.67", "2026-10-15T08:18:28", 24.37),
        _tx("b3", 4143.83, 4151.06, rest_omvang, "2026-10-15T08:31:00", 17.13),
    ]
    return trades, txs


def test_rest_met_omvang_op_honderdsten_wordt_overgenomen():
    trades, txs = _scenario("2.68")
    u = stem_af(trades, txs, 0.8924, NU, 100.0)
    assert u.in_orde, [a.uitleg for a in u.afwijkingen]
    per_id = {o["trade_id"]: o["velden"] for o in u.overnames}
    assert per_id[3052]["close_price"] == pytest.approx(4150.96)
    assert per_id[3053]["close_price"] == pytest.approx(4151.06)
    assert per_id[3052]["net_pnl_account"] == pytest.approx(17.39)
    # De deelsluitingen houden hun eigen (juiste) uitstap.
    assert "close_price" not in per_id.get(3063, {})
    assert "close_price" not in per_id.get(3062, {})


@pytest.mark.parametrize("omvang", ["2.67", "2.675", "2.68"])
def test_afronding_naar_boven_en_beneden_gelijk_behandeld(omvang):
    trades, txs = _scenario(omvang)
    assert stem_af(trades, txs, 0.8924, NU, 100.0).in_orde

