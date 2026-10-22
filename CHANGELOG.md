# Changelog — Gold Scalper

## 2.19.3 - 22-10-2026

### export_data: de Bitvavo-mand geeft de trades van alle markten
- Gemeten 22-10 05:55: de mand had 311 gesloten trades (PUMP-EUR 184, PEPE-EUR 90, BILL-EUR 37; samen −3.992 EUR op papier), maar `export_data` gaf *total 0*: alleen de database van de hoofdlus (BTC-EUR) werd gelezen, terwijl elk lid een eigen database heeft. Zo was de mand niet te onderzoeken.
- Nu leest de dienst bij een mand alle leden, op sluitmoment gesorteerd, met de markt als laatste kolom (`markt`, ook bij IG en Pepperstone). Nieuw veld `markt` om op één markt te filteren. Bij één markt blijft de volgorde zoals hij was.
- Alleen lezen; raakt geen strategie, risico of orders; geen nieuwe run.
- Test: `test_v2193_export_mand.py` (4).

## 2.19.2 - 21-10-2026

### Database: geen transactiefout meer bij gelijktijdige aanroepen
- Gemeten 21-10 20:59: de afstemming na de herstart faalde met *cannot commit - no transaction is active*; de IG-afwijkingen bleven daardoor staan tot de volgende ronde.
- Oorzaak: alle databaseaanroepen delen één SQLite-verbinding en lopen via de executor in verschillende threads. Rondde de ene thread zijn commit af terwijl de andere net wilde committen, dan vond die geen transactie meer (in de test ook *bad parameter or other API misuse*).
- Nu: elke methode van de tradedatabase houdt één herintreedbare slot vast, en de gebufferde signaalwegschrijver gebruikt dezelfde slot. Raakt geen strategie, risico of orders; geen nieuwe run.
- Test: `test_v2192_db_gelijktijdig.py` (3; faalde vóór de fix).

## 2.19.1 - 21-10-2026

### Leeg accountantwoord is geen meting (geen valse noodstop, geen 100 % drawdown)
- Gemeten 21-10 13:14:07: IG gaf één keer saldo 0 en equity 0 (ervoor en erna ~10,03 mln). De vloertoets zag 0 onder de vloer van 9,53 mln: NOODSTOP om 13:15 (hervat 13:42 met de knop). Daarna bleef *Max. drawdown* van de IG-run op 100 % staan en noemde het oordeel "drawdown te groot".
- Nu: (1) IG zonder saldo in het accountantwoord = fout (geen 0 invullen); (2) saldo én equity precies 0 terwijl er eerder een positieve equity gemeten was = leeg antwoord: zelfde pad als een mislukte opvraging (2.4.4: geen risicotoets, geen instap, geen equitypunt; exitbeheer loopt door); (3) de drawdown slaat zulke 0/0-punten over bij een run met een gemeten positieve opening - dat herstelt de 100 % van de lopende IG-run na de herstart.
- Raakt geen strategie, risicogrenzen of ordergrootte; geen nieuwe run.
- Test: `test_v2191_leeg_account.py` (6).

## 2.19.0 - 21-10-2026

### Daghandel draait weer (op kwartierbars)
- Gevraagd 21-10 06:13: "Gold scalper helemaal controleren en waar mogelijk de strategie verbeteren".
- Gevonden: de daghandel - de enige opzet met een backtest over 2011-2018 (kosten ~20 % van de beweging) - heeft sinds de overstap naar 1m nooit gehandeld. Hij kreeg de bars van het tijdvak van de entry (1m, hooguit 800 = 13 uur) en wachtte op "50 afgesloten uren voor de uur-EMA's"; zijn kanaal van 80 bars was 80 minuten in plaats van 20 uur, en zijn volgstop rekende in ATR(1m) in plaats van ATR(15m). Bij XAUUSD 1 trade in een week, bij IG 1, in de Bitvavo-mand 0.
- Nu krijgt de daghandel de kwartierbars die de veldproef al bijhoudt (400 = 100 uur, bij het opstarten uit het archief of de broker), en zijn exits ATR(15m). Geen kwartierbars: geen daghandel (niet op 1m). Regels en strategieversie ongewijzigd: geen nieuwe run.

### Overig
- Sensor Evaluaties: alleen de 30 meest voorkomende weigeringsredenen (plus het aantal soorten). Redenen met getallen erin maakten de attributen groter dan 16 KB; de recorder waarschuwde 3.269 keer in één nacht.
- Dienst `export_data`: kies de Gold Scalper met `entry_id` (zonder keuze kwam de eerste terug: de Bitvavo-mand, 0 trades) en de trades hebben nu ook strategie, modus, id en ticket - voor onderzoek naar uitstappen (MFE/MAE per opzet).
- Tests: `test_v2190_daghandel_kwartier.py` (7); `test_v200_daghandel.py` en `test_v210_combinatie.py` aangepast aan de invoer per strategie.

## 2.18.5 - 20-10-2026

### Afwijkingen bij de broker één keer melden
- Gemeld 20-10 17:42: "Ik blijf van goldscalper maar de afwijkende melding krijgen". Dezelfde oude afwijkingen (o.a. een IG-trade van bijna zes dagen geleden die niet in het brokeroverzicht staat, uitstapprijzen een paar tienden anders) stonden in elke afstemming en kwamen per broker elke vier uur opnieuw binnen.
- Nu krijg je per afwijking één melding; bekende afwijkingen blijven zichtbaar in het dashboard (meetkwaliteit), maar sturen geen bericht meer. Wat al gemeld was, telt bij de overgang als gemeld. Het onthouden overleeft een herstart en vervalt na drie weken.
- Test: `test_v2185_afstemmingsmelding.py` (4).

## 2.18.4 - 20-10-2026

### Mand: posities op risico, niet op de kleinste order
- Gemeld 20-10 13:21 (screenshot): "Nog steeds mini posities?" Een positie op PUMP-EUR van 1.271 units, ruim 5 euro, ondanks een inzet tot 2.000 euro.
- Oorzaak: bij *alles* krijgen veldproefopzetten de vaste scalpgrootte (1 oz, verkleind tot 100 USD risico). Bij crypto werd 1 "oz" de kleinste order van de exchange. Nu krijgt spot (Bitvavo) de gewone grootte op risico (risico per trade van het saldo, standaard 0,5 %), begrensd door de inzet per koop; schaduwtrades rekenen net zo. Goud verandert niet.
- In het paneel stonden instap, koers, stop en doel bij goedkope munten als 0,00: alle koersen hebben nu decimalen naar grootte (goud blijft op twee). Punten idem.
- Een papieren positie stond als *Daghandel*: op papier is het ticket het trade-ID en dat werd niet gekoppeld aan de database. Nu wel, dus de echte opzet (bijvoorbeeld vp:momentum:15m).
- Tests: `test_v2184_grootte.py` (3).

## 2.18.3 - 20-10-2026

### Mand: geen instap tijdens het opstarten
- Live gezien 20-10 11:30, na de herstart van 11:26: 8 posities open bij een maximum van 5 (PEPE-EUR 3, PUMP-EUR 3, PHA-EUR 1, EPIC-EUR 1). De markten starten met vier tegelijk; wie al draaide stapte in terwijl andere markten hun open posities nog terugzetten, en die telden pas mee als ze klaar waren.
- Nu opent de mand niets nieuws tot alle markten (met hun posities) draaien. Bestaande posities blijven gewoon lopen en sluiten op hun eigen stop, doel of tijd.
- Test: 1 in `test_v2180_mand.py`.

## 2.18.2 - 20-10-2026

### Mand: een mislukte instap houdt geen plek meer bezet
- Live gezien 20-10 11:02: de mand telde 5 van 5 posities terwijl er maar 2 open stonden (PUMP-EUR). Drie markten kregen elke cyclus een plek toegezegd, openden niets (kostenfilter, grootte) en hielden de plek 30 s vast - en de volgende cyclus opnieuw. Zo bleven andere markten buiten.
- Nu geeft de lus de plek meteen terug als hij niets opent (`BitvavoMand.vrijgeven`), op beide instappaden.
- De reden van het kostenfilter toont de afstanden in 4 significante cijfers (bij munten van een paar cent stond er "stop 0.00, minimaal 0.02").
- Tests: 2 in `test_v2180_mand.py`.

### Mand: markt kiezen voor de grafiek, en live koersen
- Gemeld 20-10: "Waar kan ik nu bijvoorbeeld een andere crypto munt voor de grafiek selecteren? ... heb nergens een dropdown keuze menu" en "En data is niet live, refreshed elke 5 seconden, graag live".
- In het mandvak een keuzelijst *Grafiek* (markten met een open positie hebben een ●); een klik op een marktkaart doet hetzelfde. De grafiek, de positie, de markt en de trades eronder zijn dan van die markt; de mand blijft bovenaan staan en de knop *Bitvavo-mand* blijft gekozen. Valt een gekozen markt later uit de mand, dan toont het paneel de mand zelf.
- Live: een verbinding met de publieke websocket van Bitvavo (`ticker`), ook op papier, zonder sleutel en zonder REST-verzoek. De gekozen markt voedt de grafiek en de koers (tot 4 keer per seconde), alle markten van de mand voeden de tabel met open posities, de kaarten en de tegel *Open P&L* (tot 2 keer per seconde). Alleen weergave: de handel blijft op de cyclus. Valt de verbinding weg, dan opnieuw verbinden met oplopende wachttijd en tot dan de 5-s-verversing.
- Tests: `test_v2183_mandlive.py` (5).

## 2.18.1 - 20-10-2026

### De mand in één dashboard
- Gemeld 20-10: "Ik wil 1 dashboard, niet legio aan tabladen, ik wil in 1 oogopslag alle openstaande orders voor alle markten zien." In 2.18.0 stond elke markt van de mand als eigen knop in de brokerkeuze.
- Nu één knop *Bitvavo-mand*. Bovenaan het paneel het vak *Bitvavo-mand · alle open posities*: één tabel met markt, richting, units, instap, koers, stop, doel, resultaat (bedrag en %), resultaat bij de stop en duur; daaronder per markt een kaart met koers, open resultaat, netto, aantal trades, spread, status en waarom hij niet instapt. Markten die uit de mand vallen zijn gestippeld.
- De tegel *Open P&L* telt bij de mand alle markten.
- Koersen en hoeveelheden met decimalen naar grootte (0,0027 BTC en 0,00001162 EUR bleven anders 0,00). Bij goud verandert er niets.
- Tests: `test_v2181_mandpaneel.py` (4), waaronder een weergavetest op desktop en mobiel.

## 2.18.0 - 20-10-2026

