# Leerlog Gold Scalper

Onderzoeksproject op IG-demo: edge van ruis onderscheiden. Alleen gemeten getallen; KPI's in KPI.csv.

## 07-10 · samenvatting dag (3 tussenronden 23:15-23:45, eerste baseline)
- Baseline 06/07-10: 56 trades / 7 clusters, netto −120,53 USD (bruto −18,65, kosten 101,88 = 1,82/trade), PF 0,651, winst 44,6 %; t netto −2,05, t bruto −0,24 → verlies uit de kosten; ~17 clusters nodig voor een bruto-toets.
- Slippage 3× de aanname (0,06 vs 0,02); latency p90 207 ms, p99 253 ms.
- Meetfout "geleerd" telde doel/stop op ruwe sluitreden → L-GS-001 gebouwd v1.7.1 (tussenronde, foute data). Klokafhankelijke tests → L-GS-002. H-GS-1 (doeltreffers 19,6 % < 40 %) gestart.

## 08-10 · samenvatting dag (9 rondes; ingekort na 14 dagen)
- Nacht 03:00-03:35: 5 trades (1 winst), netto −27,58, alle in regime range (range nu n=21, t −2,98; trend n=40, t −0,29). Trades niet onafhankelijk → alleen volgen (H-GS-3).
- Waarschuwing "Slechts 1 transactie(s) over 24 uur … datumbereik komt niet aan": geen bug; venster (−6 u/+12 u) wordt toegepast, telling daalde 2→1 toen het venster voorbij 07-10 schoof. Tekst klopt niet en logt elke ~80 s → L…
- 1 trade (03:35) op geschatte uitstapprijs (−11,23); correctielus zoekt hem tot 2 dagen → H-GS-2: binnen enkele uren gecorrigeerd. Afstemming 56/56; 5 nog niet bij de broker.
- Latency-basis van de sensor is nu 1000 cycli (p50 176, p99 514, max 4128 ms) → niet vergelijkbaar met p99 253 ms (n=56 trades); nieuwe baseline.
- L-GS-001 (1.7.1) nog niet geïnstalleerd → geleerd zegt nog doel 14,8% tegen 19,7% op bewijs. Testsuite main 1707 groen om 01:51 UTC (L-GS-002 viel niet om buiten de pauze).
- Geen release (1.7.1 wacht op installatie; niets acuut).
- 1.7.1 geïnstalleerd (herstart 07:03). L-GS-001 geverifieerd: geleerd `target_hit_rate` 0,185 = sensor Doel geraakt 18,5% (12/65); de ATR-notitie rust nu op de juiste telling (18% tegen 40% verwacht).
- H-GS-3 (regime): range n=22, t −3,22, winst 27%; trend n=43, t −0,55, winst 49%. Trades in een cluster niet onafhankelijk; per regime clusters nog niet geteld → volgen, geen conclusie.

## 09-10 · samenvatting dag (6 rondes; ingekort na 14 dagen)
- L-GS-005 (tijdstops): regime `tijdstop` 94 trades / 6 clusters: netto −0,73 (−0,01/trade, t −0,02), bruto +131,48 (+1,40/trade, t bruto 1,84) tegen `zonder_tijdstop` −2,95/trade (t −3,28). Bij gem./sd van nu is t bruto ≥ 2 na…
- H-GS-7 bevestigd en uitgebreid: bruto 1,40/trade ≈ kosten 1,41/trade; trades per cluster 15,7 (tijdstop) tegen 6,8. Tijdstops maken ook de clusters langer (cluster 16: 220 min, herinstap steeds < 10 min) → clusters groeien tr…
- H-GS-6 verworpen: p99 1067 ms over 2000 metingen uit ~22:10-03:45, een venster zonder herstart (laatste 22:02). De staart komt dus niet van herstarts. Uitsplitsing p99: signal→bookkeeping 409, candles→exits 334, exits→signal…
- L-GS-004: sluitreden onbekend 3/162 (1,9%), kosten gemeten 96,3%. Bij 1.7.9-herstart 22:02: 1 trade in database open maar bij IG al dicht → afgestemd.
- Rooster-klokrand (gebouwd 1.7.10, L-GS-006; 1831 tests groen, workflow groen, HACS ververst): elke nacht 2× WARNING "broker gesloten, rooster open … feestdag" om 22:59:59 en 23:59:59. Oorzaak: pauze tot en met 23:59:59 vergel…
- L-GS-002 bleek al gebouwd in 1.7.7 (klok vast op handelsmoment); verificatie tijdens de dagpauze in de ronde van 23:40.
- H-GS-3 (regime) en H-GS-4/5 (schaduwtoetsen, drempel 20 clusters) volgen.
- Clusterteller staat stil: cluster 16 loopt sinds 22:01 UTC door — 87 trades in 461 min (41% van alle trades), netto +0,63, bruto +132,50. Met tijdstops volgt de herinstap steeds < 10 min, dus komt er geen nieuw cluster bij. G…

## 10-10 · samenvatting dag (6 rondes; ingekort na 14 dagen)
- Weekend, demo, geen knoppen. Dag 09-10: 180 trades, netto −126,88 (bruto +137,78, kosten 264,66) → H-GS-7 (bruto < kosten). Run 101: 64 trades / 6 clusters, PF 0,44, t −2,34; 7 van ~20 uurblokken → geen conclusie.
- L-GS-008: 240-s-tijdstop 93,3 % gelijk aan de echte trade; langere tijdstops slechter (2 blokken, geen toets).
- Acuut gebouwd 1.10.1 (L-GS-009): `max_drawdown` 99,9 % door de startbalans als equitypunt bij een mislukte opvraging → 0,0 % geverifieerd. 1.10.0: sluitreden onbekend 3,1 → 0,0 %, afstemming bewaard over herstarts.
- Gevonden: time-out bij de positie-voorcheck gaf "Unexpected error" → L-GS-010 (gepland).
- Meetbaarheid: trade-niveau niet in diagnostics; drawdown in % zegt weinig op ~10 mln demo-equity.

## 11-10 · samenvatting dag (6 rondes; ingekort na 14 dagen)
- Zondag, markt dicht; demo, handel aan, geen knoppen. Recorder-purge 03:00 sloot o.a. latency p99, status en evaluaties uit → van die sensoren alleen de actuele stand meetbaar.
- Handelsweek 06..09-10: 303 trades, netto −343,09 = bruto +110,57 − kosten 453,66 (per trade −1,13 / +0,37 / 1,50; kosten 4,1× bruto); run 100 t_cluster −3,28 (16), run 101 −2,34 (6). Netto-verlies aangetoond, bruto-edge niet (~73 blokken nodig).
- ~40 HA-herstarts: afstemming `in_orde`, drawdown 0,0 %, sluitreden onbekend 0,0 % → 1.10.0/1.10.1 houden. 0 Gold Scalper-fouten; latency p99 253-830 ms (gesloten markt + herstarts).
- L-GS-010 (1.10.2, voorcheck-time-out) eerst als patch (push geweigerd), gereleased 21:00, actief 23:31. H-GS-7 (bruto < kosten) houdt; H-GS-9 gesloten; H-GS-10 toets 16-10.

## 12-10 · samenvatting dag (6 rondes; ingekort na 14 dagen)
- Zondag 11-10 0 trades. Run 101 (scalp) slot: 128 trades, netto −196,66 (−1,54/trade), t_cluster −3,34 → H-GS-7 (bruto < kosten) bevestigd en gesloten met de strategie.
- Storing 12-10 02:21-03:21 (TypeError in sort, 360×) → L-GS-012; meetfout sluittijd verdwenen positie (L-GS-011). Piramide stond aan → L-GS-016.
- Strategiewissels (chatsessie, Ruud): 2.0.0 daghandel, 2.1.0 combinatie (run 105: 35 scalptrades, netto −20,55, 0 daghandel), 2.2.x bijkopen vastgelegd, 2.3.0 export, 2.4.0/2.4.1 veldproef 45 opzetten (run 107).
- Columbus Day: broker 19:00 dicht binnen het rooster. Latency p99 0,66-0,90 s (herstarts). Hypotheses: H-GS-10 (vrijdagsluiting), H-GS-11 (daghandelkosten).

## 21-10 19:40 · dagafsluiting (inhaalronde na gat 13-10 20:15 → 21-10)
- Gat 13..20-10: geen leerrondes. Intussen 2.6.2 → **2.19.0** (actief; o.a. Pepperstone 14-10, Bitvavo-mand papier 20-10, daghandel op kwartierbars 21-10). IG-runhistorie vóór 19-10 niet meer in de sensoren (alleen lopende run) → 13..18-10 IG niet per dag meetbaar; 12-10 uit `analyse/` overgenomen in KPI.csv.
- **IG** (run sinds 19-10 09:00 UTC, veldproef 15m/30m): 160 trades / 10 clusters, netto −101 (bruto +926, kosten 1.027 = 6,42/trade), PF 0,97, t_cluster −0,13. Per dag +134 / −446 / +215. Uurblokken t_bruto 1,12 (44) → ~140 blokken nodig voor bruto t=2; netto geen edge.
- **Pepperstone** (sinds 14-10): 1.571 trades / 6 clusters, netto −8.739, bruto −2.477 (al negatief vóór kosten), kosten 6.262; t_netto −2,09 over 111 uurblokken → aantoonbaar verliesgevend, niet alleen kosten. Sluitreden onbekend 26,1 %.
- **Meetfout/bug (L-GS-020):** IG-equity 0/0 om 13:14:07 → NOODSTOP 13:15, hervat 13:42 (knop, niet door deze ronde); drawdown IG staat sindsdien op 100 %. Bouwen geweigerd door de toestemmingscontrole van deze sessie → gepland, geen release.
- **Latency** verslechterd: p99 IG 35,2 s, Pepperstone 15,1 s (exitbeheer `candles->exits` domineert); Pepperstone dagmiddel 5,0 s → 9,3 (20-10) → 13,9 s (21-10).
- Hypotheses: **H-GS-11** daghandelkosten ≈ 20 % van de beweging (1 daghandeltrade sinds 2.19.0 → niet meetbaar); **H-GS-12** latency stijgt met de Bitvavo-mand (20 lussen sinds 20-10; samenhang in de tijd, oorzaak niet bewezen); **H-GS-13** IG New York-sessie positief (t_netto 2,23 / 16 blokken; 3 sessies vergeleken = meervoudig toetsen, eerst ≥ 30 nieuwe blokken). H-GS-10 vervallen (vrijdagtoets 16-10 niet gemeten).
- Niet meetbaar: slippage verwacht/gerealiseerd per trade (geen attribuut), IG-dagen vóór 19-10, IG-latencystatistiek (geen long-term statistics).
- Geen release; geen knoppen, geen instellingen gewijzigd.

laatste ronde: 21-10 19:40, gemeten t/m 21-10 19:45

