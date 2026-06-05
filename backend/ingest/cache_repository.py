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
from datetime import datetime, timedelta

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

    async def merge_candles_range(
        self,
        market: str,
        rows: list[dict],
        *,
        exchange: str,
        resolution: str,
        start,
        end,
        batch_size: int = _DEFAULT_BATCH,
    ) -> int:
        """Replace cached candles for ``market`` **only within [start, end]** with
        ``rows`` (issue #81). Unlike ``replace_candles`` (whole-market delete), this
        deletes just the fetched window then inserts, so a date-range fetch extends
        / refreshes coverage without touching bars outside the window. One tx."""
        from db.client import get_db

        db = await get_db()
        written = 0
        async with db.tx(timeout=_TX_TIMEOUT) as tx:
            await tx.ohlcvcache.delete_many(
                where={
                    "exchange": exchange,
                    "market": market,
                    "resolution": resolution,
                    "timestamp": {"gte": start, "lte": end},
                }
            )
            for batch in _chunks(rows, batch_size):
                written += await tx.ohlcvcache.create_many(
                    data=batch, skip_duplicates=True
                )
        return written

    async def merge_funding_range(
        self,
        market: str,
        rows: list[dict],
        *,
        exchange: str,
        start,
        end,
        batch_size: int = _DEFAULT_BATCH,
    ) -> int:
        """Range-scoped funding merge — the funding analogue of
        ``merge_candles_range`` (issue #81)."""
        from db.client import get_db

        db = await get_db()
        written = 0
        async with db.tx(timeout=_TX_TIMEOUT) as tx:
            await tx.fundingratecache.delete_many(
                where={
                    "exchange": exchange,
                    "market": market,
                    "timestamp": {"gte": start, "lte": end},
                }
            )
            for batch in _chunks(rows, batch_size):
                written += await tx.fundingratecache.create_many(
                    data=batch, skip_duplicates=True
                )
        return written

    async def get_inventory(
        self, *, exchange: str, resolution: str, step_seconds: int
    ) -> list[dict]:
        """Per-market coverage for the data-inventory view (issue #80).

        One SQL-side ``GROUP BY market`` with count + min/max(timestamp) — so a
        few dozen rows summarise the whole (hundreds-of-thousands-row) cache
        without pulling the bars. ``completeness`` is bars / the bars a gapless
        series would hold between first & last at ``step_seconds`` (1.0 = no gaps),
        the cheap proxy for the ingest's gap detection.
        """
        from db.client import get_db

        db = await get_db()
        groups = await db.ohlcvcache.group_by(
            by=["market"],
            where={"exchange": exchange, "resolution": resolution},
            count={"_all": True},
            min={"timestamp": True},
            max={"timestamp": True},
        )
        out: list[dict] = []
        for g in groups:
            bars = g["_count"]["_all"]
            # group_by serialises the aggregated datetimes as ISO strings.
            first = _as_dt(g["_min"]["timestamp"])
            last = _as_dt(g["_max"]["timestamp"])
            span = (last - first).total_seconds()
            expected = int(span // step_seconds) + 1 if step_seconds > 0 else bars
            completeness = min(1.0, bars / expected) if expected > 0 else 0.0
            out.append(
                {
                    "market": g["market"],
                    "bars": bars,
                    "first": first.isoformat(),
                    "last": last.isoformat(),
                    "completeness": round(completeness, 4),
                }
            )
        return sorted(out, key=lambda r: r["market"])

    async def get_funding_summary(self, *, exchange: str) -> dict:
        """Total funding rows + distinct markets cached (issue #80)."""
        from db.client import get_db

        db = await get_db()
        groups = await db.fundingratecache.group_by(
            by=["market"],
            where={"exchange": exchange},
            count={"_all": True},
        )
        return {
            "markets": len(groups),
            "rows": sum(g["_count"]["_all"] for g in groups),
        }

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


def _as_dt(value) -> datetime:
    """Coerce a group_by timestamp (ISO string from Prisma, or a datetime from a
    fake repo) to a ``datetime``."""
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


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
