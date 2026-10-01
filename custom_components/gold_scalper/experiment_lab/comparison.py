"""Reference tegenover challenger: vergelijken zonder winnaar.

Er bestaat hier geen veld ``winner``, geen ``best_strategy``, geen promotie en
geen route naar de actieve configuratie. Een vergelijking toont per onderdeel de
waarde van beide kanten, het verschil als dat mathematisch en semantisch
verantwoord is, en waarom het anders niet wordt berekend.

Vergelijkbaarheid gaat vóór alles. Dezelfde datasetnaam is niet genoeg: hash,
periode, vensters, versies, valuta, kostenmodel en getrouwheid worden elk apart
gecontroleerd.
"""

from __future__ import annotations

COMPARISON_SCHEMA_VERSION = 1
COMPARISON_RULES_VERSION = 1

ASSESSMENT_COMPARISON, DEEP_RESULT_COMPARISON = "ASSESSMENT_COMPARISON", "DEEP_RESULT_COMPARISON"
DIRECT, PARTIAL, NOT_COMPARABLE = "DIRECTLY_COMPARABLE", "PARTIALLY_COMPARABLE", "NOT_COMPARABLE"
SAME, DIFFERENT, UNKNOWN = "SAME", "DIFFERENT", "UNKNOWN"
COMPARED, INSUFFICIENT_COMPARABILITY = "COMPARED", "INSUFFICIENT_COMPARABILITY"

#: Controles die bij een verschil elke directe vergelijking uitsluiten.
HARD = ("dataset_hash", "window_intervals", "instrument_currency")
#: Controles die bij een verschil de vergelijking gedeeltelijk maken.
SOFT = ("symbol", "timeframe", "dataset_period", "dataset_bar_count", "dataset_quality_status",
        "segment_schema_version", "walk_forward_schema_version", "window_count", "window_type",
        "cost_model", "metrics_version", "result_schema_version", "backtest_engine_version",
        "execution_semantics_version", "strategy_version", "conversion_status",
        "execution_fidelity", "assessment_rules_version", "candidate_set_hash", "selection_rule")

#: Richting per metriek, onderdeel van deze regelversie. Alleen informatief:
#: er volgt nooit een winnaar uit. None = geen richting.
DIRECTION = {
    "net_pnl": "HIGHER", "gross_pnl": "HIGHER", "expectancy": "HIGHER", "profit_factor": "HIGHER",
    "win_rate": "HIGHER", "average_win": "HIGHER", "average_trade": "HIGHER",
    "median_trade": "HIGHER", "gross_per_trade": "HIGHER", "net_per_trade": "HIGHER",
    "total_costs": "LOWER", "cost_per_trade": "LOWER", "maximum_drawdown": "LOWER",
    "ambiguous_exit_share": "LOWER",
}
#: Metrieken waarin kosten zitten: alleen vergelijkbaar bij hetzelfde kostenmodel.
COST_DEPENDENT = {"net_pnl", "total_costs", "expectancy", "profit_factor", "win_rate", "average_win",
                  "average_loss", "average_trade", "median_trade", "cost_per_trade", "net_per_trade",
                  "maximum_drawdown", "largest_win", "largest_loss", "cost_per_day"}
FID_ORDER = {"INSUFFICIENT_EXECUTION_FIDELITY": 0, "LIMITED_EXECUTION_FIDELITY": 1,
             "HIGH_EXECUTION_FIDELITY": 2}


def checks(ref: dict, ch: dict) -> list[dict]:
    """Eén controle per onderdeel. ``ref`` en ``ch`` zijn kanten met dezelfde sleutels."""
    uit = []
    for code in HARD + SOFT:
        a, b = ref.get(code), ch.get(code)
        status = UNKNOWN if a is None or b is None else (SAME if a == b else DIFFERENT)
        uit.append({"check_code": code, "reference": a, "challenger": b, "status": status,
                    "severity": "HARD" if code in HARD else "SOFT"})
    return uit


def comparability(cs: list[dict]) -> tuple[str, list[str]]:
    hard = [c["check_code"] for c in cs if c["severity"] == "HARD" and c["status"] != SAME]
    zacht = [c["check_code"] for c in cs if c["severity"] == "SOFT" and c["status"] != SAME]
    if hard:
        return NOT_COMPARABLE, [f"{c} verschilt of is onbekend" for c in hard]
    if zacht:
        return PARTIAL, [f"{c} verschilt of is onbekend" for c in zacht]
    return DIRECT, ["dataset, vensters, valuta, kosten, versies en getrouwheid gelijk"]


def _same(cs, code):
    return next(c for c in cs if c["check_code"] == code)["status"] == SAME