## 21-10 23:40 · tussenronde
- Actief **2.19.1** (2.19.2 gereleased 22:15, niet geïnstalleerd; HACS ververst). Herstart 20:58; daarna afstemming "cannot commit - no transaction is active" (20:59) = wat 2.19.2 oplost. Markt goud dicht 23:00-00:00.
- **L-GS-020 geverifieerd:** IG *Max. drawdown* 0,01 % (was 100 %), 0 noodstops.
- **IG** run: 175 trades / 11 clusters, netto −32 (bruto +1.077, kosten 1.110 = 6,34/trade), PF 0,99, t_cluster −0,04. Sinds 19:45: 15 trades, netto +69. Uurblokken 49, t_bruto 1,29 (was 1,12/44).
- **Pepperstone:** 1.585 trades / 8 clusters, netto −9.096, bruto −2.859; t_netto −2,17 over 114 blokken (was −2,09/111). Sinds 19:45: 14 trades, −357.
- **H-GS-13** (IG New York positief): t_netto 2,35 / 21 blokken (5 nieuw, eis ≥ 30 nieuwe). Tegenproef op Pepperstone (zelfde goud, ander opzetmengsel): NY t_netto −0,28 / t_bruto 0,41 over 44 blokken → repliceert niet; wijst eerder op toeval of opzetmix dan op een sessie-effect. Blijft open, geen voorstel.
- Latency p99: IG 34,7 s (max 104,6 s), Pepperstone 14,6 s, Bitvavo 6,7 s; bij IG en Pepperstone domineert `candles->exits`, bij Bitvavo niet (0,6 s) → H-GS-12 (mand vertraagt de goudlussen) blijft plausibel.
- Logruis: na elke herstart worden alle eerder uitgezette veldproefopzetten opnieuw als "uitgezet" gemeld (21 WARNINGs om 20:58-21:56); de lijst start leeg (`_vp_uitgezet`). Meetbaarheid: "nieuw" is niet nieuw → meenemen bij de volgende diagnose-release (zelf bouwen).
- Bitvavo-papier: 11× "Openen geweigerd (papermarge)" (nodig 1.6-2,0k, vrij ~0,7k), 0 trades.
- Geen release; geen knoppen, geen instellingen.

laatste ronde: 21-10 23:40, gemeten t/m 21-10 23:43

## 22-10 03:40 · dagafsluiting 21-10
- Actief **2.19.1**; 2.19.2 staat klaar, niet geïnstalleerd → geen release (niet stapelen). Demo, 0 noodstops, IG drawdown 0,01 %. Geen knoppen, geen instellingen.
- **Dag 21-10:** IG 72 trades netto **+281** (bruto +658, kosten 377 = 5,24/trade); Pepperstone 187 trades netto **−2.413** (bruto −1.902, kosten 511). Eén dag, geen conclusie.
- **IG run** (sinds 19-10): 182 trades / 12 clusters, netto −205 (bruto +960, kosten 1.165), PF 0,94, t_cluster −0,25. Uurblokken 52: t_bruto 1,13, t_netto −0,24 → bruto mogelijk iets, netto niets. Bij bruto ~18 USD/blok en deze spreiding zijn ~165 blokken nodig voor t_bruto 2; netto geen edge in zicht zolang kosten ≈ bruto.
- **Pepperstone run:** 1.606 trades, netto −9.175, bruto −2.857; t_netto −2,18 over 118 blokken → blijft aantoonbaar verliesgevend, ook bruto negatief.
- **H-GS-13** (IG New York positief): t_netto 2,35 → **1,93** (22 blokken; +1 blok). Pepperstone NY −0,37 (45 blokken). Verzwakt; eis blijft ≥ 30 nieuwe blokken (nu 6) en replicatie.
- **H-GS-12** (latency): p99 IG 33,0 s, Pepperstone 13,1 s (beide `candles->exits`), Bitvavo 4,3 s (was 6,7). Geen nieuwe oorzaakinformatie.
- Logruis "veldproefopzet uitgezet" na elke herstart (21× bij 20:58) → **L-GS-021** gepland (zelf bouwen: logging). Afstemming IG 2.237/2.239, Pepperstone 1.715/1.720.
- Niet meetbaar: slippage verwacht/gerealiseerd per trade (geen attribuut), IG-dagen vóór 19-10.
- Hypotheses: H-GS-11 (daghandelkosten; geen nieuwe daghandeltrades gemeten), H-GS-12 (latency/mand), H-GS-13 (IG NY). Geen release.

laatste ronde: 22-10 03:40, gemeten t/m 22-10 03:45

## 22-10 07:40 · tussenronde
- Actief **2.19.2** (geïnstalleerd, herstart 07:07-07:09). Demo/papier; noodstop-sensoren alle uit. Bij de herstart 2 WARNINGs "Noodstop uit een eerdere sessie blijft actief" zonder marktnaam: al gemeld door de meldronde (05:51), niet dubbel opgenomen. Geen knoppen, geen instellingen.
- **IG** sinds 03:45: 12 trades, netto −215 (run 194 trades, −420, PF 0,89, t −0,49). **Pepperstone**: 25 trades, netto +477 (run 1.631, −8.698, PF 0,80, t −1,41 over 9 clusters). Eén ochtend, geen conclusie; uurblokken-t in de dagafsluiting.
- Latency p99: IG 33,1 s, Pepperstone 13,8 s, Bitvavo 5,5 s → H-GS-12 ongewijzigd.
- Afstemming: IG 2.236/2.238 (2 uitstapverschillen ~3 USD), Pepperstone 1.735/1.740 (7, waarvan 1 trade na 7,4 dagen niet bij de broker).
- **L-GS-021 bevestigd op 2.19.2:** bij de herstart weer 22× "Veldproefopzet … uitgezet" (zelfde opzetten, oude n). 2.19.2 is geïnstalleerd → bouwen in de dagafsluiting 23-10 (alleen logging).
- Hypotheses: H-GS-11, H-GS-12, H-GS-13 (IG NY; vandaag nog geen NY-sessie). Geen release.

laatste ronde: 22-10 07:40, gemeten t/m 22-10 07:45

## 22-10 11:40 · tussenronde
- Actief **2.19.4** (andere sessie 08:22; herstarts ~09:02 en ~11:03). Demo/papier; geen knoppen, geen instellingen.
- **IG** sinds 07:45: +10 trades, netto **+189,5** (run 204 trades / 15 clusters, −230, PF 0,94, t_cluster −0,28). Uurblokken 59: t_bruto 1,20, t_netto −0,26; NY nog 22 blokken (t_netto 1,93, geen nieuwe NY-sessie) → H-GS-13 ongewijzigd.
- **Pepperstone**: +17 trades, netto −116 (run 1.648, −8.814, PF 0,80, t −1,41); blokken 125 t_netto −2,09, t_bruto −0,58 → blijft aantoonbaar verliesgevend.
- Latency p99: IG 32,5 s, Pepperstone 16,9 s, Bitvavo 11,0 s (was 5,5; DNS-storing 10:24-10:40 met 286 koers-/positiewaarschuwingen) → H-GS-12: storing extern, geen nieuwe oorzaak.
- Afstemming: IG 2.224/2.226 (2 uitstapverschillen ~7 USD, 1 nog niet bij de broker), Pepperstone 1.757/1.762 (7; 1 trade na 7,6 dagen niet bij de broker).
- **L-GS-021 3e keer:** herstart 09:02 op 2.19.4 weer 22× "Veldproefopzet … uitgezet". Blijft gepland voor de dagafsluiting 23-10.
- **Kandidaat "papiersaldo reset bij herladen" (GS-LEERLOG 06:25) nagelezen:** `risk_per_trade_pct` zit in de vingerafdruk (`_fingerprint_material` → `sizing`), dus 0,5 → 0,25 % start een **nieuwe run** en die begint bewust op 10.000 (`_herstel_uit_run` telt alleen trades van de lopende run). Geen bug; vervallen.
- Hypotheses: H-GS-11 (daghandelkosten), H-GS-12 (latency/mand), H-GS-13 (IG NY). Geen release.

laatste ronde: 22-10 11:40, gemeten t/m 22-10 11:45

## 22-10 15:40 · tussenronde
- Actief 2.19.4 (herstarts 14:18, 14:34, 15:27 door EMS-installaties). Demo/papier; geen knoppen, geen instellingen.
- **IG** sinds 11:45: +22 trades, netto −187,2 (run 226 / 15 clusters, −417, PF 0,91, t_cluster −0,50). Cluster 15 (08:45-15:45, 29 trades): bruto −3,3, netto −146,3 → kosten ~4,9 USD/trade maken het verlies (H-GS-11). Grootste cluster (nr 7, −443) weg: netto +25 → geen edge, geen conclusie bij 15 clusters (≥ 30 nodig voor een redelijke t-toets).
- **Pepperstone**: +33 trades, netto −235,5 (run 1.681, −9.050, PF 0,80, t −1,45).
- Latency p99: IG 32,2 s, Pepperstone 18,2 s, Bitvavo 13,5 s → H-GS-12 ongewijzigd.
- Afstemming: IG 2.225/2.227 (2 uitstapverschillen ~7,5 USD; 4 nog niet bij de broker), Pepperstone 1.790/1.795 (7; 1 trade na 7,8 dagen niet bij de broker).
- Bitvavo-mand: noodstop aan sinds 2.19.4 (PUMP-EUR, dagverlies 10,03 % uit een eerdere sessie; BILL-EUR sinds 14:19 niet meer). Na elke herstart ~1 min "uit" (14:18, 14:34, 15:27) tot de opslag geladen is → kort vals "uit" (n=3, meetbaarheid; volgen).
- L-GS-021 4e keer (15:28: 22× "uitgezet"); daarnaast bij elke herstart 10× "Opgewarmd met 96-247 candles" (Bitvavo).
- H-GS-13 (IG NY): sessie pas 15:30 begonnen; uitslag in de dagafsluiting.
- Hypotheses: H-GS-11 (daghandelkosten), H-GS-12 (latency/mand), H-GS-13 (IG NY). Geen release.

laatste ronde: 22-10 15:40, gemeten t/m 22-10 15:45

## 22-10 19:40 · tussenronde
- Actief **2.20.3** (andere sessies: 2.19.5, 2.20.0-2.20.3 tussen 15:01 en 19:03; herstart 19:07). Demo/papier; noodstops alle uit (ook de Bitvavo-mand). Geen knoppen, geen instellingen.
- **Nieuwe runs IG en Pepperstone sinds 16:48** (config-entry herladen 16:49; oorzaak niet in deze ronde vastgesteld). IG 19 trades / 1 cluster: netto +125,9 (bruto +226, kosten 100 = 5,3/trade, 44 % van bruto), PF 1,57. Pepperstone 24 trades / 1 cluster: netto +614,8, PF 5,28. Eén cluster → géén toets mogelijk (≥ 30 clusters nodig); oude runs eindigden op IG −417 (15 cl.) en Pepperstone −9.050 (t −1,45).
- H-GS-13 (IG NY): de NY-middag valt nu in een nieuwe run; uitslag van de oude run in de dagafsluiting uit de uurblokken.
- Latency p99: IG 32,3 s, Pepperstone 25,5 s (was 18,2), Bitvavo 13,3 s → H-GS-12: achtergrond-afstemming (2.20.0) liet IG p99 nog niet zakken; 1 dag meten.
- **Afstemming beter:** IG 0 afwijkingen (was 2, opgelost door 2.20.0/2.20.1), Pepperstone 3 (was 7).
- **L-GS-021 geverifieerd:** herstart 19:07 0× "uitgezet"/"Opgewarmd" (was 22× per herstart).
- Hypotheses: H-GS-11 (daghandelkosten), H-GS-12 (latency/mand), H-GS-13 (IG NY). Geen release.

laatste ronde: 22-10 19:40, gemeten t/m 22-10 19:45

