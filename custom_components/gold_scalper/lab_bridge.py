"""Alleen-lezende brug tussen het barsarchief en het Experiment Lab.

Het Lab mag het barsarchief niet kennen: het archief is muteerbaar, en een
object waarmee gelezen kan worden, kan in de verkeerde hand ook schrijven. Deze
brug staat daarom **buiten** het Lab en geeft uitsluitend gewone,
onveranderlijke gegevens door: ``BarInput``, ``MarketWindow`` en
``DatasetSpec``.

Strenger dan "alleen lezen afspreken": de brug gebruikt niet het
``BarArchive``-object - dat heeft een schrijfbare verbinding - maar opent het
archiefbestand zelf in SQLite's **alleen-lezenmodus** (``mode=ro``). SQLite
weigert dan elke schrijfpoging, ook als hier ooit per ongeluk een zou staan.

Wat de brug nooit doorgeeft: het archief, de verbinding, de coordinator, de
broker, een config entry of ``hass``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .broker.schedule import SPOT_GOLD, Session, is_open
from .experiment_lab.datasets import BarInput, DatasetSpec, MarketWindow
from .strategy.aggregator import BAR_SECONDS


class ArchiveReader:
    """Leest bars uit het archiefbestand, alleen-lezend."""

    def __init__(self, path: str | Path) -> None:
        pad = Path(path).resolve()
        if not pad.exists():
            raise FileNotFoundError(pad)
        # mode=ro: SQLite zelf weigert elke schrijfpoging op deze verbinding.
        self._conn = sqlite3.connect(f"file:{pad}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def read_bars(
        self, symbol: str, timeframe: str, now_ts: int,
        start_ts: int | None = None, end_ts: int | None = None,
    ) -> tuple[BarInput, ...]:
        """Bars als onveranderlijke gewone gegevens.

        ``bar_status`` volgt uit de tijd: een bar waarvan het einde na
        ``now_ts`` ligt, liep nog - ``incomplete``. Dezelfde regel als
        ``closed_only`` in de live-lus. Er wordt niets weggelaten; de status
        gaat mee in de identiteit van de snapshot.
        """
        lengte = BAR_SECONDS[timeframe]
        voorwaarden, waarden = ["symbol=?", "timeframe=?"], [symbol, timeframe]
        if start_ts is not None:
            voorwaarden.append("timestamp>=?")
            waarden.append(start_ts)
        if end_ts is not None:
            voorwaarden.append("timestamp<=?")
            waarden.append(end_ts)
        rijen = self._conn.execute(
            "SELECT timestamp, open, high, low, close, volume, source FROM bars "
            f"WHERE {' AND '.join(voorwaarden)} ORDER BY timestamp",
            waarden,
        ).fetchall()
        return tuple(
            BarInput(
                ts=int(r["timestamp"]), open=float(r["open"]), high=float(r["high"]),
                low=float(r["low"]), close=float(r["close"]),
                volume=float(r["volume"]) if r["volume"] is not None else None,
                source=str(r["source"] or "onbekend"),
                bar_status="incomplete" if int(r["timestamp"]) + lengte > now_ts else "closed",
            )
            for r in rijen
        )


def market_windows(
    start_ts: int, end_ts: int, timeframe: str, session: Session = SPOT_GOLD,
) -> tuple[MarketWindow, ...]:
    """Wanneer de markt volgens het ingestelde rooster open is, als gewone vensters.

    Dit is het **rooster**, geen waarneming: feestdagen en ongeplande
    sluitingen staan er niet in. Het Lab behandelt een gat buiten deze
    vensters als verwachte sluiting, en een gat erbinnen als ontbrekend.
    """
    lengte = BAR_SECONDS[timeframe]
    vensters: list[MarketWindow] = []
    begin = None
    t = (start_ts // lengte) * lengte
    while t <= end_ts:
        open_nu, _ = is_open(session, datetime.fromtimestamp(t, timezone.utc))
        if open_nu and begin is None:
            begin = t
        elif not open_nu and begin is not None:
            vensters.append(MarketWindow(begin, t))
            begin = None
        t += lengte
    if begin is not None:
        vensters.append(MarketWindow(begin, t))
    return tuple(vensters)


def dataset_spec(
    symbol: str, timeframe: str, precision: int | None,
) -> DatasetSpec:
    """Metadata voor de snapshot.

    De precisie hoort uit de instrumentgegevens van de broker te komen
    (``decimalPlacesFactor``). Ontbreekt die, dan geldt twee decimalen - wat
    voor goud klopt - en staat dat als terugval in de snapshot.
    """
    if precision is None:
        return DatasetSpec(symbol, timeframe, 2, "fallback", "bar_archive")
    return DatasetSpec(symbol, timeframe, int(precision), "instrument_metadata", "bar_archive")
