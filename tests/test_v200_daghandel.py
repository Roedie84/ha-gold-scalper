"""2.0.0 (L-GS-014): van scalpen naar daghandel.

Besluit Ruud 12-10-2026. Regels gelijk aan de backtest over 2011-2018 en
IG 2026 (zie strategy/daghandel.py): uitbraak uit het kanaal van 20 uur in
de richting van de uur-EMA20/50, stop 4 x ATR(15m), volgstop 6 x ATR vanaf
2 x ATR winst, geen tijdstop, dicht om 20:45 UTC.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.analysis.signals import Candles  # noqa: E402
from gold_scalper.broker.exits import ExitConfig, ExitManager  # noqa: E402
from gold_scalper.const import (  # noqa: E402
    CONF_STRATEGIE, DEFAULT_STRATEGIE, INTEGRATION_VERSION, STRATEGIE_DAGHANDEL, STRATEGIEEN,
)
from gold_scalper.strategy import daghandel as D  # noqa: E402
from gold_scalper.strategy.scalping import ScalpConfig  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
START = int(datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc).timestamp())  # maandag



def _zonder_deel(cfg):
    """2.5.9: deze test gaat over de stop, niet over de deelwinst."""
    cfg.enable_partial_close = False
    return cfg

def _candles(n=400, stijging=0.05, slot_extra=0.0):
    ts, o, h, l, c = [], [], [], [], []
    prijs = 4000.0
    for i in range(n):
        golf = 3.0 * math.sin(i / 5.0)
        basis = prijs + i * stijging + golf
        ts.append(START + i * 900)
        o.append(basis)
        c.append(basis + (slot_extra if i == n - 1 else 0.2))
        h.append(max(o[-1], c[-1]) + 1.0)
        l.append(min(o[-1], c[-1]) - 1.0)
    return Candles(ts, o, h, l, c, [0.0] * n)


def _cfg():
    return ScalpConfig(max_spread=9.0)


def _eval(candles, uur=10, **kw):
    slot = candles.close[-1]
    return D.evaluate_daghandel(candles, slot - 0.4, slot + 0.4, _cfg(), uur, **kw)


# --- signaal ------------------------------------------------------------ #

def test_uitbraak_in_de_trend_geeft_long_met_stop_van_4_atr():
    s = _eval(_candles(slot_extra=30.0))
    assert s.should_trade and s.geldig and s.direction == 1
    atr = s.components["atr"]
    assert s.take_profit is None
    assert abs((_candles(slot_extra=30.0).close[-1] + 0.4) - s.stop_loss - 4 * atr) < 0.01
    assert s.components["strategie"] == "daghandel"


def test_geen_uitbraak_wacht():
    s = _eval(_candles(slot_extra=0.0))
    assert not s.should_trade and s.reject_reason == "geen_uitbraak"
    assert s.direction == 1  # uurtrend omhoog


def test_uitbraak_tegen_de_trend_telt_niet():
    s = _eval(_candles(slot_extra=-60.0))
    assert not s.should_trade and s.reject_reason == "geen_uitbraak"


def test_dalende_trend_geeft_short():
    s = _eval(_candles(stijging=-0.05, slot_extra=-30.0))
    assert s.should_trade and s.direction == -1
    c = _candles(stijging=-0.05, slot_extra=-30.0)
    assert abs(s.stop_loss - (c.close[-1] - 0.4) - 4 * s.components["atr"]) < 0.01


def test_alleen_tussen_7_en_17_utc():
    c = _candles(slot_extra=30.0)
    assert _eval(c, uur=6).reject_reason == "outside_hours"
    assert _eval(c, uur=17).reject_reason == "outside_hours"
    assert _eval(c, uur=16, minuut_utc=45).should_trade


def test_een_positie_tegelijk_en_wachten_na_instap():
    c = _candles(slot_extra=30.0)
    s = _eval(c, open_position_count=1)
    assert not s.should_trade and s.geldig
    s = _eval(c, seconds_since_last_entry=300)
    assert not s.should_trade and s.reject_reason == "cooldown"


def test_te_weinig_data():
    assert _eval(_candles(n=60)).reject_reason == "insufficient_data"


def test_uur_ema_kijkt_niet_in_het_lopende_uur():
    c = _candles(n=400)
    snel, _ = D.uur_emas(c)
    c2 = _candles(n=400, slot_extra=500.0)  # alleen de laatste bar anders
    assert D.uur_emas(c2)[0] == snel


# --- uitstap ------------------------------------------------------------ #

T = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)


def _uit(nu, open_=T, bid=4000.0, stop=3980.0, atr=5.0):
    m = ExitManager(_zonder_deel(D.exit_config()))
    return m.evaluate("buy", 1.0, 4000.0, stop, bid, bid + 0.5, atr, open_, nu, 0.9)


def test_geen_tijdstop_wel_break_even_vanaf_1_atr():
    assert _uit(T + timedelta(minutes=30)).kind == "hold"
    assert _uit(T + timedelta(hours=3), bid=4001.2).kind == "hold"  # 2.5.5: onder +1,5 USD
    # 2.5.1: break-even vanaf 1 x ATR15 (instap + 1,2 x kosten 0,9).
    a = _uit(T + timedelta(hours=3), bid=4008.0)
    assert a.kind == "modify_stop" and abs(a.new_stop - 4005.6) < 1e-6  # 2.5.7: winstslot 70% van +8


def test_volgstop_vanaf_2_atr_op_4_atr():
    """2.1.0: 4 x ATR (was 6)."""
    a = _uit(T + timedelta(hours=1), bid=4015.0)  # 3 x ATR winst
    assert a.kind == "modify_stop" and abs(a.new_stop - 4010.5) < 1e-6  # 2.5.7: winstslot strakker
    a = _uit(T + timedelta(hours=1), bid=4009.0)  # 1,8 x ATR: nog geen volgstop
    assert a.kind == "modify_stop" and abs(a.new_stop - 4006.3) < 1e-6  # 2.5.7: winstslot


def test_dicht_om_2045_utc_en_na_een_dagwissel():
    assert _uit(T.replace(hour=20, minute=44)).kind == "hold"
    a = _uit(T.replace(hour=20, minute=45))
    assert a.kind == "close" and "einde handelsdag" in a.reason
    a = _uit(T + timedelta(days=1, hours=-3), open_=T)  # 07:00 volgende dag
    assert a.kind == "close"


def test_scalpconfig_ongewijzigd():
    assert ExitConfig().sluit_om_uur_utc is None
    m = ExitManager(ExitConfig())
    assert m.evaluate("buy", 1.0, 4000.0, 3990.0, 4000.1, 4000.6, 5.0, T,
                      T.replace(hour=21), 0.9).kind == "close"  # max_hold 900s


# --- koppeling ------------------------------------------------------------ #

def test_standaard_daghandel_en_keuze():
    assert DEFAULT_STRATEGIE == STRATEGIE_DAGHANDEL
    assert {"daghandel", "scalp"} <= set(STRATEGIEEN)
    for taal in ("nl", "en"):
        d = json.loads((PKG / "translations" / f"{taal}.json").read_text(encoding="utf-8"))
        assert d["options"]["step"]["init"]["data"][CONF_STRATEGIE]
        assert set(d["selector"]["strategie"]["options"]) == set(STRATEGIEEN)


def test_coordinator_kiest_beslisser_uitstap_en_nieuwe_run():
    bron = (PKG / "coordinator.py").read_text(encoding="utf-8")
    assert "self._beslisser(now, strategie), self._candles" in bron
    assert "daghandel_mod.exit_config()\n            if self._strategie in (STRATEGIE_DAGHANDEL, STRATEGIE_COMBINATIE)" in bron
    assert '"strategy": self.strategie_versie,' in bron
    assert bron.count("self.db.start_run, self.mode.value, self.strategie_versie,") == 2
    assert "if self.db is None or not ref or strategie != STRATEGIE_SCALP:" in bron
    assert "(self.reeks.enabled or self.pyramid.enabled)" in bron
    assert D.STRATEGIE_VERSIE.startswith("daghandel-")


def test_versie():
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == INTEGRATION_VERSION
    assert tuple(map(int, INTEGRATION_VERSION.split("."))) >= (2, 0, 0)


# --- de lus met daghandel ------------------------------------------------- #

def test_volledige_cyclus_met_daghandel(tmp_path, monkeypatch):
    import asyncio

    sys.path.insert(0, os.path.dirname(__file__))
    from test_broker_cycle import ScriptedVenue, _coordinator

    coordinator, _ = _coordinator(ScriptedVenue(), tmp_path, monkeypatch)
    coordinator._strategie = STRATEGIE_DAGHANDEL
    coordinator.exits = ExitManager(D.exit_config())
    assert coordinator.daghandel and coordinator.strategie_versie == D.STRATEGIE_VERSIE
    data = asyncio.run(coordinator._async_update_data())
    assert isinstance(data, dict)
    sig = coordinator._last_signal
    if sig is not None:
        assert sig.components.get("strategie") == "daghandel" or sig.reject_reason == "insufficient_data"
