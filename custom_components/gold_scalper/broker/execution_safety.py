"""Veiligheidslaag rond echte orders.

Papermodus kent geen van de storingen hieronder, en juist daarom moeten ze hier
expliciet worden afgevangen: het zijn de gevallen waarin de bewijsfase je
niets heeft geleerd omdat ze er niet in voorkwamen.

Drie risico's, in volgorde van hoeveel geld ze kunnen kosten.

**Onbeschermde positie.** De order wordt gevuld maar de stop-loss komt er niet
op - omdat de broker een minimale stopafstand hanteert, omdat het niveau
inmiddels aan de verkeerde kant van de markt ligt, of omdat de tweede aanroep
faalde. Je hebt dan een open positie zonder rem. Dit is het enige scenario met
in principe onbegrensd verlies, en het wordt hier hard afgehandeld: stop
alsnog plaatsen, en lukt dat niet, positie sluiten.

**Dubbele order.** Je stuurt een order, de verbinding valt weg vóór het
antwoord, en je weet niet of hij is uitgevoerd. Opnieuw sturen verdubbelt je
positie; niet sturen laat een onbewaakte positie achter. Beide zijn fout, dus
moet je het kúnnen weten - vandaar een eigen ordernummer dat bij de broker
terug te vinden is.

**Ongeldige orderparameters.** Volume onder het minimum, stop te dicht op de
markt, prijs niet afgerond op de tick. Die weigert de broker, maar pas nadat je
strategie al een signaal heeft weggegooid. Beter vooraf controleren.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .adapter import ExecutionVenue, OrderResult, VenueError, VenuePosition

_LOGGER = logging.getLogger(__name__)

#: Hoe vaak, en na hoeveel seconden, een onbevestigde order direct wordt
#: teruggezocht voordat hij als openstaand wordt geregistreerd. Samen tien
#: seconden: meer dan een cyclus, zodat er in die tijd niets nieuws gebeurt.
UNCONFIRMED_LOOKUP_DELAYS = (1.0, 2.0, 3.0, 4.0)

#: Na zoveel seconden zonder uitsluitsel vervalt een openstaande order. Er
#: wordt dan weer gehandeld; de periodieke afstemming met de broker is het
#: vangnet en zet de noodstop aan als hij tóch als onbekende positie opduikt.
PENDING_EXPIRY_SECONDS = 600


@dataclass(slots=True)
class PendingOrder:
    """Een order die verstuurd is maar waarvan de uitkomst onbekend is."""

    client_id: str
    symbol: str
    side: str
    created: datetime
    stop_loss: float | None = None
    context: object = None


@dataclass(slots=True)
class BrokerLimits:
    """Grenzen die de broker oplegt. Ophalen bij de venue, niet gokken."""

    min_volume: float = 0.01
    max_volume: float = 100.0
    volume_step: float = 0.01
    #: Minimale afstand tussen koers en stop, in prijs-eenheden.
    min_stop_distance: float = 0.0
    #: Kleinste prijsstap; stops moeten hierop afgerond worden.
    tick_size: float = 0.01

    def round_volume(self, volume: float) -> float:
        if self.volume_step <= 0:
            return volume
        steps = round(volume / self.volume_step)
        return round(steps * self.volume_step, 8)

    def round_price(self, price: float) -> float:
        if self.tick_size <= 0:
            return price
        return round(round(price / self.tick_size) * self.tick_size, 8)


@dataclass(slots=True)
class PreflightResult:
    ok: bool
    volume: float
    stop_loss: float | None
    take_profit: float | None
    problems: list[str] = field(default_factory=list)
    adjustments: list[str] = field(default_factory=list)


def preflight(
    side: str,
    volume: float,
    price: float,
    stop_loss: float | None,
    take_profit: float | None,
    limits: BrokerLimits,
) -> PreflightResult:
    """Controleer en corrigeer orderparameters vóór verzending.

    Corrigeert wat veilig te corrigeren is (afronding) en weigert wat dat niet
    is (te klein volume, stop aan de verkeerde kant). Een stop verder wegzetten
    om aan de minimumafstand te voldoen gebeurt bewust *niet* stilzwijgend: dat
    vergroot je risico zonder dat je het vroeg.
    """
    problems: list[str] = []
    adjustments: list[str] = []

    rounded = limits.round_volume(volume)
    if abs(rounded - volume) > 1e-9:
        adjustments.append(f"volume {volume} afgerond naar {rounded}")
    if rounded < limits.min_volume:
        problems.append(
            f"volume {rounded} onder het brokerminimum {limits.min_volume}"
        )
    if rounded > limits.max_volume:
        problems.append(
            f"volume {rounded} boven het brokermaximum {limits.max_volume}"
        )

    long = side == "buy"

    def _check_level(level: float | None, name: str, must_be_below: bool):
        if level is None:
            return None
        snapped = limits.round_price(level)
        if abs(snapped - level) > 1e-9:
            adjustments.append(f"{name} {level} afgerond naar {snapped}")
        wrong_side = (snapped >= price) if must_be_below else (snapped <= price)
        if wrong_side:
            problems.append(
                f"{name} {snapped} ligt aan de verkeerde kant van de koers {price}"
            )
            return snapped
        distance = abs(price - snapped)
        if limits.min_stop_distance and distance < limits.min_stop_distance:
            problems.append(
                f"{name} ligt {distance:.3f} van de koers; de broker eist minimaal "
                f"{limits.min_stop_distance:.3f}. De stop verder wegzetten zou je "
                "risico vergroten, dus deze trade wordt overgeslagen."
            )
        return snapped

    stop = _check_level(stop_loss, "stop-loss", must_be_below=long)
    target = _check_level(take_profit, "take-profit", must_be_below=not long)

    return PreflightResult(
        ok=not problems, volume=rounded, stop_loss=stop,
        take_profit=target, problems=problems, adjustments=adjustments,
    )


class SafeExecutor:
    """Wikkelt een venue in met bescherming tegen dubbele en onbewaakte orders."""

    def __init__(
        self,
        venue: ExecutionVenue,
        limits: BrokerLimits | None = None,
        strategy_tag: str = "gold_scalper",
    ) -> None:
        self.venue = venue
        self.limits = limits or BrokerLimits()
        self.strategy_tag = strategy_tag
        #: Ordernummers die verzonden zijn maar waarvan het antwoord uitbleef.
        self._in_flight: dict[str, datetime] = {}
        #: Orders met onbekende uitkomst. Zolang hier iets staat, mag er geen
        #: nieuwe order uit: de vorige kan al uitgevoerd zijn.
        self.pending: dict[str, PendingOrder] = {}
        self.lookup_delays: tuple[float, ...] = UNCONFIRMED_LOOKUP_DELAYS
        self.pending_expiry = PENDING_EXPIRY_SECONDS

    @property
    def has_pending(self) -> bool:
        return bool(self.pending)

    # -- openen -------------------------------------------------------------- #

    async def open_protected(
        self,
        symbol: str,
        side: str,
        units: float,
        price: float,
        stop_loss: float | None,
        take_profit: float | None = None,
        context: object = None,
    ) -> tuple[OrderResult, list[str]]:
        """Open een positie en garandeer dat er een stop op zit.

        Een positie zonder stop is het enige scenario met in principe
        onbegrensd verlies. Lukt het niet er een op te krijgen, dan gaat de
        positie direct weer dicht - een kleine zekere kost is beter dan een
        onbekende.
        """
        notes: list[str] = []

        if stop_loss is None:
            raise VenueError(
                "Weigering: een live positie zonder stop-loss wordt niet geopend."
            )
        if self.pending:
            # Tweede slot achter de coordinator: nooit een order terwijl de
            # uitkomst van de vorige onbekend is.
            return OrderResult(
                success=False,
                error="Er staat nog een onbevestigde order open; eerst terugvinden.",
            ), notes

        check = preflight(side, units, price, stop_loss, take_profit, self.limits)
        notes.extend(check.adjustments)
        if not check.ok:
            return OrderResult(success=False, error="; ".join(check.problems)), notes

        client_id = f"{self.strategy_tag}-{uuid.uuid4().hex[:12]}"
        self._in_flight[client_id] = datetime.now(timezone.utc)

        try:
            result = await self.venue.place_order(
                symbol, side, check.volume,
                stop_loss=check.stop_loss, take_profit=check.take_profit,
                comment=client_id,
            )
        except VenueError as err:
            # Antwoord uitgebleven: we weten niet of hij is uitgevoerd. Kijken
            # bij de broker in plaats van gokken.
            notes.append(f"Order gaf een fout ({err}); posities worden nagekeken")
            recovered = await self._find_by_comment(symbol, client_id)
            if recovered:
                notes.append(
                    f"Order bleek tóch uitgevoerd (ticket {recovered.ticket}); "
                    "geen tweede order verstuurd"
                )
                result = OrderResult(
                    success=True, ticket=recovered.ticket,
                    fill_price=recovered.open_price, units=recovered.units,
                )
            else:
                self._in_flight.pop(client_id, None)
                raise
        finally:
            self._in_flight.pop(client_id, None)

        if result.unconfirmed:
            gevonden, afgewezen = await self._lookup_unconfirmed(symbol, client_id, side)
            if afgewezen:
                notes.append(f"Order {client_id} was afgewezen door de broker; niets open")
                return OrderResult(
                    success=False, requested_price=result.requested_price,
                    latency_ms=result.latency_ms, client_ref=client_id,
                    error="Order afgewezen (achteraf bevestigd)",
                ), notes
            if gevonden is None:
                self.pending[client_id] = PendingOrder(
                    client_id, symbol, side, datetime.now(timezone.utc),
                    check.stop_loss, context,
                )
                notes.append(
                    f"Order {client_id} onbevestigd en nog niet teruggevonden; "
                    "nieuwe orders wachten"
                )
                return result, notes
            notes.append(
                f"Order {client_id} onbevestigd maar teruggevonden als ticket "
                f"{gevonden.ticket}; geen tweede order verstuurd"
            )
            result = OrderResult(
                success=True, ticket=str(gevonden.ticket),
                fill_price=gevonden.open_price or None, units=gevonden.units,
                requested_price=result.requested_price,
                latency_ms=result.latency_ms, client_ref=client_id,
            )

        if not result.success or not result.ticket:
            return result, notes

        protected, note = await self._ensure_stop(
            symbol, result.ticket, check.stop_loss
        )

        # Ook het doel nakijken. Minder ernstig dan een ontbrekende stop - de
        # bot sluit zelf zodra de koers het doel raakt - maar zonder deze
        # controle merk je nooit dat je winst onbeschermd is als Home Assistant
        # uitvalt.
        if check.take_profit is not None:
            target_note = await self._verify_target(
                symbol, result.ticket, check.take_profit
            )
            if target_note:
                notes.append(target_note)
        # Het doel wordt óók nagekeken, maar met andere gevolgen. Ontbreekt de
        # stop, dan is de positie onbeschermd en gaat hij dicht. Ontbreekt het
        # doel, dan sluit de bot zelf op het niveau - dat werkt zolang Home
        # Assistant draait. Dat verschil hoort zichtbaar te zijn in plaats van
        # stilzwijgend aangenomen.
        if check.take_profit is not None:
            target_note = await self._verify_target(
                symbol, result.ticket, check.take_profit
            )
            if target_note:
                notes.append(target_note)
        if note:
            notes.append(note)
        if not protected:
            notes.append("Positie zonder stop; wordt direct gesloten")
            try:
                await self.venue.close(result.ticket)
            except VenueError as err:
                _LOGGER.critical(
                    "ONBESCHERMDE POSITIE %s kon niet gesloten worden: %s. "
                    "Grijp handmatig in bij je broker.", result.ticket, err,
                )
                notes.append(
                    "SLUITEN MISLUKT - handmatig ingrijpen bij de broker vereist"
                )
            return OrderResult(
                success=False, ticket=result.ticket,
                error="stop-loss kon niet geplaatst worden",
            ), notes

        return result, notes

    async def _ensure_stop(
        self, symbol: str, ticket: str, stop_loss: float
    ) -> tuple[bool, str | None]:
        """Controleer dat de stop er werkelijk op zit, en plaats hem anders alsnog."""
        try:
            positions = await self.venue.positions(symbol)
        except VenueError as err:
            return False, f"Kon posities niet nakijken: {err}"

        position = next((p for p in positions if str(p.ticket) == str(ticket)), None)
        if position is None:
            # Al gesloten - bijvoorbeeld direct op de TP. Geen probleem.
            return True, None
        if position.stop_loss:
            return True, None

        try:
            await self.venue.modify_stop(ticket, stop_loss)
        except VenueError as err:
            return False, f"Stop plaatsen mislukte: {err}"

        try:
            positions = await self.venue.positions(symbol)
        except VenueError as err:
            return False, f"Kon stop niet verifiëren: {err}"
        position = next((p for p in positions if str(p.ticket) == str(ticket)), None)
        if position is None or position.stop_loss:
            return True, "Stop achteraf geplaatst"
        return False, "Stop staat er na twee pogingen nog niet op"

    async def _verify_target(
        self, symbol: str, ticket: str, take_profit: float
    ) -> str | None:
        """Controleer of het doel bij de broker staat, en plaats het anders alsnog.

        Bij IG heet dit veld ``limitLevel``. Wordt hij geweigerd - meestal omdat
        het niveau te dicht bij de markt ligt - dan blijft de positie zonder
        doel achter. Dat is minder ernstig dan een ontbrekende stop, want de
        bot sluit zelf zodra de koers het doel raakt, maar het betekent wel dat
        je winst niet beschermd is als Home Assistant uitvalt.
        """
        try:
            positions = await self.venue.positions(symbol)
        except VenueError as err:
            return f"Kon het doel niet nakijken: {err}"

        position = next(
            (p for p in positions if str(p.ticket) == str(ticket)), None
        )
        if position is None or position.take_profit:
            return None

        # Niet elke venue kan een doel achteraf plaatsen. Blind aanroepen laat
        # de hele orderafhandeling crashen op een adapter die de methode niet
        # heeft, en dat is een veel groter probleem dan een ontbrekend doel.
        modify = getattr(self.venue, "modify_target", None)
        if modify is None:
            return (
                "Deze databron kan een doel niet achteraf plaatsen. De bot "
                "sluit zelf op het doel, maar die winst is niet beschermd als "
                "Home Assistant uitvalt."
            )

        try:
            await modify(ticket, take_profit)
        except VenueError as err:
            return (
                f"Het doel staat niet bij de broker en plaatsen mislukte ({err}). "
                "De bot sluit zelf op het doel, maar die winst is niet beschermd "
                "als Home Assistant uitvalt."
            )
        return "Doel achteraf bij de broker geplaatst"

    async def _lookup_unconfirmed(
        self, symbol: str, client_id: str, side: str,
    ) -> tuple[VenuePosition | None, bool]:
        """Zoek een onbevestigde order direct terug: ``(positie, afgewezen)``."""
        for delay in self.lookup_delays:
            if delay:
                await asyncio.sleep(delay)
            gevonden, afgewezen = await self._zoek(symbol, client_id, side)
            if gevonden is not None or afgewezen:
                return gevonden, afgewezen
        return None, False

    async def _zoek(
        self, symbol: str, client_id: str, side: str,
        known_tickets: set[str] | None = None,
    ) -> tuple[VenuePosition | None, bool]:
        """Eén zoekpoging: ``(positie, definitief_afgewezen)``.

        Volgorde: eigen ordernummer in de positielijst; dan de bevestiging
        opnieuw opvragen (IG); dan, als laatste, precies één onbekende
        positie in dezelfde richting.
        """
        try:
            posities = await self.venue.positions(symbol)
        except VenueError:
            return None, False
        for positie in posities:
            if client_id in (getattr(positie, "comment", "") or ""):
                return positie, False

        vraag = getattr(self.venue, "confirm_status", None)
        if vraag is not None:
            status, deal_id = await vraag(client_id)
            if status == "REJECTED":
                return None, True
            if status == "ACCEPTED" and deal_id:
                for positie in posities:
                    if str(positie.ticket) == deal_id:
                        return positie, False

        if known_tickets is not None:
            onbekend = [
                p for p in posities
                if str(p.ticket) not in known_tickets and p.side == side
            ]
            if len(onbekend) == 1:
                return onbekend[0], False
        return None, False

    async def resolve_pending(
        self, known_tickets: set[str],
    ) -> tuple[list[tuple[PendingOrder, VenuePosition]], list[str]]:
        """Zoek openstaande orders terug. Eén poging per order, niet slapen.

        Geeft de teruggevonden orders met hun positie, en notities over wat
        er verder gebeurde (afgewezen, verlopen). Een teruggevonden positie
        krijgt dezelfde stopcontrole als een gewone opening.
        """
        gevonden: list[tuple[PendingOrder, VenuePosition]] = []
        notes: list[str] = []
        nu = datetime.now(timezone.utc)
        for client_id, order in list(self.pending.items()):
            positie, afgewezen = await self._zoek(
                order.symbol, client_id, order.side, known_tickets,
            )
            if positie is not None:
                del self.pending[client_id]
                known_tickets.add(str(positie.ticket))
                if order.stop_loss is not None:
                    beschermd, note = await self._ensure_stop(
                        order.symbol, str(positie.ticket), order.stop_loss,
                    )
                    if note:
                        notes.append(note)
                    if not beschermd:
                        notes.append(
                            f"Teruggevonden positie {positie.ticket} zonder stop; "
                            "wordt direct gesloten"
                        )
                        try:
                            await self.venue.close(str(positie.ticket))
                        except VenueError as err:
                            _LOGGER.critical(
                                "ONBESCHERMDE POSITIE %s kon niet gesloten worden: "
                                "%s. Grijp handmatig in bij je broker.",
                                positie.ticket, err,
                            )
                        continue
                notes.append(
                    f"Onbevestigde order {client_id} teruggevonden als ticket "
                    f"{positie.ticket}"
                )
                gevonden.append((order, positie))
            elif afgewezen:
                del self.pending[client_id]
                notes.append(f"Onbevestigde order {client_id} was afgewezen; niets open")
            elif (nu - order.created).total_seconds() > self.pending_expiry:
                del self.pending[client_id]
                notes.append(
                    f"Onbevestigde order {client_id} na {self.pending_expiry}s niet "
                    "teruggevonden; aangenomen niet uitgevoerd. De afstemming met "
                    "de broker vangt hem als hij toch opduikt."
                )
        return gevonden, notes

    async def _find_by_comment(
        self, symbol: str, client_id: str
    ) -> VenuePosition | None:
        """Zoek een positie op ons eigen ordernummer.

        Dit is de reden dat elke order een uniek nummer meekrijgt: zonder dat
        kun je na een verbroken verbinding niet vaststellen of jouw order is
        uitgevoerd, en is elke keuze - opnieuw sturen of niet - een gok.
        """
        try:
            positions = await self.venue.positions(symbol)
        except VenueError:
            return None
        for position in positions:
            if client_id in (getattr(position, "comment", "") or ""):
                return position
        return None

    # -- bewaking ------------------------------------------------------------ #

    async def audit_positions(self, symbol: str) -> list[str]:
        """Controleer periodiek of elke open positie nog een stop heeft.

        Een stop kan verdwijnen doordat een wijziging half is doorgekomen of
        doordat de broker hem heeft ingetrokken. Dat merk je zonder controle
        pas als het geld weg is.
        """
        problems: list[str] = []
        try:
            positions = await self.venue.positions(symbol)
        except VenueError as err:
            return [f"Kon posities niet ophalen: {err}"]

        for position in positions:
            if position.stop_loss:
                continue
            problems.append(
                f"Positie {position.ticket} ({position.side} {position.units}) "
                "heeft géén stop-loss"
            )
            _LOGGER.error(
                "Onbeschermde positie %s gevonden bij controle", position.ticket
            )
        return problems
