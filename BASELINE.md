# Baseline Gold Scalper

| KPI | referentie | periode / n | vastgesteld |
|---|---|---|---|
| Netto per trade | −2,15 USD | 06-10..07-10, n=56 | 07-10 23:15 |
| Bruto per trade | −0,33 USD | idem | 07-10 23:15 |
| Kosten per trade | 1,82 USD (100% gemeten) | idem | 07-10 23:15 |
| t netto / bruto (clusters) | −2,05 / −0,24 | 7 clusters | 07-10 23:15 |
| Profit factor | 0,651 | n=56 | 07-10 23:15 |
| Slippage gemeten/aanname | 3,0× | n=56 | 07-10 23:15 |
| Latency p90 totaal | 207 ms | n=56 | 07-10 23:15 |
| Doel geraakt (bewijs) | 19,6 % | n=56 | 07-10 23:15 |
| Latency totaal p50 / p99 (cycli) | 176 / 514 ms | n=1000 cycli | 08-10 03:40 |
| Netto/bruto/kosten per trade (dag) | −1,61 / +0,34 / 1,95 USD | 07-10, n=40, 4 clusters | 08-10 03:40 |
| Clusters nodig voor bruto-edge t=2 | ~18 | sd 28,1 bij 8 clusters | 08-10 03:40 |
| Totaal (trades / clusters) | 162 / 16: netto −201,00, bruto +49,19, kosten 250,19; t −2,54 | t/m 09-10 03:41 | 09-10 03:40 |
| Tijdstopregime per trade | netto −0,01 · bruto +1,40 (t 1,84) · kosten 1,41; 15,7 trades/cluster | 94 trades, 6 clusters | 09-10 03:40 |
| Latency p99 zonder herstart | 1067 ms (p50 229) | n=2000, 22:10-03:45 | 09-10 03:40 |
| Rooster-klokrand-WARNINGs | 2 per nacht | 08-10 | 09-10 03:40 |
| Dag 09-10 per trade (run 100+101) | netto −0,70 · bruto +0,77 · kosten 1,47 USD | 180 trades | 10-10 03:40 |
| Run 101 uurblokken | 7 blokken: t_netto −2,34, t_bruto +0,62, bruto +2,58/blok, kosten ~14/blok | 64 trades | 10-10 03:40 |
| Handelsweek 06-10..09-10 per trade | netto −1,13 · bruto +0,37 · kosten 1,50 USD (kosten/bruto 4,1) | 303 trades (run 100: 16 clusters, t −3,28; run 101: 6, t −2,34) | 11-10 03:40 |
| Run 101 uurblokken nodig | t_bruto 2 bij ~73 blokken (bruto +2,58/blok, sd 10,97); kosten 14,0/blok | 7 blokken | 11-10 03:40 |
| Latency gesloten markt p50 / p99 | 183 / 253 ms (geen handelscycli; geen referentie voor handel) | n=2000 | 11-10 03:40 |
| Run 101 uurblokken (10) | t_netto −2,08 (lag1 −0,02), t_bruto +0,70 (lag1 −0,30); bruto +2,63/blok, sd 11,9 → ~83 blokken voor t=2; kosten 12,4/blok | 78 trades | 12-10 03:40 |
| Run 101 totaal | 78 trades / 8 clusters: netto −97,38 · bruto +26,30 · kosten 123,68 (per trade −1,25 / +0,34 / 1,59); PF 0,472; t_cluster −2,86 | t/m 12-10 03:45 | 12-10 03:40 |
| Handelsnacht ma 00:15-02:19 per trade | netto −1,23 · bruto +0,59 · kosten 1,82 USD | 14 trades | 12-10 03:40 |
| Latency handel p50 / p99 | 188 / 667 ms (incl. herstart 03:33) | n=2000 | 12-10 03:40 |
| IG run 19-10.. (veldproef 15m/30m + daghandel) | 160 trades / 10 clusters: netto −101 · bruto +926 · kosten 1.027 (6,42/trade); PF 0,967; t_cluster −0,13; uurblokken t_bruto 1,12 (44) → ~140 blokken voor bruto t=2; netto geen edge | 19-10 09:00..21-10 19:45 UTC | 21-10 19:45 |
| Pepperstone XAUUSD (start 14-10) | 1.571 trades / 6 clusters: netto −8.739 · bruto −2.477 · kosten 6.262 (3,99/trade); PF 0,79; uurblokken t_netto −2,09 (111), t_bruto −0,60 | 14-10..21-10 | 21-10 19:45 |
| Latency p99 (cycli) | IG 35,2 s · Pepperstone 15,1 s (p50 445 / 355 ms); Pepperstone dagmiddel 5,0 s (14..16-10, 19-10) → 9,3 s (20-10) → 13,9 s (21-10) | n=2000 | 21-10 19:45 |
| Sluitreden onbekend Pepperstone | 26,1 % (410/1.571) | 14..21-10 | 21-10 19:45 |
| IG daghandel/veldproef run 19-10 | 182 trades / 12 clusters: netto −205 · bruto +960 · kosten 1.165; uurblokken t_bruto 1,13 / t_netto −0,24 (52) | 19..22-10 | 22-10 03:40 |
| Pepperstone XAUUSD | 1.606 trades: netto −9.175 · bruto −2.857; t_netto −2,18 (118 blokken) | 14..22-10 | 22-10 03:40 |

