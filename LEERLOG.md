# Leerlog Gold Scalper

Onderzoeksproject op IG-demo: edge van ruis onderscheiden. Alleen gemeten getallen; KPI's in KPI.csv.

## 07-10 · samenvatting dag (3 tussenronden 23:15-23:45, eerste baseline)
- Baseline 06/07-10: 56 trades / 7 clusters, netto −120,53 USD (bruto −18,65, kosten 101,88 = 1,82/trade), PF 0,651, winst 44,6 %; t netto −2,05, t bruto −0,24 → verlies uit de kosten; ~17 clusters nodig voor een bruto-toets.
- Slippage 3× de aanname (0,06 vs 0,02); latency p90 207 ms, p99 253 ms.
- Meetfout "geleerd" telde doel/stop op ruwe sluitreden → L-GS-001 gebouwd v1.7.1 (tussenronde, foute data). Klokafhankelijke tests → L-GS-002. H-GS-1 (doeltreffers 19,6 % < 40 %) gestart.

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

## 09-10 07:40 · tussenronde
- Geïnstalleerd: 1.7.10 (06:02), 1.8.0 (07:00), **1.8.1** (07:41; broker-dashboard, live koers via IG-streaming; chatsessie). Herstarts 06:03, 06:57, 07:02, 07:42; bij de laatste 1 trade in database open maar bij IG al dicht → afgestemd (`afstemming` in_orde).
- Sinds 03:45: **48 trades**, netto −14,58 = bruto +56,10 − kosten 70,69 (1,47/trade). Totaal 210 trades: netto −215,58 = bruto +105,29 − kosten 320,88; PF 0,69; winst 37,6%; t −2,88 (16 clusters). Geen conclusie.
- **Clusterteller staat stil:** cluster 16 loopt sinds 22:01 UTC door — 87 trades in 461 min (41% van alle trades), netto +0,63, bruto +132,50. Met tijdstops volgt de herinstap steeds < 10 min, dus komt er geen nieuw cluster bij. Gevolg: t-cluster en het beslismoment van L-GS-005 (≥ 10 clusters in het tijdstopregime, nu 6) komen niet dichterbij, hoeveel trades er ook bijkomen. → L-GS-007 (zelf bouwen: extra maat, bestaande t en oordeel ongewijzigd).
- **L-GS-005 / H-GS-7:** regime `tijdstop` 142 trades / 6 clusters: netto −0,11/trade (t −0,51, PF 0,94), bruto +1,32/trade tegen kosten 1,43/trade — patroon ongewijzigd: bruto ≈ kosten.
- **H-GS-8 (latency):** p99 1306 ms (was 1067); venster (~2000 rondes ≈ 02:10-07:45) bevat 4 herstarts, dus geen schone toets. p99 candles→exits 514, signal→bookkeeping 467, exits→signal 369, start→quote 353. Antwoord op de vraag van 03:40: p99 beweegt wel (geen bevroren waarde).
- Nieuw (1.8.1): 1× WARNING "live koers via IG-streaming niet beschikbaar (verbinding verbroken door de server); dashboard ververst elke 5 s" — handel niet geraakt; volgen of het blijft.
- Noodstop sinds 1.7.9: 0×. Sluitreden onbekend 1,9%, kosten gemeten 96,2%.
- Geen release (tussenronde). Geen knoppen, geen instellingen.

laatste ronde: 09-10 07:40, gemeten t/m 09-10 07:45

## 09-10 11:40 · tussenronde
- Geïnstalleerd: **1.9.1** (1.9.0 meerdere posities + 1.9.1 live koers; chatsessie 08:27). HA-herstarts 10:09, 10:40 (lifecycle reconciling → running). Demo.
- **Run 100 afgesloten om 10:07** (1.9.0 start run 101 om 10:09): eindstand 239 trades / 16 clusters, netto −262,99 = bruto +92,48 − kosten 355,47; t −3,28. Sinds 07:45 nog 29 trades: netto −47,41, bruto −12,81, kosten 34,59 (1,19/trade).
- **Run 101 = nieuwe regel (besluit Ruud 09-10):** tot 3 posities per richting, long en short naast elkaar; gelijktijdige trades vallen in één cluster. Tot 11:44: 7 trades in 1 cluster (10:11-10:45), netto −20,61, bruto −10,29, kosten 10,32; 5 tijdstops, 2 stops. 165 signalen geweigerd omdat er in dezelfde candle al een long opende. Niet vergelijkbaar met run 100 → aparte baseline.
- **Gevolg L-GS-005:** het tijdstopregime van run 100 bleef op 6 clusters staan (142 trades: netto −0,11/trade, bruto +1,32, kosten 1,43). Het beslismoment "≥ 10 clusters" kan in run 100 niet meer gehaald worden; in run 101 meten gelijktijdige posities als één cluster. Wat het beslismoment nu wordt is aan Ruud (zie VOORSTELLEN). L-GS-007 (tijdblokken) wordt daardoor belangrijker.
- **L-GS-004 werkt:** 11:26 afstemming corrigeerde een uitstap (4194,89 → 4199,83 bij IG; −9,82 → −1,21). Afstemming in_orde; sluitreden onbekend 0/7; kosten gemeten 5/7 (recente trades berekend, zo ontworpen).
- **H-GS-8 (latency):** p99 1044 ms, p50 222 (n=2000, venster met 2 herstarts) → geen schone toets; staart weer in candles→exits (495) en signal→bookkeeping (405).
- Noodstop sinds 1.7.9: 0×. Geen release (tussenronde). Geen knoppen, geen instellingen.

