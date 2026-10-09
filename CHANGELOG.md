# Changelog — Gold Scalper

## 1.9.1

* **Geen strategiewijziging.** Alleen de live koers en de layout van het
  dashboard; de handel is niet aangeraakt.
* **Live koers via alternatieve IG-items.** IG antwoordde op
  `MARKET:<epic>` met "REQERR 21 Invalid group". Bij REQERR 21-24 probeert de
  stroom nu vanzelf, in deze volgorde: `MARKET:<epic>` met minimale velden
  (BID OFFER UPDATE_TIME MARKET_STATE), `CHART:<epic>:TICK` (DISTINCT; BID OFR
  LTP UTM) en `CHART:<epic>:1MINUTE` (MERGE; BID_CLOSE OFR_CLOSE UTM
  CONS_END). Wat werkt, wordt onthouden voor de volgende verbinding. Pas als
  alles geweigerd wordt, komt er één WARNING met de REQERR-code per variant.
  Geen `LS_data_adapter` (IG gebruikt de standaardadapter); `:` in de groep
  gaat correct gecodeerd als `%3A`.
* **Markt-kaart**: lange waarden (bijv. "waarom geen trade") lopen nu over
  meerdere regels binnen de kaart in plaats van er rechts buiten. Ook de
  regel "live, indicatief" in de account-strip blijft op een telefoon binnen
  de tegel. Het dashboard vult de beschikbare breedte (maximaal 1800 px,
  gecentreerd).
* **Na de update eenmaal de browser verversen** (nieuwe paneelcode).
* Nieuw: `tests/test_v191.py` (variantvolgorde, chart-ticks, Playwright-check
  van de kaarten op 1496 en 390 px).

## 1.9.0

**Besluit van de eigenaar (Ruud, 09-10-2026, 07:59)**, na uitleg van de
nadelen: *"meer posities mogen worden geopend, dit om sneller data te
vergaren … long en short mag gelijktijdig ook meerdere"*. Gekozen: maximaal
3 posities per richting (dus hooguit 3 long + 3 short = 6 tegelijk), elke
positie op haar huidige grootte (geen verdeling van het risico), en
schaduwtrades. Dit vervangt de eerdere regels "max 1 positie / geen
pyramiding / strategie niet wijzigen tot 30 clusters" **alleen voor dit
punt**. Al het andere blijft gelijk: niets richting live (alleen demo/paper),
vloer, daglimiet, noodstop, dead man's switch, tijdstop, SL/TP-logica en
signaallogica.

> **Waarschuwing.** Elke positie houdt haar volle grootte. Bij drie
> posities in dezelfde richting zijn kosten (spread, slippage) en risico
> van één marktbeweging tot **3×** zo groot als voorheen; met long en short
> tegelijk betaal je bovendien kosten aan beide kanten.

* **Nieuwe optie** *Maximaal posities per richting*
  (`max_positions_per_richting`, 1..3, standaard 3) in de opties. Een
  signaal opent een positie als er in die richting minder dan de limiet
  open staan (onbevestigde orders tellen mee). Long en short mogen naast
  elkaar bestaan; een tegengesteld signaal sluit niets. Totaalvangnet in de
  risicobewaking: 2 × de limiet.
* **Minimale spreiding.** Een extra positie in dezelfde richting alleen in
  een **latere candle** dan de laatste open positie in die richting **én**
  met een instapprijs die **≥ 0,3 × ATR** verschilt van elke open positie in
  die richting (0,3 × ATR is de dode zone van de tijdstop). Daarnaast
  hooguit **één nieuwe positie per cyclus** en de bestaande cooldown.
* **Marge en vloer.** Een extra positie wordt geweigerd als de geschatte
  marge (5% van de nominale waarde) niet in 90% van de door de broker
  gemelde vrije marge past, of als de equity onder de vloer zou komen
  wanneer alle open stops plus de nieuwe stop geraakt worden.
