"""
Historical-data inventory (issue #80).

  GET /api/data/inventory — per-market coverage of the OHLCV cache (bars, date
                            range, completeness) + a funding summary, so the
                            dashboard can show what the scan/sim/ff/backtest
                            engines are actually running on. Read-only; fetching
                            new data by date range is tracked separately (#81).
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import config
from auth import require_api_key
from ingest import historical_fetch
from ingest.cache_repository import get_ohlcv_cache_repository

logger = logging.getLogger(__name__)

router = APIRouter()

# Seconds per bar for the cached resolutions — used to size the gapless-series
# expectation behind ``completeness``. Falls back to 1h for anything unlisted.
_RESOLUTION_SECONDS = {
    "1MIN": 60,
    "5MINS": 300,
    "15MINS": 900,
    "30MINS": 1800,
    "1HOUR": 3600,
    "4HOURS": 14400,
    "1DAY": 86400,
}


@router.get("/api/data/inventory", dependencies=[Depends(require_api_key)])
async def data_inventory() -> dict:
    """Per-market cache coverage + a funding summary for the Data section."""
    exchange = config.DEFAULT_EXCHANGE
    resolution = config.CANDLE_RESOLUTION
    step = _RESOLUTION_SECONDS.get(resolution, 3600)
    repo = get_ohlcv_cache_repository()
    try:
        markets = await repo.get_inventory(
            exchange=exchange, resolution=resolution, step_seconds=step
        )
        funding = await repo.get_funding_summary(exchange=exchange)
    except Exception as exc:  # DB / generated-client unavailable
        logger.error("data inventory query failed: %s", exc)
        raise HTTPException(status_code=503, detail="Cache datastore unavailable.")

    # ISO strings share one format/zone, so lexical min/max == chronological.
    earliest = min((m["first"] for m in markets), default=None)
    latest = max((m["last"] for m in markets), default=None)
    return {
        "exchange": exchange,
        "resolution": resolution,
        "markets": markets,
        "summary": {
            "market_count": len(markets),
            "total_bars": sum(m["bars"] for m in markets),
            "earliest": earliest,
            "latest": latest,
            "funding_markets": funding["markets"],
            "funding_rows": funding["rows"],
        },
    }


class FetchBody(BaseModel):
    start: datetime
    end: datetime


@router.post("/api/data/fetch", dependencies=[Depends(require_api_key)])
async def start_fetch(body: FetchBody) -> dict:
    """
    Launch a background fetch of liquid-market OHLCV/funding for [start, end] from
    the dYdX mainnet indexer (issue #81). Cleans + merges into the cache within the
    window (no data loss). 422 on a bad/oversized range, 409 if one is already
    running. Poll ``/api/data/fetch/status``; stop via ``/api/data/fetch/cancel``.
    """
    try:
        return await historical_fetch.start_fetch(body.start, body.end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/api/data/fetch/status", dependencies=[Depends(require_api_key)])
async def fetch_status() -> dict:
    """Progress of the current/last historical fetch."""
    return historical_fetch.get_state()


@router.post("/api/data/fetch/cancel", dependencies=[Depends(require_api_key)])
async def cancel_fetch() -> dict:
    """Request the running fetch stop at the next market boundary."""
    historical_fetch.request_cancel()
    return historical_fetch.get_state()
