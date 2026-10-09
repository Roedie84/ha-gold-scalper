"""Testopzet.

Het probleem: ``custom_components/gold_scalper/__init__.py`` importeert Home
Assistant, zoals elke integratie doet. Daardoor sleept het importeren van een
zuivere logicamodule als ``storage.database`` de hele HA-boom mee, en die is
hier niet geïnstalleerd.

De oplossing is niet om Home Assistant als testafhankelijkheid toe te voegen -
dat is honderden megabytes en maakt de suite traag en broos. In plaats daarvan
staat hier een minimale nep-``homeassistant`` die alleen bij het importeren
hoeft te werken. Alles wat écht getest wordt (indicatoren, kostenboekhouding,
risicolimieten, poort, exits, rapportage) raakt Home Assistant niet aan.

Het gevolg is dat de kernlogica in elke omgeving te draaien is: op je laptop,
in CI, zonder HA. Dat is bewust: de rekenkern hoort onafhankelijk verifieerbaar
te zijn van het platform waarop hij toevallig draait.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components"))


class _Anything:
    """Staat alles toe: aanroepen, indexeren, erven, attributen opvragen.

    Genoeg om import-tijd te overleven zonder ook maar iets te doen.
    """

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __call__(self, *args, **kwargs):
        return _Anything()

    def __getattr__(self, name):
        return _Anything()

    def __getitem__(self, key):
        return _Anything()

    def __iter__(self):
        return iter(())

    def __or__(self, other):
        return _Anything()

    def __ror__(self, other):
        return _Anything()

    def __mro_entries__(self, bases):
        # Nodig omdat integratieklassen erven van HA-basisklassen zoals
        # DataUpdateCoordinator[dict]. Python vraagt dan om de echte bases;
        # een lege tuple laat de klasse gewoon van object erven.
        return ()


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Anything()


class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Fabriceert elke ``homeassistant.*`` module op aanvraag.

    Gebruikt het moderne ``find_spec``-protocol; het oude
    ``find_module``/``load_module`` is in Python 3.12 verwijderd.
    """

    # Bewust alléén homeassistant. Voluptuous is een klein zuiver
    # Python-pakket dat gewoon geïnstalleerd kan worden, en het stubben ervan
    # was een dure fout: alle schemavalidatie slikte dan stilzwijgend alles,
    # waardoor een ongeldige config-flow er ongemerkt doorheen kwam en pas in
    # de UI opdook als "400: Bad Request".
    PREFIXES = ("homeassistant",)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] not in self.PREFIXES:
            return None
        spec = importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        spec.submodule_search_locations = []
        return spec

    def create_module(self, spec):
        return _StubModule(spec.name)

    def exec_module(self, module):
        module.__path__ = []


def _install_stubs() -> None:
    try:
        import homeassistant  # noqa: F401
        return  # echte HA aanwezig; niets te doen
    except ImportError:
        pass
    sys.meta_path.insert(0, _StubFinder())

    # Een paar constanten die als echte waarde gebruikt worden in plaats van
    # alleen doorgegeven, en die dus geen _Anything mogen zijn.
    import homeassistant.const as ha_const  # type: ignore

    ha_const.PERCENTAGE = "%"
    ha_const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"

    # DataUpdateCoordinator moet een échte basisklasse zijn, geen _Anything.
    #
    # De coordinator roept super().__init__(hass, logger, name=..., ...) aan;
    # met een stub die naar object valt, faalt dat. Zonder werkende basisklasse
    # is de hele handelslus niet te draaien in een test - en precies daar zijn
    # vier fouten op rij doorheen geglipt: een aangeroepen methode die niet
    # bestond, een aanroep met te weinig argumenten, een nulpositie die als
    # verweesd gold, en uitersten die op nul bleven staan.
    import homeassistant.helpers.update_coordinator as huc  # type: ignore
    from datetime import timedelta as _timedelta

    class _Coordinator:
        """Genoeg DataUpdateCoordinator om de lus te laten draaien."""

        def __init__(self, hass=None, logger=None, *, name=None,
                     update_interval=None, **kwargs):
            self.hass = hass
            self.name = name
            self.update_interval = update_interval or _timedelta(seconds=10)
            self.data = None
            self.last_update_success = True
            self._listeners = {}

        def __class_getitem__(cls, item):
            return cls

        async def async_request_refresh(self):
            self.data = await self._async_update_data()

        async def async_refresh(self):
            await self.async_request_refresh()

        async def async_config_entry_first_refresh(self):
            await self.async_request_refresh()

        def async_set_updated_data(self, data):
            self.data = data

        def async_add_listener(self, update_callback, context=None):
            return lambda: None

        def async_update_listeners(self):
            pass

    huc.DataUpdateCoordinator = _Coordinator
    huc.UpdateFailed = type("UpdateFailed", (Exception,), {})

    # Store moet echt kunnen opslaan en teruggeven. De stub gaf _Anything
    # terug, en dat is niet te awaiten - waardoor de handelslus al struikelde
    # voordat er iets van de handel zelf getest kon worden.
    import homeassistant.helpers.storage as ha_storage  # type: ignore

    class _Store:
        """Opslag in het geheugen, met dezelfde vorm als die van HA."""

        def __init__(self, hass=None, version=1, key="", **kwargs):
            self.key = key
            self._data = None

        async def async_load(self):
            return self._data

        async def async_save(self, data):
            self._data = data

        async def async_remove(self):
            self._data = None

    ha_storage.Store = _Store


_install_stubs()


# --------------------------------------------------------------------------- #
# Vaste klok voor de simulator
# --------------------------------------------------------------------------- #

import pytest  # noqa: E402

#: Maandag 7 september 2026, 12:00 UTC. De simulator verankert ``candles()``
#: aan "nu" en berekent prijzen uit het absolute tijdstip: zonder vaste klok
#: krijgt een test elk moment andere marktdata.
VASTE_KLOK = 1_788_782_400


@pytest.fixture
def vaste_klok(monkeypatch):
    """Zet de klok van de simulator vast op ``VASTE_KLOK``.

    Voor tests die simulatordata via ``venue.candles()`` gebruiken en een
    absolute waarde of drempel toetsen. Verandert geen productielogica: alleen
    wat de simulator als "nu" ziet.
    """
    import gold_scalper.broker.simulator as sim

    echt = sim.datetime

    class Vast(echt):
        @classmethod
        def now(cls, tz=None):
            moment = echt.fromtimestamp(VASTE_KLOK, sim.timezone.utc)
            return moment if tz is not None else moment.replace(tzinfo=None)

    monkeypatch.setattr(sim, "datetime", Vast)
    return VASTE_KLOK



def pytest_configure(config):
    """Bij ``-n auto`` (xdist) de groepsverdeling gebruiken.

    Sommige modules (``test_lab_services_57``) delen een fixture per module en
    bouwen voort op eerdere tests in dezelfde module. Met de standaard
    verdeling over workers kwamen die op verschillende workers terecht en
    faalden ze wisselend. Met ``loadgroup`` blijven tests met dezelfde
    ``xdist_group`` op één worker; de rest wordt verdeeld zoals voorheen.

    De workers lezen de opdrachtregel opnieuw en zien de aanpassing van de
    controller niet; daarom gaat de keuze mee via ``workerinput``.
    """
    werker = getattr(config, "workerinput", None)
    if werker is not None:
        if werker.get("gs_loadgroup"):
            config.option.loadgroup = True
        return
    if getattr(config.option, "dist", "no") == "load":
        config.option.dist = "loadgroup"


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node):
    node.workerinput["gs_loadgroup"] = (
        node.config.getoption("dist", "no") == "loadgroup"
    )
