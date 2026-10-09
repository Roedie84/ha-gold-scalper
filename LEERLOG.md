# Leerlog Gold Scalper

Onderzoeksproject op IG-demo: edge van ruis onderscheiden. Alleen gemeten getallen; KPI's in KPI.csv.

## 07-10 23:15 · tussenronde (eerste ronde, baseline)
- Gemeten: 56 trades in 7 clusters (06-10 06:30 - 07-10 19:03 UTC). Netto −120,53 USD = bruto −18,65 − kosten 101,88 (1,82 USD/trade, 100% gemeten). PF 0,651, winst 44,6%.
- t netto over clusters −2,05; t bruto (zelf berekend) −0,24 → bruto niet van nul te onderscheiden, netto verlies komt uit de kosten (kosten/bruto-verhouding 5,5).
- Eerlijk over n: 7 clusters. Om een bruto-edge ter grootte van de kosten (14,6 USD/cluster bij sd 29,6) met t=2 te zien zijn ~17 clusters nodig; voor een netto-oordeel meer. Geen conclusie over de strategie.
- Regime: range 16 trades t −2,91 (netto −97,82), trend 40 trades t −0,29 — trades niet onafhankelijk, n te klein; alleen volgen.
- Uitvoering: slippage 3× de aanname (0,06 vs 0,02); latency p90 207 ms, max 786 ms (exits→signal).
- Meetfout gevonden: `learning/analysis.py` telt doel/stop uit de ruwe `close_reason` (na afstemming overschreven met `broker_gesloten_gecorrigeerd`, 24/56). Gevolg: "geleerd" meldt doel 14% en "ATR mogelijk overschat", terwijl de sensor Doel geraakt (op bewijs, 0% onbekend) 19,6% geeft. → L-GS-001 (zelf bouwen, meetfout; bij de dagafsluiting).
- Hypothese H-GS-1: doeltreffers liggen onder de verwachte 40% (19,6%, n=56). Pas toetsen na fix en ≥100 trades.
- Afstemming met broker: "nog_niet" (wel 24 trades gecorrigeerd via transacties).
- Geen release (tussenronde; 1.7.0 vandaag al uitgebracht en geïnstalleerd).

laatste ronde: 07-10 23:15, gemeten t/m 07-10 23:15

## 07-10 23:40 · tussenronde (handmatig gestart)
- Correctie: de vorige ronde was om 23:15, niet 23:30 (tijdstempels aangepast).
- Gebouwd: **v1.7.1** = L-GS-001 (geleerd telt doel/stop op de effectieve sluitreden; 2 nieuwe tests). Gereleased in een tussenronde omdat "geleerd" nu foute data gaf (doel 14% i.p.v. 19,6% en een onterechte ATR-notitie). Workflow groen; HACS ververst.
- Testsuite: 1707 groen, 5 overgeslagen, met de klok vast op 10:00 UTC. Zonder vaste klok falen 4 tests in `test_unconfirmed_orders.py` tijdens de dagpauze (ook op main zonder wijziging) → L-GS-002.
- Geen nieuwe trades sinds 19:03 UTC (markt in dagpauze).

laatste ronde: 07-10 23:40, gemeten t/m 07-10 23:40

## 07-10 23:45 · tussenronde
- Geen nieuwe trades (56; status markt_gesloten, dagpauze). Open posities 0. Equity 7169,85; max drawdown 1,89%.
- Nieuw vastgelegd: latency p99 252,7 ms (n=56) naast p90 207 ms.
- v1.7.1 (L-GS-001) nog niet geïnstalleerd (HA draait 1.7.0) → verificatie wacht op installatie.
- Hypotheses ongewijzigd (H-GS-1 pas toetsen na fix en ≥100 trades; bruto-edge-toets pas bij ~17 clusters, nu 7).
- Geen release.

laatste ronde: 07-10 23:45, gemeten t/m 07-10 23:44