* **Netting.** IG opent met `forceOpen: true` een aparte positie. Meldt de
  orderbevestiging toch een bestaande deal als (deels) gesloten
  (`affectedDeals`), of verdwijnt/krimpt een tegengestelde positie bij het
  openen (positielijst vlak na de order, alleen bij hedgen), dan: ERROR in
  het logboek, melding, attribuut `netting_gedetecteerd`, en hedgen staat
  uit tot een herstart. Geen stille verrekening.
* **Per positie.** Tijdstop, maximale duur, trailing, sluiten na
  bevestiging (1.7.9), sluitverzoek-genadetermijn (1.7.8), afstemming en
  opstartcontrole werkten al per ticket; nu getest met meerdere
  gelijktijdige posities in beide richtingen.
* **Statistiek.** Clusterdefinitie ongewijzigd: trades gesorteerd op
  opening, een trade die opent vóór of binnen 10 minuten na het laatste
  sluitmoment hoort bij hetzelfde cluster. Gelijktijdig open trades vallen
  daardoor altijd in één cluster en tellen niet als onafhankelijk. Nieuw
  veld per trade `gelijktijdig_open` (aantal andere open posities bij
  instap) om later te toetsen of stapelen iets toevoegt.
* **Nieuwe run.** De uitvoeringsversie gaat van 3 naar **4**. Die zit in de
  vingerafdruk en geldt als structureel, dus 1.9.0 start bij de eerste
  herstart een **nieuwe bewijsfase**; de run krijgt de aantekening
  `meerdere_posities`. Het aantal per richting zit ook in de vingerafdruk
  (`positielimiet`): wie het later wijzigt, start weer een nieuwe run. De
  markering "methodologisch gemengd" (overlap = fout) slaat runs met een
  limiet per richting over, want daar is overlap opzet.
* **Schaduwtrades.** Elk geldig signaal (door alle signaalfilters) dat niet
  wordt uitgevoerd vanwege positielimiet, cooldown, marge, vloer, netting,
  een risicolimiet (daglimiet, noodstop, pauze, tradelimiet,
  spreadvangnet), handel uit, levenscyclus, een onbevestigde order, de
  wisselkoers of "al één per cyclus", wordt gesimuleerd: instap op laat/bied
  van dat moment (incl. spread), dezelfde stop en doel, stop/doel getoetst
  op de bar-uitersten zoals de papersimulatie (beide geraakt = stop),
  tijdstop, maximale duur, trailing en break-even via dezelfde exitregels.
  Kosten: spread in de prijzen plus geschatte slippage per zijde en
  commissie. Niet: signaalfilters, markt dicht, verouderde koers,
  sluitingsbuffer en de spreidingsregel (een kopie). Ontdubbeling: per
  richting hooguit één per candle, met dezelfde 0,3 × ATR-spreiding. Een
  schaduwtrade die > 5 minuten niet bijgewerkt kon worden, vervalt en telt
  niet mee. Geen extra brokerverzoeken. Eigen tabel `schaduw_trades`; telt
  nergens mee in het echte resultaat, de bewijsfase of de live-poort.
* **Sensor** *Schaduwtrades* (aantal; attributen winst%, PF, netto, kosten,
  t-statistiek op clusters, per reden). Sensor *Open posities* toont nu
  ticket, doel, aantal long/short, de limiet en eventuele netting.
* **Broker-dashboard**: telling per richting, netting-chip en paneel
  "Schaduwtrades (gesimuleerd)". Na de update eenmaal de browser verversen.
* Nieuw: `tests/test_v190.py`.

## 1.8.2

* **Geen strategiewijziging.** Alleen de live koers op het dashboard.
* **Live koers via HTTP-streaming** in plaats van een websocket: IG sloot de
  websocket zonder antwoord ("verbinding verbroken door de server"), terwijl
  Lightstreamer over HTTP wel bereikbaar is. Nu `create_session.txt` als
  stroom, `control.txt` voor het abonnement en `bind_session.txt` na LOOP
  (TLCP-2.1.0). De websocket-route is verwijderd.
* **Betere diagnose**: bij een fout één WARNING met transport, HTTP-status en
  de eerste serverregel; elke serverregel op DEBUG. Wachtwoord en tokens
  komen nooit in het logboek.
