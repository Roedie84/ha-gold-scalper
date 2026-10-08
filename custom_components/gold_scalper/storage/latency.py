"""Latency-instrumentatie en gebufferd wegschrijven.

Twee problemen die samen de doorvoer bepalen.

**Meten.** Je kunt niet optimaliseren wat je niet meet, en bij een tradebot is
de interessante latency niet "hoe snel is mijn code" maar "hoeveel tijd zit er
tussen de tick die het signaal veroorzaakte en de fill". Die keten loopt over
meerdere machines. ``LatencyBudget`` legt elke schakel vast zodat achteraf te
zien is waar de tijd blijft, in plaats van te gokken.

**Schrijven.** De oorspronkelijke ``TradeDatabase`` doet ``commit()`` na elke
insert. Met WAL is dat een fsync per trade, ordegrootte 1-10 ms afhankelijk van
je opslag. Op een Raspberry Pi met SD-kaart kan het tienvoudig erger zijn. Bij
honderden signalen per minuut wordt de database dan de traagste schakel in een
systeem dat verder in microseconden werkt.

De oplossing is bufferen met een periodieke flush. Dat introduceert een risico
dat bewust benoemd moet worden: bij een harde crash verlies je wat er in de
buffer stond. Voor de ``signals``-tabel is dat acceptabel. Voor ``trades`` niet
- dat is je bewijsmateriaal - dus die worden altijd direct doorgeschreven.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)

#: Omvang van de steekproef per schakel (1.7.6). Wordt over een herstart heen
#: bewaard; daarvóór begon hij na elke herstart opnieuw.
LATENCY_VENSTER = 2000
#: Vanaf zoveel metingen geldt de p99 als betrouwbaar; daaronder bepalen een
#: paar uitschieters hem en heet hij indicatief (1.7.6).
P99_BETROUWBAAR_VANAF = 1000
#: Maximaal aantal schakels dat wordt teruggezet; begrenst wat een
#: beschadigd bestand kan aanrichten.
_MAX_SCHAKELS = 32


@dataclass(slots=True)
class LatencyBudget:
    """Meet de keten van tick tot order in één trade.

    Gebruik:

        budget = LatencyBudget()
        budget.mark("tick_broker_time", tick_timestamp)
        budget.mark("tick_received")
        ...
        budget.mark("signal_computed")
        budget.mark("order_sent")
        budget.mark("fill_confirmed")
        print(budget.report())
    """

    stages: dict[str, float] = field(default_factory=dict)
    _order: list[str] = field(default_factory=list)

    def mark(self, stage: str, timestamp: float | None = None) -> None:
        self.stages[stage] = timestamp if timestamp is not None else time.perf_counter()
        if stage not in self._order:
            self._order.append(stage)

    def elapsed_ms(self, start: str, end: str) -> float | None:
        a, b = self.stages.get(start), self.stages.get(end)
        return None if (a is None or b is None) else (b - a) * 1000.0

    def total_ms(self) -> float | None:
        if len(self._order) < 2:
            return None
        return self.elapsed_ms(self._order[0], self._order[-1])

    def report(self) -> dict[str, float]:
        """Per schakel de duur in milliseconden."""
        out: dict[str, float] = {}
        for previous, current in zip(self._order, self._order[1:]):
            delta = self.elapsed_ms(previous, current)
            if delta is not None:
                out[f"{previous}->{current}"] = round(delta, 3)
        total = self.total_ms()
        if total is not None:
            out["total"] = round(total, 3)
        return out


class LatencyTracker:
    """Verzamelt latency-statistieken over veel trades.

    Rapporteert percentielen in plaats van gemiddelden. Het gemiddelde is bij
    latency vrijwel altijd misleidend: de verdeling heeft een lange staart, en
    juist die staart bepaalt of je stop op tijd wordt geplaatst. De p99 is het
    getal dat telt.
    """

    def __init__(self, window: int = 1000) -> None:
        self._samples: dict[str, deque[float]] = {}
        self._window = window
        self._lock = threading.Lock()
        #: Een bewaarde steekproef wordt hooguit één keer teruggezet; een
        #: tweede keer zou dezelfde metingen dubbel tellen.
        self._hersteld = False

    def record(self, budget: LatencyBudget) -> None:
        with self._lock:
            for stage, value in budget.report().items():
                bucket = self._samples.setdefault(stage, deque(maxlen=self._window))
                bucket.append(value)

    def stats(self) -> dict[str, dict[str, float]]:
        with self._lock:
            out = {}
            for stage, values in self._samples.items():
                if not values:
                    continue
                ordered = sorted(values)
                n = len(ordered)

                def pct(p: float) -> float:
                    return round(ordered[min(n - 1, int(n * p))], 3)

                # Een percentiel bij weinig waarnemingen is misleidend: bij
                # negen metingen is de "p99" gewoon het maximum, en dan
                # presenteer je één uitschieter als een betrouwbaar getal.
                # Liever weglaten dan schijnzekerheid geven.
                entry = {
                    "samples": n,
                    "median": pct(0.5),
                    "max": round(ordered[-1], 3),
                }
                if n >= 20:
                    entry["p90"] = pct(0.9)
                if n >= 100:
                    entry["p99"] = pct(0.99)
                out[stage] = entry
            return out

    def export(self) -> dict[str, list[float]]:
        """De steekproef per schakel, om te bewaren (1.7.6)."""
        with self._lock:
            return {stage: list(values) for stage, values in self._samples.items()}

    def restore(self, data: Any) -> int:
        """Zet een bewaarde steekproef terug (1.7.6). Geeft het aantal metingen.

        Bewaarde metingen komen vóór wat er in deze sessie al gemeten is, en
        het venster blijft begrensd. Onleesbare waarden worden overgeslagen;
        meten verandert hierdoor niet.
        """
        if not isinstance(data, dict) or self._hersteld:
            return 0
        aantal = 0
        with self._lock:
            self._hersteld = True
            for stage, values in list(data.items())[:_MAX_SCHAKELS]:
                if not isinstance(values, (list, tuple)):
                    continue
                oud: list[float] = []
                for v in values[-self._window:]:
                    try:
                        getal = float(v)
                    except (TypeError, ValueError):
                        continue
                    if getal == getal and getal not in (float("inf"), float("-inf")):
                        oud.append(getal)
                if not oud:
                    continue
                huidig = self._samples.get(str(stage))
                bucket: deque[float] = deque(oud, maxlen=self._window)
                if huidig:
                    bucket.extend(huidig)
                self._samples[str(stage)] = bucket
                aantal += len(bucket)
        return aantal

    def slowest_stage(self) -> tuple[str, float] | None:
        """Welke schakel kost mediaan de meeste tijd."""
        stats = self.stats()
        candidates = {k: v["median"] for k, v in stats.items() if k != "total"}
        if not candidates:
            return None
        stage = max(candidates, key=candidates.get)
        return stage, candidates[stage]


class BufferedWriter:
    """Bufferde inserts met periodieke flush.

    Alleen voor data waarvan verlies bij een crash acceptabel is. Trades gaan
    hier expliciet niet doorheen.
    """

    def __init__(
        self,
        flush_callback: Callable[[list[tuple]], None],
        max_buffer: int = 200,
        max_age_seconds: float = 5.0,
    ) -> None:
        self._buffer: list[tuple] = []
        self._flush = flush_callback
        self._max_buffer = max_buffer
        self._max_age = max_age_seconds
        self._last_flush = time.monotonic()
        self._lock = threading.Lock()
        self._dropped = 0

    def add(self, row: tuple) -> None:
        with self._lock:
            self._buffer.append(row)
            should_flush = (
                len(self._buffer) >= self._max_buffer
                or (time.monotonic() - self._last_flush) >= self._max_age
            )
            if should_flush:
                self._flush_locked()

    def flush(self) -> int:
        with self._lock:
            return self._flush_locked()

    def _flush_locked(self) -> int:
        if not self._buffer:
            return 0
        rows, self._buffer = self._buffer, []
        self._last_flush = time.monotonic()
        try:
            self._flush(rows)
        except Exception:  # noqa: BLE001
            # Niet stilzwijgend laten verdwijnen: als de database structureel
            # weigert, moet dat zichtbaar worden in plaats van dat er data
            # wegvalt zonder spoor.
            self._dropped += len(rows)
            _LOGGER.exception(
                "Flush van %d rijen mislukt; totaal verloren: %d", len(rows), self._dropped
            )
            return 0
        return len(rows)

    @property
    def pending(self) -> int:
        return len(self._buffer)

    @property
    def dropped(self) -> int:
        return self._dropped


def install_buffered_signals(database: Any, flush_interval: float = 5.0) -> BufferedWriter:
    """Vervang ``log_signal`` door een gebufferde variant.

    De signaaltabel krijgt bij scalping honderden rijen per minuut en is
    daarmee de grootste schrijfbelasting. Trades blijven ongebufferd.
    """

    def _flush(rows: list[tuple]) -> None:
        database.conn.executemany(
            """INSERT INTO signals
               (run_id, ts, score, confidence, state, regime, spread, acted,
                reject_reason, detail_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        database.conn.commit()

    writer = BufferedWriter(_flush, max_buffer=200, max_age_seconds=flush_interval)

    import json
    from datetime import datetime, timezone

    def log_signal(
        run_id, score, confidence, state, regime, spread, acted,
        reject_reason=None, detail=None,
    ) -> None:
        writer.add((
            run_id,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            score, confidence, state, regime, spread, int(acted), reject_reason,
            json.dumps(detail, default=str) if detail else None,
        ))

    database.log_signal = log_signal  # type: ignore[method-assign]
    database.flush_signals = writer.flush  # type: ignore[attr-defined]
    return writer
