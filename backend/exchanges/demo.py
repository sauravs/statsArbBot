"""
Deterministic in-process market-data source for offline development, demos, and
end-to-end tests.

Activated by ``SCAN_DATA_SOURCE=fake`` (see config). It implements the same
``PriceSource`` surface as :class:`DydxDataClient` (``get_markets`` /
``get_historical_closes`` / ``aclose``) but synthesises a fixed set of markets —
several genuinely cointegrated pairs plus some independent random walks — so a
scan completes in milliseconds with a stable, network-free result.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)
_N = 400  # candles per market


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cointegrated_pair(seed: int, *, beta: float, alpha: float) -> tuple[list[float], list[float]]:
    rng = np.random.default_rng(seed)
    s2 = 100 + np.cumsum(rng.normal(0, 1, _N))
    eps = np.zeros(_N)
    for t in range(1, _N):
        eps[t] = 0.5 * eps[t - 1] + rng.normal(0, 0.5)
    s1 = beta * s2 + alpha + eps
    return s1.tolist(), s2.tolist()


def _random_walk(seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    return (50 + np.cumsum(rng.normal(0, 1, _N))).tolist()


def _build_series() -> dict[str, list[float]]:
    series: dict[str, list[float]] = {}
    # Two cointegrated pairs (should pass the filter).
    p1a, p1b = _cointegrated_pair(11, beta=2.0, alpha=5.0)
    p2a, p2b = _cointegrated_pair(23, beta=1.4, alpha=-3.0)
    series["DEMO1-USD"] = p1a
    series["DEMO2-USD"] = p1b
    series["DEMO3-USD"] = p2a
    series["DEMO4-USD"] = p2b
    # Independent walks (should not be cointegrated with anything).
    series["NOISE1-USD"] = _random_walk(101)
    series["NOISE2-USD"] = _random_walk(202)
    return series


class DemoDataClient:
    """A network-free PriceSource with deterministic synthetic markets."""

    def __init__(self) -> None:
        self._series = _build_series()

    async def get_markets(self) -> dict[str, dict]:
        return {m: {"status": "ACTIVE"} for m in self._series}

    async def get_historical_closes(
        self, market: str, *, num_pages=None, now=None
    ) -> list[dict]:
        closes = self._series.get(market, [])
        return [
            {"datetime": _iso(_ANCHOR + timedelta(hours=i)), "close": float(c)}
            for i, c in enumerate(closes)
        ]

    async def aclose(self) -> None:  # parity with DydxDataClient
        return None


# ── Offline trade client (Phase 5b) ──────────────────────────────────────────
# The live engine builds a *fresh* trade client per pass and closes it in a
# ``finally`` (engine.py), so per-instance state would not survive between an
# entry-scan pass and a later abort/exit pass. A real exchange holds positions
# and collateral between calls; this module-level store mirrors that, giving the
# offline live-trading UI / E2E coherent state across passes. It persists for the
# life of the process and starts empty (deterministic) — see ``reset_demo_account``.
_DEMO_FILL_PRICE = 100.0
_DEMO_START_COLLATERAL = 10_000.0
_demo_positions: dict[str, object] = {}
_demo_account: dict[str, float] = {
    "free_collateral": _DEMO_START_COLLATERAL,
    "equity": _DEMO_START_COLLATERAL,
}


def reset_demo_account() -> None:
    """Clear the in-memory demo positions/collateral (used by tests)."""
    _demo_positions.clear()
    _demo_account["free_collateral"] = _DEMO_START_COLLATERAL
    _demo_account["equity"] = _DEMO_START_COLLATERAL


class DemoTradeClient:
    """A network-free, walletless ``TradeClient`` for offline live trading.

    Activated by ``SCAN_DATA_SOURCE=fake`` (the project's single "offline mode"
    switch). Simulates immediate fills, tracks positions in the process-level
    store above, and serves a fixed collateral/equity — so the Phase-5b live UI
    (BotControls / AccountCard / OpenTradesTable / abort) drives the *real*
    engine path deterministically, with no SDK, wallet, or network.
    """

    async def place_market_order(
        self, *, market: str, side: str, size: float, reduce_only: bool = False
    ):
        from trading.broker import OrderResult, Position

        price = _DEMO_FILL_PRICE
        if reduce_only:
            _demo_positions.pop(market, None)
        else:
            _demo_positions[market] = Position(
                market=market,
                side="LONG" if side == "BUY" else "SHORT",
                size=size,
                entry_price=price,
            )
        return OrderResult(
            market=market, side=side, size=size, price=price,
            client_id=1, reduce_only=reduce_only,
        )

    async def is_open_position(self, market: str) -> bool:
        return market in _demo_positions

    async def get_open_positions(self) -> dict:
        return dict(_demo_positions)

    async def get_free_collateral(self) -> float:
        return _demo_account["free_collateral"]

    async def get_account_equity(self) -> float:
        return _demo_account["equity"]

    async def cancel_all_orders(self) -> None:
        return None

    async def aclose(self) -> None:
        return None
