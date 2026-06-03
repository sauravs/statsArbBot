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
from datetime import timedelta

logger = logging.getLogger(__name__)

_DEFAULT_BATCH = 1000
# A market spans ~17k hourly bars; the delete+insert tx must outlast the prisma
# default (5s). Generous so a slow/remote DB still commits atomically.
_TX_TIMEOUT = timedelta(seconds=120)


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
        """Replace all candles for (exchange, market, resolution). Returns count.

        The delete + batched inserts run in one transaction so an interrupted
        run never leaves a market truncated in the cache (Phases 7/8 read it).
        """
        from db.client import get_db

        db = await get_db()
        written = 0
        async with db.tx(timeout=_TX_TIMEOUT) as tx:
            await tx.ohlcvcache.delete_many(
                where={"exchange": exchange, "market": market, "resolution": resolution}
            )
            for batch in _chunks(rows, batch_size):
                written += await tx.ohlcvcache.create_many(data=batch, skip_duplicates=True)
        return written

    async def replace_funding(
        self,
        market: str,
        rows: list[dict],
        *,
        exchange: str,
        batch_size: int = _DEFAULT_BATCH,
    ) -> int:
        """Replace all funding rows for (exchange, market) atomically. Returns count."""
        from db.client import get_db

        db = await get_db()
        written = 0
        async with db.tx(timeout=_TX_TIMEOUT) as tx:
            await tx.fundingratecache.delete_many(
                where={"exchange": exchange, "market": market}
            )
            for batch in _chunks(rows, batch_size):
                written += await tx.fundingratecache.create_many(data=batch, skip_duplicates=True)
        return written

    async def count_candles(self, *, exchange: str, resolution: str) -> int:
        from db.client import get_db

        db = await get_db()
        return await db.ohlcvcache.count(
            where={"exchange": exchange, "resolution": resolution}
        )

    async def get_markets(self, *, exchange: str, resolution: str) -> list[str]:
        """Distinct cached market tickers for (exchange, resolution), sorted.

        The walk-forward backtest (Phase 8) needs the universe of markets to scan
        each window; unlike the live scan there is no exchange ``get_markets`` to
        call — the universe is whatever the Phase-2.5 ingest seeded.

        Uses a SQL-side ``GROUP BY market`` rather than ``find_many(distinct=…)``:
        prisma-client-py applies ``distinct`` *client-side* after fetching every
        matching row, which over a fully-seeded cache (~17k bars × dozens of markets)
        would pull hundreds of thousands of rows just to list a few dozen tickers.
        """
        from db.client import get_db

        db = await get_db()
        groups = await db.ohlcvcache.group_by(
            by=["market"],
            where={"exchange": exchange, "resolution": resolution},
        )
        return sorted(g["market"] for g in groups)

    # ── reads (Phase 7 fast-forward replay) ──────────────────────────────────

    async def get_candles(
        self,
        market: str,
        *,
        exchange: str,
        resolution: str,
        start=None,
        end=None,
    ) -> list[dict]:
        """Clean candles for (exchange, market, resolution) in [start, end], ascending.

        Returns ``[{"timestamp": datetime, "close": float}, …]`` — the slice the
        replay aligns and walks. ``start``/``end`` are tz-aware datetimes (inclusive).
        """
        from db.client import get_db

        db = await get_db()
        where: dict = {"exchange": exchange, "market": market, "resolution": resolution}
        ts: dict = {}
        if start is not None:
            ts["gte"] = start
        if end is not None:
            ts["lte"] = end
        if ts:
            where["timestamp"] = ts
        records = await db.ohlcvcache.find_many(
            where=where, order=[{"timestamp": "asc"}]
        )
        return [{"timestamp": r.timestamp, "close": r.close} for r in records]

    async def get_funding(
        self, market: str, *, exchange: str, start=None, end=None
    ) -> list[dict]:
        """Funding rates for (exchange, market) in [start, end], ascending."""
        from db.client import get_db

        db = await get_db()
        where: dict = {"exchange": exchange, "market": market}
        ts: dict = {}
        if start is not None:
            ts["gte"] = start
        if end is not None:
            ts["lte"] = end
        if ts:
            where["timestamp"] = ts
        records = await db.fundingratecache.find_many(
            where=where, order=[{"timestamp": "asc"}]
        )
        return [{"timestamp": r.timestamp, "funding_rate": r.funding_rate} for r in records]


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
