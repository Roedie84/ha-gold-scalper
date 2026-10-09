"""Meerdere posities tegelijk: telling, spreiding, marge en netting (1.9.0).

Besluit van de eigenaar (09-10-2026): er mogen meer posities open om sneller
data te verzamelen, long en short naast elkaar. Maximaal
``max_positions_per_richting`` per richting (standaard 3, dus hooguit 3 long
en 3 short), elke positie op haar eigen, ongewijzigde grootte.

Puur Python, zonder Home Assistant: alles hier is los te toetsen.

**Minimale spreiding.** Een extra positie in dezelfde richting mag alleen als
ze geen kopie is van een positie die er al staat. Twee eisen, allebei:

1. **Een latere candle** dan de meest recente open positie in die richting.
   Binnen één candle is de marktsituatie dezelfde; drie instappen in dezelfde
   minuut zijn één waarneming met drie keer de inzet.
2. **Een instapprijs die minstens 0,3 x ATR verschilt** van elke open positie
   in die richting. Na een candle kan de koers op precies hetzelfde niveau
   staan, en dan meet een tweede positie opnieuw hetzelfde. 0,3 x ATR is de
   dode zone van de tijdstop (``time_stop_deadzone_atr``): daarbinnen geldt
   een positie als "niet van zijn plek gekomen", dus daarbinnen is een nieuwe
   instap ook niet van een andere plek.

Tijd alleen laat in een stille markt kopieën op dezelfde prijs toe; prijs
alleen laat bij een snelle uitschieter drie instappen binnen seconden toe.
Pas samen sluiten ze "hetzelfde moment" uit. Daarnaast hooguit één nieuwe
positie per cyclus (coordinator) en de bestaande cooldown tussen instappen.

**Marge en vloer.** Een extra positie wordt geweigerd als de geschatte marge
niet in de vrije marge past (met 10% buffer), of als de equity onder de
vloer zou zakken wanneer álle open stops plus de nieuwe stop geraakt worden.

**Netting.** IG opent met ``forceOpen: true`` een aparte positie, ook tegen
een bestaande in. Verrekent een account toch (``affectedDeals`` met een
gesloten deal in de bevestiging, of een tegengestelde positie die bij het
openen verdwijnt), dan wordt dat gedetecteerd, luid gemeld en wordt hedgen
uitgeschakeld - nooit een stille verrekening.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Callable, Iterable

#: Minimale prijsafstand tot elke open positie in dezelfde richting, in ATR.
MIN_SPREIDING_ATR = 0.3
#: Geschatte margefactor voor goud bij IG (retail, 20:1 = 5%). Een schatting:
#: de broker rekent zelf, de vrije marge die hij meldt is leidend.
MARGE_FACTOR = 0.05
#: Hooguit dit deel van de vrije marge gebruiken voor één extra positie.
MARGE_BUFFER = 0.9
#: Statussen in ``affectedDeals`` die op verrekening wijzen.
NETTING_STATUSSEN = frozenset({"FULLY_CLOSED", "PARTIALLY_CLOSED", "DELETED"})


def richting_van(side) -> int:
    """'buy' → 1, 'sell' → -1."""
    return 1 if str(side or "buy").lower() in ("buy", "long", "1") else -1


def tel_per_richting(posities: Iterable, pending: Iterable = ()) -> dict[int, int]:
    """Aantal open posities per richting, onbevestigde orders inbegrepen.

    Een onbevestigde order kan een positie zijn; hij telt mee tot hij is
    teruggevonden of vervallen. Anders houdt de limiet niet.
    """
    telling = {1: 0, -1: 0}
    for p in posities:
        telling[richting_van(getattr(p, "side", "buy"))] += 1
    for o in pending:
        telling[richting_van(getattr(o, "side", "buy"))] += 1
    return telling


def bar_index(moment, bar_seconden: int) -> int | None:
    """Volgnummer van de candle waarin ``moment`` valt."""
    if moment is None or not bar_seconden:
        return None
    if isinstance(moment, (int, float)):
        ts = float(moment)
    elif isinstance(moment, datetime):
        ts = moment.timestamp()
    else:
        try:
            ts = datetime.fromisoformat(str(moment)).timestamp()
        except (TypeError, ValueError):
            return None
    return int(math.floor(ts / bar_seconden))


def spreiding_ok(
    richting: int,
    instap: float,
    atr: float | None,
    bestaand: Iterable[tuple[float, object]],
    nu,
    bar_seconden: int,
    min_atr: float = MIN_SPREIDING_ATR,
) -> tuple[bool, str | None]:
    """Mag er naast ``bestaand`` (instap, opentijd) een positie bij?

    ``bestaand`` bevat alleen de open posities in dezelfde richting. Zonder
    bruikbare ATR geen extra positie: dan is de afstand niet te toetsen.
    """
    bestaand = [(float(p), t) for p, t in bestaand if p is not None]
    if not bestaand:
        return True, None
    kant = "long" if richting == 1 else "short"
    nu_bar = bar_index(nu, bar_seconden)
    bars = [bar_index(t, bar_seconden) for _, t in bestaand]
    bekend = [b for b in bars if b is not None]
    if nu_bar is None or len(bekend) != len(bars):
        return False, (
            f"spreiding: openingstijd van een {kant}-positie onbekend; geen "
            "tweede instap zonder vast te stellen dat het een latere candle is"
        )
    if max(bekend) >= nu_bar:
        return False, (
            f"spreiding: er opende al een {kant}-positie in deze candle; een "
            "tweede is een kopie van hetzelfde moment"
        )
    if not atr or atr <= 0:
        return False, "spreiding: geen bruikbare ATR om de afstand te toetsen"
    drempel = min_atr * atr
    dichtst = min(abs(instap - p) for p, _ in bestaand)
    if dichtst < drempel:
        return False, (
            f"spreiding: instap {instap:.2f} ligt {dichtst:.2f} van een open "
            f"{kant}-positie; minimaal {drempel:.2f} ({min_atr:g} x ATR)"
        )
    return True, None


def positie_risico(positie, units_fallback: float | None = None,
                   stop_fallback_afstand: float | None = None) -> float:
    """Verlies in instrumentvaluta als de stop van deze positie geraakt wordt.

    Ontbreekt de stop, dan de afstand van het nieuwe signaal als schatting;
    ontbreekt ook die, dan telt de positie als 0 (en zegt de broker het via
    de vrije marge).
    """
    instap = getattr(positie, "open_price", None)
    stop = getattr(positie, "stop_loss", None)
    units = getattr(positie, "units", None)
    if units is None:
        volume = getattr(positie, "volume", None)
        units = (volume or 0) * 100.0 if volume is not None else units_fallback
    try:
        units = float(units or 0.0)
    except (TypeError, ValueError):
        units = 0.0
    if not math.isfinite(units):
        units = float(units_fallback or 0.0)
    if instap is None:
        return 0.0
    if stop is None:
        afstand = stop_fallback_afstand or 0.0
    else:
        richting = richting_van(getattr(positie, "side", "buy"))
        afstand = max(0.0, (float(instap) - float(stop)) * richting)
    return afstand * units


def marge_en_vloer_ok(
    *,
    units: float,
    prijs: float,
    instap: float,
    stop: float | None,
    equity: float | None,
    vloer: float | None,
    marge_vrij: float | None,
    open_posities: Iterable,
    naar_account: Callable[[float], float] = lambda x: x,
    marge_factor: float = MARGE_FACTOR,
) -> tuple[bool, str | None, dict]:
    """Past een extra positie in de marge en boven de vloer?

    Alle bedragen worden naar accountvaluta omgerekend met ``naar_account``.
    ``marge_vrij`` is wat de broker als vrij meldt (accountvaluta); None of
    nul betekent: niet gemeld, dan alleen de vloertoets.
    """
    open_posities = list(open_posities)
    nieuw_afstand = abs(instap - stop) if stop is not None else 0.0
    marge_nodig = naar_account(units * prijs * marge_factor)
    open_risico = naar_account(sum(
        positie_risico(p, units, nieuw_afstand) for p in open_posities
    ))
    nieuw_risico = naar_account(nieuw_afstand * units)
    info = {
        "marge_nodig": round(marge_nodig, 2),
        "marge_vrij": None if marge_vrij is None else round(marge_vrij, 2),
        "open_risico": round(open_risico, 2),
        "nieuw_risico": round(nieuw_risico, 2),
    }
    if not open_posities:
        # De eerste positie valt onder de gewone risicotoets, zoals vóór 1.9.0.
        return True, None, info
    if marge_vrij is not None and marge_vrij > 0 \
            and marge_nodig > marge_vrij * MARGE_BUFFER:
        return False, (
            f"marge: geschat {marge_nodig:.2f} nodig, {marge_vrij:.2f} vrij "
            f"(maximaal {MARGE_BUFFER:.0%} gebruiken)"
        ), info
    if equity is not None and vloer is not None:
        slechtst = equity - open_risico - nieuw_risico
        info["equity_alle_stops"] = round(slechtst, 2)
        if slechtst < vloer:
            return False, (
                f"vloer: als alle {len(open_posities) + 1} stops geraakt worden "
                f"staat de equity op {slechtst:.2f}, onder de vloer van "
                f"{vloer:.2f}"
            ), info
    return True, None, info


def netting_uit_bevestiging(affected) -> list[str]:
    """Deals die een orderbevestiging als (deels) gesloten meldt."""
    uit = []
    for deal in affected or []:
        if not isinstance(deal, dict):
            continue
        if str(deal.get("status", "")).upper() in NETTING_STATUSSEN:
            uit.append(str(deal.get("dealId") or "?"))
    return uit


def netting_uit_posities(
    voor: Iterable, na: Iterable, richting: int, nieuw_ticket: str | None,
) -> list[str]:
    """Tegengestelde posities die bij het openen verdwenen of kromp.

    ``voor`` is de positielijst vlak voor de order, ``na`` vlak erna. Een
    tegengestelde positie die weg is of kleiner werd, terwijl er geen
    sluitverzoek van ons liep, wijst op verrekening. Een nieuwe positie die
    niet in de lijst staat ook.
    """
    na = list(na)
    na_per_ticket = {str(getattr(p, "ticket", "")): p for p in na}
    verdacht = []
    for p in voor:
        if richting_van(getattr(p, "side", "buy")) == richting:
            continue
        t = str(getattr(p, "ticket", ""))
        nu = na_per_ticket.get(t)
        if nu is None:
            verdacht.append(t)
            continue
        try:
            if float(getattr(nu, "units", 0) or 0) < float(getattr(p, "units", 0) or 0) - 1e-9:
                verdacht.append(t)
        except (TypeError, ValueError):
            pass
    if verdacht and nieuw_ticket and str(nieuw_ticket) not in na_per_ticket:
        verdacht.append(f"nieuw:{nieuw_ticket}")
    return verdacht
