"""Veldproef: veel opzetten op veel tijdvakken tegelijk, met echte demo-orders (2.4.0).

Opdracht van Ruud (12-10-2026): "geen schaduw trading maar echt traden op
diverse candle-tijden, 1m 3m 5m 15m 30m, zoveel mogelijk, allemaal om dat te
verzamelen en te leren" en "geen keuzes voor mij, vol gas".

Onderzoek vooraf (L-GS-017, 12-10, bars van IG juni-oktober en 10 dagen
10-secondenkoersen): 54 opzetten x 6 tijdvakken x 18 uitstapvarianten. Bruto
(zonder kosten) gemiddeld ~0 op alle tijdvakken; wat op het eerste deel won,
verloor op het laatste deel. Er is dus vooraf geen winnaar aan te wijzen. Deze
veldproef draait daarom alle families op alle tijdvakken tegelijk, elk met een
vaste kleine grootte, zodat de werkelijke uitvoering (spread, slippage, fills)
per opzet en per tijdvak gemeten wordt. Wat zich over veel trades bewijst, kan
later groter; wat verliest, gaat eruit.

Elke opzet heet ``vp:<familie>:<tijdvak>`` en heeft:

* hooguit één open positie tegelijk (per opzet);
* een instap alleen op een nieuw afgesloten bar van zijn eigen tijdvak;
* stop ``STOP_ATR`` x ATR(14) en doel ``RR`` x de stopafstand, beide bij de
  broker; een maximale duur van ``HOLD_BARS`` bars van zijn tijdvak.

Zuivere functies, zonder Home Assistant.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..analysis.signals import Candles
from ..broker.exits import BREAKEVEN_MIN_AFSTAND_USD, DEELWINST_FRACTIE, ExitConfig
from .aggregator import BAR_SECONDS, QuoteAggregator
from .scalping import ScalpConfig, ScalpSignal

VELDPROEF_VERSIE = "veldproef-2.1.0"  # 2.6.3: uitstap in R. 2.6.2: 2.6.2: grootte op risico, max 3 met risico per richting. 2.6.1: 2.6.1: groepsregel per tijdvak. 2.5.9: deelwinst. 2.5.7: winstslot. 2.5.6: verliezende opzetten uit (1.5.0: break-even uiterlijk +1,5 USD)
PREFIX = "vp:"

TIJDVAKKEN = ("1m", "3m", "5m", "15m", "30m")
FAMILIES = (
    "ema_cross", "donchian", "rsi_rev", "bb_fade", "structuur_trend",
    "structuur_hl", "momentum", "pullback", "inside",
)
STOP_ATR = 1.5
#: 2.4.1: IG wees stops van ~0,56 USD af (ATTACHED_ORDER_LEVEL_ERROR, 1m);
#: de stopafstand is minstens dit.
MIN_STOP_USD = 1.0
RR = 2.0
HOLD_BARS = 48
#: Minimaal aantal afgesloten bars voor een besluit.
MIN_BARS = 60
#: Hoeveel bars per tijdvak in het geheugen.
MAX_BARS = 400


#: 2.5.6 (opdracht Ruud: "een opzet uitzetten bij >= 100 trades en t < -2"):
#: een opzet met minstens zoveel gesloten trades en een t-statistiek van het
#: netto resultaat per trade onder deze grens stapt niet meer in.
UITZET_MIN_N = 100
UITZET_MAX_T = -2.0
#: 2.6.1 (Ruud 13-10: "strategy verbeteren"): dezelfde regel per GROEP - alle
#: opzetten van één tijdvak samen, en scalp (incl. turbo) als geheel. Strenger,
#: omdat een groep veel trades telt: n >= 200 en t < -3. Op 13-10 19:00:
#: 1m n=481 t=-8,7; 3m n=257 t=-4,8; scalp n=381 t ~ -9 (gemiddeld -0,8 USD/oz
#: per trade, ongeveer de spread: op 1m/3m en scalp verdient de beweging de
#: kosten niet terug). 5m (n=183), 15m en 30m blijven aan.
GROEP_MIN_N = 200
GROEP_MAX_T = -3.0

#: 2.6.2 (Ruud 13-10: "verliezen per trade zijn te groot"): een veldproeftrade
#: riskeert hooguit dit bedrag (USD) tot de stop. De grootte volgt uit de
#: stopafstand (bij een stop van 9 USD/oz: 11 oz in plaats van 50), met de
#: vaste scalpgrootte als bovengrens. Op 13-10 18:05 verloren vijf trades van
#: 50 oz met stops van 4-9 USD samen 1.506 USD.
MAX_RISICO_PER_TRADE_USD = 100.0
#: 2.6.2: hooguit zoveel veldproefposities per richting die nog risico lopen
#: (stop nog niet op of voorbij de instap). Op 13-10 18:05-18:06 openden vijf
#: shorts binnen een minuut op dezelfde beweging en gingen samen naar de stop.
MAX_POSITIES_MET_RISICO = 3


def grootte_op_risico(units: float, instap: float, stop: float | None) -> float:
    """2.6.2: grootte zodat het verlies tot de stop hooguit
    MAX_RISICO_PER_TRADE_USD is; nooit groter dan ``units``, minstens 1 oz."""
    if stop is None or not instap:
        return units
    afstand = abs(float(instap) - float(stop))
    if afstand <= 0:
        return units
    return max(1.0, min(units, math.floor(MAX_RISICO_PER_TRADE_USD / afstand * 10) / 10))


def loopt_risico(side: str, open_price: float | None, stop: float | None) -> bool:
    """2.6.2: staat de stop nog aan de verlieskant van de instap?"""
    if open_price is None or stop is None:
        return True
    d = 1 if side == "buy" else -1
    return (float(stop) - float(open_price)) * d < 0


def t_statistiek(netto: list[float]) -> float:
    n = len(netto)
    if n < 2:
        return 0.0
    gem = sum(netto) / n
    var = sum((x - gem) ** 2 for x in netto) / (n - 1)
    if var <= 0:
        return 0.0
    return gem / math.sqrt(var / n)


def uitgezette_opzetten(per_opzet: dict[str, list[float]]) -> dict[str, dict]:
    """2.5.6: welke opzetten bewezen verliezen (n >= UITZET_MIN_N en
    t < UITZET_MAX_T, netto per trade). Geeft per opzet n, netto en t."""
    uit: dict[str, dict] = {}
    for naam, netto in per_opzet.items():
        if not is_veldproef(naam) or len(netto) < UITZET_MIN_N:
            continue
        t = t_statistiek(netto)
        if t < UITZET_MAX_T:
            uit[naam] = {"n": len(netto), "netto": round(sum(netto), 2), "t": round(t, 2)}
    # 2.6.1: per tijdvak als groep.
    per_tf: dict[str, list[float]] = {}
    for naam, netto in per_opzet.items():
        if is_veldproef(naam) and naam.count(":") == 2:
            per_tf.setdefault(naam.split(":")[2], []).extend(netto)
    for tf, netto in per_tf.items():
        groep = groep_uitgezet(netto)
        if groep is None:
            continue
        for naam in namen():
            if naam.endswith(":" + tf):
                uit[naam] = {**groep, "groep": tf}
    return uit


def groep_uitgezet(netto: list[float]) -> dict | None:
    """2.6.1: n >= GROEP_MIN_N en t < GROEP_MAX_T -> de hele groep uit."""
    if len(netto) < GROEP_MIN_N:
        return None
    t = t_statistiek(netto)
    if t >= GROEP_MAX_T:
        return None
    return {"n": len(netto), "netto": round(sum(netto), 2), "t": round(t, 2)}


def namen() -> tuple[str, ...]:
    return tuple(f"{PREFIX}{f}:{tf}" for tf in TIJDVAKKEN for f in FAMILIES)


def is_veldproef(naam: str | None) -> bool:
    return bool(naam) and str(naam).startswith(PREFIX)


def ontleed(naam: str) -> tuple[str, str]:
    _, familie, tf = naam.split(":")
    return familie, tf


#: 2.4.10 (Ruud 13-10: "+3 USD en toch uitgestopt"): break-even en volgstop
#: in R (de stopafstand bij instap). De coordinator geeft voor een
#: veldproefpositie R door op de plek van de ATR (zie :func:`r_van`).
#: 2.5.1 (Ruud 13-10: "relatief snel stop naar entry"): 0,5R (was 1R).
BREAKEVEN_R = 0.5
#: 2.6.3: de helft dicht op 1R; winstslot vanaf 1R 50 %, vanaf 2R 70 % (in R).
DEELWINST_R = 1.0
WINSTSLOT_R = ((1.0, 0.5), (2.0, 0.7))
VOLGSTOP_VANAF_R = 1.5
VOLGSTOP_AFSTAND_R = 1.0


def exit_config(naam: str) -> ExitConfig:
    """Stop en doel staan bij de broker. Hier: break-even vanaf 1R, volgstop
    vanaf 1,5R op 1R afstand, en de maximale duur. Geen tijdstop, geen
    deelsluiting. Afstanden in R: de coordinator geeft R door als 'atr'."""
    _, tf = ontleed(naam)
    # 2.6.3 (Ruud 14-10: "gold scalper verbeteren"): alles in R in plaats van
    # vaste USD. Nacht 13/14-10 (58 trades, 5m-30m, stops 4-12 USD): winnaars
    # gemiddeld +18 USD tegen verliezers -89 USD bij 59 % winst. De vaste
    # drempels (break-even +1,5, winstslot vanaf +2, deelwinst vanaf +3 USD)
    # sneden de winnaars af bij ~0,2R terwijl het verlies 1R bleef.
    return ExitConfig(
        breakeven_trigger_atr=BREAKEVEN_R,
        breakeven_min_afstand_usd=BREAKEVEN_MIN_AFSTAND_USD,
        breakeven_trigger_usd=None,
        enable_partial_close=True,
        partial_close_fraction=DEELWINST_FRACTIE,
        partial_close_trigger_atr=DEELWINST_R,
        partial_close_trigger_usd=None,
        winstslot_treden=WINSTSLOT_R,
        winstslot_in_atr=True,
        enable_trailing=True,
        trailing_activate_atr=VOLGSTOP_VANAF_R,
        trailing_distance_atr=VOLGSTOP_AFSTAND_R,
        time_stop_seconds=10 ** 9,
        max_hold_seconds=HOLD_BARS * BAR_SECONDS[tf],
    )


def r_van(open_price, take_profit) -> float:
    """R (stopafstand bij instap) van een veldproefpositie.

    Het doel staat vast op RR x R vanaf de instap en schuift nooit mee (de
    stop wel), dus R = |doel - instap| / RR. Zonder bruikbaar doel de
    minimale stopafstand.
    """
    try:
        r = abs(float(take_profit) - float(open_price)) / RR
    except (TypeError, ValueError):
        return MIN_STOP_USD
    return r if r > 0 else MIN_STOP_USD


# -- indicatoren (op lijsten, laatste waarde) --------------------------------- #

def _ema_reeks(x: list[float], n: int) -> list[float]:
    a = 2.0 / (n + 1.0)
    uit = [x[0]]
    for v in x[1:]:
        uit.append(a * v + (1 - a) * uit[-1])
    return uit


def _atr(h, l, c, n=14) -> list[float]:
    tr = [h[0] - l[0]] + [
        max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))
    ]
    return _ema_reeks(tr, n)


def _rsi(c, n) -> list[float]:
    up = [0.0] + [max(c[i] - c[i - 1], 0.0) for i in range(1, len(c))]
    dn = [0.0] + [max(c[i - 1] - c[i], 0.0) for i in range(1, len(c))]
    eu, ed = _ema_reeks(up, n), _ema_reeks(dn, n)
    return [100 - 100 / (1 + u / max(d, 1e-9)) for u, d in zip(eu, ed)]


def _pivots(h, l, k):
    """Bevestigde toppen en bodems (prijs, index waarop bevestigd)."""
    toppen, bodems = [], []
    for i in range(k, len(h) - k):
        if h[i] == max(h[i - k:i + k + 1]):
            toppen.append((h[i], i + k))
        if l[i] == min(l[i - k:i + k + 1]):
            bodems.append((l[i], i + k))
    return toppen, bodems


@dataclass
class Kenmerken:
    """Wat alle families op één tijdvak nodig hebben, voor de laatste bar."""

    ts: int
    richting: dict = field(default_factory=dict)   # familie -> -1/0/1
    atr: float = 0.0
    slot: float = 0.0
    uitleg: dict = field(default_factory=dict)


def kenmerken(c: Candles) -> Kenmerken | None:
    """Bereken voor elke familie het signaal op de laatste afgesloten bar."""
    n = len(c)
    if n < MIN_BARS:
        return None
    o, h, l, s = c.open, c.high, c.low, c.close
    atr = _atr(h, l, s)
    a = atr[-1]
    e50 = _ema_reeks(s, 50)
    k = Kenmerken(ts=int(c.timestamp[-1]), atr=a, slot=s[-1])
    r = k.richting

    # EMA 9/21: kruising op de laatste bar.
    f, sl = _ema_reeks(s, 9), _ema_reeks(s, 21)
    r["ema_cross"] = 1 if f[-1] > sl[-1] and f[-2] <= sl[-2] else -1 if f[-1] < sl[-1] and f[-2] >= sl[-2] else 0

    # Donchian 40 met trendfilter EMA50.
    hh, ll = max(h[-41:-1]), min(l[-41:-1])
    r["donchian"] = 1 if s[-1] > hh and s[-1] > e50[-1] else -1 if s[-1] < ll and s[-1] < e50[-1] else 0

    # RSI(2) uitersten: terugkeer.
    rs = _rsi(s, 2)[-1]
    r["rsi_rev"] = 1 if rs < 10 else -1 if rs > 90 else 0

    # Bollinger(20, 2.5) uitersten: terugkeer.
    m = sum(s[-20:]) / 20
    sd = math.sqrt(sum((x - m) ** 2 for x in s[-20:]) / 20)
    r["bb_fade"] = 1 if s[-1] < m - 2.5 * sd else -1 if s[-1] > m + 2.5 * sd else 0

    # Marktstructuur (pivots k=3): HH+HL / LH+LL.
    toppen, bodems = _pivots(h, l, 3)
    trend = 0
    if len(toppen) >= 2 and len(bodems) >= 2:
        hh_ = toppen[-1][0] > toppen[-2][0]
        hl_ = bodems[-1][0] > bodems[-2][0]
        trend = 1 if hh_ and hl_ else -1 if (not hh_ and not hl_) else 0
    # trend: breuk van de laatste top (op) of bodem (neer) in de richting.
    st = 0
    if trend == 1 and toppen and s[-1] > toppen[-1][0] >= s[-2]:
        st = 1
    elif trend == -1 and bodems and s[-1] < bodems[-1][0] <= s[-2]:
        st = -1
    r["structuur_trend"] = st
    # hl: zojuist een hogere bodem (lagere top) bevestigd in de structuur.
    sh = 0
    if trend == 1 and bodems and bodems[-1][1] == n - 1:
        sh = 1
    elif trend == -1 and toppen and toppen[-1][1] == n - 1:
        sh = -1
    r["structuur_hl"] = sh
    k.uitleg["structuur"] = {1: "HH+HL", -1: "LH+LL", 0: "range"}[trend]

    # Momentum: 12 bars > 1 x ATR, in de richting van EMA50.
    mo = s[-1] - s[-13]
    r["momentum"] = 1 if mo > a and s[-1] > e50[-1] else -1 if mo < -a and s[-1] < e50[-1] else 0

    # Pullback naar EMA20 in een EMA20/50-trend.
    e20 = _ema_reeks(s, 20)
    r["pullback"] = (
        1 if e20[-1] > e50[-1] and l[-1] <= e20[-1] < s[-1]
        else -1 if e20[-1] < e50[-1] and h[-1] >= e20[-1] > s[-1] else 0
    )

    # Inside bar gevolgd door een uitbraak, met trendfilter.
    ins = h[-2] < h[-3] and l[-2] > l[-3]
    r["inside"] = (
        1 if ins and s[-1] > h[-2] and s[-1] > e50[-1]
        else -1 if ins and s[-1] < l[-2] and s[-1] < e50[-1] else 0
    )
    return k


# -- bars op alle tijdvakken -------------------------------------------------- #

class MeerTijdvakken:
    """Bouwt bars op alle veldproeftijdvakken uit dezelfde koersen."""

    def __init__(self) -> None:
        self.agg = {tf: QuoteAggregator(tf, max_bars=MAX_BARS) for tf in TIJDVAKKEN}
        self._cache: dict[str, Kenmerken | None] = {}

    def voeg_toe(self, prijs: float, moment, tradeable: bool) -> list[str]:
        """Geeft de tijdvakken waarvan zojuist een bar afsloot."""
        klaar = []
        for tf, agg in self.agg.items():
            if agg.add(prijs, moment, tradeable):
                klaar.append(tf)
        return klaar

    def vul(self, tf: str, c: Candles) -> None:
        """Opwarmen met historische bars (archief of recorder)."""
        agg = self.agg[tf]
        rijen = [[int(t), o, h, l, cl, float(v or 1)] for t, o, h, l, cl, v in zip(
            c.timestamp, c.open, c.high, c.low, c.close, c.volume)]
        bestaand = {r[0] for r in agg._closed}
        agg._closed = sorted([r for r in rijen if r[0] not in bestaand] + agg._closed)[-MAX_BARS:]
        self._cache.pop(tf, None)

    def candles(self, tf: str) -> Candles | None:
        agg = self.agg[tf]
        if not agg._closed:
            return None
        return agg.candles()

    def aantal(self) -> dict[str, int]:
        return {tf: len(a._closed) for tf, a in self.agg.items()}

    def kenmerken(self, tf: str) -> Kenmerken | None:
        c = self.candles(tf)
        if c is None or len(c) < MIN_BARS:
            return None
        oud = self._cache.get(tf)
        if oud is not None and oud.ts == int(c.timestamp[-1]):
            return oud
        nieuw = kenmerken(c)
        self._cache[tf] = nieuw
        return nieuw


def hersample(c: Candles, seconden: int) -> Candles:
    """Bars samenvoegen tot een langer tijdvak (bijv. 15m naar 30m)."""
    groepen: dict[int, list[int]] = {}
    for i, t in enumerate(c.timestamp):
        groepen.setdefault(int(t) // seconden * seconden, []).append(i)
    ts = sorted(groepen)
    return Candles(
        timestamp=ts,
        open=[c.open[groepen[k][0]] for k in ts],
        high=[max(c.high[i] for i in groepen[k]) for k in ts],
        low=[min(c.low[i] for i in groepen[k]) for k in ts],
        close=[c.close[groepen[k][-1]] for k in ts],
        volume=[float(len(groepen[k])) for k in ts],
    )


def bars_uit_koersen(punten: list[tuple[float, float]], seconden: int) -> Candles | None:
    """Bars uit (tijd, koers)-punten; de lopende (laatste) bar valt weg."""
    if not punten:
        return None
    rijen: dict[int, list[float]] = {}
    for t, p in sorted(punten):
        k = int(t) // seconden * seconden
        r = rijen.get(k)
        if r is None:
            rijen[k] = [p, p, p, p, 1.0]
        else:
            r[1] = max(r[1], p); r[2] = min(r[2], p); r[3] = p; r[4] += 1
    ts = sorted(rijen)[:-1]
    if not ts:
        return None
    return Candles(
        timestamp=ts, open=[rijen[k][0] for k in ts], high=[rijen[k][1] for k in ts],
        low=[rijen[k][2] for k in ts], close=[rijen[k][3] for k in ts],
        volume=[rijen[k][4] for k in ts],
    )


# -- besluit ------------------------------------------------------------------ #

def evalueer(
    naam: str, bars: MeerTijdvakken, bid: float, ask: float, cfg: ScalpConfig,
    open_position_count: int = 0, seconds_since_last_entry: float = 1e9,
    laatste_bar: dict | None = None, uitgezet=None,
) -> ScalpSignal:
    familie, tf = ontleed(naam)

    def weiger(reden, tekst, richting=0, onderdelen=None):
        return ScalpSignal(direction=richting, score=0.0, confidence=0.0, should_trade=False,
                           reject_reason=reden, reason=tekst,
                           components={"strategie": naam, **(onderdelen or {})})

    if uitgezet and naam in uitgezet:
        info = uitgezet[naam] if isinstance(uitgezet, dict) else {}
        return weiger("opzet_uitgezet",
                      f"{naam}: uitgezet (n={info.get('n', '?')}, t={info.get('t', '?')}, "
                      f"grens n >= {UITZET_MIN_N} en t < {UITZET_MAX_T:g})")
    if ask - bid > cfg.max_spread:
        return weiger("spread_too_wide", f"Spread {ask - bid:.2f} boven {cfg.max_spread:.2f}")
    k = bars.kenmerken(tf)
    if k is None:
        return weiger("insufficient_data", f"{tf}: nog geen {MIN_BARS} bars")
    if k.atr <= 0:
        return weiger("insufficient_data", f"{tf}: geen ATR")
    d = k.richting.get(familie, 0)
    onderdelen = {"tijdvak": tf, "familie": familie, "atr": round(k.atr, 3),
                  "bar": k.ts, **{f"s_{f}": v for f, v in k.richting.items() if f == familie}}
    if d == 0:
        return weiger("geen_signaal", f"{naam}: geen signaal op de bar van {tf}", 0, onderdelen)
    # Eén instap per bar: dezelfde bar levert geen tweede trade op.
    if laatste_bar is not None and laatste_bar.get(naam) == k.ts:
        return weiger("al_gebruikt", f"{naam}: signaal van deze bar al gebruikt", d, onderdelen)

    instap = ask if d == 1 else bid
    afstand = max(STOP_ATR * k.atr, MIN_STOP_USD)
    # 2.4.8 (Ruud 13-10: "scalp moet kort, snel en kleine winsten pakken"):
    # het vaste winstdoel uit de instellingen geldt weer alleen voor scalp. De
    # veldproef houdt RR x de stop, passend bij het tijdvak van de opzet.
    doel = RR * afstand
    doel_tekst = f"doel {RR:g}R"
    sig = ScalpSignal(
        direction=d, score=float(d), confidence=1.0, should_trade=True,
        reject_reason=None, geldig=True,
        reason=(f"Veldproef {familie} op {tf}: {'long' if d == 1 else 'short'}, "
                f"stop {STOP_ATR:g} x ATR ({afstand:.2f}), {doel_tekst}, "
                f"hooguit {HOLD_BARS} bars"),
        stop_loss=round(instap - d * afstand, 2),
        take_profit=round(instap + d * doel, 2),
        expected_move=round(doel, 3),
        expected_cost=round(ask - bid + 2 * cfg.expected_slippage, 3),
        components=onderdelen | {"strategie": naam},
    )
    if open_position_count >= 1:
        sig.should_trade = False
        sig.reject_reason = "max_positions_zelfde_richting"
        sig.reason = f"{naam}: al een positie open"
    return sig
