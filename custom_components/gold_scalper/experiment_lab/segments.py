"""Chronologische segmenten: TRAIN, VALIDATION en TEST.

Grenssemantiek (``SEGMENT_SCHEMA_VERSION = 1``)
----------------------------------------------

Alle tijden zijn gehele UTC-seconden (``time_unit = unix_seconds_utc``); een
bar wordt aangeduid met het tijdstip waarop hij **begint**.

* **Evaluatie-interval** ``[start_ts, end_ts)``, halfopen: een bar hoort bij
  het segment als ``start_ts <= ts < end_ts``. Een bar op ``end_ts`` hoort bij
  het volgende segment, nooit bij beide.
* **Opwarmen** ``[warmup_start_ts, start_ts)``: de ``STRATEGY_WINDOW_BARS``
  bars vóór het segment - hetzelfde venster als live. Ze voeden de
  indicatoren, maar openen geen positie, tellen niet als beoordeling en komen
  in geen enkele metriek voor. Een bar mag voor meerdere segmenten opwarmdata
  zijn, maar telt in hooguit één evaluatiepopulatie.
* **Afkapmoment** ``open_cutoff_ts = end_ts - max_hold_seconds - bar_seconds``:
  vanaf dat moment geen nieuwe positie. ``max_hold_seconds`` wordt vóór de
  uitvoering vastgelegd, niet achteraf gemeten. Er gaat één barlengte extra af,
  omdat de backtest een tijdslimiet pas op de eerstvolgende bar kan uitvoeren.
* **Geen bar van na het segment**: een segment krijgt nooit bars op of na
  ``end_ts``, ook niet voor de exit van een open positie. Zo kan geen
  VALIDATION- of TEST-bar in een eerder segment lekken. Staat een positie bij
  het einde nog open, dan sluit ze op de slotkoers van de laatste segmentbar,
  met reden ``segment_end``, en heet ze ``cross_boundary``. Ze blijft bij haar
  openingssegment.
* **Toeschrijving**: een trade hoort bij het segment waarin ze opent. De
  handelsdag blijft die van de sluiting (Europe/Amsterdam); tijden blijven UTC.

Opwarmstatus
------------

* ``FULL_WARMUP``: minstens ``STRATEGY_WINDOW_BARS`` bars vóór het segment.
* ``PARTIAL_WARMUP``: minder, maar minstens ``WARMUP_BARS`` - het minimum
  waarmee de backtestmotor beoordeelt. Toegestaan, en zichtbaar.
* ``INSUFFICIENT_WARMUP``: minder dan dat. Zo'n plan wordt geweigerd.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass

from ..analysis.backtest import WARMUP_BARS
from ..const import STRATEGY_WINDOW_BARS
from ..strategy.aggregator import BAR_SECONDS
from .models import canonical_json, config_hash

SEGMENT_SCHEMA_VERSION = 1
KINDS = ("TRAIN", "VALIDATION", "TEST")
TIME_UNIT = "unix_seconds_utc"
BOUNDARY_SEMANTICS = "[start_ts, end_ts) halfopen; bar op end_ts hoort bij het volgende segment"
WARMUP_RULE = f"de {STRATEGY_WINDOW_BARS} bars voor start_ts (STRATEGY_WINDOW_BARS)"
OPEN_CUTOFF_RULE = "open_cutoff_ts = end_ts - max_hold_seconds - bar_seconds"

FULL, PARTIAL, INSUFFICIENT = "FULL_WARMUP", "PARTIAL_WARMUP", "INSUFFICIENT_WARMUP"


class SegmentPlanError(ValueError):
    """Een segmentplan dat niet deugt. Er wordt dan niets vastgelegd."""


@dataclass(frozen=True, slots=True)
class Segment:
    kind: str
    sequence_number: int
    start_ts: int
    end_ts: int
    warmup_start_ts: int
    open_cutoff_ts: int
    warmup_bars: int
    warmup_status: str

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__slots__}


@dataclass(frozen=True, slots=True)
class SegmentPlan:
    dataset_id: int
    dataset_hash: str
    timeframe: str
    bar_seconds: int
    max_hold_seconds: int
    segments: tuple[Segment, ...]
    segment_schema_version: int = SEGMENT_SCHEMA_VERSION

    def as_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id, "dataset_hash": self.dataset_hash,
            "timeframe": self.timeframe, "bar_seconds": self.bar_seconds,
            "max_hold_seconds": self.max_hold_seconds,
            "segment_schema_version": self.segment_schema_version,
            "time_unit": TIME_UNIT, "boundary_semantics": BOUNDARY_SEMANTICS,
            "warmup_rule": WARMUP_RULE, "open_cutoff_rule": OPEN_CUTOFF_RULE,
            "segments": [s.as_dict() for s in self.segments],
        }

    @property
    def plan_hash(self) -> str:
        """Identiteit van het plan: dataset, grenzen, regels en versie."""
        return config_hash(self.as_dict())


def warmup_status(bars: int) -> str:
    if bars >= STRATEGY_WINDOW_BARS:
        return FULL
    if bars >= WARMUP_BARS:
        return PARTIAL
    return INSUFFICIENT


#: Gedwongen sluiting aan het segmenteinde (fase 5). Een onderzoeksmaatregel
#: tegen lekken, geen normale uitvoering: vastgelegd bij elk segmentresultaat.
FORCED_EXIT_POLICY = "CLOSE_AT_LAST_SEGMENT_BAR"
FORCED_EXIT_PRICE_RULE = (
    "slotkoers van de laatste bar voor end_ts; long verkoopt tegen bied (midden - "
    "halve spread), short koopt tegen laat (midden + halve spread)"
)
FORCED_EXIT_COST_RULE = "dezelfde spread en slippage als elke andere exit; geen extra kosten"
FORCED_EXIT_FIDELITY = (
    "gedwongen sluiting: de positie zou in werkelijkheid hebben doorgelopen. Een "
    "segment met veel van deze sluitingen is niet representatief voor normale uitvoering."
)


def make_segment(soort: str, volgnr: int, start: int, einde: int, bar_ts: list[int],
                 lengte: int, max_hold_seconds: int) -> "Segment":
    """Eén segment met opwarmen en afkapmoment. De enige plek waar die regels staan."""
    start, einde = int(start), int(einde)
    if not start < einde:
        raise SegmentPlanError(f"{soort}: start moet voor einde liggen")
    idx = bisect.bisect_left(bar_ts, start)
    if not [t for t in bar_ts[idx:idx + 1] if t < einde]:
        raise SegmentPlanError(f"{soort}: geen enkele bar in [{start}, {einde})")
    opwarm_idx = max(0, idx - STRATEGY_WINDOW_BARS)
    opwarm_bars = idx - opwarm_idx
    status = warmup_status(opwarm_bars)
    if status == INSUFFICIENT:
        raise SegmentPlanError(
            f"{soort}: {opwarm_bars} bars opwarmdata, minder dan de {WARMUP_BARS} "
            "waarmee de backtest beoordeelt"
        )
    afkap = einde - max_hold_seconds - lengte
    if afkap <= start:
        raise SegmentPlanError(f"{soort}: te kort - het afkapmoment ligt niet na de start")
    return Segment(
        kind=soort, sequence_number=volgnr, start_ts=start, end_ts=einde,
        warmup_start_ts=bar_ts[opwarm_idx] if opwarm_bars else start,
        open_cutoff_ts=afkap, warmup_bars=opwarm_bars, warmup_status=status,
    )


def build_plan(
    dataset_id: int, dataset_hash: str, timeframe: str, bar_ts: list[int],
    grenzen: dict[str, tuple[int, int]], max_hold_seconds: int,
) -> SegmentPlan:
    """Bouw en valideer een plan. ``grenzen`` geeft per soort ``(start, einde)``.

    ``bar_ts`` zijn de tijdstippen van de verzegelde dataset, oplopend. Het
    plan wordt volledig gecontroleerd voordat het bestaat.
    """
    if timeframe not in BAR_SECONDS:
        raise SegmentPlanError(f"onbekend tijdsframe: {timeframe}")
    if set(grenzen) != set(KINDS):
        raise SegmentPlanError(f"een plan heeft precies {', '.join(KINDS)}")
    if not isinstance(max_hold_seconds, int) or max_hold_seconds <= 0:
        raise SegmentPlanError("max_hold_seconds moet een positief geheel getal zijn")
    if list(bar_ts) != sorted(set(bar_ts)):
        raise SegmentPlanError("de datasettijdstippen zijn niet strikt oplopend")
    lengte = BAR_SECONDS[timeframe]

    segmenten = [
        make_segment(soort, volgnr, *grenzen[soort], bar_ts, lengte, max_hold_seconds)
        for volgnr, soort in enumerate(KINDS, start=1)
    ]

    for eerder, later in zip(segmenten, segmenten[1:]):
        if eerder.end_ts > later.start_ts:
            raise SegmentPlanError(
                f"{later.kind} begint voor {eerder.kind} eindigt: segmenten mogen "
                "niet overlappen en moeten chronologisch zijn"
            )
    return SegmentPlan(dataset_id, dataset_hash, timeframe, lengte,
                       max_hold_seconds, tuple(segmenten))


def normalize_family_id(tekst: str) -> str:
    """Een hypothesefamilie deterministisch genormaliseerd.

    NFKC, kleine letters, accenten weg, elke reeks niet-alfanumerieke tekens
    wordt één koppelteken. "Tijdslimiet  2 bars" en "tijdslimiet-2-bars" zijn
    dezelfde familie; een andere experimentnaam verandert daar niets aan.
    """
    if not isinstance(tekst, str):
        raise ValueError("hypothesefamilie moet tekst zijn")
    genormaliseerd = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", tekst))
    zonder_accent = "".join(c for c in genormaliseerd if not unicodedata.combining(c))
    schoon = re.sub(r"[^a-z0-9]+", "-", zonder_accent.casefold()).strip("-")
    if not schoon:
        raise ValueError("hypothesefamilie is leeg na normalisatie")
    return schoon


def plan_canonical(plan: SegmentPlan) -> str:
    return canonical_json(plan.as_dict())