## 22-10 23:40 · tussenronde
- Actief **2.20.4** (andere sessie 20:06: Pepperstone-afstemming op positienummer; herstarts 20:10 en 22:11). Demo/papier; geen knoppen, geen instellingen. Markten dicht (dagpauze).
- **IG** (run sinds 16:48): +11 trades, netto −116,9 → 30 trades / 1 cluster, netto +8,96, bruto 167,3, kosten 158,3 (5,28/trade = **95 % van bruto**), PF 1,02. `vp:rsi_rev:15m` 9 trades −181,9 (11 % winst). → H-GS-11: op IG eten de kosten de bruto winst vrijwel op.
- **Pepperstone**: +15 trades, netto +160,4 → 39 trades / 2 clusters, netto 775,2, kosten 78,3 (2,0/trade, 9 %), PF 3,14, t 1,71. 2 clusters → geen conclusie (≥ 30 nodig).
- Latency p99 na de herstart van 22:11 (venster opnieuw gevuld, markt dicht): IG 2,3 s (was 32,3), Pepperstone 13,7 s (25,5), Bitvavo 2,9 s (13,3) → H-GS-12 pas op een volle handelsdag beoordelen.
- Afstemming: IG 2249/2249 (0), Pepperstone 1848/1849 (1: uitstap 4181,94 tegen 4184,55; was 3 → 2.20.4 werkt).
- Logs: 21:01 "Veldproefopzet vp:donchian:15m uitgezet" (n=40, netto −644,5) = echte uitschakeling, geen herstartruis; herstarts 20:10 en 22:11 0× ruis → L-GS-021 nu 3× schoon. 23:24 1× "Openen geweigerd (papermarge)" (1999,54 nodig, 1997,93 vrij; zo bedoeld sinds 1.9.0). 17 koerstime-outs IG/Bitvavo (steeds 1 van 3, hersteld).
- Hypotheses: H-GS-11 (daghandelkosten), H-GS-12 (latency/mand), H-GS-13 (IG NY). Geen release.

laatste ronde: 22-10 23:40, gemeten t/m 22-10 23:45

## 23-10 03:40 · dagafsluiting 22-10
- Actief **2.20.4** (geïnstalleerd). Demo/papier; noodstops uit; geen knoppen, geen instellingen. Geen release (niets acuut; L-GS-011/019 blijven gepland).
- **IG** (run sinds 22-10 16:48): 39 trades / **4 clusters**, netto −214,7, bruto +31,6 tegen kosten 246,2 (6,3/trade, 7,8× bruto), PF 0,72, t −0,90. Nacht 23:45-03:45 9 trades −223,6 (één cluster −232,6 = 89 %). `vp:rsi_rev:15m` 14 trades: bruto +0,24, kosten 106,9 → H-GS-11 sterker: op IG eten de kosten elke bruto voorsprong op.
- **Pepperstone**: 62 trades / **2 clusters**, netto +395,1 (cluster 1 +614,8, cluster 2 −219,7), PF 1,36, t 0,47. Nacht −380,1 in 23 trades. Met 2 clusters geen enkele conclusie; ≥ 30 clusters nodig voor een toets (t ≥ 2).
- **Meetbaarheid, nieuw:** 3 Pepperstone-opzetten met **negatieve kosten** (netto > bruto: bb_fade:30m −3,48, structuur_hl:30m −4,04, structuur_trend:15m −1,56). Kan prijsverbetering of swap zijn, of bruto op een andere koers dan de broker-afrekening; vóór een voorstel per trade nagaan (n=3).
- **H-GS-12 (latency):** nachtsessie p99 IG 1,25 s, Pepperstone 1,32 s, Bitvavo 0,95 s (overdag 22-10 32 s). Volle handelsdag vandaag beslist.
- **H-GS-13 (IG NY):** niet meetbaar — de oude run (t/m 16:48) staat niet meer in de sensoren; per-uur-resultaat van een afgesloten run is niet leesbaar (meetbaarheid).
- Zelf gedetecteerd 23:47: saldosprong zonder trade (equity 10.000 → 8.995, −10,1 %), dagstart op de vorige referentie gehouden. Zelfde orde als de eerdere mand-noodstop (dagverlies 10,03 %); volgen.
- Afstemming: IG 0 afwijkingen, Pepperstone 1 (bekend). Koerstime-outs 38× (steeds 1 van 3, hersteld).
- Hypotheses: H-GS-11 (daghandelkosten IG), H-GS-12 (latency), H-GS-13 (IG NY; nu niet meetbaar). Geen release.

laatste ronde: 23-10 03:40, gemeten t/m 23-10 03:50

## 23-10 07:40 · tussenronde
- Actief **2.21.0** (andere sessie 07:35, vijf punten met akkoord Ruud; actief na de herstart van 07:39). Demo/papier; geen knoppen, geen instellingen.
- **IG**: +15 trades sinds 03:45 → 54 trades / 5 clusters, netto −214,7 → **+56,7**, kosten 289,9 (5,37/trade, 84 % van bruto), PF 1,06. t = 2,32 maar bij 5 clusters (df 4; 5 %-grens 2,78) en cluster 1 = 56 % van de trades → geen conclusie. De sensortekst "onder 2,0 is toeval" suggereert bij n=5 meer dan er is (meetbaarheid).
- **Pepperstone**: +36 trades → 98 trades / 4 clusters, netto 395 → **1058** (top 1530 om 04:02), PF 1,61, t 1,13; kosten 2,05/trade (16 %). 03:52-04:01 tot **11 open posities** tegelijk (vóór 2.21.0; limiet per richting 1) en 20 sluitingen in 6 min → precies het patroon dat 2.21.0 dicht. Na 07:39 max 1 → effect meten over de handelsdag.
- Afstemming Pepperstone 1906/1907: nog 1 afwijking, nu als bedrag (+37,75 tegen +22,65, overgenomen) i.p.v. uitstapprijs; `hersteld` false. Volgende afstemming na 2.21.0 afwachten.
- **H-GS-12:** p99 Pepperstone 1,3 → 3,0 s bij de opening, IG 1,5 s; volle handelsdag in de dagafsluiting.
- Logruis: "HA sluit af" 169× sinds 22-10 17:22 bij ~21 herstarts (~8 per herstart, één per coördinator per stop). Klein; noteren.
- Hypotheses: H-GS-11 (daghandelkosten IG: nu 84 % van bruto), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). Geen release.

laatste ronde: 23-10 07:40, gemeten t/m 23-10 07:45

## 23-10 11:40 · tussenronde
- Actief **2.21.1** (06:26, andere sessie; 2.21.0 07:35). Demo/papier; noodstops uit; geen knoppen, geen instellingen. 10:03 "Veldproefopzet vp:momentum:5m uitgezet" (n=40, netto −608) = echte uitschakeling.
- **IG**: +5 trades → 59 trades / **7 clusters**, netto 56,7 → **88,4**, kosten 7,40/trade in deze ronde (run 326,9 = 79 % van bruto), PF 1,09, t 1,84 (df 6; 5 %-grens 2,45; grootste cluster 51 % van de trades) → geen conclusie.
- **Pepperstone**: +8 trades → 106 / 5 clusters, netto 1058 → **680** (−378 in 8 trades; clusters 3-5 samen −659), PF 1,32, t 0,62; zonder de grootste cluster −44 → de run steunt op één nachtcluster. Oordeel `failed`.
- **2.21.0 effect (limiet per richting):** max open posities na 07:39 = 1, op één moment 2 (08:24:19-08:24:40, 21 s; richting niet terug te lezen). Was 11 om 04:00 → werkt; het 21-s-geval in de dagafsluiting nalezen in de tradelijst.
- **Afstemming:** IG 0 afwijkingen, **Pepperstone 0** (was 1); "261 bijgewerkt naar het bedrag van de broker". Mogelijke verklaring voor de negatieve kosten (netto > bruto, opnieuw in cluster 5: −276,87 tegen −277,51): bruto op eigen koersen, netto op het brokerbedrag. Toetsen in de dagafsluiting (per trade bruto vs brokerbedrag).
- **H-GS-12:** handelsochtend p99 IG 1,37 s, Pepperstone 1,69, Bitvavo 1,37 (22-10 overdag 32 s) → vandaag tot nu normaal.
- **2.21.1 effect:** "HA sluit af" 07:39 en 08:40 elk 1× (was ~8 per stop) → werkt (n=2).
- Hypotheses: H-GS-11 (kosten IG), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). Geen release.

laatste ronde: 23-10 11:40, gemeten t/m 23-10 11:45

## 23-10 15:40 · tussenronde
- Actief **2.21.1**. Demo/papier; noodstops IG/Pepperstone/BTC uit; geen knoppen, geen instellingen. Herstarts 11:51/14:54/15:17 (EMS-installaties); "HA sluit af" 1× per stop (2.21.1 houdt).
- **IG**: +6 trades → 65 / **7 clusters**, netto 88,4 → **127,9**, PF 1,12, **t 3,48** (df 6, 5 %-grens 2,45); 6 van 7 clusters positief. Toch geen conclusie: alle clusters binnen 25 u (één regime), cluster 1 = 46 % van de trades met netto 9; kosten 75 % van bruto (8,5/trade deze ronde). Nodig: ≥ 30 clusters over ≥ 5 handelsdagen.
- **Pepperstone**: +9 trades → 115 / 7 clusters, netto 680 → **239** (−441); clusters 3-7 (heel 23-10) alle negatief, −1.100; t 0,21, oordeel failed. Zelfde goud, zelfde uren als IG (+) → verschil zit in de opzetten per broker, niet in de markt (n=7, observatie).
- 2.21.0: max 2 open Pepperstone 14:27 (11 s); IG 2 bij 13:15/13:30/15:15 (20-30 s, op de kwartierwissel) → richting niet leesbaar (L-GS-019).
- **H-GS-12:** p99 Pepperstone 1,5 → 3,0 s in de middag, IG 2,7, Bitvavo ≤ 2,1; geen pieken als 22-10 (32 s).
- **Nieuw (meetbaarheid):** 15:18 "Noodstop uit een eerdere sessie blijft actief: dagverlies 10,11 %" zonder markt/entry; mand PUMP equity 7.771 (−22 %), PEPE 9.111; mand-attribuut toont geen noodstop per markt → kandidaat L-GS-022.
- Hypotheses: H-GS-11 (kosten IG 75 % van bruto), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). Geen release.

laatste ronde: 23-10 15:40, gemeten t/m 23-10 15:45

## 23-10 19:40 · tussenronde
- Actief **2.21.1**. Demo/papier; geen knoppen, geen instellingen. Geen HA-herstart sinds 15:17.
- **IG**: +13 trades → 78 / **9 clusters**, netto 127,9 → **122,6**, PF 1,09; **t 3,48 → 0,59** door één cluster (16:15-17:06, 10 trades, −143,7). Precies de waarschuwing van 15:40: bij < 30 clusters zegt t niets. Kosten 77 % van bruto (5,39/trade).
- **Pepperstone**: +18 trades → 133 / 7 clusters, netto 238,9 → **23,0**, PF 1,007, t 0,02; cluster 7 (13:27-18:54) 25 trades −485; alle 5 clusters sinds 04:30 negatief (−1.316), de run steunt op twee nachtclusters van 22-10. Kosten 92 % van bruto.
- 2.21.0: Pepperstone 3× 2 open (16:15, 16:30, 16:31; 21-22 s), IG 1× (16:31, 32 s) → telkens kort, richting niet leesbaar (L-GS-019).
- **H-GS-12:** p99 Pepperstone 3,10 → 1,82 s in de avond; BTC-mand 1,04 s.
- **Noodstop mand (papier):** 16:30:56 "NOODSTOP: dagverlies 10,05 %" → binary noodstop BTC-EUR aan; markt niet in de logregel (L-GS-022 blijft gepland).
- **Nieuw (logging/meetbaarheid):** "HA sluit af" om 16:18/17:18/18:18/19:18 zonder HA-herstart = elk uur een mandlid dat stopt (mand 21 → 20) → **L-GS-023** (gepland). Eerdere KPI-regels "HA sluit af" telden deze mee als herstarts.
- Hypotheses: H-GS-11 (kosten IG 77 % / PP 92 % van bruto), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). Geen release.

