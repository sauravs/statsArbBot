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
from datetime import datetime

from db.serde import enum_value as _enum_value
from db.serde import iso as _iso

logger = logging.getLogger(__name__)

# JSON result columns — wrapped in prisma.Json on write, returned parsed on read.
_JSON_FIELDS = ("equity_curve", "per_window", "per_pair_pnl", "exit_reasons")

# Per-trade columns copied from an engine trade record into a BacktestTrade row.
_TRADE_FIELDS = (
    "base_market", "quote_market", "direction", "hold_hours", "entry_z", "exit_z",
    "entry_base_px", "entry_quote_px", "exit_base_px", "exit_quote_px",
    "hedge_ratio", "intercept", "half_life",
    "exit_reason", "notional_usd", "gross_pnl", "fee_cost", "funding_pnl", "net_pnl",
)


def _dt(value):
    """Coerce an ISO-string (or datetime) timestamp to a datetime for Prisma."""
    return datetime.fromisoformat(value) if isinstance(value, str) else value


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

        import config

        db = await get_db()
        # Scope to the active market-data source so demo strategies stay in demo and
        # live in live (issue #98), like the manual-trades list.
        records = await db.strategy.find_many(
            where={"data_source": config.SCAN_DATA_SOURCE}
        )
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
        # Rank within each data source independently (issue #98) — demo and live are
        # incomparable worlds, so a demo run shouldn't out/under-rank a live one.
        sources = {r.data_source for r in records}
        ranked_ids: set[str] = set()
        for source in sources:
            group = [r for r in records if r.data_source == source]
            ranked = sorted(
                [r for r in group if r.net_pnl is not None],
                key=lambda r: (-r.net_pnl, str(r.created_at)),
            )
            for i, r in enumerate(ranked, start=1):
                ranked_ids.add(r.id)
                if r.rank != i:
                    await db.strategy.update(where={"id": r.id}, data={"rank": i})
        for r in records:
            if r.id not in ranked_ids and r.rank is not None:
                await db.strategy.update(where={"id": r.id}, data={"rank": None})

    # ── per-trade blotter (issue #162) ─────────────────────────────────────────

    async def create_backtest_trades(
        self, strategy_id: str, window_index: int, trades: list[dict]
    ) -> int:
        """Batch-insert one window's closed trades, stamped with its window index."""
        if not trades:
            return 0
        from db.client import get_db

        db = await get_db()
        rows = [
            {
                "strategy_id": strategy_id,
                "window_index": window_index,
                "exchange": t["exchange"],
                "entry_time": _dt(t["entry_time"]),
                "exit_time": _dt(t["exit_time"]),
                **{k: t.get(k) for k in _TRADE_FIELDS},
            }
            for t in trades
        ]
        await db.backtesttrade.create_many(data=rows)
        return len(rows)

    async def list_backtest_trades(
        self, strategy_id: str, *, window_index: int | None = None,
        limit: int = 50, offset: int = 0, outcome: str | None = None,
    ) -> dict:
        """Paginated trades for a strategy, optionally scoped to one window and/or an
        ``outcome`` filter. ``losing_tp`` = take-profit exits that still closed at a
        net loss (reason=TAKE_PROFIT AND net_pnl<0) — filtered in the DB so the total
        and pagination stay correct across the whole result set."""
        from db.client import get_db

        db = await get_db()
        where: dict = {"strategy_id": strategy_id}
        if window_index is not None:
            where["window_index"] = window_index
        if outcome == "losing_tp":
            where["exit_reason"] = "TAKE_PROFIT"
            where["net_pnl"] = {"lt": 0}
        total = await db.backtesttrade.count(where=where)
        records = await db.backtesttrade.find_many(
            where=where,
            order=[{"entry_time": "asc"}, {"id": "asc"}],
            take=limit,
            skip=offset,
        )
        return {"trades": [self._trade_to_dict(r) for r in records], "total": total}

    async def get_backtest_trade(self, trade_id: str) -> dict | None:
        """One persisted trade by id (drives the per-trade chart, issue #166)."""
        from db.client import get_db

        db = await get_db()
        record = await db.backtesttrade.find_unique(where={"id": trade_id})
        return self._trade_to_dict(record) if record is not None else None

    async def delete_backtest_trades(self, strategy_id: str) -> None:
        """Drop all persisted trades for a strategy (fresh re-run clears priors)."""
        from db.client import get_db

        db = await get_db()
        await db.backtesttrade.delete_many(where={"strategy_id": strategy_id})

    @staticmethod
    def _trade_to_dict(r) -> dict:
        return {
            "id": r.id,
            "strategy_id": r.strategy_id,
            "window_index": r.window_index,
            "exchange": _enum_value(r.exchange),
            "base_market": r.base_market,
            "quote_market": r.quote_market,
            "direction": r.direction,
            "entry_time": _iso(r.entry_time),
            "exit_time": _iso(r.exit_time),
            "hold_hours": r.hold_hours,
            "entry_z": r.entry_z,
            "exit_z": r.exit_z,
            "entry_base_px": r.entry_base_px,
            "entry_quote_px": r.entry_quote_px,
            "exit_base_px": r.exit_base_px,
            "exit_quote_px": r.exit_quote_px,
            "hedge_ratio": r.hedge_ratio,
            "intercept": r.intercept,
            "half_life": r.half_life,
            "exit_reason": r.exit_reason,
            "notional_usd": r.notional_usd,
            "gross_pnl": r.gross_pnl,
            "fee_cost": r.fee_cost,
            "funding_pnl": r.funding_pnl,
            "net_pnl": r.net_pnl,
        }

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
            "data_source": r.data_source,
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
