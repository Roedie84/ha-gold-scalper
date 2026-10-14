"""Execution ledger: per order wat er werkelijk gebeurde (2.7.0).

Opdracht Ruud 14-10 ("Gold Scalper verbeterplan"): per order reconstrueren
wat er gebeurde - signaal, verzending, fill, latency, spread, slippage - en
expliciet onderscheiden wat gemeten, van de broker, berekend, geschat of
ontbrekend is. Een schatting mag nooit als brokerwaarde gelden.

Zuiver, zonder Home Assistant: de coordinator geeft de tijden en koersen
door en schrijft de rij weg.
"""
from __future__ import annotations

from datetime import datetime

GEMETEN = "gemeten"
BROKER = "broker"
BEREKEND = "berekend"
GESCHAT = "geschat"
ONTBREEKT = "ontbreekt"

#: Een live tick is bruikbaar als verzendkoers als hij hooguit zo oud is.
TICK_MAX_LEEFTIJD_S = 5.0


def _ms(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() * 1000.0, 1)


def ledger_rij(
    *,
    run_id: int | None,
    strategie: str | None,
    side: str,
    units_gevraagd: float | None,
    signaal_ts: datetime,
    signaal_bid: float | None,
    signaal_ask: float | None,
    koers_ts: datetime | None,
    candle_ts: datetime | None,
    verzend_ts: datetime | None,
    tick: tuple | None,
    bevestiging_ts: datetime | None,
    result=None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> dict:
    """Bouw één rij voor de tabel ``uitvoering``.

    ``tick`` is (tijd, bid, ask) van de live stroom, of None. Is hij hooguit
    ``TICK_MAX_LEEFTIJD_S`` oud op het verzendmoment, dan is dat de gemeten
    verzendkoers; anders is de verzendkoers de signaalkoers (geschat).
    """
    d = 1 if side == "buy" else -1
    herkomst: dict[str, str] = {}

    def zet(veld, waarde, bron):
        herkomst[veld] = bron if waarde is not None else ONTBREEKT
        return waarde

    rij: dict = {
        "run_id": run_id,
        "strategie": strategie,
        "richting": d,
        "units_gevraagd": units_gevraagd,
        "signaal_ts": signaal_ts.isoformat(),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
    }
    rij["signaal_bid"] = zet("signaal_bid", signaal_bid, GEMETEN)
    rij["signaal_ask"] = zet("signaal_ask", signaal_ask, GEMETEN)
    rij["spread_signaal"] = zet(
        "spread_signaal",
        round(signaal_ask - signaal_bid, 4) if signaal_bid and signaal_ask else None,
        BEREKEND,
    )
    rij["koers_leeftijd_s"] = zet(
        "koers_leeftijd_s",
        round((signaal_ts - koers_ts).total_seconds(), 2) if koers_ts else None,
        GEMETEN,
    )
    rij["candle_leeftijd_s"] = zet(
        "candle_leeftijd_s",
        round((signaal_ts - candle_ts).total_seconds(), 1) if candle_ts else None,
        GEMETEN,
    )
    rij["verzend_ts"] = verzend_ts.isoformat() if verzend_ts else None
    herkomst["verzend_ts"] = GEMETEN if verzend_ts else ONTBREEKT

    vb = va = None
    bron_verzend = ONTBREEKT
    if tick and verzend_ts is not None:
        t, b, a = tick
        try:
            leeftijd = verzend_ts.timestamp() - float(t)
        except (TypeError, ValueError):
            leeftijd = None
        if leeftijd is not None and 0 <= leeftijd <= TICK_MAX_LEEFTIJD_S and b and a:
            vb, va, bron_verzend = float(b), float(a), GEMETEN
    if vb is None and signaal_bid and signaal_ask:
        vb, va, bron_verzend = signaal_bid, signaal_ask, GESCHAT
    rij["verzend_bid"], rij["verzend_ask"] = vb, va
    herkomst["verzend_bid"] = herkomst["verzend_ask"] = bron_verzend
    rij["spread_verzending"] = round(va - vb, 4) if vb and va else None
    herkomst["spread_verzending"] = bron_verzend if vb and va else ONTBREEKT

    rij["latentie_signaal_order_ms"] = zet(
        "latentie_signaal_order_ms", _ms(signaal_ts, verzend_ts), GEMETEN)
    rij["latentie_order_fill_ms"] = zet(
        "latentie_order_fill_ms", _ms(verzend_ts, bevestiging_ts), GEMETEN)
    rij["bevestiging_ts"] = bevestiging_ts.isoformat() if bevestiging_ts else None
    herkomst["bevestiging_ts"] = GEMETEN if bevestiging_ts else ONTBREEKT

    if result is not None:
        rij["broker_ticket"] = str(result.ticket) if getattr(result, "ticket", None) else None
        rij["client_ref"] = getattr(result, "client_ref", None)
        rij["units_gevuld"] = zet("units_gevuld", getattr(result, "units", None), BROKER)
        rij["latentie_broker_ms"] = zet(
            "latentie_broker_ms", getattr(result, "latency_ms", None), GEMETEN)
        gevraagd = getattr(result, "requested_price", None)
        if gevraagd is None and (vb or va):
            gevraagd = va if d == 1 else vb
            herkomst["gevraagde_prijs"] = bron_verzend if gevraagd is not None else ONTBREEKT
        else:
            herkomst["gevraagde_prijs"] = GEMETEN if gevraagd is not None else ONTBREEKT
        rij["gevraagde_prijs"] = gevraagd
        rij["fill_prijs"] = zet("fill_prijs", getattr(result, "fill_price", None), BROKER)
        if rij["fill_prijs"] is not None and gevraagd is not None:
            # Positief = nadelig voor ons.
            rij["slippage_usd"] = round((rij["fill_prijs"] - gevraagd) * d, 4)
            herkomst["slippage_usd"] = BEREKEND
        else:
            rij["slippage_usd"] = None
            herkomst["slippage_usd"] = ONTBREEKT
        if getattr(result, "unconfirmed", False):
            rij["resultaat"] = "onbevestigd"
        else:
            rij["resultaat"] = "gevuld" if getattr(result, "success", False) else "afgewezen"
        rij["fout"] = getattr(result, "error", None)
    else:
        rij["resultaat"] = "fout"
    rij["herkomst"] = herkomst
    return rij