## 08-10 03:40 · dagafsluiting 07-10
- Dag 07-10: 40 trades, 4 clusters, winst 47,5%; netto −64,41 = bruto +13,69 − kosten 78,11 (1,95/trade). t netto −1,19, t bruto +0,18 (n=4, geen conclusie).
- Totaal t/m 08-10 03:40: 61 trades, 8 clusters, netto −148,10 (bruto −39,41, kosten 108,70), PF 0,62. t netto −2,51, t bruto −0,50. Voor een bruto-edge ter grootte van de kosten (13,6/cluster, sd 28,1) zijn ~18 clusters nodig → nog 10. Geen oordeel over de strategie.
- Nacht 03:00-03:35: 5 trades (1 winst), netto −27,58, alle in regime range (range nu n=21, t −2,98; trend n=40, t −0,29). Trades niet onafhankelijk → alleen volgen (H-GS-3).
- Waarschuwing "Slechts 1 transactie(s) over 24 uur … datumbereik komt niet aan": geen bug; venster (−6 u/+12 u) wordt toegepast, telling daalde 2→1 toen het venster voorbij 07-10 schoof. Tekst klopt niet en logt elke ~80 s → L-GS-003 (cosmetisch).
- 1 trade (03:35) op geschatte uitstapprijs (−11,23); correctielus zoekt hem tot 2 dagen → H-GS-2: binnen enkele uren gecorrigeerd. Afstemming 56/56; 5 nog niet bij de broker.
- Latency-basis van de sensor is nu 1000 cycli (p50 176, p99 514, max 4128 ms) → niet vergelijkbaar met p99 253 ms (n=56 trades); nieuwe baseline.
- L-GS-001 (1.7.1) nog niet geïnstalleerd → geleerd zegt nog doel 14,8% tegen 19,7% op bewijs. Testsuite main 1707 groen om 01:51 UTC (L-GS-002 viel niet om buiten de pauze).
- Geen release (1.7.1 wacht op installatie; niets acuut).

laatste ronde: 08-10 04:40, gemeten t/m 08-10 03:45

## 08-10 07:40 · tussenronde
- 1.7.1 geïnstalleerd (herstart 07:03). **L-GS-001 geverifieerd:** geleerd `target_hit_rate` 0,185 = sensor Doel geraakt 18,5% (12/65); de ATR-notitie rust nu op de juiste telling (18% tegen 40% verwacht).
- Sinds 03:45: 4 trades (netto −31,72). Totaal 65 trades, 9 clusters: netto −179,82 = bruto −65,98 − kosten 113,84 (1,75/trade). PF 0,575, winst 41,5%.
- t netto −2,92, t bruto −0,80 (n=9). Voor een bruto-edge ter grootte van de kosten (12,65/cluster, sd 27,45) ~19 clusters nodig → nog 10. Geen oordeel over de strategie.
- H-GS-3 (regime): range n=22, t −3,22, winst 27%; trend n=43, t −0,55, winst 49%. Trades in een cluster niet onafhankelijk; per regime clusters nog niet geteld → volgen, geen conclusie.
- H-GS-2: geschatte uitstap van 03:35 — alle 65 sluitredenen nu bekend/bewezen; kosten 63 gemeten, 2 berekend (nieuwste, nog niet bij de broker).
- Geleerd: 36/38 verliezen "verkeerde richting", 2 "stop te krap" (fixable 5%).
- Latency p99 393,5 ms (1000 cycli; was 514,5). Drawdown 2,43%.
- Geen release.


## 08-10 · chatsessie
- **L-GS-003 gebouwd 1.7.2 (08-10, chatsessie):** transactiewaarschuwing (22× tussen 03:15-04:03) vergelijkt nu met eigen trades die >6 u dicht zijn; 1× per uur WARNING, anders DEBUG. Alleen logging. Release v1.7.2 groen, HACS ververst. Meten na installatie: 0 van deze waarschuwingen in een nacht zonder echte afwijking.
- **L-GS-004 gebouwd 1.7.3 (08-10, chatsessie):** 4 geschatte uitstappen vandaag kwamen doordat alleen het (achterlopende) transactieoverzicht werd gevraagd. Nu eerst het activiteitenoverzicht (+ /confirms), anders max. 4 herkansingen binnen 4 min; correctie/afstemming zetten bij een voorlopige trade meteen sluitreden en gemeten kosten. Alleen boekhouding. Release v1.7.3 groen, HACS ververst. Meten na installatie: 0× WARNING "geschatte uitstapprijs" per dag, Sluitreden onbekend/kosten berekend alleen voor trades < 5 min oud.
laatste ronde: 08-10 07:40, gemeten t/m 08-10 07:43

