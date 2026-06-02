"""
Build the historical close-price matrix used by the cointegration scan.

Fetches candles for every eligible market concurrently (bounded by a semaphore
so the indexer is not hammered), aligns them on their shared timestamps, and
drops markets that are too short or leave gaps. Columns are market tickers; rows
are candle timestamps.

The builder is exchange-agnostic: it depends only on the small ``PriceSource``
protocol, so the live :class:`DydxDataClient` or a fake can be passed in.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Protocol

import pandas as pd

import config

logger = logging.getLogger(__name__)


class PriceSource(Protocol):
    """Minimal surface the price-matrix builder needs from an exchange client."""

    async def get_markets(self) -> dict[str, dict]: ...

    async def get_historical_closes(
        self, market: str, *, num_pages: int | None = ..., now=...
    ) -> list[dict]: ...


@dataclass(frozen=True)
class PriceMatrix:
    """A close-price DataFrame plus the time window it spans."""

    df: pd.DataFrame  # columns = tickers, index = ISO timestamps, values = close
    window_start: datetime
    window_end: datetime

    @property
    def num_markets(self) -> int:
        return self.df.shape[1]

    @property
    def num_rows(self) -> int:
        return self.df.shape[0]

    @property
    def is_empty(self) -> bool:
        return self.df.empty


def _parse_iso(ts: str) -> datetime:
    """Parse a dYdX ISO timestamp (``...Z``) to an aware UTC datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


async def build_price_matrix(
    client: PriceSource,
    *,
    markets: list[str] | None = None,
    num_pages: int | None = None,
    concurrency: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    now=None,
) -> PriceMatrix:
    """
    Construct the aligned close-price matrix.

    Args:
        client: an object exposing ``get_markets`` / ``get_historical_closes``.
        markets: explicit ticker list; if None, discovered via ``get_markets``.
        num_pages: candle-history pages per market (defaults to config).
        concurrency: max simultaneous candle fetches (defaults to config).
        progress_callback: invoked ``(done, total)`` after each market completes.
        now: anchor passed through for deterministic time windows in tests.

    Returns a :class:`PriceMatrix`; ``is_empty`` is True when no usable data.
    """
    if markets is None:
        markets = list((await client.get_markets()).keys())
    concurrency = concurrency or config.SCAN_FETCH_CONCURRENCY

    total = len(markets)
    done = 0
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(ticker: str) -> tuple[str, list[dict]]:
        nonlocal done
        async with sem:
            try:
                closes = await client.get_historical_closes(
                    ticker, num_pages=num_pages, now=now
                )
            except Exception as exc:  # one bad market must not abort the scan
                logger.warning("price fetch failed for %s: %s", ticker, exc)
                closes = []
            done += 1
            if progress_callback:
                progress_callback(done, total)
            return ticker, closes

    results = await asyncio.gather(*(fetch_one(t) for t in markets))

    price_data: dict[str, dict[str, float]] = {}
    for ticker, closes in results:
        if len(closes) < config.MIN_CANDLES_PER_MARKET:
            if closes:
                logger.info("Skipping %s: only %d candles", ticker, len(closes))
            continue
        price_data[ticker] = {c["datetime"]: c["close"] for c in closes}

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    if not price_data:
        logger.warning("No usable market price data.")
        return PriceMatrix(df=pd.DataFrame(), window_start=epoch, window_end=epoch)

    df = pd.DataFrame(price_data)
    # Drop any market that does not cover every shared timestamp (leaves no gaps).
    df.dropna(axis=1, how="any", inplace=True)
    df.sort_index(inplace=True)
    logger.info("Price matrix: %d rows × %d markets", df.shape[0], df.shape[1])

    if df.empty:
        return PriceMatrix(df=df, window_start=epoch, window_end=epoch)

    window_start = _parse_iso(str(df.index.min()))
    window_end = _parse_iso(str(df.index.max()))
    return PriceMatrix(df=df, window_start=window_start, window_end=window_end)
