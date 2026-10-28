# GS-LEERLOG — 4-uurscontrole Gold Scalper (opdracht Ruud 13-10-2026)

Per ronde: gemeten, trades per uur, conclusies, gebouwd, instellingen. Eerdere rondes: `LEERLOG.md`.

## 13-10 08:10 · eerste ronde
- Actief 2.4.6 (run 113 sinds 05:58 UTC, veldproef-1.1.0, take_profit_usd 2 door Ruud gezet 05:58). Demo, noodstop/dataprobleem uit, 10 posities open (8L/2S, 0,5 contract, broker-stops aanwezig). Eq. 9.995.859 (max DD sinds run 107: 6.250 = 0,06 %).
- Trades/uur (openingen, UTC): 03u 52, 04u 53, 05u 93; run 113 ~29 in 14 min. Grootste weigerredenen run ≥110: max_positions_zelfde_richting 3138 (vóór 2.4.2), al_gebruikt 2037, netting 735, score 575.
- Sinds run 107, 209 gesloten: veldproef 195 netto −3.439 (bruto +3.846, kosten 7.285; win 31 %, PF 0,73); scalp 14 netto −1.054 (PF 0,03). Per tijdvak: 1m n=99 netto −3.525 (t −2,8), 3m −833, 5m +775, 15m −53, 30m +198.
- Families n≥30: rsi_rev n=60 netto −4.216 (bruto −2.129, t −4,0; rsi_rev:1m n=31 t −3,1) → < 100 trades, dus nog aan; momentum n=59 −387 (t −0,2). Rest n<30: geen oordeel.
- **Gevonden:** 23 trades uit run 110/111 staan in de database open terwijl de broker ze niet meer heeft → tellen nergens mee (netto sinds start onvolledig). Oorzaak: alleen live geziene posities worden over een runwissel meegenomen.
- **Gebouwd 2.4.7** (suite 2107 groen, in HACS, herstart door Ruud): verweesde trades (< 46 u) afwikkelen op uitstapprijs+sluitmoment uit het IG-activiteitenoverzicht, 3 per 5 min, nooit op schatting, niet in daglimiet/verliesreeks. Test test_v247.
- Afstemming: 1 afwijking (trade 1437, vp:momentum:1m: wij TP 4196,87 +130 EUR, broker 4194,14 +7,10); zwakke koppeling (zelfde instapprijs als trade 1143) → bewust niet overgenomen. IG rate limit (account/api-key allowance) ~6× per uur, telkens binnen 1-2 cycli hersteld.
- Instellingen: **niets gewijzigd.** Risico per trade is klein (0,5 contract ≈ 100-600 EUR bij stop op ~10 mln), dag-/vloerlimieten lopen niet aan. TP 2 USD tegen stops 2-12 USD vraagt > 75 % winst; Ruud zette dit net, n=19 → meten: per tijdvak winst% en netto onder TP 2, terugdraaien/voorstel bij n ≥ 30 per tijdvak.
- Volgende ronde meten: aantal verweesde trades afgewikkeld (na herstart), netto per tijdvak onder TP 2, rsi_rev richting 100 trades.

laatste ronde: 13-10 08:10

## 13-10 08:30 · handmatige herhaalronde (20 min na de vorige)
- Payload noemde 2.4.6 niet actief en TP 3; gemeten: run 113 draait veldproef-1.1.0 (2.4.6 actief), take_profit_usd 2. 2.4.7 in HACS, wacht op herstart Ruud. Geen nieuwe release (vorige 20 min geleden, data nauwelijks veranderd).
- 06:17 UTC opnieuw netting: order DIAAAAYM2QT5RB7 verrekende 2 longs ondanks forceOpen → hedgen uit tot herstart: nu 7 long / 0 short, tegengestelde signalen geweigerd (kost trades). Integratie meldde dit zelf aan Ruud.
- Afstemming 269/271: oude afwijking (trade 1437) opgelost; 2 nieuwe: instap 4196,33/4196,32, wij uitstap 4193,31/4192,37, broker beide 4194,87 (−64,05) → vermoedelijk de nettingprijs; zwakke koppeling (twee trades zelfde instap), dus niet overgenomen.
- Open punt voor volgende ronde: waarom IG ondanks forceOpen verrekent (alleen bij gelijke grootte/tegelijk?) en of hedgen-uit-tot-herstart > 20 % trades kost. Instellingen ongewijzigd.

laatste ronde: 13-10 08:30


## 13-10 09:15 · ronde 3
- Actief nog 2.4.6 (2.4.7 geïnstalleerd, wacht op herstart Ruud). Demo, noodstop/dataprobleem uit. Eq. 9.992.328.
- Trades/uur (openingen, UTC): 05u 93, 06u 55, 07u 18 in 13 min. Run 113 (TP 2, 05:58-07:14): 77 gesloten, netto −4.856, bruto −2.072, kosten 2.784, win 29 %, PF 0,30, t −4,36.
- **TP 2 USD gemeten slechter:** veldproef run 107-112 (eigen doel 2R, med. 4,79 USD) n=179 −12,5/trade (t −0,9); run 113 (TP 2) n=68 −57,4/trade (t −3,8); verschil ≈ 45/trade, Welch t ≈ 2,3. Mediane stop 2,1 USD + kosten ~1 USD/oz → quitte pas bij ~75 % winst; gemeten 29 %. Schade vooral op 3m-15m (grotere stops): niet-1m −81/trade tegen +3,7 eerder; 1m −41 tegen −29.
- **Instelling: take_profit_usd 2 → 0** (elke strategie haar eigen doel: veldproef 2R, scalp eigen doel, daghandel volgstop). Run 114 sinds 07:14 UTC. Verwacht: aantal openingen gelijk (doel bepaalt geen instap), netto per trade terug richting −12. Meten: per trade en per tijdvak tegen run 113; terugdraaien als run 114 na n ≥ 60 niet beter is.
- Kosten zijn de kern: sinds run 107 bruto +1.760, kosten 9.758. tf 1m n=128 bruto +209 kosten 4.410 (t −4,25). Familie rsi_rev n=82 t −4,0 (rsi_rev:1m n=43 t −3,2) → bij 100 trades uitzetten als t < −2 blijft. Scalp n=20 PF 0,05: < 30, geen oordeel.
- Afstemming: nieuwe afwijkingen bij paren met gelijke instap (4193,69/4193,70: wij −205,76, broker −13,07) → zelfde koppelprobleem als vorige ronde; volgende ronde uitzoeken of de uitstapprijs bij gelijktijdige trades verkeerd wordt toegewezen. IG rate limit ~4×/uur, telkens hersteld; 1 order mislukt door rate limit.
- Geen release (2.4.7 van 40 min geleden wacht op herstart).

laatste ronde: 13-10 09:15

## 13-10 08:55 · chat met Ruud
- Ruud: scalp-posities stonden gelijk aan "Daghandel"-posities. Oorzaak: (1) paneelbug, veldproefopzetten kregen bij "alles" het label Daghandel + max duur tot 20:45; (2) sinds 2.4.6 gold TP 2 USD voor alles, dus 30m-opzetten met 12 USD stop gedroegen zich als scalp.
- Besluit Ruud: vast doel alleen voor scalp ("kort, snel, kleine winsten"). **2.4.8** gebouwd: veldproef terug naar 2R, daghandel geen doel (volgstop/20:45), nieuwe strategieversies (nieuwe run), paneel toont "VP <familie> <tf>". Suite 2112 groen, in HACS; herstart door Ruud (activeert ook 2.4.7).
- Nieuwe wens Ruud: scalp veel trades per 1m-candle, pyramide-achtig, tot 100 trades, doel desnoods 1 USD. Nog niet gebouwd; vraagt ontwerpkeuze (zie chat): blokkades nu = spreidingsregel (1 per richting per candle), max 20 per richting, IG-ratelimiet, kosten ~0,6-0,75 USD/oz tegen 1 USD doel.

laatste ronde: 13-10 08:55

