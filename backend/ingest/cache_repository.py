"""
Persistence for the historical OHLCV / funding cache (Phase 2.5).

A thin seam over the Prisma client — mirrors ``db/scan_repository.py`` — so the
ingest pipeline depends on an interface, not the generated client directly.
Tests inject :class:`FakeOhlcvCacheRepository` (no DB / no generated client);
the ingest CLI uses :class:`PrismaOhlcvCacheRepository`.

Semantics are idempotent per market: each call replaces all rows for
``(exchange, market, resolution)`` so re-running the ingest is safe. Inserts are
batched because a single market spans ~17k hourly bars over the 2024–2025 range.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DEFAULT_BATCH = 1000


class PrismaOhlcvCacheRepository:
    """Prisma-backed cache writer. Imports the generated client lazily."""

    async def replace_candles(
        self,
        market: str,
        rows: list[dict],
        *,
        exchange: str,
        resolution: str,
        batch_size: int = _DEFAULT_BATCH,
    ) -> int:
        """Replace all candles for (exchange, market, resolution). Returns count."""
        from db.client import get_db

        db = await get_db()
        await db.ohlcvcache.delete_many(
            where={"exchange": exchange, "market": market, "resolution": resolution}
        )
        written = 0
        for batch in _chunks(rows, batch_size):
            written += await db.ohlcvcache.create_many(data=batch, skip_duplicates=True)
        return written

    async def replace_funding(
        self,
        market: str,
        rows: list[dict],
        *,
        exchange: str,
        batch_size: int = _DEFAULT_BATCH,
    ) -> int:
        """Replace all funding rows for (exchange, market). Returns count."""
        from db.client import get_db

        db = await get_db()
        await db.fundingratecache.delete_many(
            where={"exchange": exchange, "market": market}
        )
        written = 0
        for batch in _chunks(rows, batch_size):
            written += await db.fundingratecache.create_many(data=batch, skip_duplicates=True)
        return written

    async def count_candles(self, *, exchange: str, resolution: str) -> int:
        from db.client import get_db

        db = await get_db()
        return await db.ohlcvcache.count(
            where={"exchange": exchange, "resolution": resolution}
        )


def _chunks(rows: list[dict], size: int):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


_repo: PrismaOhlcvCacheRepository | None = None


def get_ohlcv_cache_repository() -> PrismaOhlcvCacheRepository:
    """Return the process-wide cache repository singleton."""
    global _repo
    if _repo is None:
        _repo = PrismaOhlcvCacheRepository()
    return _repo
