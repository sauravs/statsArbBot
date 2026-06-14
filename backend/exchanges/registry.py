"""
Exchange registry — single source of truth for supported exchanges (ADR-0004).

Adding an exchange:
  1. Add an entry to EXCHANGE_REGISTRY below.
  2. Create exchanges/<name>/ with a data client implementing the same surface
     as exchanges.dydx.client.DydxDataClient.
  3. Flip ``integrated=True`` when the adapter is ready.

The UI reads GET /exchange/list, built from this registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExchangeInfo:
    id: str
    label: str
    integrated: bool
    has_testnet: bool
    live_modes: list[str] = field(default_factory=list)
    integration_note: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "integrated": self.integrated,
            "has_testnet": self.has_testnet,
            "live_modes": self.live_modes,
            "integration_note": self.integration_note,
        }


EXCHANGE_REGISTRY: dict[str, ExchangeInfo] = {
    "dydx": ExchangeInfo(
        id="dydx",
        label="dYdX",
        integrated=True,
        has_testnet=True,
        live_modes=["forward_test", "simulation", "production"],
    ),
    "binance": ExchangeInfo(
        id="binance",
        label="Binance",
        integrated=False,
        has_testnet=False,
        live_modes=[],
        integration_note="Binance Futures — deferred (out of scope this rewrite)",
    ),
    "hyperliquid": ExchangeInfo(
        id="hyperliquid",
        label="Hyperliquid",
        # Data integrated (branch `hyperliquid`, Slices 1–2): scan, historical
        # fetch, backtest, sim and fast-forward all run on live HL `/info` data.
        # `live_modes` is empty until the HL trade client lands (Slice 4), so live
        # trading is cleanly rejected (see routers/live.py) — `integrated` here
        # means "data integrated", not "tradeable".
        integrated=True,
        has_testnet=True,
        live_modes=[],
        integration_note="Data integrated (scan/backtest/sim/ff); trading lands in Slice 4",
    ),
}


def get_exchange(exchange_id: str) -> ExchangeInfo:
    """Return ExchangeInfo by id, raising ValueError if unknown."""
    info = EXCHANGE_REGISTRY.get(exchange_id)
    if info is None:
        known = ", ".join(EXCHANGE_REGISTRY)
        raise ValueError(f"Unknown exchange '{exchange_id}'. Known: {known}")
    return info


def list_exchanges() -> list[dict]:
    """Return all exchanges as serialisable dicts (UI consumes this)."""
    return [info.to_dict() for info in EXCHANGE_REGISTRY.values()]