laatste ronde: 09-10 11:40, gemeten t/m 09-10 11:45

## 09-10 15:40 · tussenronde
- Geïnstalleerd: **1.9.4** (1.9.2 schaduwtrades op echte ordergrootte, 1.9.4 daglimiet/vermogensvloer over de startbalans; chatsessies). HA-herstarts 12:10, 12:24, 12:39, 12:50, 13:53, 14:42 (lifecycle sluit netjes af). Demo, handel aan; geen knoppen gebruikt.
- Run 101 t/m 15:44: **40 trades / 3 clusters**, netto −58,57, bruto +7,41, kosten 65,98 (1,65/trade); PF 0,43, winst 35 %, t −2,13; alle 40 in regime `tijdstop`. Sinds 11:45: 33 trades (cluster 2: 30 trades 13:00-14:49, cluster 3: 3), netto −37,96 = bruto +17,70 − kosten 55,66 (1,69/trade). H-GS-7 onveranderd: bruto ≈ 0,5/trade tegen kosten ≈ 1,7/trade.
- Cluster 2 bevat 75 % van de trades; met meerdere posities per richting groeien clusters (30 trades in 109 min). Bij ~3 clusters/dag duurt een t-toets op ~18 clusters ≈ 6 handelsdagen. L-GS-007 (tijdblokken) wordt belangrijker.
- Schaduwtrades (1.9.2): 7 (allemaal reden `cooldown`), netto −32,27, PF 0,14, 4 clusters — n veel te klein.
- **Sluitreden onbekend 2/40 (5 %)** (was 0/7 om 11:40; run 100 1,9 %), bij 6 herstarts in 3 uur. H-GS-9 (nieuw): onbekend-aandeel hangt aan herstarts; toetsen op een dag zonder installaties. Afstemming `in_orde`. Kosten gemeten 90 %.
- Latency p99 980 ms, p50 194 (n=2000, venster met herstarts → geen schone H-GS-8-toets); staart signal→bookkeeping 323, exits→signal 270, candles→exits 266.
- Noodstop 0×. Geen release (tussenronde).

laatste ronde: 09-10 15:40, gemeten t/m 09-10 15:45

## 09-10 19:40 · tussenronde
- Geïnstalleerd: **1.9.5** (L-GS-007 tijdblokken + L-GS-008 tijdstopvarianten). HA-herstarts 16:16-19:29 (7). Demo, handel aan, status wachtend; geen knoppen gebruikt. Noodstop 0×, dataprobleem uit.
- Run 101 t/m 19:44: **53 trades / 5 clusters**, netto −60,52, kosten 81,56 → bruto +21,04; PF 0,49, winst 36 %, t −1,77; alles regime `tijdstop`. Sinds 15:44: 13 trades, netto −1,95 = bruto +13,63 − kosten 15,58 (1,20/trade).
- **L-GS-007 werkt:** 6 uurblokken (08-15 UTC), t_netto −1,82, t_bruto +0,73, lag-1 netto 0,28. Per sessie: Londen 3 blokken netto −55,41 (bruto +5,67), New York 3 blokken netto −5,11 (bruto +15,38, t_bruto 1,70). Langste cluster 109 min (< 120). n = 6 blokken: geen conclusie; ~20 blokken nodig.
- **L-GS-008 werkt:** 4 volledig nagespeelde trades, 240-s-variant komt 4/4 overeen met de echte trade (gem. verschil −0,05). Langere tijdstops 480/720/geen: −0,27/−1,04/−1,31 per trade t.o.v. 240 (1 blok, t n.v.t.). Oordeel pas bij ≥ 20 uurblokken.
- H-GS-7 (bruto < kosten) houdt: bruto 0,40/trade tegen kosten 1,54/trade over run 101. H-GS-9: sluitreden onbekend 2/53 (3,8 %), geen nieuwe sinds 15:44 ondanks 7 herstarts. Kosten gemeten 96,2 %. Latency p99 890 ms (venster met herstarts). Afstemming in_orde.
- Geen release (tussenronde).

laatste ronde: 09-10 19:40, gemeten t/m 09-10 19:44

