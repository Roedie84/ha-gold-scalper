"""Daghandel: trendvolgende uitbraak op uurschaal, dicht voor het einde van de dag (2.0.0).

Besluit van Ruud (12-10-2026): van scalpen naar daghandel. Onderzoek
(L-GS-014) over 2011-2018 (160.000 kwartierbars) en IG juni-oktober 2026:

* De scalper verloor ~1,5 USD/oz per trade: de kosten (spread + slippage)
  waren ongeveer even groot als de beweging die een trade van vier minuten
  kan vangen.
* Van vijf vooraf vastgelegde daghandelopzetten was deze de beste: netto
  +0,10 ATR(15m) per trade in 2011-2014, +0,17 in 2015-2018 en -0,02 op de
  IG-data van 2026 (35 trades). De kosten zijn hier ~20% van de beweging in
  plaats van ~100%. **Een aantoonbaar voordeel is het niet** (t < 1); het
  draait op demo om dat te meten.

Regels (gelijk aan de backtest):

* **Richting**: EMA(20) boven EMA(50) op de slotkoersen per uur (alleen
  afgesloten uren) = alleen long; eronder = alleen short.
* **Instap**: het slot van de laatste afgesloten kwartierbar breekt door het
  hoogste hoog (long) of laagste laag (short) van de 80 bars ervóór (20 uur).
  Alleen tussen 07:00 en 17:00 UTC, hooguit één positie tegelijk.
* **Stop**: 2 x ATR(1u) = 4 x ATR(15m) van de instap.
* **Uitstap** (in ``broker/exits``): meelopende stop op 4 x ATR(15m) vanaf
  2 x ATR winst, geen tijdstop, geen break-even; uiterlijk om 20:45 UTC
  dicht (geen nachtkosten, geen gat over de dagpauze).

Geeft een ``ScalpSignal`` terug zodat de rest van de keten (orders,
schaduwtrades, logging) ongewijzigd werkt.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..analysis.signals import Candles
from ..broker.exits import ExitConfig
from ..analysis.volatility import atr
from .scalping import ScalpConfig, ScalpSignal

#: In runs.strategy_version; een andere strategie is altijd een nieuwe run.
STRATEGIE_VERSIE = "daghandel-1.0.0"

KANAAL_BARS = 80
EMA_SNEL = 20
EMA_TRAAG = 50
STOP_ATR15 = 4.0
#: 2.1.0 (Ruud: "winst veiligstellen met trailing stops"): 4 in plaats van
#: 6 x ATR. Backtest 2011-2018: netto +0,20 tegen +0,12 ATR per trade, beter
#: in beide helften (+0,27/+0,13 tegen +0,10/+0,13). Krapper (2 x ATR vanaf
#: 1 x ATR) of een break-evenstop deden het slechter: dan stopt een trend
#: te vroeg. Vanaf 2 x ATR winst ligt de stop op instap - 2 x ATR; vanaf
#: 4 x ATR winst staat er winst vast.
VOLGSTOP_ATR15 = 4.0
VOLGSTOP_VANAF_ATR15 = 2.0
INSTAP_VAN_UUR = 7.0
INSTAP_TOT_UUR = 17.0
#: 20:45 UTC: laatste kwartier vóór de dagpauze van IG.
SLUIT_OM_UUR = 20.75
#: Na een instap minstens één bar wachten (de backtest stapt pas in op een
#: bar ná de vorige uitstap).
WACHT_SECONDEN = 900


def exit_config() -> ExitConfig:
    """Uitstapregels van de backtest: geen tijdstop, geen break-even, geen
    deelsluiting; volgstop 4 x ATR vanaf 2 x ATR winst (2.1.0); dicht om
    20:45 UTC. ``max_hold_seconds`` is alleen een vangnet."""
    return ExitConfig(
        breakeven_trigger_atr=1e9,
        enable_partial_close=False,
        enable_trailing=True,
        trailing_activate_atr=VOLGSTOP_VANAF_ATR15,
        trailing_distance_atr=VOLGSTOP_ATR15,
        time_stop_seconds=10 ** 9,
        max_hold_seconds=14 * 3600,
        sluit_om_uur_utc=SLUIT_OM_UUR,
    )


def _seconden(ts: float) -> float:
    return ts / 1000.0 if ts > 1e12 else float(ts)


def _ema(waarden: list[float], span: int) -> float | None:
    if not waarden:
        return None
    alfa = 2.0 / (span + 1.0)
    e = waarden[0]
    for x in waarden[1:]:
        e += alfa * (x - e)
    return e


def uur_emas(candles: Candles) -> tuple[float | None, float | None]:
    """EMA20/50 over de slotkoers per afgesloten uur, vóór het uur van de
    laatste bar (zoals de backtest: geen kijken in het lopende uur)."""
    if not len(candles):
        return None, None
    laatste_uur = int(_seconden(candles.timestamp[-1]) // 3600)
    per_uur: dict[int, float] = {}
    for ts, slot in zip(candles.timestamp, candles.close):
        uur = int(_seconden(ts) // 3600)
        if uur < laatste_uur:
            per_uur[uur] = slot
    reeks = [per_uur[u] for u in sorted(per_uur)]
    if len(reeks) < EMA_TRAAG:
        return None, None
    return _ema(reeks, EMA_SNEL), _ema(reeks, EMA_TRAAG)


@dataclass(slots=True)
class DaghandelStand:
    """Wat de strategie ziet, voor de diagnose."""

    ema_snel: float | None
    ema_traag: float | None
    kanaal_hoog: float | None
    kanaal_laag: float | None
    atr15: float | None


def stand(candles: Candles, cfg: ScalpConfig) -> DaghandelStand:
    if len(candles) < KANAAL_BARS + 1:
        return DaghandelStand(None, None, None, None, None)
    snel, traag = uur_emas(candles)
    a = atr(candles, 14)[-1]
    return DaghandelStand(
        snel, traag,
        max(candles.high[-KANAAL_BARS - 1:-1]),
        min(candles.low[-KANAAL_BARS - 1:-1]),
        None if a is None else a * cfg.atr_correction,
    )


def evaluate_daghandel(
    candles: Candles,
    bid: float,
    ask: float,
    cfg: ScalpConfig,
    hour_utc: int,
    open_position_count: int = 0,
    seconds_since_last_entry: float = 1e9,
    open_position_side: int = 0,
    open_per_richting: dict[int, int] | None = None,
    minuut_utc: int = 0,
) -> ScalpSignal:
    """Zelfde aanroep als ``scalping.evaluate``; ander besluit."""

    def weiger(reden: str, tekst: str, score: float = 0.0, richting: int = 0,
               onderdelen: dict | None = None) -> ScalpSignal:
        return ScalpSignal(
            direction=richting, score=score, confidence=0.0, should_trade=False,
            reject_reason=reden, reason=tekst, components=onderdelen or {},
        )

    if len(candles) < KANAAL_BARS + 1:
        return weiger("insufficient_data", f"Slechts {len(candles)} candles beschikbaar")
    spread = ask - bid
    if spread > cfg.max_spread:
        return weiger("spread_too_wide",
                      f"Spread {spread:.3f} boven de absolute limiet {cfg.max_spread:.3f}")

    s = stand(candles, cfg)
    onderdelen = {
        "strategie": "daghandel",
        "ema20_uur": None if s.ema_snel is None else round(s.ema_snel, 3),
        "ema50_uur": None if s.ema_traag is None else round(s.ema_traag, 3),
        "kanaal_hoog": s.kanaal_hoog, "kanaal_laag": s.kanaal_laag,
        "atr": None if s.atr15 is None else round(s.atr15, 3),
        "spread_atr_ratio": None if not s.atr15 else round(spread / s.atr15, 3),
    }
    if s.ema_snel is None or s.ema_traag is None:
        return weiger("insufficient_data", "Nog geen 50 afgesloten uren voor de uur-EMA's",
                      onderdelen=onderdelen)
    if not s.atr15 or s.atr15 <= 0:
        return weiger("insufficient_data", "Geen bruikbare ATR", onderdelen=onderdelen)

    trend = 1 if s.ema_snel > s.ema_traag else -1
    slot = candles.close[-1]
    uitbraak = (
        1 if trend == 1 and slot > s.kanaal_hoog
        else -1 if trend == -1 and slot < s.kanaal_laag
        else 0
    )
    # Score: hoe ver het slot door het kanaal is, in ATR, met het teken van
    # de richting. Alleen ter informatie; de beslissing is ja/nee.
    if trend == 1:
        afstand = (slot - s.kanaal_hoog) / s.atr15
    else:
        afstand = (s.kanaal_laag - slot) / s.atr15
    score = max(-1.0, min(1.0, trend * (0.5 + afstand / 4.0))) if uitbraak else 0.0
    onderdelen["trend"] = trend
    onderdelen["uitbraak_atr"] = round(afstand, 3)

    kant = "long" if trend == 1 else "short"
    uur = hour_utc + minuut_utc / 60.0
    if not uitbraak:
        grens = s.kanaal_hoog if trend == 1 else s.kanaal_laag
        return weiger(
            "geen_uitbraak",
            f"Trend {kant} (uur-EMA20 {s.ema_snel:.2f} {'>' if trend == 1 else '<'} "
            f"EMA50 {s.ema_traag:.2f}); slot {slot:.2f} nog niet door "
            f"{grens:.2f} (kanaal 20 uur)",
            0.0, trend, onderdelen,
        )
    if not (INSTAP_VAN_UUR <= uur < INSTAP_TOT_UUR):
        return weiger(
            "outside_hours",
            f"Uitbraak {kant}, maar instappen alleen tussen 07:00 en 17:00 UTC",
            score, trend, onderdelen,
        )

    entry = ask if trend == 1 else bid
    stop = entry - trend * STOP_ATR15 * s.atr15
    signaal = ScalpSignal(
        direction=trend, score=round(score, 3), confidence=1.0,
        should_trade=True, reject_reason=None, geldig=True,
        reason=(
            f"Daghandel {kant}: slot {slot:.2f} door het kanaal van 20 uur "
            f"({s.kanaal_hoog:.2f}/{s.kanaal_laag:.2f}), uurtrend {kant}. "
            f"Stop {STOP_ATR15:g} x ATR ({STOP_ATR15 * s.atr15:.2f} USD/oz), "
            f"volgstop {VOLGSTOP_ATR15:g} x ATR vanaf {VOLGSTOP_VANAF_ATR15:g} x ATR winst, dicht om 20:45 UTC"
        ),
        stop_loss=round(stop, 3),
        take_profit=None,
        expected_move=round(STOP_ATR15 * s.atr15, 3),
        expected_cost=round(spread + 2 * cfg.expected_slippage, 3),
        components=onderdelen,
    )
    if open_position_count >= 1:
        signaal.should_trade = False
        signaal.reject_reason = "max_positions_zelfde_richting"
        signaal.reason = "Daghandel: al een positie open; hooguit één tegelijk"
    elif seconds_since_last_entry < WACHT_SECONDEN:
        signaal.should_trade = False
        signaal.reject_reason = "cooldown"
        signaal.reason = (
            f"Daghandel: nog {WACHT_SECONDEN - seconds_since_last_entry:.0f}s "
            "wachten na de vorige instap"
        )
    return signaal
