"""
Engle-Granger cointegration test, OLS hedge ratio, and the pair-analysis
orchestrator — the single source of statistical truth reused by scan, live
trading, simulation, fast-forward replay, and backtest.

Pipeline (PRD §3.1):
  1. Engle-Granger two-step test (statsmodels.coint) → p-value, t-stat, 5% crit.
  2. OLS ``S1 = α + β·S2 + ε`` → hedge ratio β and intercept α (Option-B #1
     includes the intercept; the reference omitted it).
  3. Spread = S1 − β·S2 − α.
  4. OU half-life of the spread.
  5. Keep pairs where p < PVALUE_MAX and 0 < half_life <= MAX_HALF_LIFE_H
     (Option-B #4 tightens the half-life cap to 72h).

This module is pure: no DB, no exchange, no I/O. Callers persist the results.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import statsmodels.api as sm
from numpy.typing import ArrayLike
from statsmodels.tsa.stattools import coint

import config

from .halflife import half_life
from .spread import compute_spread, zero_crossings

# statsmodels.tsa.stattools.coint returns critical values ordered [1%, 5%, 10%].
_CRIT_VALUE_5PCT_INDEX = 1


@dataclass(frozen=True)
class HedgeFit:
    """Result of the cointegrating OLS regression ``S1 = α + β·S2 + ε``."""

    hedge_ratio: float  # β — units of S2 per unit of S1
    intercept: float    # α — 0.0 when fit without an intercept (legacy mode)


@dataclass(frozen=True)
class CointegrationTest:
    """Engle-Granger two-step test output."""

    p_value: float
    t_statistic: float
    critical_value_5pct: float

    def is_cointegrated(self, pvalue_max: float = 0.05) -> bool:
        """
        Engle-Granger acceptance criterion at the given p-value cutoff:
        ``p < pvalue_max`` AND the t-statistic clears the 5% critical value.
        The p-value gate is the single, caller-controlled threshold — there is no
        second hardcoded copy to drift out of sync.
        """
        return self.p_value < pvalue_max and self.t_statistic < self.critical_value_5pct

    @property
    def is_significant(self) -> bool:
        """Convenience for the standard 5% criterion (``is_cointegrated(0.05)``)."""
        return self.is_cointegrated(0.05)


@dataclass(frozen=True)
class PairAnalysis:
    """Full statistical summary of a candidate pair."""

    hedge_ratio: float
    intercept: float
    p_value: float
    t_statistic: float
    critical_value_5pct: float
    half_life: float
    zero_crossings: int
    passes_filter: bool


def fit_hedge_ratio(
    series_1: ArrayLike,
    series_2: ArrayLike,
    *,
    include_intercept: bool = True,
) -> HedgeFit:
    """
    Fit the cointegrating regression ``S1 = α + β·S2 (+ ε)`` by OLS.

    Args:
        series_1: base price series (dependent variable, S1).
        series_2: quote price series (regressor, S2).
        include_intercept: Option-B default True fits and returns α. Pass False
            for the legacy no-intercept form (α forced to 0.0), used to reproduce
            the reference bot in parity tests.

    Returns:
        A :class:`HedgeFit` with β and α.
    """
    s1 = np.asarray(series_1, dtype=np.float64)
    s2 = np.asarray(series_2, dtype=np.float64)

    if include_intercept:
        design = sm.add_constant(s2)
        params = sm.OLS(s1, design).fit().params
        return HedgeFit(hedge_ratio=float(params[1]), intercept=float(params[0]))

    params = sm.OLS(s1, s2).fit().params
    return HedgeFit(hedge_ratio=float(params[0]), intercept=0.0)


def engle_granger(series_1: ArrayLike, series_2: ArrayLike) -> CointegrationTest:
    """
    Run the Engle-Granger two-step cointegration test via ``statsmodels.coint``.

    The test is independent of the hedge-ratio intercept choice — it runs its own
    internal regression — so its outputs match the reference regardless of
    Option-B #1.

    Returns:
        A :class:`CointegrationTest` with p-value, t-statistic, and the 5%
        critical value (``coint`` returns critical values at 1/5/10%).
    """
    s1 = np.asarray(series_1, dtype=np.float64)
    s2 = np.asarray(series_2, dtype=np.float64)
    t_stat, p_value, crit_values = coint(s1, s2)
    return CointegrationTest(
        p_value=float(p_value),
        t_statistic=float(t_stat),
        critical_value_5pct=float(crit_values[_CRIT_VALUE_5PCT_INDEX]),
    )


def analyze_pair(
    series_1: ArrayLike,
    series_2: ArrayLike,
    *,
    include_intercept: bool = True,
    max_half_life: float | None = None,
    pvalue_max: float | None = None,
) -> PairAnalysis:
    """
    Full pair pipeline: cointegration test → hedge ratio → spread → half-life →
    filter decision. This is what the scan calls per candidate pair.

    A pair passes the filter when it is statistically cointegrated
    (``p < pvalue_max`` and the t-stat clears the 5% critical value) **and** its
    spread mean-reverts fast enough (``0 < half_life <= max_half_life``).

    ``max_half_life`` / ``pvalue_max`` default to the live ``config`` values,
    resolved at call time (not frozen at import) so the configured policy is
    honoured even if it changes during the process lifetime.
    """
    if max_half_life is None:
        max_half_life = config.MAX_HALF_LIFE_H
    if pvalue_max is None:
        pvalue_max = config.PVALUE_MAX

    test = engle_granger(series_1, series_2)
    fit = fit_hedge_ratio(series_1, series_2, include_intercept=include_intercept)
    spread = compute_spread(series_1, series_2, fit.hedge_ratio, fit.intercept)
    hl = half_life(spread)
    crossings = zero_crossings(spread)

    cointegrated = test.is_cointegrated(pvalue_max)
    half_life_ok = np.isfinite(hl) and 0 < hl <= max_half_life
    passes = bool(cointegrated and half_life_ok)

    return PairAnalysis(
        hedge_ratio=fit.hedge_ratio,
        intercept=fit.intercept,
        p_value=test.p_value,
        t_statistic=test.t_statistic,
        critical_value_5pct=test.critical_value_5pct,
        half_life=hl,
        zero_crossings=crossings,
        passes_filter=passes,
    )
