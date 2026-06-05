"""
Unit tests for DydxDataClient.get_historical_closes concurrent page fetch (#61).

Uses an httpx mock transport that records how many requests are in flight at once
so we can prove the concurrent path overlaps the (disjoint) page fetches while the
default sequential path does not — and that both produce the same merged, sorted,
de-duplicated closes.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from exchanges.dydx.client import DydxDataClient


class _OverlapTransport(httpx.AsyncBaseTransport):
    """Records peak concurrent in-flight requests; returns one candle per page."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0
        self._n = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            # Hold the request open briefly so overlapping fetches actually coexist.
            await asyncio.sleep(0.05)
            self._n += 1
            # A distinct timestamp per page so the merge keeps all of them.
            started = f"2026-01-0{self._n}T00:00:00.000Z"
            body = {"candles": [{"startedAt": started, "close": f"{self._n}.0"}]}
            return httpx.Response(200, json=body)
        finally:
            self.in_flight -= 1


@pytest.mark.asyncio
async def test_concurrent_fetch_overlaps_pages():
    transport = _OverlapTransport()
    client = DydxDataClient(data_url="https://x", transport=transport)
    try:
        closes = await client.get_historical_closes(
            "AAA-USD", num_pages=3, concurrent=True
        )
    finally:
        await client.aclose()

    # Three disjoint pages merged, sorted ascending by timestamp.
    assert [c["close"] for c in closes] == [1.0, 2.0, 3.0]
    # The three page fetches overlapped (peak > 1) — proves they ran concurrently.
    assert transport.peak >= 2


@pytest.mark.asyncio
async def test_sequential_fetch_does_not_overlap():
    transport = _OverlapTransport()
    client = DydxDataClient(data_url="https://x", transport=transport)
    try:
        closes = await client.get_historical_closes(
            "AAA-USD", num_pages=3, concurrent=False
        )
    finally:
        await client.aclose()

    assert len(closes) == 3
    # Default path issues one request at a time.
    assert transport.peak == 1
