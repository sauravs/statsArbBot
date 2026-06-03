"""
Live trading engine (PRD F5) — orchestrates sessions, entry scans, exit
management, and emergency abort over the DB-backed state.

The engine is the seam the router drives. It:
  * serialises every mutating pass behind one process lock, so a concurrent
    entry-scan / exit-manage / abort can never interleave order placement on the
    same account (ADR-0003: explicit concurrency control, not "the event loop
    makes it safe");
  * builds a fresh data client (live prices) and trade client (account/orders)
    per pass and closes them in a ``finally`` (mirrors the manual router), so a
    failed pass never leaks a connection;
  * resolves the approval gate and alerter through their getters at call time, so
    the Phase-9 Telegram swap takes effect without touching the engine.

Dependencies are referenced as module globals (``make_trade_client`` etc.) so
tests can monkeypatch them with fakes — the Phase-5a gate is integration tests
against a mocked dYdX.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from db.live_repository import get_live_repository
from db.scan_repository import get_scan_repository
from exchanges import make_data_client, make_trade_client
from statcore import opposite_side
from trading.alerts import get_alerter
from trading.approval import get_approval_gate
from trading.close import persist_closed_pair
from trading.entry import scan_for_entries
from trading.exit import manage_exits

logger = logging.getLogger(__name__)


class NoActiveSession(Exception):
    """Raised when an entry/exit pass is requested with no active live session."""


async def _safe_close(client) -> None:
    try:
        await client.aclose()
    except Exception as exc:  # must never mask the pass result
        logger.warning("client close failed: %s", exc)


class LiveEngine:
    """Process-wide orchestrator for the live trading bot."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    # ── session control ───────────────────────────────────────────────────────

    async def start_session(self, *, exchange: str, mode: str) -> dict:
        """Activate the bot for (exchange, mode); returns the active session."""
        return await get_live_repository().start_session(exchange=exchange, mode=mode)

    async def stop_session(self, *, exchange: str, mode: str) -> dict:
        """Deactivate the bot. Open trades are left for the exit manager to close."""
        stopped = await get_live_repository().stop_session(exchange=exchange, mode=mode)
        return {"stopped_sessions": stopped}

    async def get_session(self, *, exchange: str, mode: str) -> dict | None:
        return await get_live_repository().get_active_session(exchange=exchange, mode=mode)

    async def list_trades(
        self, *, exchange: str, mode: str, status: str | None = None
    ) -> list[dict]:
        return await get_live_repository().list_trades(
            exchange=exchange, mode=mode, status=status
        )

    # ── passes ────────────────────────────────────────────────────────────────

    async def run_entry_scan(self, *, exchange: str, mode: str, **opts) -> dict:
        async with self._lock:
            repo = get_live_repository()
            session = await repo.get_active_session(exchange=exchange, mode=mode)
            if session is None:
                raise NoActiveSession("No active session — start the bot first.")
            pairs = await get_scan_repository().get_latest_pairs(
                exchange=exchange, mode=mode
            )
            if not pairs:
                return {"opened": 0, "evaluated": 0, "message": "No scanned pairs.", "outcomes": []}

            trade_client = await make_trade_client()
            data_client = make_data_client()
            try:
                return await scan_for_entries(
                    trade_client=trade_client,
                    data_client=data_client,
                    repo=repo,
                    gate=get_approval_gate(),
                    alerter=get_alerter(),
                    pairs=pairs,
                    session_id=session["id"],
                    exchange=exchange,
                    mode=mode,
                    **opts,
                )
            finally:
                await _safe_close(trade_client)
                await _safe_close(data_client)

    async def run_exit_management(self, *, exchange: str, mode: str, **opts) -> dict:
        async with self._lock:
            trade_client = await make_trade_client()
            data_client = make_data_client()
            try:
                return await manage_exits(
                    trade_client=trade_client,
                    data_client=data_client,
                    repo=get_live_repository(),
                    gate=get_approval_gate(),
                    alerter=get_alerter(),
                    exchange=exchange,
                    mode=mode,
                    **opts,
                )
            finally:
                await _safe_close(trade_client)
                await _safe_close(data_client)

    async def abort_all(self, *, exchange: str, mode: str) -> dict:
        """Emergency stop: cancel orders, close every position reduce-only, and
        mark all OPEN trades CLOSED (``ABORTED``)."""
        async with self._lock:
            repo = get_live_repository()
            alerter = get_alerter()
            trade_client = await make_trade_client()
            try:
                await alerter.notify(f"ABORT ALL triggered for {exchange}/{mode}.")
                await trade_client.cancel_all_orders()
                positions = await trade_client.get_open_positions()
                closed = []
                for market, pos in positions.items():
                    if pos.size <= 0:
                        continue
                    side = "SELL" if pos.side == "LONG" else "BUY"
                    r = await trade_client.place_market_order(
                        market=market, side=side, size=pos.size, reduce_only=True
                    )
                    closed.append({"market": market, "ok": r is not None})

                # An emergency close that failed leaves a live position the
                # operator believes is flat — escalate loudly.
                failed = [c["market"] for c in closed if not c["ok"]]
                if failed:
                    await alerter.code_red(
                        f"ABORT could not close: {', '.join(failed)} — positions may still be live."
                    )

                now = datetime.now(timezone.utc)
                open_trades = await repo.get_open_trades(exchange=exchange, mode=mode)
                for t in open_trades:
                    # Emergency close: no reliable fill price, so record a flat
                    # (zero-P&L) ABORTED close; the real fills are auditable on-chain.
                    await repo.close_trade(
                        t["id"],
                        exit_price_leg1=t["entry_price_leg1"],
                        exit_price_leg2=t["entry_price_leg2"],
                        exit_z_score=None,
                        exit_reason="ABORTED",
                        pnl=0.0,
                        closed_at=now,
                    )
                return {"positions_closed": closed, "trades_marked": len(open_trades)}
            finally:
                await _safe_close(trade_client)

    async def close_pair(
        self, *, exchange: str, mode: str, base_market: str, quote_market: str
    ) -> dict:
        """Immediately close one open pair, reduce-only (the Telegram ``/cancel``
        path). An explicit operator override — no approval gate, like ``abort_all``
        but scoped to a single pair.

        This is the rewrite's fix for the prototype's ``connect_dydx`` bug: the
        prototype's ``/cancel`` handler called a function (``create_dydx_connection``)
        that did not exist (the real one was ``connect_dydx``), raising ``NameError``
        at runtime. Here ``/cancel`` calls this real, named engine method instead.
        """
        async with self._lock:
            repo = get_live_repository()
            open_trades = await repo.get_open_trades(exchange=exchange, mode=mode)
            trade = next(
                (
                    t
                    for t in open_trades
                    if t["base_market"] == base_market
                    and t["quote_market"] == quote_market
                ),
                None,
            )
            if trade is None:
                return {
                    "found": False,
                    "closed": False,
                    "base_market": base_market,
                    "quote_market": quote_market,
                }

            alerter = get_alerter()
            trade_client = await make_trade_client()
            try:
                # Only close legs that are actually live on-exchange (mirrors
                # abort_all / the exit manager's orphan handling): a leg that
                # already closed outside the bot needs no order, and firing a
                # reduce-only at a flat position would falsely report failure.
                positions = await trade_client.get_open_positions()
                fills: dict[str, float] = {}  # market → fill price, only for legs we closed
                failed: list[str] = []
                for market, side, size in (
                    (base_market, trade["base_side"], trade["base_size"]),
                    (quote_market, trade["quote_side"], trade["quote_size"]),
                ):
                    if market not in positions:
                        continue  # already flat — nothing to unwind
                    r = await trade_client.place_market_order(
                        market=market, side=opposite_side(side), size=size, reduce_only=True
                    )
                    if r is None:
                        failed.append(market)
                    else:
                        fills[market] = r.price

                if failed:
                    # A reduce-only close failed — keep the trade OPEN so the exit
                    # manager retries (and unwinds any orphaned naked leg). Escalate.
                    await alerter.code_red(
                        f"/cancel could not close {', '.join(failed)} on "
                        f"{base_market}/{quote_market} — position may still be live."
                    )
                    return {
                        "found": True,
                        "closed": False,
                        "base_market": base_market,
                        "quote_market": quote_market,
                    }

                # Real P&L only when this call closed BOTH legs (both fills known);
                # if either leg was already flat its fill is unknown → pnl=None
                # rather than a fabricated number. ``persist_closed_pair`` owns that
                # rule (shared with the exit manager's reconcile/orphan path).
                pnl_value = await persist_closed_pair(
                    repo, trade, alerter,
                    reason="CANCELLED", exit_z=None,
                    base_fill=fills.get(base_market),
                    quote_fill=fills.get(quote_market),
                    now=datetime.now(timezone.utc),
                    notice="/cancel closed",
                )
                return {
                    "found": True,
                    "closed": True,
                    "base_market": base_market,
                    "quote_market": quote_market,
                    "pnl": pnl_value,
                }
            finally:
                await _safe_close(trade_client)

    async def account_summary(self) -> dict:
        trade_client = await make_trade_client()
        try:
            return {
                "free_collateral": await trade_client.get_free_collateral(),
                "equity": await trade_client.get_account_equity(),
            }
        finally:
            await _safe_close(trade_client)


_engine: LiveEngine | None = None


def get_live_engine() -> LiveEngine:
    """Return the process-wide live engine singleton."""
    global _engine
    if _engine is None:
        _engine = LiveEngine()
    return _engine
