"""Wat elke gerapporteerde metriek precies betekent.

Eerst stonden er getallen naast elkaar die niet over dezelfde trades gingen,
niet in dezelfde valuta stonden of niet over dezelfde dag telden - en dat was
aan de getallen niet te zien. Hier staat per metriek:

* **populatie** - over welke trades hij gaat
* **valuta** - instrumentvaluta, accountvaluta of eenheidsloos
* **tijdzone** - voor alles wat per dag telt
* **noemer** - waardoor gedeeld wordt, bij een verhouding of gemiddelde

Een test controleert dat elke metriek die de diagnostiek meldt hier staat.
"""

from __future__ import annotations

from .timeutil import TRADING_TZ

GESLOTEN_RUN = "gesloten trades van de actieve run, deelsluitingen inbegrepen"
INSTRUMENT = "instrumentvaluta (USD)"
ACCOUNT = "accountvaluta (EUR bij dit account)"
GEEN = "eenheidsloos"
HANDELSDAG = f"handelsdag in {TRADING_TZ.key}; tijden opgeslagen in UTC"
N_VT = "n.v.t."

METRICS: dict[str, dict[str, str]] = {
    "net_pnl": {"populatie": GESLOTEN_RUN, "valuta": INSTRUMENT,
                "tijdzone": N_VT, "noemer": N_VT},
    "gross_pnl": {"populatie": GESLOTEN_RUN, "valuta": INSTRUMENT,
                  "tijdzone": N_VT, "noemer": N_VT},
    "total_costs": {"populatie": GESLOTEN_RUN, "valuta": INSTRUMENT,
                    "tijdzone": N_VT, "noemer": N_VT},
    "cost_per_trade": {"populatie": GESLOTEN_RUN, "valuta": INSTRUMENT,
                       "tijdzone": N_VT, "noemer": "aantal gesloten trades"},
    "win_rate": {"populatie": GESLOTEN_RUN, "valuta": GEEN, "tijdzone": N_VT,
                 "noemer": "aantal gesloten trades"},
    "expectancy": {"populatie": GESLOTEN_RUN, "valuta": INSTRUMENT,
                   "tijdzone": N_VT, "noemer": "aantal gesloten trades"},
    "profit_factor": {"populatie": GESLOTEN_RUN, "valuta": GEEN,
                      "tijdzone": N_VT,
                      "noemer": "som van de verliezen (absoluut)"},
    "t_statistic": {"populatie": GESLOTEN_RUN, "valuta": GEEN, "tijdzone": N_VT,
                    "noemer": "standaardfout van het netto per trade"},
    "max_drawdown": {"populatie": "equitycurve van de run", "valuta": ACCOUNT,
                     "tijdzone": N_VT, "noemer": N_VT},
    "max_drawdown_pct": {"populatie": "equitycurve van de run",
                         "valuta": GEEN, "tijdzone": N_VT,
                         "noemer": "hoogste equity tot dan toe (accountvaluta)"},
    "daily": {"populatie": GESLOTEN_RUN, "valuta": INSTRUMENT,
              "tijdzone": HANDELSDAG, "noemer": N_VT},
    "periods": {"populatie": GESLOTEN_RUN, "valuta": INSTRUMENT,
                "tijdzone": HANDELSDAG, "noemer": N_VT},
    "exit_stats": {"populatie": GESLOTEN_RUN, "valuta": GEEN, "tijdzone": N_VT,
                   "noemer": "aantal gesloten trades; onbekend deel apart"},
    "ledger_costs": {"populatie": GESLOTEN_RUN, "valuta": INSTRUMENT,
                     "tijdzone": N_VT, "noemer": N_VT},
    "net_pnl_account": {"populatie": "per trade", "valuta": ACCOUNT,
                        "tijdzone": N_VT, "noemer": N_VT},
    "effective_equity_floor": {"populatie": "account", "valuta": ACCOUNT,
                               "tijdzone": N_VT, "noemer": N_VT},
    "sessions": {"populatie": GESLOTEN_RUN, "valuta": INSTRUMENT,
                 "tijdzone": "beursuren in UTC (geen kalenderdag)",
                 "noemer": "aantal trades per sessie"},
}

VELDEN = ("populatie", "valuta", "tijdzone", "noemer")