## 09-10 23:40 · tussenronde
- Geïnstalleerd: 1.9.5. HA-herstarts 19:48, 20:53, 22:43 (lifecycle sluit netjes af). Demo, handel aan; markt sinds vrijdag 23:00 dicht (weekend). Geen knoppen gebruikt. Noodstop 0×.
- Run 101 t/m 23:00: **64 trades / 6 clusters**, netto −80,10, bruto +18,09, kosten 98,19; PF 0,44, winst 35,9 %, t −2,34. Sinds 19:44: 11 trades (20:00-20:48, één uurblok), netto −19,58 = bruto −2,95 − kosten 16,63 (1,51/trade).
- L-GS-007 tijdblokken: 7 blokken, t_netto −2,34, **t_bruto +0,62**; Londen bruto +5,67 (3 blokken), New York bruto +12,42 (4, t_bruto 1,06). H-GS-7 (bruto < kosten) houdt: bruto 0,28/trade tegen 1,53 kosten. Geen conclusie bij 7 van ~20 blokken.
- L-GS-008: 15 volledige trades, 240-s-variant 93,3 % gelijk aan echt (zelfde sluitreden 100 %); 480/720/geen −0,28/−0,75/−0,89 per trade t.o.v. 240 (2 blokken). Langere tijdstop tot nu slechter; oordeel bij ≥ 20 blokken.
- **Vrijdagsluiting gemeten:** broker meldde 22:47:20-23:00 21 keer wisselend open/dicht (rooster: open tot 23:00) → 1 WARNING "… feestdag of vervroegde sluiting"; geen trades in die periode (sluitbuffer). **H-GS-10 (nieuw):** IG sluit spot goud op vrijdag in de praktijk ~13 min vóór 23:00 met een flikkerende `marketState`. Toets vrijdag 16-10; geen risico (gesloten wint), wel een misleidende meldtekst.
- **L-GS-002 geverifieerd:** volledige suite tijdens gesloten markt (23:4x) groen: 1991 passed, 5 skipped (6 min 50 s).
- Sluitreden onbekend 2/64 (3,1 %), kosten gemeten 96,9 %, latency p99 826 ms / p50 185 (venster met 3 herstarts). Afstemming in_orde. Geen release (tussenronde).

laatste ronde: 09-10 23:40, gemeten t/m 09-10 23:50

## 10-10 03:40 · dagafsluiting 09-10
- Markt dicht sinds vrijdag 23:00 (weekend); demo, handel aan, geen knoppen gebruikt. Sinds 23:50 geen trades of wijzigingen.
- Dag 09-10 (lokaal): **180 trades** (run 100 tot 10:07: 116; run 101: 64), netto −126,88 = bruto +137,78 − kosten 264,66 → per trade −0,70 / +0,77 / 1,47. H-GS-7 (bruto < kosten) houdt over de hele dag.
- Run 101 (tot 3 posities per richting): 64 trades / 6 clusters / 7 uurblokken: netto −80,10, bruto +18,09 (+0,28/trade) tegen kosten 98,19 (1,53/trade); PF 0,44; t_cluster −2,34; uurblokken t_netto −2,34, t_bruto +0,62, lag-1 netto 0,20. Londen bruto +5,67 (3 blokken), New York +12,42 (4). **Geen conclusie:** 7 van ~20 blokken; bij sd van nu is t_bruto 2 pas bij ~70 blokken haalbaar als de bruto-edge per blok +2,6 blijft — d.w.z. netto blijft negatief zolang kosten/blok ~14 zijn.
- L-GS-008: 15 nagespeelde trades, 240-s-variant 93,3 % gelijk; langere tijdstops slechter (480 −0,28, 720 −0,75, geen −0,89 per trade; 2 blokken). NB: `t_blokken` −2,0/−3,9/−4,7 bij 2 blokken (df 1) is geen toets; de sensor zegt zelf "te weinig blokken".
- H-GS-7-toets (eerste instap per cluster tegen herinstappen) niet gedaan: trade-niveau staat niet in diagnostics/attributen (alleen samenvattingen) → meetbaarheid; kandidaat-attribuut `bruto_eerste_instap_vs_herinstap` bij een volgende dagafsluiting met handel.
- H-GS-10 (vrijdagsluiting ~13 min vroeg, flikkerende marketState) toets vrijdag 16-10. Geen release (geen gepland punt, geen bug; weekend).

laatste ronde: 10-10 03:40, gemeten t/m 10-10 03:46

## 10-10 07:40 · tussenronde
- Weekend: status `markt_gesloten`, demo, handel aan, open posities 0, noodstop/dataprobleem uit, afstemming in_orde. Geen knoppen gebruikt. Geen trades sinds vrijdag 23:00 → run 101 ongewijzigd (64 trades / 6 clusters, netto −80,10, t −2,34, PF 0,44).
- Logboek sinds 03:46: geen nieuwe Gold Scalper-meldingen. Latency p99 242 ms (gesloten markt, geen handelscycli → geen toets).
- Meetbaarheid: `max_drawdown` 0,0 % is afronding (−80 op een demosaldo van ~10 mln = 0,0008 %); in % zegt hij op dit account niets — volgen of een absolute drawdown nodig is (geen voorstel nu).
- Hypotheses H-GS-7 (bruto < kosten), H-GS-10 (vrijdagsluiting, toets 16-10) ongewijzigd. Geen release.

laatste ronde: 10-10 07:40, gemeten t/m 10-10 07:44

