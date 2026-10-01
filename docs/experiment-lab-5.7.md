# Experiment Lab 5.7 (fase 9B deel 1): diensten, leesmodellen, lifecycle

**EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING**

Basis: GitHub `752c044` (5.6.2). Geen dashboard; dat is 5.8.

## Lagen

```
Home Assistant
  __init__.py      7 diensten (lab_*), schema uit ACTION_FIELDS, response verplicht
  lab_panel.py     beheerderscontrole, leesmodelroute, voortgangsevents, unload
        │  alleen paden, gewone waarden
        ▼
  lab_actions.py       invoercontrole, idempotentie, leesbaar antwoord   (zonder hass)
  lab_read_models.py   12 leesmodellen, allowlisted                     (zonder hass)
        │
        ▼
  experiment_lab/      bestaande logica: snapshot, walk-forward, runner,
                       beoordeling, vergelijking; research_design.py (nieuw)
```

Geen enkele 5.7-module raakt een config entry, de strategie, de broker, de
modus, de live-gate of risico-instellingen. Statische tests bewaken dat.

## Diensten

Alle via Ontwikkelhulpmiddelen → Acties, met *Reactie* aan. Alle eisen een
**ingelogde beheerder** (server-side). Een aanroep zonder gebruiker, zoals een
automatisering, wordt geweigerd. Een script dat een beheerder start, werkt wel.

| Dienst | Doet | Opent TEST |
|---|---|---|
| `lab_snapshot` | dataset uit het barsarchief (alleen lezen) | nee |
| `lab_create_walk_forward` | concept-walk-forward met bestaande validatie | nee |
| `lab_register` | concept → registered | nee |
| `lab_start` | start via de runner; wacht niet | nee |
| `lab_cancel` | concept/geregistreerd/lopend → cancelled | nee |
| `lab_assess` | beoordeling (fase 7) | **ja, eerste toegang** |
| `lab_compare` | vergelijking; standaard uit beoordelingen | alleen DEEP |

`DEEP_RESULT_COMPARISON` vraagt `confirm_test_reuse: true`; anders
`confirmation_required` met uitleg dat het als hergebruik telt.

Antwoordvorm, altijd:

```
ok, action, object_id, replayed, message, data | error{code, message, object_id}
```

Geen paden, geheimen, tracebacks of volledige tradelijsten. Paden in invoer
worden geweigerd (`path_not_allowed`), onbekende velden ook
(`unknown_parameter`), onbekende configsleutels via de worker-validatie
(`invalid_config`).

### Idempotentie

Optioneel `request_id` (8-64 tekens) bij snapshot, concept, registreren,
starten, beoordelen en vergelijken. Zelfde id + zelfde actie + zelfde invoer:
het eerdere antwoord, `replayed: true`, niets dubbel. Andere actie of invoer:
`request_id_conflict`. Opslag in `lab_requests`: alleen geslaagde verzoeken,
30 dagen, hooguit 1000 regels; opruimen bij elk nieuw verzoek.

### Voorbeeld

```yaml
action: gold_scalper.lab_create_walk_forward
data:
  name: basis bruto OOS
  hypothesis: gemiddeld bruto OOS-resultaat per trade is niet nul
  expected_effect: onbekend
  hypothesis_family_id: bruto-oos
  dataset_id: 1
  mode: SEQUENTIAL_OOS
  train_days: 5
  test_days: 2
  window_count: 3
  candidates:
    - label: huidig
      config:
        strategy: {entry_threshold: 0.45, take_profit_atr: 1.5, stop_loss_atr: 1.0}
        exits: {max_hold_seconds: 900}
        execution: {spread: 0.6, slippage: 0.05, units: 2.0, instrument_currency: USD}
```

## Leesmodellen

`GET /api/gold_scalper/lab/v1/<model>?id=<n>` (of `?family=<id>`), ingelogde
beheerder, `no-store`. Modellen: `overview`, `experiments`, `experiment`,
`progress`, `test_status`, `datasets`, `dataset`, `assessments`, `assessment`,
`comparisons`, `comparison`, `family`. Elk veld staat in
`lab_read_models.MODEL_KEYS`; een test vergelijkt exact.

* Geen leesmodel opent TEST of logt een toegang.
* `TestStatus` en `ExperimentDetail` tonen nooit een TEST-prestatie.
* `AssessmentDetail` en `ComparisonDetail` dragen altijd de disclaimer.
* `ComparisonDetail.metric_comparison_available` is `false` bij een
  vergelijking zonder metriekverschillen; er wordt nooit diep gelezen om ze te
  krijgen.

## Voortgang en events

* `gold_scalper_lab_progress`: elke 5 s gekeken, hooguit elke 10 s een event,
  alleen bij verandering (status, venster, kandidaat, segment, ≥ 1 %).
  Velden: `experiment_id, status, progress_pct, windows_total, current_window,
  windows_completed, candidates_total, current_candidate, current_segment,
  bars_total, bars_processed`.
