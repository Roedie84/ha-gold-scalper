"""Backtest: de strategie over historische candles laten lopen.

**Het belangrijkste ontwerpbesluit.** Deze module bouwt de strategie niet na.
Hij roept dezelfde ``evaluate()`` aan en dezelfde ``ExitManager`` als de live
handelslus. Een backtest die de strategie herimplementeert, toetst de
herimplementatie - en die is per definitie een andere. Elke afwijking die je
dan meet, kan net zo goed in de nabouw zitten als in de markt.

**Wat hier wél gemodelleerd wordt.** Instap op bid of ask, spread als kosten,
slippage als aanname, stops getoetst tegen de uitersten binnen de bar in plaats
van tegen de slotkoers, en bij twijfel de ongunstige volgorde.

**Wat níet.** Spread die verbreedt rond nieuws, requotes, partiële fills,
latency tussen signaal en fill, en het feit dat je broker je orderflow ziet.
Een backtest valt daardoor stelselmatig gunstiger uit dan de werkelijkheid.
Reken op minder, niet op meer.

**En de grootste valkuil is niet technisch.** Een backtest die je gebruikt om
instellingen te kiezen, meet daarna niets meer: je hebt de uitkomst in de
keuze gestopt. Draai hem één keer, noteer de uitkomst, en verander daarna niets
op grond van wat je zag. Wie twintig varianten probeert en de beste kiest, heeft
de beste van twintig ruisuitkomsten gekozen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..analysis.signals import Candles
from ..broker.exits import ExitConfig, ExitManager
from ..const import EXECUTION_SEMANTICS_VERSION, STRATEGY_WINDOW_BARS
from ..strategy.scalping import ScalpConfig, evaluate

_LOGGER = logging.getLogger(__name__)

#: Aantal candles dat de indicatoren nodig hebben voordat er gehandeld wordt.
WARMUP_BARS = 300

#: Versie van deze backtestmotor. Een uitslag draagt hem mee, zodat zichtbaar
#: blijft met welke motor hij is gemaakt.
#:
#: 1  de strategie kreeg bij elke bar de volledige historie tot dan toe:
#:    kwadratische looptijd, en een ander startpunt voor EMA's en ATR dan live.
#: 2  hetzelfde begrensde venster als live (``STRATEGY_WINDOW_BARS``).
#: 3  kosten per component (spread, slippage), de oorspronkelijke stop en het
#:    doel, en per trade of de exit dubbelzinnig was. Uitkomsten per trade
#:    gelijk aan versie 2; de uitvoer is uitgebreid.
#: 4  segmenten: optioneel pas vanaf een tijdstip beoordelen, geen nieuwe
#:    instap vanaf een afkapmoment, en een positie die aan het einde van de
#:    data nog openstaat sluiten op de laatste bar (reden ``segment_end``) in
#:    plaats van weglaten. Zonder die opties identiek aan versie 3.
BACKTEST_ENGINE_VERSION = 4

#: Wat een bar-gebaseerde backtest wel en niet kan nabootsen. Staat in elke
#: uitslag, zodat een oordeel nooit sterker klinkt dan de motor rechtvaardigt.
BEKENDE_BEPERKINGEN = (
    "Exits worden per bar beoordeeld; live gebeurt dat elke 10 seconden. Een "
    "tijdstop of trailing stop reageert in de backtest pas bij de volgende bar.",
    "Binnen één bar is de volgorde van hoog en laag onbekend. Raken stop en doel "
    "dezelfde bar, dan telt de stop (vooraf vastgelegde, voorzichtige regel).",
    "Instap op de slotkoers van de bar met een vaste halve spread en slippage; "
    "live is de spread variabel.",
    "Geen wisselkoersopslag van de broker in deze uitslag.",
)


@dataclass(slots=True)
class BacktestTrade:
    opened_at: int
    closed_at: int
    side: str
    units: float
    entry: float
    exit: float
    entry_mid: float
    exit_mid: float
    gross: float
    cost: float
    net: float
    reason: str
    score: float
    regime: str | None = None
    mae: float = 0.0
    mfe: float = 0.0
    #: Kosten per component, in instrumentvaluta. ``cost`` = hun som.
    #: Spread: beide halve spreads (instap en uitstap). Slippage: alleen bij
    #: de instap - zo rekent deze motor al sinds versie 1.
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    #: Stop en doel zoals ze bij de instap werden gezet.
    stop_price: float | None = None
    target_price: float | None = None
    #: Stop en doel vielen in dezelfde bar; de stop is aangenomen.
    ambiguous_exit: bool = False

    def as_record(self) -> dict:
        """Alle velden, onafgerond. De bron voor het Experiment Lab.

        ``as_dict`` rondt af voor weergave (bruto en netto op 2 decimalen) en
        is daarom ongeschikt als bron: afgeronde bruto min onafgeronde kosten
        is geen afgeronde netto.
        """
        return {f: getattr(self, f) for f in self.__dataclass_fields__}

    def as_dict(self) -> dict:
        return {
            "opened_at": self.opened_at, "closed_at": self.closed_at,
            "side": self.side, "units": round(self.units, 3),
            "entry": round(self.entry, 3), "exit": round(self.exit, 3),
            "gross": round(self.gross, 2), "cost": round(self.cost, 2),
            "net": round(self.net, 2), "reason": self.reason,
            "score": round(self.score, 3), "regime": self.regime,
            "spread_cost": self.spread_cost, "slippage_cost": self.slippage_cost,
            "stop_price": self.stop_price, "target_price": self.target_price,
            "ambiguous_exit": self.ambiguous_exit,
        }


@dataclass(slots=True)
class BacktestResult:
    bars: int = 0
    evaluations: int = 0
    trades: list[BacktestTrade] = field(default_factory=list)
    rejections: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: Trades waarbij stop en doel in dezelfde bar vielen.
    ambiguous_exits: int = 0
    #: Tijdsframe afgeleid uit de afstand tussen de bars, in seconden.
    bar_spacing_seconds: int | None = None

    @property
    def net_pnl(self) -> float:
        return sum(t.net for t in self.trades)

    @property
    def gross_pnl(self) -> float:
        return sum(t.gross for t in self.trades)

    @property
    def total_costs(self) -> float:
        return sum(t.cost for t in self.trades)

    def summary(self) -> dict:
        wins = [t for t in self.trades if t.net > 0]
        losses = [t for t in self.trades if t.net <= 0]
        return {
            "bars": self.bars,
            "evaluations": self.evaluations,
            "trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (
                round(len(wins) / len(self.trades) * 100, 1)
                if self.trades else 0.0
            ),
            "gross_pnl": round(self.gross_pnl, 2),
            "total_costs": round(self.total_costs, 2),
            "net_pnl": round(self.net_pnl, 2),
            "cost_ratio": (
                round(self.total_costs / abs(self.gross_pnl), 3)
                if self.gross_pnl else None
            ),
            "rejections": dict(
                sorted(self.rejections.items(), key=lambda kv: -kv[1])
            ),
            "warnings": self.warnings,
            "provenance": {
                "engine_version": BACKTEST_ENGINE_VERSION,
                "strategy_window_bars": STRATEGY_WINDOW_BARS,
                "execution_semantics": EXECUTION_SEMANTICS_VERSION,
            },
            "fidelity": {
                "simulation_model": "BAR_ONLY",
                "execution_fidelity": "BAR_ONLY",
                "signal_resolution": "slot van de bar",
                "entry_resolution": "slot van de bar",
                "exit_resolution": "hoog/laag van de volgende bar",
                "source_bar_seconds": self.bar_spacing_seconds,
                "intrabar_data_available": False,
                "intrabar_assumption": "stop eerst",
                "ambiguous_exits": self.ambiguous_exits,
                "ambiguous_share": (
                    round(self.ambiguous_exits / len(self.trades) * 100, 1)
                    if self.trades else 0.0
                ),
                "known_limitations": list(BEKENDE_BEPERKINGEN),
            },
        }


def run_backtest(
    candles: Candles,
    strategy: ScalpConfig,
    exits: ExitConfig | None = None,
    *,
    spread: float = 0.60,
    slippage: float = 0.02,
    units: float = 1.0,
    invert: bool = False,
    progress=None,
    progress_every: int = 200,
    evaluate_from_ts: int | None = None,
    no_entries_from_ts: int | None = None,
    close_open_at_end: bool = False,
) -> BacktestResult:
    """Loop bar voor bar door de historie met de échte strategiecode.

    Met ``invert`` wordt elk signaal omgedraaid: een koopsignaal wordt een
    verkoop en omgekeerd.

    Dat is geen truc maar een toets met nul vrijheidsgraden. De gemeten
    trefkans van 30,4% ligt ver onder de 39,3% die willekeurig instappen zou
    opleveren bij dezelfde exits. Een signaal dat structureel slechter is dan
    toeval bevat informatie - met het verkeerde teken. Of dat werkelijk zo is,
    valt alleen te zien door het om te draaien.

    Let op wat dit NIET is: er valt niets aan af te stellen. Het werkt of het
    werkt niet, en dat is precies waarom deze toets wel mag waar
    parameteroptimalisatie niet mag.
    """
    result = BacktestResult(bars=len(candles))
    if len(candles) < WARMUP_BARS + 10:
        result.warnings.append(
            f"{len(candles)} bars; er zijn er minstens {WARMUP_BARS + 10} nodig "
            "voordat de indicatoren iets zeggen."
        )
        return result

    manager = ExitManager(exits or ExitConfig())
    half = spread / 2.0
    round_trip = spread + 2 * slippage

    open_trade: dict | None = None

    if len(candles) > 1:
        afstanden = sorted(
            b - a for a, b in zip(candles.timestamp, candles.timestamp[1:])
        )
        result.bar_spacing_seconds = int(afstanden[len(afstanden) // 2])

    totaal = max(0, len(candles) - 1 - WARMUP_BARS)
    for i in range(WARMUP_BARS, len(candles) - 1):
        # Voortgang en coöperatief annuleren. De aanroep mag een uitzondering
        # gooien om te stoppen; die gaat ongewijzigd naar boven. Zonder
        # aanroep verandert er niets aan het gedrag.
        if progress is not None and (i - WARMUP_BARS) % progress_every == 0:
            progress(i - WARMUP_BARS, totaal)

        # Hetzelfde begrensde venster als live: de laatste
        # STRATEGY_WINDOW_BARS afgesloten bars tot en met bar i. Nooit bars
        # na i - die bestonden op het beslismoment nog niet.
        begin = max(0, i + 1 - STRATEGY_WINDOW_BARS)
        window = Candles(
            candles.timestamp[begin:i + 1], candles.open[begin:i + 1],
            candles.high[begin:i + 1], candles.low[begin:i + 1],
            candles.close[begin:i + 1], candles.volume[begin:i + 1],
        )
        mid = candles.close[i]
        bid, ask = mid - half, mid + half
        moment = datetime.fromtimestamp(candles.timestamp[i], timezone.utc)

        # --- lopende positie beheren --------------------------------------- #
        if open_trade is not None:
            nxt = i + 1
            high, low = candles.high[nxt], candles.low[nxt]
            long = open_trade["side"] == "buy"
            direction = 1.0 if long else -1.0

            # Uitersten binnen de volgende bar, niet de slotkoers. Op de
            # slotkoers toetsen mist stops die geraakt werden en daarna
            # herstelden - allemaal in je voordeel, wat het resultaat
            # stelselmatig te mooi maakt.
            worst = (low - half) if long else (high + half)
            best = (high - half) if long else (low + half)
            open_trade["mae"] = min(
                open_trade["mae"], (worst - open_trade["entry"]) * direction
            )
            open_trade["mfe"] = max(
                open_trade["mfe"], (best - open_trade["entry"]) * direction
            )

            stop_hit = open_trade["stop"] is not None and (
                worst <= open_trade["stop"] if long else worst >= open_trade["stop"]
            )
            target_hit = open_trade["target"] is not None and (
                best >= open_trade["target"] if long else best <= open_trade["target"]
            )

            # Zijn beide binnen dezelfde bar geraakt, dan valt uit een candle
            # niet af te leiden welke eerst kwam. De stop aannemen is de enige
            # verdedigbare keuze; gokken op de gunstige volgorde is precies hoe
            # een backtest zichzelf rijk rekent.
            # De mid die bij de exitprijs hoort, niet de slotkoers van de bar.
            # Die twee door elkaar halen maakte de kosten negatief: bruto werd
            # op een heel ander prijsniveau berekend dan netto.
            dubbelzinnig = bool(stop_hit and target_hit)
            if dubbelzinnig:
                result.ambiguous_exits += 1
            if stop_hit:
                level = open_trade["stop"]
                _close(result, open_trade, level, "stop_loss",
                       candles.timestamp[nxt], level + (half if long else -half),
                       units, round_trip, spread, slippage, dubbelzinnig)
                open_trade = None
            elif target_hit:
                level = open_trade["target"]
                _close(result, open_trade, level, "take_profit",
                       candles.timestamp[nxt], level + (half if long else -half),
                       units, round_trip, spread, slippage)
                open_trade = None
            else:
                action = manager.evaluate(
                    side=open_trade["side"], volume=units / 100.0,
                    open_price=open_trade["entry"],
                    current_stop=open_trade["stop"],
                    bid=bid, ask=ask,
                    atr=open_trade["atr"],
                    opened_at=open_trade["opened"],
                    now=moment,
                    round_trip_cost_per_oz=round_trip,
                    partial_taken=open_trade["partial"],
                )
                if action.kind == "close":
                    exit_price = bid if long else ask
                    _close(result, open_trade, exit_price, action.reason[:40],
                           candles.timestamp[i], mid, units, round_trip,
                           spread, slippage)
                    open_trade = None
                elif action.kind == "modify_stop":
                    open_trade["stop"] = action.new_stop
                elif action.kind == "partial_close":
                    open_trade["partial"] = True

        # --- signaal zoeken ------------------------------------------------- #
        # Segmenten: vóór evaluate_from_ts is het opwarmdata (voedt alleen het
        # venster), vanaf no_entries_from_ts geen nieuwe instap meer. Beide
        # tellen niet mee als beoordeling.
        if open_trade is None and (
            (evaluate_from_ts is not None and candles.timestamp[i] < evaluate_from_ts)
            or (no_entries_from_ts is not None and candles.timestamp[i] >= no_entries_from_ts)
        ):
            continue
        if open_trade is None:
            result.evaluations += 1
            signal = evaluate(
                window, bid, ask, strategy, moment.hour, 0, 1e9
            )
            if not signal.should_trade:
                key = signal.reject_reason or "onbekend"
                result.rejections[key] = result.rejections.get(key, 0) + 1
                continue

            long = signal.direction == 1
            stop, target = signal.stop_loss, signal.take_profit

            if invert:
                # De richting omdraaien én de niveaus mee spiegelen.
                #
                # Alleen de kant omdraaien zou de stop boven de instap laten
                # liggen voor een short en het doel eronder: de positie sluit
                # dan meteen. Je zou iets toetsen wat je niet bedoelde en een
                # zinloze uitkomst krijgen die eruitziet als een antwoord.
                #
                # De afstanden blijven gelijk, zodat de verhouding tussen doel
                # en stop hetzelfde is als in de gewone richting.
                doel_afstand = (
                    abs(target - mid) if target is not None else None
                )
                stop_afstand = abs(stop - mid) if stop is not None else None
                long = not long
                richting = 1.0 if long else -1.0
                target = (
                    mid + richting * doel_afstand
                    if doel_afstand is not None else None
                )
                stop = (
                    mid - richting * stop_afstand
                    if stop_afstand is not None else None
                )

            entry = (ask if long else bid) + (slippage if long else -slippage)
            open_trade = {
                "side": "buy" if long else "sell",
                "entry": entry,
                "entry_mid": mid,
                "stop": stop,
                "target": target,
                "stop_initial": stop,
                "target_initial": target,
                "atr": signal.components.get("atr", 1.0),
                "opened": moment,
                "opened_ts": candles.timestamp[i],
                "score": signal.score,
                "regime": signal.components.get("regime"),
                "partial": False,
                "mae": 0.0,
                "mfe": 0.0,
            }

    if open_trade is not None and close_open_at_end and len(candles) > 0:
        # Segmenteinde: sluiten op de slotkoers van de laatste bar, aan de
        # juiste kant van de spread. Nooit bars van na het segment gebruiken.
        laatste = len(candles) - 1
        mid_eind = candles.close[laatste]
        lang = open_trade["side"] == "buy"
        uit = mid_eind - half if lang else mid_eind + half
        _close(result, open_trade, uit, "segment_end", candles.timestamp[laatste],
               mid_eind, units, round_trip, spread, slippage)
        open_trade = None
    if open_trade is not None:
        result.warnings.append(
            "De laatste positie stond bij het einde van de data nog open en is "
            "niet meegeteld."
        )
    return result


def _close(
    result: BacktestResult, trade: dict, exit_price: float, reason: str,
    closed_ts: int, exit_mid: float, units: float, round_trip: float,
    spread: float = 0.0, slippage: float = 0.0, ambiguous: bool = False,
) -> None:
    direction = 1.0 if trade["side"] == "buy" else -1.0
    gross = (exit_mid - trade["entry_mid"]) * direction * units
    net = (exit_price - trade["entry"]) * direction * units
    # De kosten uit de modelgrootheden: spread over instap en uitstap samen,
    # slippage alleen bij de instap. Hun som is algebraïsch gelijk aan
    # bruto - netto; een verschil groter dan afrondingsruis is een fout.
    spread_cost = spread * units
    slippage_cost = slippage * units
    if abs((gross - net) - (spread_cost + slippage_cost)) > 1e-6 * max(1.0, abs(gross)):
        raise AssertionError(
            f"kosten per component sluiten niet aan: {gross - net} tegenover "
            f"{spread_cost + slippage_cost}"
        )
    result.trades.append(BacktestTrade(
        opened_at=trade["opened_ts"], closed_at=closed_ts,
        side=trade["side"], units=units,
        entry=trade["entry"], exit=exit_price,
        entry_mid=trade["entry_mid"], exit_mid=exit_mid,
        gross=gross, cost=gross - net, net=net,
        reason=reason, score=trade["score"], regime=trade["regime"],
        mae=trade["mae"], mfe=trade["mfe"],
        spread_cost=spread_cost, slippage_cost=slippage_cost,
        stop_price=trade.get("stop_initial"), target_price=trade.get("target_initial"),
        ambiguous_exit=ambiguous,
    ))
