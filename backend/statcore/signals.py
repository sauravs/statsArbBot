"""
Trading-signal decision logic — the rules that turn a Z-score into an action.

One source of truth for entry, take-profit exit, and stop-loss, reused by live
trading, real-time simulation, fast-forward replay, and backtest. Encodes three
of the four Option-B changes (research.md §5/§6, ADR-0002):

  * Entry  : |Z| >= ZSCORE_THRESH (default 1.5).
  * Exit   : |Z| < EXIT_ZSCORE (default 0.5)         — replaces zero-crossing (#3).
  * Stop   : |Z| >= STOP_LOSS_ZSCORE (default 4.0)   — hard stop, was unwired (#2),
             OR position age > TIME_STOP_HALF_LIFE_MULT × half_life (#2).

Entry direction (PRD §3.2): the spread is ``S1 − β·S2 − α``.
  Z < 0 → spread below mean → BUY base (S1), SELL quote (S2)  — bet spread rises.
  Z > 0 → spread above mean → SELL base (S1), BUY quote (S2)  — bet spread falls.

Pure functions: no DB, no clock, no exchange. The caller supplies the current
Z-score and (for the time stop) the position's age.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

import config


class Side(str, Enum):
    """Order side for a single leg."""

    BUY = "BUY"
    SELL = "SELL"


def opposite_side(side: str) -> str:
    """The reduce-only close side for a leg opened with ``side`` (BUY↔SELL)."""
    normalized = getattr(side, "value", side)
    if normalized == Side.BUY.value:
        return Side.SELL.value
    if normalized == Side.SELL.value:
        return Side.BUY.value
    raise ValueError(f"side must be BUY or SELL, got {side!r}")


class ExitReason(str, Enum):
    """Why a position is being closed."""

    TAKE_PROFIT = "TAKE_PROFIT"        # |Z| reverted below the exit threshold
    STOP_LOSS_ZSCORE = "STOP_LOSS_ZSCORE"  # |Z| diverged past the stop threshold
    STOP_LOSS_TIME = "STOP_LOSS_TIME"      # held longer than N × half-life


@dataclass(frozen=True)
class EntrySignal:
    """An entry instruction for the two legs of a pair."""

    base_side: Side   # action on S1 (base market)
    quote_side: Side  # action on S2 (quote market)
    zscore: float


@dataclass(frozen=True)
class ExitSignal:
    """An exit instruction with the reason that triggered it."""

    reason: ExitReason
    zscore: float


def evaluate_entry(
    zscore: float,
    *,
    entry_threshold: float | None = None,
) -> EntrySignal | None:
    """
    Decide whether to open a position given the current Z-score.

    Returns an :class:`EntrySignal` when ``|Z| >= entry_threshold``, otherwise
    ``None``. A ``nan`` Z-score (insufficient data / zero-variance window) never
    triggers an entry.

    ``entry_threshold`` defaults to the live ``config.ZSCORE_THRESH``, resolved at
    call time (not frozen at import) so a changed threshold — e.g. the manual-trade
    Z slider in PRD F4.1 — takes effect.
    """
    if entry_threshold is None:
        entry_threshold = config.ZSCORE_THRESH
    if math.isnan(zscore) or abs(zscore) < entry_threshold:
        return None
    if zscore < 0:
        # Spread below mean → expect it to rise → long the spread.
        return EntrySignal(base_side=Side.BUY, quote_side=Side.SELL, zscore=zscore)
    # Spread above mean → expect it to fall → short the spread.
    return EntrySignal(base_side=Side.SELL, quote_side=Side.BUY, zscore=zscore)


def evaluate_exit(
    zscore: float,
    *,
    position_age_hours: float | None = None,
    half_life: float | None = None,
    exit_threshold: float | None = None,
    stop_threshold: float | None = None,
    time_stop_mult: float | None = None,
) -> ExitSignal | None:
    """
    Decide whether to close an open position given the current Z-score and age.

    Precedence (most urgent first):
      1. Stop-loss on divergence: ``|Z| >= stop_threshold`` — the cointegration
         is breaking down; cut the loss.
      2. Take-profit: ``|Z| < exit_threshold`` — the spread has reverted, so the
         trade thesis succeeded. This is ranked above the time stop: a reverted
         spread is a win, not a breakdown, even if the position is also old.
      3. Stop-loss on time: ``position_age_hours > time_stop_mult × half_life``
         (only when both age and a positive, finite half-life are supplied) — held
         too long without reverting, a sign of cointegration breakdown.

    Returns the triggering :class:`ExitSignal`, or ``None`` to hold. A ``nan``
    Z-score still allows the time stop to fire (data may be momentarily missing
    while the position has aged out); a non-finite ``position_age_hours`` is
    ignored so a bad clock/timestamp cannot mask the time stop's preconditions.

    Thresholds default to the live ``config`` values, resolved at call time.
    """
    if exit_threshold is None:
        exit_threshold = config.EXIT_ZSCORE
    if stop_threshold is None:
        stop_threshold = config.STOP_LOSS_ZSCORE
    if time_stop_mult is None:
        time_stop_mult = config.TIME_STOP_HALF_LIFE_MULT

    if not math.isnan(zscore) and abs(zscore) >= stop_threshold:
        return ExitSignal(reason=ExitReason.STOP_LOSS_ZSCORE, zscore=zscore)

    if not math.isnan(zscore) and abs(zscore) < exit_threshold:
        return ExitSignal(reason=ExitReason.TAKE_PROFIT, zscore=zscore)

    if (
        position_age_hours is not None
        and math.isfinite(position_age_hours)
        and half_life is not None
        and math.isfinite(half_life)
        and half_life > 0
        and position_age_hours > time_stop_mult * half_life
    ):
        return ExitSignal(reason=ExitReason.STOP_LOSS_TIME, zscore=zscore)

    return None
