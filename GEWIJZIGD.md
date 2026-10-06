# Van 1.0.0 naar 1.1.0

Eén zip met alleen de gewijzigde bestanden sinds 1.0.0. Suite: **1650 tests
groen**, 1 overgeslagen (de test die een echte Home Assistant vraagt).

## Uitpakken

Inhoud naar de repository slepen, committen, release `v1.1.0` maken, in HACS
bijwerken, Home Assistant herstarten.

## Wat je merkt

* Eenmalig een **nieuwe run** (de groottemethode zit nu in de vingerafdruk).
  Run 99 blijft bewaard; vanaf nu bevat een run nooit meer twee
  groottemethoden.
* Nieuwe beoordelingen hebben `GROSS_EVIDENCE` (bruto per trade tegen nul) en
  de juiste Bonferroni-drempel bij één kandidaat.
* Bestaande beoordelingen veranderen niet.

## Bestanden

* `custom_components/gold_scalper/coordinator.py`
* `custom_components/gold_scalper/experiment_lab/assessment.py`
* `custom_components/gold_scalper/experiment_lab/storage.py`
* `custom_components/gold_scalper/experiment_lab/research_design.py`
* `custom_components/gold_scalper/const.py`, `manifest.json` (1.1.0)
* `tests/test_release_110.py` (nieuw), `tests/test_lab_comparison.py`,
  `tests/test_lab_services_57.py`
* `CHANGELOG.md`, `GEWIJZIGD.md`
