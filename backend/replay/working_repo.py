"""
In-memory working ledger for a fast-forward replay.

``simulation.run_tick`` writes the session/positions/trades it mutates through a
small repository interface. The real-time sim uses the Prisma-backed
``PrismaSimRepository`` so a session survives a restart; a fast-forward replay is
a *batch* job — it walks thousands of historical bars in one task and persists
only the final aggregates (``SavedFFSimulation``). Forcing every intermediate
open/close through Postgres would be thousands of writes for no durability
benefit, so the replay drives ``run_tick`` against this in-memory ledger instead.

It implements exactly the methods ``run_tick`` (and the engine's close path) call,
and mirrors ``PrismaSimRepository``'s serialisation contract: datetimes are
returned as ISO strings (the engine's age clock parses ``entry_time`` with
``datetime.fromisoformat``), so the same tick core runs unchanged.
"""

from __future__ import annotations

from datetime import datetime


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _ser(row: dict, keys) -> dict:
    out = dict(row)
    for k in keys:
        out[k] = _iso(out.get(k))
    return out


class WorkingSimRepository:
    """Process-local stand-in for ``PrismaSimRepository`` during one replay."""

    def __init__(self, session: dict) -> None:
        self._session = dict(session)
        self.positions: dict[str, dict] = {}
        self.trades: list[dict] = []
        self._seq = 0

    @property
    def session_id(self) -> str:
        return self._session["id"]

    # ── session ──────────────────────────────────────────────────────────────
    async def get_session(self, session_id: str) -> dict | None:
        return dict(self._session) if self._session["id"] == session_id else None

    async def update_session(self, session_id: str, data: dict) -> dict | None:
        if self._session["id"] != session_id:
            return None
        self._session.update(_ser(data, ("last_tick_at", "stopped_at")))
        return dict(self._session)

    # ── positions ────────────────────────────────────────────────────────────
    async def create_position(self, data: dict) -> dict:
        self._seq += 1
        pid = f"p_{self._seq}"
        row = _ser(data, ("entry_time",))
        row["id"] = pid
        row.setdefault("status", "OPEN")
        row.setdefault("funding_pnl", 0.0)
        self.positions[pid] = row
        return dict(row)

    async def get_open_positions(self, session_id: str) -> list[dict]:
        rows = [r for r in self.positions.values() if r["status"] == "OPEN"]
        return [dict(r) for r in sorted(rows, key=lambda r: r["entry_time"])]

    async def update_position(self, position_id: str, data: dict) -> dict | None:
        row = self.positions.get(position_id)
        if row is None:
            return None
        row.update(data)
        return dict(row)

    async def close_position(self, position_id: str) -> dict | None:
        return await self.update_position(position_id, {"status": "CLOSED"})

    # ── trades ───────────────────────────────────────────────────────────────
    async def create_trade(self, data: dict) -> dict:
        self._seq += 1
        row = _ser(data, ("entry_time", "exit_time"))
        row["id"] = f"t_{self._seq}"
        self.trades.append(row)
        return dict(row)

    async def list_trades(self, session_id: str) -> list[dict]:
        return [dict(r) for r in self.trades]
