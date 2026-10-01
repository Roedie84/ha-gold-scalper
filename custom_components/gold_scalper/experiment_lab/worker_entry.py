"""Invoer voor het aparte werkproces. Wordt als script gestart, niet als module.

Waarom zo: Python voert bij elke import van een submodule eerst het
bovenliggende pakket uit, en ``gold_scalper/__init__.py`` laadt de
coordinator en Home Assistant. Een werkproces dat gewoon
``import gold_scalper.experiment_lab.worker`` doet, zou die dus meeladen.

Dit script registreert vóór elke import een **leeg** pakketobject voor
``gold_scalper``, met alleen het pad naar de pakketmap. Python ziet het pakket
dan als geladen en voert de echte ``__init__.py`` niet uit. Submodules worden
gewoon uit de map gevonden.

Aan het eind meldt het proces welke modules het werkelijk heeft geladen. Een
test legt vast dat daar geen coordinator, broker, Home Assistant of andere
verboden module tussen zit.

Protocol, één JSON-object per regel:

* stdin, eerste regel: de ``RunRequest``; daarna eventueel ``{"cancel": true}``
* stdout: ``progress``, en tot slot precies één van ``result``, ``cancelled``
  of ``error``, gevolgd door ``modules``
"""

import json
import os
import sys
import threading
import types
from pathlib import Path

PAKKETMAP = Path(__file__).resolve().parent.parent


def _pakket_zonder_init() -> None:
    pakket = types.ModuleType("gold_scalper")
    pakket.__path__ = [str(PAKKETMAP)]
    pakket.__package__ = "gold_scalper"
    sys.modules["gold_scalper"] = pakket


def _meld(bericht: dict) -> None:
    sys.stdout.write(json.dumps(bericht) + "\n")
    sys.stdout.flush()


def main() -> int:
    _pakket_zonder_init()
    from gold_scalper.experiment_lab.worker import (  # noqa: E402
        Cancelled, RunRequest, execute,
    )

    request = RunRequest(**json.loads(sys.stdin.readline()))
    stoppen = threading.Event()

    def luister() -> None:
        for regel in sys.stdin:
            try:
                if json.loads(regel).get("cancel"):
                    stoppen.set()
                    return
            except ValueError:
                continue

    threading.Thread(target=luister, daemon=True).start()

    code = 0
    try:
        uitslag = execute(
            request, stoppen.is_set,
            lambda gedaan, totaal, **extra: _meld(
                {"type": "progress", "done": gedaan, "total": totaal, **extra}),
        )
        _meld({"type": "result", "result": uitslag})
    except Cancelled:
        _meld({"type": "cancelled"})
    except Exception as err:  # noqa: BLE001 - de fout gaat terug naar de controller
        _meld({"type": "error", "message": f"{type(err).__name__}: {err}"})
        code = 1
    _meld({"type": "modules", "loaded": sorted(sys.modules)})
    return code


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    # Hard afsluiten: de luisterdraad staat nog op stdin te wachten, en het
    # normale afsluiten van Python kan daarop blijven hangen. Er valt niets op
    # te ruimen - de database stond alleen-lezend open en is al gesloten.
    os._exit(code)
