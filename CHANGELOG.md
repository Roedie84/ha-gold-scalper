# Changelog — Gold Scalper

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
