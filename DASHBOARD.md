# Dashboard

Sinds 1.4.0 verschijnt het dashboard vanzelf. Geen knop indrukken, geen YAML
plakken, geen `www/`-map, geen herstart.

## Broker-dashboard (1.8.0)

Het menu-item **Gold Scalper** in de zijbalk (`/gold-scalper`) toont sinds
1.8.0 het broker-dashboard: een eigen webcomponent
(`frontend/broker-panel.js`, geregistreerd als `panel_custom`) in plaats van
de iframe met het overzicht. Zelfde zijbalk-ingang, dus geen handwerk. De
module-URL draagt `?v=<versie>-<inhoudshash>`, zodat de browser na een update
geen oude code houdt; ververs na de update eenmaal de browser.

Indeling (desktop raster, telefoon één kolom, geen horizontale scroll):

1. Kopbalk: merk-icoon, instrument, DEMO/PAPIER/ECHT GELD, markt open/dicht,
   status, handel aan/uit, toestand, noodstop/dataprobleem, bied/laat, klok.
2. Account-strip: equity en saldo, open P&L, dag-P&L (equity t.o.v.
   dagstart), netto van de run, kosten, vermogensvloer met afstand.
3. Koersgrafiek: candlesticks zelf getekend op canvas (geen bibliotheek of
   CDN), tijdframe 1m/5m/15m door aggregatie, crosshair met OHLC, scrollen =
   zoom, slepen = schuiven, dubbelklik = terug. Voor een open positie lijnen
   voor instap (met richting, units en P&L), stop-loss (rood) en
   take-profit (groen); recente trades als driehoekjes (instap) en bolletjes
   (uitstap, groen/rood naar resultaat).
4. Open positie en markt: P&L, SL/TP-ligging, tijdstop- en
   maximale-duuraftelling; bied/laat, dagbereik, spread, ATR, signaal.
5. Open posities, equity en drawdown, recente trades (laatste 20, met
   sluitreden en kostenbron gemeten/berekend), onderzoek en statistiek.
6. Sinds 1.9.0: **Schaduwtrades (gesimuleerd)**, een apart gestippeld paneel
   onderaan: aantal, winst%, profit factor, netto na geschatte kosten,
   t-statistiek op clusters en waarom de signalen niet werden uitgevoerd.
   Telt níet mee in het resultaat, de statistiek of de bewijsfase.

Meerdere posities (1.9.0): de tabel *Open posities* toont elke positie per
ticket met eigen P&L (live, indicatief) en tijdstopaftelling; de grafiek
tekent instap-, stop- en doellijnen per positie. De kop toont de telling
"x long · y short / max n" en een rode chip *netting* als de broker
tegengestelde posities verrekende. Het paneel *Open positie* toont de eerste
positie en het aantal open per richting.

Alleen weergave: geen knoppen die handelen, sluiten of iets aan- of
uitzetten. Bediening blijft via de entiteiten en acties van de integratie.
Het klassieke overzicht en het keuringsrapport zijn onderaan gelinkt.

### Route `/api/gold_scalper/broker`

* `GET`, `requires_auth`, alleen beheerders (zoals het paneel). Geen andere
  methodes; de database gaat open met een eigen alleen-lezende verbinding
  (`mode=ro`).
* Antwoord: één JSON-model (`api: 1`) met `instrument`, `koers`, `status`,
  `alarm`, `candles` (hooguit 720), `posities`, `account`, `equity`
  (hooguit 400 punten, gelijkmatig over de run), `trades` (laatste 20),
  `markers` (trades binnen het candlevenster), `stats` en `sleutel`.
  Sinds 1.9.0 daarnaast `posities_telling` (`long`, `short`, `limiet`),
  `netting` (null of de gedetecteerde verrekening) en `schaduw` (aantal,
  open, vervallen, winst%, pf, netto, kosten, verwachting, clusters, t,
  per reden). Alleen toegevoegd, niets hernoemd; daarom blijft `api: 1`.
* Per coordinatorcyclus één keer gebouwd. Het paneel vraagt elke 5 s met
  `?since=<sleutel>`; zolang er geen nieuwe cyclus was is het antwoord
  `{"ongewijzigd": true}`. Bij een verborgen tabblad vraagt het niets.
* Optioneel `?entry=<entry_id>` bij meerdere configuraties.
* "Clusters x van 30" is een richtgetal voor de weergave, geen poort.

### Live koers via IG-streaming (1.8.1, HTTP-streaming sinds 1.8.2)

* Alleen met IG als broker in **demo- of live-modus**; in paper (of met een
  andere databron) blijft het dashboard op de 5-s-poll.
* Het paneel abonneert zich via de bestaande websocket van Home Assistant op
  `gold_scalper/broker_stream` (alleen beheerders, geen schrijfacties). De
  integratie opent dan één alleen-lezende Lightstreamer-verbinding
  (eigen minimale TLCP-2.1.0-client over aiohttp met HTTP-streaming:
  `create_session.txt`, `control.txt`, `bind_session.txt` na LOOP; geen
  extra afhankelijkheid. De websocket van 1.8.1 werd door IG gesloten)
  voor `MARKET:<epic>` (BID, OFFER, UPDATE_TIME, CHANGE, CHANGE_PCT, HIGH,
  LOW, MARKET_STATE).