## 13-10 ~10:00 · chat met Ruud (vervolg)
- **2.4.9** (suite 2120 groen, in HACS): scalpreeks (stap 0,30, max 100 stukken, doel 1,00 per stuk, gedeelde stop, max 3 per cyclus, standaard aan), reden per strategie in het paneel (was alleen daghandel "geen_uitbraak"), scalpdoel instelbaar per 0,1 USD.
- Ruud zette om 07:14 UTC take_profit_usd 0 (eigen doel per strategie); run 115 sinds 07:34.
- Ruud: "trailing stop/profit werkt niet, +3 USD en toch uitgestopt". Gemeten run ≥110 (248 gesloten): MFE ≥ 2 USD/oz en toch verlies = 4 van 27, allemaal veldproef (1m/3m/5m; bv. id 1648/1649 vp:5m MFE 2,7 → stop). Scalp 0 van 2. Oorzaak: veldproef heeft bewust geen break-even/volgstop (alleen stop 1,5 ATR, doel 2R, max 48 bars); het label "Daghandel" (bug, opgelost in 2.4.8) liet het lijken op een kapotte daghandelvolgstop. Voorstel aan Ruud: break-even/volgstop in R voor de veldproef.

laatste ronde: 13-10 10:00


## 13-10 10:11 · ronde 4 (4-uurscontrole)
- 2.4.9 actief (run 117 sinds 08:10 UTC; Ruud zette net take_profit_usd 1, scalp_reeks_doel 0,5). Demo, noodstop/dataprobleem uit, eq. 9.988.554. Na herstart IG rate limit (account allowance) ~5× in 4 min, hersteld.
- Openingen/uur (UTC): 03u 52, 04u 53, 05u 93, 06u 55, 07u 91, 08u 29 (eerste 11 min) → ~60-90/uur, doel "veel trades" gehaald.
- Sinds run 107 (n=385): netto −12.466, bruto +1.601, kosten 14.067 (kosten > 8× bruto), win 33 %, PF 0,55, t −4,1. Runs: 113 −59,8/tr (n=82), 114 −38 (n=23), 115 −61,5 (n=54).
- Veldproef n=356 t −3,5 (bruto +3.058); per tijdvak: 1m n=182 t −4,75 (bruto +686, kosten 6.479); 3m n=68 t −2,5; 5m/15m/30m rond nul vóór kosten positief. Opzetten max n=56 (rsi_rev:1m, momentum:1m t −4,0) → < 100, nog niet uitzetten. Familie rsi_rev n=109 t −2,6, momentum n=110 t −2,4.
- Scalp n=29 net −2.316, PF 0,09, ook bruto negatief (−1.457); uitstap 20× tijdslimiet. < 30: geen oordeel, maar slechtste onderdeel. Config-waarschuwing: doel 1,00 tegen stop ~5,7 (ATR) → 85 % winst nodig vóór kosten.
- Afstemming 394/395; 1 afwijking (instap 4194,25: wij 4190,33, broker 4185,13). 4 verweesde trades (run 113/114) zijn op dezelfde prijs 4190,33 / 07:33:56 afgewikkeld → één sluitactiviteit met meerdere affectedDealIds (netting?). Mogelijk correct, mogelijk fout: volgende ronde activiteit van die tickets naast transactieoverzicht leggen. Nog 21 trades uit runs 23-98 staan > 46 u "open" in de db (buiten de wezen-grens; tellen nergens mee).
- Instellingen: niets gewijzigd (Ruud stelde 2 min geleden zelf bij; nieuwe run, 24-u-regel). Geen release (geen bug met voldoende bewijs).
- Volgende ronde: run 117 per strategie (scalpreeks met doel 0,5: winst% en netto per stuk), kosten/trade per tijdvak, 1m-veldproef richting 100 per opzet.

laatste ronde: 13-10 10:11

## 13-10 ~10:40 · chat met Ruud (vervolg)
- Ruud herstartte 10:08/10:10 (2.4.9 actief); weesjes-afwikkeling werkt (o.a. 2L69KAS, LLVNAN), maar acht kregen allemaal 4190,33 uit één activiteit 07:33:56; transactieoverzicht: 2L69KAS 4185,13 (−410,50) → 1 afwijking.
- **2.4.10** (suite 2127 groen, in HACS, herstart Ruud): veldproef break-even 1R, volgstop vanaf 1,5R op 1R (R = doelafstand/2), veldproef-1.3.0; weesjes als voorlopig gemarkeerd zodat de afstemming de transactieprijs overneemt.
- Ruud: doel = winstgevend ("al doe je 100000 trades per dag"). Screenshot "Scalp" met TP 4176/4208: dat zijn veldproefposities (max 47:20/2u23/11u59/23u59 = 1m/3m/15m/30m x 48 bars) met een oud paneelscript in de browser → pagina herladen.
- Instellingen nu: take_profit_usd 0 (Ruud 09:14), scalp_reeks default aan (stap 0,30, max 100, doel 1,00).
- Aanpassing geplande controletaak gevraagd door Ruud; bijwerken werd door de rechtencontrole geweigerd → Ruud moet het toestaan.

laatste ronde: 13-10 10:40

## 13-10 10:34 · instellingen (op vraag Ruud, run 118 sinds 08:32 UTC na herstart)
- take_profit_usd 0 -> 1,0 (scalp: "kort, snel, klein"; met 0 gold 1,5 x ATR15 ~ 8 USD). stop_loss_usd 0 -> 2,0 (was 1 x ATR15 ~ 5,6: doel 1 tegen stop 5,6 vraagt > 85 % winst; nu ~67 %). min_edge_multiple 2 -> 1 (filter eist doel >= 2 x kosten ~1,5 USD; daardoor zou elk scalpsignaal met doel 1 geweigerd worden; doel telt al vanaf de vulprijs). max_trades_per_day 1000 -> 2000 (bij ~90/u plus scalpreeks raakt 1000 binnen een dag de grens).
- Ruud zette zelf scalp_reeks_doel_usd 0,5. Ongewijzigd: risico 3 %/max 500 oz (alleen daghandel risicogestuurd; ~0,1 % van 10 mln per trade), daglimiet/vloer, max 20 per richting.
- Meten: scalp winst%, netto/trade, aantal scalptrades/uur vóór en na; terug als netto per scalptrade na >= 30 trades duidelijk slechter is.

laatste ronde: 13-10 10:34

## 13-10 ~11:05 · chat met Ruud (vervolg)
- Ruud herstartte 10:32 (2.4.10 actief, run 118); mijn instellingswijziging 10:34 → run 119. Daarna toonde het paneel alle open posities als "Daghandel": paneel las alleen open trades van de lopende run → fallback primaire strategie.
- **2.4.11** (suite 2130 groen, in HACS): paneel leest ook open trades uit eerdere runs (2 dagen); tijdstip/reden/aantal van de laatste stopverplaatsing per positie (kolommen stop_gewijzigd_op/stop_wijzigingen/stop_reden), onder SL "↕ hh:mm (n×)".
- Screenshots "Scalp" met verre TP (max 42:36 / 3u53) zijn veldproef 1m/5m met een oud paneelscript in de app → app/browser verversen.
- Wens Ruud: "turbo trading, seconden" bij scalp. Nu: cyclus 10 s (minimum), IG-limiet al ~6x/u geraakt. Er is al een IG-koersstream (alleen voor het paneel). Voorstel: scalp op de stream laten reageren met een orderbudget; wacht op akkoord.

laatste ronde: 13-10 11:05


## 13-10 11:12 · ronde 5 (geplande controle)
- 2.4.11 actief sinds herstart ~09:02 UTC (run 119 sinds 08:34 UTC). Demo, noodstop/dataprobleem uit, afstemming in_orde, 6 open (1 long/5 short), eq. 10.074.218. Na herstart weer IG rate limit (account allowance) en DNS-time-outs ~1 min; 12 trades bij de broker al gesloten → afgewikkeld.
- Run 119 (37 min, uit sensor): 39 trades (~63/u), alle veldproef; netto −2.042, bruto −490, kosten 1.552 (3,2× bruto), win 28 %, PF 0,24. Scalp 0 trades (score onder drempel 0,45). Momentum 1m/3m n=15 −1.054 (slechtste), maar alle opzetten n < 30.
- Databaseanalyse niet gedaan: uitvoeren van het onderzoeksscript via de File editor werd deze ronde door de rechtencontrole geweigerd → Ruud moet dit toestaan, anders alleen sensorcijfers.
- Geen release (geen bug met bewijs), geen instellingen (laatste wijziging 10:34, 24-u-regel; n te klein).
- Volgende ronde: scalp met doel 1/stop 2 zodra n ≥ 30; veldproef 1m-kosten (~0,8 USD/oz per trade tegen R ~1,5 ATR1m); momentum:1m richting n=100.

