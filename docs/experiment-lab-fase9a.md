# Experiment Lab, fase 9A: paneeltoets (Gold Scalper 5.6.0)

**EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING**

Doel: aantonen dat `panel_custom` veilig en betrouwbaar werkt op Home Assistant
2026.9, voordat fase 9B erop bouwt. Het paneel toont alleen een statusregel.
Geen knoppen, geen runner, geen import, geen TEST-toegang, geen beoordeling,
geen vergelijking.

## Architectuur

```
Home Assistant
  └─ gold_scalper/__init__.py
       ├─ handel: coordinator, platforms, diensten      (ongewijzigd)
       └─ _async_lab()  ── try/except, lazy import ──┐
                                                      ▼
            lab_panel.py  (HA-adapter, BUITEN experiment_lab)
              ├─ hass.config.path("gold_scalper_lab.db")
              ├─ LabDatabase(pad).open()  +  recover_interrupted()  (1x per proces)
              ├─ LabStatusView   GET /api/gold_scalper/lab/status   (auth + admin)
              ├─ StaticPathConfig /gold_scalper_lab/lab-panel.js
              └─ panel_custom    /gold-scalper-lab  (require_admin, geen iframe)
                                                      │  alleen: pad (str), bool
                                                      ▼
            experiment_lab/   (kent geen hass, coordinator, broker, opties)
```

De adapter geeft het Lab uitsluitend een bestandspad en roept alleen
`open`, `recover_interrupted`, `schema_version`, `experiment_count` en `close`
aan. Een test vervangt `LabDatabase` door een spion en bewijst dat.

## Lifecycle

| Moment | Gedrag |
|---|---|
| Setup eerste entry | database openen, herstel (eerste keer in dit proces), route + statisch pad (eerste keer in dit proces), paneel registreren |
| Setup volgende entry | niets: één Lab per Home Assistant |
| Unload laatste entry | paneel verwijderen, verbinding sluiten |
| Herladen | unload + setup: paneel terug, geen tweede herstel, geen dubbele route |
| HA-herstart | nieuw proces: herstel opnieuw, één keer |
| Lab-fout | gelogd onder `custom_components.gold_scalper.lab_panel`; de handel start gewoon |

Herstel zet alleen `running` op `interrupted`. `queued` blijft `queued`; er is
in 9A geen code die iets start. Mislukt het openen, dan wordt herstel bij de
volgende poging alsnog uitgevoerd.

Beperking van Home Assistant: een HTTP-route en een statisch pad zijn niet te
verwijderen. Ze blijven na unload bestaan; de route antwoordt dan
`lab_error: not_loaded`. Het paneel zelf verdwijnt wel.

## Statusroute

`GET /api/gold_scalper/lab/status`

* `requires_auth = True` (Home Assistant weigert zonder sessie met 401);
* daarachter een eigen controle: geen gebruiker 401, geen beheerder 403;
* `Cache-Control: no-store`;
* antwoord bestaat exact uit deze sleutels, allemaal gewone waarden:
  `api_version, authenticated, backend, gold_scalper_version, invariant,
  lab_available, lab_error, lab_schema_version, lab_schema_expected,
  recovery_performed, recovery_interrupted, experiment_count`;
* fouten als code (`open_failed`, `recovery_failed`, `read_failed`,
  `not_loaded`), nooit als tekst: een OSError-tekst bevat het pad.

## Frontend

`frontend/lab-panel.js`: één module, geen buildstap, geen externe scripts of
CDN, geen `eval`/`Function`/`innerHTML`, geen browseropslag, geen token in een
URL. Ophalen via `hass.callApi`; de Home Assistant-frontend voegt de sessie
zelf toe. Alle waarden via `textContent`. De module-URL krijgt
`?v=<versie>-<inhoudshash>`: elke wijziging van het bestand geeft een nieuwe
URL.

## Handmatige acceptatie op Home Assistant 2026.9

Alle punten: **NOT_TESTED — requires real Home Assistant 2026.9 installation.**

| # | Controle | Hoe |
|---|---|---|
| 1 | *Gold Scalper Lab* staat precies één keer in de zijbalk | zijbalk bekijken |
| 2 | Het bestaande *Gold Scalper*-paneel staat er nog | zijbalk bekijken |
| 3 | Het nieuwe paneel opent zonder browserfout | DevTools → Console |
| 4 | De lokale module laadt | DevTools → Network: `/gold_scalper_lab/lab-panel.js?v=5.6.0-…`, status 200 |
| 5 | Geen externe scripts of CDN | Network, filter op JS: alleen je eigen HA-adres |
| 6 | Zonder sessie geen status | privévenster: `https://<ha>/api/gold_scalper/lab/status` geeft 401 |
| 7 | Ingelogd als beheerder: status zichtbaar | paneel toont alle regels; Network: 200 JSON |
| 8 | Geen credentials zichtbaar | Network-antwoord en Application-tab: geen token, wachtwoord of account |
| 9 | Geen lokaal databasepad zichtbaar | antwoord bevat geen `/config/` of `.db` |
| 10 | Paginarefresh registreert niets dubbel | F5; nog steeds één zijbalkitem |
| 11 | Herladen van Gold Scalper geeft geen tweede paneel | Apparaten en diensten → Gold Scalper → Herladen |
| 12 | Herstart geeft geen dubbele registratie | HA herstarten; één item; log zonder `Overwriting panel` |
| 13 | Coordinator werkt | sensoren blijven verversen |
| 14 | Paper/demo-trading onveranderd | zelfde run-ID als vóór de update, trades lopen door |
| 15 | Geen experiment gestart | paneel: *Experimenten* gelijk aan vooraf; niets `running` |
| 16 | Geen TEST-resultaat geopend | `test_access_log` en `wf_test_access_log` in `gold_scalper_lab.db` ongewijzigd |
| 17 | Geen beoordeling gemaakt | tabel `assessments` ongewijzigd |
| 18 | Geen vergelijking gemaakt | tabel `comparisons` ongewijzigd |
| 19 | Actieve configuratie ongewijzigd | opties van Gold Scalper vergelijken met vooraf |
| 20 | Invariant intact | paneel toont `EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING` |

Aanvullend: een gebruiker zonder beheerdersrecht ziet het paneel niet en krijgt
op de statusroute 403.

Werkt `panel_custom` niet: geen terugval naar een onbeveiligd iframe. Dan gaat
9B verder met alleen diensten en meldingen.

## Vastgelegd voor later (geen onderdeel van 9A)

* **IG-quotum.** Vóór grootschalig gebruik van `import_history` eerst meten
  hoeveel van het weekquotum de normale live polling verbruikt. Pas daarna
  bepalen hoeveel historie veilig in één keer kan.
* **Omgekeerde strategie.** Alleen sanity check: bruto hoort ongeveer te
  spiegelen, kosten blijven, asymmetrie wijst op fills, uitvoering,
  richtingseffecten of een fout. Bewijsvraag: bruto OOS-resultaat per trade
  tegen nul, daarna netto tegen nul. Beoordelingsregels in 9A ongewijzigd.
* **Werkproces bij unload (9B).** Herstel draait één keer per proces. Stopt 9B
  bij unload een lopend werkproces, dan moet die unload het experiment zelf op
  `interrupted` zetten; anders blijft het `running` tot de volgende herstart.
* **Versies.** 9A = 5.6, 9B deel 1 = 5.7, 9B deel 2 = 5.8 (5.7.1 alleen als
  klein en achterwaarts compatibel).
