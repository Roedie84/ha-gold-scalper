"""EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING

De grens tussen het Experiment Lab en de handel, op drie lagen:

1. **Bereiken.** De importgraaf van het Lab - transitief, ook via
   tussenmodules - bevat geen enkele module waarmee de handel te beïnvloeden
   is, en niets van Home Assistant.
2. **Ontvangen.** Geen functie in het Lab neemt ``hass``, een coordinator,
   een config entry, een venue of een broker aan, en de Lab-code verwijst er
   ook niet naar.
3. **Schrijven.** Het Lab kent geen schrijfpad naar config entries, opties of
   de databases van de handel.

De controles toetsen zichzelf: een kunstmatige module die de grens
opzettelijk - ook indirect - overschrijdt, moet worden gevangen. Anders zou
een groene test niets bewijzen.
"""
import ast
from pathlib import Path


PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"
PAKKET = "gold_scalper"

#: Modules waarmee de handel te beïnvloeden is. Elk ervan geeft toegang tot
#: orders, posities, risicobewaking, de schakelaars, de configuratie of de
#: tradedatabase.
VERBODEN = {
    "gold_scalper",                       # het pakket zelf laadt de coordinator
    "gold_scalper.coordinator", "gold_scalper.modes", "gold_scalper.lifecycle",
    "gold_scalper.switch", "gold_scalper.button", "gold_scalper.sensor",
    "gold_scalper.binary_sensor", "gold_scalper.config_flow",
    "gold_scalper.http", "gold_scalper.diagnostics", "gold_scalper.notify",
    "gold_scalper.entity",
    "gold_scalper.broker.ig_capital", "gold_scalper.broker.adapter",
    "gold_scalper.broker.paper", "gold_scalper.broker.simulator",
    "gold_scalper.broker.execution_safety", "gold_scalper.broker.risk",
    "gold_scalper.broker.reconcile_audit",
    "gold_scalper.storage.database", "gold_scalper.storage.state",
    "gold_scalper.storage.bar_archive",
    # De brug importeert het Lab, nooit andersom: anders bereikt het Lab via
    # de brug alsnog het archiefbestand en het brokerrooster.
    "gold_scalper.lab_bridge", "gold_scalper.broker.schedule",
    # Fase 9A: de Home Assistant-koppeling kent het Lab, nooit andersom.
    "gold_scalper.lab_panel",
}

#: Externe pakketten die het Lab nooit mag bereiken.
VERBODEN_EXTERN = {"homeassistant", "aiohttp", "voluptuous"}

#: Namen die het Lab niet mag ontvangen of aanspreken.
VERBODEN_NAMEN = {
    "hass", "coordinator", "config_entry", "config_entries", "venue",
    "broker", "place_order", "close_position", "modify_stop",
    "async_update_entry", "async_create_entry", "options",
}


def _module_naam(pad: Path, wortel: Path) -> str:
    deel = pad.relative_to(wortel.parent).with_suffix("")
    delen = list(deel.parts)
    if delen[-1] == "__init__":
        delen = delen[:-1]
    return ".".join(delen)


def _pad_van(module: str, wortel: Path) -> Path | None:
    rel = Path(*module.split(".")[1:]) if "." in module else Path()
    for kandidaat in (wortel / rel.with_suffix(".py") if rel.parts else None,
                      wortel / rel / "__init__.py"):
        if kandidaat is not None and kandidaat.exists():
            return kandidaat
    return None


def _imports(pad: Path, wortel: Path) -> set[str]:
    """Alle modules die dit bestand expliciet importeert, volledig benoemd."""
    boom = ast.parse(pad.read_text(encoding="utf-8"))
    eigen = _module_naam(pad, wortel)
    pakket = eigen if pad.name == "__init__.py" else eigen.rsplit(".", 1)[0]
    uit: set[str] = set()
    for knoop in ast.walk(boom):
        if isinstance(knoop, ast.Import):
            for n in knoop.names:
                uit.add(n.name)
        elif isinstance(knoop, ast.ImportFrom):
            if knoop.level:
                basis = pakket.split(".")
                basis = basis[: len(basis) - (knoop.level - 1)]
                doel = ".".join(basis + ([knoop.module] if knoop.module else []))
            else:
                doel = knoop.module or ""
            uit.add(doel)
            # "from . import x" of "from .pakket import module"
            for n in knoop.names:
                sub = f"{doel}.{n.name}"
                if _pad_van(sub, wortel) is not None:
                    uit.add(sub)
    return uit


