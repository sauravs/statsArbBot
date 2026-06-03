"""
Fast-forward simulation endpoints (PRD F7.3). The control surface the Phase-7 UI
(list / run / detail / saved-results) consumes.

  POST /api/ff/simulations            — create + launch a replay (background).
  GET  /api/ff/simulations            — list runs (newest first).
  GET  /api/ff/simulations/{id}       — one run with its saved aggregates.
  POST /api/ff/simulations/{id}/stop  — cancel a running replay (partial save).

A run replays historical OHLCV from the candle source over [start_time, end_time]
through the same engine the real-time sim uses; the heavy work happens in a
background task, so the POST returns immediately with a RUNNING row and the UI
polls the detail endpoint for progress → COMPLETED. Thresholds are bounded at this
trust boundary (as in the sim/live routers) so a degenerate value can't be
persisted onto a run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

import config
from auth import require_api_key
from db.scan_repository import get_scan_repository
from exchanges import EXCHANGE_REGISTRY
from replay.candle_source import demo_window
from replay.engine import FFSimNotFound, get_ff_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ff", dependencies=[Depends(require_api_key)])


def _validate_exchange(exchange: str) -> None:
    if exchange not in EXCHANGE_REGISTRY:
        raise HTTPException(status_code=422, detail=f"Unknown exchange '{exchange}'.")
    if not EXCHANGE_REGISTRY[exchange].integrated:
        raise HTTPException(status_code=422, detail=f"Exchange '{exchange}' is not integrated.")


def _guard_db(exc: Exception) -> HTTPException:
    logger.error("fast-forward engine DB error: %s", exc)
    return HTTPException(status_code=503, detail="Fast-forward datastore unavailable.")


class CreateFFBody(BaseModel):
    exchange: str = config.DEFAULT_EXCHANGE
    label: str | None = Field(default=None, max_length=120)
    # Optional offline: defaults to the demo history window when omitted in fake mode.
    start_time: datetime | None = None
    end_time: datetime | None = None
    speed: int = Field(default=3600, ge=1, le=1_000_000)
    starting_capital: float = Field(default=10_000.0, gt=0)
    zscore_window: int = Field(default=config.ZSCORE_WINDOW, ge=3, le=500)
    entry_threshold: float = Field(default=config.ZSCORE_THRESH, ge=0.5, le=4.0)
    exit_threshold: float = Field(default=config.EXIT_ZSCORE, gt=0.0, le=2.0)
    stop_threshold: float = Field(default=config.STOP_LOSS_ZSCORE, ge=1.0, le=10.0)
    usd_per_trade: float = Field(default=config.USD_PER_TRADE, gt=0)
    max_active_pairs: int | None = Field(default=None, ge=1, le=100)
    slippage_pct: float = Field(default=0.05, ge=0.0, le=5.0)
    taker_fee_pct: float = Field(default=0.05, ge=0.0, le=5.0)
    funding_freq_h: int = Field(default=1, ge=1, le=24)


def _resolve_window(body: CreateFFBody) -> tuple[datetime, datetime]:
    start, end = body.start_time, body.end_time
    if start is None or end is None:
        if config.SCAN_DATA_SOURCE == "fake":
            d_start, d_end = demo_window()
            start = start or d_start
            end = end or d_end
        else:
            raise HTTPException(
                status_code=422, detail="start_time and end_time are required."
            )
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if start >= end:
        raise HTTPException(status_code=422, detail="start_time must be before end_time.")
    return start, end


@router.post("/simulations", status_code=201)
async def create_simulation(body: CreateFFBody, background: BackgroundTasks) -> dict:
    _validate_exchange(body.exchange)
    start, end = _resolve_window(body)

    # Fail fast if there's nothing to replay (a replay needs the scan's β/α).
    try:
        pairs = await get_scan_repository().get_latest_pairs(
            exchange=body.exchange, mode=config.DEFAULT_MODE
        )
    except Exception as exc:
        raise _guard_db(exc)
    if not pairs:
        raise HTTPException(
            status_code=409,
            detail="No cointegrated pairs to replay — run a scan first.",
        )

    params = body.model_dump(exclude={"start_time", "end_time"})
    params["start_time"] = start
    params["end_time"] = end
    params["status"] = "RUNNING"
    try:
        row = await get_ff_engine().create(params)
    except Exception as exc:
        raise _guard_db(exc)

    background.add_task(get_ff_engine().run_replay, row["id"])
    return row


@router.get("/simulations")
async def list_simulations() -> dict:
    try:
        runs = await get_ff_engine().list()
    except Exception as exc:
        raise _guard_db(exc)
    return {"simulations": runs, "count": len(runs)}


@router.get("/simulations/{ff_id}")
async def get_simulation(ff_id: str) -> dict:
    try:
        run = await get_ff_engine().get(ff_id)
    except Exception as exc:
        raise _guard_db(exc)
    if run is None:
        raise HTTPException(status_code=404, detail="Fast-forward simulation not found.")
    return run


@router.post("/simulations/{ff_id}/stop")
async def stop_simulation(ff_id: str) -> dict:
    try:
        return await get_ff_engine().request_stop(ff_id)
    except FFSimNotFound:
        raise HTTPException(status_code=404, detail="Fast-forward simulation not found.")
    except Exception as exc:
        raise _guard_db(exc)
