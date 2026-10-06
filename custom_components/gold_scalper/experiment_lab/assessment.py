"""Beoordeling van een walk-forwardexperiment: verklaarbaar, zonder totaalscore.

Een beoordeling bestaat uit afzonderlijke componenten. Elke component heeft een
status, een gemeten waarde, een voorwaarde en een uitleg. De classificatie volgt
uit **één** regelboek (``RULEBOOK``) en wordt daarna begrensd door plafonds: de
uitvoeringsgetrouwheid, het hergebruik van TEST-data en de opwarmkwaliteit.

Wat een classificatie **niet** is: een winstgarantie, een advies, toestemming
voor live handel, of een reden om iets te promoveren. ``ROBUST_OUT_OF_SAMPLE``
betekent uitsluitend: onder de geregistreerde datasets, kostenmodellen,
segmentregels en getrouwheidsbeperkingen bleven de gemeten resultaten
out-of-sample voldoende consistent volgens deze regels.

Deze module is pure logica. Het ophalen van TEST-resultaten - altijd via de
gelogde toegangsweg - en het opslaan gebeuren in ``storage.py``.
"""

from __future__ import annotations

import math
import statistics

from ..analysis.indicator_lab import drempel_t

ASSESSMENT_SCHEMA_VERSION = 1
#: 2 (1.1): component GROSS_EVIDENCE - het bruto OOS-resultaat per trade
#: tegen nul, vóór de nettotoets (onderzoeksopzet H_GROSS_OOS_PER_TRADE).
#: De classificatie blijft op netto; bruto is bewijs over het signaal, niet
#: over wat er na kosten overblijft.
ASSESSMENT_RULES_VERSION = 2

PASS, WARNING, FAIL = "PASS", "WARNING", "FAIL"
INSUFFICIENT_DATA, NOT_APPLICABLE, UNKNOWN_INPUT = "INSUFFICIENT_DATA", "NOT_APPLICABLE", "UNKNOWN_INPUT"

# Classificaties, van zwak naar sterk positief bewijs. De volgorde bepaalt alleen
# hoe plafonds werken; negatieve uitkomsten worden door een plafond nooit verhoogd.
INSUFF, NEEDS_OOS, NO_EVIDENCE = "INSUFFICIENT_DATA", "NEEDS_OUT_OF_SAMPLE", "NO_EVIDENCE"
NO_EDGE, OVERFIT = "LIKELY_NO_EDGE", "LIKELY_OVERFIT"
POSSIBLE, ROBUST = "POSSIBLE_EDGE", "ROBUST_OUT_OF_SAMPLE"
_STERKTE = {POSSIBLE: 1, ROBUST: 2}

HIGH_FID, LIMITED_FID, INSUFF_FID = (
    "HIGH_EXECUTION_FIDELITY", "LIMITED_EXECUTION_FIDELITY", "INSUFFICIENT_EXECUTION_FIDELITY")

#: Elke drempel met naam, waarde en onderbouwing. Er staat nergens anders een
#: getal in de beoordeling; een test controleert dat.
RULEBOOK: dict[str, dict] = {
    "MIN_OOS_TRADES": {
        "value": 30,
        "reason": "Zelfde minimum als de bestaande onderzoekslogica (MIN_PER_PERIOD en "
                  "MIN_PER_SESSION = 30); daaronder is de normale benadering van "
                  "drempel_t niet te verdedigen."},
    "MIN_OOS_WINDOWS": {
        "value": 3,
        "reason": "Zelfde als de robuustheidstoets (minstens drie periodes): met minder "
                  "vensters is spreiding tussen vensters niet te beoordelen."},
    "ALPHA": {
        "value": 0.05,
        "reason": "De standaard van drempel_t in het indicatorlab; Bonferroni over het "
                  "aantal geëvalueerde configuraties in de familie."},
    "MAJORITY_SHARE": {
        "value": 0.5,
        "reason": "Meerderheid: meer dan de helft. Gebruikt voor het aandeel positieve "
                  "vensters en voor concentratie in het beste venster."},
    "OVERFIT_MIN_SIGNALS": {
        "value": 2,
        "reason": "Eén signaal is onvoldoende voor LIKELY_OVERFIT; vereist is het verval "
                  "van TRAIN naar TEST plus minstens één ander signaal."},
}