laatste ronde: 23-10 19:40, gemeten t/m 23-10 19:45

## 23-10 23:40 · tussenronde
- Actief **2.21.1**; 2.21.2 (L-GS-019) staat gedownload in HACS maar is pas actief na een HA-herstart. Demo/papier; geen knoppen, geen instellingen. Goud dicht sinds 22:55 (weekend).
- **IG:** +2 trades (20:00 +27,5; 22:46 +31,5) → 80 trades, netto **181,65**, PF 1,13, kosten 71 % van bruto. t per trade 0,81; per cluster nog steeds te weinig clusters (9-11) voor een toets (~18-30 nodig).
- **Pepperstone:** +5 trades, avondcluster 19:50-20:30 −171 (3 trades) → 138 trades, netto **−137,03**, PF 0,96, kosten 187 % van bruto; oordeel `failed`. Kosten daalden 300,88 → 294,16 zonder nieuwe trade (afstemming met broker).
- **Nieuw (meting):** Pepperstone houdt **1 short open over het weekend** (13 units, open 3999,48 om 21:57, stop 3999,16 = in winst, doel 3984,94); vorige weekenden 0 open. Er is geen weekendregel in de code (`enforce_trading_hours` uit, `trading_end_hour` 23) → geen bug; gaprisico is een strategiekeuze voor Ruud. Uitkomst maandag meten.
- Veldproef vp:structuur_trend:3m 20:31 uitgezet (n=42, netto −118,75, `t=None`). Mand: "HA sluit af" 20:18/21:18/22:18 (L-GS-023 gepland). Latency p99 Pepperstone 1,82 → 1,24 s.
- Hypotheses: H-GS-11 (kosten IG 71 % / PP 187 % van bruto), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). Geen release.

laatste ronde: 23-10 23:40, gemeten t/m 23-10 23:45

## 24-10 03:40 · dagafsluiting 23-10
- Actief 2.21.1 (2.21.2 gedownload, actief na een HA-herstart) → **release 2.21.3** (L-GS-022 + L-GS-023, alleen logging/weergave; suite 1979 groen, 8 nieuwe tests). Demo/papier; geen knoppen, geen instellingen. Goud dicht (weekend).
- **IG dag 23-10:** 50 trades, netto **+172,68** (bruto 449,55, kosten 276,86 = 62 %), winst 56 %. Run: 80 trades, netto 181,65, PF 1,13, t per trade 0,81, ~11 clusters. Eén cluster (16:15-17:06, −143,7) zette t van 3,48 naar 0,59 → bij < 30 clusters geen conclusie; nodig ≥ 30 clusters over ≥ 5 handelsdagen.
- **Pepperstone dag 23-10:** 99 trades, netto **−912,22** (bruto −693,61, kosten 218,61), winst 50,5 %; 22-10 was +775. Run 138 trades, netto −137, PF 0,96, oordeel failed. Zelfde goud, zelfde uren: IG +, PP − → verschil in de opzetten per broker (observatie, n=2 dagen).
- **H-GS-11 (kosten):** IG 62 % van bruto (run 71 %), PP 184 %. Nieuw (meetbaarheid): *Resultaat per periode* houdt de brokercorrectie van de kosten niet bij (week 296,92 tegen sensor 294,16) → **L-GS-024** (gepland).
- **H-GS-12 (latency):** p99 nu IG 0,71 / PP 0,79 / mand 0,62 s (markt dicht); dagpieken 23-10 tot 3,1 s, geen 32 s als 22-10.
- Mand: PEPE-EUR in noodstop blokkeert de mand; PUMP-EUR equity 7.610 (−24 %). Pepperstone houdt 1 short over het weekend (stop in winst; gaprisico = strategiekeuze Ruud, geen bug).
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar).

## 24-10 07:40 · tussenronde (niet gemeten)
- HA-MCP kon niet verbinden (502 bij opbouw van de verbinding) → geen history, logs of dashboard; niets gemeten, geen release, dashboardkaart niet bijgewerkt. Volgende ronde meet door vanaf 03:55 (recorder bewaart ~10 d, dus geen verlies).

laatste ronde: 24-10 07:40, gemeten t/m 24-10 03:55

## 24-10 11:40 · tussenronde
- Actief **2.22.0** (2.21.3 vanaf 07:41, 2.22.0 sinds herstart 10:16). Demo/papier; geen knoppen, geen instellingen. Goud dicht (weekend); IG en Pepperstone 0 nieuwe trades.
- **L-GS-023 geverifieerd:** "HA sluit af" alleen bij de echte herstarts 07:40 en 10:15; om 08:18/09:18 geen valse regel meer (t/m 07:18 elk uur). **L-GS-022 geverifieerd:** de bewaarde noodstop noemt de markt (pepe-eur, bill-eur).
- **2.22.0 D:** Pepperstone (138 trades, 8 clusters) van `failed` naar `insufficient_data`; zo bedoeld.
- **Mand (2.22.0 B/C):** 12 leden, 20 geweerd op spread, geen noodstop meer per mand. Alleen **PUMP-EUR** handelt: sinds 10:16 3 trades, equity 7.610 → 7.518; spread bij de herziening 11:17 **0,0295 %**, net onder de grens 0,03 % (2.22.0 noemde PUMP ~0,04 % als verliezer). Run PUMP 175 trades, −2.460,68 (−14,1 per trade). → **L-GS-025** (open, Ruud).
- **H-GS-12 (latency):** p99 IG 0,73 / PP 0,82 / mand 0,76 s.
- Pepperstone-short (58810248) nog open in het weekend; geopend vóór 2.22.0, de weekendsluiting is vrijdag 30-10 te toetsen.
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). Geen release.

laatste ronde: 24-10 11:40, gemeten t/m 24-10 11:45

## 24-10 15:40 · tussenronde
- Actief **2.22.0** (geen herstart sinds 10:16). Demo/papier; geen knoppen, geen instellingen. Goud dicht (weekend): IG en Pepperstone 0 trades; Pepperstone-short nog open (stop in winst).
- **Mand:** PUMP-EUR 11:40 → 13:17 +10 trades, netto −2.460,68 → **−2.565,22** (−10,5 per trade), equity 7.426. Herziening 13:17: spread 0,0238 % (in); **15:17: 0,0398 % → geweerd**. Twee herzieningen, twee kanten van de grens → steunt **L-GS-025** (toelating op één moment). Uitfasering was netjes (`_stop_als_plat`: alleen stoppen als plat; 15:17 0 open).
- Mand 12 → 16 → 15 → 14 leden; geen lid handelt nu (spot geen short / kostenfilter).
- **H-GS-12 (latency):** p99 IG 0,49 / PP 0,69 / mand 0,54 s. Bitvavo-koersfouten 6× (5× WLD-EUR leeg boek, 1× SOL-EUR gekruist boek), telkens 1 van max. 3 → correct afgewezen.
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). n blijft 9-11 clusters IG / 8 PP: geen toets. Geen release.

laatste ronde: 24-10 15:40, gemeten t/m 24-10 15:45

## 24-10 19:40 · tussenronde
- Actief **2.22.0** (geen herstart sinds 10:16). Demo/papier; geen knoppen, geen instellingen. Goud dicht (weekend): IG en Pepperstone 0 trades; Pepperstone-short nog open. Geen nieuwe Gold Scalper-logregels.
- **Mand:** herziening 19:17 liet **PUMP-EUR weer toe** (spread 0,0295 %, net onder 0,03 %) na de weigering van 15:17 (0,0398 %) → derde wissel in 6 uur. Sinds 15:40 +15 trades, netto −2.565 → **−2.758** (−12,9 per trade), equity 7.236, 2 open. Steunt **L-GS-025** (open, Ruud).
- ZIG-EUR valt uit de mand met 1 open positie (alleen nog sluiten) - zo bedoeld.
- **H-GS-12 (latency):** p99 IG 0,49 / PP 0,53 / mand 0,45 s.
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). n blijft 9-11 clusters IG / 8 PP (nodig ≥ 30 over ≥ 5 handelsdagen): geen toets. Geen release.

laatste ronde: 24-10 19:40, gemeten t/m 24-10 19:50

## 24-10 23:40 · tussenronde
- **2.22.1 staat op schijf maar draait niet:** diagnostics `integration_manifest.version` = **2.22.0**; HA is sinds 10:16 niet herstart (HACS 20:02 "herstart vereist"; eerste zip-poging 20:01:52 mislukte op een GitHub-header, de tweede slaagde). Code nagelezen: de fix klopt (`rond_prijs` rondt bij munten op significante cijfers); de test van 2.22.1 dekt PUMP (stop 0,5 % te krap). Activeren = HA herstarten (Ruud).
- **Mand:** PUMP-EUR bleef handelen: 19:53 → 23:40 +15 trades (200 → 215), netto −2.758 → **−2.896** (−9,2 per trade), equity 7.091. 21:20 geen weigering; herziening 23:17 zet PUMP op uitfaseren (3 open, alleen nog sluiten). Mand 13 leden, de rest weigert (spot-short / kostenfilter).
- Goud dicht (weekend): IG en Pepperstone 0 trades. Demo/papier; geen knoppen, geen instellingen.
- Hypotheses: H-GS-11 (kosten; PUMP bruto ook negatief), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). n blijft 9-11 clusters IG / 8 PP (nodig ≥ 30 over ≥ 5 handelsdagen): geen toets. Geen release (de fix bestaat al).

laatste ronde: 24-10 23:40, gemeten t/m 24-10 23:45

## 25-10 03:40 · dagafsluiting 24-10
- **2.22.1 staat klaar maar draait niet** (HACS 24-10 20:02, HA niet herstart sinds 10:16) → geen release (niet stapelen). Demo/papier; geen knoppen, geen instellingen.
- Dag 24-10 (za): goud dicht → IG en Pepperstone 0 trades. Runs ongewijzigd: IG 80 trades (~11 clusters), netto 181,65, PF 1,134, t 0,81; Pepperstone 138 trades (8 clusters), netto −137,03, PF 0,958, t −0,11. Pepperstone-short nog open (weekendsluiting vrijdag 30-10 toetsen).
- **Mand:** herziening 02:17 weert PUMP-EUR op spread (0,0674 %); mand 10 leden, geen enkele handelt (6× spot geen short, 4× kostenfilter). Laatst gemeten PUMP-run (23:40) 215 trades, netto −2.896 (−13,5 per trade). **Meetbaarheid:** een vertrokken markt verdwijnt mét zijn resultaat uit `per_markt` (`mand.overzicht` toont alleen huidige leden) → eindstand PUMP niet af te lezen → **L-GS-026** (gepland).
- DNS-storing ~00:45: Bitvavo-koers 3-6× op rij mislukt (entiteiten kort onbeschikbaar), cTrader-positie 2-3 van max. 3 → afgevangen, geen beslissingen; extern.
- **H-GS-12 (latency):** p99 IG 0,68 / PP 0,76 / mand 0,48 s (markt dicht, geen toets).
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). n 11 clusters IG / 8 PP (nodig ≥ 30 over ≥ 5 handelsdagen): geen toets. L-GS-024 wacht op een handelsdag én de installatie van 2.22.1.

