"""Gegevens voor het broker-dashboard (1.8.0).

Puur Python, zonder Home Assistant-imports: de HTTP-route in ``http.py``
verzamelt de ruwe toestand en deze module maakt er één compact JSON-model van.
Zo is de vorm los te testen.

Alleen lezen. De database wordt geopend met ``mode=ro``: een eigen,
alleen-lezende verbinding naast die van de coordinator. Daardoor kan deze
route per constructie niets schrijven en zit hij de handelslus niet in de weg.

Omvang is begrensd: hooguit ``MAX_CANDLES`` candles, ``MAX_EQUITY_POINTS``
punten equity (gelijkmatig uitgedund over de hele run), ``RECENT_TRADES``
trades in de tabel en ``MARKER_TRADES`` voor de markers in de grafiek.

Niets in dit model beïnvloedt een beslissing. Het richtgetal voor clusters
(``CLUSTERS_RICHTGETAL``) is uitsluitend weergave; de live-poort en het
oordeel staan in ``modes.py`` en ``storage/performance.py``.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Omhoog bij elke wijziging van de sleutels.
BROKER_API_VERSION = 1

MAX_CANDLES = 720
MAX_EQUITY_POINTS = 400
RECENT_TRADES = 20
MARKER_TRADES = 150
#: Weergave: zoveel clusters is een redelijke ondergrens voor een t-toets.
#: Geen poort; het oordeel komt uit storage/performance.py.
CLUSTERS_RICHTGETAL = 30

INSTRUMENT_NAMEN = {
    "CS.D.CFEGOLD.CEA.IP": "Goud",
    "CS.D.CFDGOLD.CFDGC.IP": "Goud",
    "XAU_USD": "Goud",
    "XAUUSD": "Goud",
    "GC=F": "Goud (future)",
}

STATUS_LABELS = {
    "noodstop": "Noodstop",
    "afgestemd_probleem": "Posities kloppen niet",
    "gepauzeerd": "Gepauzeerd",
    "uitgeschakeld": "Handel staat uit",
    "markt_gesloten": "Markt gesloten",
    "opwarmen": "Opwarmen",
    "positie_open": "Positie open",
    "wachtend": "Actief",
    "afwikkelen": "Afwikkelen",
    "koers_verouderd": "Koers verouderd",
    "rooster_wijkt_af": "Rooster wijkt af",
}

#: Toon per status: ok (groen), let (oranje), gevaar (rood), neutraal.
STATUS_TOON = {
    "noodstop": "gevaar",
    "afgestemd_probleem": "gevaar",
    "gepauzeerd": "let",
    "uitgeschakeld": "neutraal",
    "markt_gesloten": "neutraal",
    "opwarmen": "let",
    "positie_open": "ok",
    "wachtend": "ok",
    "afwikkelen": "let",
    "koers_verouderd": "let",
    "rooster_wijkt_af": "let",
}

LIFECYCLE_LABELS = {
    "running": "Draait",
    "draining": "Afwikkelen",
    "stopped": "Gestopt",
    "diverged": "Afwijking",
    "starting": "Opstarten",
}

OORDEEL_LABELS = {
    "no_data": "Nog geen trades",
    "insufficient_data": "Te weinig gegevens",
    "failed": "Geen edge aantoonbaar",
    "passed": "Statistisch houdbaar",
}


# --------------------------------------------------------------- helpers -- #

def _num(value, digits: int | None = None):
    """Eindig getal of None. NaN en oneindig zijn geen geldige JSON."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, digits) if digits is not None else f


