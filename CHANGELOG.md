# Changelog — Gold Scalper

## 1.7.0

* **Een haperende koersopvraging maakt niet meer alles onbeschikbaar.** Op
  7 oktober liep de koersopvraging bij IG zes keer in anderhalf uur tegen de
  time-out van 6 s aan; elke keer werden álle entiteiten kort
  onbeschikbaar, ook de noodstop. Nu blijft het laatste beeld staan tot
  drie mislukte opvragingen op rij (`KOERS_HOUD_MAX_MISLUKT`) en zolang de
  laatste verse koers hooguit 180 s oud is (`KOERS_HOUD_MAX_SECONDEN`).
  *Dataprobleem* gaat dan aan, met `koers_verouderd`,
  `koers_leeftijd_seconden`, `koers_mislukt_op_rij` en `koers_fout` in de
  attributen (de eerste twee ook bij *Koers*), *Status* meldt
  `koers_verouderd`, en het log krijgt een waarschuwing. Pas daarna de oude
  storing.
* **Niet handelen op een oude koers.** Een vastgehouden cyclus beslist niets:
  geen signaal, geen instap, geen stop verplaatsen of sluiten. Stops en
  doelen staan bij de broker en werken gewoon door; het eigen exitbeheer
  wacht hooguit drie cycli. `_open_position` weigert bovendien zelf bij een
  verouderde koers.
* **Noodstop en Afstemming blijven zichtbaar**, ook na de drempel. De
  noodstop leest de risicobewaking rechtstreeks; de afstemming toont het
  laatste resultaat.
* **Statistiek per cluster.** De sensor *t-statistiek* toont per cluster
  (laatste 50) `per_cluster`: `nr`, `trades`, `start`, `eind`, `duur_min`,
  `netto_usd`, `bruto_usd` en `netto_eur` (alleen als de broker alle trades
  in het cluster in euro afrekende). Daarbij hoe zwaar het grootste cluster
  weegt: `grootste_cluster_aandeel_trades_procent`,
  `grootste_cluster_aandeel_netto_procent` (absoluut resultaat als deel van
  de som van alle absolute clusterresultaten), `grootste_cluster_netto_usd`
  en `netto_zonder_grootste_cluster_usd`. Zo is te zien of één
  trendepisode het resultaat draagt.

## 1.6.1

* **Minder ruis in het log.** "Geen transactie gevonden" is alleen nog een
  waarschuwing als de broker het sluitmoment van de trade al voorbij is.
  Loopt zijn transactieoverzicht nog achter (nieuwste regel van voor het
  sluiten), dan is niet vinden normaal en staat de regel op debug; de
  correctie zoekt later opnieuw. Op 7 oktober gaf dat vijf waarschuwingen
  voor trades van het laatste uur.
* De eenmalige regel met de veldnamen van het transactieoverzicht staat op
  debug; die velden zijn sinds 1.4.0 bekend.

## 1.6.0

* **t-statistiek over clusters.** Trades die binnen 10 minuten na het sluiten
  van de vorige openen, tellen als één cluster (`CLUSTER_MINUTEN`). Op
  7 oktober opende de bot vier trades in vier minuten, telkens ~10 s na het
  sluiten; dat zijn geen vier onafhankelijke waarnemingen, en per trade
  tellen maakte de toets te zeker. `t_statistic` (en dus het oordeel) gaat nu
  over clusters; de oude waarde staat in `t_statistic_per_trade`, met
  `clusters` en `t_basis` erbij. De sensor *t-statistiek* toont ze als
  attributen.
* **Versienummer.** `INTEGRATION_VERSION` liep sinds 1.4.0 achter op het
  manifest (de diagnose meldde 1.4.0 terwijl 1.5.0 draaide).

## 1.5.0

* **Veilig herstarten uit één bron.** De binaire sensor *Veilig herstarten*
  en het attribuut `safe_to_restart` van *Toestand* spraken elkaar tegen
  (aan tegenover false bij running, 0 open). Beide komen nu uit
  `lifecycle.veilig_herstarten()`: zonder open posities altijd veilig, mét
  posities pas na afwikkelen. De oude betekenis staat in
  `levenscyclus_afgewikkeld`.
