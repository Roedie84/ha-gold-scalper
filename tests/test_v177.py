"""1.7.7: bruto met teken in het oordeel en saldosprong zonder trade.

* De kostenzin in het oordeel toont bruto met teken. Bij −30,53 stond er
  "die is gevangen (31)"; nu "bruto −31", en de zin zegt dat de kosten
  bovenop een verlies komen.
* Een equitysprong van meer dan 10% zonder gesloten trade of open positie is
  een dataprobleem: de vorige referentie blijft gelden voor dagstart,
  run-opening en vloer. Eén WARNING per gebeurtenis; herstel door terugkeer
  binnen 10% of 24 uur stabiliteit (INFO).
"""
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper import const  # noqa: E402
from gold_scalper.broker.risk import RiskLimits, RiskManager  # noqa: E402
from gold_scalper.broker.saldosprong import SaldoSprongBewaker  # noqa: E402
from gold_scalper.storage import performance  # noqa: E402

T0 = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
LOGGER = "gold_scalper.broker.saldosprong"


# ---------------- 1. bruto met teken ---------------- #

def test_met_teken():
    assert performance.met_teken(-30.53) == "−31"
    assert performance.met_teken(20.4) == "+20"
    assert performance.met_teken(0.2) == "0"


def test_negatief_bruto_kosten_komen_bovenop_verlies():
    zin = performance.kosten_reden(165.45, -30.53)
    assert "bruto −31" in zin
    assert "(31)" not in zin
    assert "bovenop" in zin
    assert "165" in zin
    assert "overtreffen" not in zin


def test_positief_bruto_houdt_de_bestaande_strekking():
    zin = performance.kosten_reden(165.45, 120.0)
    assert zin.startswith("kosten (165) overtreffen de bruto marktbeweging")
    assert "bruto +120" in zin


def test_oordeel_gebruikt_de_tekenzin():
    stats = {
        "trades": 200, "net_pnl": -195.98, "cost_ratio": 5.4,
        "total_costs": 165.45, "gross_pnl": -30.53,
        "edge_surplus_per_oz": -0.1, "avg_excursion_per_oz": 0.1,
        "breakeven_edge_per_oz": 0.2, "losses": 120, "profit_factor": 0.5,
        "t_statistic": -2.0, "max_drawdown_pct": 2.0,
        "max_drawdown_pct_trade_sequence": 2.0,
    }
    tekst = str(performance.verdict(stats))
    assert "bruto −31" in tekst
    assert "gevangen (31)" not in tekst


# ---------------- 2. saldosprong zonder trade ---------------- #

def _bewaker(start=10_000.0):
    b = SaldoSprongBewaker()
    b.meet(T0, start, positie_open=False, sluitingen=0)
    return b


def test_eerste_meting_is_geen_sprong():
    b = SaldoSprongBewaker()
    b.meet(T0, 10_000_000.0, positie_open=False, sluitingen=0)
    assert not b.actief
    assert b.referentie == 10_000_000.0


def test_kleine_verandering_is_geen_sprong():
    b = _bewaker()
    b.meet(T0 + timedelta(minutes=1), 10_900.0, positie_open=False, sluitingen=0)
    assert not b.actief
    assert b.referentie == 10_900.0


def test_sprong_zonder_trade_is_dataprobleem_met_een_warning(caplog):
    b = _bewaker()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        for i in range(1, 6):
            b.meet(T0 + timedelta(minutes=i), 10_000_000.0,
                   positie_open=False, sluitingen=0)
    assert b.actief
    assert "saldosprong zonder trade" in b.reden
    assert b.betrouwbaar(10_000_000.0) == 10_000.0
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert b.as_dict()["actief"] is True


def test_sprong_door_gesloten_trade_is_verklaard():
    b = _bewaker()
    b.meet(T0 + timedelta(minutes=1), 7_000.0, positie_open=False, sluitingen=1)
    assert not b.actief
    assert b.referentie == 7_000.0


def test_sprong_met_open_positie_is_verklaard():
    b = _bewaker()
    b.meet(T0 + timedelta(minutes=1), 8_500.0, positie_open=True, sluitingen=0)
    assert not b.actief


def test_herstel_bij_terugkeer_binnen_drempel(caplog):
    b = _bewaker()
    b.meet(T0 + timedelta(minutes=1), 10_000_000.0, positie_open=False, sluitingen=0)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        b.meet(T0 + timedelta(minutes=2), 10_050.0, positie_open=False, sluitingen=0)
    assert not b.actief
    assert b.referentie == 10_050.0
    assert any(r.levelno == logging.INFO for r in caplog.records)


def test_na_24_uur_stabiel_nieuwe_referentie(caplog):
    b = _bewaker()
    b.meet(T0, 10_000_000.0, positie_open=False, sluitingen=0)
    b.meet(T0 + timedelta(hours=23), 10_000_100.0, positie_open=False, sluitingen=0)
    assert b.actief
    with caplog.at_level(logging.INFO, logger=LOGGER):
        b.meet(T0 + timedelta(hours=24), 10_000_003.0, positie_open=False,
               sluitingen=0)
    assert not b.actief
    assert b.referentie == 10_000_003.0
    assert any("nieuwe referentie" in r.getMessage() for r in caplog.records)


def test_opnieuw_springen_is_een_nieuwe_gebeurtenis(caplog):
    b = _bewaker()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        b.meet(T0 + timedelta(minutes=1), 10_000_000.0, positie_open=False, sluitingen=0)
        b.meet(T0 + timedelta(minutes=2), 50_000.0, positie_open=False, sluitingen=0)
    assert len(caplog.records) == 2
    assert b.referentie == 10_000.0


def test_mislukte_meting_telt_niet():
    b = _bewaker()
    b.meet(T0 + timedelta(minutes=1), None, positie_open=False, sluitingen=0)
    assert not b.actief and b.referentie == 10_000.0


def test_bewaren_en_terugzetten():
    b = _bewaker()
    b.meet(T0 + timedelta(minutes=1), 10_000_000.0, positie_open=False, sluitingen=0)
    nieuw = SaldoSprongBewaker()
    nieuw.herstel(b.export())
    assert nieuw.actief
    assert nieuw.referentie == 10_000.0
    assert nieuw.betrouwbaar(10_000_000.0) == 10_000.0
    leeg = SaldoSprongBewaker()
    leeg.herstel(None)
    assert leeg.referentie is None and not leeg.actief


def test_dagstart_rolt_naar_vorige_referentie_bij_actieve_sprong():
    rm = RiskManager(RiskLimits(), 10_000.0, now=T0)
    b = _bewaker()
    b.meet(T0 + timedelta(minutes=1), 10_000_000.0, positie_open=False, sluitingen=0)
    rm.saldosprong = b
    rm._roll_day(T0 + timedelta(days=1), 10_000_000.0)
    assert rm.state.day_start_balance == 10_000.0


def test_dagstart_normaal_zonder_sprong():
    rm = RiskManager(RiskLimits(), 10_000.0, now=T0)
    rm.saldosprong = _bewaker()
    rm._roll_day(T0 + timedelta(days=1), 10_200.0)
    assert rm.state.day_start_balance == 10_200.0


def test_record_close_telt_sluitingen():
    rm = RiskManager(RiskLimits(), 10_000.0, now=T0)
    rm.record_close(-5.0, T0)
    rm.record_close(3.0, T0)
    assert rm.sluitingen == 2

