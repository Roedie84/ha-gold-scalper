"""1.7.10 - rooster: klokrand is geen afwijking (leerronde 9 oktober).

Elke nacht stond twee keer 'De broker meldt de markt gesloten terwijl het
rooster hem open zegt ... vrijwel altijd een feestdag' in het logboek: om
22:59:59 (broker net dicht, onze klok een fractie eerder) en om 23:59:59,06
(het rooster rekende 23:59:59 als laatste pauzeseconde, maar met de
microseconden erbij was het al 'open'). Geen van beide is een feestdag.
Wat er gehandeld mag worden verandert niet: bij onenigheid wint 'gesloten'.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.schedule import (  # noqa: E402
    ROOSTERGRENS_MARGE_S, SPOT_GOLD, bij_roostergrens, cross_check, is_open,
)

AMS = ZoneInfo("Europe/Amsterdam")


def test_de_laatste_pauzeseconde_is_ook_met_microseconden_dicht():
    moment = datetime(2026, 10, 8, 23, 59, 59, 61_625, tzinfo=AMS)
    assert is_open(SPOT_GOLD, moment)[0] is False
    tradeable, note = cross_check(False, SPOT_GOLD, moment)
    assert tradeable is False and note is None


def test_na_middernacht_weer_open():
    assert is_open(SPOT_GOLD, datetime(2026, 10, 9, 0, 0, 0, 500, tzinfo=AMS))[0] is True


def test_een_seconde_voor_de_pauze_is_een_klokrand():
    moment = datetime(2026, 10, 8, 22, 59, 59, 98_115, tzinfo=AMS)
    tradeable, note = cross_check(False, SPOT_GOLD, moment)
    assert tradeable is False and note  # er wordt nog steeds niet gehandeld
    assert bij_roostergrens(SPOT_GOLD, moment) is True


def test_midden_in_de_sessie_is_geen_klokrand():
    moment = datetime(2026, 10, 8, 14, 0, tzinfo=AMS)
    assert bij_roostergrens(SPOT_GOLD, moment) is False
    # een echte afwijking (feestdag) blijft dus een waarschuwing
    assert cross_check(False, SPOT_GOLD, moment)[1]


def test_vrijdagsluiting_en_maandagopening_zijn_ook_grenzen():
    vrijdag = datetime(2026, 10, 9, 23, 0, 5, tzinfo=AMS)
    maandag = datetime(2026, 10, 12, 0, 0, 3, tzinfo=AMS)
    assert bij_roostergrens(SPOT_GOLD, vrijdag)
    assert bij_roostergrens(SPOT_GOLD, maandag)
    assert ROOSTERGRENS_MARGE_S == 15
    assert bij_roostergrens(SPOT_GOLD, datetime(2026, 10, 9, 23, 1, 0, tzinfo=AMS)) is False


def test_utc_moment_werkt_ook():
    moment = datetime(2026, 10, 8, 20, 59, 59, tzinfo=timezone.utc)
    assert bij_roostergrens(SPOT_GOLD, moment)


def test_de_coordinator_meldt_een_klokrand_niet_als_waarschuwing():
    bron = (Path(__file__).parent.parent / "custom_components" / "gold_scalper" / "coordinator.py").read_text()
    blok = bron[bron.index("if note != self._last_schedule_note:"):][:400]
    assert "_LOGGER.debug if bij_roostergrens(SPOT_GOLD, now)" in blok
    assert "else _LOGGER.warning" in blok
    assert 'melden("Handelstijden: %s", note)' in blok


PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def test_version_is_consistent():
    import json

    from gold_scalper import const

    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION == "1.7.10"
    readme = (PKG.parent.parent / "README.md").read_text(encoding="utf-8")
    assert "Huidige versie: **1.7.10**" in readme
    changelog = (PKG.parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.split("## ")[1].startswith("1.7.10")
