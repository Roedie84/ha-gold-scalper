"""Lovelace-dashboard, opgebouwd uit de werkelijke entiteit-id's.

Het oude ``lovelace.yaml`` verwees naar id's als ``sensor.gold_scalper_price``.
Home Assistant maakt die niet aan: het apparaat heet "Gold Scalper
<instrument>", dus de koers wordt bijvoorbeeld
``sensor.gold_scalper_cs_d_cfegold_cea_ip_koers``. Gegokte id's leveren een
dashboard vol "entiteit niet gevonden".

Deze module krijgt de id's uit het entiteitenregister - per unieke sleutel -
en bouwt daar het dashboard mee. Wat niet bestaat, wordt weggelaten in plaats
van als kapotte kaart getoond.
"""

from __future__ import annotations

from typing import Any

import yaml


def _entities(ids: dict[str, str], *regels: tuple[str, str]) -> list[dict]:
    return [
        {"entity": ids[sleutel], "name": naam}
        for sleutel, naam in regels if sleutel in ids
    ]


def build_dashboard(ids: dict[str, str], symbol: str = "") -> str:
    """YAML voor de ruwe configuratie-editor van een dashboard.

    ``ids`` koppelt de sleutel van een entiteit (``price``, ``fx_rate``, ...)
    aan zijn werkelijke entiteit-id.
    """
    kaarten: list[dict[str, Any]] = []

    toestand = _entities(
        ids,
        ("status", "Status"), ("mode", "Modus"), ("lifecycle", "Toestand"),
        ("risk_state", "Risico"), ("halted", "Noodstop"),
        ("tradeable", "Markt handelbaar"), ("safe_to_restart", "Veilig herstarten"),
    )
    if toestand:
        kaarten.append({"type": "entities", "title": "Toestand", "entities": toestand})

    bediening = _entities(ids, ("trading_enabled", "Handel actief"))
    for sleutel, naam, icoon in (
        ("resume", "Hervatten", "mdi:play-circle-outline"),
        ("prepare_shutdown", "Afwikkelen voor herstart", "mdi:stop-circle-outline"),
        ("close_all", "Alles sluiten", "mdi:close-octagon-outline"),
    ):
        if sleutel in ids:
            bediening.append({"entity": ids[sleutel], "name": naam, "icon": icoon})
    if bediening:
        kaarten.append({"type": "entities", "title": "Bediening", "entities": bediening})

    meet = _entities(
        ids,
        ("fx_entry", "Nieuwe posities"), ("fx_rate", "Wisselkoers"),
        ("equity_floor", "Vermogensvloer"), ("reconciliation", "Afstemming met broker"),
        ("candle_source", "Candlebron"), ("costs_measured", "Kosten gemeten"),
        ("data_integrity", "Gegevens intact"),
    )
    if meet:
        kaarten.append({"type": "entities", "title": "Meetkwaliteit", "entities": meet})

    exits = _entities(
        ids,
        ("exits_target", "Doel geraakt"), ("exits_stop", "Stop geraakt"),
        ("exits_unknown", "Sluitreden onbekend"),
    )
    if exits:
        kaarten.append({
            "type": "entities", "title": "Hoe trades eindigden", "entities": exits,
        })

    resultaat = _entities(
        ids,
        ("trades", "Trades"), ("net_pnl", "Netto"), ("total_costs", "Kosten"),
        ("win_rate", "Trefkans"), ("profit_factor", "Winstfactor"),
        ("t_statistic", "t-statistiek"), ("max_drawdown", "Max. drawdown"),
        ("verdict", "Oordeel"), ("live_unlocked", "Live vrijgegeven"),
    )
    if resultaat:
        kaarten.append({"type": "entities", "title": "Resultaat", "entities": resultaat})

    markt = _entities(
        ids,
        ("price", "Koers"), ("spread", "Spread"), ("atr", "ATR"),
        ("signal", "Signaal"), ("equity", "Equity"), ("open_positions", "Open posities"),
    )
    if markt:
        kaarten.append({"type": "entities", "title": "Markt", "entities": markt})

    grafiek = [ids[k] for k in ("net_pnl",) if k in ids]
    if grafiek:
        kaarten.append({
            "type": "history-graph", "title": "Netto resultaat",
            "hours_to_show": 168, "entities": grafiek,
        })

    dashboard = {
        "views": [{
            "title": f"Gold Scalper {symbol}".strip(),
            "path": "gold-scalper",
            "icon": "mdi:gold",
            "cards": kaarten,
        }]
    }
    kop = (
        "# Gold Scalper-dashboard, gegenereerd uit het entiteitenregister.\n"
        "# Plakken via Instellingen -> Dashboards -> (dashboard) -> ... ->\n"
        "# Dashboard bewerken -> ... -> Ruwe configuratie-editor.\n"
        "# Opnieuw genereren na een update: actie gold_scalper.write_dashboard.\n\n"
    )
    return kop + yaml.safe_dump(dashboard, allow_unicode=True, sort_keys=False)
