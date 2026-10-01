"""Provenance en methodologische segmentatie.

Run 97 begon voor de reparatie van 5.3.2 en liep daarna door, omdat een
codereparatie de vingerafdruk niet veranderde. Hij meet daardoor twee
gedragingen door elkaar: onzichtbare posities zonder exitbeheer en met
gestapelde trades, en daarna zichtbare posities met werkend exitbeheer.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.const import EXECUTION_SEMANTICS_VERSION, INTEGRATION_VERSION
from gold_scalper.storage.database import Trade, TradeDatabase

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def _trade(run, open_iso, close_iso, ticket):
    return Trade(
        run_id=run, mode="demo", symbol="GOLD", side="sell", volume=0.0176,
        open_time=open_iso, open_price=4300.0, open_mid=4300.3,
        open_spread=0.6, close_time=close_iso, net_pnl=1.0, gross_pnl=2.0,
        total_cost=1.0, broker_ticket=ticket, close_reason="stop_loss",
    )


def test_version_constant_matches_the_manifest():
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == INTEGRATION_VERSION


def test_semantics_version_is_in_the_fingerprint():
    """Een gedragswijziging start een nieuwe run - ook als de strategie gelijk
    blijft. Daarom zit de uitvoeringsversie in de vingerafdruk."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    materiaal = bron.split("def _fingerprint_material")[1].split("\n    @staticmethod")[0]
    assert '"execution_semantics": EXECUTION_SEMANTICS_VERSION' in materiaal
    assert '"candle_source"' in materiaal


def test_a_new_run_records_its_provenance():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    config = bron.split("def _run_config")[1].split("\n    def ")[0]
    for veld in ("integration_version", "execution_semantics", "strategy",
                 "venue", "environment", "mode", "timeframe", "candle_source",
                 "instrument_currency", "account_currency", "risk"):
        assert f'"{veld}"' in config, veld


def test_each_trade_carries_its_semantics_version():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "execution_semantics=EXECUTION_SEMANTICS_VERSION" in bron


def test_a_stop_is_only_trusted_from_version_2():
    """Tot versie 2 werd een verplaatste stop niet teruggeschreven."""
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    blok = bron.split("def _stop_trusted")[1].split("\n    def ")[0]
    assert ">= 2" in blok


def test_overlapping_trades_mark_a_run_as_mixed(tmp_path):
    """Met een limiet van één positie kunnen trades elkaar niet overlappen. Het
    kenmerk van de fout die 5.3.2 oploste."""
    db = TradeDatabase(tmp_path / "m.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    # vóór de fix: twee tegelijk open
    db.insert_trade(_trade(run, "2026-09-23T08:30:00+00:00", "2026-09-23T09:48:00+00:00", "A"))
    db.insert_trade(_trade(run, "2026-09-23T09:40:00+00:00", "2026-09-23T09:55:00+00:00", "B"))
    # na de fix: netjes na elkaar
    db.insert_trade(_trade(run, "2026-09-23T14:00:00+00:00", "2026-09-23T14:20:00+00:00", "C"))
    db.insert_trade(_trade(run, "2026-09-23T15:00:00+00:00", "2026-09-23T15:20:00+00:00", "D"))
    db.close()

    db = TradeDatabase(tmp_path / "m.db")
    db.connect()
    aantekeningen = db.run_annotations(run)
    assert len(aantekeningen) == 1
    assert aantekeningen[0]["kind"] == "methodologisch_gemengd"
    assert aantekeningen[0]["boundary"] == "2026-09-23T09:55:00+00:00"


def test_marking_is_idempotent_and_adds_only(tmp_path):
    db = TradeDatabase(tmp_path / "i.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    db.insert_trade(_trade(run, "2026-09-23T08:30:00+00:00", "2026-09-23T09:48:00+00:00", "A"))
    db.insert_trade(_trade(run, "2026-09-23T09:40:00+00:00", "2026-09-23T09:55:00+00:00", "B"))
    for _ in range(3):
        db.detect_mixed_runs()
    assert len(db.run_annotations(run)) == 1
    assert len(db.closed_trades(run)) == 2, "de run zelf is aangeraakt"


def test_a_clean_run_is_not_marked(tmp_path):
    db = TradeDatabase(tmp_path / "s.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    db.insert_trade(_trade(run, "2026-09-23T08:30:00+00:00", "2026-09-23T08:50:00+00:00", "A"))
    db.insert_trade(_trade(run, "2026-09-23T09:00:00+00:00", "2026-09-23T09:20:00+00:00", "B"))
    db.detect_mixed_runs()
    assert db.run_annotations(run) == []


def test_partial_closes_are_not_overlaps(tmp_path):
    """Een deelsluiting deelt het interval van zijn moedertrade."""
    db = TradeDatabase(tmp_path / "p.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    db.insert_trade(_trade(run, "2026-09-23T08:30:00+00:00", "2026-09-23T09:00:00+00:00", "A"))
    db.insert_trade(_trade(run, "2026-09-23T08:30:00+00:00", "2026-09-23T08:45:00+00:00", "A-deel"))
    db.detect_mixed_runs()
    assert db.run_annotations(run) == []


def test_annotations_are_shown_in_the_report(tmp_path):
    from gold_scalper.dashboard.report import build_report

    db = TradeDatabase(tmp_path / "rp.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    db.annotate_run(run, "methodologisch_gemengd", "twee gedragingen", "2026-09-23")
    html = build_report(db, run)
    assert "Aantekeningen bij deze run" in html and "twee gedragingen" in html