laatste ronde: 13-10 11:12

## 13-10 ~11:50 · 2.5.0 turbo-scalp (akkoord Ruud)
- **2.5.0** (suite 2137 groen, in HACS, herstart Ruud): scalp reageert op de IG-koersstroom, max 1 ronde/s, scalpreeks + nieuwe scalpposities, zelfde grendels als de cyclus, orderbudget 20/min (instelbaar 1-60), nooit tegelijk met de cyclus, posities/saldo uit de laatste cyclus. Instellingen scalp_turbo (aan) en scalp_turbo_orders_per_min. Paneel: regel "Turbo-scalp" met verbruik.
- Test test_v181 (stroom voedt nooit beslissingen) bewust aangepast: alleen _turbo_start mag de stroom lezen.
- Meten na herstart: turbo-orders/uur, IG-403-meldingen per uur (mag niet stijgen), netto per scalptrade turbo vs cyclus (components turbo).

laatste ronde: 13-10 11:50


## 13-10 11:42 · instelling (chat, op verzoek Ruud)
- entry_threshold 0,45 -> 0,30: scalp deed 0 trades in run 119 (score onder 0,45), daardoor ook turbo-scalp (2.5.0) 0 orders. Run 120 sinds ~09:42 UTC.
- Meten: scalptrades/uur (turbo vs cyclus), winst%, netto per scalptrade; terug naar 0,45 (of tussenwaarde) als netto per scalptrade na >= 30 trades duidelijk negatief is (t < -2). Telt als instellingenronde voor de 24-uursregel.

laatste ronde: 13-10 11:42

## 13-10 ~12:05 · 2.5.1 snelle break-even (chat, Ruud)
- **2.5.1** (in HACS, wacht op herstart Ruud): scalp stop naar instap bij +0,6 USD/oz; veldproef break-even 0,5R (was 1R); daghandel break-even vanaf 1 x ATR15 (was uit); stop minstens 0,6 USD van de koers. Suite: 2134 groen + 6 bestaande tests aangepast aan het nieuwe gedrag.
- Meten na herstart: aandeel trades dat op break-even sluit, gemiddeld verlies per verliestrade (moet dalen), gemiddelde winst per winnaar (mag niet veel dalen), netto per trade per strategie. Daghandel: backtest 2.1.0 vond break-even slechter; bij n >= 30 vergelijken en zo nodig terug.
- Let op logs: veel IG 403 exceeded-account-allowance / api-key-allowance sinds de turbo (2.5.0) en de herstart; "Openen mislukt" 5x.

laatste ronde: 13-10 12:05

## 13-10 12:30 · ronde 6 (geplande controle)
- 2.5.1 actief (run 121 sinds 10:01 UTC). Demo, noodstop/dataprobleem uit, afstemming in_orde (3 afwijkingen uitstap/bedrag, o.a. instap 4187,87: +59,92 wij / −74,35 broker). Trades/uur vandaag 50-97 (actieve uren).
- Vandaag n=548: netto −19.864, bruto +618, kosten 20.483 (0,79 USD/oz), t −6,0. Veldproef n=518 −17.494 (t −5,4); 1m n=269 −10.872 (t −7,9, kosten 0,78/oz tegen MFE 0,70/oz: structureel); 15m n=46 ~0 (PF 0,99); bb_fade n=11 +310. Scalp-basis n=30 −2.370 (t −3,8); sinds run 119 0 scalptrades (score onder 0,30).
- Per opzet (alle tijd): rsi_rev:1m n=85 t −3,95, momentum:1m n=78 t −5,15 → bij n ≥ 100 uitzetten; er bestaat nog geen mechanisme om één opzet uit te zetten (volgende release).
- Valse netting 10:02:09: long 286ATAG sloot op zijn stop terwijl short 28VDTA7 opende (die stond tot 10:08 open) → hedgen uit tot herstart, shortsignalen geweigerd.
- **2.5.2** (suite 2144 groen/5 skip, in HACS, herstart Ruud): netting alleen als de nieuwe positie ontbreekt of kleiner is dan besteld.
- Instellingen: niets (laatste wijziging 09:41 UTC, 24-u-regel; geen acuut risico).
- Volgende: opzet-uitzetmechanisme (n ≥ 100, t < −2) voor momentum:1m/rsi_rev:1m; effect 2.5.1 break-even (run 121: 10 trades, 0 % win, nog te klein).

laatste ronde: 13-10 12:30

## 13-10 ~12:55 · 2.5.3 turbo-uitbraak (chat, Ruud keuze 2)
- **2.5.3** (suite 2148 groen + 1 paneeltest aangepast; in HACS, wacht op herstart): eigen turbosignaal op de ticks (strategy/turbo.py): uitbraak >= 0,10 USD door de band van 45 s, doorzetting >= 0,30 in 10 s, band 0,4-6 USD, 30 s wachten; stop/doel van scalp (2/1), scalpexits (break-even +0,6). open_reason "turbo uitbraak"/"turbo scalp"; paneel toont "Turbo scalp". Bovenop 2.5.2 (netting) van de geplande ronde.
- Meten na herstart: uitbraakorders/uur (redenen.turbo), netto per turbotrade, winst%, aandeel break-even; IG-403 per uur. Bij n >= 30 en t < -2: band/doorzet-drempels aanscherpen of uitzetten.

laatste ronde: 13-10 12:55

## 13-10 ~13:35 · 2.5.4 + 2.5.5 (chat, Ruud)
- **2.5.4**: grens max posities per richting 20 -> 100 (instelling zelf nog 20; Ruud: "mocht veel hoger"). Na herstart instellen op 100 (of Ruud zelf).
- **2.5.5** (suite 2156 groen, in HACS, wacht op herstart): break-even uiterlijk bij +1,5 USD/oz voor veldproef en daghandel (naast 0,5R / 1 ATR15; screenshot: rsi_rev 15m/30m op +3 USD zonder BE). Omkeer-exit: tegengesteld signaal van de eigen strategie -> verlies of < 0,6 USD winst sluiten, anders stop op 0,6 USD van de koers. Nieuwe strategieversies.
- Meten: aandeel sluitingen "signaal gedraaid" (verlies/winst), netto per trade voor/na, gemiddeld verlies per verliestrade, aandeel break-even. Let op omkeer bij veldproef: tegengestelde opzetten in dezelfde familie/tf kunnen veel omkeren -> te veel sluiten = kosten; terug als netto per trade slechter wordt.

laatste ronde: 13-10 13:35

## 13-10 ~13:45 · ronde 7 (geplande controle)
- Actief: 2.5.3 (run 122 sinds 10:54 UTC, veldproef-1.4.0); in HACS staat nu 2.5.6 (bevat ook 2.5.4/2.5.5 van de chat), herstart Ruud. Noodstop/dataprobleem uit, demo. Afstemming: 500/505 kloppen, 5 afwijkingen uitstapprijs/bedrag. 10 open posities met stops. 21 oude open rijen (aug–1 okt, runs 23-98) staan nog in de DB (bekend, geen broker-positie).
- Vandaag n=616: netto −22.686, t −6,55, win 31 %, PF 0,48. Trades/uur 53-97 (actieve uren). Run 122: n=36, −2.348 (t −5,3).
- Per tijdvak (alle tijd, veldproef): 1m n=306 −10.992 (t −6,55; kosten ~0,78/oz tegen MFE ~0,6/oz), 3m n=117 t −2,96, 5m n=87 t −2,29, 15m n=49 ~0 (t −0,03), 30m n=30 −1.010.
- Opzetten: rsi_rev:1m n=100 t −2,72 → valt onder de uitzetregel; momentum:1m n=86 t −3,42 (volgt bij 100). Scalp-basis n=30 −2.370 (t −3,8); turbo-uitbraak n=6 alle verlies (te klein); reeksstukken n=3 +46.
- IG 403 exceeded-account-allowance: 11x "Openen mislukt" vandaag (laatste 13:12); DNS-time-outs 3x.
- **2.5.6** (suite 2161 groen/5 skip, in HACS, herstart Ruud): opzet met n ≥ 100 en t < −2 (netto per trade, alle runs) stapt niet meer in; lijst elke 5 min uit de DB, zichtbaar in de veldproefreden en als logwaarschuwing. veldproef-1.6.0.
- Instellingen: niets (24-u-regel sinds 09:41 UTC; geen acuut risico, dagverlies ~0,2 % van de rekening).
- Volgende: 1m-tijdvak als geheel (n=306, t −6,55) — na herstart meten of de uitzetregel per opzet volstaat; anders voorstel 1m uit of grotere stop op 1m. Effect 2.5.5 break-even/omkeer-exit meten.

