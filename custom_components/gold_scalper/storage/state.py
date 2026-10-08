"""Toestand die een herstart moet overleven.

Twee dingen stonden tot nu toe alleen in het geheugen, en dat waren precies de
twee die er het meest toe doen.

**De hoofdschakelaar.** Wie hem aanzette en daarna Home Assistant herstartte -
voor een update, een herconfiguratie, wat dan ook - kwam terug met een bot die
stilstond zonder dat iets dat meldde. Dat is niet alleen onhandig maar ook
misleidend: je gaat ervan uit dat er gehandeld wordt.

**De noodstop.** Dit is de ernstiger van de twee. Een noodstop wordt gezet
omdat er iets grondig mis is: dagverlies overschreden, equity onder de
ondergrens, dataverbinding dood. Als een herstart die toestand wist, is de
noodrem precies zo betrouwbaar als de vraag of iemand toevallig herstart heeft.
Een bot die na een verliesdag vanzelf weer begint omdat er een update
langskwam, is gevaarlijker dan een bot zonder noodrem, want je vertrouwt op
bescherming die er niet is.

Opgeslagen in ``.storage/gold_scalper_state``, per config entry.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "gold_scalper_state"
STORAGE_VERSION = 1


@dataclass(slots=True)
class RuntimeState:
    """Wat er bewaard blijft tussen herstarts."""

    enabled: bool = False
    halted: bool = False
    halt_reason: str | None = None
    #: Verliesreeks blijft staan: drie verliezers gevolgd door een herstart
    #: zijn nog steeds drie verliezers.
    consecutive_losses: int = 0
    #: Handelsdag en dagstartsaldo, zodat de dagverlieslimiet niet reset bij
    #: een herstart halverwege de dag.
    day: str | None = None
    day_start_balance: float | None = None
    trades_today: int = 0
    #: Handmatige hervattingen vandaag; begrensd zodat de daglimiet geen
    #: suggestie wordt.
    resumes_today: int = 0
    run_id: int | None = None
    #: Laatst bekende wisselkoers van instrument- naar accountvaluta.
    #:
    #: Zonder dit begon elke herstart zonder koers. De koers wordt alleen
    #: afgeleid uit een gecorrigeerde trade, dus tot de eerstvolgende correctie
    #: werd de positiegrootte niet omgerekend - ongeveer acht procent te klein -
    #: en bleef de kolom in accountvaluta leeg.
    conversion_rate: float | None = None
    #: Voorzichtige koers voor de positiegrootte (biedkant van EUR/USD).
    conversion_risk_rate: float | None = None
    #: Wanneer de koers gold, in UTC. Zonder tijdstip is hij niet bruikbaar
    #: voor een nieuwe positie.
    conversion_rate_at: str | None = None
    #: Meldde de bron bij de laatste ophaling een gesloten markt?
    conversion_market_closed: bool | None = None
    #: Recentste koers waartegen de broker een verlies omrekende, en wanneer.
    conversion_loss_rate: float | None = None
    conversion_loss_rate_at: str | None = None
    #: Zelfgebouwde bars, zodat de opwarmfase een herstart overleeft. Zonder
    #: dit kost elke update opnieuw uren voordat de analyse iets kan zeggen.
    bars: dict | None = None
    #: Tickets waarvan al een deel is afgeroomd. Zonder dit wordt na een
    #: herstart dezelfde positie opnieuw gehalveerd, en bij herhaling tot niets.
    partial_taken: list | None = None

    # -- 1.7.5: herstartbestendigheid --------------------------------------- #
    #
    # Alles hieronder is optioneel: een toestand van een oudere versie heeft
    # deze velden niet en laadt gewoon, met de standaardwaarde.

    #: Uiterste mee- en tegenbeweging per open ticket (``ticket -> {mfe, mae}``).
    #: Zonder dit begon de meting na een herstart opnieuw bij nul en kreeg de
    #: verliesanalyse een kleinere beweging dan er werkelijk was.
    excursions: dict | None = None
    #: Hetzelfde voor open papertrades (``trade-id -> {mfe, mae}``); die worden
    #: pas bij het sluiten in de database gezet.
    paper_excursions: dict | None = None
    #: Einde van een pauze na een verliesreeks, ISO in UTC. Zonder dit hief
    #: een herstart de pauze op.
    paused_until: str | None = None
    #: Laatste risicogebeurtenissen (pauze, noodstop), voor de sensor.
    risk_triggered: list | None = None
    #: Moment van de laatste instap (epoch-seconden). De strategie wacht een
    #: minimale tijd tussen twee instappen; na een herstart was dat nul.
    last_entry_ts: float | None = None
    #: Laatst door de broker bevestigde accountvaluta. Valt de opvraging bij
    #: het opstarten weg, dan geldt deze en niet de standaard "USD".
    account_currency: str | None = None
    #: Onbevestigde orders, minimaal (zie ``SafeExecutor.export_pending``).
    pending_orders: list | None = None
    #: Verse schattingen die nog bij de broker worden nagevraagd.
    herkansingen: dict | None = None
    #: Controlebevindingen die al gemeld zijn.
    audit_gemeld: list | None = None
    #: Onderdrukking en uurbericht van de meldingen (``Notifier.export``).
    notify_sent: dict | None = None
    #: 1.7.7: saldosprongbewaking (``SaldoSprongBewaker.export``): de laatst
    #: betrouwbare referentie en een eventuele actieve sprong. Zonder dit zou
    #: een herstart tijdens een sprong de sprongwaarde als referentie nemen.
    saldosprong: dict | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class StateStore:
    """Leest en schrijft de toestand per config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._entry_id = entry_id
        self._all: dict[str, Any] = {}

    async def async_load(self) -> RuntimeState:
        self._all = await self._store.async_load() or {}
        raw = self._all.get(self._entry_id) or {}
        fields = {f for f in RuntimeState.__dataclass_fields__}
        state = RuntimeState(**{k: v for k, v in raw.items() if k in fields})

        if state.halted:
            _LOGGER.warning(
                "Noodstop uit een eerdere sessie blijft actief: %s. "
                "Gebruik gold_scalper.resume nadat je de oorzaak hebt vastgesteld.",
                state.halt_reason,
            )
        elif state.enabled:
            _LOGGER.info("Handel was ingeschakeld vóór de herstart; hervat.")
        return state

    async def async_save(self, state: RuntimeState) -> None:
        self._all[self._entry_id] = state.as_dict()
        await self._store.async_save(self._all)

    async def async_remove(self) -> None:
        """Opruimen als de entry verwijderd wordt."""
        self._all.pop(self._entry_id, None)
        await self._store.async_save(self._all)


