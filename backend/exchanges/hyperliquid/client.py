"""
Hyperliquid read-only market-data client (branch `hyperliquid`, Phase 1).

The dYdX counterpart talks to the indexer REST API directly with httpx; this does
the same against Hyperliquid's public ``/info`` endpoint (a single POST endpoint
whose ``type`` selects the query — no API key/KYC for read-only data). Order
placement / EIP-712 signing is a later phase and lives elsewhere.

**Normalisation is the contract.** The ingest orchestrator (``ingest.historical_fetch``)
reads dYdX-shaped keys straight off the raw dicts a data client returns —
``c["startedAt"] / open / high / low / close / baseTokenVolume`` for candles and
``f["effectiveAt"] / rate`` for funding. So this client maps Hyperliquid's native
shapes (``{t, o, h, l, c, v}`` candles in ms; ``{time, fundingRate}`` funding) onto
those same keys, letting the venue-agnostic ingest path stay unchanged. Methods are
duck-typed against the ``PriceSource`` protocol the price-matrix builder depends on.

Two Hyperliquid-specific facts shape the code:
  * candle queries are capped at ~5,000 bars per request regardless of range, so
    ``fetch_ohlcv_range`` walks the window in <=5,000-bar chunks (issue: the live
    API cannot deep-backfill — bulk history comes from the S3 archive separately);
  * ``fundingHistory`` truncates long ranges, so ``fetch_funding_range`` chunks by
    ~7 days.

Use as an async context manager so the connection pool is reused across the many
candle requests of a scan and closed cleanly:

    async with HyperliquidDataClient() as client:
        markets = await client.get_markets()
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import httpx

import config

logger = logging.getLogger(__name__)


# Canonical (dYdX-style) resolution → Hyperliquid interval string. The bot's
# CANDLE_RESOLUTION is expressed in dYdX's vocabulary ("1HOUR"); Hyperliquid wants
# "1h". Kept as an explicit table so an unsupported resolution fails loudly rather
# than silently fetching the wrong granularity.
_RESOLUTION_TO_INTERVAL: dict[str, str] = {
    "1MIN": "1m",
    "5MINS": "5m",
    "15MINS": "15m",
    "30MINS": "30m",
    "1HOUR": "1h",
    "4HOURS": "4h",
    "1DAY": "1d",
}
_RESOLUTION_SECONDS: dict[str, int] = {
    "1MIN": 60,
    "5MINS": 300,
    "15MINS": 900,
    "30MINS": 1800,
    "1HOUR": 3600,
    "4HOURS": 14400,
    "1DAY": 86400,
}

# Hyperliquid caps a candle snapshot at ~5,000 bars per request irrespective of
# the requested [startTime, endTime] (see module docstring / HYPERLIQUID_RESEARCH).
_MAX_CANDLES_PER_REQUEST = 5000
# fundingHistory truncates long ranges; walk it in ~7-day windows.
_FUNDING_WINDOW = timedelta(days=7)


def _to_iso(ms: int) -> str:
    """Hyperliquid epoch-millis → indexer-style ISO ``YYYY-MM-DDTHH:MM:SSZ``.

    Matches the dYdX ``startedAt`` / ``effectiveAt`` string shape so the shared
    ingest path can ``pd.to_datetime(..., utc=True)`` it without special-casing.
    """
    return (
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


# Process-wide gate on concurrent /info requests (mirrors the dYdX #65 gate): every
# HyperliquidDataClient instance draws from one semaphore so the scan, charts, and
# mark-to-market share a single rate budget. Lazily created and rebound if the
# running event loop changes (a Semaphore binds to the loop it's first awaited on).
_info_sem: asyncio.Semaphore | None = None
_info_sem_loop: asyncio.AbstractEventLoop | None = None


def _info_semaphore() -> asyncio.Semaphore:
    global _info_sem, _info_sem_loop
    loop = asyncio.get_running_loop()
    if _info_sem is None or _info_sem_loop is not loop:
        _info_sem = asyncio.Semaphore(config.HYPERLIQUID_INFO_MAX_CONCURRENCY)
        _info_sem_loop = loop
    return _info_sem


class HyperliquidDataClient:
    """Read-only adapter for the Hyperliquid ``/info`` API."""

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
        self.data_url = (data_url or config.HYPERLIQUID_DATA_API_URL).rstrip("/")
        self.resolution = resolution or config.CANDLE_RESOLUTION
        if self.resolution not in _RESOLUTION_TO_INTERVAL:
            raise ValueError(
                f"unsupported resolution {self.resolution!r} for Hyperliquid; "
                f"known: {', '.join(_RESOLUTION_TO_INTERVAL)}"
            )
        self.candles_per_page = candles_per_page or config.CANDLES_PER_PAGE
        self.timeout = timeout
        self.max_retries = max_retries
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    @property
    def _interval(self) -> str:
        return _RESOLUTION_TO_INTERVAL[self.resolution]

    @property
    def _resolution_seconds(self) -> int:
        return _RESOLUTION_SECONDS[self.resolution]

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

    async def __aenter__(self) -> "HyperliquidDataClient":
        self._http()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ── /info transport ──────────────────────────────────────────────────────

    async def _info(self, body: dict):
        """POST one ``/info`` query, retrying with backoff on 429.

        Held under the process-wide gate so concurrent callers don't burst the API
        into throttling. The gate wraps the whole retry loop — a request waiting out
        a 429 keeps its slot so the back-pressure propagates to every caller rather
        than releasing a slot that immediately fires into the throttle. Returns the
        decoded JSON, or ``None`` on a non-recoverable error (caller decides).
        """
        url = f"{self.data_url}/info"
        async with _info_semaphore():
            for attempt in range(self.max_retries):
                try:
                    resp = await self._http().post(url, json=body)
                    if resp.status_code == 429:
                        await self._backoff(body.get("type", "?"), attempt, resp)
                        continue
                    resp.raise_for_status()
                    return resp.json()
                except httpx.HTTPStatusError as exc:
                    if (
                        exc.response.status_code == 429
                        and attempt < self.max_retries - 1
                    ):
                        await self._backoff(body.get("type", "?"), attempt, exc.response)
                        continue
                    logger.warning("info %s failed: %s", body.get("type"), exc)
                    return None
                except httpx.HTTPError as exc:
                    logger.warning("info %s error: %s", body.get("type"), exc)
                    return None
        return None

    async def _backoff(self, what: str, attempt: int, resp: httpx.Response) -> None:
        retry_after = resp.headers.get("Retry-After")
        wait = (
            float(retry_after)
            if retry_after
            else min((2**attempt) + random.uniform(0.5, 1.5), 30.0)
        )
        logger.warning(
            "429 on %s — waiting %.1fs (attempt %d/%d)",
            what, wait, attempt + 1, self.max_retries,
        )
        await asyncio.sleep(wait)

    # ── markets ──────────────────────────────────────────────────────────────

    @staticmethod
    def _is_stablecoin(coin: str) -> bool:
        base = coin.upper()
        return any(kw in base for kw in config.STABLECOIN_KEYWORDS)

    async def get_markets(self) -> dict[str, dict]:
        """
        Fetch perpetual markets, keeping non-delisted, non-stablecoin coins above
        the minimum 24h notional volume. Returns ``{coin: market_data}`` — the coin
        name (e.g. ``"BTC"``) is the market identifier used everywhere downstream
        (Hyperliquid perps are keyed by coin, not a ``BTC-USD`` ticker).

        ``metaAndAssetCtxs`` returns ``[meta, assetCtxs]`` where ``assetCtxs`` is
        positionally aligned with ``meta["universe"]``; ``dayNtlVlm`` is the 24h USD
        notional we filter on.
        """
        data = await self._info({"type": "metaAndAssetCtxs"})
        if not data or len(data) < 2:
            logger.warning("metaAndAssetCtxs returned no data")
            return {}
        meta, ctxs = data[0], data[1]
        universe = meta.get("universe", [])

        filtered: dict[str, dict] = {}
        for asset, ctx in zip(universe, ctxs):
            coin = asset.get("name")
            if not coin or asset.get("isDelisted"):
                continue
            if self._is_stablecoin(coin):
                continue
            try:
                volume = float(ctx.get("dayNtlVlm", 0))
            except (TypeError, ValueError):
                volume = 0.0
            if volume < config.MIN_LIQUIDITY_USD:
                continue
            filtered[coin] = {
                "name": coin,
                "volume24H": volume,
                "markPx": ctx.get("markPx"),
                "funding": ctx.get("funding"),
                "openInterest": ctx.get("openInterest"),
                "szDecimals": asset.get("szDecimals"),
                "maxLeverage": asset.get("maxLeverage"),
            }

        logger.info(
            "HL markets after filter: %d / %d", len(filtered), len(universe)
        )
        return filtered

    # ── candles ──────────────────────────────────────────────────────────────

    async def _candle_snapshot(self, coin: str, start_ms: int, end_ms: int) -> list[dict]:
        """One candleSnapshot query → raw Hyperliquid candle dicts (``{t,o,h,l,c,v}``)."""
        body = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": self._interval,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        }
        data = await self._info(body)
        return data if isinstance(data, list) else []

    async def get_historical_closes(
        self,
        market: str,
        *,
        num_pages: int | None = None,
        now=None,
        concurrent: bool = False,
    ) -> list[dict]:
        """
        Fetch recent historical close prices for one market.

        Returns a chronologically-sorted, de-duplicated list of
        ``{"datetime": str, "close": float}`` (empty on failure), matching the dYdX
        client's shape. ``num_pages * candles_per_page`` bars back from ``now`` are
        requested in a single snapshot (Hyperliquid returns a contiguous range), so
        the ``concurrent`` flag is accepted for protocol parity but unused.
        """
        pages = num_pages or config.NUM_HISTORICAL_PAGES
        bars = min(pages * self.candles_per_page, _MAX_CANDLES_PER_REQUEST)
        end_dt = now or datetime.now(timezone.utc)
        end_ms = _ms(end_dt)
        start_ms = end_ms - bars * self._resolution_seconds * 1000

        candles = await self._candle_snapshot(market, start_ms, end_ms)
        by_datetime: dict[str, float] = {}
        for c in candles:
            by_datetime[_to_iso(int(c["t"]))] = float(c["c"])
        return [
            {"datetime": ts, "close": close}
            for ts, close in sorted(by_datetime.items())
        ]

    async def get_current_prices(self, markets: list[str]) -> dict[str, float]:
        """Latest mid price for many markets in a **single** ``/info`` request.

        Hyperliquid's ``allMids`` returns ``{coin: priceStr}`` for the whole
        universe in one call (~0.4s), so the dashboard's price poll costs one
        request regardless of how many pairs the scan found — instead of one
        ``candleSnapshot`` per market. That fan-out (~179 requests every 20s for
        HL's large universe) was saturating the ``/info`` rate budget into 429s
        and starving the manual-record snapshot (issue #142). dYdX has no such
        bulk endpoint, so it keeps the per-market path; ``current_prices`` picks
        whichever a client provides.

        Markets absent from ``allMids`` (or with an unparseable price) are simply
        omitted — the caller renders "—". Returns ``{}`` on a fetch failure.
        """
        data = await self._info({"type": "allMids"})
        if not isinstance(data, dict):
            logger.warning("allMids returned no data")
            return {}
        out: dict[str, float] = {}
        for market in dict.fromkeys(markets):  # de-dupe, preserve order
            raw = data.get(market)
            if raw is None:
                continue
            try:
                out[market] = float(raw)
            except (TypeError, ValueError):
                continue
        return out

    async def fetch_ohlcv_range(self, market: str, start, end) -> list[dict]:
        """Fetch full OHLCV candles for ``market`` over [start, end].

        Walks forward in <=5,000-bar chunks (Hyperliquid's per-request cap), de-duped
        by timestamp. Returns dicts using the **dYdX key names** the ingest
        orchestrator reads (``startedAt`` / open / high / low / close /
        baseTokenVolume), with prices/volume coerced to floats; the caller cleans +
        caches them.
        """
        step = _MAX_CANDLES_PER_REQUEST * self._resolution_seconds  # seconds per chunk
        out: dict[str, dict] = {}
        cursor = start
        for _ in range(2000):  # safety bound
            if cursor >= end:
                break
            chunk_end = min(cursor + timedelta(seconds=step), end)
            candles = await self._candle_snapshot(market, _ms(cursor), _ms(chunk_end))
            if not candles:
                # No data in this window — advance past it rather than spin.
                cursor = chunk_end
                continue
            for c in candles:
                iso = _to_iso(int(c["t"]))
                out[iso] = {
                    "startedAt": iso,
                    "open": float(c["o"]),
                    "high": float(c["h"]),
                    "low": float(c["l"]),
                    "close": float(c["c"]),
                    "baseTokenVolume": float(c.get("v", 0)),
                }
            latest = max(int(c["t"]) for c in candles)
            next_cursor = datetime.fromtimestamp(
                latest / 1000, tz=timezone.utc
            ) + timedelta(seconds=self._resolution_seconds)
            if next_cursor <= cursor:  # no forward progress
                break
            cursor = next_cursor
        return list(out.values())

    async def fetch_funding_range(self, market: str, start, end) -> list[dict]:
        """Paginate historical funding for ``market`` over [start, end].

        Walks forward in ~7-day windows (fundingHistory truncates long ranges).
        Returns dicts using the **dYdX key names** (``effectiveAt`` / ``rate``) so
        the shared ingest path is unchanged; the caller filters/cleans/caches.
        Best-effort: a window error ends the walk with whatever was collected.
        """
        out: dict[str, dict] = {}
        cursor = start
        for _ in range(2000):
            if cursor >= end:
                break
            window_end = min(cursor + _FUNDING_WINDOW, end)
            data = await self._info(
                {
                    "type": "fundingHistory",
                    "coin": market,
                    "startTime": _ms(cursor),
                    "endTime": _ms(window_end),
                }
            )
            if not isinstance(data, list) or not data:
                cursor = window_end
                continue
            for f in data:
                iso = _to_iso(int(f["time"]))
                out[iso] = {"effectiveAt": iso, "rate": float(f["fundingRate"])}
            cursor = window_end
        return list(out.values())
