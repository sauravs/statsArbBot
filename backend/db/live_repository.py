"""
Persistence for live-bot sessions and trades (PRD F5.3) — a thin Prisma seam.

DB-backed live state (ADR-0003): the prototype tracked open trades in a flat
``bot_agents.json`` that raced and drifted; here every session and trade is a row,
so the exit manager reconciles against the DB and a restart restores state.

Mirrors ``db/scan_repository.py`` and ``manual/repository.py``: the engine/router
depend on this class, tests inject ``FakeLiveRepository`` (no Prisma / no client),
and the process uses :class:`PrismaLiveRepository` via :func:`get_live_repository`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _enum_value(value) -> str:
    return getattr(value, "value", value)


class PrismaLiveRepository:
    """Prisma-backed implementation. Imports the generated client lazily."""

    # ── sessions ──────────────────────────────────────────────────────────────

    async def get_active_session(self, *, exchange: str, mode: str) -> dict | None:
        from db.client import get_db

        db = await get_db()
        record = await db.livesession.find_first(
            where={"exchange": exchange, "mode": mode, "active": True},
            order=[{"started_at": "desc"}],
        )
        return self._session_to_dict(record) if record is not None else None

    async def start_session(self, *, exchange: str, mode: str) -> dict:
        """Return the active session for (exchange, mode), creating one if none."""
        existing = await self.get_active_session(exchange=exchange, mode=mode)
        if existing is not None:
            return existing
        from db.client import get_db

        db = await get_db()
        record = await db.livesession.create(
            data={"exchange": exchange, "mode": mode, "active": True}
        )
        return self._session_to_dict(record)

    async def stop_session(self, *, exchange: str, mode: str) -> int:
        """Deactivate all active sessions for (exchange, mode). Returns the count."""
        from db.client import get_db

        db = await get_db()
        return await db.livesession.update_many(
            where={"exchange": exchange, "mode": mode, "active": True},
            data={"active": False, "stopped_at": datetime.now(timezone.utc)},
        )

    # ── trades ────────────────────────────────────────────────────────────────

    async def create_trade(self, data: dict) -> dict:
        from db.client import get_db

        db = await get_db()
        record = await db.livetrade.create(data=data)
        return self._trade_to_dict(record)

    async def list_trades(
        self, *, exchange: str, mode: str, status: str | None = None
    ) -> list[dict]:
        from db.client import get_db

        db = await get_db()
        where: dict = {"exchange": exchange, "mode": mode}
        if status is not None:
            where["status"] = status
        records = await db.livetrade.find_many(
            where=where, order=[{"opened_at": "desc"}]
        )
        return [self._trade_to_dict(r) for r in records]

    async def get_open_trades(self, *, exchange: str, mode: str) -> list[dict]:
        return await self.list_trades(exchange=exchange, mode=mode, status="OPEN")

    async def close_trade(
        self,
        trade_id: str,
        *,
        exit_price_leg1: float,
        exit_price_leg2: float,
        exit_z_score: float | None,
        exit_reason: str,
        pnl: float,
        closed_at: datetime,
    ) -> dict | None:
        from db.client import get_db
        from prisma.errors import RecordNotFoundError

        db = await get_db()
        try:
            record = await db.livetrade.update(
                where={"id": trade_id},
                data={
                    "status": "CLOSED",
                    "exit_price_leg1": exit_price_leg1,
                    "exit_price_leg2": exit_price_leg2,
                    "exit_z_score": exit_z_score,
                    "exit_reason": exit_reason,
                    "pnl": pnl,
                    "closed_at": closed_at,
                },
            )
        except RecordNotFoundError:
            return None
        return self._trade_to_dict(record) if record is not None else None

    async def mark_error(self, trade_id: str, *, error: str) -> dict | None:
        from db.client import get_db
        from prisma.errors import RecordNotFoundError

        db = await get_db()
        try:
            record = await db.livetrade.update(
                where={"id": trade_id}, data={"status": "ERROR", "error": error}
            )
        except RecordNotFoundError:
            return None
        return self._trade_to_dict(record) if record is not None else None

    # ── serialisation ─────────────────────────────────────────────────────────

    @staticmethod
    def _session_to_dict(r) -> dict:
        return {
            "id": r.id,
            "exchange": _enum_value(r.exchange),
            "mode": _enum_value(r.mode),
            "active": r.active,
            "started_at": _iso(r.started_at),
            "stopped_at": _iso(r.stopped_at),
        }

    @staticmethod
    def _trade_to_dict(r) -> dict:
        return {
            "id": r.id,
            "session_id": r.session_id,
            "exchange": _enum_value(r.exchange),
            "mode": _enum_value(r.mode),
            "base_market": r.base_market,
            "quote_market": r.quote_market,
            "base_side": r.base_side,
            "quote_side": r.quote_side,
            "base_size": r.base_size,
            "quote_size": r.quote_size,
            "hedge_ratio": r.hedge_ratio,
            "half_life": r.half_life,
            "entry_z_score": r.entry_z_score,
            "entry_price_leg1": r.entry_price_leg1,
            "entry_price_leg2": r.entry_price_leg2,
            "status": _enum_value(r.status),
            "opened_at": _iso(r.opened_at),
            "exit_z_score": r.exit_z_score,
            "exit_price_leg1": r.exit_price_leg1,
            "exit_price_leg2": r.exit_price_leg2,
            "exit_reason": r.exit_reason,
            "pnl": r.pnl,
            "closed_at": _iso(r.closed_at),
            "error": r.error,
        }


_repo: PrismaLiveRepository | None = None


def get_live_repository() -> PrismaLiveRepository:
    """Return the process-wide live-trading repository singleton."""
    global _repo
    if _repo is None:
        _repo = PrismaLiveRepository()
    return _repo
