# Tijd, geld en herkomst

Wat elk getal in Gold Scalper betekent. Geschreven naar aanleiding van de audit
van versie 5.3.3, waarin drie onderdelen drie definities van een dag gebruikten
en bedragen in euro's en dollars zonder label naast elkaar stonden.

---

## Tijd

| | |
|---|---|
| **Opslag** | altijd UTC. Een tijd zonder tijdzone uit de database is UTC (`timeutil.parse_utc`). |
| **Handelsdag** | de kalenderdag in **Europe/Amsterdam** (`timeutil.trading_day`). De dagelijkse onderbreking van goud (23:00–24:00 lokaal) valt zo samen met de dagwissel. |
| **Sessies** | Azië, Londen, New York: beursuren in **UTC**. Een sessie is geen kalenderdag. |

Eén trade heeft precies één UTC-sluiting en precies één handelsdag.
Dagcijfers, periodeoverzicht, risicodag (dagverlies), live-poort en
robuustheidslabels gebruiken allemaal dezelfde functie.

Voorbeeld: een trade die om 22:30 UTC sluit, valt in de zomer op de **volgende**
handelsdag (00:30 lokaal) en in de winter op **dezelfde** (23:30 lokaal). De
dagwissel ligt in UTC dus om 22:00 in de zomer en om 23:00 in de winter.

---

## Geld

Twee valuta, elk met een vaste rol.

| valuta | wat erin staat |
|---|---|
| **instrumentvaluta (USD)** | trade-P&L (`net_pnl`, `gross_pnl`), kosten (`total_cost`), expectancy, t-statistiek, winstfactor, live-poort, leerlaag, indicatorlab |
| **accountvaluta (EUR)** | equity en balans van de broker, dagverlieslimiet, vermogensvloer, equitycurve, drawdown, `net_pnl_account` |

Waar ze elkaar raken:

| plek | hoe |
|---|---|
| positiegrootte | risicobudget in EUR ÷ **biedkoers**-omrekening → USD ÷ stopafstand in USD per ounce. De biedkant geeft het kleinste dollarbudget: het risico wordt nooit onderschat. |
| resultaat per trade in EUR | bij een correctie het bedrag van de broker zelf (`fx_source = broker_settlement`); anders omgerekend met de middenkoers van dat moment, met bron en tijdstip |
| rapportgrafiek | equity in EUR; de kostenlijn wordt eerst omgerekend. Zonder koers wordt hij weggelaten, met een melding. |

Historische `net_pnl_account` wordt **niet** met één koers gereconstrueerd.

---

## Wisselkoers

Bronnen, in volgorde:

1. **EUR/USD-marktkoers van IG** (`ig_market`), elke vijf minuten ververst.
2. Een koers afgeleid uit een **afgerekende trade** (`broker_settlement`). Die
   overschrijft een marktkoers van minder dan een uur oud niet.
3. De laatst bewaarde koers (`persisted`), met zijn eigen leeftijd.

Geldigheid voor een **nieuwe positie**:

| leeftijd | bruikbaar? |
|---|---|
| ≤ 24 uur | ja |
| 24–72 uur | alleen als IG meldt dat EUR/USD gesloten is |
| > 72 uur | nooit |
| status onbekend | grens 24 uur |
| geen tijdstip (bewaard door een oudere versie) | nee |

Een onbruikbare koers blokkeert **alleen nieuwe posities** waarvoor omrekening
nodig is. Exitbeheer, afstemming en veiligheidsfuncties lopen door.

---

## Balansen

| naam | wat |
|---|---|
| `configured_starting_balance` | de ingestelde startbalans |
| `opening_equity_account` | equity bij de start van de run, bij de broker opgehaald, één keer vastgelegd |
| `current_equity_account` | laatst gemelde equity van de broker |
| `configured_floor` | ingestelde startbalans × vloerpercentage |
| `run_floor` | opening × vloerpercentage |
| `effective_equity_floor` | de **hoogste** van de twee |

De strengste vloer telt, zodat de overstap op de werkelijke opening de
bescherming nooit verlaagt. Het vloerpercentage zelf verandert niet.

---

## Kosten

| `cost_source` | betekenis | in het rapport |
|---|---|---|
| `measured` | eigen sluitorder, werkelijke fill | `1.20` |
| `calculated` | afgeleid uit prijzen, bijvoorbeeld bij een door de broker gesloten positie | `1.20*` |
| `assumed` | gemodelleerd in de papersimulatie | `1.20*` |
| `unknown` | van vóór 5.4.0; herkomst niet meer vast te stellen | `1.20?` |

De kostenlijn komt uit het ledger, in elke modus. Per trade geldt
`gross_pnl − total_cost = net_pnl`.

---

## Sluitredenen

| veld | betekenis |
|---|---|
| `close_reason` | bestaand label, voor achterwaartse compatibiliteit |
| `original_close_reason` | één keer gezet, **nooit** overschreven |
| `reconciled_close_reason` | alleen met bewijs afgeleid: `take_profit`, `stop_loss` of `unknown` |
| `close_reason_source` | `own_order`, `inferred_from_quote`, `reconciled_price_match`, `estimated`, `none` |
| `close_reason_evidence` | de uitleg bij de afleiding |
| `reconciliation_status` | `pending`, `reconciled`, `unfindable` |

Bewijs voor een doeltreffer: de uitstapprijs van de broker ligt binnen 0,01 van
het doelniveau. Voor een stoptreffer idem, maar alleen voor trades vanaf
uitvoeringsversie 2 — daarvóór kan de stop in de database verouderd zijn.

---

## Herkomst van een run

Elke run legt vast: integratieversie, strategieversie, uitvoeringsversie,
configuratiehash, venue, omgeving, modus, tijdsframe, candlebron, valuta's en
de relevante risico-instellingen. Elke trade krijgt zijn uitvoeringsversie mee.

| uitvoeringsversie | gedrag |
|---|---|
| 1 | t/m 5.3.1: open posities als gesloten gezien, geen exitbeheer, positielimiet hield niet |
| 2 | 5.3.2–5.3.3: posities zichtbaar, verplaatste stops teruggeschreven |
| 3 | 5.4.0: één handelsdag, kosten uit het ledger, sluitredenen op bewijs, wisselkoersgeldigheid, alleen afgesloten brokerbars |

Uitvoeringsversie en candlebron zitten in de vingerafdruk: een wijziging start
een nieuwe run. Een run waarin trades elkaar overlappen — onmogelijk bij een
limiet van één positie — wordt gemarkeerd als **methodologisch gemengd**. Die
aantekening wordt toegevoegd, de run zelf blijft onaangeroerd.
