"""
Historical candle/funding sources for the fast-forward replay (PRD F7.1).

Two implementations behind one small surface, selected by ``SCAN_DATA_SOURCE``
exactly like :func:`exchanges.make_data_client`:

  * :class:`OhlcvCacheSource` — the production path: reads the cleaned bars and
    funding rates seeded into ``OhlcvCache`` / ``FundingRateCache`` by Phase 2.5.
  * :class:`DemoCandleSource` — the offline path (``SCAN_DATA_SOURCE=fake``):
    replays the same deterministic DEMO markets the fake scan/realtime feed use,
    so a fake-mode scan's β/α line up with the replayed prices for a network-free,
    deterministic E2E.

A "candle" here is the minimal ``{"timestamp": datetime, "close": float}`` the
replay needs (the cost model marks against closes); funding is
``{"timestamp": datetime, "funding_rate": float}``. All timestamps are tz-aware
UTC datetimes so the cursor arithmetic and the engine's position-age clock agree.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config


class OhlcvCacheSource:
    """Reads historical candles/funding from the Phase-2.5 cache (Postgres)."""

    def __init__(self, *, exchange: str, resolution: str | None = None) -> None:
        self.exchange = exchange
        self.resolution = resolution or config.CANDLE_RESOLUTION

    async def get_candles(
        self, market: str, *, start: datetime, end: datetime
    ) -> list[dict]:
        from ingest.cache_repository import get_ohlcv_cache_repository

        return await get_ohlcv_cache_repository().get_candles(
            market,
            exchange=self.exchange,
            resolution=self.resolution,
            start=start,
            end=end,
        )

    async def get_funding(
        self, market: str, *, start: datetime, end: datetime
    ) -> list[dict]:
        from ingest.cache_repository import get_ohlcv_cache_repository

        return await get_ohlcv_cache_repository().get_funding(
            market, exchange=self.exchange, start=start, end=end
        )

    async def available_markets(self) -> list[str]:
        from ingest.cache_repository import get_ohlcv_cache_repository

        return await get_ohlcv_cache_repository().get_markets(
            exchange=self.exchange, resolution=self.resolution
        )


class DemoCandleSource:
    """Deterministic offline candle source over the synthetic DEMO markets.

    The DEMO series are a fixed number of hourly bars anchored at
    ``exchanges.demo.DEMO_ANCHOR``; this maps them onto timestamps and returns the
    in-range slice. No funding data (the demo run exercises slippage/fees only).
    """

    def __init__(self) -> None:
        from exchanges.demo import DEMO_ANCHOR, demo_series

        self._anchor = DEMO_ANCHOR
        self._series = demo_series()

    def _candles(self, market: str) -> list[dict]:
        closes = self._series.get(market, [])
        return [
            {
                "timestamp": self._anchor + timedelta(hours=i),
                "close": float(c),
            }
            for i, c in enumerate(closes)
        ]

    async def get_candles(
        self, market: str, *, start: datetime, end: datetime
    ) -> list[dict]:
        return [c for c in self._candles(market) if start <= c["timestamp"] <= end]

    async def get_funding(
        self, market: str, *, start: datetime, end: datetime
    ) -> list[dict]:
        return []

    async def available_markets(self) -> list[str]:
        return sorted(self._series.keys())


def make_candle_source(*, exchange: str | None = None) -> OhlcvCacheSource | DemoCandleSource:
    """Return the configured historical candle source (``SCAN_DATA_SOURCE`` switch)."""
    if config.SCAN_DATA_SOURCE == "fake":
        return DemoCandleSource()
    return OhlcvCacheSource(exchange=exchange or config.DEFAULT_EXCHANGE)


def demo_window() -> tuple[datetime, datetime]:
    """The full [start, end] span of the demo synthetic history (offline default)."""
    from exchanges.demo import DEMO_ANCHOR, DEMO_BARS

    start = DEMO_ANCHOR.replace(tzinfo=timezone.utc) if DEMO_ANCHOR.tzinfo is None else DEMO_ANCHOR
    return start, start + timedelta(hours=DEMO_BARS - 1)
