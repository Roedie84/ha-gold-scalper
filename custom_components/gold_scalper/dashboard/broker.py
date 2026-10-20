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

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

#: Omhoog bij elke wijziging van de sleutels.
BROKER_API_VERSION = 1

MAX_CANDLES = 720
MAX_EQUITY_POINTS = 400
RECENT_TRADES = 20
MARKER_TRADES = 150
#: 2.13.0: signalen per setup in de grafiek - zo ver terug, en hooguit zoveel.
SIGNAAL_UREN = 24
MAX_SIGNALEN = 600
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
    elif r == "tijdslimiet" or (r.startswith("na ") and "atr" in r):
        kort = "Tijdstop"
    elif r == "eigen_exit":
        kort = "Eigen exit"
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
    "duration_seconds, stop_loss, take_profit, exit_regime, run_id"
)

#: 1.10.0: optioneel, alleen als de kolom er al is (een database die nog
#: niet door deze versie is geopend, heeft ze niet).
_TRADE_KOLOMMEN_EXTRA = ("looptijd_s", "close_reason_source", "strategie", "open_reason",
                         "stop_gewijzigd_op", "stop_wijzigingen", "stop_reden")


def _kolommen(conn: sqlite3.Connection) -> str:
    try:
        bestaand = {r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()}
    except sqlite3.Error:
        bestaand = set()
    extra = [k for k in _TRADE_KOLOMMEN_EXTRA if k in bestaand]
    return ", ".join([_TRADE_KOLOMMEN, *extra])


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
        kolommen = _kolommen(conn)
        # 2.4.11: ook open trades uit eerdere runs (meegenomen over een
        # runwissel of herstart). Zonder die rijen kende het paneel hun
        # strategie, stop en doel niet en toonde het de primaire strategie.
        open_rijen = conn.execute(
            f"SELECT {kolommen} FROM trades WHERE close_time IS NULL AND ("
            "run_id=? OR (broker_ticket IS NOT NULL AND broker_ticket != '' "
            "AND open_time >= datetime('now', '-2 days')))",
            (run_id,),
        ).fetchall()
        # 2.9.4: ook trades van eerdere runs die de laatste 2 dagen sloten.
        # Een optiewijziging start een nieuwe run; posities uit de vorige run
        # lopen door en sluiten later. Alleen de lopende run tonen liet de
        # lijst stilstaan terwijl er wel trades sloten (Pepperstone 14-10).
        gesloten = conn.execute(
            f"SELECT {kolommen} FROM trades WHERE close_time IS NOT NULL AND ("
            "run_id=? OR close_time >= datetime('now', '-2 days')) "
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
        reeks = _reeks(conn, run_id)
        # 2.13.0: signalen met een richting (per setup) voor de grafiek.
        vanaf = (datetime.now(timezone.utc) - timedelta(hours=SIGNAAL_UREN)).isoformat(timespec="seconds")
        try:
            signalen = conn.execute(
                "SELECT ts, state, acted, reject_reason, detail_json FROM signals "
                "WHERE run_id=? AND ts >= ? AND state != 'flat' ORDER BY ts DESC LIMIT ?",
                (run_id, vanaf, MAX_SIGNALEN * 20),
            ).fetchall()
        except sqlite3.Error:
            signalen = []
        # 2.5.9: genomen deelwinst per open positie (rij "<ticket>-deel").
        delen = {
            str(t)[: -len("-deel")]: (n or 0.0, a)
            for t, n, a in conn.execute(
                "SELECT broker_ticket, SUM(net_pnl), SUM(net_pnl_account) FROM trades "
                "WHERE broker_ticket LIKE '%-deel' AND close_time IS NOT NULL "
                "AND open_time >= datetime('now', '-2 days') GROUP BY broker_ticket"
            )
        } if "net_pnl_account" in kolommen else {
            str(t)[: -len("-deel")]: (n or 0.0, None)
            for t, n in conn.execute(
                "SELECT broker_ticket, SUM(net_pnl) FROM trades "
                "WHERE broker_ticket LIKE '%-deel' AND close_time IS NOT NULL "
                "AND open_time >= datetime('now', '-2 days') GROUP BY broker_ticket"
            )
        }
    finally:
        conn.close()
    return {
        "delen": delen,
        "open": [dict(r) for r in open_rijen],
        "gesloten": [{**dict(r), "eerdere_run": dict(r).get("run_id") not in (None, run_id)}
                     for r in gesloten],
        "equity": [dict(r) for r in equity],
        "equity_rijen": aantal,
        "reeks": reeks,
        "signalen": [dict(r) for r in signalen],
    }


def _reeks(conn: sqlite3.Connection, run_id: int) -> dict | None:
    """2.4.5: resultaat sinds de start van de huidige strategie.

    Elke instellingswijziging start een nieuwe run, en een positie telt bij
    de run die haar opende. "Netto run" mist daardoor de posities van eerdere
    runs die nu pas sluiten. De reeks = de aaneengesloten runs (zelfde modus,
    zelfde strategieversie) tot en met de huidige; daarover alle gesloten
    trades plus de saldoverandering bij de broker als controle."""
    try:
        runs = conn.execute(
            "SELECT id, started_at, mode, strategy_version FROM runs WHERE id<=? "
            "ORDER BY id DESC LIMIT 500",
            (run_id,),
        ).fetchall()
        if not runs or runs[0]["id"] != run_id:
            return None
        huidig = runs[0]
        ids = []
        for r in runs:
            if r["mode"] != huidig["mode"] or r["strategy_version"] != huidig["strategy_version"]:
                break
            ids.append(r["id"])
        start = runs[len(ids) - 1]["started_at"]
        plek = ",".join("?" * len(ids))
        som = conn.execute(
            f"SELECT COUNT(*), SUM(net_pnl), SUM(gross_pnl), SUM(total_cost) FROM trades "
            f"WHERE run_id IN ({plek}) AND close_time IS NOT NULL AND net_pnl IS NOT NULL",
            ids,
        ).fetchone()
        open_n = conn.execute(
            f"SELECT COUNT(*) FROM trades WHERE run_id IN ({plek}) AND close_time IS NULL",
            ids,
        ).fetchone()[0]
        eerste = conn.execute(
            f"SELECT balance FROM equity WHERE run_id IN ({plek}) AND balance IS NOT NULL "
            "ORDER BY ts LIMIT 1",
            ids,
        ).fetchone()
        laatste = conn.execute(
            f"SELECT balance FROM equity WHERE run_id IN ({plek}) AND balance IS NOT NULL "
            "ORDER BY ts DESC LIMIT 1",
            ids,
        ).fetchone()
    except sqlite3.Error:
        return None
    return {
        "start": start,
        "runs": len(ids),
        "strategie": huidig["strategy_version"],
        "trades": som[0] or 0,
        "netto": som[1],
        "bruto": som[2],
        "kosten": som[3],
        "open": open_n,
        "saldo_verschil": (
            laatste[0] - eerste[0] if eerste is not None and laatste is not None else None
        ),
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


def _position_rows(data: dict, db_open: list[dict], exit_cfg: dict, quote,
                   delen: dict | None = None) -> list[dict]:
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
        strategie = _strategie(db, data)
        daghandel = strategie == "daghandel"
        vp_duur = _vp_max_duur_s(strategie)
        uit.append({
            "strategie": strategie,
            # 2.2.1: bijkoop (pyramide) van een andere positie.
            "bijkoop": str(db.get("open_reason") or "").startswith("pyramide van "),
            # 2.5.3: geopend door turbo-scalp (live koers).
            "turbo": str(db.get("open_reason") or "").startswith("turbo"),
            "ticket": ticket,
            "richting": "long" if side == "buy" else "short",
            # 2.18.0: crypto (0,0021 BTC) verdwijnt bij twee decimalen.
            "units": _num(units, 2 if abs(float(units or 0)) >= 100 else 8),
            "instap": instap,
            "koers": koers,
            "sl": _num(getattr(p, "stop_loss", None)) or _num(db.get("stop_loss")),
            "tp": _num(getattr(p, "take_profit", None)) or _num(db.get("take_profit")),
            # 2.4.11: laatste stopverplaatsing (break-even/volgstop).
            "sl_gewijzigd": _epoch(db.get("stop_gewijzigd_op")),
            "sl_wijzigingen": db.get("stop_wijzigingen") or 0,
            "sl_reden": db.get("stop_reden"),
            "punten": _num(punten, 3),
            "pnl": _num(pnl, 2),
            "pnl_account": _num(getattr(p, "unrealised_pnl", None), 2),
            # 2.5.9: al genomen deelwinst (instrumentvaluta), en in
            # accountvaluta als de broker die meldde.
            "gerealiseerd": _num((delen or {}).get(ticket, (None, None))[0], 2),
            "gerealiseerd_account": _num((delen or {}).get(ticket, (None, None))[1], 2),
            "geopend": geopend,
            "regime": regime,
            # 2.1.0: daghandel heeft geen tijdstop; "max. duur" is dan de tijd
            # tot 20:45 UTC, wanneer hij dicht gaat.
            "tijdstop_s": None if daghandel or vp_duur is not None
            or regime == "zonder_tijdstop"
            else exit_cfg.get("time_stop_seconds"),
            "dode_zone_atr": None if daghandel or vp_duur is not None
            else exit_cfg.get("time_stop_deadzone_atr"),
            "max_duur_s": _sluit_daghandel_s(geopend) if daghandel
            else vp_duur if vp_duur is not None
            else exit_cfg.get("max_hold_seconds"),
        })
    return uit


def _trade_rows(rijen: list[dict]) -> list[dict]:
    uit = []
    for r in rijen[:RECENT_TRADES]:
        kort, lang = sluitreden(r.get("close_reason"), r.get("reconciled_close_reason"))
        # 1.10.0: looptijd apart; een achteraf uit de afstemming ingevulde
        # reden is als zodanig gemarkeerd.
        looptijd = r.get("looptijd_s")
        if looptijd is not None and lang:
            lang = f"{lang} (na {looptijd}s)"
        bron = "afstemming" if r.get("close_reason_source") == "afstemming" else None
        if bron:
            lang = f"{lang} - achteraf ingevuld uit de afstemming met de broker"
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
            "reden_bron": bron,
            "looptijd_s": looptijd,
            "kostenbron": r.get("cost_source") or "unknown",
            "duur_s": r.get("duration_seconds"),
            "run": r.get("run_id"),
            "eerdere_run": bool(r.get("eerdere_run")),
        })
    return uit