laatste ronde: 25-10 03:40, gemeten t/m 25-10 03:50

## 25-10 07:40 · tussenronde
- **HA herstart 06:00 CET: 2.22.1 actief** (kostenfilterfix). Demo/papier; geen knoppen, geen instellingen.
- Goud dicht (zondag): IG en Pepperstone 0 trades; Pepperstone-short nog open. Mand (herziening 06:01Z): 12 leden, 0 open, 0 trades (spot geen short / kostenfilter); PEPE geweerd op spread 0,038 %; `noodstop_markten` leeg.
- Bij de start opnieuw "Noodstop uit een eerdere sessie blijft actief" voor pepe-eur en bill-eur (geen mandleden, geen effect). Nog geen voorstel: lijkt bewust (de noodstop moet blijven als de markt terugkomt).
- **H-GS-12 (latency):** p99 IG 0,66 / PP 0,72 / mand 0,54 s (markt dicht).
- 2.22.1 draait → **L-GS-026** mag in de dagafsluiting van 26-10 gebouwd worden; L-GS-024 wacht op een handelsdag (ma 26-10 → 27-10 03:40).
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). n 11 clusters IG / 8 PP (nodig ≥ 30 over ≥ 5 handelsdagen): geen toets. Geen release.

laatste ronde: 25-10 07:40, gemeten t/m 25-10 07:45

## 25-10 11:40 · tussenronde
- **Andere sessie releasede 2.22.2 (10:04, mandgrootboek) en 2.23.0 (10:52, spot-longs op 1h/4h/1d); geïnstalleerd** via de herstarts van 10:08 en 10:53. Demo/papier; geen knoppen, geen instellingen.
- **L-GS-026 gedekt door 2.22.2:** `Trades.per_markt` toont alle 32 markten uit hun database, ook vertrokken. Eerste volledige mandstand (sinds run-start, papier): **561 trades, netto −6.296**, 213 W / 348 V (38 %), 548× stop, 1× doel. PUMP 223 (−2.988; 15 % winst), BILL 152 (−1.807), PEPE 163 (−1.243; 60 % winst), ICNT 15 (−197), PTB 4, IOST 3, ZIG 1 (+7); 25 markten 0.
- **H-GS-11 (kosten) versterkt:** mand −11,2 per trade, PF 0,12, t −1,31; verlies zit bij de drie munten met de kleine koers (PUMP/BILL/PEPE = 538 van 561 trades, −6.038) - precies de kostenfout van vóór 2.22.1.
- **Meetbaarheid:** *Equity* mand = 10.000 + som van alle markten = 3.684 terwijl *Vermogensvloer* 5.000 (hoofdlus) toont → oogt als vloerbreuk, is het niet (risico leest de eigen lus; `mand.py` sensor_equity). Ook *Max. drawdown* 63 % gaat over die opgetelde reeks. Bewuste keuze in 2.22.2 → alleen vastgelegd.
- Goud dicht (zondag): IG/Pepperstone 0 trades; Pepperstone-short nog open. Mand 15 leden, 0 open, 0 nieuwe trades sinds 07:40. Latency p99 IG 0,71 / mand 0,71 s (H-GS-12, markt dicht).
- Hypotheses: H-GS-11, H-GS-12, H-GS-13 (IG NY; niet meetbaar). Goud n 11 clusters IG / 8 PP (nodig ≥ 30 over ≥ 5 handelsdagen): geen toets. 2.23.0-opzetten: nog 0 trades. Geen release.

laatste ronde: 25-10 11:40, gemeten t/m 25-10 11:45

## 25-10 15:40 · tussenronde
- 2.23.0 actief; geen herstart sinds 10:53. Demo/papier; geen knoppen, geen instellingen.
- **Mand (2.23.0, eerste longs):** 14 open papierposities (SOL, ADA, ETH, HYPE, WLD, NEAR, SUI, ONDO, LINK, DOGE, XLM, LTC, AVAX, FARTCOIN; 6 daarvan in uitfasering, alleen nog sluiten). Gesloten +3 sinds 11:40: PROMPT 2 (−16,58), CT 1 (−27,26) → **564 trades, netto −6.340**, PF 0,12, t −1,31. De 2.23.0-opzetten zelf: nog 0 gesloten → geen oordeel.
- Weigeringen sluiten aan: 37× "dubbele order: al een long", 29× kostenfilter, 477× spot geen short.
- **H-GS-12 (latency):** p99 IG **1,60** / PP **1,90** / mand **1,38 s** (was ~0,7): DNS-storing 13:36-15:39 (116 waarschuwingen, max 5 mislukt op rij → entiteiten kort onbeschikbaar, geen beslissingen). Extern; p99 meet de storing mee → bij de dagafsluiting p99 buiten storingsminuten apart noemen.
- Goud dicht (zondag): IG/Pepperstone 0 trades; Pepperstone-short nog open.
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). Goud n 11 clusters IG / 8 PP (nodig ≥ 30 over ≥ 5 handelsdagen): geen toets. Geen release.

laatste ronde: 25-10 15:40, gemeten t/m 25-10 15:45

