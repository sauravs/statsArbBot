"""
Unit tests for the multiple-testing correction module (Phase-2 Slice 4, gate B3):
Deflated Sharpe Ratio + PBO/CSCV. Formula checks + the key overfit/skill cases.
"""

from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist

import pytest

from stats.deflated_sharpe import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    kurtosis,
    pbo_cscv,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
    skewness,
)


# ── moments ──────────────────────────────────────────────────────────────────


def test_sharpe_and_moment_edge_cases():
    assert sharpe_ratio([]) == 0.0
    assert sharpe_ratio([1.0]) == 0.0
    assert sharpe_ratio([2.0, 2.0, 2.0]) == 0.0        # zero variance
    assert skewness([1.0, 1.0]) == 0.0
    assert kurtosis([1.0, 1.0]) == 3.0                  # normal default


def test_sharpe_matches_mean_over_std():
    r = [0.01, -0.02, 0.03, 0.00, 0.015]
    n = len(r)
    mean = sum(r) / n
    var = sum((x - mean) ** 2 for x in r) / n
    assert sharpe_ratio(r) == pytest.approx(mean / math.sqrt(var))


# ── PSR / DSR ────────────────────────────────────────────────────────────────


def test_psr_matches_documented_formula():
    sr, bench, T, skew, kurt = 0.1, 0.0, 100, 0.0, 3.0
    denom = 1 - skew * sr + ((kurt - 1) / 4) * sr ** 2
    expected = NormalDist().cdf((sr - bench) * math.sqrt(T - 1) / math.sqrt(denom))
    assert probabilistic_sharpe_ratio(sr, bench, T, skew, kurt) == pytest.approx(expected)


def test_psr_is_a_probability_and_monotonic_in_sr():
    lo = probabilistic_sharpe_ratio(0.05, 0.0, 200, 0.0, 3.0)
    hi = probabilistic_sharpe_ratio(0.20, 0.0, 200, 0.0, 3.0)
    assert 0.0 <= lo <= hi <= 1.0
    # A higher benchmark lowers the probability.
    assert probabilistic_sharpe_ratio(0.20, 0.15, 200, 0.0, 3.0) < hi


def test_expected_max_sharpe_grows_with_trials_and_dispersion():
    assert expected_max_sharpe(1, 0.5) == 0.0            # a single trial → no deflation
    assert expected_max_sharpe(10, 0.0) == 0.0           # no dispersion → no deflation
    more_trials = expected_max_sharpe(100, 0.5)
    fewer = expected_max_sharpe(10, 0.5)
    assert more_trials > fewer > 0.0
    assert expected_max_sharpe(50, 1.0) > expected_max_sharpe(50, 0.5)


def test_deflation_lowers_significance_as_trials_grow():
    # A modestly positive return series.
    returns = [0.02, -0.01, 0.03, 0.01, -0.005, 0.025, 0.015, -0.02, 0.02, 0.01] * 6
    single = deflated_sharpe_ratio(returns, n_trials=1, trial_sr_variance=0.0)
    searched = deflated_sharpe_ratio(returns, n_trials=69, trial_sr_variance=0.25)
    assert 0.0 <= searched < single <= 1.0  # correcting for 69 trials only lowers it


def test_deflated_sharpe_high_for_strong_series_few_trials():
    # Consistently positive with modest noise → strong Sharpe, one trial → near 1.
    returns = [0.02, 0.018, 0.022, 0.019, 0.021, 0.017, 0.023, 0.02] * 12
    dsr = deflated_sharpe_ratio(returns, n_trials=1, trial_sr_variance=0.0)
    assert dsr > 0.99


# ── PBO / CSCV ───────────────────────────────────────────────────────────────


_BS = 5
_WITHIN = [1.0, 1.1, 0.9, 1.05, 0.95]  # mean 1.0, non-zero variance


def _overfit_matrix():
    """Each config wins in exactly one block-pair (IS) and loses in its complement
    (OOS): the IS-best is always the OOS-worst → PBO ≈ 1."""
    blocks = [list(range(i * _BS, (i + 1) * _BS)) for i in range(4)]
    pairs = list(combinations(range(4), 2))  # 6 configs
    T, N = 4 * _BS, len(pairs)
    M = [[0.0] * N for _ in range(T)]
    for c, good_pair in enumerate(pairs):
        for b in range(4):
            sign = 1.0 if b in good_pair else -1.0
            for j, r in enumerate(blocks[b]):
                M[r][c] = sign * _WITHIN[j]
    return M


_TIGHT = [1.0, 1.01, 0.99, 1.005, 0.995]  # mean 1.0, MUCH smaller variance → higher SR


def _skillful_matrix():
    """One config is positive with low relative noise in every block, so it has the
    highest Sharpe both IS and OOS (Sharpe is scale-invariant — genuine skill comes
    from a *tighter* mean/std, not a bigger number). The rest are the overfit
    configs. The dominant config is best IS and OOS → PBO ≈ 0."""
    M = _overfit_matrix()
    for r in range(len(M)):
        M[r].append(_TIGHT[r % _BS])  # extra column: always-good, high-Sharpe config
    return M


def test_pbo_near_one_for_overfit_set():
    assert pbo_cscv(_overfit_matrix(), n_splits=4) == pytest.approx(1.0)


def test_pbo_near_zero_for_a_dominant_config():
    assert pbo_cscv(_skillful_matrix(), n_splits=4) == pytest.approx(0.0)


def test_pbo_guards_small_input():
    assert pbo_cscv([], n_splits=4) == 0.0
    assert pbo_cscv([[0.1]], n_splits=4) == 0.0        # only 1 config
    assert pbo_cscv([[0.1, 0.2]], n_splits=4) == 0.0   # fewer rows than splits
