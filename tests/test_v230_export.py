"""2.3.0: export_data - archiefbars en trades als antwoord, alleen lezen."""
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "gold_scalper"


def test_dienst_is_geregistreerd_met_antwoord():
    bron = (PKG / "__init__.py").read_text(encoding="utf-8")
    assert "DOMAIN, SERVICE_EXPORT_DATA, _zeg_wat_er_misging(\"export_data\")(export_data)" in bron
    assert "supports_response=SupportsResponse.ONLY," in bron.split("SERVICE_EXPORT_DATA, _zeg")[1][:1500]


def test_dienst_vraagt_niets_bij_de_broker():
    bron = (PKG / "__init__.py").read_text(encoding="utf-8")
    blok = bron.split("async def export_data")[1].split("hass.services.async_register")[0]
    assert "venue" not in blok and "import_history" not in blok


def test_services_yaml_en_const():
    assert "export_data:" in (PKG / "services.yaml").read_text(encoding="utf-8")
    assert 'SERVICE_EXPORT_DATA: Final = "export_data"' in (PKG / "const.py").read_text(encoding="utf-8")


def test_archief_laden_levert_kolommen(tmp_path):
    from gold_scalper.analysis.signals import Candles
    from gold_scalper.storage.bar_archive import BarArchive

    a = BarArchive(tmp_path / "bars.db")
    a.connect()
    c = Candles(timestamp=[900, 1800], open=[1.0, 2.0], high=[1.5, 2.5], low=[0.5, 1.5],
                close=[1.2, 2.2], volume=[1, 1])
    a.store("X", "15m", c)
    terug = a.load("X", "15m")
    rijen = [list(r) for r in zip(terug.timestamp, terug.open, terug.high, terug.low, terug.close, terug.volume)]
    assert rijen[0] == [900, 1.0, 1.5, 0.5, 1.2, 1]
    assert a.available() == [{"symbol": "X", "timeframe": "15m", "bars": 2}]
