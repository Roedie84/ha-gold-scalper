# Changelog — Gold Scalper

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
