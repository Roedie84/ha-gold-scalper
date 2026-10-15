"""2.10.0: schaduwsimulatie zonder uitersten van vóór de instap; tijdvakken met de hand uit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from gold_scalper.strategy import uitgezet_schaduw as U
from gold_scalper.strategy import veldproef as V
from gold_scalper.strategy.schaduw import uitersten_voor

T0 = datetime(2026, 10, 15, 7, 0, 30, tzinfo=timezone.utc)


def _sig(richting=1, stop=4095.0, doel=4110.0, bar="b1"):
    return SimpleNamespace(geldig=True, direction=richting, stop_loss=stop, take_profit=doel,
                           score=0.5, components={"bar": bar})


def test_uitersten_van_voor_de_instap_tellen_niet():
    t = SimpleNamespace(open_time=T0.isoformat())
    # bar die begon vóór de instap: instap ná het begin -> niet meetellen
    assert uitersten_voor(t, 4120.0, 4090.0, T0 - timedelta(seconds=30)) == (None, None)
    # bar die begon ná de instap: wel
    assert uitersten_voor(t, 4120.0, 4090.0, T0 + timedelta(seconds=30)) == (4120.0, 4090.0)
    assert uitersten_voor(t, None, None, T0) == (None, None)


def test_doel_niet_geraakt_door_signaalbar():
    """Long rsi_rev: de signaalbar had een hoog boven het doel, maar vóór de instap."""
    b = U.UitgezetBoek()
    tr = b.openen(strategie="vp:rsi_rev:1m", signal=_sig(), bid=4100.0, ask=4100.2,
                  nu=T0, units=10)
    assert tr is not None
    exits = SimpleNamespace(evaluate=lambda **k: SimpleNamespace(kind="hold", new_stop=None))
    b.bijwerken(bid=4100.1, ask=4100.3, hoog=4111.0, laag=4099.0, nu=T0 + timedelta(seconds=10),
                exits_voor=lambda n: exits, maat_voor=lambda t: 2.0,
                uitersten_vanaf=T0.replace(second=0))      # bar van vóór de instap
    assert tr.status == "open"                              # vroeger: take_profit
    b.bijwerken(bid=4100.1, ask=4100.3, hoog=4111.0, laag=4099.0, nu=T0 + timedelta(seconds=60),
                exits_voor=lambda n: exits, maat_voor=lambda t: 2.0,
                uitersten_vanaf=T0 + timedelta(seconds=30))  # nieuwe bar na de instap
    assert tr.status == "gesloten" and tr.close_reason == "take_profit"


def test_geldig_vanaf_en_hypothese():
    from gold_scalper.learning import onderzoek as O
    h = {x.hypothesis_id: x for x in O.HYPOTHESEN}["H-GS-003"]
    assert h.confirmation_vanaf == U.GELDIG_VANAF


def test_tijdvak_met_de_hand_uit():
    uit = V.handmatig_uitgezet({"vp:momentum:1m": [-1.0, -2.0, 0.5]}, ("1m",))
    assert set(uit) == {n for n in V.namen() if n.endswith(":1m")}
    assert uit["vp:momentum:1m"]["handmatig"] and uit["vp:momentum:1m"]["n"] == 3
    assert uit["vp:rsi_rev:1m"]["t"] is None
    assert V.handmatig_uitgezet({}, ()) == {}
    # evalueer weigert een uitgezette opzet (en markeert hem voor de schaduw)
    from pathlib import Path
    co = (Path(__file__).resolve().parents[1] / "custom_components" / "gold_scalper"
          / "coordinator.py").read_text(encoding="utf-8")
    assert "handmatig_uitgezet(" in co and "uitersten_vanaf=vanaf" in co
