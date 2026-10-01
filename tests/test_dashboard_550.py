"""Meetkwaliteit zichtbaar: sensoren, overzichtspagina en een dashboard met de
werkelijke entiteit-id's.

Wat 5.4 meet stond alleen in de diagnostiek. Een geblokkeerde wisselkoers -
geen nieuwe posities - bleef daardoor twee versies lang onzichtbaar. En het
meegeleverde dashboard verwees naar id's die Home Assistant niet aanmaakt.
"""
import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.dashboard.lovelace import build_dashboard
from gold_scalper.dashboard.overview import _meetkwaliteit
from gold_scalper.meetkwaliteit import SPECS

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"

DATA = {
    "conversion": {
        "needed": True, "rate": 0.88122, "risk_rate": 0.8867,
        "rate_source": "ig_instrument", "rate_age_hours": 0.02,
        "direction": "EUR per USD", "usable_for_entry": True,
        "entry_reason": "koers 0.0 uur oud, binnen 24 uur",
        "risk_basis": "verlieskoers van de broker, hoger dan het midden",
    },
    "balances": {
        "effective_equity_floor": 5000.0, "applied": "configured_floor",
        "configured_floor": 5000.0, "run_floor": 3633.05,
        "opening_equity_account": 7266.1, "current_equity_account": 7300.0,
        "equity_floor_pct": 50.0, "account_currency": "EUR",
    },
    "exit_stats": {
        "noemer": 20, "afgestemd": 4, "take_profit": {"n": 3, "pct": 15.0},
        "stop_loss": {"n": 7, "pct": 35.0}, "eigen_exit": {"n": 6, "pct": 30.0},
        "unknown": {"n": 4, "pct": 20.0}, "toelichting": "ondergrenzen",
    },
    "reconciliation": {"in_orde": False, "samenvatting": "18 van 20 kloppen",
                       "afwijkingen": [{}, {}], "moment": "2026-09-29T06:10:00"},
    "candle_setting": {"configured": False, "override": True, "effective": True,
                       "origin": "options", "conflicting": True},
    "ledger_costs": {"trades": 20, "measured": 5, "calculated": 12,
                     "assumed": 0, "unknown": 3, "total": 24.1},
}


def _spec(sleutel):
    return next(s for s in SPECS if s["key"] == sleutel)


def _waarde(sleutel):
    s = _spec(sleutel)
    return s["value_fn"](DATA), (s["attrs_fn"](DATA) if s.get("attrs_fn") else {})


def test_nine_new_sensors_with_unique_keys():
    """Uniek, ook naast de bestaande sensoren."""
    bron = (PKG / "sensor.py").read_text(encoding="utf-8")
    bestaand = set(__import__("re").findall(r'key="([^"]+)"', bron))
    nieuw = [s["key"] for s in SPECS]
    assert len(nieuw) == 9 and len(set(nieuw)) == 9
    assert not bestaand & set(nieuw)
    assert "SENSORS + MEETKWALITEIT" in bron


@pytest.mark.parametrize("sleutel,verwacht", [
    ("fx_rate", 0.88122), ("fx_entry", "toegestaan"), ("equity_floor", 5000.0),
    ("exits_target", 15.0), ("exits_stop", 35.0), ("exits_unknown", 20.0),
    ("reconciliation", "afwijkingen"), ("candle_source", "quotes"),
    ("costs_measured", 25.0),
])
def test_sensor_values(sleutel, verwacht):
    assert _waarde(sleutel)[0] == verwacht


def test_a_blocked_rate_is_visible_with_its_reason():
    blok = {"conversion": {"needed": True, "usable_for_entry": False,
                           "entry_reason": "leeftijd van de koers onbekend"}}
    s = _spec("fx_entry")
    assert s["value_fn"](blok) == "geblokkeerd"
    assert s["attrs_fn"](blok)["reden"] == "leeftijd van de koers onbekend"


def test_the_floor_shows_the_room_left():
    assert _waarde("equity_floor")[1]["ruimte_tot_vloer"] == 2300.0


def test_the_target_rate_says_it_is_a_lower_bound():
    attrs = _waarde("exits_target")[1]
    assert attrs["ondergrens"] is True and attrs["van"] == 20


def test_empty_data_gives_no_crash():
    for s in SPECS:
        s["value_fn"]({})
        if s.get("attrs_fn"):
            try:
                s["attrs_fn"]({})
            except (KeyError, TypeError):
                pass   # de entiteit vangt dit af; de waarde zelf moet werken


def test_the_overview_shows_measurement_quality():
    html = _meetkwaliteit(DATA)
    for tekst in ("Wisselkoers", "Nieuwe posities", "Vermogensvloer",
                  "Hoe trades eindigden", "2 afwijking(en)",
                  "de opties gelden", "5 van 20"):
        assert tekst in html, tekst


def test_the_overview_marks_a_blocked_rate():
    html = _meetkwaliteit({"conversion": {"needed": True, "usable_for_entry": False,
                                          "entry_reason": "geen koers"}})
    assert "geblokkeerd" in html and "geen koers" in html


def test_the_dashboard_uses_real_ids_and_skips_missing():
    ids = {
        "price": "sensor.gold_scalper_cs_d_cfegold_cea_ip_koers",
        "fx_entry": "sensor.gold_scalper_cs_d_cfegold_cea_ip_instap_op_wisselkoers",
        "trading_enabled": "switch.gold_scalper_cs_d_cfegold_cea_ip_handel_actief",
        "resume": "button.gold_scalper_cs_d_cfegold_cea_ip_hervatten",
    }
    tekst = build_dashboard(ids, "CS.D.CFEGOLD.CEA.IP")
    dash = yaml.safe_load(tekst)
    gebruikt = {
        e["entity"] for k in dash["views"][0]["cards"]
        for e in k.get("entities", []) if isinstance(e, dict)
    }
    assert gebruikt == set(ids.values())
    assert "sensor.gold_scalper_price" not in tekst


def test_the_old_template_no_longer_guesses_ids():
    oud = (PKG / "dashboard" / "lovelace.yaml").read_text(encoding="utf-8")
    assert "entity:" not in oud and "write_dashboard" in oud


def test_the_new_values_are_in_the_cycle_data():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    for sleutel in ('"balances"', '"exit_stats"', '"reconciliation"',
                    '"candle_setting"', '"ledger_costs"'):
        assert sleutel + ":" in bron, sleutel
