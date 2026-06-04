"""
Persistence for walk-forward backtest strategies (Phase 8) — a thin Prisma seam
over ``Strategy``, mirroring ``db/ff_repository.py``.

One row is a strategy *and* its latest backtest result: the create endpoint inserts
it PENDING, the engine updates progress / partial aggregates / final results as it
sweeps windows, and CRUD + list/detail read it back. The JSON result columns
(equity curve, per-window summary, per-pair P&L, exit reasons) are wrapped with
``prisma.Json`` on write and returned parsed on read. ``recompute_ranks`` re-ranks
strategies by net P&L (F8.3). Tests inject ``FakeStrategyRepository``.
"""

from __future__ import annotations

import logging

from db.serde import enum_value as _enum_value
from db.serde import iso as _iso

logger = logging.getLogger(__name__)

# JSON result columns — wrapped in prisma.Json on write, returned parsed on read.
_JSON_FIELDS = ("equity_curve", "per_window", "per_pair_pnl", "exit_reasons")


class PrismaStrategyRepository:
    """Prisma-backed implementation. Imports the generated client lazily."""

    async def create(self, params: dict) -> dict:
        from db.client import get_db

        db = await get_db()
        record = await db.strategy.create(data=self._encode(params))
        return self._to_dict(record)

    async def get(self, strategy_id: str) -> dict | None:
        from db.client import get_db

        db = await get_db()
        record = await db.strategy.find_unique(where={"id": strategy_id})
        return self._to_dict(record) if record is not None else None

    async def list(self) -> list[dict]:
        from db.client import get_db

        db = await get_db()
        records = await db.strategy.find_many()
        return _sorted([self._to_dict(r) for r in records])

    async def update(self, strategy_id: str, data: dict) -> dict | None:
        from db.client import get_db
        from prisma.errors import RecordNotFoundError

        db = await get_db()
        try:
            record = await db.strategy.update(
                where={"id": strategy_id}, data=self._encode(data)
            )
        except RecordNotFoundError:
            return None
        return self._to_dict(record) if record is not None else None

    async def delete(self, strategy_id: str) -> bool:
        from db.client import get_db
        from prisma.errors import RecordNotFoundError

        db = await get_db()
        try:
            await db.strategy.delete(where={"id": strategy_id})
        except RecordNotFoundError:
            return False
        return True

    async def recompute_ranks(self) -> None:
        """Rank strategies with a known net P&L (COMPLETED/STOPPED) best-first.

        Others get rank ``None``. Ties broken by ``created_at`` (older first) for a
        stable order.
        """
        from db.client import get_db

        db = await get_db()
        records = await db.strategy.find_many()
        ranked = sorted(
            [r for r in records if r.net_pnl is not None],
            key=lambda r: (-r.net_pnl, str(r.created_at)),
        )
        ranked_ids = {r.id for r in ranked}
        for i, r in enumerate(ranked, start=1):
            if r.rank != i:
                await db.strategy.update(where={"id": r.id}, data={"rank": i})
        for r in records:
            if r.id not in ranked_ids and r.rank is not None:
                await db.strategy.update(where={"id": r.id}, data={"rank": None})

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
            "name": r.name,
            "description": r.description,
            "status": _enum_value(r.status),
            "scan_window_days": r.scan_window_days,
            "trade_window_days": r.trade_window_days,
            "zscore_window": r.zscore_window,
            "entry_threshold": r.entry_threshold,
            "exit_threshold": r.exit_threshold,
            "stop_threshold": r.stop_threshold,
            "pvalue_max": r.pvalue_max,
            "max_half_life_h": r.max_half_life_h,
            "start_time": _iso(r.start_time),
            "end_time": _iso(r.end_time),
            "starting_capital": r.starting_capital,
            "usd_per_trade": r.usd_per_trade,
            "max_active_pairs": r.max_active_pairs,
            "slippage_pct": r.slippage_pct,
            "taker_fee_pct": r.taker_fee_pct,
            "funding_freq_h": r.funding_freq_h,
            "total_windows": r.total_windows,
            "processed_windows": r.processed_windows,
            "progress": r.progress,
            "current_capital": r.current_capital,
            "final_capital": r.final_capital,
            "net_pnl": r.net_pnl,
            "total_trades": r.total_trades,
            "win_rate": r.win_rate,
            "rank": r.rank,
            "equity_curve": r.equity_curve,
            "per_window": r.per_window,
            "per_pair_pnl": r.per_pair_pnl,
            "exit_reasons": r.exit_reasons,
            "report_md": r.report_md,
            "error": r.error,
            "created_at": _iso(r.created_at),
            "updated_at": _iso(r.updated_at),
            "completed_at": _iso(r.completed_at),
        }


def _sorted(rows: list[dict]) -> list[dict]:
    """Ranked rows first (best net P&L), then unranked newest-first."""
    ranked = sorted((r for r in rows if r.get("rank")), key=lambda r: r["rank"])
    unranked = sorted(
        (r for r in rows if not r.get("rank")),
        key=lambda r: r.get("created_at") or "",
        reverse=True,
    )
    return ranked + unranked


_repo: PrismaStrategyRepository | None = None


def get_strategy_repository() -> PrismaStrategyRepository:
    """Return the process-wide strategy repository singleton."""
    global _repo
    if _repo is None:
        _repo = PrismaStrategyRepository()
    return _repo
