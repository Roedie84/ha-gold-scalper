"""De Bitvavo-mand: één entry, handelen op de meest liquide markten (2.18.0).

Gevraagd 20-10: "Ik wil dat de integratie op alle markten analyseert en zelf
handelt, niet op alleen BTC". Gekozen: de meest liquide markten (standaard
twintig), elk uur opnieuw samengesteld, met hooguit vijf open posities over
de hele mand en per koop hooguit de ingestelde inzet.

Opbouw. Elke markt in de mand krijgt een eigen handelslus - dezelfde
``GoldScalperCoordinator`` als bij één markt, met een eigen database, een
eigen run en een eigen grootboek. De gekozen markt van de entry is de
hoofdlus (die heeft de sensoren en schakelaars); de andere markten draaien
als leden zonder eigen entiteiten. Wat ze delen, regelt deze klasse:

* **Hoeveel posities.** Een nieuwe positie mag alleen als de hele mand onder
  het maximum zit (``mag_openen``). Op papier net zo, anders meet de
  bewijsfase iets wat live niet kan.
* **De poort naar live.** Live gaat open op het bewijs van de hele mand: alle
  gesloten papieren trades van alle markten samen, met dezelfde strategie.
  Een markt die net in de mand kwam, hoeft niet zelf weken te bewijzen.
* **De samenstelling.** Elk uur de toppers op volume en spread. Een markt die
  eruit valt maar nog een positie heeft, blijft draaien tot die dicht is en
  opent intussen niets nieuws. Markten met een open positie worden bewaard,
  zodat ze na een herstart terugkomen, ook als ze geen topper meer zijn.

Aan/uit, noodstop en hervatten gelden voor de hele mand: de schakelaar van de
hoofdlus wordt naar alle leden doorgezet.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    BV_MAND_HERZIEN_MINUTEN,
    BV_MAND_MAX_SPREAD_PCT,
    CONF_BV_AANTAL,
    CONF_BV_MARKT,
    CONF_BV_MARKTEN,
    CONF_BV_MAX_POSITIES,
    CONF_BV_MIN_VOLUME,
    CONF_SYMBOL,
    CONF_VENUE,
    BV_MARKTEN_MAND,
    DEFAULT_BV_AANTAL,
    DEFAULT_BV_MAX_POSITIES,
    DEFAULT_BV_MIN_VOLUME,
    DOMAIN,
    VENUE_BITVAVO,
)

_LOGGER = logging.getLogger(__name__)

#: Zoveel leden tegelijk opstarten (warm-up haalt candles op).
_GELIJK_OPSTARTEN = 4


def _tijd(waarde) -> datetime:
    """Een sluitmoment als datetime (tekst of datetime); onbekend = vooraan."""
    if isinstance(waarde, datetime):
        return waarde if waarde.tzinfo else waarde.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(waarde))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def is_mand(options: dict) -> bool:
    return (options.get(CONF_VENUE) == VENUE_BITVAVO
            and options.get(CONF_BV_MARKTEN, BV_MARKTEN_MAND) == BV_MARKTEN_MAND)


def lid_sleutel(entry_id: str, markt: str) -> str:
    """De sleutel van een lid in ``hass.data[DOMAIN]`` en zijn eigen opslag."""
    return f"{entry_id}_{markt.lower()}"


class LidEntry:
    """De config entry zoals een lid hem ziet: dezelfde instellingen, een
    andere markt en een eigen ``entry_id`` (voor de eigen opslag)."""

    def __init__(self, entry, markt: str) -> None:
        self._entry = entry
        self.markt = markt.upper()
        self.entry_id = lid_sleutel(entry.entry_id, self.markt)
        self.hoofd_entry_id = entry.entry_id
        extra = {CONF_BV_MARKT: self.markt, CONF_SYMBOL: self.markt}
        self.data = {**entry.data, **extra}
        self.options = {**entry.options, **extra} if CONF_BV_MARKT in entry.options \
            or CONF_SYMBOL in entry.options else dict(entry.options)
        self.title = f"{self.markt} (Bitvavo-mand)"

    def __getattr__(self, naam: str) -> Any:
        return getattr(self._entry, naam)


class BitvavoMand:
    """Houdt de leden van de mand bij en wat ze delen."""

    def __init__(self, hass: HomeAssistant, entry, hoofd) -> None:
        self.hass = hass
        self.entry = entry
        self.hoofd = hoofd
        opties = {**entry.data, **entry.options}
        self.aantal = max(1, int(opties.get(CONF_BV_AANTAL, DEFAULT_BV_AANTAL)))
        self.max_posities = max(1, int(opties.get(CONF_BV_MAX_POSITIES, DEFAULT_BV_MAX_POSITIES)))
        self.min_volume = float(opties.get(CONF_BV_MIN_VOLUME, DEFAULT_BV_MIN_VOLUME))
        #: markt -> coordinator, zonder de hoofdlus.
        self.leden: dict[str, Any] = {}
        #: Leden die uit de mand vielen maar nog een positie hebben.
        self.uitfaseren: set[str] = set()
        self.selectie: list[dict] = []
        self.laatste_fout: str | None = None
        self.herzien_om: str | None = None
        self._poort: tuple[float, dict] | None = None
        self._slot = asyncio.Lock()
        #: Eén herziening tegelijk (anders start dezelfde markt twee keer).
        self._herzien_slot = asyncio.Lock()
        #: Markten met een positie volgens het bewaarde bestand, nog niet gestart.
        self._bewaard_met_positie: set[str] = set()
        self._stop_timer = None
        self._store = None
        self._gestopt = False
        #: 2.18.3: pas nieuwe posities als alle markten draaien. Bij het
        #: opstarten zetten markten hun posities terug terwijl andere al
        #: instappen; die teruggezette posities telden nog niet mee (live
        #: gezien 20-10 11:30: 8 van hooguit 5 open na een herstart).
        self._gereed = False
        #: Een plek die net is toegezegd: markt -> (tijdstip, open op dat moment).
        #: Twee leden in dezelfde seconde zien anders allebei nog een vrije plek.
        self._toegezegd: dict[str, tuple[float, int]] = {}

    # -- gedeeld ---------------------------------------------------------------- #

    def alle(self) -> list:
        return [self.hoofd, *self.leden.values()]

    @staticmethod
    def _open_bij(c) -> int:
        """Open posities van een lid. Live telt een koop zonder antwoord mee
        (die kan uitgevoerd zijn); bij twijfel liever een plek te veel bezet."""
        try:
            if c.mode.places_orders:
                onbevestigd = sum(1 for v in (getattr(c.venue, "_onbevestigd", {}) or {}).values()
                                  if not str(v).startswith("afgewezen:"))
                return len(getattr(c.venue, "_grootboek", {}) or {}) + onbevestigd
            return len(c.paper.open_positions) if c.paper else 0
        except Exception:  # noqa: BLE001
            return 0

    @staticmethod
    def _gestopt_door_risico(c) -> bool:
        try:
            from .broker.risk import TradingState

            return c.risk.state.state is TradingState.HALTED
        except Exception:  # noqa: BLE001
            return False

    def waarde_elders(self, venue) -> float:
        """Wat de andere markten van de mand kochten, tegen hun laatste bieding
        (voor het vermogen van de hele mand)."""
        totaal = 0.0
        for c in self.alle():
            if getattr(c, "venue", None) is venue:
                continue
            units = sum(float(r.get("units") or 0) for r in
                        (getattr(c.venue, "_grootboek", {}) or {}).values())
            bid = getattr(getattr(c, "_last_quote", None), "bid", None)
            if units and bid:
                totaal += units * float(bid)
        return totaal

    #: Zo lang telt een toegezegde plek mee als de positie (nog) niet zichtbaar is.
    TOEZEGGING_S = 30.0

    def aantal_open(self) -> int:
        nu = time.monotonic()
        totaal = 0
        for c in self.alle():
            open_c = self._open_bij(c)
            belofte = self._toegezegd.get(getattr(c, "symbol", ""))
            if belofte and nu - belofte[0] < self.TOEZEGGING_S and open_c <= belofte[1]:
                open_c += 1
            totaal += open_c
        return totaal

    def mag_openen(self, c) -> tuple[bool, str | None]:
        """Mag dit lid een nieuwe positie openen? Zo ja, dan is de plek
        toegezegd tot de positie zichtbaar is (of na 30 s vervalt)."""
        markt = getattr(c, "symbol", "")
        if self._gestopt:
            return False, "mand: wordt gestopt"
        if not self._gereed:
            return False, "mand: start nog op (eerst alle markten met hun posities)"
        if markt in self.uitfaseren or markt not in {x.symbol for x in self.alle()}:
            return False, "mand: markt valt uit de mand, alleen nog sluiten"
        gestopt = [x.symbol for x in self.alle() if self._gestopt_door_risico(x)]
        if gestopt:
            # Eén noodstop geldt voor de hele mand.
            return False, f"mand: noodstop bij {', '.join(gestopt)}"
        self._toegezegd.pop(markt, None)
        open_nu = self.aantal_open()
        if open_nu >= self.max_posities:
            return False, f"mand: al {open_nu} van hooguit {self.max_posities} posities open"
        self._toegezegd[markt] = (time.monotonic(), self._open_bij(c))
        return True, None

    def vrijgeven(self, c) -> None:
        """2.18.2: de lus opende toch niets (kostenfilter, risico, grootte):
        de toegezegde plek komt meteen vrij. Anders hield een markt die elke
        cyclus een signaal had maar nooit opende, steeds een plek bezet."""
        self._toegezegd.pop(getattr(c, "symbol", ""), None)

    async def poort(self) -> dict:
        """De poort naar live op het bewijs van de hele mand (hooguit eens per
        twee minuten berekend; alle leden lezen hetzelfde)."""
        nu = time.monotonic()
        if self._poort and nu - self._poort[0] < 120:
            return self._poort[1]
        async with self._slot:
            if self._poort and time.monotonic() - self._poort[0] < 120:
                return self._poort[1]
            uit = await self._bereken_poort()
            self._poort = (time.monotonic(), uit)
            return uit

    async def _bereken_poort(self) -> dict:
        from .modes import LiveGate
        from .storage import performance

        h = self.hoofd
        bewijs = await self.hass.async_add_executor_job(h._laatste_papieren_run)
        if bewijs is None:
            return {
                "unlocked": False, "checks": {},
                "blocking_reasons": ["Nog geen papieren run van de mand: eerst op papier de "
                                     "bewijsfase doorlopen (modus paper)."],
                "summary": "Live gesloten: geen papieren bewijsfase.",
            }
        trades: list = []
        for c in self.alle():
            try:
                run = await self.hass.async_add_executor_job(c._laatste_papieren_run)
                if run is not None:
                    trades.extend(await self.hass.async_add_executor_job(c.db.closed_trades, run))
            except Exception:  # noqa: BLE001 - één onleesbaar lid breekt de poort niet
                _LOGGER.debug("Mand: trades van %s niet te lezen", getattr(c, "symbol", "?"),
                              exc_info=True)
        trades.sort(key=lambda t: _tijd(getattr(t, "close_time", None)))
        stats = await self.hass.async_add_executor_job(
            performance.compute_for_run, h.db, bewijs, trades)
        run = await self.hass.async_add_executor_job(h.db.get_run, bewijs)
        daily = performance.daily_breakdown(trades)
        gate = LiveGate().evaluate(stats, run or {}, daily, h.robustness,
                                   h._boekhouding_status()).as_dict()
        # De afstemming van élke markt telt: een afwijking bij één lid houdt de
        # hele mand dicht.
        mis = []
        for c in self.alle():
            try:
                st = c._boekhouding_status()
            except Exception:  # noqa: BLE001
                st = None
            if c is not h and st and ((st.get("afwijkingen") or 0) or (st.get("kritiek_open") or 0)):
                mis.append(c.symbol)
        if mis:
            gate["unlocked"] = False
            gate.setdefault("blocking_reasons", []).append(
                "Afstemming niet sluitend bij: " + ", ".join(mis))
        gate["mand"] = {"markten": len(self.alle()), "trades": len(trades)}
        return gate

    # -- samenstelling ----------------------------------------------------------- #

    async def _bewaarde_markten(self) -> list[str]:
        from homeassistant.helpers.storage import Store

        self._store = Store(self.hass, 1, f"{DOMAIN}_mand_{self.entry.entry_id}")
        try:
            data = await self._store.async_load() or {}
        except Exception:  # noqa: BLE001
            data = {}
        return [str(m).upper() for m in data.get("met_positie") or []]

    async def _bewaar(self) -> None:
        if self._store is None:
            return
        # Ook wat het bestand al als 'met positie' kende maar (nog) niet draait:
        # nooit een markt met een positie vergeten.
        met_positie = sorted({m for m, c in self.leden.items() if self._open_bij(c)}
                             | (self._bewaard_met_positie - set(self.leden)))
        try:
            await self._store.async_save({
                "met_positie": met_positie,
                "selectie": [r["market"] for r in self.selectie],
            })
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Mand niet bewaard", exc_info=True)

    async def async_start(self) -> None:
        """Bij het opstarten: eerst de markten met een open positie, dan de toppers."""
        bewaard = await self._bewaarde_markten()
        self._bewaard_met_positie = set(bewaard)
        try:
            await self._herzien(extra=bewaard)
        finally:
            self._gereed = True
        self._stop_timer = async_track_time_interval(
            self.hass, self._tik, timedelta(minutes=BV_MAND_HERZIEN_MINUTEN))

    @callback
    def _tik(self, _nu) -> None:
        maak = getattr(self.entry, "async_create_background_task", None)
        taak = self._herzien()
        if maak is not None:
            maak(self.hass, taak, "gold_scalper mand herzien")
        else:
            self.hass.async_create_task(taak)

    async def _herzien(self, extra: list[str] | None = None) -> None:
        async with self._herzien_slot:
            if self._gestopt:
                return
            await self._herzien_kern(extra)
            if not self._gestopt:
                await self._bewaar()

    async def _herzien_kern(self, extra: list[str] | None = None) -> None:
        from .broker import bitvavo as bv

        try:
            self.selectie = await bv.mand_toppers(
                self.hoofd.venue, self.aantal, self.min_volume, BV_MAND_MAX_SPREAD_PCT,
                verplicht=[self.hoofd.symbol])
            self.laatste_fout = None
        except Exception as err:  # noqa: BLE001 - de lopende leden draaien gewoon door
            self.laatste_fout = str(err)
            _LOGGER.warning("Bitvavo-mand niet samen te stellen: %s", err)
            if not self.selectie and not extra:
                return
        self.herzien_om = datetime.now(timezone.utc).isoformat()
        gewenst = [r["market"] for r in self.selectie if r["market"] != self.hoofd.symbol]
        for markt in extra or []:
            if markt not in gewenst and markt != self.hoofd.symbol:
                gewenst.append(markt)
        # Nieuwe leden, een paar tegelijk.
        nieuw = [m for m in gewenst if m not in self.leden]
        for i in range(0, len(nieuw), _GELIJK_OPSTARTEN):
            if self._gestopt:
                return
            await asyncio.gather(*(self._start_lid(m) for m in nieuw[i:i + _GELIJK_OPSTARTEN]))
        # Wie terug is in de selectie, mag weer openen.
        topper = {r["market"] for r in self.selectie}
        self.uitfaseren -= topper
        # Wie geen topper is: eerst uitfaseren (opent niets meer), dan stoppen
        # zodra er niets open staat. Ook een markt die alleen terugkwam omdat
        # hij een positie had.
        for markt in [m for m in self.leden if m not in topper]:
            self.uitfaseren.add(markt)
        for markt in list(self.uitfaseren):
            if self._gestopt:
                return
            c = self.leden.get(markt)
            if c is None:
                self.uitfaseren.discard(markt)
                continue
            await self._stop_als_plat(markt, c)
        _LOGGER.info("Bitvavo-mand: %s markten (%s), %s posities open",
                     len(self.alle()), ", ".join([self.hoofd.symbol, *self.leden]),
                     self.aantal_open())

    async def _stop_als_plat(self, markt: str, c) -> None:
        """Stoppen als er niets open staat - gecontroleerd binnen het slot van
        de lus, zodat er niet net een positie opengaat."""
        slot = getattr(c, "_cyclus_slot", None)
        if slot is None:
            if not self._open_bij(c):
                self.uitfaseren.discard(markt)
                await self._stop_lid(markt)
            return
        async with slot:
            if self._open_bij(c):
                return
            self.leden.pop(markt, None)
            self.uitfaseren.discard(markt)
        await self._stop_lid(markt, al_weg=c)

    async def _start_lid(self, markt: str) -> None:
        from .coordinator import GoldScalperCoordinator

        lid_entry = LidEntry(self.entry, markt)
        c = GoldScalperCoordinator(self.hass, lid_entry)
        c._mand = self
        geregistreerd = False
        try:
            await c.async_setup()
            if getattr(c, "venue", None) is not None:
                c.venue.mand_waarde = self.waarde_elders
            # Aan/uit volgt de hoofdlus, al vóór de eerste cyclus.
            c._enabled = bool(self.hoofd.enabled)
            # Geen uurbericht per markt; de hoofdlus meldt.
            try:
                import dataclasses

                c.notifier.config = dataclasses.replace(c.notifier.config, hourly=False)
            except Exception:  # noqa: BLE001
                pass
            if self._gestopt:
                raise asyncio.CancelledError
            # Meetellen vóór de eerste cyclus: die kan al een positie openen.
            self.leden[markt] = c
            self.hass.data.setdefault(DOMAIN, {})[lid_entry.entry_id] = c
            geregistreerd = True
            await c.async_refresh()
        except asyncio.CancelledError:
            await self._ruim_op(markt, lid_entry.entry_id, c)
            if not self._gestopt:
                raise
            return
        except Exception as err:  # noqa: BLE001 - één markt mag de mand niet breken
            _LOGGER.warning("Bitvavo-mand: %s niet gestart: %s", markt, err)
            await self._ruim_op(markt, lid_entry.entry_id, c)
            return
        if not geregistreerd or self._gestopt:
            return
        # Zonder luisteraar ververst een DataUpdateCoordinator niet vanzelf;
        # een lid heeft geen entiteiten.
        c._mand_luisteraar = c.async_add_listener(lambda: None)
        try:
            maak = getattr(self.entry, "async_create_background_task", None)
            taak = c.async_afstemming_na_herstart()
            if maak is not None:
                maak(self.hass, taak, f"gold_scalper afstemming {markt}")
            else:
                self.hass.async_create_task(taak)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Afstemming van %s niet gepland", markt, exc_info=True)

    async def _ruim_op(self, markt: str, sleutel: str, c) -> None:
        """Een lid dat niet (helemaal) startte: niets laten openstaan."""
        if self.leden.get(markt) is c:
            self.leden.pop(markt, None)
        if self.hass.data.get(DOMAIN, {}).get(sleutel) is c:
            self.hass.data[DOMAIN].pop(sleutel, None)
        try:
            await asyncio.shield(c.async_shutdown_hook(mandlid=True))
        except BaseException:  # noqa: BLE001
            db = getattr(c, "db", None)
            if db is not None:
                try:
                    db.close()
                except Exception:  # noqa: BLE001
                    pass

    async def _stop_lid(self, markt: str, al_weg=None) -> None:
        c = al_weg or self.leden.pop(markt, None)
        self.uitfaseren.discard(markt)
        if c is None:
            return
        self.hass.data.get(DOMAIN, {}).pop(c.entry.entry_id, None)
        try:
            from .broker_stream import async_stop_stream

            await async_stop_stream(self.hass, c.entry.entry_id)
        except Exception:  # noqa: BLE001
            pass
        stop = getattr(c, "_mand_luisteraar", None)
        if stop:
            stop()
        try:
            await c.async_shutdown()
        except Exception:  # noqa: BLE001
            pass
        # 2.21.3 (L-GS-023): loopt de mand door (async_stop zet _gestopt
        # eerst), dan is dit geen HA-stop.
        await c.async_shutdown_hook(mandlid=not self._gestopt)

    async def async_stop(self) -> None:
        if self._gestopt:
            return
        # Eerst bewaren (met de echte leden), dan pas stoppen.
        await self._bewaar()
        self._gestopt = True
        if self._stop_timer:
            self._stop_timer()
            self._stop_timer = None
        for markt in list(self.leden):
            await self._stop_lid(markt)

    async def zet_aan(self, waarde: bool) -> None:
        """De schakelaar van de hoofdlus geldt voor de hele mand."""
        for c in list(self.leden.values()):
            if c.enabled != waarde:
                await c.async_set_enabled(waarde)

    def overzicht(self) -> dict:
        """Voor de sensor en het dashboard."""
        rijen = []
        info = {r["market"]: r for r in self.selectie}
        for c in self.alle():
            markt = c.symbol
            data = getattr(c, "data", None) or {}
            rijen.append({
                "markt": markt,
                "open": self._open_bij(c),
                "volume_24u": (info.get(markt) or {}).get("volume"),
                "spread_pct": (info.get(markt) or {}).get("spread_pct"),
                "uitfaseren": markt in self.uitfaseren,
                "koers": data.get("price"),
                "netto": (data.get("stats") or {}).get("net_pnl"),
                "trades": (data.get("stats") or {}).get("trades"),
                "weigering": getattr(c, "_laatste_weigering", None),
                # 2.21.3 (L-GS-022): staat dit lid zelf in een noodstop?
                "noodstop": bool(self._gestopt_door_risico(c)),
                # 2.21.0: equity en een actieve saldosprong per markt. De leden
                # hebben geen eigen sensoren; zonder dit was een sprong bij
                # een lid nergens te zien (22-10 23:47).
                "equity": data.get("equity"),
                "saldosprong": (data.get("saldosprong") or {}).get("reden")
                if (data.get("saldosprong") or {}).get("actief") else None,
            })
        return {
            "markten": len(rijen), "open_posities": self.aantal_open(),
            "max_posities": self.max_posities, "doel_aantal": self.aantal,
            "min_volume": self.min_volume, "herzien_om": self.herzien_om,
            "fout": self.laatste_fout, "per_markt": rijen,
            "saldosprong": [r["markt"] for r in rijen if r.get("saldosprong")],
        }

    def saldosprongen(self) -> list[str]:
        """2.21.0: redenen van een actieve saldosprong bij de leden."""
        uit = []
        for c in self.leden.values():
            sprong = getattr(c, "saldosprong", None)
            if sprong is not None and getattr(sprong, "actief", False):
                uit.append(sprong.reden or c.symbol)
        return uit
