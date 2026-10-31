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

from datetime import date, datetime, timezone

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
    #: 2.24.0 (L-GS-029): handelsdag (ISO) waarop de noodstop afging. Een
    #: dagverlies-noodstop van een eerdere handelsdag wordt bij het opstarten
    #: niet teruggezet.
    halt_day: str | None = None
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


def _gedeeld(hass: HomeAssistant, sleutel: str) -> dict:
    """2.18.0: één Store en één inhoud per bestand, gedeeld door alle entries.

    Elke entry hield een eigen kopie van het hele bestand, gelezen bij het
    opstarten, en schreef bij elke wijziging die hele kopie terug. Met twee
    entries (IG en Pepperstone) overschreef de ene zo de nieuwere toestand van
    de andere met wat er bij het opstarten stond; met een Bitvavo-mand van
    twintig markten zou dat bij elke cyclus gebeuren.
    """
    data = getattr(hass, "data", None)
    if not isinstance(data, dict):
        return {"store": Store(hass, STORAGE_VERSION, sleutel), "all": None}
    pool = data.setdefault("gold_scalper_gedeelde_stores", {})
    if sleutel not in pool:
        pool[sleutel] = {"store": Store(hass, STORAGE_VERSION, sleutel), "all": None}
    return pool[sleutel]


async def _lees_gedeeld(gedeeld: dict) -> dict:
    """Het bestand lezen in de gedeelde inhoud. Elke wijziging wordt meteen
    geschreven, dus het bestand is de actuele stand; de inhoud wordt ter
    plekke bijgewerkt zodat alle entries hetzelfde object blijven delen."""
    inhoud = await gedeeld["store"].async_load() or {}
    if gedeeld["all"] is None:
        gedeeld["all"] = {}
    gedeeld["all"].clear()
    gedeeld["all"].update(inhoud)
    return gedeeld["all"]


async def _schrijf_gedeeld(gedeeld: dict) -> None:
    # Een ondiepe kopie: HA schrijft het bestand mogelijk pas na een andere
    # wijziging in hetzelfde dict.
    await gedeeld["store"].async_save(dict(gedeeld["all"] or {}))


async def _verwijder_gedeeld(gedeeld: dict, entry_id: str) -> None:
    """De entry en zijn mandleden (``<entry_id>_<markt>``) uit het bestand
    halen, zonder de andere entries te raken."""
    alles = await _lees_gedeeld(gedeeld)
    for sleutel in [k for k in alles if k == entry_id or k.startswith(f"{entry_id}_")]:
        alles.pop(sleutel, None)
    await _schrijf_gedeeld(gedeeld)


def is_dagverlies_noodstop(reden: str | None) -> bool:
    """2.24.0 (L-GS-029): een noodstop op de dagverlieslimiet (zie
    ``RiskManager.can_open``: "dagverlies x% bereikt de limiet ...")."""
    return str(reden or "").strip().lower().startswith("dagverlies")


def is_mandvloer_noodstop(reden: str | None) -> bool:
    """2.27.0 (L-GS-035): een noodstop op de vloer van de hele Bitvavo-mand
    (zie ``RiskManager.toets_mandvloer``: "equity van de mand ... onder de
    ondergrens ...")."""
    return str(reden or "").strip().lower().startswith("equity van de mand")


def noodstop_dag(state: RuntimeState) -> date | None:
    """2.24.0 (L-GS-029): de handelsdag waarop een bewaarde noodstop afging.

    Eerst het veld ``halt_day`` (vanaf 2.24.0). Een toestand van een oudere
    versie heeft dat niet; dan de laatste ``NOODSTOP``-regel met dezelfde reden
    uit de bewaarde risicogebeurtenissen (die heeft een tijdstip). Geen van
    beide: onbekend. ``state.day`` telt niet: die rolt ook door terwijl de
    noodstop staat en zegt dus niets over wanneer hij afging.
    """
    from ..timeutil import trading_day

    if state.halt_day:
        try:
            return date.fromisoformat(str(state.halt_day))
        except ValueError:
            pass
    reden = str(state.halt_reason or "")
    for regel in reversed(list(state.risk_triggered or [])):
        tekst = str(regel)
        tijd, sep, rest = tekst.partition(" NOODSTOP: ")
        if not sep or (reden and rest.strip() != reden.strip()):
            continue
        try:
            moment = datetime.fromisoformat(tijd.strip())
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return trading_day(moment)
    return None


def verlopen_dagverlies_noodstop(state: RuntimeState, vandaag: date) -> bool:
    """2.24.0 (L-GS-029): is dit een dagverlies-noodstop van een eerdere
    handelsdag? Alleen dan wordt hij bij het opstarten niet teruggezet.

    Andere noodstops (equity onder de vloer, dode data, trade-limiet) blijven
    altijd staan. Een dagverlies-noodstop zonder bekende dag blijft staan als
    de bewaarde handelsdag vandaag is (voorzichtig); anders vervalt hij - de
    dagverliestoets rekent bij de eerste instap opnieuw vanaf het bewaarde
    dagstartsaldo, dus een verlies van vandaag zet hem meteen terug.
    """
    if not state.halted or not is_dagverlies_noodstop(state.halt_reason):
        return False
    dag = noodstop_dag(state)
    if dag is None:
        try:
            dag = date.fromisoformat(str(state.day)) if state.day else None
        except ValueError:
            dag = None
        if dag is None:
            return True
    return dag < vandaag


