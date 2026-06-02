"""
Exit manager (PRD §3.2, F5.2) — one pass that closes open pairs that have reverted,
diverged, or aged out, and reconciles the DB against the exchange.

For each OPEN trade in the DB:

  1. **Reconcile both legs gone** — if neither leg is live on-exchange, the
     position closed outside the bot; mark the trade CLOSED (``RECONCILED``) with
     best-effort P&L from current prices.
  2. **Orphaned leg** — if exactly one leg is live, immediately close it
     reduce-only (no naked exposure) and mark the trade CLOSED (``ORPHANED``).
  3. **Both legs live** — recompute the current Z and apply the Option-B exit
     rules via ``statcore.evaluate_exit``:
       * take-profit ``|Z| < EXIT_ZSCORE`` (0.5),
       * stop-loss ``|Z| ≥ STOP_LOSS_ZSCORE`` (4.0),
       * time-stop age > ``TIME_STOP_HALF_LIFE_MULT × half_life`` (3×).
     On a fire (and approval) close both legs reduce-only and record **real P&L**
     from the close fill prices.

The Z-score is invariant to the cointegration intercept α (it cancels in
``(spread − mean)/std``), so exit Z is recomputed with ``intercept=0`` — the live
trade row need not store α.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from marketdata.pair_series import current_pair_snapshot
from statcore import evaluate_exit, opposite_side
from trading.alerts import Alerter
from trading.approval import ApprovalGate
from trading.broker import TradeClient
from trading.pnl import compute_live_pnl

logger = logging.getLogger(__name__)


def _age_hours(opened_at: str | None, now: datetime) -> float | None:
    """Hours since ``opened_at`` (ISO string), or None if unparseable."""
    if not opened_at:
        return None
    try:
        dt = datetime.fromisoformat(opened_at)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 3600.0


async def manage_exits(
    *,
    trade_client: TradeClient,
    data_client,  # PriceSource (read-only live prices)
    repo,  # live repository
    gate: ApprovalGate,
    alerter: Alerter,
    exchange: str,
    mode: str,
    exit_threshold: float | None = None,
    stop_threshold: float | None = None,
    time_stop_mult: float | None = None,
    window: int | None = None,
    now=None,
) -> dict:
    """Run one exit-management pass. Returns a summary dict (no exceptions escape)."""
    now_dt = now or datetime.now(timezone.utc)
    open_trades = await repo.get_open_trades(exchange=exchange, mode=mode)
    outcomes: list[dict] = []
    closed = 0

    if not open_trades:
        return {"managed": 0, "closed": 0, "message": "No open trades to manage.", "outcomes": []}

    positions = await trade_client.get_open_positions()

    for trade in open_trades:
        base = trade["base_market"]
        quote = trade["quote_market"]
        base_live = base in positions
        quote_live = quote in positions

        # ── 1. Both legs gone — reconcile out of the DB ──────────────────────
        # The position closed outside the bot; the actual fill prices are unknown,
        # so record CLOSED with pnl=None (not a fabricated current-price number).
        if not base_live and not quote_live:
            await _close_in_db(
                repo, trade, alerter,
                reason="RECONCILED", exit_z=None, now=now_dt,
                base_fill=None, quote_fill=None,
            )
            closed += 1
            outcomes.append({"pair": [base, quote], "action": "reconciled"})
            continue

        # ── 2. Orphaned leg — close it reduce-only, then reconcile ───────────
        if base_live != quote_live:
            orphan = base if base_live else quote
            orphan_side = trade["base_side"] if base_live else trade["quote_side"]
            orphan_size = trade["base_size"] if base_live else trade["quote_size"]
            await alerter.notify(f"Orphaned leg {orphan} on {base}/{quote} — closing reduce-only.")
            result = await trade_client.place_market_order(
                market=orphan, side=opposite_side(orphan_side), size=orphan_size, reduce_only=True
            )
            if result is None:
                # The orphan close failed — keep the trade OPEN so the next pass
                # retries; marking it CLOSED would orphan a naked leg untracked.
                await alerter.code_red(
                    f"Orphan close FAILED for {orphan} ({base}/{quote}) — naked leg remains."
                )
                outcomes.append({"pair": [base, quote], "action": "orphan_close_failed"})
                continue
            await _close_in_db(
                repo, trade, alerter,
                reason="ORPHANED", exit_z=None, now=now_dt,
                base_fill=None, quote_fill=None,
            )
            closed += 1
            outcomes.append({"pair": [base, quote], "action": "orphaned"})
            continue

        # ── 3. Both legs live — evaluate the exit rules ──────────────────────
        snap = await current_pair_snapshot(
            data_client,
            base_market=base,
            quote_market=quote,
            hedge_ratio=trade["hedge_ratio"],
            intercept=0.0,  # Z is invariant to α
            window=window,
            now=now,
        )
        if snap is None:
            # No usable live price/Z right now — hold rather than act on a NaN Z
            # (which would otherwise fabricate an exit and persist NaN). The next
            # pass retries; the prototype likewise kept the position.
            outcomes.append({"pair": [base, quote], "action": "held", "reason": "no_price"})
            continue
        z = snap.z_score
        age = _age_hours(trade.get("opened_at"), now_dt)
        exit_sig = evaluate_exit(
            z,
            position_age_hours=age,
            half_life=trade["half_life"],
            exit_threshold=exit_threshold,
            stop_threshold=stop_threshold,
            time_stop_mult=time_stop_mult,
        )
        if exit_sig is None:
            outcomes.append({"pair": [base, quote], "action": "held", "z_score": z})
            continue

        approved = await gate.request(
            {
                "kind": "exit",
                "exchange": exchange,
                "mode": mode,
                "base_market": base,
                "quote_market": quote,
                "z_score": z,
                "reason": exit_sig.reason.value,
            }
        )
        if not approved:
            outcomes.append({"pair": [base, quote], "action": "held", "reason": "rejected", "z_score": z})
            continue

        # Close both legs reduce-only.
        r1 = await trade_client.place_market_order(
            market=base, side=opposite_side(trade["base_side"]), size=trade["base_size"], reduce_only=True
        )
        r2 = await trade_client.place_market_order(
            market=quote, side=opposite_side(trade["quote_side"]), size=trade["quote_size"], reduce_only=True
        )
        if r1 is None or r2 is None:
            # Keep OPEN and retry next pass. If exactly one leg closed, the next
            # pass sees it as an orphan and unwinds the remaining naked leg.
            await alerter.notify(
                f"Close error on {base}/{quote} "
                f"(base={'OK' if r1 else 'FAIL'}, quote={'OK' if r2 else 'FAIL'}) — will retry next pass."
            )
            outcomes.append({"pair": [base, quote], "action": "close_failed"})
            continue

        await _close_in_db(
            repo, trade, alerter,
            reason=exit_sig.reason.value, exit_z=z, now=now_dt,
            base_fill=r1.price, quote_fill=r2.price,
        )
        closed += 1
        outcomes.append(
            {"pair": [base, quote], "action": "closed", "reason": exit_sig.reason.value, "z_score": z}
        )

    return {
        "managed": len(open_trades),
        "closed": closed,
        "message": f"Exit management complete — {closed}/{len(open_trades)} closed.",
        "outcomes": outcomes,
    }


async def _close_in_db(
    repo, trade, alerter,
    *, reason: str, exit_z: float | None, now: datetime,
    base_fill: float | None, quote_fill: float | None,
) -> None:
    """Persist a CLOSED trade.

    When both legs were closed by the bot (``base_fill``/``quote_fill`` known),
    record the real per-leg P&L from those fill prices. When the legs closed
    outside the bot (reconcile/orphan — fills unknown), record ``pnl=None`` and
    null exit prices rather than fabricating a number from unrelated current
    prices.
    """
    if base_fill is not None and quote_fill is not None:
        pnl = compute_live_pnl(
            base_side=trade["base_side"],
            quote_side=trade["quote_side"],
            base_size=trade["base_size"],
            quote_size=trade["quote_size"],
            entry_price_leg1=trade["entry_price_leg1"],
            entry_price_leg2=trade["entry_price_leg2"],
            exit_price_leg1=base_fill,
            exit_price_leg2=quote_fill,
        )
        pnl_value: float | None = pnl.pnl
    else:
        pnl_value = None  # actual fills unknown — do not fabricate P&L

    await repo.close_trade(
        trade["id"],
        exit_price_leg1=base_fill,
        exit_price_leg2=quote_fill,
        exit_z_score=exit_z,
        exit_reason=reason,
        pnl=pnl_value,
        closed_at=now,
    )
    pnl_str = f"${pnl_value:,.2f}" if pnl_value is not None else "unknown"
    await alerter.notify(
        f"Trade closed: {trade['base_market']}/{trade['quote_market']} "
        f"({reason}) P&L={pnl_str}"
    )