RESULTS_KEY = "gold_scalper_results"


class ResultsStore:
    """Uitkomsten die geen handelstoestand zijn maar een herstart moeten overleven.

    1.7.5. Backtest, validatie, indicatorlab en de waarneming van de
    sluitingsuren stonden alleen in het geheugen: na een herstart waren ze weg
    en moest een backtest van minuten opnieuw, en begon de waarneming van de
    sluitingsuren weer bij nul. Een eigen bestand, los van de toestand: dit is
    meting, geen noodrem, en hoort die niet te kunnen beschadigen.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, RESULTS_KEY)
        self._entry_id = entry_id
        self._all: dict[str, Any] = {}

    async def async_load(self) -> dict[str, Any]:
        try:
            self._all = await self._store.async_load() or {}
        except Exception as err:  # noqa: BLE001 - meting mag het opstarten niet breken
            _LOGGER.warning("Bewaarde uitkomsten niet te lezen: %s", err)
            self._all = {}
        raw = self._all.get(self._entry_id)
        return dict(raw) if isinstance(raw, dict) else {}

    async def async_save(self, data: dict[str, Any]) -> None:
        self._all[self._entry_id] = data
        await self._store.async_save(self._all)

    async def async_remove(self) -> None:
        self._all.pop(self._entry_id, None)
        await self._store.async_save(self._all)