## 08-10 11:00 · varianten-analyse (onderzoek, niets aan de strategie veranderd)
Vraag Ruud: kan de strategie meer opleveren? Alleen gelezen; geen knoppen, instellingen of code op main.
- **Data:** tradedatabase/barsarchief zijn binair (SQLite) en niet leesbaar via de bestandseditor; daarom uit de HA-recorder: koers (mid, elke 10 s, 19 328 punten 06-10 00:00 – 08-10 09:00 UTC), open posities (zijde, units, instap, stop + verplaatsingen), signaal (regime). 66 van 68 trades teruggevonden (2 in cluster 6 vielen binnen één pollingcyclus), 10 clusters (herinstap < 10 min), regime 44 trend / 22 range = geleerd. Geen IG-aanroepen.
- **Replay:** zelfde exitlogica als live (`exits.py`: doel/stop bij de broker, break-even 0,8×ATR, trailing 1,5/1,2), halve spread 0,40 (gemeten instap: fill − mid mediaan 0,40), stopslippage 0,06. Controle: 53/66 uitstaptijden binnen 60 s van live, zelfde uitkomsten; sim netto −253 (−3,83/trade) tegen live −200 (−2,95): de replay is ~0,9/trade pessimistischer, vergelijkingen zijn daarom gepaard (variant − basis op dezelfde trades).
- **Bevinding (bug):** tijdstops (240 s / 900 s) vuren op IG nooit: `VenuePosition` heeft geen `open_time` → leeftijd 0. Live duur gem. 1408 s, max 5272 s. → **L-GS-005 (open, Ruud beslist)**.
- **Resultaten** (netto in USD incl. spread en slippage; t_cl = cluster-t op netto per cluster; IS = clusters 1-5, OOS = 6-10; per trade):

| variant | n | clusters | netto | netto/tr | PF | t_cl | IS n · /tr | OOS n · /tr |
|---|---|---|---|---|---|---|---|---|
| basis (doel 1,5 ATR) | 66 | 10 | −253 | −3,83 | 0,47 | −3,81 | 33 · −3,63 | 33 · −4,04 |
| a. doel 2,25 ATR (×1,5) | 66 | 10 | −214 | −3,24 | 0,56 | −2,29 | 33 · −3,44 | 33 · −3,04 |
| a. doel 3,0 ATR (×2) | 66 | 10 | −180 | −2,73 | 0,63 | −1,75 | 33 · −2,42 | 33 · −3,05 |
| b. geen instap in range | 44 | 6 | −95 | −2,16 | 0,67 | −2,22 | 17 · −0,42 | 27 · −3,25 |
| c1. 1 min bevestiging | 32 | 9 | −22 | −0,67 | 0,88 | −0,24 | 13 · −4,29 | 19 · +1,80 |
| c2. 2 min bevestiging | 18 | 6 | −18 | −1,02 | 0,85 | −0,40 | 7 · −3,65 | 11 · +0,65 |
| c3. +0,25 ATR binnen 3 min | 29 | 7 | −36 | −1,23 | 0,81 | −0,54 | 14 · −3,74 | 15 · +1,10 |
| b + c3 | 21 | 4 | +17 | +0,80 | 1,14 | +0,43 | 6 · +0,04 | 15 · +1,10 |
| doel 3,0 + c3 | 29 | 7 | +75 | +2,58 | 1,40 | +0,58 | 14 · +2,27 | 15 · +2,86 |
| doel 3,0 + c2 (beste IS) | 18 | 6 | +67 | +3,71 | 1,56 | +0,60 | 7 · +6,38 | 11 · +2,01 |
| tijdstops werkend (L-GS-005) | 66 | 10 | −88 | −1,34 | 0,57 | −1,35 | 33 · −2,18 | 33 · −0,49 |
| tijdstops + c1 | 32 | 9 | +33 | +1,04 | 1,46 | +0,51 | 13 · −1,61 | 19 · +2,85 |

