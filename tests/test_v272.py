"""2.7.2: deelsluiting en rest niet meer aan dezelfde brokertransactie;
stop met winst apart in de exitverdeling."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from gold_scalper.broker.ig_capital import match_transaction
from gold_scalper.learning.exit_stats import exit_stats

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _tx(close_level, gesloten, pnl, ref):
    return {"openLevel": "4147.72", "closeLevel": str(close_level), "size": "+5.3",
            "openDateUtc": "2026-10-14T06:00:01", "dateUtc": gesloten,
            "profitAndLoss": f"€{pnl}", "currency": "€", "reference": ref,
            "instrumentName": "Spot Gold converted at 0.885"}


TX = [_tx(4155.12, "2026-10-14T06:11:40", 34.71, "DEEL"),
      _tx(4157.54, "2026-10-14T06:25:00", 46.10, "REST")]


def test_rest_krijgt_eigen_transactie():
    m = match_transaction(TX, "T1", 4147.72, "buy", 5.3, "2026-10-14T06:00:01+00:00",
                          "2026-10-14T06:25:00+00:00")
    assert m["reference"] == "REST" and m["exit_price"] == 4157.54


def test_deelsluiting_krijgt_eigen_transactie():
    m = match_transaction(TX, "T1-deel", 4147.72, "buy", 5.3, "2026-10-14T06:00:01+00:00",
                          "2026-10-14T06:11:40+00:00")
    assert m["reference"] == "DEEL"


def test_zonder_sluitmoment_ongewijzigd():
    m = match_transaction(TX, "T1", 4147.72, "buy", 5.3, "2026-10-14T06:00:01+00:00")
    assert m is not None


def test_prijs_blijft_zwaarder_dan_sluitmoment():
    tx = [dict(TX[0], openLevel="4147.80", dateUtc="2026-10-14T06:25:00"), TX[0]]
    m = match_transaction(tx, "T1", 4147.72, "buy", 5.3, "2026-10-14T06:00:01+00:00",
                          "2026-10-14T06:25:00+00:00")
    assert m["open_price"] == 4147.72


def _t(reden, netto):
    return SimpleNamespace(close_time="x", close_reason=reden, net_pnl=netto,
                           reconciled_close_reason=None, reconciliation_status=None)


def test_stop_met_winst_apart():
    s = exit_stats([_t("stop_loss", 9.0), _t("stop_loss", -90.0), _t("stop_loss", 7.0),
                    _t("take_profit", 50.0)])
    assert s["stop_loss"]["n"] == 3
    assert s["stop_winst"]["n"] == 2 and s["stop_verlies"]["n"] == 1
    assert s["stop_winst"]["pct"] == 50.0


def test_negatieve_kosten_worden_opnieuw_gemeten():
    bron = (PKG / "learning" / "afstemming.py").read_text(encoding="utf-8")
    assert "kosten_fout = trade.total_cost is not None and trade.total_cost < -0.01" in bron


def test_paneel():
    js = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
    assert "stop met winst" in js and "winst vastgezet" in js
    py = (PKG / "dashboard" / "broker.py").read_text(encoding="utf-8")
    assert '"stop_winst_pct"' in py
