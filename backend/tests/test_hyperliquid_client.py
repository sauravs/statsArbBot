"""
Unit tests for HyperliquidDataClient (branch `hyperliquid`, Phase 1).

The thing that matters most is **normalisation**: the venue-agnostic ingest path
reads dYdX-shaped keys straight off whatever a data client returns, so these tests
pin that Hyperliquid's native ``/info`` shapes (``{t,o,h,l,c,v}`` candles in epoch
ms; ``{time,fundingRate}`` funding; ``metaAndAssetCtxs``) are mapped onto the same
keys (``startedAt`` / ``baseTokenVolume`` / ``effectiveAt`` / ``rate`` …) with the
right types, ordering, and market filtering.

An httpx mock transport routes by the POSTed ``/info`` query ``type`` so one fake
stands in for the live API.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

import config
from exchanges.hyperliquid.client import HyperliquidDataClient


def _route(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    qtype = body.get("type")

    if qtype == "metaAndAssetCtxs":
        meta = {
            "universe": [
                {"name": "BTC", "szDecimals": 3, "maxLeverage": 50},
                {"name": "TINY", "szDecimals": 2, "maxLeverage": 10},
                {"name": "USDC", "szDecimals": 2, "maxLeverage": 5},
                {"name": "OLD", "szDecimals": 2, "maxLeverage": 5, "isDelisted": True},
            ],
        }
        ctxs = [
            {"dayNtlVlm": "5000000.0", "markPx": "50000.0", "funding": "0.0000125"},
            {"dayNtlVlm": "100.0", "markPx": "1.0", "funding": "0.0"},   # below MIN
            {"dayNtlVlm": "9000000.0", "markPx": "1.0", "funding": "0.0"},  # stable
            {"dayNtlVlm": "9000000.0", "markPx": "9.0", "funding": "0.0"},  # delisted
        ]
        return httpx.Response(200, json=[meta, ctxs])

    if qtype == "candleSnapshot":
        # Deliberately out of order to prove sorting; strings as the API returns.
        return httpx.Response(
            200,
            json=[
                {"t": 1700003600000, "o": "11", "h": "13", "l": "10", "c": "12", "v": "7"},
                {"t": 1700000000000, "o": "1", "h": "3", "l": "0.5", "c": "2", "v": "5"},
            ],
        )

    if qtype == "fundingHistory":
        return httpx.Response(
            200,
            json=[
                {"coin": "BTC", "fundingRate": "0.0000125", "premium": "0.0", "time": 1700000000000},
            ],
        )

    if qtype == "allMids":
        # {coin: priceStr} for the whole universe in one response (perps keyed by
        # coin; spot pairs by "@idx"). Only the requested coins are returned.
        return httpx.Response(
            200,
            json={"BTC": "50000.5", "ETH": "3000.0", "@1": "1.0"},
        )

    return httpx.Response(404, json={"error": "unhandled"})


def _client() -> HyperliquidDataClient:
    return HyperliquidDataClient(
        data_url="https://hl.test", transport=httpx.MockTransport(_route)
    )


@pytest.mark.asyncio
async def test_get_markets_filters_and_keys_by_coin():
    async with _client() as client:
        markets = await client.get_markets()
    # BTC kept; TINY dropped (below MIN_LIQUIDITY_USD), USDC dropped (stablecoin),
    # OLD dropped (delisted).
    assert set(markets) == {"BTC"}
    assert markets["BTC"]["volume24H"] == 5_000_000.0
    assert markets["BTC"]["name"] == "BTC"


@pytest.mark.asyncio
async def test_historical_closes_sorted_and_float():
    async with _client() as client:
        closes = await client.get_historical_closes("BTC", num_pages=1)
    # Sorted ascending by timestamp; close coerced to float.
    assert [c["close"] for c in closes] == [2.0, 12.0]
    assert all(isinstance(c["close"], float) for c in closes)
    assert closes[0]["datetime"] < closes[1]["datetime"]


@pytest.mark.asyncio
async def test_fetch_ohlcv_range_normalises_to_dydx_keys():
    start = datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc)
    end = datetime(2023, 11, 15, 0, 0, tzinfo=timezone.utc)
    async with _client() as client:
        bars = await client.fetch_ohlcv_range("BTC", start, end)
    assert bars, "expected normalised bars"
    bar = bars[0]
    # The exact dYdX-shaped keys the ingest orchestrator reads, as floats.
    assert set(bar) == {"startedAt", "open", "high", "low", "close", "baseTokenVolume"}
    assert isinstance(bar["startedAt"], str) and bar["startedAt"].endswith("Z")
    for k in ("open", "high", "low", "close", "baseTokenVolume"):
        assert isinstance(bar[k], float)


@pytest.mark.asyncio
async def test_fetch_funding_range_normalises_to_dydx_keys():
    start = datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc)
    end = datetime(2023, 11, 15, 0, 0, tzinfo=timezone.utc)
    async with _client() as client:
        funding = await client.fetch_funding_range("BTC", start, end)
    assert funding == [{"effectiveAt": funding[0]["effectiveAt"], "rate": 0.0000125}]
    assert funding[0]["effectiveAt"].endswith("Z")


@pytest.mark.asyncio
async def test_get_current_prices_bulk_maps_allmids(monkeypatch):
    """One ``allMids`` call → {market: float} for the requested markets; absent
    markets omitted (issue #142 — replaces the per-market candleSnapshot fan-out)."""
    calls: list[str] = []

    async def _spy(self, body):
        calls.append(body.get("type"))
        return await _orig_info(self, body)

    _orig_info = HyperliquidDataClient._info
    monkeypatch.setattr(HyperliquidDataClient, "_info", _spy)

    async with _client() as client:
        prices = await client.get_current_prices(["BTC", "ETH", "MISSING", "BTC"])

    assert prices == {"BTC": 50000.5, "ETH": 3000.0}  # MISSING omitted, de-duped
    assert all(isinstance(v, float) for v in prices.values())
    assert calls == ["allMids"], "must be a single bulk request, not per-market"


@pytest.mark.asyncio
async def test_unsupported_resolution_raises():
    with pytest.raises(ValueError):
        HyperliquidDataClient(resolution="3HOURS")