laatste ronde: 13-10 13:45

## 13-10 ~16:30 · ronde 8 (geplande controle, onder RUST IN DE REGELS)
- Runs: 128 (13:01 UTC; 46 trades in 16 min, −2.387, bruto −570, kosten 1.817 = 3,2x bruto, scalp n=20 −835 t −2,1) → 130 sinds 14:04 UTC na chatreleases 2.5.7 winstslot / 2.5.9 deelwinst (Ruud). Run 130: 59 trades in ~26 min (~135/u), win 77 %, bruto +1.336, kosten 1.929, netto −593. Noodstop/dataprobleem uit, demo, afstemming 499/501 (2 afwijkingen uitstapprijs).
- DB niet gelezen: uitvoeren via de File editor-app werd deze ronde door de sandbox geweigerd → analyse alleen uit sensoren/logs.
- IG 403 exceeded-account-allowance: >100 logregels in ~2 u, pieken van 10 mislukte orders binnen 10 s, koers tot 57 s oud zonder exitbeheer. Oorzaak (bug): elke 403 → opnieuw inloggen, ook bij een limietfout; die login raakt dezelfde limiet.
- **2.6.0** (suite 2183 groen/5 skip, in HACS, herstart Ruud): limietfout (exceeded-*) direct als fout, geen herlogin; sessie blijft. Vingerafdruk ongewijzigd. Versietests 2.5.9 naar >=.
- Instellingen: niets (fix pakt de limiet aan; een optiewijziging herlaadt de integratie midden in een run).
- Voorstel (strategie, niet gebouwd): reeksstukken krijgen doel = koers + 0,5 bij plaatsing, maar 2e/3e stuk in dezelfde cyclus vult hoger → effectief doel 0,17-0,35 USD bij gedeelde stop ~3,5 USD (R:R ~1:15). Doel vanaf de vulprijs, of max 1 stuk per cyclus.
- Meten na herstart: 403-regels per uur (moet fors dalen), "Openen mislukt" per uur.

laatste ronde: 13-10 16:30

## 13-10 ~16:40 · ronde 8b (geplande controle, parallel aan ronde 8)
- Zelfde 403-fix gebouwd en getest (2182 groen), maar 2.6.0 stond al op main → niet uitgebracht (dubbel). 2.5.9 actief, run 130 (14:04 UTC), 28 trades (19 dicht, −1.238).
- DB wel gelezen (File editor werkte). Vandaag n=1.121 dicht: netto −46.059 USD, bruto −2.974, kosten 0,79 USD/oz tegen MFE 0,96/oz, MAE −1,87/oz; win 35 %, PF 0,41, t −10,7. Trades/u 11-13 UTC: 139/169/185.
- Runs 128-130 n=212: −9.887 (t −5,0). Sluitredenen: broker_gesloten_gemeten 102 (−5.858), stop 54 (−3.541), doel 22 (+552), omkeer-exit 15 (13 verlies, −0,4..−3,6 USD/oz), deelwinst 4 (+356).
- Vandaag per bron: scalp-turbo n=79 −3.155 (win 16 %, t −4,6); scalp-pyramide n=105 −3.032 (win 60 % maar PF 0,34: MFE 0,08/oz); 1m-opzetten allemaal negatief (donchian t −5,0, pullback −4,0, structuur_hl −3,7, momentum −4,1 → uitgezet n=102; rsi_rev:1m uitgezet n=115).
- Instellingen: niets (laatste wijziging 13:01 UTC < 48 u; dagverlies ~0,46 % rekening, geen acuut risico).
- Voorstel (strategie/instelling, niet gedaan): turbo uit (scalp_turbo) bij n ≥ 100 als t < −2 blijft; 1m-tijdvak als geheel uit (kosten ≈ MFE). Grootte: alles op 0,5 contract; risico via grootte i.p.v. aantal pas na bewijs.
- Let op: 21 HA-afsluitingen in 6 u → elke herstart nieuwe IG-login (+ quotum) en nieuwe run.

laatste ronde: 13-10 16:40

## 13-10 ~17:15 · ronde 9 (geplande controle, RUST IN DE REGELS)
- Actief 2.5.9, run 130 (14:04 UTC); 2.6.0 (403-fix) staat in HACS, wacht op herstart Ruud. Geen nieuwe commits sinds ronde 8. Noodstop/dataprobleem uit, demo, 12-14 open met stops. Afstemming 501/505 (4 afwijkingen uitstapprijs).
- Run 130 n=146 dicht in 68 min (~130/u): netto −5.978, t −4,1, DD −5.978 (geen piek), win 55 %, slippage instap gem. 0,21 USD/oz. Vandaag n=1.251: −50.175, t −11,1.
- Per bron run 130: scalp-reeksstukken n=48 −2.492 (win 58 %, PF 0,22, MFE 0,08/oz, MAE −2,35/oz); vp:1m n=23 −1.342 (t −3,1); vp:3m n=17 −1.062; turbo-uitbraak n=17 −328; vp:15m n=10 ~0; vp:30m n=9 +195 (PF 2,4).
- Uitstap: stop n=50 −3.018, broker_gesloten n=48 −3.385, tijd n=15 −746, doel n=14 +346, deelwinst n=11 +880, omkeer-exit n=3 −58.
- Nog steeds 403 exceeded-account/api-key-allowance (9x koers, 6x openen sinds 14:31 UTC) → 2.6.0 actief maken lost de herlogin-verdubbeling op.
- 15:02 UTC: 2 posities met stop broker ≠ DB (DB strakker). modify_stop telt "gelukt" op dealReference zonder deal-bevestiging; een door IG geweigerde verplaatsing komt zo in de DB. Niet gebouwd (extra bevestiging kost een verzoek per stopverplaatsing bij al krappe limiet); meten of het vaker voorkomt.
- Code: niets (geen aantoonbare bug met verlies; dubbele wachtende release vermeden). Instellingen: niets (< 48 u, geen acuut risico, dagverlies ~0,5 % rekening).
- Voorstel blijft: reeksstukken (bevestigd: MFE 0,08/oz bij gedeelde stop ~2,3/oz = R:R ≪ 1) uit of 1 stuk per cyclus met doel vanaf vulprijs; 1m-tijdvak uit.

laatste ronde: 13-10 17:15

