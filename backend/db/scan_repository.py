"""
Persistence for cointegration scan results — the DB half of the dual-write.

This is a thin seam over the Prisma client so the scan orchestrator and the
``/api/pairs`` router depend on an interface, not the generated client directly.
Tests inject a fake repository (no DB / no generated client required); the
process uses :class:`PrismaScanRepository` via :func:`get_scan_repository`.

Semantics: the table holds the **latest** scan per (exchange, mode). Each run
replaces the previous rows in a single transaction, so ``/api/pairs`` reading
back after a reload always sees a complete, current result set (never a
half-written one).
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class PrismaScanRepository:
    """Prisma-backed implementation. Imports the generated client lazily."""

    async def replace_scan_results(
        self, rows: list[dict], *, exchange: str, mode: str
    ) -> int:
        """
        Replace all rows for (exchange, mode) with ``rows`` in one transaction.
        ``rows`` are dicts of CointScanResult fields. Returns the count written.
        """
        from db.client import get_db

        db = await get_db()
        async with db.tx() as tx:
            await tx.cointscanresult.delete_many(
                where={"exchange": exchange, "mode": mode}
            )
            if rows:
                await tx.cointscanresult.create_many(data=rows)
        return len(rows)

    async def get_latest_pairs(self, *, exchange: str, mode: str) -> list[dict]:
        """Return the stored pairs for (exchange, mode), best quality first."""
        from db.client import get_db

        db = await get_db()
        records = await db.cointscanresult.find_many(
            where={"exchange": exchange, "mode": mode},
            # p_value tie-break makes the order deterministic across reads and
            # matches the CSV half of the dual-write.
            order=[{"zero_crossings": "desc"}, {"p_value": "asc"}],
        )
        return [self._to_dict(r) for r in records]

    async def get_pair(
        self, *, exchange: str, mode: str, base_market: str, quote_market: str
    ) -> dict | None:
        """Return one stored pair (orientation-sensitive), or None if absent.

        The single lookup the pair-detail and manual-record endpoints share, so
        the scan is the one source of a pair's β/α/half-life.
        """
        pairs = await self.get_latest_pairs(exchange=exchange, mode=mode)
        return next(
            (
                p
                for p in pairs
                if p["base_market"] == base_market
                and p["quote_market"] == quote_market
            ),
            None,
        )

    @staticmethod
    def _to_dict(r) -> dict:
        return {
            "base_market": r.base_market,
            "quote_market": r.quote_market,
            "hedge_ratio": r.hedge_ratio,
            "intercept": r.intercept,
            "half_life": r.half_life,
            "zero_crossings": r.zero_crossings,
            "p_value": r.p_value,
            "z_score": r.z_score,
            "spread_std": r.spread_std,
            "scanned_at": _iso(r.scanned_at),
            "window_start": _iso(r.window_start),
            "window_end": _iso(r.window_end),
            "exchange": r.exchange,
            "mode": r.mode,
        }


_repo: PrismaScanRepository | None = None


def get_scan_repository() -> PrismaScanRepository:
    """Return the process-wide scan repository singleton."""
    global _repo
    if _repo is None:
        _repo = PrismaScanRepository()
    return _repo
