"""1.9.6 - het paneel verspringt niet meer tijdens scrollen op mobiel."""
from pathlib import Path

JS = Path(__file__).parents[1] / "custom_components" / "gold_scalper" / "frontend" / "broker-panel.js"


def _js() -> str:
    return JS.read_text(encoding="utf-8")


def test_tekenen_wacht_tot_het_scrollen_klaar_is():
    js = _js()
    assert "const scrolltNog = () =>" in js
    assert "if (scrolltNog()) {" in js
    assert "_renderNu()" in js
    for gebeurtenis in ("scroll", "touchstart", "touchmove", "touchend", "touchcancel", "wheel"):
        assert f'window.addEventListener("{gebeurtenis}"' in js


def test_blok_alleen_vervangen_als_de_html_anders_is():
    js = _js()
    assert "function onthoudHtml(el)" in js
    assert 'for (const el of this._root.querySelectorAll("[id]")) onthoudHtml(el);' in js


def test_versie_196():
    import json
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
    from gold_scalper import const

    pkg = JS.parents[1]
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION
    log = (pkg.parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "\n## 1.9.6\n" in log
