"""1.9.1 - live koers via alternatieve IG-items, layout van de Markt-kaart.

IG antwoordde live op ``MARKET:<epic>`` met "REQERR 21 Invalid group". De
stroom probeert dan vanzelf minimale MARKET-velden, ``CHART:<epic>:TICK``
(DISTINCT) en ``CHART:<epic>:1MINUTE`` en onthoudt wat werkt. Daarnaast liepen
lange waarden in de Markt-kaart ("waarom geen trade") buiten de kaart.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.dashboard import stream as S  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "gold_scalper"
JS = (PKG / "frontend" / "broker-panel.js").read_text(encoding="utf-8")
CREDS = {"endpoint": "https://demo-apd.marketdatasystems.com", "user": "ACC1",
         "password": "CST-abc|XST-def", "epic": "CS.D.CFEGOLD.CEA.IP", "generatie": 1}
EPIC = CREDS["epic"]


class ControlTransport:
    """Nep-HTTP-transport: control-antwoorden per groep, stroom uit een lijst."""

    def __init__(self, antwoorden, stroom):
        self.antwoorden = antwoorden          # group -> antwoordregel
        self.stroom = list(stroom)
        self.controls = []

    async def create_session(self, params):
        pass

    def bound(self, sessie, link):
        pass

    async def control(self, params):
        self.controls.append(params)
        return self.antwoorden.get(params["LS_group"], f"REQOK,{params['LS_reqId']}")

    async def rebind(self):
        pass

    async def receive(self, timeout):
        await asyncio.sleep(0)
        return self.stroom.pop(0) if self.stroom else None

    async def close(self):
        pass


def _run(tr, variant=0):
    ticks, live, gekozen = [], [], []

    async def go():
        try:
            await S.run_connection(tr, CREDS, ticks.append, lambda: live.append(1),
                                   clock=lambda: 7.0, variant=variant,
                                   on_variant=gekozen.append)
        except S.TlcpError as err:
            return err
        return None

    fout = asyncio.run(go())
    return ticks, live, gekozen, fout


def test_variant_order_and_params():
    namen = [v["naam"] for v in S.LS_VARIANTEN]
    assert namen == ["MARKET", "MARKET-minimaal", "CHART-TICK", "CHART-1MINUTE"]
    p = [S.subscribe_params(EPIC, i + 1, i + 1, v) for i, v in enumerate(S.LS_VARIANTEN)]
    assert p[1]["LS_group"] == f"MARKET:{EPIC}" and p[1]["LS_schema"] == "BID OFFER UPDATE_TIME MARKET_STATE"
    assert p[2]["LS_group"] == f"CHART:{EPIC}:TICK" and p[2]["LS_mode"] == "DISTINCT"
    assert p[2]["LS_schema"] == "BID OFR LTP UTM"
    assert p[3]["LS_group"] == f"CHART:{EPIC}:1MINUTE" and p[3]["LS_mode"] == "MERGE"
    assert p[3]["LS_schema"] == "BID_CLOSE OFR_CLOSE UTM CONS_END"
    for x in p:
        assert "LS_data_adapter" not in x          # IG: standaardadapter
    # ':' wordt %3A in het formulier en komt bij de server terug als ':'
    from urllib.parse import parse_qs
    body = S.encode_params(p[2])
    assert "LS_group=CHART%3ACS.D.CFEGOLD.CEA.IP%3ATICK" in body
    assert parse_qs(body)["LS_group"] == [f"CHART:{EPIC}:TICK"]


def test_reqerr_21_falls_back_to_chart_tick():
    tr = ControlTransport(
        {f"MARKET:{EPIC}": "REQERR,1,21,Invalid group"},
        ["CONOK,S1,50000,5000,*", "SUBOK,3,1,4",
         "U,3,1,4130.1|4130.4|4130.25|1791523200123",
         "U,3,1,4130.2||4130.3|1791523201456",
         "U,1,1,9999|9999|x|y",                   # oud abonnement: negeren
         None])
    # MARKET (beide varianten) geweigerd, CHART-TICK geaccepteerd
    ticks, live, gekozen, fout = _run(tr)
    groepen = [c["LS_group"] for c in tr.controls]
    assert groepen == [f"MARKET:{EPIC}", f"MARKET:{EPIC}", f"CHART:{EPIC}:TICK"]
    assert [c["LS_subId"] for c in tr.controls] == [1, 2, 3]
    assert [c["LS_reqId"] for c in tr.controls] == [1, 2, 3]
    assert gekozen[0] == 2 and live == [1]
    assert [t["bied"] for t in ticks] == [4130.1, 4130.2]
    assert ticks[1]["laat"] == 4130.4                 # OFR = laat, ongewijzigd
    assert ticks[0]["broker_tijd"] == "05:20:00"      # UTM epoch-ms -> UTC
    assert fout.soort == "GESLOTEN"


def test_chart_1minute_parsing():
    w = ["4131.5", "4131.8", "1791523260000", "0"]
    t = S.tick_from_values(w, 9.0, S.LS_VARIANTEN[3]["schema"])
    assert t["bied"] == 4131.5 and t["laat"] == 4131.8
    assert t["mid"] == pytest.approx(4131.65) and t["spread"] == pytest.approx(0.3)
    assert t["broker_tijd"] == "05:21:00" and t["tijd"] == 9.0
    # MARKET blijft werken zoals in 1.8.x
    m = S.tick_from_values(["1", "2", "12:00:00", None, None, None, None, "TRADEABLE"], 1.0)
    assert m["bied"] == 1 and m["laat"] == 2 and m["broker_tijd"] == "12:00:00"
    assert m["markt"] == "TRADEABLE"
    # onzin in UTM breekt niets
    assert S.tick_from_values(["1", "2", "abc", None], 1.0, S.LS_VARIANTEN[3]["schema"])["broker_tijd"] is None


def test_all_variants_refused_one_error_with_codes():
    tr = ControlTransport(
        {f"MARKET:{EPIC}": "REQERR,1,21,Invalid group",
         f"CHART:{EPIC}:TICK": "REQERR,3,23,Invalid schema",
         f"CHART:{EPIC}:1MINUTE": "REQERR,4,21,Invalid group"},
        ["CONOK,S1,50000,5000,*"])
    ticks, live, gekozen, fout = _run(tr)
    assert fout.soort == "REQERR" and fout.code == "alle"
    for deel in ("MARKET REQERR 21", "MARKET-minimaal REQERR 21",
                 "CHART-TICK REQERR 23", "CHART-1MINUTE REQERR 21"):
        assert deel in fout.tekst
    assert len(tr.controls) == 4 and not live and not gekozen


def test_other_reqerr_is_not_a_variant_problem():
    tr = ControlTransport({f"MARKET:{EPIC}": "REQERR,1,20,Session not found"},
                          ["CONOK,S1,50000,5000,*"])
    _t, _l, _g, fout = _run(tr)
    assert fout.code == "20" and len(tr.controls) == 1


def test_remembered_variant_is_tried_first():
    tr = ControlTransport({}, ["CONOK,S1,50000,5000,*", "SUBOK,1,1,4", None])
    _t, live, gekozen, _f = _run(tr, variant=2)
    assert tr.controls[0]["LS_group"] == f"CHART:{EPIC}:TICK"
    assert gekozen[-1] == 2 and live == [1]
    assert S._variant_volgorde(2) == [2, 0, 1, 3]
    assert S._variant_volgorde(9) == [0, 1, 2, 3]


def test_pricestream_remembers_variant_and_warns_once_with_codes(monkeypatch, caplog):
    monkeypatch.setattr(S, "LS_BACKOFF_SECONDS", (0.01,))
    weiger_alles = {f"MARKET:{EPIC}": "REQERR,1,21,Invalid group",
                    f"CHART:{EPIC}:TICK": "REQERR,1,21,Invalid group",
                    f"CHART:{EPIC}:1MINUTE": "REQERR,1,21,Invalid group"}
    transports = [
        ControlTransport({f"MARKET:{EPIC}": "REQERR,1,21,Invalid group"},
                         ["CONOK,S1,50000,5000,*", "SUBOK,3,1,4", None]),
    ]

    async def go():
        geopend = []

        async def open_transport(endpoint):
            geopend.append(endpoint)
            if transports:
                return transports.pop(0)
            return ControlTransport(weiger_alles, ["CONOK,S1,50000,5000,*"])

        ps = S.PriceStream(lambda: dict(CREDS), open_transport)
        ps.subscribe(lambda m: None)
        await asyncio.sleep(0.01)
        onthouden = ps.variant
        await asyncio.sleep(0.1)
        await ps.async_stop()
        return onthouden

    with caplog.at_level(logging.DEBUG, logger=S.__name__):
        onthouden = asyncio.run(go())
    assert onthouden == 2                              # CHART-TICK werkte
    w = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(w) == 1
    # eerste fout: verbinding dicht na live; daarna alles geweigerd -> geen
    # tweede WARNING, wel DEBUG met de codes
    alles = "\n".join(r.getMessage() for r in caplog.records)
    assert "CHART-TICK REQERR 21" in alles


def test_stream_still_display_only():
    code = (PKG / "dashboard" / "stream.py").read_text(encoding="utf-8").split('"""', 2)[2]
    for verboden in ("place_order", "coordinator", "self._request(", "_login("):
        assert verboden not in code