* Nog steeds alleen met IG in demo- of live-modus, niet in paper; alleen
  weergave, geen extra IG-REST-verzoek, geen nieuwe afhankelijkheid.
* Het paneel zelf is niet gewijzigd: browser verversen is niet nodig (na de
  update naar 1.8.1 wel eenmaal gedaan hebben).
* Nieuw: `tests/test_v182.py` (lokale Lightstreamer-nepserver over HTTP).

## 1.8.1

* **Geen strategiewijziging.** Strategie, in- en uitstap, parameters,
  risico, positiegrootte en vingerafdruk zijn niet aangeraakt. De handel
  blijft op REST en op de bestaande cyclus.
* **Live koers op het broker-dashboard via IG-streaming** (Lightstreamer):
  bied/laat in de kopbalk, laatste koers en verandering, de lopende candle
  en prijslijn in de grafiek, en open P&L per positie en in de account-strip,
  gemarkeerd "live, indicatief" (het officiële bedrag blijft dat van de
  broker per cyclus). Statusbolletje LIVE (groen) of "elke 5 s" (grijs).
* **Live alleen met IG, in demo- of live-modus, niet in paper.** Anders, of
  bij een storing, blijft het dashboard elke 5 s verversen (één WARNING in
  het logboek, opnieuw proberen met oplopende wachttijd).
* Alleen-lezend en alleen zolang het dashboard open is (stopt 60 s na het
  laatste paneel). Eigen minimale TLCP-client over aiohttp: geen nieuwe
  afhankelijkheid, geen extra REST-verzoek (tokens uit de bestaande sessie).
  Nieuw websocket-commando `gold_scalper/broker_stream`, alleen beheerders.
* **Na de update eenmaal de browser verversen.**
* Nieuw: `tests/test_v181.py`.

## 1.8.0

* **Geen strategiewijziging.** Strategie, in- en uitstap, parameters,
  risico, positiegrootte en vingerafdruk zijn niet aangeraakt.
* **Broker-dashboard** in dezelfde stijl als StormchaseNL en EMS (donker
  petrol met goud, glaspanelen, kleine hoofdletterlabels, grote cijfers).
  Het menu-item **Gold Scalper** toont het nu op dezelfde zijbalk-ingang:
  kopbalk met bied/laat, DEMO-badge, markt, status en alarmen;
  account-strip; candlestickgrafiek (1m/5m/15m, crosshair, zoom) met lijnen
  voor instap, stop-loss en take-profit en markers van recente trades; open
  posities met tijdstop-aftelling; equity en drawdown; laatste 20 trades;
  onderzoek en statistiek. Op een telefoon één kolom.
* Alleen weergave: geen handelsknoppen. Het klassieke overzicht en het
  keuringsrapport blijven bereikbaar en zijn onderaan gelinkt.
* Nieuwe route `GET /api/gold_scalper/broker`: geauthenticeerd, alleen
  beheerders, alleen-lezend (eigen `mode=ro`-verbinding), begrensd en per
  cyclus gecachet (zie `DASHBOARD.md`).
* **Na de update eenmaal de browser verversen** (de module-URL heeft een
  nieuwe versieparameter).
* Nieuw: `tests/test_v180.py`.

## 1.7.10

* **Geen strategiewijziging.** Strategie, in- en uitstap, parameters,
  standaardwaarden, positiegrootte en vingerafdruk zijn niet aangeraakt.
  Bij onenigheid tussen broker en rooster wint nog steeds 'gesloten'.
* **Klokrand is geen roosterafwijking** (leerronde 9 oktober). Elke nacht
  stond twee keer "De broker meldt de markt gesloten terwijl het rooster hem
  open zegt ... vrijwel altijd een feestdag" in het logboek, om 22:59:59 en
  om 23:59:59:
  * 23:59:59,06: het rooster rekende de pauze tot en met 23:59:59, maar
    vergeleek met microseconden - daardoor was het rooster al 'open'. Het
    rooster rekent nu in hele seconden.
  * 22:59:59: onze klok liep een fractie achter op de sluiting van de
    broker. Binnen 15 s van een opening of sluiting volgens het rooster
    (`bij_roostergrens`) gaat zo'n verschil nu als DEBUG in het logboek in
    plaats van als WARNING. Een echte afwijking midden in de sessie blijft
    een waarschuwing.
