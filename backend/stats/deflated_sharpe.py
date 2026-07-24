"""
Multiple-testing correction for strategy selection (Phase-2 Slice 4, gate B3) —
pure functions, stdlib only (``statistics.NormalDist``; NO scipy / mlfinlab).

Two in-house implementations of Bailey & López de Prado's work:

  * **Deflated Sharpe Ratio (DSR)** — the probability a strategy's *true* Sharpe is
    positive, after correcting for (a) the **number of trials** searched (69 configs
    here → the "best" is plausibly the luckiest draw), (b) return **non-normality**
    (skew/kurtosis), and (c) **sample length**. DSR > 0.95 ⇒ significant at 5% *after*
    the search is accounted for. This is what gate B3 needs.
  * **PBO (Probability of Backtest Overfitting)** via CSCV (Combinatorially Symmetric
    Cross-Validation) — the probability the in-sample-best config underperforms the
    median out-of-sample. PBO near 1 ⇒ the leaderboard is overfit.

References: Bailey & López de Prado, "The Deflated Sharpe Ratio" (2014) and "The
Probability of Backtest Overfitting" (2015); reference impl esvhd/pypbo.
"""

from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist

_N = NormalDist()  # standard normal
_EULER_MASCHERONI = 0.5772156649015329


# ── moments ──────────────────────────────────────────────────────────────────


def sharpe_ratio(returns: list[float]) -> float:
    """Per-observation Sharpe = mean / population-std. 0 if <2 obs or zero variance."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n  # population
    if var <= 0:
        return 0.0
    return mean / math.sqrt(var)


def skewness(returns: list[float]) -> float:
    """Population skewness. 0 for <3 obs or zero variance."""
    n = len(returns)
    if n < 3:
        return 0.0
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    if m2 <= 0:
        return 0.0
    m3 = sum((r - mean) ** 3 for r in returns) / n
    return m3 / m2 ** 1.5


def kurtosis(returns: list[float]) -> float:
    """Population kurtosis, **non-excess** (normal = 3). 3.0 for <4 obs / zero var."""
    n = len(returns)
    if n < 4:
        return 3.0
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    if m2 <= 0:
        return 3.0
    m4 = sum((r - mean) ** 4 for r in returns) / n
    return m4 / m2 ** 2


# ── probabilistic / deflated Sharpe ──────────────────────────────────────────


def probabilistic_sharpe_ratio(
    observed_sr: float,
    benchmark_sr: float,
    n_obs: int,
    skew: float,
    kurt: float,
) -> float:
    """PSR: P(true SR > ``benchmark_sr``) given the observed SR and the return
    distribution's skew/kurtosis (Bailey & López de Prado). All Sharpes are
    per-observation. Returns a probability in [0, 1]."""
    if n_obs < 2:
        return 0.0
    denom = 1.0 - skew * observed_sr + ((kurt - 1.0) / 4.0) * observed_sr ** 2
    if denom <= 0:
        # Degenerate distribution — fall back to the sign of the edge.
        return 1.0 if observed_sr > benchmark_sr else 0.0
    z = (observed_sr - benchmark_sr) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return _N.cdf(z)


def expected_max_sharpe(n_trials: int, trial_sr_std: float) -> float:
    """Expected **maximum** Sharpe under the null (no skill) across ``n_trials``
    independent trials — the deflation benchmark. Grows with both the number of
    trials and the dispersion of the trial Sharpes."""
    if n_trials <= 1 or trial_sr_std <= 0:
        return 0.0
    z1 = _N.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return trial_sr_std * ((1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)


def deflated_sharpe_ratio(
    returns: list[float],
    n_trials: int,
    trial_sr_variance: float,
) -> float:
    """Deflated Sharpe Ratio: PSR benchmarked against the expected-max Sharpe of an
    ``n_trials`` search whose trial Sharpes have variance ``trial_sr_variance``.

    ``returns`` is the candidate's per-observation return series. Returns P(true SR >
    deflated benchmark) ∈ [0, 1]; **> 0.95 clears gate B3** (significant after the
    69-config search). With a single trial (or zero SR dispersion) it degrades to the
    plain PSR against 0.
    """
    sr = sharpe_ratio(returns)
    sr_star = expected_max_sharpe(n_trials, math.sqrt(max(0.0, trial_sr_variance)))
    return probabilistic_sharpe_ratio(
        sr, sr_star, len(returns), skewness(returns), kurtosis(returns)
    )


# ── PBO via CSCV ─────────────────────────────────────────────────────────────


def _sharpe_over_rows(matrix: list[list[float]], rows: tuple[int, ...], col: int) -> float:
    return sharpe_ratio([matrix[r][col] for r in rows])


def pbo_cscv(returns_matrix: list[list[float]], n_splits: int = 8) -> float:
    """Probability of Backtest Overfitting via CSCV (López de Prado).

    ``returns_matrix`` is ``T_obs × N_configs`` (row = time sub-observation, column =
    config's return there). The T rows are cut into ``n_splits`` (even) contiguous
    blocks; for every way to choose half the blocks as in-sample (the rest
    out-of-sample), the IS-best config's OOS relative rank gives a logit λ. **PBO =
    fraction of splits where λ ≤ 0** (IS-best lands at/below the OOS median) — near 1
    means the leaderboard is overfit. Returns 0.0 if the matrix is too small.
    """
    T = len(returns_matrix)
    if T == 0:
        return 0.0
    N = len(returns_matrix[0])
    if N < 2 or n_splits < 2:
        return 0.0
    if n_splits % 2 == 1:
        n_splits -= 1
    if T < n_splits:
        return 0.0

    block = T // n_splits
    blocks = [tuple(range(i * block, (i + 1) * block)) for i in range(n_splits)]
    all_ids = set(range(n_splits))

    logits_le_zero = 0
    total = 0
    for is_ids in combinations(range(n_splits), n_splits // 2):
        is_rows = tuple(r for b in is_ids for r in blocks[b])
        oos_rows = tuple(r for b in (all_ids - set(is_ids)) for r in blocks[b])
        is_perf = [_sharpe_over_rows(returns_matrix, is_rows, c) for c in range(N)]
        oos_perf = [_sharpe_over_rows(returns_matrix, oos_rows, c) for c in range(N)]
        best = max(range(N), key=lambda c: is_perf[c])
        # OOS relative rank of the IS-best (fraction of configs it beats OOS).
        worse = sum(1 for c in range(N) if oos_perf[c] < oos_perf[best])
        omega = (worse + 0.5) / N  # in (0, 1), 0.5-corrected to avoid 0/1
        lam = math.log(omega / (1.0 - omega))
        total += 1
        if lam <= 0.0:
            logits_le_zero += 1
    return logits_le_zero / total if total else 0.0
