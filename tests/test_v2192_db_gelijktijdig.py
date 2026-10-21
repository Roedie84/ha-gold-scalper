"""2.19.2: de tradedatabase verdraagt gelijktijdige aanroepen uit de executor.

Gemeten 21-10 20:59: de afstemming na de herstart faalde met *cannot commit -
no transaction is active*. Alle aanroepen delen één SQLite-verbinding
(``check_same_thread=False``) en lopen via ``async_add_executor_job`` in
verschillende threads. Commit thread A terwijl thread B net zijn eigen commit
afrondt, dan vindt A geen transactie meer.
"""

from __future__ import annotations

import os
import sys
import threading

HIER = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HIER, "..", "custom_components"))

from gold_scalper.storage.database import TradeDatabase  # noqa: E402
from gold_scalper.storage.latency import install_buffered_signals  # noqa: E402


def _db(tmp_path):
    db = TradeDatabase(tmp_path / "t.db")
    db.connect()
    return db


def test_gelijktijdig_schrijven_geeft_geen_transactiefout(tmp_path):
    db = _db(tmp_path)
    run_id = db.start_run("paper", "v", "XAUUSD", {}, 1000.0)
    fouten: list[BaseException] = []
    start = threading.Barrier(8)

    def werk(n):
        try:
            start.wait()
            for i in range(150):
                db.annotate_run(run_id, f"k{n}-{i}", "x")
                db.set_run_opening(run_id, 1000.0 + i, "EUR")
                db.list_runs(5)
        except BaseException as err:  # noqa: BLE001
            fouten.append(err)

    draden = [threading.Thread(target=werk, args=(n,)) for n in range(8)]
    for d in draden:
        d.start()
    for d in draden:
        d.join()
    assert not fouten, fouten[:3]
    assert len(db.run_annotations(run_id)) == 8 * 150


def test_gebufferde_signalen_wachten_op_dezelfde_slot(tmp_path):
    db = _db(tmp_path)
    run_id = db.start_run("paper", "v", "XAUUSD", {}, 1000.0)
    writer = install_buffered_signals(db, flush_interval=3600)
    fouten: list[BaseException] = []

    def signalen():
        try:
            for _ in range(20):
                for _ in range(50):
                    db.log_signal(run_id, 0.1, 0.2, "s", "r", 0.3, False, None, {})
                writer.flush()
        except BaseException as err:  # noqa: BLE001
            fouten.append(err)

    def runs():
        try:
            for i in range(300):
                db.annotate_run(run_id, f"r{threading.get_ident()}-{i}", "x")
        except BaseException as err:  # noqa: BLE001
            fouten.append(err)

    draden = [threading.Thread(target=signalen), threading.Thread(target=runs),
              threading.Thread(target=runs)]
    for d in draden:
        d.start()
    for d in draden:
        d.join()
    assert not fouten, fouten[:3]


def test_slot_is_herintreedbaar(tmp_path):
    # Methoden roepen elkaar aan (connect -> detect_mixed_runs); dat mag niet
    # vastlopen op de eigen slot.
    db = _db(tmp_path)
    db.close()
    db.connect()
    assert db.list_runs(1) == []
