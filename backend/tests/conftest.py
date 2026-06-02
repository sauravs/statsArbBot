"""Shared test fixtures and synthetic market-data helpers for Phase 2."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

# Anchor for deterministic synthetic candle timestamps.
_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_cointegrated_series(n: int = 400, *, seed: int = 7) -> tuple[list[float], list[float]]:
    """
    Build a strongly cointegrated pair: S2 is a random walk; S1 = 2·S2 + α + ε
    where ε is a fast mean-reverting AR(1) (phi=0.5 → ~1-period half-life). The
    spread S1 − 2·S2 is stationary, so Engle-Granger should accept it with a small
    p-value and a half-life well inside the 72h cap.
    """
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 1, n)
    s2 = 100 + np.cumsum(steps)  # random walk
    eps = np.zeros(n)
    for t in range(1, n):
        eps[t] = 0.5 * eps[t - 1] + rng.normal(0, 0.5)
    s1 = 2.0 * s2 + 5.0 + eps
    return s1.tolist(), s2.tolist()


def make_independent_walk(n: int = 400, *, seed: int = 99) -> list[float]:
    """An independent random walk — not cointegrated with the pair above."""
    rng = np.random.default_rng(seed)
    return (50 + np.cumsum(rng.normal(0, 1, n))).tolist()


def make_flat_series(n: int = 400, *, value: float = 100.0) -> list[float]:
    """A constant series — degenerate input that makes coint()/OLS misbehave."""
    return [value] * n


def closes_to_candles(closes: list[float]) -> list[dict]:
    """Convert a close list into the {datetime, close} shape the client returns."""
    return [
        {"datetime": _iso(_ANCHOR + timedelta(hours=i)), "close": float(c)}
        for i, c in enumerate(closes)
    ]


class FakeDydxClient:
    """In-memory PriceSource: serves preset close series, no network."""

    def __init__(self, series: dict[str, list[float]]) -> None:
        self._series = series
        self.closed = False

    async def get_markets(self) -> dict[str, dict]:
        return {m: {"status": "ACTIVE"} for m in self._series}

    async def get_historical_closes(
        self, market: str, *, num_pages=None, now=None
    ) -> list[dict]:
        return closes_to_candles(self._series.get(market, []))

    async def aclose(self) -> None:
        self.closed = True


class FakeScanRepository:
    """In-memory stand-in for PrismaScanRepository (no DB / generated client)."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], list[dict]] = {}

    async def replace_scan_results(self, rows, *, exchange, mode) -> int:
        # Serialise datetimes the way the Prisma version's reader would emit them.
        serialised = []
        for r in rows:
            row = dict(r)
            for k in ("scanned_at", "window_start", "window_end"):
                v = row.get(k)
                if isinstance(v, datetime):
                    row[k] = v.isoformat()
            serialised.append(row)
        self.store[(exchange, mode)] = serialised
        return len(serialised)

    async def get_latest_pairs(self, *, exchange, mode) -> list[dict]:
        rows = self.store.get((exchange, mode), [])
        # Mirror PrismaScanRepository: zero_crossings desc, p_value asc tie-break.
        return sorted(rows, key=lambda r: (-r["zero_crossings"], r["p_value"]))