## 25-10 19:40 · tussenronde
- 2.23.0 actief; HA herstartte 15:54, 16:09, 17:25 en 18:47 (installaties EMS elders), Gold Scalper herlaadde ook 16:37. Demo/papier; geen knoppen, geen instellingen.
- **Mand:** 19 leden, **18 open papierlongs** (was 14; +BABY 2, ANIME 2), 0 gesloten sinds 15:40 → nog **564 trades, netto −6.340**, PF 0,12, t −1,31. Open longs staan licht in de plus (equity per lid +2..+6). 2.23.0-opzetten: nog 0 gesloten → geen oordeel.
- **PEPE-EUR terug in de mand (spread 0,018 %) en geblokkeerd door de oude noodstop** (dagverlies 10,05 %, eerdere sessie): 682 long- + 413 short-weigeringen; `binary_sensor …btc_eur_noodstop` aan sinds 18:47:58 (ook 16:10-17:10 toen PEPE even lid was). Bewust: hervatten is handwerk (gold_scalper.resume) - niet aangeraakt.
- **Opstartartefact (meetfout, 5 starts):** in de eerste ~25 s na elke start tonen *Trades*/*Nettoresultaat* eerst 0, dan een deelsom (152/163/376/316 trades; −1.807/−1.243/−4.823/−3.077) en pas daarna 564/−6.340; *Noodstop* flapt 10 s aan (15:55, 17:25). Oorzaak in de code: `mand.grootboek()`/`statistiek()` lopen al vóór `_gereed` en vóór `_laad_archief()` (mand.py `async_start`). Geen effect op de handel; wel op recorder/statistiek en automations op die sensoren → **L-GS-027** (gepland, zelf bouwen: rapportage).
- **H-GS-12 (latency):** p99 IG 1,84 / mand 1,48 s (15:40: 1,60/1,38) - nog verhoogd na de DNS-storing en de herstarts; markt dicht → p99 buiten storings-/opstartminuten in de dagafsluiting.
- Goud dicht (zondag, IG opent ~23:00): IG/Pepperstone 0 trades; Pepperstone-short nog open.
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency), H-GS-13 (IG NY; niet meetbaar). Goud n 11 clusters IG / 8 PP (nodig ≥ 30 over ≥ 5 handelsdagen): geen toets. Geen release (tussenronde).

laatste ronde: 25-10 19:40, gemeten t/m 25-10 19:45

## 25-10 23:40 · tussenronde
- 2.23.0 actief; geen herstart sinds 18:47. Demo/papier; geen knoppen, geen instellingen.
- **Goud open (zo 23:00):** Pepperstone 138 → **144 trades** (de open short sloot 23:01, daarna 5 nieuwe; 23:45 1 open). Netto Pepperstone totaal −24,79 (bruto +330,09, kosten 354,88, kostenratio 1,08); kosten 97,9 % gemeten. **IG 0 trades:** status `rooster_wijkt_af` - broker zegt open, rooster dicht ("dagelijkse onderbreking 23:00-24:00", en zondag valt buiten de rooster-week die maandag 00:00 opent). Bewust: bij onenigheid wint 'gesloten' (schedule.py). Gevolg gemeten: IG mist elke dag 23:00-24:00 waarin Pepperstone handelt (vanavond 6 trades). Nog geen voorstel: eerst ≥ 3 avonden vergelijken (H-GS-13).
- IG-afstemming 23:01: 1323/1324 trades kloppen, 1 afwijking (−37,44 tegen −34,04 bij de broker, overgenomen).
- **Mand:** 19 leden, 19 open papierlongs, 0 gesloten → nog **564 trades, netto −6.340**, PF 0,12, t −1,31. PEPE weer uit de mand (spread 0,055 %) → noodstop-sensor volgt het lidmaatschap: aan 20:48-21:48, uit sinds 21:48 (herziening per uur). ANIME: 3.890× "risico in deze richting boven de grens".
- **Meetbaarheid (nieuw):** sinds **23:00:15** weigert de recorder de attributen van `sensor.gold_scalper_btc_eur_mand` (18,0 kB > 16 kB; 269× in 45 min) → geen historie meer van open posities/weigeringen per markt. Grootte: `per_markt` 10,7 kB, `buiten_mand` 5,5 kB (waarvan 3,6 kB markten met 0 trades). → **L-GS-028** (gepland, zelf bouwen: rapportage; samen met L-GS-027 in de dagafsluiting).
- **H-GS-12 (latency):** p99 Pepperstone 0,76 / mand 0,58 s (19:40 mand 1,48) - terug op het normale niveau na de DNS-storing; IG geen nieuwe meting (handelt niet).
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency, genormaliseerd), H-GS-13 (IG NY/rooster). Goud n 11 clusters IG / 8 PP (nodig ≥ 30 over ≥ 5 handelsdagen): geen toets. Geen release (tussenronde).

laatste ronde: 25-10 23:40, gemeten t/m 25-10 23:45

## 26-10 03:40 · dagafsluiting 25-10
- 2.23.0 actief; HA-herstarts 25-10 09:29-18:47 (installaties elders), geen sinds 18:47. Demo/papier; geen knoppen, geen instellingen, handel niet aangeraakt.
- **Dag 25-10 (zo):** goud alleen 23:00-24:00. **Pepperstone 7 trades** (138 → 145, incl. de weekendshort 23:01): netto **+102,14** = bruto 177,26 − kosten 75,12 (42 %; incl. afstemming 23:01: 183 trades naar brokerbedrag, kosten +39,83 zonder trade). **IG 0 trades** (rooster: zondag + 23-24 dicht, H-GS-13 avond 1 van 3). Week 43 Pepperstone 145 trades, netto −34,89 (bruto 334,39, kosten 369,28 = 110 %); IG 80 trades, netto +181,64.
- Nacht 26-10 t/m 03:41 (telt bij 26-10): Pepperstone +17 trades, netto +179,63 (winst 82 %); IG 3 trades (02:01-02:25), −1,83. Runs: IG 83 trades, netto 179,82, PF 1,123, t 0,80; Pepperstone 162, netto 144,74, PF 1,041, t 0,11. n IG ~12 / PP ~10 clusters (nodig ≥ 30 over ≥ 5 handelsdagen): **geen toets**.
- **Mand:** 25-10 +3 trades (12:36-14:27), −43,85; nacht +4 (−87,63) → 568 trades, netto −6.428, PF 0,12, t −1,33, equity 3.514. 18 leden, **15 in uitfaseren** (alleen BTC/SOL/ETH volwaardig), 20 papierlongs open; weigeringen 13.823× "valt uit de mand, alleen nog sluiten", 5.285× risico in deze richting. De 2.23.0-opzetten: 0 gesloten → geen oordeel.
- **H-GS-12 (latency):** p99 buiten de storingen PP 0,71-0,84 s, mand 0,48-0,74 s (25-10 00-13 u en 22-24 u); tijdens DNS-storing 13:05-15:40 + herstarts tot 2,08 / 1,42 s, rond 21:30 genormaliseerd. Nacht: DNS-storing 00:11-02:34 (Bitvavo/IG/cTrader 1-3 op rij mislukt, afgevangen; extern). IG-latency/-status: geen recorderhistorie (uitgesloten sinds 11-10) → alleen actuele stand (IG 0,76 s).
- **Release 2.23.1** (L-GS-027 + L-GS-028; suite 2046 groen, 7 skipped, 13 nieuwe tests): mandsensoren onbekend tot leden + archief geladen, noodstop van leden pas daarna; *Mand*-attributen: buiten_mand alleen met trades (max. 15), top-3 weigeringen per lid → toets 20 leden + 80 vertrokken < 14 kB (nu 18,0 kB). Plus logregel "Slippage 0.000 begrensd op 0.000" met echte bedragen.
- Hypotheses: H-GS-11 (kosten; PP week 43 kosten 110 % van bruto), H-GS-12 (latency, genormaliseerd), H-GS-13 (IG rooster 23-24 u; 1/3 avonden). Geen nieuwe voorstellen; L-GS-025 blijft open.

laatste ronde: 26-10 03:40, gemeten t/m 26-10 03:45

## 26-10 07:40 · tussenronde
- HA herstartte 07:12 → **2.23.1 actief**. **2.24.0** (andere sessie 07:42: L-GS-025 mediane spread 24 u, L-GS-029 oude dagverlies-noodstops niet terugzetten, slippage in bp) is gedownload en wacht op een herstart. Demo/papier; geen knoppen, geen instellingen.
- **L-GS-028 eerste toets OK:** 0 recorder-WARNINGs voor `sensor.gold_scalper_btc_eur_mand` sinds 07:12 (laatste 07:10:59; 25-10 23:00 → 07:11 ~1.700×).
- **L-GS-027 deels:** bij de herstart 07:12 bleef *Nettoresultaat* netjes onbekend en flapte *Noodstop* niet, maar *Trades* stond **13 s op 0** (07:12:17) voor onbekend → 569 (07:13:02). Oorzaak in de code: de eerste verversing en het aanmaken van de sensoren (`__init__.py`) lopen vóór `coordinator._mand = mand`, dus `mand_wacht` is dan nog False en de eigen BTC-EUR-stats (0 trades) gaan erdoor. *Mand* (aantal markten) liep 5 → 13 → 25 → 21 tijdens het opstarten van de leden (echte opbouw, geen meetfout). → **L-GS-030** (gepland, zelf bouwen: rapportage; na installatie van 2.24.0, niet stapelen).
- Goud: IG 83 → **89 trades** (−88,81; run netto 91,01, PF 1,056, t 0,37); Pepperstone 162 → **168** (−33,51; run 111,23, PF 1,031, t 0,09). n IG ~13 / PP ~11 clusters (nodig ≥ 30 over ≥ 5 handelsdagen): **geen toets**. IG 1 positie open.
- Mand: +1 trade (+9,27) → 569, netto −6.418, PF 0,12, t −1,32. Na de herstart weer "Noodstop uit een eerdere sessie" voor BILL-EUR (10,11 %) → 2.24.0 (L-GS-029) ruimt dat op.
- **H-GS-12 (latency):** p99 IG 0,91 / PP 0,78 / mand 0,59 s - normaal.
- **Herstart 07:47 → 2.24.0 actief.** Zelfde artefact opnieuw: *Trades* 07:47:06 **0** (22 s) → onbekend → 569 (07:48:00); noodstop geen flap → L-GS-030 n=2, bouwen in de dagafsluiting 27-10 03:40 (2.24.0 staat er nu op).
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency, normaal), H-GS-13 (IG rooster 23-24 u; vanavond avond 2 van 3). Geen release (tussenronde).

laatste ronde: 26-10 07:40, gemeten t/m 26-10 07:45

## 26-10 11:40 · tussenronde
- 2.24.0 actief (herstart 10:27/10:28). Demo/papier; geen knoppen, geen instellingen.
- Goud: IG 89 → **94 trades** (−104,25; run netto −13,24, PF 0,992, t −0,04); Pepperstone 168 → **176** (−45,28; run 65,95, PF 1,017, t 0,05). Beide 1 positie open, afstemming `in_orde`. n IG ~14 / PP ~12 clusters (nodig ≥ 30 over ≥ 5 handelsdagen): **geen toets**; beide runs schuiven naar nul.
- Mand: 0 trades (569, netto −6.418, PF 0,12, t −1,32), 0 open; noodstop-markten leeg (L-GS-029 houdt na herstart 10:28 ✓).
- **L-GS-025 (2.24.0) eerste toets:** `spread_toelating` = mediaan_24u, 95 markten met historie, 20 geweerd op de mediaan (o.a. PUMP 0,036 / PEPE 0,043 / NEAR 0,032 boven de grens 0,03 %, ook als de momentspread eronder lag: PEPE 0,023, NEAR 0,027). In/uit-wissels per markt per dag → dagafsluiting.
- **L-GS-030 n=3:** herstart 10:28 weer *Trades* **0** (10:28:10, 25 s) → onbekend → 569 (10:28:58); netto alleen onbekend, noodstop geen flap; *Mand* 5 → 17 → 20 (opbouw).
- **H-GS-12 (latency):** p99 IG 0,96 / PP 0,85 / mand 0,54 s - normaal.
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency), H-GS-13 (IG rooster 23-24 u; vanavond avond 2 van 3). Geen release.

laatste ronde: 26-10 11:40, gemeten t/m 26-10 11:45

## 26-10 15:40 · tussenronde
- 2.24.0 actief (HA-herstarts 13:32, 15:00, 15:13). Na 15:13: 1 trade bij de broker al gesloten (stop tijdens herstart) → administratie bijgewerkt (lifecycle-waarschuwing, geen fout). Demo/papier; geen knoppen, geen instellingen.
- Goud: IG 94 → **109 trades** (−153,71; run netto −166,95, PF 0,923, t −0,39, 11 clusters); Pepperstone 176 → **190** (−158,88; run −92,93, PF 0,978, t −0,07, 15 clusters). **Beide runs nu negatief.** Afstemming beide `in_orde`.
- **Verlies van vandaag is één regime, bij beide brokers tegelijk:** IG cluster 11 (02:15-14:36 UTC, 26 trades) netto −346,77 / **bruto −177,84**; PP cluster 15 (08:57-14:37 UTC) netto −261,64 / **bruto −222,96**. Bruto negatief → niet alleen kosten. Les voor de toets: clusters van beide brokers zijn niet onafhankelijk (zelfde markt, zelfde moment); voor een edge-toets ≥ 30 clusters **per broker** over ≥ 5 handelsdagen, en één doorlopende 'cluster' van 12 u (herinstap < 10 min) telt als 1. Nu IG 11 / PP 15: **geen toets**.
- Kosten per trade IG 5,69 USD (kosten/bruto 1,37), PP 2,60 (1,23); gemeten 99 %. H-GS-11 (kosten > bruto) blijft staan.
- **Mand:** 0 gesloten trades (569, netto −6.418), maar **21 open posities** (equity 3.646 / balans 3.582). Correctie op 11:40 ("0 open"): de sensor *Open posities* op het mandapparaat telt alleen BTC-EUR; het mand-attribuut `open_posities` = 21 stond er al om 11:40. → meetbaarheid, voorstel in de dagafsluiting na code-check (bewuste keuze of fout?).
- **H-GS-12 (latency):** p99 IG **1,38** s (deelstappen 0,78) / PP 1,11 / mand 0,61 - hoger dan 11:40 (0,96/0,85), binnen de herstarts (max 15,7 s). Na een rustige periode opnieuw meten.
- Hypotheses: H-GS-11 (kosten), H-GS-12 (latency, herstarts), H-GS-13 (IG rooster 23-24 u; vanavond avond 2 van 3). Geen release.

laatste ronde: 26-10 15:40, gemeten t/m 26-10 15:45

## 26-10 19:40 · tussenronde
- 2.24.0 actief; **2.24.1 gedownload 19:32, wacht op een herstart** (HA-herstart 19:15 was ervóór). *Open posities* op het mandapparaat dus nog 0 terwijl `Mand.open_posities` 19 is - verwacht, geen nieuwe fout. Demo/papier; geen knoppen, geen instellingen.
- Goud: IG 109 → **116 trades** (−76,64; run netto −243,59, PF 0,896, t −0,49); Pepperstone 190 → **198** (+3,20; run −89,73, PF 0,979, t −0,07). Afstemming beide `in_orde`, 1 positie open elk.
- **Zelfde regime loopt door:** IG cluster 11 nu 33 trades 02:15-17:31 UTC (916 min), netto −423,41 / bruto −217,99; zonder dat cluster run +179,81. PP cluster 15: 23 trades 08:57-17:30 UTC, −258,44 / bruto −194,31. Een hele handelsdag is bij doorlopend handelen één cluster → clusters per broker stijgen nauwelijks (IG 11, PP 15). Voor ≥ 30 clusters per broker zijn bij dit tempo (~1-3 nieuwe per dag) nog 2-3 weken nodig. **Geen toets.**
- Mand: 569 → **573 trades** (+10,75; netto −6.407,64, PF 0,123, t −1,32), 19 open, 19 markten.
- **L-GS-030 n=4:** herstart 19:15 *Trades* **0** (19:15:27, 12 s) → onbekend → 573 (19:16:10); netto alleen onbekend; *Mand* 5 → 13 → 22 → 19 (opbouw).
- DNS-storing 19:33 (Bitvavo/IG/cTrader 4-6 op rij mislukt, entiteiten 11 s onbeschikbaar, afgevangen; extern). Latency p99 IG **1,41** s / PP 0,99 / mand 0,68 (herstart + DNS).
- Hypotheses: H-GS-11 (kosten; vandaag ook bruto negatief), H-GS-12 (latency; IG blijft > 1 s, na een rustige nacht opnieuw), H-GS-13 (IG rooster 23-24 u; vanavond avond 2 van 3). Geen release.

laatste ronde: 26-10 19:40, gemeten t/m 26-10 19:45

## 26-10 23:40 · tussenronde
- **2.24.2 actief** (andere sessie 20:00 UTC+1; herstarts 20:06, 20:25, 21:08, 21:52). **2.24.1 werkt:** *Open posities* mand = 19 = `Mand.open_posities`. Demo/papier; geen knoppen, geen instellingen.
- Goud: IG 116 → **120 trades** (−136,80; run netto −380,39, PF 0,848, t −0,61); Pepperstone 198 → **200** (−201,46: 19:58 −100,80 en 21:54 −100,66; run −291,19, PF 0,935, t −0,23). 19:58 verloren beide brokers tegelijk (IG −99,37) = één marktbeweging, niet onafhankelijk. Clusters IG ~11 / PP ~15 (nodig ≥ 30 per broker): **geen toets**.
- Mand: 0 nieuwe trades (573, netto −6.407,64), 19 open.
- **H-GS-13 verklaard (avond 2 van 3):** beide brokers dicht **21:59/22:00 → 23:01 CET** = 17:00-18:00 New York; de VS hebben tot 01-11 nog zomertijd. Het rooster heeft de pauze vast op 23:00-24:00 Amsterdam → IG wacht tot 24:00 terwijl Pepperstone om 23:01 weer opende. Geen rooster- of brokerfout maar een tijdzonefout in het rooster, alleen in de DST-weken → **L-GS-031** (open). Toets: vr 30-10 sluiting 22:00 CET; vanaf 02-11 weer 23:00-24:00.
- **Stilstandcontrole:** *Tijdstopvarianten* IG/PP ≥ 10 d op 0 ("te weinig blokken") - meet alleen scalp, de veldproef heeft geen tijdstop → kan nooit vorderen; ook exitregime "tijdstop" op alle veldproeftrades → **L-GS-032** (gepland, rapportage, dagafsluiting). Mand: *Resultaat per periode* en *Kosten gemeten* unknown sinds 20-10, *Afstemming* "nog_niet" (papier, geen broker) → dagafsluiting: code nalezen of dat bewust is.
- **L-GS-030 n=8:** elke herstart *Trades* ~30 s **0** → onbekend → 573, *Open posities* 0 bij het afsluiten; bouwen in de dagafsluiting 27-10.
- Latency p99 IG 1,10 / PP 1,04 / mand 0,64 s (4 herstarts) - H-GS-12 na een rustige nacht opnieuw.
- Hypotheses: H-GS-11 (kosten; bruto vandaag ook negatief), H-GS-12 (latency), H-GS-13 (→ verklaard, L-GS-031). Geen release (tussenronde; 2.24.2 vandaag al gereleased).

laatste ronde: 26-10 23:40, gemeten t/m 26-10 23:45

## 27-10 03:40 · dagafsluiting 26-10
- 2.24.2 actief; **release 2.24.3** (04:03; L-GS-030 + L-GS-032, alleen weergave/statistiek; suite 2102 groen, workflow groen, HACS ververst; wacht op installatie). Demo/papier; geen knoppen, geen instellingen. DNS-storing ~02:12 (Bitvavo/cTrader 1-2 op rij mislukt, afgevangen).
- **Goud 26-10 (UTC-dag):** Pepperstone 56 trades, netto **−361,76** (bruto −198,67, kosten 163,09); IG 40 trades, **−562,03** (bruto −313,38, kosten 248,65). Bruto bij beide negatief → niet alleen kosten. IG-verlies zit in één cluster (nr. 11: 37 trades 02:15-19:42 UTC, −560,21; zonder dat cluster run +197,68).
- **Runs:** IG 122 trades / 12 clusters, netto −362,51, PF 0,855, t −0,585; PP 220 / 19 clusters, −545,19, PF 0,892, t −0,408 (nacht 27-10 cluster 19: 14 trades 00:30-02:45 UTC, −383,16). Nodig ≥ 30 clusters per broker over ≥ 5 handelsdagen: **geen toets**. Clusters van beide brokers vallen samen (zelfde markt, zelfde moment) → niet onafhankelijk.
- 03:16 zette de eigen regel `vp:pullback:30m` uit (n=40 in de database, netto −548,3) - bestaande regel 2.5.6/2.14.0, geen ingreep.
- **H-GS-13 avond 3 van 3:** brokers dicht 22:00-23:01 CET; IG volgens rooster dicht tot 24:00, PP handelde 23:01-01:09 (6 trades +129,16) → L-GS-031 (open). Toets vr 30-10 sluiting 22:00 CET.
- **Mand:** 26-10 +5 trades (568 → 573, netto +20,02), 19 open, 19 markten. L-GS-025: PUMP-EUR en PEPE-EUR blijven geweerd op de mediaan (0,036/0,048 % > 0,03 %); wissels per dag niet meetbaar uit de attributen (alleen `herzien_om`).
- **Latency (H-GS-12) na een rustige nacht normaal:** p99 IG 0,86 / PP 0,87 / mand 0,39 s → hypothese gesloten.
- Stilstand: *Tijdstopvarianten* (L-GS-032 → 2.24.3); nieuw: mand *Resultaat per periode* unknown sinds 20-10 → **L-GS-033** (gepland). *Kosten gemeten*/*Afstemming* mand bewust leeg (papier).
- Hypotheses: H-GS-11 (kosten > bruto; 26-10 ook bruto negatief), H-GS-13 (→ L-GS-031, toets 30-10), **H-GS-14** (nieuw: het dagverlies komt uit één doorlopend regime-cluster per dag, bij beide brokers tegelijk; n=2 dagen).