### Bitvavo-mand: handelen op de meest liquide markten
- Gevraagd 20-10: "Ik wil dat de integratie op alle markten analyseert en zelf handelt, niet op alleen BTC". Gekozen: de meest liquide markten, met hooguit een aantal open posities en een inzet per koop.
- Nieuw bij een Bitvavo-entry: *Markten* (`mand`, standaard, of `een` zoals in 2.17.0), het aantal markten (20), het maximum aantal open posities over de hele mand (5) en de minimale 24-uurshandel (250.000 EUR).
- Samenstelling (`broker/bitvavo.py`: `kies_markten`, `mand_toppers`): twee publieke verzoeken (`/markets`, `/ticker/24h`), alleen EUR-markten die handelen en een stoporder kennen, geen stablecoins, spread hooguit 0,2 %, gesorteerd op volume; de gekozen markt altijd erbij. Elk uur opnieuw.
- `mand.py`: elke markt draait als eigen handelslus (zelfde code als bij één markt, eigen database, run en grootboek). De gekozen markt heeft de entiteiten; de andere draaien zonder. Gedeeld: het maximum aantal posities (ook op papier, met een toegezegde plek tegen twee gelijktijdige instappen), de schakelaar, en de poort naar live op alle papieren trades van de mand samen. Een markt die uit de mand valt met een positie blijft draaien tot die dicht is en opent niets nieuws; markten met een positie komen na een herstart terug.
- Sensor *Mand*: aantal markten, open posities, per markt koers, resultaat, volume, spread en de laatste weigering. In de brokerkeuze van het dashboard staat elke markt als *Bitvavo <markt>*.
- Opgelost, ook voor IG en Pepperstone: de toestand (`gold_scalper_state`) en de uitkomsten (`gold_scalper_results`) waren per entry een eigen kopie van het hele bestand, gelezen bij het opstarten; elke entry schreef bij elke wijziging zijn kopie terug en zette daarmee de nieuwere toestand van de andere terug naar die van het opstarten (bijvoorbeeld een noodstop). Nu delen alle entries één inhoud.
- Het barsarchief wacht ruimer op een slot (30 s): met de mand schrijven tientallen markten erin.
- Veiligheid van de mand (uit de review): een noodstop bij één markt houdt de hele mand tegen; een koop zonder antwoord bezet een plek; het vermogen live is dat van de hele mand (geld plus alles wat de bot op alle markten kocht), zodat de daglimiet niet schrikt van een koop op een andere markt; een nieuwe markt telt mee en volgt de schakelaar al vóór zijn eerste cyclus; een markt wordt alleen gestopt als hij plat is, gecontroleerd binnen zijn eigen cyclusslot; markten met een positie worden nooit uit het bewaarde bestand vergeten; één herziening tegelijk; stoppen is veilig bij een herstart halverwege. De knoppen *Alles sluiten*, *Afwikkelen* en *Hervatten* gelden voor de hele mand; rapport, dashboard, backtest en import lopen één keer per entry, niet per markt. Geen uurbericht per markt. De poort blijft dicht als de afstemming bij één markt niet sluit. Saldi worden 5 s gedeeld tussen de markten (vóór een order altijd vers).
- Een entry verwijderen wiste de toestand van alle andere entries (een nieuw, leeg object schreef het hele bestand terug); nu worden alleen die entry en zijn mandleden verwijderd, en een onleesbaar uitkomstenbestand wordt niet overschreven.
- Tests: `test_v2180_mand.py` (19).

## 2.17.0 - 20-10-2026

### Bitvavo: handelen in crypto
- Gevraagd 20-10: "Kunnen we bitvavo ook integreren? Om ook in crypto te handelen?" en "Direct compleet maken, zodat met alles gehandeld kan worden en dat ik eventueel zou kunnen overstappen naar echt geld, ik heb al een API".
- Nieuwe databron `bitvavo` (`broker/bitvavo.py`, REST API v2, HMAC-SHA256 zoals de officiele SDK): elke markt van Bitvavo te kiezen (keuzelijst uit `/markets`), per markt een eigen entry en database (`gold_scalper_bitvavo_<markt>.db`).
- Twee standen. `paper`: live koersen en orderboek, uitvoering gesimuleerd met het tarief per zijde (0,25 %, daarna het werkelijke tarief uit `/account/fees`), geen hefboom, geen swap; geen sleutel nodig. `live`: echte orders, alleen als de laatste papieren run van die markt de bewijsfase (LiveGate) haalde; zolang niet gaat er niets uit (geen fout, een weigeringsreden). Bitvavo heeft geen demo; `demo` geldt daar als papier.
- Spot: alleen kopen. Een short-signaal opent niets (ook op papier niet, anders meet de bewijsfase iets wat live niet kan); het blijft de omkeer-exit van een lopende long voeden. De venue weigert `sell` als opening sowieso.
- Bitvavo kent geen posities: de bot houdt een grootboek bij (elke koop een regel, order-ID als ticket), bewaard in `.storage` en teruggezet na een herstart. Na elke koop een `stopLoss`-order bij Bitvavo (beste bieding); een afgegane stop sluit de regel. Sluiten: eerst de stop annuleren, dan precies de gekochte hoeveelheid verkopen, nooit meer dan vrij is - eigen munten blijven onaangeroerd. Onbevestigde kopen worden op hun clientOrderId teruggevonden. `operatorId` bij elke handelsopdracht.
- Grenzen: hooguit de ingestelde inzet per koop (standaard 250 EUR), nooit meer dan het vrije geld, en de kleinste order en stap van de markt.
- Schaal (`strategy/schaal.py`): de vaste afstanden in USD/oz uit de goudstrategieen (minimale stop, break-even, winstslot, deelwinst, spreadgrenzen, slippage) schalen met de koers mee (factor koers / 4000), koersen worden op significante cijfers afgerond in plaats van op 2-3 decimalen, eenheden volgen de stap van de exchange en procentuele kosten tellen mee in de kostenpoort, het veldproef-kostenfilter, de schaduwtrades en de papiersimulatie. Voor goud verandert er niets: zonder Bitvavo geldt de neutrale schaal en geven alle functies exact wat ze gaven.
- Startinstellingen voor een Bitvavo-entry: grootte op risico (0,5 %), scalp uit (0,5 % kosten per rondreis), veldproef zonder 1m/3m/5m, spreadgrens 0,2 % van de koers. 3m-bars worden uit 1m opgebouwd.
- Bedragen in de sensoren in de valuta van de markt (EUR).
- Veiligheid bij echt geld: sluiten verkoopt pas als vaststaat dat de stop bij Bitvavo weg is (anders twee keer verkopen); een mislukte verkoop zet de stop terug; een stop verplaatsen controleert eerst of de oude al afging. Geen antwoord of time-out: de order wordt op een vaste clientOrderId teruggezocht en nooit blind herhaald, ook na een herstart. Een duidelijk nee (saldo, minimum) is een gewone weigering. Kosten in de munt zelf gaan van de positie af. Het vermogen telt alleen het geld van de markt en wat de bot kocht, niet je eigen munten. Live alleen in de stand `live`, en het bewijs moet een papieren run zijn met dezelfde strategie en markt.
- De schaal geldt per entry en per aanroep (verversing en diensten) en wordt daarna teruggezet, zodat goud nooit de schaal van een crypto-entry erft. De commissie van een boeking komt rechtstreeks uit de eigen venue.
- Tests: `test_v2170_bitvavo.py` (39), waaronder een volledige handelslus op papier met een spot-venue. Volledige suite: 1837 geslaagd, 5 overgeslagen.

## 2.16.0 - 19-10-2026

### Experiment Lab verwijderd
- Gevraagd 19-10 ("Wat doet het gold scalper lab nu nog?" en daarna "Graag"): het Lab werd niet meer gebruikt; het onderzoek gaat inmiddels via de veldproef, de schaduwtrades en `indicator_lab` op het barsarchief.
- Weg: het Lab-paneel in de zijbalk, de diensten `lab_snapshot`, `lab_create_walk_forward`, `lab_register`, `lab_start`, `lab_cancel`, `lab_assess` en `lab_compare`, de modules `experiment_lab/`, `lab_panel`, `lab_actions`, `lab_bridge`, `lab_read_models`, `frontend/lab-panel.js`, `tools/lab_executor_benchmark.py` en de Lab-documentatie.
- Blijft: `gold_scalper_lab.db` in de configuratiemap wordt niet aangeraakt (niets weggegooid). `indicator_lab` is iets anders en blijft.
- De handel verandert niet: het Lab kon nooit orders plaatsen en werd pas na de handel geladen.
- Tests: de Lab-tests zijn mee verwijderd; uit `test_release_110.py` blijven de vingerafdruktests.

## 2.15.0 - 19-10-2026

### Marktomstandigheden bij elke veldproefinstap vastgelegd
- Gevraagd 19-10: "Kunnen we goldscalper nog verbeteren? Ik draai nog steeds verlies." Analyse van alle trades (IG 3.278, Pepperstone 1.131): bruto samen ongeveer nul (IG +275, Pepperstone -2.097); het verlies zijn de kosten (IG 67.210, waarvan 59.976 op 13-10 alleen). Sinds 16-10 staat Pepperstone bijna quitte (bruto +1.198 tegen kosten 1.712).
- De voor de hand liggende volgende toets - werkt een opzet beter met de grote trend mee, bij een sterke trend (ADX), of na een uitschieter (RSI)? - kon niet: bij veldproeftrades bleven `entry_trend`, `entry_adx`, `entry_rsi`, `entry_ema_dist` en `entry_momentum` leeg. Alleen scalp vulde ze.
- Nu: `kenmerken()` berekent per bar een context (EMA50-richting over 10 bars, afstand tot de EMA50 en 12-barsverandering in ATR, RSI(14), ADX(14)); `instap_context()` zet die in het signaal, met als `trend` de richting op 30m (de hogere trend). Wordt bij de order vastgelegd in de bestaande kolommen.
- Beslist niets: zelfde signalen, stops, doelen en strategieversie (`veldproef-2.1.0`); de run loopt door. Een fout geeft een lege context.
- Tests: `test_v2150_instapcontext.py` (4).

## 2.14.3 - 19-10-2026

### Geen valse netting meer op een hedged account (Pepperstone)
- 19-10 01:30 meldde de integratie netting en zette hedgen uit tot de herstart. Nagekeken bij cTrader: het account is HEDGED (`accountType` 0). In de dealhistorie sloot long 58459739 om 01:30:06.324 op zijn eigen stop (order 74631086, de stoporder van de opening); 4 ms later opende de nieuwe short 58460015 volledig (8 oz). De positievergelijking zag de long verdwijnen.
- Nu: de cTrader-venue leest het accounttype bij het verbinden (`account_hedged`). Bij een hedged account wordt de positievergelijking overgeslagen; een verrekening die de broker zelf in de bevestiging meldt, telt nog steeds.
- Tests: `test_v2143_hedged_geen_netting.py` (3).

## 2.14.2 - 19-10-2026

### Dashboard: live koers herstelt zich zelf
- Gemeld 19-10: het Pepperstone-dashboard bleef op "elke 5 s" staan. De server stroomde de koers wel live (via de websocket gecontroleerd: beide brokers `live`, ticks binnen), dus het abonnement van het paneel was vastgelopen, bijvoorbeeld na een herstart of herverbinding.
- Nu: een waakhond in het paneel abonneert opnieuw als LIVE 60 s wegblijft of er 60 s geen tick meer komt; na "niet beschikbaar" (papier) wordt het na 5 minuten opnieuw geprobeerd.
- Tests: `test_v2142_live_waakhond.py` (2).

## 2.14.1 - 17-10-2026

### Afstemming Pepperstone: 10 "ontbrekende" trades van 14-10
- Gevonden bij de HA-controle 17-10: de afstemming meldde steeds 10 afwijkingen ("staat na 2,1 dagen niet in het overzicht van de broker") voor trades van 14-10 18:57-19:12.
- Oorzaak: deelsluitingen van vóór 2.11.1 staan in de administratie als onafgeronde helft (24,5 oz) terwijl de broker op hele ounces sloot (24 en 25). Het verschil van 0,5 oz viel buiten de omvangtolerantie (0,25 oz). Live bevestigd in de dealhistorie van cTrader.
- Nu: bij exact dezelfde instapprijs en hetzelfde openingsmoment (binnen 5 s) mag de omvang tot 1 oz afwijken; het sluitmoment kiest tussen deel en rest.
- Tests: `test_v2141_afstemming_omvang.py` (3).

## 2.14.0 - 16-10-2026

### Kostenregel: opzetten die hun kosten niet terugverdienen gaan uit
- Gevraagd 16-10 bij het oordeel "geen edge aantoonbaar" (Pepperstone, 753 trades, bruto -1.619, kosten 3.519): "Als de integratie er beter van wordt alles wat nodig is uitvoeren."
- Analyse (Pepperstone, per positie): momentum en rsi_rev op 1m/3m/5m waren 327 posities met bruto -611 en kosten 2.105 - ruim de helft van alle kosten, zonder koersbeweging om ze te dragen. De t-regel (n >= 100, t < -2) greep niet: lage kosten per trade gaan op in de spreiding.
- Nieuw: een veldproefopzet stapt niet meer in als hij over minstens 40 posities bruto minder dan de helft van zijn kosten terugverdient (`KOSTEN_UITZET_MIN_N`, `KOSTEN_UITZET_DEKKING`). Per broker, over alle runs, deelsluitingen bij hun positie. Schaduwtrades lopen door (2.7.1). Weigerreden: "bruto … dekt de kosten … niet".
- Naar de huidige cijfers gaan uit: Pepperstone momentum 1m/3m/5m, rsi_rev 3m/5m; IG o.a. momentum:15m, pullback:15m, rsi_rev:30m (1m/3m/5m stonden daar al uit). Blijven aan: o.a. structuur_hl, donchian:3m, structuur_trend:3m, rsi_rev:15m.
- Geen nieuwe strategieversie: de run (en het bewijsfase-oordeel) loopt door.
- Tests: `test_v2140_kostenregel.py` (4).

