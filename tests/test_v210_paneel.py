"""2.1.0: paneel - uurgrafiek en instapmarkers met de strategie."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.dashboard import broker as B  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
JS = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")


def test_markers_dragen_de_strategie():
    rij = {"open_time": "2026-10-12T10:00:00+00:00", "close_time": "2026-10-12T11:00:00+00:00",
           "side": "buy", "open_price": 4100.0, "close_price": 4110.0, "net_pnl": 9.5,
           "strategie": "daghandel"}
    m = B._markers([rij], None, {"primaire_strategie": "scalp"})
    assert m[0]["strategie"] == "daghandel"
    rij2 = {**rij, "strategie": None}
    assert B._markers([rij2], None, {"primaire_strategie": "scalp"})[0]["strategie"] == "scalp"


def test_open_posities_krijgen_een_instapmarker():
    rij = {"open_time": "2026-10-12T10:00:00+00:00", "side": "sell", "open_price": 4100.0,
           "strategie": "scalp"}
    m = B._open_markers([rij], {})
    assert m[0]["open"] and m[0]["s_t"] is None and m[0]["richting"] == "short"
    assert m[0]["strategie"] == "scalp"


def test_daghandel_telt_af_tot_2045_utc():
    open_t = int(datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc).timestamp())
    assert B._sluit_daghandel_s(open_t) == 10 * 3600 + 45 * 60
    pos = SimpleNamespace(ticket="T1", side="buy", units=5.0, open_price=4100.0,
                          stop_loss=4080.0, take_profit=None, open_time=None)
    data = {"open_positions": [pos], "primaire_strategie": "daghandel"}
    db = [{"broker_ticket": "T1", "open_time": "2026-10-12T10:00:00+00:00", "strategie": "daghandel"}]
    quote = SimpleNamespace(bid=4105.0, ask=4105.6)
    rij = B._position_rows(data, db, {"time_stop_seconds": 240, "max_hold_seconds": 900,
                                      "time_stop_deadzone_atr": 0.3}, quote)[0]
    assert rij["strategie"] == "daghandel" and rij["tijdstop_s"] is None
    assert rij["max_duur_s"] == 10 * 3600 + 45 * 60
    db[0]["strategie"] = "scalp"
    rij = B._position_rows(data, db, {"time_stop_seconds": 240, "max_hold_seconds": 900,
                                      "time_stop_deadzone_atr": 0.3}, quote)[0]
    assert rij["tijdstop_s"] == 240 and rij["max_duur_s"] == 900


def test_js_uurgrafiek_en_letters():
    assert "3600 / base" in JS
    assert 'dh ? "D" : "S"' in JS and 'class="strat' in JS
    assert "strategie" in B._TRADE_KOLOMMEN_EXTRA


def test_v221_strategiekolom_en_bijkoop():
    assert "<th>Strategie</th>" in JS and "+ bijkoop" in JS
    assert "open_reason" in B._TRADE_KOLOMMEN_EXTRA
    pos = SimpleNamespace(ticket="T9", side="sell", units=0.5, open_price=4100.0,
                          stop_loss=4105.0, take_profit=None, open_time=None)
    db = [{"broker_ticket": "T9", "open_time": "2026-10-12T10:00:00+00:00",
           "strategie": "scalp", "open_reason": "pyramide van T1"}]
    rij = B._position_rows({"open_positions": [pos]}, db, {}, SimpleNamespace(bid=4099.0, ask=4099.6))[0]
    assert rij["bijkoop"] is True and rij["strategie"] == "scalp"
