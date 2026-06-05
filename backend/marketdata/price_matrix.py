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
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

import pandas as pd

import config

logger = logging.getLogger(__name__)


class PriceSource(Protocol):
    """Minimal surface the price-matrix builder needs from an exchange client."""

    async def get_markets(self) -> dict[str, dict]: ...

    async def get_historical_closes(
        self, market: str, *, num_pages: int | None = ..., now=..., concurrent: bool = ...
    ) -> list[dict]: ...


@dataclass(frozen=True)
class PriceMatrix:
    """A close-price DataFrame plus the time window it spans."""

    df: pd.DataFrame  # columns = tickers, index = ISO timestamps, values = close
    window_start: datetime
    window_end: datetime
    # Markets that were eligible but did NOT make it into the matrix, mapped to a
    # reason: "fetch_failed" (issue #7 — indexer 429/error exhaustion), "no_data",
    # "too_short", or "misaligned" (issue #6 — dropped by the union-timestamp join
    # because its history didn't cover every shared bar). Surfaced so a scan that
    # silently loses most of the universe is visible rather than reported as a
    # clean success.
    dropped: dict[str, str] = field(default_factory=dict)

    @property
    def num_markets(self) -> int:
        return self.df.shape[1]

    @property
    def num_rows(self) -> int:
        return self.df.shape[0]

    @property
    def num_dropped(self) -> int:
        return len(self.dropped)

    @property
    def dropped_by_reason(self) -> dict[str, int]:
        """Excluded-market counts grouped by reason (for logging / status)."""
        return dict(Counter(self.dropped.values()))

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
    should_stop: Callable[[], bool] | None = None,
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
        should_stop: polled before each market's fetch; when it returns True the
            remaining fetches are skipped so an operator stop (#59) ends the fetch
            phase promptly without leaving orphaned requests in flight.
        now: anchor passed through for deterministic time windows in tests.

    Returns a :class:`PriceMatrix`; ``is_empty`` is True when no usable data.
    """
    if markets is None:
        markets = list((await client.get_markets()).keys())
    concurrency = concurrency or config.SCAN_FETCH_CONCURRENCY

    total = len(markets)
    done = 0
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(ticker: str) -> tuple[str, list[dict], bool]:
        nonlocal done
        async with sem:
            # Cooperative stop (#59): once requested, skip the remaining fetches so
            # the phase winds down quickly (no orphaned in-flight requests). The
            # partial matrix is discarded by the caller, which stops on the flag.
            if should_stop is not None and should_stop():
                return ticker, [], False
            failed = False
            try:
                closes = await client.get_historical_closes(
                    ticker, num_pages=num_pages, now=now
                )
            except Exception as exc:  # one bad market must not abort the scan
                logger.warning("price fetch failed for %s: %s", ticker, exc)
                closes = []
                failed = True
            done += 1
            if progress_callback:
                progress_callback(done, total)
            return ticker, closes, failed

    results = await asyncio.gather(*(fetch_one(t) for t in markets))

    price_data: dict[str, dict[str, float]] = {}
    dropped: dict[str, str] = {}
    for ticker, closes, failed in results:
        if failed:
            dropped[ticker] = "fetch_failed"  # issue #7: 429/error exhaustion
            continue
        if not closes:
            dropped[ticker] = "no_data"
            continue
        if len(closes) < config.MIN_CANDLES_PER_MARKET:
            logger.info("Skipping %s: only %d candles", ticker, len(closes))
            dropped[ticker] = "too_short"
            continue
        price_data[ticker] = {c["datetime"]: c["close"] for c in closes}

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    if not price_data:
        logger.warning("No usable market price data (excluded %d: %s).",
                       len(dropped), dict(Counter(dropped.values())))
        return PriceMatrix(
            df=pd.DataFrame(), window_start=epoch, window_end=epoch, dropped=dropped
        )

    df = pd.DataFrame(price_data)
    # Drop any market that does not cover every shared timestamp (cointegration
    # needs aligned series). Unlike before, the dropped columns are recorded as
    # "misaligned" (issue #6) rather than silently discarded.
    eligible = set(df.columns)
    df.dropna(axis=1, how="any", inplace=True)
    for ticker in eligible - set(df.columns):
        dropped[ticker] = "misaligned"
    df.sort_index(inplace=True)

    if dropped:
        logger.info(
            "Price matrix: %d rows × %d markets (excluded %d: %s)",
            df.shape[0], df.shape[1], len(dropped), dict(Counter(dropped.values())),
        )
    else:
        logger.info("Price matrix: %d rows × %d markets", df.shape[0], df.shape[1])

    if df.empty:
        return PriceMatrix(
            df=df, window_start=epoch, window_end=epoch, dropped=dropped
        )

    window_start = _parse_iso(str(df.index.min()))
    window_end = _parse_iso(str(df.index.max()))
    return PriceMatrix(
        df=df, window_start=window_start, window_end=window_end, dropped=dropped
    )