def _epoch(value) -> int | None:
    """ISO-tekst of datetime naar Unix-seconden (UTC)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def sluitreden(reden: str | None, gereconcilieerd: str | None = None) -> tuple[str, str]:
    """(kort label, volledige tekst) voor een sluitreden."""
    tekst = gereconcilieerd or reden or ""
    r = tekst.lower()
    if not r:
        return "onbekend", ""
    if r.startswith("take_profit") or r == "doel":
        kort = "Doel"
    elif r.startswith("stop_loss"):
        kort = "Stop"
    elif r.startswith("trailing"):
        kort = "Trailing stop"
    elif r.startswith("maximale positieduur") or r.startswith("max"):
        kort = "Max. duur"
    elif r.startswith("na ") and "atr" in r:
        kort = "Tijdstop"
    elif r.startswith("eerste doel") or r == "partial_close":
        kort = "Deelsluiting"
    elif r in ("handmatig", "manual"):
        kort = "Handmatig"
    elif r.startswith("broker_gesloten"):
        kort = "Door broker"
    elif r == "unknown":
        kort = "Onbekend"
    else:
        kort = tekst[:24]
    return kort, tekst


# ------------------------------------------------------------- database -- #

_TRADE_KOLOMMEN = (
    "id, broker_ticket, side, volume, open_time, open_price, close_time, "
    "close_price, close_reason, reconciled_close_reason, net_pnl, "
    "net_pnl_account, account_currency, total_cost, cost_source, "
    "duration_seconds, stop_loss, take_profit, exit_regime"
)


def open_readonly(path: str | Path) -> sqlite3.Connection:
    """Alleen-lezende verbinding. Schrijven geeft 'attempt to write a readonly database'."""
    uri = f"file:{Path(path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def read_database(path: str | Path, run_id: int) -> dict:
    """Open trades, recente gesloten trades en een uitgedunde equitycurve."""
    conn = open_readonly(path)
    try:
        open_rijen = conn.execute(
            f"SELECT {_TRADE_KOLOMMEN} FROM trades WHERE run_id=? AND close_time IS NULL",
            (run_id,),
        ).fetchall()
        gesloten = conn.execute(
            f"SELECT {_TRADE_KOLOMMEN} FROM trades WHERE run_id=? AND close_time IS NOT NULL "
            "ORDER BY close_time DESC LIMIT ?",
            (run_id, max(RECENT_TRADES, MARKER_TRADES)),
        ).fetchall()
        aantal = conn.execute(
            "SELECT COUNT(*) FROM equity WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        stap = max(1, math.ceil(aantal / MAX_EQUITY_POINTS))
        equity = conn.execute(
            "SELECT ts, balance, equity FROM ("
            "  SELECT ts, balance, equity, ROW_NUMBER() OVER (ORDER BY ts) AS rn"
            "  FROM equity WHERE run_id=?"
            ") WHERE (rn - 1) % ? = 0 OR rn = ? ORDER BY ts",
            (run_id, stap, aantal),
        ).fetchall()
    finally:
        conn.close()
    return {
        "open": [dict(r) for r in open_rijen],
        "gesloten": [dict(r) for r in gesloten],
        "equity": [dict(r) for r in equity],
        "equity_rijen": aantal,
    }


# --------------------------------------------------------------- model --- #

def candles_slice(candles, limit: int = MAX_CANDLES) -> dict | None:
    """Kopie van de laatste ``limit`` candles. In de event-loop aanroepen."""
    if candles is None:
        return None
    try:
        n = min(len(candles.close), len(candles.timestamp), len(candles.open),
                len(candles.high), len(candles.low))
    except AttributeError:
        return None
    if n == 0:
        return None
    start = max(0, n - limit)
    return {
        "t": [int(x) for x in candles.timestamp[start:n]],
        "o": [round(float(x), 3) for x in candles.open[start:n]],
        "h": [round(float(x), 3) for x in candles.high[start:n]],
        "l": [round(float(x), 3) for x in candles.low[start:n]],
        "c": [round(float(x), 3) for x in candles.close[start:n]],
    }


def _tf_seconds(c: dict | None, fallback: str | None) -> int:
    if c and len(c["t"]) >= 3:
        diffs = sorted(b - a for a, b in zip(c["t"][:-1], c["t"][1:]) if b > a)
        if diffs:
            return int(diffs[len(diffs) // 2])
    tabel = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
    return tabel.get(str(fallback or ""), 60)


def _dagverandering(c: dict | None, prijs, tz) -> dict | None:
    """Verandering sinds de eerste candle van vandaag (lokale tijd) in het geheugen."""
    if not c or prijs is None:
        return None
    from datetime import tzinfo

    nu = datetime.now(tz if isinstance(tz, tzinfo) else timezone.utc)
    middernacht = int(nu.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    idx = next((i for i, t in enumerate(c["t"]) if t >= middernacht), None)
    if idx is None:
        idx = 0
    ref = c["o"][idx]
    if not ref:
        return None
    return {
        "ref": ref, "ref_t": c["t"][idx],
        "verandering": round(prijs - ref, 3),
        "pct": round((prijs - ref) / ref * 100.0, 3),
        "hoog": max(c["h"][idx:]), "laag": min(c["l"][idx:]),
        "volledig": idx > 0,
    }


def _position_rows(data: dict, db_open: list[dict], exit_cfg: dict, quote) -> list[dict]:
    per_ticket = {str(r.get("broker_ticket")): r for r in db_open if r.get("broker_ticket")}
    bid = _num(getattr(quote, "bid", None))
    ask = _num(getattr(quote, "ask", None))
    uit = []
    for p in data.get("open_positions") or []:
        ticket = str(getattr(p, "ticket", None) or getattr(p, "id", "") or "")
        side = getattr(p, "side", "buy")
        units = getattr(p, "units", None)
        if units is None:
            units = (getattr(p, "volume", 0) or 0) * 100.0
        instap = _num(getattr(p, "open_price", None))
        koers = bid if side == "buy" else ask
        if koers is None:
            koers = _num(getattr(p, "current_price", None))
        punten = None
        pnl = None
        if koers is not None and instap is not None:
            punten = (koers - instap) if side == "buy" else (instap - koers)
            pnl = punten * float(units)
        db = per_ticket.get(ticket, {})
        geopend = _epoch(getattr(p, "open_time", None)) or _epoch(db.get("open_time"))
        regime = db.get("exit_regime")
        uit.append({
            "ticket": ticket,
            "richting": "long" if side == "buy" else "short",
            "units": _num(units, 2),
            "instap": instap,
            "koers": koers,
            "sl": _num(getattr(p, "stop_loss", None)) or _num(db.get("stop_loss")),
            "tp": _num(getattr(p, "take_profit", None)) or _num(db.get("take_profit")),
            "punten": _num(punten, 3),
            "pnl": _num(pnl, 2),
            "pnl_account": _num(getattr(p, "unrealised_pnl", None), 2),
            "geopend": geopend,
            "regime": regime,
            "tijdstop_s": exit_cfg.get("time_stop_seconds") if regime != "zonder_tijdstop" else None,
            "dode_zone_atr": exit_cfg.get("time_stop_deadzone_atr"),
            "max_duur_s": exit_cfg.get("max_hold_seconds"),
        })
    return uit


def _trade_rows(rijen: list[dict]) -> list[dict]:
    uit = []
    for r in rijen[:RECENT_TRADES]:
        kort, lang = sluitreden(r.get("close_reason"), r.get("reconciled_close_reason"))
        uit.append({
            "ticket": r.get("broker_ticket") or str(r.get("id")),
            "richting": "long" if r.get("side") == "buy" else "short",
            "units": _num((r.get("volume") or 0) * 100.0, 2),
            "open_t": _epoch(r.get("open_time")),
            "sluit_t": _epoch(r.get("close_time")),
            "instap": _num(r.get("open_price")),
            "uitstap": _num(r.get("close_price")),
            "pnl": _num(r.get("net_pnl"), 2),
            "pnl_account": _num(r.get("net_pnl_account"), 2),
            "valuta_account": r.get("account_currency"),
            "kosten": _num(r.get("total_cost"), 2),
            "reden": kort,
            "reden_lang": lang,
            "kostenbron": r.get("cost_source") or "unknown",
            "duur_s": r.get("duration_seconds"),
        })
    return uit


def _markers(rijen: list[dict], vanaf: int | None) -> list[dict]:
    uit = []
    for r in rijen[:MARKER_TRADES]:
        o = _epoch(r.get("open_time"))
        s = _epoch(r.get("close_time"))
        if vanaf is not None and (s or 0) < vanaf:
            continue
        uit.append({
            "o_t": o, "s_t": s,
            "richting": "long" if r.get("side") == "buy" else "short",
            "instap": _num(r.get("open_price")),
            "uitstap": _num(r.get("close_price")),
            "pnl": _num(r.get("net_pnl"), 2),
        })
    uit.reverse()
    return uit


def _alarmen(data: dict, status_code: str) -> dict:
    risk = data.get("risk") or {}
    noodstop = risk.get("state") == "halted"
    redenen = []
    if data.get("koers_verouderd"):
        redenen.append(
            f"koers verouderd ({data.get('koers_leeftijd_seconden')} s oud)"
        )
    if not data.get("candles_consistent", True):
        redenen.append("candlekolommen ongelijk")
    sprong = data.get("saldosprong") or {}
    if sprong.get("actief"):
        redenen.append(sprong.get("reden") or "onverklaarde saldosprong")
    if (data.get("candles") or 0) < 60:
        redenen.append(f"te weinig candles ({data.get('candles') or 0} van 60)")
    return {
        "noodstop": {"actief": noodstop, "reden": risk.get("halt_reason")},
        "dataprobleem": {"actief": bool(redenen), "redenen": redenen},
        "afstemming_probleem": status_code == "afgestemd_probleem",
    }


def build_payload(
    data: dict,
    *,
    symbol: str,
    timeframe: str | None,
    candles: dict | None,
    db: dict | None,
    exit_cfg: dict,
    version: str,
    status: tuple[str, str],
    places_orders: bool,
    uses_real_money: bool,
    tz=None,
) -> dict[str, Any]:
    """Het volledige model voor één verversing."""
    quote = data.get("quote")
    stats = data.get("stats") or {}
    balances = data.get("balances") or {}
    conversion = data.get("conversion") or {}
    db = db or {"open": [], "gesloten": [], "equity": [], "equity_rijen": 0}
    code, detail = status
    prijs = _num(data.get("price"))
    account_valuta = balances.get("account_currency") or conversion.get("account")

    equity_nu = _num(data.get("equity"))
    vloer = _num(balances.get("effective_equity_floor"))
    dag_start = _num((data.get("risk") or {}).get("day_start_balance"))

    lat = (data.get("latency") or {}).get("total") or {}
    exits = data.get("exit_stats") or {}
    recon = data.get("reconciliation") or {}

    modus = data.get("mode")
    if uses_real_money:
        geld = "echt"
    elif places_orders:
        geld = "demo"
    else:
        geld = "papier"

    return {
        "api": BROKER_API_VERSION,
        "versie": version,
        "gegenereerd": int(datetime.now(timezone.utc).timestamp()),
        "instrument": {
            "symbool": symbol,
            "naam": INSTRUMENT_NAMEN.get(symbol, symbol),
            "timeframe": timeframe,
            "tf_s": _tf_seconds(candles, timeframe),
            "valuta": conversion.get("instrument") or "USD",
            "valuta_account": account_valuta,
            # 1.8.1: accountvaluta per eenheid instrumentvaluta, voor de
            # indicatieve live P&L in het paneel. None = onbekend.
            "omrekening": _num(conversion.get("rate"), 6),
        },
        "koers": {
            "bied": _num(getattr(quote, "bid", None)),
            "laat": _num(getattr(quote, "ask", None)),
            "mid": prijs,
            "spread": _num(data.get("spread"), 3),
            "tijd": _epoch(getattr(quote, "time", None)),
            "leeftijd_s": _num(data.get("quote_age_seconds"), 1),
            "atr": _num(data.get("atr"), 3),
            "dag": _dagverandering(candles, prijs, tz),
        },
        "status": {
            "code": code,
            "label": STATUS_LABELS.get(code, code),
            "toon": STATUS_TOON.get(code, "neutraal"),
            "detail": detail,
            "modus": modus,
            "geld": geld,
            "handel_aan": bool(data.get("enabled")),
            "toestand": (data.get("lifecycle") or {}).get("state"),
            "toestand_label": LIFECYCLE_LABELS.get(
                (data.get("lifecycle") or {}).get("state"),
                (data.get("lifecycle") or {}).get("state"),
            ),
            "risico": (data.get("risk") or {}).get("state"),
            "markt_open": data.get("market_open"),
            "koers_verouderd": bool(data.get("koers_verouderd")),
            "signaal": _signaal(data.get("signal")),
            "reden_geen_trade": data.get("reject_reason"),
        },
        "alarm": _alarmen(data, code),
        "candles": candles,
        "posities": _position_rows(data, db["open"], exit_cfg, quote),
        "account": {
            "valuta": account_valuta,
            "equity": equity_nu,
            "saldo": _num(data.get("balance")),
            "dag_pnl": (
                _num(equity_nu - dag_start, 2)
                if equity_nu is not None and dag_start else None
            ),
            "vloer": vloer,
            "vloer_afstand": (
                _num(equity_nu - vloer, 2) if equity_nu is not None and vloer is not None else None
            ),
            "netto": _num(stats.get("net_pnl"), 2),
            "bruto": _num(stats.get("gross_pnl"), 2),
            "kosten": _num(stats.get("total_costs"), 2),
            "kosten_per_trade": _num(stats.get("cost_per_trade"), 3),
            "stats_valuta": conversion.get("instrument") or "USD",
        },
        "equity": {
            "t": [_epoch(r["ts"]) for r in db["equity"]],
            "equity": [_num(r["equity"], 2) for r in db["equity"]],
            "saldo": [_num(r["balance"], 2) for r in db["equity"]],
            "rijen": db.get("equity_rijen", 0),
        },
        "trades": _trade_rows(db["gesloten"]),
        "markers": _markers(db["gesloten"], candles["t"][0] if candles else None),
        "stats": {
            "trades": stats.get("trades") or 0,
            "winst": stats.get("wins"),
            "verlies": stats.get("losses"),
            "clusters": stats.get("clusters") or 0,
            "clusters_richtgetal": CLUSTERS_RICHTGETAL,
            "winst_pct": _num(stats.get("win_rate"), 1),
            "pf": _num(stats.get("profit_factor"), 2),
            "t": _num(stats.get("t_statistic"), 2),
            "t_drempel": 2.0,
            "netto": _num(stats.get("net_pnl"), 2),
            "verwachting": _num(stats.get("expectancy"), 2),
            "max_dd_pct": _num(stats.get("max_drawdown_pct"), 2),
            "oordeel": stats.get("verdict") or "no_data",
            "oordeel_label": OORDEEL_LABELS.get(stats.get("verdict"), stats.get("verdict")),
            "oordeel_tekst": stats.get("verdict_text"),
            "doel_pct": (exits.get("take_profit") or {}).get("pct"),
            "stop_pct": (exits.get("stop_loss") or {}).get("pct"),
            "onbekend_pct": (exits.get("unknown") or {}).get("pct"),
            "exits_noemer": exits.get("noemer"),
            "latency_p50": _num(lat.get("median"), 0),
            "latency_p99": _num(lat.get("p99") if lat.get("p99") is not None else lat.get("p90"), 0),
            "latency_staart": "p99" if lat.get("p99") is not None else ("p90" if lat.get("p90") is not None else None),
            "latency_n": lat.get("samples") or 0,
            "afstemming": (
                None if not recon else
                {"in_orde": bool(recon.get("in_orde")),
                 "afwijkingen": len(recon.get("afwijkingen") or []),
                 "tekst": recon.get("samenvatting")}
            ),
            "poort": (data.get("gate") or {}).get("checks") or {},
            "run": stats.get("run_id"),
        },
    }


def _signaal(signal) -> dict | None:
    if signal is None:
        return None
    richting = getattr(signal, "direction", 0) or 0
    return {
        "richting": "long" if richting > 0 else "short" if richting < 0 else "vlak",
        "score": _num(getattr(signal, "score", None), 2),
        "zekerheid": _num(getattr(signal, "confidence", None), 2),
    }
