"""
Ornstein-Uhlenbeck half-life of mean reversion.

The spread of a cointegrated pair is modelled as an OU process. Discretising and
regressing the spread's first difference on its lagged level,

    Δspread_t = a + b · spread_{t−1} + ε_t,

the reversion speed is ``−b`` and the half-life — the expected time to revert
halfway to the mean — is

    half_life = −ln(2) / b.

A short half-life means fast reversion (good for trading); a non-negative ``b``
means the spread is not mean-reverting, so the half-life is undefined and we
return ``nan`` (the pair filter rejects it).

The fit reproduces the reference implementation: the first lag/return value is
backfilled from the second so no row is dropped.
(research.md §4; reference: pythonforfinance.net mean-reversion part 2.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from numpy.typing import ArrayLike


def half_life(spread: ArrayLike, *, rounded: bool = False) -> float:
    """
    Estimate the OU half-life (in observation periods — hours, on hourly bars).

    Args:
        spread: the spread series (must contain at least 2 finite points).
        rounded: if True, round to the nearest whole period (the reference bot's
            behaviour, used by parity tests). Default False keeps full precision.

    Returns:
        The half-life as a float, or ``nan`` if the spread is not mean-reverting
        (regression slope ``b >= 0``) or cannot be estimated.
    """
    s = pd.Series(np.asarray(spread, dtype=np.float64)).dropna().reset_index(drop=True)
    if s.size < 2:
        return float("nan")

    lag = s.shift(1)
    lag.iloc[0] = lag.iloc[1]
    ret = s - lag
    ret.iloc[0] = ret.iloc[1]

    # has_constant="add" forces a two-column design even when the lag is
    # constant (otherwise add_constant silently drops the redundant column and
    # the slope index would not exist).
    design = sm.add_constant(lag.to_numpy(), has_constant="add")
    try:
        result = sm.OLS(ret.to_numpy(), design).fit()
    except (ValueError, np.linalg.LinAlgError):
        return float("nan")

    # params = [intercept a, slope b]; add_constant prepends the constant.
    # Mean reversion requires a meaningfully negative slope. A slope at or above
    # ~0 (including floating-point noise around zero for a trend / random walk)
    # implies no reversion — half-life is undefined. The epsilon rejects speeds
    # so slow (half-life > ~7e8 periods) that the pair is never tradeable.
    b = result.params[1]
    if not np.isfinite(b) or b >= -1e-9:
        return float("nan")

    hl = -np.log(2) / b
    return float(round(hl, 0)) if rounded else float(hl)
