"""De kern van de uitvoering: één experiment, op één verzegelde dataset.

Dezelfde kern draait in een thread of in een apart proces. Ze krijgt alleen
een ``RunRequest`` met gewone waarden - identificatie, het pad naar de
Lab-database, de configuratie - en opent de Lab-database zelf **alleen-lezend**.
Er gaat geen databaseverbinding, geen ``hass``, geen coordinator en geen broker
over de grens.

De kern schrijft niets. De controller is de enige schrijver in de
Lab-database; de kern levert alleen een resultaat terug.
"""

from __future__ import annotations

import bisect
import hashlib
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..analysis.backtest import BACKTEST_ENGINE_VERSION, WARMUP_BARS, run_backtest
from ..analysis.signals import Candles
from ..broker.exits import ExitConfig
from ..strategy.scalping import ScalpConfig
from ..timeutil import trading_day
from .costs import COST_MODEL_VERSION, build_cost_model
from .datasets import CanonicalBar, DatasetSpec, dataset_hash
from .metrics import (
    METRICS_VERSION, breakdowns, compute_metrics, normalize_trade, rejection_breakdown,
)
from .models import canonical_json, config_hash
from .segments import (
    FORCED_EXIT_COST_RULE, FORCED_EXIT_FIDELITY, FORCED_EXIT_POLICY,
    FORCED_EXIT_PRICE_RULE, KINDS, SEGMENT_SCHEMA_VERSION,
)
from .walk_forward import WALK_FORWARD_SCHEMA_VERSION

#: Versie van de resultaatvorm. 1 = technisch resultaat met trades als JSON
#: (fase 3, LEGACY_TECHNICAL_RESULT). 2 = genormaliseerde trades, kosten per
#: component, metrieken en uitsplitsingen (NORMALIZED_METRICS_RESULT).
RESULT_SCHEMA_VERSION = 2


class Cancelled(Exception):
    """Coöperatief geannuleerd. Nooit een voltooid resultaat."""