## 10-10 11:40 · tussenronde
- Weekend: `markt_gesloten`, demo, handel aan, open posities 0, noodstop/dataprobleem uit. Geen knoppen gebruikt. Geïnstalleerd **1.9.6**; 1.10.0 (chatsessie 11:42: afstemming bewaard, sluitreden achteraf) nog niet. HA-herstarts 08:20, 08:44, 09:18, 10:52. Run 101 ongewijzigd (64 trades / 6 clusters, netto −80,09, PF 0,436, t −2,34).
- **Gevonden (acuut) → L-GS-009, gebouwd 1.10.1:** `max_drawdown` 99,9 % sinds 08:20. Bij een mislukte accountopvraging schreef de cyclus de startbalans (10.000) als equitypunt weg; tegen ~10 mln demo-equity is dat 99,9 %. Nu alleen gemeten equity; oude terugvalpunten tellen niet. Geen strategie- of risicowijziging. Suite 2025 groen, workflow groen, HACS ververst. (Meetbaarheidspunt van 07:40 over 0,0 % afronding blijft: in % zegt het op dit account weinig.)
- Afstemming `nog_niet` na de herstart van 10:52 (in 1.9.6 niet bewaard; 1.10.0 lost dat op).
- Hypotheses H-GS-7 (bruto < kosten, ~20 uurblokken nodig; nu 7), H-GS-10 (vrijdagsluiting, toets 16-10) ongewijzigd.

laatste ronde: 10-10 11:40, gemeten t/m 10-10 11:50

## 10-10 15:40 · tussenronde
- Weekend: `markt_gesloten`, demo, handel aan, open posities 0, noodstop/dataprobleem uit, oordeel `insufficient_data`. Geen knoppen gebruikt. Geïnstalleerd **1.10.0** (12:04) en **1.10.1** (13:37). HA-herstarts 12:04, 13:37, 14:41. Run 101 ongewijzigd (64 trades / 6 clusters, netto −80,10, PF 0,436, t −2,34).
- **L-GS-009 geverifieerd:** `max_drawdown` 99,9 → **0,0 %** om 13:37 en blijft 0,0 na de herstart van 14:41.
- 1.10.0 eerste meetpunten: sluitreden onbekend 3,1 → **0,0 %** (2 trades achteraf ingevuld), afstemming `in_orde` sinds 12:04 en bewaard over 2 herstarts (was `nog_niet` na elke herstart). Kosten gemeten 96,9 %.
- Hypotheses H-GS-7 (bruto < kosten, ~20 uurblokken nodig; nu 7), H-GS-10 (vrijdagsluiting, toets 16-10) ongewijzigd. Geen release.

laatste ronde: 10-10 15:40, gemeten t/m 10-10 15:45

## 10-10 19:40 · tussenronde
- Weekend: `markt_gesloten`, demo, handel aan, open posities 0, noodstop/dataprobleem uit, oordeel `insufficient_data`. Geen knoppen gebruikt. Geïnstalleerd 1.10.1. Run 101 ongewijzigd (64 trades / 6 clusters, netto −80,10, PF 0,436, t −2,34).
- 3 HA-herstarts (16:19, 16:40, 18:07): afstemming bleef `in_orde`, max. drawdown 0,0 %, sluitreden onbekend 0,0 % → 1.10.0/1.10.1 houden over herstarts.
- **Gevonden:** 19:27 1× ERROR "Unexpected error fetching gold_scalper data" met traceback: IG antwoordde niet binnen 15 s op GET /positions. De koersopvraging vangt een `VenueError` af (laatste beeld vasthouden, niets beslissen); de positie-voorcheck (`_open_positions` in `_async_update_data`) niet → de hele cyclus faalt als onverwachte fout. Geen schade (weekend, geen beslissing), wel foute classificatie → **L-GS-010** (gepland, zelf bouwen: foutafhandeling, geen strategiewijziging), bouwen in een dagafsluiting.
- Latency p99 273 ms (gesloten markt, geen toets). Hypotheses H-GS-7 (bruto < kosten; 7 van ~20 uurblokken), H-GS-10 (vrijdagsluiting, toets 16-10) ongewijzigd. Geen release.

laatste ronde: 10-10 19:40, gemeten t/m 10-10 19:45

## 10-10 23:40 · tussenronde
- Weekend: `markt_gesloten`, demo, handel aan, open posities 0, noodstop/dataprobleem uit, oordeel `insufficient_data`. Geen knoppen gebruikt. Geïnstalleerd 1.10.1. Run 101 ongewijzigd (64 trades / 6 clusters, netto −80,10, PF 0,436, t −2,34).
- 2 HA-herstarts (19:47, 20:25): afscheid netjes gelogd, afstemming `in_orde`, max. drawdown 0,0 %, sluitreden onbekend 0,0 % → houdt over herstarts. Logboek sinds 19:27: geen nieuwe Gold Scalper-fouten (L-GS-010 eenmalig, blijft gepland).
- Latency p99 408 ms (was 273; gesloten markt, geen handelscycli → geen toets).
- Hypotheses H-GS-7 (bruto < kosten; 7 van ~20 uurblokken), H-GS-10 (vrijdagsluiting, toets 16-10) ongewijzigd. Geen release.

laatste ronde: 10-10 23:40, gemeten t/m 10-10 23:45

