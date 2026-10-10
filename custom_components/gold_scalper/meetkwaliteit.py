"""Rekenregels voor de sensoren die de meetkwaliteit tonen.

Los van Home Assistant, zodat ze te toetsen zijn: de sensorbeschrijvingen
zelf zijn in de testomgeving niet aan te maken. ``sensor.py`` bouwt de
entiteiten uit ``SPECS``; deze module bepaalt wat ze tonen.

Eerst stond wat 5.4 meet alleen in de diagnostiek. Een geblokkeerde
wisselkoers - geen nieuwe posities - bleef daardoor twee versies lang
onzichtbaar.
"""

from __future__ import annotations


def _fx(d: dict) -> dict:
    return d.get("conversion") or {}


def _fx_status(d: dict) -> str:
    c = _fx(d)
    if not c.get("needed"):
        return "niet_nodig"
    return "toegestaan" if c.get("usable_for_entry") else "geblokkeerd"


def _floor(d: dict) -> dict:
    return d.get("balances") or {}


def _exits(d: dict) -> dict:
    return d.get("exit_stats") or {}


def _afstemming(d: dict) -> str:
    r = d.get("reconciliation") or {}
    if not r:
        return "nog_niet"
    return "in_orde" if r.get("in_orde") else "afwijkingen"


def _gemeten_pct(d: dict):
    k = d.get("ledger_costs") or {}
    n = k.get("trades") or 0
    return round((k.get("measured") or 0) / n * 100, 1) if n else None




