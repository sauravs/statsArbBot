"""
Unit tests for HyperliquidTradeClient (branch `hyperliquid`, Slice 4a).

Drives the client with fake ``Exchange`` / ``Info`` objects — no SDK, network, or
wallet — exactly like the dYdX ``FakeTradeClient`` gate. Pins the SDK-response
parsing (fills, errors, non-fills), reduce_only routing through ``market_close``,
size rounding to the venue's szDecimals, signed-size position parsing, and the
safe-empty / None-on-failure discipline the engine relies on.
"""

from __future__ import annotations

import pytest

import config
from exchanges.hyperliquid.trade_client import HyperliquidTradeClient
from trading.broker import OrderResult, Position

ADDR = "0xabc0000000000000000000000000000000000000"


def _ok(total_sz: float, avg_px: float) -> dict:
    return {
        "status": "ok",
        "response": {"data": {"statuses": [{"filled": {"totalSz": str(total_sz), "avgPx": str(avg_px)}}]}},
    }


class FakeExchange:
    def __init__(self, response=None):
        self.response = response if response is not None else _ok(1.0, 100.0)
        self.opens: list[tuple] = []
        self.closes: list[tuple] = []
        self.cancels: list[tuple] = []

    def market_open(self, name, is_buy, sz, px, slippage):
        self.opens.append((name, is_buy, sz, px, slippage))
        return self.response

    def market_close(self, coin, sz, px, slippage):
        self.closes.append((coin, sz, px, slippage))
        return self.response

    def cancel(self, coin, oid):
        self.cancels.append((coin, oid))


class FakeInfo:
    def __init__(self, user_state=None, orders=None):
        self._user_state = user_state or {}
        self._orders = orders or []

    def user_state(self, address):
        return self._user_state

    def open_orders(self, address):
        return self._orders


def _client(exchange=None, info=None, sz_decimals=None) -> HyperliquidTradeClient:
    return HyperliquidTradeClient(
        exchange or FakeExchange(),
        info or FakeInfo(),
        address=ADDR,
        sz_decimals=sz_decimals or {"BTC": 3, "ETH": 2},
        slippage=0.05,
    )


@pytest.mark.asyncio
async def test_market_open_buy_parses_fill():
    ex = FakeExchange(_ok(0.123, 50000.0))
    c = _client(exchange=ex)
    res = await c.place_market_order(market="BTC", side="BUY", size=0.1234, reduce_only=False)
    assert isinstance(res, OrderResult)
    assert res.market == "BTC" and res.side == "BUY"
    assert res.size == 0.123 and res.price == 50000.0 and res.reduce_only is False
    # Routed through market_open with is_buy=True and size rounded to szDecimals (3).
    assert ex.opens and ex.opens[0][1] is True and ex.opens[0][2] == 0.123
    assert not ex.closes


@pytest.mark.asyncio
async def test_reduce_only_routes_through_market_close():
    ex = FakeExchange(_ok(2.0, 25.0))
    c = _client(exchange=ex)
    res = await c.place_market_order(market="ETH", side="SELL", size=2.0, reduce_only=True)
    assert res is not None and res.reduce_only is True
    assert ex.closes and ex.closes[0][0] == "ETH"
    assert not ex.opens


@pytest.mark.asyncio
async def test_order_not_ok_returns_none():
    c = _client(exchange=FakeExchange({"status": "err", "response": "rejected"}))
    assert await c.place_market_order(market="BTC", side="BUY", size=1.0) is None


@pytest.mark.asyncio
async def test_order_error_status_returns_none():
    resp = {"status": "ok", "response": {"data": {"statuses": [{"error": "insufficient margin"}]}}}
    c = _client(exchange=FakeExchange(resp))
    assert await c.place_market_order(market="BTC", side="BUY", size=1.0) is None


@pytest.mark.asyncio
async def test_size_rounds_to_zero_skips():
    # 0.0001 BTC rounded to 3 dp → 0.0 → no order placed.
    ex = FakeExchange()
    c = _client(exchange=ex)
    assert await c.place_market_order(market="BTC", side="BUY", size=0.0001) is None
    assert not ex.opens


@pytest.mark.asyncio
async def test_get_open_positions_parses_signed_size():
    state = {
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "0.5", "entryPx": "60000"}},
            {"position": {"coin": "ETH", "szi": "-3.0", "entryPx": "2500"}},
            {"position": {"coin": "SOL", "szi": "0", "entryPx": "0"}},  # flat → skipped
        ]
    }
    c = _client(info=FakeInfo(user_state=state))
    pos = await c.get_open_positions()
    assert set(pos) == {"BTC", "ETH"}
    assert pos["BTC"] == Position(market="BTC", side="LONG", size=0.5, entry_price=60000.0)
    assert pos["ETH"] == Position(market="ETH", side="SHORT", size=3.0, entry_price=2500.0)
    assert await c.is_open_position("BTC") is True
    assert await c.is_open_position("SOL") is False


@pytest.mark.asyncio
async def test_collateral_and_equity():
    state = {"withdrawable": "1234.5", "marginSummary": {"accountValue": "9876.5"}}
    c = _client(info=FakeInfo(user_state=state))
    assert await c.get_free_collateral() == 1234.5
    assert await c.get_account_equity() == 9876.5


@pytest.mark.asyncio
async def test_queries_safe_empty_on_failure():
    class Boom(FakeInfo):
        def user_state(self, address):
            raise RuntimeError("network down")

    c = _client(info=Boom())
    assert await c.get_open_positions() == {}
    assert await c.get_free_collateral() == 0.0
    assert await c.get_account_equity() == 0.0


@pytest.mark.asyncio
async def test_cancel_all_orders_cancels_each():
    ex = FakeExchange()
    info = FakeInfo(orders=[{"coin": "BTC", "oid": 1}, {"coin": "ETH", "oid": 2}])
    c = _client(exchange=ex, info=info)
    await c.cancel_all_orders()
    assert ex.cancels == [("BTC", 1), ("ETH", 2)]


@pytest.mark.asyncio
async def test_connect_without_key_raises(monkeypatch):
    monkeypatch.setattr(config, "HYPERLIQUID_PRIVATE_KEY", "")
    with pytest.raises(RuntimeError, match="HYPERLIQUID_PRIVATE_KEY"):
        await HyperliquidTradeClient.connect()