def _r(naam: str):
    return RULEBOOK[naam]["value"]


def component(code, status, value=None, unit=None, n=None, condition="", blocking=False,
              explanation="", details=None, results=(), windows=()) -> dict:
    return {"component_code": code, "component_version": ASSESSMENT_RULES_VERSION,
            "status": status, "measured_value": value, "unit": unit, "sample_size": n,
            "required_condition": condition, "blocking": bool(blocking),
            "explanation": explanation, "details": details or {},
            "source_result_ids": sorted(results), "source_window_ids": sorted(windows)}


# --------------------------------------------------------------------------- #
# componenten
# --------------------------------------------------------------------------- #

def _test_vensters(inp):
    return [w for w in inp["windows"] if w.get("test")]


def _oos_nets(inp):
    return [t["net"] for w in _test_vensters(inp) for t in w["test"]["trades"]]


def c_compatibility(inp):
    versies = {w["test"]["versions"] for w in _test_vensters(inp)}
    valuta = {w["test"]["cost_currency"] for w in _test_vensters(inp)}
    ids = [w["test"]["result_id"] for w in _test_vensters(inp)]
    if not ids:
        return component("COMPATIBILITY", NOT_APPLICABLE, explanation="geen TEST-resultaten")
    ok = len(versies) == 1 and len(valuta) == 1
    return component("COMPATIBILITY", PASS if ok else FAIL, len(versies), "versiecombinaties",
                     len(ids), "één versiecombinatie en één valuta", not ok,
                     "compatibel" if ok else "incompatibele versies of valuta; niet samengevoegd",
                     {"versions": [list(v) for v in sorted(versies)], "currencies": sorted(valuta)},
                     ids, [w["window_id"] for w in _test_vensters(inp)])


def c_data_sufficiency(inp):
    tv = _test_vensters(inp)
    n, vensters = len(_oos_nets(inp)), len(tv)
    dagen = {t["trading_day"] for w in tv for t in w["test"]["trades"]}
    statussen = [w["status"] for w in inp["windows"]]
    detail = {"oos_trades": n, "completed_test_windows": vensters, "test_trading_days": len(dagen),
              "regimes": len({t["regime"] for w in tv for t in w["test"]["trades"]}),
              "no_selection_windows": statussen.count("NO_SELECTION"),
              "validation_rejected_windows": statussen.count("VALIDATION_REJECTED"),
              "failed_or_interrupted_windows": sum(s in ("FAILED", "INTERRUPTED", "CANCELLED")
                                                   for s in statussen),
              "complete_metric_share": (sum(1 for w in tv if w["test"]["metrics_complete"]) / vensters
                                        if vensters else None)}
    ok = n >= _r("MIN_OOS_TRADES") and vensters >= _r("MIN_OOS_WINDOWS")
    return component("DATA_SUFFICIENCY", PASS if ok else INSUFFICIENT_DATA, n, "OOS-trades", n,
                     f">= MIN_OOS_TRADES ({_r('MIN_OOS_TRADES')}) en >= MIN_OOS_WINDOWS "
                     f"({_r('MIN_OOS_WINDOWS')}) voltooide TEST-vensters", not ok,
                     f"{n} OOS-trades in {vensters} TEST-vensters", detail,
                     [w["test"]["result_id"] for w in tv], [w["window_id"] for w in tv])


