"""
Persistence for manual trades (PRD F4) — a thin Prisma seam.

Mirrors ``db/scan_repository.py``: the router depends on this interface, tests
inject an in-memory fake (no Prisma / no generated client), and the process uses
:class:`PrismaManualTradeRepository` via :func:`get_manual_trade_repository`.
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
    """Prisma enums round-trip as str-like; normalise to the plain value."""
    return getattr(value, "value", value)


class PrismaManualTradeRepository:
    """Prisma-backed implementation. Imports the generated client lazily."""

    async def create(self, data: dict) -> dict:
        from db.client import get_db

        db = await get_db()
        record = await db.manualtrade.create(data=data)
        return self._to_dict(record)

    async def list(
        self, *, exchange: str, mode: str, data_source: str | None = None
    ) -> list[dict]:
        from db.client import get_db

        db = await get_db()
        where: dict = {"exchange": exchange, "mode": mode}
        if data_source is not None:
            where["data_source"] = data_source
        records = await db.manualtrade.find_many(
            where=where,
            order=[{"recorded_at": "desc"}],
        )
        return [self._to_dict(r) for r in records]

    async def get(self, trade_id: str) -> dict | None:
        from db.client import get_db

        db = await get_db()
        record = await db.manualtrade.find_unique(where={"id": trade_id})
        return self._to_dict(record) if record is not None else None

    async def get_latest_for_pair(
        self,
        *,
        exchange: str,
        mode: str,
        base_market: str,
        quote_market: str,
        data_source: str | None = None,
    ) -> dict | None:
        """Most recent recorded trade for one pair (newest first), or None.

        Lets the chart endpoint reuse a recorded trade's stored β/half-life when
        the pair has rolled out of the latest scan, so a recorded entry's chart
        keeps rendering for the life of the trade (issue #137).
        """
        from db.client import get_db

        db = await get_db()
        where: dict = {
            "exchange": exchange,
            "mode": mode,
            "base_market": base_market,
            "quote_market": quote_market,
        }
        if data_source is not None:
            where["data_source"] = data_source
        record = await db.manualtrade.find_first(
            where=where, order=[{"recorded_at": "desc"}]
        )
        return self._to_dict(record) if record is not None else None

    async def close(
        self,
        trade_id: str,
        *,
        exit_price_leg1: float,
        exit_price_leg2: float,
        pnl: float,
        closed_at: datetime,
        exit_ref_price_leg1: float | None = None,
        exit_ref_price_leg2: float | None = None,
    ) -> dict | None:
        """Mark a trade CLOSED with its exit prices and realised P&L.

        ``exit_ref_price_leg*`` are the server-captured REFERENCE prices at close
        time; paired with the operator's actual ``exit_price_leg*`` fills they
        make exit slippage measurable. Omitted (``None``) when the reference
        fetch fails — closing must never be blocked by a price lookup.

        Returns the updated row, or ``None`` if the id does not exist.
        """
        from db.client import get_db
        from prisma.errors import RecordNotFoundError

        db = await get_db()
        data: dict = {
            "status": "CLOSED",
            "exit_price_leg1": exit_price_leg1,
            "exit_price_leg2": exit_price_leg2,
            "pnl": pnl,
            "closed_at": closed_at,
        }
        # Only write the references when we actually have them, so a failed
        # price fetch leaves the columns NULL rather than storing a bogus 0.
        if exit_ref_price_leg1 is not None:
            data["exit_ref_price_leg1"] = exit_ref_price_leg1
        if exit_ref_price_leg2 is not None:
            data["exit_ref_price_leg2"] = exit_ref_price_leg2
        try:
            record = await db.manualtrade.update(where={"id": trade_id}, data=data)
        except RecordNotFoundError:
            return None
        # prisma-client-py returns None from update() when no row matched.
        return self._to_dict(record) if record is not None else None

    async def delete(self, trade_id: str) -> bool:
        """Hard-delete a manual trade (issue #55).

        Returns ``True`` if a row was removed, ``False`` if the id did not exist.
        """
        from db.client import get_db
        from prisma.errors import RecordNotFoundError

        db = await get_db()
        try:
            record = await db.manualtrade.delete(where={"id": trade_id})
        except RecordNotFoundError:
            return False
        # prisma-client-py returns None from delete() when no row matched.
        return record is not None

    @staticmethod
    def _to_dict(r) -> dict:
        return {
            "id": r.id,
            "exchange": _enum_value(r.exchange),
            "mode": _enum_value(r.mode),
            "data_source": r.data_source,
            "base_market": r.base_market,
            "quote_market": r.quote_market,
            "hedge_ratio": r.hedge_ratio,
            "half_life": r.half_life,
            "p_value": r.p_value,
            "z_score": r.z_score,
            "spread_value": r.spread_value,
            "entry_price_leg1": r.entry_price_leg1,
            "entry_price_leg2": r.entry_price_leg2,
            "capital_leg1_usd": r.capital_leg1_usd,
            "capital_leg2_usd": r.capital_leg2_usd,
            "recorded_at": _iso(r.recorded_at),
            "status": _enum_value(r.status),
            "closed_at": _iso(r.closed_at),
            "exit_price_leg1": r.exit_price_leg1,
            "exit_price_leg2": r.exit_price_leg2,
            "pnl": r.pnl,
            # Realised-execution capture (slippage measurement). getattr keeps
            # in-memory test fakes and any pre-migration row shape working.
            "fill_price_leg1": getattr(r, "fill_price_leg1", None),
            "fill_price_leg2": getattr(r, "fill_price_leg2", None),
            "exit_ref_price_leg1": getattr(r, "exit_ref_price_leg1", None),
            "exit_ref_price_leg2": getattr(r, "exit_ref_price_leg2", None),
        }


_repo: PrismaManualTradeRepository | None = None


def get_manual_trade_repository() -> PrismaManualTradeRepository:
    """Return the process-wide manual-trade repository singleton."""
    global _repo
    if _repo is None:
        _repo = PrismaManualTradeRepository()
    return _repo