def _strategie(rij: dict, data: dict) -> str:
    """2.1.0: strategie van een trade; zonder eigen veld die van de run."""
    eigen = rij.get("strategie")
    if eigen in ("daghandel", "scalp"):
        return eigen
    # 2.4.8: veldproefopzetten (vp:<familie>:<tf>) niet meer als de primaire
    # strategie tonen; bij "alles" stonden ze als "Daghandel" in het paneel.
    if isinstance(eigen, str) and eigen.startswith("vp:"):
        return eigen
    return data.get("primaire_strategie") or "scalp"


def _vp_max_duur_s(strategie: str) -> int | None:
    """2.4.8: maximale duur van een veldproefopzet (HOLD_BARS bars), anders None."""
    if not str(strategie or "").startswith("vp:"):
        return None
    try:
        from ..strategy import veldproef

        return int(veldproef.exit_config(strategie).max_hold_seconds)
    except Exception:  # noqa: BLE001 - alleen weergave
        return None


def _sluit_daghandel_s(geopend: int | None) -> int | None:
    """Seconden van de opening tot 20:45 UTC op die dag (daghandel)."""
    if geopend is None:
        return None
    from datetime import datetime, timezone

    o = datetime.fromtimestamp(geopend, timezone.utc)
    sluit = o.replace(hour=20, minute=45, second=0, microsecond=0)
    return max(0, int((sluit - o).total_seconds()))


