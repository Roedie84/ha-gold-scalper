"""Onderzoek op de echte (demo)trades: edge-rapport en vooraf geregistreerde
hypotheses (2.7.0, verbeterplan Ruud 14-10, P4-P6).

Het Experiment Lab toetst strategieën op historische bars. Dit is de
tegenhanger voor wat er werkelijk bij de broker gebeurde: elke gesloten trade
met zijn gemeten kosten, zijn afstemming en zijn uitvoering.

Uitgangspunten uit het verbeterplan:

* **Netto expectancy is de maatstaf**, niet het winstpercentage.
* **Gelijktijdige trades zijn geen onafhankelijke waarnemingen.** Trades in
  dezelfde richting die binnen ``CLUSTER_GAT_S`` na de vorige opening in die
  richting openen - over alle strategieën heen - vormen één cluster. De
  t-statistiek gaat over clustertotalen.
* **Segmenten zijn metingen, geen filters.** Sessie, volatiliteit, spread,
  richting, regime: alleen rapporteren. Pas een verschil dat in de
  bevestigingsperiode terugkomt, mag kandidaat worden.
* **Discovery en confirmation gescheiden.** Een hypothese legt vooraf vast op
  welke periode ze ontdekt is en op welke ongeziene periode ze getoetst
  wordt; de uitslag gaat alleen over de bevestigingsperiode.
* **"Geen aantoonbare edge" is een geldige uitkomst.**

Zuiver Python, zonder Home Assistant; invoer zijn rijen uit de tabel
``trades`` als dict.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

ONDERZOEK_VERSIE = 1
#: Trades in dezelfde richting die binnen zoveel seconden na elkaar openen,
#: horen bij één marktbeweging.
CLUSTER_GAT_S = 600
#: Minimaal zoveel clusters voor een uitspraak.
MIN_CLUSTERS = 30
#: t-grens voor "aantoonbaar" (eenzijdig, ongeveer 97,5 %).
T_GRENS = 2.0

SESSIES = (
    # (naam, van_uur_utc, tot_uur_utc)
    ("Azie", 0, 7),
    ("Londen", 7, 12),
    ("Londen/New York", 12, 16),
    ("New York", 16, 21),
    ("Laat", 21, 24),
)


def _ts(waarde) -> datetime | None:
    if not waarde:
        return None
    try:
        t = datetime.fromisoformat(str(waarde).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def sessie(t: datetime) -> str:
    u = t.astimezone(timezone.utc).hour
    for naam, van, tot in SESSIES:
        if van <= u < tot:
            return naam
    return "Laat"


def netto_account(t: dict) -> float:
    """Netto in accountvaluta: de brokerwaarde als die er is, anders netto x fx."""
    v = t.get("net_pnl_account")
    if v is not None:
        return float(v)
    fx = t.get("fx_rate") or 1.0
    return float(t.get("net_pnl") or 0.0) * float(fx)


def bruto_account(t: dict) -> float:
    fx = t.get("fx_rate") or 1.0
    return float(t.get("gross_pnl") or 0.0) * float(fx)


def kosten_account(t: dict) -> float:
    fx = t.get("fx_rate") or 1.0
    return float(t.get("total_cost") or 0.0) * float(fx)


def is_deel(t: dict) -> bool:
    return str(t.get("broker_ticket") or "").endswith("-deel")


def clusters(trades: list[dict], gat_s: int = CLUSTER_GAT_S) -> list[list[dict]]:
    """Per richting: een trade die binnen ``gat_s`` na de vorige opening in
    die richting opent, hoort bij hetzelfde cluster. Deelsluitingen horen
    bij hun eigen trade (zelfde opentijd)."""
    uit: list[list[dict]] = []
    for richting in ("buy", "sell"):
        rij = sorted(
            (t for t in trades if t.get("side") == richting and _ts(t.get("open_time"))),
            key=lambda t: _ts(t["open_time"]),
        )
        huidig: list[dict] = []
        vorige = None
        for t in rij:
            moment = _ts(t["open_time"])
            if vorige is not None and (moment - vorige).total_seconds() > gat_s and huidig:
                uit.append(huidig)
                huidig = []
            huidig.append(t)
            vorige = moment
        if huidig:
            uit.append(huidig)
    return uit


def _t(waarden: list[float]) -> float | None:
    n = len(waarden)
    if n < 2:
        return None
    gem = sum(waarden) / n
    var = sum((x - gem) ** 2 for x in waarden) / (n - 1)
    if var <= 0:
        return None
    return gem / math.sqrt(var / n)


def _max_drawdown(reeks: list[float]) -> float:
    piek = stand = dd = 0.0
    for x in reeks:
        stand += x
        piek = max(piek, stand)
        dd = min(dd, stand - piek)
    return dd


def kengetallen(trades: list[dict]) -> dict:
    """De beoordelingsmaatstaven uit het verbeterplan, in accountvaluta.
    Een deelsluiting telt mee in het resultaat, niet als aparte trade."""
    hoofd = [t for t in trades if not is_deel(t)]
    netto = [netto_account(t) for t in trades]
    bruto = [bruto_account(t) for t in trades]
    kosten = [kosten_account(t) for t in trades]
    cl = clusters(trades)
    per_cluster = [sum(netto_account(t) for t in c) for c in cl]
    winst = [x for x in netto if x > 0]
    verlies = [x for x in netto if x < 0]
    n = len(hoofd)
    som_n, som_b, som_k = sum(netto), sum(bruto), sum(kosten)
    tijd = sorted(trades, key=lambda t: str(t.get("close_time") or ""))
    return {
        "trades": n,
        "clusters": len(cl),
        "netto": round(som_n, 2),
        "netto_per_trade": round(som_n / n, 2) if n else None,
        "netto_per_cluster": round(sum(per_cluster) / len(cl), 2) if cl else None,
        "t_clusters": round(_t(per_cluster), 2) if _t(per_cluster) is not None else None,
        "bruto_per_trade": round(som_b / n, 2) if n else None,
        "kosten_per_trade": round(som_k / n, 2) if n else None,
        "kosten_pct_bruto": round(100 * som_k / som_b, 1) if som_b > 0 else None,
        "profit_factor": round(sum(winst) / -sum(verlies), 2) if verlies else None,
        "gem_winst": round(sum(winst) / len(winst), 2) if winst else None,
        "gem_verlies": round(sum(verlies) / len(verlies), 2) if verlies else None,
        "payoff": (round((sum(winst) / len(winst)) / (-sum(verlies) / len(verlies)), 2)
                   if winst and verlies else None),
        "winst_pct": round(100 * sum(1 for t in hoofd if netto_account(t) > 0) / n, 1) if n else None,
        "max_drawdown": round(_max_drawdown([netto_account(t) for t in tijd]), 2),
        "afgestemd_pct": (round(100 * sum(1 for t in hoofd
                                          if t.get("reconciliation_status") == "reconciled") / n, 1)
                          if n else None),
    }


def _volatiliteit_grenzen(trades: list[dict]) -> tuple[float, float] | None:
    atr = sorted(float(t["entry_atr"]) for t in trades
                 if t.get("entry_atr") not in (None, 0) and not is_deel(t))
    if len(atr) < 9:
        return None
    return atr[len(atr) // 3], atr[2 * len(atr) // 3]


def _spread_grens(trades: list[dict]) -> float | None:
    s = sorted(float(t["open_spread"]) for t in trades if t.get("open_spread") is not None)
    if not s:
        return None
    return s[len(s) // 2] * 1.25


def segmenten(trades: list[dict]) -> dict:
    """Meten, niet filteren: kengetallen per segment."""
    vol = _volatiliteit_grenzen(trades)
    spr = _spread_grens(trades)

    def sleutels(t: dict) -> dict:
        m = _ts(t.get("open_time"))
        uit = {
            "richting": "long" if t.get("side") == "buy" else "short",
            "sessie": sessie(m) if m else "onbekend",
            "regime": t.get("regime") or "onbekend",
            "strategie": _groep(t.get("strategie")),
        }
        a = t.get("entry_atr")
        if vol and a:
            uit["volatiliteit"] = ("laag" if a <= vol[0] else "hoog" if a > vol[1] else "normaal")
        if spr is not None and t.get("open_spread") is not None:
            uit["spread"] = "verhoogd" if float(t["open_spread"]) > spr else "normaal"
        return uit

    groepen: dict[str, dict[str, list[dict]]] = {}
    for t in trades:
        for dim, waarde in sleutels(t).items():
            groepen.setdefault(dim, {}).setdefault(waarde, []).append(t)
    return {
        dim: {w: kengetallen(ts) for w, ts in sorted(waarden.items())}
        for dim, waarden in groepen.items()
    }


def _groep(strategie: str | None) -> str:
    s = str(strategie or "-")
    if s.startswith("vp:"):
        return "veldproef " + s.split(":")[-1]
    return s


def oordeel(k: dict) -> str:
    """'aantoonbare edge' alleen bij genoeg clusters, positieve netto per
    cluster en t boven de grens; anders eerlijk wat er ontbreekt."""
    if (k.get("clusters") or 0) < MIN_CLUSTERS:
        return "te weinig data"
    t = k.get("t_clusters")
    if (k.get("netto_per_cluster") or 0) > 0 and t is not None and t >= T_GRENS:
        return "aantoonbare edge"
    if t is not None and t <= -T_GRENS:
        return "aantoonbaar verliesgevend"
    return "geen aantoonbare edge"


# --- vooraf geregistreerde hypotheses --------------------------------------- #

@dataclass(frozen=True)
class Hypothese:
    hypothesis_id: str
    beschrijving: str
    strategy_version: str
    entry_definition: str
    exit_definition: str
    expected_market_regime: str
    #: Welke trades erbij horen: prefix van ``strategie`` (bv. "vp:") en
    #: tijdvakken (leeg = alle).
    strategie_prefix: str
    tijdvakken: tuple = ()
    richting: str | None = None
    discovery_tot: str = ""        # ISO, exclusief
    confirmation_vanaf: str = ""   # ISO, inclusief
    primary_metric: str = "netto_per_cluster"
    minimum_effect_size: float = 0.0
    rejection_rule: str = ""
    min_clusters: int = MIN_CLUSTERS
    economische_logica: str = ""
    extra: dict = field(default_factory=dict)


#: Vastgelegd op 14-10-2026, vóór de bevestigingsperiode begon. Niet achteraf
#: aanpassen: een nieuwe versie krijgt een nieuw id.
HYPOTHESEN: tuple[Hypothese, ...] = (
    Hypothese(
        hypothesis_id="H-GS-001",
        beschrijving="Veldproef op 15m/30m heeft na alle kosten een positieve netto expectancy per cluster.",
        strategy_version="veldproef-2.1.0",
        entry_definition="45 vaste veldproefopzetten (9 families) op 15m en 30m, instap op een gesloten bar.",
        exit_definition="stop 1,5 x ATR(tf) = 1R, doel 2R, break-even 0,5R, helft dicht op 1R, winstslot 1R/2R, volgstop vanaf 1,5R.",
        expected_market_regime="alle; geen filter",
        strategie_prefix="vp:", tijdvakken=("15m", "30m"),
        discovery_tot="2026-10-14T04:32:00+00:00",
        confirmation_vanaf="2026-10-14T04:32:00+00:00",
        minimum_effect_size=0.0,
        rejection_rule=(f"verworpen als na >= {MIN_CLUSTERS} clusters in de bevestigingsperiode "
                        "de netto per cluster <= 0 is of t < 1,0"),
        economische_logica=("Bewegingen op 15m/30m zijn 3-6 USD/oz tegen ~0,8 USD/oz kosten bij IG; "
                            "op 1m/3m is de beweging van dezelfde orde als de spread."),
    ),
    Hypothese(
        hypothesis_id="H-GS-002",
        beschrijving="Veldproef op 5m heeft na alle kosten een positieve netto expectancy per cluster.",
        strategy_version="veldproef-2.1.0",
        entry_definition="45 vaste veldproefopzetten op 5m.",
        exit_definition="als H-GS-001.",
        expected_market_regime="alle; geen filter",
        strategie_prefix="vp:", tijdvakken=("5m",),
        discovery_tot="2026-10-14T04:32:00+00:00",
        confirmation_vanaf="2026-10-14T04:32:00+00:00",
        rejection_rule=(f"verworpen als na >= {MIN_CLUSTERS} clusters in de bevestigingsperiode "
                        "de netto per cluster <= 0 is of t < 1,0"),
        economische_logica="Tussen 3m (te klein t.o.v. de kosten) en 15m in; open vraag.",
    ),
)


def _hoort_bij(h: Hypothese, t: dict) -> bool:
    s = str(t.get("strategie") or "")
    if not s.startswith(h.strategie_prefix):
        return False
    if h.tijdvakken and s.split(":")[-1] not in h.tijdvakken:
        return False
    if h.richting and t.get("side") != h.richting:
        return False
    return True


def toets(h: Hypothese, trades: list[dict]) -> dict:
    """Discovery en confirmation apart; het oordeel gaat alleen over de
    bevestigingsperiode."""
    eigen = [t for t in trades if _hoort_bij(h, t)]
    ontdekking = [t for t in eigen if str(t.get("open_time") or "") < h.discovery_tot]
    bevestiging = [t for t in eigen if str(t.get("open_time") or "") >= h.confirmation_vanaf]
    kd, kb = kengetallen(ontdekking), kengetallen(bevestiging)
    if kb["clusters"] < h.min_clusters:
        uitslag = "loopt (te weinig clusters)"
    else:
        waarde = kb.get(h.primary_metric) or 0.0
        t = kb.get("t_clusters")
        if waarde <= h.minimum_effect_size or t is None or t < 1.0:
            uitslag = "verworpen"
        elif t >= T_GRENS:
            uitslag = "bevestigd"
        else:
            uitslag = "niet verworpen, niet bevestigd"
    return {
        "hypothesis_id": h.hypothesis_id,
        "uitslag": uitslag,
        "discovery": kd,
        "confirmation": kb,
        "definitie": {k: v for k, v in asdict(h).items() if k != "extra"},
    }


def rapport(trades: list[dict]) -> dict:
    """Het volledige onderzoeksrapport over de gegeven gesloten trades."""
    totaal = kengetallen(trades)
    return {
        "versie": ONDERZOEK_VERSIE,
        "totaal": totaal,
        "oordeel": oordeel(totaal),
        "segmenten": segmenten(trades),
        "hypotheses": [toets(h, trades) for h in HYPOTHESEN],
        "uitleg": ("Netto in accountvaluta; clusters per richting met een gat van "
                   f"{CLUSTER_GAT_S // 60} min; segmenten zijn metingen, geen filters."),
    }


def samenvatting(r: dict) -> dict:
    """Klein genoeg voor een sensorattribuut."""
    t = r.get("totaal") or {}
    return {
        "oordeel": r.get("oordeel"),
        "trades": t.get("trades"),
        "clusters": t.get("clusters"),
        "netto_per_cluster": t.get("netto_per_cluster"),
        "t_clusters": t.get("t_clusters"),
        "kosten_pct_bruto": t.get("kosten_pct_bruto"),
        "afgestemd_pct": t.get("afgestemd_pct"),
        "hypotheses": {h["hypothesis_id"]: h["uitslag"] for h in r.get("hypotheses", [])},
    }
