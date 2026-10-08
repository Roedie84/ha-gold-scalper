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

