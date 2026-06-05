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

import config
import exchanges.dydx.client as client_mod
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


class _Counter:
    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0


class _SharedCounterTransport(httpx.AsyncBaseTransport):
    """Counts in-flight requests against a shared counter (across clients)."""

    def __init__(self, counter: _Counter) -> None:
        self._c = counter
        self._n = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._c.in_flight += 1
        self._c.peak = max(self._c.peak, self._c.in_flight)
        try:
            await asyncio.sleep(0.05)
            self._n += 1
            body = {"candles": [{"startedAt": f"2026-01-0{self._n}T00:00:00.000Z", "close": "1.0"}]}
            return httpx.Response(200, json=body)
        finally:
            self._c.in_flight -= 1


@pytest.mark.asyncio
async def test_global_cap_limits_concurrency_across_clients(monkeypatch):
    """Issue #65: every DydxDataClient draws from one process-wide gate, so even
    separate client instances (one per call site) can't burst the indexer."""
    monkeypatch.setattr(config, "DYDX_INDEXER_MAX_CONCURRENCY", 2)
    # Reset the lazily-built global so it picks up the patched cap + this loop.
    monkeypatch.setattr(client_mod, "_indexer_sem", None)
    monkeypatch.setattr(client_mod, "_indexer_sem_loop", None)

    counter = _Counter()
    c1 = DydxDataClient(data_url="https://x", transport=_SharedCounterTransport(counter))
    c2 = DydxDataClient(data_url="https://x", transport=_SharedCounterTransport(counter))
    try:
        # 2 clients × 3 concurrent pages = 6 requests wanting to run at once.
        await asyncio.gather(
            c1.get_historical_closes("A-USD", num_pages=3, concurrent=True),
            c2.get_historical_closes("B-USD", num_pages=3, concurrent=True),
        )
    finally:
        await c1.aclose()
        await c2.aclose()

    # The shared gate held total in-flight to the cap despite 6 wanting to run.
    assert counter.peak <= 2


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
