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
