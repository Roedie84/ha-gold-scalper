"""Meldingen naar je telefoon.

Twee soorten, met een heel verschillend karakter.

**Het uurbericht** is een samenvatting: wat is er dit uur gebeurd, wat staat er
onder de streep. Rustig, samenvattend, en overslaan als er niets te melden valt
- een melding elk uur die "nul trades" zegt, leer je binnen een dag negeren, en
dan mis je ook de berichten die er wél toe doen.

**De waarschuwing** gaat direct en één keer per gebeurtenis. Noodstop,
onbeschermde positie, dataprobleem. Op iOS wordt die als kritieke melding
verstuurd zodat hij door een stille stand heen komt; bij een noodstop op een
handelsbot is dat gepast.

De dubbeldetectie zit hier en niet in een automatisering: dezelfde toestand
duurt vaak vele cycli, en zonder onderdrukking krijg je elke tien seconden
hetzelfde bericht.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

#: Minimale tijd tussen twee identieke waarschuwingen.
REPEAT_AFTER = timedelta(hours=4)

#: Bestaat de notify-dienst nog niet - bij het opstarten laadt mobile_app vaak
#: later dan deze integratie - dan zoveel seconden wachten en opnieuw kijken.
OPNIEUW_NA_S = 30

#: Zo vaak opnieuw kijken voordat een melding wordt opgegeven: tien minuten.
MAX_POGINGEN = 20

#: Hooguit zoveel meldingen vasthouden tot de dienst er is.
MAX_WACHTEND = 10


@dataclass(slots=True)
class NotifierConfig:
    service: str | None = None          # bv. "mobile_app_iphone_van_ruud"
    hourly: bool = True
    critical: bool = True
    #: Uurbericht overslaan als er geen trades en geen bijzonderheden waren.
    skip_quiet_hours: bool = True


@dataclass(slots=True)
class _Sent:
    """Wat er al verstuurd is, om herhaling te voorkomen."""

    keys: dict[str, datetime] = field(default_factory=dict)
    last_hourly: datetime | None = None
    last_trade_count: int = 0
    last_net: float = 0.0


class Notifier:
    """Verstuurt meldingen via de notify-dienst die je hebt gekozen."""

    def __init__(self, hass: HomeAssistant, config: NotifierConfig) -> None:
        self.hass = hass
        self.config = config
        self._sent = _Sent()
        #: Meldingen die wachten tot de notify-dienst bestaat.
        self._wachtend: list[dict] = []
        self._pogingen = 0
        self._herhaling = None

    @property
    def enabled(self) -> bool:
        return bool(self.config.service)

    # -- over een herstart heen (1.7.5) ------------------------------------- #

    def export(self) -> dict:
        """Wat er al verstuurd is, om te bewaren.

        Zonder dit kwam na elke herstart dezelfde waarschuwing opnieuw binnen
        (de onderdrukking van vier uur was weg), en telde het eerste uurbericht
        alle trades van de run als "dit uur".
        """
        return {
            "keys": {k: v.isoformat() for k, v in self._sent.keys.items()},
            "last_hourly": (
                self._sent.last_hourly.isoformat() if self._sent.last_hourly else None
            ),
            "last_trade_count": self._sent.last_trade_count,
            "last_net": self._sent.last_net,
        }

    def restore(self, data: dict | None) -> bool:
        """Bewaarde verzendtoestand terugzetten. False als er niets bruikbaars was."""
        if not isinstance(data, dict):
            return False

        def _moment(waarde) -> datetime | None:
            try:
                m = datetime.fromisoformat(str(waarde))
            except (TypeError, ValueError):
                return None
            return m if m.tzinfo else m.replace(tzinfo=timezone.utc)

        for sleutel, waarde in (data.get("keys") or {}).items():
            moment = _moment(waarde)
            if moment is not None:
                self._sent.keys[str(sleutel)] = moment
        if data.get("last_hourly"):
            self._sent.last_hourly = _moment(data["last_hourly"])
        try:
            self._sent.last_trade_count = int(data.get("last_trade_count") or 0)
            self._sent.last_net = float(data.get("last_net") or 0.0)
        except (TypeError, ValueError):
            return False
        return True

    @property
    def has_hourly_baseline(self) -> bool:
        """Is er al een vertrekpunt voor het uurbericht gezet?"""
        return self._sent.last_hourly is not None

    def seed(self, trade_count: int, net: float) -> None:
        """Beginstand van het uurbericht uit de run zelf (1.7.5).

        Voor een toestand van een oudere versie zonder bewaarde verzendtoestand:
        anders telde het eerste uurbericht na de herstart alle trades van de
        run als nieuw.
        """
        self._sent.last_trade_count = int(trade_count or 0)
        self._sent.last_net = float(net or 0.0)

    async def _send(
        self, title: str, message: str, *, critical: bool = False,
        tag: str | None = None,
    ) -> None:
        if not self.enabled:
            return

        data: dict = {"title": title, "message": message}
        extra: dict = {}
        if tag:
            # Een tag laat een nieuwe melding de vorige vervangen in plaats van
            # ernaast te komen staan. Anders staat je scherm vol met dezelfde
            # waarschuwing.
            extra["tag"] = tag
        if critical and self.config.critical:
            # Komt door een stille stand heen. Bij een noodstop op een
            # handelsbot is dat gepast; bij een uurbericht niet.
            extra["push"] = {
                "sound": {"name": "default", "critical": 1, "volume": 0.8}
            }
            extra["priority"] = "high"
            extra["ttl"] = 0
        if extra:
            data["data"] = extra

        if not self._dienst_bestaat():
            # Bij het opstarten: mobile_app is er vaak nog niet. Vasthouden en
            # opnieuw proberen, in plaats van de opstartmelding te verliezen.
            self._wachtend = (self._wachtend + [data])[-MAX_WACHTEND:]
            self._plan_herhaling()
            return

        await self._roep_aan(data)

    def _dienst_bestaat(self) -> bool:
        has = getattr(self.hass.services, "has_service", None)
        if has is None:
            return True
        try:
            return bool(has("notify", self.config.service))
        except Exception:  # noqa: BLE001
            return True

    def _plan_herhaling(self) -> None:
        if self._herhaling is not None:
            return
        try:
            from homeassistant.helpers.event import async_call_later
        except ImportError:  # pragma: no cover
            return
        self._herhaling = async_call_later(
            self.hass, OPNIEUW_NA_S, self._probeer_wachtend
        )

    async def _probeer_wachtend(self, _now=None) -> None:
        """Wachtende meldingen versturen zodra de dienst er is."""
        self._herhaling = None
        if not self._wachtend:
            return
        if self._dienst_bestaat():
            wachtend, self._wachtend, self._pogingen = self._wachtend, [], 0
            for data in wachtend:
                await self._roep_aan(data)
            return
        self._pogingen += 1
        if self._pogingen >= MAX_POGINGEN:
            _LOGGER.warning(
                "notify.%s bestaat na %d minuten nog niet; %d melding(en) "
                "niet verstuurd.", self.config.service,
                MAX_POGINGEN * OPNIEUW_NA_S // 60, len(self._wachtend),
            )
            self._wachtend, self._pogingen = [], 0
            return
        self._plan_herhaling()

    async def _roep_aan(self, data: dict) -> None:
        try:
            await self.hass.services.async_call(
                "notify", self.config.service, data, blocking=False
            )
        except Exception as err:  # noqa: BLE001 - een melding mag nooit de lus slopen
            _LOGGER.warning(
                "Melding versturen via notify.%s mislukte: %s",
                self.config.service, err,
            )

    # -- waarschuwingen ------------------------------------------------------ #

    async def alert(
        self, key: str, title: str, message: str, *, critical: bool = True
    ) -> None:
        """Eén melding per gebeurtenis, niet per cyclus.

        Dezelfde toestand duurt vaak vele cycli. Zonder onderdrukking krijg je
        elke tien seconden hetzelfde bericht, en dan zet je meldingen uit.
        """
        now = datetime.now(timezone.utc)
        previous = self._sent.keys.get(key)
        if previous and now - previous < REPEAT_AFTER:
            return
        self._sent.keys[key] = now
        await self._send(title, message, critical=critical, tag=key)

    def clear(self, key: str) -> None:
        """Meld dat een toestand voorbij is, zodat hij opnieuw kan waarschuwen."""
        self._sent.keys.pop(key, None)

    # -- uurbericht ---------------------------------------------------------- #

    def hourly_due(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if not (self.enabled and self.config.hourly):
            return False
        if self._sent.last_hourly is None:
            self._sent.last_hourly = now
            return False
        return (now - self._sent.last_hourly) >= timedelta(hours=1)

    async def send_hourly(self, data: dict, now: datetime | None = None) -> bool:
        """Samenvatting van het afgelopen uur. Geeft False als hij is overgeslagen."""
        now = now or datetime.now(timezone.utc)
        self._sent.last_hourly = now

        stats = data.get("stats") or {}
        trades = stats.get("trades") or 0
        net = stats.get("net_pnl") or 0.0

        new_trades = trades - self._sent.last_trade_count
        delta = net - self._sent.last_net
        self._sent.last_trade_count = trades
        self._sent.last_net = net

        state, detail = data.get("status", ("wachtend", ""))
        quiet = new_trades == 0 and state in ("wachtend", "markt_gesloten")

        if self.config.skip_quiet_hours and quiet:
            # Een uurbericht dat elke keer "nul trades" zegt, leer je negeren.
            # Dan mis je ook de berichten die er wél toe doen.
            _LOGGER.debug("Uurbericht overgeslagen: niets gebeurd")
            return False

        signals = stats.get("signals") or {}
        lines = [
            f"{new_trades} trades dit uur ({trades} totaal)",
            f"Dit uur: {delta:+.2f}   Totaal: {net:+.2f}",
        ]
        if stats.get("total_costs"):
            lines.append(f"Kosten totaal: {stats['total_costs']:.2f}")
        if stats.get("win_rate") is not None and trades:
            lines.append(f"Trefkans: {stats['win_rate']:.0f}%")
        if signals.get("evaluations"):
            lines.append(
                f"Signalen: {signals.get('acted', 0)} van "
                f"{signals['evaluations']} evaluaties"
            )
        lines.append(f"Status: {detail or state}")

        await self._send(
            f"Gold Scalper · {delta:+.2f} dit uur",
            "\n".join(lines),
            critical=False,
            tag="gold_scalper_hourly",
        )
        return True
