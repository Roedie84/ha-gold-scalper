# Voorstellen Gold Scalper

Status: open / akkoord / afgewezen / gebouwd vX / geverifieerd / teruggedraaid. Nooit live handelen, nooit pyramiding, geen knoppen.

## L-GS-001 · doel-/stoptreffers in "geleerd" op de effectieve sluitreden
- Status: **geverifieerd 08-10 07:40** (gebouwd v1.7.1 07-10 23:38; geïnstalleerd 07:03): geleerd 0,185 = sensor 18,5% (n=65)
- Onderbouwing: 07-10, n=56: `analyse_execution` gebruikt `t.close_reason`; 24 trades staan daar als `broker_gesloten_gecorrigeerd`. Daardoor target_hit_rate 0,143 / stop_hit_rate 0,429 tegen 19,6% / 80,4% op bewijs (`exit_stats.effective_reason`). De notitie "ATR mogelijk overschat" rust op een ondergrens.
- Bouw: `learning/analysis.py` → `effective_reason(t)` in plaats van `t.close_reason`; test met gecorrigeerde trades. Raakt geen handelslogica.
- Verwacht effect: geleerd.execution gelijk aan sensoren Doel/Stop geraakt; geen misleidende ATR-notitie.
- Meten na bouw: target_hit_rate in geleerd == doel_geraakt-sensor/100 (±0,001).

## L-GS-002 · klokafhankelijke tests vastzetten
- Status: **gepland (zelf bouwen: testrobuustheid, raakt geen handelslogica)**
- Onderbouwing: 07-10 23:25: 4 van 21 tests in `tests/test_unconfirmed_orders.py` falen tijdens de dagpauze van de markt, ook op main zonder wijziging; met de klok vast op 10:00 UTC slagen ze. Een release in de pauze kan daardoor niet met een groene suite.
- Bouw: in die tests (of in conftest) de tijd vastzetten op een handelsmoment, of de markttijd injecteren.
- Meten na bouw: volledige suite groen om 21:30 UTC.

## L-GS-003 · transactiewaarschuwing: juiste venstertekst en geen vals alarm
- Status: **gebouwd 1.7.2 (08-10, chatsessie)** — commit 6ed4659, release v1.7.2 groen, HACS ververst; nog niet geïnstalleerd. L-GS-002 niet meegenomen.
- Uitvoering: vaste drempel <3 vervangen door vergelijking met eigen gesloten trades in hetzelfde venster (alleen trades >6 u dicht tellen); WARNING hooguit 1× per uur met het echte venster in UTC, anders DEBUG; ook 'overzicht leeg' valt hieronder. 7 nieuwe tests; suite 1714 groen, 5 overgeslagen.
- Onderbouwing: 08-10 03:02-03:41: `broker/ig_capital.py` `closed_deal` waarschuwt bij <3 transacties "over de afgelopen vierentwintig uur … datumbereik komt vermoedelijk niet aan", elke ~80 s. Het venster is sluiten −6 u .. +12 u en wordt wel toegepast (telling 2→1 toen het voorbij 07-10 schoof); na de avondpauze is het venster normaal bijna leeg.
- Bouw: heuristiek vergelijken met het aantal eigen trades in hetzelfde venster; tekst met het echte venster; eens per ticket loggen. Test.
- Meten na bouw: 0 van deze waarschuwingen in een nacht zonder echte afwijking.