def c_multiple_testing(inp):
    fam = inp["family"]
    toetsen = max(1, fam.get("evaluated_configurations", 1))
    drempel = drempel_t(toetsen, _r("ALPHA"))
    return component("MULTIPLE_TESTING", PASS, drempel, "t-drempel", toetsen,
                     "Bonferroni via drempel_t over het aantal geëvalueerde configuraties",
                     False, f"{toetsen} geëvalueerde configuratie(s) in de familie; vereiste t = {drempel}",
                     {"evaluated_configurations": toetsen, "unique_train_configurations":
                      fam.get("unique_train_configurations"), "reproductions": fam.get("reproductions"),
                      "test_accesses": fam.get("test_accesses"),
                      "reused_test_accesses": fam.get("reused_test_accesses"),
                      "overlapping_test_accesses": fam.get("overlapping_test_accesses"),
                      "method": "drempel_t: tweezijdig, normale benadering, geldig vanaf "
                                "MIN_OOS_TRADES trades"})


def c_statistics(inp, drempel):
    nets = _oos_nets(inp)
    n = len(nets)
    if n < 2:
        return component("STATISTICAL_EVIDENCE", INSUFFICIENT_DATA, None, "t", n,
                         "minstens twee OOS-trades", True, "te weinig trades voor een spreiding")
    gem, sd = statistics.mean(nets), statistics.stdev(nets)
    se = sd / math.sqrt(n) if sd > 0 else None
    t = gem / se if se else None
    ci = (gem - drempel * se, gem + drempel * se) if se else None
    if t is None:
        status, uitleg = UNKNOWN_INPUT, "geen spreiding: t niet te berekenen"
    elif t >= drempel:
        status, uitleg = PASS, f"t = {t:.2f} >= {drempel}: positief effect boven de gecorrigeerde drempel"
    elif t <= -drempel:
        status, uitleg = FAIL, f"t = {t:.2f} <= -{drempel}: negatief effect"
    else:
        status, uitleg = WARNING, f"|t| = {abs(t):.2f} < {drempel}: geen overtuigend effect"
    return component("STATISTICAL_EVIDENCE", status, t, "t", n, f"|t| >= {drempel} (gecorrigeerd)",
                     False, uitleg, {"mean": gem, "stdev": sd, "standard_error": se,
                                     "interval_at_threshold": ci, "threshold": drempel})


def c_window_consistency(inp):
    tv = _test_vensters(inp)
    nets = [(w["window_id"], w["test"]["metrics"].get("net_pnl", {}).get("value")) for w in tv]
    geldig = [(i, v) for i, v in nets if v is not None]
    if len(geldig) < _r("MIN_OOS_WINDOWS"):
        return component("WINDOW_CONSISTENCY", INSUFFICIENT_DATA, len(geldig), "vensters",
                         len(geldig), f">= MIN_OOS_WINDOWS ({_r('MIN_OOS_WINDOWS')})", False,
                         "te weinig TEST-vensters om spreiding te beoordelen",
                         windows=[i for i, _ in geldig])
    pos = sum(1 for _, v in geldig if v > 0)
    neg = sum(1 for _, v in geldig if v < 0)
    aandeel = pos / len(geldig)
    ok = aandeel > _r("MAJORITY_SHARE")
    return component("WINDOW_CONSISTENCY", PASS if ok else WARNING, aandeel, "aandeel positief",
                     len(geldig), f"aandeel positieve vensters > MAJORITY_SHARE ({_r('MAJORITY_SHARE')})",
                     False, f"{pos} positief, {neg} negatief, {len(geldig) - pos - neg} break-even",
                     {"net_per_window": dict(geldig), "positive": pos, "negative": neg,
                      "breakeven": len(geldig) - pos - neg,
                      "median_window_net": statistics.median(v for _, v in geldig),
                      "spread_stdev": statistics.stdev(v for _, v in geldig) if len(geldig) > 1 else None},
                     windows=[i for i, _ in geldig])


def _aandeel(delen: dict, totaal: float):
    """Aandeel van het grootste deel; alleen zinvol bij een positief totaal."""
    if not delen or totaal is None or totaal <= 0:
        return None
    return max(delen.values()) / totaal


