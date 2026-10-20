"""2.18.5 - afwijkingen bij de broker één keer melden, niet elke vier uur.

Gemeld 20-10 17:42: "Ik blijf van goldscalper maar de afwijkende melding
krijgen". Dezelfde oude afwijkingen (een trade van bijna zes dagen geleden,
uitstapprijzen een paar tienden anders) stonden in elke afstemming en kwamen
per broker elke vier uur opnieuw binnen.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.notify import Notifier, NotifierConfig  # noqa: E402

BRON = (Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
        / "coordinator.py").read_text(encoding="utf-8")


def _n():
    return Notifier(None, NotifierConfig(service="mobile_app_test"))


def test_dezelfde_afwijking_maar_een_keer():
    n = _n()
    assert n.nieuw("afstemming:", ["A:verschilt", "B:ontbreekt"]) == ["A:verschilt", "B:ontbreekt"]
    assert n.nieuw("afstemming:", ["A:verschilt", "B:ontbreekt"]) == []
    assert n.nieuw("afstemming:", ["A:verschilt", "C:verschilt"]) == ["C:verschilt"]


def test_gemeld_blijft_bewaard_over_een_herstart():
    n = _n()
    n.nieuw("afstemming:", ["A:verschilt"])
    m = _n()
    m.restore(n.export())
    assert m.nieuw("afstemming:", ["A:verschilt"]) == []


def test_oude_sleutels_vervallen():
    n = _n()
    n._sent.keys["afstemming:A:verschilt"] = datetime.now(timezone.utc) - timedelta(days=30)
    n._sent.keys["ander"] = datetime.now(timezone.utc) - timedelta(days=30)
    assert n.nieuw("afstemming:", ["A:verschilt"]) == ["A:verschilt"]
    assert "ander" in n._sent.keys


def test_coordinator_meldt_alleen_nieuwe_en_niet_bij_de_overgang():
    assert 'self.notifier.alert(\n                "afstemming"' not in BRON
    assert '"afstemming:", [f"{a.ticket}:{a.soort}"' in BRON
    assert "nieuwe = [] if overgang else" in BRON
