"""Exchange adapters and the exchange registry.

dYdX v4 is the only integrated exchange (Phase 2); Binance and Hyperliquid are
declared in the registry as not-yet-integrated so the UI can surface them as
disabled options. See ADR-0004.
"""

from .registry import EXCHANGE_REGISTRY, ExchangeInfo, get_exchange, list_exchanges


def make_data_client():
    """
    Build a read-only price-data client for the configured data source.

    ``SCAN_DATA_SOURCE=fake`` → the deterministic, network-free
    :class:`exchanges.demo.DemoDataClient` (offline dev, demos, E2E); otherwise
    the live :class:`exchanges.dydx.client.DydxDataClient`. The returned object
    satisfies the ``PriceSource`` protocol and is an async context manager.

    One place for the switch the scan orchestrator and the pair-detail series
    endpoint both use, so they always read from the same source. Imports are
    deferred so importing the registry never pulls in httpx/the demo module.
    """
    import config

    if config.SCAN_DATA_SOURCE == "fake":
        from exchanges.demo import DemoDataClient

        return DemoDataClient()
    from exchanges.dydx.client import DydxDataClient

    return DydxDataClient()


__all__ = [
    "EXCHANGE_REGISTRY",
    "ExchangeInfo",
    "get_exchange",
    "list_exchanges",
    "make_data_client",
]