def c_concentration(inp):
    tv = _test_vensters(inp)
    trades = [t for w in tv for t in w["test"]["trades"]]
    totaal = sum(t["net"] for t in trades) if trades else None
    groepen = {}
    for sleutel in ("trading_day", "regime", "session"):
        g = {}
        for t in trades:
            g[t[sleutel]] = g.get(t[sleutel], 0.0) + t["net"]
        groepen[sleutel] = _aandeel(g, totaal)
    per_venster = {w["window_id"]: sum(t["net"] for t in w["test"]["trades"]) for w in tv}
    groepen["window"] = _aandeel(per_venster, totaal)
    groepen["best_trade"] = (max(t["net"] for t in trades) / totaal) if trades and totaal and totaal > 0 else None
    if totaal is None or totaal <= 0:
        return component("RESULT_CONCENTRATION", NOT_APPLICABLE, None, "aandeel", len(trades),
                         "positief totaalresultaat", False,
                         "totaal niet positief: een concentratieaandeel heeft geen betekenis", groepen)
    zwaar = groepen["window"] is not None and groepen["window"] > _r("MAJORITY_SHARE")
    return component("RESULT_CONCENTRATION", WARNING if zwaar else PASS, groepen["window"],
                     "aandeel beste venster", len(trades),
                     f"beste venster <= MAJORITY_SHARE ({_r('MAJORITY_SHARE')}) van het totaal", False,
                     "meer dan de helft van het resultaat uit één venster" if zwaar
                     else "resultaat niet in één venster geconcentreerd", groepen)


def c_degradation(inp):
    paren = [(w["window_id"], w["train_selected"], w["test"]["metrics"].get("net_pnl", {}).get("value"))
             for w in _test_vensters(inp) if w.get("train_selected") is not None]
    if not paren:
        return component("TRAIN_TEST_DEGRADATION", NOT_APPLICABLE, None, None, 0,
                         "TRAIN-resultaat van de gekozen kandidaat", False,
                         "geen selectie (bijvoorbeeld SEQUENTIAL_OOS)")
    omgeslagen = sum(1 for _, tr, te in paren if tr is not None and te is not None and tr > 0 >= te)
    vergelijkbaar = sum(1 for _, tr, te in paren if tr is not None and te is not None)
    signaal = vergelijkbaar > 0 and omgeslagen / vergelijkbaar > _r("MAJORITY_SHARE")
    return component("TRAIN_TEST_DEGRADATION", WARNING if signaal else PASS,
                     omgeslagen / vergelijkbaar if vergelijkbaar else None, "aandeel omgeslagen",
                     vergelijkbaar, "meerderheid van de vensters niet omgeslagen van TRAIN > 0 naar TEST <= 0",
                     False, f"{omgeslagen} van {vergelijkbaar} vensters: TRAIN positief, TEST niet",
                     {"train_vs_test": [{"window_id": i, "train": tr, "test": te} for i, tr, te in paren],
                      "validation_rejected": sum(1 for w in inp["windows"]
                                                 if w["status"] == "VALIDATION_REJECTED"),
                      "overfit_signal": signaal},
                     windows=[i for i, _, _ in paren])


def c_cost_sensitivity(inp):
    return component("COST_SENSITIVITY", NOT_APPLICABLE, None, None, None,
                     "meerdere vooraf geregistreerde kostenscenario's", False,
                     "per experiment is één kostenmodel geregistreerd; er wordt geen scenario verzonnen")


