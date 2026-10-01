# Herkomst van fase 4 van het Experiment Lab

Technische aantekening, zodat de oorsprong van fase 4 traceerbaar blijft.

| | |
|---|---|
| basiscommit (fase 3) | `d023da9` |
| eindcommit (fase 4) | `543feac` |

## Wat er gebeurde

Tijdens fase 4 was de werkomgeving van Claude een tijd onbereikbaar. Toen hij
terugkwam, bevatte de werkkopie niet-gecommit werk voor fase 4 (tijdstempels
13:41–13:52 op 29-09-2026):

**Nieuw, niet gevolgd door git**

- `custom_components/gold_scalper/experiment_lab/costs.py`
- `custom_components/gold_scalper/experiment_lab/metrics.py`
- `custom_components/gold_scalper/session_rules.py`
- `tests/test_lab_metrics.py`

**Gewijzigd, niet gecommit**

- `custom_components/gold_scalper/analysis/backtest.py`
- `custom_components/gold_scalper/experiment_lab/runner.py`
- `custom_components/gold_scalper/experiment_lab/storage.py`
- `custom_components/gold_scalper/experiment_lab/worker.py`
- `custom_components/gold_scalper/learning/sessions.py`
- `tests/test_backtest_window.py`, `tests/test_lab_boundary.py`,
  `tests/test_lab_datasets.py`, `tests/test_lab_foundation.py`,
  `tests/test_lab_runner.py`

## Hoe het is beoordeeld

- De volledige diff tegen `d023da9` is inhoudelijk beoordeeld tegen de
  opdracht voor fase 4: schema, kostenformules, wisselkoersmodel,
  metriekdefinities, triggers en de controle door de controller.
- Aangevuld: markering van reproducties onder andere versies, een test die de
  motorversie aan haar uitvoer vastpint, en de beschrijving van het
  isolatiemechanisme van het werkproces.
- Een tijdsafhankelijke bestaande test is herschreven
  (`test_backtest_invert.py::test_the_distances_stay_the_same`).
- De volledige suite slaagde na de beoordeling: 1389 geslaagd, 1 overgeslagen.

Vanaf `543feac` vormen de gecommitte code, de diff en de tests de
controleerbare basis. De niet-gecommitte oorsprong is geen reden om fase 4
opnieuw te bouwen.

## Veiligheidskopie

`gold-scalper-lab-fase0-3-veiligheidskopie.zip` is uitsluitend een kopie van
fase 0–3, gemaakt zodat dat werk niet alleen in de werkomgeving bestond. Het is
**geen installatiebestand** en hoort niet in de repository, een release of het
HACS-pakket.
