"""2.25.0 - twee punten, elk door Ruud goedgekeurd (27-10 20:16).

Punt 4 - vermogensvloer van de Bitvavo-mand op papier. Live telt
``bitvavo.account()`` de munten van alle leden mee, dus de vloer gaat over de
hele mand. Op papier had elk lid een eigen saldo van 10.000 en toetste de vloer
per markt: de papiermand handelde door bij 3.632 (vloer 5.000). Nu toetst de
vloer op papier de equity van de hele mand, elke cyclus.

Punt 7 - L-GS-031: handelsrooster op New Yorkse tijd. 3 van 3 avonden
(24-26/10): beide brokers dicht 22:00 en open 23:01 CET (= 17:00-18:00 New
York; Europa ging 25-10 naar wintertijd, de VS pas 1-11). Het rooster had de
pauze vast op 23:00-24:00 Amsterdam: IG wachtte tot 24:00.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper import mand as mand_mod  # noqa: E402
from gold_scalper.broker import schedule  # noqa: E402
from gold_scalper.broker.risk import RiskLimits, RiskManager, TradingState  # noqa: E402
from gold_scalper.broker.simulator import SimulatorVenue  # noqa: E402
from gold_scalper.const import INTEGRATION_VERSION  # noqa: E402
from test_v2213_mandlid_en_noodstop import _Lid, _mand  # noqa: E402

AMS = ZoneInfo("Europe/Amsterdam")
NY = ZoneInfo("America/New_York")
NU = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _ams(jaar, maand, dag, uur, minuut=0, seconde=0):
    return datetime(jaar, maand, dag, uur, minuut, seconde, tzinfo=AMS)


def test_versie_2_25_0():
    assert tuple(int(x) for x in INTEGRATION_VERSION.split(".")) >= (2, 25, 0)


# --------------------------------------------------------------------------- #
# Punt 4: vermogensvloer van de hele mand op papier
# --------------------------------------------------------------------------- #

def _risk(pct=50.0):
    return RiskManager(RiskLimits(equity_floor_pct=pct, max_daily_loss_pct=99.0),
                       10_000.0, now=NU)


def _args(**over):
    base = dict(now=NU, balance=10_000.0, equity=10_000.0, starting_balance=10_000.0,
                open_positions=0, volume=0.01, spread=0.0, last_tick_age=1.0,
                market_open=True, atr=1.0, opening_equity=10_000.0)
    base.update(over)
    return base


def test_mandvloer_rekent_op_de_startbalans_van_de_mand():
    v = _risk().mandvloer((3632.0, 10_000.0))
    assert v["effective_equity_floor"] == pytest.approx(5000.0)
    assert v["current_equity_account"] == pytest.approx(3632.0)
    assert v["bereik"] == "mand"


def test_mand_onder_de_vloer_geeft_noodstop():
    r = _risk()
    assert r.toets_mandvloer((3632.0, 10_000.0)) is True
    assert r.state.state is TradingState.HALTED
    assert "equity van de mand 3632.00" in r.state.halt_reason
    assert "geldt voor de hele mand" in r.state.halt_reason


def test_mand_boven_de_vloer_of_onbekend_geen_noodstop():
    r = _risk()
    assert r.toets_mandvloer((5000.0, 10_000.0)) is False
    assert r.toets_mandvloer((None, 10_000.0)) is False
    assert r.toets_mandvloer(None) is False
    assert r.state.state is TradingState.RUNNING


def test_can_open_toetst_de_mand_niet_het_eigen_saldo():
    # Eigen papiersaldo 10.000 (deze markt handelde niet), mand op 3.632:
    # tot 2.24.3 mocht dit lid gewoon openen.
    r = _risk()
    ok, reden = r.can_open(**_args(vloer_mand=(3632.0, 10_000.0)))
    assert ok is False and reden == "equity van de mand onder de ondergrens"
    assert r.state.state is TradingState.HALTED


def test_can_open_eigen_markt_laag_maar_mand_gezond():
    # De vloer gaat over de mand: één markt met 4.000 op zijn eigen saldo legt
    # niets stil zolang de mand als geheel boven de vloer zit (net als live).
    r = _risk()
    ok, reden = r.can_open(**_args(equity=4000.0, balance=4000.0,
                                   vloer_mand=(9000.0, 10_000.0)))
    assert ok is True and reden is None


def test_zonder_mand_ongewijzigd():
    r = _risk()
    ok, _ = r.can_open(**_args(equity=4000.0, balance=4000.0))
    assert ok is False and r.state.state is TradingState.HALTED
    assert "hele mand" not in r.state.halt_reason


def _lid(symbol, equity):
    lid = _Lid(symbol)
    lid.starting_balance = 10_000.0
    lid.data = {"stats": {"trades": 1, "net_pnl": equity - 10_000.0},
                "equity": equity, "balance": equity}
    return lid


def test_vloer_equity_van_de_mand_is_de_som_van_alle_leden():
    hoofd = _lid("BTC-EUR", 10_000.0)
    m = _mand(hoofd)
    m.leden = {"PEPE-EUR": _lid("PEPE-EUR", 8_000.0), "PUMP-EUR": _lid("PUMP-EUR", 7_000.0)}
    # Een vertrokken markt telt mee via het archief.
    m._archief = {"BILL-EUR": ({"markt": "BILL-EUR", "trades": 9, "netto": -1_368.0,
                                "startbalans": 10_000.0, "bron": "database"}, [])}
    m._archief_geladen = True
    eq, start = m.vloer_equity()
    assert start == 10_000.0
    assert eq == pytest.approx(10_000.0 - 2_000.0 - 3_000.0 - 1_368.0)   # 3.632
    assert eq == m.grootboek()["equity"]
    # De verse equity van het lid deze cyclus telt in plaats van de vorige.
    eq2, _ = m.vloer_equity(m.leden["PEPE-EUR"], 7_900.0)
    assert eq2 == pytest.approx(eq - 100.0)


def test_vloer_equity_pas_als_de_mand_gereed_is():
    m = _mand(_lid("BTC-EUR", 10_000.0))
    m._archief_geladen = False
    assert m.vloer_equity() is None


def _coord(mand=None, paper=True):
    from gold_scalper.coordinator import GoldScalperCoordinator

    c = GoldScalperCoordinator.__new__(GoldScalperCoordinator)
    c._mand = mand
    c.paper = SimpleNamespace() if paper else None
    return c


def test_coordinator_mand_vloer_alleen_op_papier_in_een_mand():
    m = _mand(_lid("BTC-EUR", 10_000.0))
    m._archief_geladen = True
    assert _coord(m)._mand_vloer(10_000.0) == (10_000.0, 10_000.0)
    assert _coord(None)._mand_vloer(10_000.0) is None
    # Live: bitvavo.account() telt de hele mand al; geen tweede toets.
    assert _coord(m, paper=False)._mand_vloer(10_000.0) is None


def test_coordinator_toetst_de_mandvloer_elke_cyclus():
    """De toets staat in de boekhouding van de cyclus, niet alleen bij een
    signaal: op 1h/4h/1d komt een signaal zelden, de noodstop moet meteen."""
    bron = open(os.path.join(os.path.dirname(mand_mod.__file__), "coordinator.py"),
                encoding="utf-8").read()
    blok = bron[bron.index('self._deel.mark("saldo")'):][:900]
    assert "vloer_mand = self._mand_vloer(equity)" in blok
    assert "self.risk.toets_mandvloer(vloer_mand)" in blok
    assert bron.count("vloer_mand=vloer_mand") == 1
    assert 'vloer_mand=self._mand_vloer(ctx["equity"])' in bron


class _Notifier:
    enabled = True

    def __init__(self):
        self.alerts = []

    async def alert(self, sleutel, titel, tekst, critical=True):
        self.alerts.append(sleutel)

    def clear(self, sleutel):
        pass

    def hourly_due(self):
        return False


def _notify_coord(mand, is_hoofd):
    c = _coord(mand)
    c.notifier = _Notifier()
    c.risk = _risk()
    c.risk.toets_mandvloer((3632.0, 10_000.0))
    c._previous_risk_state = "running"
    c.lifecycle = SimpleNamespace(state=SimpleNamespace(value="running"))
    c.executor_notes = []
    c.data = {}
    if is_hoofd:
        mand.hoofd = c
    return c


def test_alleen_de_hoofdlus_meldt_de_mandvloer():
    m = _mand(_lid("BTC-EUR", 10_000.0))
    lid = _notify_coord(m, is_hoofd=False)
    asyncio.run(lid._notify({}))
    assert lid.notifier.alerts == []
    assert lid._previous_risk_state == "halted"
    hoofd = _notify_coord(m, is_hoofd=True)
    asyncio.run(hoofd._notify({}))
    assert hoofd.notifier.alerts == ["halt"]


# --------------------------------------------------------------------------- #
# Punt 7: L-GS-031, het rooster van spot goud in New Yorkse tijd
# --------------------------------------------------------------------------- #

def test_rooster_staat_in_new_york():
    assert schedule.SPOT_GOLD.tz.key == "America/New_York"
    assert schedule.WEEKEND_GOLD.tz.key == "Europe/Amsterdam"


@pytest.mark.parametrize("dag", [26, 27, 28, 29])
def test_dst_week_pauze_22_tot_23_cet(dag):
    """Ma 26 t/m do 29-10-2026: Europa wintertijd, VS nog zomertijd. Zo
    gemeten bij beide brokers (L-GS-031, 3 van 3 avonden)."""
    assert schedule.is_open(schedule.SPOT_GOLD, _ams(2026, 10, dag, 21, 59))[0] is True
    dicht, reden = schedule.is_open(schedule.SPOT_GOLD, _ams(2026, 10, dag, 22, 30))
    assert dicht is False and "22:00 tot 23:00" in reden
    assert schedule.is_open(schedule.SPOT_GOLD, _ams(2026, 10, dag, 23, 1))[0] is True
    # Tot 2.24.3 dicht (rooster 23:00-24:00): IG wachtte tot 24:00.
    assert schedule.is_open(schedule.SPOT_GOLD, _ams(2026, 10, dag, 23, 30))[0] is True


def test_gewone_winter_en_zomer_ongewijzigd():
    # Winter (beide wintertijd): pauze 23:00-24:00 CET, zoals altijd.
    for t, verwacht in [((2026, 11, 4, 22, 59), True), ((2026, 11, 4, 23, 30), False),
                        ((2026, 11, 5, 0, 0), True)]:
        assert schedule.is_open(schedule.SPOT_GOLD, _ams(*t))[0] is verwacht
    # Zomer (beide zomertijd): idem.
    for t, verwacht in [((2026, 7, 15, 22, 59), True), ((2026, 7, 15, 23, 30), False),
                        ((2026, 7, 16, 0, 0), True)]:
        assert schedule.is_open(schedule.SPOT_GOLD, _ams(*t))[0] is verwacht


def test_maart_dst_weken():
    # 2027: VS zomertijd vanaf 14-03, Europa vanaf 28-03. Woensdag 17-03:
    # 17:00 New York = 21:00 UTC = 22:00 CET.
    assert schedule.is_open(schedule.SPOT_GOLD, _ams(2027, 3, 17, 22, 30))[0] is False
    assert schedule.is_open(schedule.SPOT_GOLD, _ams(2027, 3, 17, 23, 30))[0] is True


def test_week_open_en_dicht_in_new_york():
    # Zondag 01-11-2026 (VS schakelt die nacht om): opent 18:00 NY = 00:00 CET.
    assert schedule.is_open(schedule.SPOT_GOLD, _ams(2026, 11, 1, 23, 59))[0] is False
    assert schedule.is_open(schedule.SPOT_GOLD, _ams(2026, 11, 2, 0, 0, 1))[0] is True
    # Zondag 25-10-2026 (VS nog zomertijd): opent al 23:00 CET.
    assert schedule.is_open(schedule.SPOT_GOLD, _ams(2026, 10, 25, 22, 59))[0] is False
    assert schedule.is_open(schedule.SPOT_GOLD, _ams(2026, 10, 25, 23, 1))[0] is True
    # Zaterdag altijd dicht.
    dicht, reden = schedule.is_open(schedule.SPOT_GOLD, _ams(2026, 10, 31, 12, 0))
    assert dicht is False and reden == "buiten de handelsweek"


def test_vrijdag_30_10_sluit_om_22_cet():
    vr = schedule.SPOT_GOLD
    assert schedule.is_open(vr, _ams(2026, 10, 30, 21, 59))[0] is True
    dicht, reden = schedule.is_open(vr, _ams(2026, 10, 30, 22, 1))
    assert dicht is False and "gesloten sinds 22:00" in reden
    # Vrijdag 06-11 (beide wintertijd): weer 23:00.
    assert schedule.is_open(vr, _ams(2026, 11, 6, 22, 59))[0] is True
    assert schedule.is_open(vr, _ams(2026, 11, 6, 23, 1))[0] is False


def test_weekendsluiting_2_22_0_schuift_mee():
    """Geen instap in het laatste uur, sluiten vanaf 30 minuten ervoor: op vr
    30-10 dus vanaf 21:00 en 21:30 CET, op vr 06-11 vanaf 22:00 en 22:30."""
    f = schedule.minuten_tot_weekendsluiting
    assert f(schedule.SPOT_GOLD, _ams(2026, 10, 30, 21, 10)) == pytest.approx(50)
    assert f(schedule.SPOT_GOLD, _ams(2026, 10, 30, 21, 30)) == pytest.approx(30)
    assert f(schedule.SPOT_GOLD, _ams(2026, 10, 30, 22, 10)) is None      # al dicht
    assert f(schedule.SPOT_GOLD, _ams(2026, 11, 6, 22, 10)) == pytest.approx(50)
    assert f(schedule.SPOT_GOLD, _ams(2026, 11, 6, 22, 30)) == pytest.approx(30)
    # Op een gewone dag geen weekendsluiting (de dagpauze telt niet).
    assert f(schedule.SPOT_GOLD, _ams(2026, 10, 29, 21, 50)) is None


def test_coordinator_weekendgrendels_op_vr_30_10():
    from gold_scalper.coordinator import (
        WEEKEND_GEEN_INSTAP_MIN, WEEKEND_SLUIT_MIN, GoldScalperCoordinator,
    )

    c = GoldScalperCoordinator.__new__(GoldScalperCoordinator)
    c.venue = SimpleNamespace()        # geen eigen rooster: IG-rooster
    c._use_schedule = True
    assert c._weekend_instap_reden(_ams(2026, 10, 30, 20, 50)) is None
    reden = c._weekend_instap_reden(_ams(2026, 10, 30, 21, 10))
    assert reden and "weekendsluiting over 50 min" in reden
    assert c._minuten_tot_weekendsluiting(_ams(2026, 10, 30, 21, 31)) <= WEEKEND_SLUIT_MIN
    assert WEEKEND_GEEN_INSTAP_MIN == 60 and WEEKEND_SLUIT_MIN == 30


def test_minuten_tot_sluiting_in_de_dst_week():
    f = schedule.minutes_until_close
    assert f(schedule.SPOT_GOLD, _ams(2026, 10, 28, 21, 50)) == pytest.approx(10)
    assert f(schedule.SPOT_GOLD, _ams(2026, 11, 4, 22, 50)) == pytest.approx(10)
    assert f(schedule.SPOT_GOLD, _ams(2026, 10, 28, 22, 30)) is None


def test_kruiscontrole_dst_week_geen_afwijking_meer():
    """26-10 23:01: broker open, rooster dicht ('rooster_wijkt_af'). Nu eens."""
    open_nu, melding = schedule.cross_check(True, schedule.SPOT_GOLD, _ams(2026, 10, 26, 23, 1))
    assert open_nu is True and melding is None
    open_nu, melding = schedule.cross_check(False, schedule.SPOT_GOLD, _ams(2026, 10, 26, 22, 0, 30))
    assert open_nu is False and melding is None


def test_klokrand_op_de_new_yorkse_grens():
    assert schedule.bij_roostergrens(schedule.SPOT_GOLD, _ams(2026, 10, 27, 22, 0, 5))
    assert schedule.bij_roostergrens(schedule.SPOT_GOLD, _ams(2026, 10, 27, 23, 0, 3))
    assert not schedule.bij_roostergrens(schedule.SPOT_GOLD, _ams(2026, 10, 27, 23, 30))


def test_simulator_weekend_in_new_york():
    v = SimulatorVenue.__new__(SimulatorVenue)
    # Vr 30-10 21:30 UTC = 17:30 New York (zomertijd): dicht.
    assert v._is_market_open(datetime(2026, 10, 30, 21, 30, tzinfo=timezone.utc)) is False
    # Vr 06-11 21:30 UTC = 16:30 New York (wintertijd): nog open.
    assert v._is_market_open(datetime(2026, 11, 6, 21, 30, tzinfo=timezone.utc)) is True
    # Zo 08-11 22:30 UTC = 17:30 New York: nog dicht; 23:30 UTC open.
    assert v._is_market_open(datetime(2026, 11, 8, 22, 30, tzinfo=timezone.utc)) is False
    assert v._is_market_open(datetime(2026, 11, 8, 23, 30, tzinfo=timezone.utc)) is True