class RunError(ValueError):
    """De aanvraag of de dataset deugt niet; er is niets uitgevoerd."""


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Alles wat de uitvoering krijgt. Uitsluitend gewone waarden."""

    experiment_id: int
    dataset_id: int
    dataset_hash: str
    lab_db_path: str
    config: dict
    config_hash: str
    #: Het vergrendelde segmentplan als gewone gegevens, of None voor een
    #: ongesegmenteerde uitvoering (fase 4).
    segment_plan: dict | None = None
    #: Eén segment (walk-forward, fase 6): {kind, start_ts, end_ts,
    #: warmup_start_ts, open_cutoff_ts, warmup_status}. Gewone gegevens.
    single_segment: dict | None = None

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


#: Welke configuratiesleutels er zijn. Onbekende sleutels worden geweigerd:
#: een tikfout mag niet stil een standaardwaarde opleveren.
_SCALP_VELDEN = {f.name for f in fields(ScalpConfig)}
_EXIT_VELDEN = {f.name for f in fields(ExitConfig)}
_UITVOERING_VELDEN = {
    "spread", "slippage", "units", "invert", "instrument_currency", "fx_conversion",
}


def build_configs(config: dict) -> tuple[ScalpConfig, ExitConfig, dict]:
    onbekend = set(config) - {"strategy", "exits", "execution"}
    if onbekend:
        raise RunError(f"onbekende configuratieonderdelen: {sorted(onbekend)}")
    strategie = config.get("strategy") or {}
    exits = config.get("exits") or {}
    uitvoering = config.get("execution") or {}
    for naam, deel, toegestaan in (
        ("strategy", strategie, _SCALP_VELDEN), ("exits", exits, _EXIT_VELDEN),
        ("execution", uitvoering, _UITVOERING_VELDEN),
    ):
        fout = set(deel) - toegestaan
        if fout:
            raise RunError(f"onbekende sleutels in {naam}: {sorted(fout)}")
    return ScalpConfig(**strategie), ExitConfig(**exits), dict(uitvoering)


def _uit_geheel(waarde: int, precisie: int) -> str:
    stap = Decimal(1).scaleb(-precisie)
    return format(Decimal(waarde).scaleb(-precisie).quantize(stap), "f")


def read_sealed_dataset(path: str, dataset_id: int, verwachte_hash: str):
    """De verzegelde dataset, alleen-lezend, en opnieuw geverifieerd.

    Nogmaals controleren in de kern zelf: tussen de controle van de controller
    en het starten van de uitvoering mag niets zijn veranderd.
    """
    pad = Path(path).resolve()
    conn = sqlite3.connect(f"file:{pad}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        ds = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if ds is None:
            raise RunError(f"dataset {dataset_id} bestaat niet")
        if ds["sealed"] != 1:
            raise RunError(f"dataset {dataset_id} is niet verzegeld")
        if ds["hash"] != verwachte_hash:
            raise RunError("de dataset hoort niet bij deze aanvraag")
        p = ds["instrument_precision"]
        rijen = conn.execute(
            "SELECT * FROM dataset_bars WHERE dataset_id=? ORDER BY ts", (dataset_id,)
        ).fetchall()
    finally:
        conn.close()

    bars = [
        CanonicalBar(r["ts"], _uit_geheel(r["open"], p), _uit_geheel(r["high"], p),
                     _uit_geheel(r["low"], p), _uit_geheel(r["close"], p),
                     r["volume"], r["source"], r["bar_status"])
        for r in rijen
    ]
    spec = DatasetSpec(ds["symbol"], ds["timeframe"], p, ds["precision_origin"],
                       ds["source"], ds["timezone"])
    if len(bars) != ds["bar_count"] or dataset_hash(spec, bars) != ds["hash"]:
        raise RunError("de opgeslagen dataset klopt niet met zijn eigen hash")
    candles = Candles(
        [b.ts for b in bars], [float(b.open) for b in bars],
        [float(b.high) for b in bars], [float(b.low) for b in bars],
        [float(b.close) for b in bars],
        # Een ontbrekend volume wordt 0: de strategie gebruikt geen volume.
        [float(b.volume) if b.volume not in (None, "-") else 0.0 for b in bars],
    )
    return candles, dict(ds)


def execute(request: RunRequest, should_stop, on_progress) -> dict:
    """Voer één experiment uit en geef het technische resultaat terug.

    ``should_stop()`` wordt tussendoor gevraagd; is het antwoord ja, dan stopt
    de uitvoering met ``Cancelled``. ``on_progress(verwerkt, totaal)`` krijgt
    de voortgang. De kern schrijft zelf niets weg.
    """
    if config_hash(request.config) != request.config_hash:
        raise RunError("de configuratie hoort niet bij de opgegeven configuratiehash")
    strategie, exits, uitvoering = build_configs(request.config)
    candles, ds = read_sealed_dataset(
        request.lab_db_path, request.dataset_id, request.dataset_hash,
    )

    def voortgang(verwerkt: int, totaal: int) -> None:
        if should_stop():
            raise Cancelled()
        on_progress(verwerkt, totaal)

    kostenmodel = build_cost_model(uitvoering)
    if request.single_segment is not None:
        return _single(request, candles, ds, strategie, exits, uitvoering,
                       kostenmodel, should_stop, on_progress)
    if request.segment_plan is not None:
        return _segmented(request, candles, ds, strategie, exits, uitvoering,
                          kostenmodel, should_stop, on_progress)
    resultaat = run_backtest(
        candles, strategie, exits,
        spread=kostenmodel["spread_model"]["value_per_unit"],
        slippage=kostenmodel["slippage_model"]["value_per_unit"],
        units=float(uitvoering.get("units", 1.0)),
        invert=bool(uitvoering.get("invert", False)),
        progress=voortgang,
    )
    samenvatting = resultaat.summary()
    trades = [
        normalize_trade(i, t.as_record(), kostenmodel)
        for i, t in enumerate(resultaat.trades, start=1)
    ]
    precisie = ds["instrument_precision"]
    # Handelsdagen van de dataset zelf: elke dag met minstens één bar, ook
    # zonder trade. Anders tellen alleen dagen mét trades en is de frequentie
    # stelselmatig te hoog.
    dagen = sorted({
        trading_day(datetime.fromtimestamp(ts, timezone.utc)).isoformat()
        for ts in candles.timestamp
    })
    return {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "summary": samenvatting,
        "trades": trades,
        "metrics": compute_metrics(trades, samenvatting, dagen, precisie, kostenmodel),
        "breakdowns": breakdowns(trades, precisie, kostenmodel["cost_currency"]),
        "rejections": rejection_breakdown(samenvatting),
        "cost_model": kostenmodel,
        "versions": {
            "backtest_engine_version": BACKTEST_ENGINE_VERSION,
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "cost_model_version": COST_MODEL_VERSION,
            "metrics_version": METRICS_VERSION,
        },
        # Vingerafdruk van de technische uitkomst: samenvatting en
        # genormaliseerde trades. Uit de opgeslagen rijen opnieuw te berekenen.
        "result_hash": result_hash(samenvatting, trades),
        "provenance": {
            "dataset_id": request.dataset_id,
            "dataset_hash": request.dataset_hash,
            "dataset_quality_status": ds["quality_status"],
            "dataset_quality": ds["quality_json"],
            "config_hash": request.config_hash,
            "backtest_engine_version": BACKTEST_ENGINE_VERSION,
            "bars": len(candles),
            "instrument_precision": precisie,
        },
    }


def result_hash(samenvatting: dict, trades: list[dict]) -> str:
    return hashlib.sha256(
        canonical_json({"summary": samenvatting, "trades": trades}).encode("utf-8")
    ).hexdigest()


def _plak(candles: Candles, van: int, tot: int) -> Candles:
    """Bars met ``van <= ts < tot``. Nooit een bar op of na ``tot``."""
    i = bisect.bisect_left(candles.timestamp, van)
    j = bisect.bisect_left(candles.timestamp, tot)
    return Candles(candles.timestamp[i:j], candles.open[i:j], candles.high[i:j],
                   candles.low[i:j], candles.close[i:j], candles.volume[i:j])


def _segmented(request, candles, ds, strategie, exits, uitvoering, kostenmodel,
               should_stop, on_progress) -> dict:
    """TRAIN, VALIDATION en TEST, na elkaar, elk op zijn eigen plak.

    Elk segment krijgt zijn opwarmbars en zijn evaluatie-interval, en **nooit**
    een bar op of na zijn einde. Daarmee kan een later segment - ook TEST -
    niet in een eerder segment lekken, ook niet via de exit van een open
    positie. Per segment dezelfde keten als in fase 4.
    """
    plan = request.segment_plan
    segmenten = plan["segments"]
    if [s["kind"] for s in segmenten] != list(KINDS):
        raise RunError("het segmentplan heeft niet precies TRAIN, VALIDATION, TEST")
    if exits.max_hold_seconds > plan["max_hold_seconds"]:
        raise RunError("de maximale houdtijd van de configuratie is langer dan in het plan")
    plakken = [_plak(candles, s["warmup_start_ts"], s["end_ts"]) for s in segmenten]
    totalen = [max(0, len(p) - 1 - WARMUP_BARS) for p in plakken]
    totaal = sum(totalen)
    precisie = ds["instrument_precision"]
    uit = []

    for n, (seg, plak) in enumerate(zip(segmenten, plakken)):
        offset = sum(totalen[:n])

        def voortgang(verwerkt: int, _totaal: int, _offset=offset, _soort=seg["kind"], _n=n):
            if should_stop():
                raise Cancelled()
            on_progress(_offset + verwerkt, totaal, segment=_soort,
                        segments_completed=_n, segments_total=len(segmenten))

        uit.append(_run_segment(seg, plak, strategie, exits, uitvoering, kostenmodel,
                                precisie, voortgang))
        on_progress(offset + totalen[n], totaal, segment=seg["kind"],
                    segments_completed=n + 1, segments_total=len(segmenten))

    return {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "segmented": True,
        "segments": uit,
        "cost_model": kostenmodel,
        "versions": {
            "backtest_engine_version": BACKTEST_ENGINE_VERSION,
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "cost_model_version": COST_MODEL_VERSION,
            "metrics_version": METRICS_VERSION,
            "segment_schema_version": SEGMENT_SCHEMA_VERSION,
        },
        "result_hash": hashlib.sha256(
            canonical_json([s["result_hash"] for s in uit]).encode("utf-8")
        ).hexdigest(),
        "provenance": {
            "dataset_id": request.dataset_id, "dataset_hash": request.dataset_hash,
            "dataset_quality_status": ds["quality_status"],
            "dataset_quality": ds["quality_json"],
            "config_hash": request.config_hash,
            "segment_plan_hash": plan["plan_hash"],
            "backtest_engine_version": BACKTEST_ENGINE_VERSION,
            "bars": len(candles), "instrument_precision": precisie,
        },
    }


def _run_segment(seg, plak, strategie, exits, uitvoering, kostenmodel, precisie, voortgang) -> dict:
    """Eén segment: backtest op zijn plak, dezelfde keten als fase 4, plus de
    gegevens over gedwongen sluitingen aan het segmenteinde."""
    if plak.timestamp and plak.timestamp[-1] >= seg["end_ts"]:
        raise RunError(f"{seg['kind']}: een bar van na het segment in de invoer")
    res = run_backtest(
        plak, strategie, exits,
        spread=kostenmodel["spread_model"]["value_per_unit"],
        slippage=kostenmodel["slippage_model"]["value_per_unit"],
        units=float(uitvoering.get("units", 1.0)),
        invert=bool(uitvoering.get("invert", False)),
        progress=voortgang,
        evaluate_from_ts=seg["start_ts"], no_entries_from_ts=seg["open_cutoff_ts"],
        close_open_at_end=True,
    )
    samenvatting = res.summary()
    trades = []
    for i, t in enumerate(res.trades, start=1):
        rij = normalize_trade(i, t.as_record(), kostenmodel)
        if not seg["start_ts"] <= rij["opened_ts"] < seg["open_cutoff_ts"]:
            raise RunError(f"{seg['kind']}: trade {i} opent buiten [start, afkapmoment)")
        rij["cross_boundary"] = t.reason == "segment_end"
        trades.append(rij)
    dagen = sorted({
        trading_day(datetime.fromtimestamp(ts, timezone.utc)).isoformat()
        for ts in plak.timestamp if seg["start_ts"] <= ts
    })
    n = len(trades)
    einde = sum(1 for t in trades if t["close_reason"] == "segment_end")
    grens = sum(1 for t in trades if t["cross_boundary"])
    return {
        "kind": seg["kind"], "warmup_status": seg["warmup_status"],
        "summary": samenvatting, "trades": trades,
        "metrics": compute_metrics(trades, samenvatting, dagen, precisie, kostenmodel),
        "breakdowns": breakdowns(trades, precisie, kostenmodel["cost_currency"]),
        "rejections": rejection_breakdown(samenvatting),
        "result_hash": result_hash(samenvatting, trades),
        "bars_in_slice": len(plak),
        "forced_exit": {
            "segment_end_close_count": einde,
            "segment_end_close_share": round(einde / n, 6) if n else None,
            "cross_boundary_count": grens,
            "cross_boundary_share": round(grens / n, 6) if n else None,
            "forced_exit_policy": FORCED_EXIT_POLICY,
            "forced_exit_price_rule": FORCED_EXIT_PRICE_RULE,
            "forced_exit_cost_rule": FORCED_EXIT_COST_RULE,
            "segment_schema_version": SEGMENT_SCHEMA_VERSION,
            "execution_fidelity_limitation": FORCED_EXIT_FIDELITY,
        },
    }


def _single(request, candles, ds, strategie, exits, uitvoering, kostenmodel,
            should_stop, on_progress) -> dict:
    """Eén segment van één kandidaat (walk-forward)."""
    seg = request.single_segment
    if exits.max_hold_seconds > seg["max_hold_seconds"]:
        raise RunError("de maximale houdtijd van de configuratie is langer dan in het plan")
    plak = _plak(candles, seg["warmup_start_ts"], seg["end_ts"])
    totaal = max(0, len(plak) - 1 - WARMUP_BARS)

    def voortgang(verwerkt: int, _t: int) -> None:
        if should_stop():
            raise Cancelled()
        on_progress(verwerkt, totaal, segment=seg["kind"])

    uit = _run_segment(seg, plak, strategie, exits, uitvoering, kostenmodel,
                       ds["instrument_precision"], voortgang)
    return {
        "result_schema_version": RESULT_SCHEMA_VERSION, "single_segment": True,
        "segment": uit, "cost_model": kostenmodel,
        "versions": {
            "backtest_engine_version": BACKTEST_ENGINE_VERSION,
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "cost_model_version": COST_MODEL_VERSION, "metrics_version": METRICS_VERSION,
            "segment_schema_version": SEGMENT_SCHEMA_VERSION,
            "walk_forward_schema_version": WALK_FORWARD_SCHEMA_VERSION,
        },
        "result_hash": uit["result_hash"],
        "provenance": {
            "dataset_id": request.dataset_id, "dataset_hash": request.dataset_hash,
            "dataset_quality_status": ds["quality_status"], "config_hash": request.config_hash,
            "segment": {k: seg[k] for k in ("kind", "start_ts", "end_ts", "warmup_start_ts",
                                            "open_cutoff_ts")},
        },
    }