def metric_delta(naam: str, a: dict | None, b: dict | None, cs: list[dict]) -> dict:
    """Verschil van één metriek, alleen als dat verantwoord is."""
    uit = {"section": "metric", "key": naam, "direction": DIRECTION.get(naam),
           "reference": a and a.get("value"), "challenger": b and b.get("value"),
           "unit": (a or b or {}).get("unit"), "currency": (a or b or {}).get("currency"),
           "reference_n": a and a.get("sample_size"), "challenger_n": b and b.get("sample_size"),
           "absolute_delta": None, "relative_delta": None}
    if not (_same(cs, "dataset_hash") and _same(cs, "window_intervals")):
        return {**uit, "status": NOT_COMPARABLE, "explanation": "andere data of andere TEST-vensters"}
    if not (_same(cs, "metrics_version") and _same(cs, "instrument_currency")):
        return {**uit, "status": NOT_COMPARABLE, "explanation": "andere metriekversie of valuta"}
    if naam in COST_DEPENDENT and not _same(cs, "cost_model"):
        return {**uit, "status": NOT_COMPARABLE,
                "explanation": "ander kostenmodel: netto niet op dezelfde kostenbasis"}
    if not a or not b or a.get("calculation_status") != "VALID" or b.get("calculation_status") != "VALID":
        return {**uit, "status": "NOT_APPLICABLE", "explanation": "een van beide waarden is niet geldig"}
    va, vb = a["value"], b["value"]
    rel = (vb - va) / abs(va) if va not in (0, 0.0) else None
    return {**uit, "status": "COMPARED", "absolute_delta": vb - va, "relative_delta": rel,
            "explanation": "relatief verschil niet zinvol: referentie is nul" if rel is None
            else "vergeleken"}


def component_delta(code: str, a: dict | None, b: dict | None) -> dict:
    """Status en waarde naast elkaar; geen 'beter' of 'slechter' zonder eenduidige semantiek."""
    sa, sb = a and a["status"], b and b["status"]
    tekst = "geen verschil" if sa == sb else f"reference {sa}, challenger {sb}"
    if code == "TEST_INDEPENDENCE" and sa == "INDEPENDENT" and sb in ("REUSED", "HEAVILY_REUSED", "OVERLAPPING"):
        tekst = "lagere TEST-onafhankelijkheid bij challenger"
    elif code == "TEST_INDEPENDENCE" and sb == "INDEPENDENT" and sa in ("REUSED", "HEAVILY_REUSED", "OVERLAPPING"):
        tekst = "lagere TEST-onafhankelijkheid bij reference"
    return {"section": "component", "key": code, "reference": sa, "challenger": sb,
            "reference_value": a and a.get("measured_value"), "challenger_value": b and b.get("measured_value"),
            "reference_n": a and a.get("sample_size"), "challenger_n": b and b.get("sample_size"),
            "status": SAME if sa == sb else DIFFERENT, "explanation": tekst,
            "details": {"reference_blocking": a and a.get("blocking"),
                        "challenger_blocking": b and b.get("blocking"),
                        "reference_version": a and a.get("component_version"),
                        "challenger_version": b and b.get("component_version")}}


def flags(ref: dict, ch: dict, metric_items: list[dict]) -> list[str]:
    """Waarschuwingen die altijd zichtbaar moeten zijn."""
    uit = []
    fr, fc = FID_ORDER.get(ref.get("execution_fidelity"), -1), FID_ORDER.get(ch.get("execution_fidelity"), -1)
    net = next((m for m in metric_items if m["key"] == "net_pnl" and m["status"] == "COMPARED"), None)
    gunstiger_ch = (net and net["absolute_delta"] > 0) or ch.get("final_rank", 0) > ref.get("final_rank", 0)
    gunstiger_ref = (net and net["absolute_delta"] < 0) or ref.get("final_rank", 0) > ch.get("final_rank", 0)
    if gunstiger_ch and fc < fr:
        uit.append("RESULT_WITH_LOWER_FIDELITY: challenger oogt gunstiger bij lagere getrouwheid")
    if gunstiger_ref and fr < fc:
        uit.append("RESULT_WITH_LOWER_FIDELITY: reference oogt gunstiger bij lagere getrouwheid")
    for kant, d in (("reference", ref), ("challenger", ch)):
        if d.get("test_independence") in ("REUSED", "HEAVILY_REUSED", "OVERLAPPING"):
            uit.append(f"TEST_REUSED: {kant} heeft {d['test_independence']} TEST-data")
    if ref.get("assessment_rules_version") != ch.get("assessment_rules_version"):
        uit.append("ASSESSMENT_RULES_DIFFER: classificaties komen uit verschillende regelversies")
    return uit


#: Volgorde van classificaties alleen voor de waarschuwing hierboven; nooit
#: om een winnaar aan te wijzen.
CLASS_RANK = {"POSSIBLE_EDGE": 1, "ROBUST_OUT_OF_SAMPLE": 2}