- **Toets en multiple testing:** 30 varianten doorgerekend (3 doelen × regime aan/uit × 4 instapregels + 6 met tijdstops). Bonferroni: α 0,05/30 → |t| ≈ 3,6 nodig. **Geen variant heeft een netto-t boven 0,75**; de beste positieve rijen zijn de beste van 30 ruisuitkomsten op 3–7 clusters. Filters (b, c) lijken in de gepaarde vergelijking sterk (t 2–5), maar dat is grotendeels mechanisch: trades weglaten uit een verliesgevende basis verbetert het totaal altijd. Selectietoets (zelfde aantal willekeurige trades weglaten): c1 p 0,008, c3 p 0,005, b p 0,04 — op trade-niveau, trades in een cluster zijn niet onafhankelijk, dus te optimistisch.
- **Tijd van de dag** (basis, netto/trade): Azië 00-07 −5,90 (24 tr, 6 cl), Londen 07-12 −2,48 (16, 5), NY 12-17 −1,49 (20, 2), laat 17-21 −7,00 (6, 2). Te weinig clusters per blok; geen filter getoetst.
- **Hoeveel extra clusters:** tijdstops (gepaard verschil +16,5/cluster, sd 24,2): ~9 clusters voor t=2, ~28 voor t=3,6. Instapbevestiging c1: ~6 resp. ~18 (maar mechanisch effect, zie boven). Voor een **netto positief** resultaat met t=2: tijdstops+c1 ~156 clusters, doel 3,0+c3 ~120 — praktisch onbereikbaar op dit tempo (≈4 clusters/dag).
- **Oordeel:** de strategie winstgevend maken is met deze data niet aan te tonen; geen parameter aanpassen op grond van deze tabel. Wel duidelijk: (1) tijdstops werken niet zoals ontworpen (bug) — herstellen verkleint het verlies waarschijnlijk (IS én OOS beter) → L-GS-005; (2) instapbevestiging en regimefilter worden hypotheses, niet ingebouwd: **H-GS-4** "1 min bevestiging in signaalrichting verbetert netto/trade" en **H-GS-5** "doel ×2 met bevestiging". Beide schaduw-meten met de replay op nieuwe clusters (geen codewijziging), oordeel pas na ≥ 20 nieuwe clusters, met correctie voor 30 geteste varianten. H-GS-3 (regime) blijft volgen: OOS hield het voordeel niet vast (−3,25/trade).
- Reproduceren: `analyse/2026-10-08-varianten/` (trades.json, price.json.gz uitpakken, `python3 grid.py`, `extra.py`, `need.py`).

laatste ronde: 08-10 11:00, gemeten t/m 08-10 09:00 UTC

## 08-10 11:40 (chatsessie)
- L-GS-005 akkoord (Ruud 11:19), gebouwd en uitgebracht als 1.7.4. Meten: sluitreden tijdstop/maximale duur verschijnt; langste duur ≤ 910 s; netto/trade per cluster tegen baseline −2,95 (68 trades, 10 clusters). Beslissen na 10 nieuwe clusters.
- Positiegrootte bewust niet verhoogd (demosaldo 10 mln): verandert de vingerafdruk en vervuilt de meting van L-GS-005.

## 08-10 11:45 · tussenronde
- Geïnstalleerd: 1.7.3 (herstart 10:55; bevat 1.7.2). 1.7.4 (L-GS-005, tijdstops) stond in HACS nog niet als update → `update_information` gedaan: HACS toont nu 1.7.3 → 1.7.4 (wacht op installatie).
- Sinds 07:43: 3 trades (08:42 −11,09; 09:21 −10,82 op geschatte uitstap; 10:04 +1,73) → netto −20,45, bruto −16,30, kosten 4,14. Sinds 10:04 geen trade (signaal flat, status "signaal te zwak"). Alle 3 zitten al in de varianten-analyse van 11:00 (t/m 09:00 UTC).
- Totaal 68 trades, 10 clusters: netto −200,27 = bruto −82,29 − kosten 117,98 (1,73/trade); PF 0,551; winst 41,2%; t netto −3,28 (10 clusters); max drawdown 2,76%. Bruto-t niet opnieuw berekend (geen nieuw cluster sinds 11:00).
- **L-GS-004:** de geschatte trade van 09:21 is bij de start van 10:55 afgestemd (sluitreden onbekend 0/68, `broker_gesloten_geschat` → `gecorrigeerd`). Sinds 1.7.3 nog geen trade → 0× "geschatte uitstapprijs" zegt nog niets. Kosten: 67 gemeten, 1 berekend (trade 10:04, broker-sluiting; berekend tot de afstemming is zo ontworpen) → meetcriterium "berekend alleen < 5 min oud" in de dagafsluiting toetsen.
- **L-GS-003:** sinds 1.7.2/1.7.3 0× de transactiewaarschuwing (22× in de nacht ervoor); de nacht is de echte toets.
- Latency p99 405,9 ms (n=295 cycli sinds 10:55; p50 174,9).
- Opgeruimd: 185 per ongeluk gecommitte `__pycache__`-bestanden (commit 96dea9c) van de leerlog-branch gehaald + `.gitignore`.
- H-GS-4/5 (instapbevestiging, doel ×2): geen nieuwe clusters → niets te schaduwmeten. H-GS-3 (regime) volgen.
- Geen release.

