"""
Rolling Z-score of the spread — the live trading signal.

    z_t = (spread_t − rolling_mean_t) / rolling_std_t

The mean and standard deviation are computed over a trailing window (default 21,
configurable via ``config.ZSCORE_WINDOW``). The standard deviation uses the
sample convention (ddof=1), matching pandas' ``rolling().std()`` and the
reference bot. The first ``window − 1`` observations are ``NaN`` because the
window is not yet full.

This fixes the prototype's simulation bug, which approximated the std as
``abs(spread) * 0.02`` instead of a true rolling window (research.md / PRD §7).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray


def rolling_zscore(spread: ArrayLike, window: int) -> NDArray[np.float64]:
    """
    Compute the trailing rolling Z-score series of ``spread``.

    Args:
        spread: the spread series.
        window: trailing window length (number of observations).

    Returns:
        A float64 array the same length as ``spread``; the first ``window − 1``
        entries are ``NaN``.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    s = pd.Series(np.asarray(spread, dtype=np.float64))
    mean = s.rolling(window=window).mean()
    std = s.rolling(window=window).std()  # ddof=1 (sample std)
    z = (s - mean) / std
    return z.to_numpy(dtype=np.float64)


def latest_zscore(spread: ArrayLike, window: int) -> float:
    """
    The current (most recent) Z-score — what entry/exit decisions act on.

    Returns ``nan`` if there are fewer than ``window`` observations or the
    trailing window has zero variance (constant spread → undefined Z-score).
    """
    s = np.asarray(spread, dtype=np.float64)
    if s.size < window:
        return float("nan")
    tail = s[-window:]
    std = tail.std(ddof=1)
    if std == 0 or np.isnan(std):
        return float("nan")
    return float((tail[-1] - tail.mean()) / std)
