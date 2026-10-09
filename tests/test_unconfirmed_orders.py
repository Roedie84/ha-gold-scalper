"""Onbevestigde orders: onbekend, niet mislukt (5.6.1).

Het incident van 30-09: IG demo bevestigde orders niet binnen de wachttijd van
één seconde. Elke order gold als "niet geplaatst", de volgende cyclus stuurde
een nieuwe, en de broker voerde ze allemaal uit. Elf orders in twee minuten,
twaalf op de dag, allemaal onbewaakt.

Wat hier vastligt:

* een onbevestigde order wordt teruggezocht, niet opnieuw verstuurd;
* zolang hij niet terug is, gaat er geen enkele nieuwe order uit;
* een teruggevonden positie wordt vastgelegd, krijgt een stop, en telt mee;
* ook als de broker de positie pas later in zijn lijst toont.
"""
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.adapter import OrderResult, VenuePosition  # noqa: E402
from gold_scalper.broker.execution_safety import SafeExecutor  # noqa: E402


class TraagBevestigend:
    """Voert elke order uit, bevestigt nooit, en toont posities pas na
    ``verborgen`` opvragingen."""

    name = "traag"

    def __init__(self, *, verborgen=0, met_referentie=True, confirm=None,
                 stop_mee=True):
        self.verborgen = verborgen
        self.met_referentie = met_referentie
        self._confirm = confirm           # None: geen confirm_status
        self.stop_mee = stop_mee
        self._posities: list[VenuePosition] = []
        self.orders = []
        self.stops = []
        self.gesloten = []
        if confirm is not None:
            self.confirm_status = self._confirm_status

    async def place_order(self, symbol, side, units, stop_loss=None,
                          take_profit=None, comment=""):
        self.orders.append(comment)
        ticket = f"D{len(self.orders)}"
        self._posities.append(VenuePosition(
            ticket=ticket, symbol=symbol, side=side, units=units,
            open_price=4180.0 + len(self.orders), stop_loss=stop_loss if self.stop_mee else None,
            take_profit=take_profit,
            comment=comment if self.met_referentie else None,
        ))
        return OrderResult(success=False, unconfirmed=True, client_ref=comment,
                           error=f"Geen bevestiging voor {comment}.")

    async def positions(self, symbol=None):
        if self.verborgen > 0:
            self.verborgen -= 1
            return []
        return list(self._posities)

    async def _confirm_status(self, reference):
        status, deal = self._confirm
        return status, deal

    async def modify_stop(self, ticket, stop_loss, take_profit=None):
        self.stops.append((ticket, stop_loss))
        for p in self._posities:
            if p.ticket == ticket:
                p.stop_loss = stop_loss

    async def modify_target(self, ticket, take_profit, stop_loss=None):
        for p in self._posities:
            if p.ticket == ticket:
                p.take_profit = take_profit

    async def close(self, ticket, units=None):
        self.gesloten.append(ticket)
        self._posities = [p for p in self._posities if p.ticket != ticket]
        return OrderResult(success=True, ticket=ticket)


def _executor(venue):
    ex = SafeExecutor(venue)
    ex.lookup_delays = (0.0, 0.0, 0.0, 0.0)
    return ex


def _open(ex, side="buy"):
    return asyncio.run(ex.open_protected(
        "GOLD", side, 1.3, 4180.0, stop_loss=4170.0, take_profit=4195.0,
        context=("sig", "koers", side, "nu"),
    ))


# ------------------------------------------------------- veiligheidslaag --

def test_an_unconfirmed_order_found_at_once_counts_as_opened():
    venue = TraagBevestigend()
    ex = _executor(venue)
    result, notes = _open(ex)
    assert result.success and result.ticket == "D1"
    assert len(venue.orders) == 1 and not ex.has_pending
    assert any("teruggevonden" in n for n in notes)


def test_an_unconfirmed_order_not_yet_visible_becomes_pending():
    venue = TraagBevestigend(verborgen=100)
    ex = _executor(venue)
    result, _ = _open(ex)
    assert result.unconfirmed and not result.success and result.ticket is None
    assert ex.has_pending and len(venue.orders) == 1