class StateStore:
    """Leest en schrijft de toestand per config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._gedeeld = _gedeeld(hass, STORAGE_KEY)
        self._store: Store = self._gedeeld["store"]
        self._entry_id = entry_id
        self._all: dict[str, Any] = {}
        self.vervallen_noodstop: str | None = None

    @staticmethod
    def _nu() -> datetime:
        return datetime.now(timezone.utc)

    async def async_load(self, mandlid: bool = False) -> RuntimeState:
        self._all = await _lees_gedeeld(self._gedeeld)
        raw = self._all.get(self._entry_id) or {}
        fields = {f for f in RuntimeState.__dataclass_fields__}
        state = RuntimeState(**{k: v for k, v in raw.items() if k in fields})

        # 2.24.0 (L-GS-029): een dagverlies-noodstop van een eerdere handelsdag
        # komt niet terug (na elke herstart stonden PEPE-EUR en BILL-EUR weer
        # stil met "uit een eerdere sessie"). Meteen gewist in het bestand,
        # zodat hij ook bij een volgende start niet terugkomt.
        self.vervallen_noodstop: str | None = None
        from ..timeutil import trading_day

        vandaag = trading_day(self._nu())
        if verlopen_dagverlies_noodstop(state, vandaag):
            dag = noodstop_dag(state)
            self.vervallen_noodstop = state.halt_reason
            _LOGGER.info(
                "Dagverlies-noodstop van een eerdere handelsdag (%s) niet "
                "teruggezet (%s): %s", dag.isoformat() if dag else "onbekend",
                self._entry_id, state.halt_reason,
            )
            state.halted = False
            state.halt_reason = None
            state.halt_day = None
            try:
                await self.async_save(state)
            except Exception:  # noqa: BLE001 - de coordinator bewaart later opnieuw
                _LOGGER.debug("Gewiste noodstop niet meteen bewaard", exc_info=True)
        elif mandlid and state.halted and is_mandvloer_noodstop(state.halt_reason):
            # 2.27.0 (L-GS-035, akkoord 31-10): de vloer van de hele mand wordt
            # elke cyclus opnieuw getoetst, door elk lid, tegen de huidige
            # startbalans. Een bewaarde mandvloer-noodstop van een lid hoeft
            # dus niet terug: ligt de mand nog onder de vloer, dan gaat hij in
            # de eerste cyclus meteen weer aan. FARTCOIN, LTC, NEAR en PUMP
            # bleven na elke herstart staan op "3.653 onder 5.000" terwijl de
            # vloer sinds 29-10 500.000 is en de mand op 993.686 staat; buiten
            # de mand waren ze ook niet met gold_scalper.resume te bereiken.
            self.vervallen_noodstop = state.halt_reason
            _LOGGER.info(
                "Mandvloer-noodstop niet teruggezet (%s): %s. De vloer van de "
                "mand wordt in de eerste cyclus opnieuw getoetst.",
                self._entry_id, state.halt_reason,
            )
            state.halted = False
            state.halt_reason = None
            state.halt_day = None
            try:
                await self.async_save(state)
            except Exception:  # noqa: BLE001 - de coordinator bewaart later opnieuw
                _LOGGER.debug("Gewiste noodstop niet meteen bewaard", exc_info=True)
        elif state.halted and not state.halt_day:
            dag = noodstop_dag(state)
            if dag is not None:
                state.halt_day = dag.isoformat()

        if state.halted:
            _LOGGER.warning(
                "Noodstop uit een eerdere sessie blijft actief (%s): %s. "
                "Gebruik gold_scalper.resume nadat je de oorzaak hebt vastgesteld.",
                # 2.21.3 (L-GS-022): welke markt; bij de mand eindigt de
                # entry-id op _<markt> (23-10 15:18 stond er geen markt bij)
                self._entry_id,
                state.halt_reason,
            )
        elif state.enabled:
            _LOGGER.info("Handel was ingeschakeld vóór de herstart; hervat.")
        return state

    async def async_save(self, state: RuntimeState) -> None:
        if self._gedeeld["all"] is None:
            await _lees_gedeeld(self._gedeeld)
        self._all = self._gedeeld["all"]
        self._all[self._entry_id] = state.as_dict()
        await _schrijf_gedeeld(self._gedeeld)

    async def async_remove(self) -> None:
        """Opruimen als de entry verwijderd wordt (nooit de andere entries)."""
        await _verwijder_gedeeld(self._gedeeld, self._entry_id)


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
        self._gedeeld = _gedeeld(hass, RESULTS_KEY)
        self._store: Store = self._gedeeld["store"]
        self._entry_id = entry_id
        self._all: dict[str, Any] = {}

    async def async_load(self) -> dict[str, Any]:
        try:
            self._all = await _lees_gedeeld(self._gedeeld)
        except Exception as err:  # noqa: BLE001 - meting mag het opstarten niet breken
            _LOGGER.warning("Bewaarde uitkomsten niet te lezen: %s", err)
            self._onleesbaar = True
            return {}
        raw = self._all.get(self._entry_id)
        return dict(raw) if isinstance(raw, dict) else {}

    async def async_save(self, data: dict[str, Any]) -> None:
        if getattr(self, "_onleesbaar", False):
            # Niet schrijven over een bestand dat niet te lezen was: dat zou de
            # uitkomsten van alle andere entries wissen.
            return
        if self._gedeeld["all"] is None:
            await _lees_gedeeld(self._gedeeld)
        self._all = self._gedeeld["all"]
        self._all[self._entry_id] = data
        await _schrijf_gedeeld(self._gedeeld)

    async def async_remove(self) -> None:
        await _verwijder_gedeeld(self._gedeeld, self._entry_id)
