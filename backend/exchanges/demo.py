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
