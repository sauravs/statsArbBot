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
async def test_uses_bulk_get_current_prices_when_client_provides_it():
    """A venue that exposes ``get_current_prices`` (Hyperliquid's one-shot
    ``allMids``) is used directly — the per-market candle loop is bypassed so a
    large pairs set costs one request, not one per market (issue #142)."""

    class BulkClient(FakeDydxClient):
        def __init__(self):
            super().__init__({})
            self.bulk_calls = 0
            self.per_market_calls = 0

        async def get_current_prices(self, markets):
            self.bulk_calls += 1
            return {m: 7.0 for m in markets if m != "MISSING"}

        async def get_historical_closes(self, market, *, num_pages=None, now=None):
            self.per_market_calls += 1
            return await super().get_historical_closes(market, num_pages=num_pages, now=now)

    client = BulkClient()
    prices = await current_prices(client, ["AAA", "BBB", "MISSING", "AAA"])
    assert prices == {"AAA": 7.0, "BBB": 7.0}
    assert client.bulk_calls == 1
    assert client.per_market_calls == 0  # per-market path never touched


@pytest.mark.asyncio
async def test_bulk_failure_is_resilient_returns_empty():
    """A failing bulk call yields an empty column, never a 500 (issue #142)."""

    class BrokenBulkClient(FakeDydxClient):
        async def get_current_prices(self, markets):
            raise RuntimeError("allMids blip")

    prices = await current_prices(BrokenBulkClient({}), ["AAA", "BBB"])
    assert prices == {}


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
