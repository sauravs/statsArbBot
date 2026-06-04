"""
Live Manual Trading endpoints (PRD F4).

  POST /api/manual/record       — record a manual trade off a scanned pair; entry
                                   prices + current spread/Z are captured server-side.
  GET  /api/manual              — list recorded manual trades (newest first).
  POST /api/manual/{id}/close   — mark a trade CLOSED with exit prices; compute P&L.

The pair's β/α/half-life come from the latest scan (authoritative), not the
client, so a recorded trade's spread matches what the scan found.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import config
from auth import require_api_key
from db.scan_repository import get_scan_repository
from exchanges import EXCHANGE_REGISTRY, make_data_client
from manual.pnl import compute_manual_pnl
from manual.repository import get_manual_trade_repository
from marketdata.pair_series import current_pair_snapshot, current_prices

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/manual", dependencies=[Depends(require_api_key)])

# The TradingMode enum values a request may target.
_VALID_MODES = {"forward_test", "simulation", "production"}


def _validate_market_scope(exchange: str, mode: str) -> None:
    """Reject unknown exchange/mode with a 422 before they reach Prisma (a bad
    enum would otherwise surface as an opaque 500)."""
    if exchange not in EXCHANGE_REGISTRY:
        raise HTTPException(status_code=422, detail=f"Unknown exchange '{exchange}'.")
    if mode not in _VALID_MODES:
        raise HTTPException(status_code=422, detail=f"Unknown mode '{mode}'.")


class RecordBody(BaseModel):
    base_market: str
    quote_market: str
    capital_leg1_usd: float = Field(gt=0)
    capital_leg2_usd: float = Field(gt=0)
    exchange: str = config.DEFAULT_EXCHANGE
    mode: str = config.DEFAULT_MODE


class CloseBody(BaseModel):
    exit_price_leg1: float = Field(gt=0)
    exit_price_leg2: float = Field(gt=0)
    closed_at: datetime | None = None


@router.post("/record", status_code=201)
async def record_manual_trade(body: RecordBody) -> dict:
    _validate_market_scope(body.exchange, body.mode)
    try:
        record = await get_scan_repository().get_pair(
            exchange=body.exchange,
            mode=body.mode,
            base_market=body.base_market,
            quote_market=body.quote_market,
        )
    except Exception as exc:
        logger.error("record_manual_trade scan read failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not read pairs from the database.")

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pair {body.base_market}/{body.quote_market} not found in the latest scan.",
        )

    client = make_data_client()
    try:
        snap = await current_pair_snapshot(
            client,
            base_market=body.base_market,
            quote_market=body.quote_market,
            hedge_ratio=record["hedge_ratio"],
            intercept=record.get("intercept", 0.0) or 0.0,
        )
    finally:
        try:
            await client.aclose()
        except Exception as exc:  # must not mask the result/error
            logger.warning("data client close failed: %s", exc)

    if snap is None:
        raise HTTPException(
            status_code=422,
            detail=f"No usable current price/Z for {body.base_market}/{body.quote_market}.",
        )

    data = {
        "exchange": body.exchange,
        "mode": body.mode,
        # Stamp the active data source so demo trades stay separable from live
        # ones in the dashboard (issue #43 follow-up).
        "data_source": config.SCAN_DATA_SOURCE,
        "base_market": body.base_market,
        "quote_market": body.quote_market,
        "hedge_ratio": record["hedge_ratio"],
        "half_life": record["half_life"],
        "z_score": snap.z_score,
        "spread_value": snap.spread_value,
        "entry_price_leg1": snap.base_price,
        "entry_price_leg2": snap.quote_price,
        "capital_leg1_usd": body.capital_leg1_usd,
        "capital_leg2_usd": body.capital_leg2_usd,
        "recorded_at": datetime.now(timezone.utc),
        "status": "OPEN",
    }
    return await get_manual_trade_repository().create(data)


@router.get("")
async def list_manual_trades(
    exchange: str = Query(default=config.DEFAULT_EXCHANGE),
    mode: str = Query(default=config.DEFAULT_MODE),
) -> dict:
    _validate_market_scope(exchange, mode)
    try:
        # Only trades recorded under the active data source — so demo trades
        # don't bleed into the live view and vice-versa (issue #43 follow-up).
        trades = await get_manual_trade_repository().list(
            exchange=exchange, mode=mode, data_source=config.SCAN_DATA_SOURCE
        )
    except Exception as exc:
        logger.error("list_manual_trades DB read failed: %s", exc)
        return {"trades": [], "count": 0, "error": "Could not read manual trades."}
    return {"trades": trades, "count": len(trades), "error": None}


@router.get("/portfolio")
async def manual_portfolio(
    exchange: str = Query(default=config.DEFAULT_EXCHANGE),
    mode: str = Query(default=config.DEFAULT_MODE),
) -> dict:
    """
    Portfolio summary for manual trades (issue #37 PR-2).

    - ``allocated_capital`` — Σ(capital_leg1 + capital_leg2) over OPEN trades.
    - ``unrealized_pnl`` — OPEN trades marked to market: each leg's current price
      used as the exit in the same ``compute_manual_pnl`` formula. ``None`` if no
      OPEN trade could be priced (so the UI shows "—" rather than a misleading 0).
    - ``realized_pnl`` — Σ stored P&L over CLOSED trades.
    - ``open_count`` / ``closed_count`` — lifecycle counts.

    Stays 200 with an ``error`` string on a DB/fetch failure so the panel renders.
    """
    _validate_market_scope(exchange, mode)
    try:
        trades = await get_manual_trade_repository().list(
            exchange=exchange, mode=mode, data_source=config.SCAN_DATA_SOURCE
        )
    except Exception as exc:
        logger.error("manual_portfolio DB read failed: %s", exc)
        return {
            "allocated_capital": 0.0,
            "unrealized_pnl": None,
            "realized_pnl": 0.0,
            "open_count": 0,
            "closed_count": 0,
            "error": "Could not read manual trades.",
        }

    open_trades = [t for t in trades if t["status"] == "OPEN"]
    closed_trades = [t for t in trades if t["status"] == "CLOSED"]
    allocated = sum(t["capital_leg1_usd"] + t["capital_leg2_usd"] for t in open_trades)
    realized = sum(t["pnl"] for t in closed_trades if t["pnl"] is not None)

    unrealized: float | None = None
    error: str | None = None
    if open_trades:
        markets = [m for t in open_trades for m in (t["base_market"], t["quote_market"])]
        client = make_data_client()
        try:
            prices = await current_prices(client, markets)
        except Exception as exc:
            logger.error("manual_portfolio price fetch failed: %s", exc)
            prices = {}
            error = "Could not fetch current prices."
        finally:
            try:
                await client.aclose()
            except Exception as exc:  # must not mask a real result/error
                logger.warning("data client close failed: %s", exc)

        priced_total = 0.0
        any_priced = False
        for t in open_trades:
            base_price = prices.get(t["base_market"])
            quote_price = prices.get(t["quote_market"])
            if base_price is None or quote_price is None:
                continue
            pnl = compute_manual_pnl(
                z_score=t["z_score"],
                entry_price_leg1=t["entry_price_leg1"],
                entry_price_leg2=t["entry_price_leg2"],
                exit_price_leg1=base_price,
                exit_price_leg2=quote_price,
                capital_leg1_usd=t["capital_leg1_usd"],
                capital_leg2_usd=t["capital_leg2_usd"],
            )
            priced_total += pnl.pnl
            any_priced = True
        if any_priced:
            unrealized = priced_total

    return {
        "allocated_capital": allocated,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "open_count": len(open_trades),
        "closed_count": len(closed_trades),
        "error": error,
    }


@router.post("/{trade_id}/close")
async def close_manual_trade(trade_id: str, body: CloseBody) -> dict:
    repo = get_manual_trade_repository()
    trade = await repo.get(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Manual trade {trade_id} not found.")
    if trade["status"] == "CLOSED":
        raise HTTPException(status_code=409, detail="Trade is already closed.")

    pnl = compute_manual_pnl(
        z_score=trade["z_score"],
        entry_price_leg1=trade["entry_price_leg1"],
        entry_price_leg2=trade["entry_price_leg2"],
        exit_price_leg1=body.exit_price_leg1,
        exit_price_leg2=body.exit_price_leg2,
        capital_leg1_usd=trade["capital_leg1_usd"],
        capital_leg2_usd=trade["capital_leg2_usd"],
    )
    closed_at = body.closed_at or datetime.now(timezone.utc)
    updated = await repo.close(
        trade_id,
        exit_price_leg1=body.exit_price_leg1,
        exit_price_leg2=body.exit_price_leg2,
        pnl=pnl.pnl,
        closed_at=closed_at,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Manual trade {trade_id} not found.")
    return {**updated, "pnl_breakdown": pnl.to_dict()}