### Omkeer met winst groen
- Gevraagd 16-10: "Winstgevende omkeertrades dienen ook groen te zijn in hoe trades eindigen." Het omkeerdeel is gesplitst: met winst groen, met verlies rood, beide met een gouden rand; netto per deel in de legenda.

## 2.13.4 - 16-10-2026

### Omgekeerde trades in "Hoe trades eindigden"
- Gevraagd 16-10: "Omgekeerde trades ook meenemen in hoe trades eindigen."
- Nieuw deel "omkeer" (goud) in de verdeling, met netto ernaast: trades die de omkeer sloot (verlies beperkt / kleine winst) én trades die sloten op de stop die de omkeer vastzette. Ze gaan af van "overig" en van de stops, zodat de balk op 100% blijft; tooltip splitst gesloten en vastgezet.
- `exit_stats` geeft `omkeer`, `omkeer_gesloten`, `omkeer_vastgezet` als uitsplitsing (de bestaande tellingen blijven gelijk). Ook in overzicht en rapport.
- `stop_reden` wordt nu met de trade ingelezen (alleen lezen; insert/update overschrijven hem niet).
- Tests: `test_v2134_omkeer_exits.py` (3).

## 2.13.3 - 16-10-2026

### Omkeren over alle setups en tijdvakken (besluit Ruud)
- Gemeld 16-10 13:31: "Wel extra shorts openen, maar de longs niet sluiten." Besluit: "Omkeren: komt er een short-signaal, dan sluiten alle longs, met verlies of met vastgezette winst. Op alle timeframes."
- Opent een setup (welke en op welk tijdvak ook) een positie, dan krijgen alle eerder geopende posities de andere kant op de omkeerregel van 2.5.5: in verlies of met te weinig winst sluiten, anders de winst vastzetten (stop vlak bij de koers). Sluitreden "omkeer door <setup>: …".
- Posities die ná die instap opengingen, houden hun eigen regel (2.5.5 per setup).
- Eerdere meting (15-10, vroeg afsluiten) gaf geen verbetering; het effect is te volgen in de sluitredenen.
- Tests: `test_v2133_omkeer_alle.py` (6).

## 2.13.2 - 16-10-2026

### Pepperstone lag stil: dubbele deelsluiting en "database is locked"
- Gemeld 16-10 13:14: Pepperstone niet beschikbaar. De entry stond sinds 09:53 op setup_error: `UNIQUE constraint failed: trades.broker_ticket, trades.mode` in `_record_partial` (een tweede "<ticket>-deel"-rij), en om 13:16 bij een nieuwe poging `database is locked`.
- Oorzaak 1: het deel telde pas als genomen na het boeken. Viel het boeken om, dan werd bij elke ronde en elke herstart opnieuw een deel bij de broker gesloten. Nu: direct na de sluiting bij de broker als genomen gemarkeerd; bij het opstarten aangevuld uit de database (open posities met een deel-rij).
- Oorzaak 2: een tweede deelsluiting op dezelfde positie gaf een tweede deel-rij. Nu wordt het bij de bestaande deel-rij opgeteld.
- Oorzaak 3: de mislukte INSERT liet een open transactie achter en een mislukte setup sloot de database niet; de volgende poging vond het bestand vergrendeld. Nu: rollback bij een mislukte INSERT, rollback bij sluiten, en de database dicht als de setup mislukt.
- Een boekfout bij een deelsluiting legt het exitbeheer niet meer stil (gelogd, de afstemming zet de omvang recht).
- Tests: `test_v2132_dubbele_deelsluiting.py` (4).

## 2.13.1 - 16-10-2026

### Grafiek: signalen niet meer als kolommen
- Gemeld 16-10 11:01 (schermafdruk, 15m): per candle kolommen van tientallen ruitjes tot buiten de grafiek. Op 15m vallen alle setups en tijdvakken (1m/3m/5m) in één candle, en een uitgezette opzet logt elke cyclus.
- Signalen met reden `opzet_uitgezet` tellen niet meer als marker.
- Hooguit 3 ruitjes per kant per candle (gehandeld eerst), de rest als "+N"; binnen de grafiek gehouden. De kopregel bij de cursor noemt het totaal.
- Tests: `test_v2130_grafiek_indicatoren.py` (+2).

## 2.13.0 - 16-10-2026

### Grafiek: signalen per setup en indicatoren
- Gevraagd 16-10: "Kunnen indicatoren, uitbraken etc per tijd in de grafiek worden gezet?" Gekozen: alle vier.
- Knoppen boven de grafiek (per browser onthouden): **Signalen** (ruit op de candle waar een setup een signaal gaf; vol = gehandeld, open = overgeslagen, met de setup en reden in de kopregel bij de cursor), **EMA** (20/50), **BB/DC** (Bollinger 20,2 en Donchian 20 over de vorige candles; ▲▼ bij een slot buiten het kanaal), **RSI/ATR** (RSI 14 als lijn met 30/70, ATR 14 als staafjes in een paneel onder de candles).
- Indicatoren worden in het paneel uit de candles van het gekozen tijdvak berekend; de waarden bij de cursor staan in de kopregel.
- Server: `signaal_markers()` - signalen met een richting van de lopende run (laatste 24 uur, hooguit 600), één per setup per bar.
- Het kostenfilter (2.12.0) zet nu zijn reden in het signalenlog ("kostenfilter: stop x, minimaal y"); eerder telde zo'n signaal daar als gehandeld.
- De dunne stippellijnen in de grafiek (al langer): verbinden instap en uitstap van een gesloten trade (groen winst, rood verlies).
- Tests: `test_v2130_grafiek_indicatoren.py` (3).

## 2.12.0 - 16-10-2026

### Veldproef: kostenfilter op de stopafstand
- Gevraagd 16-10: "IG en Pepperstone analyseren en verbeteren".
- Analyse (posities, deelsluitingen samengevoegd): bij geen van beide brokers een rand na kosten. IG laatste dag bruto +123, kosten 726 (0,83 USD/oz per rondreis); Pepperstone bruto +516, kosten 958 (0,18 USD/oz).
- Trades met een stop van 2 USD of minder (grootte op het plafond van 50 oz) verloren bij beide (IG n=18 t=-2,6; Pepperstone n=65 t=-2,3). Bij IG was een stop van 3-5 USD -0,39R per trade (n=17): de kosten zijn daar een kwart van het risico.
- Nu: een veldproefsignaal wordt overgeslagen als de stop dichter ligt dan max(2 USD, 8 x rondreiskosten per oz). Kosten = actuele spread + commissie + 0,15 slippage. IG: ongeveer 6,9 USD, Pepperstone 2 USD.
- Teller in de coordinatordata (`kostenfilter`: overgeslagen, per opzet, laatste).
- Let op bij eigen analyses: de hoofdrij van een positie met deelsluiting toont de RESTomvang; tel de `-deel`-rijen erbij voor de oorspronkelijke grootte.
- Tests: `test_v2120_kostenfilter.py` (6).

## 2.11.1 - 15-10-2026

### IG: geen noodstop meer door afronding bij een deelsluiting
- Gemeld 15-10: "IG geeft nu telkens noodstops". Twee posities: "broker meldt 2.68, database 2.67".
- Oorzaak: bij een deelsluiting ging `round(2.675, 2)` = 2,67 naar IG, maar de functie gaf 2,675 terug; de database boekte 2,675 dicht. Na elke handmatige hervatting kwam de noodstop terug.
- `IgVenue.close` rondt nu af vóór het versturen en geeft dat getal terug (of de omvang die IG bevestigt).
- Bestaande verschillen tot één volumestap (0,01) zet de controle recht naar de omvang van de broker (`_herstel_afronding`, waarschuwing in het logboek); een groter verschil blijft een noodstop.
- Tests: `test_v2111_afronding.py` (5).

## 2.8.1 - 14-10-2026

### cTrader: binnen de verzoeklimieten blijven
- Eerste opstart van de Pepperstone-integratie faalde: `BLOCKED_PAYLOAD_TYPE: You are being rate limited` bij het opwarmen (validatie in de wizard plus oplopende historie-aanvragen en veldproef-opwarming vlak na elkaar).
- Verzoeken worden nu gespreid: historie (trendbars, deals) hooguit één per 0,4 s (cTrader staat 5/s toe), overige één per 0,05 s.
- Bij "rate limited" tot 4 pogingen met oplopende wachttijd (1,5 s, 3 s, ...); orders worden nooit opnieuw verstuurd. Aantal in `request_stats()` als `geremd`.

## 2.11.0 - 15-10-2026

### Schaduwmeting: instap met bevestiging op 15m (besluit Ruud)
- **Doorgerekend 15-10** (1m-koersen cTrader, echte veldproefposities sinds 14-10; IG n=80, Pepperstone n=263), in R per trade:
  - Vroeg afbreken (in de eerste bar sluiten bij 0,5R tegen + 1m-slot tegen): IG -0,167 -> -0,174, Pepperstone -0,093 -> -0,091. Geen verbetering; niet gebouwd.
  - Instap met bevestiging (eerste 1m-candle na het signaal moet in de richting sluiten, instap op de slotkoers, zelfde stop en doel; anders geen trade): IG -0,167 -> +0,005 (verschil t 2,0; 15m -0,26 -> +0,02, t 2,9; 30m slechter), Pepperstone -0,093 -> -0,070 (t 0,4; 15m -0,07 -> +0,17, n=14). Nergens duidelijk winstgevend, en met 4 regels x 5 tijdvakken x 2 brokers kan één goede cel toeval zijn. Daarom niet doorgevoerd maar gemeten op nieuwe data.
- **Nieuw: `strategy/bevestiging.py`.** Per echt gehandeld 15m-veldproefsignaal een paar in de schaduw: *direct* (instap bij het signaal) en *bevestigd* (na de eerste afgesloten 1m-bar die ná het signaal begon, alleen als die in de richting sloot en de stop niet raakte; anders uitkomst 0). Zelfde simulator en uitersten (alleen van na de instap), dus een eerlijke paarvergelijking. Geen echte orders.
- Afgeronde paren in tabel `bevestiging_schaduw`; sensor **Bevestiging 15m (schaduw)**: paren, bevestigd/niet bevestigd, R per trade direct en bevestigd, verschil en t. Oordeel vanaf 30 paren; "voorstel om door te voeren" alleen als het verschil t >= 2 heeft én bevestigd positief is.

## 2.10.0 - 15-10-2026

### Analyse beide brokers (15-10, besluit Ruud: A en B)
IG sinds 14-10 06:00 UTC: 101 trades, netto -2.023 (daghandel 1 trade van 500 oz -1.185, van vóór het risicoplafond; vp 15m -683, 30m -173). Pepperstone: 290 trades, netto -2.690 (scalp -1.394, uit; vp 1m -1.037 bruto -0,08 USD/oz; 3m +2 bruto +0,33; 5m -279; 15m +195 n=15). Geen opzet met aantoonbare edge na kosten.

### A. Veldproef-tijdvakken met de hand uit
- Nieuwe optie `vp_tijdvakken_uit` (meerkeuze 1m/3m/5m/15m/30m). Alle opzetten van zo'n tijdvak gelden als uitgezet ("handmatig"), meteen bij het starten; de schaduwtrades lopen door. Geen nieuwe run.
- Voor Pepperstone: 1m uit (verliest ook vóór kosten, net als bij IG).

