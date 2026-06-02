"""Exchange adapters and the exchange registry.

dYdX v4 is the only integrated exchange (Phase 2); Binance and Hyperliquid are
declared in the registry as not-yet-integrated so the UI can surface them as
disabled options. See ADR-0004.
"""

from .registry import EXCHANGE_REGISTRY, ExchangeInfo, get_exchange, list_exchanges

__all__ = ["EXCHANGE_REGISTRY", "ExchangeInfo", "get_exchange", "list_exchanges"]
