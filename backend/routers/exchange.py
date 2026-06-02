"""
Exchange registry endpoint.

  GET /exchange/list  — supported exchanges and their integration status, so the
                        UI can offer dYdX and show Binance/Hyperliquid as disabled.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import require_api_key
from exchanges import list_exchanges

router = APIRouter(prefix="/exchange", dependencies=[Depends(require_api_key)])


@router.get("/list")
async def exchange_list() -> dict:
    return {"exchanges": list_exchanges()}
