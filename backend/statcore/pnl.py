"""
The per-leg realised-P&L primitive — the one signed-arithmetic rule shared by
every P&L path (live, manual, simulation, replay, backtest).

A pair position holds two opposite **legs**. The realised P&L of a single leg is:

    side_sign  = +1 for a long (BUY) leg, −1 for a short (SELL) leg
    leg_pnl    = side_sign · (exit_price − entry_price) · size

Everything above this (how ``size`` is obtained — fixed units at fill, capital
÷ entry, or a cost-modelled fill — and how the legs are paired) is the caller's
concern. Phase 10 lifts this rule into ``statcore`` (issue #18): it is exactly
the kind of algorithmic truth this package exists to keep single-sourced, so a
sign-flip can only ever be wrong in one place, checked against the same ``Side``
enum live trading uses.
"""

from __future__ import annotations

from .signals import Side


def side_sign(side) -> float:
    """+1 for a long (BUY) leg, −1 for a short (SELL) leg.

    Accepts a ``Side`` or its string value; raises ``ValueError`` on anything else.
    """
    normalized = getattr(side, "value", side)
    if normalized == Side.BUY.value:
        return 1.0
    if normalized == Side.SELL.value:
        return -1.0
    raise ValueError(f"side must be BUY or SELL, got {side!r}")


def leg_pnl(*, side, entry_price: float, exit_price: float, size: float) -> float:
    """Signed realised P&L of one leg: ``side_sign(side)·(exit−entry)·size``."""
    return side_sign(side) * (exit_price - entry_price) * size
