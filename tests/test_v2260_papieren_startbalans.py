"""2.26.0: een gewijzigde startbalans geldt ook voor de lopende papieren run.

Gevraagd 29-10 (Bitvavo-mand, papier): "start bedrag naar 1000000 zodat de
vloer nooit geraakt wordt maar er wel data wordt verzameld." De startbalans zit
niet in de vingerafdruk, dus bij een voortgezette run won altijd de opgeslagen
waarde (mand: ingesteld 100.000, run 10.000) en deed de instelling niets.
"""
import asyncio
from types import SimpleNamespace


def _zelf(db, run_id, opgeslagen, gekozen, papier=True):
    class _Hass:
        async def async_add_executor_job(self, f, *args):
            return f(*args)

    return SimpleNamespace(
        mode=SimpleNamespace(places_orders=not papier),
        run_id=run_id, db=db, hass=_Hass(),
        entry=SimpleNamespace(options={} if gekozen is None else {"starting_balance": gekozen}),
        starting_balance=opgeslagen,
    )


def _db(tmp_path):
    from gold_scalper.storage.database import TradeDatabase

    db = TradeDatabase(tmp_path / "m.db")
    db.connect()
    run = db.start_run("paper", "v1", "BTC-EUR", {}, 10000.0, None, "fp")
    return db, run


def _pas_toe(zelf):
    from gold_scalper.coordinator import GoldScalperCoordinator as G

    asyncio.run(G._pas_papieren_startbalans_toe(zelf))


def test_papier_neemt_de_ingestelde_startbalans_over(tmp_path):
    db, run = _db(tmp_path)
    zelf = _zelf(db, run, 10000.0, 1_000_000)

    _pas_toe(zelf)

    assert zelf.starting_balance == 1_000_000.0
    assert db.get_run(run)["starting_balance"] == 1_000_000.0
    kinds = [a["kind"] for a in db.run_annotations(run)]
    assert "startbalans_1000000" in kinds


def test_demo_en_live_blijven_ongemoeid(tmp_path):
    db, run = _db(tmp_path)
    zelf = _zelf(db, run, 10000.0, 1_000_000, papier=False)

    _pas_toe(zelf)

    assert zelf.starting_balance == 10000.0
    assert db.get_run(run)["starting_balance"] == 10000.0


def test_zonder_eigen_instelling_niets(tmp_path):
    db, run = _db(tmp_path)
    zelf = _zelf(db, run, 10000.0, None)

    _pas_toe(zelf)

    assert zelf.starting_balance == 10000.0


def test_gelijke_balans_geen_aantekening(tmp_path):
    db, run = _db(tmp_path)
    zelf = _zelf(db, run, 10000.0, 10000.0)

    _pas_toe(zelf)

    assert db.run_annotations(run) == []


def test_voortgezette_run_roept_het_aan():
    from pathlib import Path

    import gold_scalper.coordinator as c

    bron = Path(c.__file__).read_text(encoding="utf-8")
    blok = bron.split('self.starting_balance = float(existing["starting_balance"])')[1][:300]
    assert "await self._pas_papieren_startbalans_toe()" in blok
