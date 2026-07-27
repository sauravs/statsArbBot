"""
FastAPI application factory — statsArbBot.

Run from the backend/ directory:
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload

Domain routers are registered in the lifespan (deferred imports avoid circular
imports at module load). Phase 0 ships only the system/health router; later
phases add scan, pairs, manual, live, sim, ff, backtest, exchange.
"""

from __future__ import annotations

import logging
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
      1. `prisma migrate deploy` — apply pending migrations (idempotent, best-effort).
      2. Connect the Prisma async client singleton.
    Shutdown:
      3. Disconnect the Prisma client cleanly.
    """
    if config.DATABASE_URL:
        logger.info("Running prisma migrate deploy…")
        try:
            result = subprocess.run(
                ["prisma", "migrate", "deploy", "--schema", "prisma/schema.prisma"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent,
            )
            if result.returncode != 0:
                logger.warning("prisma migrate deploy stderr:\n%s", result.stderr)
            else:
                logger.info("Migrations applied.")
        except FileNotFoundError:
            logger.warning(
                "prisma CLI not found — skipping migrate deploy. "
                "Use Docker or install the prisma CLI to apply migrations."
            )

        try:
            from db.client import get_db

            await get_db()
            logger.info("Prisma client connected.")
        except Exception as exc:
            logger.error("DB connect failed: %s", exc)

        # Re-apply any operator-persisted signal thresholds (issue #74) so they
        # survive a restart instead of resetting to the env defaults. Best-effort:
        # a missing/invalid row just leaves the defaults in place.
        try:
            from db.bot_config_repository import load_persisted_thresholds

            await load_persisted_thresholds()
        except Exception as exc:
            logger.error("loading persisted thresholds failed: %s", exc)

        # Start the simulation scheduler and re-register any RUNNING sessions so
        # real-time sims survive an API restart (PRD F6.4). Best-effort: a failure
        # here must not block the API from serving.
        try:
            from simulation.scheduler import reregister_running_sessions, sim_scheduler

            sim_scheduler.start()
            await reregister_running_sessions()
        except Exception as exc:
            logger.error("Simulation scheduler startup failed: %s", exc)

        # Re-drive any campaigns left RUNNING by a crash/restart (Phase-3 WS3). Members
        # are persisted Strategy rows with their own resume cursor, so this picks up
        # where the queue left off. Best-effort — must not block serving.
        try:
            from backtest.campaign_runner import resume_running_campaigns

            await resume_running_campaigns()
        except Exception as exc:
            logger.error("Campaign resume on startup failed: %s", exc)
    else:
        logger.warning("DATABASE_URL not set — running without a database.")

    # Install the Telegram approval gate + alerter (PRD F9.1) if configured;
    # otherwise the AutoApproveGate/LoggingAlerter defaults stay. Best-effort —
    # a Telegram failure must not block the API from serving (DB-independent).
    try:
        from telegrambot.runtime import start_telegram

        await start_telegram()
    except Exception as exc:
        logger.error("Telegram startup failed: %s", exc)

    yield

    try:
        from telegrambot.runtime import stop_telegram

        await stop_telegram()
    except Exception as exc:  # pragma: no cover
        logger.warning("Telegram shutdown failed: %s", exc)

    try:
        from simulation.scheduler import sim_scheduler

        sim_scheduler.stop()
    except Exception as exc:  # pragma: no cover
        logger.warning("Simulation scheduler stop failed: %s", exc)

    if config.DATABASE_URL:
        try:
            from db.client import close_db

            await close_db()
        except Exception as exc:  # pragma: no cover
            logger.warning("DB close failed: %s", exc)


def create_app() -> FastAPI:
    app = FastAPI(title="statsArbBot API", version="0.1.0", lifespan=lifespan)

    # The browser only ever reaches the API through the Next.js proxy (same
    # origin), but CORS is permissive in dev for direct probing.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from routers.backtest import router as backtest_router
    from routers.data import router as data_router
    from routers.exchange import router as exchange_router
    from routers.ff import router as ff_router
    from routers.live import router as live_router
    from routers.manual import router as manual_router
    from routers.pairs import router as pairs_router
    from routers.scan import router as scan_router
    from routers.sim import router as sim_router
    from routers.system import router as system_router

    app.include_router(system_router)
    app.include_router(scan_router)
    app.include_router(pairs_router)
    app.include_router(manual_router)
    app.include_router(live_router)
    app.include_router(sim_router)
    app.include_router(ff_router)
    app.include_router(backtest_router)
    app.include_router(data_router)
    app.include_router(exchange_router)
    return app


app = create_app()