## 11-10 03:40 · dagafsluiting 10-10
- Zaterdag, markt dicht: 0 trades, demo, handel aan, geen knoppen. Geïnstalleerd 1.10.1. 12 HA-herstarts (08:20-20:25), netjes afgesloten. Recorder: automation 03:00 purge (o.a. Gold Scalper latency p99, status, evaluaties nu uitgesloten) + repack → historie van die sensoren is niet meer meetbaar, alleen de actuele stand.
- Dag 10-10 gemeten: drawdown 317 min fout (99,9 % tot 13:37, daarna 0,0 door 1.10.1); afstemming `nog_niet` 08:20-12:04, daarna `in_orde` over 9 herstarts (1.10.0); dataprobleem 2× 10 s (00:08, 00:14); 1 "Unexpected error" 19:27 (entiteiten 11 s onbeschikbaar). Latency p99 253 / p50 183 ms (gesloten markt, geen toets).
- **Handelsweek 06-10..09-10:** 303 trades, netto −343,09 = bruto +110,57 − kosten 453,66 → per trade −1,13 / +0,37 / 1,50; kosten 4,1× het bruto. Netto/trade per dag −1,61 → −1,43 → −0,70 (tijdstops vanaf 08-10). t_cluster run 100 −3,28 (16), run 101 −2,34 (6). Netto-verlies is aangetoond; een bruto-edge niet: run 101 t_bruto 0,62 bij 7 blokken, ~73 blokken nodig bij deze sd.
- H-GS-7 (bruto < kosten): houdt over de hele week (0,37 tegen 1,50/trade). H-GS-9 (sluitreden onbekend door herstarts) gesloten: 1.10.0 vult achteraf in, 0,0 % na 12 herstarts. H-GS-10 (vrijdagsluiting ~13 min vroeg): toets vr 16-10.
- **L-GS-010 gebouwd als 1.10.2** (voorcheck-time-out → laatste beeld vasthouden, niets beslissen; suite 2031 groen, 6 nieuwe tests), maar **niet gereleased**: push naar main geweigerd door de toestemmingscontrole. Patch in `analyse/2026-10-11-L-GS-010/`. Geen HACS-verversing.

laatste ronde: 11-10 03:40, gemeten t/m 11-10 03:45

## 11-10 07:40 · tussenronde
- Zondag, markt dicht (opent zo ~23:00): `markt_gesloten`, demo, handel aan, open posities 0, noodstop/dataprobleem uit, oordeel `insufficient_data`. Geen knoppen gebruikt. Geïnstalleerd 1.10.1 (geen nieuwere release; 1.10.2 ligt als patch klaar, L-GS-010). Run 101 ongewijzigd (64 trades / 6 clusters, netto −80,10, PF 0,436, t −2,34).
- Geen HA-herstart sinds 20:26; afstemming `in_orde`, max. drawdown 0,0 %, sluitreden onbekend 0,0 %. Logboek 03:45-07:45: 0 Gold Scalper-fouten. Latency p99 258 ms (gesloten markt, geen toets).
- Hypotheses H-GS-7 (bruto < kosten; 7 van ~20 uurblokken, ~73 nodig voor een bruto-toets), H-GS-10 (vrijdagsluiting, toets 16-10) ongewijzigd. Geen release (L-GS-010 niet acuut: bij een time-out beslist de cyclus niets; wacht op de dagafsluiting/toestemming).

laatste ronde: 11-10 07:40, gemeten t/m 11-10 07:45

## 11-10 11:40 · tussenronde
- Zondag, markt dicht (opent ~23:00): `markt_gesloten`, demo, handel aan, open posities 0, noodstop/dataprobleem uit, oordeel `insufficient_data`. Geen knoppen gebruikt. Geïnstalleerd 1.10.1. Run 101 ongewijzigd (64 trades / 6 clusters, netto −80,10, PF 0,436, t −2,34).
- HA-herstarts 08:40 en 10:15: afstemming bleef `in_orde`, max. drawdown 0,0 %, sluitreden onbekend 0,0 % → houdt. Logboek 07:45-11:40: 0 Gold Scalper-fouten. Latency p99 328 ms (gesloten markt, geen toets).
- L-GS-010 (1.10.2, time-out positie-voorcheck) ligt als patch klaar; niet acuut zolang de markt dicht is. Eerste handelsnacht (zo 23:00 →) is de eerste kans op een nieuwe time-out → tellen in de dagafsluiting.
- Hypotheses H-GS-7 (bruto < kosten; 7 van ~73 uurblokken voor een bruto-toets), H-GS-10 (vrijdagsluiting, toets 16-10) ongewijzigd. Geen release.

laatste ronde: 11-10 11:40, gemeten t/m 11-10 11:40

## 11-10 15:40 · tussenronde
- Zondag, markt dicht (opent ~23:00): `markt_gesloten`, demo, handel aan, open posities 0, noodstop/dataprobleem uit, oordeel `insufficient_data`. Geen knoppen gebruikt. Geïnstalleerd 1.10.1. Run 101 ongewijzigd (64 trades / 6 clusters, netto −80,10, PF 0,436, t −2,34).
- 20 HA-herstarts 11:47-15:33 (supervisor): afstemming bleef `in_orde`, max. drawdown 0,0 %, sluitreden onbekend 0,0 % → houdt ook bij veel herstarts. 0 Gold Scalper-fouten. Latency p99 830 ms (gesloten markt + herstarts, geen toets).
- L-GS-010 (1.10.2) ligt als patch klaar; eerste handelsnacht → tellen in de dagafsluiting.
- Hypotheses H-GS-7 (bruto < kosten), H-GS-10 (vrijdagsluiting, toets 16-10) ongewijzigd. Geen release.

laatste ronde: 11-10 15:40, gemeten t/m 11-10 15:40

