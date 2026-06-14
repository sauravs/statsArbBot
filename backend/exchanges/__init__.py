"""Exchange adapters and the exchange registry.

dYdX v4 is the integrated trading venue. Hyperliquid is being added on branch
`hyperliquid` — its read-only data client is wired in (Slice 1: scan/backtest on
HL data), but HL trading lands in Slice 4, so ``make_trade_client`` still rejects
it. Binance stays a registry stub. See ADR-0004 and docs/HYPERLIQUID_PLAN.md.
"""

from .registry import EXCHANGE_REGISTRY, ExchangeInfo, get_exchange, list_exchanges


def make_data_client():
    """
    Build a read-only price-data client for the configured data source.

    Explicit dispatch on ``SCAN_DATA_SOURCE`` (one of ``VALID_DATA_SOURCES``):
    ``fake`` → deterministic, network-free :class:`exchanges.demo.DemoDataClient`;
    ``dydx`` → live :class:`exchanges.dydx.client.DydxDataClient`;
    ``hyperliquid`` → live :class:`exchanges.hyperliquid.client.HyperliquidDataClient`.
    The returned object satisfies the ``PriceSource`` protocol and is an async
    context manager. An unknown source raises rather than silently defaulting.

    One place for the switch the scan orchestrator and the pair-detail series
    endpoint both use, so they always read from the same source. Imports are
    deferred so importing the registry never pulls in httpx/the demo module.
    """
    import config

    source = config.SCAN_DATA_SOURCE
    if source == "fake":
        from exchanges.demo import DemoDataClient

        return DemoDataClient()
    if source == "hyperliquid":
        from exchanges.hyperliquid.client import HyperliquidDataClient

        return HyperliquidDataClient()
    if source == "dydx":
        from exchanges.dydx.client import DydxDataClient

        return DydxDataClient()
    raise ValueError(
        f"unknown SCAN_DATA_SOURCE {source!r}; valid: {config.VALID_DATA_SOURCES}"
    )


async def make_trade_client():
    """
    Connect and return a live trade-execution client (Phase 5a/5b).

    ``SCAN_DATA_SOURCE=fake`` → the deterministic, network-free
    :class:`exchanges.demo.DemoTradeClient` (offline dev, demos, the Phase-5b live
    UI E2E); otherwise the live :class:`exchanges.dydx.trade_client.DydxTradeClient`
    (testnet for forward_test, mainnet for production per ``ENVIRONMENT``).

    Reuses the one "offline mode" switch the data client uses so a single env var
    flips the whole stack off the network. Imports are deferred so importing the
    registry never pulls in ``dydx-v4-client`` / ``hyperliquid-python-sdk``. Returns
    an object satisfying the ``trading.broker.TradeClient`` protocol.

    ``hyperliquid`` connects via the HL trade client (Slice 4, testnet for
    forward_test / mainnet for production per ``ENVIRONMENT``); it raises cleanly if
    no wallet key is configured rather than silently routing orders anywhere else.
    """
    import config

    source = config.SCAN_DATA_SOURCE
    if source == "fake":
        from exchanges.demo import DemoTradeClient

        return DemoTradeClient()
    if source == "hyperliquid":
        from exchanges.hyperliquid.trade_client import HyperliquidTradeClient

        return await HyperliquidTradeClient.connect()
    if source == "dydx":
        from exchanges.dydx.trade_client import DydxTradeClient

        return await DydxTradeClient.connect()
    raise ValueError(
        f"unknown SCAN_DATA_SOURCE {source!r}; valid: {config.VALID_DATA_SOURCES}"
    )


__all__ = [
    "EXCHANGE_REGISTRY",
    "ExchangeInfo",
    "get_exchange",
    "list_exchanges",
    "make_data_client",
    "make_trade_client",
]
