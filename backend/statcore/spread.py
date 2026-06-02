"""
Spread construction and the zero-crossings pair-quality metric.

The spread is the residual of the cointegrating regression. Option-B change #1
(see research.md §2, ADR-0002) subtracts the OLS intercept α so the spread is
the *stationary* residual centred on zero rather than a residual plus a constant
drift:

    spread_t = S1_t − β·S2_t − α          (Option-B, this rewrite)
    spread_t = S1_t − β·S2_t              (legacy reference, α = 0)

The legacy form is recoverable by passing ``alpha=0.0`` — used by the parity
tests to reproduce the ground-truth reference CSVs exactly.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray


def compute_spread(
    series_1: ArrayLike,
    series_2: ArrayLike,
    hedge_ratio: float,
    intercept: float = 0.0,
) -> NDArray[np.float64]:
    """
    Build the cointegration spread ``S1 − β·S2 − α``.

    Args:
        series_1: base price series (S1).
        series_2: quote price series (S2).
        hedge_ratio: OLS slope β.
        intercept: OLS intercept α. Defaults to 0.0 (legacy/no-intercept form);
            pass the fitted α for the Option-B spread.

    Returns:
        The spread as a float64 array, aligned element-wise with the inputs.
    """
    s1 = np.asarray(series_1, dtype=np.float64)
    s2 = np.asarray(series_2, dtype=np.float64)
    if s1.shape != s2.shape:
        raise ValueError(f"series length mismatch: {s1.shape} vs {s2.shape}")
    return s1 - hedge_ratio * s2 - intercept


def zero_crossings(spread: ArrayLike) -> int:
    """
    Count how many times the spread crosses its own mean.

    A higher count is empirical evidence of reliable mean reversion (Do & Faff
    2010; research.md §7). The spread is demeaned first, then sign changes
    between consecutive observations are counted — this reproduces the reference
    bot's ``zero_crossings`` column.

    Note: ``np.sign(0) == 0``, so an observation landing exactly on the mean is
    counted as two sign changes (into 0, then out of 0). On float price data an
    exact tie with the mean is effectively never hit, so this matches the
    reference in practice; the metric is a relative quality heuristic, not an
    exact crossing count.
    """
    s = np.asarray(spread, dtype=np.float64)
    s = s[~np.isnan(s)]
    if s.size < 2:
        return 0
    demeaned = s - s.mean()
    return int((np.diff(np.sign(demeaned)) != 0).sum())