## L-GS-004 · uitstapprijs navragen vóór afrekenen op een schatting
- Status: **gebouwd 1.7.3 (08-10, chatsessie)** — commit 1bff725, release v1.7.3 groen, HACS ververst; nog niet geïnstalleerd.
- Onderbouwing: 08-10 4 trades op geschatte uitstap (03:35, 04:55, 06:22, 09:21; 3 zonder herstart). Broker sloot zelf op stop/doel; alleen het transactieoverzicht werd gevraagd en dat liep achter ("Slechts 1 transactie(s)"), en de koers stond bij ontdekken al terug van het niveau. Gevolg: sluitreden_onbekend 1/68, kosten 66 gemeten/2 berekend, tot ~$10/trade mis tot de afstemming.
- Bouw: `closed_deal_activity` (IG `/history/activity` v3 detailed; strenge koppeling op `POSITION_CLOSED` + affectedDealId, opening telt nooit; zonder niveau via `/confirms/{dealReference}`) direct bij ontdekken; anders voorlopig + max. 4 herkansingen op 20/60/120/240 s (1 verzoek per poging); correctie en afstemming zetten bij een voorlopige trade in één keer prijs, sluitreden en gemeten kosten. 18 nieuwe tests; suite 1732 groen, 5 overgeslagen. Alleen boekhouding.
- Meten na installatie: (1) WARNING "geschatte uitstapprijs" per dag → verwacht 0 (hooguit bij IG-storing); (2) INFO "alsnog op de brokerprijs afgerekend bij herkansing" telt de vertraagde gevallen; (3) sensor Sluitreden onbekend en kosten berekend → alleen trades < ~5 min oud; (4) `raw_responses.activity_v3` (diagnose) eenmalig controleren op de veldnamen `details.actions[].affectedDealId`/`details.level`. Valt (1) niet naar 0 → activiteitveldnamen wijken af; dan via (4) bijstellen.


## L-GS-005 · tijdstops laten werken op IG (open_time van de positie vullen)
- Status: **open — Ruud beslist** (verandert handelsgedrag; niet zelf bouwen)
- Onderbouwing (08-10, varianten-analyse, zie LEERLOG 08-10 11:00): `broker/ig_capital.py` bouwt `VenuePosition` zonder `open_time`; `coordinator._manage_open_positions` doet `_as_datetime(None, now)` → leeftijd altijd 0 s. Daardoor vuren de ontworpen tijdstop (240 s binnen 0,3×ATR) en de harde limiet (900 s) uit `broker/exits.py` nooit. Gemeten: gem. duur 1408 s, langste 5272 s (> 900). Backtest/Lab rekenen wél met tijdstops → live en backtest zijn op dit punt niet vergelijkbaar.
- Wat verandert: alleen dat `open_time` gevuld wordt (IG `position.createdDateUTC`, terugval: `open_time` van de eigen trade via ticket) + test. **Geen parameterwijziging**; daardoor gaan de bestaande defaults werken: `time_stop_seconds=240`, `time_stop_deadzone_atr=0.3`, `max_hold_seconds=900`. Doel 1,5×ATR, stop 1,0×ATR, break-even 0,8×ATR blijven gelijk.
- Verwacht effect (replay van 66 live trades op het 10-s koerspad, IS = clusters 1-5, OOS = 6-10): netto/trade −3,83 → −1,34 (IS −3,63 → −2,18; OOS −4,04 → −0,49); 49/66 exits worden tijdexits, gem. duur ~1576 → ~263 s, doel geraakt 20% → 8%. Gepaarde t per cluster +2,15 (10 clusters; kritiek 2,26 bij df 9) → **niet bewezen**, en netto blijft negatief: dit verkleint verlies, maakt de strategie niet winstgevend. Replay modelleert niet dat posities sneller vrijkomen en er dus vaker opnieuw ingestapt wordt (meer kosten).
- Meten na invoering: (1) sluitreden "maximale positieduur"/"tijdstop" verschijnt; langste duur ≤ 910 s; (2) netto, bruto en kosten per trade en per cluster tegen baseline live −2,95 netto/trade (68 trades, 10 clusters); trades per cluster tegen 6,8; (3) na 10 nieuwe clusters gepaarde toets: zelfde trades zonder tijdstops naspelen (scripts in `analyse/2026-10-08-varianten/`) vs werkelijk. Houden bij verschil/cluster > 0 met t ≥ 2; terugdraaien bij verschil ≤ 0 na 10 clusters.