* `gold_scalper_lab_finished`: id en eindstatus, plus een melding.
* `gold_scalper_lab_action`: actie, ok, object-id.

## Unload met een lopend experiment

1. geen nieuwe start meer (`lab_unloading`);
2. de runner krijgt `interrupt()`, stopt het werkproces zelf en beëindigt het
   na zijn bestaande wachttijd;
3. hooguit 30 s wachten;
4. staat het daarna nog op `running`: zelf naar `interrupted`;
5. `queued` blijft `queued` en start niet;
6. de handel wordt niet aangeraakt.

Een `interrupted` experiment start na herladen niet opnieuw: het is een
eindstatus.

## Schema 9 (Lab-database)

Eén transactie, idempotent, bij het eerste openen na de update.

* `access_purposes` (code, segment_log, walk_forward_log, registered_in_schema):
  FINAL_EVALUATION, REPRODUCTION_REVIEW, AUDIT, DEBUG_AFTER_FAILURE
  (beide logs), ASSESSMENT, COMPARISON (alleen walk-forwardlog). Alleen
  toevoegen; bijwerken en verwijderen geweigerd.
* `test_access_log` en `wf_test_access_log` herbouwd, **voor de laatste keer**:
  `purpose` verwijst met een foreign key naar `access_purposes`; een trigger
  bewaakt in welke log een doel mag. Alle bestaande regels gaan ongewijzigd
  mee; de alleen-toevoegen-triggers komen terug. Een nieuw doel is voortaan één
  `INSERT OR IGNORE` in een migratie.
* `lab_requests` voor idempotentie.

`OOS_AGGREGATE_READ` is in de code een `access_type`, geen doel; het staat
daarom niet in `access_purposes`.

## Tradedatabase en rapport

* Kolom `exit_price_provenance` (JSON). Een uitstapprijs die hooguit 0,01
  afwijkt van IG, wordt overgenomen; de oude waarde, de brokerprijs, het
  verschil, de status, de bron en het tijdstip staan erbij. Groter verschil:
  afwijking, niet overgenomen.
* Rapport: kolom **Ounces** (opgeslagen lots × `CONTRACT_SIZE`), met de lots
  als tooltip.

## IG-verzoeken

`diagnostics → ig_requests`: aantal historische-prijsverzoeken, live
koersverzoeken en overige, sinds de start. `historical_allowance` alleen als IG
het meegeeft (`metadata.allowance` bij historische prijzen); anders leeg.
Geen import_history in 5.7.

## Onderzoeksopzet

`experiment_lab/research_design.py`: eerst H0 bruto (gemiddeld bruto
OOS-resultaat per trade = 0, tweezijdig), daarna H0 netto met alle kosten. De
omgekeerde strategie is `SANITY_CHECK`, `independent_evidence = False`. Geen
wijziging van de beoordelingsregels; geen parameteraanpassing.

## Piramide

Bijkopen wordt niet vastgelegd in administratie of afstemming. Piramide mag
pas aan als dat wel gebeurt. Staat het aan, dan waarschuwt het log bij elke
start; de instelling wordt niet gewijzigd.

## Acceptatie op Home Assistant 2026.9

Alle punten: **NOT_TESTED — requires real Home Assistant 2026.9 installation.**

1. Na herstart: Lab-paneel toont 5.7.0 en schema 9 (verwacht 9).
2. Ontwikkelhulpmiddelen → Acties toont zeven `Gold Scalper: Lab: …`-acties.
3. `lab_snapshot` met `symbol: GOLD`, `timeframe: 15m` geeft een leesbare
   reactie met dataset, bars en kwaliteit.
4. Dezelfde aanroep nog eens: `reused: true`, zelfde dataset.
5. `lab_create_walk_forward` (voorbeeld hierboven) geeft een concept.
6. `lab_register` toont "TEST blijft verzegeld."
7. `lab_start` keert direct terug; voortgangsevents in Ontwikkelhulpmiddelen →
   Events (`gold_scalper_lab_progress`), niet meer dan één per 10 s.
8. Na afloop: melding *Gold Scalper Lab: Experiment n: completed*.
9. `lab_assess`: classificatie met disclaimer.
10. `lab_compare` zonder mode: ASSESSMENT_COMPARISON, geen winnaar.
11. `lab_compare` met DEEP zonder bevestiging: `confirmation_required`.
12. Een niet-beheerder krijgt `forbidden`.
13. `/api/gold_scalper/lab/v1/overview` in een privévenster: 401.
14. Herladen tijdens een lopend experiment: experiment wordt `interrupted`,
    start niet opnieuw; geen `worker_entry`-proces achtergebleven.
15. Handel ongewijzigd: zelfde run-ID, opties ongewijzigd, geen noodstop.
16. Diagnose bevat `ig_requests`.
17. Rapport: kolom Ounces gelijk aan de grootte bij IG.
