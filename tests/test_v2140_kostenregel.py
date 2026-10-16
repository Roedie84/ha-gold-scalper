"""2.14.0 (Ruud 16-10): opzetten waarvan de bruto beweging de kosten niet dekt, uit."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.strategy import veldproef as vp  # noqa: E402


def test_bruto_dekt_kosten_niet_uit():
    uit = vp.kosten_uitgezet({
        "vp:momentum:3m": {"n": 106, "bruto": 198, "kosten": 488, "netto": -290},
        "vp:rsi_rev:5m": {"n": 70, "bruto": -139, "kosten": 235, "netto": -374},
        "vp:structuur_hl:3m": {"n": 18, "bruto": 819, "kosten": 93, "netto": 727},
        "vp:donchian:3m": {"n": 40, "bruto": 686, "kosten": 132, "netto": 554},
        "vp:rsi_rev:1m": {"n": 47, "bruto": 197, "kosten": 386, "netto": -190},
        "daghandel": {"n": 99, "bruto": -1, "kosten": 50, "netto": -51},
    })
    assert set(uit) == {"vp:momentum:3m", "vp:rsi_rev:5m"}
    assert uit["vp:momentum:3m"]["regel"] == "kosten"


def test_te_weinig_trades_blijft_aan():
    assert vp.kosten_uitgezet({"vp:momentum:1m": {"n": 39, "bruto": -500, "kosten": 300, "netto": -800}}) == {}


def test_weigertekst():
    uit = {"vp:momentum:3m": {"n": 106, "bruto": 198.0, "kosten": 488.0, "netto": -290.0,
                              "t": None, "regel": "kosten"}}
    from types import SimpleNamespace
    sig = vp.evalueer("vp:momentum:3m", {}, 4000.0, 4010.0, SimpleNamespace(max_spread=1.0), 0, 1e9, None, uitgezet=uit)
    assert sig.reject_reason == "opzet_uitgezet"
    assert "dekt de kosten" in sig.reason


def test_database_per_positie():
    from gold_scalper.storage.database import Trade, TradeDatabase
    with tempfile.TemporaryDirectory() as d:
        db = TradeDatabase(os.path.join(d, "t.db"))
        db.connect()
        for tk, b, k in (("A", 10.0, 3.0), ("A-deel", 5.0, 1.0), ("B", -4.0, 3.0)):
            t = Trade(run_id=1, mode="demo", symbol="XAUUSD", side="buy", volume=0.01,
                      open_time="2026-10-16T10:00:00", open_price=1.0, open_mid=1.0,
                      open_spread=0.1, broker_ticket=tk, strategie="vp:momentum:3m",
                      close_time="2026-10-16T10:10:00", gross_pnl=b, total_cost=k, net_pnl=b - k)
            db.insert_trade(t)
        r = db.bruto_kosten_per_strategie("vp:")["vp:momentum:3m"]
        assert r["n"] == 2 and r["bruto"] == 11.0 and r["kosten"] == 7.0 and r["netto"] == 4.0
