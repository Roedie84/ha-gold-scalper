"""2.24.0 (L-GS-025): spreadhistorie per markt voor de Bitvavo-mand.

De mand liet markten toe op één momentopname van de spread (de 24-uurs
ticker op het moment van herzien). PUMP-EUR en PEPE-EUR hangen rond de grens
van 0,03 % en wisselden zo elk uur in en uit de mand. Nu telt de mediaan van
de waarnemingen over de laatste 24 uur. Te weinig waarnemingen (net
geïnstalleerd, nieuwe markt): dan de momentopname, zoals voorheen.

Pure logica, zonder Home Assistant: de mand bewaart de export in zijn eigen
bestand, zodat de mediaan een herstart overleeft.
"""

from __future__ import annotations

from statistics import median

#: Venster van de mediaan.
SPREAD_VENSTER_S = 24 * 3600
#: Minstens zoveel waarnemingen in het venster, anders de momentopname.
MIN_WAARNEMINGEN = 12
#: Hooguit zoveel waarnemingen per markt (24 uur elk kwartier = 96).
MAX_PER_MARKT = 200
#: Twee waarnemingen dichter bij elkaar dan dit tellen als één (de herziening
#: en de kwartierwaarneming vallen soms samen).
MIN_AFSTAND_S = 300


class SpreadHistorie:
    """Waarnemingen ``markt -> [(epoch-seconden, spread in %), ...]``."""

    def __init__(self) -> None:
        self._data: dict[str, list[tuple[float, float]]] = {}

    def __len__(self) -> int:
        return len(self._data)

    def waarneem(self, nu: float, spreads: dict[str, float]) -> int:
        """Leg een momentopname vast; geeft het aantal vastgelegde markten."""
        n = 0
        for markt, spread in (spreads or {}).items():
            try:
                s = float(spread)
            except (TypeError, ValueError):
                continue
            if s < 0 or s != s:  # negatief of NaN
                continue
            rij = self._data.setdefault(str(markt).upper(), [])
            if rij and nu - rij[-1][0] < MIN_AFSTAND_S:
                rij[-1] = (float(nu), round(s, 5))
            else:
                rij.append((float(nu), round(s, 5)))
            n += 1
        self.snoei(nu)
        return n

    def snoei(self, nu: float) -> None:
        grens = nu - SPREAD_VENSTER_S
        for markt in list(self._data):
            rij = [w for w in self._data[markt] if w[0] >= grens and w[0] <= nu + 60]
            if rij:
                self._data[markt] = rij[-MAX_PER_MARKT:]
            else:
                self._data.pop(markt, None)

    def aantal(self, markt: str, nu: float) -> int:
        grens = nu - SPREAD_VENSTER_S
        return sum(1 for t, _ in self._data.get(str(markt).upper(), ()) if t >= grens)

    def mediaan(self, markt: str, nu: float,
                minimum: int = MIN_WAARNEMINGEN) -> float | None:
        """Mediane spread over de laatste 24 uur; ``None`` bij te weinig
        waarnemingen (dan geldt de momentopname)."""
        grens = nu - SPREAD_VENSTER_S
        waarden = [s for t, s in self._data.get(str(markt).upper(), ()) if t >= grens]
        if len(waarden) < max(1, int(minimum)):
            return None
        return float(median(waarden))

    # -- bewaren ---------------------------------------------------------------- #

    def export(self) -> dict:
        return {m: [[int(t), s] for t, s in rij] for m, rij in self._data.items()}

    def herstel(self, data, nu: float) -> None:
        """Uit het bestand; onleesbare regels worden overgeslagen."""
        self._data = {}
        if not isinstance(data, dict):
            return
        for markt, rij in data.items():
            goed = []
            for w in rij or []:
                try:
                    t, s = float(w[0]), float(w[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if s >= 0:
                    goed.append((t, s))
            if goed:
                goed.sort()
                self._data[str(markt).upper()] = goed
        self.snoei(nu)
