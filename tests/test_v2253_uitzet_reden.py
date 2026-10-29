"""2.25.3: de logregel bij een uitgezette veldproefopzet noemt de reden.

Leerronde 28-10 19:43: "Veldproefopzet vp:donchian:15m uitgezet: n=40,
netto -683.92, t=None" - bij de kostenregel is t altijd None; dat de bruto
beweging de kosten niet dekte stond nergens.
"""
import inspect

from custom_components.gold_scalper.strategy import veldproef as vp


def test_kostenregel_noemt_bruto_en_kosten():
    uit = vp.kosten_uitgezet({"vp:donchian:15m": {"n": 40, "bruto": 120.0, "kosten": 803.92, "netto": -683.92}})
    tekst = vp.uitzet_reden(uit["vp:donchian:15m"])

    assert "kostenregel" in tekst
    assert "120.0" in tekst and "803.92" in tekst
    assert "None" not in tekst


def test_handmatig_en_groep_en_t_regel():
    assert vp.uitzet_reden({"t": -1.2, "handmatig": True}).startswith("tijdvak met de hand uit")
    assert vp.uitzet_reden({"t": -2.1, "groep": "3m"}) == "groep 3m uit, t=-2.1"
    assert vp.uitzet_reden({"t": -1.8}) == "t=-1.8"


def test_logregel_gebruikt_de_reden():
    from custom_components.gold_scalper import coordinator

    bron = inspect.getsource(coordinator)
    assert "veldproef_mod.uitzet_reden(nieuw[naam])" in bron
    assert "Veldproefopzet %s uitgezet: n=%s, netto %s, t=%s" not in bron
