"""
Unit tests for the offline demo trade client + the make_trade_client fake seam
(Phase 5b). These back the network-free live-trading UI E2E: with
``SCAN_DATA_SOURCE=fake`` the engine drives a real ``TradeClient`` that simulates
fills and holds positions/collateral in process-level state across passes.
"""

from __future__ import annotations

import pytest

import config
import exchanges
from exchanges.demo import DemoTradeClient, reset_demo_account
from trading.broker import TradeClient


@pytest.fixture(autouse=True)
def _clean_demo_account():
    reset_demo_account()
    yield
    reset_demo_account()


async def test_make_trade_client_returns_demo_in_fake_mode(monkeypatch):
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "fake")
    client = await exchanges.make_trade_client()
    assert isinstance(client, DemoTradeClient)
    # Satisfies the protocol the engine/agent depend on.
    assert isinstance(client, TradeClient)


async def test_demo_account_serves_fixed_collateral_and_equity():
    client = DemoTradeClient()
    assert await client.get_free_collateral() == 10_000.0
    assert await client.get_account_equity() == 10_000.0
    # Comfortably above USD_MIN_COLLATERAL so the entry collateral guard passes.
    assert await client.get_free_collateral() >= config.USD_MIN_COLLATERAL


async def test_open_then_reduce_only_close_tracks_position():
    client = DemoTradeClient()
    result = await client.place_market_order(market="DEMO3-USD", side="SELL", size=2.0)
    assert result is not None and result.market == "DEMO3-USD"
    assert await client.is_open_position("DEMO3-USD") is True
    positions = await client.get_open_positions()
    assert positions["DEMO3-USD"].side == "SHORT"

    await client.place_market_order(
        market="DEMO3-USD", side="BUY", size=2.0, reduce_only=True
    )
    assert await client.is_open_position("DEMO3-USD") is False


async def test_position_state_persists_across_client_instances():
    # The engine builds a fresh client per pass; demo state must survive (a real
    # exchange holds positions between calls).
    first = DemoTradeClient()
    await first.place_market_order(market="DEMO1-USD", side="BUY", size=1.0)
    await first.aclose()

    second = DemoTradeClient()
    assert await second.is_open_position("DEMO1-USD") is True


async def test_reset_demo_account_clears_positions():
    client = DemoTradeClient()
    await client.place_market_order(market="DEMO1-USD", side="BUY", size=1.0)
    reset_demo_account()
    assert await client.get_open_positions() == {}
