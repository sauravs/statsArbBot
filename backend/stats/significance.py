"""
Leaderboard significance (Phase-2 Slice 4, gate B3) — apply the Deflated Sharpe
Ratio across the saved-strategy search so no config is judged on an uncorrected
leaderboard.

**DSR is wired to the leaderboard; PBO is not.** PBO/CSCV requires N configs
evaluated over the *same* observations, but the saved configs span different date
ranges (s1–s4), so a leaderboard-wide PBO is ill-defined. PBO stays a validated tool
(``stats.deflated_sharpe.pbo_cscv``) for a controlled same-window overfitting study;
the dashboard surfaces **DSR** per config.
"""

from __future__ import annotations

from statistics import pvariance

from stats.deflated_sharpe import deflated_sharpe_ratio, sharpe_ratio

# A config needs at least this many walk-forward windows to have a return series
# meaningful enough to score.
_MIN_WINDOWS = 2


def strategy_window_returns(strategy: dict) -> list[float]:
    """Per-window return series: ``per_window[i].net_pnl / starting_capital``."""
    per_window = strategy.get("per_window") or []
    cap = strategy.get("starting_capital") or 0.0
    if cap <= 0:
        return []
    return [(w.get("net_pnl") or 0.0) / cap for w in per_window]


def compute_leaderboard_dsr(strategies: list[dict], min_windows: int = _MIN_WINDOWS) -> dict:
    """DSR for every scoreable saved strategy, deflated for the size of the search.

    The **trials** are all configs with ≥ ``min_windows`` windows; the deflation uses
    their count (N) and the variance of their Sharpes. Returns
    ``{n_trials, trial_sr_variance, dsr: {id: value}}`` — ``dsr`` in [0,1]; **> 0.95
    clears gate B3** (significant after correcting for the search).
    """
    trials = [s for s in strategies if len(strategy_window_returns(s)) >= min_windows]
    srs = [sharpe_ratio(strategy_window_returns(s)) for s in trials]
    n_trials = len(trials)
    trial_var = pvariance(srs) if len(srs) >= 2 else 0.0
    dsr = {
        s["id"]: deflated_sharpe_ratio(
            strategy_window_returns(s), n_trials, trial_var
        )
        for s in trials
    }
    return {"n_trials": n_trials, "trial_sr_variance": trial_var, "dsr": dsr}
