"""Gesloten trades als tabel voor de dienst ``export_data`` (2.19.3).

Los van Home Assistant, zodat het zonder HA te toetsen is. Een Bitvavo-mand
bewaart de trades per markt in de database van elk lid; de hoofdlus (de
gekozen markt) heeft er vaak geen. Daarom gaan alle markten van de mand mee,
met de markt als laatste kolom.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


def _tijd(waarde: Any) -> datetime:
    if isinstance(waarde, datetime):
        return waarde if waarde.tzinfo else waarde.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(waarde))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def trades_tabel(bronnen: Iterable[tuple[str, list]], velden: Iterable[str],
                 offset: int, limit: int, markt: str | None = None) -> dict:
    """``bronnen`` = [(markt, gesloten trades)]. Eén bron: volgorde van de
    database (zoals vóór 2.19.3). Meer bronnen: op sluitmoment, dan markt."""
    velden = list(velden)
    bronnen = [(str(m), list(t or [])) for m, t in bronnen
               if not markt or str(m).upper() == str(markt).upper()]
    rijen = [(m, t) for m, trades in bronnen for t in trades]
    if len(bronnen) > 1:
        rijen.sort(key=lambda mt: (_tijd(getattr(mt[1], "close_time", None)), mt[0]))
    return {
        "total": len(rijen), "offset": offset,
        "columns": [*velden, "markt"],
        "rows": [[getattr(t, v, None) for v in velden] + [m]
                 for m, t in rijen[offset:offset + limit]],
        "markten": [m for m, _ in bronnen],
    }
