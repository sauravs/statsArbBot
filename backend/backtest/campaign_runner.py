"""
Campaign execution queue (Phase-3 WS3, Slice 2).

Drives a campaign's member strategies through the existing ``BacktestEngine.run`` with
**bounded concurrency** (``campaign.concurrency`` — small, the prod box is 2-vCPU).
DB-backed so a restart resumes: every member is a persisted ``Strategy`` with its own
``processed_windows`` cursor, and campaigns left ``RUNNING`` by a crash are re-driven
at startup (:func:`resume_running_campaigns`, mirroring the sim scheduler's
``reregister_running_sessions``).

Control mirrors the engine's per-strategy model: a ``_control`` flag per campaign
(``pause`` / ``stop``) is checked before a member is launched, and in-flight members
are paused/stopped via the engine. Honest cost: the driver sets the process-global
``PER_MARKET_SLIPPAGE`` / ``MARKET_IMPACT`` to the campaign's ``cost_flags`` for the
duration of the run and **restores** them in a ``finally`` (operator-approved
2026-07-27) — a non-campaign backtest started mid-campaign would see the same globals.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import config
from backtest.engine import get_backtest_engine
from db.backtest_repository import get_strategy_repository
from db.campaign_repository import get_campaign_repository

logger = logging.getLogger(__name__)

_TERMINAL = frozenset({"COMPLETED", "FAILED", "STOPPED"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CampaignRunner:
    """Process-wide orchestrator; one background driver task per active campaign."""

    def __init__(self) -> None:
        self._control: dict[str, str] = {}          # campaign_id -> "pause" | "stop"
        self._tasks: dict[str, asyncio.Task] = {}    # campaign_id -> driver task

    async def start(self, campaign_id: str) -> dict | None:
        """Launch (or resume) the driver for a campaign. Idempotent: a campaign whose
        driver is already running is left alone."""
        repo = get_campaign_repository()
        camp = await repo.get(campaign_id)
        if camp is None:
            return None
        existing = self._tasks.get(campaign_id)
        if existing is not None and not existing.done():
            return camp
        self._control.pop(campaign_id, None)
        self._tasks[campaign_id] = asyncio.create_task(self._drive(campaign_id))
        return camp

    # Resuming a PAUSED campaign is exactly re-launching its driver.
    resume = start

    async def request_pause(self, campaign_id: str) -> dict | None:
        """Stop launching new members and pause any in-flight ones (resumable)."""
        self._control[campaign_id] = "pause"
        await self._signal_members(campaign_id, "pause")
        return await get_campaign_repository().update(campaign_id, {"status": "PAUSED"})

    async def request_stop(self, campaign_id: str) -> dict | None:
        """Terminally stop the campaign: no new members, in-flight ones stopped."""
        self._control[campaign_id] = "stop"
        await self._signal_members(campaign_id, "stop")
        return await get_campaign_repository().update(
            campaign_id, {"status": "STOPPED", "ended_at": _now()}
        )

    async def _signal_members(self, campaign_id: str, action: str) -> None:
        engine = get_backtest_engine()
        for m in await get_strategy_repository().list_by_campaign(campaign_id):
            if m["status"] == "RUNNING":
                if action == "pause":
                    await engine.request_pause(m["id"])
                else:
                    await engine.request_stop(m["id"])

    async def _drive(self, campaign_id: str) -> None:
        camp_repo = get_campaign_repository()
        strat_repo = get_strategy_repository()
        engine = get_backtest_engine()

        camp = await camp_repo.get(campaign_id)
        if camp is None:
            return

        # Honest cost flags for the run — saved + restored in finally.
        flags = (camp.get("spec") or {}).get("cost_flags") or {}
        saved = (config.PER_MARKET_SLIPPAGE, config.MARKET_IMPACT)
        config.PER_MARKET_SLIPPAGE = bool(flags.get("per_market_slippage", saved[0]))
        config.MARKET_IMPACT = bool(flags.get("market_impact", saved[1]))
        await camp_repo.update(campaign_id, {"status": "RUNNING", "started_at": _now()})

        try:
            # Normalise members left RUNNING by a crash (engine.run would skip a
            # RUNNING row): resumable if they have a cursor, else restart fresh.
            for m in await strat_repo.list_by_campaign(campaign_id):
                if m["status"] == "RUNNING":
                    resumable = (m.get("processed_windows") or 0) > 0
                    await strat_repo.update(
                        m["id"], {"status": "PAUSED" if resumable else "PENDING"}
                    )

            sem = asyncio.Semaphore(max(1, int(camp.get("concurrency") or 1)))

            async def run_one(member_id: str) -> None:
                async with sem:
                    # A pause/stop that landed while queued → don't launch this member.
                    if self._control.get(campaign_id) in ("pause", "stop"):
                        return
                    await engine.run(member_id)

            todo = [
                m["id"]
                for m in await strat_repo.list_by_campaign(campaign_id)
                if m["status"] not in _TERMINAL
            ]
            await asyncio.gather(
                *(run_one(mid) for mid in todo), return_exceptions=True
            )

            await self._finalise(campaign_id)
        except Exception:
            logger.exception("campaign %s driver crashed", campaign_id)
            await camp_repo.update(campaign_id, {"status": "PAUSED"})
        finally:
            config.PER_MARKET_SLIPPAGE, config.MARKET_IMPACT = saved
            self._control.pop(campaign_id, None)
            self._tasks.pop(campaign_id, None)

    async def _finalise(self, campaign_id: str) -> None:
        """Recompute counters from member states + set the terminal campaign status."""
        camp_repo = get_campaign_repository()
        members = await get_strategy_repository().list_by_campaign(campaign_id)
        completed = sum(1 for m in members if m["status"] == "COMPLETED")
        failed = sum(1 for m in members if m["status"] == "FAILED")

        control = self._control.get(campaign_id)
        if control == "stop":
            status = "STOPPED"
        elif control == "pause" or not all(m["status"] in _TERMINAL for m in members):
            # Paused, or some members are still non-terminal (a pause interrupted them).
            status = "PAUSED"
        else:
            status = "DONE"

        update: dict = {"status": status, "completed": completed, "failed": failed}
        if status in ("DONE", "STOPPED"):
            update["ended_at"] = _now()
        await camp_repo.update(campaign_id, update)


_runner: CampaignRunner | None = None


def get_campaign_runner() -> CampaignRunner:
    """Return the process-wide campaign runner singleton."""
    global _runner
    if _runner is None:
        _runner = CampaignRunner()
    return _runner


async def resume_running_campaigns() -> None:
    """Re-launch drivers for campaigns left RUNNING by a crash/restart (startup hook)."""
    try:
        running = await get_campaign_repository().list_running()
    except Exception as exc:
        logger.error("resume_running_campaigns: list failed: %s", exc)
        return
    runner = get_campaign_runner()
    for camp in running:
        logger.info("resuming campaign %s after restart", camp["id"])
        await runner.start(camp["id"])
