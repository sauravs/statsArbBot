"""
Persisting a closed pair — the shared tail of every live close path (PRD F5.3).

Closing an open **pair** ends the same way wherever it is triggered (the exit
manager's reverted/orphan/reconcile branches, or the Telegram ``/cancel``
override): record the trade CLOSED with **real per-leg P&L when both close fills
are known**, and ``pnl=None`` when a leg closed outside the bot (fills unknown)
— *never* a number fabricated from unrelated prices — then notify.

Phase 10 lifts that tail out of ``trading/exit.py`` and ``trading/engine.py``
(the ``_close_in_db`` ≈ ``close_pair`` echo, issue #18) so the "don't fabricate
P&L" rule and the close-record shape live in one place. The position-aware
*which legs to close* logic stays at each call site (it differs: the exit
manager already knows both legs are live, ``close_pair`` re-checks per leg), as
does ``abort_all`` (a whole-book flat close with no per-fill P&L).
"""

from __future__ import annotations

from datetime import datetime

from trading.pnl import compute_live_pnl


async def persist_closed_pair(
    repo,
    trade,
    alerter,
    *,
    reason: str,
    exit_z: float | None,
    base_fill: float | None,
    quote_fill: float | None,
    now: datetime,
    notice: str = "Trade closed",
) -> float | None:
    """Persist a CLOSED trade and notify; return the recorded P&L (or ``None``).

    When both legs were closed by the bot (``base_fill``/``quote_fill`` known),
    record the real per-leg P&L from those fills. When a leg closed outside the
    bot (reconcile/orphan — fills unknown), record ``pnl=None`` and null exit
    prices rather than fabricating a number from unrelated current prices.
    """
    if base_fill is not None and quote_fill is not None:
        pnl_value: float | None = compute_live_pnl(
            base_side=trade["base_side"],
            quote_side=trade["quote_side"],
            base_size=trade["base_size"],
            quote_size=trade["quote_size"],
            entry_price_leg1=trade["entry_price_leg1"],
            entry_price_leg2=trade["entry_price_leg2"],
            exit_price_leg1=base_fill,
            exit_price_leg2=quote_fill,
        ).pnl
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
        f"{notice}: {trade['base_market']}/{trade['quote_market']} ({reason}) P&L={pnl_str}"
    )
    return pnl_value
