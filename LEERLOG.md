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

laatste ronde: 08-10 07:40, gemeten t/m 08-10 07:43