def _open_markers(rijen: list[dict], data: dict) -> list[dict]:
    """2.1.0: instapmarkers van de open posities (nog zonder uitstap)."""
    uit = []
    for r in rijen:
        uit.append({
            "o_t": _epoch(r.get("open_time")), "s_t": None,
            "richting": "long" if r.get("side") == "buy" else "short",
            "instap": _num(r.get("open_price")), "uitstap": None, "pnl": None,
            "strategie": _strategie(r, data), "open": True,
        })
    return uit


def _markers(rijen: list[dict], vanaf: int | None, data: dict | None = None) -> list[dict]:
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
            "strategie": _strategie(r, data or {}),
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


def _reeks_payload(r: dict | None) -> dict | None:
    if not r:
        return None
    return {
        "start": _epoch(r.get("start")),
        "runs": r.get("runs") or 0,
        "strategie": r.get("strategie"),
        "trades": r.get("trades") or 0,
        "netto": _num(r.get("netto"), 2),
        "bruto": _num(r.get("bruto"), 2),
        "kosten": _num(r.get("kosten"), 2),
        "open": r.get("open") or 0,
        "saldo_verschil": _num(r.get("saldo_verschil"), 2),
    }


def signaal_markers(rijen: list[dict] | None) -> list[dict]:
    """2.13.0: één marker per setup per signaalbar, oudste eerst.

    Een veldproefsignaal blijft zijn hele bar staan en wordt elke cyclus
    gelogd; per (setup, bar, richting) telt het eerste moment, en gehandeld
    als het in één van die rondes werd uitgevoerd.
    """
    uit: dict[tuple, dict] = {}
    for r in rijen or []:
        try:
            detail = json.loads(r.get("detail_json") or "{}") or {}
        except (TypeError, ValueError):
            detail = {}
        strategie = detail.get("strategie")
        if not strategie:
            continue
        # 2.13.1: signalen van een uitgezette opzet zijn geen kandidaat;
        # op 15m gaven ze kolommen van tientallen ruitjes per candle.
        if str(r.get("reject_reason") or "").startswith("opzet_uitgezet"):
            continue
        richting = "long" if r.get("state") == "buy" else "short" if r.get("state") == "sell" else None
        t = _epoch(r.get("ts"))
        if richting is None or t is None:
            continue
        sleutel = (strategie, detail.get("bar") or t // 60, richting)
        m = uit.get(sleutel)
        gehandeld = bool(r.get("acted"))
        if m is None:
            uit[sleutel] = {"t": t, "strategie": strategie, "richting": richting,
                            "gehandeld": gehandeld, "reden": None if gehandeld else r.get("reject_reason")}
        else:
            m["t"] = min(m["t"], t)
            if gehandeld:
                m["gehandeld"] = True
                m["reden"] = None
    rij = sorted(uit.values(), key=lambda m: m["t"])
    return rij[-MAX_SIGNALEN:]


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
    candles_fijn: dict | None = None,
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
    # 1.9.4: daglimiet over dezelfde basis als RiskManager.can_open (de
    # kleinste van dagstart en startbalans), op het slechtste van saldo en
    # equity. Zo laten dashboard en noodrem hetzelfde percentage zien.
    risico = data.get("risk") or {}
    dag_basis = _num(risico.get("risicobasis"))
    saldo_nu = _num(data.get("balance"))
    slechtste = (
        min(x for x in (equity_nu, saldo_nu) if x is not None)
        if equity_nu is not None or saldo_nu is not None else None
    )
    dag_verlies_pct = (
        _num((dag_start - slechtste) / dag_basis * 100.0, 2)
        if dag_start and dag_basis and slechtste is not None else None
    )
    vloer_budget = (
        _num(balances.get("opening_equity_account") - vloer, 2)
        if vloer is not None and balances.get("opening_equity_account") else None
    )

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
            # 2.4.9: per strategie bij alles/combinatie.
            "redenen_per_strategie": data.get("redenen_per_strategie") or {},
        },
        "alarm": _alarmen(data, code),
        "candles": candles,
        "candles_fijn": candles_fijn or {},
        "posities": _position_rows(data, db["open"], exit_cfg, quote, db.get("delen")),
        # 1.9.0: telling per richting en de limiet; netting als hij optrad.
        "posities_telling": _telling(data),
        "netting": data.get("netting"),
        # 1.9.0: schaduwtrades - gesimuleerd, telt nergens mee.
        "schaduw": _schaduw(data.get("schaduw"), conversion.get("instrument") or "USD"),
        # 1.9.5: tijdstopvarianten - gesimuleerd, alleen meting.
        "varianten": _varianten(data.get("tijdstopvarianten")),
        "account": {
            "valuta": account_valuta,
            "equity": equity_nu,
            "saldo": _num(data.get("balance")),
            "dag_pnl": (
                _num(equity_nu - dag_start, 2)
                if equity_nu is not None and dag_start else None
            ),
            "dag_verlies_pct": dag_verlies_pct,
            "daglimiet_pct": _num(risico.get("max_daily_loss_pct"), 2),
            "daglimiet": _num(risico.get("daglimiet_bedrag"), 2),
            "vloer": vloer,
            # 1.9.4: totale verliesruimte van de run (opening min vloer); de
            # meter in het paneel rekent hierover in plaats van over de equity.
            "vloer_budget": vloer_budget,
            "vloer_toegepast": balances.get("applied"),
            "vloer_afstand": (
                _num(equity_nu - vloer, 2) if equity_nu is not None and vloer is not None else None
            ),
            "netto": _num(stats.get("net_pnl"), 2),
            "bruto": _num(stats.get("gross_pnl"), 2),
            "kosten": _num(stats.get("total_costs"), 2),
            "kosten_per_trade": _num(stats.get("cost_per_trade"), 3),
            "stats_valuta": conversion.get("instrument") or "USD",
            # 2.4.5: hoofdgetal "Netto sinds start" (alle runs van deze strategie).
            "reeks": _reeks_payload(db.get("reeks")),
        },
        "equity": {
            "t": [_epoch(r["ts"]) for r in db["equity"]],
            "equity": [_num(r["equity"], 2) for r in db["equity"]],
            "saldo": [_num(r["balance"], 2) for r in db["equity"]],
            "rijen": db.get("equity_rijen", 0),
        },
        "trades": _trade_rows(db["gesloten"]),
        "markers": _markers(db["gesloten"], candles["t"][0] if candles else None, data)
        + _open_markers(db["open"], data),
        # 2.13.0: signalen per setup voor de grafiek.
        "signalen": signaal_markers(db.get("signalen")),
        # 2.1.0: strategiekeuze voor de grafieklegenda.
        "strategie": data.get("strategie_keuze") or data.get("primaire_strategie"),
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
            "stop_winst_pct": (exits.get("stop_winst") or {}).get("pct"),
            "stop_verlies_pct": (exits.get("stop_verlies") or {}).get("pct"),
            "onbekend_pct": (exits.get("unknown") or {}).get("pct"),
            "exits_noemer": exits.get("noemer"),
            # 2.13.4: omgekeerde trades (gesloten door de omkeer, of op de
            # stop die de omkeer vastzette).
            "omkeer_gesloten_pct": (exits.get("omkeer_gesloten") or {}).get("pct"),
            "omkeer_vastgezet_pct": (exits.get("omkeer_vastgezet") or {}).get("pct"),
            "omkeer_vastgezet_winst_pct": (exits.get("omkeer_vastgezet") or {}).get("winst_pct"),
            "omkeer_n": (exits.get("omkeer") or {}).get("n"),
            "omkeer_winst_pct": (exits.get("omkeer_winst") or {}).get("pct"),
            "omkeer_verlies_pct": (exits.get("omkeer_verlies") or {}).get("pct"),
            "omkeer_winst_netto": _num((exits.get("omkeer_winst") or {}).get("netto"), 2),
            "omkeer_verlies_netto": _num((exits.get("omkeer_verlies") or {}).get("netto"), 2),
            "omkeer_netto": _num((exits.get("omkeer") or {}).get("netto"), 2),
            "latency_p50": _num(lat.get("median"), 0),
            "latency_p99": _num(lat.get("p99") if lat.get("p99") is not None else lat.get("p90"), 0),
            "latency_staart": "p99" if lat.get("p99") is not None else ("p90" if lat.get("p90") is not None else None),
            "latency_n": lat.get("samples") or 0,
            "afstemming": (
                None if not recon else
                {"in_orde": bool(recon.get("in_orde")),
                 "afwijkingen": len(recon.get("afwijkingen") or []),
                 "tekst": recon.get("samenvatting"),
                 # 1.10.0: tijdstip, en of het de bewaarde uitkomst van
                 # vóór een herstart is.
                 "moment": recon.get("moment"),
                 "hersteld": bool(recon.get("hersteld"))}
            ),
            "poort": (data.get("gate") or {}).get("checks") or {},
            "run": stats.get("run_id"),
        },
    }