### B. Schaduwsimulatie geijkt
- **Gevonden:** schaduw en echt liepen ver uiteen op dezelfde signalen: rsi_rev 1m in de schaduw (IG) +24.691 USD, bruto +1,93 USD/oz, t 7,8 (n=527); echt bij Pepperstone -305, bruto -0,04 (n=31). Scalp: schaduw bruto -4,56 USD/oz, echt -0,31.
- **Oorzaak:** de schaduw (en de cooldown-schaduw) kreeg elke cyclus de hoog/laag van de laatst afgesloten candle mee, ook als die vóór de instap lag - bij de veldproef is dat de signaalbar zelf. Stop en doel werden "geraakt" door koersen van vóór de trade. De tijdstopvarianten hadden die toets al (`uitersten_vanaf`, 1.9.5), de schaduwboeken niet.
- **Nu:** `schaduw.uitersten_voor`: alleen uitersten van bars die ná de instap begonnen en alleen bij een nieuwe bar (`_uitersten_voor_varianten`), voor de schaduw van uitgezette groepen én de cooldown-schaduw.
- **Gevolg:** schaduwrijen van vóór 15-10 05:00 UTC (`GELDIG_VANAF`) tellen niet mee in onderzoek en statistiek. H-GS-003 (uitsluiten 1m/3m/scalp terecht?) begint de bevestiging opnieuw op 15-10 05:00 UTC; de eerdere schaduwcijfers waren vertekend.

## 2.9.5 - 14-10-2026

### Pepperstone: handelsrooster van de broker
- Melding Ruud: markt lijkt eerder te sluiten bij Pepperstone. Klopt: XAUUSD bij Pepperstone pauzeert 16:59-18:01 New York = 22:59-00:01 Amsterdam (IG: 23:00-24:00); vrijdag dicht om 16:55 NY. Gelezen uit het symbool (`schedule`, `scheduleTimeZone` America/New_York, `holiday`).
- Gevolg tot nu toe: om 22:59 bleef de markt voor Gold Scalper nog 5 min "open" (alleen koersleeftijd) -> NOODSTOP "geen tickdata gedurende 31s tijdens handelsuren"; na een herverbinding in de pauze gaf de momentopname een verse koerstijd.
- Nu: `CTraderVenue.markt_open()` / `minuten_tot_sluiting()` uit het rooster (incl. feestdagen); `quote.tradeable` = rooster open én koers < 5 min oud. Het IG-rooster wordt voor zo'n venue niet meer ernaast gelegd; de "geen nieuwe posities vlak voor sluiting"-regel gebruikt het rooster van de venue.
- Volgstop nagekeken: werkt. Stops bij de broker staan op de door het exitbeheer gezette niveaus (bv. 4101,30 = break-even + marge); de volgstop begint pas bij 1,5R. Tijdens de dagpauze wordt niets verschoven (markt dicht).

## 2.9.4 - 14-10-2026

### Dashboard: recente trades bleven staan
- Melding Ruud: "recente trades lijken niet te updaten". Oorzaak: de lijst toonde alleen de lopende run. Een optiewijziging (turbo uit, 22:44) startte run 4; posities uit run 3 sloten daarna wel (20:52, 20:55 UTC), maar vielen buiten de lijst.
- Nu: de laatste gesloten trades van de lopende run én trades uit eerdere runs die de laatste 2 dagen sloten, met "· run N" erachter. Statistiek, equity en bewijsfase blijven per run.

### Pepperstone: stop en doel op het gevraagde niveau
- Drie 1m-shorts sloten op de stop met "kosten -5,00": cTrader zet stop en doel bij een marktorder relatief tot de vulprijs, dus bij slippage niet op het niveau in de administratie; de kostenmeting rekende dan tegen een stop die er niet lag.
- Na de vulling worden stop en doel nu op de gevraagde niveaus gezet (`AmendPositionSLTP`), als die aan de goede kant van de vulprijs liggen; anders blijven de relatieve staan.

## 2.9.3 - 14-10-2026

### Pepperstone na de eerste 99 trades (besluit Ruud: advies 1, 2, 3)
Eerste 1,5 uur Pepperstone-demo (99 trades, netto -1.419 USD): scalp 58 trades, bruto -811, netto -1.222 (t -3,11) - verliest ook vóór kosten (-0,28 USD/oz), dus geen kostenprobleem maar geen edge. Veldproef 1m -825, 3m/5m +627 (n=20, nog toeval). Kosten ~0,15 USD/oz rondreis tegen ~0,8 bij IG.
1. **Scalp met de hand uit** - nieuwe optie `scalp_uit` (Scalp (incl. turbo) uitzetten). Werkt als de groepsregel (n >= 200, t < -3), maar meteen; de schaduwtrades van H-GS-003 lopen door. Afwijzingsreden "scalp uitgezet (handmatig)". Aangezet voor Pepperstone.
2. **Commissie in de eigen kosten** - cTrader rekent 3,50 USD per lot per zijde (gemeten: precies het verschil van 3,50 per 50 oz in de afstemming). `CTraderVenue.commissie_per_lot_per_zijde` (uit het symbool, anders 3,50); netto bij eigen sluiting en deelsluiting min commissie, kosten plus commissie, ook in de kosten/edge-toets (`commission_per_lot_per_side`). IG ongewijzigd (0).
3. Veldproef loopt door.

## 2.9.2 - 14-10-2026

### Pepperstone: noodstop na deelsluiting
- Twee keer NOODSTOP (20:59 en 21:15): "broker meldt 25.0, database 24.50" en "10.0 tegen 9.50". Oorzaak: de deelsluiting vraagt de helft (49 oz -> 24,5); cTrader sluit in hele ounces en sloot 24. De database boekte 24,5 dicht, dus bleef 24,5 open tegen 25 bij de broker.
- Nu wordt geboekt wat de broker bevestigde (`deel_units`): nooit meer dan gevraagd, zonder bevestiging het gevraagde (IG ongewijzigd).

## 2.9.1 - 14-10-2026

### Live koers ook bij Pepperstone
- Vraag Ruud: waarom live koers per tick alleen bij IG? Omdat de stroom op IG-streaming (Lightstreamer) gebouwd was. cTrader pusht de koersen al over de bestaande verbinding (spot-abonnement), dus geen tweede verbinding nodig.
- Nieuw: `VenueTickStream` (dashboard/stream.py) - zelfde gedrag als de IG-stroom (status, max. ticks per seconde, replay), gevoed door `CTraderVenue.luister_koers`. Zonder koers > 60 s: status terugval (markt dicht).
- Daardoor werkt ook de turbo-scalp (als scalp aan staat) bij Pepperstone op de live koers, net als bij IG.
- Tekst in het paneel: "live van de broker" in plaats van "via IG-streaming".
- Trendbars: 5 extra gevraagd en afgekapt; cTrader liet de lopende bar weg (119 i.p.v. 120), waardoor het opwarmen bij 119 stopte.
- Test `test_every_called_method_exists` volgt nu basisklassen uit hetzelfde bestand.

## 2.9.0 - 14-10-2026

### Dashboard: broker kiezen
- **Wens Ruud:** één Gold Scalper-dashboard met een knop om de broker te kiezen; verder alles gelijk, per broker.
- Knop **IG | Pepperstone** in de kop van het dashboard (verschijnt zodra er meer dan één Gold Scalper-integratie is). Alles daaronder - grafiek, posities, equity, statistiek, trades, schaduwtrades, live koers - komt van de gekozen integratie.
- De keuze wordt per browser onthouden. Keuringsrapport en klassiek overzicht openen voor dezelfde broker.
- API: `/api/gold_scalper/broker` geeft `brokers` (entry, naam, modus) mee; `?entry=` kiest de broker (bestond al).

### cTrader: binnen de verzoeklimieten blijven
- Eerste opstart van de Pepperstone-integratie faalde: `BLOCKED_PAYLOAD_TYPE: You are being rate limited` bij het opwarmen (validatie in de wizard plus oplopende historie-aanvragen vlak na elkaar).
- Verzoeken worden gespreid: historie (trendbars, deals) hooguit één per 0,4 s (cTrader staat 5/s toe), overige één per 0,05 s.
- Bij "rate limited" tot 4 pogingen met oplopende wachttijd; orders worden nooit opnieuw verstuurd. Aantal in `request_stats()` als `geremd`.

## 2.8.0 - 14-10-2026

### Pepperstone (cTrader Open API) naast IG
- **Besluit Ruud:** Pepperstone Razor via cTrader, naast IG ("laat ze naast elkaar draaien, IG moet ook actief blijven"). Spread XAUUSD gemeten 13-10: ~0,10 USD/oz tegen ~0,76 bij IG.
- **Nieuw: `broker/ctrader.py`** - JSON over WebSocket (`wss://demo.ctraderapi.com:5036`), één blijvende verbinding met hartslag, alleen `aiohttp`. Verkend op het demo-account (14-10): app- en accountaanmelding, XAUUSD (symbool 41, 1 oz = volume 100, stap 1 oz), saldo, trendbars, posities, koersen.
  - Orders: marktorder met relatieve stop en doel; grootte naar beneden afgerond op hele ounces (nooit meer risico dan gevraagd), onder 1 oz geen order.
  - Stop/doel aanpassen (`AmendPositionSLTP`, het andere niveau gaat mee), (deel)sluiten, posities met eigen ordernummer.
  - Afstemming: sluitende deals in IG-vorm, zodat `match_transaction` en `learning/afstemming` ongewijzigd werken; `closed_deal` rechtstreeks op positienummer.
  - Tokens: bij het instellen uit secrets.yaml (`ctrader_*`); een ververst token wordt in de entry bewaard.
- **Naast elkaar:** een tweede Gold Scalper-integratie met eigen database (`gold_scalper_ctrader.db`): geen menging van trades, afstemming of onderzoek met IG. De veldproef warmt bij cTrader op met de trendbars van de broker zelf.
- Instellen: Integratie toevoegen -> Gold Scalper -> "Pepperstone / cTrader"; alleen de SLEUTELNAMEN uit secrets.yaml.

### Tests
- `tests/test_v280_ctrader.py`.

## 2.7.3 - 14-10-2026

### Hard risicoplafond per order: 100 USD tot de stop (P2)
- **Gevonden:** 14-10 13:15 opende Daghandel een short van **500 oz** met de stop 21 USD weg: ~10.500 USD (~9.400 EUR) risico. De grootte volgde uit 3 % van het startsaldo van de run (1.000.000), begrensd op het maximum van 500 oz. Een veldproeftrade riskeert hooguit 100 USD; deze ene trade woog in de statistiek als ~100 trades. De risicolimieten van 2.7.0 grepen niet in omdat ze meeschalen met het risico per trade.
- **Wijziging:** `risico_plafond()` (strategy/posities.py): elke order - daghandel, scalp, veldproef, bijkoop - riskeert hooguit `MAX_RISICO_PER_ORDER_USD` = 100 USD tot zijn stop (naar beneden afgerond op 0,1 oz, minstens 1 oz). Ook de grootte van schaduwtrades volgt dit plafond. De instelling "risico per trade" blijft bestaan maar kan dit plafond niet meer overschrijden.
- Signalen, stops en uitstapregels ongewijzigd; geen nieuwe run.
- De lopende positie van 500 oz blijft lopen onder zijn eigen regels.

### Tests
- `tests/test_v273.py`.

## 2.7.2 - 14-10-2026

### Afstemming: deelsluiting en rest van een positie verwisseld (P1)
- **Gevonden:** een deelsluiting en de rest van dezelfde positie hebben bij IG dezelfde instapprijs, hetzelfde openingsmoment en (bij de helft) dezelfde omvang. De koppeling pakte dan de eerste transactie: de rest kreeg de uitstapprijs en het bedrag van de deelsluiting.
- **Bewijs:** 14-10 08:25: drie restposities met exact de uitstap en P&L van hun deelsluiting (+39,22 / +27,16 / +26,23 USD) en negatieve "gemeten" kosten (-11,69 / -22,53 / -20,28). In de hele database 50 trades met negatieve kosten sinds 26-08. Het resultaat van de deelsluiting telde dubbel, dat van de rest ontbrak.
- **Wijziging:** bij gelijke prijs/omvang beslist het sluitmoment welke transactie bij welke trade hoort (alle drie de aanroepen). Negatieve kosten gelden als fout: bij de volgende afstemming worden prijs, bedrag en kosten opnieuw van de broker overgenomen en gemeten. Trades binnen het afstemvenster (10 dagen) herstellen zo vanzelf; oudere blijven zoals ze zijn.

### Paneel: stop met winst
- "Hoe trades eindigden" splitst de stop in **stop met winst** (na break-even, winstslot of volgstop) en **stop met verlies**; in de tradelijst staat bij een winnende stop "winst vastgezet".

### Tests
- `tests/test_v272.py`.

## 2.7.1 - 14-10-2026

