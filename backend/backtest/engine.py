"""
Walk-forward backtest engine (PRD F8) — sweeps sliding scan/trade windows over the
historical cache, driving the SAME stateless tick core the live bot / real-time
sim / fast-forward replay use (``simulation.run_tick``), one source of truth
(PLAN §1).

Per window:
  1. **Scan** the formation window with ``statcore`` (offloaded to a worker thread
     — ``statsmodels.coint`` over 90 days is CPU-bound, like the live scan).
  2. **Trade** the following test window: align the selected pairs' historical
     closes and walk a cursor hour-by-hour through ``run_tick`` on out-of-sample
     data, carrying capital forward.
  3. **Force-close** every open position at the window boundary (the next window
     re-scans and may pick different pairs / hedge ratios), realising P&L.

Each window boundary persists partial results (the resume cursor
``processed_windows`` + carried ``current_capital`` + accumulated aggregates), so a
PAUSED or STOPPED run resumes from the next unprocessed window without recomputing
finished windows (F8.2). On completion the engine generates the markdown report and
recomputes the cross-strategy rank by net P&L (F8.3).

**Orchestration choice (ADR-0008):** the PRD calls for "subprocess orchestration".
We instead run the sweep as a FastAPI background task and offload the CPU-bound
per-window scan via ``asyncio.to_thread`` — the codebase's established CPU-offload
idiom (the live scan in ``scan.orchestrator``, the FF replay in ``replay.engine``).
It delivers the same progress / pause / stop / resume semantics (in-memory control
flags checked at each window boundary + DB-persisted partial state) without the IPC
and process-management fragility of a subprocess.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import config
from backtest.report import build_report
from backtest.scan_window import scan_window_pairs
from backtest.windows import Window, build_windows
from db.backtest_repository import get_strategy_repository
from replay.candle_source import demo_window, make_candle_source
from replay.engine import _equity_at
from replay.historical_feed import (
    FundingTable,
    align_pairs,
    replay_timeline,
    snapshots_at,
)
from replay.working_repo import WorkingSimRepository
from simulation.engine import _close_position, run_tick
from simulation.feed import PairTick

logger = logging.getLogger(__name__)

# Cap on persisted equity-curve points (downsampled across all windows).
_MAX_CURVE_POINTS = 500


class StrategyNotFound(Exception):
    """Raised when a control / read targets an unknown strategy id."""


class BacktestEngine:
    """Orchestrates walk-forward backtests; one ``Strategy`` row per run."""

    def __init__(self) -> None:
        # strategy_id → "pause" | "stop" — checked at each window boundary.
        self._control: dict[str, str] = {}

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def create(self, params: dict) -> dict:
        return await get_strategy_repository().create(params)

    async def get(self, strategy_id: str) -> dict | None:
        return await get_strategy_repository().get(strategy_id)

    async def list(self) -> list[dict]:
        return await get_strategy_repository().list()

    async def update(self, strategy_id: str, data: dict) -> dict | None:
        return await get_strategy_repository().update(strategy_id, data)

    async def delete(self, strategy_id: str) -> bool:
        repo = get_strategy_repository()
        ok = await repo.delete(strategy_id)
        if ok:
            await repo.recompute_ranks()
        return ok

    # ── control ───────────────────────────────────────────────────────────────

    async def request_pause(self, strategy_id: str) -> dict:
        return await self._request(strategy_id, "pause")

    async def request_stop(self, strategy_id: str) -> dict:
        return await self._request(strategy_id, "stop")

    async def _request(self, strategy_id: str, action: str) -> dict:
        repo = get_strategy_repository()
        row = await repo.get(strategy_id)
        if row is None:
            raise StrategyNotFound(strategy_id)
        # Only a RUNNING sweep can be paused/stopped from inside the loop; the loop
        # checks the flag at the next window boundary.
        if row["status"] == "RUNNING":
            self._control[strategy_id] = action
        return row

    # ── the sweep ─────────────────────────────────────────────────────────────

    async def run(self, strategy_id: str) -> dict | None:
        """Run (or resume) the whole walk-forward sweep for ``strategy_id``."""
        repo = get_strategy_repository()
        try:
            row = await repo.get(strategy_id)
            if row is None:
                raise StrategyNotFound(strategy_id)
            if row["status"] == "RUNNING":
                return row  # already sweeping — don't double-launch
            return await self._sweep(repo, row)
        except Exception as exc:  # a batch failure must not crash the worker
            logger.exception("backtest %s failed", strategy_id)
            await repo.update(
                strategy_id,
                {
                    "status": "FAILED",
                    "error": str(exc)[:500],
                    "completed_at": datetime.now(timezone.utc),
                },
            )
            return None
        finally:
            self._control.pop(strategy_id, None)

    async def _sweep(self, repo, row: dict) -> dict:
        strategy_id = row["id"]
        exchange = row["exchange"]
        zwindow = int(row["zscore_window"])

        start, end = _resolve_span(row)
        windows = build_windows(
            start,
            end,
            scan_days=int(row["scan_window_days"]),
            trade_days=int(row["trade_window_days"]),
        )
        if not windows:
            raise RuntimeError(
                "History span is too short for one scan + trade window — "
                "widen the date range or shorten the windows."
            )
        total = len(windows)

        # Resume from a PAUSED run's cursor; otherwise start fresh.
        resuming = row["status"] == "PAUSED" and row.get("processed_windows", 0) > 0
        if resuming:
            cursor_idx = int(row["processed_windows"])
            capital = row.get("current_capital") or row["starting_capital"]
            acc = _Accumulator.from_row(row)
        else:
            cursor_idx = 0
            capital = row["starting_capital"]
            acc = _Accumulator()

        init: dict = {
            "status": "RUNNING", "total_windows": total,
            "error": None, "completed_at": None,
        }
        if not resuming:
            # Clear any stale result from a previous run before re-sweeping. JSON
            # columns reset to empty containers, not None — prisma-client-py rejects
            # a bare None for a nullable Json field on update.
            init.update(
                {
                    "processed_windows": 0, "progress": 0.0,
                    "current_capital": capital,
                    "final_capital": None, "net_pnl": None, "total_trades": 0,
                    "win_rate": None, "rank": None,
                    "equity_curve": [], "per_window": [],
                    "per_pair_pnl": {}, "exit_reasons": {}, "report_md": None,
                }
            )
        await repo.update(strategy_id, init)

        # One candle/funding fetch for the whole run (every leg of every window).
        markets = await _universe(exchange)
        load_start = windows[cursor_idx].scan_start if cursor_idx < total else start
        candles_by_market, funding_by_market = await _load_history(
            exchange, markets, load_start, windows[-1].trade_end
        )
        funding = FundingTable(funding_by_market)

        # Budget equity points across the remaining windows.
        remaining = max(1, total - cursor_idx)
        pts_per_window = max(2, _MAX_CURVE_POINTS // remaining)

        session_base = _session_params(row)
        terminal = None
        for w in windows[cursor_idx:]:
            action = self._control.get(strategy_id)
            if action == "stop":
                terminal = "STOPPED"
                break
            if action == "pause":
                terminal = "PAUSED"
                break

            capital = await self._run_window(
                repo, strategy_id, w, candles_by_market, funding, zwindow,
                row, session_base, capital, acc, pts_per_window,
            )
            acc.processed = w.index + 1
            await repo.update(
                strategy_id,
                {
                    "processed_windows": acc.processed,
                    "progress": round(acc.processed / total, 4),
                    "current_capital": round(capital, 6),
                    **acc.snapshot(),
                },
            )

        return await self._finalise(
            repo, strategy_id, row, capital, acc, total, terminal
        )

    async def _run_window(
        self, repo, strategy_id, w: Window, candles_by_market, funding, zwindow,
        row, session_base, capital, acc, pts_per_window,
    ) -> float:
        """Scan + trade one window; mutate ``acc``; return the carried capital."""
        # 1. Scan the formation window (CPU-bound → worker thread).
        min_rows = zwindow + 10
        pairs = await asyncio.to_thread(
            scan_window_pairs,
            candles_by_market, w.scan_start, w.scan_end,
            pvalue_max=row["pvalue_max"],
            max_half_life=row["max_half_life_h"],
            min_rows=min_rows,
        )

        window_trades = 0
        window_pnl = 0.0
        if pairs:
            aligned = align_pairs(pairs, candles_by_market)
            aligned_by_pair = {(ap.base_market, ap.quote_market): ap for ap in aligned}
            timeline = replay_timeline(aligned, start=w.trade_start, end=w.trade_end)
            if timeline:
                session = {
                    **session_base,
                    "id": strategy_id,
                    "current_capital": capital,
                    "tick_count": 0,
                    "last_tick_at": None,
                }
                wrepo = WorkingSimRepository(session)
                markets = {ap.base_market for ap in aligned} | {
                    ap.quote_market for ap in aligned
                }
                sample_every = max(1, len(timeline) // pts_per_window)
                for i, cur in enumerate(timeline):
                    snaps = snapshots_at(aligned, cur, window=zwindow)
                    rates = funding.rates_at(cur, markets) if not funding.empty else {}
                    cur_session = await wrepo.get_session(strategy_id)
                    await run_tick(
                        wrepo, cur_session, snaps,
                        funding_rates=rates or None, now=cur,
                    )
                    if i % sample_every == 0:
                        equity = await _equity_at(wrepo, aligned_by_pair, cur)
                        acc.add_equity(cur, equity)
                # Force-close at the final traded bar (END_OF_WINDOW).
                final_cur = timeline[-1]
                capital = await _close_window(
                    wrepo, aligned_by_pair, final_cur, zwindow
                )
                trades = await wrepo.list_trades(strategy_id)
                window_trades = len(trades)
                window_pnl = round(sum(t["net_pnl"] for t in trades), 6)
                acc.merge_trades(trades)
                acc.add_equity(final_cur, capital)

        acc.add_window(
            {
                "index": w.index,
                "scan_start": w.scan_start.isoformat(),
                "scan_end": w.scan_end.isoformat(),
                "trade_start": w.trade_start.isoformat(),
                "trade_end": w.trade_end.isoformat(),
                "pairs": len(pairs),
                "trades": window_trades,
                "net_pnl": window_pnl,
            }
        )
        return capital

    async def _finalise(
        self, repo, strategy_id, row, capital, acc, total, terminal
    ) -> dict:
        if terminal == "PAUSED":
            status = "PAUSED"
        elif terminal == "STOPPED":
            status = "STOPPED"
        else:
            status = "COMPLETED"

        data: dict = {
            "status": status,
            "current_capital": round(capital, 6),
            "processed_windows": acc.processed,
            "progress": round(acc.processed / total, 4) if total else 0.0,
            **acc.snapshot(),
        }
        if status == "PAUSED":
            # A paused run keeps RUNNING-style nullable results; persist partials only.
            updated = await repo.update(strategy_id, data)
            logger.info(
                "backtest %s paused at window %d/%d", strategy_id, acc.processed, total
            )
            return updated

        # COMPLETED or STOPPED — book the final result + report, then rank.
        net_pnl = round(capital - row["starting_capital"], 6)
        win_rate = (acc.wins / acc.trades) if acc.trades else None
        data.update(
            {
                "final_capital": round(capital, 6),
                "net_pnl": net_pnl,
                "total_trades": acc.trades,
                "win_rate": win_rate,
                "completed_at": datetime.now(timezone.utc),
            }
        )
        report_row = {**row, **data}
        data["report_md"] = build_report(report_row)
        await repo.update(strategy_id, data)
        await repo.recompute_ranks()
        logger.info(
            "backtest %s %s: %d trades, net %.2f over %d/%d windows",
            strategy_id, status.lower(), acc.trades, net_pnl, acc.processed, total,
        )
        return await repo.get(strategy_id)


# ── per-run accumulator ──────────────────────────────────────────────────────


class _Accumulator:
    """Cross-window aggregates, serialisable to/from the Strategy row for resume."""

    def __init__(self) -> None:
        self.equity_curve: list[dict] = []
        self.per_window: list[dict] = []
        self.per_pair: dict[str, dict] = {}
        self.exit_reasons: dict[str, int] = {}
        self.trades = 0
        self.wins = 0
        self.processed = 0

    @classmethod
    def from_row(cls, row: dict) -> "_Accumulator":
        acc = cls()
        acc.equity_curve = list(row.get("equity_curve") or [])
        acc.per_window = list(row.get("per_window") or [])
        acc.per_pair = dict(row.get("per_pair_pnl") or {})
        acc.exit_reasons = dict(row.get("exit_reasons") or {})
        acc.trades = int(row.get("total_trades") or 0)
        acc.wins = sum(b.get("wins", 0) for b in acc.per_pair.values())
        acc.processed = int(row.get("processed_windows") or 0)
        return acc

    def add_equity(self, cursor: datetime, equity: float) -> None:
        self.equity_curve.append(
            {"t": int(cursor.timestamp()), "equity": round(equity, 2)}
        )

    def add_window(self, summary: dict) -> None:
        self.per_window.append(summary)

    def merge_trades(self, trades: list[dict]) -> None:
        for t in trades:
            key = f"{t['base_market']}/{t['quote_market']}"
            bucket = self.per_pair.setdefault(
                key, {"net_pnl": 0.0, "trades": 0, "wins": 0}
            )
            bucket["net_pnl"] = round(bucket["net_pnl"] + t["net_pnl"], 6)
            bucket["trades"] += 1
            self.trades += 1
            if t["net_pnl"] > 0:
                bucket["wins"] += 1
                self.wins += 1
            self.exit_reasons[t["exit_reason"]] = (
                self.exit_reasons.get(t["exit_reason"], 0) + 1
            )

    def snapshot(self) -> dict:
        return {
            "equity_curve": list(self.equity_curve),
            "per_window": list(self.per_window),
            "per_pair_pnl": dict(self.per_pair),
            "exit_reasons": dict(self.exit_reasons),
            "total_trades": self.trades,
        }


# ── helpers ──────────────────────────────────────────────────────────────────


async def _close_window(
    wrepo: WorkingSimRepository, aligned_by_pair: dict, cursor: datetime, window: int
) -> float:
    """Force-close every open position at the final traded bar (END_OF_WINDOW).

    Closes at the bar's real close prices (the next window re-scans, so positions
    don't carry); funding/fees already accrued are realised. Returns the capital
    after closing.
    """
    open_positions = await wrepo.get_open_positions(wrepo.session_id)
    session = await wrepo.get_session(wrepo.session_id)
    capital = session["current_capital"]
    for pos in open_positions:
        ap = aligned_by_pair.get((pos["base_market"], pos["quote_market"]))
        prices = ap.price_at(cursor) if ap is not None else None
        synthetic = prices is None
        if synthetic:
            base_px, quote_px = pos["entry_base_px"], pos["entry_quote_px"]
            exit_z = None
        else:
            base_px, quote_px = prices
            tick = ap.tick_at(cursor, window=window)
            exit_z = tick.z_score if tick is not None else None
        snap = PairTick(
            base_market=pos["base_market"],
            quote_market=pos["quote_market"],
            hedge_ratio=pos["hedge_ratio"],
            half_life=pos["half_life"],
            base_price=base_px,
            quote_price=quote_px,
            z_score=exit_z if exit_z is not None else pos["entry_z"],
            spread_value=0.0,
        )
        capital += await _close_position(
            wrepo, session, pos, snap, "END_OF_WINDOW",
            exit_z=exit_z, now=cursor,
            slippage_pct=0.0 if synthetic else None,
            taker_fee_pct=0.0 if synthetic else None,
        )
    await wrepo.update_session(session["id"], {"current_capital": capital})
    return capital


def _resolve_span(row: dict) -> tuple[datetime, datetime]:
    start, end = row.get("start_time"), row.get("end_time")
    if (start is None or end is None) and config.SCAN_DATA_SOURCE == "fake":
        d_start, d_end = demo_window()
        start = start or d_start
        end = end or d_end
    if start is None or end is None:
        raise RuntimeError("start_time and end_time are required.")
    return _aware(start), _aware(end)


def _session_params(row: dict) -> dict:
    return {
        "exchange": row["exchange"],
        "entry_threshold": row["entry_threshold"],
        "exit_threshold": row["exit_threshold"],
        "stop_threshold": row["stop_threshold"],
        "usd_per_trade": row["usd_per_trade"],
        "max_active_pairs": row.get("max_active_pairs"),
        "slippage_pct": row["slippage_pct"],
        "taker_fee_pct": row["taker_fee_pct"],
        "funding_freq_h": row["funding_freq_h"],
    }


async def _universe(exchange: str) -> list[str]:
    source = make_candle_source(exchange=exchange)
    return await source.available_markets()


async def _load_history(exchange, markets, start, end):
    source = make_candle_source(exchange=exchange)
    market_list = list(markets)
    candle_results, funding_results = await asyncio.gather(
        asyncio.gather(*(source.get_candles(m, start=start, end=end) for m in market_list)),
        asyncio.gather(*(source.get_funding(m, start=start, end=end) for m in market_list)),
    )
    return dict(zip(market_list, candle_results)), dict(zip(market_list, funding_results))


def _aware(value) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


_engine: BacktestEngine | None = None


def get_backtest_engine() -> BacktestEngine:
    """Return the process-wide backtest engine singleton."""
    global _engine
    if _engine is None:
        _engine = BacktestEngine()
    return _engine
