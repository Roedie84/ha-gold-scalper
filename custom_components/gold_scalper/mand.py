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

Aan/uit en hervatten gelden voor de hele mand: de schakelaar van de hoofdlus
wordt naar alle leden doorgezet. Een noodstop geldt sinds 2.22.0 per markt:
gaat één lid over zijn dagverlieslimiet, dan stopt alleen dat lid; de rest
van de mand blijft meten. Hervatten kan per markt (``gold_scalper.resume``
met ``markt``) of voor alles.

Spreadgrens (2.22.0): een markt komt alleen in de mand bij een spread van
hooguit ``BV_MAND_MAX_SPREAD_PCT`` (0,03 %), en een lid opent niets zolang zijn
actuele spread daarboven ligt.

2.24.0 (L-GS-025): de toelating toetst de mediane spread over 24 uur (elk
kwartier een waarneming, bewaard in het bestand van de mand), niet één
momentopname; PUMP-EUR en PEPE-EUR wisselden zo elk uur in en uit. Te weinig
waarnemingen: de momentopname, zoals voorheen. Het openen blijft op de
actuele spread: dat is wat een instap nu kost.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    BV_MAND_HERZIEN_MINUTEN,
    BV_MAND_SPREAD_MONSTER_MINUTEN,
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

from .spreadhistorie import SpreadHistorie

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


#: 2.23.1 (L-GS-028): begrenzing van de attributen van de sensor *Mand*
#: (de recorder bewaart attributen tot 16 kB).
_TOP_WEIGERINGEN_LID = 3
_MAX_BUITEN_MAND = 15


def _rond(waarde, cijfers: int):
    """Afronden voor de attributen; geen getal = ongewijzigd."""
    if isinstance(waarde, bool) or not isinstance(waarde, (int, float)):
        return waarde
    if cijfers == 0:
        return int(round(waarde))
    if cijfers >= 6 and waarde != 0:
        return float(f"{waarde:.{cijfers}g}")
    return round(float(waarde), cijfers)


def _buiten_mand(per_markt: list) -> dict:
    """2.23.1 (L-GS-028): het deel ``buiten_mand`` van het mandoverzicht."""
    buiten = [r for r in per_markt if r.get("bron") == "database"]
    met = sorted((r for r in buiten if r.get("trades")),
                 key=lambda r: (-(r.get("trades") or 0), r["markt"]))
    rest = met[_MAX_BUITEN_MAND:]
    uit = {
        "buiten_mand": [
            {"markt": r["markt"], "trades": r.get("trades"),
             "netto": _rond(r.get("netto"), 2), "laatste_trade": r.get("laatste_trade")}
            for r in met[:_MAX_BUITEN_MAND]],
        "buiten_mand_zonder_trades": len(buiten) - len(met),
    }
    if rest:
        uit["buiten_mand_overig"] = {
            "markten": len(rest),
            "trades": sum(int(r.get("trades") or 0) for r in rest),
            "netto": round(sum(float(r.get("netto") or 0.0) for r in rest), 2),
        }
    return uit


def _top(teller, n: int) -> dict:
    """2.23.0: de ``n`` grootste tellingen, aflopend."""
    if not isinstance(teller, dict):
        return {}
    return dict(sorted(teller.items(), key=lambda kv: (-kv[1], kv[0]))[:n])


def db_bestand(markt: str) -> str:
    """2.22.2: het databasebestand van een Bitvavo-markt (zelfde regel als de
    coordinator sinds 2.17.0)."""
    return f"gold_scalper_bitvavo_{str(markt).lower().replace('-', '_')}.db"


def markt_uit_bestand(naam: str) -> str | None:
    """Omgekeerd: ``gold_scalper_bitvavo_pepe_eur.db`` -> ``PEPE-EUR``."""
    voor, na = "gold_scalper_bitvavo_", ".db"
    naam = os.path.basename(str(naam))
    if not (naam.startswith(voor) and naam.endswith(na)):
        return None
    kern = naam[len(voor):-len(na)]
    return kern.upper().replace("_", "-") if kern else None


