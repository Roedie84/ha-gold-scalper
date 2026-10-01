"""Rapport en diagnostiek na 5.4.0: uitslagen zichtbaar, metrieken gedefinieerd,
exits met noemer, en geen valutamelding meer als er wel wordt omgerekend."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.reconcile_audit import compare_positions
from gold_scalper.storage.database import Trade, TradeDatabase

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def test_the_currency_warning_stops_once_conversion_works():
    """Een waarschuwing die niet meer klopt, leer je negeren."""
    zonder = compare_positions([], [], expected_currency="USD",
                               account_currency="EUR", conversion_known=False)
    met = compare_positions([], [], expected_currency="USD",
                            account_currency="EUR", conversion_known=True)
    assert any(f.code == "valuta_verschilt" for f in zonder.findings)
    assert not any(f.code == "valuta_verschilt" for f in met.findings)


def test_user_actions_show_their_result():
    """Geslaagde acties logden op informatieniveau en het logboek toont alleen
    waarschuwingen: een geslaagde backtest leek mislukt."""
    init = (PKG / "__init__.py").read_text(encoding="utf-8")
    for sleutel in ('"backtest"', '"validatie"', '"lab"', '"afstemming"', '"antwoorden"'):
        assert sleutel in init, sleutel
    assert '"persistent_notification", "create"' in init


def test_metric_definitions_are_in_diagnostics():
    diag = (PKG / "diagnostics.py").read_text(encoding="utf-8")
    assert '"metric_definitions": METRICS' in diag


def test_the_report_shows_exits_with_denominator(tmp_path):
    from gold_scalper.dashboard.report import build_report

    db = TradeDatabase(tmp_path / "e.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    for i, reden in enumerate(("take_profit", "stop_loss", "broker_gesloten_gecorrigeerd")):
        db.insert_trade(Trade(
            run_id=run, mode="demo", symbol="GOLD", side="buy", volume=0.01,
            open_time=f"2026-09-28T1{i}:00:00+00:00", open_price=4300.0,
            open_mid=4300.0, open_spread=0.6,
            close_time=f"2026-09-28T1{i}:20:00+00:00", net_pnl=1.0,
            gross_pnl=2.0, total_cost=1.0, close_reason=reden,
            original_close_reason=reden if i < 2 else "unknown",
        ))
    html = build_report(db, run)
    assert "Hoe trades eindigden" in html and "van 3" in html
    assert "ondergrenzen" in html


def test_the_report_names_the_drawdown_basis(tmp_path):
    from gold_scalper.dashboard.report import build_report

    db = TradeDatabase(tmp_path / "dd.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    db.insert_trade(Trade(
        run_id=run, mode="demo", symbol="GOLD", side="buy", volume=0.01,
        open_time="2026-09-28T10:00:00+00:00", open_price=4300.0,
        open_mid=4300.0, open_spread=0.6,
        close_time="2026-09-28T10:20:00+00:00", net_pnl=1.0,
        gross_pnl=2.0, total_cost=1.0, close_reason="stop_loss",
    ))
    for eq in (7300.0, 7200.0):
        db.record_equity(run, eq, eq, 0, 0.0)
    assert "equity in" in build_report(db, run)
