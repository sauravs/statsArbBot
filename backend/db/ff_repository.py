"""
Persistence for fast-forward simulation runs (PRD F7) — a thin Prisma seam over
``SavedFFSimulation``, mirroring ``db/sim_repository.py``.

A run is one row: the create endpoint inserts it RUNNING, the engine updates
progress/aggregates as it replays, and list/detail read it back. The JSON result
columns (equity curve, per-pair P&L, exit reasons) are wrapped with ``prisma.Json``
on write and returned parsed on read. Tests inject ``FakeFFRepository``.
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# JSON result columns — wrapped in prisma.Json on write, returned parsed on read.
_JSON_FIELDS = ("equity_curve", "per_pair_pnl", "exit_reasons")


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _enum_value(value) -> str:
    return getattr(value, "value", value)


class PrismaFFRepository:
    """Prisma-backed implementation. Imports the generated client lazily."""

    async def create(self, params: dict) -> dict:
        from db.client import get_db

        db = await get_db()
        record = await db.savedffsimulation.create(data=self._encode(params))
        return self._to_dict(record)

    async def get(self, ff_id: str) -> dict | None:
        from db.client import get_db

        db = await get_db()
        record = await db.savedffsimulation.find_unique(where={"id": ff_id})
        return self._to_dict(record) if record is not None else None

    async def list(self) -> list[dict]:
        from db.client import get_db

        db = await get_db()
        records = await db.savedffsimulation.find_many(order=[{"created_at": "desc"}])
        return [self._to_dict(r) for r in records]

    async def update(self, ff_id: str, data: dict) -> dict | None:
        from db.client import get_db
        from prisma.errors import RecordNotFoundError

        db = await get_db()
        try:
            record = await db.savedffsimulation.update(
                where={"id": ff_id}, data=self._encode(data)
            )
        except RecordNotFoundError:
            return None
        return self._to_dict(record) if record is not None else None

    @staticmethod
    def _encode(data: dict) -> dict:
        from prisma import Json

        out = dict(data)
        for k in _JSON_FIELDS:
            if k in out and out[k] is not None:
                out[k] = Json(out[k])
        return out

    @staticmethod
    def _to_dict(r) -> dict:
        return {
            "id": r.id,
            "exchange": _enum_value(r.exchange),
            "label": r.label,
            "status": _enum_value(r.status),
            "start_time": _iso(r.start_time),
            "end_time": _iso(r.end_time),
            "speed": r.speed,
            "zscore_window": r.zscore_window,
            "entry_threshold": r.entry_threshold,
            "exit_threshold": r.exit_threshold,
            "stop_threshold": r.stop_threshold,
            "usd_per_trade": r.usd_per_trade,
            "max_active_pairs": r.max_active_pairs,
            "slippage_pct": r.slippage_pct,
            "taker_fee_pct": r.taker_fee_pct,
            "funding_freq_h": r.funding_freq_h,
            "pairs_count": r.pairs_count,
            "total_ticks": r.total_ticks,
            "processed_ticks": r.processed_ticks,
            "progress": r.progress,
            "starting_capital": r.starting_capital,
            "final_capital": r.final_capital,
            "realised_pnl": r.realised_pnl,
            "total_trades": r.total_trades,
            "equity_curve": r.equity_curve,
            "per_pair_pnl": r.per_pair_pnl,
            "exit_reasons": r.exit_reasons,
            "error": r.error,
            "created_at": _iso(r.created_at),
            "completed_at": _iso(r.completed_at),
        }


_repo: PrismaFFRepository | None = None


def get_ff_repository() -> PrismaFFRepository:
    """Return the process-wide fast-forward repository singleton."""
    global _repo
    if _repo is None:
        _repo = PrismaFFRepository()
    return _repo
