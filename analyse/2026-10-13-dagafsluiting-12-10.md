# Dagafsluiting 12-10 · Gold Scalper (ronde gestart 03:40, afgerond 11:30)

LEERLOG.md/KPI.csv niet zelf bijgewerkt: git-netwerkacties en lokale python werden in deze sessie door de toestemmingscontrole geweigerd. De volgende ronde neemt deze regels over (KPI.csv type DAG, datum 2026-10-12) en verwijdert dit bestand.

## KPI's dag 12-10 (lokale dag, uit de tussenrondes van 12-10)
- gs_trades 99: run 101 (scalpen, tot 15:04) 64 trades (78 → 128 sinds 00:00 incl. nacht), run 105 (combinatie 15:46-22:39) 35 trades, run 107 (veldproef vanaf 22:41) 0 gesloten
- gs_netto_usd −137.11: run 101 −116.56 (−1.82/trade), run 105 −20.55 (−0.59/trade; bruto +1.25, kosten 21.79 = 0.62/trade)
- run 101 slot: 128 trades, netto −196.66, t_cluster −3.34 (10 clusters, 11:45) → H-GS-7 (bruto < kosten bij scalpen) bevestigd en gesloten met de strategiewissel
- gs_unexpected_errors 360 (02:21:52-03:21:44, TypeError sort(); fix 1.10.3); gs_sluittijd_fout_min 60 (trade 78, L-GS-011)
- gs_broker_403 3 (17:22, 19:06, 22:29; elk 1 van 3, hersteld)
- gs_veldproef_orderafwijzingen 41 (22:40-22:50, vóór 2.4.1)
- gs_afstemming in_orde de hele dag; noodstop 0; sluitreden onbekend 0.0 %
- gs_herstarts 24
- Daghandel: 0 trades op 12-10 → H-GS-11 (kosten ≈ 20 % van de beweging) nog niet meetbaar

## Status voorstellen
- L-GS-011 (sluitmoment van de broker): door deze ronde opnieuw gebouwd op 2.4.1 (branch leer-2.4.2 lokaal, 12 nieuwe tests, suite 2105 groen) maar NIET gereleased: push naar main geweigerd door de toestemmingscontrole, en main staat inmiddels op 2.4.11 (chatsessie, 2.4.2-2.4.11 op 13-10). Versienummer 2.4.2 is intussen door de chatsessie gebruikt. Volgende stap: controleren of 2.4.7 ("verweesde trades afwikkelen op brokerdata") het sluitmoment al van de broker neemt; zo niet, patch `analyse/2026-10-12-L-GS-011/sluitmoment-2.1.1.patch` op 2.4.11 zetten.
- L-GS-019 (strategie per open positie op sensor `positions`): gebouwd op 2.4.1 (zelfde lokale branch), niet gereleased. 2.4.8 zette een veldproeflabel in het paneel; of de sensor het nu ook toont, controleren vóór opnieuw bouwen. Kanttekening uit de bouw: `dashboard/broker.py::_strategie` kende alleen daghandel/scalp (mogelijk opgelost in 2.4.8).
- Geen release door deze ronde.

laatste ronde: 13-10 11:30 (dagafsluiting 12-10), gemeten t/m 12-10 24:00