def bereikbaar(startbestanden, wortel: Path) -> dict[str, list[str]]:
    """Transitieve importgraaf vanaf de Lab-bestanden: module -> importpad."""
    gezien: dict[str, list[str]] = {}
    werk = [(_module_naam(p, wortel), [_module_naam(p, wortel)]) for p in startbestanden]
    while werk:
        module, route = werk.pop()
        pad = _pad_van(module, wortel) if module.startswith(PAKKET) else None
        if pad is None:
            continue
        for doel in _imports(pad, wortel):
            if doel in gezien:
                continue
            gezien[doel] = route + [doel]
            if doel.startswith(PAKKET):
                werk.append((doel, route + [doel]))
    return gezien


def overtredingen(startbestanden, wortel: Path) -> list[str]:
    fouten = []
    for doel, route in bereikbaar(startbestanden, wortel).items():
        extern = doel.split(".")[0]
        if doel in VERBODEN or extern in VERBODEN_EXTERN:
            fouten.append(" -> ".join(route))
    return sorted(fouten)


def _lab_bestanden(wortel: Path = PKG):
    return sorted((wortel / "experiment_lab").rglob("*.py"))


# ---------------- 1. bereiken ----------------

def test_EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING_reach():
    """De volledige importgraaf van het Lab, transitief."""
    fouten = overtredingen(_lab_bestanden(), PKG)
    assert fouten == [], "het Lab bereikt de handel:\n" + "\n".join(fouten)


def test_the_lab_reaches_only_pure_modules():
    """Positieve lijst: wat het Lab nu bereikt, en niets anders."""
    intern = {m for m in bereikbaar(_lab_bestanden(), PKG) if m.startswith(PAKKET)}
    toegestaan = {
        "gold_scalper.experiment_lab", "gold_scalper.experiment_lab.models",
        "gold_scalper.experiment_lab.storage", "gold_scalper.experiment_lab.datasets",
        "gold_scalper.experiment_lab.worker", "gold_scalper.experiment_lab.segments",
        "gold_scalper.experiment_lab.walk_forward", "gold_scalper.experiment_lab.runner",
        "gold_scalper.experiment_lab.assessment", "gold_scalper.analysis.indicator_lab",
        "gold_scalper.experiment_lab.comparison", "gold_scalper.experiment_lab.costs",
        "gold_scalper.experiment_lab.metrics", "gold_scalper.session_rules", "gold_scalper.timeutil",
        "gold_scalper.analysis.engine", "gold_scalper.analysis.levels",
        "gold_scalper.analysis.patterns", "gold_scalper.analysis.statistics",
        "gold_scalper.analysis.volume",
        # zuivere rekenmodules: de ene tabel met barlengtes en het Candles-type
        "gold_scalper.strategy", "gold_scalper.strategy.aggregator",
        "gold_scalper.analysis", "gold_scalper.analysis.signals",
        # sinds fase 3: de backtestmotor en wat hij gebruikt. Allemaal
        # rekenwerk; geen order, positie, account of configuratie.
        "gold_scalper.analysis.backtest", "gold_scalper.analysis.core",
        "gold_scalper.analysis.momentum", "gold_scalper.analysis.trend",
        "gold_scalper.analysis.volatility", "gold_scalper.strategy.scalping",
        "gold_scalper.strategy.structure", "gold_scalper.broker.exits",
        "gold_scalper.const",
        # sinds fase 4: kosten en metrieken, met de ene definitie van
        # handelsdag (Europe/Amsterdam) en sessie (UTC).
        "gold_scalper.experiment_lab.costs", "gold_scalper.experiment_lab.metrics",
        "gold_scalper.timeutil", "gold_scalper.session_rules",
    }
    assert intern <= toegestaan, sorted(intern - toegestaan)


