"""Het eerste onderzoeksmodel, vastgelegd vóór er data voor is (5.7).

**EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING**

Alleen een beschrijving. Deze module rekent niets uit, wijzigt geen
beoordelingsregels en past geen strategieparameter aan. Zij legt vast welke
vragen in welke volgorde gesteld worden, zodat die keuze niet achteraf door de
uitkomst wordt bepaald.

Volgorde: eerst bruto, dan netto. De nettovraag neemt alle geregistreerde
kosten mee en komt pas aan bod nadat de brutovraag is beantwoord.

De omgekeerde strategie is een controle, geen bevestiging: zij gebruikt
dezelfde data en dezelfde signalen, en is dus niet onafhankelijk.
"""

from __future__ import annotations

from dataclasses import dataclass

RESEARCH_DESIGN_VERSION = 1


@dataclass(frozen=True)
class Hypothesis:
    code: str
    order: int
    quantity: str
    null: str
    alternative: str
    sided: str
    costs: str
    role: str
    independent_evidence: bool


GROSS = Hypothesis(
    code="H_GROSS_OOS_PER_TRADE", order=1,
    quantity="gemiddeld bruto OOS-resultaat per trade",
    null="gemiddeld bruto OOS-resultaat per trade = 0",
    alternative="gemiddeld bruto OOS-resultaat per trade ≠ 0",
    sided="two-sided", costs="excluded", role="PRIMARY",
    independent_evidence=True,
)

NET = Hypothesis(
    code="H_NET_OOS_PER_TRADE", order=2,
    quantity="gemiddeld netto OOS-resultaat per trade",
    null="gemiddeld netto OOS-resultaat per trade = 0",
    alternative="gemiddeld netto OOS-resultaat per trade ≠ 0",
    sided="two-sided", costs="all_registered_costs", role="SECONDARY_AFTER_GROSS",
    independent_evidence=True,
)

INVERSE_SANITY_CHECK = Hypothesis(
    code="CHECK_INVERSE_MIRRORS_GROSS", order=3,
    quantity="bruto resultaat van de omgekeerde strategie",
    null="bruto ongeveer gespiegeld; kosten blijven positief",
    alternative="afwijkende spiegeling: asymmetrische fills, richtingseffect of fout",
    sided="not_a_test", costs="reported_separately", role="SANITY_CHECK",
    # Zelfde data, zelfde signalen: nooit een onafhankelijke bevestiging.
    independent_evidence=False,
)

DESIGN: tuple[Hypothesis, ...] = (GROSS, NET, INVERSE_SANITY_CHECK)


def as_dict() -> dict:
    """Het model als gewone gegevens, voor documentatie en weergave."""
    return {
        "research_design_version": RESEARCH_DESIGN_VERSION,
        "hypotheses": [h.__dict__.copy() for h in DESIGN],
        "changes_assessment_rules": False,
        "changes_strategy_parameters": False,
    }
