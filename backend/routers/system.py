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

from fastapi import APIRouter, Depends

import config
from auth import require_api_key

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
    }
