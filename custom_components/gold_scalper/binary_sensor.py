"""Binaire sensoren: de dingen waar je een automatisering op hangt."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass, BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .lifecycle import veilig_herstarten
from .const import DOMAIN
from .coordinator import GoldScalperCoordinator
from .entity import GoldScalperEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: GoldScalperCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SafeToRestart(coordinator, entry),
        LiveUnlocked(coordinator, entry),
        RiskHalted(coordinator, entry),
        MarketTradeable(coordinator, entry),
        DataIntegrity(coordinator, entry),
        ModeOverridden(coordinator, entry),
    ])


class SafeToRestart(GoldScalperEntity, BinarySensorEntity):
    """Aan als Home Assistant herstart kan worden zonder open posities."""

    _attr_name = "Veilig herstarten"
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_safe_to_restart"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not data:
            return None
        return veilig_herstarten(data.get("open_positions"), self.coordinator.lifecycle)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "open_positions": len(data.get("open_positions") or []),
            "lifecycle_state": (data.get("lifecycle") or {}).get("state"),
            "hint": (
                "Roep gold_scalper.prepare_shutdown aan vóór een update, en wacht "
                "tot deze sensor aan staat."
            ),
        }


class LiveUnlocked(GoldScalperEntity, BinarySensorEntity):
    """Aan als de bewijsfase geslaagd is en live handel vrijgegeven mag worden."""

    _attr_name = "Live vrijgegeven"
    _attr_icon = "mdi:lock-open-check"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_live_unlocked"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if not data else bool((data.get("gate") or {}).get("unlocked"))

    @property
    def extra_state_attributes(self) -> dict:
        gate = (self.coordinator.data or {}).get("gate") or {}
        return {
            "checks": gate.get("checks", {}),
            "blocking_reasons": gate.get("blocking_reasons", []),
            "summary": gate.get("summary"),
        }


def _mand_gestopt(c) -> list[tuple[str, str | None]]:
    """2.19.4: de noodstop van een mandlid is zichtbaar op de noodstop van de
    mand (hoofdlus). 2.22.0: hij stopt alleen die markt; de rest van de mand
    handelt door (attribuut ``markten`` noemt wie stilstaat). Geeft
    ``(markt, reden)`` van de gestopte leden; leeg buiten een mand en voor
    de leden zelf."""
    mand = getattr(c, "_mand", None)
    if mand is None or getattr(mand, "hoofd", None) is not c:
        return []
    # 2.23.1 (L-GS-027): tijdens het opstarten van de mand niet. Een lid dat
    # met een oude noodstop opstart en bij de eerste herziening de mand weer
    # verlaat, liet de noodstop 10 s aan- en uitflappen. De eigen noodstop
    # van de hoofdlus telt wel meteen; nieuwe posities wachten sowieso tot
    # de mand gereed is.
    if not getattr(mand, "boek_gereed", True):
        return []
    gestopt = []
    for lid in list(getattr(mand, "leden", {}).values()):
        try:
            toestand = lid.risk.as_dict()
        except Exception:  # noqa: BLE001 - een lid zonder risico telt niet
            continue
        if toestand.get("state") == "halted":
            gestopt.append((getattr(lid, "symbol", "?"), toestand.get("halt_reason")))
    return gestopt


class RiskHalted(GoldScalperEntity, BinarySensorEntity):
    """Aan bij een noodstop. Vereist handmatig hervatten."""

    _attr_name = "Noodstop"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:hand-back-left"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_halted"

    @property
    def available(self) -> bool:
        # 1.7.0: de noodstop blijft zichtbaar, ook als de koersopvraging
        # faalt. Hij leest de risicobewaking rechtstreeks, niet de cyclus.
        return True

    def _risk(self) -> dict:
        try:
            return self.coordinator.risk.as_dict()
        except Exception:  # noqa: BLE001 - dan de laatste cyclus
            return (self.coordinator.data or {}).get("risk") or {}

    @property
    def is_on(self) -> bool | None:
        risk = self._risk()
        if _mand_gestopt(self.coordinator):
            return True
        if not risk:
            return None
        return risk.get("state") == "halted"

    @property
    def extra_state_attributes(self) -> dict:
        risk = self._risk()
        attrs = {
            "reason": risk.get("halt_reason"),
            "recent_triggers": risk.get("recent_triggers", []),
            "hint": "Roep gold_scalper.resume aan nadat je de oorzaak hebt vastgesteld.",
        }
        gestopt = _mand_gestopt(self.coordinator)
        if gestopt:
            attrs["markten"] = [m for m, _ in gestopt]
            # 2.22.0: noodstop per markt, niet voor de hele mand.
            attrs["geldt_voor"] = "alleen deze markten; de rest van de mand handelt door"
            attrs["hint"] = ("Hervat één markt met gold_scalper.resume en 'markt', "
                             "of alles zonder 'markt'.")
            if not attrs["reason"]:
                attrs["reason"] = "; ".join(f"{m}: {r}" for m, r in gestopt)
        return attrs


class MarketTradeable(GoldScalperEntity, BinarySensorEntity):
    """Aan als de markt open is en de spread binnen de limiet valt."""

    _attr_name = "Markt verhandelbaar"
    _attr_icon = "mdi:store-clock"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_tradeable"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not data or not data.get("quote"):
            return None
        quote = data["quote"]
        if not quote.tradeable:
            return False
        # Dezelfde toets als de strategie, anders toont deze sensor groen
        # terwijl er geweigerd wordt - of omgekeerd.
        atr = data.get("atr")
        if atr and atr > 0:
            ratio = quote.spread / atr
            return ratio <= self.coordinator.strategy_cfg.max_spread_atr_ratio
        return quote.spread <= self.coordinator.strategy_cfg.max_spread

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        quote = data.get("quote")
        atr = data.get("atr")
        spread = getattr(quote, "spread", None)
        return {
            "spread": spread,
            "atr": atr,
            "spread_atr_ratio": (
                round(spread / atr, 3) if (spread and atr and atr > 0) else None
            ),
            "max_ratio": self.coordinator.strategy_cfg.max_spread_atr_ratio,
            "max_spread_absolute": self.coordinator.strategy_cfg.max_spread,
            "market_open": getattr(quote, "tradeable", None),
        }


def _mand_sprongen(coordinator) -> list[str]:
    """2.21.0: actieve saldosprongen bij de leden van de Bitvavo-mand."""
    mand = getattr(coordinator, "_mand", None)
    if mand is None or not hasattr(mand, "saldosprongen"):
        return []
    try:
        return list(mand.saldosprongen())
    except Exception:  # noqa: BLE001 - alleen weergave
        return []


class DataIntegrity(GoldScalperEntity, BinarySensorEntity):
    """Aan als de OHLCV-kolommen uit de pas lopen.

    Bestaat omdat dit precies zo'n storing is die niets zichtbaars doet: de
    integratie blijft draaien, de sensoren blijven waarden tonen, maar de
    indicatoren rekenen op verschoven data. Zonder deze melding zie je het pas
    als je een diagnostiekexport naast elkaar legt.
    """

    _attr_name = "Dataprobleem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-decagram"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_data_integrity"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not data:
            return None
        # 1.7.0: een vastgehouden (verouderde) koers is een dataprobleem.
        if data.get("koers_verouderd"):
            return True
        if not data.get("candles_consistent", True):
            return True
        # 1.7.7: een saldosprong zonder trade is een dataprobleem.
        if (data.get("saldosprong") or {}).get("actief"):
            return True
        # 2.21.0: ook bij een lid van de Bitvavo-mand (geen eigen sensoren).
        if _mand_sprongen(self.coordinator):
            return True
        # Te weinig historie is óók een dataprobleem: de indicatoren geven dan
        # waarden terug die nergens op steunen.
        return (data.get("candles") or 0) < 60

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "candles": data.get("candles"),
            "indicator_bars": self.coordinator.state.bars,
            "columns_consistent": data.get("candles_consistent"),
            "koers_verouderd": bool(data.get("koers_verouderd")),
            "koers_leeftijd_seconden": data.get("koers_leeftijd_seconden"),
            "koers_mislukt_op_rij": data.get("koers_mislukt_op_rij", 0),
            "koers_fout": data.get("koers_fout"),
            "saldosprong": bool((data.get("saldosprong") or {}).get("actief")),
            "saldosprong_reden": (data.get("saldosprong") or {}).get("reden"),
            "saldo_referentie": (data.get("saldosprong") or {}).get("referentie"),
            "saldosprong_mand": _mand_sprongen(self.coordinator),
            "hint": (
                "Bij een probleem wordt de historie automatisch opnieuw opgehaald "
                "bij de volgende cyclus."
            ),
        }


class ModeOverridden(GoldScalperEntity, BinarySensorEntity):
    """Aan als de gekozen modus is genegeerd.

    Bestaat omdat een stilzwijgende overschrijving gevaarlijk is: wie 'live'
    kiest en niets hoort, gaat ervan uit dat het live staat.
    """

    _attr_name = "Modus genegeerd"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_mode_overridden"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not data:
            return None
        return data.get("mode") != data.get("requested_mode")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "requested": data.get("requested_mode"),
            "actual": data.get("mode"),
            "reason": data.get("mode_override_reason"),
        }
