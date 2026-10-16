"""2.13.4 (Ruud 16-10): "Omgekeerde trades ook meenemen in hoe trades eindigen"."""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.learning.exit_stats import exit_stats, is_omkeer  # noqa: E402


def _t(reden, net, stop_reden=None):
    return SimpleNamespace(close_time="2026-10-16T10:00:00", close_reason=reden,
                           original_close_reason=reden, reconciled_close_reason=None,
                           net_pnl=net, stop_reden=stop_reden)


def test_soorten():
    assert is_omkeer(_t("omkeer door vp:inside:15m: signaal gedraaid, verlies beperkt", -5)) == "gesloten"
    assert is_omkeer(_t("signaal gedraaid, kleine winst genomen (+0.05 USD/oz)", 1)) == "gesloten"
    assert is_omkeer(_t("stop_loss", 20, "signaal gedraaid: winst vastgezet, stop 0.40")) == "vastgezet"
    assert is_omkeer(_t("stop_loss", 20, "break-even")) is None
    assert is_omkeer(_t("take_profit", 20, "signaal gedraaid: winst vastgezet")) is None


def test_telling():
    s = exit_stats([
        _t("take_profit", 10),
        _t("stop_loss", -10),
        _t("stop_loss", 8, "omkeer door vp:x:3m: signaal gedraaid: winst vastgezet"),
        _t("omkeer door vp:x:3m: signaal gedraaid, verlies beperkt", -3),
    ])
    assert s["noemer"] == 4
    assert s["omkeer"] == {"n": 2, "pct": 50.0, "netto": 5.0}
    assert s["omkeer_gesloten"]["n"] == 1 and s["omkeer_vastgezet"]["winst_n"] == 1
    # uitsplitsing, geen extra soort: gewone telling ongewijzigd
    assert s["stop_loss"]["n"] == 2 and s["eigen_exit"]["n"] == 1


def test_stop_reden_niet_overschreven_door_update():
    from gold_scalper.storage.database import TradeDatabase, Trade
    with tempfile.TemporaryDirectory() as d:
        db = TradeDatabase(os.path.join(d, "t.db"))
        db.connect()
        t = Trade(run_id=1, mode="demo", symbol="XAUUSD", side="buy", volume=0.01,
                  open_time="2026-10-16T10:00:00", open_price=1.0, open_mid=1.0,
                  open_spread=0.1, broker_ticket="A1")
        t.id = db.insert_trade(t)
        db.stop_gewijzigd("A1", "2026-10-16T10:05:00", "signaal gedraaid: winst vastgezet")
        t.close_time = "2026-10-16T10:10:00"
        t.close_reason = "stop_loss"
        t.net_pnl = 4.0
        db.update_trade(t)
        terug = db.closed_trades()[0]
        assert terug.stop_reden == "signaal gedraaid: winst vastgezet"
        assert is_omkeer(terug) == "vastgezet"