def test_no_second_order_while_one_is_pending():
    venue = TraagBevestigend(verborgen=100)
    ex = _executor(venue)
    _open(ex)
    for _ in range(10):
        result, _ = _open(ex)
        assert not result.success
    assert len(venue.orders) == 1, "er ging een order uit terwijl de vorige onbekend was"


def test_pending_is_resolved_once_the_broker_shows_the_position():
    venue = TraagBevestigend(verborgen=4)       # precies de directe zoekpogingen
    ex = _executor(venue)
    _open(ex)
    assert ex.has_pending
    gevonden, notes = asyncio.run(ex.resolve_pending(set()))
    assert [p.ticket for _, p in gevonden] == ["D1"]
    assert gevonden[0][0].context == ("sig", "koers", "buy", "nu")
    assert not ex.has_pending


def test_a_rejected_order_is_released_without_a_position():
    venue = TraagBevestigend(verborgen=100, confirm=("REJECTED", None))
    ex = _executor(venue)
    _open(ex)
    assert not ex.has_pending        # direct uitsluitsel: afgewezen
    assert len(venue.orders) == 1


def test_accepted_deal_id_finds_the_position_without_reference():
    venue = TraagBevestigend(met_referentie=False, confirm=("ACCEPTED", "D1"))
    ex = _executor(venue)
    result, _ = _open(ex)
    assert result.success and result.ticket == "D1"


def test_last_resort_is_exactly_one_unknown_position_in_the_same_direction():
    venue = TraagBevestigend(verborgen=100, met_referentie=False)
    ex = _executor(venue)
    _open(ex)
    venue.verborgen = 0
    venue._posities.append(VenuePosition(
        ticket="BEKEND", symbol="GOLD", side="buy", units=1.3, open_price=4000.0,
        stop_loss=3990.0,
    ))
    gevonden, _ = asyncio.run(ex.resolve_pending({"BEKEND"}))
    assert [p.ticket for _, p in gevonden] == ["D1"]


def test_two_unknown_positions_are_not_guessed():
    venue = TraagBevestigend(verborgen=100, met_referentie=False)
    ex = _executor(venue)
    _open(ex)
    venue.verborgen = 0
    venue._posities.append(VenuePosition(
        ticket="X", symbol="GOLD", side="buy", units=1.3, open_price=4000.0,
        stop_loss=3990.0,
    ))
    gevonden, _ = asyncio.run(ex.resolve_pending(set()))
    assert gevonden == [] and ex.has_pending


def test_pending_expires_and_the_audit_is_the_safety_net():
    venue = TraagBevestigend(verborgen=10_000)
    ex = _executor(venue)
    _open(ex)
    ex.pending_expiry = -1
    gevonden, notes = asyncio.run(ex.resolve_pending(set()))
    assert gevonden == [] and not ex.has_pending
    assert any("afstemming" in n for n in notes)


def test_a_recovered_position_without_stop_gets_one():
    venue = TraagBevestigend(verborgen=100, stop_mee=False)
    ex = _executor(venue)
    _open(ex)
    venue.verborgen = 0
    gevonden, _ = asyncio.run(ex.resolve_pending(set()))
    assert gevonden and venue.stops == [("D1", 4170.0)]


def test_a_plain_rejection_is_not_pending():
    class Weigerend(TraagBevestigend):
        async def place_order(self, *a, **k):
            self.orders.append("x")
            return OrderResult(success=False, error="geweigerd")
    ex = _executor(Weigerend())
    result, _ = _open(ex)
    assert not result.success and not ex.has_pending


# ------------------------------------------------------------------- IG --

