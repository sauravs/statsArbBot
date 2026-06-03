"""
Per-leg P&L for a manual pairs trade — pure, no DB / no I/O.

A manual trade is a two-leg spread position. The entry direction follows the
same Option-B rule as ``statcore.signals.evaluate_entry`` (PRD §3.2):

    z < 0 → spread below mean → BUY base (leg 1), SELL quote (leg 2)
    z ≥ 0 → spread above mean → SELL base (leg 1), BUY quote (leg 2)

Each leg is sized by the capital the operator allocated to it, so the units held
are ``capital / entry_price``. A long leg profits when its price rises, a short
leg when its price falls; realised P&L is the sum of both legs:

    units_i        = capital_i / entry_price_i
    pnl_leg_i      = units_i · (exit_price_i − entry_price_i) · side_sign_i
    pnl            = pnl_leg1 + pnl_leg2

where ``side_sign`` is +1 for a long (BUY) leg and −1 for a short (SELL) leg.
"""

from __future__ import annotations

from dataclasses import dataclass

from statcore import Side, leg_pnl


@dataclass(frozen=True)
class ManualPnl:
    """Realised P&L of a closed manual trade, broken down by leg."""

    pnl_leg1: float
    pnl_leg2: float
    pnl: float
    base_is_long: bool  # True → leg 1 (base) was long, leg 2 (quote) short

    def to_dict(self) -> dict:
        return {
            "pnl_leg1": self.pnl_leg1,
            "pnl_leg2": self.pnl_leg2,
            "pnl": self.pnl,
            "base_is_long": self.base_is_long,
        }


def compute_manual_pnl(
    *,
    z_score: float,
    entry_price_leg1: float,
    entry_price_leg2: float,
    exit_price_leg1: float,
    exit_price_leg2: float,
    capital_leg1_usd: float,
    capital_leg2_usd: float,
) -> ManualPnl:
    """
    Compute realised per-leg P&L for a closed manual trade.

    Direction is taken from the sign of the entry ``z_score`` (the same rule as
    ``statcore.evaluate_entry``): a negative Z longs the base leg and shorts the
    quote leg; a non-negative Z does the reverse.

    Raises ``ValueError`` on a non-positive entry price (units would be undefined).
    """
    if entry_price_leg1 <= 0 or entry_price_leg2 <= 0:
        raise ValueError("entry prices must be positive to size the legs")

    # z < 0 longs the base leg (shorts quote); z ≥ 0 reverses (market-neutral).
    base_is_long = z_score < 0
    base_side = Side.BUY if base_is_long else Side.SELL
    quote_side = Side.SELL if base_is_long else Side.BUY

    units_leg1 = capital_leg1_usd / entry_price_leg1
    units_leg2 = capital_leg2_usd / entry_price_leg2

    pnl_leg1 = leg_pnl(
        side=base_side, entry_price=entry_price_leg1, exit_price=exit_price_leg1, size=units_leg1
    )
    pnl_leg2 = leg_pnl(
        side=quote_side, entry_price=entry_price_leg2, exit_price=exit_price_leg2, size=units_leg2
    )

    return ManualPnl(
        pnl_leg1=pnl_leg1,
        pnl_leg2=pnl_leg2,
        pnl=pnl_leg1 + pnl_leg2,
        base_is_long=base_is_long,
    )