### H-GS-003: uitsluiting veldproef 1m/3m en scalp, getoetst op ongeziene data
- **Gevonden:** 1m, 3m en scalp staan sinds 2.6.1 (13-10 ~17:47 UTC) uit via de groepsregel (n >= 200, t < -3). Dat besluit is niet vooraf als hypothese vastgelegd en er kwam daarna geen data meer van die groepen: het was niet te bevestigen.
- **Bewijs (30 dagen demo):** bruto per oz 1m -0,06, 3m -0,07, scalp -0,16 USD tegen ~0,8 USD/oz kosten (spread 0,76 + slippage ~0,03); per cluster t = -3,3 / -3,3 / -2,9.
- **Wijziging:** H-GS-003 geregistreerd (verwachting negatief; ontdekking tot 13-10 17:48 UTC, bevestiging vanaf 14-10 06:00 UTC; verworpen bij netto per cluster >= 0 of t > -1, bevestigd bij netto < 0 en t <= -2, na >= 30 clusters). Eerlijk vermeld: registratie achteraf voor het besluit, vooraf voor de bevestiging.
- **Bevestiging zonder echte orders:** geldige signalen van uitgezette opzetten worden als schaduwtrade gevolgd (`strategy/uitgezet_schaduw.py`, tabel `uitgezet_schaduw`): per opzet één tegelijk en één per bar, instap incl. gemeten spread, gemeten gemiddelde slippage 0,02/oz per zijde, eigen uitstapregels (veldproef in R; geen deelsluiting), grootte als een echte order. Herkomst `geschat`; telt nergens mee in het echte resultaat, de bewijsfase of de live-poort. Echte orders zouden de risico-/clusterlimieten van H-GS-001/002 opeten.
- Onderzoeksrapport: hypotheses kunnen een negatieve verwachting en een eigen bevestigingsbron hebben; H-GS-001/002 ongewijzigd.

### Paneel
- Open posities: kolom **Bij TP** - resultaat als het doel nu geraakt wordt (resterende units, accountvaluta) en de verhouding tot het risico bij SL.

### Tests
- `tests/test_v271.py`.

## 2.7.0 — verbeterplan fase P0-P6 (meetketen, risico, onderzoek)

Opdracht Ruud 14-10 ("Gold Scalper verbeterplan"). Geen strategie- of
parameterwijziging; de live-poort is alleen strenger geworden.

* **P0 afstemming over alle pagina's.** Het IG-transactieoverzicht werd met
  één pagina van 500 opgehaald. Gevolg: van de 2.014 gesloten trades van de
  laatste 7 dagen was 55 % (1.117) nooit met de broker afgestemd (13-10 alleen
  al 1.576 trades). Waar wel afgestemd, klopte het (897 trades, gemiddeld
  0,002 EUR verschil). Nu alle pagina's (max 20 x 500), en staat er een oudere
  trade nog niet afgestemd, dan kijkt de afstemming tot daar terug (max 10
  dagen).
* **P0 instapprijs** van open posities wordt naast de broker gelegd
  (`instap_verschilt`).
* **Live-poort strenger:** nieuwe eis `boekhouding_klopt_met_broker` - geen
  afwijkingen bij gesloten trades en geen kritieke bevinding bij open posities.
  Nog niet afgestemd = dicht. Demo verandert niet.
* **P2 risicolimieten over alle posities samen** (`strategy/posities.py`):
  totaal open risico <= max(0,5 %, 5 x risico per trade) en per richting
  <= max(0,3 %, 3 x risico per trade) van het startsaldo, notional per richting
  <= 10 x startsaldo (hefboomgrens), en hooguit 3 nieuwe posities per richting in 5
  minuten over alle strategieën (één marktbeweging = één cluster). Een stop op
  break-even of in de winst telt niet als risico.
* **P3 execution ledger** (tabel `uitvoering`, `broker/uitvoering.py`): per
  order signaalmoment en bid/ask, ouderdom van koers en candle bij het besluit,
  verzendmoment en verzendkoers (live tick als die <= 5 s oud is), gevraagde
  prijs, fill, bevestigingsmoment, latency signaal->order, order->fill en
  broker-rondreis, spread bij signaal en verzending, slippage, stop, doel,
  ticket. Per veld de herkomst: gemeten / broker / berekend / geschat /
  ontbreekt. Alleen meten: geen grens op ouderdom of latency.
