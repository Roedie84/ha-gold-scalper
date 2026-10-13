"""2.6.0: een IG-verzoekenlimiet (403 exceeded-*) leidt niet tot opnieuw inloggen."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from gold_scalper.broker.adapter import VenueError  # noqa: E402
from gold_scalper.broker.ig_capital import IgVenue, _is_limietfout  # noqa: E402
from gold_scalper.const import INTEGRATION_VERSION  # noqa: E402

from test_ig_capital import MARKET, FakeResponse, FakeSession  # noqa: E402


def test_versie():
    assert tuple(map(int, INTEGRATION_VERSION.split("."))) >= (2, 6, 0)


def test_is_limietfout():
    assert _is_limietfout({"errorCode": "error.public-api.exceeded-account-allowance"})
    assert _is_limietfout({"errorCode": "error.public-api.exceeded-api-key-allowance"})
    assert not _is_limietfout({"errorCode": "error.security.client-token-invalid"})
    assert not _is_limietfout(None)
    assert not _is_limietfout("tekst")


class Teller(FakeSession):
    """Eerste verzoek na het inloggen krijgt de gegeven 403, daarna MARKET."""

    def __init__(self, code):
        super().__init__({})
        self.code = code
        self.n = 0

    def request(self, method, url, **kw):
        self.calls.append({"method": method, "url": url})
        self.n += 1
        if self.n == 1:
            return FakeResponse({"errorCode": self.code}, 403)
        return FakeResponse(MARKET[0], 200)


def _logins(sessie):
    return sum(1 for c in sessie.calls if c["method"] == "POST" and "/session" in c["url"])


def test_limiet_geeft_fout_zonder_herlogin():
    sessie = Teller("error.public-api.exceeded-account-allowance")
    venue = IgVenue(sessie, "k", "u", "p", environment="demo", epic="GOLD")
    with pytest.raises(VenueError, match="exceeded-account-allowance"):
        asyncio.run(venue.quote())
    assert _logins(sessie) == 1  # alleen de eerste sessie, geen tweede
    assert sessie.n == 1  # niet opnieuw geprobeerd
    assert venue._cst == "cst-token"  # sessie blijft staan


def test_sleutellimiet_ook_zonder_herlogin():
    sessie = Teller("error.public-api.exceeded-api-key-allowance")
    venue = IgVenue(sessie, "k", "u", "p", environment="demo", epic="GOLD")
    with pytest.raises(VenueError, match="Rate limit van de sleutel"):
        asyncio.run(venue.quote())
    assert _logins(sessie) == 1


def test_andere_403_logt_nog_wel_opnieuw_in():
    sessie = Teller("error.security.client-token-invalid")
    venue = IgVenue(sessie, "k", "u", "p", environment="demo", epic="GOLD")
    q = asyncio.run(venue.quote())
    assert q.bid == pytest.approx(3300.1)
    assert _logins(sessie) == 2