SPECS: tuple[dict, ...] = (
    dict(
        key="fx_rate", name="Wisselkoers", icon="mdi:currency-eur",
        state_class="measurement", suggested_display_precision=5,
        value_fn=lambda d: _fx(d).get("rate"),
        attrs_fn=lambda d: {
            "richting": _fx(d).get("direction"),
            "bron": _fx(d).get("rate_source"),
            "leeftijd_uren": _fx(d).get("rate_age_hours"),
            "koers_voor_positiegrootte": _fx(d).get("risk_rate"),
            "basis_positiegrootte": _fx(d).get("risk_basis"),
        },
    ),
    dict(
        key="fx_entry", name="Instap op wisselkoers",
        icon="mdi:swap-horizontal-circle-outline",
        device_class="enum",
        options=["toegestaan", "geblokkeerd", "niet_nodig"],
        value_fn=_fx_status,
        attrs_fn=lambda d: {"reden": _fx(d).get("entry_reason")},
    ),
    dict(
        key="equity_floor", name="Vermogensvloer", icon="mdi:floor-plan",
        state_class="measurement", suggested_display_precision=2,
        value_fn=lambda d: _floor(d).get("effective_equity_floor"),
        attrs_fn=lambda d: {
            "valuta": _floor(d).get("account_currency"),
            "toegepast": _floor(d).get("applied"),
            "vloer_ingestelde_balans": _floor(d).get("configured_floor"),
            "vloer_opening_run": _floor(d).get("run_floor"),
            # 1.9.4
            "verliesvloer": _floor(d).get("verliesvloer"),
            "max_verlies_run": _floor(d).get("max_verlies_run"),
            "opening_equity": _floor(d).get("opening_equity_account"),
            "huidige_equity": _floor(d).get("current_equity_account"),
            "ruimte_tot_vloer": (
                round(_floor(d)["current_equity_account"]
                      - _floor(d)["effective_equity_floor"], 2)
                if _floor(d).get("current_equity_account") is not None else None
            ),
            "percentage": _floor(d).get("equity_floor_pct"),
        },
    ),
    dict(
        key="exits_target", name="Doel geraakt", icon="mdi:target",
        native_unit_of_measurement="%",
        state_class="measurement", suggested_display_precision=1,
        value_fn=lambda d: (_exits(d).get("take_profit") or {}).get("pct"),
        attrs_fn=lambda d: {
            "aantal": (_exits(d).get("take_profit") or {}).get("n"),
            "van": _exits(d).get("noemer"),
            "onbekend_pct": (_exits(d).get("unknown") or {}).get("pct"),
            "ondergrens": bool((_exits(d).get("unknown") or {}).get("n")),
            "toelichting": _exits(d).get("toelichting"),
        },
    ),
    dict(
        key="exits_stop", name="Stop geraakt", icon="mdi:hand-back-left",
        native_unit_of_measurement="%",
        state_class="measurement", suggested_display_precision=1,
        value_fn=lambda d: (_exits(d).get("stop_loss") or {}).get("pct"),
        attrs_fn=lambda d: {
            "aantal": (_exits(d).get("stop_loss") or {}).get("n"),
            "van": _exits(d).get("noemer"),
        },
    ),
    dict(
        key="exits_unknown", name="Sluitreden onbekend", icon="mdi:help-circle-outline",
        native_unit_of_measurement="%",
        state_class="measurement", suggested_display_precision=1,
        value_fn=lambda d: (_exits(d).get("unknown") or {}).get("pct"),
        attrs_fn=lambda d: {
            "aantal": (_exits(d).get("unknown") or {}).get("n"),
            "van": _exits(d).get("noemer"),
            "afgestemd": _exits(d).get("afgestemd"),
            # 1.10.0: redenen die achteraf uit de afstemming kwamen.
            "achteraf_ingevuld": _exits(d).get("achteraf_ingevuld"),
            "reden_bron": "afstemming" if _exits(d).get("achteraf_ingevuld") else None,
        },
    ),
    dict(
        key="reconciliation", name="Afstemming met broker",
        # 1.7.0: zichtbaar houden bij een storing.
        blijft_beschikbaar=True,
        icon="mdi:scale-balance",
        device_class="enum",
        options=["in_orde", "afwijkingen", "nog_niet"],
        value_fn=_afstemming,
        attrs_fn=lambda d: {
            "samenvatting": (d.get("reconciliation") or {}).get("samenvatting"),
            "afwijkingen": len((d.get("reconciliation") or {}).get("afwijkingen") or []),
            "moment": (d.get("reconciliation") or {}).get("moment"),
            # 1.10.0: de bewaarde uitkomst overleeft een herstart; "hersteld"
            # zegt dat het die van vóór de herstart is.
            "hersteld": bool((d.get("reconciliation") or {}).get("hersteld")),
            "trades": (d.get("reconciliation") or {}).get("trades"),
            "gevonden": (d.get("reconciliation") or {}).get("gevonden"),
            "kloppend": (d.get("reconciliation") or {}).get("kloppend"),
            "nog_niet_verwerkt": (d.get("reconciliation") or {}).get("nog_niet_verwerkt"),
            "verschillen": [
                a.get("uitleg") for a in
                ((d.get("reconciliation") or {}).get("afwijkingen") or [])[:5]
                if isinstance(a, dict)
            ],
            "sluitreden_ingevuld": (d.get("reconciliation") or {}).get("sluitreden_ingevuld"),
            "laatste_fout": d.get("afstemming_fout"),
        },
    ),
    dict(
        key="candle_source", name="Candlebron", icon="mdi:chart-box-outline",
        device_class="enum", options=["quotes", "broker"],
        value_fn=lambda d: "quotes" if (d.get("candle_setting") or {}).get("effective") else "broker",
        attrs_fn=lambda d: {
            "basisconfiguratie": (d.get("candle_setting") or {}).get("configured"),
            "opties": (d.get("candle_setting") or {}).get("override"),
            "herkomst": (d.get("candle_setting") or {}).get("origin"),
            "tegenstrijdig": (d.get("candle_setting") or {}).get("conflicting"),
        },
    ),
    dict(
        key="costs_measured", name="Kosten gemeten", icon="mdi:cash-check",
        native_unit_of_measurement="%",
        state_class="measurement", suggested_display_precision=1,
        value_fn=_gemeten_pct,
        attrs_fn=lambda d: {
            k: (d.get("ledger_costs") or {}).get(k)
            for k in ("measured", "calculated", "assumed", "unknown", "trades", "total")
        },
    ),
)
