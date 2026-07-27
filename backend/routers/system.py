"""
System / health endpoints.

  GET /health            — public liveness probe (no auth); used by ops & smoke.
  GET /api/system/health — authenticated readiness probe behind the proxy's
                           X-API-Key; reports database connectivity so the
                           dashboard can prove the full UI → proxy → API → DB
                           chain end-to-end.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import config
from auth import require_api_key
from db.bot_config_repository import get_bot_config_repository
from db.scan_repository import get_scan_repository

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Public liveness probe."""
    return {"status": "ok", "service": "statsarb-api"}


@router.get("/api/system/health", dependencies=[Depends(require_api_key)])
async def system_health() -> dict:
    """Authenticated readiness probe — reports DB connectivity."""
    db_status = "disconnected"
    if config.DATABASE_URL:
        try:
            from db.client import get_db

            db = await get_db()
            db_status = "connected" if db.is_connected() else "disconnected"
        except Exception as exc:  # pragma: no cover - depends on generated client
            logger.warning("DB health check failed: %s", exc)
            db_status = "error"
    return {
        "status": "ok",
        "database": db_status,
        "environment": config.ENVIRONMENT,
        # The active market-data source ("fake" → synthetic demo data, "dydx" →
        # the live indexer). Lets the UI show a DEMO/LIVE data badge (issue #42).
        "data_source": config.SCAN_DATA_SOURCE,
        # The active live/manual-scan liquidity floor (24h $ notional) — WS1.
        # Runtime-settable; drives what the scan/manual list surfaces.
        "scan_floor": config.get_min_liquidity_usd(),
        # Read-time scan/manual-list minimisation knobs (WS2): half-spread ceiling
        # + top-N cap. {max_half_spread_pct, top_n}; 0 = off.
        "scan_list_filters": config.get_scan_list_filters(),
    }


class DataSourceBody(BaseModel):
    source: str


@router.post("/api/system/data-source", dependencies=[Depends(require_api_key)])
async def set_data_source(body: DataSourceBody) -> dict:
    """
    Switch the app-wide market-data source at runtime (issue #43).

    "fake" → synthetic demo markets; "dydx" → the live indexer. Takes effect for
    subsequent requests without a restart (no order placement — a read-only data
    switch). Resets to the env default on restart.

    Switching **clears the latest scan's pairs** for the default scope, since
    pairs found under the previous source (e.g. the demo markets) are meaningless
    under the new one — the UI then prompts a re-scan.
    """
    source = body.source.strip().lower()
    if source not in config.VALID_DATA_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"source must be one of {list(config.VALID_DATA_SOURCES)}.",
        )

    previous = config.SCAN_DATA_SOURCE
    config.set_scan_data_source(source)

    switched = source != previous
    if switched:
        try:
            await get_scan_repository().replace_scan_results(
                [], exchange=config.DEFAULT_EXCHANGE, mode=config.DEFAULT_MODE
            )
        except Exception as exc:  # don't fail the switch on a clear hiccup
            logger.warning("clearing pairs after data-source switch failed: %s", exc)

    logger.info("data source set to %s (was %s)", source, previous)
    return {"data_source": source, "previous": previous, "pairs_cleared": switched}


class ScanFloorBody(BaseModel):
    min_liquidity_usd: float


@router.get("/api/system/scan-floor", dependencies=[Depends(require_api_key)])
async def get_scan_floor() -> dict:
    """The active live/manual-scan liquidity floor (24h $ notional) — WS1."""
    return {"min_liquidity_usd": config.get_min_liquidity_usd()}


@router.post("/api/system/scan-floor", dependencies=[Depends(require_api_key)])
async def set_scan_floor(body: ScanFloorBody) -> dict:
    """
    Set the live/manual-scan liquidity floor at runtime (WS1).

    Both exchange clients read ``config.MIN_LIQUIDITY_USD`` at scan time, so this
    takes effect on the next scan without a restart. Resets to the env default on
    restart (like the data-source switch — a restart can't leave a stale
    override). Validates finite & ``0 <= value <= MIN_LIQUIDITY_USD_MAX`` (422).

    This is a **tractability/executability** knob (surface a reviewable, fillable
    pair list), NOT an alpha lever — raising it does not create edge.
    """
    previous = config.get_min_liquidity_usd()
    try:
        config.set_min_liquidity_usd(body.min_liquidity_usd)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    result = config.get_min_liquidity_usd()
    logger.info("scan floor set to %s (was %s)", result, previous)
    return {"min_liquidity_usd": result, "previous": previous}


class ScanListFiltersBody(BaseModel):
    # Both optional so the UI can set either knob independently.
    max_half_spread_pct: float | None = None
    top_n: int | None = None


@router.get("/api/system/scan-list-filters", dependencies=[Depends(require_api_key)])
async def get_scan_list_filters() -> dict:
    """The active read-time scan/manual-list minimisation knobs (WS2)."""
    return config.get_scan_list_filters()


@router.post("/api/system/scan-list-filters", dependencies=[Depends(require_api_key)])
async def set_scan_list_filters(body: ScanListFiltersBody) -> dict:
    """
    Set the read-time scan/manual-list minimisation knobs at runtime (WS2).

    ``max_half_spread_pct`` drops pairs whose wider leg exceeds it; ``top_n`` keeps
    the most tradable N (by ``min($-vol)·1/half_life·(1-p)``). Either may be omitted
    to leave it unchanged; 0 turns a knob off. Applied read-time to the pairs/manual
    list (no re-scan) and reset to the env default on restart. Validates each (422).

    A **tractability** lens — surface a shorter, fillable shortlist — NOT an alpha
    lever: filtering toward liquid names does not add edge (PHASE2_STRATEGY_PLAN §4).
    """
    try:
        if body.max_half_spread_pct is not None:
            config.set_scan_max_half_spread_pct(body.max_half_spread_pct)
        if body.top_n is not None:
            config.set_scan_top_n(body.top_n)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    result = config.get_scan_list_filters()
    logger.info("scan list filters set to %s", result)
    return result


class ThresholdsBody(BaseModel):
    entry: float
    exit: float
    stop: float


@router.get("/api/system/thresholds", dependencies=[Depends(require_api_key)])
async def get_thresholds() -> dict:
    """The active Option-B signal thresholds (entry/exit/stop) — issue #74."""
    return config.get_signal_thresholds()


@router.post("/api/system/thresholds", dependencies=[Depends(require_api_key)])
async def set_thresholds(body: ThresholdsBody) -> dict:
    """
    Set the app-wide Option-B signal thresholds at runtime (issue #74).

    Validates bounds + the ordering ``exit < entry < stop`` (422 on violation),
    applies them to ``config`` (every consumer reads them at call time, so the
    pair-detail chart and the live/sim strategy pick them up without a restart),
    then persists them to ``BotConfigHistory`` so they survive a restart. A
    persistence hiccup keeps the runtime value and is reported via ``persisted``.
    """
    try:
        config.set_signal_thresholds(body.entry, body.exit, body.stop)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    persisted = True
    try:
        await get_bot_config_repository().save_thresholds(
            body.entry,
            body.exit,
            body.stop,
            exchange=config.DEFAULT_EXCHANGE,
            mode=config.DEFAULT_MODE,
        )
    except Exception as exc:  # don't lose the runtime change on a DB hiccup
        persisted = False
        logger.warning("persisting thresholds failed (kept runtime value): %s", exc)

    result = config.get_signal_thresholds()
    result["persisted"] = persisted
    logger.info("signal thresholds set to %s (persisted=%s)", result, persisted)
    return result