* **P4-P6 onderzoek op echte trades** (`learning/onderzoek.py`): netto
  expectancy per trade en per cluster (per richting, gat 10 min, over alle
  strategieën), t over clusters, bruto, kosten en kosten als % van bruto,
  profit factor, payoff, gemiddelde winst/verlies, drawdown, % afgestemd;
  segmenten (richting, sessie, volatiliteit, spread, regime, strategie) als
  meting, niet als filter; eerlijk oordeel ("te weinig data", "geen aantoonbare
  edge", "aantoonbare edge", "aantoonbaar verliesgevend"). Twee vooraf
  geregistreerde hypotheses (H-GS-001 veldproef 15m/30m, H-GS-002 5m) met
  gescheiden discovery (tot 14-10 04:32 UTC) en confirmation (daarna) en een
  vaste rejection rule. Samenvatting als attribuut `onderzoek` van de sensor
  Oordeel, volledig in de diagnostiek.

## 2.6.3

* **Veldproef-uitstap in R in plaats van vaste USD** (Ruud 14-10: "gold scalper
  verbeteren"). Nacht 13/14-10, 58 trades op 5m-30m (stops 4-12 USD/oz):
  59 % winst, maar winnaars gemiddeld +18 USD tegen verliezers -89 USD
  (netto -1.208 incl. +308 deelwinst). De vaste drempels (break-even +1,5,
  winstslot vanaf +2, deelwinst vanaf +3 USD) sneden de winnaars af bij
  ~0,2R terwijl een verlies 1R kost. Nu voor de veldproef: break-even op
  0,5R, de helft dicht op 1R, winstslot vanaf 1R 50 % en vanaf 2R 70 % van de
  winst, volgstop vanaf 1,5R op 1R. Scalp en daghandel ongewijzigd.
* Strategieversies: veldproef-2.1.0, combinatie-1.9.0 (nieuwe run).

## 2.6.2

* **Kleinere verliezen per trade** (Ruud 13-10: "verliezen per trade zijn te
  groot"). Sinds 19:48: 7 verliezers gemiddeld -270 USD tegen 4 winnaars
  gemiddeld +92. Oorzaak: elke veldproeftrade was 50 oz, ongeacht de stop
  (4-13 USD/oz op 5m/15m/30m), dus 200-650 USD risico per trade.
  * **Grootte op risico:** een veldproeftrade riskeert hooguit 100 USD tot de
    stop; de grootte volgt uit de stopafstand (stop 9 USD -> 11 oz), met de
    scalpgrootte (50 oz) als bovengrens en 1 oz als ondergrens.
  * **Geen clusters:** hooguit 3 veldproefposities per richting die nog risico
    lopen (stop nog niet op of voorbij de instap). Op 13-10 18:05-18:06 openden
    vijf shorts op dezelfde beweging en verloren samen 1.506 USD. Posities met
    de stop op break-even of in de winst tellen niet mee.
* Strategieversies: veldproef-2.0.0, combinatie-1.8.0 (nieuwe run).

## 2.6.1

* **Bewezen verliezende groepen gaan uit** (Ruud 13-10: "strategy verbeteren").
  Dezelfde regel als 2.5.6, nu per groep en strenger: alle veldproefopzetten
  van één tijdvak samen, en scalp (incl. turbo) als geheel, gaan uit bij
  n >= 200 en t < -3 (netto per trade, alle runs). Stand 13-10 19:00 (USD/oz
  per trade): 1m n=481 -0,77 t=-8,7; 3m n=257 -0,80 t=-4,8; scalp n=381
  -0,78 tot -1,18 t ~ -5 per soort. Dat is ongeveer de spread: op die korte
  termijn verdient de beweging de kosten niet terug. 5m (n=183), 15m en 30m
  blijven aan (sinds de nieuwe uitstapregels 5m +0,92, 15m +0,35, 30m +1,09
  USD/oz per trade). Het paneel toont "alle 1m (n, t)" en "scalp uitgezet".
* Strategieversies: veldproef-1.9.0, combinatie-1.7.0 (nieuwe run).

## 2.6.0

* **Verzoekenlimiet van IG is geen verlopen sessie.** Bij elke HTTP 403 logde
  de client opnieuw in, ook bij `error.public-api.exceeded-account-allowance`
  en `exceeded-api-key-allowance`. Dat inloggen is zelf een verzoek dat
  dezelfde limiet raakt ("Inloggen mislukte ... 403"), dus elke geweigerde
  koersopvraging of order kostte er twee en hield de limiet langer vol. Op
  13-10 in ruim twee uur meer dan 100 van die logregels, waaronder reeksen van
  10 mislukte orders binnen 10 s. Nu: een limietfout komt meteen terug als
  fout (de bestaande afhandeling wacht en probeert de volgende cyclus), de
  sessie blijft staan. Andere 401/403 (verlopen token) loggen nog steeds
  opnieuw in. Geen strategie- of instellingswijziging: zelfde vingerafdruk.
* Tests: `test_v260.py`.
* Versietests van 2.5.9 vergelijken met >= (zoals de andere).

## 2.5.9

* **Deelwinst voor alle strategieën** (Ruud 13-10: "partial profits werkt nog
  steeds niet? Units blijven op 50 staan"). Deelsluiting stond bij elke
  strategie uit. Nu: de helft van de positie dicht vanaf +3 USD/oz winst (of
  de ATR/R-drempel als die eerder komt); de rest loopt door met break-even,
  winstslot en volgstop. Geboekt als eigen gesloten trade `<ticket>-deel`.
* **Open posities: kolom "Gerealiseerd"** met de al genomen deelwinst per
  positie; de Units-kolom toont wat er nog openstaat.
* Strategieversies omhoog (nieuwe run): veldproef-1.8.0, daghandel-1.6.0,
  combinatie-1.6.0, scalp-0.4.0.

## 2.5.8

* **Open posities: kolom "Bij SL"** (Ruud 13-10: "in het open posities
  overzicht verwacht ik ook iets als gerealiseerde profit/loss"). Per positie
  het resultaat als de stop nu geraakt wordt, in accountvaluta: groen
  "vastgezet" zodra break-even of de winstslot de stop in de winst heeft
  gezet, anders rood "risico".

## 2.5.7

* **Winstslot: winst sneller vastzetten, ook bij volatiliteit** (Ruud 13-10:
  "bij sommige posities wordt de winst nog niet snel genoeg veiliggesteld,
  zeker bij volaliteit"). Tussen break-even (+1,5 USD/oz) en de ATR-trailing
  (pas vanaf 1,5 x ATR, bij ATR 5,4 dus +8 USD) stond de stop op de instap
  en kon de hele winst teruglopen. Nu voor alle strategieën: vanaf +2 USD/oz
  de helft van de lopende winst vast, vanaf +5 USD/oz 70%; altijd minstens
  0,6 USD van de koers. De stop schuift alleen mee. Trailing en winstslot:
  de strakste wint.
* Strategieversies omhoog (nieuwe run): veldproef-1.7.0, daghandel-1.5.0,
  combinatie-1.5.0, scalp-0.3.0.

## 2.5.6

* **Bewezen verliezende veldproefopzetten gaan uit** (regel van Ruud: "een
  opzet uitzetten bij >= 100 trades en t < -2", netto per trade). Elke 5
  minuten leest de coordinator per opzet het netto van alle gesloten trades
  (over alle runs); een opzet met n >= 100 en t < -2 stapt niet meer in
  (reden `opzet_uitgezet`). De lijst staat in de reden van de veldproef in het
  paneel en elke nieuw uitgezette opzet komt als waarschuwing in het log.
  Op 13-10 13:15 UTC+2 geldt dat voor `rsi_rev:1m` (n=100, netto -2.884 USD,
  t -2,72); `momentum:1m` (n=86, t -3,42) volgt bij 100 trades.
* Strategieversie veldproef-1.6.0: nieuwe run.
* Tests: `test_v256.py`.

## 2.5.5

* **Break-even uiterlijk bij +1,5 USD/oz, ook bij veldproef en daghandel**
  (Ruud 13-10: veldproef rsi_rev 15m/30m stonden op +3 USD en de stop stond nog
  niet op de instap). De R- of ATR-drempel van 2.5.1 (0,5R / 1 x ATR15) is bij
  15m/30m 3,5-5 USD; nu geldt wat het eerst gehaald wordt. Scalp blijft +0,6.
  Nieuwe strategieversies (veldproef-1.5.0, daghandel-1.4.0, combinatie-1.4.0).
* **Omkeer-exit: signaal of trend gedraaid** (Ruud 13-10: "als de trend of
  het signaal verandert, posities in verlies sluiten; in winst de winst zoveel
  mogelijk pakken"). Geeft de eigen strategie van een positie een signaal in de
  andere richting (veldproefopzet, scalp, daghandel-uurtrend), dan: in verlies
  of met minder dan 0,6 USD/oz winst sluiten; anders de stop op 0,6 USD/oz van
  de koers zetten (zo dicht als IG toelaat). Gebruikt de signalen van de vorige
  cyclus; een signaal zonder richting telt niet.
* Tests: `test_v255.py`.

## 2.5.4

* **Tot 100 posities per richting** (Ruud 13-10: "max posities mocht veel
  hoger"). De grens van de instelling *Max posities per richting* gaat van 20
  naar 100 (totaal dus tot 200). Let op: meer posities betekent meer
  stopwijzigingen bij IG en dus sneller de verzoekenlimiet; het orderbudget van
  turbo en de bestaande grendels (marge, vloer, daglimiet) blijven gelden.
* Tests: `test_v190`/`test_v242` volgen de nieuwe grens.

## 2.5.3

* **Eigen turbosignaal: uitbraak op de live koers** (Ruud 13-10, keuze 2).
  Turbo-scalp (2.5.0) reageerde alleen op het gewone scalpsignaal, en dat kwam
  zelden boven de drempel (score ~0,1 tegen 0,30): 0 turbotrades. Nieuw in
  `strategy/turbo.py`: de middenkoers breekt minstens 0,10 USD door de band van
  de laatste 45 s (zonder de laatste 2 s), met minstens 0,30 USD doorzetting in
  10 s; band tussen 0,40 en 6 USD; spread binnen `max_spread`; 30 s wachten na
  een uitbraakinstap. Stop en doel van scalp (2 / 1 USD), scalpexits met snelle
  break-even. Elke tick voedt het signaal; geeft het scalpsignaal niets, dan
  beslist de uitbraak. Zelfde grendels en orderbudget als turbo-scalp.
* Paneel/redenen: aantal uitbraakorders en de laatste uitbraakuitkomst.
* Vingerafdruk: `scalp_turbo` bevat de signaalversie (turbo-uitbraak-1.0.0):
  nieuwe run.
* Paneel: kolom Strategie toont "Turbo scalp" voor posities die turbo-scalp
  opende (open_reason "turbo uitbraak" / "turbo scalp").
* Tests: `test_v253.py`.

## 2.5.2

* **Geen valse netting meer als een tegengestelde positie op haar eigen stop
  sluit.** Op 13-10 om 10:02 UTC opende een veldproef-short (28VDTA7) in
  dezelfde seconden waarin een veldproef-long (286ATAG) bij de broker op zijn
  stop sloot. De nettingcontrole zag de long verdwijnen en meldde
  verrekening; daarop ging hedgen uit tot een herstart, zodat alle
  tegengestelde signalen (bv. momentum:1m en pullback:3m short) geweigerd
  werden. De short stond na de order gewoon volledig open (sloot pas om
  10:08 op zijn stop), en IG opent met `forceOpen` altijd apart. Nu geldt:
  staat de nieuwe positie er na de order volledig, dan is er niets
  verrekend. Een echte (gedeeltelijke) verrekening, waarbij de nieuwe
  positie ontbreekt of kleiner is dan besteld, wordt nog steeds luid gemeld.
  Geen strategiewijziging (zelfde strategieversie).
* Tests: `test_v252.py`.

## 2.5.1

* **Snel de stop naar de instap, bij alle strategieën** (Ruud 13-10: "bij alle
  trades relatief snel stop naar entry om verliezen te beperken").
  * Scalp: stop naar de instap zodra +0,6 USD/oz winst staat (was 0,8 x ATR15,
    ~4 USD, bij een doel van 1 USD dus nooit).
  * Veldproef: break-even vanaf 0,5R (was 1R).
  * Daghandel: break-even vanaf 1 x ATR15 = 0,25R (was uit; de backtest van
    2.1.0 vond break-even slechter voor de daghandel: meten).
  * De stop blijft minstens 0,6 USD/oz van de koers (IG weigert stops te dicht
    bij de koers); past instap + kosten niet, dan de instap zelf.
  * Nieuwe strategieversies (veldproef-1.4.0, daghandel-1.3.0,
    combinatie-1.3.0): nieuwe run.
* Tests: `test_v251.py`; `test_v195` volgt de nieuwe scalpconfiguratie.

## 2.5.0

* **Turbo-scalp** (Ruud 13-10: "turbo trading, bij wijze van seconden, moet
  mogelijk zijn tijdens scalpen"). De scalp reageert nu ook op de live koers
  van IG (dezelfde stroom als het paneel) in plaats van alleen op de cyclus
  van 10 s: hooguit één ronde per seconde, met bijkopen in de scalpreeks en
  nieuwe scalpposities. Dezelfde grendels als de cyclus (risico, wisselkoers,
  sluiting, netting, spreiding, marge, vloer). Een *orderbudget per minuut*
  (standaard 20) houdt de IG-limieten heel; de turbo gebruikt de posities
  en het saldo van de laatste cyclus en vraagt alleen na een order de
  posities opnieuw op. Draait nooit tegelijk met de cyclus. Alleen met IG in
  demo/live en bij scalp/combinatie/alles. Twee nieuwe instellingen (staat
  standaard aan); hoort bij de vingerafdruk: nieuwe run. Het paneel toont
  onder de redenen een regel "Turbo-scalp" met het verbruik.
* Tests: `test_v250.py`.

## 2.4.11

* **Paneel: open posities uit een vorige run kregen het label "Daghandel".**
  Het paneel las alleen de open trades van de lopende run. Na elke
  instellingswijziging of herstart (nieuwe run) kende het de posities die
  nog openstonden niet en viel het terug op de primaire strategie
  (daghandel), met de maximale duur tot 20:45. Nu ook open trades uit
  eerdere runs (laatste 2 dagen), met hun eigen strategie, stop en doel.
* **Tijdstip van de laatste stopverplaatsing** (Ruud 13-10: "om trailing te
  controleren"). Elke verplaatste stop (break-even, volgstop) legt moment,
  reden en aantal vast; het paneel toont onder SL "↕ hh:mm (n×)", met de
  reden als tooltip.
* Tests: `test_v2411.py`.

## 2.4.10

* **Veldproef: break-even en volgstop** (Ruud 13-10: "soms mooie P&L van 3
  USD en toch uitgestopt"). De veldproef had bewust alleen stop, doel (2R)
  en maximale duur. Gemeten sinds run 110: 4 van de 27 trades die minstens
  2 USD/oz in de plus stonden, sloten toch met verlies, alle vier veldproef.
  Nu: vanaf 1R winst de stop naar instap plus kosten, vanaf 1,5R een
  volgstop op 1R afstand. R is de stopafstand bij instap, afgeleid uit het
  vaste doel (R = doel-afstand / 2). Nieuwe strategieversie
  (veldproef-1.3.0): nieuwe run.
* **Verweesde trades worden door de afstemming nagekeken.** Na de herstart
  van 13-10 kregen acht weesjes allemaal 4190,33 uit één activiteit van de
  broker; het transactieoverzicht rekende er een af op 4185,13. De
  afwikkeling staat nu als voorlopig, zodat de afstemming de prijs van de
  broker overneemt.
* Tests: `test_v2410.py`.

## 2.4.9

* **Scalpreeks** (Ruud 13-10: "bij scalpen veel meer trades in de
  minuutcandle, soort pyramide opbouwen ... mogelijk zelfs met 1 USD winst;
  tot wel 100 trades"). Loopt een scalppositie in de goede richting, dan komt
  er bij elke *stap* (standaard 0,30 USD/oz sinds het vorige stuk) een stuk
  van dezelfde grootte bij, tot *maximaal 100 stukken* per reeks en hooguit
  3 per cyclus (IG-limieten). Elk stuk heeft een eigen *winstdoel*
  (standaard 1,00 USD/oz) en deelt de stop van de eerste positie. Nooit
  bijkopen bij tegenslag. Elk stuk is een eigen trade ("pyramide van
  <ticket>"), dus resultaat, kosten en afstemming kloppen; voor de statistiek
  is een reeks één cluster. Vier nieuwe instellingen; staat standaard aan en
  vervangt voor scalp de ATR-piramide. Hoort bij de vingerafdruk: nieuwe run.
* *Doel als vast bedrag* (scalp) in stappen van 0,1 USD in plaats van 0,5,
  zodat ook een doel van 0,2 USD kan (Ruud 13-10: "mag al bij 0,2 sluiten
  als het maar winstgevend is"). Het doel telt vanaf de vulprijs, dus na de
  spread.
* **Paneel: reden per strategie.** Bij *alles* stond onder *Waarom geen
  trade* alleen de reden van de daghandel ("geen_uitbraak"), ook als scalp
  en veldproef gewoon handelden. Nu per strategie: daghandel, scalp, en voor
  de veldproef hoeveel signalen er deze cyclus instapten.
* Tests: `test_v249.py`.

## 2.4.8

* **Vast winstdoel alleen nog voor scalp** (Ruud 13-10: "scalp moet kort,
  snel en kleine winsten pakken"). Sinds 2.4.6 gold *Doel als vast bedrag*
  (`take_profit_usd`) voor alle strategieën: met 2 USD gedroegen de
  veldproefopzetten op 15m/30m (stops 8-12 USD) zich als scalp en was er
  geen verschil meer. Nu weer: scalp het vaste doel, de veldproef 2 x de
  stop, de daghandel geen doel (volgstop en 20:45 UTC). Nieuwe
  strategieversies (veldproef-1.2.0, daghandel-1.2.0, combinatie-1.2.0):
  nieuwe run.
* **Paneel: veldproefposities kregen het label "Daghandel"** bij de keuze
  *alles*, met de maximale duur tot 20:45. Nu "VP <familie> <tijdvak>" met
  de eigen maximale duur (48 bars van het tijdvak) en zonder tijdstop.
* Tests: `test_v248.py`, `test_v246.py` bijgewerkt.

## 2.4.7

* **Verweesde trades worden afgewikkeld.** Een positie uit een eerdere run
  die al dicht was voordat de nieuwe run hem kon meenemen (runwissel,
  herstart), bleef eeuwig open in de database en telde in geen enkel
  resultaat mee. Op 13-10 ging het om 23 veldproeftrades uit run 110/111.
  Elke 5 minuten worden er nu tot 3 nagevraagd in het activiteitenoverzicht
  van de broker en afgewikkeld op diens uitstapprijs en sluitmoment, in hun
  eigen run. Nooit op een schatting: niet gevonden = blijft staan. Telt niet
  mee voor daglimiet of verliesreeks. Alleen trades jonger dan 46 uur.
* Tests: `test_v247.py`.

## 2.4.6

* **Winstdoel uit de instellingen voor alle strategieën** (Ruud 13-10: "alles
  op instelbaar doel, nu 3"). *Doel als vast bedrag* (`take_profit_usd`, USD/oz)
  gold alleen voor scalp. Nu ook voor de veldproef (was vast 2R) en de
  daghandel (was geen doel; de volgstop en 20:45 UTC blijven). 0 = elke
  strategie haar eigen doel zoals voorheen. Nieuwe strategieversies
  (veldproef-1.1.0, daghandel-1.1.0, combinatie-1.1.0): nieuwe run.
* Tests: `test_v246.py`.

## 2.4.5

* **Dashboard: "Netto sinds start" in plaats van "Netto run".** Elke
  instellingswijziging start een nieuwe run en een positie telt bij de run die
  haar opende; "Netto run" toonde op 13-10 -841 USD terwijl het saldo bij IG
  in die run +2.429 EUR steeg (posities van run 108 sloten in run 110). Het
  hoofdgetal telt nu alle runs van de huidige strategie (zelfde modus en
  strategieversie, aaneengesloten), met eronder de huidige run en de
  saldoverandering bij de broker als controle. *Kosten* gaat over dezelfde reeks.
* **Grafiek: 1m, 3m, 5m, 15m, 30m, 1u en 4u.** 1m/3m/5m/30m komen uit de
  veldproefbars, 15m/1u/4u uit de basiscandles (45m en 3u vervallen).
* Tests: `test_v245.py`.

## 2.4.4

* **Geen valse noodstop meer als het saldo niet op te vragen is.** Faalde het
  opvragen van het account (IG-limiet `exceeded-account-allowance`, DNS-fout),
  dan werd de startbalans als equity ingevuld. Met *Startbalans* 1.000.000 op
  een account van ~10 miljoen viel dat onder de verliesvloer: NOODSTOP op
  13-10 02:16 en 06:43 zonder enig verlies. Nu geldt de laatst gemeten
  waarde voor de weergave en wordt er die cyclus geen risicotoets gedaan en
  geen positie geopend ("saldo van de broker niet op te vragen"); het
  exitbeheer loopt door.
* Tests: `test_v244.py`.

## 2.4.3

* **Afstemming met de broker over alle runs.** De dagelijkse afstemming (en
  de actie *Afstemmen met de broker*) keek alleen naar de lopende run. Na een
  runwissel bleven de laatste dagen van de vorige run ongecontroleerd: op
  13-10 06:03 meldde hij "geen gesloten trades" omdat run 110 net begonnen
  was. Nu alle gesloten brokertrades van dezelfde modus binnen het venster.
* Tests: `test_v243.py`.

## 2.4.2

* **Tot 20 posities per richting** (Ruud 13-10). De grens van de instelling
  *Posities per richting* gaat van 3 naar 20; het totaal groeit mee
  (2 x de limiet, plus daghandel en veldproef).
* Tests: `test_v242.py`, `test_v190.py` (grens).

## 2.4.1

* **Veldproef: minimale stopafstand 1,0 USD.** IG wees de 1m-orders af met
  `ATTACHED_ORDER_LEVEL_ERROR` (stop 0,56 USD bij 1,5 x ATR(1m)). Het doel
  blijft 2 x de stopafstand.
* Een afgewezen veldproeforder wordt niet elke cyclus opnieuw geprobeerd;
  pas de volgende bar van dat tijdvak telt weer.
* Tests: `test_v241.py`.

## 2.4.0

* **Veldproef: alle opzetten op 1m, 3m, 5m, 15m en 30m met echte demo-orders
  (L-GS-018, opdracht Ruud 12-10: "geen schaduw trading maar echt traden op
  diverse candle-tijden, zoveel mogelijk, om te verzamelen en te leren").**
  Nieuwe strategiekeuze **alles** = daghandel + scalp + 45 veldproefopzetten
  (`vp:<familie>:<tijdvak>`): EMA 9/21-kruising, Donchian 40 met trend, RSI(2)
  terugkeer, Bollinger 2,5 terugkeer, marktstructuur (breuk in HH/HL resp.
  LH/LL, en instap op een bevestigde hogere bodem / lagere top), momentum,
  pullback naar EMA20 en inside-bar-uitbraak.
  * Per opzet hooguit één positie, één instap per bar van het eigen
    tijdvak, vaste grootte (`scalp_units`), stop 1,5 x ATR(14) en doel 2R bij
    de broker, hooguit 48 bars open. Geen schaduwtrades.
  * Tot 6 nieuwe posities per cyclus; het totaal aantal posities groeit met
    één per opzet. Alleen de daghandel telt voor de verliesreeks.
  * Bars op alle vijf tijdvakken uit de koersen (behalve 15m ook in het
    archief); bij het opstarten opgewarmd uit het archief, 30m uit de 15m van
    IG en anders uit de koersgeschiedenis van Home Assistant (10 dagen).
  * Signaallog alleen voor veldproefsignalen met een richting.
* Onderzoek vooraf (L-GS-017, 6.048 varianten op 1m-30m met kosten 1,4
  USD/oz): bruto gemiddeld ~0, winnaars op het eerste deel verloren op het
  laatste. Er is vooraf geen winnaar; de veldproef meet de werkelijke
  uitvoering per opzet en tijdvak. Live blijft dicht.
* Tijdvak `3m` toegevoegd.
* Tests: `test_v240_veldproef.py`.

## 2.3.0

* **Nieuwe actie `gold_scalper.export_data` (L-GS-017, onderzoek).** Geeft
  archiefbars (`kind: bars`, per tijdvak), de inhoud van het archief
  (`kind: available`) of gesloten trades (`kind: trades`, optioneel per run)
  terug als antwoord, in pagina's (`offset`/`limit`, hooguit 5000). Alleen
  lezen: geen verzoek naar de broker, de handel verandert niet. Bedoeld om
  strategieën op 1m/5m/15m/30m buiten Home Assistant te toetsen (opdracht
  Ruud 12-10: "de integratie moet winstgevend worden").
* Tests: `test_v230_export.py`.

## 2.2.1

* Paneel, tabel *Open posities*: kolom **Strategie** (Daghandel/Scalp) met
  "+ bijkoop" bij een pyramide-toevoeging. Alle open posities stonden er al in
  (en in de grafiek elk met instap-, stop- en doellijn); nu zie je per regel
  welke strategie hem opende.

## 2.2.0

* **Pyramiden volwaardig (besluit Ruud 12-10: "moet actief zijn").** Tot nu
  toe werd een bijkoop wel bij de broker geplaatst maar nergens vastgelegd:
  geen resultaat, geen kosten, en bij de afstemming een onbekende positie.
  Nu:
  * elke bijkoop is een eigen trade met `open_reason` "pyramide van
    <ticket>" en de strategie van de oorspronkelijke positie;
  * de verplaatste stop van de oorspronkelijke positie gaat ook in de eigen
    administratie;
  * een bijkoop piramidet zelf niet verder (anders stapelden toevoegingen
    zich op toevoegingen);
  * na een herstart telt het aantal toevoegingen door uit de administratie;
  * een onbevestigde bijkoop wordt teruggezocht en dan vastgelegd, zoals een
    gewone order.
* Bij de combinatie piramidet alleen de scalp (de daghandel is zonder
  bijkopen getoetst). De waarschuwing "bijkopen wordt nog niet vastgelegd"
  is weg.
* Tests: `test_v220_pyramide.py`.

## 2.1.1

* Status en *Open posities*: bij de combinatie telde "long/short" alleen de
  daghandelposities ("1 positie(s) open (0 long, 0 short)"). Nu alle posities.

## 2.1.0

* **Combinatie van daghandel en scalpen, beide met echte orders (L-GS-015,
  besluit Ruud 12-10-2026).** Nieuwe keuze *Combinatie* bij *Strategie*.
  Elke positie draagt de strategie die haar opende (`trades.strategie`, nieuwe
  kolom) en houdt haar eigen regels:
  * daghandel: risicogestuurde grootte, hooguit één positie, volgstop, dicht
    om 20:45 UTC;
  * scalp: vaste grootte *Scalpgrootte bij combinatie* (standaard 1 oz), de
    limiet per richting, het oorspronkelijke exitbeheer met tijdstop,
    tijdstopvarianten en (indien aan) pyramiden.
* Spreiding en cooldown per strategie; marge, vloer, daglimiet en het totaal
  aantal posities over alles samen (totaal +1 voor de daghandelpositie).
* De verliesreeks telt bij de combinatie alleen de daghandel: een gewone
  scalpreeks legt de daghandel niet meer stil.
* Resultaat per strategie in de sensor *Trades* (`per_strategie`) en het
  signaal per strategie in de sensor *Signaal* (`per_strategie`).
* Een andere keuze of scalpgrootte is een andere opzet: nieuwe run
  (`combinatie-1.0.0`).
* *Startbalans papermodus* heet nu *Startbalans (basis voor positiegrootte en
  limieten)*, met uitleg: het geldt ook op de IG-demo.
* **Daghandel: winst eerder veiligstellen (Ruud: "winst veilig stellen met
  trailing stops").** Volgstop 4 x ATR(15m) vanaf 2 x ATR winst (was 6 x ATR).
  Backtest 2011-2018 (zelfde signalen): netto +0,20 tegen +0,12 ATR per
  trade, beter in beide helften. Krapper (2 x ATR) of een break-evenstop
  deed het slechter (-0,10 / -0,03): een trend wordt dan te vroeg
  afgebroken. Scalpen houdt break-even bij 0,8 x ATR en de volgstop van
  1,2 x ATR vanaf 1,5 x ATR.
* **Paneel**: uurgrafiek erbij (15m · 45m · 1u · 3u); instapmarkers van open
  en gesloten posities met de strategie (D = daghandel, groter met gouden
  rand; S = scalp), het label ook bij de instaplijn en op de positiekaart;
  bij daghandel telt *Max. duur* af tot 20:45 UTC in plaats van een tijdstop.
* Tests: `test_v210_combinatie.py`, `test_v210_paneel.py`.

## 2.0.1

* **Een andere strategie start altijd een nieuwe run.** In 2.0.0 werd run 101
  (scalpen) na de overstap op daghandel gewoon voortgezet: de strategie was
  niet zelf ingesteld (standaardwaarde) en telde daarom niet als wijziging.
  `strategy` hoort nu bij de structurele verschillen, net als bron en
  tijdvak.
* Tests: `test_v201.py`.

## 2.0.0

* **Van scalpen naar daghandel (L-GS-014, besluit Ruud 12-10-2026).** Nieuwe
  instelling *Strategie*, standaard **daghandel**; *scalpen* blijft kiesbaar.
  Een andere strategie is een andere opzet en start dus een nieuwe run
  (`strategy_version` `daghandel-1.0.0`).
* **Waarom.** De scalper verloor ~1,5 USD/oz per trade (run 101: 126 trades,
  bruto +7, kosten 192): bij trades van vier minuten zijn de kosten even
  groot als de beweging. Vijf vooraf vastgelegde daghandelopzetten getoetst
  op 2011-2018 (Dukascopy, 160.000 kwartierbars) en IG juni-oktober 2026.
  De beste, trendvolgend op uurbasis: netto +0,10 / +0,17 / -0,02 ATR(15m)
  per trade (2011-14 / 2015-18 / IG 2026). Kosten ~20% van de beweging in
  plaats van ~100%. **Geen aantoonbaar voordeel** (t < 1): dit draait op
  demo om het te meten; de livepoort blijft dicht.
* **Regels** (`strategy/daghandel.py`, gelijk aan de backtest; 89 van 91
  signalen identiek op feb-apr 2016):
  * richting: uur-EMA20 boven/onder EMA50 (alleen afgesloten uren);
  * instap: slot door het hoog/laag van de 80 kwartierbars ervóór, alleen
    07:00-17:00 UTC, hooguit één positie, 15 min wachten na een instap;
  * stop 4 x ATR(15m), geen doel;
  * uitstap: volgstop 6 x ATR vanaf 2 x ATR winst, geen tijdstop, geen
    break-even, uiterlijk **20:45 UTC dicht** (ook elke positie van een
    eerdere dag): geen nachtkosten, geen gat over de dagpauze.
* `ExitConfig.sluit_om_uur_utc` (nieuw, standaard uit voor scalpen).
* Bij daghandel geen tijdstopvarianten (er is geen tijdstop) en geen
  pyramiden.
* Toetsregel vooraf: na >= 100 trades netto > 0 met t >= 2 over handelsdagen;
  anders heeft ook deze opzet geen voordeel.
* Tests: `test_v200_daghandel.py` (16).

## 1.11.0

* **Geen strategiewijziging; foutafhandeling (L-GS-012).** Instapsignalen,
  uitstappen, ordergrootte en risico zijn niet aangeraakt.
* **Een afwikkelfout bij één trade legt de cyclus niet meer stil.** Op 12-10
  02:21-03:21 faalde elke cyclus een uur lang op één verdwenen trade; ook het
  exitbeheer en de tijdstops van andere posities stonden dan stil. Nu wordt
  een onverwachte fout per trade afgevangen: die trade blijft staan en wordt
  de volgende cyclus opnieuw geprobeerd, de rest van de cyclus loopt door.
  De fout komt één keer met traceback in het log.
* **Geen instap in een cyclus waarin een afwikkeling mislukte** (eerst de
  boekhouding rond). Reden in de diagnostiek: "afwikkeling van een trade
  mislukt: geen instap deze cyclus".
* **Reparatiemelding** in Home Assistant als dezelfde trade 10 cycli op rij
  niet af te wikkelen is; verdwijnt vanzelf als het weer lukt.
* Tests: `test_v1110.py` (7).

## 1.10.3

* **Geen strategiewijziging; foutafhandeling.** Instappen, uitstappen,
  ordergrootte, risico en handelslogica zijn niet aangeraakt.
* **Integratie viel uit bij het afrekenen van een verdwenen positie.** Op
  12-10 vanaf 02:21 gaf elke cyclus "Unexpected error fetching gold_scalper"
  (360 keer) en waren alle entiteiten onbeschikbaar. Bij het zoeken naar de
  uitstapprijs stonden twee verschillende transacties met hetzelfde
  `openLevel` in het overzicht; `sort()` vergeleek daarna de transacties
  zelf (dicts) en gooide een `TypeError`. Nu wordt alleen op verschil en
  niveau gesorteerd.
* Tests: `test_transactie_volledigheid.py` (+1).

## 1.10.2

* **Geen strategiewijziging; foutafhandeling.** Instappen, uitstappen,
  ordergrootte, risico en handelslogica zijn niet aangeraakt.
* **Time-out op het positie-overzicht is een tijdelijke brokerfout.** Op
  10-10 19:27 antwoordde IG niet binnen 15 s op `GET /positions` in de
  voorcheck van de cyclus. Die fout werd niet afgevangen: Home Assistant
  logde "Unexpected error fetching gold_scalper" met traceback en alle
  entiteiten waren even onbeschikbaar. Nu gaat het zoals bij een mislukte
  koers (1.7.0): het laatste beeld blijft staan (`koers_verouderd`,
  `mislukte_opvraging: Positie-opvraging`), en in die cyclus wordt niets
  beslist - geen instap, geen stop verplaatsen, geen sluiting. Na drie keer op
  rij volgt een gewone updatefout (geen "Unexpected error").
* De teller van mislukte opvragingen gaat pas terug naar nul als koers én
  positie-overzicht binnen zijn; de logtekst noemt welke opvraging mislukte.
* Tests: `test_release_1102.py` (5).

## 1.10.1

* **Geen strategiewijziging; meetfout in de drawdown.** Instappen, uitstappen,
  ordergrootte, risico en handelslogica zijn niet aangeraakt.
* **De terugval op de startbalans is geen equitymeting.** Mislukte de
  accountopvraging bij de broker (zoals na een herstart in het weekend), dan
  rekende de cyclus met de ingestelde startbalans (10.000) en schreef die als
  equitypunt in de equitycurve. Op een demo-account van ~10 mln gaf één zo'n
  punt op 10-10 een **max. drawdown van 99,9 %** (sensor, rapport en de
  redenen van het oordeel). Nu wordt alleen een gemeten equity weggeschreven.
* **Bestaande terugvalpunten tellen niet meer.** `account_drawdown` slaat
  punten over waar equity = saldo = startbalans van de run terwijl de
  gemeten opening van de run meer dan 1 % afwijkt; het aantal staat in
  `terugvalpunten_overgeslagen`. Zonder gemeten opening (papier) of met een
  opening rond de startbalans verandert er niets.
* Tests: `test_release_1101.py` (6).

## 1.10.0

* **Afstemming met de broker bewaard.** De uitkomst van de laatste afstemming
  (status, tijdstip, aantallen, verschillen) overleeft een herstart; de sensor
  toont hem met `moment` en `hersteld` als attribuut. Na een herstart wordt
  één keer afgestemd, ook als de markt dicht is. Alleen lezen bij de broker
  (transactie- en activiteitenoverzicht); er wordt niets geplaatst, gesloten
  of gewijzigd. Is de broker niet bereikbaar, dan blijft de bewaarde uitkomst
  staan (`laatste_fout`) en probeert de lus het later opnieuw.
* **Sluitreden achteraf ingevuld.** Een trade met sluitreden onbekend krijgt
  zijn reden uit de afstemming als de broker hem kent: doel (uitstap op het
  doel), stop (door het systeem van de broker gesloten), tijdslimiet of
  maximale duur (via de API gesloten na die looptijd), handmatig (web,
  mobiel, dealer). Gemarkeerd met bron `afstemming`; de oorspronkelijke reden
  blijft staan. Doel geraakt, stop geraakt en sluitreden onbekend volgen
  meteen.
* **Sluitredenen gegroepeerd.** "na 243s nog binnen 0.3xATR ..." is nu de
  soort `tijdslimiet` (en "maximale positieduur ..." `max_duur`), met de
  looptijd apart in `looptijd_s`. Opgeslagen trades worden bij het openen van
  de database omgezet. Paneel: looptijd in de toelichting, een `*` bij een
  achteraf ingevulde reden.
* Geen strategie- of handelswijziging.

## 1.9.6

* **Het paneel verspringt niet meer tijdens scrollen op mobiel.** De live
  koers bouwde meerdere keren per seconde blokken opnieuw op, ook als er
  niets veranderde. Op een telefoon (vooral iOS) schoof de pagina daardoor
  tijdens het scrollen. Nu wordt een blok alleen vervangen als de HTML echt
  anders is, en tijdens aanraken, scrollen en het uitrollen daarna wacht het
  paneel met bijwerken; daarna in een keer. Geen strategiewijziging.

## 1.9.5

* **Geen strategiewijziging, alleen meting.** Instappen, uitstappen,
  ordergrootte, risico en de configuratie van het echte exitbeheer zijn niet
  aangeraakt; de tijdstop blijft 240 s.
* **Tijdstopvarianten (L-GS-008).** Elke echte positie (demo/broker en
  papier) wordt nagespeeld met vier varianten: tijdstop **240 s** (spiegel van
  de huidige instelling, om de simulatie tegen de echte uitkomst te toetsen),
  **480 s**, **720 s** en **geen tijdstop**, allemaal met de ingestelde
  maximale positieduur (900 s). Verder identiek: zelfde instapprijs (de
  werkelijke fill als die bekend is, anders de instapkoers), grootte,
  beginstop, doel, trailing en break-even. Elke variant heeft een eigen
  kopie van de exitconfiguratie; de echte wordt nooit gewijzigd.
  * Gesimuleerd met dezelfde regels als de schaduwtrades (de stap is nu
    gedeelde code): stop en doel tegen de uitersten van de bars, beide geraakt
    telt de stop, afrekenen op bied (long) of laat (short), slippage en
    commissie als bij schaduwtrades. Verfijning: alleen uitersten van bars die
    die cyclus afsloten en ná de instap begonnen.
  * Een variant loopt door nadat de echte trade sloot, tot zijn eigen
    uitstap. Geen extra verzoeken bij de broker.
  * Eigen tabel `tijdstop_varianten` (gekoppeld aan ticket, run en variant).
    Na een herstart worden open varianten herladen; een gat in de koersdata
    van meer dan 300 s of een nieuwe run geeft de status *vervallen*.
  * Nieuwe sensor **Tijdstopvarianten**: waarde = aantal geëvalueerde
    uurblokken; attributen per variant (trades, netto, bruto, kosten,
    netto/trade, winst%, PF, doel%/stop%/tijdstop%, gemiddelde duur), het
    gepaarde verschil tegen 240 s per trade en per uurblok (t over blokken,
    lag-1-autocorrelatie, aantal blokken), de overeenkomst van de
    240-variant met de echte trade (zelfde sluitreden en |verschil netto| <
    0,50 USD) en een oordeel: "te weinig blokken" tot 20 uurblokken, daarna
    de beste variant met t ≥ 2 of "geen duidelijk verschil". De beslissing
    blijft bij Ruud.
  * Brokerpaneel: tabel onder de schaduwtrades.
* **Toets per uurblok (L-GS-007).** In de prestatiecijfers een extra blok
  `per_tijdblok` (attribuut op de sensor *Oordeel*): netto en bruto per blok
  van 60 minuten (uur van opening, UTC) met t over blokken en lag-1, per
  exitregime en per handelssessie, plus de waarschuwing
  `cluster_langer_dan_120_min`. Cluster-t, oordeel en live-poort blijven
  ongewijzigd.
* Tests: `tests/test_v195.py`. Vijf tests in `test_v190.py` hingen af van
  het tijdstip waarop ze draaiden (de simulator rekent vanaf "nu"); hun
  marktdata staat nu op een vast moment.
* Bijwerken via HACS en herstarten, bij voorkeur zonder open positie. Daarna
  eenmaal de browser verversen (nieuwe paneelcode).

## 1.9.4

* **Geen strategiewijziging.** Alleen de risicoremmen (daglimiet en
  vermogensvloer); signalen, ordergrootte en exits zijn niet aangeraakt.
* **Daglimiet en vermogensvloer rekenen over de startbalans.** Op de IG-demo
  staat ~10 miljoen, terwijl de ingestelde startbalans 10.000 is. Beide
  remmen rekenden over de equity van het account en gingen daardoor
  feitelijk nooit af: de daglimiet van 10% lag op ~1 miljoen verlies, de
  vloer van 50% op ~5 miljoen.
  * Daglimiet: het dagverlies telt nu als percentage van de *kleinste* van
    dagstartsaldo en startbalans. Op de demo: 10% van 10.000 = **1.000**
    verlies per dag.
  * Vermogensvloer: naast de vloer op de ingestelde balans en die op de
    opening van de run nu een **verliesvloer**: vanaf de equity bij de start
    van de run mag hooguit (100 − 50)% van de kleinste van startbalans en die
    equity verloren gaan. Op de demo: **maximaal 5.000 verlies per run**
    (vloer = opening − 5.000).
  * Op een echt account rond de startbalans verandert er niets: de strengste
    vloer wint nog steeds (bijv. startbalans 10.000, opening 7.266: vloer
    blijft 5.000). Een saldo onder de startbalans versoepelt niets.
* **Saldosprong: geen noodstop.** Staat de saldosprongbewaker aan (een
  onverklaarde sprong in het saldo, bijv. een reset van het demosaldo), dan
  leidt een vloer- of daglimietoverschrijding niet tot een noodstop met
  handmatig hervatten, maar tot een weigering van nieuwe posities
  ("saldosprong: … niet betrouwbaar te toetsen") tot de sprong verklaard is.
* Vermogensvloer-sensor toont `verliesvloer` en `max_verlies_run`; de
  toegepaste vloer kan nu ook `verliesvloer` zijn. Het brokerpaneel toont
  het dagverlies als percentage van de daglimiet (zelfde basis als de rem)
  en de vloermeter rekent over de verliesruimte van de run.
* README noemde nog versie 1.9.1; bijgewerkt.
* Tests: `test_lab_services_57` faalde wisselend onder `pytest -n auto`
  (gedeelde module-fixture over meerdere workers); die module draait nu op
  één worker (xdist `loadgroup`).

## 1.9.3

* Versieconstante bijgewerkt (1.9.2 meldde zich intern nog als 1.9.1); een
  test bewaakt nu dat manifest en constante gelijk zijn. Verder gelijk aan
  1.9.2.

## 1.9.2

* **Geen strategiewijziging.** Alleen de berekening van schaduwtrades.
* **Schaduwtrades op de echte ordergrootte.** De grootte van een schaduwtrade
  kwam uit de equity van het brokeraccount (IG-demo: ~10 miljoen) in plaats
  van het startsaldo dat een echte order gebruikt. Bij risicogestuurde
  grootte openden schaduwtrades daardoor op de maximale grootte, en waren
  resultaat en kosten tientallen keren groter dan bij een echte trade
  (bijv. +$203 en $42 kosten per trade). Nu exact dezelfde berekening als
  een echte order (papersimulatie bij paper, anders het startsaldo).
* De schaduwtrades van vóór deze versie krijgen eenmalig de status
  *vervallen* ("grootte onjuist berekend"); ze tellen niet meer mee in de
  schaduwstatistiek. De telling begint opnieuw.

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
