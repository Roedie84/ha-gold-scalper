"""Kostenmodel van het Experiment Lab.

Elke kostencomponent heeft een waarde, een bron en een toelichting. Er bestaat
geen totale kostenpost die niet uit zijn componenten is op te bouwen.

Instrumentvaluta en accountvaluta worden nooit bij elkaar opgeteld:

* per trade, in instrumentvaluta::

      gross_pnl_instrument
        - spread_cost_instrument - slippage_cost_instrument
        - commission_cost_instrument - other_cost_instrument
        = net_pnl_instrument

* per trade, in accountvaluta - alleen als de omrekening bruikbaar is::

      converted          = net_pnl_instrument * fx_rate
      fx_cost_account    = |converted| * opslag / 100
                           (winstopslag als converted > 0, verliesopslag als < 0)
      net_pnl_account    = converted - fx_cost_account
      gross_pnl_account  = gross_pnl_instrument * fx_rate
      total_cost_account = total_cost_instrument * fx_rate + fx_cost_account

  zodat ``gross_pnl_account - total_cost_account = net_pnl_account``.

De wisselkoersopslag wordt **nooit** vast ingebouwd. Hij geldt alleen als hij
per experiment expliciet is opgegeven, met zijn herkomst. Historische
waarnemingen zijn geen universeel brokerpercentage.
"""

from __future__ import annotations

from math import isfinite

#: Verhogen zodra de berekening of de betekenis van een kostencomponent
#: verandert. Oude resultaten houden hun versie.
COST_MODEL_VERSION = 1

MEASURED, CALCULATED, ASSUMED, UNKNOWN = "MEASURED", "CALCULATED", "ASSUMED", "UNKNOWN"
BRONNEN = (MEASURED, CALCULATED, ASSUMED, UNKNOWN)

#: Conversiestatus per trade.
CONVERTED, NOT_CONFIGURED, UNUSABLE = "CONVERTED", "UNKNOWN", "UNUSABLE"


class CostModelError(ValueError):
    """Het kostenmodel is niet eenduidig opgegeven."""


def _getal(waarde, naam: str, minimum: float = 0.0) -> float:
    try:
        getal = float(waarde)
    except (TypeError, ValueError) as err:
        raise CostModelError(f"{naam} is geen getal: {waarde!r}") from err
    if not isfinite(getal) or getal < minimum:
        raise CostModelError(f"{naam} moet eindig zijn en minstens {minimum}: {getal}")
    return getal


def build_cost_model(execution: dict) -> dict:
    """Het kostenmodel van één resultaat, uit de uitvoeringsconfiguratie.

    ``instrument_currency`` is verplicht: een bedrag zonder valuta bestaat niet.
    """
    valuta = execution.get("instrument_currency")
    if not valuta or not isinstance(valuta, str):
        raise CostModelError("execution.instrument_currency is verplicht")
    spread = _getal(execution.get("spread", 0.60), "spread")
    slippage = _getal(execution.get("slippage", 0.02), "slippage")

    model = {
        "cost_model_version": COST_MODEL_VERSION,
        "cost_currency": valuta,
        "spread_model": {
            "type": "vast per ounce", "value_per_unit": spread, "source": ASSUMED,
            "applied": "halve spread bij instap en halve spread bij uitstap",
        },
        "slippage_model": {
            "type": "vast per ounce", "value_per_unit": slippage, "source": ASSUMED,
            "applied": "alleen bij de instap (zo rekent backtestmotor 1-3)",
        },
        "commission_model": {
            "type": "geen", "value_per_unit": 0.0, "source": ASSUMED,
            "applied": "de backtestmotor rekent geen commissie",
        },
        "other_model": {
            "type": "geen", "value_per_unit": 0.0, "source": ASSUMED,
            "applied": "geen overige kosten gemodelleerd",
        },
        "fx_model": _fx_model(execution.get("fx_conversion")),
        "assumptions": [
            "Kosten in instrumentvaluta; de wisselkoersopslag alleen in accountvaluta.",
            "De exitbeheerder rekent met spread + 2x slippage; de geboekte kosten "
            "bevatten 1x slippage. Dat verschil is bestaand motorgedrag.",
        ],
    }
    return model


def _fx_model(fx) -> dict:
    if not fx:
        return {"status": NOT_CONFIGURED, "source": UNKNOWN,
                "reason": "geen omrekening opgegeven; accountbedragen blijven leeg"}
    try:
        rekening = fx.get("account_currency")
        if not rekening or not isinstance(rekening, str):
            raise CostModelError("fx_conversion.account_currency is verplicht")
        koers = _getal(fx.get("rate"), "fx_conversion.rate", minimum=1e-12)
        winst = fx.get("profit_markup_pct")
        verlies = fx.get("loss_markup_pct")
        if winst is None or verlies is None:
            return {"status": UNUSABLE, "source": UNKNOWN, "account_currency": rekening,
                    "reason": "opslag voor winst of verlies ontbreekt; zonder beide "
                              "is het accountresultaat niet eenduidig"}
        winst = _getal(winst, "profit_markup_pct")
        verlies = _getal(verlies, "loss_markup_pct")
        if winst >= 10 or verlies >= 10:
            raise CostModelError("een opslag van 10% of meer is geen wisselkoersopslag")
        herkomst = fx.get("origin", ASSUMED)
        if herkomst not in BRONNEN:
            raise CostModelError(f"onbekende herkomst: {herkomst}")
        return {
            "status": CONVERTED, "account_currency": rekening, "rate": koers,
            "rate_direction": "accountvaluta per eenheid instrumentvaluta",
            "rate_source": str(fx.get("rate_source") or ""),
            "rate_timestamp": fx.get("rate_timestamp"),
            "profit_markup_pct": winst, "loss_markup_pct": verlies,
            "source": herkomst,
        }
    except CostModelError:
        raise


def account_fields(gross: float, total_cost: float, net: float, fx_model: dict) -> dict:
    """Accountbedragen van één trade, of allemaal leeg als dat niet eenduidig kan."""
    leeg = {
        "account_currency": fx_model.get("account_currency"),
        "fx_rate": None, "fx_source": None, "fx_timestamp": None,
        "fx_cost_account": None, "gross_pnl_account": None,
        "total_cost_account": None, "net_pnl_account": None,
        "conversion_status": fx_model["status"],
    }
    if fx_model["status"] != CONVERTED:
        return leeg
    koers = fx_model["rate"]
    omgerekend = net * koers
    opslag = fx_model["profit_markup_pct"] if omgerekend > 0 else fx_model["loss_markup_pct"]
    fx_kosten = abs(omgerekend) * opslag / 100.0
    return {
        "account_currency": fx_model["account_currency"],
        "fx_rate": koers, "fx_source": fx_model["rate_source"],
        "fx_timestamp": fx_model["rate_timestamp"],
        "fx_cost_account": fx_kosten,
        "gross_pnl_account": gross * koers,
        "total_cost_account": total_cost * koers + fx_kosten,
        "net_pnl_account": omgerekend - fx_kosten,
        "conversion_status": CONVERTED,
    }
