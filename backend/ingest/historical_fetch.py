"""
Live historical-data fetch by date range (issue #81).

Discovers the liquid dYdX market universe, fetches full OHLCV (+funding) for a
**capped** date range from the mainnet indexer (behind the #65 rate cap), cleans
it with the Phase-2.5 rules, and **merges it into the cache within the requested
window** (``merge_candles_range`` — never touches bars outside [start, end], so a
fetch extends/refreshes coverage with no data loss).

Runs as a single process-wide background job with progress + cancel, mirroring the
scan: state is mutated only on the event loop, the network/CPU work is awaited. The
client is built via :func:`make_fetch_client` so tests can inject a fake.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import pandas as pd

import config
from exchanges.dydx.client import DydxDataClient
from ingest.cache_repository import get_ohlcv_cache_repository
from ingest.cleaning import clean_funding, clean_ohlcv

logger = logging.getLogger(__name__)


@dataclass
class MarketResult:
    market: str
    bars: int = 0
    funding_rows: int = 0
    status: str = "pending"  # pending | ok | empty | error
    error: str | None = None


@dataclass
class FetchState:
    running: bool = False
    cancel_requested: bool = False
    cancelled: bool = False
    start: str | None = None
    end: str | None = None
    total_markets: int = 0
    markets_done: int = 0
    current_market: str | None = None
    results: list[MarketResult] = field(default_factory=list)
    error: str | None = None
    finished_at: str | None = None

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "cancel_requested": self.cancel_requested,
            "cancelled": self.cancelled,
            "start": self.start,
            "end": self.end,
            "total_markets": self.total_markets,
            "markets_done": self.markets_done,
            "current_market": self.current_market,
            "results": [asdict(r) for r in self.results],
            "error": self.error,
            "finished_at": self.finished_at,
        }


_state = FetchState()


def get_state() -> dict:
    return _state.snapshot()


def request_cancel() -> None:
    """Ask a running fetch to stop at the next market boundary."""
    if _state.running:
        _state.cancel_requested = True


def make_fetch_client() -> DydxDataClient:
    """The indexer client a fetch uses (mainnet — price data is always mainnet).
    Indirected so tests can monkeypatch in a fake."""
    return DydxDataClient(data_url=config.DYDX_MAINNET_INDEXER)


def _validate(start: datetime, end: datetime) -> None:
    now = datetime.now(timezone.utc)
    if start >= end:
        raise ValueError("start must be before end")
    if end > now:
        raise ValueError("end cannot be in the future")
    if (end - start).days > config.DATA_FETCH_MAX_DAYS:
        raise ValueError(
            f"range too large — max {config.DATA_FETCH_MAX_DAYS} days per fetch"
        )


async def start_fetch(start: datetime, end: datetime) -> dict:
    """Validate + launch a background fetch. Raises ValueError (bad range) /
    RuntimeError (already running). Returns the initial state snapshot."""
    global _state
    _validate(start, end)
    if _state.running:
        raise RuntimeError("a fetch is already running")
    # Claim + reset (no await between the guard above and here → atomic on the loop).
    _state = FetchState(running=True, start=start.isoformat(), end=end.isoformat())
    asyncio.create_task(_run(start, end))
    return _state.snapshot()


async def _run(start: datetime, end: datetime) -> None:
    try:
        client = make_fetch_client()
        async with client:
            tickers = sorted((await client.get_markets()).keys())
            _state.total_markets = len(tickers)
            _state.results = [MarketResult(market=t) for t in tickers]
            repo = get_ohlcv_cache_repository()
            by_market = {r.market: r for r in _state.results}
            for ticker in tickers:
                if _state.cancel_requested:
                    _state.cancelled = True
                    break
                _state.current_market = ticker
                result = by_market[ticker]
                try:
                    await _fetch_one(client, repo, ticker, start, end, result)
                except Exception as exc:  # one bad market can't sink the run
                    result.status = "error"
                    result.error = str(exc)
                    logger.warning("fetch failed for %s: %s", ticker, exc)
                _state.markets_done += 1
    except Exception as exc:
        _state.error = str(exc)
        logger.error("historical fetch crashed: %s", exc)
    finally:
        _state.running = False
        _state.current_market = None
        _state.finished_at = datetime.now(timezone.utc).isoformat()


async def _fetch_one(client, repo, market, start, end, result: MarketResult) -> None:
    raw = await client.fetch_ohlcv_range(market, start, end)
    if raw:
        df = pd.DataFrame(
            [
                {
                    "timestamp": c["startedAt"],
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c.get("baseTokenVolume", 0),
                }
                for c in raw
            ]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        clean_df, _ = clean_ohlcv(
            df,
            drop_flat=config.INGEST_DROP_FLAT,
            drop_zero_volume=config.INGEST_DROP_ZERO_VOLUME,
        )
        clean_df = _within(clean_df, start, end)
        rows = _candle_rows(clean_df, market)
        if rows:
            result.bars = await repo.merge_candles_range(
                market,
                rows,
                exchange=config.DEFAULT_EXCHANGE,
                resolution=config.CANDLE_RESOLUTION,
                start=start,
                end=end,
            )

    if config.INGEST_FUNDING:
        fraw = await client.fetch_funding_range(market, start, end)
        if fraw:
            fdf = pd.DataFrame(
                [{"timestamp": f["effectiveAt"], "funding_rate": f["rate"]} for f in fraw]
            )
            fdf["timestamp"] = pd.to_datetime(fdf["timestamp"], utc=True)
            fclean, _, _ = clean_funding(fdf)
            fclean = _within(fclean, start, end)
            frows = _funding_rows(fclean, market)
            if frows:
                result.funding_rows = await repo.merge_funding_range(
                    market,
                    frows,
                    exchange=config.DEFAULT_EXCHANGE,
                    start=start,
                    end=end,
                )

    result.status = "ok" if result.bars else "empty"


def _within(df: pd.DataFrame, start, end) -> pd.DataFrame:
    if df.empty:
        return df
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    return df[(df["timestamp"] >= lo) & (df["timestamp"] <= hi)]


def _candle_rows(df: pd.DataFrame, market: str) -> list[dict]:
    return [
        {
            "exchange": config.DEFAULT_EXCHANGE,
            "market": market,
            "resolution": config.CANDLE_RESOLUTION,
            "timestamp": r.timestamp.to_pydatetime(),
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": float(r.volume),
        }
        for r in df.itertuples(index=False)
    ]


def _funding_rows(df: pd.DataFrame, market: str) -> list[dict]:
    return [
        {
            "exchange": config.DEFAULT_EXCHANGE,
            "market": market,
            "timestamp": r.timestamp.to_pydatetime(),
            "funding_rate": float(r.funding_rate),
        }
        for r in df.itertuples(index=False)
    ]
