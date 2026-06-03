"""
Real-time simulation endpoints (PRD F6.5). The paper-trading control surface the
Phase-6 UI (create / pause / resume / stop / top-up) consumes.

  POST /api/sim/sessions             — create a session (starts ticking).
  GET  /api/sim/sessions             — list sessions (newest first).
  GET  /api/sim/sessions/{id}        — session + open positions + trades + equity.
  POST /api/sim/sessions/{id}/pause  — stop ticking (resumable).
  POST /api/sim/sessions/{id}/resume — resume ticking.
  POST /api/sim/sessions/{id}/stop   — end session; force-close open positions.
  POST /api/sim/sessions/{id}/topup  — add virtual capital.
  POST /api/sim/sessions/{id}/tick   — run one tick now (manual / E2E driver).

Ticking otherwise happens on the session's APScheduler interval (F6.4). The engine
serialises ticks per process, so a manual tick and a scheduled one can't interleave.
Thresholds are bounded at this trust boundary (as in the live router) so a degenerate
value can't be persisted onto a session.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import config
from auth import require_api_key
from exchanges import EXCHANGE_REGISTRY
from simulation.engine import SimSessionNotFound, SimSessionTerminal, get_sim_engine
from simulation.scheduler import sim_scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sim", dependencies=[Depends(require_api_key)])


def _validate_exchange(exchange: str) -> None:
    if exchange not in EXCHANGE_REGISTRY:
        raise HTTPException(status_code=422, detail=f"Unknown exchange '{exchange}'.")
    if not EXCHANGE_REGISTRY[exchange].integrated:
        raise HTTPException(status_code=422, detail=f"Exchange '{exchange}' is not integrated.")


def _guard_db(exc: Exception) -> HTTPException:
    logger.error("sim engine DB error: %s", exc)
    return HTTPException(status_code=503, detail="Simulation datastore unavailable.")


class CreateSessionBody(BaseModel):
    exchange: str = config.DEFAULT_EXCHANGE
    label: str | None = Field(default=None, max_length=120)
    starting_capital: float = Field(default=10_000.0, gt=0)
    interval_seconds: int = Field(default=60, ge=1, le=86_400)
    zscore_window: int = Field(default=config.ZSCORE_WINDOW, ge=3, le=500)
    entry_threshold: float = Field(default=config.ZSCORE_THRESH, ge=0.5, le=4.0)
    exit_threshold: float = Field(default=config.EXIT_ZSCORE, gt=0.0, le=2.0)
    stop_threshold: float = Field(default=config.STOP_LOSS_ZSCORE, ge=1.0, le=10.0)
    usd_per_trade: float = Field(default=config.USD_PER_TRADE, gt=0)
    max_active_pairs: int | None = Field(default=None, ge=1, le=100)
    slippage_pct: float = Field(default=0.05, ge=0.0, le=5.0)
    taker_fee_pct: float = Field(default=0.05, ge=0.0, le=5.0)
    funding_freq_h: int = Field(default=1, ge=1, le=24)


class TopUpBody(BaseModel):
    amount: float = Field(gt=0)


@router.post("/sessions", status_code=201)
async def create_session(body: CreateSessionBody) -> dict:
    _validate_exchange(body.exchange)
    params = body.model_dump()
    params["mode"] = "simulation"
    params["status"] = "RUNNING"
    try:
        session = await get_sim_engine().create_session(params)
    except Exception as exc:
        raise _guard_db(exc)
    sim_scheduler.schedule(session["id"], session["interval_seconds"])
    return session


@router.get("/sessions")
async def list_sessions() -> dict:
    try:
        sessions = await get_sim_engine().list_sessions()
    except Exception as exc:
        raise _guard_db(exc)
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    try:
        return await get_sim_engine().overview(session_id)
    except SimSessionNotFound:
        raise HTTPException(status_code=404, detail="Simulation session not found.")
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard_db(exc)


@router.post("/sessions/{session_id}/pause")
async def pause_session(session_id: str) -> dict:
    try:
        session = await get_sim_engine().set_status(session_id, "PAUSED")
    except SimSessionNotFound:
        raise HTTPException(status_code=404, detail="Simulation session not found.")
    except SimSessionTerminal:
        raise HTTPException(status_code=409, detail="A stopped session cannot be paused.")
    except Exception as exc:
        raise _guard_db(exc)
    sim_scheduler.unschedule(session_id)
    return session


@router.post("/sessions/{session_id}/resume")
async def resume_session(session_id: str) -> dict:
    # The STOPPED guard is enforced atomically inside set_status (under the engine
    # lock + a source-state re-read), so a stop that lands between any pre-check
    # and the write — or a /pause that laundered STOPPED→PAUSED — still can't
    # revive a terminal session.
    try:
        session = await get_sim_engine().set_status(session_id, "RUNNING")
    except SimSessionNotFound:
        raise HTTPException(status_code=404, detail="Simulation session not found.")
    except SimSessionTerminal:
        raise HTTPException(status_code=409, detail="A stopped session cannot be resumed.")
    except Exception as exc:
        raise _guard_db(exc)
    sim_scheduler.schedule(session["id"], session["interval_seconds"])
    return session


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str) -> dict:
    try:
        result = await get_sim_engine().stop(session_id)
    except SimSessionNotFound:
        raise HTTPException(status_code=404, detail="Simulation session not found.")
    except Exception as exc:
        raise _guard_db(exc)
    sim_scheduler.unschedule(session_id)
    return result


@router.post("/sessions/{session_id}/topup")
async def topup_session(session_id: str, body: TopUpBody) -> dict:
    try:
        return await get_sim_engine().top_up(session_id, body.amount)
    except SimSessionNotFound:
        raise HTTPException(status_code=404, detail="Simulation session not found.")
    except SimSessionTerminal:
        raise HTTPException(status_code=409, detail="A stopped session cannot be topped up.")
    except Exception as exc:
        raise _guard_db(exc)


@router.post("/sessions/{session_id}/tick")
async def tick_session(session_id: str) -> dict:
    try:
        return await get_sim_engine().tick(session_id)
    except SimSessionNotFound:
        raise HTTPException(status_code=404, detail="Simulation session not found.")
    except Exception as exc:
        raise _guard_db(exc)
