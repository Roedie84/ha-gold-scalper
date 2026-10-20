"""2.18.1 - de Bitvavo-mand in één dashboard.

Gemeld 20-10: "Ik wil 1 dashboard, niet legio aan tabladen, ik wil in 1
oogopslag alle openstaande orders voor alle markten zien." In 2.18.0 stond
elke markt als eigen knop in de brokerkeuze. Nu: één knop *Bitvavo-mand*,
bovenaan het paneel alle open posities van alle markten in één tabel en per
markt een kaart.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.dashboard.broker import mand_payload  # noqa: E402
from test_v191 import _playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "gold_scalper"
JS = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")


def _positie(ticket, prijs, units):
    return SimpleNamespace(ticket=ticket, side="buy", units=units, open_price=prijs,
                           stop_loss=prijs * 0.99, take_profit=prijs * 1.02,
                           open_time=datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc),
                           unrealised_pnl=None, current_price=None)


def test_alle_open_posities_van_alle_markten_in_een_lijst():
    btc = {"price": 91000.0, "quote": SimpleNamespace(bid=91000.0, ask=91010.0),
           "open_positions": [_positie("B1", 90000.0, 0.0027)], "stats": {"net_pnl": 3.0, "trades": 4}}
    pepe = {"price": 0.0000120, "quote": SimpleNamespace(bid=0.0000120, ask=0.0000121),
            "open_positions": [_positie("P1", 0.0000116, 21_500_000)], "stats": {"net_pnl": -1.0}}
    leeg = {"price": 3000.0, "quote": SimpleNamespace(bid=3000.0, ask=3000.5),
            "open_positions": [], "stats": {}}
    overzicht = {"max_posities": 5, "per_markt": [
        {"markt": "ETH-EUR", "weigering": "mand: al 5 van hooguit 5 posities open", "spread_pct": 0.017}]}
    uit = mand_payload([
        {"markt": "BTC-EUR", "data": btc, "status": ("positie_open", "Positie open")},
        {"markt": "PEPE-EUR", "data": pepe, "status": ("positie_open", "")},
        {"markt": "ETH-EUR", "data": leeg, "status": ("wachtend", "Wacht op een signaal")},
        {"markt": "SOL-EUR", "data": None, "status": None},
    ], overzicht)
    assert uit["open"] == 2 and uit["max_posities"] == 5
    assert {p["markt"] for p in uit["posities"]} == {"BTC-EUR", "PEPE-EUR"}
    btc_rij = next(p for p in uit["posities"] if p["markt"] == "BTC-EUR")
    assert btc_rij["units"] == 0.0027                       # niet afgerond op 0,00
    assert btc_rij["pnl"] == round((91000.0 - 90000.0) * 0.0027, 2)
    assert uit["pnl_open"] == round(2.7 + (0.0000120 - 0.0000116) * 21_500_000, 2)
    assert uit["netto"] == 2.0
    eth = next(m for m in uit["markten"] if m["markt"] == "ETH-EUR")
    assert eth["open"] == 0 and eth["weigering"].startswith("mand:")
    sol = next(m for m in uit["markten"] if m["markt"] == "SOL-EUR")
    assert sol["status"] == "opstarten" and sol["koers"] is None


def test_de_brokerkeuze_toont_de_mand_als_een_knop(monkeypatch):
    from gold_scalper import http as h

    mand = SimpleNamespace()
    hoofd = SimpleNamespace(entry=SimpleNamespace(entry_id="E1", data={"venue": "bitvavo"}, options={},
                                                  title="Bitvavo-mand"),
                            venue=SimpleNamespace(name="bitvavo"), mode=SimpleNamespace(value="paper"),
                            data={"x": 1}, symbol="BTC-EUR", _mand=mand)
    lid = SimpleNamespace(entry=SimpleNamespace(entry_id="E1_eth-eur", hoofd_entry_id="E1",
                                                data={"venue": "bitvavo"}, options={}, title="ETH"),
                          venue=SimpleNamespace(name="bitvavo"), mode=SimpleNamespace(value="paper"),
                          data={"x": 1}, symbol="ETH-EUR", _mand=mand)
    ig = SimpleNamespace(entry=SimpleNamespace(entry_id="IG", data={"venue": "ig"}, options={}, title="IG"),
                         venue=SimpleNamespace(name="ig"), mode=SimpleNamespace(value="demo"),
                         data={"x": 1}, symbol="GOLD")
    hass = SimpleNamespace(data={"gold_scalper": {"E1": hoofd, "E1_eth-eur": lid, "IG": ig}})
    keuzes = h.broker_keuzes(hass)
    assert [k["naam"] for k in keuzes] == ["Bitvavo-mand", "IG"]


def test_het_paneel_heeft_een_mandvak_bovenaan():
    assert 'id="p-mand"' in JS and "_renderMand(d)" in JS
    assert '"mand mand mand mand mand mand mand mand mand mand mand mand"' in JS
    # Zonder mand verandert er niets aan de indeling.
    assert 'class="raster zonder-mand"' in JS
    assert "fmtA(p.units)" in JS


def test_playwright_de_mand_past_op_desktop_en_mobiel(tmp_path):
    import pytest

    pw = _playwright()
    if pw is None:
        pytest.skip("Playwright/Chromium niet beschikbaar")
    module, chrome = pw
    fx = ROOT / "tests" / "fixtures"
    shutil.copy(fx / "broker_panel_v2180.html", tmp_path / "broker_panel_v2180.html")
    shutil.copy(PKG / "frontend" / "broker-panel.js", tmp_path / "broker-panel.js")
    script = (fx / "broker_panel_v2180.mjs").read_text(encoding="utf-8").replace(
        "PLAYWRIGHT_MODULE", module)
    (tmp_path / "check.mjs").write_text(script, encoding="utf-8")
    res = subprocess.run(["node", str(tmp_path / "check.mjs"), str(tmp_path), str(tmp_path / "d.png")],
                         capture_output=True, text=True, timeout=120,
                         env={**os.environ, "PW_CHROMIUM": chrome})
    uit = res.stdout + res.stderr
    assert res.returncode == 0 and "\nOK" in "\n" + res.stdout, uit
    assert "desktop scroll 1496 1496" in uit and "buiten 0" in uit
