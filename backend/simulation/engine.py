"""
Real-time simulation engine (PRD F6) — a DB-backed, stateless-across-ticks paper
trader.

Two layers, mirroring ``trading/`` (Phase 5a):

  * :func:`run_tick` — the pure tick core. Given the session row, a list of
    :class:`~simulation.feed.PairTick` snapshots, and the repository, it accrues
    funding, closes reverted/diverged/aged positions, opens new ones on live
    signals, and updates capital. It reads **all** state from the repo each call,
    so a session restored after an API restart resumes exactly where it left off
    (F6.1). Signal logic is ``statcore.evaluate_entry``/``evaluate_exit`` — the
    same single source of truth the live bot uses, and the fix for the prototype's
    ``0.02``-std Z-score (F6.2).
  * :class:`SimulationEngine` — the orchestrator the router and scheduler drive.
    Holds one process lock so a scheduler tick and a manual tick/stop can never
    interleave on the same session, builds the read-only data client per tick,
    and turns the latest scan's pairs into snapshots via :mod:`simulation.feed`.

Capital convention (fixes a prototype double-count): ``current_capital`` changes
**only on close**, by the closed trade's ``net_pnl`` (which already nets entry +
exit fees and funding). Open positions don't touch capital; mark-to-market lives
in the equity reported by :meth:`SimulationEngine.overview`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import config
from db.scan_repository import get_scan_repository
from db.sim_repository import get_sim_repository
from exchanges import make_data_client
from simulation.costs import (
    compute_exit_pnl,
    compute_funding,
    compute_unrealized_pnl,
    direction_from_z,
    simulate_pair_entry,
)
from simulation.feed import PairTick, build_realtime_snapshots
from statcore import evaluate_entry, evaluate_exit

logger = logging.getLogger(__name__)


class SimSessionNotFound(Exception):
    """Raised when a tick / control targets a session id that does not exist."""


def _age_hours(entry_time: str | None, now: datetime) -> float | None:
    if not entry_time:
        return None
    try:
        dt = datetime.fromisoformat(entry_time)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 3600.0


async def _accrue_funding(
    repo, session: dict, positions: list[dict], funding_rates: dict[str, float], now: datetime
) -> float:
    """Accrue funding on every open position for the hours since the last tick.

    dYdX funds hourly; the per-period rate is scaled by elapsed_hours /
    funding_freq_h so a tick that spans part of a period accrues proportionally.
    Returns the total funding accrued this tick.
    """
    last = _age_hours(session.get("last_tick_at"), now)
    elapsed_hours = last if (last is not None and last > 0) else 0.0
    if elapsed_hours <= 0:
        return 0.0
    freq = session.get("funding_freq_h") or 1
    periods = elapsed_hours / float(freq)
    total = 0.0
    for pos in positions:
        base_rate = funding_rates.get(pos["base_market"], 0.0)
        quote_rate = funding_rates.get(pos["quote_market"], 0.0)
        if base_rate == 0.0 and quote_rate == 0.0:
            continue
        delta = compute_funding(
            direction=pos["direction"],
            base_size=pos["base_size"],
            quote_size=pos["quote_size"],
            entry_base_px=pos["entry_base_px"],
            entry_quote_px=pos["entry_quote_px"],
            base_rate=base_rate,
            quote_rate=quote_rate,
        ) * periods
        await repo.update_position(pos["id"], {"funding_pnl": pos["funding_pnl"] + delta})
        total += delta
    return total


async def run_tick(
    repo,
    session: dict,
    snapshots: list[PairTick],
    *,
    funding_rates: dict[str, float] | None = None,
    now: datetime | None = None,
) -> dict:
    """Run one simulation tick against ``session`` using ``snapshots``.

    Pure of any data source — the caller supplies the snapshots (live feed for
    real-time, historical replay for Phase 7). Returns a summary dict; never
    raises on a per-pair problem (a bad pair is skipped, not fatal).
    """
    now = now or datetime.now(timezone.utc)
    session_id = session["id"]

    entry_threshold = session.get("entry_threshold") or config.ZSCORE_THRESH
    exit_threshold = session.get("exit_threshold") or config.EXIT_ZSCORE
    stop_threshold = session.get("stop_threshold") or config.STOP_LOSS_ZSCORE
    usd_per_trade = session.get("usd_per_trade") or config.USD_PER_TRADE
    max_active = session.get("max_active_pairs")
    time_stop_mult = config.TIME_STOP_HALF_LIFE_MULT

    snap_by_pair = {(s.base_market, s.quote_market): s for s in snapshots}
    summary = {"entries": 0, "exits": 0, "funding_accrued": 0.0, "evaluated": len(snapshots)}

    # ── 1. Funding accrual (only when rates are supplied) ────────────────────
    open_positions = await repo.get_open_positions(session_id)
    if funding_rates:
        summary["funding_accrued"] = await _accrue_funding(
            repo, session, open_positions, funding_rates, now
        )
        open_positions = await repo.get_open_positions(session_id)  # reload funding_pnl

    current_capital = session["current_capital"]

    # ── 2. Exits ─────────────────────────────────────────────────────────────
    still_open: list[dict] = []
    for pos in open_positions:
        snap = snap_by_pair.get((pos["base_market"], pos["quote_market"]))
        if snap is None:
            still_open.append(pos)  # no live price — hold, retry next tick
            continue
        age = _age_hours(pos.get("entry_time"), now)
        exit_sig = evaluate_exit(
            snap.z_score,
            position_age_hours=age,
            half_life=pos["half_life"],
            exit_threshold=exit_threshold,
            stop_threshold=stop_threshold,
            time_stop_mult=time_stop_mult,
        )
        if exit_sig is None:
            still_open.append(pos)
            continue
        current_capital += await _close_position(
            repo, session, pos, snap, exit_sig.reason.value, exit_z=snap.z_score, now=now
        )
        summary["exits"] += 1

    # ── 3. Entries ───────────────────────────────────────────────────────────
    open_pairs = {(p["base_market"], p["quote_market"]) for p in still_open}
    # Track deployed notional so a tick with many simultaneous signals can't
    # over-leverage the paper account: each dollar-neutral pair commits ~one leg's
    # notional as margin, and capital only releases on close. Without this, a
    # default max_active_pairs=None lets the engine open a position for *every*
    # signalling pair regardless of capital.
    committed = len(still_open) * usd_per_trade
    for snap in snapshots:
        if max_active is not None and len(open_pairs) >= max_active:
            break
        if (snap.base_market, snap.quote_market) in open_pairs:
            continue
        if snap.base_price <= 0 or snap.quote_price <= 0:
            continue
        if evaluate_entry(snap.z_score, entry_threshold=entry_threshold) is None:
            continue
        # Margin guard: stop once another position would exceed available capital
        # (all positions size at usd_per_trade, so no later pair can fit either).
        if committed + usd_per_trade > current_capital:
            break
        await _open_position(repo, session, snap, usd_per_trade, now)
        open_pairs.add((snap.base_market, snap.quote_market))
        committed += usd_per_trade
        summary["entries"] += 1

    # ── 4. Persist session progress ──────────────────────────────────────────
    await repo.update_session(
        session_id,
        {
            "current_capital": current_capital,
            "tick_count": session.get("tick_count", 0) + 1,
            "last_tick_at": now,
        },
    )
    summary["current_capital"] = current_capital
    return summary


async def _open_position(repo, session: dict, snap: PairTick, usd_per_trade: float, now) -> None:
    direction = direction_from_z(snap.z_score)
    fill = simulate_pair_entry(
        base_market=snap.base_market,
        quote_market=snap.quote_market,
        direction=direction,
        base_price=snap.base_price,
        quote_price=snap.quote_price,
        hedge_ratio=snap.hedge_ratio,
        usd_per_trade=usd_per_trade,
        slippage_pct=session.get("slippage_pct", 0.05),
        taker_fee_pct=session.get("taker_fee_pct", 0.05),
    )
    await repo.create_position(
        {
            "session_id": session["id"],
            "exchange": session["exchange"],
            "base_market": snap.base_market,
            "quote_market": snap.quote_market,
            "direction": direction,
            "base_size": fill.base.size,
            "quote_size": fill.quote.size,
            "hedge_ratio": snap.hedge_ratio,
            "half_life": snap.half_life,
            "entry_z": snap.z_score,
            "entry_base_px": fill.base.fill_price,
            "entry_quote_px": fill.quote.fill_price,
            "entry_time": now,
            "fee_cost": fill.total_fee,
            "funding_pnl": 0.0,
            "status": "OPEN",
        }
    )


async def _close_position(
    repo, session: dict, pos: dict, snap: PairTick, reason: str, *, exit_z: float | None, now
) -> float:
    """Close a position into a SimTrade. Returns the realised net P&L (capital delta)."""
    pnl = compute_exit_pnl(
        direction=pos["direction"],
        entry_base_px=pos["entry_base_px"],
        entry_quote_px=pos["entry_quote_px"],
        exit_base_px=snap.base_price,
        exit_quote_px=snap.quote_price,
        base_size=pos["base_size"],
        quote_size=pos["quote_size"],
        entry_fee=pos["fee_cost"],
        slippage_pct=session.get("slippage_pct", 0.05),
        taker_fee_pct=session.get("taker_fee_pct", 0.05),
        funding_pnl=pos.get("funding_pnl", 0.0),
    )
    age = _age_hours(pos.get("entry_time"), now) or 0.0
    await repo.create_trade(
        {
            "session_id": session["id"],
            "exchange": session["exchange"],
            "base_market": pos["base_market"],
            "quote_market": pos["quote_market"],
            "direction": pos["direction"],
            "entry_time": pos["entry_time"],
            "exit_time": now,
            "hold_hours": round(age, 4),
            "entry_z": pos["entry_z"],
            "exit_z": exit_z,
            "exit_reason": reason,
            "notional_usd": pos["base_size"] * pos["entry_base_px"],
            **pnl,
        }
    )
    await repo.close_position(pos["id"])
    return pnl["net_pnl"]


# ── Orchestrator ─────────────────────────────────────────────────────────────


class SimulationEngine:
    """Process-wide orchestrator for real-time simulation sessions."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    # session lifecycle ---------------------------------------------------------

    async def create_session(self, params: dict) -> dict:
        return await get_sim_repository().create_session(params)

    async def list_sessions(self) -> list[dict]:
        return await get_sim_repository().list_sessions()

    async def get_session(self, session_id: str) -> dict | None:
        return await get_sim_repository().get_session(session_id)

    async def set_status(self, session_id: str, status: str) -> dict:
        repo = get_sim_repository()
        session = await repo.get_session(session_id)
        if session is None:
            raise SimSessionNotFound(session_id)
        data: dict = {"status": status}
        if status == "STOPPED":
            data["stopped_at"] = datetime.now(timezone.utc)
        return await repo.update_session(session_id, data)

    async def top_up(self, session_id: str, amount: float) -> dict:
        repo = get_sim_repository()
        session = await repo.get_session(session_id)
        if session is None:
            raise SimSessionNotFound(session_id)
        new_capital = session["current_capital"] + amount
        return await repo.update_session(session_id, {"current_capital": new_capital})

    # ticking -------------------------------------------------------------------

    async def _snapshots_for(
        self, session: dict, *, only_pairs: set[tuple[str, str]] | None = None
    ) -> list[PairTick]:
        """Build live snapshots for a session's pairs (latest scan, mainnet prices).

        ``only_pairs`` restricts the work to a subset of (base, quote) keys — used
        by ``overview``/``stop``, which only need to mark the currently-open
        positions to market, not recompute Z for the whole scan universe.
        """
        pairs = await get_scan_repository().get_latest_pairs(
            exchange=session["exchange"], mode=config.DEFAULT_MODE
        )
        if only_pairs is not None:
            pairs = [p for p in pairs if (p["base_market"], p["quote_market"]) in only_pairs]
        if not pairs:
            return []
        client = make_data_client()
        try:
            return await build_realtime_snapshots(
                client, pairs, window=session.get("zscore_window")
            )
        finally:
            try:
                await client.aclose()
            except Exception as exc:  # pragma: no cover
                logger.warning("sim data client close failed: %s", exc)

    async def tick(self, session_id: str) -> dict:
        """Run one real-time tick (scheduler / manual). Serialised per process.

        Funding is *not* accrued here: the cost model and ``run_tick`` support it
        (and the replay path in Phase 7 will supply per-bar rates from
        ``FundingRateCache``), but fetching *live* funding rates for a real-time
        session is a separate indexer integration deferred to a follow-up issue.
        Slippage and taker fees still apply on every open/close.
        """
        async with self._lock:
            repo = get_sim_repository()
            session = await repo.get_session(session_id)
            if session is None:
                raise SimSessionNotFound(session_id)
            if session["status"] != "RUNNING":
                return {"skipped": True, "reason": f"session {session['status']}"}
            snapshots = await self._snapshots_for(session)
            if not snapshots:
                await repo.update_session(
                    session_id,
                    {"tick_count": session.get("tick_count", 0) + 1,
                     "last_tick_at": datetime.now(timezone.utc)},
                )
                return {"entries": 0, "exits": 0, "evaluated": 0, "message": "No pairs/prices."}
            return await run_tick(repo, session, snapshots)

    async def stop(self, session_id: str) -> dict:
        """Stop a session: force-close every open position at current prices."""
        async with self._lock:
            repo = get_sim_repository()
            session = await repo.get_session(session_id)
            if session is None:
                raise SimSessionNotFound(session_id)
            now = datetime.now(timezone.utc)
            open_positions = await repo.get_open_positions(session_id)
            closed = 0
            if open_positions:
                only = {(p["base_market"], p["quote_market"]) for p in open_positions}
                snapshots = await self._snapshots_for(session, only_pairs=only)
                snap_by_pair = {(s.base_market, s.quote_market): s for s in snapshots}
                capital = session["current_capital"]
                for pos in open_positions:
                    snap = snap_by_pair.get((pos["base_market"], pos["quote_market"]))
                    if snap is None:
                        # No price to mark against — close flat (entry prices) so no
                        # naked virtual position lingers; P&L is just accrued funding.
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
                        repo, session, pos, snap, "STOPPED", exit_z=None, now=now
                    )
                    closed += 1
                await repo.update_session(session_id, {"current_capital": capital})
            updated = await repo.update_session(
                session_id, {"status": "STOPPED", "stopped_at": now}
            )
            return {"session": updated, "positions_closed": closed}

    async def overview(self, session_id: str) -> dict:
        """Session row + open positions (marked to market) + trade history + equity."""
        repo = get_sim_repository()
        session = await repo.get_session(session_id)
        if session is None:
            raise SimSessionNotFound(session_id)
        positions = await repo.get_open_positions(session_id)
        trades = await repo.list_trades(session_id)

        unrealized = 0.0
        marked: list[dict] = []
        snap_by_pair: dict[tuple[str, str], PairTick] = {}
        if positions and session["status"] != "STOPPED":
            only = {(p["base_market"], p["quote_market"]) for p in positions}
            snapshots = await self._snapshots_for(session, only_pairs=only)
            snap_by_pair = {(s.base_market, s.quote_market): s for s in snapshots}
        for pos in positions:
            snap = snap_by_pair.get((pos["base_market"], pos["quote_market"]))
            upnl: float | None = None
            if snap is not None:
                gross = compute_unrealized_pnl(
                    direction=pos["direction"],
                    entry_base_px=pos["entry_base_px"],
                    entry_quote_px=pos["entry_quote_px"],
                    base_price=snap.base_price,
                    quote_price=snap.quote_price,
                    base_size=pos["base_size"],
                    quote_size=pos["quote_size"],
                )
                upnl = gross - pos["fee_cost"] + pos.get("funding_pnl", 0.0)
                unrealized += upnl
            marked.append({**pos, "unrealized_pnl": upnl,
                           "current_z": snap.z_score if snap else None})

        equity = session["current_capital"] + unrealized
        return {
            "session": session,
            "positions": marked,
            "trades": trades,
            "equity": equity,
            "unrealized_pnl": unrealized,
            "open_count": len(positions),
            "closed_count": len(trades),
        }


_engine: SimulationEngine | None = None


def get_sim_engine() -> SimulationEngine:
    """Return the process-wide simulation engine singleton."""
    global _engine
    if _engine is None:
        _engine = SimulationEngine()
    return _engine
