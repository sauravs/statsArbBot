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
    entry_threshold: float = config.ZSCORE_THRESH,
) -> EntrySignal | None:
    """
    Decide whether to open a position given the current Z-score.

    Returns an :class:`EntrySignal` when ``|Z| >= entry_threshold``, otherwise
    ``None``. A ``nan`` Z-score (insufficient data / zero-variance window) never
    triggers an entry.
    """
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
    exit_threshold: float = config.EXIT_ZSCORE,
    stop_threshold: float = config.STOP_LOSS_ZSCORE,
    time_stop_mult: float = config.TIME_STOP_HALF_LIFE_MULT,
) -> ExitSignal | None:
    """
    Decide whether to close an open position given the current Z-score and age.

    Precedence (most urgent first):
      1. Stop-loss on divergence: ``|Z| >= stop_threshold``.
      2. Stop-loss on time: ``position_age_hours > time_stop_mult × half_life``
         (only when both age and a positive, finite half-life are supplied).
      3. Take-profit: ``|Z| < exit_threshold``.

    Returns the triggering :class:`ExitSignal`, or ``None`` to hold. A ``nan``
    Z-score still allows the time stop to fire (data may be momentarily missing
    while the position has aged out).
    """
    if not math.isnan(zscore) and abs(zscore) >= stop_threshold:
        return ExitSignal(reason=ExitReason.STOP_LOSS_ZSCORE, zscore=zscore)

    if (
        position_age_hours is not None
        and half_life is not None
        and math.isfinite(half_life)
        and half_life > 0
        and position_age_hours > time_stop_mult * half_life
    ):
        return ExitSignal(reason=ExitReason.STOP_LOSS_TIME, zscore=zscore)

    if not math.isnan(zscore) and abs(zscore) < exit_threshold:
        return ExitSignal(reason=ExitReason.TAKE_PROFIT, zscore=zscore)

    return None
