"""
Fast-forward replay engine (PRD F7) — replay historical OHLCV at N× speed through
the *same* stateless tick core the real-time sim uses.

A run is a batch job, not a long-lived ticking session: it loads the latest scan's
pairs, pulls their historical closes (+ funding) from the candle source over
[start, end], aligns each pair once, then walks a moving cursor hour-by-hour
calling :func:`simulation.engine.run_tick` with the bar's :class:`PairTick`
snapshots and per-bar funding rates. The intermediate positions/trades live in an
in-memory :class:`~replay.working_repo.WorkingSimRepository`; only the aggregates
(equity curve, per-pair P&L, exit-reason histogram) are persisted, to a single
``SavedFFSimulation`` row (F7.2).

Reusing ``run_tick`` verbatim means the replay's entry/exit/stop/time-stop rules,
cost model, margin guard, and no-reopen-after-stop behaviour are identical to live
and real-time-sim trading — one source of truth (PLAN §1). Funding accrual from
``FundingRateCache`` is exercised here, closing the replay half of issue #23.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import config
from db.ff_repository import get_ff_repository
from db.scan_repository import get_scan_repository
from replay.candle_source import make_candle_source
from replay.historical_feed import (
    FundingTable,
    align_pairs,
    replay_timeline,
    snapshots_at,
)
from replay.working_repo import WorkingSimRepository
from simulation.costs import compute_unrealized_pnl
from simulation.engine import _close_position, run_tick

logger = logging.getLogger(__name__)

# Cap on persisted equity-curve points: a long replay is thousands of bars, but a
# chart needs only ~hundreds — downsample so the JSON column stays small.
_MAX_CURVE_POINTS = 500
# Persist progress in ~5% steps (one DB write per step), not every bar.
_PROGRESS_STEPS = 20


class FFSimNotFound(Exception):
    """Raised when a control / read targets an unknown fast-forward run id."""


class FastForwardReplayEngine:
    """Orchestrates fast-forward replays; one row in ``SavedFFSimulation`` per run."""

    def __init__(self) -> None:
        self._cancelled: set[str] = set()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def create(self, params: dict) -> dict:
        return await get_ff_repository().create(params)

    async def get(self, ff_id: str) -> dict | None:
        return await get_ff_repository().get(ff_id)

    async def list(self) -> list[dict]:
        return await get_ff_repository().list()

    async def request_stop(self, ff_id: str) -> dict:
        repo = get_ff_repository()
        row = await repo.get(ff_id)
        if row is None:
            raise FFSimNotFound(ff_id)
        # Only a RUNNING replay can be cancelled; the loop checks the flag each bar.
        if row["status"] == "RUNNING":
            self._cancelled.add(ff_id)
        return row

    # ── the replay ────────────────────────────────────────────────────────────

    async def run_replay(self, ff_id: str) -> dict | None:
        """Run the whole replay for ``ff_id`` to completion (or cancellation)."""
        repo = get_ff_repository()
        try:
            row = await repo.get(ff_id)
            if row is None:
                raise FFSimNotFound(ff_id)
            return await self._replay(repo, row)
        except Exception as exc:  # a batch failure must not crash the worker
            logger.exception("fast-forward replay %s failed", ff_id)
            await repo.update(
                ff_id,
                {
                    "status": "FAILED",
                    "error": str(exc)[:500],
                    "completed_at": datetime.now(timezone.utc),
                },
            )
            return None
        finally:
            self._cancelled.discard(ff_id)

    async def _replay(self, repo, row: dict) -> dict:
        ff_id = row["id"]
        exchange = row["exchange"]
        window = int(row["zscore_window"])
        start = _aware(row["start_time"])
        end = _aware(row["end_time"])

        # 1. Pairs from the latest scan (cointegration is mode-independent market
        #    structure — read under DEFAULT_MODE, like the real-time sim).
        pairs = await get_scan_repository().get_latest_pairs(
            exchange=exchange, mode=config.DEFAULT_MODE
        )
        if not pairs:
            raise RuntimeError("No cointegrated pairs in the latest scan — run a scan first.")

        # 2. Load history for every leg (+ warm-up bars before the window so the
        #    rolling Z is defined from the very first trading cursor).
        markets = {p["base_market"] for p in pairs} | {p["quote_market"] for p in pairs}
        load_start = start - timedelta(hours=window + 2)
        source = make_candle_source(exchange=exchange)
        candles_by_market: dict[str, list[dict]] = {}
        funding_by_market: dict[str, list[dict]] = {}
        for market in markets:
            candles_by_market[market] = await source.get_candles(
                market, start=load_start, end=end
            )
            funding_by_market[market] = await source.get_funding(
                market, start=load_start, end=end
            )

        aligned = align_pairs(pairs, candles_by_market)
        timeline = replay_timeline(aligned, start=start, end=end)
        if not timeline:
            raise RuntimeError("No historical bars in the selected window for these pairs.")
        funding = FundingTable(funding_by_market)

        total = len(timeline)
        await repo.update(
            ff_id, {"pairs_count": len(aligned), "total_ticks": total}
        )

        # 3. Working session for run_tick (in-memory ledger).
        session = {
            "id": ff_id,
            "exchange": exchange,
            "current_capital": row["starting_capital"],
            "entry_threshold": row["entry_threshold"],
            "exit_threshold": row["exit_threshold"],
            "stop_threshold": row["stop_threshold"],
            "usd_per_trade": row["usd_per_trade"],
            "max_active_pairs": row.get("max_active_pairs"),
            "slippage_pct": row["slippage_pct"],
            "taker_fee_pct": row["taker_fee_pct"],
            "funding_freq_h": row["funding_freq_h"],
            "tick_count": 0,
            "last_tick_at": None,
        }
        wrepo = WorkingSimRepository(session)

        # 4. Walk the cursor.
        sample_every = max(1, total // _MAX_CURVE_POINTS)
        progress_every = max(1, total // _PROGRESS_STEPS)
        equity_curve: list[dict] = []
        cancelled = False
        for i, cursor in enumerate(timeline):
            if ff_id in self._cancelled:
                cancelled = True
                break
            snaps = snapshots_at(aligned, cursor, window=window)
            snap_by_pair = {(s.base_market, s.quote_market): s for s in snaps}
            rates = funding.rates_at(cursor, markets) if not funding.empty else {}
            cur_session = await wrepo.get_session(ff_id)
            await run_tick(
                wrepo, cur_session, snaps, funding_rates=rates or None, now=cursor
            )
            if i % sample_every == 0 or i == total - 1:
                equity = await _equity_at(wrepo, snap_by_pair)
                equity_curve.append(
                    {"t": int(cursor.timestamp()), "equity": round(equity, 2)}
                )
            if i % progress_every == 0:
                await repo.update(
                    ff_id,
                    {"processed_ticks": i + 1, "progress": round((i + 1) / total, 4)},
                )

        # 5. Force-close whatever is still open at the final cursor, then aggregate.
        final_cursor = timeline[len(timeline) - 1] if not cancelled else timeline[i]
        await self._close_remaining(wrepo, aligned, final_cursor, window)
        return await self._finalise(repo, ff_id, wrepo, equity_curve, cancelled, total, i + 1)

    async def _close_remaining(
        self, wrepo: WorkingSimRepository, aligned, cursor: datetime, window: int
    ) -> None:
        """Mark every still-open position to the final bar and book it (END_OF_REPLAY)."""
        open_positions = await wrepo.get_open_positions(wrepo.session_id)
        if not open_positions:
            return
        snap_by_pair = {
            (s.base_market, s.quote_market): s
            for s in snapshots_at(aligned, cursor, window=window)
        }
        session = await wrepo.get_session(wrepo.session_id)
        capital = session["current_capital"]
        # Close at the final *historical* cursor (not wall-clock) so the trade's
        # exit_time and hold_hours stay on the replay's timeline.
        now = cursor
        for pos in open_positions:
            snap = snap_by_pair.get((pos["base_market"], pos["quote_market"]))
            synthetic = snap is None
            if synthetic:
                from simulation.feed import PairTick

                snap = PairTick(
                    base_market=pos["base_market"],
                    quote_market=pos["quote_market"],
                    hedge_ratio=pos["hedge_ratio"],
                    half_life=pos["half_life"],
                    base_price=pos["entry_base_px"],
                    quote_price=pos["entry_quote_px"],
                    z_score=pos["entry_z"],
                    spread_value=0.0,
                )
            capital += await _close_position(
                wrepo, session, pos, snap, "END_OF_REPLAY",
                exit_z=None if synthetic else snap.z_score, now=now,
                slippage_pct=0.0 if synthetic else None,
                taker_fee_pct=0.0 if synthetic else None,
            )
        await wrepo.update_session(session["id"], {"current_capital": capital})

    async def _finalise(
        self, repo, ff_id, wrepo, equity_curve, cancelled, total, processed
    ) -> dict:
        trades = await wrepo.list_trades(ff_id)
        realised = round(sum(t["net_pnl"] for t in trades), 6)
        per_pair: dict[str, dict] = {}
        exit_reasons: dict[str, int] = {}
        for t in trades:
            key = f"{t['base_market']}/{t['quote_market']}"
            bucket = per_pair.setdefault(key, {"net_pnl": 0.0, "trades": 0, "wins": 0})
            bucket["net_pnl"] = round(bucket["net_pnl"] + t["net_pnl"], 6)
            bucket["trades"] += 1
            if t["net_pnl"] > 0:
                bucket["wins"] += 1
            exit_reasons[t["exit_reason"]] = exit_reasons.get(t["exit_reason"], 0) + 1
        final_capital = (await wrepo.get_session(ff_id))["current_capital"]
        updated = await repo.update(
            ff_id,
            {
                "status": "STOPPED" if cancelled else "COMPLETED",
                "processed_ticks": processed,
                "progress": round(processed / total, 4) if total else 1.0,
                "final_capital": round(final_capital, 6),
                "realised_pnl": realised,
                "total_trades": len(trades),
                "equity_curve": equity_curve,
                "per_pair_pnl": per_pair,
                "exit_reasons": exit_reasons,
                "completed_at": datetime.now(timezone.utc),
            },
        )
        logger.info(
            "fast-forward %s %s: %d trades, realised %.2f over %d/%d ticks",
            ff_id, "stopped" if cancelled else "completed",
            len(trades), realised, processed, total,
        )
        return updated


async def _equity_at(wrepo: WorkingSimRepository, snap_by_pair: dict) -> float:
    """Capital + Σ mark-to-market unrealised at the current bar (matches engine.overview)."""
    session = await wrepo.get_session(wrepo.session_id)
    unrealised = 0.0
    for pos in await wrepo.get_open_positions(session["id"]):
        snap = snap_by_pair.get((pos["base_market"], pos["quote_market"]))
        if snap is None:
            continue
        gross = compute_unrealized_pnl(
            direction=pos["direction"],
            entry_base_px=pos["entry_base_px"],
            entry_quote_px=pos["entry_quote_px"],
            base_price=snap.base_price,
            quote_price=snap.quote_price,
            base_size=pos["base_size"],
            quote_size=pos["quote_size"],
        )
        unrealised += gross - pos["fee_cost"] + pos.get("funding_pnl", 0.0)
    return session["current_capital"] + unrealised


def _aware(value) -> datetime:
    """Coerce a stored timestamp (ISO string or datetime) to a tz-aware UTC datetime."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


_engine: FastForwardReplayEngine | None = None


def get_ff_engine() -> FastForwardReplayEngine:
    """Return the process-wide fast-forward engine singleton."""
    global _engine
    if _engine is None:
        _engine = FastForwardReplayEngine()
    return _engine
