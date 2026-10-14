"""Geheimen uit secrets.yaml (2.8.0).

Ruud wil nooit tokens in een chat of formulier plakken: ze staan in
``secrets.yaml``. De configuratie bewaart alleen de SLEUTELNAAM; de waarde
wordt bij het instellen gelezen.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import load_yaml


def lees_geheimen(hass: HomeAssistant, sleutels: list[str]) -> dict[str, str | None]:
    """De waarden van deze sleutels uit secrets.yaml (None als afwezig)."""
    pad = hass.config.path("secrets.yaml")
    try:
        inhoud = load_yaml(pad) or {}
    except Exception:  # noqa: BLE001 - geen bestand, of onleesbaar
        inhoud = {}
    uit = {}
    for s in sleutels:
        w = inhoud.get(s) if isinstance(inhoud, dict) else None
        uit[s] = str(w).strip() if w not in (None, "") else None
    return uit


async def async_lees_geheimen(hass: HomeAssistant, sleutels: list[str]) -> dict[str, str | None]:
    return await hass.async_add_executor_job(lees_geheimen, hass, sleutels)