laatste ronde: 08-10 11:45, gemeten t/m 08-10 11:44

## 08-10 15:40 · tussenronde
- Geïnstalleerd: 1.7.6 (1.7.4 L-GS-005, 1.7.5 herstartbestendigheid, 1.7.6 `exit_regime` per trade + bewaarde latencysteekproef; chatsessie). HA-herstarts sinds 11:45: 6. Run gemarkeerd als "methodologisch gemengd" (14:19) → cijfers per regime apart.
- Sinds 11:44: 7 trades in 2 clusters (12:35-13:04: −11,12 −1,81 −2,61 +16,83 −2,68 −10,71; 14:45 +14,67; +0,23 afstemming 14:01) → netto +2,80, bruto +12,79, kosten 9,99 (1,43/trade, 100% gemeten). Totaal 75 trades: netto −197,47, PF 0,584, winst 40,0%, t −2,82, max DD 2,76%.
- **L-GS-005 eerste meetpunt gehaald:** sluitredenen tijdstop 3× (na 240, 241, 460 s) en maximale duur 1× (900 s, bij +9,17 USD/oz); gem. duur 1408 → 1316 s. Regime `tijdstop` 7 trades/2 clusters +0,40/trade (PF 1,10, t 0,11) tegen `zonder_tijdstop` 68/10 −2,95 (t −3,28). **Geen conclusie:** 2 clusters; gepaarde toets na ≥10 nieuwe clusters (plan in VOORSTELLEN).
- Opvallend: tijdstop van 460 s past bij de regel (na 240 s eerst buiten, later weer binnen 0,3×ATR); de 900-s-limiet sloot een winnende positie (+9,17/oz). Beide horen bij het ontwerp; volgen of de max-duur vaker winnaars afkapt dan verliezers.
- **Latency:** p99 1628 ms (n=477, "indicatief"; p50 262, max 4,6 s; `start->quote` max 3,4 s) tegen 406 ms om 11:45 (n=295). 1.7.6 bewaart de steekproef over herstarts (n loopt door over 5 herstarts) → eerste meetpunt gehaald. **H-GS-6 (nieuw):** de staart komt van de herstarts/drukte rond 14:19-15:39 (6 herstarts), niet van IG. Toets: p99 in de nacht zonder herstarts (dagafsluiting).
- **L-GS-003/004:** 0× transactiewaarschuwing en 0× "geschatte uitstapprijs" in het logvenster 13:48-15:40; sluitreden onbekend 0, kosten 100% gemeten.
- H-GS-4/5 (instapbevestiging/doel ×2): 2 nieuwe clusters, nog niet schaduwgemeten (drempel 20 clusters). H-GS-3 volgen.
- Geen release (tussenronde, niets acuut).

laatste ronde: 08-10 15:40, gemeten t/m 08-10 15:44

