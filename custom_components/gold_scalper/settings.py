"""Eén plek die bepaalt welke waarde van een instelling werkelijk geldt.

``build_from_quotes`` stond op twee plekken: in de basisconfiguratie (het
verbindingsformulier) en in de opties. De opties wonnen stilzwijgend. Wie het
verbindingsformulier opnieuw invulde en de schakelaar uitzette, veranderde
daarmee niets - en de bars werden zelf opgebouwd terwijl je dacht dat ze van
de broker kwamen.

Regels:

* De **opties** zijn de plek waar de waarde thuishoort.
* Staat hij niet in de opties, dan telt de basisconfiguratie (oudere
  installaties). Er wordt niets gemigreerd: dat zou de integratie herladen en
  kan de actieve waarde niet veranderen, dus het voegt alleen risico toe.
* De drie waarden - geconfigureerd, overschreven, effectief - zijn altijd samen
  zichtbaar, met de herkomst van de effectieve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Resolved:
    key: str
    configured: Any          # waarde in de basisconfiguratie, of None
    override: Any            # waarde in de opties, of None
    effective: Any           # wat werkelijk geldt
    origin: str              # "options" / "data" / "default"

    @property
    def conflicting(self) -> bool:
        """Staan er twee verschillende waarden, waarvan er één stil wordt genegeerd?"""
        return (
            self.configured is not None
            and self.override is not None
            and self.configured != self.override
        )

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "configured": self.configured,
            "override": self.override,
            "effective": self.effective,
            "origin": self.origin,
            "conflicting": self.conflicting,
        }


def resolve(
    data: Mapping[str, Any], options: Mapping[str, Any], key: str, default: Any,
) -> Resolved:
    """Bepaal de geldende waarde, met de herkomst erbij."""
    configured = data.get(key)
    override = options.get(key)
    if override is not None:
        return Resolved(key, configured, override, override, "options")
    if configured is not None:
        return Resolved(key, configured, None, configured, "data")
    return Resolved(key, None, None, default, "default")


def candle_source(build_from_quotes: bool) -> str:
    """Waar de bars vandaan komen, in woorden die in diagnostiek en run staan."""
    return "quotes" if build_from_quotes else "broker"