laatste ronde: 27-10 03:40, gemeten t/m 27-10 03:50

## 27-10 07:40 · tussenronde
- HA herstartte 06:04 → **2.24.3 actief**. Demo/papier; geen knoppen, geen instellingen. Logs: 1 koersopvraging IG time-out (07:22, afgevangen), 1 trade bij controle afgerekend (07:10, gesloten op stop).
- **L-GS-030 toets 1 OK:** bij de herstart 06:04 mand *Trades* 574 → onbekend → 574 (06:05:34), **geen 0**; netto idem (n=1; was 4 van 4 keer 0).
- **L-GS-032 OK:** *Tijdstopvarianten* IG/PP "niet van toepassing", `van_toepassing` false; PP `per_exitregime` heeft sinds 07:10 een groep `veldproef` (2 trades, −198,44; oudere open trades houden 'tijdstop').
- **Goud 03:50-07:40:** Pepperstone 7 trades, **−333,53** (3 stops van ~−100: 05:56, 07:10, 07:21) → run 227, −878,72, PF 0,837, t −0,643; IG 8 trades, −13,68 (twee winsten +55/+53 om 04:40-04:45, stops −100 om 05:51 en 06:30) → 130, −376,19, PF 0,861, t −0,585. ~20 clusters PP / ~13 IG: nodig ≥ 30 per broker over ≥ 5 handelsdagen → **geen toets**.
- **H-GS-14** (dagverlies uit één regime-cluster, beide brokers tegelijk): vanochtend PP −334 tegen IG −14 in hetzelfde venster → 'tegelijk' houdt hier niet; hypothese blijft open (n=3 dagen nodig).
- Mand: +1 trade (574, netto −6.410,57), 18 open; *Resultaat per periode* nog unknown (L-GS-033, kan nu in de dagafsluiting: 2.24.3 staat erop).
- Latency p99: IG 0,91 / PP 0,90 / mand 0,45 s - normaal.
- Hypotheses: H-GS-11 (kosten > bruto), H-GS-13 (→ L-GS-031, toets vr 30-10), H-GS-14. Geen release.

laatste ronde: 27-10 07:40, gemeten t/m 27-10 07:40