## 13-10 ~18:15 · ronde 10 (geplande controle, RUST IN DE REGELS)
- 2.6.0 actief, run 131 sinds 15:28 UTC (scalp_reeks uit in de vingerafdruk). 75 dicht + 6 open in 43 min (~105/u). Noodstop/dataprobleem uit, demo, alle open posities met stop en doel. Afstemming 503/507 (4 afwijkingen; paren lijken onderling verwisseld, bv. −369/−374).
- Run 131: netto −689, bruto +2.056, kosten 2.746 (0,78 USD/oz), win 52 %, PF 0,75, t −1,0, DD −1.414, slippage instap 0,13/oz.
- Per bron: vp:1m n=26 −1.156 (t −3,2, MFE 0,74/oz < kosten); turbo-uitbraak n=15 −568 (win 6 %); vp:3m n=16 +62; vp:5m n=7 +372; vp:15m n=9 +492; vp:30m n=2 +109 → 3m-30m samen n=34 +1.035. Vandaag n=1.369: −52.145, bruto ≈ 0, kosten 52.377 → kosten zijn het hele verlies.
- 2.6.0 werkt: geen "Inloggen mislukte" meer; 403-limiet nog ~4 korte reeksen/u (2-3 koersvragen, 1x 6 orders in 0,5 s om 15:00 UTC) i.p.v. >50/u.
- Code: niets (geen aantoonbare bug met verlies). Instellingen: niets (laatste wijziging 15:28 UTC < 48 u).
- Voorstel bij volgende wijzigingsronde (≥ 15-10 15:28 UTC, als het zo blijft): turbo uit (dag n≈94, t < −4) en 1m-tijdvak uit; tijdvakken 3m-30m houden.
- Meten: blijft 3m-30m positief bij n ≥ 100; 403-reeksen per uur.

laatste ronde: 13-10 18:15

## 13-10 ~19:15 · ronde 11 (geplande controle, RUST IN DE REGELS)
- 2.6.0 actief, run 131 (15:28 UTC), geen nieuwe commits. 165 dicht + 7 open in 101 min (~98/u). Noodstop/dataprobleem uit, demo, alle open met stop en doel. Afstemming 502/506 (zelfde 4 afwijkingen).
- Run 131: netto −2.647, bruto +3.061, win 52 %, PF 0,62, t −2,4. Dashboard −2.420 EUR ≈ DB in EUR; 162 vs 165 trades (lag).
- Per bron: turbo n=33 −1.582 (win 9 %, PF 0,10, t −3,9); vp:1m n=55 −2.398 (MFE ≤ 0,8/oz); vp:3m n=39 −51; vp:5m n=16 +730; vp:15m n=17 +351; vp:30m n=4 +218 → 5m-30m n=37 +1.299.
- Uitstap: tijdslimiet n=20 −1.170 (win 5 %), deelwinst n=15 +875, stop n=64 −566, broker_gesloten n=63 −1.547.
- Logs: 403-limiet nog 1 reeks (5 orders 15:00 UTC), geen herlogin meer; DNS/time-outs naar IG 16:33 UTC (los, herstelde zich).
- Code: niets. Instellingen: niets (< 48 u sinds 15:28 UTC).
- Voorstel blijft (volgende ronde ≥ 15-10 15:28 UTC, als n het bevestigt): turbo uit en 1m-tijdvak uit; samen −3.980 van −2.647 in deze run.

laatste ronde: 13-10 19:15

## 13-10 ~20:15 · ronde 12 (geplande controle, RUST IN DE REGELS)
- 2.6.1 (uit de chat met Ruud, 17:12 UTC) geïnstalleerd en actief: run 132 sinds 17:48 UTC. Bij de start uitgezet: alle 1m (n=507, t −9,8), alle 3m (n=276, t −5,4), scalp+turbo (n=395, t −9,0). Run 132 handelt alleen nog 5m/15m/30m: 13 trades in 22 min (~35/u, was ~100/u).
- Run 132 n=11 dicht: −1.180, bruto −797, kosten 383 (0,85/oz), win 45 %, t −1,7 → n veel te klein. Run 131 eindstand n=223 −1.617 (t −1,2). Vandaag n=1.529 −54.284 (≈0,5 % rekening).
- Noodstop/dataprobleem uit, demo, 2 open (vp momentum:15m, rsi_rev:5m) met stop en doel. Afstemming 500/504 (4 afwijkingen, DB-bedrag ≠ broker, geen netting).
- Logs: DNS-time-outs naar IG 19:13 en 19:57 lokaal (herstelde zich); geen 403-reeksen meer. Stop broker ≠ DB 2x (19:12 4148,97 vs 4153,64; 20:08 4159,30 vs 4159,55). Exitbeheer stuurt de stop elke cyclus opnieuw vanaf de brokerpositie → lijkt zelfherstellend, geen aantoonbaar verlies; niet gebouwd.
- Oude rijen zonder close_time (aug/sep, strategie leeg, 21 stuks) staan nog in trades; niet bij de broker → alleen administratief.
- Code: niets. Instellingen: niets (< 48 u sinds 15:28 UTC, geen acuut risico).
- Meten: 5m-30m bij n ≥ 100 in run 132 (eerder +; nu klein −); trades/uur na de uitschakeling.

laatste ronde: 13-10 20:15

## 21-10 ~19:55 · ronde 13 (geplande controle; 2.19.0 actief sinds herstart 16:47 UTC)
- **Gebouwd 2.19.1** (L-GS-020, suite 1892 groen + 5 skip, in HACS gedownload, herstart door Ruud): leeg accountantwoord (saldo én equity 0 na gemeten > 0, of IG zonder saldo) = geen meting → geen vloertoets/noodstop, geen equitypunt; drawdown slaat 0/0-punten over (herstelt IG *Max. drawdown* 100 %). Geen strategie/vingerafdruk geraakt. Test test_v2191_leeg_account (6).
- **Bitvavo-mand staat stil:** "mand: noodstop bij PUMP-EUR" (dagverlies 10,31 % ≥ 10 %, al actief bij herstart 13:45 UTC) blokkeert alle 20 markten. Mand netto −1.392 EUR (PUMP n=86 −1.045, ICNT n=15 −197, PEPE n=46 −150). Hervatten = knop Ruud.
- **Pepperstone** (sensor n=1.571): netto −8.739, bruto −2.477, kosten 6.262 (3,99/trade). Per tijdvak netto: 5m −3.579 (bruto −2.232, n=411), 3m −1.604 (bruto +1.090), 1m −1.430, 15m −1.266, 30m −861. Families: alleen bb_fade (+287, n=97) en structuur_hl (+35) ≥ 0; beste opzet structuur_hl:3m t 1,98 bij 45 opzetten → overleeft Bonferroni niet (|t| ≳ 3,2).
- **IG** run 135: n=161, netto −86, PF 0,97, t −0,11. Veldproef 1m/3m/5m uitgezet; 15m/30m deels via kostregel. Afstemming IG 2/2232, XAUUSD 7/1687 afwijkingen (oud).
- **Daghandel** draait nu (2.19.0): reden "geen_uitbraak" op kanaal 20 uur/uur-EMA bij beide; nog 0 trades sinds 16:47 UTC.
- Instellingen: niets (geen gemeten verlies met voldoende n dat een instelling verklaart; Bitvavo: eerst noodstop oorzaak, memecoins PUMP/ICNT dragen 89 % van het verlies → volgende ronde min_volume/marktkeuze overwegen bij n ≥ 200 mand).
- Meten: na herstart IG drawdown ≈ 0 %; daghandeltrades per dag; mand per markt na hervatten.

laatste ronde: 21-10 19:55

