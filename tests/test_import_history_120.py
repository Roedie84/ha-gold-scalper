"""1.2.0: historie per periode, terug in de tijd, binnen een puntenbudget.

Tot 1.1 vroeg import_history alleen de laatste bars op (bij IG hooguit 1000).
Die stonden al in het archief: de dienst kon het archief nooit verder terug
laten reiken.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.adapter import VenueError  # noqa: E402
from gold_scalper.broker.ig_capital import IgVenue  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _prijs(ts):
    lvl = {"bid": 4000.0, "ask": 4000.8}
    return {"snapshotTimeUTC": ts.strftime("%Y-%m-%dT%H:%M:%S"), "openPrice": lvl,
            "highPrice": lvl, "lowPrice": lvl, "closePrice": lvl, "lastTradedVolume": 1}


class Nep:
    """IG die per blok elke 15 minuten een bar geeft."""

    def __init__(self, toelage=None, fout_bij=None):
        self.vragen = []
        self.toelage = toelage
        self.fout_bij = fout_bij

    async def __call__(self, method, path, version="1", params=None, **kw):
        self.vragen.append(params)
        if self.fout_bij is not None and len(self.vragen) == self.fout_bij:
            raise VenueError("error.public-api.exceeded-account-historical-data-allowance")
        van = datetime.strptime(params["from"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        tot = datetime.strptime(params["to"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        prijzen, t = [], van
        while t < tot:
            prijzen.append(_prijs(t))
            t += timedelta(minutes=15)
        uit = {"prices": prijzen}
        if self.toelage is not None:
            self.toelage -= len(prijzen)
            uit["metadata"] = {"allowance": {"remainingAllowance": self.toelage,
                                             "totalAllowance": 10000}}
        return uit


def _venue(nep):
    v = IgVenue.__new__(IgVenue)
    v.epic = "CS.D.CFEGOLD.CEA.IP"
    v._request = nep
    return v


def _run(v, dagen, budget):
    return asyncio.run(v.history("CS.D.CFEGOLD.CEA.IP", "15m", T0, T0 + timedelta(days=dagen), budget))


def test_a_period_is_fetched_in_weekly_chunks_from_old_to_new():
    nep = Nep()
    c, info = _run(_venue(nep), 21, 10000)
    assert info["chunks"] == 3 and info["stopped"] == "complete"
    assert [p["from"][:10] for p in nep.vragen] == ["2026-06-01", "2026-06-08", "2026-06-15"]
    assert all(p["pageSize"] == 0 and "max" not in p for p in nep.vragen)
    assert len(c) == 21 * 96 == info["points"]
    assert list(c.timestamp) == sorted(set(c.timestamp))


def test_the_budget_is_never_exceeded():
    nep = Nep()
    c, info = _run(_venue(nep), 60, 2000)
    assert info["stopped"] == "budget"
    assert info["points"] <= 2000
    assert info["chunks"] == 2                      # 2 × 672; een derde zou 2016 worden


def test_it_stops_when_ig_says_the_allowance_is_nearly_gone():
    nep = Nep(toelage=1500)
    c, info = _run(_venue(nep), 60, 10000)
    assert info["stopped"] == "allowance" and info["chunks"] == 2
    assert info["allowance"]["remainingAllowance"] == 1500 - 2 * 672


def test_an_ig_error_keeps_what_arrived():
    nep = Nep(fout_bij=3)
    c, info = _run(_venue(nep), 60, 10000)
    assert info["stopped"] == "error" and "allowance" in info["error"]
    assert len(c) == 2 * 672


def test_no_allowance_is_invented():
    c, info = _run(_venue(Nep()), 7, 10000)
    assert info["allowance"] is None


def test_the_service_goes_back_from_the_oldest_bar_and_answers():
    bron = (PKG / "__init__.py").read_text(encoding="utf-8")
    dienst = bron.split("async def import_history(")[1].split("\n    hass.services.async_register(")[0]
    assert "voor.first" in dienst and "venue.history(" in dienst
    assert "return antwoord" in dienst
    reg = bron.split("SERVICE_IMPORT_HISTORY, _zeg_wat_er_misging")[1].split(")\n")[0:3]
    assert "supports_response=SupportsResponse.OPTIONAL" in "".join(reg) or \
        "supports_response=SupportsResponse.OPTIONAL" in bron.split("SERVICE_IMPORT_HISTORY, _zeg")[1][:600]
    assert 'vol.Exclusive("days", "manier")' in bron


def test_the_error_wrapper_passes_the_response_through():
    bron = (PKG / "__init__.py").read_text(encoding="utf-8")
    omhulsel = bron.split("def _zeg_wat_er_misging")[1].split("return omhullen")[0]
    assert "return await functie(call)" in omhulsel