def c_parameter_sensitivity(inp):
    kand = inp["candidates"]
    if len(kand) < 3:
        return component("PARAMETER_SENSITIVITY", NOT_APPLICABLE, None, None, len(kand),
                         "minstens drie kandidaten die in één parameter verschillen", False,
                         "te weinig kandidaten voor een lokale omgeving")
    verschil = _enige_verschil([k["config"] for k in kand])
    if verschil is None:
        return component("PARAMETER_SENSITIVITY", NOT_APPLICABLE, None, None, len(kand),
                         "kandidaten verschillen in precies één numerieke parameter", False,
                         "kandidaten zijn geen lokale parameteromgeving; geen schijnanalyse")
    per_venster = []
    for w in inp["windows"]:
        if w.get("selected_candidate_id") is None:
            continue
        rij = sorted(kand, key=lambda k: _pad(k["config"], verschil))
        pos = [i for i, k in enumerate(rij) if k["id"] == w["selected_candidate_id"]][0]
        buren = [rij[j] for j in (pos - 1, pos + 1) if 0 <= j < len(rij)]
        eigen = rij[pos]["train_nets"].get(w["window_index"])
        buur = [b["train_nets"].get(w["window_index"]) for b in buren]
        if eigen is None or any(b is None for b in buur):
            continue
        per_venster.append({"window_index": w["window_index"], "selected": eigen, "neighbours": buur,
                            "flip": eigen > 0 and all(b <= 0 for b in buur),
                            "mixed": eigen > 0 and any(b <= 0 for b in buur)})
    if not per_venster:
        return component("PARAMETER_SENSITIVITY", INSUFFICIENT_DATA, None, None, 0,
                         "TRAIN-resultaten van de gekozen kandidaat en zijn buren", False,
                         "geen vergelijkbare vensters")
    if any(v["flip"] for v in per_venster):
        status, uitleg = "VERY_SENSITIVE", "gekozen punt positief, alle buren niet: één exact punt domineert"
    elif any(v["mixed"] for v in per_venster):
        status, uitleg = "SENSITIVE", "buren wisselen van teken ten opzichte van het gekozen punt"
    else:
        status, uitleg = "STABLE", "buren gaan dezelfde kant op als het gekozen punt"
    return component("PARAMETER_SENSITIVITY", status, None, None, len(per_venster),
                     "regels: VERY_SENSITIVE als alle buren omslaan; SENSITIVE als een buur omslaat",
                     False, uitleg, {"parameter": ".".join(verschil), "windows": per_venster})


def _pad(config, pad):
    for deel in pad:
        config = config[deel]
    return config


def _enige_verschil(configs):
    """Het enige pad waarop de configuraties numeriek verschillen, of None."""
    def plat(d, voor=()):
        for k, v in d.items():
            if isinstance(v, dict):
                yield from plat(v, voor + (k,))
            else:
                yield voor + (k,), v
    vlak = [dict(plat(c)) for c in configs]
    sleutels = set().union(*vlak)
    verschillend = [s for s in sleutels if len({repr(v.get(s)) for v in vlak}) > 1]
    if len(verschillend) != 1 or not all(isinstance(v.get(verschillend[0]), (int, float)) for v in vlak):
        return None
    return verschillend[0]


def c_dataset_quality(inp):
    q = inp["dataset"]
    codes = sorted({f["code"] for f in q["findings"]})
    status = {"OK": PASS, "WARNING": WARNING, "BLOCKED": FAIL}[q["quality_status"]]
    return component("DATASET_QUALITY", status, None, None, None, "geen BLOCKED-dataset",
                     q["quality_status"] == "BLOCKED",
                     f"datasetstatus {q['quality_status']}; bevindingen: {', '.join(codes) or 'geen'}. "
                     "unknown_market_expectation is geen bewezen ontbrekende data.",
                     {"quality_status": q["quality_status"], "finding_codes": codes})


def c_warmup(inp):
    tv = _test_vensters(inp)
    deels = [w["window_id"] for w in tv if w["test"]["warmup_status"] != "FULL_WARMUP"]
    if not tv:
        return component("WARMUP_QUALITY", NOT_APPLICABLE)
    return component("WARMUP_QUALITY", WARNING if deels else PASS, len(deels) / len(tv),
                     "aandeel PARTIAL_WARMUP", len(tv), "alle TEST-vensters FULL_WARMUP", False,
                     f"{len(deels)} van {len(tv)} TEST-vensters met PARTIAL_WARMUP",
                     {"partial_windows": deels}, windows=[w["window_id"] for w in tv])


