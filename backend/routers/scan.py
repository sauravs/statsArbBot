"""
Cointegration scan control endpoints.

  POST /api/scan/start   — claim and launch a background scan (409 if running).
  GET  /api/scan/status  — current scan progress (polled by the dashboard).
  POST /api/scan/reset    — clear idle state back to zero.

The start guard lives in ``ScanState.try_begin()`` so two concurrent start
requests cannot launch overlapping scans (the prototype's race).
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from auth import require_api_key
from scan import SCAN_STATE, run_scan

router = APIRouter(prefix="/api/scan", dependencies=[Depends(require_api_key)])


class ScanStartBody(BaseModel):
    quick: bool = False  # quick scan fetches fewer history pages
    num_pages: int | None = None  # explicit override


@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
async def start_scan(body: ScanStartBody, background_tasks: BackgroundTasks) -> dict:
    if not await SCAN_STATE.try_begin():
        raise HTTPException(status_code=409, detail="Scan already running")
    background_tasks.add_task(run_scan, quick=body.quick, num_pages=body.num_pages)
    label = "Quick" if body.quick else "Full"
    return {"message": f"{label} scan started", "started": True}


@router.post("/stop")
async def stop_scan() -> dict:
    """Request the running scan to stop at its next safe checkpoint (issue #59).

    Whatever pairs were found so far are persisted; 409 if no scan is running.
    """
    if not await SCAN_STATE.request_stop():
        raise HTTPException(status_code=409, detail="No scan is running")
    return SCAN_STATE.snapshot()


@router.get("/status")
async def scan_status() -> dict:
    return SCAN_STATE.snapshot()


@router.post("/reset")
async def reset_scan() -> dict:
    await SCAN_STATE.reset()
    return SCAN_STATE.snapshot()