## 22-10 ~06:20 · ronde 14 (geplande controle; 2.19.2 actief na herstart 21-10 ~20:30 UTC)
- **Gebouwd 2.19.3** (suite 1899 groen + 5 skip, release via workflow, in HACS gedownload, herstart = Ruud): export_data leest bij de Bitvavo-mand alle leden (gaf total 0 bij 311 trades), kolom `markt` + filter `markt`. Geen strategie/vingerafdruk geraakt.
- **Uitstapanalyse Pepperstone** (volledige export, 1752 rijen = 1466 posities met deelsluitingen samengevoegd): netto −10.154, bruto −3.050, kosten 7.104, t −3,6. Win 48 %, gem. winst +52 vs verlies −61. Posities met deelsluiting (n=286) +29.359; zonder (stop/broker/omkeer, n≈1.170) −40.100. Grote verliezers (≤ −60, n=413): mediaan MFE 5,7 USD, 49 % had MFE < 5 → verlies zit in de instap (meteen tegen), niet in de uitstap. Herinstap ≤ 15 min na groot verlies: geen verschil (−7,9 vs −6,9/positie).
- Per opzet (46): beste vp:inside:1m t 1,85, structuur_hl:3m 1,20 → niets overleeft Bonferroni (|t| ≳ 3,3). Families inside/bb_fade bruto +, netto ≈ 0. Sessie: Azië −4.263 (t −2,6), NY 17-24 −3.031 (t −2,2). Sinds vorige ronde n=41 +490.
- **IG** run: n=195, netto −426, PF 0,89, t −0,49. **Daghandel**: uitbraaksignalen (short, 1,8 ATR) maar 05:50 UTC buiten 07-17 → nog 0 trades.
- **Bitvavo-mand: weer noodstop** (BILL-EUR 10,03 %, PUMP-EUR 10,06 % dagverlies; blijft na herstart actief) → hervatten = knop Ruud. Mand n=311 −3.992 EUR (≈ −40 % papier): PUMP n=184 −2.365, BILL n=37 −1.055, PEPE n=90 −573; alle andere markten 0 trades.
- **Instelling Bitvavo-mand** (papier): risk_per_trade_pct 0,5 → 0,25. Waarom: n=311, alle drie gehandelde markten negatief, 10 %-dagverlies stopt de hele mand → halve grootte = minder noodstops, aantal trades (leren) blijft. Meten: noodstops per dag, netto per trade in R.
- Meten: daghandeltrades vanaf 07:00 UTC; mand per markt via export (na herstart 2.19.3); volgende stap marktkeuze (alleen memecoins halen het kostenfilter?).
- Let op: het herladen door de instelling (06:09 UTC) zette twee papiermarkten van 7.635/8.945 terug naar 10.000 (gezien in woning-analyse) → papiersaldo reset bij herladen = kandidaat-bug volgende ronde.

laatste ronde: 22-10 06:25

## 22-10 ~19:55 · ronde 15 (geplande controle; 2.20.3 actief sinds herstart 17:07 UTC)
- Sinds ronde 14: 2.19.4-2.20.3 uit de chat (afstemming). Instellingen op 14:48 UTC gewijzigd (niet door deze ronde) → nieuwe runs IG 136 / Pepperstone 5 / mand.
- **Pepperstone** totaal n=1.833: netto −10.034, bruto −2.550, kosten 7.483, t −3,9. Sinds 06:25 n=80 +148 (t 0,3); run 5 n=24 +615 (t 3,2, maar n klein en 15 posities). Per tijdvak sinds 19-10: 5m −1.660 (t −2,0), 3m −1.205, 30m −782, 15m −272 (bruto +111). Geen opzet overleeft Bonferroni.
- **IG** totaal n=3.546 −67.470 (bruto +1.453 → kosten zijn het verlies). Sinds 06:25 n=68 −229 (bruto +171, kosten 400); run 136 n=19 +126.
- **Daghandel** handelt sinds 2.19.0: Pep n=8 +8,7, IG n=8 −16; posities 0,01-0,03 oz (stop 4 ATR15), deelwinst + break-even na ~1,5 USD → duur minuten (zo bedoeld sinds 2.5.1/2.5.9, Ruud); n te klein.
- **Bitvavo-mand** sinds 06:25 n=82 −785 EUR: bruto ≈ 0, kosten 781 (BILL spread 0,18 %). Alleen BILL/PUMP/PEPE handelen; rest weigert (spot short / kostenfilter).
- **Gebouwd 2.20.4** (suite 1948 groen + 5 skip): Pepperstone-afstemming koppelt op positionId (58312111: deel/rest 9,5 oz vs hele oz bij broker → nooit gekoppeld; `nagezocht` leeg bewees dat de deals er al waren). Uitgebracht (release v2.20.4 via workflow; de 403 gold alleen de handmatige tagpush), in HACS gedownload; herstart = Ruud. Zijtak `claude/v2.20.4` mag weg.
- Instellingen: niets (Bitvavo < 48 u sinds 06:09; IG/Pep net nieuwe run).
- Meten: na 2.20.4 afstemming XAUUSD 0 afwijkingen; run 5/136 bij n ≥ 100; mand kosten/bruto per markt.

laatste ronde: 22-10 19:55

## 23-10 ~06:05 · ronde 16 (geplande controle; 2.21.0 actief sinds herstart 05:39 UTC)
- Sinds ronde 15: 2.21.0 uit de chat (limiet per richting over alle strategieën, afstemming één deal per trade, saldosprong papier, cTrader-tempo). Geen dubbel werk; deze ronde geen code.
- **Pepperstone** run 5 (sinds 22-10 14:48): n=99 netto +957, bruto +1.160, kosten 203; win 71 %; t 0,95 over 4 clusters (per trade 1,68) → niet significant. Gedragen door de daling 4061→3990 (bijna alles short). Veel dubbele instappen op één prijs/moment (donchian:30m + structuur_trend:30m e.d.) blazen n op; 2.21.0 stopt dat. Afstemming 1906/1907: rest 4174,32 bedrag eenmalig overgenomen (+37,75 → +22,65) bij de eerste ronde na 2.21.0 → volgende ronde 0 verwacht.
- **IG** run 136: n=54 +57, PF 1,06; rsi_rev:15m n=18 −136 (bruto −9, kosten 127). Afstemming in orde.
- **Daghandel**: Pep 2 (+10,7), IG 1 (+0,8). n te klein.
- **Bitvavo-mand** run 5: n=324, netto ≈ −3.520 EUR (PUMP n=122 −1.749, BILL n=119 −1.393, PEPE n=83 −378); 17 markten weigeren (kostenfilter/spot short). Geen noodstop nu, 9 open (limiet 3/richting/markt).
- Logs schoon; ruis: "HA sluit af" ~22× per herstart (één per mandlid) → kandidaat kleine fix (één keer warning, rest debug).
- Instellingen: niets (mand < 48 u sinds 22-10 06:09; IG/Pep gewijzigd 22-10 14:48).
- Volgende ronde (na 24-10 06:09): mand marktkeuze/kosten (−11 EUR/trade, kosten ≈ verlies); Pep afstemming 0; aantal gelijktijdige posities na 2.21.0.

laatste ronde: 23-10 06:05

## 23-10 ~20:00 · ronde 17 (geplande controle; 2.21.1 actief)
- **Gebouwd 2.21.2** (L-GS-019, suite 1972 groen + 7 skip, release via workflow, in HACS gedownload; herstart = Ruud): `strategie` per positie op *Open posities*. Alleen weergave. L-GS-022/023 blijven voor de dagafsluiting (niet dubbel gebouwd).
- **Pepperstone** run 5: n=133 netto +23 (PF 1,007), kosten 279 (2,1/trade). Per tijdvak: 3m n=56 −619 (bruto −453, kosten 166); 15m n=43 +283; 30m n=26 +356; 5m n=5 −10. 3m ook eerder steeds negatief (ronde 13/15), maar n < 200 en niets overleeft Bonferroni.
- **IG** run 136: n=78 +123 (PF 1,09, t 0,59); kosten 421 = 77 % van bruto. rsi_rev:15m n=29 bruto +155, kosten 204 (7,0/trade) → kostregel grijpt bij n ≥ 40 als het zo blijft.
- **Daghandel**: Pep 3 (+12,6), IG 2 (+0,4). Gelijktijdig tegengesteld (14:30: daghandel short + bb_fade:15m long) = dubbele spread zonder netto blootstelling; n=1, alleen noteren.
- **Bitvavo-mand**: noodstop sinds 16:30 (bij PEPE-EUR), alle markten geblokkeerd → hervatten = knop Ruud. Alleen PUMP (n=172 −2.390) en PEPE (n=163 −1.243) handelen; BILL weg; 18 markten weigeren (spot short/kosten).
- Negatieve kosten in export = gunstige slip t.o.v. het beslismidden (zo bedoeld, `learning/kosten.py`); geen bug.
- Instellingen: niets (Pep/IG gewijzigd 22-10 14:48, mand 22-10 06:09 → < 48 u).
- Volgende ronde (na 24-10 14:48): Pep `vp_tijdvakken_uit` + 3m overwegen als 3m bij n ≥ 100 nog bruto < 0; mand: marktkeuze (alleen memecoins halen het filter, kosten ≈ verlies); risk_per_trade_pct 3 bij Pep = groot (gezet 22-10, niet door deze ronde).

laatste ronde: 23-10 20:00

