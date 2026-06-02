"""
Trade-execution seam — the order/position interface the engine drives, and the
shape of an order result.

The engine, :class:`BotAgent`, and the entry/exit managers depend only on the
:class:`TradeClient` protocol — never on ``dydx-v4-client`` directly — so:

  * the live :class:`exchanges.dydx.trade_client.DydxTradeClient` (testnet for
    forward_test, mainnet for production) is one implementation, and
  * tests inject a ``FakeTradeClient`` that simulates fills and positions with no
    network or wallet (the Phase-5a gate is "integration tests w/ mocked dYdX").

This mirrors the read-only ``PriceSource`` protocol the market-data layer uses,
extending it to the side-effecting account/order operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class OrderResult:
    """Outcome of a single market-order placement."""

    market: str
    side: str        # "BUY" | "SELL"
    size: float      # filled/submitted size in units
    price: float     # fill/accept price used
    client_id: int | None = None
    reduce_only: bool = False

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "side": self.side,
            "size": self.size,
            "price": self.price,
            "client_id": self.client_id,
            "reduce_only": self.reduce_only,
        }


@dataclass(frozen=True)
class Position:
    """An open perpetual position as reported by the exchange."""

    market: str
    side: str   # "LONG" | "SHORT"
    size: float  # absolute size in units
    entry_price: float


@runtime_checkable
class TradeClient(Protocol):
    """Account/order operations against an exchange. Read-only queries return
    safe empties on failure; placement returns ``None`` on failure (never raises),
    so the engine can run its failsafe logic deterministically."""

    async def place_market_order(
        self, *, market: str, side: str, size: float, reduce_only: bool = False
    ) -> OrderResult | None:
        ...

    async def is_open_position(self, market: str) -> bool:
        ...

    async def get_open_positions(self) -> dict[str, Position]:
        ...

    async def get_free_collateral(self) -> float:
        ...

    async def get_account_equity(self) -> float:
        ...

    async def cancel_all_orders(self) -> None:
        ...

    async def aclose(self) -> None:
        ...