def c_forced_exits(inp):
    tv = _test_vensters(inp)
    n = sum(len(w["test"]["trades"]) for w in tv)
    einde = sum(w["test"]["segment_end_close_count"] for w in tv)
    grens = sum(w["test"]["cross_boundary_count"] for w in tv)
    if n == 0:
        return component("FORCED_EXITS", INSUFFICIENT_DATA, None, None, 0, "", False, "geen OOS-trades")
    gedwongen = [t["net"] for w in tv for t in w["test"]["trades"] if t["close_reason"] == "segment_end"]
    # Alleen NONE en PRESENT: voor MATERIAL bestaat nog geen onderbouwde grens.
    return component("FORCED_EXITS", PASS if einde == 0 else WARNING, einde / n,
                     "aandeel segment_end", n, "categorie NONE of PRESENT; geen harde grens", False,
                     "geen gedwongen sluitingen" if einde == 0
                     else f"{einde} gedwongen sluitingen aan het segmenteinde",
                     {"category": "NONE" if einde == 0 else "PRESENT",
                      "segment_end_close_count": einde, "segment_end_close_share": einde / n,
                      "cross_boundary_count": grens, "cross_boundary_share": grens / n,
                      "forced_exit_net": sum(gedwongen) if gedwongen else 0.0})


def c_fidelity(inp):
    tv = _test_vensters(inp)
    fid = [w["test"]["fidelity"] for w in tv]
    if not fid or any(not f for f in fid):
        return component("EXECUTION_FIDELITY", FAIL, INSUFF_FID, None, len(tv),
                         "getrouwheidsgegevens bij elk resultaat", True, "getrouwheid onbekend",
                         {"level": INSUFF_FID})
    modellen = {f.get("simulation_model") for f in fid}
    niveau = HIGH_FID if modellen <= {"QUOTE_REPLAY", "LIVE_OBSERVED"} else LIMITED_FID
    dubbel = sum(f.get("ambiguous_exits", 0) for f in fid)
    beperkingen = sorted({b for f in fid for b in f.get("known_limitations", [])})
    return component("EXECUTION_FIDELITY", WARNING if niveau != HIGH_FID else PASS, niveau, None,
                     len(tv), "QUOTE_REPLAY of LIVE_OBSERVED voor HIGH", False,
                     f"simulatie {', '.join(sorted(m or '?' for m in modellen))}: "
                     "exits alleen op barinformatie, intrabarvolgorde onbekend (stop eerst), "
                     "live spread en slippage kunnen afwijken",
                     {"level": niveau, "simulation_models": sorted(m or "?" for m in modellen),
                      "ambiguous_exits": dubbel, "known_limitations": beperkingen,
                      "live_validation_available": False})


def c_test_independence(inp):
    toegang = inp["access"]
    hergebruik = sum(1 for a in toegang if a["data_reused"])
    overlap = sum(1 for a in toegang if a["overlapping_prior_count"] > 0)
    zwaar = any(a["prior_access_count"] > 1 for a in toegang)
    if not toegang:
        status = "UNKNOWN"
    elif zwaar:
        status = "HEAVILY_REUSED"
    elif hergebruik:
        status = "REUSED"
    elif overlap:
        status = "OVERLAPPING"
    else:
        status = "INDEPENDENT"
    return component("TEST_INDEPENDENCE", status, hergebruik, "hergebruikte vensters", len(toegang),
                     "INDEPENDENT: geen eerder geopende identieke of overlappende TEST-data", False,
                     "regels: HEAVILY_REUSED bij meer dan één eerdere toegang tot hetzelfde interval; "
                     "REUSED bij één; OVERLAPPING bij overlappende intervallen",
                     {"accesses": toegang, "reused_windows": hergebruik, "overlapping_windows": overlap})


# --------------------------------------------------------------------------- #
# classificatie
# --------------------------------------------------------------------------- #

def _oos_grosses(inp):
    return [t["gross"] for w in _test_vensters(inp) for t in w["test"]["trades"]
            if t.get("gross") is not None]