# ------------------------------------------------------------ layout -- #

def test_css_long_values_wrap_inside_card():
    assert ".rijen > div { display: grid; grid-template-columns: max-content minmax(0, 1fr)" in JS
    rijen_b = JS.split(".rijen b {")[1].split("}")[0]
    assert "overflow-wrap: anywhere" in rijen_b and "white-space: normal" in rijen_b
    assert "min-width: 0" in rijen_b
    assert "max-width: 1800px" in JS and "max-width: 1720px" not in JS


def _playwright():
    for kandidaat in ("/opt/npm-tools/node_modules/playwright/index.mjs",):
        if Path(kandidaat).exists():
            module = kandidaat
            break
    else:
        return None
    chrome = None
    for pad in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")):
        chrome = str(pad)
    if not chrome or not shutil.which("node"):
        return None
    return module, chrome


def test_playwright_market_card_and_full_width(tmp_path):
    pw = _playwright()
    if pw is None:
        pytest.skip("Playwright/Chromium niet beschikbaar")
    module, chrome = pw
    fx = ROOT / "tests" / "fixtures"
    shutil.copy(fx / "broker_panel_v191.html", tmp_path / "broker_panel_v191.html")
    shutil.copy(PKG / "frontend" / "broker-panel.js", tmp_path / "broker-panel.js")
    script = (fx / "broker_panel_v191.mjs").read_text(encoding="utf-8").replace(
        "PLAYWRIGHT_MODULE", module)
    (tmp_path / "check.mjs").write_text(script, encoding="utf-8")
    shot = os.environ.get("GS_V191_SHOT") or str(tmp_path / "v191.png")
    res = subprocess.run(["node", str(tmp_path / "check.mjs"), str(tmp_path), shot],
                         capture_output=True, text=True, timeout=120,
                         env={**os.environ, "PW_CHROMIUM": chrome})
    uit = res.stdout + res.stderr
    assert res.returncode == 0 and "\nOK" in "\n" + res.stdout, uit
    assert "desktop scroll 1496 1496" in uit and "buiten 0" in uit
    assert "mobiel scroll 390 390" in uit


def test_version_and_changelog():
    from gold_scalper import const

    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION
    sectie = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("\n## 1.9.1\n")[1].split("\n## ")[0]
    assert "REQERR 21" in sectie and "CHART" in sectie and "Markt" in sectie
