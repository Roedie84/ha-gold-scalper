"""1.4.0: afstemming die slippage herkent, gemeten kosten, opstartmelding.

Live op 7 oktober, na de herstart van 10:49: de afstemming stond op
"afwijkingen" voor een trade met instap 4130,94 die op 4136,10 was geboekt en
bij IG op 4135,93 sloot. Dezelfde trade - instap, richting, omvang en
openingsmoment kloppen - dus geen verkeerde koppeling maar slippage. Verder
stond `kosten_gemeten` op nul en ging de opstartmelding verloren omdat
notify.mobile_app_* nog niet bestond.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.ig_capital import match_transaction  # noqa: E402
from gold_scalper.learning.afstemming import stem_af  # noqa: E402
from gold_scalper.learning.kosten import meet_kosten  # noqa: E402
from gold_scalper.notify import Notifier, NotifierConfig  # noqa: E402
from gold_scalper.storage.database import Trade  # noqa: E402

NU = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)
OPEN = NU - timedelta(hours=1)


def _trade(**over):
    basis = dict(
        run_id=1, mode="demo", symbol="GOLD", side="buy", volume=0.0153,
        open_time=OPEN.isoformat(), open_price=4130.94, open_mid=4130.64,
        open_spread=0.6, close_time=(NU - timedelta(minutes=20)).isoformat(),
        close_price=4136.10, close_mid=4135.80, close_spread=0.6,
        net_pnl=7.89, close_reason="trailing_exit",
        original_close_reason="trailing_exit", broker_ticket="DIAAAAT1",
        cost_source="measured",
    )
    basis.update(over)
    t = Trade(**basis)
    t.id = 1
    return t


def _tx(open_level=4130.94, close_level=4135.93, pnl="E6.79", size="1.53",
        open_dt=OPEN, **extra):
    tx = {
        "openLevel": str(open_level), "closeLevel": str(close_level),
        "profitAndLoss": pnl, "size": size, "reference": "JZ3RYUBE",
        "instrumentName": "Spot Gold ($1) converted at 0.8731",
        "dateUtc": (NU - timedelta(minutes=19)).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if open_dt is not None:
        tx["openDateUtc"] = (open_dt + timedelta(seconds=2)).strftime(
            "%Y-%m-%dT%H:%M:%S")
    tx.update(extra)
    return tx


# --- koppelen op openingsmoment ---------------------------------------------


def test_the_opening_moment_separates_equal_entries():
    """Twee trades op dezelfde instapprijs, uren na elkaar."""
    vroeg = _tx(close_level=4120.00, open_dt=OPEN - timedelta(hours=3))
    juist = _tx(close_level=4135.93)
    m = match_transaction([vroeg, juist], "DIAAAAT1", 4130.94, "buy", 1.53,
                          OPEN.isoformat())
    assert m["exit_price"] == pytest.approx(4135.93)
    assert m["matched_on"] == "instapprijs+opentijd"
    assert m["reference"] == "JZ3RYUBE"


def test_without_an_opening_moment_the_old_rule_applies():
    m = match_transaction([_tx(open_dt=None)], "T", 4130.94, "buy", 1.53,
                          OPEN.isoformat())
    assert m["matched_on"] == "instapprijs"


# --- slippage is geen afwijking ---------------------------------------------


def test_a_strong_match_adopts_the_broker_exit_as_slippage():
    trade = _trade()
    uitslag = stem_af([trade], [_tx()], 0.8731, NU)

    assert uitslag.in_orde, uitslag.afwijkingen
    assert uitslag.slippage_overgenomen == 1
    velden = uitslag.overnames[0]["velden"]
    assert velden["close_price"] == pytest.approx(4135.93)
    herkomst = json.loads(velden["exit_price_provenance"])
    assert herkomst["status"] == "ADOPTED_BROKER_SETTLEMENT_SLIPPAGE"
    assert herkomst["original_local"] == pytest.approx(4136.10)


def test_a_weak_match_with_a_large_difference_stays_an_afwijking():
    """Zonder openingsmoment is niet zeker dat het dezelfde trade is."""
    uitslag = stem_af([_trade()], [_tx(open_dt=None)], 0.8731, NU)
    assert len(uitslag.afwijkingen) == 1
    assert "uitstap" in uitslag.afwijkingen[0].uitleg


def test_a_different_size_is_not_strong():
    uitslag = stem_af([_trade()], [_tx(size="1.40")], 0.8731, NU)
    assert not uitslag.in_orde


# --- gemeten kosten ---------------------------------------------------------


def test_costs_of_an_own_close_are_measured():
    t = _trade(cost_source="calculated")
    k = meet_kosten(t, 4135.93, 100.0)
    units = 1.53
    # instap 0,30 boven het midden, uitstap 0,13 onder het midden
    assert k["total_cost"] == pytest.approx((0.30 + (4135.80 - 4135.93)) * units)
    assert k["spread_cost"] == pytest.approx(0.6 * units)


def test_costs_of_a_stop_include_the_slippage_past_the_level():
    t = _trade(original_close_reason="stop_loss", close_reason="stop_loss",
               stop_loss=4125.00, cost_source="calculated", side="buy")
    k = meet_kosten(t, 4124.80, 100.0)
    units = 1.53
    assert k["uitstap_slippage"] == pytest.approx(0.20 * units)
    assert k["total_cost"] == pytest.approx((0.30 + 0.30 + 0.20) * units)


def test_a_broker_close_without_known_reason_is_not_measured():
    t = _trade(original_close_reason="broker_gesloten_geschat",
               close_reason="broker_gesloten_gecorrigeerd", cost_source="calculated")
    assert meet_kosten(t, 4135.93, 100.0) is None


def test_reconciliation_marks_costs_as_measured():
    t = _trade(cost_source="calculated", close_price=4135.93)
    uitslag = stem_af([t], [_tx()], 0.8731, NU)
    velden = uitslag.overnames[0]["velden"]
    assert velden["cost_source"] == "measured"
    assert uitslag.kosten_gemeten == 1
    assert velden["gross_pnl"] == pytest.approx(
        velden.get("net_pnl", t.net_pnl) + velden["total_cost"])


def test_already_measured_costs_are_left_alone():
    t = _trade(cost_source="measured", close_price=4135.93)
    uitslag = stem_af([t], [_tx()], 0.8731, NU)
    assert uitslag.kosten_gemeten == 0


# --- opstartmelding ---------------------------------------------------------


class _Hass:
    def __init__(self):
        self.calls = []
        self.services = self
        self.bestaat = False

    def has_service(self, domain, service):
        return self.bestaat

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append(data)


def test_a_message_waits_until_the_notify_service_exists(monkeypatch):
    hass = _Hass()
    n = Notifier(hass, NotifierConfig(service="mobile_app_iphone"))
    monkeypatch.setattr(n, "_plan_herhaling", lambda: None)

    asyncio.run(n.alert("start", "Gold Scalper gestart", "demo"))
    assert hass.calls == []

    hass.bestaat = True
    asyncio.run(n._probeer_wachtend())
    assert [c["title"] for c in hass.calls] == ["Gold Scalper gestart"]


def test_waiting_gives_up_after_ten_minutes(monkeypatch):
    from gold_scalper.notify import MAX_POGINGEN

    hass = _Hass()
    n = Notifier(hass, NotifierConfig(service="mobile_app_iphone"))
    monkeypatch.setattr(n, "_plan_herhaling", lambda: None)
    asyncio.run(n.alert("start", "T", "M"))
    for _ in range(MAX_POGINGEN):
        asyncio.run(n._probeer_wachtend())
    assert n._wachtend == []
