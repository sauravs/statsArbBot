"""
Tests for the exchange client factories (`exchanges.make_data_client` /
`make_trade_client`) — the one switch every consumer routes through.

Pins the Slice-1 dispatch: `SCAN_DATA_SOURCE=hyperliquid` yields the live HL data
client, an unknown source raises (no silent default), and HL *trading* is rejected
until Slice 4 so a venue with live data but no trade client can never silently
route orders to dYdX.
"""

from __future__ import annotations

import pytest

import config
from exchanges import make_data_client, make_trade_client
from exchanges.demo import DemoDataClient
from exchanges.dydx.client import DydxDataClient
from exchanges.hyperliquid.client import HyperliquidDataClient


@pytest.mark.parametrize(
    "source, expected",
    [
        ("fake", DemoDataClient),
        ("dydx", DydxDataClient),
        ("hyperliquid", HyperliquidDataClient),
    ],
)
def test_make_data_client_dispatch(monkeypatch, source, expected):
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", source)
    client = make_data_client()
    assert isinstance(client, expected)


def test_make_data_client_unknown_source_raises(monkeypatch):
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "bogus")
    with pytest.raises(ValueError, match="unknown SCAN_DATA_SOURCE"):
        make_data_client()


@pytest.mark.asyncio
async def test_make_trade_client_rejects_hyperliquid(monkeypatch):
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "hyperliquid")
    with pytest.raises(NotImplementedError, match="Hyperliquid trading"):
        await make_trade_client()


@pytest.mark.asyncio
async def test_make_trade_client_unknown_source_raises(monkeypatch):
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "bogus")
    with pytest.raises(ValueError, match="unknown SCAN_DATA_SOURCE"):
        await make_trade_client()


@pytest.mark.parametrize(
    "source, expected",
    [
        ("dydx", "dydx"),
        ("hyperliquid", "hyperliquid"),
        ("fake", "dydx"),  # offline source has no venue → DEFAULT_EXCHANGE
    ],
)
def test_active_exchange_follows_data_source(monkeypatch, source, expected):
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", source)
    monkeypatch.setattr(config, "DEFAULT_EXCHANGE", "dydx")
    assert config.active_exchange() == expected