* **Latency bij weinig metingen.** *Latency p99* bleef unknown tot 100
  metingen. Nu p90 vanaf 20 metingen, met `basis` (bijv. "p90, p99 pas vanaf
  100 metingen (n=24)") en `metingen` in de attributen. Onder de 20 metingen
  blijft hij bewust leeg.

## 1.4.0

* **Afstemming herkent slippage.** Klopt een trade met de broker op
  instapprijs, richting, omvang én openingsmoment (`openDateUtc`, binnen tien
  minuten), dan is een verschil in uitstapprijs geen verkeerde koppeling maar
  slippage. De prijs van de broker wordt overgenomen, met de oude waarde in
  `exit_price_provenance` (`ADOPTED_BROKER_SETTLEMENT_SLIPPAGE`), en het telt
  niet meer als afwijking. Bij een zwakke koppeling blijft het een afwijking.
* **Koppelen op openingsmoment.** Het veld `reference` van IG is niet het
  dealId van de positie (dat koppelde nooit); het openingsmoment wel. Twee
  trades met dezelfde instapprijs uren na elkaar worden zo niet meer verwisseld.
  De referentie van IG wordt bij een overname vastgelegd.
* **Afstemming elk kwartier zolang er iets openstaat** (afwijking of trade die
  de broker nog niet verwerkte), anders elk uur.
* **Gemeten kosten.** Met de afrekening van de broker worden de kosten per
  trade gemeten: instap tegen het midden, uitstap tegen het order­niveau
  (stop/doel) of het midden (eigen sluitorder), gesplitst in spread en
  slippage. `cost_source` gaat dan naar `measured`.
* **Opstartmelding gaat niet meer verloren.** Bestaat de notify-dienst nog
  niet (mobile_app laadt vaak later), dan wacht de melding en wordt elke 30 s
  opnieuw geprobeerd, tot tien minuten.

## 1.3.0

* **Namen en labels** in het Lab mogen komma's, accenten en `&` bevatten. De
  foutmelding noemt nu welke tekens zijn toegestaan.
* **Voortgang bij walk-forward**: `bars_total` en `bars_processed` worden
  gevuld, opgeteld over alle eenheden; na afloop zijn ze gelijk.
* **Leesmodel versie 2**: `AssessmentDetail` geeft per component de details
  (gemiddelde, spreiding, standaardfout, interval). Bij `GROSS_EVIDENCE`
  daarmee ook gemiddeld bruto, netto en kosten per trade.

## 1.2.0

* **`import_history` gaat terug in de tijd.** Nieuw veld `days`: zoveel dagen
  vóór de oudste bar in het archief, opgehaald in blokken van een week via een
  datumbereik bij IG. Tot nu toe vroeg de dienst alleen de laatste bars op
  (bij IG hooguit 1000), en die stonden al in het archief.
* **Puntenbudget** `max_points` (standaard 5000). Stopt vóór het blok dat het
  budget zou overschrijden, en ook als IG meldt dat het quotum bijna op is.
  Een fout halverwege bewaart wat al binnen was.
* **Leesbare reactie**: opgehaald, nieuw, gebruikte punten, waar gestopt en
  waarom, resterend quotum (alleen als IG het meegeeft), en de stand van het
  archief.

## 1.1.0

* **Brutotoets in de beoordeling** (regelversie 2). Nieuwe component
  `GROSS_EVIDENCE`: gemiddeld bruto OOS-resultaat per trade tegen nul,
  tweezijdig, met dezelfde gecorrigeerde drempel als de nettotoets. Toont ook
  gemiddeld bruto, netto en kosten per trade. Niet blokkerend; de classificatie
  blijft op netto. Beoordelingen uit regelversie 1 blijven ongewijzigd; een
  vergelijking tussen versie 1 en 2 krijgt de waarschuwing
  `ASSESSMENT_RULES_DIFFER`.
* **Telling geëvalueerde configuraties gecorrigeerd.** Een walk-forward met één
  kandidaat telde als twee (de experimenthash én de kandidaat). Daardoor was de
  drempel te streng (t = 2,25 in plaats van 1,96).
* **Groottemethode in de vingerafdruk.** Vast of uit risico bepaald (en het
  risicopercentage) start bij wijziging een nieuwe run. Bij deze update begint
  daarom eenmalig een nieuwe run; de vorige blijft bewaard. Het maximum blijft
  erbuiten (een limiet).

## 1.0.0

Eerste release in `Roedie84/ha-gold-scalper`. Inhoudelijk gelijk aan
Goldscalper 5.7.0 uit `Roedie84/Goldscalper`; alleen versienummer, URL's en
README zijn aangepast. Domein `gold_scalper` ongewijzigd.

Wat 1.0.0 bevat, met de oude versienummers erbij:

* **Experiment Lab (fase 0-8, 9A, 9B deel 1)** - onderzoek op historische
  data, nooit live orders (`EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING`).
  * datasets, segmenten, walk-forward, beoordeling, vergelijking;
  * Lab-paneel via `panel_custom`, met geauthenticeerde statusroute (5.6.0);
  * zeven Lab-acties met leesbare reactie en idempotentie, twaalf
    leesmodellen, gedempte voortgangsevents, unload die een lopend experiment
    op `interrupted` zet, Lab-schema 9 met `access_purposes` (5.7.0).
* **Handelslus**
  * onbevestigde orders worden teruggezocht en blokkeren nieuwe orders, in
    plaats van opnieuw verstuurd (5.6.1).
* **Administratie**
  * bedragen exact volgens IG: omrekenkoers van de broker, overname bij de
    afstemming, afstemming elk uur (5.6.2);
  * uitstapprijs tot een cent overgenomen van IG met herkomst; rapport in
    ounces (5.7.0).
* **Diagnose**: tellingen van IG-verzoeken; quotum alleen als IG het meegeeft.

Bekende beperking: bijkopen (piramide) wordt niet vastgelegd. Laat piramide
uit; het log waarschuwt als het aan staat.

Oudere geschiedenis (tot en met 5.7.0) staat in de vorige repository.
