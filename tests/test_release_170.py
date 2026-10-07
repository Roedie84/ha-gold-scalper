"""1.7.0: laatste gegevens vasthouden bij een losse mislukte koersopvraging,
en statistiek per cluster.

Live op 7 oktober: de koersopvraging bij IG liep zes keer in anderhalf uur
tegen de time-out van 6 s aan. Elke keer werden álle entiteiten kort
onbeschikbaar, ook de noodstop.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from gold_scalper.broker.adapter import VenueError, VenueQuote  # noqa: E402
from gold_scalper.const import (  # noqa: E402
    KOERS_HOUD_MAX_MISLUKT, KOERS_HOUD_MAX_SECONDEN,
)
from gold_scalper.storage.database import Trade  # noqa: E402
from gold_scalper.storage.performance import (  # noqa: E402
    CLUSTER_LIJST_MAX, cluster_details, cluster_resultaten,
    cluster_samenvatting, compute,
)


# ---------------- koers vasthouden ---------------- #

def _opzet(tmp_path, monkeypatch):
    """Coordinator die bij elk signaal zou willen instappen."""
    from test_broker_cycle import ScriptedVenue, _coordinator
    from test_unconfirmed_orders import _Signaal

    import gold_scalper.coordinator as co

    class Haperend(ScriptedVenue):
        faalt: bool = False

        async def quote(self, symbol=None):
            if self.faalt:
                raise VenueError("Time-out na 6 s bij GET /markets/CS.D.CFDGOLD")
            half = self.spread / 2
            return VenueQuote(bid=self.price - half, ask=self.price + half,
                              time=datetime.now(timezone.utc), tradeable=True)

    aanroepen = []

    def altijd(*args):
        aanroepen.append(args)
        return _Signaal()

    monkeypatch.setattr(co, "evaluate", altijd)
    venue = Haperend()
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator.executor.venue = venue
    coordinator._enabled = True
    return coordinator, venue, aanroepen


def test_een_mislukte_opvraging_houdt_het_laatste_beeld(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    vers = asyncio.run(coordinator._async_update_data())
    assert vers["koers_verouderd"] is False
    assert vers["koers_mislukt_op_rij"] == 0

    venue.faalt = True
    data = asyncio.run(coordinator._async_update_data())

    assert data["koers_verouderd"] is True
    assert data["koers_mislukt_op_rij"] == 1
    assert data["koers_leeftijd_seconden"] is not None
    assert "Time-out" in data["koers_fout"]
    assert data["price"] == vers["price"]
    assert data["signal"] is None
    assert data["reject_reason"].startswith("koers verouderd")
    # Noodstop en levenscyclus blijven in het beeld.
    assert data["risk"]["state"] == coordinator.risk.as_dict()["state"]
    assert "safe_to_restart" in data["lifecycle"]


def test_op_een_verouderde_koers_wordt_niet_gehandeld(tmp_path, monkeypatch):
    coordinator, venue, aanroepen = _opzet(tmp_path, monkeypatch)
    asyncio.run(coordinator._async_update_data())
    orders = len(venue.orders)
    evaluaties = len(aanroepen)

    venue.faalt = True
    for _ in range(KOERS_HOUD_MAX_MISLUKT):
        asyncio.run(coordinator._async_update_data())

    assert len(venue.orders) == orders, "instap op een verouderde koers"
    assert len(aanroepen) == evaluaties, "strategie draaide op een oude koers"
    assert coordinator.koers_verouderd is True


def test_tweede_grendel_in_open_position(tmp_path, monkeypatch):
    from test_unconfirmed_orders import _Signaal

    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    coordinator._koers_mislukt = 1
    quote = VenueQuote(bid=4399.7, ask=4400.3, time=datetime.now(timezone.utc),
                       tradeable=True)
    asyncio.run(coordinator._open_position(_Signaal(), quote,
                                           datetime.now(timezone.utc)))
    assert venue.orders == []


def test_na_de_drempel_de_oude_storing(tmp_path, monkeypatch):
    import gold_scalper.coordinator as co

    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    asyncio.run(coordinator._async_update_data())
    venue.faalt = True
    for _ in range(KOERS_HOUD_MAX_MISLUKT):
        asyncio.run(coordinator._async_update_data())
    with pytest.raises(co.UpdateFailed):
        asyncio.run(coordinator._async_update_data())


def test_te_oude_koers_escaleert_ook_bij_weinig_pogingen(tmp_path, monkeypatch):
    import gold_scalper.coordinator as co

    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    asyncio.run(coordinator._async_update_data())
    coordinator._laatste_verse_koers_om -= timedelta(
        seconds=KOERS_HOUD_MAX_SECONDEN + 1
    )
    venue.faalt = True
    with pytest.raises(co.UpdateFailed):
        asyncio.run(coordinator._async_update_data())


def test_zonder_eerdere_gegevens_meteen_de_oude_storing(tmp_path, monkeypatch):
    import gold_scalper.coordinator as co

    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    venue.faalt = True
    with pytest.raises(co.UpdateFailed):
        asyncio.run(coordinator._async_update_data())


def test_herstel_zet_de_teller_terug(tmp_path, monkeypatch):
    coordinator, venue, _ = _opzet(tmp_path, monkeypatch)
    asyncio.run(coordinator._async_update_data())
    venue.faalt = True
    asyncio.run(coordinator._async_update_data())
    asyncio.run(coordinator._async_update_data())
    venue.faalt = False
    data = asyncio.run(coordinator._async_update_data())
    assert data["koers_verouderd"] is False
    assert coordinator.koers_verouderd is False
    # En daarna mag er weer drie keer worden vastgehouden.
    venue.faalt = True
    for _ in range(KOERS_HOUD_MAX_MISLUKT):
        assert asyncio.run(coordinator._async_update_data())["koers_verouderd"]


def test_dataprobleem_gaat_aan_bij_verouderde_koers():
    from gold_scalper.binary_sensor import DataIntegrity

    nep = SimpleNamespace(coordinator=SimpleNamespace(
        data={"koers_verouderd": True, "candles": 500, "candles_consistent": True},
        state=SimpleNamespace(bars=500),
    ))
    assert DataIntegrity.is_on.fget(nep) is True
    nep.coordinator.data["koers_verouderd"] = False
    assert DataIntegrity.is_on.fget(nep) is False


def test_noodstop_blijft_beschikbaar_en_leest_de_risicobewaking():
    from gold_scalper.binary_sensor import RiskHalted

    risk = SimpleNamespace(as_dict=lambda: {"state": "halted", "halt_reason": "x"})
    nep = SimpleNamespace(coordinator=SimpleNamespace(data=None, risk=risk))
    nep._risk = lambda: RiskHalted._risk(nep)
    assert RiskHalted.available.fget(nep) is True
    assert RiskHalted.is_on.fget(nep) is True


def test_afstemming_blijft_beschikbaar():
    # sensor.py zelf laadt niet zonder echte HA; de regel staat in SPECS.
    from gold_scalper.meetkwaliteit import SPECS

    spec = next(s for s in SPECS if s["key"] == "reconciliation")
    assert spec["blijft_beschikbaar"] is True


def test_status_meldt_verouderde_koers_maar_noodstop_gaat_voor():
    from gold_scalper.status import build_status

    d = {"koers_verouderd": True, "koers_mislukt_op_rij": 2,
         "koers_leeftijd_seconden": 41.0, "enabled": True}
    assert build_status(d)[0] == "koers_verouderd"
    d["risk"] = {"state": "halted", "halt_reason": "dagverlies"}
    assert build_status(d)[0] == "noodstop"


# ---------------- per cluster ---------------- #

T0 = datetime(2026, 10, 7, 13, 55, tzinfo=timezone.utc)


def _trade(i, open_dt, minuten, pnl, bruto=None, eur=None):
    t = Trade(
        run_id=1, mode="demo", symbol="GOLD", side="sell", volume=0.01,
        open_time=open_dt.isoformat(), open_price=4123.0, open_mid=4122.7,
        open_spread=0.6,
        close_time=(open_dt + timedelta(minutes=minuten)).isoformat(),
        close_price=4124.0, net_pnl=pnl,
        gross_pnl=pnl + 0.5 if bruto is None else bruto, total_cost=0.5,
    )
    if eur is not None:
        t.net_pnl_account = eur
        t.account_currency = "EUR"
    t.id = i
    return t


def test_cluster_details_per_cluster():
    a = _trade(1, T0, 1, -8.55, eur=-7.9)
    b = _trade(2, T0 + timedelta(minutes=1, seconds=10), 1, -11.86, eur=-11.0)
    c = _trade(3, T0 + timedelta(hours=2), 3, 5.0)
    d = cluster_details([c, b, a])

    assert len(d) == 2
    eerste, tweede = d
    assert eerste["nr"] == 1 and eerste["trades"] == 2
    assert eerste["start"] == T0.isoformat()
    assert eerste["eind"] == (T0 + timedelta(minutes=2, seconds=10)).isoformat()
    assert eerste["duur_min"] == pytest.approx(2.2, abs=0.05)
    assert eerste["netto_usd"] == pytest.approx(-20.41)
    assert eerste["bruto_usd"] == pytest.approx(-19.41)
    assert eerste["netto_eur"] == pytest.approx(-18.9)
    assert tweede["trades"] == 1 and tweede["duur_min"] == 3.0
    assert tweede["netto_eur"] is None, "geen euro-afrekening bekend"
    # Zelfde indeling als de t-statistiek.
    assert [x["netto_usd"] for x in d] == pytest.approx(cluster_resultaten([a, b, c]))


def test_samenvatting_grootste_cluster():
    trades = [
        _trade(1, T0, 1, 30.0),
        _trade(2, T0 + timedelta(minutes=2), 1, 20.0),
        _trade(3, T0 + timedelta(minutes=4), 1, 10.0),
        _trade(4, T0 + timedelta(hours=3), 1, -5.0),
        _trade(5, T0 + timedelta(hours=5), 1, -5.0),
    ]
    s = cluster_samenvatting(cluster_details(trades))
    assert s["grootste_cluster_aandeel_trades_procent"] == 60.0
    assert s["grootste_cluster_trades_nr"] == 1
    assert s["grootste_cluster_aandeel_netto_procent"] == pytest.approx(85.7, abs=0.1)
    assert s["grootste_cluster_netto_usd"] == 60.0
    assert s["netto_zonder_grootste_cluster_usd"] == -10.0


def test_compute_lijst_is_begrensd_en_klein():
    import json

    trades = [_trade(i, T0 + timedelta(hours=i), 1, 1.0 + i % 3) for i in range(80)]
    s = compute(trades)
    assert s["clusters"] == 80
    assert len(s["per_cluster"]) == CLUSTER_LIJST_MAX
    assert s["per_cluster"][-1]["nr"] == 80, "de laatste clusters, niet de eerste"
    assert len(json.dumps(s["per_cluster"])) < 10_000, "ruim onder 16 KB"
    assert "grootste_cluster_aandeel_netto_procent" in s["cluster_samenvatting"]


def test_t_statistiek_onveranderd_door_details():
    trades = []
    for i in range(6):
        start = T0 + timedelta(hours=i)
        trades.append(_trade(2 * i, start, 1, -2.0 - i))
        trades.append(_trade(2 * i + 1, start + timedelta(minutes=2), 1, -1.0))
    s = compute(trades)
    assert s["clusters"] == 6
    assert len(s["per_cluster"]) == 6
    assert all(c["trades"] == 2 for c in s["per_cluster"])
