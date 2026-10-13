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
