# ha-gold-scalper 1.0.0

Volledige repository, klaar voor `Roedie84/ha-gold-scalper`. Inhoudelijk
Goldscalper 5.7.0; zie `CHANGELOG.md`.

## Naar GitHub

Sleep de **inhoud** van deze map in de lege repository en commit. Daarna een
release maken: tag `v1.0.0`, titel `1.0.0`. HACS gebruikt de tags.

## Overstappen in Home Assistant

1. HACS → oude repository `Roedie84/Goldscalper` verwijderen (niet de
   integratie zelf).
2. HACS → ⋮ → *Aangepaste repositories* → `https://github.com/Roedie84/ha-gold-scalper`,
   categorie *Integratie* → downloaden.
3. Home Assistant herstarten.

Het domein blijft `gold_scalper`: entiteiten, tradedatabase, barsarchief,
Lab-database en opties blijven werken. De lopende run gaat door (de versie zit
niet in de vingerafdruk). Draaide je nog 5.6.2, dan migreert de Lab-database
bij deze herstart naar schema 9.

Controle: het Lab-paneel toont *Gold Scalper-versie 1.0.0* en *Lab-schema 9
(verwacht 9)*.

## Niet meegenomen

De EMS-bestanden die per ongeluk in de oude repository stonden (`752c044`).
Die horen in de EMS-repository.

## Tests

1640 geslaagd, 1 overgeslagen (de test die een echte Home Assistant vraagt).