## 11-10 19:40 · tussenronde
- Zondag, markt dicht (opent ~23:00): `markt_gesloten`, demo, handel aan, open posities 0, noodstop/dataprobleem uit, oordeel `insufficient_data`. Geen knoppen gebruikt. Geïnstalleerd 1.10.1. Run 101 ongewijzigd (64 trades / 6 clusters, netto −80,10, PF 0,436, t −2,34).
- 10 HA-herstarts 15:49-18:09: afstemming bleef `in_orde`, max. drawdown 0,0 %, sluitreden onbekend 0,0 %. 0 Gold Scalper-fouten. Latency p99 783 ms (gesloten markt + herstarts, geen toets).
- L-GS-010 (1.10.2) ligt als patch klaar (main nog b3be347); eerste handelsnacht → time-outs tellen in de dagafsluiting.
- Hypotheses H-GS-7 (bruto < kosten), H-GS-10 (vrijdagsluiting, toets 16-10) ongewijzigd. Geen release.

laatste ronde: 11-10 19:40, gemeten t/m 11-10 19:45

## 11-10 23:40 · tussenronde
- Zondagavond, markt nog dicht (`markt_gesloten`); demo, handel aan, open posities 0, noodstop/dataprobleem uit, oordeel `insufficient_data`. Geen knoppen gebruikt. Run 101 ongewijzigd (64 trades / 6 clusters, netto −80,10, PF 0,436, t −2,34).
- **1.10.2 (L-GS-010) gereleased 21:00 en actief sinds de herstart van 23:31.** 8 herstarts 21:02-23:31: afstemming `in_orde`, max. drawdown 0,0 %, sluitreden onbekend 0,0 %. 0 Gold Scalper-fouten. Latency p99 279 ms (gesloten markt).
- Eerste handelsnacht onder 1.10.2 → voorcheck-time-outs tellen in de dagafsluiting.
- Hypotheses H-GS-7 (bruto < kosten), H-GS-10 (vrijdagsluiting, toets 16-10) ongewijzigd. Geen release.

laatste ronde: 11-10 23:40, gemeten t/m 11-10 23:45

## 12-10 03:40 · dagafsluiting 11-10
- Zondag 11-10 (lokaal): markt dicht, 0 trades, 40 HA-herstarts; afstemming `in_orde`, drawdown 0,0 %, sluitreden onbekend 0,0 % over alle herstarts. 0 Gold Scalper-fouten. Geen knoppen gebruikt. Geïnstalleerd nu **1.10.3** (03:33; release van een andere sessie 03:31).
- **Eerste handelsnacht (ma 00:15-02:19):** 14 trades, netto −17,28 = bruto +8,21 − kosten 25,49 → per trade −1,23 / +0,59 / 1,82 (7d: −1,13 / +0,37 / 1,50). Run 101: 78 trades / 8 clusters, netto −97,38, PF 0,472, t_cluster −2,86 (bruto +0,99); 10 uurblokken t_netto −2,08, t_bruto +0,70 → ~83 blokken voor een bruto-toets.
- **Storing 02:21:52-03:21:44:** 360× "Unexpected error" (TypeError in `sort()` bij twee transacties met gelijk openLevel, terwijl het overzicht trade 78 nog niet had). Integratie 60 min onbeschikbaar: geen instap, geen positiebeheer. Enige open positie (78) was al door IG gesloten → geen onbewaakte positie. Hield op toen IG de transactie toonde; fix 1.10.3 (andere sessie).
- **Gevonden (meetfout):** trade 78 kreeg als sluittijd het moment van ontdekken (03:21:54) i.p.v. de brokertijd (~02:21:50): looptijd ~62 min i.p.v. ~2,5 min, cluster 8 66,9 min. `_settle_vanished_positions` → `_record_broker_close` gebruikt `now`; `dateUtc` uit het transactieoverzicht wordt alleen bij latere correcties gebruikt. → **L-GS-011** gebouwd en getest (suite 2036 groen, 4 nieuwe tests), niet gereleased (al een release vandaag; niet acuut). Patch `analyse/2026-10-12-L-GS-011/sluitmoment.patch`; bewerken van de main-checkout werd door de toestemmingscontrole geweigerd → gebouwd in een kopie.
- L-GS-010: 0 voorcheck-time-outs in de nacht → nog niet getoetst. Nieuw voorstel **L-GS-012** (open): een fout in de afwikkeling van één trade legt nu de hele cyclus stil (zoals 02:21-03:21).
- Tijdstopvarianten: 4 blokken, 240-overeenkomst 92,9 %; 720 s +1,10/trade (t 0,94) → geen oordeel (<20). Latency p99 667 / p50 188 ms (handel + herstart).
- H-GS-7 (bruto < kosten) houdt (0,59 tegen 1,82). H-GS-10 (vrijdagsluiting) toets 16-10. Geen release.

laatste ronde: 12-10 03:40, gemeten t/m 12-10 03:45