## 08-10 19:40 · tussenronde
- Geïnstalleerd: 1.7.6 (herstarts 16:31, 17:41, 18:36; lifecycle 18:36 reconciling → running). Run 100, demo.
- Sinds 15:44: **26 trades in 2 clusters** (13: 17:15-18:45, 22 trades, netto −2,69, bruto +30,96; 14: 19:15-19:33, 4 trades, netto +4,27, bruto +8,10) → netto +1,58, bruto +39,06, kosten 37,48 (1,44/trade). Totaal 101 trades / 14 clusters: netto −195,88 = bruto −30,43 − kosten 165,45; PF 0,631; winst 36,6%; t −2,665 (clusters); max DD 2,76%.
- **L-GS-005 (tijdstops):** regime `tijdstop` 33 trades / 4 clusters: netto +4,39 (+0,13/trade, PF 1,05, t 0,20), bruto +51,87 (+1,57/trade, t bruto 1,77 over 4 clusters) tegen `zonder_tijdstop` 68/10 netto −2,95/trade, bruto −1,21/trade. 24 tijdexits (23 tijdstop 240-567 s, 1 max-duur). **Geen conclusie:** 4 clusters; met de huidige spreiding (sd 11,2 USD/cluster, gem. +1,1) zijn ~400 clusters nodig voor netto t=2 — de netto-toets is praktisch onbereikbaar; de geplande gepaarde toets (≥10 clusters) blijft het beslismoment.
- **H-GS-7 (nieuw):** tijdstops verhogen het tempo (cluster 13: 22 trades in 91 min; 8,3 trades/cluster tegen 6,8) en daarmee de kosten; het bruto voordeel (+1,57/trade) wordt grotendeels door kosten (1,44/trade) opgegeten. Toets bij ≥10 clusters: bruto/trade en kosten/cluster per regime.
- **L-GS-004:** sluitreden onbekend 1/101 (was 0/75) — waarschijnlijk een trade die nog in de afstemming hangt (7 trades "nog niet in zijn overzicht", loopt uren achter; afstemming in_orde, 94/94 kloppend). Kosten 98 gemeten / 3 berekend (recente trades, zo ontworpen). Toetsen in de dagafsluiting: moet naar 0 na afstemming.
- **H-GS-6 (latency):** p99 976 ms over n=1890 (niet meer indicatief; p50 239, max 4604 uit de herstartdrukte van 14-15 u). start→quote p99 357, exits→signal p99 318. Nachttoets zonder herstarts blijft staan.
- Uitvoering: slippage gemeten 0,07 tegen 0,02 aangenomen (3,5×); doel geraakt 15,8% tegen 40% verwacht. Sessies: Londen −0,17/trade (n 42), New York −2,06 (38), Azië −5,25 (21) — geen sessie t > 0,1 → geen filter.
- H-GS-4/5 (bevestiging, doel ×2): 4 nieuwe clusters sinds de varianten-analyse (drempel 20) → nog niet schaduwgemeten. H-GS-3 (regime): range −131,8 (55 tr, t −2,03), trend −63,8 (46, t −0,79).
- Geen release (tussenronde, niets acuut). Geen knoppen, geen instellingen.

laatste ronde: 08-10 19:40, gemeten t/m 08-10 19:44

## 08-10 23:40 · tussenronde
- Geïnstalleerd: 1.7.9 (1.7.7 saldosprong, 1.7.8 geen noodstop na eigen sluiting/race met IG, 1.7.9 sluiting pas boeken na bevestiging IG; chatsessie). Herstart 22:02 (reconciling → running). Markt sinds 23:00 dicht (dagpauze).
- Sinds 19:44: **22 trades in 1 cluster** (15: 21:15-22:50, netto −21,17, bruto +2,38, kosten 23,55 = 1,07/trade). Totaal 123 trades / 15 clusters: netto −217,23 = bruto −28,23 − kosten 189,00; PF 0,613; winst 34,2%; t −2,95 (clusters, nagerekend); max DD 2,76%.
- **Noodstop 21:20** ("positie open bij de broker maar niet in de database") → 12 signalen geweigerd; hervat 21:22, "alles sluiten" 21:58 (1 sluitreden "handmatig"). Dit is de race die 1.7.8/1.7.9 oplossen → na 1.7.9 tellen: 0× deze noodstop.
- **L-GS-005 (tijdstops):** regime `tijdstop` nu 55 trades / 5 clusters: netto −16,96 (−0,31/trade, t −0,55, PF 0,85), bruto +54,07 (+0,98/trade, t bruto 1,79) tegen 19:40 +4,39 netto. Geen conclusie (5 clusters; bij gem. −3,4 en sd 13,9 USD/cluster zou pas na ~67 clusters iets significant worden). Beslismoment blijft ≥10 clusters gepaard.
- **H-GS-7 sterker:** cluster 15 weer 22 trades in 95 min; in het tijdstopregime bruto 0,98/trade tegen kosten 1,29/trade → het bruto voordeel wordt volledig door het hogere tempo opgegeten.
- **L-GS-004:** sluitreden onbekend 3/123 (was 1/101); afstemming in_orde (107/107 kloppend, 15 nog niet bij IG verwerkt). Kosten 120 gemeten / 3 berekend. Toets in de dagafsluiting: onbekend moet na afstemming dalen.
- **H-GS-6 (latency):** p99 1067 ms (n=2000), p50 247, max 7,6 s (candles→exits max 6,2 s) — staart rond de noodstop/herstart. Nachttoets blijft staan.
- Opgemerkt: 22:59:59 waarschuwing "broker meldt gesloten, rooster open" — 1 s vóór de dagpauze van 23:00 (klokrand; `closures` uur 22: 1/350). Eenmalig, geen voorstel.
- Geen release (tussenronde, niets acuut). Geen knoppen, geen instellingen.

