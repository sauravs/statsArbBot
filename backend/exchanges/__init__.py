"""Exchange adapters and the exchange registry.

dYdX v4 is the integrated trading venue. Hyperliquid is being added on branch
`hyperliquid` — its read-only data client is wired in (Slice 1: scan/backtest on
HL data), but HL trading lands in Slice 4, so ``make_trade_client`` still rejects
it. Binance stays a registry stub. See ADR-0004 and docs/HYPERLIQUID_PLAN.md.
"""

from .registry import EXCHANGE_REGISTRY, ExchangeInfo, get_exchange, list_exchanges


def make_data_client(exchange: str | None = None):
    """
    Build a read-only price-data client for ``exchange``, or for the configured
    data source when it is not given.

    **Pass ``exchange`` whenever the caller owns a persisted venue** (a simulation
    session, a live session). ``SCAN_DATA_SOURCE`` is a *mutable process global* —
    the data-source endpoint changes it at runtime and it resets to its env default
    on every restart — so a long-lived session that priced off the global would
    select its pairs from one venue and its prices from another after any restart.
    Hyperliquid and dYdX share market names (BTC, XRP, SUI, LDO…), so that failure
    is not loud: those legs fetch *successfully* from the wrong exchange.

    Explicit dispatch on the resolved source (one of ``VALID_DATA_SOURCES``):
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

    # `fake` is a whole-process offline mode (demo markets, no network), so it wins
    # over a caller's venue: a session created against dydx must not start making
    # real network calls just because the process was flipped into demo.
    source = config.SCAN_DATA_SOURCE
    if source != "fake" and exchange is not None:
        source = exchange
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
        f"unknown data source {source!r}; valid: {config.VALID_DATA_SOURCES}"
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