## 24-10 ~07:55 · ronde 18 (geplande controle; 2.21.3 actief sinds herstart 05:41 UTC, 2.22.0 gedownload → herstart = Ruud)
- Sinds ronde 17: 2.21.3 en 2.22.0 uit de chat (weekendsluiting, spreadgrens mand 0,03 %, noodstop per markt, oordeel op clusters). Geen dubbel werk; deze ronde geen code.
- Weekend: goud dicht. **Pepperstone** run 5 n=138 netto −137 (PF 0,96, t −0,11); sinds ronde 17 1 trade. Per tijdvak: 3m n=59 −738 (bruto −547, kosten 190), 15m n=44 +235, 30m n=27 +364. structuur_hl:15m n=11 +357 (t 3,6) / structuur_trend:30m n=7 +273: n te klein, Bonferroni niet gehaald. 1 short open over het weekend (58810248, stop 3999,16 ≈ instap).
- **IG** run 136 n=80 +182 (PF 1,13, t 0,81); rsi_rev:15m n=31 bruto +229, kosten 218 (7,0/trade) → kostregel bij n ≥ 40.
- **Mand**: geen trades sinds noodstop PEPE-EUR (23-10 16:31); 2.22.0 laat na herstart de rest weer meten. Logs schoon (alleen de bewaarde noodstops PEPE/BILL).
- Instellingen: niets (48-u-grens Pep/IG tot 24-10 14:48; markt dicht).
- Volgende ronde: na herstart 2.22.0 controleren (weekendsluiting vr, mand per markt, oordeel); Pep 3m bij n ≥ 100 nog bruto < 0 → `vp_tijdvakken_uit` + 3m overwegen.

laatste ronde: 24-10 07:55

## 24-10 ~18:05 · ronde 19 (geplande controle; 2.22.0 actief sinds herstart ~08:17 UTC)
- **Gebouwd 2.22.1** (bug, suite 2009 groen + 7 skip, release via workflow, in HACS gedownload; herstart = Ruud): kostenfilter rekende de taker-fee niet mee bij een kleine koers. `_commissie(1.0)` rondt af op 4 decimalen → PUMP-fee per eenheid 0,0000186 werd 0; filter zag alleen spread+slip (min. stop 0,27 % i.p.v. ~4 % zoals BTC/ETH/XRP). Nu `_commissie_ruw` in `_kosten_per_oz`; goud ongewijzigd.
- **Mand**: alleen PUMP-EUR handelt (spread 0,0295 % net onder de grens 0,03 %). n=384 (runs 4-5) netto −5.124, bruto −1.024, kosten 4.100; 372/384 op de stop; 3m n=167 bruto t −5,5. Sinds herstart n=28 −369 (win 7 %). Na 2.22.1 verwacht: mand vrijwel stil (alles weigert op kosten) — eerlijke uitkomst bij 0,5 % rondreis.
- **Pepperstone/IG**: weekend dicht, geen nieuwe trades. Pep run 5 n=138 −137 (oordeel nu insufficient_data door 2.22.0); IG n=80 +182. Pep-short 58810248 nog open over het weekend.
- Logs: alleen losse koersfouten Bitvavo (gekruist orderboek SOL-EUR, 6×). Instellingen: niets (fix lost het mandprobleem op; markt dicht).
- Volgende ronde: na herstart 2.22.1 controleren dat PUMP weigert ("kostenfilter"); maandag Pep 3m (n=59 bruto −547) bij n ≥ 100 → `vp_tijdvakken_uit` + 3m overwegen; vrijdag weekendsluiting meten. Open vraag voor Ruud (geen actie nu): mand alleen zinvol met lagere kosten (maker/limietorders) of langere tijdvakken.

laatste ronde: 24-10 18:05

## 25-10 ~07:50 · ronde 20 (geplande controle; 2.22.1 actief sinds herstart 06:00 CET)
- 2.22.1 actief (update-entiteit off = bijgewerkt). Geen nieuwe commits op main sinds 2.22.1; tussenronde 07:40 had dezelfde stand → geen dubbel werk, geen code.
- Zondag: goud dicht, IG/Pep 0 nieuwe trades (Pep-short 58810248 open). Mand: 12 leden, 0 trades/0 open, oordeel insufficient_data, toestand running; PUMP niet meer in handel (kostenfilter/spread).
- Logs: alleen bewaarde noodstops pepe-eur/bill-eur (geen mandlid, geen effect) en 1 losse Bitvavo-koersfout (ANIME-EUR). Instellingen: niets.
- Volgende ronde (ma 26-10): Pep 3m (n=59 bruto −547) bij n ≥ 100 → `vp_tijdvakken_uit` + 3m; mand: weigert PUMP op "kostenfilter"?; L-GS-026 staat gepland voor de dagafsluiting 26-10 (niet zelf bouwen).

laatste ronde: 25-10 07:50

## 25-10 ~19:50 · ronde 21 (geplande controle; 2.23.0 actief, update-entiteit off)
- Sinds ronde 20: 2.22.2 (mandgrootboek) en 2.23.0 (spot-longs 1h/4h/1d) uit de chat; tussenronde 19:40 (LEERLOG.md) plande L-GS-027 (opstartartefact mandsensoren) voor de dagafsluiting 26-10 → niet dubbel gebouwd; geen code deze ronde.
- **Mand** (stand 19:48): 19 leden, 564 trades (oud, vooral PUMP/PEPE/BILL), netto −6.340, PF 0,12; 2.23.0-longs nog 0 gesloten → geen oordeel. Mand-equity 3.711 < vermogensvloer 5.000 is de som van alle leden (elk eigen saldo); geen blokkade, papier.
- PEPE-EUR weer lid en geblokkeerd door de bewaarde noodstop (10,05 %); bewust zo laten (hervatten = Ruud, en PEPE was een verliezer).
- **Goud**: zondag dicht; IG/Pep 0 nieuwe trades, Pep-short 58810248 open. Logs: alleen bewaarde noodstops PEPE/BILL.
- Instellingen: niets (markt dicht; Pep 3m n=59 < 100).
- Volgende ronde (ma 26-10): Pep 3m bij n ≥ 100 en bruto < 0 → `vp_tijdvakken_uit` + 3m; eerste gesloten `vp:*:1h|4h|1d` in de mand (netto vs. kosten); L-GS-027 na dagafsluiting controleren.

laatste ronde: 25-10 19:50

## 26-10 ~07:55 · ronde 22 (geplande controle; 2.24.0 actief sinds herstart 07:47)
- 2.24.0 actief (update-entiteit off). Tussenronde 07:40 en 2.24.0 uit andere sessies; L-GS-030 gepland voor dagafsluiting 27-10 → niet dubbel gebouwd, geen code.
- L-GS-029 eerste toets OK: na herstart 07:47 geen "Noodstop uit een eerdere sessie" meer (BILL-EUR); 0 recorder-WARNINGs mand; alle noodstop-sensoren off.
- **Pepperstone** run 5 n=168 netto +111 (bruto 548, kosten 437, PF 1,03, t 0,16). 3m n=72 netto −550, bruto −303 (bruto t −0,57); 15m n=60 +390; 30m n=27 +364. structuur_hl:15m n=12 +359 (t 3,5): klein n, Bonferroni niet gehaald.
- **IG** run 136 n=89 netto +91 (bruto 578, kosten 487 = 84 %); rsi_rev:15m n=38 bruto 181 > 0,5 x kosten (130) → kostregel niet geraakt.
- Instellingen: niets (Pep 3m n=72 < 100 → wachten).
- Volgende ronde: Pep 3m bij n ≥ 100 en bruto < 0 → `vp_tijdvakken_uit` + 3m; IG rsi_rev:15m bij n ≥ 40; mand: eerste `vp:*:1h|4h|1d` gesloten.

laatste ronde: 26-10 07:55

