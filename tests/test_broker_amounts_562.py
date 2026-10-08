"""5.6.2: elke gesloten trade klopt op de cent met het overzicht van de broker.

Vastgesteld op 30-09 door het rapport naast het IG-overzicht te leggen:

* trade 17:07, 1,23 oz, 4169,14 -> 4159,95. Prijsbeweging -$11,30; IG boekte
  -€10,04 tegen 0,88785144. Het rapport gaf -$11,38: het eurobedrag was
  teruggerekend met de middenkoers (0,882) in plaats van die van de broker.
* De kolom "USD" in het rapport bevatte euro's, met één koers voor de hele run.

De vaste gevallen hieronder zijn die echte trades.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.ig_capital import match_transaction  # noqa: E402
from gold_scalper.learning.afstemming import stem_af  # noqa: E402
from gold_scalper.storage.database import Trade, TradeDatabase  # noqa: E402

NU = datetime(2026, 9, 30, 19, 0, tzinfo=timezone.utc)
MIDDEN = 0.882


def _trade(open_price, close_price, net, *, side="buy", volume=0.0123,
           cost=0.74, account=None, fx=None, bron=None, tid=1, ticket="DIAAAA1"):
    return Trade(
        id=tid, run_id=98, mode="demo", symbol="GOLD", side=side, volume=volume,
        open_time=(NU - timedelta(hours=1)).isoformat(), open_price=open_price,
        open_mid=open_price, open_spread=0.6,
        close_time=(NU - timedelta(minutes=10)).isoformat(),
        close_price=close_price, net_pnl=net, total_cost=cost,
        gross_pnl=None if net is None else net + cost,
        net_pnl_account=account, fx_rate=fx, fx_source=bron,
        close_reason="broker_gesloten_gecorrigeerd", broker_ticket=ticket,
    )


def _tx(open_level, close_level, eur, size, koers):
    return {
        "openLevel": str(open_level), "closeLevel": str(close_level),
        "profitAndLoss": f"E{eur}", "size": size,
        "instrumentName": f"Spot Gold ($1) converted at {koers}",
        "dateUtc": (NU - timedelta(minutes=10)).isoformat(),
    }


# 30-09 17:07, zoals het rapport hem had en zoals IG hem boekte.
T1707 = dict(open_price=4169.14, close_price=4159.95, net=-11.38)
TX1707 = _tx(4169.14, 4159.95, -10.04, "+1.23", 0.88785144)


# ------------------------------------------------------------- koppeling --

def test_the_match_carries_size_open_level_and_broker_rate():
    m = match_transaction([TX1707], "x", 4169.14, "buy", 1.23)
    assert m["size"] == pytest.approx(1.23)
    assert m["open_price"] == pytest.approx(4169.14)
    assert m["conversion_rate"] == pytest.approx(0.88785144)
    assert m["profit_account"] == pytest.approx(-10.04)


# ------------------------------------------------------------- afstemming --

def test_the_17_07_trade_is_brought_to_the_cent():
    trade = _trade(**T1707)
    uitslag = stem_af([trade], [TX1707], MIDDEN, NU)
    (overname,) = uitslag.overnames
    v = overname["velden"]
    # Dollars uit prijzen en omvang van de broker: exact de beweging.
    assert v["net_pnl"] == pytest.approx(-11.3037, abs=1e-4)
    assert v["net_pnl_account"] == pytest.approx(-10.04)
    assert v["fx_rate"] == pytest.approx(0.88785144)
    assert v["fx_source"] == "broker_settlement"
    assert v["gross_pnl"] == pytest.approx(-11.3037 + 0.74, abs=1e-4)
    # Het verschil was koersasymmetrie, geen fout: bijgewerkt, geen afwijking.
    assert uitslag.kloppend == 1 and uitslag.in_orde
    # En het eindresultaat rijmt op de cent met IG.
    assert abs(v["net_pnl"] * v["fx_rate"] - (-10.04)) < 0.01


def test_a_winner_uses_the_winning_rate():
    """04:07: IG rekent winst om tegen een lagere koers dan verlies."""
    trade = _trade(4169.07, 4177.57, 16.83, volume=0.0198, cost=1.27)
    tx = _tx(4169.07, 4177.57, 14.73, "+1.98", 0.875065024)
    uitslag = stem_af([trade], [tx], MIDDEN, NU)
    v = uitslag.overnames[0]["velden"]
    assert "net_pnl" not in v                  # dollars klopten al
    assert v["net_pnl_account"] == pytest.approx(14.73)
    assert v["fx_rate"] == pytest.approx(0.875065024)


def test_an_exact_trade_needs_nothing():
    trade = _trade(4169.14, 4159.95, -11.3037, account=-10.04,
                   fx=0.88785144, bron="broker_settlement")
    uitslag = stem_af([trade], [TX1707], MIDDEN, NU)
    assert uitslag.overnames == [] and uitslag.kloppend == 1


def test_the_filled_size_is_taken_from_the_broker():
    trade = _trade(4169.14, 4159.95, -11.38, volume=0.01238)
    uitslag = stem_af([trade], [TX1707], MIDDEN, NU)
    assert uitslag.overnames[0]["velden"]["volume"] == pytest.approx(0.0123)


def test_a_different_exit_is_never_adopted():
    trade = _trade(4169.14, 4165.00, -5.0)
    uitslag = stem_af([trade], [TX1707], MIDDEN, NU)
    assert uitslag.overnames == []
    assert "uitstap" in uitslag.afwijkingen[0].uitleg


def test_a_large_amount_difference_is_adopted_and_reported():
    trade = _trade(4169.14, 4159.95, -3.00)
    uitslag = stem_af([trade], [TX1707], MIDDEN, NU)
    assert uitslag.overnames[0]["velden"]["net_pnl_account"] == pytest.approx(-10.04)
    assert "overgenomen" in uitslag.afwijkingen[0].uitleg


def test_when_price_and_amount_disagree_the_booked_amount_wins():
    """Rijmt de prijsbeweging niet met wat de broker boekte, dan geldt zijn
    bedrag gedeeld door zijn koers."""
    trade = _trade(4169.14, 4159.95, -11.38)
    tx = _tx(4169.14, 4159.95, -9.50, "+1.23", 0.88785144)
    v = stem_af([trade], [tx], MIDDEN, NU).overnames[0]["velden"]
    assert v["net_pnl"] == pytest.approx(-9.50 / 0.88785144, abs=1e-4)


def test_without_a_broker_rate_nothing_is_adopted():
    tx = dict(TX1707)
    tx["instrumentName"] = "Spot Gold ($1)"
    uitslag = stem_af([_trade(**T1707)], [tx], MIDDEN, NU)
    assert uitslag.overnames == [] and uitslag.kloppend == 1


def test_the_summary_mentions_updates():
    uitslag = stem_af([_trade(**T1707)], [TX1707], MIDDEN, NU)
    assert "bijgewerkt naar het bedrag van de broker" in uitslag.samenvatting()
    assert uitslag.as_dict()["bijgewerkt"] == 1


# ----------------------------------------------------------- herstel oud --

def test_old_settlements_are_recomputed_with_the_broker_rate(tmp_path):
    db = TradeDatabase(tmp_path / "t.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    t = _trade(**T1707, account=-10.04, fx=0.88785144, bron="broker_settlement")
    t.id, t.run_id = None, run
    db.insert_trade(t)
    assert db.repair_broker_settlement_usd() == 1
    (hersteld,) = db.closed_trades(run)
    assert hersteld.net_pnl == pytest.approx(-10.04 / 0.88785144, abs=1e-4)
    assert hersteld.gross_pnl == pytest.approx(hersteld.net_pnl + 0.74, abs=1e-4)
    assert db.repair_broker_settlement_usd() == 0          # idempotent


def test_repair_leaves_other_trades_alone(tmp_path):
    db = TradeDatabase(tmp_path / "t.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {}, 10000.0, None, "fp")
    t = _trade(4186.17, 4179.99, -11.06, volume=0.0179, account=-9.70,
               fx=MIDDEN, bron="ig_instrument")
    t.id, t.run_id = None, run
    db.insert_trade(t)
    assert db.repair_broker_settlement_usd() == 0
    assert db.closed_trades(run)[0].net_pnl == pytest.approx(-11.06)


# ------------------------------------------------------------ coordinator --

def _coordinator(tmp_path, monkeypatch, transacties, deal=None):
    from test_broker_cycle import ScriptedVenue, _coordinator as maak

    class Venue(ScriptedVenue):
        async def transactions(self, van, tot):
            return transacties

        async def closed_deal(self, *args, **kwargs):
            return deal

    venue = Venue()
    coordinator, _ = maak(venue, tmp_path, monkeypatch)
    coordinator.conversion.instrument = "USD"
    coordinator.conversion.account = "EUR"
    coordinator.conversion.rate = MIDDEN
    return coordinator


def test_reconcile_writes_the_broker_amounts(tmp_path, monkeypatch):
    coordinator = _coordinator(tmp_path, monkeypatch, [TX1707])
    t = _trade(**T1707)
    t.id, t.run_id = None, coordinator.run_id
    t.close_time = datetime.now(timezone.utc).isoformat()
    coordinator.db.insert_trade(t)

    uitslag = asyncio.run(coordinator.async_reconcile())
    assert uitslag["bijgewerkt"] == 1 and uitslag["in_orde"]
    (opgeslagen,) = coordinator.db.closed_trades(coordinator.run_id)
    assert opgeslagen.net_pnl == pytest.approx(-11.3037, abs=1e-4)
    assert opgeslagen.net_pnl_account == pytest.approx(-10.04)
    assert opgeslagen.fx_rate == pytest.approx(0.88785144)
    assert opgeslagen.account_currency == "EUR"

    # Tweede keer: niets meer te doen.
    assert asyncio.run(coordinator.async_reconcile())["bijgewerkt"] == 0


def test_the_correction_divides_by_the_broker_rate(tmp_path, monkeypatch):
    deal = {"exit_price": 4159.95, "profit_account": -10.04,
            "conversion_rate": 0.88785144, "closed_at": NU.isoformat()}
    coordinator = _coordinator(tmp_path, monkeypatch, [], deal)
    t = _trade(4169.14, 4159.95, -9.0)
    t.id, t.run_id = None, coordinator.run_id
    t.close_reason = "broker_gesloten_geschat"
    coordinator.db.insert_trade(t)

    asyncio.run(coordinator._correct_estimated_settlements(NU))
    (gecorrigeerd,) = coordinator.db.closed_trades(coordinator.run_id)
    assert gecorrigeerd.net_pnl == pytest.approx(-10.04 / 0.88785144, abs=1e-3)
    assert gecorrigeerd.net_pnl != pytest.approx(-10.04 / MIDDEN, abs=1e-3)


# ---------------------------------------------------------------- rapport --

def test_the_report_column_shows_the_broker_amount_under_the_right_currency(tmp_path):
    from gold_scalper.dashboard.report import build_report

    db = TradeDatabase(tmp_path / "r.db")
    db.connect()
    run = db.start_run("demo", "v1", "GOLD", {"account_currency": "USD"}, 10000.0, None, "fp")
    exact = _trade(**T1707, account=-10.04, fx=0.88785144, bron="broker_settlement")
    benaderd = _trade(4186.17, 4179.99, -11.06, volume=0.0179, account=-9.75,
                      fx=MIDDEN, bron="ig_instrument", ticket="DIAAAA2")
    for t in (exact, benaderd):
        t.id, t.run_id = None, run
        db.insert_trade(t)

    html = build_report(db, run, conversion={"account": "EUR", "rate": MIDDEN})
    kop = html.split('<table class="trades">', 1)[1].split("</thead>", 1)[0]
    assert ">EUR<" in kop and ">USD<" not in kop
    assert ">-10.04<" in html                       # exact, van de broker
    assert "&asymp;-9.75<" in html                  # benadering, gemarkeerd
