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
    integrated: bool  # data integrated: scan / historical fetch / backtest / manual
    has_testnet: bool
    live_modes: list[str] = field(default_factory=list)  # live/automated trading modes
    # Whether the Simulation + Fast-Forward (paper-trading) sections are available.
    # Separate from `integrated` (data) so a venue can have backtest/manual without
    # its sim/replay paths being validated/enabled. Empty live_modes ≠ no sim.
    sim_enabled: bool = False
    integration_note: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "integrated": self.integrated,
            "has_testnet": self.has_testnet,
            "live_modes": self.live_modes,
            "sim_enabled": self.sim_enabled,
            "integration_note": self.integration_note,
        }


EXCHANGE_REGISTRY: dict[str, ExchangeInfo] = {
    "dydx": ExchangeInfo(
        id="dydx",
        label="dYdX",
        integrated=True,
        has_testnet=True,
        live_modes=["forward_test", "simulation", "production"],
        sim_enabled=True,
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
        # HL delivers **Manual Trading + Backtest + paper trading** (data is
        # integrated: scan / historical fetch / backtest run on live HL `/info`
        # data). `live_modes` stays intentionally EMPTY — LiveBot and any
        # testnet/live AUTOMATED trading for HL are still PENDING, so live trading
        # is cleanly rejected (routers/live.py). The HL trade client (Slice 4a) is
        # built + tested but PARKED behind that gate. `integrated` here means
        # "data integrated", not "tradeable".
        integrated=True,
        has_testnet=True,
        live_modes=[],
        # Phase 5: Simulation + Fast-Forward enabled for HL. This flag was
        # protecting a real defect, not merely an unvalidated path — both paper
        # paths used to take their price client from the mutable SCAN_DATA_SOURCE
        # global rather than from the session's own venue, so after any api restart
        # an HL session would have priced HL pairs against the dYdX indexer (silently,
        # for the market names the two venues share). Both now resolve their client
        # and their per-market costs from the persisted `exchange`, so the flag is
        # safe to open. Virtual money only — this grants no order-placing capability.
        sim_enabled=True,
        integration_note="Data + Manual Trading + Backtest + paper trading (Simulation / Fast-Forward); LiveBot + automated live trading pending",
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
