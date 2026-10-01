"""Metrieken van het Experiment Lab: één definitie per metriek.

Alles hier meet. Er wordt niets vergeleken, geselecteerd, gerangschikt of
beoordeeld: een kleine groep blijft een kleine groep, en een hogere frequentie
is geen verdienste.

Elke metriek draagt haar eigen metadata: eenheid, valuta, tijdzone, populatie,
teller, noemer, steekproefomvang en berekeningsstatus. Een waarde die niet
bestaat - winstfactor zonder verliezen, een gemiddelde van niets - is ``None``
met een status, nooit een stille 0.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone

from ..session_rules import session_of
from ..timeutil import TRADING_TZ, trading_day
from .costs import CONVERTED, account_fields

#: Verhogen zodra de berekening of betekenis van een metriek verandert.
METRICS_VERSION = 1

VALID = "VALID"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNKNOWN_INPUT = "UNKNOWN_INPUT"
PARTIAL = "PARTIAL"

HANDELSDAG_TZ = TRADING_TZ.key                      # Europe/Amsterdam
SESSIE_TZ = "UTC (sessiedefinitie)"
FIDELITY = "BAR_ONLY"

#: De velden van een genormaliseerde trade, in vaste volgorde. Dezelfde
#: volgorde voor de databasekolommen en voor de resultaathash.
TRADE_FIELDS = (
    "sequence_number", "opened_ts", "closed_ts", "trading_day", "timezone",
    "side", "units", "instrument_currency", "account_currency",
    "entry_price", "exit_price", "entry_mid", "exit_mid", "stop_price", "target_price",
    "gross_pnl_instrument", "spread_cost_instrument", "slippage_cost_instrument",
    "commission_cost_instrument", "other_cost_instrument",
    "total_cost_instrument", "net_pnl_instrument",
    "fx_rate", "fx_source", "fx_timestamp", "fx_cost_account", "conversion_status",
    "gross_pnl_account", "total_cost_account", "net_pnl_account",
    "holding_seconds", "regime", "session", "close_reason",
    "mae", "mfe", "ambiguous_exit", "fidelity_status",
)


# --------------------------------------------------------------------------- #
# normaliseren
# --------------------------------------------------------------------------- #

def normalize_trade(seq: int, bt: dict, cost_model: dict) -> dict:
    """Eén backtesttrade als genormaliseerde rij. Rekent geen handel opnieuw:
    neemt de uitkomst en de componenten van de motor over en voegt de
    classificaties en accountbedragen toe."""
    geopend = datetime.fromtimestamp(bt["opened_at"], timezone.utc)
    gesloten = datetime.fromtimestamp(bt["closed_at"], timezone.utc)
    spread, slip = bt["spread_cost"], bt["slippage_cost"]
    commissie = cost_model["commission_model"]["value_per_unit"] * bt["units"]
    overig = cost_model["other_model"]["value_per_unit"] * bt["units"]
    totaal = spread + slip + commissie + overig
    rij = {
        "sequence_number": seq,
        "opened_ts": bt["opened_at"], "closed_ts": bt["closed_at"],
        # De handelsdag van de sluiting, in Europe/Amsterdam - zoals overal.
        "trading_day": trading_day(gesloten).isoformat(),
        "timezone": HANDELSDAG_TZ,
        "side": bt["side"], "units": bt["units"],
        "instrument_currency": cost_model["cost_currency"],
        "entry_price": bt["entry"], "exit_price": bt["exit"],
        "entry_mid": bt["entry_mid"], "exit_mid": bt["exit_mid"],
        "stop_price": bt.get("stop_price"), "target_price": bt.get("target_price"),
        "gross_pnl_instrument": bt["gross"],
        "spread_cost_instrument": spread, "slippage_cost_instrument": slip,
        "commission_cost_instrument": commissie, "other_cost_instrument": overig,
        "total_cost_instrument": totaal, "net_pnl_instrument": bt["net"],
        "holding_seconds": bt["closed_at"] - bt["opened_at"],
        "regime": bt.get("regime"),
        # De sessie van de opening, in UTC - de bestaande sessiedefinitie.
        "session": session_of(geopend),
        "close_reason": bt["reason"],
        "mae": bt.get("mae"), "mfe": bt.get("mfe"),
        "ambiguous_exit": 1 if bt.get("ambiguous_exit") else 0,
        "fidelity_status": FIDELITY,
    }
    rij.update(account_fields(bt["gross"], totaal, bt["net"], cost_model["fx_model"]))
    return {veld: _zonder_min_nul(rij.get(veld)) for veld in TRADE_FIELDS}


def _zonder_min_nul(waarde):
    """-0.0 wordt 0.0. SQLite bewaart het teken van nul niet, en in canonieke
    JSON zijn "-0.0" en "0.0" verschillende tekst: zonder dit geeft een uit de
    database gelezen trade een andere resultaathash dan de oorspronkelijke.
    Een bruto van -0.0 ontstaat bij een short met gelijke in- en uitstapmidden."""
    return waarde + 0.0 if isinstance(waarde, float) else waarde


# --------------------------------------------------------------------------- #
# definities
# --------------------------------------------------------------------------- #

_I, _A, _N = "instrument", "account", None
POP = "gesloten trades van dit resultaat"

#: De definitie van elke metriek. ``currency``: instrumentvaluta, accountvaluta
#: of geen. Deze tabel is de enige plek waar een metriek wordt gedefinieerd.
DEFINITIONS: dict[str, dict] = {
    "trade_count": dict(unit="trades", currency=_N, numerator="aantal trades", denominator=None),
    "wins": dict(unit="trades", currency=_N, numerator="netto > +drempel", denominator=None),
    "losses": dict(unit="trades", currency=_N, numerator="netto < -drempel", denominator=None),
    "breakeven": dict(unit="trades", currency=_N, numerator="|netto| <= drempel", denominator=None),
    "unknown_result_count": dict(unit="trades", currency=_N, numerator="netto onbekend", denominator=None),
    "win_rate": dict(unit="%", currency=_N, numerator="wins", denominator="trade_count"),
    "gross_pnl": dict(unit="bedrag", currency=_I, numerator="som bruto", denominator=None),
    "total_costs": dict(unit="bedrag", currency=_I, numerator="som kosten", denominator=None),
    "net_pnl": dict(unit="bedrag", currency=_I, numerator="som netto", denominator=None),
    "average_trade": dict(unit="bedrag", currency=_I, numerator="som netto", denominator="trade_count"),
    "median_trade": dict(unit="bedrag", currency=_I, numerator="mediaan netto", denominator="trade_count"),
    "average_win": dict(unit="bedrag", currency=_I, numerator="som netto van wins", denominator="wins"),
    "average_loss": dict(unit="bedrag", currency=_I, numerator="som netto van losses", denominator="losses"),
    "profit_factor": dict(unit="verhouding", currency=_N, numerator="som netto van wins",
                          denominator="|som netto van losses|"),
    "expectancy": dict(unit="bedrag", currency=_I,
                       numerator="P(win)*gem. win + P(loss)*gem. loss (breakeven telt 0)",
                       denominator="trade_count"),
    "largest_win": dict(unit="bedrag", currency=_I, numerator="grootste netto", denominator=None),
    "largest_loss": dict(unit="bedrag", currency=_I, numerator="kleinste netto", denominator=None),
    "maximum_drawdown": dict(unit="bedrag", currency=_I,
                             numerator="grootste daling van cumulatieve netto P&L vanaf 0, "
                                       "in volgorde van sluiting", denominator=None),
    "maximum_drawdown_pct": dict(unit="%", currency=_N, numerator="maximum_drawdown",
                                 denominator="expliciete kapitaalbasis"),
    "maximum_drawdown_account": dict(unit="bedrag", currency=_A,
                                     numerator="grootste daling van cumulatieve netto "
                                               "P&L in accountvaluta vanaf 0", denominator=None),
    "net_pnl_account": dict(unit="bedrag", currency=_A, numerator="som netto in accountvaluta",
                            denominator=None),
    "fx_cost_account": dict(unit="bedrag", currency=_A, numerator="som wisselkoersopslag",
                            denominator=None),
    "average_holding_seconds": dict(unit="s", currency=_N, numerator="som houdtijd", denominator="trade_count"),
    "median_holding_seconds": dict(unit="s", currency=_N, numerator="mediaan houdtijd", denominator="trade_count"),
    "p90_holding_seconds": dict(unit="s", currency=_N,
                                numerator="90e percentiel houdtijd (nearest rank)", denominator="trade_count"),
    "trading_days": dict(unit="dagen", currency=_N,
                         numerator="handelsdagen met minstens één bar in de dataset", denominator=None),
    "trades_per_day_mean": dict(unit="trades/dag", currency=_N, numerator="trade_count", denominator="trading_days"),
    "trades_per_day_median": dict(unit="trades/dag", currency=_N,
                                  numerator="mediaan trades per handelsdag (dagen zonder trade tellen als 0)",
                                  denominator="trading_days"),
    "signal_evaluations": dict(unit="evaluaties", currency=_N,
                               numerator="bars zonder open positie waarop de strategie werd gevraagd",
                               denominator=None),
    "accepted_signals": dict(unit="evaluaties", currency=_N, numerator="signalen die tot een trade leidden",
                             denominator="signal_evaluations"),
    "rejected_signals": dict(unit="evaluaties", currency=_N, numerator="afgewezen evaluaties",
                             denominator="signal_evaluations"),
    "signals_per_day": dict(unit="evaluaties/dag", currency=_N, numerator="signal_evaluations",
                            denominator="trading_days"),
    "gross_per_trade": dict(unit="bedrag", currency=_I, numerator="gross_pnl", denominator="trade_count"),
    "cost_per_trade": dict(unit="bedrag", currency=_I, numerator="total_costs", denominator="trade_count"),
    "net_per_trade": dict(unit="bedrag", currency=_I, numerator="net_pnl", denominator="trade_count"),
    "cost_per_day": dict(unit="bedrag/dag", currency=_I, numerator="total_costs", denominator="trading_days"),
    "ambiguous_exit_count": dict(unit="trades", currency=_N, numerator="stop en doel in dezelfde bar",
                                 denominator=None),
    "ambiguous_exit_share": dict(unit="%", currency=_N, numerator="ambiguous_exit_count",
                                 denominator="trade_count"),
}

#: Wat er voor ``completed`` minstens moet zijn opgeslagen: alle definities.
#: Een metriek die niet bestaat, staat er ook - met waarde None en een status.
REQUIRED_METRICS = tuple(sorted(DEFINITIONS))


def _record(naam: str, waarde, status: str, n: int, currencies: dict,
            teller=None, noemer=None, tijdzone=None, populatie=POP) -> dict:
    d = DEFINITIONS[naam]
    valuta = currencies.get(d["currency"]) if d["currency"] else None
    return {
        "metric_name": naam, "metric_version": METRICS_VERSION,
        "value": waarde, "unit": d["unit"], "currency": valuta,
        "timezone": tijdzone, "population": populatie,
        "numerator": teller, "denominator": noemer,
        "numerator_definition": d["numerator"], "denominator_definition": d["denominator"],
        "sample_size": n, "calculation_status": status,
    }


def _p90(waarden: list) -> float:
    """Nearest rank: de kleinste waarde waaronder minstens 90% valt."""
    geordend = sorted(waarden)
    return geordend[max(0, math.ceil(0.9 * len(geordend)) - 1)]


def _drawdown(reeks: list[float]) -> float:
    cumulatief, piek, grootste = 0.0, 0.0, 0.0
    for x in reeks:
        cumulatief += x
        piek = max(piek, cumulatief)
        grootste = max(grootste, piek - cumulatief)
    return grootste


def breakeven_tolerance(precision: int, units: float) -> float:
    """Een halve prijsstap per ounce: kleiner is geen meetbare winst of verlies."""
    return 0.5 * 10 ** (-precision) * units


# --------------------------------------------------------------------------- #
# berekenen
# --------------------------------------------------------------------------- #

def compute_metrics(trades: list[dict], summary: dict, dataset_days: list[str],
                    precision: int, cost_model: dict) -> list[dict]:
    """Alle metrieken uit ``DEFINITIONS``, elk met metadata en status."""
    valuta = {_I: cost_model["cost_currency"],
              _A: cost_model["fx_model"].get("account_currency")}
    n = len(trades)
    uit: list[dict] = []

    def r(naam, waarde, status=VALID, **kw):
        uit.append(_record(naam, waarde, status, kw.pop("n", n), valuta, **kw))

    netten = [t["net_pnl_instrument"] for t in trades]
    bekend = [x for x in netten if x is not None]
    tol = breakeven_tolerance(precision, trades[0]["units"]) if trades else 0.0
    wins = [x for x in bekend if x > tol]
    losses = [x for x in bekend if x < -tol]
    even = [x for x in bekend if abs(x) <= tol]
    leeg = INSUFFICIENT_DATA

    r("trade_count", n)
    r("wins", len(wins), n=len(bekend))
    r("losses", len(losses), n=len(bekend))
    r("breakeven", len(even), n=len(bekend))
    r("unknown_result_count", n - len(bekend))
    r("win_rate", round(len(wins) / len(bekend) * 100, 4) if bekend else None,
      VALID if bekend else leeg, teller=len(wins), noemer=len(bekend))

    bruto = sum(t["gross_pnl_instrument"] for t in trades)
    kosten = sum(t["total_cost_instrument"] for t in trades)
    netto = sum(bekend)
    r("gross_pnl", bruto)
    r("total_costs", kosten)
    r("net_pnl", netto)
    r("average_trade", netto / len(bekend) if bekend else None,
      VALID if bekend else leeg, teller=netto, noemer=len(bekend))
    r("median_trade", statistics.median(bekend) if bekend else None, VALID if bekend else leeg)
    r("average_win", sum(wins) / len(wins) if wins else None,
      VALID if wins else (leeg if not bekend else NOT_APPLICABLE),
      teller=sum(wins), noemer=len(wins), n=len(wins))
    r("average_loss", sum(losses) / len(losses) if losses else None,
      VALID if losses else (leeg if not bekend else NOT_APPLICABLE),
      teller=sum(losses), noemer=len(losses), n=len(losses))
    if not bekend:
        r("profit_factor", None, leeg)
    elif not losses:
        r("profit_factor", None, NOT_APPLICABLE, teller=sum(wins), noemer=0.0)
    else:
        r("profit_factor", sum(wins) / abs(sum(losses)), teller=sum(wins), noemer=abs(sum(losses)))
    if bekend:
        p_w, p_l = len(wins) / len(bekend), len(losses) / len(bekend)
        verwachting = ((p_w * (sum(wins) / len(wins)) if wins else 0.0)
                       + (p_l * (sum(losses) / len(losses)) if losses else 0.0))
        r("expectancy", verwachting, noemer=len(bekend))
    else:
        r("expectancy", None, leeg)
    r("largest_win", max(wins) if wins else None, VALID if wins else (leeg if not bekend else NOT_APPLICABLE))
    r("largest_loss", min(losses) if losses else None,
      VALID if losses else (leeg if not bekend else NOT_APPLICABLE))

    geordend = sorted(trades, key=lambda t: (t["closed_ts"], t["sequence_number"]))
    r("maximum_drawdown", _drawdown([t["net_pnl_instrument"] for t in geordend]) if n else None,
      VALID if n else leeg)
    # Geen impliciete startbalans: zonder expliciete basis bestaat dit getal niet.
    r("maximum_drawdown_pct", None, NOT_APPLICABLE,
      noemer=None, populatie=POP + "; geen expliciete kapitaalbasis opgegeven")

    omgerekend = [t for t in geordend if t["conversion_status"] == CONVERTED]
    if n and len(omgerekend) == n:
        r("maximum_drawdown_account", _drawdown([t["net_pnl_account"] for t in geordend]))
        r("net_pnl_account", sum(t["net_pnl_account"] for t in trades))
        r("fx_cost_account", sum(t["fx_cost_account"] for t in trades))
    else:
        status = leeg if not n else (UNKNOWN_INPUT if not omgerekend else PARTIAL)
        for naam in ("maximum_drawdown_account", "net_pnl_account", "fx_cost_account"):
            r(naam, None, status, teller=len(omgerekend), noemer=n)

    houd = [t["holding_seconds"] for t in trades]
    r("average_holding_seconds", sum(houd) / n if n else None, VALID if n else leeg)
    r("median_holding_seconds", statistics.median(houd) if n else None, VALID if n else leeg)
    r("p90_holding_seconds", _p90(houd) if n else None, VALID if n else leeg)

    dagen = sorted(set(dataset_days))
    d = len(dagen)
    per_dag = defaultdict(int)
    for t in trades:
        per_dag[t["trading_day"]] += 1
    telling = [per_dag.get(dag, 0) for dag in dagen]
    r("trading_days", d, tijdzone=HANDELSDAG_TZ, n=d)
    r("trades_per_day_mean", n / d if d else None, VALID if d else leeg,
      teller=n, noemer=d, tijdzone=HANDELSDAG_TZ, n=d)
    r("trades_per_day_median", statistics.median(telling) if d else None, VALID if d else leeg,
      noemer=d, tijdzone=HANDELSDAG_TZ, n=d)

    evaluaties = summary.get("evaluations")
    afgewezen = sum((summary.get("rejections") or {}).values())
    if evaluaties is None:
        for naam in ("signal_evaluations", "accepted_signals", "rejected_signals", "signals_per_day"):
            r(naam, None, UNKNOWN_INPUT)
    else:
        r("signal_evaluations", evaluaties, n=evaluaties)
        # Geaccepteerd = evaluaties die tot een trade leidden. Een positie die
        # bij het einde van de data nog openstond, is geaccepteerd maar niet
        # gesloten; daarom telt deze metriek evaluaties, niet trades.
        r("accepted_signals", evaluaties - afgewezen, teller=evaluaties - afgewezen,
          noemer=evaluaties, n=evaluaties)
        r("rejected_signals", afgewezen, teller=afgewezen, noemer=evaluaties, n=evaluaties)
        r("signals_per_day", evaluaties / d if d else None, VALID if d else leeg,
          teller=evaluaties, noemer=d, tijdzone=HANDELSDAG_TZ, n=d)

    for naam, som in (("gross_per_trade", bruto), ("cost_per_trade", kosten), ("net_per_trade", netto)):
        r(naam, som / n if n else None, VALID if n else leeg, teller=som, noemer=n)
    r("cost_per_day", kosten / d if d else None, VALID if d else leeg,
      teller=kosten, noemer=d, tijdzone=HANDELSDAG_TZ, n=d)

    dubbel = sum(t["ambiguous_exit"] for t in trades)
    r("ambiguous_exit_count", dubbel)
    r("ambiguous_exit_share", round(dubbel / n * 100, 4) if n else None,
      VALID if n else leeg, teller=dubbel, noemer=n)
    return uit


def rejection_breakdown(summary: dict) -> list[dict]:
    """Afgewezen evaluaties per code. De motor levert codes, geen tekst."""
    evaluaties = summary.get("evaluations") or 0
    return [
        {"code": code, "count": aantal,
         "share": round(aantal / evaluaties * 100, 4) if evaluaties else None,
         "denominator": evaluaties}
        for code, aantal in sorted((summary.get("rejections") or {}).items())
    ]


DIMENSIONS = {
    "trading_day": HANDELSDAG_TZ,
    "session": SESSIE_TZ,
    "regime": None,
    "close_reason": None,
}


def breakdowns(trades: list[dict], precision: int, cost_currency: str) -> list[dict]:
    """Uitsplitsingen per handelsdag, sessie, regime en sluitreden. Geen oordeel."""
    tol = breakeven_tolerance(precision, trades[0]["units"]) if trades else 0.0
    uit = []
    for dimensie, tz in DIMENSIONS.items():
        groepen: dict[str, list] = defaultdict(list)
        for t in trades:
            groepen[str(t[dimensie]) if t[dimensie] is not None else "onbekend"].append(t)
        for label in sorted(groepen):
            groep = groepen[label]
            netten = [t["net_pnl_instrument"] for t in groep]
            wins = sum(1 for x in netten if x > tol)
            uit.append({
                "dimension": dimensie, "label": label, "timezone": tz,
                "currency": cost_currency,
                "trade_count": len(groep), "sample_size": len(groep), "wins": wins,
                "gross": sum(t["gross_pnl_instrument"] for t in groep),
                "costs": sum(t["total_cost_instrument"] for t in groep),
                "net": sum(netten),
                "win_rate": round(wins / len(groep) * 100, 4),
                "win_rate_numerator": wins, "win_rate_denominator": len(groep),
                "expectancy": sum(netten) / len(groep),
            })
    return uit


# --------------------------------------------------------------------------- #
# invarianten - onafhankelijk nagelopen door de controller
# --------------------------------------------------------------------------- #

TOLERANCE = 1e-6


def check_invariants(trades: list[dict], metrics: list[dict], parts: list[dict]) -> list[str]:
    """Wat moet kloppen, of een lijst met wat niet klopt. Rekent geen handel."""
    fouten = []
    for t in trades:
        comps = (t["spread_cost_instrument"] + t["slippage_cost_instrument"]
                 + t["commission_cost_instrument"] + t["other_cost_instrument"])
        if abs(comps - t["total_cost_instrument"]) > TOLERANCE:
            fouten.append(f"trade {t['sequence_number']}: componenten != totaal")
        if abs(t["gross_pnl_instrument"] - t["total_cost_instrument"]
               - t["net_pnl_instrument"]) > TOLERANCE * max(1.0, abs(t["gross_pnl_instrument"])):
            fouten.append(f"trade {t['sequence_number']}: bruto - kosten != netto")
        if t["conversion_status"] == CONVERTED:
            if abs(t["gross_pnl_account"] - t["total_cost_account"] - t["net_pnl_account"]) > TOLERANCE:
                fouten.append(f"trade {t['sequence_number']}: accountformule sluit niet")
        elif any(t[v] is not None for v in ("gross_pnl_account", "total_cost_account",
                                             "net_pnl_account", "fx_cost_account")):
            fouten.append(f"trade {t['sequence_number']}: accountbedrag zonder omrekening")
    m = {x["metric_name"]: x for x in metrics}
    ontbrekend = set(REQUIRED_METRICS) - set(m)
    if ontbrekend:
        fouten.append(f"metrieken ontbreken: {sorted(ontbrekend)}")
        return fouten
    if m["trade_count"]["value"] != len(trades):
        fouten.append("trade_count past niet bij de trades")
    for naam, veld in (("gross_pnl", "gross_pnl_instrument"), ("total_costs", "total_cost_instrument"),
                       ("net_pnl", "net_pnl_instrument")):
        if abs(m[naam]["value"] - sum(t[veld] for t in trades)) > TOLERANCE * max(1, len(trades)):
            fouten.append(f"{naam} past niet bij de som van de trades")
    if abs(m["gross_pnl"]["value"] - m["total_costs"]["value"] - m["net_pnl"]["value"]) \
            > TOLERANCE * max(1, len(trades)):
        fouten.append("populatie: bruto - kosten != netto")
    for dimensie in DIMENSIONS:
        rijen = [p for p in parts if p["dimension"] == dimensie]
        if sum(p["trade_count"] for p in rijen) != len(trades):
            fouten.append(f"uitsplitsing {dimensie}: aantallen sluiten niet")
        if trades and abs(sum(p["net"] for p in rijen) - m["net_pnl"]["value"]) > TOLERANCE * len(trades):
            fouten.append(f"uitsplitsing {dimensie}: netto sluit niet")
    return fouten