## 27-10 11:40 · tussenronde
- Herstarts 08:00 en 11:34; **2.24.3 actief**. Demo/papier; geen knoppen, geen instellingen. Geen release.
- **L-GS-030 geverifieerd:** 3 herstarts (06:04, 08:00, 11:34) mand *Trades*/*Open posities* 574/18 → onbekend → 574/18, nooit 0 (was 4 van 4 keer 0).
- **Goud 07:40-11:40:** Pepperstone 14 trades, **+140,53** → run 241, −738,19, PF 0,866, t −0,537; IG 8 trades, **−65,96** → 138, −442,15, PF 0,842, t −0,688. Clusters ~21 PP / ~14 IG; nodig ≥ 30 per broker over ≥ 5 handelsdagen → **geen toets**.
- **H-GS-14:** tweede venster op rij met tegengestelde uitkomst PP/IG (ochtend −334/−14, nu +141/−66) → "beide brokers tegelijk" houdt binnen de dag niet; toets blijft op dagniveau (n=3 dagen).
- Mand: 574 trades, netto −6.410,57 (geen nieuwe trade), 18 open; *Resultaat per periode* unknown (L-GS-033, dagafsluiting 28-10).
- Latency p99: IG 1,28 / PP 0,90 / mand 0,60 s - IG hoger na 2 herstarts (zelfde patroon als 26-10), geen nieuwe hypothese.
- Hypotheses: H-GS-11 (kosten > bruto), H-GS-13 (→ L-GS-031, toets vr 30-10), H-GS-14.

laatste ronde: 27-10 11:40, gemeten t/m 27-10 11:43

## 27-10 15:58 · tussenronde
- Herstart 12:32; **2.24.3 actief**. Demo/papier; geen knoppen, geen instellingen. Geen release. Logs: 3 koersopvragingen mislukt (IG time-out 1×, Bitvavo SUI/LINK geen bied/laat), afgevangen.
- **Goud 11:40-15:58:** Pepperstone 11 trades, **+297,63** → run 252, −440,56, PF 0,921, t −0,316; IG 13 trades, **−367,02** → 151, −809,17, PF 0,750, t −1,182 (stop geraakt 47,7 %). Clusters nog < 30 per broker → **geen toets**.
- **H-GS-14:** derde venster op rij tegengesteld (PP +298 / IG −367). Binnen de dag geen 'beide tegelijk'; toets op dagniveau (n=3 dagen).
- Mand: 576 trades (+2), netto −6.435,69 (−25,12), 16 open; *Resultaat per periode* unknown (L-GS-033, dagafsluiting 28-10).
- Latency p99: IG 1,26 / **PP 1,51** / mand 0,65 s - PP hoger dan vanochtend (0,90); n=1, volgen.
- Stilstand: alleen mand *Resultaat per periode* (L-GS-033, gepland).
- Hypotheses: H-GS-11 (kosten > bruto), H-GS-13 (→ L-GS-031, toets vr 30-10), H-GS-14.

laatste ronde: 27-10 15:58, gemeten t/m 27-10 15:58

## 27-10 19:41 · tussenronde
- Geen herstart sinds 12:32; **2.24.3 actief**. Demo/papier; geen knoppen, geen instellingen. Geen release. Logs: Bitvavo-koersopvragingen (geen bied/laat, AVAX onbruikbaar boek) 7×, telkens 1 van max. 3, afgevangen.
- **Goud 15:58-19:41:** Pepperstone 7 trades, **−36,95** → run 259, −477,51, PF 0,917, t −0,344; IG 9 trades, **+45,69** → 160, −763,48, PF 0,771, t −1,139 (stop 46,9 %). Clusters nog < 30 per broker → **geen toets**.
- **H-GS-14:** vierde venster op rij tegengesteld (PP −37 / IG +46). Binnen de dag nooit 'beide tegelijk'; toets op dagniveau (n=3 dagen).
- Mand: 576 trades, netto −6.435,69 (geen nieuwe trade), 16 open; *Resultaat per periode* unknown (L-GS-033, dagafsluiting 28-10).
- **Latency p99 PP 0,90 → 1,51 → 1,72 s** (11:40/15:58/19:41), IG 1,38, mand 0,59. Stijgt sinds de herstart van 12:32 zonder nieuwe herstart; volgen in de dagafsluiting (p99 per dag, n=1 dag).
- Stilstand: alleen mand *Resultaat per periode* (L-GS-033, gepland).
- Hypotheses: H-GS-11 (kosten > bruto), H-GS-13 (→ L-GS-031, toets vr 30-10), H-GS-14.

laatste ronde: 27-10 19:41, gemeten t/m 27-10 19:41

## 27-10 23:41 · tussenronde
- Herstarts 20:40 (installatie) en 21:01; **2.25.0 actief** (andere sessie 20:31, akkoord Ruud). Demo/papier; geen knoppen, geen instellingen. Geen release. DNS-storing 21:02-21:44 (extern): koersopvragingen mislukt (110×), entiteiten kort onbeschikbaar, afgevangen.
- **Goud 19:41-23:45:** Pepperstone 2 trades, **−133,62** → run 261, −611,13, PF 0,896, t −0,442; IG 3 trades, **+132,29** → 163, −631,19, PF 0,811, t −0,977 (stop 47,9 %). Clusters < 30 per broker → **geen toets**.
- **H-GS-14:** vijfde venster op rij tegengesteld (PP −134 / IG +132). Toets op dagniveau (dagafsluiting).
- **2.25.0 punt 4:** mand in noodstop sinds 21:03 (equity mand 3.653 < vloer 5.000; "geldt voor de hele mand") - zoals verwacht en geaccepteerd. Geen nieuwe mandtrades (576, −6.435,69), 16 open.
- **L-GS-031 eerste avond voldaan:** IG markt dicht 22:00, weer open 23:01 (was 24:00); 0 roosterwaarschuwingen op 27-10 (26-10: 2). Nog te toetsen: vr 30-10 sluiting 22:00.
- **Latency p99 PP 1,72 → 1,15 s** na de herstart van 21:01 (IG 1,26, mand 0,59): de stijging van vandaag hing aan de looptijd sinds de herstart (n=1 dag; dagafsluiting p99 per dag).
- Stilstand: alleen mand *Resultaat per periode* (L-GS-033, dagafsluiting 28-10).
- Hypotheses: H-GS-11 (kosten > bruto), H-GS-13 (→ L-GS-031, toets vr 30-10), H-GS-14.

laatste ronde: 27-10 23:41, gemeten t/m 27-10 23:45

## 28-10 03:40 · dagafsluiting 27-10
- 2.25.0 actief; **release 2.25.1** (03:59; L-GS-033: *Resultaat per periode* van de mand over de hele mand - alleen weergave; suite 2134 groen + 7 skip, workflow groen, HACS ververst; wacht op installatie). Demo/papier; geen knoppen, geen instellingen.
- **Goud 27-10 (handelsdag):** Pepperstone 60 trades, netto **−209,82** (bruto −47,17, kosten 162,65); IG 43 trades, **−250,80** (bruto −27,73, kosten 223,07). Bruto bij beide opnieuw negatief (26-10 ook); week 44 bruto PP −262 / IG −413.
- **Runs:** IG 165 tr / 18 cl, −719,60, PF 0,791, t −1,11; PP 275 tr / 27 cl, −659,73, PF 0,892, t −0,48. Nodig ≥ 30 cl per broker over ≥ 5 handelsdagen → **geen toets** (PP morgen mogelijk 30). Bij het huidige clustergemiddelde (−24, sd 267) zou PP ~480 clusters nodig hebben om het verschil van 0 te onderscheiden.
- **H-GS-14 op dagniveau:** zelfde teken PP/IG op 3 van 4 gezamenlijke dagen (22, 26, 27-10; 23-10 tegengesteld). 'Eén verliescluster per dag' 2 van 4 broker-dagen (IG 26-10, PP 27-10 = 2 nachtclusters 00:30-06:21 UTC −717); IG 27-10 verlies verdeeld over 4 clusters. → richting houdt, 'één cluster' niet; n=4 dagen.
- **L-GS-024 vervalt:** periodes-kosten = kosten-sensor (PP 731,65, IG 923,79; verschil 0,00).
- Mand: noodstop sinds 21:03 (vloer 5.000, equity 3.653-3.697) zoals verwacht; 4 open posities gesloten (576 → 580, +50,57), 12 open. Afstemming PP 1052/1052 (2 bedragen van de broker overgenomen), IG 456/456. L-GS-031: 0 roosterafwijkingen, IG 23:01 open.
- Latency p99 27-10: PP mediaan 0,97 s (max 1,76), mand 0,56, IG 0,81 (alleen actueel). Logs: DNS-storing 21:02-21:44 en losse cTrader/Bitvavo time-outs, afgevangen.
- Stilstand: alleen mand *Resultaat per periode* (→ 2.25.1). L-GS-011 (sluitmoment verdwenen positie) staat sinds 21-10 op gepland → volgende vrije dagafsluiting.
- Hypotheses: H-GS-11 (kosten > bruto; deze week ook bruto negatief), H-GS-13 (→ L-GS-031, toets vr 30-10 22:00), H-GS-14 (dagrichting gelijk 3/4; 'één cluster' verworpen als regel).

laatste ronde: 28-10 03:40, gemeten t/m 28-10 03:45

## 28-10 07:41 · tussenronde
- Herstarts 06:10 en 06:52 → **2.25.1 actief**. 2.25.2 (L-GS-011, andere sessie 07:13) workflow groen, maar HACS toonde nog 2.25.1 → HACS-informatie ververst (wacht op installatie). Demo/papier; geen knoppen, geen instellingen. Geen release.
- **Goud 03:45-07:45:** Pepperstone 3 trades, **+150,63** → run 278, −509,10, PF 0,917, t −0,37 (27 clusters); IG 5 trades, **−12,88** → 170, −732,48, PF 0,792, t −1,13 (18 clusters). Clusters < 30 per broker → **geen toets**. PP-run steunt op één cluster (+724; zonder: −1.233).
- **H-GS-14:** dit venster tegengesteld (PP + / IG −); toets op dagniveau in de dagafsluiting.
- **L-GS-033 geverifieerd:** mand *Resultaat per periode* gevuld (vandaag 4 trades +50,57; week 44 16 trades −45,08). Correctie op de dagafsluiting: de 4 sluitingen (576 → 580) vielen op **28-10 01:00**, niet op 27-10.
- Mand: noodstop blijft (equity 3.652-3.698 < vloer 5.000, zoals verwacht), 12 open. Logs: één Bitvavo-time-out (afgevangen).
- Latency p99: PP 1,11 s, IG 1,09, mand 0,51.
- Stilstand: **geen** (mand-periodes opgelost).
- Hypotheses: H-GS-11 (kosten > bruto), H-GS-13 (→ L-GS-031, toets vr 30-10 22:00), H-GS-14.

laatste ronde: 28-10 07:41, gemeten t/m 28-10 07:45

## 28-10 11:42 · tussenronde
- Herstart 10:25 → **2.25.2 actief** (L-GS-011 geïnstalleerd). Demo/papier; geen knoppen, geen instellingen. Geen release.
- **Goud 07:45-11:45:** Pepperstone 9 trades, **+34,24** → run 287, −474,86, PF 0,925, t −0,34; IG 11 trades, **−335,29** (cluster 19: 10 trades −373,15) → 181, −1.067,77, PF 0,729, t −1,47.
- **Eerste toetsbare run (PP, 30 clusters over 5 handelsdagen):** gem −15,8 per cluster, sd 254, 14/30 positief, t −0,34 → **geen edge aantoonbaar, niet van 0 te onderscheiden**; zonder grootste cluster −1.199. Bij dit gemiddelde zijn ~1.030 clusters nodig voor |t| = 2. IG 19 clusters (< 30): bij gem −56 zou ~35 clusters een negatieve uitslag kunnen tonen.
- Mand: noodstop blijft (equity 3.712 < vloer 5.000, zoals verwacht), 580 trades, 12 open. Logs: één Bitvavo-time-out (afgevangen).
- Latency p99 (1,3 u na herstart): PP 1,30 s, IG 1,47, mand 0,71 (07:41: 1,11/1,09/0,51) → hoger; per dag in de dagafsluiting.
- Stilstand: **geen** (mand *kosten gemeten* leeg = papiermodus, geen brokerkosten).
- Hypotheses: H-GS-11 (kosten > bruto), H-GS-13 (→ L-GS-031, toets vr 30-10 22:00), H-GS-14 (dagrichting; vandaag tot nu tegengesteld).

laatste ronde: 28-10 11:42, gemeten t/m 28-10 11:45

## 28-10 15:43 · tussenronde
- **2.25.2 actief**, geen herstart sinds 10:25. Demo/papier; geen knoppen, geen instellingen. Geen release.
- **Goud 11:45-15:45:** Pepperstone 13 trades, **+152,42** → run 300, −322,44, PF 0,951, t −0,23 (35 clusters: gem −9,2, sd 236, 18/35 positief; zonder grootste −1.046,63); IG 4 trades, **−28,55** → 185, −1.096,32, PF 0,729, t −1,39 (21 clusters, < 30 → geen toets).
- **Toets PP (35 clusters):** niet van 0 te onderscheiden; bij dit gemiddelde zijn ~2.600 clusters nodig voor |t| = 2 → een edge van deze grootte is met demo-data praktisch niet aan te tonen. IG: bij gem −52 / sd 172 ~43 clusters voor een negatieve uitslag.
- **H-GS-14:** vandaag tot nu PP **+234** (cl. 27-35) tegen IG **−402** (cl. 18-21, cluster 19 −473) → tegengesteld, zelfde markt en tijd; toets op dagniveau in de dagafsluiting.
- Mand: noodstop blijft (equity 3.646 < vloer 5.000, zoals verwacht), 582 trades, 10 open. Logs: Bitvavo-orderboek 2× onbruikbaar (WLD/XRP, afgevangen).
- Latency p99: PP 1,03 s, IG 1,21, mand 0,70 (11:42: 1,30/1,47/0,71) → weer lager na de herstart.
- Stilstand: **geen**.
- Hypotheses: H-GS-11 (kosten > bruto), H-GS-13 (→ L-GS-031, toets vr 30-10 22:00), H-GS-14 (dagrichting; vandaag tegengesteld).

laatste ronde: 28-10 15:43, gemeten t/m 28-10 15:45

## 28-10 19:43 · tussenronde
- **2.25.2 actief** (herstart 19:18). Demo/papier; geen knoppen, geen instellingen. Geen release.
- **Goud 15:45-19:45:** Pepperstone 9 trades, **−275,17** → run 309, −597,61, PF 0,915, t −0,43 (37 clusters: gem −16,2, sd 230, 17/37 positief; zonder grootste −1.321,80); IG 7 trades, **−22,08** → 192, −1.118,40, PF 0,733, t −1,37 (22 clusters, < 30 → geen toets).
- **Toets PP:** niet van 0 te onderscheiden; ~810 clusters nodig voor |t| = 2 bij dit gemiddelde. IG: ~47 clusters voor een negatieve uitslag (nu 22).
- **H-GS-11:** cluster 35 PP bruto +69,78 → netto −50,87 (9 trades, kosten 120,65). 19:33 zette de kostenregel `vp:donchian:15m` uit (n=40, netto −683,92; bruto dekt de kosten niet). De logregel toont dan `t=None` zonder de reden → kandidaat rapportageverbetering dagafsluiting (bruto/kosten in de logregel).
- **H-GS-14:** dag tot nu PP **−40,70** en IG **−497,90** → nu zelfde richting (15:43 nog tegengesteld). 18:15Z zelfde instapmoment: PP 1 trade −8,71, IG 3 trades −134,82.
- Mand: noodstop blijft (equity 3.685 < vloer 5.000), 582 trades, 10 open. Logs ~19:32 DNS-time-outs Bitvavo/IG (extern, afgevangen).
- Latency p99: PP 1,38 s, IG 1,36, mand 0,79 (↑ na de herstart van 19:18).
- Stilstand: **geen**.
- Hypotheses: H-GS-11 (kosten > bruto; kostenregel zet opzet uit), H-GS-13 (→ L-GS-031, toets vr 30-10 22:00), H-GS-14 (dagrichting; vandaag eerst tegengesteld, nu gelijk).

laatste ronde: 28-10 19:43, gemeten t/m 28-10 19:45