def ontdek_markten(map_pad: str) -> list[str]:
    """2.22.2: alle markten waarvan een database bestaat. De bestanden blijven
    staan als een markt de mand verlaat; zo vindt de mand ook trades terug van
    markten die al weg waren (PEPE-EUR, PUMP-EUR, BILL-EUR, ...)."""
    uit = []
    for pad in sorted(glob.glob(os.path.join(map_pad, "gold_scalper_bitvavo_*.db"))):
        markt = markt_uit_bestand(pad)
        if markt:
            uit.append(markt)
    return uit


def _samenvatting(markt: str, trades: list, run: dict | None, runs: int,
                  bron: str) -> dict:
    netto = [float(t.net_pnl or 0.0) for t in trades]
    start = float((run or {}).get("starting_balance") or 0.0) or None
    laatste = max((str(t.close_time) for t in trades if t.close_time), default=None)
    return {
        "markt": markt,
        "trades": len(trades),
        "wins": sum(1 for x in netto if x > 0),
        "losses": sum(1 for x in netto if x <= 0),
        "netto": round(sum(netto), 2),
        "kosten": round(sum(float(t.total_cost or 0.0) for t in trades), 2),
        "startbalans": start,
        "run_id": (run or {}).get("id"),
        "runs": runs,
        "laatste_trade": laatste,
        "bron": bron,
    }


def lees_markt(pad: str, markt: str, strategie_versie: str) -> tuple[dict, list] | None:
    """2.22.2: gesloten trades van de laatste papieren run van één markt, direct
    uit zijn database (voor markten die nu niet draaien). Synchroon: in een
    executor aanroepen. None als er geen bestand of geen passende run is."""
    from .modes import TradingMode
    from .storage.database import TradeDatabase

    if not os.path.exists(pad):
        return None
    db = TradeDatabase(pad)
    try:
        db.connect()
        passend = [
            r for r in db.list_runs(limit=50)
            if str(r.get("mode")) == TradingMode.PAPER.value
            and str(r.get("strategy_version")) == str(strategie_versie)
            and str(r.get("symbol") or "").upper() == markt.upper()
        ]
        if not passend:
            return None
        run = passend[0]
        trades = db.closed_trades(int(run["id"]))
        samenvatting = _samenvatting(markt, trades, run, len(passend), "database")
        # Ter informatie: trades in eerdere papieren runs (een andere opzet;
        # die horen niet bij dit bewijs en tellen niet mee).
        samenvatting["eerdere_runs_trades"] = sum(
            len(db.closed_trades(int(r["id"]))) for r in passend[1:])
        return samenvatting, trades
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass


# -- sensorwaarden (2.22.2; los van Home Assistant, zodat ze testbaar zijn) ---- #

def sensor_stats(d: dict) -> dict:
    """De statistiek achter trades/netto/oordeel: bij de hoofdlus van de mand
    die van de hele mand, anders die van de eigen markt.

    2.23.1 (L-GS-027): zolang de mand nog opstart (leden en archief nog niet
    geladen) geen waarde - niet de eigen markt (0) en geen deelsom."""
    if d.get("mand_wacht"):
        return {}
    return d.get("mand_stats") or d.get("stats") or {}


def sensor_equity(d: dict):
    if d.get("mand_wacht"):
        return None
    boek = d.get("mand_boek") or {}
    if boek.get("equity") is not None:
        return boek["equity"]
    return d.get("equity")


def sensor_equity_attrs(d: dict) -> dict:
    boek = d.get("mand_boek") or {}
    if not boek:
        return {"balance": d.get("balance")}
    return {
        "balance": boek.get("balans", d.get("balance")),
        "startbalans": boek.get("startbalans"),
        "equity_eigen_markt": d.get("equity"),
        "balance_eigen_markt": d.get("balance"),
    }


