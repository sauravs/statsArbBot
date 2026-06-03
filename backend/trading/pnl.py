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

from statcore import leg_pnl


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
    pnl_leg1 = leg_pnl(
        side=base_side, entry_price=entry_price_leg1, exit_price=exit_price_leg1, size=base_size
    )
    pnl_leg2 = leg_pnl(
        side=quote_side, entry_price=entry_price_leg2, exit_price=exit_price_leg2, size=quote_size
    )
    return LivePnl(pnl_leg1=pnl_leg1, pnl_leg2=pnl_leg2, pnl=pnl_leg1 + pnl_leg2)