def _telling(data: dict) -> dict:
    pr = data.get("posities_per_richting") or {}
    posities = data.get("open_positions") or []
    if not pr:
        long_ = sum(1 for p in posities if getattr(p, "side", "buy") == "buy")
        pr = {"long": long_, "short": len(posities) - long_, "limiet": None}
    return {"long": pr.get("long", 0), "short": pr.get("short", 0),
            "limiet": pr.get("limiet")}


def _schaduw(stats: dict | None, valuta: str) -> dict:
    """Compact model voor het paneel 'Schaduwtrades (gesimuleerd)'."""
    s = stats or {}
    return {
        "trades": s.get("trades") or 0,
        "open": s.get("open") or 0,
        "vervallen": s.get("vervallen") or 0,
        "winst_pct": _num(s.get("winst_pct"), 1),
        "pf": _num(s.get("profit_factor"), 2),
        "netto": _num(s.get("netto"), 2),
        "kosten": _num(s.get("kosten"), 2),
        "verwachting": _num(s.get("verwachting"), 2),
        "clusters": s.get("clusters") or 0,
        "t": _num(s.get("t_statistiek"), 2),
        "t_basis": s.get("t_basis"),
        "per_reden": s.get("per_reden") or {},
        "valuta": valuta,
    }


def _varianten(stats: dict | None) -> dict | None:
    """Compact model voor de tabel 'Tijdstopvarianten' (1.9.5)."""
    if not stats:
        return None
    gepaard = stats.get("gepaard_tegen_240") or {}
    rijen = []
    for naam, v in (stats.get("per_variant") or {}).items():
        g = gepaard.get(naam) or {}
        rijen.append({
            "variant": naam,
            "trades": v.get("trades") or 0,
            "netto": _num(v.get("netto"), 2),
            "per_trade": _num(v.get("netto_per_trade"), 2),
            "winst_pct": _num(v.get("winst_pct"), 1),
            "pf": _num(v.get("profit_factor"), 2),
            "doel_pct": _num(v.get("doel_pct"), 1),
            "tijdstop_pct": _num(v.get("tijdstop_pct"), 1),
            "duur_s": _num(v.get("gem_duur_s"), 0),
            "verschil_blok": _num(g.get("verschil_per_blok"), 2),
            "t_blok": _num(g.get("t_blokken"), 2),
        })
    ov = stats.get("overeenkomst") or {}
    return {
        "blokken": stats.get("blokken") or 0,
        "open": stats.get("open") or 0,
        "oordeel": stats.get("oordeel"),
        "overeenkomst_pct": _num(ov.get("overeenkomst_pct"), 1),
        "vergeleken": ov.get("vergeleken") or 0,
        "rijen": rijen,
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


def mand_payload(leden: list[dict], overzicht: dict | None) -> dict:
    """2.18.0: de Bitvavo-mand in één oogopslag: alle open posities van alle
    markten in één tabel, en per markt een regel.

    ``leden``: per markt ``{"markt", "data", "status": (code, tekst)}``, met
    ``data`` de laatste cyclus van die markt (of None als hij nog opstart).
    """
    posities = []
    markten = []
    info = {r.get("markt"): r for r in (overzicht or {}).get("per_markt") or []}
    for lid in leden:
        markt = lid.get("markt")
        data = lid.get("data") or {}
        quote = data.get("quote")
        rijen = _position_rows(data, [], {}, quote) if data else []
        for r in rijen:
            r["markt"] = markt
        posities.extend(rijen)
        code, tekst = lid.get("status") or (None, None)
        i = info.get(markt) or {}
        stats = data.get("stats") or {}
        markten.append({
            "markt": markt,
            "koers": _num(data.get("price")),
            "spread_pct": _num(i.get("spread_pct"), 3),
            "volume_24u": _num(i.get("volume_24u"), 0),
            "open": len(rijen),
            "pnl_open": _num(sum(r["pnl"] or 0 for r in rijen), 2) if rijen else None,
            "netto": _num(stats.get("net_pnl"), 2),
            "trades": stats.get("trades"),
            "status": code or ("opstarten" if not data else None),
            "status_label": STATUS_LABELS.get(code, code or "Opstarten"),
            "status_toon": STATUS_TOON.get(code, "neutraal"),
            "toelichting": tekst,
            "weigering": i.get("weigering"),
            "uitfaseren": bool(i.get("uitfaseren")),
        })
    posities.sort(key=lambda r: r.get("geopend") or 0, reverse=True)
    totaal_open = sum(r["pnl"] or 0 for r in posities)
    netto = [m["netto"] for m in markten if m["netto"] is not None]
    return {
        "posities": posities,
        "markten": markten,
        "open": len(posities),
        "max_posities": (overzicht or {}).get("max_posities"),
        "pnl_open": _num(totaal_open, 2),
        "netto": _num(sum(netto), 2) if netto else None,
        "herzien_om": (overzicht or {}).get("herzien_om"),
        "fout": (overzicht or {}).get("fout"),
    }
