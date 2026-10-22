"""2.19.3: export_data geeft bij de Bitvavo-mand de trades van alle markten.

Gemeten 22-10: de mand had 311 gesloten trades (PUMP-EUR 184, PEPE-EUR 90,
BILL-EUR 37), maar export_data gaf total 0: alleen de database van de
hoofdlus (BTC-EUR) werd gelezen, de leden hebben elk een eigen database.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace as T

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.export import trades_tabel  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
VELDEN = ("id", "close_time", "net_pnl")


def test_een_bron_houdt_de_volgorde_en_krijgt_markt_als_laatste_kolom():
    trades = [T(id=2, close_time="2026-10-22T02:00:00+00:00", net_pnl=1.0),
              T(id=1, close_time="2026-10-22T01:00:00+00:00", net_pnl=-1.0)]
    uit = trades_tabel([("XAUUSD", trades)], VELDEN, 0, 10)
    assert uit["total"] == 2
    assert uit["columns"] == ["id", "close_time", "net_pnl", "markt"]
    assert [r[0] for r in uit["rows"]] == [2, 1]
    assert uit["rows"][0][-1] == "XAUUSD"


def test_mand_neemt_alle_leden_mee_op_sluitmoment():
    hoofd = ("BTC-EUR", [])
    pump = ("PUMP-EUR", [T(id=1, close_time="2026-10-21T10:00:00+00:00", net_pnl=-5),
                         T(id=2, close_time="2026-10-21T12:00:00+00:00", net_pnl=3)])
    pepe = ("PEPE-EUR", [T(id=1, close_time="2026-10-21T11:00:00+00:00", net_pnl=-2)])
    uit = trades_tabel([hoofd, pump, pepe], VELDEN, 0, 10)
    assert uit["total"] == 3
    assert [(r[-1], r[0]) for r in uit["rows"]] == [("PUMP-EUR", 1), ("PEPE-EUR", 1), ("PUMP-EUR", 2)]
    # pagina's
    assert [r[-1] for r in trades_tabel([hoofd, pump, pepe], VELDEN, 1, 1)["rows"]] == ["PEPE-EUR"]


def test_filter_op_markt():
    pump = ("PUMP-EUR", [T(id=1, close_time="2026-10-21T10:00:00+00:00", net_pnl=-5)])
    pepe = ("PEPE-EUR", [T(id=7, close_time="2026-10-21T11:00:00+00:00", net_pnl=-2)])
    uit = trades_tabel([pump, pepe], VELDEN, 0, 10, markt="pepe-eur")
    assert uit["total"] == 1 and uit["rows"][0][0] == 7 and uit["markten"] == ["PEPE-EUR"]


def test_dienst_leest_de_leden_van_de_mand():
    init = (PKG / "__init__.py").read_text(encoding="utf-8")
    blok = init.split("async def export_data")[1].split("hass.services.async_register")[0]
    assert "mand.leden.values()" in blok and "trades_tabel(" in blok
    assert 'vol.Optional("markt"): str' in init
    assert "    markt:" in (PKG / "services.yaml").read_text(encoding="utf-8")
