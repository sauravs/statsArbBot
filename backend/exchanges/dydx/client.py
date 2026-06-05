"""
dYdX v4 read-only market-data client (Phase 2).

Talks to the indexer REST API directly with httpx — the dYdX SDK wrapper does not
expose the ``fromISO``/``toISO`` candle parameters needed for paginated history,
so we bypass it (the reference bot did the same). Order placement / signing is a
Phase-5 concern and lives elsewhere.

Design for testability:
  * the indexer base URL is injectable (``data_url``), so an httpx ``MockTransport``
    can stand in for the live indexer in tests;
  * methods are duck-typed against the ``PriceSource`` protocol the price-matrix
    builder depends on, so a plain fake object can replace this client entirely.

Use as an async context manager so the underlying connection pool is reused
across the many candle requests of a scan and closed cleanly:

    async with DydxDataClient() as client:
        markets = await client.get_markets()
"""

from __future__ import annotations

import asyncio
import logging
import random

import httpx

import config
from marketdata.time_windows import iso_time_windows

logger = logging.getLogger(__name__)


# Process-wide gate on concurrent indexer candle requests (issue #65). Every
# DydxDataClient instance (one per call site) draws from this single semaphore, so
# the scan, the pairs-price poll, record snapshots, the portfolio mark-to-market,
# and charts share one rate budget and never burst the indexer into Retry-After
# throttling. Created lazily and rebound if the running event loop changes (an
# asyncio.Semaphore binds to the loop it's first awaited on — without this a
# fresh test loop would hit "bound to a different event loop").
_indexer_sem: asyncio.Semaphore | None = None
_indexer_sem_loop: asyncio.AbstractEventLoop | None = None


def _indexer_semaphore() -> asyncio.Semaphore:
    global _indexer_sem, _indexer_sem_loop
    loop = asyncio.get_running_loop()
    if _indexer_sem is None or _indexer_sem_loop is not loop:
        _indexer_sem = asyncio.Semaphore(config.DYDX_INDEXER_MAX_CONCURRENCY)
        _indexer_sem_loop = loop
    return _indexer_sem


