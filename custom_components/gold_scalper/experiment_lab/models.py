"""Datamodel en de ene toestandsmachine van het Experiment Lab.

Alle statusovergangen staan hier. De database dwingt dezelfde lijst af met een
trigger (zie ``storage.py``), zodat een overgang die hier niet staat ook met
rechtstreekse SQL niet te maken is.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    DRAFT = "draft"
    REGISTERED = "registered"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


#: Afgesloten: daarna verandert er niets meer aan het experiment of zijn
#: resultaten. Aantekeningen blijven mogelijk.
TERMINAL = frozenset({
    Status.COMPLETED, Status.FAILED, Status.INTERRUPTED, Status.CANCELLED,
})

#: De enige toegestane overgangen.
#:
#: Annuleren kan tot en met ``running``; daarna is het experiment afgesloten.
#: ``interrupted`` ontstaat alleen uit ``running``: een herstart tijdens de
#: uitvoering. Hervatten bestaat niet - een nieuwe poging is een reproductie.
ALLOWED: dict[Status, frozenset[Status]] = {
    Status.DRAFT: frozenset({Status.REGISTERED, Status.CANCELLED}),
    Status.REGISTERED: frozenset({Status.QUEUED, Status.CANCELLED}),
    Status.QUEUED: frozenset({Status.RUNNING, Status.CANCELLED}),
    Status.RUNNING: frozenset({
        Status.COMPLETED, Status.FAILED, Status.INTERRUPTED, Status.CANCELLED,
    }),
    Status.COMPLETED: frozenset(),
    Status.FAILED: frozenset(),
    Status.INTERRUPTED: frozenset(),
    Status.CANCELLED: frozenset(),
}


class IllegalTransition(ValueError):
    """Een statusovergang die niet in ``ALLOWED`` staat."""


def check_transition(van: Status | str, naar: Status | str) -> None:
    van, naar = Status(van), Status(naar)
    if naar not in ALLOWED[van]:
        raise IllegalTransition(f"{van.value} -> {naar.value} is niet toegestaan")


#: Velden die bij de overgang naar ``registered`` worden vergrendeld: de
#: onderzoeksvraag en hoe hij wordt beoordeeld. Vastgelegd vóórdat er een
#: uitslag bestaat, zodat de vraag niet achteraf naar de uitslag kan schuiven.
LOCKED_AT_REGISTRATION = (
    "name", "type", "hypothesis", "expected_effect", "primary_metric",
    "secondary_metrics", "evaluation_method", "hypothesis_family_id",
    "software_version", "strategy_version", "execution_semantics_version",
    "config_hash", "reproduced_from",
    # Sinds schema 2: een geregistreerd experiment kan niet naar een andere
    # dataset worden omgehangen.
    "dataset_id",
)

#: Wat verplicht ingevuld moet zijn om te registreren.
REQUIRED_FOR_REGISTRATION = (
    "hypothesis", "expected_effect", "primary_metric", "evaluation_method",
    "hypothesis_family_id",
)


class ExperimentType(str, Enum):
    BASELINE = "baseline"
    CHALLENGER = "challenger"
    TIMEFRAME = "timeframe"
    EXECUTION = "execution"
    COST_STRESS = "cost_stress"
    REGIME = "regime"
    WALK_FORWARD = "walk_forward"
    OUT_OF_SAMPLE = "out_of_sample"
    SHADOW = "shadow"


def canonical_json(waarde) -> str:
    """Vaste serialisatie: dezelfde inhoud geeft altijd dezelfde tekst.

    Sleutels gesorteerd, geen spaties, geen ASCII-omzetting. Een getal wordt
    geschreven zoals Python het representeert; ``NaN`` en oneindig worden
    geweigerd, omdat die geen eenduidige tekstvorm hebben.
    """
    return json.dumps(
        waarde, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


def config_hash(config: dict) -> str:
    """SHA-256 over de canonieke vorm van een configuratie."""
    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class Experiment:
    id: int | None = None
    name: str = ""
    description: str = ""
    type: str = ExperimentType.BASELINE.value
    status: str = Status.DRAFT.value

    hypothesis: str = ""
    expected_effect: str = ""
    primary_metric: str = ""
    secondary_metrics: list = field(default_factory=list)
    evaluation_method: str = ""
    hypothesis_family_id: str = ""

    software_version: str = ""
    strategy_version: str = ""
    execution_semantics_version: int | None = None
    config_hash: str = ""

    created_at: str = ""
    registered_at: str | None = None
    locked_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    reproduced_from: int | None = None
    error: str | None = None
    #: De snapshot waarop het experiment rust. Alleen te wijzigen als draft.
    dataset_id: int | None = None
