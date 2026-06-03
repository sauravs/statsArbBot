"""
Persistence for real-time simulation sessions, positions, and trades (PRD F6) —
a thin Prisma seam mirroring ``db/live_repository.py`` and ``db/scan_repository.py``.

DB-backed state (ADR-0003): the engine reads every tick's state from here, so a
session survives an API restart (the scheduler re-registers RUNNING sessions on
startup). Tests inject ``FakeSimRepository`` (no Prisma / no generated client);
the process uses :class:`PrismaSimRepository` via :func:`get_sim_repository`.
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


def _enum_value(value) -> str:
    return getattr(value, "value", value)


class PrismaSimRepository:
    """Prisma-backed implementation. Imports the generated client lazily."""

    # ── sessions ──────────────────────────────────────────────────────────────

    async def create_session(self, params: dict) -> dict:
        from db.client import get_db

        db = await get_db()
        data = dict(params)
        data.setdefault("current_capital", data.get("starting_capital"))
        record = await db.simsession.create(data=data)
        return self._session_to_dict(record)

    async def get_session(self, session_id: str) -> dict | None:
        from db.client import get_db

        db = await get_db()
        record = await db.simsession.find_unique(where={"id": session_id})
        return self._session_to_dict(record) if record is not None else None

    async def list_sessions(self) -> list[dict]:
        from db.client import get_db

        db = await get_db()
        records = await db.simsession.find_many(order=[{"created_at": "desc"}])
        # Attach realised P&L (Σ closed-trade net_pnl) per session in one grouped
        # query, so the list view shows true profit — NOT current − starting
        # capital, which also counts top-ups. One aggregate, not N+1.
        grouped = await db.simtrade.group_by(
            by=["session_id"], sum={"net_pnl": True}
        )
        pnl_by_session = {
            g["session_id"]: (g.get("_sum") or {}).get("net_pnl") or 0.0 for g in grouped
        }
        out = []
        for r in records:
            d = self._session_to_dict(r)
            d["realised_pnl"] = pnl_by_session.get(r.id, 0.0)
            out.append(d)
        return out

    async def list_running_sessions(self) -> list[dict]:
        """RUNNING sessions — re-registered with the scheduler on API startup."""
        from db.client import get_db

        db = await get_db()
        records = await db.simsession.find_many(where={"status": "RUNNING"})
        return [self._session_to_dict(r) for r in records]

    async def update_session(self, session_id: str, data: dict) -> dict | None:
        from db.client import get_db
        from prisma.errors import RecordNotFoundError

        db = await get_db()
        try:
            record = await db.simsession.update(where={"id": session_id}, data=data)
        except RecordNotFoundError:
            return None
        return self._session_to_dict(record) if record is not None else None

    # ── positions ─────────────────────────────────────────────────────────────

    async def create_position(self, data: dict) -> dict:
        from db.client import get_db

        db = await get_db()
        record = await db.simposition.create(data=data)
        return self._position_to_dict(record)

    async def get_open_positions(self, session_id: str) -> list[dict]:
        from db.client import get_db

        db = await get_db()
        records = await db.simposition.find_many(
            where={"session_id": session_id, "status": "OPEN"},
            order=[{"entry_time": "asc"}],
        )
        return [self._position_to_dict(r) for r in records]

    async def update_position(self, position_id: str, data: dict) -> dict | None:
        from db.client import get_db
        from prisma.errors import RecordNotFoundError

        db = await get_db()
        try:
            record = await db.simposition.update(where={"id": position_id}, data=data)
        except RecordNotFoundError:
            return None
        return self._position_to_dict(record) if record is not None else None

    async def close_position(self, position_id: str) -> dict | None:
        return await self.update_position(position_id, {"status": "CLOSED"})

    # ── trades ────────────────────────────────────────────────────────────────

    async def create_trade(self, data: dict) -> dict:
        from db.client import get_db

        db = await get_db()
        record = await db.simtrade.create(data=data)
        return self._trade_to_dict(record)

    async def list_trades(self, session_id: str) -> list[dict]:
        from db.client import get_db

        db = await get_db()
        records = await db.simtrade.find_many(
            where={"session_id": session_id}, order=[{"exit_time": "desc"}]
        )
        return [self._trade_to_dict(r) for r in records]

    # ── serialisation ─────────────────────────────────────────────────────────

    @staticmethod
    def _session_to_dict(r) -> dict:
        return {
            "id": r.id,
            "exchange": _enum_value(r.exchange),
            "mode": _enum_value(r.mode),
            "label": r.label,
            "status": _enum_value(r.status),
            "starting_capital": r.starting_capital,
            "current_capital": r.current_capital,
            "interval_seconds": r.interval_seconds,
            "zscore_window": r.zscore_window,
            "entry_threshold": r.entry_threshold,
            "exit_threshold": r.exit_threshold,
            "stop_threshold": r.stop_threshold,
            "usd_per_trade": r.usd_per_trade,
            "max_active_pairs": r.max_active_pairs,
            "slippage_pct": r.slippage_pct,
            "taker_fee_pct": r.taker_fee_pct,
            "funding_freq_h": r.funding_freq_h,
            "tick_count": r.tick_count,
            "last_tick_at": _iso(r.last_tick_at),
            "created_at": _iso(r.created_at),
            "stopped_at": _iso(r.stopped_at),
        }

    @staticmethod
    def _position_to_dict(r) -> dict:
        return {
            "id": r.id,
            "session_id": r.session_id,
            "exchange": _enum_value(r.exchange),
            "base_market": r.base_market,
            "quote_market": r.quote_market,
            "direction": r.direction,
            "base_size": r.base_size,
            "quote_size": r.quote_size,
            "hedge_ratio": r.hedge_ratio,
            "half_life": r.half_life,
            "entry_z": r.entry_z,
            "entry_base_px": r.entry_base_px,
            "entry_quote_px": r.entry_quote_px,
            "entry_time": _iso(r.entry_time),
            "fee_cost": r.fee_cost,
            "funding_pnl": r.funding_pnl,
            "status": _enum_value(r.status),
        }

    @staticmethod
    def _trade_to_dict(r) -> dict:
        return {
            "id": r.id,
            "session_id": r.session_id,
            "exchange": _enum_value(r.exchange),
            "base_market": r.base_market,
            "quote_market": r.quote_market,
            "direction": r.direction,
            "entry_time": _iso(r.entry_time),
            "exit_time": _iso(r.exit_time),
            "hold_hours": r.hold_hours,
            "entry_z": r.entry_z,
            "exit_z": r.exit_z,
            "exit_reason": r.exit_reason,
            "notional_usd": r.notional_usd,
            "gross_pnl": r.gross_pnl,
            "fee_cost": r.fee_cost,
            "funding_pnl": r.funding_pnl,
            "net_pnl": r.net_pnl,
        }


_repo: PrismaSimRepository | None = None


def get_sim_repository() -> PrismaSimRepository:
    """Return the process-wide simulation repository singleton."""
    global _repo
    if _repo is None:
        _repo = PrismaSimRepository()
    return _repo