class DydxDataClient:
    """Read-only adapter for the dYdX v4 indexer REST API."""

    def __init__(
        self,
        *,
        data_url: str | None = None,
        resolution: str | None = None,
        candles_per_page: int | None = None,
        timeout: float = 20.0,
        max_retries: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.data_url = (data_url or config.DYDX_DATA_INDEXER).rstrip("/")
        self.resolution = resolution or config.CANDLE_RESOLUTION
        self.candles_per_page = candles_per_page or config.CANDLES_PER_PAGE
        self.timeout = timeout
        self.max_retries = max_retries
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout, transport=self._transport
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "DydxDataClient":
        self._http()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ── markets ──────────────────────────────────────────────────────────────

    @staticmethod
    def _is_stablecoin(ticker: str) -> bool:
        base = ticker.split("-")[0].upper()
        return any(kw in base for kw in config.STABLECOIN_KEYWORDS)

    async def get_markets(self) -> dict[str, dict]:
        """
        Fetch perpetual markets, keeping only those that are ACTIVE, non-stablecoin,
        and above the minimum 24h volume. Returns ``{ticker: market_data}``.
        """
        resp = await self._http().get(f"{self.data_url}/v4/perpetualMarkets")
        resp.raise_for_status()
        all_markets = resp.json().get("markets", {})

        filtered: dict[str, dict] = {}
        for ticker, data in all_markets.items():
            if data.get("status") != "ACTIVE":
                continue
            if self._is_stablecoin(ticker):
                continue
            try:
                volume = float(data.get("volume24H", 0))
            except (TypeError, ValueError):
                volume = 0.0
            if volume < config.MIN_LIQUIDITY_USD:
                continue
            filtered[ticker] = data

        logger.info("Markets after filter: %d / %d", len(filtered), len(all_markets))
        return filtered

    # ── candles ──────────────────────────────────────────────────────────────

    async def _get_candle_page(
        self, market: str, from_iso: str, to_iso: str
    ) -> list[dict]:
        """Fetch one candle page, retrying with backoff on 429 rate-limits.

        Held under the process-wide indexer gate so concurrent callers don't burst
        the indexer into throttling (issue #65). The gate intentionally wraps the
        whole retry loop — a request waiting out a 429 backoff keeps holding its
        slot, so when the indexer is already unhappy that pressure propagates to
        every caller (the whole process slows down) instead of the gate releasing
        a slot that would immediately fire another request into the throttle.
        """
        url = f"{self.data_url}/v4/candles/perpetualMarkets/{market}"
        params = {
            "resolution": self.resolution,
            "fromISO": from_iso,
            "toISO": to_iso,
            "limit": self.candles_per_page,
        }
        async with _indexer_semaphore():
            for attempt in range(self.max_retries):
                try:
                    resp = await self._http().get(url, params=params)
                    if resp.status_code == 429:
                        await self._backoff(market, attempt, resp)
                        continue
                    resp.raise_for_status()
                    return resp.json().get("candles", [])
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429 and attempt < self.max_retries - 1:
                        await self._backoff(market, attempt, exc.response)
                        continue
                    logger.warning("candle fetch failed for %s: %s", market, exc)
                    return []
                except httpx.HTTPError as exc:
                    logger.warning("candle fetch error for %s: %s", market, exc)
                    return []
        return []

    async def _backoff(
        self, market: str, attempt: int, resp: httpx.Response
    ) -> None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            wait = float(retry_after)
        else:
            wait = min((2**attempt) + random.uniform(0.5, 1.5), 30.0)
        logger.warning(
            "429 for %s — waiting %.1fs (attempt %d/%d)",
            market, wait, attempt + 1, self.max_retries,
        )
        await asyncio.sleep(wait)

    async def get_historical_closes(
        self,
        market: str,
        *,
        num_pages: int | None = None,
        now=None,
        concurrent: bool = False,
    ) -> list[dict]:
        """
        Fetch paginated historical close prices for one market.

        Returns a chronologically-sorted, de-duplicated list of
        ``{"datetime": str, "close": float}`` dicts (empty on total failure).

        ``concurrent`` fetches the (disjoint) page windows in parallel rather than
        sequentially — used by the pair-detail chart (issue #61) where a small
        page count makes the burst safe and the latency win large. The scan's bulk
        fetch keeps the sequential default so it doesn't multiply its indexer load.
        """
        pages = num_pages or config.NUM_HISTORICAL_PAGES
        windows = iso_time_windows(
            pages,
            resolution=self.resolution,
            candles_per_page=self.candles_per_page,
            now=now,
        )

        if concurrent and len(windows) > 1:
            pages_candles = await asyncio.gather(
                *(
                    self._get_candle_page(market, w["from_iso"], w["to_iso"])
                    for w in windows
                )
            )
        else:
            pages_candles = [
                await self._get_candle_page(market, w["from_iso"], w["to_iso"])
                for w in windows
            ]

        by_datetime: dict[str, float] = {}
        for candles in pages_candles:
            for c in candles:
                # Last write wins on duplicate timestamps; values are identical.
                by_datetime[c["startedAt"]] = float(c["close"])

        return [
            {"datetime": ts, "close": close}
            for ts, close in sorted(by_datetime.items())
        ]

    # ── account ──────────────────────────────────────────────────────────────

    async def get_free_collateral(
        self, address: str, subaccount: int = 0
    ) -> float:
        """Return free collateral (USD) for a subaccount, 0.0 on failure."""
        url = f"{self.data_url}/v4/addresses/{address}/subaccountNumber/{subaccount}"
        try:
            resp = await self._http().get(url)
            resp.raise_for_status()
            sub = resp.json().get("subaccount", {})
            return float(sub.get("freeCollateral", 0))
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            logger.warning("free collateral fetch failed: %s", exc)
            return 0.0
