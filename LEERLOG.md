# Leerlog Gold Scalper

Onderzoeksproject op IG-demo: edge van ruis onderscheiden. Alleen gemeten getallen; KPI's in KPI.csv.

## 07-10 23:30 · tussenronde (eerste ronde, baseline)
- Gemeten: 56 trades in 7 clusters (06-10 06:30 - 07-10 19:03 UTC). Netto −120,53 USD = bruto −18,65 − kosten 101,88 (1,82 USD/trade, 100% gemeten). PF 0,651, winst 44,6%.
- t netto over clusters −2,05; t bruto (zelf berekend) −0,24 → bruto niet van nul te onderscheiden, netto verlies komt uit de kosten (kosten/bruto-verhouding 5,5).
- Eerlijk over n: 7 clusters. Om een bruto-edge ter grootte van de kosten (14,6 USD/cluster bij sd 29,6) met t=2 te zien zijn ~17 clusters nodig; voor een netto-oordeel meer. Geen conclusie over de strategie.
- Regime: range 16 trades t −2,91 (netto −97,82), trend 40 trades t −0,29 — trades niet onafhankelijk, n te klein; alleen volgen.
- Uitvoering: slippage 3× de aanname (0,06 vs 0,02); latency p90 207 ms, max 786 ms (exits→signal).
- Meetfout gevonden: `learning/analysis.py` telt doel/stop uit de ruwe `close_reason` (na afstemming overschreven met `broker_gesloten_gecorrigeerd`, 24/56). Gevolg: "geleerd" meldt doel 14% en "ATR mogelijk overschat", terwijl de sensor Doel geraakt (op bewijs, 0% onbekend) 19,6% geeft. → L-GS-001 (zelf bouwen, meetfout; bij de dagafsluiting).
- Hypothese H-GS-1: doeltreffers liggen onder de verwachte 40% (19,6%, n=56). Pas toetsen na fix en ≥100 trades.
- Afstemming met broker: "nog_niet" (wel 24 trades gecorrigeerd via transacties).
- Geen release (tussenronde; 1.7.0 vandaag al uitgebracht en geïnstalleerd).

laatste ronde: 07-10 23:30, gemeten t/m 07-10 23:15
