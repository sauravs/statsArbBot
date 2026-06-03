"""
Simulation cost model (PRD F6.3) — pure functions, no DB / no IO.

Models the three frictions a real dYdX pairs trade pays, all configurable per
session (percent values):

  * **slippage** — adverse per leg: a BUY fills slightly above the reference price,
    a SELL slightly below, on both the entry and the exit order.
  * **taker fee** — charged on the filled notional of every leg (entry and exit).
  * **funding** — accrued every ``funding_freq_h`` hours at the current rate; a long
    leg pays funding, a short leg receives it.

Sizing is hedge-ratio-weighted (the cointegration hedge): hold ``usd_per_trade``
of the base leg and ``β`` units of quote per base unit, so the position tracks the
spread ``S1 − β·S2`` it was opened on. Directions follow ``statcore.evaluate_entry``:

  * ``LONG_BASE``  (entry Z < 0): BUY base, SELL quote — bet the spread rises.
  * ``SHORT_BASE`` (entry Z ≥ 0): SELL base, BUY quote — bet the spread falls.

P&L convention (fixes a prototype double-count): capital is touched **only on
close**, by ``net_pnl = gross − (entry_fee + exit_fee) + funding``. The entry fee
is *not* separately deducted at entry (the prototype subtracted it at entry and
again inside ``net_pnl``).
"""

from __future__ import annotations

from dataclasses import dataclass

# Position directions (also stored on SimPosition.direction).
LONG_BASE = "LONG_BASE"
SHORT_BASE = "SHORT_BASE"


def direction_from_z(z: float) -> str:
    """Entry direction from the signed entry Z (same rule as statcore.evaluate_entry)."""
    return LONG_BASE if z < 0 else SHORT_BASE


def _entry_sides(direction: str) -> tuple[str, str]:
    """(base_side, quote_side) at entry for a direction."""
    if direction == LONG_BASE:
        return "BUY", "SELL"
    return "SELL", "BUY"


def apply_slippage(side: str, raw_price: float, slippage_pct: float) -> float:
    """Adverse fill price: a BUY pays up, a SELL receives down."""
    mult = 1.0 + slippage_pct / 100.0 if side == "BUY" else 1.0 - slippage_pct / 100.0
    return raw_price * mult


def _leg_pnl(side: str, entry_price: float, exit_price: float, size: float) -> float:
    """Signed per-leg P&L: +1 for a long (BUY) leg, −1 for a short (SELL) leg."""
    sign = 1.0 if side == "BUY" else -1.0
    return sign * (exit_price - entry_price) * size


@dataclass(frozen=True)
class LegFill:
    """A single filled leg (after slippage)."""

    market: str
    side: str  # BUY | SELL
    size: float
    raw_price: float
    fill_price: float
    notional: float
    fee: float


@dataclass(frozen=True)
class PairEntryFill:
    """Both legs of a simulated entry, plus the combined entry fee."""

    base: LegFill
    quote: LegFill
    total_fee: float


def _fill_leg(
    market: str,
    side: str,
    raw_price: float,
    size: float,
    slippage_pct: float,
    taker_fee_pct: float,
) -> LegFill:
    fill_price = apply_slippage(side, raw_price, slippage_pct)
    notional = fill_price * size
    fee = notional * taker_fee_pct / 100.0
    return LegFill(
        market=market,
        side=side,
        size=size,
        raw_price=raw_price,
        fill_price=fill_price,
        notional=notional,
        fee=fee,
    )


def simulate_pair_entry(
    *,
    base_market: str,
    quote_market: str,
    direction: str,
    base_price: float,
    quote_price: float,
    hedge_ratio: float,
    usd_per_trade: float,
    slippage_pct: float,
    taker_fee_pct: float,
) -> PairEntryFill:
    """Simulate opening a two-leg pair position; returns both filled legs."""
    base_side, quote_side = _entry_sides(direction)
    base_size = usd_per_trade / base_price
    quote_size = base_size * abs(hedge_ratio)
    base = _fill_leg(base_market, base_side, base_price, base_size, slippage_pct, taker_fee_pct)
    quote = _fill_leg(quote_market, quote_side, quote_price, quote_size, slippage_pct, taker_fee_pct)
    return PairEntryFill(base=base, quote=quote, total_fee=base.fee + quote.fee)


def compute_exit_pnl(
    *,
    direction: str,
    entry_base_px: float,
    entry_quote_px: float,
    exit_base_px: float,
    exit_quote_px: float,
    base_size: float,
    quote_size: float,
    entry_fee: float,
    slippage_pct: float,
    taker_fee_pct: float,
    funding_pnl: float = 0.0,
) -> dict:
    """
    Realised P&L for closing a simulated position.

    ``entry_base_px`` / ``entry_quote_px`` are the stored entry *fill* prices.
    The exit reverses each leg's side and pays adverse slippage + taker fee on the
    closing notional. Returns ``{gross_pnl, fee_cost, funding_pnl, net_pnl}`` where
    ``fee_cost`` is entry + exit fees and ``net_pnl = gross − fee_cost + funding``.
    """
    base_side, quote_side = _entry_sides(direction)
    # Closing order takes the opposite side of each leg.
    base_exit_side = "SELL" if base_side == "BUY" else "BUY"
    quote_exit_side = "SELL" if quote_side == "BUY" else "BUY"
    base_exit_fill = apply_slippage(base_exit_side, exit_base_px, slippage_pct)
    quote_exit_fill = apply_slippage(quote_exit_side, exit_quote_px, slippage_pct)

    gross_pnl = _leg_pnl(base_side, entry_base_px, base_exit_fill, base_size) + _leg_pnl(
        quote_side, entry_quote_px, quote_exit_fill, quote_size
    )
    exit_fee = (
        base_exit_fill * base_size + quote_exit_fill * quote_size
    ) * taker_fee_pct / 100.0
    total_fee = entry_fee + exit_fee
    net_pnl = gross_pnl - total_fee + funding_pnl

    return {
        "gross_pnl": round(gross_pnl, 6),
        "fee_cost": round(total_fee, 6),
        "funding_pnl": round(funding_pnl, 6),
        "net_pnl": round(net_pnl, 6),
    }


def compute_unrealized_pnl(
    *,
    direction: str,
    entry_base_px: float,
    entry_quote_px: float,
    base_price: float,
    quote_price: float,
    base_size: float,
    quote_size: float,
) -> float:
    """
    Mark-to-market gross P&L of an open position at current prices (no exit
    slippage/fee modelled). Used to mark equity = capital + Σ unrealised.
    """
    base_side, quote_side = _entry_sides(direction)
    return _leg_pnl(base_side, entry_base_px, base_price, base_size) + _leg_pnl(
        quote_side, entry_quote_px, quote_price, quote_size
    )


def compute_funding(
    *,
    direction: str,
    base_size: float,
    quote_size: float,
    entry_base_px: float,
    entry_quote_px: float,
    base_rate: float,
    quote_rate: float,
) -> float:
    """
    Funding accrued over one funding period for the pair (PRD F6.3).

    A long leg pays funding (negative), a short leg receives it (positive), each on
    the leg's notional. ``LONG_BASE`` is long base / short quote; ``SHORT_BASE`` is
    the reverse.
    """
    base_notional = base_size * entry_base_px
    quote_notional = quote_size * entry_quote_px
    if direction == LONG_BASE:
        return -base_rate * base_notional + quote_rate * quote_notional
    return base_rate * base_notional - quote_rate * quote_notional