def sensor_trades_extra(d: dict) -> dict:
    if d.get("mand_wacht"):
        return {"mand_start": True}
    boek = d.get("mand_boek") or {}
    if not boek:
        return {}
    return {"per_markt": boek.get("per_markt"),
            "eigen_markt": (d.get("stats") or {}).get("trades")}


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
        #: 2.22.0: markten met genoeg volume maar een te brede spread.
        self.geweerd_spread: list[dict] = []
        #: Een plek die net is toegezegd: markt -> (tijdstip, open op dat moment).
        #: Twee leden in dezelfde seconde zien anders allebei nog een vrije plek.
        self._toegezegd: dict[str, tuple[float, int]] = {}
        #: 2.22.2: het grootboek van de hele mand. Markten die nu niet draaien
        #: (uit de mand gevallen, geweerd op spread) houden hier hun gesloten
        #: trades: markt -> (samenvatting, trades). Bron: hun eigen database.
        self._archief: dict[str, tuple[dict, list]] = {}
        #: Markten die ooit in de mand zaten (bewaard; plus de bestanden).
        self.ooit: set[str] = set()
        #: Statistiek over alle gesloten trades van de mand (hooguit eens per
        #: twee minuten berekend): (moment, stats, aantal trades).
        self._mand_stats: tuple[float, dict, tuple] | None = None
        #: 2.23.1 (L-GS-027): het archief is minstens één keer ingelezen.
        self._archief_geladen = False
        #: 2.24.0 (L-GS-025): spreadwaarnemingen per markt (24 uur, bewaard).
        self.spread_historie = SpreadHistorie()
        self._monster_timer = None

    @property
    def boek_gereed(self) -> bool:
        """2.23.1 (L-GS-027): alle leden gestart en het archief ingelezen. Pas
        dan kloppen trades, netto en equity van de hele mand; daarvoor tonen
        de mandsensoren geen waarde (eerder: 0, dan een deelsom)."""
        return bool(self._gereed and self._archief_geladen)

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
        if self._gestopt_door_risico(c):
            # 2.22.0: een noodstop geldt per markt. Alleen dit lid staat stil;
            # de andere leden blijven meten (was: de hele mand, sinds 23-10
            # 16:31 door PEPE-EUR).
            return False, f"noodstop bij {markt} (alleen deze markt)"
        spread = self._spread_pct(c)
        if spread is not None and spread > BV_MAND_MAX_SPREAD_PCT:
            # 2.22.0: kosteneis - boven de grens geen nieuwe positie.
            return False, (f"mand: spread {spread:.4f} % boven de grens van "
                           f"{BV_MAND_MAX_SPREAD_PCT} %")
        self._toegezegd.pop(markt, None)
        open_nu = self.aantal_open()
        if open_nu >= self.max_posities:
            return False, f"mand: al {open_nu} van hooguit {self.max_posities} posities open"
        self._toegezegd[markt] = (time.monotonic(), self._open_bij(c))
        return True, None

    @staticmethod
    def _spread_pct(c) -> float | None:
        """2.22.0: actuele spread van een lid in procent van de middenkoers."""
        q = getattr(c, "_last_quote", None)
        try:
            bid, ask = float(q.bid), float(q.ask)
        except (TypeError, ValueError, AttributeError):
            return None
        if bid <= 0 or ask < bid:
            return None
        return (ask - bid) / ((ask + bid) / 2) * 100

    def gestopte_markten(self) -> list[str]:
        """2.22.0: markten in noodstop (alleen die markten staan stil)."""
        return [x.symbol for x in self.alle() if self._gestopt_door_risico(x)]

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
        # 2.22.2: ook de markten die de mand al verlieten (hun trades horen
        # bij hetzelfde bewijs).
        trades = await self.alle_gesloten_trades()
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
        self.ooit |= {str(m).upper() for m in data.get("ooit") or []}
        # 2.24.0 (L-GS-025): de spreadhistorie overleeft een herstart.
        try:
            self.spread_historie.herstel(data.get("spread_historie"), time.time())
        except Exception:  # noqa: BLE001 - dan begint de historie leeg
            _LOGGER.debug("Spreadhistorie van de mand onleesbaar", exc_info=True)
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
                # 2.22.2: elke markt die ooit meedeed (voor het grootboek).
                "ooit": sorted(self.ooit | {c.symbol for c in self.alle()}),
                # 2.24.0 (L-GS-025): spreadwaarnemingen van de laatste 24 uur.
                "spread_historie": self.spread_historie.export(),
            })
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Mand niet bewaard", exc_info=True)

    async def async_start(self) -> None:
        """Bij het opstarten: eerst de markten met een open positie, dan de toppers."""
        bewaard = await self._bewaarde_markten()
        self._bewaard_met_positie = set(bewaard)
        self._koppel_historie()
        try:
            await self._herzien(extra=bewaard)
        finally:
            self._gereed = True
        await self._laad_archief()
        self._stop_timer = async_track_time_interval(
            self.hass, self._tik, timedelta(minutes=BV_MAND_HERZIEN_MINUTEN))
        self._monster_timer = async_track_time_interval(
            self.hass, self._monster_tik, timedelta(minutes=BV_MAND_SPREAD_MONSTER_MINUTEN))

    def _koppel_historie(self) -> None:
        """2.24.0 (L-GS-025): ``bv.mand_toppers`` legt elke herziening vast in
        de historie en toetst op de mediaan; die vindt hem op de venue."""
        venue = getattr(self.hoofd, "venue", None)
        if venue is not None:
            try:
                venue.spread_historie = self.spread_historie
            except Exception:  # noqa: BLE001
                pass

    @callback
    def _monster_tik(self, _nu) -> None:
        maak = getattr(self.entry, "async_create_background_task", None)
        taak = self._neem_monster()
        if maak is not None:
            maak(self.hass, taak, "gold_scalper mand spread")
        else:
            self.hass.async_create_task(taak)

    async def _neem_monster(self) -> None:
        """2.24.0 (L-GS-025): elk kwartier de spreads vastleggen (publiek)."""
        from .broker import bitvavo as bv

        if self._gestopt:
            return
        try:
            spreads = await bv.spread_monster(self.hoofd.venue, self.min_volume)
        except Exception as err:  # noqa: BLE001 - volgende keer opnieuw
            _LOGGER.debug("Bitvavo-mand: spreads niet opgehaald: %s", err)
            return
        self.spread_historie.waarneem(time.time(), spreads)
        if not self._gestopt:
            await self._bewaar()

    def spread_info(self, markt: str) -> dict:
        """2.24.0 (L-GS-025): mediane spread over 24 uur en het aantal
        waarnemingen, voor het overzicht."""
        nu = time.time()
        med = self.spread_historie.mediaan(markt, nu)
        return {"spread_mediaan_24u_pct": round(med, 4) if med is not None else None,
                "spread_waarnemingen_24u": self.spread_historie.aantal(markt, nu)}

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
        if not self._gestopt and self._gereed:
            await self._laad_archief()

    async def _herzien_kern(self, extra: list[str] | None = None) -> None:
        from .broker import bitvavo as bv

        self._koppel_historie()
        try:
            geweerd: list = []
            self.selectie = await bv.mand_toppers(
                self.hoofd.venue, self.aantal, self.min_volume, BV_MAND_MAX_SPREAD_PCT,
                verplicht=[self.hoofd.symbol], geweerd=geweerd)
            self.geweerd_spread = geweerd
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
        _LOGGER.info("Bitvavo-mand: %s markten (%s), %s posities open; spreadgrens "
                     "%s %% (mediaan 24 u), geweerd op spread: %s",
                     len(self.alle()), ", ".join([self.hoofd.symbol, *self.leden]),
                     self.aantal_open(), BV_MAND_MAX_SPREAD_PCT,
                     ", ".join(f"{r['market']} ({r.get('spread_toelating_pct', r['spread_pct'])} %"
                               f"{', mediaan' if r.get('spread_bron') == 'mediaan_24u' else ''})"
                               for r in self.geweerd_spread[:10]) or "geen")

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
        # 2.22.2: de markt blijft in het grootboek; na het stoppen opnieuw uit
        # zijn database gelezen (bij de volgende herziening).
        self.ooit.add(markt)
        self._archief.pop(markt, None)
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
        if self._monster_timer:
            self._monster_timer()
            self._monster_timer = None
        for markt in list(self.leden):
            await self._stop_lid(markt)

    async def zet_aan(self, waarde: bool) -> None:
        """De schakelaar van de hoofdlus geldt voor de hele mand."""
        for c in list(self.leden.values()):
            if c.enabled != waarde:
                await c.async_set_enabled(waarde)

    # -- grootboek van de hele mand (2.22.2) ------------------------------------ #

    async def _laad_archief(self) -> None:
        """Lees de gesloten trades van markten die nu niet draaien uit hun eigen
        database. Eenmalig per markt (ze veranderen niet zolang de markt stil
        staat); een markt die weer gaat draaien, telt via zijn lus."""
        try:
            map_pad = self.hass.config.path()
            gevonden = await self.hass.async_add_executor_job(ontdek_markten, map_pad)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Mand: databases niet te doorzoeken", exc_info=True)
            gevonden = []
        self.ooit |= set(gevonden)
        draaiend = {c.symbol for c in self.alle()}
        for markt in list(self._archief):
            if markt in draaiend:
                self._archief.pop(markt, None)
        versie = getattr(self.hoofd, "strategie_versie", None)
        nieuw = 0
        for markt in sorted(self.ooit - draaiend - set(self._archief)):
            pad = self.hass.config.path(db_bestand(markt))
            try:
                uit = await self.hass.async_add_executor_job(lees_markt, pad, markt, versie)
            except Exception as err:  # noqa: BLE001 - één onleesbare markt breekt niets
                _LOGGER.warning("Bitvavo-mand: trades van %s niet te lezen: %s", markt, err)
                continue
            if uit is not None:
                self._archief[markt] = uit
                nieuw += 1
        self._archief_geladen = True
        if nieuw:
            self._mand_stats = None
            _LOGGER.info(
                "Bitvavo-mand: grootboek aangevuld met %s markt(en) buiten de mand "
                "(%s trades)", nieuw,
                sum(s["trades"] for s, _ in self._archief.values()))

    @staticmethod
    def _rij_lid(c) -> dict:
        data = getattr(c, "data", None) or {}
        stats = data.get("stats") or {}
        start = getattr(c, "starting_balance", None)
        equity = data.get("equity")
        return {
            "markt": c.symbol, "trades": stats.get("trades") or 0,
            "wins": stats.get("wins") or 0, "losses": stats.get("losses") or 0,
            "netto": round(float(stats.get("net_pnl") or 0.0), 2),
            "kosten": round(float(stats.get("total_costs") or 0.0), 2),
            "startbalans": start, "equity": equity,
            "run_id": stats.get("run_id"), "bron": "lus",
        }

    def grootboek(self) -> dict:
        """2.22.2: trades, netto en equity van de hele mand: de draaiende markten
        uit hun lus, de andere uit hun database. De equity van de mand is de
        startbalans plus het resultaat van alle markten (inclusief de open
        posities van de draaiende markten)."""
        rijen = [self._rij_lid(c) for c in self.alle()]
        draaiend = {r["markt"] for r in rijen}
        for markt, (samenvatting, _) in sorted(self._archief.items()):
            if markt in draaiend:
                continue
            rijen.append({**samenvatting, "equity": (
                (samenvatting.get("startbalans") or 0.0) + samenvatting["netto"]
                if samenvatting.get("startbalans") else None)})
        start = float(getattr(self.hoofd, "starting_balance", None) or 0.0)
        resultaat = 0.0
        for r in rijen:
            if r.get("bron") == "lus" and r.get("equity") is not None and r.get("startbalans"):
                resultaat += float(r["equity"]) - float(r["startbalans"])
            else:
                resultaat += float(r.get("netto") or 0.0)
        netto = round(sum(float(r.get("netto") or 0.0) for r in rijen), 2)
        return {
            "trades": sum(int(r.get("trades") or 0) for r in rijen),
            "wins": sum(int(r.get("wins") or 0) for r in rijen),
            "losses": sum(int(r.get("losses") or 0) for r in rijen),
            "netto": netto,
            "kosten": round(sum(float(r.get("kosten") or 0.0) for r in rijen), 2),
            "startbalans": start or None,
            "balans": round(start + netto, 2) if start else None,
            "equity": round(start + resultaat, 2) if start else None,
            "open_posities": self.aantal_open(),
            "markten_met_trades": sorted(r["markt"] for r in rijen if r.get("trades")),
            "per_markt": sorted(
                ({k: r.get(k) for k in ("markt", "trades", "wins", "losses", "netto",
                                        "equity", "run_id", "bron", "laatste_trade",
                                        "eerdere_runs_trades")
                  if k in r}
                 for r in rijen if r.get("trades") or r.get("bron") == "database"),
                key=lambda r: (-(r.get("trades") or 0), r["markt"])),
        }

    async def alle_gesloten_trades(self) -> list:
        """Alle gesloten trades van de mand: de draaiende markten (laatste
        papieren run) en de markten in het archief."""
        trades: list = []
        draaiend = set()
        for c in self.alle():
            draaiend.add(c.symbol)
            try:
                run = await self.hass.async_add_executor_job(c._laatste_papieren_run)
                if run is not None:
                    trades.extend(await self.hass.async_add_executor_job(c.db.closed_trades, run))
            except Exception:  # noqa: BLE001 - één onleesbaar lid breekt niets
                _LOGGER.debug("Mand: trades van %s niet te lezen", getattr(c, "symbol", "?"),
                              exc_info=True)
        for markt, (_, archief) in self._archief.items():
            if markt not in draaiend:
                trades.extend(archief)
        trades.sort(key=lambda t: _tijd(getattr(t, "close_time", None)))
        return trades

    def _stats_sleutel(self) -> tuple:
        """Verandert zodra er ergens in de mand een trade sluit."""
        boek = self.grootboek()
        return (boek["trades"], boek["netto"])

    async def statistiek(self, max_leeftijd: float = 600.0) -> dict | None:
        """2.22.2: de statistiek (trades, netto, t, oordeel) over de hele mand.
        Opnieuw berekend zodra er een trade bij komt, anders hooguit eens per
        ``max_leeftijd`` seconden."""
        from .storage import performance

        nu = time.monotonic()
        sleutel = self._stats_sleutel()
        if (self._mand_stats and nu - self._mand_stats[0] < max_leeftijd
                and self._mand_stats[2] == sleutel):
            return self._mand_stats[1]
        h = self.hoofd
        if getattr(h, "db", None) is None or getattr(h, "run_id", None) is None:
            return None
        trades = await self.alle_gesloten_trades()
        stats = await self.hass.async_add_executor_job(
            performance.compute_for_run, h.db, h.run_id, trades)
        stats["over_hele_mand"] = True
        self._mand_stats = (time.monotonic(), stats, sleutel)
        return stats

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
                "volume_24u": _rond((info.get(markt) or {}).get("volume"), 0),
                "spread_pct": (info.get(markt) or {}).get("spread_pct"),
                "uitfaseren": markt in self.uitfaseren,
                "koers": _rond(data.get("price"), 6),
                "netto": (data.get("stats") or {}).get("net_pnl"),
                "trades": (data.get("stats") or {}).get("trades"),
                "weigering": getattr(c, "_laatste_weigering", None),
                # 2.23.0: alle weigeringen sinds de start, per richting en
                # reden (de laatste alleen liet zien wat toevallig het laatst
                # gebeurde - meestal een short, die spot niet kan).
                # 2.23.1 (L-GS-028): top 3 (was 8) - de attributen van de mand
                # werden > 16 kB en de recorder bewaarde ze niet meer.
                "weigeringen": _top(getattr(c, "weigeringen", None), _TOP_WEIGERINGEN_LID),
                "opzet_tijdvakken": list(getattr(c, "vp_tijdvakken", ()) or ()),
                # 2.21.3 (L-GS-022): staat dit lid zelf in een noodstop?
                "noodstop": bool(self._gestopt_door_risico(c)),
                # 2.21.0: equity en een actieve saldosprong per markt. De leden
                # hebben geen eigen sensoren; zonder dit was een sprong bij
                # een lid nergens te zien (22-10 23:47).
                "equity": _rond(data.get("equity"), 2),
                "saldosprong": (data.get("saldosprong") or {}).get("reden")
                if (data.get("saldosprong") or {}).get("actief") else None,
            })
        boek = self.grootboek()
        samen: dict[str, int] = {}
        for c in self.alle():
            for k, v in (getattr(c, "weigeringen", None) or {}).items():
                samen[k] = samen.get(k, 0) + int(v)
        return {
            # 2.23.0: weigeringen van de hele mand per richting en reden.
            "weigeringen": _top(samen, 12),
            "markten": len(rijen), "open_posities": self.aantal_open(),
            # 2.22.2: het grootboek van de hele mand, ook van markten die er
            # niet meer in zitten.
            "totaal": {k: boek[k] for k in ("trades", "wins", "losses", "netto",
                                            "kosten", "equity", "balans")},
            # 2.23.1 (L-GS-028): alleen markten buiten de mand mét trades, kort
            # (markt, trades, netto, laatste trade) en hooguit
            # ``_MAX_BUITEN_MAND``; de rest samengeteld. De volledige tabel
            # staat op *Trades* (``per_markt``) en in de diagnostics.
            **_buiten_mand(boek["per_markt"]),
            "max_posities": self.max_posities, "doel_aantal": self.aantal,
            "min_volume": self.min_volume, "herzien_om": self.herzien_om,
            "fout": self.laatste_fout, "per_markt": rijen,
            "saldosprong": [r["markt"] for r in rijen if r.get("saldosprong")],
            # 2.22.0: noodstop per markt en de spreadgrens van de mandkeuze.
            "noodstop_markten": [r["markt"] for r in rijen if r.get("noodstop")],
            "max_spread_pct": BV_MAND_MAX_SPREAD_PCT,
            "geweerd_op_spread": [
                {"markt": r["market"], "spread_pct": r["spread_pct"],
                 **({"spread_mediaan_24u_pct": r["spread_mediaan_pct"]}
                    if r.get("spread_mediaan_pct") is not None else {})}
                for r in self.geweerd_spread[:20]],
            # 2.24.0 (L-GS-025): toelating op de mediaan over 24 uur.
            "spread_toelating": "mediaan_24u",
            # Per lid de mediaan waarop toegelaten wordt (alleen bij genoeg
            # waarnemingen; compact i.v.m. de 16 kB van de recorder).
            "spread_mediaan_24u": {
                r["markt"]: med for r in rijen
                if (med := self.spread_info(r["markt"])["spread_mediaan_24u_pct"]) is not None},
            "spread_historie_markten": len(self.spread_historie),
        }

    def saldosprongen(self) -> list[str]:
        """2.21.0: redenen van een actieve saldosprong bij de leden."""
        uit = []
        for c in self.leden.values():
            sprong = getattr(c, "saldosprong", None)
            if sprong is not None and getattr(sprong, "actief", False):
                uit.append(sprong.reden or c.symbol)
        return uit
