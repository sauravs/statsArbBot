"""
Unit tests for ``marketdata.pair_series.current_prices`` (issue #37 PR-2).

Pure apart from the injected fake ``PriceSource`` — no DB / no network.
"""

from __future__ import annotations

import pytest

from marketdata.pair_series import current_prices
from tests.conftest import FakeDydxClient


@pytest.mark.asyncio
async def test_returns_latest_close_per_market():
    # closes_to_candles assigns increasing timestamps, so the last value is latest.
    client = FakeDydxClient({"AAA-USD": [10.0, 11.0, 12.5], "BBB-USD": [4.0, 3.0]})
    prices = await current_prices(client, ["AAA-USD", "BBB-USD"])
    assert prices == {"AAA-USD": 12.5, "BBB-USD": 3.0}


@pytest.mark.asyncio
async def test_dedupes_markets_and_omits_missing():
    client = FakeDydxClient({"AAA-USD": [1.0, 2.0]})
    # AAA repeated (shared across pairs) + a market with no data.
    prices = await current_prices(client, ["AAA-USD", "MISSING-USD", "AAA-USD"])
    assert prices == {"AAA-USD": 2.0}


@pytest.mark.asyncio
async def test_empty_markets_returns_empty():
    client = FakeDydxClient({"AAA-USD": [1.0]})
    assert await current_prices(client, []) == {}


@pytest.mark.asyncio
async def test_one_market_raising_does_not_blank_the_batch():
    # A market whose fetch *raises* (e.g. a network error) must not take down the
    # whole batch — the others still resolve (issue #50).
    class FlakyClient(FakeDydxClient):
        async def get_historical_closes(self, market, *, num_pages=None, now=None):
            if market == "BOOM-USD":
                raise RuntimeError("network blip")
            return await super().get_historical_closes(
                market, num_pages=num_pages, now=now
            )

    client = FlakyClient({"AAA-USD": [1.0, 2.0], "BBB-USD": [9.0]})
    prices = await current_prices(client, ["AAA-USD", "BOOM-USD", "BBB-USD"])
    assert prices == {"AAA-USD": 2.0, "BBB-USD": 9.0}
