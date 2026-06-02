"""
Prisma async client singleton.

A single connected client is shared across all request handlers and background
tasks. Created lazily on first use and reconnected if the connection drops.

    from db.client import get_db

    db = await get_db()
    rows = await db.botconfighistory.find_many()
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Prisma is imported lazily inside get_db() so the rest of the backend (and its
# unit tests) can import db.client without the generated client being present.
_db = None
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Lazy-create the asyncio lock (must be created inside the running loop)."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def get_db():
    """Return the connected Prisma singleton, creating it on first call."""
    global _db
    async with _get_lock():
        if _db is None or not _db.is_connected():
            from prisma import Prisma  # generated client

            logger.info("Connecting to database…")
            _db = Prisma()
            await _db.connect()
            logger.info("Database connected.")
    return _db


async def close_db() -> None:
    """Disconnect cleanly — called from the FastAPI lifespan on shutdown."""
    global _db
    if _db is not None and _db.is_connected():
        logger.info("Disconnecting database…")
        await _db.disconnect()
        _db = None
        logger.info("Database disconnected.")
