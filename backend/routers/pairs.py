"""
Cointegrated pairs endpoint.

  GET /api/pairs?exchange=&mode=  — the latest scan's pairs, read from the
                                     CointScanResult table so results survive a
                                     reload / API restart (PRD F2.3).

Reads the DB half of the scan's dual-write; the CSV half is for inspection only.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

import config
from auth import require_api_key
from db.scan_repository import get_scan_repository

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get("/api/pairs")
async def get_pairs(
    exchange: str = Query(default=config.DEFAULT_EXCHANGE),
    mode: str = Query(default=config.DEFAULT_MODE),
) -> dict:
    try:
        pairs = await get_scan_repository().get_latest_pairs(
            exchange=exchange, mode=mode
        )
    except Exception as exc:  # no scan yet / DB unavailable — return empty, not 500
        logger.warning("get_pairs failed: %s", exc)
        return {"pairs": [], "count": 0, "scanned_at": None, "exchange": exchange, "mode": mode}

    scanned_at = pairs[0]["scanned_at"] if pairs else None
    return {
        "pairs": pairs,
        "count": len(pairs),
        "scanned_at": scanned_at,
        "exchange": exchange,
        "mode": mode,
    }
