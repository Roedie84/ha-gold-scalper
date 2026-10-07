"""1.5.0: één bron voor veilig herstarten, en een latency-staart bij weinig
metingen.

Live op 7 oktober: veilig_herstarten stond op aan, het attribuut
safe_to_restart op false (running, 0 open). En latency p99 was unknown met
24 metingen, wat het dashboard als 0 ms toonde.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.lifecycle import veilig_herstarten  # noqa: E402


class _Lc:
    def __init__(self, veilig):
        self.safe_to_restart = veilig


def test_zonder_posities_is_herstarten_veilig():
    assert veilig_herstarten([], _Lc(False))
    assert veilig_herstarten(None, _Lc(False))


def test_met_posities_alleen_na_afwikkelen():
    assert not veilig_herstarten([{"id": 1}], _Lc(False))
    assert veilig_herstarten([{"id": 1}], _Lc(True))


def test_coordinator_en_sensor_gebruiken_dezelfde_bron():
    basis = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")
    coord = open(os.path.join(basis, "coordinator.py"), encoding="utf-8").read()
    sensor = open(os.path.join(basis, "binary_sensor.py"), encoding="utf-8").read()
    assert '"safe_to_restart": veilig_herstarten(' in coord
    assert "return veilig_herstarten(" in sensor


def _staart(totaal):
    import ast

    basis = os.path.join(os.path.dirname(__file__), "..", "custom_components", "gold_scalper")
    bron = open(os.path.join(basis, "sensor.py"), encoding="utf-8").read()
    boom = ast.parse(bron)
    fn = next(
        n for n in ast.walk(boom)
        if isinstance(n, ast.FunctionDef) and n.name == "_staart_latency"
    )
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "sensor", "exec"), ns)
    return ns["_staart_latency"]({"latency": {"total": totaal}})


def test_p99_als_die_er_is():
    assert _staart({"samples": 150, "p90": 40.0, "p99": 90.0})[0] == 90.0


def test_p90_bij_weinig_metingen():
    waarde, basis = _staart({"samples": 24, "p90": 61.0, "median": 39.0})
    assert waarde == 61.0
    assert "p90" in basis and "n=24" in basis


def test_geen_waarde_onder_de_twintig():
    waarde, basis = _staart({"samples": 9, "median": 39.0})
    assert waarde is None
    assert "te weinig" in basis
