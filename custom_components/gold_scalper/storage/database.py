"""SQLite-tradedatabase.

Deze database is de kern van de bewijsfase. Het ontwerpuitgangspunt is dat de
ledger *tegen* de strategie moet kunnen getuigen: elke kostenpost wordt apart
opgeslagen, zodat achteraf te zien is of een winstgevend ogende strategie
alleen winstgevend is omdat de kosten zijn weggemoffeld.

Daarom zijn ``gross_pnl`` en ``net_pnl`` gescheiden kolommen, en worden spread,
commissie, slippage en swap allemaal individueel bewaard. Bij scalping op goud
is de kostenpost bijna altijd groter dan de bruto marge, en dat moet zichtbaar
zijn in plaats van verstopt in één samengevat getal.

Er wordt sqlite3 in een executor gebruikt in plaats van aiosqlite: geen extra
dependency, en de schrijfvolumes zijn klein genoeg dat het niet uitmaakt.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1

MODE_PAPER = "paper"
MODE_LIVE = "live"

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Eén rij per handelssessie/strategieversie, zodat resultaten van
-- verschillende strategieversies nooit op één hoop belanden.
CREATE TABLE IF NOT EXISTS runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    mode              TEXT NOT NULL,
    strategy_version  TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    config_json       TEXT NOT NULL,
    starting_balance  REAL NOT NULL,
    note              TEXT,
    -- Hash van alles wat het handelsgedrag bepaalt. Gelijke vingerafdruk
    -- betekent: dezelfde opzet, dus dezelfde run voortzetten na een herstart.
    fingerprint       TEXT
);
-- De index op fingerprint staat bewust in _migrate() en niet hier: op een
-- bestaande database van vóór deze kolom zou CREATE INDEX falen omdat de
-- kolom pas door de migratie wordt toegevoegd.

CREATE TABLE IF NOT EXISTS trades (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER NOT NULL REFERENCES runs(id),
    mode              TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    side              TEXT NOT NULL CHECK (side IN ('buy','sell')),
    volume            REAL NOT NULL,

    open_time         TEXT NOT NULL,
    open_price        REAL NOT NULL,
    open_mid          REAL NOT NULL,
    open_spread       REAL NOT NULL,
    open_slippage     REAL NOT NULL DEFAULT 0,

    close_time        TEXT,
    close_price       REAL,
    close_mid         REAL,
    close_spread      REAL,
    close_slippage    REAL DEFAULT 0,
    close_reason      TEXT,

    stop_loss         REAL,
    take_profit       REAL,

    commission        REAL NOT NULL DEFAULT 0,
    swap              REAL NOT NULL DEFAULT 0,
    spread_cost       REAL NOT NULL DEFAULT 0,
    slippage_cost     REAL NOT NULL DEFAULT 0,
    total_cost        REAL NOT NULL DEFAULT 0,

    gross_pnl         REAL,
    net_pnl           REAL,
    return_pct        REAL,
    mae               REAL,           -- maximum adverse excursion
    mfe               REAL,           -- maximum favourable excursion
    duration_seconds  INTEGER,

    signal_score      REAL,
    signal_confidence REAL,
    regime            TEXT,
    -- Indicatorwaarden op het instapmoment.
    --
    -- Deze werden berekend, gebruikt voor de beslissing en weggegooid. Zonder
    -- ze is geen enkele correlatieanalyse mogelijk: er is niets om de uitkomst
    -- tegen af te zetten. Een vraag als "welke marktomstandigheden zijn
    -- winstgevend" is dan onbeantwoordbaar, niet vanwege te weinig trades maar
    -- omdat de gegevens ontbreken.
    --
    -- Puur observatie: ze veranderen geen enkele beslissing.
    entry_atr         REAL,
    entry_adx         REAL,
    entry_rsi         REAL,
    entry_ema_dist    REAL,
    entry_trend       REAL,
    entry_momentum    REAL,
    -- Klantsentiment bij de instap, en twee indicatoren die in een
    -- simulatie net boven de nullijn uitkwamen. Uitsluitend vastgelegd om
    -- later te kunnen toetsen, niet om op te handelen.
    entry_sentiment_long REAL,
    -- Waar de kosten vandaan komen: measured (eigen order, werkelijke fill),
    -- calculated (afgeleid uit prijzen, bijvoorbeeld bij een door de broker
    -- gesloten positie), assumed (papersimulatie) of unknown (van vóór dit
    -- veld). Een berekende of aangenomen kostenpost is geen meting.
    cost_source       TEXT,
    -- Sluitreden, niet-destructief. close_reason blijft bestaan voor
    -- bestaande queries; original_close_reason wordt één keer gezet en nooit
    -- overschreven; een afstemming schrijft naar de eigen velden.
    original_close_reason   TEXT,
    -- Uitvoeringsversie waaronder de trade is geopend. Maakt later exact
    -- vast te stellen welke trades onder welk gedrag vielen.
    execution_semantics     INTEGER,
    -- Resultaat in accountvaluta, met de omrekening erbij. Bij een correctie
    -- het bedrag van de broker zelf; anders omgerekend met de koers van dat
    -- moment. Nooit achteraf met één koers gereconstrueerd.
    net_pnl_account         REAL,
    account_currency        TEXT,
    fx_rate                 REAL,
    fx_source               TEXT,
    exit_price_provenance   TEXT,
    fx_timestamp            TEXT,
    reconciled_close_reason TEXT,
    close_reason_source     TEXT,
    close_reason_evidence   TEXT,
    reconciliation_status   TEXT,
    reconciled_at           TEXT,
    reconciliation_source   TEXT,
    entry_williams_r  REAL,
    entry_cci         REAL,
    open_reason       TEXT,
    -- Ticketnummers zijn niet numeriek. IG gebruikt sleutels als
    -- 'DIAAAAYCJETQ7A8'; alleen MetaTrader en OANDA werken met gehele
    -- getallen. De kolom heet nog mt5_ticket uit de eerste versie en is
    -- hernoemd naar broker_ticket.
    broker_ticket     TEXT,

    UNIQUE(broker_ticket, mode)
);

CREATE INDEX IF NOT EXISTS idx_trades_run   ON trades(run_id);
CREATE INDEX IF NOT EXISTS idx_trades_open  ON trades(open_time);
CREATE INDEX IF NOT EXISTS idx_trades_close ON trades(close_time);
CREATE INDEX IF NOT EXISTS idx_trades_mode  ON trades(mode);

-- Elke strategie-evaluatie, ook als er níet is gehandeld. Zonder deze tabel
-- kun je achteraf niet vaststellen of de filters te streng of te los stonden.
CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    ts            TEXT NOT NULL,
    score         REAL NOT NULL,
    confidence    REAL NOT NULL,
    state         TEXT NOT NULL,
    regime        TEXT,
    spread        REAL,
    acted         INTEGER NOT NULL DEFAULT 0,
    reject_reason TEXT,
    detail_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_run ON signals(run_id, ts);

CREATE TABLE IF NOT EXISTS equity (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL REFERENCES runs(id),
    ts             TEXT NOT NULL,
    balance        REAL NOT NULL,
    equity         REAL NOT NULL,
    open_positions INTEGER NOT NULL DEFAULT 0,
    cumulative_cost REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_equity_run ON equity(run_id, ts);

-- Aantekeningen bij een run. Alleen toevoegen, nooit herschrijven: een run
-- waarvan achteraf blijkt dat hij twee gedragingen mengt, wordt gemarkeerd,
-- niet stilzwijgend aangepast.
CREATE TABLE IF NOT EXISTS run_annotations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES runs(id),
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    boundary   TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class Trade:
    """Eén positie, van opening tot sluiting."""

    run_id: int
    mode: str
    symbol: str
    side: str
    volume: float
    open_time: str
    open_price: float
    open_mid: float
    open_spread: float
    open_slippage: float = 0.0

    close_time: str | None = None
    close_price: float | None = None
    close_mid: float | None = None
    close_spread: float | None = None
    close_slippage: float = 0.0
    close_reason: str | None = None

    stop_loss: float | None = None
    take_profit: float | None = None

    commission: float = 0.0
    swap: float = 0.0
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    total_cost: float = 0.0

    gross_pnl: float | None = None
    net_pnl: float | None = None
    return_pct: float | None = None
    mae: float | None = None
    mfe: float | None = None
    duration_seconds: int | None = None

    signal_score: float | None = None
    signal_confidence: float | None = None
    #: Indicatorwaarden op het instapmoment; zie het schema voor het waarom.
    entry_atr: float | None = None
    entry_adx: float | None = None
    entry_rsi: float | None = None
    entry_ema_dist: float | None = None
    entry_trend: float | None = None
    entry_momentum: float | None = None
    entry_sentiment_long: float | None = None
    #: measured / calculated / assumed / unknown
    cost_source: str | None = None
    #: Uitvoeringsversie bij het openen.
    execution_semantics: int | None = None
    #: Resultaat in accountvaluta en de omrekening waarmee het tot stand kwam.
    net_pnl_account: float | None = None
    account_currency: str | None = None
    fx_rate: float | None = None
    fx_source: str | None = None
    #: JSON: oorspronkelijke en broker-uitstapprijs als die is overgenomen
    #: (5.7). De oude waarde blijft zo herleidbaar.
    exit_price_provenance: str | None = None
    fx_timestamp: str | None = None
    #: Eén keer gezet, nooit overschreven.
    original_close_reason: str | None = None
    #: Alleen met bewijs afgeleid: take_profit / stop_loss / unknown.
    reconciled_close_reason: str | None = None
    close_reason_source: str | None = None
    close_reason_evidence: str | None = None
    #: pending / reconciled / unfindable
    reconciliation_status: str | None = None
    reconciled_at: str | None = None
    reconciliation_source: str | None = None
    entry_williams_r: float | None = None
    entry_cci: float | None = None
    regime: str | None = None
    open_reason: str | None = None
    #: Ticketnummer bij de broker. Tekst, niet numeriek: IG gebruikt sleutels
    #: als 'DIAAAAYCJETQ7A8'.
    broker_ticket: str | None = None
    id: int | None = None

    @property
    def is_open(self) -> bool:
        return self.close_time is None


class TradeDatabase:
    """Synchrone SQLite-laag. Aanroepen vanuit HA gaan via een executor job."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ---------------------------------------------------------- #

    def connect(self) -> None:
        self._conn = sqlite3.connect(
            self.path, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()
        # Runs die twee gedragingen mengen markeren - op bewijs, idempotent.
        gemarkeerd = self.detect_mixed_runs()
        if gemarkeerd:
            _LOGGER.warning(
                "%d run(s) gemarkeerd als methodologisch gemengd; zie de "
                "aantekeningen bij de run.", gemarkeerd,
            )
        _LOGGER.debug("Tradedatabase geopend op %s", self.path)

    def _migrate(self) -> None:
        """Voeg kolommen toe die in latere versies zijn bijgekomen.

        Zonder dit zou een bestaande database na een update stukgaan op een
        ontbrekende kolom, en dat is precies de data die je niet kwijt wilt.
        """
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        trade_columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(trades)").fetchall()
        }
        # Hernoemen van mt5_ticket naar broker_ticket, met behoud van de
        # bestaande waarden. SQLite kan een kolomtype niet wijzigen, maar
        # accepteert wel tekst in een INTEGER-kolom, dus kopiëren volstaat.
        if "mt5_ticket" in trade_columns and "broker_ticket" not in trade_columns:
            self._conn.execute("ALTER TABLE trades ADD COLUMN broker_ticket TEXT")
            self._conn.execute(
                "UPDATE trades SET broker_ticket = CAST(mt5_ticket AS TEXT) "
                "WHERE mt5_ticket IS NOT NULL"
            )
            _LOGGER.info("Database bijgewerkt: mt5_ticket -> broker_ticket")
        elif "broker_ticket" not in trade_columns:
            self._conn.execute("ALTER TABLE trades ADD COLUMN broker_ticket TEXT")

        # Indicatorwaarden op het instapmoment. Zonder deze kolommen is geen
        # correlatieanalyse mogelijk: er is niets om de uitkomst tegen af te
        # zetten. Ze komen er per stuk bij, zodat een gedeeltelijk bijgewerkte
        # database niet blijft hangen.
        for kolom in (
            "entry_atr", "entry_adx", "entry_rsi",
            "entry_ema_dist", "entry_trend", "entry_momentum",
            "entry_sentiment_long", "entry_williams_r", "entry_cci",
        ):
            if kolom not in trade_columns:
                self._conn.execute(
                    f"ALTER TABLE trades ADD COLUMN {kolom} REAL"
                )
                _LOGGER.info("Database bijgewerkt: kolom '%s' toegevoegd", kolom)

        if "cost_source" not in trade_columns:
            self._conn.execute("ALTER TABLE trades ADD COLUMN cost_source TEXT")
            _LOGGER.info("Database bijgewerkt: kolom 'cost_source' toegevoegd")
        # Oude gesloten trades: van hun kosten is niet meer vast te stellen of
        # ze gemeten waren. Idempotent: alleen lege velden.
        self._conn.execute(
            "UPDATE trades SET cost_source='unknown' "
            "WHERE cost_source IS NULL AND close_time IS NOT NULL"
        )

        for kolom in (
            "original_close_reason", "reconciled_close_reason",
            "close_reason_source", "close_reason_evidence",
            "reconciliation_status", "reconciled_at", "reconciliation_source",
        ):
            if kolom not in trade_columns:
                self._conn.execute(f"ALTER TABLE trades ADD COLUMN {kolom} TEXT")
                _LOGGER.info("Database bijgewerkt: kolom '%s' toegevoegd", kolom)
        for kolom, soort in (
            ("net_pnl_account", "REAL"), ("account_currency", "TEXT"),
            ("fx_rate", "REAL"), ("fx_source", "TEXT"), ("fx_timestamp", "TEXT"),
            ("exit_price_provenance", "TEXT"),
        ):
            if kolom not in trade_columns:
                self._conn.execute(f"ALTER TABLE trades ADD COLUMN {kolom} {soort}")
        if "execution_semantics" not in trade_columns:
            self._conn.execute(
                "ALTER TABLE trades ADD COLUMN execution_semantics INTEGER"
            )
        self._migrate_close_reasons()
        self._conn.commit()

        for kolom, soort in (("opening_equity_account", "REAL"),
                             ("account_currency", "TEXT")):
            if kolom not in existing:
                self._conn.execute(f"ALTER TABLE runs ADD COLUMN {kolom} {soort}")

        if "fingerprint" not in existing:
            self._conn.execute("ALTER TABLE runs ADD COLUMN fingerprint TEXT")
            _LOGGER.info("Database bijgewerkt: kolom 'fingerprint' toegevoegd")
        # Pas ná de kolomtoevoeging; op een oude database zou dit anders falen.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_fingerprint ON runs(fingerprint)"
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database niet verbonden; roep connect() aan")
        return self._conn

    # -- runs --------------------------------------------------------------- #

    def find_matching_run(self, fingerprint: str) -> dict | None:
        """Zoek de meest recente open run met dezelfde opzet.

        Bestaat omdat elke herstart anders een nieuwe run begon en de teller
        op nul zette. Een bewijsfase van dertig dagen is dan onhaalbaar: één
        Home Assistant-update wist hem.
        """
        row = self.conn.execute(
            "SELECT * FROM runs WHERE fingerprint = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (fingerprint,),
        ).fetchone()
        return dict(row) if row else None

    def update_run_fingerprint(
        self, run_id: int, fingerprint: str, material: dict
    ) -> None:
        """Werk de vingerafdruk bij zonder de run te onderbreken.

        Nodig wanneer een run wordt voortgezet ondanks gewijzigde
        standaardwaarden: zonder bijwerken zou de volgende herstart dezelfde
        vergelijking opnieuw moeten maken.
        """
        row = self.conn.execute(
            "SELECT config_json FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        config = {}
        if row and row["config_json"]:
            try:
                config = json.loads(row["config_json"])
            except (TypeError, ValueError):
                config = {}
        config["fingerprint_material"] = material
        self.conn.execute(
            "UPDATE runs SET fingerprint=?, config_json=? WHERE id=?",
            (fingerprint, json.dumps(config, sort_keys=True, default=str), run_id),
        )
        self.conn.commit()

    def run_totals(self) -> list[dict]:
        """Samenvatting per run, zodat eerdere runs niet uit beeld verdwijnen."""
        rows = self.conn.execute(
            """SELECT r.id, r.started_at, r.ended_at, r.mode, r.strategy_version,
                      r.symbol, r.config_json, r.starting_balance,
                      COUNT(t.id) AS trades,
                      COALESCE(SUM(t.net_pnl), 0) AS net_pnl,
                      COALESCE(SUM(t.total_cost), 0) AS costs
               FROM runs r
               LEFT JOIN trades t ON t.run_id = r.id AND t.close_time IS NOT NULL
               GROUP BY r.id ORDER BY r.id DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def start_run(
        self,
        mode: str,
        strategy_version: str,
        symbol: str,
        config: dict,
        starting_balance: float,
        note: str | None = None,
        fingerprint: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO runs
               (started_at, mode, strategy_version, symbol, config_json,
                starting_balance, note, fingerprint)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                _now(),
                mode,
                strategy_version,
                symbol,
                json.dumps(config, sort_keys=True, default=str),
                starting_balance,
                note,
                fingerprint,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def latest_open_run(self) -> dict | None:
        """De meest recente run die nog niet is afgesloten."""
        row = self.conn.execute(
            "SELECT * FROM runs WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def end_run(self, run_id: int) -> None:
        self.conn.execute("UPDATE runs SET ended_at=? WHERE id=?", (_now(), run_id))
        self.conn.commit()

    def get_run(self, run_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- trades ------------------------------------------------------------- #

    def insert_trade(self, trade: Trade) -> int:
        data = asdict(trade)
        data.pop("id", None)
        columns = ", ".join(data)
        placeholders = ", ".join("?" for _ in data)
        cur = self.conn.execute(
            f"INSERT INTO trades ({columns}) VALUES ({placeholders})",
            tuple(data.values()),
        )
        self.conn.commit()
        trade.id = int(cur.lastrowid)
        return trade.id

    def update_trade(self, trade: Trade) -> None:
        if trade.id is None:
            raise ValueError("Trade heeft geen id; eerst insert_trade aanroepen")
        data = asdict(trade)
        data.pop("id")
        # De oorspronkelijke sluitreden wordt één keer gezet en daarna nooit
        # meer overschreven - ook niet door een object dat hem leeg heeft.
        # Eerst overschreef een correctie de sluitreden, en ging verloren of
        # een positie op zijn stop of zijn doel sloot.
        assignments = ", ".join(
            "original_close_reason=COALESCE(original_close_reason, ?)"
            if k == "original_close_reason" else f"{k}=?"
            for k in data
        )
        self.conn.execute(
            f"UPDATE trades SET {assignments} WHERE id=?",
            (*data.values(), trade.id),
        )
        self.conn.commit()

    def mark_for_recheck(self, run_id: int) -> int:
        """Zet door de broker gesloten trades opnieuw op 'te controleren'.

        Raakt alleen de afstemmingsstatus. De oorspronkelijke sluitreden en de
        bedragen blijven staan tot een nieuwe afstemming ze met bewijs
        bijwerkt; eerst werd de sluitreden zelf overschreven.
        """
        cur = self.conn.execute(
            "UPDATE trades SET reconciliation_status='pending' "
            "WHERE run_id=? AND close_time IS NOT NULL AND ("
            " close_reason LIKE 'broker_gesloten%' "
            " OR reconciliation_status IN ('reconciled','unfindable'))",
            (run_id,),
        )
        self.conn.commit()
        return cur.rowcount

    def estimated_trades(self, run_id: int) -> list[Trade]:
        """Trades waarvan de uitstapprijs nog bij de broker opgezocht moet worden."""
        rijen = self.conn.execute(
            "SELECT * FROM trades WHERE run_id=? AND close_time IS NOT NULL AND ("
            " reconciliation_status='pending' "
            " OR (reconciliation_status IS NULL "
            "     AND close_reason='broker_gesloten_geschat')) "
            "ORDER BY close_time DESC LIMIT 50",
            (run_id,),
        ).fetchall()
        return [self._row_to_trade(r) for r in rijen]

    def recent_close_times(self, limit: int = 500) -> list[str]:
        """Sluitmomenten van de recentste gesloten trades, over alle runs.

        Alleen voor de diagnose van het transactieoverzicht van de broker:
        dat bevat ook trades uit eerdere runs.
        """
        rijen = self.conn.execute(
            "SELECT close_time FROM trades WHERE close_time IS NOT NULL "
            "ORDER BY close_time DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [r[0] for r in rijen]

    def open_trades(self, run_id: int) -> list[Trade]:
        rows = self.conn.execute(
            "SELECT * FROM trades WHERE run_id=? AND close_time IS NULL", (run_id,)
        ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def open_trades_by_tickets(self, tickets) -> list[Trade]:
        """Open trades met deze tickets, in welke run ook.

        Voor posities die over een runwissel heen openstaan: de trade hoort bij
        de run waarin hij opende, maar moet beheerd en afgerekend blijven tot
        zijn positie bij de broker dicht is.
        """
        lijst = [str(t) for t in tickets if t]
        if not lijst:
            return []
        vraagtekens = ",".join("?" * len(lijst))
        rows = self.conn.execute(
            f"SELECT * FROM trades WHERE close_time IS NULL "
            f"AND broker_ticket IN ({vraagtekens})",
            lijst,
        ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def repair_broker_settlement_usd(self) -> int:
        """Herreken het dollarresultaat van trades die de broker afrekende.

        Tot 5.6.2 werd het eurobedrag van de broker teruggerekend met de
        middenkoers in plaats van met de koers die de broker zelf gebruikte en
        die bij de trade staat (``fx_rate``). Idempotent: alleen rijen die meer
        dan een halve cent afwijken, worden bijgewerkt. Geeft het aantal.
        """
        rijen = self.conn.execute(
            "SELECT id, net_pnl, net_pnl_account, fx_rate, total_cost FROM trades "
            "WHERE fx_source='broker_settlement' AND fx_rate > 0 "
            "AND net_pnl_account IS NOT NULL AND close_time IS NOT NULL"
        ).fetchall()
        aantal = 0
        with self.conn:
            for rij in rijen:
                usd = round(rij["net_pnl_account"] / rij["fx_rate"], 4)
                if rij["net_pnl"] is not None and abs(rij["net_pnl"] - usd) <= 0.005:
                    continue
                self.conn.execute(
                    "UPDATE trades SET net_pnl=?, gross_pnl=? WHERE id=?",
                    (usd, round(usd + (rij["total_cost"] or 0.0), 4), rij["id"]),
                )
                aantal += 1
        return aantal

    def closed_trades(self, run_id: int | None = None, limit: int | None = None) -> list[Trade]:
        query = "SELECT * FROM trades WHERE close_time IS NOT NULL"
        params: list[Any] = []
        if run_id is not None:
            query += " AND run_id=?"
            params.append(run_id)
        query += " ORDER BY close_time ASC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        return [self._row_to_trade(r) for r in self.conn.execute(query, params).fetchall()]

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> Trade:
        fields = {f for f in Trade.__dataclass_fields__}
        return Trade(**{k: row[k] for k in row.keys() if k in fields})

    # -- signals ------------------------------------------------------------ #

    def log_signal(
        self,
        run_id: int,
        score: float,
        confidence: float,
        state: str,
        regime: str | None,
        spread: float | None,
        acted: bool,
        reject_reason: str | None = None,
        detail: dict | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO signals
               (run_id, ts, score, confidence, state, regime, spread, acted,
                reject_reason, detail_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                _now(),
                score,
                confidence,
                state,
                regime,
                spread,
                int(acted),
                reject_reason,
                json.dumps(detail, default=str) if detail else None,
            ),
        )
        self.conn.commit()

    def signal_stats(self, run_id: int) -> dict:
        """Hoeveel signalen zijn er geweest, en waarom is er niet gehandeld."""
        total = self.conn.execute(
            "SELECT COUNT(*) c, SUM(acted) a FROM signals WHERE run_id=?", (run_id,)
        ).fetchone()
        rejects = self.conn.execute(
            """SELECT reject_reason, COUNT(*) c FROM signals
               WHERE run_id=? AND acted=0 AND reject_reason IS NOT NULL
               GROUP BY reject_reason ORDER BY c DESC""",
            (run_id,),
        ).fetchall()
        return {
            "evaluations": total["c"] or 0,
            "acted": total["a"] or 0,
            "rejections": {r["reject_reason"]: r["c"] for r in rejects},
        }

    # -- equity ------------------------------------------------------------- #

    def _migrate_close_reasons(self) -> None:
        """Historische sluitredenen niet-destructief vastleggen. Idempotent.

        * Gewone trades: de oorspronkelijke reden is de huidige.
        * Gecorrigeerde trades: de oorspronkelijke reden was een schatting die
          is overschreven, en is dus onbekend. Een doeltreffer alleen met
          bewijs (uitstap binnen 0,01 van het doel); een stoptreffer nooit,
          want de stop kan verouderd zijn.
        * Geschatte en onvindbare trades krijgen hun afstemmingsstatus.
        """
        from ..learning.exit_stats import derive_close_reason

        c = self._conn
        c.execute(
            "UPDATE trades SET original_close_reason=close_reason "
            "WHERE original_close_reason IS NULL AND close_time IS NOT NULL "
            "AND close_reason IS NOT NULL "
            "AND close_reason NOT IN ('broker_gesloten_gecorrigeerd')"
        )
        c.execute(
            "UPDATE trades SET reconciliation_status='pending' "
            "WHERE reconciliation_status IS NULL "
            "AND close_reason='broker_gesloten_geschat'"
        )
        c.execute(
            "UPDATE trades SET reconciliation_status='unfindable' "
            "WHERE reconciliation_status IS NULL "
            "AND close_reason='broker_gesloten_onvindbaar'"
        )
        rijen = c.execute(
            "SELECT id, close_price, take_profit, stop_loss FROM trades "
            "WHERE close_reason='broker_gesloten_gecorrigeerd' "
            "AND original_close_reason IS NULL"
        ).fetchall()
        for rij in rijen:
            afgeleid = derive_close_reason(
                rij["close_price"], rij["take_profit"], rij["stop_loss"],
                stop_trusted=False,
            )
            c.execute(
                "UPDATE trades SET original_close_reason='unknown', "
                "reconciled_close_reason=?, close_reason_source=?, "
                "close_reason_evidence=?, reconciliation_status='reconciled', "
                "reconciliation_source='broker_transactions' WHERE id=?",
                (afgeleid.reden, afgeleid.bron, afgeleid.bewijs, rij["id"]),
            )

    def account_drawdown(self, run_id: int) -> dict:
        """Grootste daling van de equity in accountvaluta, van piek tot dal.

        De drawdown werd berekend door dollarresultaten op te tellen bij de
        ingestelde startbalans van 10.000 - twee valuta en een verouderde basis
        in één getal. Deze leest de equity zoals de broker hem meldt.
        """
        rij = self.conn.execute(
            "SELECT MAX(piek - equity) AS dd, "
            "MAX(CASE WHEN piek > 0 THEN (piek - equity) / piek END) AS ddpct, "
            "COUNT(*) AS n FROM ("
            " SELECT equity, MAX(equity) OVER (ORDER BY id) AS piek "
            " FROM equity WHERE run_id=?)",
            (run_id,),
        ).fetchone()
        n = int(rij["n"] or 0)
        return {
            "max_drawdown": round(float(rij["dd"] or 0.0), 2) if n else None,
            "max_drawdown_pct": (
                round(float(rij["ddpct"] or 0.0) * 100, 2) if n else None
            ),
            "points": n,
            "basis": "account_equity",
        }

    def set_run_opening(self, run_id: int, equity: float | None,
                        currency: str | None) -> None:
        """Equity bij de start van de run vastleggen - één keer.

        Een tweede aanroep verandert niets: de opening van een run is een
        feit, geen instelling.
        """
        self.conn.execute(
            "UPDATE runs SET opening_equity_account=?, account_currency=? "
            "WHERE id=? AND opening_equity_account IS NULL",
            (equity, currency, run_id),
        )
        self.conn.commit()

    def annotate_run(self, run_id: int, kind: str, text: str,
                     boundary: str | None = None) -> bool:
        """Aantekening toevoegen; één per soort per run. Idempotent."""
        bestaat = self.conn.execute(
            "SELECT 1 FROM run_annotations WHERE run_id=? AND kind=?",
            (run_id, kind),
        ).fetchone()
        if bestaat:
            return False
        self.conn.execute(
            "INSERT INTO run_annotations (run_id, kind, text, boundary, created_at) "
            "VALUES (?,?,?,?,?)",
            (run_id, kind, text, boundary, _now()),
        )
        self.conn.commit()
        return True

    def run_annotations(self, run_id: int) -> list[dict]:
        rijen = self.conn.execute(
            "SELECT kind, text, boundary, created_at FROM run_annotations "
            "WHERE run_id=? ORDER BY id", (run_id,),
        ).fetchall()
        return [dict(r) for r in rijen]

    def detect_mixed_runs(self) -> int:
        """Markeer runs waarin trades elkaar overlappen.

        Met een limiet van één positie kunnen trades elkaar niet overlappen.
        Deden ze dat toch, dan gold de limiet niet - het kenmerk van de fout
        die 5.3.2 oploste, toen open posities als gesloten werden gezien.
        Zo'n run meet twee gedragingen door elkaar.

        Op bewijs, niet op een versienummer: van oude trades is de versie niet
        vastgelegd. De grens is het sluitmoment van de laatste overlappende
        trade; dat is een bovengrens voor de fix, geen exact tijdstip.
        """
        gemarkeerd = 0
        for run in self.conn.execute("SELECT id FROM runs").fetchall():
            trades = self.conn.execute(
                "SELECT open_time, close_time FROM trades WHERE run_id=? "
                "AND close_time IS NOT NULL AND broker_ticket NOT LIKE '%-deel' "
                "ORDER BY open_time", (run["id"],),
            ).fetchall()
            overlap, grens, laatste_sluiting = 0, None, None
            for t in trades:
                if laatste_sluiting and t["open_time"] < laatste_sluiting:
                    overlap += 1
                    grens = max(grens or "", t["close_time"])
                if not laatste_sluiting or t["close_time"] > laatste_sluiting:
                    laatste_sluiting = t["close_time"]
            if overlap and self.annotate_run(
                run["id"], "methodologisch_gemengd",
                f"{overlap} trade(s) openden terwijl een andere nog openstond. "
                "Met een limiet van één positie kan dat niet: tot aan de grens "
                "gold de limiet niet en werkte het exitbeheer niet (fout "
                "opgelost in 5.3.2). Trades vóór en na de grens meten "
                "verschillend gedrag. De grens is een bovengrens, geen exact "
                "tijdstip.",
                boundary=grens,
            ):
                gemarkeerd += 1
        return gemarkeerd

    def ledger_costs(self, run_id: int) -> dict:
        """Kosten van de gesloten trades van een run, uit het ledger.

        De bron voor de kostenlijn in het rapport. Eerst kwam die uit de
        papersimulatie, en in demomodus bestaat die niet: de lijn stond dan
        altijd op nul, terwijl er wel degelijk kosten waren.
        """
        rij = self.conn.execute(
            "SELECT COALESCE(SUM(total_cost), 0) AS som, COUNT(*) AS n, "
            "SUM(CASE WHEN cost_source='measured' THEN 1 ELSE 0 END) AS gemeten, "
            "SUM(CASE WHEN cost_source='calculated' THEN 1 ELSE 0 END) AS berekend, "
            "SUM(CASE WHEN cost_source='assumed' THEN 1 ELSE 0 END) AS aangenomen, "
            "SUM(CASE WHEN cost_source IS NULL OR cost_source='unknown' "
            "THEN 1 ELSE 0 END) AS onbekend "
            "FROM trades WHERE run_id=? AND close_time IS NOT NULL",
            (run_id,),
        ).fetchone()
        return {
            "total": float(rij["som"] or 0.0),
            "trades": int(rij["n"] or 0),
            "measured": int(rij["gemeten"] or 0),
            "calculated": int(rij["berekend"] or 0),
            "assumed": int(rij["aangenomen"] or 0),
            "unknown": int(rij["onbekend"] or 0),
        }

    def record_equity(
        self,
        run_id: int,
        balance: float,
        equity: float,
        open_positions: int,
        cumulative_cost: float,
    ) -> None:
        self.conn.execute(
            """INSERT INTO equity
               (run_id, ts, balance, equity, open_positions, cumulative_cost)
               VALUES (?,?,?,?,?,?)""",
            (run_id, _now(), balance, equity, open_positions, cumulative_cost),
        )
        self.conn.commit()

    def equity_curve(self, run_id: int, limit: int = 5000) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ts, balance, equity, cumulative_cost FROM equity "
            "WHERE run_id=? ORDER BY ts ASC LIMIT ?",
            (run_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- housekeeping ------------------------------------------------------- #

    def prune(self, keep_days: int = 365) -> int:
        """Verwijder oude signaalregels. Trades blijven altijd staan — die zijn
        het bewijsmateriaal en mogen nooit stilzwijgend verdwijnen."""
        cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
        cur = self.conn.execute("DELETE FROM signals WHERE ts < ?", (cutoff_iso,))
        self.conn.commit()
        return cur.rowcount