| IG run 22-10 16:48.. | 80 trades / ~11 clusters: netto 181,65 · bruto 616,84 · kosten 435,19 (71 %); PF 1,13; t per trade 0,81 | 22..23-10 | 24-10 03:40 |
| Pepperstone run 22-10 16:48.. | 138 trades: netto −137,03 · bruto 159,89 · kosten 294,16; PF 0,96; t −0,11 | 22..23-10 | 24-10 03:40 |
| Bitvavo-mand: handelende leden | 0 van 10 (PUMP-EUR geweerd op spread 0,067 %) | 25-10 02:17 | 25-10 03:40 |
| Pepperstone week 43 (19..25-10) | 145 trades: netto −34,89 · bruto 334,39 · kosten 369,28 (110 % van bruto) | week 43 | 26-10 03:40 |
| Bitvavo-mand totaal | 568 trades: netto −6.428, PF 0,12, t −1,33; 2.23.0-opzetten 0 gesloten | t/m 26-10 03:41 | 26-10 03:40 |
| Latency p99 buiten storing | PP 0,71-0,84 s · mand 0,48-0,74 s (IG alleen actueel, 0,76 s) | 25-10 | 26-10 03:40 |
| Run IG / Pepperstone (veldproef) | 122 tr / 12 cl, netto −362,51, PF 0,855, t −0,59 · 220 tr / 19 cl, −545,19, PF 0,892, t −0,41 | t/m 27-10 03:40 | 27-10 03:40 |
| Latency p99 rustige nacht | IG 0,86 · PP 0,87 · mand 0,39 s | 27-10 nacht | 27-10 03:40 |
| Run IG / Pepperstone (veldproef) | 165 tr / 18 cl, netto −719,60, PF 0,791, t −1,11 · 275 tr / 27 cl, −659,73, PF 0,892, t −0,48; clustergemiddelde −40 / −24 USD (sd 153 / 267) | t/m 28-10 03:30 | 28-10 03:40 |
| Latency p99 per dag (27-10) | PP mediaan 0,97 s (max 1,76) · mand 0,56 s (max 0,75) · IG 0,81 s (alleen actueel) | 27-10 | 28-10 03:40 |
| Run IG / Pepperstone (veldproef) | 229 tr / 27 cl, netto −1.788,98, PF 0,663, t −1,83 (bruto t −0,60) · 387 tr / 44 cl, −1.018,46, PF 0,887, t −0,71 (bruto t +0,09); clustergemiddelde −66 / −23 USD (sd 188 / 215) | t/m 30-10 02:55 | 30-10 03:40 |
| Kosten per trade 7 d (23..29-10) | PP 3,08 · IG 5,78 USD; bruto 7 d negatief (PP −778, IG −572) | 343 / 195 trades | 30-10 03:40 |
| Latency p99 per dag (29-10) | PP mediaan ~1,41 s (max 1,60) · mand ~0,83 s (max 0,97) · IG 1,40 s (alleen actueel) | 29-10 | 30-10 03:40 |
| IG run-oordeel | t −1,51 bij 30 clusters (failed: geen edge) | run t/m 30-10, 258 tr | 31-10 03:40 |
| PP run bruto tegen kosten | +573 / 1.197 USD (412 tr) | run t/m 30-10 | 31-10 03:40 |
