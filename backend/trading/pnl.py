"""
Realised P&L for a live two-leg pairs trade — pure, no DB / no I/O (PRD F5.3).

A live trade is a market-neutral pair: one leg long (BUY), one short (SELL). The
sides and per-leg *unit* sizes are fixed at entry (``base_size``/``quote_size``
units, sized ``USD_PER_TRADE / fill_price`` when the legs filled), so realised
P&L is just the price move of each leg in its held direction:

    side_sign  = +1 for a long (BUY) leg, −1 for a short (SELL) leg
    pnl_leg_i  = size_i · (exit_price_i − entry_price_i) · side_sign_i
    pnl        = pnl_leg1 + pnl_leg2

This is the real P&L the prototype never computed (initial-codebase-analysis.md
§Incomplete-Features 5). It differs from ``manual.pnl`` only in that the sizes
are already in units (the live executor fixed them at fill) rather than derived
from a capital allocation.
"""

from __future__ import annotations

from dataclasses import dataclass

from statcore.signals import Side


def _side_sign(side: str) -> float:
    """+1 for a long (BUY) leg, −1 for a short (SELL) leg."""
    normalized = getattr(side, "value", side)
    if normalized == Side.BUY.value:
        return 1.0
    if normalized == Side.SELL.value:
        return -1.0
    raise ValueError(f"side must be BUY or SELL, got {side!r}")


@dataclass(frozen=True)
class LivePnl:
    """Realised P&L of a closed live trade, broken down by leg."""

    pnl_leg1: float
    pnl_leg2: float
    pnl: float

    def to_dict(self) -> dict:
        return {"pnl_leg1": self.pnl_leg1, "pnl_leg2": self.pnl_leg2, "pnl": self.pnl}


def compute_live_pnl(
    *,
    base_side: str,
    quote_side: str,
    base_size: float,
    quote_size: float,
    entry_price_leg1: float,
    entry_price_leg2: float,
    exit_price_leg1: float,
    exit_price_leg2: float,
) -> LivePnl:
    """
    Compute realised per-leg P&L for a closed live trade.

    ``base_side``/``quote_side`` are the entry sides ("BUY"/"SELL"); each leg's
    P&L is its price move times its held units, signed by its direction. Raises
    ``ValueError`` on an unrecognised side.
    """
    base_sign = _side_sign(base_side)
    quote_sign = _side_sign(quote_side)

    pnl_leg1 = base_size * (exit_price_leg1 - entry_price_leg1) * base_sign
    pnl_leg2 = quote_size * (exit_price_leg2 - entry_price_leg2) * quote_sign

    return LivePnl(pnl_leg1=pnl_leg1, pnl_leg2=pnl_leg2, pnl=pnl_leg1 + pnl_leg2)
