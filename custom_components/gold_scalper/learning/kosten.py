"""Gemeten kosten per trade, uit de afrekening van de broker (1.4).

Tot 1.3 was het aantal trades met gemeten kosten nul. Alleen een eigen
sluitorder gold als meting, en ruim negentig procent van de trades sluit op de
stop of het doel bij de broker. De kosten - zo'n zestig procent van het verlies
- waren dus overal een schatting uit spread maal omvang.

Met de afrekening van de broker erbij is het wel te meten. Kosten zijn het
verschil tussen de beweging op de middenkoersen en wat er werkelijk werd
afgerekend:

* **instap**: de vulprijs tegenover de middenkoers op het moment van de
  order. Beide eigen waarnemingen, op hetzelfde moment.
* **uitstap op stop of doel**: de broker vult op het niveau van de order; de
  halve spread is de afstand van dat niveau tot het midden, en wat hij daar
  nog naast vult is slippage. Het niveau en de vulprijs komen van de broker.
* **uitstap op een eigen sluitorder**: de vulprijs van de broker tegenover de
  middenkoers op het moment van sluiten.

Geen afsluitreden met bewijs, geen eigen middenkoers: geen meting. Dan blijft
de berekende waarde staan, met die herkomst.
"""

from __future__ import annotations

#: Sluitredenen waarbij de broker op het niveau van een order vulde. Zonder
#: spread bij het sluiten geldt de spread bij de instap; bij goud ligt die
#: binnen een sessie vrijwel vast.
_NIVEAU_REDENEN = {"stop_loss", "take_profit"}


def meet_kosten(trade, broker_uit: float, contract_size: float) -> dict | None:
    """Kosten van een trade, gemeten tegen de afrekening van de broker.

    Geeft ``{"total_cost", "spread_cost", "slippage_cost", "uitstap_slippage"}``
    in instrumentvaluta (dollars), of None als het niet te meten is.
    """
    if (trade.open_mid is None or trade.open_price is None
            or not trade.volume or broker_uit is None):
        return None
    units = trade.volume * contract_size
    richting = 1.0 if trade.side == "buy" else -1.0

    # Instap: vulprijs tegenover het midden op dat moment.
    instap = (trade.open_price - trade.open_mid) * richting * units
    instap_spread = (trade.open_spread or 0.0) / 2.0 * units
    instap_slip = instap - instap_spread

    oorspronkelijk = trade.original_close_reason or trade.close_reason or ""
    eigen_order = (
        oorspronkelijk
        and not oorspronkelijk.startswith("broker_gesloten")
        and oorspronkelijk not in _NIVEAU_REDENEN
    )

    if eigen_order:
        if trade.close_mid is None:
            return None
        uitstap = (trade.close_mid - broker_uit) * richting * units
        uitstap_spread = (trade.close_spread or 0.0) / 2.0 * units
        uitstap_slip = uitstap - uitstap_spread
    else:
        reden = trade.reconciled_close_reason or oorspronkelijk
        if reden == "stop_loss":
            niveau = trade.stop_loss
        elif reden == "take_profit":
            niveau = trade.take_profit
        else:
            return None
        if niveau is None:
            return None
        half = (trade.close_spread or trade.open_spread or 0.0) / 2.0
        uitstap_spread = half * units
        uitstap_slip = (niveau - broker_uit) * richting * units

    spread = instap_spread + uitstap_spread
    slip = instap_slip + uitstap_slip
    return {
        "total_cost": round(spread + slip, 4),
        "spread_cost": round(spread, 4),
        "slippage_cost": round(slip, 4),
        "uitstap_slippage": round(uitstap_slip, 4),
    }
