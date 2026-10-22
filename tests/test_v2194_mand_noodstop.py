"""2.19.4: de noodstop van een mandlid is zichtbaar op de noodstop van de mand.

Gemeten 22-10: PUMP-EUR en BILL-EUR stonden in noodstop (dagverlies 10 %) en
blokkeerden de hele papieren mand ("mand: noodstop bij PUMP-EUR, BILL-EUR"),
terwijl binary_sensor ..._noodstop van de mand uit stond.
"""

from types import SimpleNamespace

from gold_scalper.binary_sensor import RiskHalted


def _lid(symbol, state, reden=None):
    return SimpleNamespace(
        symbol=symbol,
        risk=SimpleNamespace(as_dict=lambda: {"state": state, "halt_reason": reden}),
    )


def _nep(leden, hoofd_state="running", hoofd_is_hoofd=True):
    risk = SimpleNamespace(as_dict=lambda: {"state": hoofd_state, "halt_reason": None})
    coordinator = SimpleNamespace(data=None, risk=risk, symbol="BTC-EUR")
    mand = SimpleNamespace(leden={l.symbol: l for l in leden})
    mand.hoofd = coordinator if hoofd_is_hoofd else object()
    coordinator._mand = mand
    nep = SimpleNamespace(coordinator=coordinator)
    nep._risk = lambda: RiskHalted._risk(nep)
    return nep


def test_gestopt_lid_zet_noodstop_van_de_mand_aan():
    nep = _nep([_lid("XRP-EUR", "running"), _lid("PUMP-EUR", "halted", "dagverlies 10.06%")])
    assert RiskHalted.is_on.fget(nep) is True
    attrs = RiskHalted.extra_state_attributes.fget(nep)
    assert attrs["markten"] == ["PUMP-EUR"]
    assert "PUMP-EUR: dagverlies 10.06%" in attrs["reason"]


def test_mand_zonder_gestopte_leden_blijft_uit():
    nep = _nep([_lid("XRP-EUR", "running"), _lid("ETH-EUR", "running")])
    assert RiskHalted.is_on.fget(nep) is False
    assert "markten" not in RiskHalted.extra_state_attributes.fget(nep)


def test_lid_zelf_kijkt_niet_naar_de_andere_leden():
    nep = _nep([_lid("PUMP-EUR", "halted", "x")], hoofd_is_hoofd=False)
    assert RiskHalted.is_on.fget(nep) is False


def test_buiten_een_mand_ongewijzigd():
    risk = SimpleNamespace(as_dict=lambda: {"state": "halted", "halt_reason": "x"})
    nep = SimpleNamespace(coordinator=SimpleNamespace(data=None, risk=risk))
    nep._risk = lambda: RiskHalted._risk(nep)
    assert RiskHalted.is_on.fget(nep) is True
