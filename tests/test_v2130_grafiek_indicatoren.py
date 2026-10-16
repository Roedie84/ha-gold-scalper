"""2.13.0: signalen per setup en indicatoren in de grafiek."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.dashboard.broker import signaal_markers  # noqa: E402

PANEEL = Path(__file__).parent.parent / "custom_components" / "gold_scalper" / "frontend" / "broker-panel.js"


def _rij(ts, state, acted, reden=None, strategie="vp:donchian:15m", bar=1):
    return {"ts": ts, "state": state, "acted": acted, "reject_reason": reden,
            "detail_json": json.dumps({"strategie": strategie, "bar": bar})}


def test_een_marker_per_setup_per_bar():
    rijen = [
        _rij("2026-10-16T08:00:20+00:00", "buy", 0, "max posities"),
        _rij("2026-10-16T08:00:40+00:00", "buy", 1),
        _rij("2026-10-16T08:01:00+00:00", "buy", 0, "al in deze bar"),
    ]
    m = signaal_markers(rijen)
    assert len(m) == 1
    assert m[0]["gehandeld"] is True and m[0]["reden"] is None
    assert m[0]["richting"] == "long" and m[0]["strategie"] == "vp:donchian:15m"


def test_overgeslagen_met_reden_en_volgorde():
    rijen = [
        _rij("2026-10-16T09:00:00+00:00", "sell", 0, "kostenfilter: stop 3.00, minimaal 6.88", bar=2),
        _rij("2026-10-16T08:00:00+00:00", "buy", 1, strategie="vp:rsi_rev:15m", bar=1),
        _rij("2026-10-16T08:30:00+00:00", "flat", 0, bar=3),
        {"ts": "2026-10-16T08:40:00+00:00", "state": "buy", "acted": 1, "reject_reason": None, "detail_json": None},
    ]
    m = signaal_markers(rijen)
    assert [x["strategie"] for x in m] == ["vp:rsi_rev:15m", "vp:donchian:15m"]
    assert m[1]["reden"].startswith("kostenfilter")


def test_paneel_heeft_indicatoren():
    js = PANEEL.read_text(encoding="utf-8")
    for naam in ("indEma", "indBb", "indDc", "indRsi", "indAtr", "_renderInd", "d.signalen", IND := "gold-scalper-indicatoren"):
        assert naam in js, naam
