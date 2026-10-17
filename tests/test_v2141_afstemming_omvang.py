"""2.14.1: deelsluitingen van vóór 2.11.1 (24,5 oz in de administratie,
24 en 25 oz bij de broker) bleven als "ontbreekt" in de afstemming staan."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from gold_scalper.broker.ig_capital import match_transaction  # noqa: E402

OPEN = "2026-10-14T18:57:07.289+00:00"


def _tx(close, oz, dt_open, dt_close):
    return {"reference": "x", "dealId": "58311816", "openLevel": 4094.94, "closeLevel": close,
            "size": f"+{oz}", "openDateUtc": dt_open, "dateUtc": dt_close}


TXS = [_tx(4096.84, 24, "2026-10-14T18:57:07.591+00:00", "2026-10-14T18:58:28.343+00:00"),
       _tx(4096.11, 25, "2026-10-14T18:57:07.591+00:00", "2026-10-14T18:59:48.939+00:00")]


def test_deel_en_rest_gekoppeld_op_sluitmoment():
    deel = match_transaction(TXS, "58311816-deel", 4094.94, "buy", 24.5, OPEN,
                             "2026-10-14T18:58:28.355+00:00")
    rest = match_transaction(TXS, "58311816", 4094.94, "buy", 24.5, OPEN,
                             "2026-10-14T18:59:49.289+00:00")
    assert deel["exit_price"] == 4096.84
    assert rest["exit_price"] == 4096.11


def test_zonder_opentijd_blijft_streng():
    assert match_transaction([{**TXS[0], "openDateUtc": None, "reference": "", "dealId": ""}],
                             "zz", 4094.94, "buy", 24.5, None, None) is None


def test_andere_opentijd_blijft_streng():
    tx = {**TXS[0], "openDateUtc": "2026-10-14T18:58:07+00:00", "reference": "", "dealId": ""}
    assert match_transaction([tx], "zz", 4094.94, "buy", 24.5, OPEN, None) is None
