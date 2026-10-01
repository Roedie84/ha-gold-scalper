"""Experiment Lab: een onderzoeksomgeving, geen handelsomgeving.

**EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING**

Deze invariant wordt op drie manieren afgedwongen, en elk ervan heeft een
eigen test:

1. **Wat de Lab-code kan bereiken.** Modules in dit pakket importeren alleen
   de standaardbibliotheek en een vaste lijst zuivere modules van Gold
   Scalper (constanten, tijd, en later de rekenregels van strategie en
   backtest). Nooit de coordinator, een broker, de papersimulatie, de
   uitvoeringsveiligheid, de schakelaars en knoppen, de risicobewaking of de
   tradedatabase - ook niet via een tussenmodule. De test loopt de volledige
   importgraaf af en controleert zichzelf met een module die de grens
   opzettelijk overschrijdt.

2. **Wat de Lab-code kan ontvangen.** Geen functie of klasse in dit pakket
   neemt ``hass``, een coordinator, een config entry, een venue of een
   brokeradapter aan. Wat niet binnenkomt, kan geen order plaatsen.

3. **Wat de Lab-code kan schrijven.** Het Lab schrijft uitsluitend in zijn
   eigen databasebestand. Er bestaat geen verwijzing naar config entries,
   opties of de actieve strategie. Promoveren van een configuratie bestaat
   niet.

Eén kanttekening, eerlijk benoemd: Python laadt bij elke import van een
submodule eerst het bovenliggende pakket, en dat van Gold Scalper laadt de
coordinator. Binnen het Home Assistant-proces gaat de grens daarom over wat
Lab-code bij naam kan bereiken en ontvangen.

Beveiligings- en isolatiemechanisme van het werkproces
------------------------------------------------------

Experimenten draaien in een apart proces (fase 3, gemeten gekozen boven een
thread). Dat proces laadt **niet** ``gold_scalper/__init__.py``, en dus niet de
coordinator, de broker of Home Assistant. Hoe:

* ``worker_entry.py`` wordt als **script** gestart, niet als module;
* het registreert vóór elke import een **leeg** ``gold_scalper``-pakketobject
  met alleen het pad naar de pakketmap, zodat Python het pakket als geladen
  beschouwt en de echte ``__init__.py`` niet uitvoert;
* het draait in Python's geïsoleerde modus (``-I``), met een omgeving die
  alleen ``PATH`` bevat - geen geheimen, geen ``PYTHON*``-variabelen;
* het opent de Lab-database alleen-lezend en schrijft niets;
* het meldt aan het eind welke modules het werkelijk heeft geladen.

**Dit mechanisme is kwetsbaar voor importwijzigingen elders in het pakket.**
Gaat een module die het werkproces laadt (bijvoorbeeld ``analysis`` of
``strategy``) ooit de coordinator, een broker of Home Assistant importeren, dan
komt die via die omweg alsnog het werkproces in. De test
``test_the_worker_process_loads_no_trading_module`` start een echt werkproces
en faalt zodra een verboden module in de gemelde lijst verschijnt. Die test mag
nooit worden verzwakt of overgeslagen.
"""

from __future__ import annotations

#: Leesbare vorm van de invariant, zodat tests en documentatie naar één naam
#: verwijzen.
INVARIANT = "EXPERIMENT_LAB_CAN_NEVER_ENABLE_LIVE_TRADING"