def c_gross(inp, drempel):
    """H_GROSS_OOS_PER_TRADE: gemiddeld bruto per trade tegen nul, tweezijdig.

    Zelfde drempel als de nettotoets. Niet blokkerend en geen invloed op de
    classificatie: het beantwoordt of het signaal vóór kosten iets doet.
    """
    bruto = _oos_grosses(inp)
    n = len(bruto)
    if n < 2:
        return component("GROSS_EVIDENCE", INSUFFICIENT_DATA, None, "t", n,
                         "minstens twee OOS-trades met bruto resultaat", False,
                         "te weinig trades voor een spreiding")
    gem, sd = statistics.mean(bruto), statistics.stdev(bruto)
    se = sd / math.sqrt(n) if sd > 0 else None
    t = gem / se if se else None
    if t is None:
        status, uitleg = UNKNOWN_INPUT, "geen spreiding: t niet te berekenen"
    elif t >= drempel:
        status, uitleg = PASS, f"bruto t = {t:.2f} >= {drempel}: positief signaal vóór kosten"
    elif t <= -drempel:
        status, uitleg = FAIL, f"bruto t = {t:.2f} <= -{drempel}: negatief signaal vóór kosten"
    else:
        status, uitleg = WARNING, f"bruto |t| = {abs(t):.2f} < {drempel}: geen signaal vóór kosten aangetoond"
    netto = _oos_nets(inp)
    return component("GROSS_EVIDENCE", status, t, "t", n,
                     f"|t| >= {drempel} (gecorrigeerd), tweezijdig", False, uitleg,
                     {"hypothesis": "H_GROSS_OOS_PER_TRADE", "mean_gross": gem, "stdev": sd,
                      "standard_error": se, "threshold": drempel,
                      "mean_net": statistics.mean(netto) if netto else None,
                      "mean_cost": (gem - statistics.mean(netto)) if netto else None})


