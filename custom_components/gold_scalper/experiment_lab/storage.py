"""Opslag van het Experiment Lab, in een eigen databasebestand.

``gold_scalper_lab.db`` staat los van de tradedatabase en het barsarchief:

* een fout in een Lab-migratie kan de tradedatabase niet raken;
* het Lab heeft fysiek geen schrijfpad naar trades;
* een beschadigde Lab-database houdt de integratie niet tegen (``try_open``).

De regels van de toestandsmachine worden in de database afgedwongen met
triggers die **gegenereerd worden uit** ``models.ALLOWED`` en
``models.LOCKED_AT_REGISTRATION``. Python en SQLite volgen daardoor precies
dezelfde lijst: wat Python weigert, weigert de database ook - ook bij
rechtstreekse SQL.

Journaalmodus: de standaard (DELETE), niet WAL. WAL is op een lokale schijf
betrouwbaar, maar niet op elke opslag waarop Home Assistant kan draaien; zonder
aantoonbare noodzaak kiest het Lab de veilige standaard.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from decimal import Decimal

from .datasets import (
    HASH_VERSION, CanonicalBar, DatasetSpec, PreparedDataset, dataset_hash,
)
from .metrics import REQUIRED_METRICS, TRADE_FIELDS
from .segments import KINDS, SegmentPlan, normalize_family_id
from .models import (
    IllegalTransition,
    ALLOWED, LOCKED_AT_REGISTRATION, REQUIRED_FOR_REGISTRATION, TERMINAL,
    Experiment, Status, canonical_json, check_transition, config_hash,
)

LAB_SCHEMA_VERSION = 9

#: De vergrendelde velden zoals ze in schema 1 waren. Een uitgerolde migratie
#: verandert nooit meer; schema 2 vervangt de trigger door een nieuwe.
LOCKED_V1 = (
    "name", "type", "hypothesis", "expected_effect", "primary_metric",
    "secondary_metrics", "evaluation_method", "hypothesis_family_id",
    "software_version", "strategy_version", "execution_semantics_version",
    "config_hash", "reproduced_from",
)


class SealedTestError(PermissionError):
    """TEST-resultaten zijn alleen via ``open_test_result`` te lezen."""


class LabDatabaseError(RuntimeError):
    """De Lab-database is niet bruikbaar. Raakt nooit de handel."""


def _nu() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sql_lijst(waarden) -> str:
    return ",".join(f"'{w.value if hasattr(w, 'value') else w}'" for w in waarden)


def _overgangsvoorwaarde() -> str:
    """SQL-voorwaarde die waar is voor precies de toegestane overgangen."""
    delen = [
        f"(OLD.status = '{van.value}' AND NEW.status IN ({_sql_lijst(naar)}))"
        for van, naar in ALLOWED.items() if naar
    ]
    return " OR ".join(delen)


def _schema_v1() -> list[str]:
    terminaal = _sql_lijst(TERMINAL)
    vergrendeld = " OR ".join(
        f"NEW.{veld} IS NOT OLD.{veld}" for veld in LOCKED_V1
    )
    verplicht = " OR ".join(
        f"COALESCE(TRIM(NEW.{veld}), '') = ''" for veld in REQUIRED_FOR_REGISTRATION
    )
    return [
        """CREATE TABLE IF NOT EXISTS lab_meta (
               key TEXT PRIMARY KEY, value TEXT NOT NULL)""",

        f"""CREATE TABLE IF NOT EXISTS experiments (
               id                          INTEGER PRIMARY KEY AUTOINCREMENT,
               name                        TEXT NOT NULL,
               description                 TEXT NOT NULL DEFAULT '',
               type                        TEXT NOT NULL,
               status                      TEXT NOT NULL
                   CHECK (status IN ({_sql_lijst(Status)})),
               hypothesis                  TEXT NOT NULL DEFAULT '',
               expected_effect             TEXT NOT NULL DEFAULT '',
               primary_metric              TEXT NOT NULL DEFAULT '',
               secondary_metrics           TEXT NOT NULL DEFAULT '[]',
               evaluation_method           TEXT NOT NULL DEFAULT '',
               hypothesis_family_id        TEXT NOT NULL DEFAULT '',
               software_version            TEXT NOT NULL DEFAULT '',
               strategy_version            TEXT NOT NULL DEFAULT '',
               execution_semantics_version INTEGER,
               config_hash                 TEXT NOT NULL DEFAULT '',
               created_at                  TEXT NOT NULL,
               registered_at               TEXT,
               locked_at                   TEXT,
               started_at                  TEXT,
               finished_at                 TEXT,
               reproduced_from             INTEGER
                   REFERENCES experiments(id) ON DELETE RESTRICT,
               error                       TEXT
           )""",

        """CREATE TABLE IF NOT EXISTS experiment_parameters (
               id            INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id INTEGER NOT NULL
                   REFERENCES experiments(id) ON DELETE CASCADE,
               role          TEXT NOT NULL
                   CHECK (role IN ('baseline','challenger','candidate')),
               config_json   TEXT NOT NULL,
               config_hash   TEXT NOT NULL
           )""",

        """CREATE TABLE IF NOT EXISTS experiment_annotations (
               id            INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id INTEGER NOT NULL
                   REFERENCES experiments(id) ON DELETE RESTRICT,
               kind          TEXT NOT NULL,
               text          TEXT NOT NULL,
               created_at    TEXT NOT NULL
           )""",

        "CREATE INDEX IF NOT EXISTS idx_exp_status ON experiments(status)",
        "CREATE INDEX IF NOT EXISTS idx_exp_family ON experiments(hypothesis_family_id)",

        # --- toestandsmachine in de database -------------------------------- #
        """CREATE TRIGGER IF NOT EXISTS exp_insert_draft
           BEFORE INSERT ON experiments WHEN NEW.status <> 'draft'
           BEGIN SELECT RAISE(ABORT, 'een experiment begint als draft'); END""",

        f"""CREATE TRIGGER IF NOT EXISTS exp_transition
           BEFORE UPDATE OF status ON experiments
           WHEN NEW.status IS NOT OLD.status AND NOT ({_overgangsvoorwaarde()})
           BEGIN SELECT RAISE(ABORT, 'illegale statusovergang'); END""",

        f"""CREATE TRIGGER IF NOT EXISTS exp_terminal_immutable
           BEFORE UPDATE ON experiments WHEN OLD.status IN ({terminaal})
           BEGIN SELECT RAISE(ABORT, 'afgesloten experiment is onveranderlijk'); END""",

        f"""CREATE TRIGGER IF NOT EXISTS exp_hypothesis_locked
           BEFORE UPDATE ON experiments
           WHEN OLD.status <> 'draft' AND ({vergrendeld})
           BEGIN SELECT RAISE(ABORT, 'hypothese en provenance zijn vergrendeld'); END""",

        f"""CREATE TRIGGER IF NOT EXISTS exp_registration_complete
           BEFORE UPDATE OF status ON experiments
           WHEN NEW.status = 'registered' AND ({verplicht})
           BEGIN SELECT RAISE(ABORT, 'registreren vraagt een volledige hypothese'); END""",

        """CREATE TRIGGER IF NOT EXISTS exp_delete_only_draft
           BEFORE DELETE ON experiments WHEN OLD.status <> 'draft'
           BEGIN SELECT RAISE(ABORT, 'alleen een draft mag worden verwijderd'); END""",

        # --- parameters: alleen te wijzigen zolang het experiment draft is --- #
        """CREATE TRIGGER IF NOT EXISTS par_insert_draft
           BEFORE INSERT ON experiment_parameters
           WHEN (SELECT status FROM experiments WHERE id = NEW.experiment_id) <> 'draft'
           BEGIN SELECT RAISE(ABORT, 'parameters zijn vergrendeld'); END""",
        """CREATE TRIGGER IF NOT EXISTS par_update_draft
           BEFORE UPDATE ON experiment_parameters
           WHEN (SELECT status FROM experiments WHERE id = OLD.experiment_id) <> 'draft'
           BEGIN SELECT RAISE(ABORT, 'parameters zijn vergrendeld'); END""",
        """CREATE TRIGGER IF NOT EXISTS par_delete_draft
           BEFORE DELETE ON experiment_parameters
           WHEN (SELECT status FROM experiments WHERE id = OLD.experiment_id) <> 'draft'
           BEGIN SELECT RAISE(ABORT, 'parameters zijn vergrendeld'); END""",

        # --- aantekeningen: alleen toevoegen ---------------------------------- #
        """CREATE TRIGGER IF NOT EXISTS ann_no_update
           BEFORE UPDATE ON experiment_annotations
           BEGIN SELECT RAISE(ABORT, 'aantekeningen zijn alleen toe te voegen'); END""",
        """CREATE TRIGGER IF NOT EXISTS ann_no_delete
           BEFORE DELETE ON experiment_annotations
           BEGIN SELECT RAISE(ABORT, 'aantekeningen zijn alleen toe te voegen'); END""",
    ]


_DATASET_KOLOMMEN = (
    "symbol", "timeframe", "source", "start_ts", "end_ts", "bar_count", "hash",
    "hash_version", "created_at", "timezone", "instrument_precision",
    "precision_origin", "quality_status", "quality_json",
)


def _schema_v2() -> list[str]:
    """Datasets als onveranderlijke snapshots, en de koppeling aan experimenten."""
    identiteit = " OR ".join(f"NEW.{k} IS NOT OLD.{k}" for k in _DATASET_KOLOMMEN)
    vergrendeld = " OR ".join(
        f"NEW.{veld} IS NOT OLD.{veld}" for veld in LOCKED_AT_REGISTRATION
    )
    return [
        """CREATE TABLE IF NOT EXISTS datasets (
               id                   INTEGER PRIMARY KEY AUTOINCREMENT,
               symbol               TEXT NOT NULL,
               timeframe            TEXT NOT NULL,
               source               TEXT NOT NULL,
               start_ts             INTEGER NOT NULL,
               end_ts               INTEGER NOT NULL,
               bar_count            INTEGER NOT NULL CHECK (bar_count > 0),
               hash                 TEXT NOT NULL,
               hash_version         INTEGER NOT NULL,
               created_at           TEXT NOT NULL,
               timezone             TEXT NOT NULL CHECK (timezone = 'UTC'),
               instrument_precision INTEGER NOT NULL,
               precision_origin     TEXT NOT NULL,
               quality_status       TEXT NOT NULL
                   CHECK (quality_status IN ('OK','WARNING','BLOCKED')),
               quality_json         TEXT NOT NULL,
               sealed               INTEGER NOT NULL DEFAULT 0 CHECK (sealed IN (0,1)),
               UNIQUE (hash, hash_version)
           )""",
        # Prijzen als geheel getal: prijs x 10^precisie. Exact, geen zwevende komma.
        """CREATE TABLE IF NOT EXISTS dataset_bars (
               dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE RESTRICT,
               ts         INTEGER NOT NULL,
               open       INTEGER NOT NULL,
               high       INTEGER NOT NULL,
               low        INTEGER NOT NULL,
               close      INTEGER NOT NULL,
               volume     TEXT,
               source     TEXT NOT NULL,
               bar_status TEXT NOT NULL,
               PRIMARY KEY (dataset_id, ts)
           ) WITHOUT ROWID""",
        """CREATE TABLE IF NOT EXISTS dataset_requests (
               id           INTEGER PRIMARY KEY AUTOINCREMENT,
               dataset_id   INTEGER NOT NULL REFERENCES datasets(id) ON DELETE RESTRICT,
               requested_at TEXT NOT NULL,
               origin       TEXT NOT NULL,
               reused       INTEGER NOT NULL
           )""",
        "ALTER TABLE experiments ADD COLUMN dataset_id INTEGER "
        "REFERENCES datasets(id) ON DELETE RESTRICT",

        # --- onveranderlijkheid van datasets ------------------------------- #
        # De enige toegestane wijziging: verzegelen (sealed 0 -> 1) met verder
        # identieke inhoud. Daarna niets meer.
        f"""CREATE TRIGGER IF NOT EXISTS ds_update
           BEFORE UPDATE ON datasets
           WHEN OLD.sealed = 1 OR NEW.sealed <> 1 OR {identiteit}
           BEGIN SELECT RAISE(ABORT, 'een dataset is onveranderlijk'); END""",
        """CREATE TRIGGER IF NOT EXISTS ds_delete
           BEFORE DELETE ON datasets
           BEGIN SELECT RAISE(ABORT, 'een dataset wordt niet verwijderd'); END""",
        """CREATE TRIGGER IF NOT EXISTS bars_insert_sealed
           BEFORE INSERT ON dataset_bars
           WHEN (SELECT sealed FROM datasets WHERE id = NEW.dataset_id) = 1
           BEGIN SELECT RAISE(ABORT, 'een verzegelde dataset krijgt geen bars meer'); END""",
        """CREATE TRIGGER IF NOT EXISTS bars_no_update
           BEFORE UPDATE ON dataset_bars
           BEGIN SELECT RAISE(ABORT, 'bars van een dataset zijn onveranderlijk'); END""",
        """CREATE TRIGGER IF NOT EXISTS bars_no_delete
           BEFORE DELETE ON dataset_bars
           BEGIN SELECT RAISE(ABORT, 'bars van een dataset zijn onveranderlijk'); END""",
        """CREATE TRIGGER IF NOT EXISTS req_no_update
           BEFORE UPDATE ON dataset_requests
           BEGIN SELECT RAISE(ABORT, 'aanvragen zijn alleen toe te voegen'); END""",
        """CREATE TRIGGER IF NOT EXISTS req_no_delete
           BEFORE DELETE ON dataset_requests
           BEGIN SELECT RAISE(ABORT, 'aanvragen zijn alleen toe te voegen'); END""",

        # --- vergrendeling uitgebreid met dataset_id ------------------------- #
        "DROP TRIGGER IF EXISTS exp_hypothesis_locked",
        f"""CREATE TRIGGER exp_hypothesis_locked
           BEFORE UPDATE ON experiments
           WHEN OLD.status <> 'draft' AND ({vergrendeld})
           BEGIN SELECT RAISE(ABORT, 'hypothese en provenance zijn vergrendeld'); END""",
    ]


def _schema_v3() -> list[str]:
    """Uitvoering: voortgang en een minimaal technisch resultaat.

    Bewust klein: de metrieken komen in fase 4. Hier alleen wat nodig is om
    één uitvoering veilig af te ronden.
    """
    terminaal = _sql_lijst(TERMINAL)
    return [
        """CREATE TABLE IF NOT EXISTS experiment_runs (
               experiment_id    INTEGER PRIMARY KEY
                   REFERENCES experiments(id) ON DELETE RESTRICT,
               executor         TEXT NOT NULL,
               bars_total       INTEGER NOT NULL DEFAULT 0 CHECK (bars_total >= 0),
               bars_processed   INTEGER NOT NULL DEFAULT 0 CHECK (bars_processed >= 0),
               progress_pct     REAL NOT NULL DEFAULT 0
                   CHECK (progress_pct >= 0 AND progress_pct <= 100),
               started_at       TEXT NOT NULL,
               last_progress_at TEXT,
               finished_at      TEXT
           )""",
        """CREATE TABLE IF NOT EXISTS experiment_results (
               experiment_id   INTEGER PRIMARY KEY
                   REFERENCES experiments(id) ON DELETE RESTRICT,
               result_hash     TEXT NOT NULL,
               summary_json    TEXT NOT NULL,
               trades_json     TEXT NOT NULL,
               provenance_json TEXT NOT NULL,
               created_at      TEXT NOT NULL
           )""",

        # Voortgang: alleen zolang het experiment loopt, en nooit achteruit.
        f"""CREATE TRIGGER IF NOT EXISTS run_update_while_active
           BEFORE UPDATE ON experiment_runs
           WHEN (SELECT status FROM experiments WHERE id = OLD.experiment_id)
                IN ({terminaal})
           BEGIN SELECT RAISE(ABORT, 'uitvoering is afgesloten'); END""",
        """CREATE TRIGGER IF NOT EXISTS run_monotone
           BEFORE UPDATE ON experiment_runs
           WHEN NEW.bars_processed < OLD.bars_processed
             OR NEW.progress_pct < OLD.progress_pct
           BEGIN SELECT RAISE(ABORT, 'voortgang gaat nooit achteruit'); END""",
        """CREATE TRIGGER IF NOT EXISTS run_no_delete
           BEFORE DELETE ON experiment_runs
           BEGIN SELECT RAISE(ABORT, 'een uitvoering wordt niet verwijderd'); END""",

        # Resultaat: alleen bij een lopend experiment, daarna onveranderlijk.
        """CREATE TRIGGER IF NOT EXISTS res_insert_running
           BEFORE INSERT ON experiment_results
           WHEN (SELECT status FROM experiments WHERE id = NEW.experiment_id) <> 'running'
           BEGIN SELECT RAISE(ABORT, 'een resultaat hoort bij een lopend experiment'); END""",
        """CREATE TRIGGER IF NOT EXISTS res_no_update
           BEFORE UPDATE ON experiment_results
           BEGIN SELECT RAISE(ABORT, 'een resultaat is onveranderlijk'); END""",
        """CREATE TRIGGER IF NOT EXISTS res_no_delete
           BEFORE DELETE ON experiment_results
           BEGIN SELECT RAISE(ABORT, 'een resultaat is onveranderlijk'); END""",

        # Voltooid kan alleen mét opgeslagen resultaat, en een ander einde
        # nooit mét resultaat. Niet afgesproken, maar afgedwongen.
        """CREATE TRIGGER IF NOT EXISTS exp_completed_needs_result
           BEFORE UPDATE OF status ON experiments
           WHEN NEW.status = 'completed'
             AND NOT EXISTS (SELECT 1 FROM experiment_results WHERE experiment_id = NEW.id)
           BEGIN SELECT RAISE(ABORT, 'voltooid zonder opgeslagen resultaat'); END""",
        """CREATE TRIGGER IF NOT EXISTS exp_other_end_no_result
           BEFORE UPDATE OF status ON experiments
           WHEN NEW.status IN ('failed','cancelled','interrupted')
             AND EXISTS (SELECT 1 FROM experiment_results WHERE experiment_id = NEW.id)
           BEGIN SELECT RAISE(ABORT, 'alleen een voltooid experiment heeft een resultaat'); END""",
    ]

LEGACY, NORMALIZED = "LEGACY_TECHNICAL_RESULT", "NORMALIZED_METRICS_RESULT"

#: SQLite-type per trade-veld.
_TRADE_TYPES = {
    "sequence_number": "INTEGER NOT NULL", "opened_ts": "INTEGER NOT NULL",
    "closed_ts": "INTEGER NOT NULL", "trading_day": "TEXT NOT NULL",
    "timezone": "TEXT NOT NULL", "side": "TEXT NOT NULL", "units": "REAL NOT NULL",
    "instrument_currency": "TEXT NOT NULL", "account_currency": "TEXT",
    "conversion_status": "TEXT NOT NULL CHECK (conversion_status IN ('CONVERTED','UNKNOWN','UNUSABLE'))",
    "regime": "TEXT", "session": "TEXT NOT NULL", "close_reason": "TEXT NOT NULL",
    "fx_source": "TEXT", "fx_timestamp": "TEXT", "fidelity_status": "TEXT NOT NULL",
    "ambiguous_exit": "INTEGER NOT NULL CHECK (ambiguous_exit IN (0,1))",
    "holding_seconds": "INTEGER NOT NULL",
    "gross_pnl_instrument": "REAL NOT NULL", "spread_cost_instrument": "REAL NOT NULL",
    "slippage_cost_instrument": "REAL NOT NULL", "commission_cost_instrument": "REAL NOT NULL",
    "other_cost_instrument": "REAL NOT NULL", "total_cost_instrument": "REAL NOT NULL",
    "net_pnl_instrument": "REAL NOT NULL",
}


def _alleen_toevoegen(tabel: str) -> list[str]:
    """Rijen alleen tijdens het lopen toevoegen; daarna onveranderlijk."""
    return [
        f"""CREATE TRIGGER IF NOT EXISTS {tabel}_insert_running
           BEFORE INSERT ON {tabel}
           WHEN (SELECT status FROM experiments WHERE id = NEW.experiment_id) <> 'running'
           BEGIN SELECT RAISE(ABORT, '{tabel}: alleen bij een lopend experiment'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS {tabel}_no_update BEFORE UPDATE ON {tabel}
           BEGIN SELECT RAISE(ABORT, '{tabel} is onveranderlijk'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS {tabel}_no_delete BEFORE DELETE ON {tabel}
           BEGIN SELECT RAISE(ABORT, '{tabel} is onveranderlijk'); END""",
    ]


def _schema_v4() -> list[str]:
    """Genormaliseerde trades, metrieken, uitsplitsingen, afwijzingen en versies.

    ``experiment_results`` wordt herbouwd zodat ``trades_json`` voor nieuwe
    resultaten leeg mag zijn. Bestaande resultaten blijven ongewijzigd en
    worden gelabeld als ``LEGACY_TECHNICAL_RESULT``.

    Volgorde is nodig: ``RENAME`` weigert zolang een trigger op
    ``experiments`` naar de oude tabel verwijst. Die twee triggers gaan eerst
    weg en komen daarna strenger terug. ``DROP TABLE`` vuurt geen
    verwijdertrigger af (nagemeten).
    """
    trade_kolommen = ",\n".join(
        f"    {v} {_TRADE_TYPES.get(v, 'REAL')}" for v in TRADE_FIELDS
    )
    verplicht = len(REQUIRED_METRICS)
    return [
        "DROP TRIGGER IF EXISTS exp_completed_needs_result",
        "DROP TRIGGER IF EXISTS exp_other_end_no_result",
        f"""CREATE TABLE experiment_results_v4 (
               experiment_id           INTEGER PRIMARY KEY
                   REFERENCES experiments(id) ON DELETE RESTRICT,
               result_kind             TEXT NOT NULL
                   CHECK (result_kind IN ('{LEGACY}','{NORMALIZED}')),
               result_schema_version   INTEGER NOT NULL,
               backtest_engine_version INTEGER,
               cost_model_version      INTEGER,
               metrics_version         INTEGER,
               result_hash             TEXT NOT NULL,
               summary_json            TEXT NOT NULL,
               trades_json             TEXT,
               provenance_json         TEXT NOT NULL,
               cost_model_json         TEXT,
               trade_count             INTEGER NOT NULL CHECK (trade_count >= 0),
               created_at              TEXT NOT NULL,
               CHECK (
                 (result_kind = '{LEGACY}' AND trades_json IS NOT NULL) OR
                 (result_kind = '{NORMALIZED}' AND trades_json IS NULL
                  AND cost_model_json IS NOT NULL AND cost_model_version IS NOT NULL
                  AND metrics_version IS NOT NULL AND backtest_engine_version IS NOT NULL)
               )
           )""",
        f"""INSERT INTO experiment_results_v4
            SELECT experiment_id, '{LEGACY}', 1,
                   json_extract(provenance_json, '$.backtest_engine_version'),
                   NULL, NULL, result_hash, summary_json, trades_json,
                   provenance_json, NULL, json_array_length(trades_json), created_at
            FROM experiment_results""",
        "DROP TABLE experiment_results",
        "ALTER TABLE experiment_results_v4 RENAME TO experiment_results",
        *_alleen_toevoegen("experiment_results"),

        f"""CREATE TABLE IF NOT EXISTS experiment_trades (
               experiment_id INTEGER NOT NULL
                   REFERENCES experiment_results(experiment_id) ON DELETE RESTRICT,
{trade_kolommen},
               PRIMARY KEY (experiment_id, sequence_number)
           ) WITHOUT ROWID""",
        *_alleen_toevoegen("experiment_trades"),

        """CREATE TABLE IF NOT EXISTS experiment_metrics (
               experiment_id          INTEGER NOT NULL
                   REFERENCES experiment_results(experiment_id) ON DELETE RESTRICT,
               metric_name            TEXT NOT NULL,
               metric_version         INTEGER NOT NULL,
               value                  REAL,
               unit                   TEXT NOT NULL,
               currency               TEXT,
               timezone               TEXT,
               population             TEXT NOT NULL,
               numerator              REAL,
               denominator            REAL,
               numerator_definition   TEXT,
               denominator_definition TEXT,
               sample_size            INTEGER NOT NULL,
               calculation_status     TEXT NOT NULL CHECK (calculation_status IN
                   ('VALID','INSUFFICIENT_DATA','NOT_APPLICABLE','UNKNOWN_INPUT','PARTIAL')),
               -- Een geldige waarde bestaat; een niet-geldige is leeg, nooit 0.
               CHECK ((calculation_status = 'VALID') = (value IS NOT NULL)),
               PRIMARY KEY (experiment_id, metric_name)
           ) WITHOUT ROWID""",
        *_alleen_toevoegen("experiment_metrics"),

        """CREATE TABLE IF NOT EXISTS experiment_breakdowns (
               experiment_id        INTEGER NOT NULL
                   REFERENCES experiment_results(experiment_id) ON DELETE RESTRICT,
               dimension            TEXT NOT NULL
                   CHECK (dimension IN ('trading_day','session','regime','close_reason')),
               label                TEXT NOT NULL,
               timezone             TEXT,
               currency             TEXT NOT NULL,
               trade_count          INTEGER NOT NULL,
               sample_size          INTEGER NOT NULL,
               wins                 INTEGER NOT NULL,
               gross                REAL NOT NULL,
               costs                REAL NOT NULL,
               net                  REAL NOT NULL,
               win_rate             REAL NOT NULL,
               win_rate_numerator   INTEGER NOT NULL,
               win_rate_denominator INTEGER NOT NULL,
               expectancy           REAL NOT NULL,
               PRIMARY KEY (experiment_id, dimension, label)
           ) WITHOUT ROWID""",
        *_alleen_toevoegen("experiment_breakdowns"),

        """CREATE TABLE IF NOT EXISTS experiment_rejections (
               experiment_id INTEGER NOT NULL
                   REFERENCES experiment_results(experiment_id) ON DELETE RESTRICT,
               code          TEXT NOT NULL,
               count         INTEGER NOT NULL,
               share         REAL,
               denominator   INTEGER NOT NULL,
               PRIMARY KEY (experiment_id, code)
           ) WITHOUT ROWID""",
        *_alleen_toevoegen("experiment_rejections"),

        # completed: resultaat, en bij een genormaliseerd resultaat ook álle
        # verplichte metrieken en precies zoveel traderijen als het resultaat noemt.
        f"""CREATE TRIGGER exp_completed_needs_result
           BEFORE UPDATE OF status ON experiments
           WHEN NEW.status = 'completed' AND (
             NOT EXISTS (SELECT 1 FROM experiment_results WHERE experiment_id = NEW.id)
             OR ((SELECT result_kind FROM experiment_results WHERE experiment_id = NEW.id) = '{NORMALIZED}'
                 AND ((SELECT COUNT(*) FROM experiment_metrics WHERE experiment_id = NEW.id) <> {verplicht}
                      OR (SELECT COUNT(*) FROM experiment_trades WHERE experiment_id = NEW.id)
                         <> (SELECT trade_count FROM experiment_results WHERE experiment_id = NEW.id))))
           BEGIN SELECT RAISE(ABORT, 'voltooid zonder volledig opgeslagen resultaat'); END""",
        """CREATE TRIGGER exp_other_end_no_result
           BEFORE UPDATE OF status ON experiments
           WHEN NEW.status IN ('failed','cancelled','interrupted')
             AND EXISTS (SELECT 1 FROM experiment_results WHERE experiment_id = NEW.id)
           BEGIN SELECT RAISE(ABORT, 'alleen een voltooid experiment heeft een resultaat'); END""",
    ]


TEST_PURPOSES = ("FINAL_EVALUATION", "REPRODUCTION_REVIEW", "AUDIT", "DEBUG_AFTER_FAILURE")
#: Sinds schema 7 kan een walk-forward-TEST ook door een beoordeling worden
#: gelezen. Dat is zelf TEST-toegang en wordt zo gelogd.
WF_TEST_PURPOSES = TEST_PURPOSES + ("ASSESSMENT", "COMPARISON")
#: Versie van de betekenis van het TEST-toegangslog. 2: doel ASSESSMENT en de
#: koppeling aan een beoordeling.
TEST_ACCESS_SCHEMA_VERSION = 3  # 3: doel COMPARISON, gekoppeld aan een vergelijking


def _schema_v5() -> list[str]:
    """Segmenten, segmentgebonden resultaten, testbescherming en toegangslog.

    De tabellen van fase 4 blijven ongewijzigd: hun resultaten zijn
    ``UNSEGMENTED`` en worden niet naar een fictief segment gemigreerd.
    Gesegmenteerde resultaten krijgen eigen tabellen, elk met ``segment_id``.
    """
    trade_kolommen = ",\n".join(
        f"    {v} {_TRADE_TYPES.get(v, 'REAL')}" for v in TRADE_FIELDS
    )
    verplicht = len(REQUIRED_METRICS)
    doelen = ",".join(f"'{d}'" for d in TEST_PURPOSES)
    alleen_draft = lambda tabel, sleutel: [  # noqa: E731
        f"""CREATE TRIGGER IF NOT EXISTS {tabel}_{wat}_draft
           BEFORE {wat.upper()} ON {tabel}
           WHEN (SELECT status FROM experiments WHERE id = {rij}.{sleutel}) <> 'draft'
           BEGIN SELECT RAISE(ABORT, '{tabel}: vergrendeld na registratie'); END"""
        for wat, rij in (("insert", "NEW"), ("update", "OLD"), ("delete", "OLD"))
    ]
    return [
        """CREATE TABLE IF NOT EXISTS segment_plans (
               experiment_id          INTEGER PRIMARY KEY
                   REFERENCES experiments(id) ON DELETE CASCADE,
               dataset_id             INTEGER NOT NULL REFERENCES datasets(id),
               dataset_hash           TEXT NOT NULL,
               plan_hash              TEXT NOT NULL,
               segment_schema_version INTEGER NOT NULL,
               time_unit              TEXT NOT NULL,
               boundary_semantics     TEXT NOT NULL,
               warmup_rule            TEXT NOT NULL,
               open_cutoff_rule       TEXT NOT NULL,
               timeframe              TEXT NOT NULL,
               bar_seconds            INTEGER NOT NULL CHECK (bar_seconds > 0),
               max_hold_seconds       INTEGER NOT NULL CHECK (max_hold_seconds > 0),
               created_at             TEXT NOT NULL
           )""",
        *alleen_draft("segment_plans", "experiment_id"),
        """CREATE TABLE IF NOT EXISTS experiment_segments (
               id              INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id   INTEGER NOT NULL
                   REFERENCES segment_plans(experiment_id) ON DELETE CASCADE,
               kind            TEXT NOT NULL,
               sequence_number INTEGER NOT NULL,
               start_ts        INTEGER NOT NULL,
               end_ts          INTEGER NOT NULL,
               warmup_start_ts INTEGER NOT NULL,
               open_cutoff_ts  INTEGER NOT NULL,
               warmup_bars     INTEGER NOT NULL CHECK (warmup_bars >= 0),
               warmup_status   TEXT NOT NULL
                   CHECK (warmup_status IN ('FULL_WARMUP','PARTIAL_WARMUP')),
               created_at      TEXT NOT NULL,
               locked_at       TEXT,
               CHECK ((kind = 'TRAIN' AND sequence_number = 1)
                   OR (kind = 'VALIDATION' AND sequence_number = 2)
                   OR (kind = 'TEST' AND sequence_number = 3)),
               CHECK (warmup_start_ts <= start_ts AND start_ts < open_cutoff_ts
                      AND open_cutoff_ts < end_ts),
               UNIQUE (experiment_id, kind)
           )""",
        # Chronologisch en zonder overlap, ook met rechtstreekse SQL.
        """CREATE TRIGGER IF NOT EXISTS seg_chronologisch
           BEFORE INSERT ON experiment_segments
           WHEN EXISTS (SELECT 1 FROM experiment_segments s
                        WHERE s.experiment_id = NEW.experiment_id AND (
                          (s.sequence_number < NEW.sequence_number AND s.end_ts > NEW.start_ts)
                       OR (s.sequence_number > NEW.sequence_number AND s.start_ts < NEW.end_ts)))
           BEGIN SELECT RAISE(ABORT, 'segmenten overlappen of zijn niet chronologisch'); END""",
        *alleen_draft("experiment_segments", "experiment_id"),

        # Registreren met een plan vraagt een volledig plan op de eigen dataset.
        """CREATE TRIGGER IF NOT EXISTS exp_registration_segments
           BEFORE UPDATE OF status ON experiments
           WHEN NEW.status = 'registered'
             AND EXISTS (SELECT 1 FROM segment_plans WHERE experiment_id = NEW.id)
             AND ((SELECT COUNT(*) FROM experiment_segments WHERE experiment_id = NEW.id) <> 3
                  OR (SELECT dataset_id FROM segment_plans WHERE experiment_id = NEW.id)
                     IS NOT NEW.dataset_id)
           BEGIN SELECT RAISE(ABORT, 'segmentplan onvolledig of op een andere dataset'); END""",

        """CREATE TABLE IF NOT EXISTS segment_results (
               segment_id              INTEGER PRIMARY KEY
                   REFERENCES experiment_segments(id) ON DELETE RESTRICT,
               experiment_id           INTEGER NOT NULL REFERENCES experiments(id),
               kind                    TEXT NOT NULL,
               result_kind             TEXT NOT NULL CHECK (result_kind = 'SEGMENT_RESULT'),
               result_hash             TEXT NOT NULL,
               summary_json            TEXT NOT NULL,
               cost_model_json         TEXT NOT NULL,
               result_schema_version   INTEGER NOT NULL,
               backtest_engine_version INTEGER NOT NULL,
               cost_model_version      INTEGER NOT NULL,
               metrics_version         INTEGER NOT NULL,
               segment_schema_version  INTEGER NOT NULL,
               trade_count             INTEGER NOT NULL CHECK (trade_count >= 0),
               cross_boundary_count    INTEGER NOT NULL CHECK (cross_boundary_count >= 0),
               warmup_status           TEXT NOT NULL,
               created_at              TEXT NOT NULL
           )""",
        *_alleen_toevoegen("segment_results"),
        f"""CREATE TABLE IF NOT EXISTS segment_trades (
               segment_id    INTEGER NOT NULL REFERENCES segment_results(segment_id),
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
{trade_kolommen},
               cross_boundary INTEGER NOT NULL CHECK (cross_boundary IN (0,1)),
               PRIMARY KEY (segment_id, sequence_number)
           ) WITHOUT ROWID""",
        *_alleen_toevoegen("segment_trades"),
        """CREATE TABLE IF NOT EXISTS segment_metrics (
               segment_id             INTEGER NOT NULL REFERENCES segment_results(segment_id),
               experiment_id          INTEGER NOT NULL REFERENCES experiments(id),
               metric_name            TEXT NOT NULL,
               metric_version         INTEGER NOT NULL,
               value                  REAL,
               unit                   TEXT NOT NULL,
               currency               TEXT,
               timezone               TEXT,
               population             TEXT NOT NULL,
               numerator              REAL,
               denominator            REAL,
               numerator_definition   TEXT,
               denominator_definition TEXT,
               sample_size            INTEGER NOT NULL,
               calculation_status     TEXT NOT NULL CHECK (calculation_status IN
                   ('VALID','INSUFFICIENT_DATA','NOT_APPLICABLE','UNKNOWN_INPUT','PARTIAL')),
               CHECK ((calculation_status = 'VALID') = (value IS NOT NULL)),
               PRIMARY KEY (segment_id, metric_name)
           ) WITHOUT ROWID""",
        *_alleen_toevoegen("segment_metrics"),
        """CREATE TABLE IF NOT EXISTS segment_breakdowns (
               segment_id           INTEGER NOT NULL REFERENCES segment_results(segment_id),
               experiment_id        INTEGER NOT NULL REFERENCES experiments(id),
               dimension            TEXT NOT NULL
                   CHECK (dimension IN ('trading_day','session','regime','close_reason')),
               label                TEXT NOT NULL,
               timezone             TEXT,
               currency             TEXT NOT NULL,
               trade_count          INTEGER NOT NULL,
               sample_size          INTEGER NOT NULL,
               wins                 INTEGER NOT NULL,
               gross                REAL NOT NULL,
               costs                REAL NOT NULL,
               net                  REAL NOT NULL,
               win_rate             REAL NOT NULL,
               win_rate_numerator   INTEGER NOT NULL,
               win_rate_denominator INTEGER NOT NULL,
               expectancy           REAL NOT NULL,
               PRIMARY KEY (segment_id, dimension, label)
           ) WITHOUT ROWID""",
        *_alleen_toevoegen("segment_breakdowns"),
        """CREATE TABLE IF NOT EXISTS segment_rejections (
               segment_id    INTEGER NOT NULL REFERENCES segment_results(segment_id),
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               code          TEXT NOT NULL,
               count         INTEGER NOT NULL,
               share         REAL,
               denominator   INTEGER NOT NULL,
               PRIMARY KEY (segment_id, code)
           ) WITHOUT ROWID""",
        *_alleen_toevoegen("segment_rejections"),

        f"""CREATE TABLE IF NOT EXISTS test_access_log (
               id                   INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id        INTEGER NOT NULL REFERENCES experiments(id),
               segment_id           INTEGER NOT NULL REFERENCES experiment_segments(id),
               hypothesis_family_id TEXT NOT NULL,
               dataset_id           INTEGER NOT NULL REFERENCES datasets(id),
               dataset_hash         TEXT NOT NULL,
               test_start_ts        INTEGER NOT NULL,
               test_end_ts          INTEGER NOT NULL,
               accessed_at          TEXT NOT NULL,
               purpose              TEXT NOT NULL CHECK (purpose IN ({doelen})),
               access_type          TEXT NOT NULL CHECK (access_type = 'TEST_RESULT_READ'),
               accessor_context     TEXT NOT NULL CHECK (length(trim(accessor_context)) > 0),
               prior_access_count   INTEGER NOT NULL CHECK (prior_access_count >= 0),
               data_reused          INTEGER NOT NULL CHECK (data_reused IN (0,1)),
               CHECK (data_reused = (prior_access_count > 0))
           )""",
        """CREATE TRIGGER IF NOT EXISTS tal_no_update BEFORE UPDATE ON test_access_log
           BEGIN SELECT RAISE(ABORT, 'test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER IF NOT EXISTS tal_no_delete BEFORE DELETE ON test_access_log
           BEGIN SELECT RAISE(ABORT, 'test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER IF NOT EXISTS tal_only_test
           BEFORE INSERT ON test_access_log
           WHEN (SELECT kind FROM experiment_segments WHERE id = NEW.segment_id) <> 'TEST'
             OR (SELECT status FROM experiments WHERE id = NEW.experiment_id) <> 'completed'
           BEGIN SELECT RAISE(ABORT, 'alleen het TEST-segment van een voltooid experiment'); END""",

        "ALTER TABLE experiment_runs ADD COLUMN current_segment TEXT",
        "ALTER TABLE experiment_runs ADD COLUMN segments_total INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE experiment_runs ADD COLUMN segments_completed INTEGER NOT NULL DEFAULT 0",
        """CREATE TRIGGER IF NOT EXISTS run_segments_monotone
           BEFORE UPDATE ON experiment_runs
           WHEN NEW.segments_completed < OLD.segments_completed
           BEGIN SELECT RAISE(ABORT, 'voltooide segmenten gaan nooit achteruit'); END""",

        # completed: óf het fase-4-resultaat is volledig, óf elk segment is dat.
        "DROP TRIGGER IF EXISTS exp_completed_needs_result",
        f"""CREATE TRIGGER exp_completed_needs_result
           BEFORE UPDATE OF status ON experiments
           WHEN NEW.status = 'completed' AND NOT (
             (EXISTS (SELECT 1 FROM experiment_results WHERE experiment_id = NEW.id)
              AND ((SELECT result_kind FROM experiment_results WHERE experiment_id = NEW.id) = '{LEGACY}'
                   OR ((SELECT COUNT(*) FROM experiment_metrics WHERE experiment_id = NEW.id) = {verplicht}
                       AND (SELECT COUNT(*) FROM experiment_trades WHERE experiment_id = NEW.id)
                           = (SELECT trade_count FROM experiment_results WHERE experiment_id = NEW.id))))
             OR
             (EXISTS (SELECT 1 FROM segment_plans WHERE experiment_id = NEW.id)
              AND (SELECT COUNT(*) FROM experiment_segments s
                   WHERE s.experiment_id = NEW.id
                     AND EXISTS (SELECT 1 FROM segment_results r WHERE r.segment_id = s.id)
                     AND (SELECT COUNT(*) FROM segment_metrics m WHERE m.segment_id = s.id) = {verplicht}
                     AND (SELECT COUNT(*) FROM segment_trades t WHERE t.segment_id = s.id)
                         = (SELECT trade_count FROM segment_results r WHERE r.segment_id = s.id)) = 3))
           BEGIN SELECT RAISE(ABORT, 'voltooid zonder volledig opgeslagen resultaat'); END""",
        "DROP TRIGGER IF EXISTS exp_other_end_no_result",
        """CREATE TRIGGER exp_other_end_no_result
           BEFORE UPDATE OF status ON experiments
           WHEN NEW.status IN ('failed','cancelled','interrupted')
             AND (EXISTS (SELECT 1 FROM experiment_results WHERE experiment_id = NEW.id)
                  OR EXISTS (SELECT 1 FROM segment_results WHERE experiment_id = NEW.id))
           BEGIN SELECT RAISE(ABORT, 'alleen een voltooid experiment heeft een resultaat'); END""",
    ]


def _resultaat_kinderen(prefix: str, sleutel: str, ouder: str) -> list[str]:
    """Trades, metrieken, uitsplitsingen en afwijzingen, gekoppeld aan één
    resultaatrij. Dezelfde kolommen als in fase 4 en 5."""
    trade_kolommen = ",\n".join(f"    {v} {_TRADE_TYPES.get(v, 'REAL')}" for v in TRADE_FIELDS)
    k = f"{sleutel} INTEGER NOT NULL REFERENCES {ouder}(id), experiment_id INTEGER NOT NULL REFERENCES experiments(id)"
    return [
        f"""CREATE TABLE IF NOT EXISTS {prefix}_trades ({k},
{trade_kolommen},
               cross_boundary INTEGER NOT NULL CHECK (cross_boundary IN (0,1)),
               PRIMARY KEY ({sleutel}, sequence_number)) WITHOUT ROWID""",
        *_alleen_toevoegen(f"{prefix}_trades"),
        f"""CREATE TABLE IF NOT EXISTS {prefix}_metrics ({k},
               metric_name TEXT NOT NULL, metric_version INTEGER NOT NULL, value REAL,
               unit TEXT NOT NULL, currency TEXT, timezone TEXT, population TEXT NOT NULL,
               numerator REAL, denominator REAL, numerator_definition TEXT,
               denominator_definition TEXT, sample_size INTEGER NOT NULL,
               calculation_status TEXT NOT NULL CHECK (calculation_status IN
                   ('VALID','INSUFFICIENT_DATA','NOT_APPLICABLE','UNKNOWN_INPUT','PARTIAL')),
               CHECK ((calculation_status = 'VALID') = (value IS NOT NULL)),
               PRIMARY KEY ({sleutel}, metric_name)) WITHOUT ROWID""",
        *_alleen_toevoegen(f"{prefix}_metrics"),
        f"""CREATE TABLE IF NOT EXISTS {prefix}_breakdowns ({k},
               dimension TEXT NOT NULL CHECK (dimension IN ('trading_day','session','regime','close_reason')),
               label TEXT NOT NULL, timezone TEXT, currency TEXT NOT NULL,
               trade_count INTEGER NOT NULL, sample_size INTEGER NOT NULL, wins INTEGER NOT NULL,
               gross REAL NOT NULL, costs REAL NOT NULL, net REAL NOT NULL, win_rate REAL NOT NULL,
               win_rate_numerator INTEGER NOT NULL, win_rate_denominator INTEGER NOT NULL,
               expectancy REAL NOT NULL,
               PRIMARY KEY ({sleutel}, dimension, label)) WITHOUT ROWID""",
        *_alleen_toevoegen(f"{prefix}_breakdowns"),
        f"""CREATE TABLE IF NOT EXISTS {prefix}_rejections ({k},
               code TEXT NOT NULL, count INTEGER NOT NULL, share REAL, denominator INTEGER NOT NULL,
               PRIMARY KEY ({sleutel}, code)) WITHOUT ROWID""",
        *_alleen_toevoegen(f"{prefix}_rejections"),
    ]


def _schema_v6() -> list[str]:
    """Walk-forward: plan, kandidaten, vensters, selectie, validatie, resultaten
    per kandidaat en venster, en een eigen toegangslog per TEST-venster.

    De tabellen van fase 4 en 5 blijven; ``segment_results`` krijgt kolommen
    voor gedwongen sluitingen aan het segmenteinde (leeg voor bestaande rijen).
    """
    from .walk_forward import WINDOW_ALLOWED, WINDOW_TERMINAL_OK
    verplicht = len(REQUIRED_METRICS)
    doelen = ",".join(f"'{d}'" for d in TEST_PURPOSES)
    statussen = ",".join(f"'{s}'" for s in WINDOW_ALLOWED)
    overgang = " OR ".join(
        f"(OLD.status = '{van}' AND NEW.status IN ({','.join(repr(n) for n in naar)}))"
        for van, naar in WINDOW_ALLOWED.items() if naar
    ).replace('"', "'")
    ok = ",".join(f"'{s}'" for s in WINDOW_TERMINAL_OK)
    alleen_draft = lambda tabel, rij_eid: [  # noqa: E731
        f"""CREATE TRIGGER IF NOT EXISTS {tabel}_{wat}_draft BEFORE {wat.upper()} ON {tabel}
           WHEN (SELECT status FROM experiments WHERE id = {rij}.{rij_eid}) <> 'draft'
           BEGIN SELECT RAISE(ABORT, '{tabel}: vergrendeld na registratie'); END"""
        for wat, rij in (("insert", "NEW"), ("update", "OLD"), ("delete", "OLD"))
    ]
    return [
        "ALTER TABLE segment_results ADD COLUMN segment_end_close_count INTEGER",
        "ALTER TABLE segment_results ADD COLUMN forced_exit_json TEXT",

        """CREATE TABLE IF NOT EXISTS wf_plans (
               experiment_id INTEGER PRIMARY KEY REFERENCES experiments(id) ON DELETE CASCADE,
               dataset_id INTEGER NOT NULL REFERENCES datasets(id), dataset_hash TEXT NOT NULL,
               mode TEXT NOT NULL CHECK (mode IN ('CANDIDATE_SELECTION_WALK_FORWARD','SEQUENTIAL_OOS')),
               window_type TEXT NOT NULL CHECK (window_type IN ('ROLLING','EXPANDING')),
               first_train_start INTEGER NOT NULL, train_length INTEGER NOT NULL,
               validation_length INTEGER NOT NULL, test_length INTEGER NOT NULL,
               step_size INTEGER NOT NULL, window_count INTEGER NOT NULL CHECK (window_count > 0),
               walk_forward_schema_version INTEGER NOT NULL,
               segment_schema_version INTEGER NOT NULL, selection_rule_version INTEGER NOT NULL,
               selection_rule_json TEXT NOT NULL, candidate_set_hash TEXT NOT NULL,
               primary_metric TEXT NOT NULL,
               selection_direction TEXT NOT NULL CHECK (selection_direction IN ('MAXIMIZE','MINIMIZE')),
               tie_break_json TEXT NOT NULL, validation_policy TEXT NOT NULL,
               missing_metric_policy TEXT NOT NULL, test_access_policy TEXT NOT NULL,
               max_hold_seconds INTEGER NOT NULL, bar_seconds INTEGER NOT NULL,
               created_at TEXT NOT NULL, locked_at TEXT)""",
        *alleen_draft("wf_plans", "experiment_id"),
        """CREATE TABLE IF NOT EXISTS wf_candidates (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id INTEGER NOT NULL REFERENCES wf_plans(experiment_id) ON DELETE CASCADE,
               parameter_id INTEGER NOT NULL REFERENCES experiment_parameters(id),
               candidate_label TEXT NOT NULL, config_hash TEXT NOT NULL, created_at TEXT NOT NULL,
               UNIQUE (experiment_id, config_hash), UNIQUE (experiment_id, candidate_label))""",
        *alleen_draft("wf_candidates", "experiment_id"),
        f"""CREATE TABLE IF NOT EXISTS wf_windows (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id INTEGER NOT NULL REFERENCES wf_plans(experiment_id) ON DELETE CASCADE,
               window_index INTEGER NOT NULL, status TEXT NOT NULL CHECK (status IN ({statussen})),
               status_reason TEXT, updated_at TEXT NOT NULL,
               UNIQUE (experiment_id, window_index))""",
        """CREATE TRIGGER IF NOT EXISTS wfw_insert_draft BEFORE INSERT ON wf_windows
           WHEN (SELECT status FROM experiments WHERE id = NEW.experiment_id) <> 'draft'
             OR NEW.status <> 'PENDING'
           BEGIN SELECT RAISE(ABORT, 'vensters ontstaan als PENDING in een draft'); END""",
        """CREATE TRIGGER IF NOT EXISTS wfw_identity BEFORE UPDATE ON wf_windows
           WHEN NEW.window_index IS NOT OLD.window_index OR NEW.experiment_id IS NOT OLD.experiment_id
           BEGIN SELECT RAISE(ABORT, 'identiteit van een venster ligt vast'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS wfw_transition BEFORE UPDATE OF status ON wf_windows
           WHEN NEW.status IS NOT OLD.status AND NOT ({overgang})
           BEGIN SELECT RAISE(ABORT, 'illegale vensterovergang'); END""",
        """CREATE TRIGGER IF NOT EXISTS wfw_direct_test_only_sequential BEFORE UPDATE OF status ON wf_windows
           WHEN OLD.status = 'PENDING' AND NEW.status = 'TESTING'
             AND (SELECT mode FROM wf_plans WHERE experiment_id = OLD.experiment_id) <> 'SEQUENTIAL_OOS'
           BEGIN SELECT RAISE(ABORT, 'TEST zonder selectie alleen bij SEQUENTIAL_OOS'); END""",
        """CREATE TRIGGER IF NOT EXISTS wfw_no_delete BEFORE DELETE ON wf_windows
           WHEN (SELECT status FROM experiments WHERE id = OLD.experiment_id) <> 'draft'
           BEGIN SELECT RAISE(ABORT, 'een venster wordt niet verwijderd'); END""",
        """CREATE TABLE IF NOT EXISTS wf_segments (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               window_id INTEGER NOT NULL REFERENCES wf_windows(id) ON DELETE CASCADE,
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               kind TEXT NOT NULL CHECK (kind IN ('TRAIN','VALIDATION','TEST')),
               start_ts INTEGER NOT NULL, end_ts INTEGER NOT NULL, warmup_start_ts INTEGER NOT NULL,
               open_cutoff_ts INTEGER NOT NULL, warmup_bars INTEGER NOT NULL,
               warmup_status TEXT NOT NULL CHECK (warmup_status IN ('FULL_WARMUP','PARTIAL_WARMUP')),
               CHECK (warmup_start_ts <= start_ts AND start_ts < open_cutoff_ts AND open_cutoff_ts < end_ts),
               UNIQUE (window_id, kind))""",
        *alleen_draft("wf_segments", "experiment_id"),
        """CREATE TRIGGER IF NOT EXISTS exp_registration_wf BEFORE UPDATE OF status ON experiments
           WHEN NEW.status = 'registered' AND EXISTS (SELECT 1 FROM wf_plans WHERE experiment_id = NEW.id)
             AND ((SELECT COUNT(*) FROM wf_windows WHERE experiment_id = NEW.id)
                    <> (SELECT window_count FROM wf_plans WHERE experiment_id = NEW.id)
                  OR (SELECT COUNT(*) FROM wf_candidates WHERE experiment_id = NEW.id) = 0
                  OR ((SELECT mode FROM wf_plans WHERE experiment_id = NEW.id) = 'SEQUENTIAL_OOS'
                      AND (SELECT COUNT(*) FROM wf_candidates WHERE experiment_id = NEW.id) <> 1)
                  OR (SELECT dataset_id FROM wf_plans WHERE experiment_id = NEW.id) IS NOT NEW.dataset_id)
           BEGIN SELECT RAISE(ABORT, 'walk-forwardplan onvolledig of inconsistent'); END""",

        """CREATE TABLE IF NOT EXISTS wf_selections (
               window_id INTEGER PRIMARY KEY REFERENCES wf_windows(id),
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               selection_status TEXT NOT NULL CHECK (selection_status IN ('SELECTED','NO_SELECTION')),
               selected_candidate_id INTEGER REFERENCES wf_candidates(id),
               selected_config_hash TEXT, primary_metric TEXT NOT NULL,
               selection_direction TEXT NOT NULL, selected_metric_value REAL,
               selected_metric_status TEXT, tie_break_values_json TEXT NOT NULL,
               selection_rule_version INTEGER NOT NULL, reason TEXT, selected_at TEXT NOT NULL,
               CHECK ((selection_status = 'SELECTED') = (selected_candidate_id IS NOT NULL)))""",
        *_alleen_toevoegen("wf_selections"),
        """CREATE TRIGGER IF NOT EXISTS wfs_only_when_selecting BEFORE INSERT ON wf_selections
           WHEN (SELECT status FROM wf_windows WHERE id = NEW.window_id) <> 'SELECTING'
           BEGIN SELECT RAISE(ABORT, 'selectie alleen in SELECTING'); END""",
        """CREATE TABLE IF NOT EXISTS wf_candidate_evaluations (
               window_id INTEGER NOT NULL REFERENCES wf_windows(id),
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               candidate_id INTEGER NOT NULL REFERENCES wf_candidates(id),
               train_result_id INTEGER NOT NULL, primary_metric_value REAL,
               primary_metric_status TEXT NOT NULL, eligible INTEGER NOT NULL CHECK (eligible IN (0,1)),
               disqualification_reason TEXT, rank_position INTEGER,
               PRIMARY KEY (window_id, candidate_id)) WITHOUT ROWID""",
        *_alleen_toevoegen("wf_candidate_evaluations"),
        """CREATE TABLE IF NOT EXISTS wf_validation_decisions (
               window_id INTEGER PRIMARY KEY REFERENCES wf_windows(id),
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               status TEXT NOT NULL CHECK (status IN ('PASSED','FAILED')),
               reason TEXT NOT NULL, decided_at TEXT NOT NULL)""",
        *_alleen_toevoegen("wf_validation_decisions"),
        """CREATE TRIGGER IF NOT EXISTS wfv_only_when_validating BEFORE INSERT ON wf_validation_decisions
           WHEN (SELECT status FROM wf_windows WHERE id = NEW.window_id) <> 'VALIDATING'
           BEGIN SELECT RAISE(ABORT, 'validatiebeslissing alleen in VALIDATING'); END""",

        """CREATE TABLE IF NOT EXISTS wf_results (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               wf_segment_id INTEGER NOT NULL REFERENCES wf_segments(id),
               window_id INTEGER NOT NULL REFERENCES wf_windows(id),
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               candidate_id INTEGER NOT NULL REFERENCES wf_candidates(id),
               kind TEXT NOT NULL, result_hash TEXT NOT NULL, summary_json TEXT NOT NULL,
               cost_model_json TEXT NOT NULL, result_schema_version INTEGER NOT NULL,
               backtest_engine_version INTEGER NOT NULL, cost_model_version INTEGER NOT NULL,
               metrics_version INTEGER NOT NULL, segment_schema_version INTEGER NOT NULL,
               walk_forward_schema_version INTEGER NOT NULL,
               trade_count INTEGER NOT NULL, cross_boundary_count INTEGER NOT NULL,
               segment_end_close_count INTEGER NOT NULL, forced_exit_json TEXT NOT NULL,
               warmup_status TEXT NOT NULL, created_at TEXT NOT NULL,
               UNIQUE (wf_segment_id, candidate_id))""",
        *_alleen_toevoegen("wf_results"),
        # TRAIN alleen tijdens TRAINING; VALIDATION en TEST alleen voor de vastgelegde keuze.
        """CREATE TRIGGER IF NOT EXISTS wfr_train BEFORE INSERT ON wf_results
           WHEN NEW.kind = 'TRAIN' AND (SELECT status FROM wf_windows WHERE id = NEW.window_id) <> 'TRAINING'
           BEGIN SELECT RAISE(ABORT, 'TRAIN-resultaat alleen in TRAINING'); END""",
        """CREATE TRIGGER IF NOT EXISTS wfr_validation BEFORE INSERT ON wf_results
           WHEN NEW.kind = 'VALIDATION' AND (
             (SELECT status FROM wf_windows WHERE id = NEW.window_id) <> 'VALIDATING'
             OR NOT EXISTS (SELECT 1 FROM wf_selections WHERE window_id = NEW.window_id
                            AND selection_status = 'SELECTED' AND selected_candidate_id = NEW.candidate_id))
           BEGIN SELECT RAISE(ABORT, 'VALIDATION alleen voor de vastgelegde keuze'); END""",
        """CREATE TRIGGER IF NOT EXISTS wfr_test BEFORE INSERT ON wf_results
           WHEN NEW.kind = 'TEST' AND (
             (SELECT status FROM wf_windows WHERE id = NEW.window_id) <> 'TESTING'
             OR ((SELECT mode FROM wf_plans WHERE experiment_id = NEW.experiment_id) <> 'SEQUENTIAL_OOS'
                 AND (NOT EXISTS (SELECT 1 FROM wf_selections WHERE window_id = NEW.window_id
                                  AND selection_status = 'SELECTED' AND selected_candidate_id = NEW.candidate_id)
                      OR ((SELECT validation_policy FROM wf_plans WHERE experiment_id = NEW.experiment_id)
                            = 'TRAIN_THEN_VALIDATION_CONFIRMATION'
                          AND NOT EXISTS (SELECT 1 FROM wf_validation_decisions
                                          WHERE window_id = NEW.window_id AND status = 'PASSED')))))
           BEGIN SELECT RAISE(ABORT, 'TEST pas na een vastgelegde, geldige keuze'); END""",
        *_resultaat_kinderen("wf", "wf_result_id", "wf_results"),

        f"""CREATE TABLE IF NOT EXISTS wf_test_access_log (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               window_id INTEGER NOT NULL REFERENCES wf_windows(id),
               wf_segment_id INTEGER NOT NULL REFERENCES wf_segments(id),
               hypothesis_family_id TEXT NOT NULL, dataset_id INTEGER NOT NULL,
               dataset_hash TEXT NOT NULL, test_start_ts INTEGER NOT NULL, test_end_ts INTEGER NOT NULL,
               accessed_at TEXT NOT NULL, purpose TEXT NOT NULL CHECK (purpose IN ({doelen})),
               access_type TEXT NOT NULL CHECK (access_type IN ('TEST_RESULT_READ','OOS_AGGREGATE_READ')),
               accessor_context TEXT NOT NULL CHECK (length(trim(accessor_context)) > 0),
               prior_access_count INTEGER NOT NULL, data_reused INTEGER NOT NULL,
               overlapping_prior_count INTEGER NOT NULL, overlap_seconds INTEGER NOT NULL,
               overlap_bars INTEGER NOT NULL,
               CHECK (data_reused = (prior_access_count > 0)))""",
        """CREATE TRIGGER IF NOT EXISTS wftal_no_update BEFORE UPDATE ON wf_test_access_log
           BEGIN SELECT RAISE(ABORT, 'wf_test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER IF NOT EXISTS wftal_no_delete BEFORE DELETE ON wf_test_access_log
           BEGIN SELECT RAISE(ABORT, 'wf_test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER IF NOT EXISTS wftal_only_test BEFORE INSERT ON wf_test_access_log
           WHEN (SELECT kind FROM wf_segments WHERE id = NEW.wf_segment_id) <> 'TEST'
             OR (SELECT status FROM experiments WHERE id = NEW.experiment_id) <> 'completed'
           BEGIN SELECT RAISE(ABORT, 'alleen het TEST-venster van een voltooid experiment'); END""",

        "ALTER TABLE experiment_runs ADD COLUMN windows_total INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE experiment_runs ADD COLUMN windows_completed INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE experiment_runs ADD COLUMN current_window INTEGER",
        "ALTER TABLE experiment_runs ADD COLUMN candidates_total INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE experiment_runs ADD COLUMN current_candidate TEXT",

        "DROP TRIGGER IF EXISTS exp_completed_needs_result",
        f"""CREATE TRIGGER exp_completed_needs_result
           BEFORE UPDATE OF status ON experiments
           WHEN NEW.status = 'completed' AND NOT (
             (EXISTS (SELECT 1 FROM experiment_results WHERE experiment_id = NEW.id)
              AND ((SELECT result_kind FROM experiment_results WHERE experiment_id = NEW.id) = '{LEGACY}'
                   OR ((SELECT COUNT(*) FROM experiment_metrics WHERE experiment_id = NEW.id) = {verplicht}
                       AND (SELECT COUNT(*) FROM experiment_trades WHERE experiment_id = NEW.id)
                           = (SELECT trade_count FROM experiment_results WHERE experiment_id = NEW.id))))
             OR
             (EXISTS (SELECT 1 FROM segment_plans WHERE experiment_id = NEW.id)
              AND (SELECT COUNT(*) FROM experiment_segments s
                   WHERE s.experiment_id = NEW.id
                     AND EXISTS (SELECT 1 FROM segment_results r WHERE r.segment_id = s.id)
                     AND (SELECT COUNT(*) FROM segment_metrics m WHERE m.segment_id = s.id) = {verplicht}
                     AND (SELECT COUNT(*) FROM segment_trades t WHERE t.segment_id = s.id)
                         = (SELECT trade_count FROM segment_results r WHERE r.segment_id = s.id)) = 3)
             OR
             (EXISTS (SELECT 1 FROM wf_plans WHERE experiment_id = NEW.id)
              AND (SELECT COUNT(*) FROM wf_windows WHERE experiment_id = NEW.id AND status IN ({ok}))
                  = (SELECT window_count FROM wf_plans WHERE experiment_id = NEW.id)
              AND NOT EXISTS (SELECT 1 FROM wf_windows w WHERE w.experiment_id = NEW.id
                              AND w.status = 'COMPLETED'
                              AND NOT EXISTS (SELECT 1 FROM wf_results r WHERE r.window_id = w.id
                                              AND r.kind = 'TEST'))
              AND NOT EXISTS (SELECT 1 FROM wf_results r WHERE r.experiment_id = NEW.id
                              AND ((SELECT COUNT(*) FROM wf_metrics m WHERE m.wf_result_id = r.id) <> {verplicht}
                                   OR (SELECT COUNT(*) FROM wf_trades t WHERE t.wf_result_id = r.id)
                                      <> r.trade_count))))
           BEGIN SELECT RAISE(ABORT, 'voltooid zonder volledig opgeslagen resultaat'); END""",
    ]


def _schema_v7() -> list[str]:
    """Beoordelingen. Het walk-forwardtoegangslog wordt herbouwd om het doel
    ASSESSMENT en een koppeling aan de beoordeling toe te voegen; bestaande
    regels blijven ongewijzigd (``DROP TABLE`` vuurt geen verwijdertrigger af)."""
    doelen = ",".join(f"'{d}'" for d in WF_TEST_PURPOSES)
    kolommen = ("id, experiment_id, window_id, wf_segment_id, hypothesis_family_id, dataset_id, "
                "dataset_hash, test_start_ts, test_end_ts, accessed_at, purpose, access_type, "
                "accessor_context, prior_access_count, data_reused, overlapping_prior_count, "
                "overlap_seconds, overlap_bars")
    return [
        """CREATE TABLE IF NOT EXISTS assessments (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               status TEXT NOT NULL CHECK (status IN ('PENDING','CALCULATING','COMPLETED','FAILED')),
               assessment_schema_version INTEGER NOT NULL, assessment_rules_version INTEGER NOT NULL,
               test_access_schema_version INTEGER NOT NULL,
               dataset_id INTEGER, dataset_hash TEXT, hypothesis_family_id TEXT,
               versions_json TEXT, raw_classification TEXT, classification_ceiling TEXT,
               fidelity_ceiling TEXT, final_classification TEXT, classification_explanation TEXT,
               test_access_count INTEGER, data_reused INTEGER, overlapping_test_data INTEGER,
               trace_json TEXT, input_json TEXT, rulebook_json TEXT, family_snapshot_json TEXT,
               error TEXT, created_at TEXT NOT NULL, completed_at TEXT,
               CHECK (status <> 'COMPLETED' OR final_classification IS NOT NULL))""",
        """CREATE TRIGGER IF NOT EXISTS ass_insert_pending BEFORE INSERT ON assessments
           WHEN NEW.status <> 'PENDING'
           BEGIN SELECT RAISE(ABORT, 'een beoordeling begint als PENDING'); END""",
        """CREATE TRIGGER IF NOT EXISTS ass_transition BEFORE UPDATE OF status ON assessments
           WHEN NEW.status IS NOT OLD.status AND NOT (
             (OLD.status = 'PENDING' AND NEW.status IN ('CALCULATING','FAILED'))
             OR (OLD.status = 'CALCULATING' AND NEW.status IN ('COMPLETED','FAILED')))
           BEGIN SELECT RAISE(ABORT, 'illegale beoordelingsovergang'); END""",
        """CREATE TRIGGER IF NOT EXISTS ass_immutable BEFORE UPDATE ON assessments
           WHEN OLD.status IN ('COMPLETED','FAILED')
           BEGIN SELECT RAISE(ABORT, 'een afgesloten beoordeling is onveranderlijk'); END""",
        """CREATE TRIGGER IF NOT EXISTS ass_no_delete BEFORE DELETE ON assessments
           BEGIN SELECT RAISE(ABORT, 'een beoordeling wordt niet verwijderd'); END""",
        """CREATE TABLE IF NOT EXISTS assessment_components (
               assessment_id INTEGER NOT NULL REFERENCES assessments(id),
               component_code TEXT NOT NULL, component_version INTEGER NOT NULL,
               status TEXT NOT NULL, measured_value TEXT, unit TEXT, sample_size INTEGER,
               required_condition TEXT NOT NULL, blocking INTEGER NOT NULL CHECK (blocking IN (0,1)),
               explanation TEXT NOT NULL, details_json TEXT NOT NULL,
               source_result_ids_json TEXT NOT NULL, source_window_ids_json TEXT NOT NULL,
               PRIMARY KEY (assessment_id, component_code)) WITHOUT ROWID""",
        """CREATE TABLE IF NOT EXISTS assessment_sources (
               assessment_id INTEGER NOT NULL REFERENCES assessments(id),
               wf_result_id INTEGER NOT NULL REFERENCES wf_results(id),
               kind TEXT NOT NULL, window_id INTEGER NOT NULL, result_hash TEXT NOT NULL,
               PRIMARY KEY (assessment_id, wf_result_id)) WITHOUT ROWID""",
        """CREATE TABLE IF NOT EXISTS assessment_annotations (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               assessment_id INTEGER NOT NULL REFERENCES assessments(id),
               kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL)""",
        *[f"""CREATE TRIGGER IF NOT EXISTS {t}_insert_calculating BEFORE INSERT ON {t}
           WHEN (SELECT status FROM assessments WHERE id = NEW.assessment_id) <> 'CALCULATING'
           BEGIN SELECT RAISE(ABORT, '{t}: alleen tijdens het berekenen'); END"""
          for t in ("assessment_components", "assessment_sources")],
        *[f"""CREATE TRIGGER IF NOT EXISTS {t}_no_{w} BEFORE {w.upper()} ON {t}
           BEGIN SELECT RAISE(ABORT, '{t} is onveranderlijk'); END"""
          for t in ("assessment_components", "assessment_sources", "assessment_annotations")
          for w in ("update", "delete")],
        f"""CREATE TABLE wf_test_access_log_v7 (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               window_id INTEGER NOT NULL REFERENCES wf_windows(id),
               wf_segment_id INTEGER NOT NULL REFERENCES wf_segments(id),
               hypothesis_family_id TEXT NOT NULL, dataset_id INTEGER NOT NULL,
               dataset_hash TEXT NOT NULL, test_start_ts INTEGER NOT NULL, test_end_ts INTEGER NOT NULL,
               accessed_at TEXT NOT NULL, purpose TEXT NOT NULL CHECK (purpose IN ({doelen})),
               access_type TEXT NOT NULL CHECK (access_type IN ('TEST_RESULT_READ','OOS_AGGREGATE_READ')),
               accessor_context TEXT NOT NULL CHECK (length(trim(accessor_context)) > 0),
               prior_access_count INTEGER NOT NULL, data_reused INTEGER NOT NULL,
               overlapping_prior_count INTEGER NOT NULL, overlap_seconds INTEGER NOT NULL,
               overlap_bars INTEGER NOT NULL,
               assessment_id INTEGER REFERENCES assessments(id),
               access_schema_version INTEGER NOT NULL DEFAULT 1,
               CHECK (data_reused = (prior_access_count > 0)),
               CHECK ((purpose = 'ASSESSMENT') = (assessment_id IS NOT NULL)))""",
        f"INSERT INTO wf_test_access_log_v7 ({kolommen}) SELECT {kolommen} FROM wf_test_access_log",
        "DROP TABLE wf_test_access_log",
        "ALTER TABLE wf_test_access_log_v7 RENAME TO wf_test_access_log",
        """CREATE TRIGGER wftal_no_update BEFORE UPDATE ON wf_test_access_log
           BEGIN SELECT RAISE(ABORT, 'wf_test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER wftal_no_delete BEFORE DELETE ON wf_test_access_log
           BEGIN SELECT RAISE(ABORT, 'wf_test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER wftal_only_test BEFORE INSERT ON wf_test_access_log
           WHEN (SELECT kind FROM wf_segments WHERE id = NEW.wf_segment_id) <> 'TEST'
             OR (SELECT status FROM experiments WHERE id = NEW.experiment_id) <> 'completed'
           BEGIN SELECT RAISE(ABORT, 'alleen het TEST-venster van een voltooid experiment'); END""",

    ]


def _schema_v8() -> list[str]:
    """Vergelijkingen (reference tegenover challenger). Het toegangslog wordt
    opnieuw herbouwd voor het doel COMPARISON en de koppeling aan een vergelijking."""
    doelen = ",".join(f"'{d}'" for d in WF_TEST_PURPOSES)
    oud = ("id, experiment_id, window_id, wf_segment_id, hypothesis_family_id, dataset_id, "
           "dataset_hash, test_start_ts, test_end_ts, accessed_at, purpose, access_type, "
           "accessor_context, prior_access_count, data_reused, overlapping_prior_count, "
           "overlap_seconds, overlap_bars, assessment_id, access_schema_version")
    terminaal = "('COMPLETED','FAILED')"
    def kind(t, extra):
        return (f"CREATE TABLE IF NOT EXISTS {t} (comparison_id INTEGER NOT NULL "
                f"REFERENCES comparisons(id), {extra}")
    return [
        """CREATE TABLE IF NOT EXISTS comparisons (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               status TEXT NOT NULL CHECK (status IN ('PENDING','CHECKING','CALCULATING','COMPLETED','FAILED')),
               mode TEXT NOT NULL CHECK (mode IN ('ASSESSMENT_COMPARISON','DEEP_RESULT_COMPARISON')),
               reference_experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               challenger_experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               reference_assessment_id INTEGER NOT NULL REFERENCES assessments(id),
               challenger_assessment_id INTEGER NOT NULL REFERENCES assessments(id),
               reference_dataset_id INTEGER, challenger_dataset_id INTEGER,
               reference_dataset_hash TEXT, challenger_dataset_hash TEXT,
               comparison_schema_version INTEGER NOT NULL, comparison_rules_version INTEGER NOT NULL,
               test_access_schema_version INTEGER NOT NULL,
               comparability_status TEXT, comparability_reasons_json TEXT, flags_json TEXT,
               result TEXT CHECK (result IS NULL OR result IN ('COMPARED','INSUFFICIENT_COMPARABILITY')),
               explanation TEXT, trace_json TEXT, input_json TEXT, error TEXT,
               created_at TEXT NOT NULL, completed_at TEXT,
               CHECK (status <> 'COMPLETED' OR (comparability_status IS NOT NULL
                      AND trace_json IS NOT NULL AND result IS NOT NULL)))""",
        """CREATE TRIGGER IF NOT EXISTS cmp_insert_pending BEFORE INSERT ON comparisons
           WHEN NEW.status <> 'PENDING'
           BEGIN SELECT RAISE(ABORT, 'een vergelijking begint als PENDING'); END""",
        """CREATE TRIGGER IF NOT EXISTS cmp_transition BEFORE UPDATE OF status ON comparisons
           WHEN NEW.status IS NOT OLD.status AND NOT (
             (OLD.status = 'PENDING' AND NEW.status IN ('CHECKING','FAILED'))
             OR (OLD.status = 'CHECKING' AND NEW.status IN ('CALCULATING','FAILED'))
             OR (OLD.status = 'CALCULATING' AND NEW.status IN ('COMPLETED','FAILED')))
           BEGIN SELECT RAISE(ABORT, 'illegale vergelijkingsovergang'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS cmp_immutable BEFORE UPDATE ON comparisons
           WHEN OLD.status IN {terminaal}
           BEGIN SELECT RAISE(ABORT, 'een afgesloten vergelijking is onveranderlijk'); END""",
        """CREATE TRIGGER IF NOT EXISTS cmp_no_delete BEFORE DELETE ON comparisons
           BEGIN SELECT RAISE(ABORT, 'een vergelijking wordt niet verwijderd'); END""",
        kind("comparison_checks", """check_code TEXT NOT NULL, severity TEXT NOT NULL,
               reference TEXT, challenger TEXT, status TEXT NOT NULL,
               PRIMARY KEY (comparison_id, check_code)) WITHOUT ROWID"""),
        kind("comparison_items", """section TEXT NOT NULL, item_key TEXT NOT NULL,
               reference TEXT, challenger TEXT, absolute_delta REAL, relative_delta REAL,
               status TEXT NOT NULL, explanation TEXT NOT NULL, details_json TEXT NOT NULL,
               PRIMARY KEY (comparison_id, section, item_key)) WITHOUT ROWID"""),
        kind("comparison_sources", """side TEXT NOT NULL, kind TEXT NOT NULL, source_id INTEGER NOT NULL,
               source_hash TEXT, PRIMARY KEY (comparison_id, side, kind, source_id)) WITHOUT ROWID"""),
        """CREATE TABLE IF NOT EXISTS comparison_annotations (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               comparison_id INTEGER NOT NULL REFERENCES comparisons(id),
               kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL)""",
        *[f"""CREATE TRIGGER IF NOT EXISTS {t}_insert_calculating BEFORE INSERT ON {t}
           WHEN (SELECT status FROM comparisons WHERE id = NEW.comparison_id) <> 'CALCULATING'
           BEGIN SELECT RAISE(ABORT, '{t}: alleen tijdens het berekenen'); END"""
          for t in ("comparison_checks", "comparison_items", "comparison_sources")],
        *[f"""CREATE TRIGGER IF NOT EXISTS {t}_no_{w} BEFORE {w.upper()} ON {t}
           BEGIN SELECT RAISE(ABORT, '{t} is onveranderlijk'); END"""
          for t in ("comparison_checks", "comparison_items", "comparison_sources",
                    "comparison_annotations") for w in ("update", "delete")],

        f"""CREATE TABLE wf_test_access_log_v8 (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               window_id INTEGER NOT NULL REFERENCES wf_windows(id),
               wf_segment_id INTEGER NOT NULL REFERENCES wf_segments(id),
               hypothesis_family_id TEXT NOT NULL, dataset_id INTEGER NOT NULL,
               dataset_hash TEXT NOT NULL, test_start_ts INTEGER NOT NULL, test_end_ts INTEGER NOT NULL,
               accessed_at TEXT NOT NULL, purpose TEXT NOT NULL CHECK (purpose IN ({doelen})),
               access_type TEXT NOT NULL CHECK (access_type IN ('TEST_RESULT_READ','OOS_AGGREGATE_READ')),
               accessor_context TEXT NOT NULL CHECK (length(trim(accessor_context)) > 0),
               prior_access_count INTEGER NOT NULL, data_reused INTEGER NOT NULL,
               overlapping_prior_count INTEGER NOT NULL, overlap_seconds INTEGER NOT NULL,
               overlap_bars INTEGER NOT NULL,
               assessment_id INTEGER REFERENCES assessments(id),
               access_schema_version INTEGER NOT NULL DEFAULT 1,
               comparison_id INTEGER REFERENCES comparisons(id),
               CHECK (data_reused = (prior_access_count > 0)),
               CHECK ((purpose = 'ASSESSMENT') = (assessment_id IS NOT NULL)),
               CHECK ((purpose = 'COMPARISON') = (comparison_id IS NOT NULL)))""",
        f"INSERT INTO wf_test_access_log_v8 ({oud}) SELECT {oud} FROM wf_test_access_log",
        "DROP TABLE wf_test_access_log",
        "ALTER TABLE wf_test_access_log_v8 RENAME TO wf_test_access_log",
        """CREATE TRIGGER wftal_no_update BEFORE UPDATE ON wf_test_access_log
           BEGIN SELECT RAISE(ABORT, 'wf_test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER wftal_no_delete BEFORE DELETE ON wf_test_access_log
           BEGIN SELECT RAISE(ABORT, 'wf_test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER wftal_only_test BEFORE INSERT ON wf_test_access_log
           WHEN (SELECT kind FROM wf_segments WHERE id = NEW.wf_segment_id) <> 'TEST'
             OR (SELECT status FROM experiments WHERE id = NEW.experiment_id) <> 'completed'
           BEGIN SELECT RAISE(ABORT, 'alleen het TEST-venster van een voltooid experiment'); END""",
    ]


#: Doelen van een TEST-toegang, met waar ze gelden. Bron van waarheid voor de
#: tabel ``access_purposes`` (schema 9). Een nieuw doel komt hier bij én in een
#: nieuwe migratie als ``INSERT OR IGNORE`` - nooit meer een tabelherbouw.
#: ``OOS_AGGREGATE_READ`` is geen doel maar een ``access_type``.
ACCESS_PURPOSES: tuple[tuple[str, int, int], ...] = (
    # (code, geldig voor segmentlog, geldig voor walk-forwardlog)
    ("FINAL_EVALUATION", 1, 1),
    ("REPRODUCTION_REVIEW", 1, 1),
    ("AUDIT", 1, 1),
    ("DEBUG_AFTER_FAILURE", 1, 1),
    ("ASSESSMENT", 0, 1),
    ("COMPARISON", 0, 1),
)


def _schema_v9() -> list[str]:
    """Doelen als referentietabel; idempotentie van Lab-acties.

    De vorige drie schemaversies herbouwden ``wf_test_access_log`` alleen om
    een doel aan een CHECK toe te voegen. Deze herbouw is de laatste: daarna
    verwijzen beide logs met een foreign key naar ``access_purposes``, en een
    trigger bewaakt in welke log een doel mag. Bestaande regels gaan
    ongewijzigd mee; de alleen-toevoegen-triggers komen terug.
    """
    tal = ("id, experiment_id, segment_id, hypothesis_family_id, dataset_id, dataset_hash, "
           "test_start_ts, test_end_ts, accessed_at, purpose, access_type, accessor_context, "
           "prior_access_count, data_reused")
    wf = ("id, experiment_id, window_id, wf_segment_id, hypothesis_family_id, dataset_id, "
          "dataset_hash, test_start_ts, test_end_ts, accessed_at, purpose, access_type, "
          "accessor_context, prior_access_count, data_reused, overlapping_prior_count, "
          "overlap_seconds, overlap_bars, assessment_id, access_schema_version, comparison_id")
    stappen = [
        """CREATE TABLE access_purposes (
               code TEXT PRIMARY KEY CHECK (code = upper(code) AND length(code) > 0),
               segment_log INTEGER NOT NULL CHECK (segment_log IN (0,1)),
               walk_forward_log INTEGER NOT NULL CHECK (walk_forward_log IN (0,1)),
               registered_in_schema INTEGER NOT NULL
           ) WITHOUT ROWID""",
        *[f"INSERT OR IGNORE INTO access_purposes VALUES ('{c}', {s}, {w}, 9)"
          for c, s, w in ACCESS_PURPOSES],
        """CREATE TRIGGER ap_no_update BEFORE UPDATE ON access_purposes
           BEGIN SELECT RAISE(ABORT, 'access_purposes is alleen toe te voegen'); END""",
        """CREATE TRIGGER ap_no_delete BEFORE DELETE ON access_purposes
           BEGIN SELECT RAISE(ABORT, 'access_purposes is alleen toe te voegen'); END""",

        """CREATE TABLE test_access_log_v9 (
               id                   INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id        INTEGER NOT NULL REFERENCES experiments(id),
               segment_id           INTEGER NOT NULL REFERENCES experiment_segments(id),
               hypothesis_family_id TEXT NOT NULL,
               dataset_id           INTEGER NOT NULL REFERENCES datasets(id),
               dataset_hash         TEXT NOT NULL,
               test_start_ts        INTEGER NOT NULL,
               test_end_ts          INTEGER NOT NULL,
               accessed_at          TEXT NOT NULL,
               purpose              TEXT NOT NULL REFERENCES access_purposes(code),
               access_type          TEXT NOT NULL CHECK (access_type = 'TEST_RESULT_READ'),
               accessor_context     TEXT NOT NULL CHECK (length(trim(accessor_context)) > 0),
               prior_access_count   INTEGER NOT NULL CHECK (prior_access_count >= 0),
               data_reused          INTEGER NOT NULL CHECK (data_reused IN (0,1)),
               CHECK (data_reused = (prior_access_count > 0))
           )""",
        f"INSERT INTO test_access_log_v9 ({tal}) SELECT {tal} FROM test_access_log",
        "DROP TABLE test_access_log",
        "ALTER TABLE test_access_log_v9 RENAME TO test_access_log",
        """CREATE TRIGGER tal_no_update BEFORE UPDATE ON test_access_log
           BEGIN SELECT RAISE(ABORT, 'test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER tal_no_delete BEFORE DELETE ON test_access_log
           BEGIN SELECT RAISE(ABORT, 'test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER tal_only_test
           BEFORE INSERT ON test_access_log
           WHEN (SELECT kind FROM experiment_segments WHERE id = NEW.segment_id) <> 'TEST'
             OR (SELECT status FROM experiments WHERE id = NEW.experiment_id) <> 'completed'
           BEGIN SELECT RAISE(ABORT, 'alleen het TEST-segment van een voltooid experiment'); END""",
        """CREATE TRIGGER tal_purpose_scope BEFORE INSERT ON test_access_log
           WHEN COALESCE((SELECT segment_log FROM access_purposes WHERE code = NEW.purpose), 0) <> 1
           BEGIN SELECT RAISE(ABORT, 'doel geldt niet voor de segmentlog'); END""",

        """CREATE TABLE wf_test_access_log_v9 (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               experiment_id INTEGER NOT NULL REFERENCES experiments(id),
               window_id INTEGER NOT NULL REFERENCES wf_windows(id),
               wf_segment_id INTEGER NOT NULL REFERENCES wf_segments(id),
               hypothesis_family_id TEXT NOT NULL, dataset_id INTEGER NOT NULL,
               dataset_hash TEXT NOT NULL, test_start_ts INTEGER NOT NULL, test_end_ts INTEGER NOT NULL,
               accessed_at TEXT NOT NULL,
               purpose TEXT NOT NULL REFERENCES access_purposes(code),
               access_type TEXT NOT NULL CHECK (access_type IN ('TEST_RESULT_READ','OOS_AGGREGATE_READ')),
               accessor_context TEXT NOT NULL CHECK (length(trim(accessor_context)) > 0),
               prior_access_count INTEGER NOT NULL, data_reused INTEGER NOT NULL,
               overlapping_prior_count INTEGER NOT NULL, overlap_seconds INTEGER NOT NULL,
               overlap_bars INTEGER NOT NULL,
               assessment_id INTEGER REFERENCES assessments(id),
               access_schema_version INTEGER NOT NULL DEFAULT 1,
               comparison_id INTEGER REFERENCES comparisons(id),
               CHECK (data_reused = (prior_access_count > 0)),
               CHECK ((purpose = 'ASSESSMENT') = (assessment_id IS NOT NULL)),
               CHECK ((purpose = 'COMPARISON') = (comparison_id IS NOT NULL)))""",
        f"INSERT INTO wf_test_access_log_v9 ({wf}) SELECT {wf} FROM wf_test_access_log",
        "DROP TABLE wf_test_access_log",
        "ALTER TABLE wf_test_access_log_v9 RENAME TO wf_test_access_log",
        """CREATE TRIGGER wftal_no_update BEFORE UPDATE ON wf_test_access_log
           BEGIN SELECT RAISE(ABORT, 'wf_test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER wftal_no_delete BEFORE DELETE ON wf_test_access_log
           BEGIN SELECT RAISE(ABORT, 'wf_test_access_log is alleen toe te voegen'); END""",
        """CREATE TRIGGER wftal_only_test BEFORE INSERT ON wf_test_access_log
           WHEN (SELECT kind FROM wf_segments WHERE id = NEW.wf_segment_id) <> 'TEST'
             OR (SELECT status FROM experiments WHERE id = NEW.experiment_id) <> 'completed'
           BEGIN SELECT RAISE(ABORT, 'alleen het TEST-venster van een voltooid experiment'); END""",
        """CREATE TRIGGER wftal_purpose_scope BEFORE INSERT ON wf_test_access_log
           WHEN COALESCE((SELECT walk_forward_log FROM access_purposes WHERE code = NEW.purpose), 0) <> 1
           BEGIN SELECT RAISE(ABORT, 'doel geldt niet voor de walk-forwardlog'); END""",

        # Idempotentie van acties uit Home Assistant. Begrensd: wat ouder is
        # dan LAB_REQUEST_TTL_DAYS of boven LAB_REQUEST_MAX uitkomt, wordt bij
        # het vastleggen van een nieuw verzoek opgeruimd.
        """CREATE TABLE lab_requests (
               request_id   TEXT PRIMARY KEY CHECK (length(request_id) BETWEEN 8 AND 64),
               action       TEXT NOT NULL,
               payload_hash TEXT NOT NULL,
               object_id    INTEGER,
               response     TEXT NOT NULL,
               created_at   TEXT NOT NULL
           )""",
    ]
    return stappen


MIGRATIONS: dict[int, list[str]] = {
    1: _schema_v1(), 2: _schema_v2(), 3: _schema_v3(), 4: _schema_v4(),
    5: _schema_v5(), 6: _schema_v6(), 7: _schema_v7(), 8: _schema_v8(),
    9: _schema_v9(),
}

#: Bewaartermijn en maximum voor ``lab_requests``.
LAB_REQUEST_TTL_DAYS = 30
LAB_REQUEST_MAX = 1000


class LabDatabase:
    """Het databasebestand van het Lab."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.conn: sqlite3.Connection | None = None

    # -- openen ------------------------------------------------------------- #

    def open(self, recover: bool = False) -> "LabDatabase":
        """Open de database.

        ``recover`` alleen bij het opstarten: dan wordt alles wat nog
        ``running`` stond ``interrupted``. Niet bij elke opening - anders
        onderbreekt elk stuk code dat de database opent een lopend experiment.
        Dat gebeurde toen de runner in fase 3 een eigen verbinding opende.
        """
        try:
            self.conn = sqlite3.connect(
                self.path, isolation_level=None, check_same_thread=False,
            )
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            if self.conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise LabDatabaseError("foreign keys niet in te schakelen")
            controle = self.conn.execute("PRAGMA quick_check").fetchone()[0]
            if controle != "ok":
                raise LabDatabaseError(f"integriteitscontrole mislukt: {controle}")
            self._migrate()
            if recover:
                self.recover_interrupted()
        except sqlite3.DatabaseError as err:
            self.close()
            raise LabDatabaseError(f"Lab-database onbruikbaar: {err}") from err
        return self

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def schema_version(self) -> int:
        rij = self.conn.execute(
            "SELECT value FROM lab_meta WHERE key='schema_version'"
        ).fetchone()
        return int(rij[0]) if rij else 0

    def experiment_count(self) -> int:
        """Hoeveel experimenten er zijn geregistreerd. Alleen lezen.

        Bestaat voor de statusregel van het paneel (fase 9A): een onschuldige
        waarde die aantoont dat de database werkelijk gelezen wordt, zonder
        inhoud, resultaten of TEST-gegevens te tonen.
        """
        return int(self.conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0])

    def access_purposes(self) -> list[dict]:
        """De geregistreerde doelen. Alleen lezen."""
        return [dict(r) for r in self.conn.execute(
            "SELECT code, segment_log, walk_forward_log, registered_in_schema "
            "FROM access_purposes ORDER BY code")]

    def request_lookup(self, request_id: str) -> dict | None:
        """Een eerder verwerkt verzoek, of None."""
        rij = self.conn.execute(
            "SELECT request_id, action, payload_hash, object_id, response FROM lab_requests "
            "WHERE request_id=?", (request_id,)).fetchone()
        return dict(rij) if rij else None

    def request_store(self, request_id: str, action: str, payload_hash: str,
                      object_id: int | None, response: str) -> None:
        """Leg een verwerkt verzoek vast en ruim verlopen verzoeken op."""
        grens = (datetime.now(timezone.utc) - timedelta(days=LAB_REQUEST_TTL_DAYS)).isoformat()
        with self.conn:
            self.conn.execute("DELETE FROM lab_requests WHERE created_at < ?", (grens,))
            self.conn.execute(
                "DELETE FROM lab_requests WHERE request_id IN (SELECT request_id FROM "
                "lab_requests ORDER BY created_at DESC LIMIT -1 OFFSET ?)", (LAB_REQUEST_MAX - 1,))
            self.conn.execute(
                "INSERT INTO lab_requests VALUES (?,?,?,?,?,?)",
                (request_id, action, payload_hash, object_id, response, _nu()))

    def _migrate(self) -> None:
        """Transactioneel en idempotent: elke versie in één transactie."""
        huidig = 0
        bestaat = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_meta'"
        ).fetchone()
        if bestaat:
            huidig = self.schema_version()
        for versie in sorted(MIGRATIONS):
            if versie <= huidig:
                continue
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                for stap in MIGRATIONS[versie]:
                    self.conn.execute(stap)
                self.conn.execute(
                    "INSERT OR REPLACE INTO lab_meta(key, value) "
                    "VALUES ('schema_version', ?)", (str(versie),),
                )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    # -- experimenten ------------------------------------------------------- #

    def create(self, exp: Experiment) -> int:
        if exp.hypothesis_family_id:
            exp.hypothesis_family_id = normalize_family_id(exp.hypothesis_family_id)
        """Een nieuw experiment, altijd als draft."""
        cur = self.conn.execute(
            """INSERT INTO experiments
               (name, description, type, status, hypothesis, expected_effect,
                primary_metric, secondary_metrics, evaluation_method,
                hypothesis_family_id, software_version, strategy_version,
                execution_semantics_version, config_hash, created_at,
                reproduced_from, dataset_id)
               VALUES (?,?,?, 'draft', ?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (exp.name, exp.description, exp.type, exp.hypothesis,
             exp.expected_effect, exp.primary_metric,
             canonical_json(list(exp.secondary_metrics)), exp.evaluation_method,
             exp.hypothesis_family_id, exp.software_version,
             exp.strategy_version, exp.execution_semantics_version,
             exp.config_hash, _nu(), exp.reproduced_from, exp.dataset_id),
        )
        return int(cur.lastrowid)

    def get(self, experiment_id: int) -> Experiment | None:
        rij = self.conn.execute(
            "SELECT * FROM experiments WHERE id=?", (experiment_id,)
        ).fetchone()
        if rij is None:
            return None
        velden = dict(rij)
        velden["secondary_metrics"] = json.loads(velden["secondary_metrics"])
        return Experiment(**velden)

    def update_draft(self, experiment_id: int, **velden) -> None:
        """Velden van een draft wijzigen. Na registratie weigert de database."""
        if "status" in velden:
            raise ValueError("de status verandert alleen via transition()")
        if "secondary_metrics" in velden:
            velden["secondary_metrics"] = canonical_json(list(velden["secondary_metrics"]))
        if velden.get("hypothesis_family_id"):
            velden["hypothesis_family_id"] = normalize_family_id(velden["hypothesis_family_id"])
        if not velden:
            return
        toewijzing = ", ".join(f"{k}=?" for k in velden)
        self.conn.execute(
            f"UPDATE experiments SET {toewijzing} WHERE id=?",
            (*velden.values(), experiment_id),
        )

    def transition(self, experiment_id: int, naar: Status | str,
                   error: str | None = None) -> None:
        """De enige manier om een status te veranderen.

        Python controleert eerst; de database controleert daarna opnieuw. Een
        overgang die hier doorheen glipt, weigert de trigger alsnog.
        """
        exp = self.get(experiment_id)
        if exp is None:
            raise LabDatabaseError(f"experiment {experiment_id} bestaat niet")
        naar = Status(naar)
        check_transition(exp.status, naar)

        nu = _nu()
        extra: dict = {}
        if naar is Status.REGISTERED:
            extra = {"registered_at": nu, "locked_at": nu}
            self.conn.execute(
                "UPDATE experiment_segments SET locked_at=? WHERE experiment_id=?",
                (nu, experiment_id),
            )
        elif naar is Status.RUNNING:
            extra = {"started_at": nu}
        elif naar in TERMINAL:
            extra = {"finished_at": nu}
            if error is not None:
                extra["error"] = error
        toewijzing = ", ".join(["status=?"] + [f"{k}=?" for k in extra])
        self.conn.execute(
            f"UPDATE experiments SET {toewijzing} WHERE id=?",
            (naar.value, *extra.values(), experiment_id),
        )

    def delete_draft(self, experiment_id: int) -> None:
        self.conn.execute("DELETE FROM experiments WHERE id=?", (experiment_id,))

    def recover_interrupted(self) -> int:
        """Wat bij het openen nog ``running`` is, was bezig tijdens een herstart.

        Het wordt ``interrupted`` - nooit ``completed``. Hervatten bestaat niet;
        een nieuwe poging is een reproductie.
        """
        rijen = self.conn.execute(
            "SELECT id FROM experiments WHERE status='running'"
        ).fetchall()
        for rij in rijen:
            self.end_run(
                rij["id"], Status.INTERRUPTED,
                "onderbroken: het Lab werd heropend terwijl dit experiment liep",
            )
        return len(rijen)

    # -- parameters --------------------------------------------------------- #

    def add_parameters(self, experiment_id: int, role: str, config: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO experiment_parameters "
            "(experiment_id, role, config_json, config_hash) VALUES (?,?,?,?)",
            (experiment_id, role, canonical_json(config), config_hash(config)),
        )
        return int(cur.lastrowid)

    def parameters(self, experiment_id: int) -> list[dict]:
        return [
            {**dict(r), "config": json.loads(r["config_json"])}
            for r in self.conn.execute(
                "SELECT * FROM experiment_parameters WHERE experiment_id=? ORDER BY id",
                (experiment_id,),
            ).fetchall()
        ]

    # -- aantekeningen ------------------------------------------------------ #

    def annotate(self, experiment_id: int, kind: str, text: str) -> int:
        """Aantekening toevoegen - ook bij een afgesloten experiment."""
        cur = self.conn.execute(
            "INSERT INTO experiment_annotations (experiment_id, kind, text, created_at) "
            "VALUES (?,?,?,?)", (experiment_id, kind, text, _nu()),
        )
        return int(cur.lastrowid)

    def annotations(self, experiment_id: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM experiment_annotations WHERE experiment_id=? ORDER BY id",
            (experiment_id,),
        ).fetchall()]

    # -- reproduceren ------------------------------------------------------- #

    def reproduce(self, original_id: int, provenance: dict) -> int:
        """Een nieuw experiment op basis van een bestaand, als draft.

        Het origineel verandert niet. De reproductie hoort bij dezelfde
        hypothesefamilie, neemt de vraag en de parameters over, en krijgt de
        provenance van de software die hem nu maakt - niet die van toen.
        """
        orig = self.get(original_id)
        if orig is None:
            raise LabDatabaseError(f"experiment {original_id} bestaat niet")
        nieuw = Experiment(
            name=f"{orig.name} (reproductie van #{original_id})",
            description=orig.description, type=orig.type,
            hypothesis=orig.hypothesis, expected_effect=orig.expected_effect,
            primary_metric=orig.primary_metric,
            secondary_metrics=list(orig.secondary_metrics),
            evaluation_method=orig.evaluation_method,
            hypothesis_family_id=orig.hypothesis_family_id,
            software_version=provenance.get("software_version", ""),
            strategy_version=provenance.get("strategy_version", ""),
            execution_semantics_version=provenance.get("execution_semantics_version"),
            config_hash=orig.config_hash,
            reproduced_from=original_id,
            # Dezelfde snapshot: een reproductie draait op exact dezelfde data.
            dataset_id=orig.dataset_id,
        )
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            nieuw_id = self.create(nieuw)
            for p in self.parameters(original_id):
                self.add_parameters(nieuw_id, p["role"], p["config"])
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return nieuw_id


    # -- uitvoering ----------------------------------------------------------- #

    def _in_transactie(self, stappen) -> None:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            stappen()
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def begin_run(self, experiment_id: int, executor: str) -> None:
        """queued -> running, en de voortgangsrij, in één transactie."""
        def stappen():
            self.transition(experiment_id, Status.RUNNING)
            self.conn.execute(
                "INSERT INTO experiment_runs (experiment_id, executor, started_at) "
                "VALUES (?,?,?)", (experiment_id, executor, _nu()),
            )
        self._in_transactie(stappen)

    def update_progress(self, experiment_id: int, verwerkt: int, totaal: int) -> None:
        """Voortgang, nooit achteruit en nooit boven 99,9% zolang het loopt:
        100% bestaat pas als het resultaat is opgeslagen."""
        pct = min(99.9, round(verwerkt / totaal * 100, 1)) if totaal else 0.0
        self.conn.execute(
            "UPDATE experiment_runs SET "
            " bars_total = MAX(bars_total, ?), bars_processed = MAX(bars_processed, ?),"
            " progress_pct = MAX(progress_pct, ?), last_progress_at = ? "
            "WHERE experiment_id = ?",
            (totaal, verwerkt, pct, _nu(), experiment_id),
        )

    def run_state(self, experiment_id: int) -> dict | None:
        rij = self.conn.execute(
            "SELECT * FROM experiment_runs WHERE experiment_id=?", (experiment_id,)
        ).fetchone()
        return dict(rij) if rij else None

    def complete_with_result(self, experiment_id: int, resultaat: dict) -> None:
        """Alles in één transactie: resultaat, trades, metrieken,
        uitsplitsingen, afwijzingen, voortgang 100%, completed. Faalt één stap,
        dan wordt alles teruggedraaid en is het experiment níet voltooid. De
        database weigert completed zolang iets ontbreekt."""
        versies = resultaat["versions"]
        trades, metrics = resultaat["trades"], resultaat["metrics"]

        def stappen():
            self.conn.execute(
                "INSERT INTO experiment_results (experiment_id, result_kind, "
                "result_schema_version, backtest_engine_version, cost_model_version, "
                "metrics_version, result_hash, summary_json, trades_json, "
                "provenance_json, cost_model_json, trade_count, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,NULL,?,?,?,?)",
                (experiment_id, NORMALIZED, versies["result_schema_version"],
                 versies["backtest_engine_version"], versies["cost_model_version"],
                 versies["metrics_version"], resultaat["result_hash"],
                 canonical_json(resultaat["summary"]),
                 canonical_json(resultaat["provenance"]),
                 canonical_json(resultaat["cost_model"]), len(trades), _nu()),
            )
            self.conn.executemany(
                f"INSERT INTO experiment_trades (experiment_id, {', '.join(TRADE_FIELDS)}) "
                f"VALUES (?, {', '.join('?' * len(TRADE_FIELDS))})",
                ((experiment_id, *(t[v] for v in TRADE_FIELDS)) for t in trades),
            )
            kolommen = ("metric_name", "metric_version", "value", "unit", "currency",
                        "timezone", "population", "numerator", "denominator",
                        "numerator_definition", "denominator_definition",
                        "sample_size", "calculation_status")
            self.conn.executemany(
                f"INSERT INTO experiment_metrics (experiment_id, {', '.join(kolommen)}) "
                f"VALUES (?, {', '.join('?' * len(kolommen))})",
                ((experiment_id, *(m[k] for k in kolommen)) for m in metrics),
            )
            deel = ("dimension", "label", "timezone", "currency", "trade_count",
                    "sample_size", "wins", "gross", "costs", "net", "win_rate",
                    "win_rate_numerator", "win_rate_denominator", "expectancy")
            self.conn.executemany(
                f"INSERT INTO experiment_breakdowns (experiment_id, {', '.join(deel)}) "
                f"VALUES (?, {', '.join('?' * len(deel))})",
                ((experiment_id, *(b[k] for k in deel)) for b in resultaat["breakdowns"]),
            )
            self.conn.executemany(
                "INSERT INTO experiment_rejections (experiment_id, code, count, share, "
                "denominator) VALUES (?,?,?,?,?)",
                ((experiment_id, r["code"], r["count"], r["share"], r["denominator"])
                 for r in resultaat["rejections"]),
            )
            self.conn.execute(
                "UPDATE experiment_runs SET progress_pct = 100, "
                "bars_processed = MAX(bars_processed, bars_total), finished_at = ? "
                "WHERE experiment_id = ?", (_nu(), experiment_id),
            )
            # Een reproductie onder andere versies is een nieuw experiment,
            # maar niet exact dezelfde uitvoeringsomgeving. Dat komt als
            # aantekening vast te liggen, in dezelfde transactie.
            verschil = self._andere_omgeving(experiment_id, versies)
            if verschil:
                self.annotate(
                    experiment_id, "uitvoeringsomgeving",
                    "Niet exact dezelfde uitvoeringsomgeving als het origineel: "
                    + "; ".join(verschil),
                )
            self.transition(experiment_id, Status.COMPLETED)
        self._in_transactie(stappen)

    def result(self, experiment_id: int) -> dict | None:
        """Het opgeslagen resultaat. Een oud resultaat blijft oud: geen
        metrieken, en dat is zichtbaar aan ``result_kind``."""
        rij = self.conn.execute(
            "SELECT * FROM experiment_results WHERE experiment_id=?", (experiment_id,)
        ).fetchone()
        if rij is None:
            return None
        uit = {
            "result_kind": rij["result_kind"],
            "versions": {k: rij[k] for k in ("result_schema_version", "backtest_engine_version",
                                              "cost_model_version", "metrics_version")},
            "result_hash": rij["result_hash"],
            "summary": json.loads(rij["summary_json"]),
            "provenance": json.loads(rij["provenance_json"]),
            "trade_count": rij["trade_count"],
        }
        if rij["result_kind"] == LEGACY:
            uit["trades"] = json.loads(rij["trades_json"])
            return uit
        uit["cost_model"] = json.loads(rij["cost_model_json"])
        uit["trades"] = [
            {v: r[v] for v in TRADE_FIELDS}
            for r in self.conn.execute(
                "SELECT * FROM experiment_trades WHERE experiment_id=? ORDER BY sequence_number",
                (experiment_id,)).fetchall()
        ]
        uit["metrics"] = {
            r["metric_name"]: dict(r) for r in self.conn.execute(
                "SELECT * FROM experiment_metrics WHERE experiment_id=?", (experiment_id,))
        }
        uit["breakdowns"] = [dict(r) for r in self.conn.execute(
            "SELECT * FROM experiment_breakdowns WHERE experiment_id=? "
            "ORDER BY dimension, label", (experiment_id,))]
        uit["rejections"] = [dict(r) for r in self.conn.execute(
            "SELECT * FROM experiment_rejections WHERE experiment_id=? ORDER BY code",
            (experiment_id,))]
        return uit

    # -- segmenten ----------------------------------------------------------- #

    def save_segment_plan(self, experiment_id: int, plan: SegmentPlan) -> None:
        """Het plan vastleggen; alleen zolang het experiment draft is.

        Een eerder plan van dezelfde draft wordt vervangen. Na registratie
        weigert de database elke wijziging.
        """
        exp = self.get(experiment_id)
        if exp is None:
            raise LabDatabaseError(f"experiment {experiment_id} bestaat niet")
        ds = self.dataset(plan.dataset_id)
        if ds is None or ds["hash"] != plan.dataset_hash:
            raise LabDatabaseError("het plan hoort niet bij een bestaande dataset")
        if exp.dataset_id != plan.dataset_id:
            raise LabDatabaseError("het plan hoort bij een andere dataset dan het experiment")
        d = plan.as_dict()

        def stappen():
            self.conn.execute("DELETE FROM segment_plans WHERE experiment_id=?", (experiment_id,))
            self.conn.execute(
                "INSERT INTO segment_plans (experiment_id, dataset_id, dataset_hash, plan_hash, "
                "segment_schema_version, time_unit, boundary_semantics, warmup_rule, "
                "open_cutoff_rule, timeframe, bar_seconds, max_hold_seconds, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (experiment_id, plan.dataset_id, plan.dataset_hash, plan.plan_hash,
                 plan.segment_schema_version, d["time_unit"], d["boundary_semantics"],
                 d["warmup_rule"], d["open_cutoff_rule"], plan.timeframe,
                 plan.bar_seconds, plan.max_hold_seconds, _nu()),
            )
            for seg in plan.segments:
                self.conn.execute(
                    "INSERT INTO experiment_segments (experiment_id, kind, sequence_number, "
                    "start_ts, end_ts, warmup_start_ts, open_cutoff_ts, warmup_bars, "
                    "warmup_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (experiment_id, seg.kind, seg.sequence_number, seg.start_ts,
                     seg.end_ts, seg.warmup_start_ts, seg.open_cutoff_ts,
                     seg.warmup_bars, seg.warmup_status, _nu()),
                )
        self._in_transactie(stappen)

    def segment_plan(self, experiment_id: int) -> dict | None:
        plan = self.conn.execute(
            "SELECT * FROM segment_plans WHERE experiment_id=?", (experiment_id,)
        ).fetchone()
        if plan is None:
            return None
        uit = dict(plan)
        uit["segments"] = [dict(r) for r in self.conn.execute(
            "SELECT * FROM experiment_segments WHERE experiment_id=? ORDER BY sequence_number",
            (experiment_id,),
        ).fetchall()]
        return uit

    def complete_segmented(self, experiment_id: int, resultaat: dict) -> None:
        """Alle segmenten in één transactie opslaan, dan pas completed.

        Faalt één segment, dan wordt alles teruggedraaid. De database weigert
        completed zolang één segment onvolledig is.
        """
        plan = self.segment_plan(experiment_id)
        if plan is None:
            raise LabDatabaseError("geen segmentplan")
        ids = {s["kind"]: s["id"] for s in plan["segments"]}
        versies = resultaat["versions"]
        kostenmodel = canonical_json(resultaat["cost_model"])

        def stappen():
            for seg in resultaat["segments"]:
                sid = ids[seg["kind"]]
                trades = seg["trades"]
                self.conn.execute(
                    "INSERT INTO segment_results (segment_id, experiment_id, kind, result_kind, "
                    "result_hash, summary_json, cost_model_json, result_schema_version, "
                    "backtest_engine_version, cost_model_version, metrics_version, "
                    "segment_schema_version, trade_count, cross_boundary_count, "
                    "warmup_status, created_at, segment_end_close_count, forced_exit_json) "
                    "VALUES (?,?,?,'SEGMENT_RESULT',?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, experiment_id, seg["kind"], seg["result_hash"],
                     canonical_json(seg["summary"]), kostenmodel,
                     versies["result_schema_version"], versies["backtest_engine_version"],
                     versies["cost_model_version"], versies["metrics_version"],
                     versies["segment_schema_version"], len(trades),
                     sum(1 for t in trades if t["cross_boundary"]),
                     seg["warmup_status"], _nu(),
                     seg["forced_exit"]["segment_end_close_count"],
                     canonical_json(seg["forced_exit"])),
                )
                velden = TRADE_FIELDS + ("cross_boundary",)
                self.conn.executemany(
                    f"INSERT INTO segment_trades (segment_id, experiment_id, {', '.join(velden)}) "
                    f"VALUES (?, ?, {', '.join('?' * len(velden))})",
                    [(sid, experiment_id, *(int(t[v]) if v == "cross_boundary" else t[v]
                                            for v in velden)) for t in trades],
                )
                self._segment_rijen("segment_metrics", sid, experiment_id, seg["metrics"])
                self._segment_rijen("segment_breakdowns", sid, experiment_id, seg["breakdowns"])
                self._segment_rijen("segment_rejections", sid, experiment_id, seg["rejections"])
            self.conn.execute(
                "UPDATE experiment_runs SET progress_pct = 100, "
                "bars_processed = MAX(bars_processed, bars_total), "
                "segments_completed = MAX(segments_completed, segments_total), "
                "current_segment = NULL, finished_at = ? WHERE experiment_id = ?",
                (_nu(), experiment_id),
            )
            verschil = self._andere_omgeving(experiment_id, versies)
            if verschil:
                self.annotate(
                    experiment_id, "uitvoeringsomgeving",
                    "Niet exact dezelfde uitvoeringsomgeving als het origineel: "
                    + "; ".join(verschil),
                )
            self.transition(experiment_id, Status.COMPLETED)
        self._in_transactie(stappen)

    def _segment_rijen(self, tabel: str, sid: int, eid: int, rijen: list[dict]) -> None:
        if not rijen:
            return
        kolommen = list(rijen[0])
        self.conn.executemany(
            f"INSERT INTO {tabel} (segment_id, experiment_id, {', '.join(kolommen)}) "
            f"VALUES (?, ?, {', '.join('?' * len(kolommen))})",
            [(sid, eid, *(r[k] for k in kolommen)) for r in rijen],
        )

    def update_segment_progress(self, experiment_id: int, segment: str, voltooid: int,
                                totaal_segmenten: int, verwerkt: int, totaal: int) -> None:
        pct = min(99.9, round(verwerkt / totaal * 100, 1)) if totaal else 0.0
        self.conn.execute(
            "UPDATE experiment_runs SET current_segment = ?, "
            " segments_total = MAX(segments_total, ?), "
            " segments_completed = MAX(segments_completed, ?), "
            " bars_total = MAX(bars_total, ?), bars_processed = MAX(bars_processed, ?), "
            " progress_pct = MAX(progress_pct, ?), last_progress_at = ? "
            "WHERE experiment_id = ?",
            (segment, totaal_segmenten, voltooid, totaal, verwerkt, pct, _nu(), experiment_id),
        )

    # -- testbescherming --------------------------------------------------- #

    def test_status(self, experiment_id: int) -> dict:
        """Of het TEST-segment bestaat, is uitgevoerd en is geopend - zonder
        een enkel TEST-resultaat op te halen. Telt niet als toegang."""
        seg = self.conn.execute(
            "SELECT id FROM experiment_segments WHERE experiment_id=? AND kind='TEST'",
            (experiment_id,),
        ).fetchone()
        if seg is None:
            return {"has_test": False, "status": "NO_TEST_SEGMENT"}
        uitgevoerd = self.conn.execute(
            "SELECT 1 FROM segment_results WHERE segment_id=?", (seg["id"],)
        ).fetchone() is not None
        geopend = self.conn.execute(
            "SELECT COUNT(*) FROM test_access_log WHERE segment_id=?", (seg["id"],)
        ).fetchone()[0]
        if not uitgevoerd:
            status = "TEST_NOT_EXECUTED"
        else:
            status = "TEST_OPENED" if geopend else "TEST_UNOPENED"
        return {"has_test": True, "executed": uitgevoerd, "opened": bool(geopend),
                "access_count": geopend, "status": status}

    def segment_overview(self, experiment_id: int) -> list[dict]:
        """Overzicht per segment. TRAIN en VALIDATION met hun metrieken; TEST
        alleen met zijn status. Haalt geen enkele TEST-waarde op."""
        plan = self.segment_plan(experiment_id)
        if plan is None:
            return []
        uit = []
        for seg in plan["segments"]:
            regel = {k: seg[k] for k in ("kind", "start_ts", "end_ts", "warmup_start_ts",
                                         "open_cutoff_ts", "warmup_bars", "warmup_status")}
            if seg["kind"] == "TEST":
                regel["test"] = self.test_status(experiment_id)
            else:
                regel["metrics"] = self.segment_metrics(seg["id"])
            uit.append(regel)
        return uit

    def segment_metrics(self, segment_id: int) -> dict:
        """Metrieken van een TRAIN- of VALIDATION-segment. Weigert TEST: die
        gaan alleen via ``open_test_result``, met een logregel."""
        seg = self.conn.execute(
            "SELECT kind FROM experiment_segments WHERE id=?", (segment_id,)
        ).fetchone()
        if seg is None:
            raise LabDatabaseError(f"segment {segment_id} bestaat niet")
        if seg["kind"] == "TEST":
            raise SealedTestError("TEST-resultaten alleen via open_test_result")
        return self._lees_metrics(segment_id)

    def _lees_metrics(self, segment_id: int) -> dict:
        return {r["metric_name"]: dict(r) for r in self.conn.execute(
            "SELECT * FROM segment_metrics WHERE segment_id=?", (segment_id,)
        ).fetchall()}

    def open_test_result(self, experiment_id: int, purpose: str, accessor_context: str) -> dict:
        """De enige weg naar TEST-resultaten. Eerst de logregel, dan de data.

        Fail-closed: de logregel en het lezen zitten in één transactie. Mislukt
        het loggen - of het vastleggen ervan - dan komt er geen enkel
        TEST-resultaat naar buiten.
        """
        if purpose not in TEST_PURPOSES:
            raise ValueError(f"onbekend doel: {purpose!r}; kies uit {', '.join(TEST_PURPOSES)}")
        exp = self.get(experiment_id)
        plan = self.segment_plan(experiment_id)
        if exp is None or plan is None:
            raise LabDatabaseError("geen gesegmenteerd experiment")
        test = next(s for s in plan["segments"] if s["kind"] == "TEST")
        data: dict = {}

        def stappen():
            eerder = self.conn.execute(
                "SELECT COUNT(*) FROM test_access_log WHERE hypothesis_family_id=? "
                "AND dataset_hash=? AND test_start_ts=? AND test_end_ts=?",
                (exp.hypothesis_family_id, plan["dataset_hash"],
                 test["start_ts"], test["end_ts"]),
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO test_access_log (experiment_id, segment_id, hypothesis_family_id, "
                "dataset_id, dataset_hash, test_start_ts, test_end_ts, accessed_at, purpose, "
                "access_type, accessor_context, prior_access_count, data_reused) "
                "VALUES (?,?,?,?,?,?,?,?,?,'TEST_RESULT_READ',?,?,?)",
                (experiment_id, test["id"], exp.hypothesis_family_id, plan["dataset_id"],
                 plan["dataset_hash"], test["start_ts"], test["end_ts"], _nu(), purpose,
                 accessor_context, eerder, int(eerder > 0)),
            )
            if eerder:
                self.annotate(
                    experiment_id, "DATA_REUSED",
                    f"TEST-data binnen familie '{exp.hypothesis_family_id}' voor de "
                    f"{eerder + 1}e keer geopend (doel {purpose}); geen onafhankelijke toets.",
                )
            resultaat = self.conn.execute(
                "SELECT * FROM segment_results WHERE segment_id=?", (test["id"],)
            ).fetchone()
            if resultaat is None:
                raise LabDatabaseError("het TEST-segment heeft geen resultaat")
            data.update({
                "segment": dict(test), "result": dict(resultaat),
                "metrics": self._lees_metrics(test["id"]),
                "data_reused": bool(eerder), "prior_access_count": eerder,
            })
        self._in_transactie(stappen)
        return data

    def family_summary(self, family_id: str) -> dict:
        """Hergebruik binnen een hypothesefamilie, zonder oordeel.

        Een geëvalueerde configuratie is de combinatie van configuratiehash,
        dataset, segmentplan en de vier resultaatversies. Een identieke
        reproductie telt daarom niet als nieuwe configuratie; een andere
        configuratiehash wel.
        """
        familie = normalize_family_id(family_id)
        exps = self.conn.execute(
            "SELECT e.id, e.status, e.dataset_id, e.primary_metric, e.config_hash, "
            "e.reproduced_from, p.plan_hash, "
            "(SELECT group_concat(backtest_engine_version || '/' || cost_model_version || '/' "
            "   || metrics_version || '/' || result_schema_version || '/' || segment_schema_version) "
            " FROM (SELECT DISTINCT backtest_engine_version, cost_model_version, metrics_version, "
            "       result_schema_version, segment_schema_version FROM segment_results "
            "       WHERE experiment_id = e.id)) AS versies "
            "FROM experiments e LEFT JOIN segment_plans p ON p.experiment_id = e.id "
            "WHERE e.hypothesis_family_id = ? ORDER BY e.id", (familie,),
        ).fetchall()
        geevalueerd = {
            (r["config_hash"], r["dataset_id"], r["plan_hash"], r["versies"])
            for r in exps if r["status"] == "completed"
        }
        # Walk-forward: een geëvalueerde configuratie is configuratiehash,
        # dataset, plan (kandidatenset en vensterindeling), versies en rol.
        wf = self.conn.execute(
            "SELECT c.config_hash, p.dataset_id, p.candidate_set_hash || '/' || p.window_type || '/' "
            "  || p.first_train_start || '/' || p.train_length || '/' || p.validation_length || '/' "
            "  || p.test_length || '/' || p.step_size || '/' || p.window_count AS plan, "
            "  r.backtest_engine_version || '/' || r.cost_model_version || '/' || r.metrics_version "
            "  || '/' || r.result_schema_version || '/' || r.segment_schema_version || '/' "
            "  || r.walk_forward_schema_version AS versies, r.kind "
            "FROM wf_results r JOIN wf_candidates c ON c.id = r.candidate_id "
            "JOIN wf_plans p ON p.experiment_id = r.experiment_id "
            "JOIN experiments e ON e.id = r.experiment_id WHERE e.hypothesis_family_id = ?",
            (familie,)).fetchall()
        geevalueerd |= {(r["config_hash"], r["dataset_id"], r["plan"], r["versies"])
                        for r in wf if r["kind"] == "TRAIN" or r["kind"] == "TEST"}
        toegang = self.conn.execute(
            "SELECT COUNT(*), MIN(t), MAX(t), SUM(hergebruik), SUM(overlap) FROM ("
            " SELECT accessed_at AS t, data_reused AS hergebruik, 0 AS overlap FROM test_access_log "
            " WHERE hypothesis_family_id=? UNION ALL "
            " SELECT accessed_at, data_reused, overlapping_prior_count > 0 FROM wf_test_access_log "
            " WHERE hypothesis_family_id=?)", (familie, familie),
        ).fetchone()
        tests_uitgevoerd = self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM wf_results r JOIN experiments e ON e.id = r.experiment_id "
            "        WHERE e.hypothesis_family_id = ? AND r.kind = 'TEST') + "
            "       (SELECT COUNT(*) FROM segment_results r JOIN experiments e ON e.id = r.experiment_id "
            "        WHERE e.hypothesis_family_id = ? AND r.kind = 'TEST')", (familie, familie),
        ).fetchone()[0]
        return {
            "hypothesis_family_id": familie,
            "datasets": sorted({r["dataset_id"] for r in exps if r["dataset_id"] is not None}),
            "primary_metrics": sorted({r["primary_metric"] for r in exps if r["primary_metric"]}),
            "configurations": sorted({r["config_hash"] for r in exps if r["config_hash"]}),
            "registered_experiments": sum(1 for r in exps if r["status"] != "draft"),
            "reproductions": sum(1 for r in exps if r["reproduced_from"] is not None),
            "evaluated_configurations": len(geevalueerd),
            "test_accesses": toegang[0], "first_test_access": toegang[1],
            "last_test_access": toegang[2],
            "reused_test_accesses": toegang[3] or 0,
            "overlapping_test_accesses": toegang[4] or 0,
            "candidates_registered": self.conn.execute(
                "SELECT COUNT(*) FROM wf_candidates c JOIN experiments e ON e.id = c.experiment_id "
                "WHERE e.hypothesis_family_id = ?", (familie,)).fetchone()[0],
            "train_runs": sum(1 for r in wf if r["kind"] == "TRAIN"),
            "unique_train_configurations": len({(r["config_hash"], r["dataset_id"], r["plan"], r["versies"])
                                                for r in wf if r["kind"] == "TRAIN"}),
            "test_executions": tests_uitgevoerd,
        }

    # -- walk-forward -------------------------------------------------------- #

    def save_walk_forward(self, experiment_id: int, *, mode: str, window_type: str,
                          windows, rule, first_train_start: int, train_length: int,
                          validation_length: int, test_length: int, step_size: int,
                          max_hold_seconds: int, bar_seconds: int,
                          candidates: list[tuple[str, int]],
                          test_access_policy: str = "SEALED_PER_WINDOW_LOGGED") -> None:
        """Plan, kandidaten, vensters en segmenten vastleggen - alleen als draft.

        ``candidates``: (label, parameter_id) van parameters met rol candidate.
        """
        from .walk_forward import (
            SELECTION_RULE_VERSION, WALK_FORWARD_SCHEMA_VERSION, candidate_set_hash,
        )
        from .segments import SEGMENT_SCHEMA_VERSION
        rule.check()
        exp = self.get(experiment_id)
        if exp is None or exp.dataset_id is None:
            raise LabDatabaseError("experiment zonder dataset")
        ds = self.dataset(exp.dataset_id)
        params = {p["id"]: p for p in self.parameters(experiment_id)}
        kand = []
        for label, pid in candidates:
            if pid not in params or params[pid]["role"] != "candidate":
                raise LabDatabaseError(f"parameter {pid} is geen kandidaat van dit experiment")
            kand.append((label, pid, params[pid]["config_hash"]))
        set_hash = candidate_set_hash([(label, h) for label, _, h in kand])
        r = rule.as_dict()

        def stappen():
            self.conn.execute("DELETE FROM wf_plans WHERE experiment_id=?", (experiment_id,))
            self.conn.execute(
                "INSERT INTO wf_plans (experiment_id, dataset_id, dataset_hash, mode, window_type, "
                "first_train_start, train_length, validation_length, test_length, step_size, "
                "window_count, walk_forward_schema_version, segment_schema_version, "
                "selection_rule_version, selection_rule_json, candidate_set_hash, primary_metric, "
                "selection_direction, tie_break_json, validation_policy, missing_metric_policy, "
                "test_access_policy, max_hold_seconds, bar_seconds, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (experiment_id, exp.dataset_id, ds["hash"], mode, window_type,
                 first_train_start, train_length, validation_length, test_length, step_size,
                 len(windows), WALK_FORWARD_SCHEMA_VERSION, SEGMENT_SCHEMA_VERSION,
                 SELECTION_RULE_VERSION, canonical_json(r), set_hash, r["primary_metric"],
                 r["direction"], canonical_json(r["tie_break"]), r["validation_policy"],
                 r["missing_metric_policy"], test_access_policy, max_hold_seconds,
                 bar_seconds, _nu()),
            )
            for label, pid, h in kand:
                self.conn.execute(
                    "INSERT INTO wf_candidates (experiment_id, parameter_id, candidate_label, "
                    "config_hash, created_at) VALUES (?,?,?,?,?)",
                    (experiment_id, pid, label, h, _nu()))
            for w in windows:
                wid = self.conn.execute(
                    "INSERT INTO wf_windows (experiment_id, window_index, status, updated_at) "
                    "VALUES (?,?,'PENDING',?)", (experiment_id, w.window_index, _nu())).lastrowid
                for seg in w.segments:
                    self.conn.execute(
                        "INSERT INTO wf_segments (window_id, experiment_id, kind, start_ts, end_ts, "
                        "warmup_start_ts, open_cutoff_ts, warmup_bars, warmup_status) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (wid, experiment_id, seg.kind, seg.start_ts, seg.end_ts,
                         seg.warmup_start_ts, seg.open_cutoff_ts, seg.warmup_bars,
                         seg.warmup_status))
        self._in_transactie(stappen)

    def wf_plan(self, experiment_id: int) -> dict | None:
        plan = self.conn.execute("SELECT * FROM wf_plans WHERE experiment_id=?",
                                 (experiment_id,)).fetchone()
        if plan is None:
            return None
        uit = dict(plan)
        uit["candidates"] = [dict(r) for r in self.conn.execute(
            "SELECT c.*, p.config_json FROM wf_candidates c JOIN experiment_parameters p "
            "ON p.id = c.parameter_id WHERE c.experiment_id=? ORDER BY c.id", (experiment_id,))]
        uit["windows"] = []
        for w in self.conn.execute("SELECT * FROM wf_windows WHERE experiment_id=? "
                                   "ORDER BY window_index", (experiment_id,)).fetchall():
            venster = dict(w)
            venster["segments"] = {r["kind"]: dict(r) for r in self.conn.execute(
                "SELECT * FROM wf_segments WHERE window_id=?", (w["id"],))}
            uit["windows"].append(venster)
        return uit

    def set_window_status(self, window_id: int, naar: str, reden: str | None = None) -> None:
        from .walk_forward import WINDOW_ALLOWED
        rij = self.conn.execute("SELECT status FROM wf_windows WHERE id=?", (window_id,)).fetchone()
        if rij is None:
            raise LabDatabaseError(f"venster {window_id} bestaat niet")
        if naar not in WINDOW_ALLOWED.get(rij["status"], ()):
            raise IllegalTransition(f"venster: {rij['status']} -> {naar} is niet toegestaan")
        self.conn.execute("UPDATE wf_windows SET status=?, status_reason=?, updated_at=? WHERE id=?",
                          (naar, reden, _nu(), window_id))

    def store_wf_result(self, window_id: int, kind: str, candidate_id: int, resultaat: dict) -> int:
        """Eén resultaat van één kandidaat op één segment, in één transactie."""
        seg = resultaat["segment"]
        versies = resultaat["versions"]
        venster = self.conn.execute("SELECT experiment_id FROM wf_windows WHERE id=?",
                                    (window_id,)).fetchone()
        wseg = self.conn.execute("SELECT id FROM wf_segments WHERE window_id=? AND kind=?",
                                 (window_id, kind)).fetchone()
        eid = venster["experiment_id"]
        rid = []

        def stappen():
            trades = seg["trades"]
            cur = self.conn.execute(
                "INSERT INTO wf_results (wf_segment_id, window_id, experiment_id, candidate_id, kind, "
                "result_hash, summary_json, cost_model_json, result_schema_version, "
                "backtest_engine_version, cost_model_version, metrics_version, "
                "segment_schema_version, walk_forward_schema_version, trade_count, "
                "cross_boundary_count, segment_end_close_count, forced_exit_json, "
                "warmup_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (wseg["id"], window_id, eid, candidate_id, kind, seg["result_hash"],
                 canonical_json(seg["summary"]), canonical_json(resultaat["cost_model"]),
                 versies["result_schema_version"], versies["backtest_engine_version"],
                 versies["cost_model_version"], versies["metrics_version"],
                 versies["segment_schema_version"], versies["walk_forward_schema_version"],
                 len(trades), seg["forced_exit"]["cross_boundary_count"],
                 seg["forced_exit"]["segment_end_close_count"],
                 canonical_json(seg["forced_exit"]), seg["warmup_status"], _nu()))
            r = cur.lastrowid
            rid.append(r)
            velden = TRADE_FIELDS + ("cross_boundary",)
            self.conn.executemany(
                f"INSERT INTO wf_trades (wf_result_id, experiment_id, {', '.join(velden)}) "
                f"VALUES (?, ?, {', '.join('?' * len(velden))})",
                [(r, eid, *(int(t[v]) if v == "cross_boundary" else t[v] for v in velden))
                 for t in trades])
            for tabel, rijen in (("wf_metrics", seg["metrics"]), ("wf_breakdowns", seg["breakdowns"]),
                                 ("wf_rejections", seg["rejections"])):
                if rijen:
                    kol = list(rijen[0])
                    self.conn.executemany(
                        f"INSERT INTO {tabel} (wf_result_id, experiment_id, {', '.join(kol)}) "
                        f"VALUES (?, ?, {', '.join('?' * len(kol))})",
                        [(r, eid, *(x[k] for k in kol)) for x in rijen])
        self._in_transactie(stappen)
        return rid[0]

    def _wf_metrics_van(self, result_id: int) -> dict:
        return {m["metric_name"]: dict(m) for m in self.conn.execute(
            "SELECT * FROM wf_metrics WHERE wf_result_id=?", (result_id,))}

    def wf_train_metrics(self, window_id: int) -> dict[int, dict]:
        """TRAIN-metrieken per kandidaat - de enige invoer van de selectie.
        Leest per definitie geen VALIDATION of TEST."""
        return {r["candidate_id"]: {"result_id": r["id"], "metrics": self._wf_metrics_van(r["id"])}
                for r in self.conn.execute("SELECT id, candidate_id FROM wf_results "
                                           "WHERE window_id=? AND kind='TRAIN'", (window_id,))}

    def wf_validation_metrics(self, window_id: int) -> dict | None:
        r = self.conn.execute("SELECT id FROM wf_results WHERE window_id=? AND kind='VALIDATION'",
                              (window_id,)).fetchone()
        return self._wf_metrics_van(r["id"]) if r else None

    def store_selection(self, window_id: int, sel, rule, kandidaten: dict, train: dict) -> None:
        """De selectie en de beoordeling per kandidaat, onveranderlijk, in één transactie.
        ``kandidaten``: sleutel -> (candidate_id, config_hash)."""
        eid = self.conn.execute("SELECT experiment_id FROM wf_windows WHERE id=?",
                                (window_id,)).fetchone()[0]
        from .walk_forward import SELECTION_RULE_VERSION

        def stappen():
            gekozen = kandidaten[sel.selected] if sel.selected else (None, None)
            self.conn.execute(
                "INSERT INTO wf_selections (window_id, experiment_id, selection_status, "
                "selected_candidate_id, selected_config_hash, primary_metric, selection_direction, "
                "selected_metric_value, selected_metric_status, tie_break_values_json, "
                "selection_rule_version, reason, selected_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (window_id, eid, sel.status, gekozen[0], gekozen[1], rule.primary_metric,
                 rule.direction, sel.selected_metric_value, sel.selected_metric_status,
                 canonical_json(sel.tie_break_values), SELECTION_RULE_VERSION, sel.reason, _nu()))
            for e in sel.evaluations:
                cid, _ = kandidaten[e["candidate"]]
                self.conn.execute(
                    "INSERT INTO wf_candidate_evaluations (window_id, experiment_id, candidate_id, "
                    "train_result_id, primary_metric_value, primary_metric_status, eligible, "
                    "disqualification_reason, rank_position) VALUES (?,?,?,?,?,?,?,?,?)",
                    (window_id, eid, cid, train[cid]["result_id"], e["primary_metric_value"],
                     e["primary_metric_status"], int(e["eligible"]),
                     e["disqualification_reason"], e["rank_position"]))
        self._in_transactie(stappen)

    def store_validation_decision(self, window_id: int, status: str, reden: str) -> None:
        eid = self.conn.execute("SELECT experiment_id FROM wf_windows WHERE id=?",
                                (window_id,)).fetchone()[0]
        self.conn.execute("INSERT INTO wf_validation_decisions (window_id, experiment_id, status, "
                          "reason, decided_at) VALUES (?,?,?,?,?)",
                          (window_id, eid, status, reden, _nu()))

    def _sluit_vensters(self, experiment_id: int, status: str, reden: str) -> None:
        """Alle niet-afgesloten vensters naar FAILED, CANCELLED of INTERRUPTED."""
        from .walk_forward import WINDOW_TERMINAL
        for w in self.conn.execute(
                "SELECT id, status FROM wf_windows WHERE experiment_id=?", (experiment_id,)).fetchall():
            if w["status"] not in WINDOW_TERMINAL:
                self.set_window_status(w["id"], status, reden)

    def update_wf_progress(self, experiment_id: int, *, pct: float, windows_total: int,
                           windows_completed: int, current_window: int | None,
                           candidates_total: int, current_candidate: str | None,
                           segment: str | None) -> None:
        self.conn.execute(
            "UPDATE experiment_runs SET progress_pct = MAX(progress_pct, ?), "
            "windows_total = MAX(windows_total, ?), windows_completed = MAX(windows_completed, ?), "
            "current_window = ?, candidates_total = MAX(candidates_total, ?), "
            "current_candidate = ?, current_segment = ?, last_progress_at = ? "
            "WHERE experiment_id = ?",
            (min(99.9, round(pct, 1)), windows_total, windows_completed, current_window,
             candidates_total, current_candidate, segment, _nu(), experiment_id))

    def wf_overview(self, experiment_id: int) -> dict:
        """Wat zonder TEST-toegang zichtbaar mag zijn: aantallen, statussen,
        provenance. Geen enkele TEST-prestatiewaarde."""
        plan = self.wf_plan(experiment_id)
        if plan is None:
            return {}
        vensters = []
        for w in plan["windows"]:
            test = self.conn.execute("SELECT id FROM wf_results WHERE window_id=? AND kind='TEST'",
                                     (w["id"],)).fetchone()
            geopend = self.conn.execute("SELECT COUNT(*) FROM wf_test_access_log WHERE window_id=?",
                                        (w["id"],)).fetchone()[0]
            sel = self.conn.execute("SELECT selection_status, selected_candidate_id FROM wf_selections "
                                    "WHERE window_id=?", (w["id"],)).fetchone()
            vensters.append({
                "window_index": w["window_index"], "status": w["status"],
                "status_reason": w["status_reason"],
                "selection_status": sel["selection_status"] if sel else None,
                "selected_candidate_id": sel["selected_candidate_id"] if sel else None,
                "test": ("TEST_NOT_EXECUTED" if test is None else
                         "TEST_OPENED" if geopend else "TEST_UNOPENED"),
            })
        tel = lambda f: sum(1 for v in vensters if f(v))  # noqa: E731
        return {
            "mode": plan["mode"], "window_type": plan["window_type"],
            "windows_total": plan["window_count"], "candidates": len(plan["candidates"]),
            "candidate_set_hash": plan["candidate_set_hash"],
            "windows_completed": tel(lambda v: v["status"] == "COMPLETED"),
            "windows_no_selection": tel(lambda v: v["status"] == "NO_SELECTION"),
            "windows_validation_rejected": tel(lambda v: v["status"] == "VALIDATION_REJECTED"),
            "test_unopened": tel(lambda v: v["test"] == "TEST_UNOPENED"),
            "test_opened": tel(lambda v: v["test"] == "TEST_OPENED"),
            "windows": vensters,
        }

    def _hergebruik(self, familie: str, ds_hash: str, start: int, einde: int, ds_id: int) -> dict:
        """Eerdere TEST-toegangen binnen de familie op dezelfde data, uit beide logs:
        exact hetzelfde interval (DATA_REUSED) en overlappende intervallen
        (OVERLAPPING_TEST_DATA), met de overlap in seconden en in bars."""
        rijen = self.conn.execute(
            "SELECT test_start_ts, test_end_ts FROM test_access_log "
            "WHERE hypothesis_family_id=? AND dataset_hash=? "
            "UNION ALL SELECT test_start_ts, test_end_ts FROM wf_test_access_log "
            "WHERE hypothesis_family_id=? AND dataset_hash=?",
            (familie, ds_hash, familie, ds_hash)).fetchall()
        gelijk = sum(1 for a, b in rijen if a == start and b == einde)
        overlap = [(max(a, start), min(b, einde)) for a, b in rijen
                   if not (a == start and b == einde) and a < einde and start < b]
        bars = sum(self.conn.execute(
            "SELECT COUNT(*) FROM dataset_bars WHERE dataset_id=? AND ts>=? AND ts<?",
            (ds_id, x, y)).fetchone()[0] for x, y in overlap)
        return {"prior": gelijk, "overlapping": len(overlap),
                "overlap_seconds": sum(y - x for x, y in overlap), "overlap_bars": bars}

    def _log_wf_toegang(self, eid: int, venster: dict, plan: dict, familie: str,
                        doel: str, context: str, soort: str,
                        assessment_id: int | None = None,
                        comparison_id: int | None = None) -> dict:
        test = venster["segments"]["TEST"]
        h = self._hergebruik(familie, plan["dataset_hash"], test["start_ts"], test["end_ts"],
                             plan["dataset_id"])
        self.conn.execute(
            "INSERT INTO wf_test_access_log (experiment_id, window_id, wf_segment_id, "
            "hypothesis_family_id, dataset_id, dataset_hash, test_start_ts, test_end_ts, "
            "accessed_at, purpose, access_type, accessor_context, prior_access_count, "
            "data_reused, overlapping_prior_count, overlap_seconds, overlap_bars, "
            "assessment_id, access_schema_version, comparison_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, venster["id"], test["id"], familie, plan["dataset_id"], plan["dataset_hash"],
             test["start_ts"], test["end_ts"], _nu(), doel, soort, context, h["prior"],
             int(h["prior"] > 0), h["overlapping"], h["overlap_seconds"], h["overlap_bars"],
             assessment_id, TEST_ACCESS_SCHEMA_VERSION, comparison_id))
        h["log_id"] = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        if h["prior"]:
            self.annotate(eid, "DATA_REUSED",
                          f"venster {venster['window_index']}: TEST-data binnen familie "
                          f"'{familie}' voor de {h['prior'] + 1}e keer geopend; geen onafhankelijke toets.")
        if h["overlapping"]:
            self.annotate(eid, "OVERLAPPING_TEST_DATA",
                          f"venster {venster['window_index']}: TEST-interval overlapt met "
                          f"{h['overlapping']} eerder geopend(e) interval(len): "
                          f"{h['overlap_seconds']} s, {h['overlap_bars']} bars.")
        return h

    def open_wf_test_result(self, experiment_id: int, window_index: int,
                            purpose: str, accessor_context: str) -> dict:
        """TEST-resultaat van één venster. Eerst de logregel, dan de data -
        in één transactie (fail-closed)."""
        if purpose not in TEST_PURPOSES:
            raise ValueError(f"onbekend doel: {purpose!r}")
        exp, plan = self.get(experiment_id), self.wf_plan(experiment_id)
        if exp is None or plan is None:
            raise LabDatabaseError("geen walk-forwardexperiment")
        venster = next(w for w in plan["windows"] if w["window_index"] == window_index)
        data: dict = {}

        def stappen():
            h = self._log_wf_toegang(experiment_id, venster, plan, exp.hypothesis_family_id,
                                     purpose, accessor_context, "TEST_RESULT_READ")
            r = self.conn.execute("SELECT * FROM wf_results WHERE window_id=? AND kind='TEST'",
                                  (venster["id"],)).fetchone()
            if r is None:
                raise LabDatabaseError(f"venster {window_index} heeft geen TEST-resultaat")
            data.update({"result": dict(r), "metrics": self._wf_metrics_van(r["id"]),
                         "data_reused": bool(h["prior"]), "prior_access_count": h["prior"],
                         "overlapping_prior_count": h["overlapping"]})
        self._in_transactie(stappen)
        return data

    def open_oos_aggregate(self, experiment_id: int, purpose: str, accessor_context: str) -> dict:
        """Technische OOS-aggregatie over de voltooide, niet-overlappende
        TEST-vensters. Zelf verzegeld: elke meegetelde TEST wordt eerst gelogd.
        Geen oordeel."""
        from datetime import datetime, timezone
        from .metrics import compute_metrics
        from ..timeutil import trading_day
        if purpose not in TEST_PURPOSES:
            raise ValueError(f"onbekend doel: {purpose!r}")
        exp, plan = self.get(experiment_id), self.wf_plan(experiment_id)
        if exp is None or plan is None:
            raise LabDatabaseError("geen walk-forwardexperiment")
        data: dict = {}

        def stappen():
            mee, niet = [], []
            for w in plan["windows"]:
                r = self.conn.execute("SELECT * FROM wf_results WHERE window_id=? AND kind='TEST'",
                                      (w["id"],)).fetchone()
                (mee if (w["status"] == "COMPLETED" and r is not None) else niet).append((w, r))
            if not mee:
                raise LabDatabaseError("geen voltooid TEST-venster om samen te voegen")
            versies = {(r["result_schema_version"], r["backtest_engine_version"], r["cost_model_version"],
                        r["metrics_version"], r["segment_schema_version"],
                        r["walk_forward_schema_version"]) for _, r in mee}
            modellen = {r["cost_model_json"] for _, r in mee}
            if len(versies) != 1 or len(modellen) != 1:
                raise LabDatabaseError("TEST-vensters met onverenigbare versies of kostenmodellen")
            for w, _ in mee:
                self._log_wf_toegang(experiment_id, w, plan, exp.hypothesis_family_id,
                                     purpose, accessor_context, "OOS_AGGREGATE_READ")
            trades, evaluaties, afwijzingen, dagen = [], 0, {}, set()
            for w, r in mee:
                for t in self.conn.execute("SELECT * FROM wf_trades WHERE wf_result_id=? "
                                           "ORDER BY sequence_number", (r["id"],)):
                    trades.append({k: t[k] for k in TRADE_FIELDS})
                sam = json.loads(r["summary_json"])
                evaluaties += sam.get("evaluations", 0)
                for code, n in (sam.get("rejections") or {}).items():
                    afwijzingen[code] = afwijzingen.get(code, 0) + n
                test = w["segments"]["TEST"]
                for (ts,) in self.conn.execute(
                        "SELECT ts FROM dataset_bars WHERE dataset_id=? AND ts>=? AND ts<?",
                        (plan["dataset_id"], test["start_ts"], test["end_ts"])):
                    dagen.add(trading_day(datetime.fromtimestamp(ts, timezone.utc)).isoformat())
            trades.sort(key=lambda t: (t["opened_ts"], t["sequence_number"]))
            for i, t in enumerate(trades, 1):
                t["sequence_number"] = i
            kosten = json.loads(next(iter(modellen)))
            precisie = self.dataset(plan["dataset_id"])["instrument_precision"]
            samen = {"evaluations": evaluaties, "rejections": afwijzingen, "trades": len(trades)}
            data.update({
                "included_window_ids": [w["id"] for w, _ in mee],
                "excluded_windows": [{"window_id": w["id"], "status": w["status"]} for w, _ in niet],
                "selection_status": {w["window_index"]: (self.conn.execute(
                    "SELECT selection_status FROM wf_selections WHERE window_id=?", (w["id"],)
                ).fetchone() or ["SEQUENTIAL_OOS"])[0] for w, _ in mee + niet},
                "trade_count": len(trades),
                "metrics": {m["metric_name"]: m for m in
                            compute_metrics(trades, samen, sorted(dagen), precisie, kosten)},
                "versions": dict(zip(("result_schema_version", "backtest_engine_version",
                                      "cost_model_version", "metrics_version",
                                      "segment_schema_version", "walk_forward_schema_version"),
                                     next(iter(versies)))),
                "currency": kosten.get("cost_currency"),
                "forced_exits": {
                    "segment_end_close_count": sum(r["segment_end_close_count"] for _, r in mee),
                    "cross_boundary_count": sum(r["cross_boundary_count"] for _, r in mee),
                },
                "execution_fidelity": "BAR_ONLY",
            })
        self._in_transactie(stappen)
        return data

    # -- beoordeling --------------------------------------------------------- #

    def create_assessment(self, experiment_id: int, accessor_context: str) -> int:
        """Een nieuwe, onveranderlijke beoordeling van een voltooid walk-forwardexperiment.

        Transactiegrens:

        * **A** - alle TEST-toegangen loggen (doel ASSESSMENT) en de resultaten
          lezen, in één transactie. Mislukt één logregel, dan wordt alles
          teruggedraaid, is er niets gelezen, en wordt de beoordeling FAILED.
        * berekenen, in het geheugen;
        * **B** - componenten, bronnen en classificatie opslaan en COMPLETED,
          in één transactie.

        Mislukt het na A, dan wordt de beoordeling FAILED **en blijven de
        logregels van A staan**: de TEST-data is werkelijk gelezen; wissen zou
        een ongelezen TEST voorwenden.
        """
        from .assessment import (
            ASSESSMENT_RULES_VERSION, ASSESSMENT_SCHEMA_VERSION, RULEBOOK, assess,
        )
        exp, plan = self.get(experiment_id), self.wf_plan(experiment_id)
        if exp is None or plan is None or exp.status != "completed":
            raise LabDatabaseError("alleen een voltooid walk-forwardexperiment is te beoordelen")
        aid = self.conn.execute(
            "INSERT INTO assessments (experiment_id, status, assessment_schema_version, "
            "assessment_rules_version, test_access_schema_version, dataset_id, dataset_hash, "
            "hypothesis_family_id, created_at) VALUES (?, 'PENDING', ?,?,?,?,?,?,?)",
            (experiment_id, ASSESSMENT_SCHEMA_VERSION, ASSESSMENT_RULES_VERSION,
             TEST_ACCESS_SCHEMA_VERSION, plan["dataset_id"], plan["dataset_hash"],
             exp.hypothesis_family_id, _nu())).lastrowid
        self.conn.execute("UPDATE assessments SET status='CALCULATING' WHERE id=?", (aid,))

        def mislukt(reden: str) -> int:
            self.conn.execute("UPDATE assessments SET status='FAILED', error=?, completed_at=? "
                              "WHERE id=?", (reden, _nu(), aid))
            return aid

        gelezen: dict = {}

        def lees():
            for w in plan["windows"]:
                r = self.conn.execute("SELECT * FROM wf_results WHERE window_id=? AND kind='TEST'",
                                      (w["id"],)).fetchone()
                if w["status"] != "COMPLETED" or r is None:
                    continue
                h = self._log_wf_toegang(experiment_id, w, plan, exp.hypothesis_family_id,
                                         "ASSESSMENT", accessor_context, "TEST_RESULT_READ",
                                         assessment_id=aid)
                gelezen[w["id"]] = (h, dict(r), [dict(t) for t in self.conn.execute(
                    "SELECT * FROM wf_trades WHERE wf_result_id=? ORDER BY sequence_number", (r["id"],))],
                    self._wf_metrics_van(r["id"]))
        try:
            self._in_transactie(lees)
        except Exception as err:  # noqa: BLE001 - fail-closed: niets gelezen
            gelezen.clear()
            return mislukt(f"TEST-toegang mislukt; niets gelezen: {type(err).__name__}: {err}")

        try:
            inp, snapshot, bronnen = self._assessment_input(experiment_id, plan, gelezen)
            uit = assess(inp)
            versies = snapshot["versions"]

            def sla_op():
                for c in uit["components"]:
                    self.conn.execute(
                        "INSERT INTO assessment_components (assessment_id, component_code, "
                        "component_version, status, measured_value, unit, sample_size, "
                        "required_condition, blocking, explanation, details_json, "
                        "source_result_ids_json, source_window_ids_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (aid, c["component_code"], c["component_version"], c["status"],
                         None if c["measured_value"] is None else str(c["measured_value"]),
                         c["unit"], c["sample_size"], c["required_condition"], int(c["blocking"]),
                         c["explanation"], canonical_json(c["details"]),
                         canonical_json(c["source_result_ids"]), canonical_json(c["source_window_ids"])))
                for b in bronnen:
                    self.conn.execute("INSERT INTO assessment_sources (assessment_id, wf_result_id, kind, "
                                      "window_id, result_hash) VALUES (?,?,?,?,?)", (aid, *b))
                self.conn.execute(
                    "UPDATE assessments SET status='COMPLETED', versions_json=?, raw_classification=?, "
                    "classification_ceiling=?, fidelity_ceiling=?, final_classification=?, "
                    "classification_explanation=?, test_access_count=?, data_reused=?, "
                    "overlapping_test_data=?, trace_json=?, input_json=?, rulebook_json=?, "
                    "family_snapshot_json=?, completed_at=? WHERE id=?",
                    (canonical_json(versies), uit["raw_classification"], uit["classification_ceiling"],
                     uit["fidelity_ceiling"], uit["final_classification"], uit["explanation"],
                     len(gelezen), int(any(a["data_reused"] for a in inp["access"])),
                     int(any(a["overlapping_prior_count"] for a in inp["access"])),
                     canonical_json({"trace": uit["trace"], "blocking": uit["blocking"],
                                     "warnings": uit["warnings"]}),
                     canonical_json(snapshot), canonical_json(RULEBOOK),
                     canonical_json(inp["family"]), _nu(), aid))
            self._in_transactie(sla_op)
        except Exception as err:  # noqa: BLE001
            return mislukt(f"na de TEST-toegang mislukt; de logregels blijven staan: "
                           f"{type(err).__name__}: {err}")
        return aid

    def _assessment_input(self, experiment_id: int, plan: dict, gelezen: dict):
        """Invoer voor de beoordeling, plus een reproduceerbare snapshot met ids en hashes."""
        from .metrics import REQUIRED_METRICS as _VERPLICHT
        exp = self.get(experiment_id)
        regel = json.loads(plan["selection_rule_json"])
        primair = regel["primary_metric"]
        vensters, bronnen, toegang = [], [], []
        for w in plan["windows"]:
            sel = self.conn.execute("SELECT * FROM wf_selections WHERE window_id=?", (w["id"],)).fetchone()
            gekozen = sel["selected_candidate_id"] if sel else None
            train_sel = None
            if gekozen is not None:
                tr = self.conn.execute("SELECT id, result_hash FROM wf_results WHERE window_id=? "
                                       "AND kind='TRAIN' AND candidate_id=?", (w["id"], gekozen)).fetchone()
                if tr:
                    train_sel = self._wf_metrics_van(tr["id"]).get(primair, {}).get("value")
                    bronnen.append((tr["id"], "TRAIN", w["id"], tr["result_hash"]))
            val = self.conn.execute("SELECT id, result_hash FROM wf_results WHERE window_id=? "
                                    "AND kind='VALIDATION'", (w["id"],)).fetchone()
            if val:
                bronnen.append((val["id"], "VALIDATION", w["id"], val["result_hash"]))
            test = None
            if w["id"] in gelezen:
                h, r, trades, metrics = gelezen[w["id"]]
                bronnen.append((r["id"], "TEST", w["id"], r["result_hash"]))
                toegang.append({"window_id": w["id"], "log_id": h["log_id"],
                                "prior_access_count": h["prior"], "data_reused": h["prior"] > 0,
                                "overlapping_prior_count": h["overlapping"],
                                "overlap_seconds": h["overlap_seconds"], "overlap_bars": h["overlap_bars"]})
                test = {"result_id": r["id"],
                        "trades": [{"net": t["net_pnl_instrument"], "trading_day": t["trading_day"],
                                    "regime": t["regime"], "session": t["session"],
                                    "close_reason": t["close_reason"]} for t in trades],
                        "metrics": {k: {"value": m["value"], "calculation_status": m["calculation_status"]}
                                    for k, m in metrics.items()},
                        "metrics_complete": len(metrics) == len(_VERPLICHT),
                        "warmup_status": r["warmup_status"],
                        "segment_end_close_count": r["segment_end_close_count"],
                        "cross_boundary_count": r["cross_boundary_count"],
                        "fidelity": json.loads(r["summary_json"]).get("fidelity"),
                        "versions": (r["result_schema_version"], r["backtest_engine_version"],
                                     r["cost_model_version"], r["metrics_version"],
                                     r["segment_schema_version"], r["walk_forward_schema_version"]),
                        "cost_currency": json.loads(r["cost_model_json"]).get("cost_currency")}
            vensters.append({"window_id": w["id"], "window_index": w["window_index"],
                             "status": w["status"], "selected_candidate_id": gekozen,
                             "train_selected": train_sel, "test": test})
        kandidaten = []
        for k in plan["candidates"]:
            nets = {}
            for w in plan["windows"]:
                tr = self.conn.execute("SELECT id FROM wf_results WHERE window_id=? AND kind='TRAIN' "
                                       "AND candidate_id=?", (w["id"], k["id"])).fetchone()
                if tr:
                    nets[w["window_index"]] = self._wf_metrics_van(tr["id"]).get(primair, {}).get("value")
            kandidaten.append({"id": k["id"], "config": json.loads(k["config_json"]), "train_nets": nets})
        ds = self.dataset(plan["dataset_id"])
        inp = {"windows": vensters, "candidates": kandidaten,
               "dataset": {"quality_status": ds["quality_status"], "findings": ds["quality"]},
               "family": self.family_summary(exp.hypothesis_family_id), "access": toegang}
        testversies = {v["test"]["versions"] for v in vensters if v["test"]}
        snapshot = {
            "experiment_id": experiment_id, "dataset_id": plan["dataset_id"],
            "dataset_hash": plan["dataset_hash"], "dataset_quality_status": ds["quality_status"],
            "candidate_set_hash": plan["candidate_set_hash"],
            "candidates": [{"id": k["id"], "config_hash": k["config_hash"]} for k in plan["candidates"]],
            "windows": [{"window_id": v["window_id"], "status": v["status"],
                         "selected_candidate_id": v["selected_candidate_id"]} for v in vensters],
            "sources": [{"wf_result_id": b[0], "kind": b[1], "window_id": b[2], "result_hash": b[3]}
                        for b in bronnen],
            "access_log_ids": [a["log_id"] for a in toegang],
            "versions": {"software_version": exp.software_version,
                         "strategy_version": exp.strategy_version,
                         "execution_semantics_version": exp.execution_semantics_version,
                         "selection_rule_version": plan["selection_rule_version"],
                         "test_result_versions": [list(v) for v in sorted(testversies)]},
        }
        return inp, snapshot, bronnen

    def assessment(self, assessment_id: int) -> dict | None:
        rij = self.conn.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
        if rij is None:
            return None
        uit = dict(rij)
        uit["components"] = {c["component_code"]: dict(c) for c in self.conn.execute(
            "SELECT * FROM assessment_components WHERE assessment_id=?", (assessment_id,))}
        return uit

    # -- vergelijking -------------------------------------------------------- #

    def _comparison_side(self, experiment_id: int, assessment_id: int) -> dict:
        """Alles wat een kant nodig heeft voor de vergelijkbaarheid - zonder één
        TEST-resultaat te lezen: beoordeling, plan, dataset en configuratie."""
        from .costs import build_cost_model
        from .comparison import CLASS_RANK
        exp, plan = self.get(experiment_id), self.wf_plan(experiment_id)
        a = self.assessment(assessment_id)
        if exp is None or plan is None or a is None or a["experiment_id"] != experiment_id \
                or a["status"] != "COMPLETED":
            raise LabDatabaseError("een kant heeft geen voltooid walk-forwardexperiment met voltooide beoordeling")
        ds = self.dataset(plan["dataset_id"])
        snap = json.loads(a["input_json"])
        tv = snap["versions"]["test_result_versions"]
        een = tv[0] if len(tv) == 1 else None
        # Het kostenmodel alleen herbouwen uit de onveranderlijke configuratie van
        # het experiment - nooit uit actuele opties - en alleen als die
        # configuratie aantoonbaar dezelfde is als waarop de beoordeling rust,
        # en de kostenmodelversie gelijk is aan die van de resultaten. Anders
        # UNKNOWN: een later gewijzigde standaardwaarde mag een historische
        # vergelijking niet veranderen.
        from .costs import COST_MODEL_VERSION
        bekend = {k["id"]: k["config_hash"] for k in snap.get("candidates", [])}
        klopt = all(config_hash(json.loads(k["config_json"])) == k["config_hash"] == bekend.get(k["id"])
                    for k in plan["candidates"])
        versie_klopt = een is not None and een[2] == COST_MODEL_VERSION
        modellen = sorted({canonical_json(build_cost_model(json.loads(k["config_json"]).get("execution") or {}))
                           for k in plan["candidates"]}) if klopt and versie_klopt else []
        kosten = json.loads(modellen[0]) if len(modellen) == 1 else None
        vensters = [[w["window_index"]] + [[w["segments"][k]["start_ts"], w["segments"][k]["end_ts"]]
                                           if k in w["segments"] else None
                                           for k in ("TRAIN", "VALIDATION", "TEST")]
                    for w in plan["windows"]]
        return {
            "experiment_id": experiment_id, "assessment_id": assessment_id,
            "dataset_id": plan["dataset_id"], "dataset_hash": ds["hash"], "symbol": ds["symbol"],
            "timeframe": ds["timeframe"], "dataset_period": [ds["start_ts"], ds["end_ts"]],
            "dataset_bar_count": ds["bar_count"], "dataset_quality_status": ds["quality_status"],
            "segment_schema_version": plan["segment_schema_version"],
            "walk_forward_schema_version": plan["walk_forward_schema_version"],
            "window_count": plan["window_count"], "window_type": plan["window_type"],
            "window_intervals": vensters,
            "cost_model": modellen[0] if len(modellen) == 1 else None,
            "cost_model_hash": (hashlib.sha256(modellen[0].encode("utf-8")).hexdigest()
                                if len(modellen) == 1 else None),
            "metrics_version": een[3] if een else None,
            "result_schema_version": een[0] if een else None,
            "backtest_engine_version": een[1] if een else None,
            "execution_semantics_version": exp.execution_semantics_version,
            "strategy_version": exp.strategy_version,
            "instrument_currency": kosten and kosten.get("cost_currency"),
            "conversion_status": kosten and kosten["fx_model"]["status"],
            "execution_fidelity": a["fidelity_ceiling"],
            "assessment_rules_version": a["assessment_rules_version"],
            "candidate_set_hash": plan["candidate_set_hash"],
            "selection_rule": plan["selection_rule_json"],
            "test_independence": a["components"].get("TEST_INDEPENDENCE", {}).get("status"),
            "final_rank": CLASS_RANK.get(a["final_classification"], 0),
            "assessment": a, "plan": plan, "snapshot": snap,
        }

    def create_comparison(self, reference_experiment_id: int, challenger_experiment_id: int, *,
                          mode: str = "ASSESSMENT_COMPARISON",
                          reference_assessment_id: int | None = None,
                          challenger_assessment_id: int | None = None,
                          accessor_context: str | None = None) -> int:
        """Reference tegenover challenger. Standaard alleen uit de beoordelingen,
        zonder nieuwe TEST-toegang. ``DEEP_RESULT_COMPARISON`` leest TEST opnieuw:
        eerst gelogd met doel COMPARISON, in één transactie, fail-closed.
        Geen winnaar, geen promotie."""
        from . import comparison as C
        from .metrics import REQUIRED_METRICS as VERPLICHT

        def laatste(eid):
            r = self.conn.execute("SELECT id FROM assessments WHERE experiment_id=? AND status='COMPLETED' "
                                  "ORDER BY id DESC LIMIT 1", (eid,)).fetchone()
            if r is None:
                raise LabDatabaseError(f"experiment {eid} heeft geen voltooide beoordeling")
            return r[0]
        ra = reference_assessment_id or laatste(reference_experiment_id)
        ca = challenger_assessment_id or laatste(challenger_experiment_id)
        if mode not in (C.ASSESSMENT_COMPARISON, C.DEEP_RESULT_COMPARISON):
            raise ValueError(f"onbekende modus: {mode}")
        cid = self.conn.execute(
            "INSERT INTO comparisons (status, mode, reference_experiment_id, challenger_experiment_id, "
            "reference_assessment_id, challenger_assessment_id, comparison_schema_version, "
            "comparison_rules_version, test_access_schema_version, created_at) "
            "VALUES ('PENDING',?,?,?,?,?,?,?,?,?)",
            (mode, reference_experiment_id, challenger_experiment_id, ra, ca,
             C.COMPARISON_SCHEMA_VERSION, C.COMPARISON_RULES_VERSION, TEST_ACCESS_SCHEMA_VERSION, _nu())).lastrowid

        def mislukt(reden):
            self.conn.execute("UPDATE comparisons SET status='FAILED', error=?, completed_at=? WHERE id=?",
                              (reden, _nu(), cid))
            return cid

        self.conn.execute("UPDATE comparisons SET status='CHECKING' WHERE id=?", (cid,))
        try:
            ref = self._comparison_side(reference_experiment_id, ra)
            ch = self._comparison_side(challenger_experiment_id, ca)
            cs = C.checks(ref, ch)
            status, redenen = C.comparability(cs)
        except Exception as err:  # noqa: BLE001
            return mislukt(f"controle mislukt: {type(err).__name__}: {err}")

        diep: dict = {}
        if mode == C.DEEP_RESULT_COMPARISON:
            def lees():
                for naam, kant in (("reference", ref), ("challenger", ch)):
                    exp = self.get(kant["experiment_id"])
                    trades, logs, per = [], [], {}
                    for w in kant["plan"]["windows"]:
                        r = self.conn.execute("SELECT * FROM wf_results WHERE window_id=? AND kind='TEST'",
                                              (w["id"],)).fetchone()
                        if w["status"] != "COMPLETED" or r is None:
                            continue
                        h = self._log_wf_toegang(kant["experiment_id"], w, kant["plan"],
                                                 exp.hypothesis_family_id, "COMPARISON",
                                                 accessor_context or "", "TEST_RESULT_READ",
                                                 comparison_id=cid)
                        logs.append(h["log_id"])
                        per[w["window_index"]] = self._wf_metrics_van(r["id"])
                        trades += [{k: t[k] for k in TRADE_FIELDS} for t in self.conn.execute(
                            "SELECT * FROM wf_trades WHERE wf_result_id=? ORDER BY sequence_number", (r["id"],))]
                    diep[naam] = {"trades": trades, "log_ids": logs, "per_window": per}
            try:
                self._in_transactie(lees)
            except Exception as err:  # noqa: BLE001 - fail-closed
                return mislukt(f"TEST-toegang mislukt; niets gelezen: {type(err).__name__}: {err}")

        try:
            self.conn.execute("UPDATE comparisons SET status='CALCULATING' WHERE id=?", (cid,))
            items = []
            ka, kb = ref["assessment"]["components"], ch["assessment"]["components"]
            for code in sorted(set(ka) | set(kb)):
                items.append(C.component_delta(code, ka.get(code), kb.get(code)))
            for veld in ("raw_classification", "classification_ceiling", "final_classification"):
                a, b = ref["assessment"][veld], ch["assessment"][veld]
                items.append({"section": "classification", "key": veld, "reference": a, "challenger": b,
                              "status": C.SAME if a == b else C.DIFFERENT,
                              "explanation": "naast elkaar; een hogere classificatie is geen bewijs "
                                             "dat een kant beter is - zie de beperkende componenten"})
            # Vensters alleen naast elkaar bij dezelfde data én dezelfde intervallen:
            # gelijke tijden op andere data zijn geen gezamenlijke toets.
            vensters_gelijk = all(next(c for c in cs if c["check_code"] == k)["status"] == C.SAME
                                  for k in ("window_intervals", "dataset_hash"))
            netten = {}
            for naam, kant in (("reference", ref), ("challenger", ch)):
                det = json.loads(kant["assessment"]["components"]["WINDOW_CONSISTENCY"]["details_json"])
                idx = {str(w["id"]): w["window_index"] for w in kant["plan"]["windows"]}
                netten[naam] = {idx[k]: v for k, v in (det.get("net_per_window") or {}).items()}
            for w in ref["plan"]["windows"]:
                i = w["window_index"]
                a, b = netten["reference"].get(i), netten["challenger"].get(i)
                if not vensters_gelijk:
                    st, uitleg = C.NOT_COMPARABLE, "andere data of andere TEST-vensters: geen directe OOS-vergelijking"
                elif a is None or b is None:
                    st, uitleg = "INSUFFICIENT_DATA", "geen voltooid TEST-venster aan een van beide kanten"
                else:
                    st = "SAME_DIRECTION" if (a > 0) == (b > 0) else "OPPOSITE_DIRECTION"
                    uitleg = "netto per venster uit de beoordelingen; geen rangorde"
                items.append({"section": "window", "key": str(i), "reference": a, "challenger": b,
                              "absolute_delta": (b - a) if st in ("SAME_DIRECTION", "OPPOSITE_DIRECTION") else None,
                              "status": st, "explanation": uitleg})
            for veld in ("candidate_set_hash", "selection_rule"):
                a, b = ref[veld], ch[veld]
                items.append({"section": "selection", "key": veld, "reference": a, "challenger": b,
                              "status": C.SAME if a == b else C.DIFFERENT,
                              "explanation": "andere kandidaten of selectieregel: selectiegedrag "
                                             "slechts gedeeltelijk vergelijkbaar" if a != b else "gelijk"})
            for naam, kant in (("reference", ref), ("challenger", ch)):
                for w in kant["plan"]["windows"]:
                    sel = self.conn.execute("SELECT selection_status, selected_config_hash FROM wf_selections "
                                            "WHERE window_id=?", (w["id"],)).fetchone()
                    items.append({"section": f"selection_{naam}", "key": str(w["window_index"]),
                                  "reference" if naam == "reference" else "challenger":
                                  json.dumps({"window_status": w["status"],
                                              "selection": sel["selection_status"] if sel else None,
                                              "selected_config_hash": sel["selected_config_hash"] if sel else None}),
                                  "status": "RECORDED", "explanation": "geen oordeel over een andere keuze"})
            if diep:
                from .metrics import compute_metrics
                pool = {}
                for naam, kant in (("reference", ref), ("challenger", ch)):
                    kost = json.loads(kant["cost_model"]) if kant["cost_model"] else {"cost_currency": None}
                    prec = self.dataset(kant["dataset_id"])["instrument_precision"]
                    tr = sorted(diep[naam]["trades"], key=lambda t: (t["opened_ts"], t["sequence_number"]))
                    for n, t in enumerate(tr, 1):
                        t["sequence_number"] = n
                    dagen = sorted({t["trading_day"] for t in tr})
                    pool[naam] = {m["metric_name"]: m for m in compute_metrics(
                        tr, {"evaluations": 0, "rejections": {}, "trades": len(tr)}, dagen, prec, kost)}
                for naam in VERPLICHT:
                    items.append(C.metric_delta(naam, pool["reference"].get(naam), pool["challenger"].get(naam), cs))
            meta = [m for m in items if m["section"] == "metric"]
            vlaggen = C.flags(ref, ch, meta)
            resultaat = C.INSUFFICIENT_COMPARABILITY if status == C.NOT_COMPARABLE else C.COMPARED
            spoor = {"comparability": {"status": status, "reasons": redenen}, "flags": vlaggen,
                     "note": None if diep else "assessmentmodus: geen metriekvergelijking over "
                             "OOS-trades; daarvoor is DEEP_RESULT_COMPARISON nodig (nieuwe TEST-toegang)"}
            invoer = {
                side: {"experiment_id": k["experiment_id"], "assessment_id": k["assessment_id"],
                       "dataset_id": k["dataset_id"], "dataset_hash": k["dataset_hash"],
                       "candidate_set_hash": k["candidate_set_hash"],
                       "assessment_sources": k["snapshot"]["sources"],
                       "assessment_versions": k["snapshot"]["versions"],
                       "cost_model": k["cost_model"], "cost_model_hash": k["cost_model_hash"],
                       "window_intervals": k["window_intervals"],
                       "comparison_access_log_ids": diep.get(side, {}).get("log_ids", [])}
                for side, k in (("reference", ref), ("challenger", ch))}
            invoer["comparison_rules"] = {"version": C.COMPARISON_RULES_VERSION, "hard": list(C.HARD),
                                          "soft": list(C.SOFT), "direction": C.DIRECTION}

            def sla_op():
                for c in cs:
                    self.conn.execute("INSERT INTO comparison_checks VALUES (?,?,?,?,?,?)",
                                      (cid, c["check_code"], c["severity"], canonical_json(c["reference"]),
                                       canonical_json(c["challenger"]), c["status"]))
                for m in items:
                    self.conn.execute(
                        "INSERT INTO comparison_items (comparison_id, section, item_key, reference, challenger, "
                        "absolute_delta, relative_delta, status, explanation, details_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (cid, m["section"], m["key"], canonical_json(m.get("reference")),
                         canonical_json(m.get("challenger")), m.get("absolute_delta"), m.get("relative_delta"),
                         m["status"], m["explanation"],
                         canonical_json({k: v for k, v in m.items() if k not in
                                         ("section", "key", "reference", "challenger", "absolute_delta",
                                          "relative_delta", "status", "explanation")})))
                for side, k in (("reference", ref), ("challenger", ch)):
                    self.conn.execute("INSERT INTO comparison_sources VALUES (?,?,?,?,?)",
                                      (cid, side, "assessment", k["assessment_id"], None))
                    for b in k["snapshot"]["sources"]:
                        self.conn.execute("INSERT OR IGNORE INTO comparison_sources VALUES (?,?,?,?,?)",
                                          (cid, side, "wf_result", b["wf_result_id"], b["result_hash"]))
                self.conn.execute(
                    "UPDATE comparisons SET status='COMPLETED', reference_dataset_id=?, challenger_dataset_id=?, "
                    "reference_dataset_hash=?, challenger_dataset_hash=?, comparability_status=?, "
                    "comparability_reasons_json=?, flags_json=?, result=?, explanation=?, trace_json=?, "
                    "input_json=?, completed_at=? WHERE id=?",
                    (ref["dataset_id"], ch["dataset_id"], ref["dataset_hash"], ch["dataset_hash"], status,
                     canonical_json(redenen), canonical_json(vlaggen), resultaat,
                     "Vergelijking zonder winnaar; geen advies, geen promotie, geen toestemming voor live handel.",
                     canonical_json(spoor), canonical_json(invoer), _nu(), cid))
            self._in_transactie(sla_op)
        except Exception as err:  # noqa: BLE001
            return mislukt(("na de TEST-toegang mislukt; de logregels blijven staan: " if diep else
                            "vergelijking mislukt: ") + f"{type(err).__name__}: {err}")
        return cid

    def comparison(self, comparison_id: int) -> dict | None:
        rij = self.conn.execute("SELECT * FROM comparisons WHERE id=?", (comparison_id,)).fetchone()
        if rij is None:
            return None
        uit = dict(rij)
        uit["checks"] = {c["check_code"]: dict(c) for c in self.conn.execute(
            "SELECT * FROM comparison_checks WHERE comparison_id=?", (comparison_id,))}
        uit["items"] = [dict(i) for i in self.conn.execute(
            "SELECT * FROM comparison_items WHERE comparison_id=?", (comparison_id,))]
        return uit

    def _andere_omgeving(self, experiment_id: int, versies: dict) -> list[str]:
        """Waarin een reproductie afwijkt van zijn origineel. Leeg als het geen
        reproductie is of alles gelijk is."""
        exp = self.get(experiment_id)
        if exp is None or exp.reproduced_from is None:
            return []
        orig = self.get(exp.reproduced_from)
        verschil = [
            f"{veld}: {getattr(orig, veld)} -> {getattr(exp, veld)}"
            for veld in ("software_version", "strategy_version",
                         "execution_semantics_version")
            if getattr(orig, veld) != getattr(exp, veld)
        ]
        rij = self.conn.execute(
            "SELECT result_schema_version, backtest_engine_version, "
            "cost_model_version, metrics_version, NULL AS segment_schema_version "
            "FROM experiment_results WHERE experiment_id=? "
            "UNION ALL SELECT result_schema_version, backtest_engine_version, "
            "cost_model_version, metrics_version, segment_schema_version "
            "FROM segment_results WHERE experiment_id=? LIMIT 1",
            (exp.reproduced_from, exp.reproduced_from),
        ).fetchone()
        if rij is None:
            verschil.append("het origineel heeft geen resultaat om mee te vergelijken")
            return verschil
        for veld in ("result_schema_version", "backtest_engine_version",
                     "cost_model_version", "metrics_version", "segment_schema_version"):
            if rij[veld] != versies.get(veld):
                verschil.append(f"{veld}: {rij[veld]} -> {versies.get(veld)}")
        return verschil

    def end_run(self, experiment_id: int, status: Status | str, reden: str) -> None:
        """Een ander einde dan voltooid: failed, cancelled of interrupted.
        De voortgang tot dat moment blijft staan als diagnose."""
        def stappen():
            if self.conn.execute("SELECT 1 FROM wf_plans WHERE experiment_id=?",
                                 (experiment_id,)).fetchone():
                self._sluit_vensters(experiment_id, Status(status).value.upper(), reden)
            self.conn.execute(
                "UPDATE experiment_runs SET finished_at = ? WHERE experiment_id = ?",
                (_nu(), experiment_id),
            )
            self.transition(experiment_id, status, error=reden)
        self._in_transactie(stappen)

    # -- datasets ----------------------------------------------------------- #

    def create_snapshot(self, prepared: PreparedDataset, origin: str) -> tuple[int, bool]:
        """Sla een voorbereide snapshot op - in één transactie - of hergebruik hem.

        Volgorde: dataset (onverzegeld) en alle bars invoegen, daarna binnen
        dezelfde transactie de invarianten nalopen op wat werkelijk is
        opgeslagen (aantal, begin, einde, opnieuw berekende hash), en pas dan
        verzegelen. Faalt iets, dan wordt alles teruggedraaid: er blijft nooit
        een dataset achter met 20.000 bars in de metadata en 12.000 in de tabel.

        Bestaat dezelfde hash al, dan wordt die dataset teruggegeven - maar
        pas na controle van metadata en inhoud. Een hash alleen is niet genoeg.
        Geeft (dataset_id, hergebruikt).
        """
        spec = prepared.spec
        if prepared.hash != dataset_hash(spec, prepared.bars):
            raise DatasetIntegrityError("de hash past niet bij de aangeleverde bars")

        bestaand = self.conn.execute(
            "SELECT * FROM datasets WHERE hash=? AND hash_version=? AND sealed=1",
            (prepared.hash, HASH_VERSION),
        ).fetchone()
        if bestaand is not None:
            verwacht = {
                "symbol": spec.symbol, "timeframe": spec.timeframe,
                "instrument_precision": spec.instrument_precision,
                "timezone": spec.timezone, "bar_count": len(prepared.bars),
                "start_ts": prepared.start_ts, "end_ts": prepared.end_ts,
            }
            afwijkend = {k: (bestaand[k], v) for k, v in verwacht.items() if bestaand[k] != v}
            if afwijkend:
                raise DatasetIntegrityError(
                    f"hash-match met afwijkende metadata: {afwijkend}"
                )
            controle = self.verify_dataset(bestaand["id"])
            if not controle["ok"]:
                raise DatasetIntegrityError(f"bestaande snapshot klopt niet: {controle}")
            self.conn.execute(
                "INSERT INTO dataset_requests (dataset_id, requested_at, origin, reused) "
                "VALUES (?,?,?,1)", (bestaand["id"], _nu(), origin),
            )
            return int(bestaand["id"]), True

        p = spec.instrument_precision
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self.conn.execute(
                f"INSERT INTO datasets ({', '.join(_DATASET_KOLOMMEN)}, sealed) "
                f"VALUES ({', '.join('?' * len(_DATASET_KOLOMMEN))}, 0)",
                (spec.symbol, spec.timeframe, spec.source, prepared.start_ts,
                 prepared.end_ts, len(prepared.bars), prepared.hash, HASH_VERSION,
                 _nu(), spec.timezone, p, spec.precision_origin,
                 prepared.quality_status,
                 canonical_json([f.as_dict() for f in prepared.findings])),
            )
            ds_id = int(cur.lastrowid)
            self.conn.executemany(
                "INSERT INTO dataset_bars (dataset_id, ts, open, high, low, close, "
                "volume, source, bar_status) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    (ds_id, b.ts, _naar_geheel(b.open, p), _naar_geheel(b.high, p),
                     _naar_geheel(b.low, p), _naar_geheel(b.close, p), b.volume,
                     b.source, b.bar_status)
                    for b in prepared.bars
                ),
            )
            controle = self.verify_dataset(ds_id, verzegeld=False)
            if not controle["ok"]:
                raise DatasetIntegrityError(f"snapshot voldoet niet aan zijn invarianten: {controle}")
            self.conn.execute("UPDATE datasets SET sealed=1 WHERE id=?", (ds_id,))
            self.conn.execute(
                "INSERT INTO dataset_requests (dataset_id, requested_at, origin, reused) "
                "VALUES (?,?,?,0)", (ds_id, _nu(), origin),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return ds_id, False

    def dataset(self, dataset_id: int) -> dict | None:
        rij = self.conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if rij is None:
            return None
        uit = dict(rij)
        uit["quality"] = json.loads(uit.pop("quality_json"))
        return uit

    def dataset_bars(self, dataset_id: int) -> list[CanonicalBar]:
        """De opgeslagen bars, terug in canonieke vorm."""
        ds = self.conn.execute(
            "SELECT instrument_precision FROM datasets WHERE id=?", (dataset_id,)
        ).fetchone()
        if ds is None:
            return []
        p = ds[0]
        return [
            CanonicalBar(r["ts"], _uit_geheel(r["open"], p), _uit_geheel(r["high"], p),
                         _uit_geheel(r["low"], p), _uit_geheel(r["close"], p),
                         r["volume"], r["source"], r["bar_status"])
            for r in self.conn.execute(
                "SELECT * FROM dataset_bars WHERE dataset_id=? ORDER BY ts", (dataset_id,)
            ).fetchall()
        ]

    def verify_dataset(self, dataset_id: int, verzegeld: bool = True) -> dict:
        """Loop de invarianten na op wat werkelijk in de database staat."""
        ds = self.conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if ds is None:
            return {"ok": False, "reden": "bestaat niet"}
        telling = self.conn.execute(
            "SELECT COUNT(*), MIN(ts), MAX(ts) FROM dataset_bars WHERE dataset_id=?",
            (dataset_id,),
        ).fetchone()
        spec = DatasetSpec(ds["symbol"], ds["timeframe"], ds["instrument_precision"],
                           ds["precision_origin"], ds["source"], ds["timezone"])
        herberekend = dataset_hash(spec, self.dataset_bars(dataset_id))
        uitslag = {
            "count_ok": telling[0] == ds["bar_count"],
            "start_ok": telling[1] == ds["start_ts"],
            "end_ok": telling[2] == ds["end_ts"],
            "hash_ok": herberekend == ds["hash"],
            "sealed_ok": (ds["sealed"] == 1) if verzegeld else True,
        }
        uitslag["ok"] = all(uitslag.values())
        return uitslag


def _naar_geheel(prijs: str, precisie: int) -> int:
    return int(Decimal(prijs).scaleb(precisie))


def _uit_geheel(waarde: int, precisie: int) -> str:
    stap = Decimal(1).scaleb(-precisie)
    return format(Decimal(waarde).scaleb(-precisie).quantize(stap), "f")


class DatasetIntegrityError(LabDatabaseError):
    """Een snapshot voldoet niet aan zijn eigen invarianten."""




def try_open(path: str | Path) -> tuple[LabDatabase | None, str | None]:
    """Open de Lab-database, of geef de reden waarom dat niet lukt.

    Gooit nooit: een onbruikbare Lab-database mag de rest van Gold Scalper
    niet tegenhouden. Het Lab en de handel zijn gescheiden foutdomeinen.
    """
    try:
        return LabDatabase(path).open(), None
    except (LabDatabaseError, OSError, sqlite3.Error) as err:
        return None, str(err)

