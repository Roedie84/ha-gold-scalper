"""2.21.1: "HA sluit af" één keer per afsluitmoment, niet per mandlid.

Live 23-10 07:38:01: 22 identieke waarschuwingen binnen 0,3 s (één per lid
van de Bitvavo-mand plus de losse markten).
"""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper import lifecycle  # noqa: E402
from gold_scalper.lifecycle import LifecycleController, LifecycleState  # noqa: E402


@pytest.mark.asyncio
async def test_een_waarschuwing_per_afsluitmoment(caplog, monkeypatch):
    monkeypatch.setattr(lifecycle, "_laatste_afsluitmelding", None)
    caplog.set_level(logging.DEBUG, logger="custom_components.gold_scalper.lifecycle")
    caplog.set_level(logging.DEBUG, logger=lifecycle.__name__)
    ctrls = [LifecycleController() for _ in range(22)]
    for c in ctrls:
        await c.emergency_shutdown([])
    meldingen = [r for r in caplog.records if "HA sluit af" in r.getMessage()]
    assert len([r for r in meldingen if r.levelno == logging.WARNING]) == 1
    assert len([r for r in meldingen if r.levelno == logging.DEBUG]) == 21
    assert all(c.state == LifecycleState.STOPPED for c in ctrls)


@pytest.mark.asyncio
async def test_nieuw_afsluitmoment_meldt_weer(caplog, monkeypatch):
    monkeypatch.setattr(lifecycle, "_laatste_afsluitmelding", None)
    caplog.set_level(logging.DEBUG, logger=lifecycle.__name__)
    tijd = iter([1000.0, 1000.0 + lifecycle._AFSLUITMELDING_VENSTER_S + 1])
    monkeypatch.setattr(lifecycle, "_klok", lambda: next(tijd))
    await LifecycleController().emergency_shutdown([])
    await LifecycleController().emergency_shutdown([])
    waarsch = [
        r for r in caplog.records
        if "HA sluit af" in r.getMessage() and r.levelno == logging.WARNING
    ]
    assert len(waarsch) == 2


@pytest.mark.asyncio
async def test_flush_callbacks_lopen_nog_steeds(monkeypatch):
    monkeypatch.setattr(lifecycle, "_laatste_afsluitmelding", None)
    geroepen = []
    await LifecycleController().emergency_shutdown([lambda: geroepen.append(1)])
    assert geroepen == [1]