* Nieuw: `tests/test_release_1710.py`.

## 1.7.9

* **Geen strategiewijziging.** Strategie, in- en uitstap, parameters,
  standaardwaarden, positiegrootte en vingerafdruk zijn niet aangeraakt.
* **Sluiting pas boeken na bevestiging door IG.** Een dealReference betekent
  alleen dat IG het verzoek ontving. Na elk sluitverzoek wordt nu
  `/confirms/{dealReference}` opgevraagd (direct, dan na 1, 3 en 10 s):
  * **ACCEPTED**: de trade wordt als gesloten geboekt (zoals voorheen).
  * **REJECTED**: niet geboekt; de positie blijft open en bewaakt, met een
    ERROR die de reden van IG noemt. De exitlogica mag hetzelfde besluit
    daarna opnieuw uitvoeren, met wachttijd (10, 30, 60, 120 s) en een
    limiet van 5 pogingen. Daarna probeert de bot het niet meer
    automatisch: de positie blijft open, bewaakt en met zijn stop bij de
    broker; ERROR met het advies hem zo nodig handmatig te sluiten.
  * **Geen bevestiging** (timeout, netwerk): niet geboekt, maar "onderweg".
    Zolang dat zo is gaat er geen tweede sluitverzoek uit. Verdwijnt de
    positie bij de broker, dan rekent de gewone afwikkeling van verdwenen
    posities hem af (gemeten uitstapprijs, of gemarkeerd als geschat). Staat hij er na 90 s nog, dan telt dat als
    een niet uitgevoerde sluiting (wachttijd en limiet zoals hierboven).
  * Ook een deelsluiting wordt alleen geboekt na bevestiging.
* **"Sluiting niet uitgevoerd" binnen 90 s.** Lopende sluitverzoeken worden
  nu elke cyclus nagekeken tegen de positielijst die de cyclus al ophaalt -
  geen extra verzoek bij IG, en de volledige controle draait niet vaker.
  Staat een als gesloten geboekte positie na 90 s nog bij de broker, dan
  volgt direct de noodstop (voorheen pas bij de volgende volledige
  controle, tot ruim drie minuten later).
* Zolang een sluiting loopt of geboekt is, stuurt de exitlogica geen tweede
  sluitverzoek op dezelfde positie (dat kon in het gat van 1.7.8).

## 1.7.8

* **Geen strategiewijziging.** Strategie, in- en uitstap, parameters,
  standaardwaarden, positiegrootte en vingerafdruk zijn niet aangeraakt.
* **Geen noodstop meer op een positie die we net zelf sloten.** Op 08-10 om
  21:20:07 sloot de tijdstop DIAAAAYMFVR7YAY. De trade werd direct als
  gesloten geboekt, en in dezelfde cyclus draaide de periodieke
  brokercontrole (`_audit_against_broker`, elke tiende cyclus). IG's
  posities-endpoint toonde de positie nog enkele seconden, dus zag de
  controle "staat open bij de broker maar niet in de database" en ging de
  noodstop aan - op een positie die al dicht was. Intermitterend: alleen als
  de controle toevallig in die seconden viel.
  Nu onthoudt de coordinator voor welke tickets wij een sluitverzoek
  verstuurden. Staat zo'n positie nog bij de broker, dan is dat binnen 90 s
  een melding (`sluiting_onderweg`, informatie) en geen noodstop; ook
  *Hervatten* binnen die termijn ziet hem niet als onbekend. Staat hij er na
  90 s nog, dan noodstop zoals voorheen, met de melding dat de sluiting niet
  is uitgevoerd (`sluiting_niet_uitgevoerd`). Een positie die wij **niet**
  sloten blijft direct een noodstop geven; die bescherming is ongewijzigd.