def assess(inp: dict) -> dict:
    """Componenten, ruwe classificatie, plafonds, eindclassificatie en spoor."""
    mt = c_multiple_testing(inp)
    comps = [c_compatibility(inp), c_data_sufficiency(inp), mt,
             c_gross(inp, mt["measured_value"]),
             c_statistics(inp, mt["measured_value"]), c_window_consistency(inp),
             c_concentration(inp), c_degradation(inp), c_cost_sensitivity(inp),
             c_parameter_sensitivity(inp), c_dataset_quality(inp), c_warmup(inp),
             c_forced_exits(inp), c_fidelity(inp), c_test_independence(inp)]
    c = {x["component_code"]: x for x in comps}
    spoor = []

    def stap(regel, uitkomst):
        spoor.append({"rule": regel, "result": uitkomst})

    if not _test_vensters(inp):
        ruw = NEEDS_OOS
        stap("geen voltooid TEST-venster via de gelogde route", ruw)
    elif c["COMPATIBILITY"]["status"] == FAIL:
        ruw = INSUFF
        stap("incompatibele versies of valuta: geen samenvoeging", ruw)
    elif c["DATASET_QUALITY"]["status"] == FAIL:
        ruw = INSUFF
        stap("dataset BLOCKED", ruw)
    elif c["DATA_SUFFICIENCY"]["status"] != PASS:
        ruw = INSUFF
        stap("datavoldoendeheid niet gehaald", ruw)
    else:
        signalen = [s for s, aan in (
            ("TRAIN_TEST_DEGRADATION", c["TRAIN_TEST_DEGRADATION"]["status"] == WARNING),
            ("MULTIPLE_TESTING", mt["sample_size"] > 1),
            ("TEST_INDEPENDENCE", c["TEST_INDEPENDENCE"]["status"] in ("REUSED", "HEAVILY_REUSED", "OVERLAPPING")),
            ("PARAMETER_SENSITIVITY", c["PARAMETER_SENSITIVITY"]["status"] == "VERY_SENSITIVE"),
            ("RESULT_CONCENTRATION", c["RESULT_CONCENTRATION"]["status"] == WARNING),
            # Alleen een signaal als het totaal positief is terwijl de meerderheid
            # van de vensters dat niet is: dan hangt het resultaat aan een paar
            # vensters. Consequent negatieve vensters zijn niet inconsistent.
            ("WINDOW_CONSISTENCY", c["WINDOW_CONSISTENCY"]["status"] == WARNING
             and sum(_oos_nets(inp)) > 0),
        ) if aan]
        st = c["STATISTICAL_EVIDENCE"]["status"]
        if "TRAIN_TEST_DEGRADATION" in signalen and len(signalen) >= _r("OVERFIT_MIN_SIGNALS"):
            ruw = OVERFIT
            stap(f"verval TRAIN->TEST plus {len(signalen) - 1} ander(e) signaal/signalen: {signalen}", ruw)
        elif st == FAIL:
            ruw = NO_EDGE
            stap("OOS-effect significant negatief (t <= -drempel)", ruw)
        elif st != PASS:
            ruw = NO_EVIDENCE
            stap("OOS-effect niet boven de gecorrigeerde drempel", ruw)
        else:
            robuust = (c["WINDOW_CONSISTENCY"]["status"] == PASS
                       and c["RESULT_CONCENTRATION"]["status"] == PASS
                       and c["TEST_INDEPENDENCE"]["status"] == "INDEPENDENT"
                       and c["PARAMETER_SENSITIVITY"]["status"] != "VERY_SENSITIVE"
                       and c["WARMUP_QUALITY"]["status"] == PASS)
            ruw = ROBUST if robuust else POSSIBLE
            stap("positief OOS-effect boven de drempel; "
                 + ("alle robuustheidsvoorwaarden voldaan" if robuust
                    else "niet alle robuustheidsvoorwaarden voldaan"), ruw)
        spoor.append({"rule": "overfitsignalen", "result": signalen})

    plafond = ROBUST
    redenen = []
    niveau = c["EXECUTION_FIDELITY"]["details"].get("level", INSUFF_FID)
    if niveau == LIMITED_FID:
        plafond = POSSIBLE
        redenen.append("LIMITED_EXECUTION_FIDELITY: maximaal POSSIBLE_EDGE")
    if niveau == INSUFF_FID:
        plafond = NO_EVIDENCE
        redenen.append("INSUFFICIENT_EXECUTION_FIDELITY: geen positieve classificatie")
    if c["TEST_INDEPENDENCE"]["status"] in ("REUSED", "HEAVILY_REUSED"):
        plafond = _laagste(plafond, POSSIBLE)
        redenen.append("DATA_REUSED: maximaal POSSIBLE_EDGE")
    if c["WARMUP_QUALITY"]["status"] == WARNING:
        plafond = _laagste(plafond, POSSIBLE)
        redenen.append("PARTIAL_WARMUP in een TEST-venster: maximaal POSSIBLE_EDGE")
    eind = _begrens(ruw, plafond)
    spoor.append({"rule": "plafonds", "result": redenen or ["geen"]})
    return {"components": comps, "raw_classification": ruw, "fidelity_ceiling": niveau,
            "classification_ceiling": plafond, "final_classification": eind, "trace": spoor,
            "explanation": _uitleg(ruw, eind, redenen),
            "blocking": [x["component_code"] for x in comps if x["blocking"]],
            "warnings": [x["component_code"] for x in comps if x["status"] in (WARNING, "SENSITIVE",
                                                                              "VERY_SENSITIVE")]}


def _laagste(a, b):
    return a if _STERKTE.get(a, 0) <= _STERKTE.get(b, 0) else b


def _begrens(ruw, plafond):
    """Een plafond verlaagt alleen positieve classificaties."""
    if ruw not in _STERKTE:
        return ruw
    if plafond not in _STERKTE:
        return plafond
    return ruw if _STERKTE[ruw] <= _STERKTE[plafond] else plafond


def _uitleg(ruw, eind, redenen):
    tekst = f"Ruwe classificatie {ruw}"
    if eind != ruw:
        tekst += f", begrensd tot {eind} ({'; '.join(redenen)})"
    return (tekst + ". Onderzoeksclassificatie van historische backtestdata; geen advies, "
            "geen winstgarantie, geen toestemming voor live handel.")
