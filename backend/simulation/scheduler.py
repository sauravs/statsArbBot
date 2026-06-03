"""
Simulation scheduler (PRD F6.4) — drives ``SimulationEngine.tick`` on a per-session
APScheduler interval.

A single ``AsyncIOScheduler`` runs in the API event loop; each RUNNING session gets
its own interval job (``coalesce=True`` + ``max_instances=1`` so a slow tick never
stacks). Jobs are not persisted — on API startup :func:`reregister_running_sessions`
reads the RUNNING sessions from the DB and reschedules them, satisfying "sessions
re-registered on API restart". The router adds a job on create/resume and removes
it on pause/stop.

APScheduler is an optional import: if it is unavailable the scheduler degrades to a
no-op (sessions can still be ticked manually via the ``/tick`` endpoint), so the
rest of the app and the test suite never hard-depend on it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    _APSCHEDULER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _APSCHEDULER_AVAILABLE = False
    logger.warning("APScheduler not installed — simulation scheduler disabled")


async def _tick_job(session_id: str) -> None:
    """The scheduled callable: run one tick, swallowing per-tick errors."""
    from simulation.engine import get_sim_engine

    try:
        result = await get_sim_engine().tick(session_id)
        logger.info("sim tick %s → %s", session_id, result)
    except Exception as exc:  # a failed tick must not kill the job
        logger.error("sim tick %s failed: %s", session_id, exc)


class SimulationScheduler:
    """Manages one interval job per RUNNING simulation session."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC") if _APSCHEDULER_AVAILABLE else None
        self._jobs: dict[str, str] = {}  # session_id -> job_id

    @property
    def available(self) -> bool:
        return self._scheduler is not None

    def start(self) -> None:
        if self._scheduler and not self._scheduler.running:
            self._scheduler.start()
            logger.info("SimulationScheduler started")

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("SimulationScheduler stopped")

    def schedule(self, session_id: str, interval_seconds: int) -> None:
        """Add/replace the interval job for a session (idempotent)."""
        if not self._scheduler:
            logger.warning("Scheduler unavailable — session %s not scheduled", session_id)
            return
        job_id = f"sim_{session_id}"
        self._scheduler.add_job(
            _tick_job,
            trigger=IntervalTrigger(seconds=max(1, int(interval_seconds))),
            id=job_id,
            args=[session_id],
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._jobs[session_id] = job_id
        logger.info("Scheduled sim session %s every %ds", session_id, interval_seconds)

    def unschedule(self, session_id: str) -> None:
        """Remove a session's job (pause/stop)."""
        if not self._scheduler:
            return
        job_id = self._jobs.pop(session_id, None)
        if job_id and self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info("Unscheduled sim session %s", session_id)

    def scheduled_ids(self) -> list[str]:
        return list(self._jobs.keys())


sim_scheduler = SimulationScheduler()


async def reregister_running_sessions() -> int:
    """Reschedule every RUNNING session from the DB (called on API startup)."""
    if not sim_scheduler.available:
        return 0
    from db.sim_repository import get_sim_repository

    sessions = await get_sim_repository().list_running_sessions()
    for s in sessions:
        sim_scheduler.schedule(s["id"], s["interval_seconds"])
    if sessions:
        logger.info("Re-registered %d running sim session(s) after restart", len(sessions))
    return len(sessions)