def _kunstmatige_boom(tmp_path, lab_code: str, tussen_code: str | None = None):
    wortel = tmp_path / "gold_scalper"
    (wortel / "experiment_lab").mkdir(parents=True)
    (wortel / "__init__.py").write_text("from .coordinator import X\n")
    (wortel / "coordinator.py").write_text("X = 1\n")
    (wortel / "broker").mkdir()
    (wortel / "broker" / "__init__.py").write_text("")
    (wortel / "broker" / "ig_capital.py").write_text("")
    (wortel / "experiment_lab" / "__init__.py").write_text("")
    (wortel / "experiment_lab" / "stuk.py").write_text(lab_code)
    if tussen_code is not None:
        (wortel / "hulp.py").write_text(tussen_code)
    return wortel


def test_the_check_catches_a_direct_violation(tmp_path):
    wortel = _kunstmatige_boom(tmp_path, "from ..coordinator import X\n")
    assert overtredingen(_lab_bestanden(wortel), wortel)


def test_the_check_catches_an_indirect_violation(tmp_path):
    """Via een onschuldig ogende tussenmodule."""
    wortel = _kunstmatige_boom(
        tmp_path, "from .. import hulp\n",
        tussen_code="from .broker import ig_capital\n",
    )
    fouten = overtredingen(_lab_bestanden(wortel), wortel)
    assert any("ig_capital" in f and "hulp" in f for f in fouten), fouten


def test_the_check_catches_home_assistant(tmp_path):
    wortel = _kunstmatige_boom(tmp_path, "import homeassistant.core\n")
    assert overtredingen(_lab_bestanden(wortel), wortel)


def test_the_check_catches_importing_the_package_root(tmp_path):
    """``from .. import X`` laadt het pakket - en daarmee de coordinator."""
    wortel = _kunstmatige_boom(tmp_path, "from .. import coordinator\n")
    assert overtredingen(_lab_bestanden(wortel), wortel)


def test_the_check_passes_a_clean_module(tmp_path):
    wortel = _kunstmatige_boom(tmp_path, "import json\nfrom . import stuk\n")
    assert overtredingen(_lab_bestanden(wortel), wortel) == []


# ---------------- 2. ontvangen ----------------

def _namen_in(pad: Path) -> set[str]:
    boom = ast.parse(pad.read_text(encoding="utf-8"))
    namen: set[str] = set()
    for k in ast.walk(boom):
        if isinstance(k, ast.arg):
            namen.add(k.arg)
        elif isinstance(k, ast.Name):
            namen.add(k.id)
        elif isinstance(k, ast.Attribute):
            namen.add(k.attr)
        elif isinstance(k, ast.keyword) and k.arg:
            namen.add(k.arg)
    return namen


def test_EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING_receive():
    """Geen parameter, variabele of attribuut met een handelsobject."""
    for pad in _lab_bestanden():
        verkeerd = _namen_in(pad) & VERBODEN_NAMEN
        assert not verkeerd, f"{pad.name}: {sorted(verkeerd)}"


def test_the_receive_check_catches_a_hass_parameter(tmp_path):
    pad = tmp_path / "x.py"
    pad.write_text("def run(hass, dataset):\n    return dataset\n")
    assert "hass" in _namen_in(pad)


# ---------------- 3. schrijven ----------------

def test_EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING_write():
    """Geen verwijzing naar de databases of de configuratie van de handel."""
    for pad in _lab_bestanden():
        tekst = pad.read_text(encoding="utf-8")
        for verboden in ("gold_scalper.db", "gold_scalper_bars.db",
                         "config_entries", "async_update_entry", ".options"):
            assert verboden not in tekst, f"{pad.name} verwijst naar {verboden}"


def test_the_lab_writes_only_to_the_path_it_is_given():
    """De opslag kent geen eigen standaardpad naar een handelsbestand: het pad
    komt van buiten, en in de tests is het altijd een tijdelijke map."""
    import inspect
    import sys

    sys.path.insert(0, str(PKG.parent))
    from gold_scalper.experiment_lab.storage import LabDatabase

    param = inspect.signature(LabDatabase.__init__).parameters["path"]
    assert param.default is inspect.Parameter.empty
