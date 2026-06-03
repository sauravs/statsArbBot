"""
Live trading bot endpoints (PRD F5). The execution core's HTTP surface — the
Phase-5b UI (OpenTradesTable, BotControls, AccountCard, …) consumes these.

  POST /api/live/session/start  — activate the bot for (exchange, mode).
  POST /api/live/session/stop   — deactivate (open trades remain for the exit mgr).
  GET  /api/live/session        — current active session (or null).
  POST /api/live/entry-scan     — run one entry-scan pass.
  POST /api/live/exit-manage    — run one exit-management pass.
  POST /api/live/abort          — emergency stop: close everything.
  GET  /api/live/trades         — list trades (optional ?status=OPEN|CLOSED|ERROR).
  GET  /api/live/account        — free collateral + equity.

Passes are serialised inside the engine; the route layer only validates scope and
maps engine errors to HTTP. Forward-test (testnet) is the only mode wired for real
execution this phase; production (mainnet) is gated behind the same surface.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import config
from auth import require_api_key
from exchanges import EXCHANGE_REGISTRY
from trading.engine import NoActiveSession, get_live_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", dependencies=[Depends(require_api_key)])

# Live execution targets a real account; only testnet/mainnet trading modes apply
# (the "simulation" mode is a virtual account handled by Phase 6, not the live bot).
_VALID_MODES = {"forward_test", "production"}
_VALID_STATUSES = {"OPEN", "CLOSED", "ERROR", "PENDING"}


def _validate_scope(exchange: str, mode: str) -> None:
    if exchange not in EXCHANGE_REGISTRY:
        raise HTTPException(status_code=422, detail=f"Unknown exchange '{exchange}'.")
    if not EXCHANGE_REGISTRY[exchange].integrated:
        raise HTTPException(status_code=422, detail=f"Exchange '{exchange}' is not integrated.")
    if mode not in _VALID_MODES:
        raise HTTPException(
            status_code=422, detail=f"Mode must be one of {sorted(_VALID_MODES)}."
        )


class ScopeBody(BaseModel):
    exchange: str = config.DEFAULT_EXCHANGE
    mode: str = config.DEFAULT_MODE


class PassBody(ScopeBody):
    # Optional per-pass threshold overrides; None → config default. Bounded HERE at
    # the trust boundary (not just in the UI) so a forged/curl request with the same
    # session can't pass a degenerate value: entry_threshold=0 opens every pair, and
    # stop_threshold=0 makes |Z|>=0 always fire → the next exit pass force-closes the
    # whole book. Out-of-range (and NaN/Infinity) → Pydantic 422 automatically.
    entry_threshold: float | None = Field(default=None, ge=0.5, le=4.0)
    exit_threshold: float | None = Field(default=None, gt=0.0, le=2.0)
    stop_threshold: float | None = Field(default=None, ge=1.0, le=10.0)


def _guard_db(exc: Exception) -> HTTPException:
    logger.error("live engine DB error: %s", exc)
    return HTTPException(status_code=503, detail="Live trading datastore unavailable.")


@router.post("/session/start", status_code=201)
async def start_session(body: ScopeBody) -> dict:
    _validate_scope(body.exchange, body.mode)
    try:
        return await get_live_engine().start_session(exchange=body.exchange, mode=body.mode)
    except Exception as exc:
        raise _guard_db(exc)


@router.post("/session/stop")
async def stop_session(body: ScopeBody) -> dict:
    _validate_scope(body.exchange, body.mode)
    try:
        return await get_live_engine().stop_session(exchange=body.exchange, mode=body.mode)
    except Exception as exc:
        raise _guard_db(exc)


@router.get("/session")
async def get_session(
    exchange: str = Query(default=config.DEFAULT_EXCHANGE),
    mode: str = Query(default=config.DEFAULT_MODE),
) -> dict:
    _validate_scope(exchange, mode)
    try:
        session = await get_live_engine().get_session(exchange=exchange, mode=mode)
    except Exception as exc:
        raise _guard_db(exc)
    return {"session": session, "active": session is not None}


@router.post("/entry-scan")
async def entry_scan(body: PassBody) -> dict:
    _validate_scope(body.exchange, body.mode)
    opts = {k: v for k, v in {"entry_threshold": body.entry_threshold}.items() if v is not None}
    try:
        return await get_live_engine().run_entry_scan(
            exchange=body.exchange, mode=body.mode, **opts
        )
    except NoActiveSession as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise _guard_db(exc)


@router.post("/exit-manage")
async def exit_manage(body: PassBody) -> dict:
    _validate_scope(body.exchange, body.mode)
    opts = {
        k: v
        for k, v in {
            "exit_threshold": body.exit_threshold,
            "stop_threshold": body.stop_threshold,
        }.items()
        if v is not None
    }
    try:
        return await get_live_engine().run_exit_management(
            exchange=body.exchange, mode=body.mode, **opts
        )
    except Exception as exc:
        raise _guard_db(exc)


@router.post("/abort")
async def abort(body: ScopeBody) -> dict:
    _validate_scope(body.exchange, body.mode)
    try:
        return await get_live_engine().abort_all(exchange=body.exchange, mode=body.mode)
    except Exception as exc:
        raise _guard_db(exc)


@router.get("/trades")
async def list_trades(
    exchange: str = Query(default=config.DEFAULT_EXCHANGE),
    mode: str = Query(default=config.DEFAULT_MODE),
    status: str | None = Query(default=None),
) -> dict:
    _validate_scope(exchange, mode)
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Unknown status '{status}'.")
    try:
        trades = await get_live_engine().list_trades(
            exchange=exchange, mode=mode, status=status
        )
    except Exception as exc:
        raise _guard_db(exc)
    return {"trades": trades, "count": len(trades)}


@router.get("/account")
async def account(
    exchange: str = Query(default=config.DEFAULT_EXCHANGE),
    mode: str = Query(default=config.DEFAULT_MODE),
) -> dict:
    _validate_scope(exchange, mode)
    try:
        return await get_live_engine().account_summary()
    except Exception as exc:
        logger.error("account summary failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not read account from exchange.")
