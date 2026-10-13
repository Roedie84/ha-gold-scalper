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