## 12-10 07:40 · tussenronde
- Maandag, markt open; demo, handel aan, 1 open positie, noodstop/dataprobleem uit, afstemming `in_orde`, drawdown 0,0 %, sluitreden onbekend 0,0 %. Geen knoppen gebruikt. 1.10.3 actief; 2 HA-herstarts (06:14, 06:48) met open-positie-afsluitmelding, daarna netjes verder. 0 Gold Scalper-fouten sinds 03:21:44 (storing L-GS-012 niet herhaald).
- **Sinds 03:45: 14 trades** (uurblokken 04 en 05 UTC): netto −35,56 = bruto −18,15 − kosten 17,41 → per trade −2,54 / −1,30 / 1,24. Ook bruto negatief deze ochtend.
- Run 101: **92 trades / 9 clusters**, netto −132,94, PF 0,412, winst 34,8 %, **t_cluster −3,24**; 12 uurblokken t_netto −2,73, bruto +8,15 (+0,68/blok, t_bruto 0,20). Per sessie bruto/blok: Azië −0,35, Londen +1,89, New York +0,78 (n=3-5, geen oordeel).
- n-toets: netto is al duidelijk negatief (t −3,2 bij 9 clusters). Of er bruto een edge is: bij het huidige gemiddelde (+0,68/blok, sd ~12) zijn ~1200 uurblokken nodig voor t = 2 → bruto niet van ruis te onderscheiden; H-GS-7 (bruto < kosten) houdt.
- L-GS-010: 0 voorcheck-time-outs (log) → nog niet getoetst. Latency p99 658 ms (herstarts). L-GS-011 klaar als patch voor 13-10.
- Hypotheses H-GS-7 (bruto < kosten), H-GS-10 (vrijdagsluiting, toets 16-10). Geen release.

laatste ronde: 12-10 07:40, gemeten t/m 12-10 07:42

## 12-10 11:40 · tussenronde
- Demo, handel aan, 1 open positie, noodstop/dataprobleem uit, afstemming `in_orde`, sluitreden onbekend 0,0 %. Geen knoppen gebruikt. 1.10.3 actief. 7 HA-herstarts (08:26-10:53) netjes afgesloten (administratie weggeschreven), 0 Gold Scalper-fouten.
- **Sinds 07:42: 22 trades** (5 nog in cluster 9, cluster 10 = Londen 10:15-11:35 lokaal, 17 trades): netto −23,00 = bruto +9,33 − kosten 32,32 (1,47/trade). Cluster 10 bruto +11,39, netto −13,73.
- Run 101: **114 trades / 10 clusters**, netto −155,94, PF 0,407, winst 33,3 %, **t_cluster −3,34**. Bruto per cluster +1,75 (sd 11,6, t 0,47) → ~177 clusters nodig om een bruto-edge van deze grootte aan te tonen; netto is al duidelijk negatief. H-GS-7 (bruto < kosten) houdt: bruto 17,48 tegen kosten 173,41.
- Tijdstopvarianten 8/20 blokken, overeenkomst 96,9 %; 240 s blijft het beste (720 −0,19/trade, geen tijdstop −0,69) → geen oordeel.
- Latency p99 791 ms (p50 215, max 5,6 s) door de herstarts. L-GS-010: 0 voorcheck-time-outs → nog niet getoetst. L-GS-011 klaar voor 13-10.
- Hypotheses H-GS-7 (bruto < kosten), H-GS-10 (vrijdagsluiting, toets 16-10). Geen release.

laatste ronde: 12-10 11:40, gemeten t/m 12-10 11:45

## 12-10 15:40 · tussenronde
- **Strategiewissel (chatsessie, besluit Ruud):** 2.0.0 daghandel (L-GS-014) 14:43, 2.0.1 15:00, **2.1.0 combinatie daghandel + scalpen** (L-GS-015) 15:42, 2.1.1 15:56 (nog niet actief). Run 101 afgesloten 15:04 → runs 102-104 → **run 105 sinds 15:46**. Hervatten-knop om 15:09 gebruikt (niet door deze ronde); logregel "Handmatige hervatting na: None" mist de reden.
- **Slot run 101 (scalpen):** 128 trades, netto −196,66 (−1,54/trade); 11:45-14:41 nog 14 trades, netto −40,72 (−2,91/trade). H-GS-7 (bruto < kosten) bevestigd en gesloten met de strategie.
- Run 105 t/m 15:55: 3 scalptrades (netto −0,99, bruto +1,10, kosten 2,09), 0 daghandeltrades, 1 scalppositie open. Geen oordeel. Toetsregel daghandel: ≥ 100 trades en t ≥ 2 over handelsdagen → bij 1-3 per dag ~35-100 handelsdagen. De oordeeltekst noemt nog "sub-minuut handel" (scalpwoorden).
- **Gevonden:** de optie *Piramide* staat aan (WARNING bij elke start, ook 15:46). Bij daghandel genegeerd, bij de combinatie weer actief voor scalpposities, terwijl bijkopen niet in administratie/afstemming komt → **L-GS-016 (open)**: optie uit.
- Afstemming `in_orde`, drawdown 0,0 %, noodstop/dataprobleem uit, demo. Latency p99 736 ms (herstarts). 0 Gold Scalper-fouten.
- **L-GS-011** opnieuw op 2.1.1 gezet (conflict met 1.11.0 opgelost); volledige suite 2077 groen, 5 skipped; release als 2.1.2 in de dagafsluiting van 13-10.
- Hypotheses: H-GS-10 (vrijdagsluiting, toets 16-10); nieuw **H-GS-11**: daghandelkosten ≈ 20 % van de beweging (backtest) → per daghandeltrade kosten/ATR meten. Geen release (chatsessie releaset vandaag al 4×).

