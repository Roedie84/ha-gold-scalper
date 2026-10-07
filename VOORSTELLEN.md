# Voorstellen Gold Scalper

Status: open / akkoord / afgewezen / gebouwd vX / geverifieerd / teruggedraaid. Nooit live handelen, nooit pyramiding, geen knoppen.

## L-GS-001 · doel-/stoptreffers in "geleerd" op de effectieve sluitreden
- Status: **gepland (zelf bouwen: meetfout in rapportage)** — bij de eerstvolgende dagafsluiting
- Onderbouwing: 07-10, n=56: `analyse_execution` gebruikt `t.close_reason`; 24 trades staan daar als `broker_gesloten_gecorrigeerd`. Daardoor target_hit_rate 0,143 / stop_hit_rate 0,429 tegen 19,6% / 80,4% op bewijs (`exit_stats.effective_reason`). De notitie "ATR mogelijk overschat" rust op een ondergrens.
- Bouw: `learning/analysis.py` → `effective_reason(t)` in plaats van `t.close_reason`; test met gecorrigeerde trades. Raakt geen handelslogica.
- Verwacht effect: geleerd.execution gelijk aan sensoren Doel/Stop geraakt; geen misleidende ATR-notitie.
- Meten na bouw: target_hit_rate in geleerd == doel_geraakt-sensor/100 (±0,001).
