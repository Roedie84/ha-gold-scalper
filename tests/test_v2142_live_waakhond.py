"""2.14.2: het paneel abonneert opnieuw als LIVE wegblijft.

Gemeld 19-10: Pepperstone-dashboard bleef op "elke 5 s" terwijl de server
de koers wel live stroomde (gecontroleerd via de websocket).
"""
from pathlib import Path

JS = (Path(__file__).parents[1] / "custom_components" / "gold_scalper"
      / "frontend" / "broker-panel.js").read_text(encoding="utf-8")


def test_waakhond_draait_elke_seconde():
    assert "this._bewaakLive(); }, 1000)" in JS
    assert "_bewaakLive() {" in JS


def test_waakhond_abonneert_opnieuw_en_wist_niet_beschikbaar():
    blok = JS.split("_bewaakLive() {", 1)[1].split("\n  }\n", 1)[0]
    assert "this._afmelden();" in blok
    assert "this._streamNiet = false;" in blok
    assert "this._abonneer();" in blok
    assert "LIVE_WAAKHOND_MS" in blok and "LIVE_NIET_OPNIEUW_MS" in blok