laatste ronde: 12-10 15:40, gemeten t/m 12-10 15:55

## 12-10 19:40 · tussenronde
- **2.2.0 (16:10) en 2.2.1 (18:31) door de chatsessie**, geïnstalleerd (actief 2.2.1, herstarts 16:12 en 18:35). 2.2.0 legt bijkopen vast als eigen trade ("pyramide van <ticket>", besluit Ruud: "moet actief zijn"); WARNING "Piramide staat aan…" sinds 16:11 weg → **L-GS-016 vervallen** (Ruud koos vastleggen i.p.v. uitzetten).
- Run 105 (combinatie) t/m 19:46: **35 trades, alle scalp, 0 daghandel** ("wachten op een uitbraak in de richting van de uurtrend"). Sinds 15:55 32 trades: netto −19,67. Run 105: netto −20,66 = bruto +1,14 − kosten 21,80 → per trade −0,59 / +0,03 / **0,62** (run 101: 1,36/trade; kleinere scalpgrootte 1 oz). PF 0,459, winst 34,3 %, t per trade −1,52, t_cluster −1,76 (3 clusters), 4 uurblokken t_netto −1,92 / t_bruto 0,21. Geen oordeel (n te klein); ook met de halve kosten blijft bruto ≈ 0 → hetzelfde beeld als H-GS-7.
- Sluitredenen: tijdstop 29, take-profit 2, stop 2, broker gemeten 2; sluitreden onbekend 0,0 %, afstemming `in_orde`, drawdown 0,0 %, noodstop/dataprobleem uit, demo. Geen knoppen gebruikt.
- Broker: 2× HTTP 403 `api-key-invalid` (17:22 positie-opvraging, 19:06 koers), elk 1 van 3 en direct hersteld → IG-demo-hapering, geen actie. 19:00 broker meldt markt gesloten binnen het rooster (één keer; 12-10 = Columbus Day) → rooster kent de Amerikaanse kalender niet, de code volgt terecht de broker.
- Latency p99 702 ms (2 herstarts). 0 Gold Scalper-fouten (ERROR).
- H-GS-11 (daghandelkosten ≈ 20 % van de beweging): 0 daghandeltrades → nog niet meetbaar. H-GS-10 (vrijdagsluiting) toets 16-10. L-GS-011 klaar voor 13-10 (rebase op 2.2.1 nodig). Geen release.

laatste ronde: 12-10 19:40, gemeten t/m 12-10 19:46

## 12-10 23:40 · tussenronde
- Chatsessie: **2.3.0** (19:51, `export_data`, L-GS-017), **2.4.0** (20:36, veldproef 45 opzetten op 1m-30m met echte demo-orders, L-GS-018, opdracht Ruud), **2.4.1** (21:15 UTC = 23:15, minimale stop 1 USD, afgewezen order niet elke cyclus herhalen). Actief 2.4.1 (herstart 23:18). Run 105 → 106 (22:38) → **run 107 sinds 22:41**.
- **Slot run 105** (combinatie): 19:46-22:39 0 nieuwe trades (Columbus Day; broker meldde 19:00 markt dicht). Eind: 35 trades, alle scalp, netto −20,55 = bruto +1,25 − kosten 21,79 (0,62/trade), winst 34,3 %, t/trade −1,51, 0 daghandeltrades. Geen oordeel (n te klein); beeld = H-GS-7.
- **Run 107 (veldproef):** 39 acties, 7 posities open (4 long/3 short, elk 1 oz, broker-stops aanwezig), 0 gesloten trades. 4 long boven `limiet_per_richting` 3 is volgens ontwerp (2.4.0: één positie per opzet bovenop de scalplimiet; `max_open_positions` + 1 + aantal opzetten, coordinator r. 341-348). Gelijke stop/doel bij twee posities past bij twee opzetten op dezelfde signaalbar (stop uit de bar, niet uit de vulprijs); niet te toetsen: het attribuut `positions` noemt geen opzet → **L-GS-019** (meetbaarheid).
- **Orderafwijzingen:** 41× ATTACHED_ORDER_LEVEL_ERROR 22:40-22:50, ~2 per 10-s-cyclus (1m-stop 0,56 USD, elke cyclus opnieuw) = wat 2.4.1 oplost; sinds 23:18 0, maar markt dicht 23:00-00:00 → toets in de ronde van 03:40.
- 1× HTTP 403 api-key-invalid (22:29, 1 van 3, hersteld). Latency p99 895 ms (6 herstarts, p50 208). Afstemming `in_orde`, noodstop/dataprobleem uit, demo. Geen knoppen gebruikt.
- Hypotheses: H-GS-10 (vrijdagsluiting, toets 16-10), H-GS-11 (daghandelkosten ≈ 20 % van de beweging: nog 0 daghandeltrades). Nieuw meetdoel veldproef: per opzet en tijdvak trades, bruto/kosten; per opzet zijn ≥ 30 trades nodig voor een ruwe toets, bij 45 opzetten dus ≥ 1.350 trades vóór een eerste vergelijking. Geen release. L-GS-011 moet nu op 2.4.1 worden gezet (dagafsluiting 13-10).

laatste ronde: 12-10 23:40, gemeten t/m 12-10 23:43

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
