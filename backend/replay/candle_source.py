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

import math
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


# Synthetic demo funding: peak hourly rate per market, and the period of the sign
# cycle. Real perps fund at roughly 0.001–0.01%/hr, spiking higher when stressed;
# the demo sits at the top of that band so a short demo hold still produces a
# funding figure that renders at cent precision.
_DEMO_FUNDING_PEAK = 0.0003  # 0.03% per hour
_DEMO_FUNDING_CYCLE_H = 24


class DemoCandleSource:
    """Deterministic offline candle source over the synthetic DEMO markets.

    The DEMO series are a fixed number of hourly bars anchored at
    ``exchanges.demo.DEMO_ANCHOR``; this maps them onto timestamps and returns the
    in-range slice, plus a deterministic synthetic funding curve per market.
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

    def _funding(self, market: str) -> list[dict]:
        """Deterministic synthetic hourly funding rates for one DEMO market.

        This used to return nothing, which made ``funding_pnl`` **structurally
        zero** on the whole demo stack — so every test that claimed to exercise
        funding was really asserting `x + 0`, and the blotter's funding column
        could never render a non-zero value offline.

        Two properties make the demo faithful enough to test against:

        * **Per-market rates.** A pair trade is long one leg and short the other,
          so identical rates would very nearly cancel. Each market gets its own
          amplitude and phase, derived from its name — so the pair nets a real
          funding figure.
        * **Both signs.** The rate follows a 24h sine, so a position pays funding
          in some windows and earns it in others, exercising the long-pays /
          short-receives branches of ``compute_funding``.

        Derived from the market name and bar index only — no RNG and no clock, so
        a demo backtest stays byte-identical across runs (the property the whole
        demo stack relies on).
        """
        closes = self._series.get(market, [])
        seed = sum(ord(ch) for ch in market)
        amplitude = _DEMO_FUNDING_PEAK * (1.0 + (seed % 5)) / 5.0
        phase = seed % _DEMO_FUNDING_CYCLE_H
        return [
            {
                "timestamp": self._anchor + timedelta(hours=i),
                "funding_rate": round(
                    amplitude
                    * math.sin(2 * math.pi * (i + phase) / _DEMO_FUNDING_CYCLE_H),
                    9,
                ),
            }
            for i in range(len(closes))
        ]

    async def get_candles(
        self, market: str, *, start: datetime, end: datetime
    ) -> list[dict]:
        return [c for c in self._candles(market) if start <= c["timestamp"] <= end]

    async def get_funding(
        self, market: str, *, start: datetime, end: datetime
    ) -> list[dict]:
        return [f for f in self._funding(market) if start <= f["timestamp"] <= end]

    async def available_markets(self) -> list[str]:
        return sorted(self._series.keys())


def make_candle_source(*, exchange: str | None = None) -> OhlcvCacheSource | DemoCandleSource:
    """Return the configured historical candle source (``SCAN_DATA_SOURCE`` switch)."""
    if config.SCAN_DATA_SOURCE == "fake":
        return DemoCandleSource()
    return OhlcvCacheSource(exchange=exchange or config.DEFAULT_EXCHANGE)


def demo_window() -> tuple[datetime, datetime]:
    """Default [start, end] window for a blank-date offline run.

    The synthetic history spans years (issue #96), but a blank-date FF / backtest
    run should stay quick, so this returns only the most-recent
    ``DEMO_DEFAULT_WINDOW_BARS`` of the series. Explicit date ranges still reach the
    full span via :class:`DemoCandleSource`.
    """
    from exchanges.demo import DEMO_ANCHOR, DEMO_BARS, DEMO_DEFAULT_WINDOW_BARS

    anchor = DEMO_ANCHOR.replace(tzinfo=timezone.utc) if DEMO_ANCHOR.tzinfo is None else DEMO_ANCHOR
    end = anchor + timedelta(hours=DEMO_BARS - 1)
    start = anchor + timedelta(hours=max(0, DEMO_BARS - DEMO_DEFAULT_WINDOW_BARS))
    return start, end