def test_ig_marks_a_missing_confirmation_as_unconfirmed(monkeypatch):
    import gold_scalper.broker.ig_capital as ig
    from gold_scalper.broker.adapter import VenueError

    monkeypatch.setattr(ig, "CONFIRM_DELAYS", (0.0, 0.0))
    venue = ig.IgVenue.__new__(ig.IgVenue)

    async def geen(*a, **k):
        raise VenueError("404 deal-not-found")
    venue._request = geen

    result = asyncio.run(venue._confirm({"dealReference": "gold_scalper-abc"}, 4180.0, 12.0, ""))
    assert result.unconfirmed and not result.success
    assert result.ticket is None and result.client_ref == "gold_scalper-abc"


@pytest.mark.parametrize("antwoord,verwacht", [
    ({"dealStatus": "ACCEPTED", "dealId": "DIAAA1"}, ("ACCEPTED", "DIAAA1")),
    ({"dealStatus": "REJECTED"}, ("REJECTED", None)),
    ({"dealStatus": "PENDING"}, ("UNKNOWN", None)),
])
def test_ig_confirm_status(antwoord, verwacht):
    import gold_scalper.broker.ig_capital as ig

    venue = ig.IgVenue.__new__(ig.IgVenue)

    async def vraag(*a, **k):
        return antwoord
    venue._request = vraag
    assert asyncio.run(venue.confirm_status("ref")) == verwacht


def test_ig_waits_longer_than_before():
    import gold_scalper.broker.ig_capital as ig
    assert sum(ig.CONFIRM_DELAYS) >= 5.0


# ----------------------------------------------------------- coordinator --

@dataclass
class _Signaal:
    direction: int = 1
    score: float = 0.8
    confidence: float = 0.8
    should_trade: bool = True
    reject_reason: str | None = None
    reason: str = "test"
    stop_loss: float | None = 4390.0
    take_profit: float | None = 4415.0
    expected_move: float = 5.0
    expected_cost: float = 0.6
    components: dict = None

    def __post_init__(self):
        self.components = self.components or {}


def _coordinator_met(venue_cls, tmp_path, monkeypatch, respecteer_telling):
    from test_broker_cycle import ScriptedVenue, _coordinator

    import gold_scalper.coordinator as co

    class Traag(ScriptedVenue):
        verborgen: int = 0

        async def place_order(self, symbol, side, units, stop_loss=None,
                              take_profit=None, comment=""):
            await ScriptedVenue.place_order(
                self, symbol, side, units, stop_loss, take_profit, comment,
            )
            return OrderResult(success=False, unconfirmed=True, client_ref=comment,
                               error="Geen bevestiging.")

        async def positions(self, symbol=None):
            if self.verborgen > 0:
                self.verborgen -= 1
                return []
            return list(self._positions)

        async def quote(self, symbol=None):
            from gold_scalper.broker.adapter import VenueQuote
            half = self.spread / 2
            return VenueQuote(bid=self.price - half, ask=self.price + half,
                              time=_nu(), tradeable=True)

    def altijd(candles, bid, ask, cfg, uur, open_count, sinds, kant, *_rest):
        # 1.9.0: de coordinator geeft ook de telling per richting mee.
        if respecteer_telling and open_count:
            return _Signaal(should_trade=False, reject_reason="max_positions")
        return _Signaal()

    monkeypatch.setattr(co, "evaluate", altijd)
    venue = Traag()
    coordinator, _ = _coordinator(venue, tmp_path, monkeypatch)
    coordinator.executor.venue = venue
    coordinator.executor.lookup_delays = (0.0,)
    coordinator._enabled = True
    coordinator.units = 1.3                   # onder de volumelimiet
    from gold_scalper.lifecycle import LifecycleState
    coordinator.lifecycle._transition(LifecycleState.RUNNING, "test")
    return coordinator, venue