laatste ronde: 08-10 23:40, gemeten t/m 08-10 23:44

## 09-10 03:40 · dagafsluiting 08-10
- Dag 08-10 (lokaal, clusters 8-15): 67 trades, netto −95,69 = bruto −8,58 − kosten 87,11 (1,30/trade); t netto −2,01, t bruto −0,15 (8 clusters, geen conclusie). Noodstop 21:20 (race, vóór 1.7.9).
- Na middernacht cluster 16: 39 trades 00:01-03:41 (220 min), netto +15,21, bruto +76,40, kosten 61,19. Totaal 162 trades / 16 clusters: netto −201,00 = bruto +49,19 − kosten 250,19; PF 0,677; winst 38,9%; t −2,54 (bruto +0,41).
- **L-GS-005 (tijdstops):** regime `tijdstop` 94 trades / 6 clusters: netto −0,73 (−0,01/trade, t −0,02), bruto +131,48 (+1,40/trade, t bruto 1,84) tegen `zonder_tijdstop` −2,95/trade (t −3,28). Bij gem./sd van nu is t bruto ≥ 2 na ~7 clusters; netto is ~0 → netto-toets onbereikbaar. Beslismoment blijft de gepaarde toets bij ≥ 10 clusters in dit regime.
- **H-GS-7 bevestigd en uitgebreid:** bruto 1,40/trade ≈ kosten 1,41/trade; trades per cluster 15,7 (tijdstop) tegen 6,8. Tijdstops maken ook de clusters langer (cluster 16: 220 min, herinstap steeds < 10 min) → clusters groeien trager en het beslismoment schuift op. Toets (volgende dagafsluiting, uit de recorder): bruto van de eerste instap per cluster tegen de herinstappen na een tijdstop.
- **H-GS-6 verworpen:** p99 1067 ms over 2000 metingen uit ~22:10-03:45, een venster zonder herstart (laatste 22:02). De staart komt dus niet van herstarts. Uitsplitsing p99: signal→bookkeeping 409, candles→exits 334, exits→signal 319, start→quote (IG) 217 ms → de staart zit vooral in eigen verwerking (H-GS-8, nieuw). Opvallend: p99 exact gelijk aan 23:40 (1066,704) terwijl p50 en max veranderden — volgende ronde controleren of hij beweegt.
- **L-GS-004:** sluitreden onbekend 3/162 (1,9%), kosten gemeten 96,3%. Bij 1.7.9-herstart 22:02: 1 trade in database open maar bij IG al dicht → afgestemd.
- **Rooster-klokrand (gebouwd 1.7.10, L-GS-006; 1831 tests groen, workflow groen, HACS ververst):** elke nacht 2× WARNING "broker gesloten, rooster open … feestdag" om 22:59:59 en 23:59:59. Oorzaak: pauze tot en met 23:59:59 vergeleken mét microseconden (23:59:59,06 = open) en een klokverschil van < 1 s op de sluiting. Handelen veranderde niet (gesloten wint).
- L-GS-002 bleek al gebouwd in 1.7.7 (klok vast op handelsmoment); verificatie tijdens de dagpauze in de ronde van 23:40.
- H-GS-3 (regime) en H-GS-4/5 (schaduwtoetsen, drempel 20 clusters) volgen.

laatste ronde: 09-10 03:40, gemeten t/m 09-10 03:45