## 26-10 ~20:00 · ronde 23 (geplande controle; 2.24.0 actief, 2.24.1 + 2.24.2 gedownload → herstart = Ruud)
- **Gebouwd 2.24.2** (bug; suite 2086 groen + 7 skip; release via workflow, in HACS gedownload): kostenfilter gold op spot alleen voor `vp:*`; de daghandel (stops in ATR(15m)) liep erbuiten. HYPE-EUR 26-10 15:00/15:15: 2 daghandeltrades, bruto +0,70, kosten 12,39 (0,51 % rondreis), netto −11,70. Nu ook daghandel op spot door het filter; goud ongewijzigd. Plus testopzet: `test_v2241` importeerde niet zonder HA (stub SensorEntityDescription).
- **Pepperstone** run 5 n=198 netto −90 (bruto 429, kosten 519). 3m: 81 regels / 66 posities, netto −783, bruto −483 (bruto t −0,87) → nog < 100 posities, wachten. vp:inside:3m 36 posities bruto −232 < 0,5 × kosten 201 → kostregel grijpt zelf bij n=40. 15m n=76 +583 (t 1,43), 30m n=32 +203: geen Bonferroni.
- **IG** run 136 n=116 netto −244 (bruto 413, kosten 657 = 159 %); vandaag −425 (bruto −204). rsi_rev:15m alle runs 152 posities bruto 1.074 ≈ kosten 1.103 → kostregel (0,5×) niet geraakt.
- **Mand**: eerste 2.23.0-trade NEAR vp:rsi_rev:4h +10,50 (bruto 13,38, kosten 2,88); 19 open. n=1: niets te zeggen.
- Instellingen: niets. Logs: DNS-storing 19:33 (extern, afgevangen). Let op: 2 losse branches `claude-test-push`/`release-2.24.2` op GitHub (verwijderen lukte hier niet; mogen weg).
- Volgende ronde: na herstart 2.24.2: mand weigert daghandel op "kostenfilter" (HYPE); Pep 3m bij ≥ 100 posities en bruto < 0 → `vp_tijdvakken_uit` + 3m.

laatste ronde: 26-10 20:00

## 27-10 ~07:55 · ronde 24 (geplande controle; 2.24.3 actief sinds herstart 06:04, update-entiteit off)
- 2.24.3 en tussenronde 07:40 uit andere sessies; L-GS-033 gepland voor dagafsluiting 28-10 → niet dubbel gebouwd, geen code.
- **Pepperstone** run 5: 227 posities, netto −879 (bruto −301, kosten 578), PF 0,84, t −1,05. 3m n=85 netto −1.110, bruto −799 (bruto t −1,38); 15m n=89 +169, 30m n=43 +229: geen Bonferroni. Vandaag 24 pos −522.
- vp:inside:3m run 5 n=40 bruto −475, maar kostregel telt alle runs (n=137, bruto 485 > 0,5 × 555) → terecht nog aan; geen bug.
- **IG** run 136: 130 trades, netto −376, PF 0,86, t −0,59 (gelijk aan 07:40).
- Logs: losse koersfouten (IG time-out, gekruist BTC-EUR-orderboek, ANIME-EUR), afgevangen. Afstemming beide in_orde, geen noodstop.
- Instellingen: niets (Pep 3m n=85 < 100).
- Volgende ronde: Pep 3m bij ≥ 100 posities en bruto < 0 → `vp_tijdvakken_uit` + 3m.

laatste ronde: 27-10 07:55

## 27-10 ~19:55 · ronde 25 (geplande controle; 2.24.3 actief, update-entiteit off)
- Sinds ronde 24 alleen tussenrondes 11:40/15:58/19:41 (LEERLOG.md); geen nieuwe commits op main → geen code, niets dubbel.
- **Pepperstone** run 5: 259 regels / 209 posities, netto −478 (bruto +213, kosten 691), PF 0,92, t −0,54. 3m 81 posities netto −928, bruto −534 (bruto t −0,78) → nog < 100. 15m 78 pos +343, 30m 37 pos +214, daghandel 4 pos +17: geen Bonferroni.
- 3m over alle runs: 595 posities bruto +1.187, kosten 3.439 → kosten > bruto (H-GS-11), automatische regels (inside/structuur_hl:3m bruto > 0,5 × kosten) terecht niet geraakt.
- **IG** run 136: 161 trades, netto −719 (bruto +170, kosten 889 = 5,2 × bruto), PF 0,78, t −1,15. rsi_rev:15m run 82 trades bruto −112; alle runs n=323 bruto 2.108 > 0,5 × 3.183 → kostregel niet geraakt, t −0,7.
- Status: geen noodstop, afstemming IG/Pep in_orde, logs alleen afgevangen Bitvavo-koersfouten (7×). Mand 576 trades −6.436, 16 open.
- Instellingen: niets (Pep 3m n=81 < 100).
- Volgende ronde: Pep 3m bij ≥ 100 posities en bruto < 0 → `vp_tijdvakken_uit` + 3m; L-GS-033 na dagafsluiting 28-10.

laatste ronde: 27-10 19:55

## 27-10 ~20:35 · akkoord Ruud 20:16, gebouwd 2.25.0
- Punt 4 (mand-vermogensvloer op papier): akkoord 27-10, gebouwd in 2.25.0 - de vloer toetst op papier elke cyclus de equity van de hele mand (som van alle leden + archief), net als live; verwacht: papiermand direct na herstart in noodstop (~3.630 < 5.000).
- Punt 7 (L-GS-031, rooster op New Yorkse tijd): akkoord 27-10, gebouwd in 2.25.0 - `SPOT_GOLD` in America/New_York, weekendgrendels schuiven mee; L-GS-031 afgehandeld. Suite 2131 groen + 5 skip; release v2.25.0, in HACS gedownload, herstart door Ruud.

laatste ronde: 27-10 20:35

## 28-10 ~07:55 · ronde 26 (geplande controle; 2.25.1 actief, 2.25.2 gedownload → herstart = Ruud)
- 2.25.1/2.25.2 en tussenronde 07:41 uit andere sessies → geen code, niets dubbel.
- **Pepperstone** run 5: 278 posities, netto −509 (bruto +232, kosten 741), t −0,56. 3m **99 posities**, netto −928, bruto −534 (bruto t −0,88); 15m 112 pos +309, 30m 48 pos +223, daghandel 5 pos +17: geen Bonferroni. vp:structuur_hl:3m 41 pos bruto −337, vp:inside:3m 48 pos bruto −135.
- Status: logs alleen één Bitvavo-time-out (afgevangen) en de verwachte mandnoodstop (equity 3.652 < 5.000). IG ongewijzigd t.o.v. 07:41 (170 tr, −732).
- Instellingen: niets (Pep 3m n=99, één onder de vooraf vastgelegde 100).
- Volgende ronde: Pep 3m ≥ 100 posities en bruto < 0 → `vp_tijdvakken_uit` + 3m (laatste instellingenwijziging > 48 u geleden).

laatste ronde: 28-10 07:55

## 28-10 ~19:50 · ronde 27 (geplande controle; 2.25.2 actief sinds herstart 19:18, update-entiteit off)
- Sinds ronde 26 alleen tussenrondes 11:42/15:43/19:43 (LEERLOG.md), geen nieuwe commits op main → geen code, niets dubbel.
- **Telcorrectie:** ronde 26 "3m 99 posities" waren regels (incl. partial_close). Posities (zelfde open_time+opzet samengevoegd): Pep run 5 = 248 (309 regels).
- **Pepperstone** run 5: netto −598 (bruto +331, kosten 929), PF 0,91, t −0,60. 3m **90 posities** netto −840, bruto −307 (bruto t −0,42); 15m 101 pos +149, 30m 41 pos +206, 5m 12 pos −130, daghandel 4 pos +17. Geen Bonferroni.
- **IG** run 136: 194 regels, netto −1.146, bruto −0,5, kosten 1.145 (H-GS-11: verlies = kosten), PF 0,73, t −1,65 (niet significant).
- Status: geen noodstop IG/Pep; mand noodstop blijft (equity 3.652 < 5.000, verwacht). Logs: DNS-time-outs Bitvavo/IG (afgevangen), vp:donchian:15m door kostenregel uit.
- Instellingen: niets (Pep 3m 90 posities < vooraf vastgelegde 100).
- Volgende ronde: Pep 3m ≥ 100 **posities** (niet regels) en bruto < 0 → `vp_tijdvakken_uit` + 3m.

laatste ronde: 28-10 19:50