#: Een vast handelsmoment: woensdag 7 oktober 2026, 12:00 Nederlandse tijd.
#: De coordinatortests hieronder liepen op de echte klok en faalden tijdens de
#: dagelijkse marktpauze (23:00-24:00) en in het weekend (L-GS-002).
HANDELSMOMENT = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def handelsmoment(monkeypatch):
    """Zet de klok van de integratie op ``HANDELSMOMENT``; de tijd loopt
    vanaf daar gewoon door, zodat verstreken tijd in de lus blijft kloppen."""
    import datetime as _dt
    import gold_scalper.coordinator  # noqa: F401  alles laden vóór het patchen

    echt = _dt.datetime
    verschil = HANDELSMOMENT - echt.now(timezone.utc)

    class Klok(echt):
        @classmethod
        def now(cls, tz=None):
            nu = echt.now(timezone.utc) + verschil
            return nu.astimezone(tz) if tz is not None else nu.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return (echt.now(timezone.utc) + verschil).replace(tzinfo=None)

    for naam, module in list(sys.modules.items()):
        if (naam == "gold_scalper" or naam.startswith("gold_scalper.")) and \
                getattr(module, "datetime", None) is echt:
            monkeypatch.setattr(module, "datetime", Klok)
    global _klok
    _klok = Klok
    yield
    _klok = None


_klok = None


def _nu():
    """De (eventueel vastgezette) klok van de integratie."""
    return (_klok or datetime).now(timezone.utc)


def _cycli(coordinator, n):
    for _ in range(n):
        asyncio.run(coordinator._async_update_data())


def test_ten_cycles_with_a_pending_order_send_nothing_new(tmp_path, monkeypatch):
    """Het incident, nagespeeld: de broker toont de positie een tijd niet en
    bevestigt nooit. Vroeger elf orders; nu één."""
    coordinator, venue = _coordinator_met(None, tmp_path, monkeypatch, False)
    venue.verborgen = 10_000
    _cycli(coordinator, 10)
    assert len(venue.orders) == 1
    assert coordinator.executor.has_pending


def test_the_pending_order_is_recorded_once_visible(tmp_path, monkeypatch):
    coordinator, venue = _coordinator_met(None, tmp_path, monkeypatch, True)
    venue.verborgen = 10_000
    _cycli(coordinator, 3)
    venue.verborgen = 0
    _cycli(coordinator, 3)
    open_trades = coordinator.db.open_trades(coordinator.run_id)
    assert [t.broker_ticket for t in open_trades] == ["T1"]
    assert not coordinator.executor.has_pending
    assert len(venue.orders) == 1, "na terugvinden ging er toch een tweede order uit"


def test_no_orphan_after_recovery(tmp_path, monkeypatch):
    from gold_scalper.broker.reconcile_audit import compare_positions

    coordinator, venue = _coordinator_met(None, tmp_path, monkeypatch, True)
    venue.verborgen = 10_000
    _cycli(coordinator, 2)
    venue.verborgen = 0
    _cycli(coordinator, 2)
    audit = compare_positions(
        asyncio.run(venue.positions()),
        coordinator.db.open_trades(coordinator.run_id),
    )
    assert not [f for f in audit.findings if f.code == "onbekende_positie"]
    assert coordinator.risk.state.state.value != "halted"


def test_pending_orders_count_as_open_positions(tmp_path, monkeypatch):
    """Zolang de broker de positie niet toont, telt de onbevestigde order
    mee; de strategie ziet dus een open positie."""
    gezien = []
    coordinator, venue = _coordinator_met(None, tmp_path, monkeypatch, True)

    import gold_scalper.coordinator as co
    oud = co.evaluate

    def spion(*args):
        gezien.append(args[5])
        return oud(*args)
    monkeypatch.setattr(co, "evaluate", spion)

    venue.verborgen = 10_000
    _cycli(coordinator, 3)
    assert gezien[0] == 0 and all(n == 1 for n in gezien[1:])


def test_the_reject_reason_says_why(tmp_path, monkeypatch):
    coordinator, venue = _coordinator_met(None, tmp_path, monkeypatch, False)
    venue.verborgen = 10_000
    _cycli(coordinator, 2)
    redenen = [
        r[0] for r in coordinator.db.conn.execute(
            "SELECT reject_reason FROM signals WHERE reject_reason IS NOT NULL"
        ).fetchall()
    ]
    assert any("onbevestigde order" in r for r in redenen)


