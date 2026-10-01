"""Walk-forward: vensters, kandidaten, selectie - pure logica, zonder opslag.

Twee modi, expliciet:

* ``CANDIDATE_SELECTION_WALK_FORWARD`` - per venster alle vooraf geregistreerde
  kandidaten op TRAIN, dan de vooraf vastgelegde selectieregel, eventueel een
  bevestiging op VALIDATION van **alleen** de gekozen kandidaat, en daarna
  alleen die kandidaat op TEST. TEST speelt nooit mee in de keuze.
* ``SEQUENTIAL_OOS`` - één vooraf geregistreerde configuratie, opeenvolgende
  TEST-vensters, geen selectie. Hier wordt niets getraind of gekozen.

Grenzen: halfopen ``[start_ts, end_ts)``, en per segment dezelfde opwarm- en
afkapregels als in fase 5 (``segments.make_segment``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .metrics import DEFINITIONS
from .models import canonical_json
from .segments import Segment, make_segment

WALK_FORWARD_SCHEMA_VERSION = 1
SELECTION_RULE_VERSION = 1

CANDIDATE_SELECTION = "CANDIDATE_SELECTION_WALK_FORWARD"
SEQUENTIAL_OOS = "SEQUENTIAL_OOS"
MODES = (CANDIDATE_SELECTION, SEQUENTIAL_OOS)
ROLLING, EXPANDING = "ROLLING", "EXPANDING"
TRAIN_ONLY = "TRAIN_ONLY_SELECTION"
TRAIN_THEN_VALIDATION = "TRAIN_THEN_VALIDATION_CONFIRMATION"
DISQUALIFY, NO_SELECTION_POLICY = "DISQUALIFY", "NO_SELECTION"
MAXIMIZE, MINIMIZE = "MAXIMIZE", "MINIMIZE"
#: Laatste, technische tie-break: de laagste configuratiehash. Alleen als die
#: vooraf in de regel is opgenomen - nooit stil toegevoegd.
CONFIG_HASH_TIEBREAK = "config_hash"

SELECTED, NO_SELECTION = "SELECTED", "NO_SELECTION"
PASSED, FAILED, NOT_REQUIRED = "PASSED", "FAILED", "NOT_REQUIRED"

# --------------------------------------------------------------------------- #
# vensterstatussen
# --------------------------------------------------------------------------- #

WINDOW_TERMINAL_OK = ("COMPLETED", "NO_SELECTION", "VALIDATION_REJECTED")
WINDOW_TERMINAL = WINDOW_TERMINAL_OK + ("FAILED", "INTERRUPTED", "CANCELLED")
_AFBREKEN = ("FAILED", "INTERRUPTED", "CANCELLED")

#: De enige toegestane overgangen per venster. TESTING betekent: TEST wordt
#: uitgevoerd - niet dat TEST is geopend.
WINDOW_ALLOWED: dict[str, tuple[str, ...]] = {
    "PENDING": ("TRAINING", "TESTING") + _AFBREKEN,        # TESTING alleen bij SEQUENTIAL_OOS
    "TRAINING": ("SELECTING",) + _AFBREKEN,
    "SELECTING": ("VALIDATING", "TESTING", "NO_SELECTION") + _AFBREKEN,
    "VALIDATING": ("TESTING", "VALIDATION_REJECTED") + _AFBREKEN,
    "TESTING": ("COMPLETED",) + _AFBREKEN,
    **{s: () for s in WINDOW_TERMINAL},
}


class WalkForwardError(ValueError):
    """Een plan, kandidatenset of selectieregel die niet deugt."""


# --------------------------------------------------------------------------- #
# selectieregel
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SelectionRule:
    primary_metric: str
    direction: str
    tie_break: tuple = ()                 # ((metriek, richting), ...) of CONFIG_HASH_TIEBREAK
    validation_policy: str = TRAIN_ONLY
    missing_metric_policy: str = DISQUALIFY
    minimum_required_status: str = "VALID"
    #: Bij TRAIN_THEN_VALIDATION: {"metric", "operator", "threshold"}.
    validation_condition: dict | None = None

    def check(self) -> None:
        if self.primary_metric not in DEFINITIONS:
            raise WalkForwardError(f"onbekende primaire metriek: {self.primary_metric}")
        if self.direction not in (MAXIMIZE, MINIMIZE):
            raise WalkForwardError("selection_direction is MAXIMIZE of MINIMIZE")
        if self.missing_metric_policy not in (DISQUALIFY, NO_SELECTION_POLICY):
            raise WalkForwardError("missing_metric_policy is DISQUALIFY of NO_SELECTION")
        if self.minimum_required_status != "VALID":
            raise WalkForwardError("in versie 1 is alleen VALID toegestaan")
        for regel in self.tie_break:
            if regel == CONFIG_HASH_TIEBREAK:
                continue
            metriek, richting = regel
            if metriek not in DEFINITIONS or richting not in (MAXIMIZE, MINIMIZE):
                raise WalkForwardError(f"ongeldige tie-break: {regel}")
        if CONFIG_HASH_TIEBREAK in self.tie_break and self.tie_break[-1] != CONFIG_HASH_TIEBREAK:
            raise WalkForwardError("de configuratiehash kan alleen de laatste tie-break zijn")
        if self.validation_policy == TRAIN_THEN_VALIDATION:
            v = self.validation_condition or {}
            if v.get("metric") not in DEFINITIONS or v.get("operator") not in (">", ">=", "<", "<=") \
                    or not isinstance(v.get("threshold"), (int, float)):
                raise WalkForwardError("TRAIN_THEN_VALIDATION vraagt een volledige validatievoorwaarde")
        elif self.validation_policy != TRAIN_ONLY:
            raise WalkForwardError(f"onbekend validatiebeleid: {self.validation_policy}")

    def as_dict(self) -> dict:
        return {
            "selection_rule_version": SELECTION_RULE_VERSION,
            "primary_metric": self.primary_metric, "direction": self.direction,
            "tie_break": [list(t) if t != CONFIG_HASH_TIEBREAK else t for t in self.tie_break],
            "validation_policy": self.validation_policy,
            "missing_metric_policy": self.missing_metric_policy,
            "minimum_required_status": self.minimum_required_status,
            "validation_condition": self.validation_condition,
        }


def candidate_set_hash(kandidaten: list[tuple[str, str]]) -> str:
    """Hash over (label, configuratiehash), canoniek gesorteerd: de volgorde van
    invoer verandert hem niet, een andere configuratie wel."""
    hashes = [h for _, h in kandidaten]
    if len(set(hashes)) != len(hashes):
        raise WalkForwardError("twee kandidaten met dezelfde configuratie")
    rijen = sorted([h, label] for label, h in kandidaten)
    return hashlib.sha256(canonical_json(rijen).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# selectie
# --------------------------------------------------------------------------- #

@dataclass
class Selection:
    status: str
    selected: str | None = None                     # candidate-sleutel
    reason: str = ""
    evaluations: list = field(default_factory=list)
    tie_break_values: dict = field(default_factory=dict)
    selected_metric_value: float | None = None
    selected_metric_status: str | None = None


def _gericht(waarde: float, richting: str) -> float:
    return -waarde if richting == MAXIMIZE else waarde


def select(rule: SelectionRule, kandidaten: dict[str, dict], config_hashes: dict[str, str]) -> Selection:
    """Pas de vooraf vastgelegde regel toe op TRAIN-metrieken.

    ``kandidaten``: sleutel -> {metric_name: {"value", "calculation_status"}}.
    Uitsluitend TRAIN-metrieken; deze functie krijgt nooit iets anders.
    Kiest nooit willekeurig: zonder unieke keuze wordt het NO_SELECTION.
    """
    rule.check()
    evals, geschikt = [], []
    for sleutel in sorted(kandidaten):
        m = kandidaten[sleutel].get(rule.primary_metric) or {}
        geldig = m.get("calculation_status") == "VALID" and m.get("value") is not None
        evals.append({"candidate": sleutel, "primary_metric_value": m.get("value") if geldig else None,
                      "primary_metric_status": m.get("calculation_status", "UNKNOWN_INPUT"),
                      "eligible": geldig,
                      "disqualification_reason": None if geldig else
                      f"{rule.primary_metric} is {m.get('calculation_status', 'afwezig')}",
                      "rank_position": None})
        if geldig:
            geschikt.append(sleutel)
        elif rule.missing_metric_policy == NO_SELECTION_POLICY:
            return Selection(NO_SELECTION, reason=f"{sleutel}: primaire metriek niet geldig "
                             "(missing_metric_policy = NO_SELECTION)", evaluations=evals)
    if not geschikt:
        return Selection(NO_SELECTION, reason="geen kandidaat met een geldige primaire metriek",
                         evaluations=evals)

    # rangorde alleen als alle geschikte waarden verschillen
    waarden = {k: kandidaten[k][rule.primary_metric]["value"] for k in geschikt}
    if len(set(waarden.values())) == len(waarden):
        for plek, k in enumerate(sorted(geschikt, key=lambda k: _gericht(waarden[k], rule.direction)), 1):
            next(e for e in evals if e["candidate"] == k)["rank_position"] = plek

    beste = min(_gericht(v, rule.direction) for v in waarden.values())
    gelijk = [k for k in geschikt if _gericht(waarden[k], rule.direction) == beste]
    gebruikt = {}
    for regel in rule.tie_break:
        if len(gelijk) == 1:
            break
        if regel == CONFIG_HASH_TIEBREAK:
            gelijk = [min(gelijk, key=lambda k: config_hashes[k])]
            gebruikt[CONFIG_HASH_TIEBREAK] = config_hashes[gelijk[0]]
            break
        metriek, richting = regel
        vals = {}
        for k in gelijk:
            m = kandidaten[k].get(metriek) or {}
            if m.get("calculation_status") != "VALID" or m.get("value") is None:
                return Selection(NO_SELECTION, evaluations=evals,
                                 reason=f"gelijkspel niet te beslechten: {metriek} niet geldig voor {k}")
            vals[k] = m["value"]
        top = min(_gericht(v, richting) for v in vals.values())
        gelijk = [k for k in gelijk if _gericht(vals[k], richting) == top]
        gebruikt[metriek] = {k: vals[k] for k in vals}
    if len(gelijk) != 1:
        return Selection(NO_SELECTION, evaluations=evals, tie_break_values=gebruikt,
                         reason=f"gelijkspel tussen {len(gelijk)} kandidaten na alle tie-breaks")
    gekozen = gelijk[0]
    return Selection(SELECTED, selected=gekozen, evaluations=evals, tie_break_values=gebruikt,
                     selected_metric_value=waarden[gekozen], selected_metric_status="VALID")


def validation_decision(rule: SelectionRule, metrics: dict | None) -> tuple[str, str]:
    """PASSED of FAILED voor alleen de gekozen kandidaat. Bij FAILED wordt er
    geen andere kandidaat geprobeerd."""
    if rule.validation_policy != TRAIN_THEN_VALIDATION:
        return NOT_REQUIRED, "TRAIN_ONLY_SELECTION"
    v = rule.validation_condition
    m = (metrics or {}).get(v["metric"]) or {}
    if m.get("calculation_status") != "VALID" or m.get("value") is None:
        return FAILED, f"{v['metric']} op VALIDATION is {m.get('calculation_status', 'afwezig')}"
    x, t = m["value"], v["threshold"]
    ok = {">": x > t, ">=": x >= t, "<": x < t, "<=": x <= t}[v["operator"]]
    return (PASSED if ok else FAILED), f"{v['metric']} = {x} {v['operator']} {t}: {'ja' if ok else 'nee'}"


# --------------------------------------------------------------------------- #
# vensters
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Window:
    window_index: int
    segments: tuple[Segment, ...]         # TRAIN (en VALIDATION) en TEST; bij SEQUENTIAL alleen TEST

    def segment(self, soort: str) -> Segment | None:
        return next((s for s in self.segments if s.kind == soort), None)


def build_windows(
    mode: str, window_type: str, bar_ts: list[int], bar_seconds: int, *,
    first_train_start: int, train_length: int, validation_length: int,
    test_length: int, step_size: int, window_count: int, max_hold_seconds: int,
) -> tuple[Window, ...]:
    """Alle vensters, vooraf en volledig. Alle lengtes in seconden; niets wordt
    uit de data afgeleid behalve de opwarmbars per segment."""
    if mode not in MODES:
        raise WalkForwardError(f"onbekende modus: {mode}")
    if window_type not in (ROLLING, EXPANDING):
        raise WalkForwardError("window_type is ROLLING of EXPANDING")
    for naam, w in (("train_length", train_length), ("test_length", test_length),
                    ("step_size", step_size), ("window_count", window_count)):
        if not isinstance(w, int) or w <= 0:
            raise WalkForwardError(f"{naam} moet een positief geheel getal zijn")
    if not isinstance(validation_length, int) or validation_length < 0:
        raise WalkForwardError("validation_length moet 0 of positief zijn")
    einde_data = bar_ts[-1] + bar_seconds

    vensters = []
    for k in range(window_count):
        if window_type == ROLLING:
            t0, t1 = first_train_start + k * step_size, first_train_start + k * step_size + train_length
        else:
            t0, t1 = first_train_start, first_train_start + train_length + k * step_size
        v1 = t1 + validation_length
        e1 = v1 + test_length
        if e1 > einde_data:
            raise WalkForwardError(f"venster {k}: TEST loopt tot na het einde van de dataset")
        segs = []
        if mode == CANDIDATE_SELECTION:
            segs.append(make_segment("TRAIN", 1, t0, t1, bar_ts, bar_seconds, max_hold_seconds))
            if validation_length:
                segs.append(make_segment("VALIDATION", 2, t1, v1, bar_ts, bar_seconds, max_hold_seconds))
        segs.append(make_segment("TEST", 3, v1, e1, bar_ts, bar_seconds, max_hold_seconds))
        vensters.append(Window(k, tuple(segs)))

    for eerder, later in zip(vensters, vensters[1:]):
        if later.segment("TEST").start_ts < eerder.segment("TEST").end_ts:
            raise WalkForwardError(
                f"TEST-vensters {eerder.window_index} en {later.window_index} overlappen; "
                "in versie 1 niet toegestaan"
            )
        if later.segment("TEST").start_ts <= eerder.segment("TEST").start_ts:
            raise WalkForwardError("vensters moeten strikt oplopend zijn")
    return tuple(vensters)

