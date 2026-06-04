"""
statcore — the pure statistical engine for statsArbBot.

The single source of algorithmic truth (PRD §3, PLAN Phase 1). Every consumer
(scan, live trading, real-time simulation, fast-forward replay, backtest) imports
its math from here so behaviour cannot drift between code paths. The module is
pure: no database, no exchange, no I/O.

The four Option-B research changes (ADR-0002) live here:
  #1 spread includes the OLS intercept α      → spread.compute_spread / cointegration
  #2 hard stop-loss + time stop               → signals.evaluate_exit
  #3 exit at |Z| < 0.5 (not zero-crossing)    → signals.evaluate_exit
  #4 half-life cap tightened to 72h           → cointegration.analyze_pair
"""

from __future__ import annotations

from .cointegration import (
    CointegrationTest,
    HedgeFit,
    PairAnalysis,
    analyze_pair,
    engle_granger,
    fit_hedge_ratio,
)
from .halflife import half_life
from .pnl import leg_pnl, side_sign
from .signals import (
    EntrySignal,
    ExitReason,
    ExitSignal,
    Side,
    evaluate_entry,
    evaluate_exit,
    opposite_side,
)
from .spread import compute_spread, zero_crossings
from .zscore import latest_zscore, rolling_zscore

__all__ = [
    # cointegration
    "CointegrationTest",
    "HedgeFit",
    "PairAnalysis",
    "analyze_pair",
    "engle_granger",
    "fit_hedge_ratio",
    # spread
    "compute_spread",
    "zero_crossings",
    # half-life
    "half_life",
    # zscore
    "rolling_zscore",
    "latest_zscore",
    # pnl
    "leg_pnl",
    "side_sign",
    # signals
    "EntrySignal",
    "ExitSignal",
    "ExitReason",
    "Side",
    "evaluate_entry",
    "evaluate_exit",
    "opposite_side",
]
