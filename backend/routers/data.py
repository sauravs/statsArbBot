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

from fastapi import APIRouter, Depends, HTTPException

import config
from auth import require_api_key
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