* **Geweigerde sluiting wordt niet meer als gesloten geboekt.** De uitkomst
  van het sluitverzoek werd genegeerd: ook zonder dealReference werd de
  trade afgeboekt, waarna de positie open stond bij de broker en dicht in de
  database. Nu blijft de trade open en bewaakt, met een ERROR in het logboek.
  (Een verzoek dat IG aanneemt maar later afwijst, valt onder de 90-s-regel
  hierboven: daarna noodstop met "niet uitgevoerd".)
* **App-icoon.** De integratie levert haar icoon zelf mee in
  `custom_components/gold_scalper/brand/` (`icon.png` 256×256,
  `icon@2x.png` 512×512, bron `icon.svg`), zoals HA sinds 2026.3 ondersteunt.
  Het verschijnt in Instellingen → Apparaten & diensten na een herstart van
  Home Assistant. Het HACS-updatescherm toont het mogelijk nog niet; dat is
  een HACS-bug (hacs/integration#5171).

## 1.7.7

* **Geen strategiewijziging.** Strategie, in- en uitstap, parameters,
  standaardwaarden, positiegrootte en vingerafdruk zijn niet aangeraakt.
  Handel en noodstop worden door niets hieronder aan- of uitgezet.
* **Bruto met teken in het oordeel.** De kostenzin toonde de absolute waarde
  van bruto: bij bruto −30,53 en kosten 165,45 stond er "kosten (165)
  overtreffen de bruto marktbeweging die is gevangen (31)". Nu met teken, en
  bij een negatief bruto inhoudelijk juist: "de gevangen marktbeweging was al
  negatief (bruto −31); de kosten (165) komen daar nog bovenop". Bij een
  positief bruto blijft de bestaande zin, met "bruto +…".
* **Saldosprong zonder trade = dataprobleem.** Op 08-10 veranderde het
  IG-demosaldo zonder trade (saldo-aanpassing door de broker). Zo'n waarde
  mag geen dagstart, run-opening of vermogensvloer bepalen. Nieuw
  (`broker/saldosprong.py`): elke cyclus wordt de gemeten equity vergeleken
  met de laatst betrouwbare referentie. Wijkt hij meer dan 10% (relatief) af
  terwijl er in de afgelopen 5 minuten geen trade sloot (ook deelsluiting) en
  geen positie of onbevestigde order open stond, dan:
  * staat de binaire sensor *Dataprobleem* aan, met attributen `saldosprong`,
    `saldosprong_reden` en `saldo_referentie`;
  * rolt een nieuwe handelsdag naar de vorige referentie als dagstart, krijgt
    een nieuwe run die referentie als opening (en dus als basis voor de vloer),
    en gebruiken *Dag opnieuw* en *Hervatten* die referentie als dagijkpunt;
  * komt er één WARNING per gebeurtenis, niet per cyclus.
  Eerste meting zonder bewaarde referentie (eerste start na installatie) is
  nooit een sprong; die wordt de referentie. Een mislukte saldo-opvraging telt
  niet als meting.
  Herstel zonder knop: keert de equity terug tot binnen 10% van de referentie,
  dan is het dataprobleem weg (INFO); blijft de nieuwe waarde 24 uur binnen
  10% van zichzelf, dan wordt hij de nieuwe referentie (INFO). Springt hij
  intussen opnieuw, dan is dat een nieuwe gebeurtenis (nieuwe WARNING, de
  24 uur beginnen opnieuw). Referentie en actieve sprong worden bewaard en
  overleven een herstart; ook te zien in de diagnostiek.
  Wat de bestaande logica doet: de sensor *Dataprobleem* is een melding, geen
  handelspoort; er wordt niet gepauzeerd en geen noodstop gezet door de
  sprong zelf. De bestaande limieten (daglimiet, vloer) blijven rekenen met de
  werkelijke equity van dit moment tegen de vastgehouden referentie; valt die
  equity onder de vloer, dan grijpt de bestaande vloertoets in zoals altijd.
  Let op: de drempel is 10%; een kleine aanpassing (zoals de paar tientjes op
  een saldo van tien miljoen) blijft daaronder en geldt als gewone meting.
* **Testrobuustheid (L-GS-002).** Vier coordinatortests in
  `tests/test_unconfirmed_orders.py` liepen op de echte klok en faalden
  tijdens de dagelijkse marktpauze en in het weekend. De klok van de
  integratie staat in die tests nu vast op een handelsmoment (woensdag
  12:00 Nederlandse tijd) en loopt vanaf daar door.
* Nieuwe tests: `tests/test_v177.py`.

## 1.7.6

* **Alleen statistiek en rapportage.** Strategie, in- en uitstap,
  risicolimieten en risicoberekeningen (dagstartsaldo, equityondergrens),
  parameters, standaardwaarden, positiegrootte en vingerafdruk zijn niet
  aangeraakt. Geen nieuwe run, en er gaat nooit een order uit door iets
  hieronder.
* **Uitstapregime per trade.** Sinds 1.7.4 vuren tijdstop en maximale duur
  ook op IG; binnen dezelfde run zijn er dus twee uitstapgedragingen. Elke
  trade krijgt nu bij het openen een `exit_regime` (`tijdstop`), in een nieuwe
  kolom die bij het opstarten wordt toegevoegd. Bestaande trades worden
  eenmalig aangevuld: een brokertrade die opende vóór de installatie van
  1.7.4/1.7.5 (herstart 8 oktober 2026, 12:16 lokale tijd = 10:16 UTC) krijgt
  `zonder_tijdstop`, alle andere `tijdstop` - ook papertrades, want die hadden
  altijd een openingstijd. Een al ingevuld regime wordt nooit overschreven;
  zonder leesbare openingstijd blijft het leeg. Let op: een trade die vóór de
  grens opende en erna sloot, telt als `zonder_tijdstop`.
* **Cijfers per regime op het oordeel.** De sensor *Oordeel* heeft een nieuw
  attribuut `per_exitregime`: per regime het aantal trades en clusters, netto
  totaal en per trade, de t-statistiek over clusters (clusters binnen het
  regime gevormd) en de profit factor. Het oordeel zelf wordt nog steeds over
  de hele run bepaald en kijkt niet naar het regime.
* **Latency-p99 over een herstart heen.** De steekproef begon na elke
  herstart opnieuw, zodat één uitschieter de p99 bepaalde (587 ms bij
  n=326). De laatste 2000 metingen per schakel worden nu bewaard in de opslag
  van de uitkomsten (elke 15 minuten en bij afsluiten) en bij opstarten
  teruggezet, één keer, vóór wat er al gemeten is. De sensor *Latency p99*
  heeft de attributen `n` en `p99_indicatief`; onder de 1000 metingen zegt
  `basis` "p99 indicatief". Wat er gemeten wordt en hoe de percentielen
  berekend worden, is ongewijzigd.

## 1.7.5

* **Een herstart verandert niets meer.** Alleen herstartbestendigheid:
  strategie, in- en uitstap, risicolimieten, parameters, standaardwaarden en
  positiegrootte zijn niet aangeraakt, en er gaat nooit een order uit door
  iets hieronder. Geen nieuwe run. Wat een herstart tot nu toe veranderde, en
  nu niet meer:
  * **papersaldo** stond weer op de startbalans (en de kostenteller op nul);
    nu startbalans plus het netto van de gesloten trades van de run;
  * **uitersten (MFE/MAE)** van open posities begonnen opnieuw bij nul; nu
    bewaard per ticket (ook voor open papertrades), en tickets die niet meer
    open staan worden opgeruimd;
  * **live-poort**: bij het opstarten en in de cyclus werd de poort berekend
    vóór de robuustheid. Na een herstart bleef de poort daardoor dicht tot er
    een trade bij kwam - in live-modus dus voorgoed. Nu eerst leren, dan de
    poort (de bedoelde volgorde; geen drempel gewijzigd). Ook de gemeten
    slippage geldt zo al vanaf de eerste cyclus;
  * **pauze na een verliesreeks** (`paused_until`) werd opgeheven; nu bewaard
    en teruggezet, net als de recente risicogebeurtenissen;
  * **accountvaluta**: faalde de opvraging bij het opstarten, dan gold "USD"
    en kon de vingerafdruk van de run daarop herschreven worden (of een nieuwe
    bewijsfase beginnen). Nu geldt de laatst door de broker bevestigde valuta,
    en een terugvalwaarde past nooit een vingerafdruk aan;
  * **afsluiten**: wacht (hooguit 15 s) op een lopende cyclus, bewaart de
    toestand, schrijft de signalen weg en sluit database én archief, buiten de
    eventloop. Tweede aanroep (stop-event én ontladen) doet niets; na het
    afsluiten draait geen cyclus meer;
  * **laatste instap** stond op "nooit"; nu uit de laatste trade van de run;
  * **onbevestigde orders** stonden alleen in het geheugen. Nu minimaal
    bewaard (eigen ordernummer, richting, tijdstip, stop en de gegevens om een
    teruggevonden positie vast te leggen) en bij het opstarten eerst
    teruggezocht, vóór de afstemming. Een order die tijdens de herstart is
    uitgevoerd, wordt zo herkend in plaats van als onbekende positie de handel
    stil te leggen; tot hij is teruggevonden, afgewezen of verlopen gaat er
    geen nieuwe order uit. Er wordt hierbij nooit iets verstuurd;
  * **meldingen**: een teruggezette noodstop gaf geen tweede melding meer
    (vorige risicostand uit de toestand), de onderdrukking van vier uur en het
    vertrekpunt van het uurbericht worden bewaard (bij een oudere toestand uit
    de run zelf), zodat het eerste uurbericht niet alle trades als "dit uur"
    telt;
  * **lopende zelfgebouwde bar** ging verloren, en de eerste bar na de herstart
    begon halverwege zijn interval maar ging als volwaardige bar het archief
    in. Nu wordt de lopende bar bewaard en in hetzelfde interval gewoon
    voortgezet; anders worden de afgebroken bar en de eerste bar na de herstart
    als onvolledig gemarkeerd: ze blijven in de reeks, maar niet in het
    archief;
  * **sluitingswaarneming, backtest, validatie en indicatorlab** gingen
    verloren; nu in een eigen opslag (`gold_scalper_results`);
  * **drawdown op de equity** viel weg in elke cyclus waarin het aantal trades
    veranderde - en dus in de eerste cyclus na elke herstart; nu meegenomen;
  * **herkansingen** van voorlopige uitstapprijzen en al **gemelde
    controlebevindingen** worden bewaard; de **evaluaties** worden vóór het
    sluiten weggeschreven, zodat de teller nooit terugloopt.
  Daarnaast: risicogestuurde grootte in papermodus riep de equity van de
  simulatie niet aan (de methode zelf ging de berekening in en faalde); en een
  dubbel stuk in de initialisatie van de coordinator is weggehaald. Oude
  bewaarde toestand zonder de nieuwe velden laadt gewoon.

## 1.7.4

* **Tijdstops werken weer op IG (L-GS-005).** De posities van IG kwamen
  binnen zonder openingstijd; de leeftijd van een positie was daardoor altijd
  nul en de ontworpen tijdstop (240 s binnen 0,3×ATR) en de maximale duur
  (900 s) vuurden nooit. Gemeten: gemiddelde duur 1408 s, langste 5272 s.
  Nu wordt `createdDateUTC` van de broker gelezen; ontbreekt die, dan geldt
  de openingstijd van de eigen trade op hetzelfde ticket (per ticket
  onthouden, niet elke cyclus opnieuw opgevraagd). **Geen parameterwijziging**:
  doel, stop, break-even, tijdstop en maximale duur hebben dezelfde waarden;
  ze gaan nu alleen werken zoals ontworpen. Geen nieuwe run. Let op: een
  positie die bij het installeren al langer dan 900 s open staat, wordt in de
  eerste cyclus gesloten.

## 1.7.3

* **Uitstapprijs navragen voordat een schatting blijft staan.** Op 8 oktober
  werden vier trades afgerekend op een geschatte uitstapprijs (03:35, 04:55,
  06:22, 09:21), drie terwijl HA gewoon draaide. Oorzaak: de broker had de
  posities zelf gesloten op stop of doel, en de enige bron die werd gevraagd
  was het transactieoverzicht - dat loopt uren achter (in het log: "Slechts 1
  transactie(s)"). Stond de koers bij het ontdekken al terug van het niveau,
  dan bleef alleen de ontdekkingskoers over. Nu, alleen boekhouding:
  * valt het transactieoverzicht leeg, dan wordt het activiteitenoverzicht
    gevraagd (`/history/activity` v3, `detailed`; `closed_deal_activity`),
    dat een sluiting binnen seconden kent. Koppeling streng op een actie
    `POSITION_CLOSED` met het dealId van de positie (`match_activity`); de
    openingsactiviteit telt nooit. Noemt de activiteit geen niveau, dan de
    `dealReference` bij `/confirms` navragen;
  * lukt dat bij het ontdekken niet, dan wordt de trade zoals voorheen
    voorlopig geboekt (`broker_gesloten_geschat`, `pending`) en daarna nog
    hooguit vier keer nagevraagd, 20/60/120/240 s na het afrekenen
    (`HERKANSING_SCHEMA`), één verzoek per poging. Daarna neemt de bestaande
    correctie uit het transactieoverzicht het over;
  * een correctie (herkansing of transactieoverzicht) zet nu in één keer
    uitstapprijs, sluitreden én gemeten kosten (`meet_kosten`), en rekent
    zonder brokerbedrag het eurobedrag opnieuw om. Voorheen ging de
    kostenbron eerst terug naar "berekend" en werd pas een afstemmingsronde
    later gemeten;
  * de afstemming behandelt een voorlopige trade als schatting: de prijs van
    de broker wordt overgenomen (ook bij een zwakke koppeling, zoals de
    correctie al deed) zonder vals alarm, met sluitreden en gemeten kosten
    (`voorlopig_bijgewerkt` in de uitslag).
  `raw_responses` toont ook `activity_v3`, zodat de veldnamen tegen het echte
  antwoord te controleren zijn. Strategie, risico, positiegrootte en
  entry/exit zijn niet aangeraakt.

## 1.7.2

* **Geen vals alarm meer over het transactieoverzicht.** `closed_deal`
  waarschuwde bij minder dan drie transacties met "Slechts N transactie(s)
  over de afgelopen vierentwintig uur … het datumbereik komt vermoedelijk
  niet aan", bij elke correctiepoging opnieuw. Op 8 oktober tussen 03:15 en
  04:03 kwam dat 22×, terwijl er niets mis was: het venster is sluiten −6 u ..
  +12 u (geen 24 u), na de avondpauze bijna leeg, en het overzicht van IG
  loopt achter. Nu vergelijkt de broker het aantal transacties met het aantal
  eigen gesloten trades in hetzelfde venster (de correctielus geeft de
  sluitmomenten mee, `own_close_times`). Alleen trades die al meer dan zes
  uur dicht zijn (`TRANSACTIE_VERTRAGING`) tellen; ontbreken die, dan één
  WARNING per uur met het echte venster in UTC, verder DEBUG. Ook de melding
  "overzicht leeg" valt hieronder. Alleen logging; raakt geen handelslogica.

## 1.7.1

* **Doel- en stoptreffers in *Geleerd* op de effectieve sluitreden.** De
  uitvoeringsmeting (`measure_execution`) telde uit `close_reason`; na een
  afstemming staat daar alleen nog `broker_gesloten_gecorrigeerd`. Op 7
  oktober gold dat voor 24 van de 56 trades, waardoor *Geleerd* doel 14% en
  stop 43% meldde (met de notitie "ATR mogelijk overschat"), terwijl *Doel
  geraakt* en *Stop geraakt* op bewijs 19,6% en 80,4% gaven. Nu dezelfde bron
  als die sensoren (`exit_stats.effective_reason`): afgeleide reden, anders de
  oorspronkelijke; een niet-afgestemde brokersluiting telt als onbekend.
  Raakt geen handelslogica.
* Opgemerkt, niet gewijzigd: vier tests in `test_unconfirmed_orders.py`
  hangen van de klok af en falen tijdens de dagpauze van de markt (rond
  21-22 UTC). Met een vaste tijd overdag slaagt de hele suite.

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