* Inloggegevens komen uit de bestaande IG-sessie van de cyclus
  (`lightstreamerEndpoint`, account-ID, `CST-<cst>|XST-<xst>`): **geen extra
  REST-verzoek**. Logt de cyclus opnieuw in, dan verbindt de stroom opnieuw
  met de nieuwe tokens.
* Start bij het eerste open paneel, stopt 60 s na het laatste, en bij
  unload/afsluiten. Hooguit 4 koersen per seconde naar het paneel.
* Bij een fout: één WARNING met transport, HTTP-status en eerste
  serverregel (nooit tokens), status "elke 5 s" (grijs) in de kopbalk,
  opnieuw proberen met oplopende wachttijd (2 s tot 2 min).
* Het paneel toont LIVE (groen) met bied/laat, de lopende candle en
  prijslijn, en open P&L per positie en in de account-strip, gemarkeerd
  **live, indicatief**. Het officiële bedrag blijft dat van de broker per
  cyclus (staat er onder "broker (per cyclus)" bij).
* De stroom voedt niets in strategie, in-/uitstap, risico, orders of de
  coordinatorcyclus; een test bewaakt dat.

## Meetkwaliteit

Sinds 5.5.0 staat op de overzichtspagina een blok **Meetkwaliteit**: de
wisselkoers en of nieuwe posities zijn toegestaan, de vermogensvloer en de
ruimte erboven, hoe trades eindigden (met het onbekende deel), de laatste
afstemming met de broker, de candlebron en hoeveel kosten gemeten zijn.

Dezelfde informatie bestaat als negen sensoren, voor je eigen dashboards en
automatiseringen.

## Een Lovelace-dashboard

    action: gold_scalper.write_dashboard

Schrijft `/config/gold_scalper_dashboard.yaml` met de entiteit-id's die Home
Assistant werkelijk heeft toegekend, uit het entiteitenregister. Plak de inhoud
in de ruwe configuratie-editor van een dashboard. Het vroegere voorbeeld in
`dashboard/lovelace.yaml` verwees naar gegokte id's en is vervangen.

## Het keuringsrapport

Na het toevoegen van de integratie staat **Gold Scalper** in je zijbalk, met een
goudkleurig icoon. Klik erop.

Het rapport wordt bij elke keer openen opnieuw gebouwd uit de database, dus wat
je ziet is altijd actueel. Ververs de pagina om bij te werken.

Direct adres, als je het buiten de zijbalk wilt openen:

```
http://homeassistant.local:8123/api/gold_scalper/report
```

### Wat je ziet vóór de eerste trade

Een rapport met de stempel **IN KEURING** en "Nog geen gesloten trades". Dat is
de juiste uitkomst, geen fout. Zodra er posities gesloten worden vullen de
equitycurve, de dagstaven en de tradelijst zich.

De signaaltrechter vult zich wél meteen: die telt élke evaluatie, ook de
afgewezen. Blijft het aantal trades op nul terwijl de evaluaties oplopen, dan
staat daar waaróm.

### Beveiliging, eerlijk benoemd

Het paneel vraagt geen authenticatie. Dat moet: een iframe in de Home
Assistant-frontend stuurt geen bearer-token mee, dus met authenticatie aan zou
het paneel simpelweg leeg blijven.

Gevolg: iedereen die je Home Assistant kan bereiken, kan dit rapport lezen. Er
staan handelsresultaten, posities en statistieken in — **geen** API-tokens,
account-ID's of inloggegevens. Die komen in de rapportgenerator niet voor, en
`tests/test_http_panel.py::test_report_never_contains_credentials` bewaakt dat.

Wil je het paneel niet, zet dan **Toon 'Gold Scalper' in de zijbalk** uit bij
de opties. Het adres blijft dan wel werken.

## Het Lovelace-dashboard

Voor live entiteiten in plaats van een momentopname.

Instellingen → Dashboards → **Nieuw dashboard toevoegen** → open het → potlood
rechtsboven → driepuntsmenu → **Ruwe configuratie-editor**. Plak de inhoud van
`dashboard/lovelace.yaml`.

Wil je het rapport eronder, voeg dan toe:

```yaml
      - type: iframe
        url: /api/gold_scalper/report
        aspect_ratio: 180%
```

## Als je niets ziet

Loop dit af, in deze volgorde:

**1. Laadt de integratie?** Instellingen → Apparaten en diensten → Gold
Scalper. Staat daar een foutmelding, kijk dan in Instellingen → Systeem →
Logboek.

**2. Zijn er entiteiten?** Klik door naar het apparaat. Je hoort er ruim twintig
te zien, waaronder `sensor.gold_scalper_koers`. Staat die op `onbekend`, dan
komt er geen data binnen.

**3. Staat het menu-item er?** Zo niet, ververs je browser hard (Ctrl+Shift+R).
Home Assistant cachet de zijbalk.

**4. Werkt het adres rechtstreeks?** Open
`http://homeassistant.local:8123/api/gold_scalper/report` in een tabblad. Krijg
je daar wel iets en in de zijbalk niet, dan is het een cacheprobleem.

## Waar te beginnen

De eerste dagen zijn twee entiteiten het interessantst.

`sensor.gold_scalper_spread` — bij publieke marktdata is dit je *aanname*, niet
een meting. Staat hij op 0, dan zijn de kosten uitgeschakeld en is elk
resultaat fictief.

`sensor.gold_scalper_evaluaties` — de trechter. Blijft `acted` op nul met
`edge_below_cost` als voornaamste reden, dan is je tijdsframe te laag voor de
spread en is M15 de volgende stap.
