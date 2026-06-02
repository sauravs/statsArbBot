"""
Phase 1 statistical-core tests.

Three groups:
  1. PARITY (the phase gate) — reproduce the ground-truth reference CSVs to
     machine precision, proving the math primitives are correct before any
     consumer relies on them.
  2. OPTION-B — assert the four research-backed changes (ADR-0002) are in effect.
  3. UNIT — behaviour and edge cases of each pure function.

Reference fixtures (committed under tests/fixtures/, copied from the gitignored
"Old Reference Resources/oldCodeRef_Main_Source/dydxRefResource/"):
  * ref_backtest_maticusdt_stxusdt.csv — 200 rows of MATIC/STX prices plus the
    reference Spread and ZScore columns (3_backtest_file.csv).
  * ref_cointegrated_pairs.csv — the scan summary; row (MATICUSDT, STXUSDT) gives
    p_value, t_value, c_value, hedge_ratio, zero_crossings (2_cointegrated_pairs.csv).

The reference computed the spread with the hedge ratio rounded to 2 dp (1.29) and
no intercept; the parity tests use those same inputs so the comparison isolates
the spread / z-score / half-life / zero-crossing math from the OLS estimate.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from statcore import (
    ExitReason,
    Side,
    analyze_pair,
    compute_spread,
    engle_granger,
    evaluate_entry,
    evaluate_exit,
    fit_hedge_ratio,
    half_life,
    latest_zscore,
    rolling_zscore,
    zero_crossings,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ZSCORE_WINDOW = 21  # the reference WINDOW; matches config.ZSCORE_WINDOW default
REF_HEDGE_RATIO = 1.29  # rounded β the reference used to build Spread/ZScore


@pytest.fixture(scope="module")
def maticusdt_stxusdt() -> pd.DataFrame:
    """200 rows of MATIC/STX prices + reference Spread and ZScore."""
    return pd.read_csv(FIXTURES / "ref_backtest_maticusdt_stxusdt.csv", index_col=0)


@pytest.fixture(scope="module")
def ref_pair_row() -> pd.Series:
    """The (MATICUSDT, STXUSDT) row from the reference scan summary."""
    df = pd.read_csv(FIXTURES / "ref_cointegrated_pairs.csv", index_col=0)
    row = df[(df["sym_1"] == "MATICUSDT") & (df["sym_2"] == "STXUSDT")]
    assert len(row) == 1, "expected exactly one MATIC/STX row in the reference"
    return row.iloc[0]


# ─────────────────────────── 1. PARITY (gate) ────────────────────────────────


def test_parity_engle_granger_matches_reference(maticusdt_stxusdt, ref_pair_row):
    s1 = maticusdt_stxusdt["MATICUSDT"].to_numpy(float)
    s2 = maticusdt_stxusdt["STXUSDT"].to_numpy(float)
    test = engle_granger(s1, s2)

    assert abs(test.t_statistic - ref_pair_row["t_value"]) < 0.01   # ref -4.77
    assert abs(test.critical_value_5pct - ref_pair_row["c_value"]) < 0.01  # ref -3.37
    assert test.p_value < 0.01  # ref reports 0.0
    assert test.is_significant


def test_parity_legacy_hedge_ratio_matches_reference(maticusdt_stxusdt, ref_pair_row):
    s1 = maticusdt_stxusdt["MATICUSDT"].to_numpy(float)
    s2 = maticusdt_stxusdt["STXUSDT"].to_numpy(float)
    fit = fit_hedge_ratio(s1, s2, include_intercept=False)

    assert fit.intercept == 0.0
    assert round(fit.hedge_ratio, 2) == REF_HEDGE_RATIO  # 1.29
    assert abs(fit.hedge_ratio - ref_pair_row["hedge_ratio"]) < 0.01


def test_parity_spread_matches_reference_column(maticusdt_stxusdt):
    s1 = maticusdt_stxusdt["MATICUSDT"].to_numpy(float)
    s2 = maticusdt_stxusdt["STXUSDT"].to_numpy(float)
    spread = compute_spread(s1, s2, REF_HEDGE_RATIO, intercept=0.0)

    np.testing.assert_allclose(
        spread, maticusdt_stxusdt["Spread"].to_numpy(float), atol=1e-9
    )


def test_parity_rolling_zscore_matches_reference_column(maticusdt_stxusdt):
    s1 = maticusdt_stxusdt["MATICUSDT"].to_numpy(float)
    s2 = maticusdt_stxusdt["STXUSDT"].to_numpy(float)
    spread = compute_spread(s1, s2, REF_HEDGE_RATIO, intercept=0.0)
    z = rolling_zscore(spread, ZSCORE_WINDOW)
    ref_z = maticusdt_stxusdt["ZScore"].to_numpy(float)

    # First window-1 entries are NaN in both ours and the reference.
    assert np.all(np.isnan(z[: ZSCORE_WINDOW - 1]))
    assert np.all(np.isnan(ref_z[: ZSCORE_WINDOW - 1]))

    mask = ~np.isnan(ref_z)
    np.testing.assert_allclose(z[mask], ref_z[mask], atol=1e-9)


def test_parity_zero_crossings_matches_reference(maticusdt_stxusdt, ref_pair_row):
    s1 = maticusdt_stxusdt["MATICUSDT"].to_numpy(float)
    s2 = maticusdt_stxusdt["STXUSDT"].to_numpy(float)
    spread = compute_spread(s1, s2, REF_HEDGE_RATIO, intercept=0.0)

    assert zero_crossings(spread) == int(ref_pair_row["zero_crossings"])  # 43


def test_parity_half_life_regression_lock(maticusdt_stxusdt):
    """No reference value is published for this pair; lock the computed result."""
    s1 = maticusdt_stxusdt["MATICUSDT"].to_numpy(float)
    s2 = maticusdt_stxusdt["STXUSDT"].to_numpy(float)
    spread = compute_spread(s1, s2, REF_HEDGE_RATIO, intercept=0.0)

    assert half_life(spread, rounded=True) == 3.0
    assert abs(half_life(spread) - 3.376) < 0.01


# ─────────────────────────── 2. OPTION-B changes ─────────────────────────────


def test_optionb_1_intercept_included_by_default(maticusdt_stxusdt):
    """#1 — the production fit returns a non-zero intercept and a shifted spread."""
    s1 = maticusdt_stxusdt["MATICUSDT"].to_numpy(float)
    s2 = maticusdt_stxusdt["STXUSDT"].to_numpy(float)

    fit = fit_hedge_ratio(s1, s2)  # include_intercept=True default
    assert fit.intercept != 0.0
    assert abs(fit.intercept - (-0.0524)) < 0.01
    assert abs(fit.hedge_ratio - 1.3368) < 0.01

    legacy = fit_hedge_ratio(s1, s2, include_intercept=False)
    spread_b = compute_spread(s1, s2, fit.hedge_ratio, fit.intercept)
    spread_legacy = compute_spread(s1, s2, legacy.hedge_ratio, legacy.intercept)
    assert not np.allclose(spread_b, spread_legacy)

    analysis = analyze_pair(s1, s2)  # default path
    assert analysis.intercept != 0.0


def test_optionb_2_hard_stop_loss_on_zscore():
    """#2 — |Z| >= 4.0 triggers a stop-loss that was previously unwired."""
    assert evaluate_exit(4.0).reason is ExitReason.STOP_LOSS_ZSCORE
    assert evaluate_exit(-4.5).reason is ExitReason.STOP_LOSS_ZSCORE
    # Just inside the stop and above the exit band → hold.
    assert evaluate_exit(3.9) is None


def test_optionb_2_time_based_stop():
    """#2 — a position older than 3 × half-life is force-closed."""
    sig = evaluate_exit(2.0, position_age_hours=31.0, half_life=10.0)
    assert sig is not None and sig.reason is ExitReason.STOP_LOSS_TIME
    # Within the time budget and outside the exit band → hold.
    assert evaluate_exit(2.0, position_age_hours=29.0, half_life=10.0) is None


def test_optionb_3_exit_below_half_not_zero_crossing():
    """#3 — take-profit fires at |Z| < 0.5, not at a zero crossing."""
    assert evaluate_exit(0.4).reason is ExitReason.TAKE_PROFIT
    assert evaluate_exit(-0.49).reason is ExitReason.TAKE_PROFIT
    # 0.5 is the boundary (strict <) and 0.3-from-zero is still open territory.
    assert evaluate_exit(0.5) is None
    assert evaluate_exit(0.8) is None


def test_optionb_4_half_life_cap_filters_slow_pairs(maticusdt_stxusdt):
    """#4 — the half-life cap rejects pairs that revert too slowly."""
    s1 = maticusdt_stxusdt["MATICUSDT"].to_numpy(float)
    s2 = maticusdt_stxusdt["STXUSDT"].to_numpy(float)

    # The pair's half-life (~3h) passes a 72h cap but fails a 2h cap.
    assert analyze_pair(s1, s2, max_half_life=72.0).passes_filter
    assert not analyze_pair(s1, s2, max_half_life=2.0).passes_filter


# ─────────────────────────── 3. UNIT / edge cases ────────────────────────────


def test_compute_spread_length_mismatch_raises():
    with pytest.raises(ValueError):
        compute_spread([1.0, 2.0, 3.0], [1.0, 2.0], 1.0)


def test_zero_crossings_constant_is_zero():
    assert zero_crossings([5.0, 5.0, 5.0, 5.0]) == 0


def test_zero_crossings_ignores_nans():
    # Demeaned [1,-1,1,-1] crosses on every step → 3 crossings.
    assert zero_crossings([1.0, np.nan, -1.0, 1.0, -1.0]) == 3


def test_rolling_zscore_requires_window_at_least_two():
    with pytest.raises(ValueError):
        rolling_zscore([1.0, 2.0, 3.0], 1)


def test_rolling_zscore_nan_prefix_and_length():
    data = list(range(50))
    z = rolling_zscore(data, ZSCORE_WINDOW)
    assert len(z) == 50
    assert np.all(np.isnan(z[: ZSCORE_WINDOW - 1]))
    assert not np.isnan(z[ZSCORE_WINDOW - 1])


def test_latest_zscore_matches_rolling_last(maticusdt_stxusdt):
    s1 = maticusdt_stxusdt["MATICUSDT"].to_numpy(float)
    s2 = maticusdt_stxusdt["STXUSDT"].to_numpy(float)
    spread = compute_spread(s1, s2, REF_HEDGE_RATIO, intercept=0.0)
    assert abs(latest_zscore(spread, ZSCORE_WINDOW) - rolling_zscore(spread, ZSCORE_WINDOW)[-1]) < 1e-12


def test_latest_zscore_undefined_cases():
    assert np.isnan(latest_zscore([1.0, 2.0], ZSCORE_WINDOW))  # too few points
    assert np.isnan(latest_zscore([3.0] * 30, ZSCORE_WINDOW))  # zero variance


def test_half_life_non_mean_reverting_is_nan():
    # A pure upward trend does not revert → slope b >= 0 → undefined half-life.
    assert np.isnan(half_life(np.arange(100, dtype=float)))


def test_half_life_constant_is_nan():
    assert np.isnan(half_life([2.0] * 50))


def test_evaluate_entry_directions():
    # Z < 0 → spread below mean → BUY base, SELL quote.
    long_spread = evaluate_entry(-2.0)
    assert long_spread.base_side is Side.BUY and long_spread.quote_side is Side.SELL
    # Z > 0 → spread above mean → SELL base, BUY quote.
    short_spread = evaluate_entry(2.0)
    assert short_spread.base_side is Side.SELL and short_spread.quote_side is Side.BUY


def test_evaluate_entry_threshold_boundary_and_nan():
    assert evaluate_entry(1.5) is not None        # |Z| == threshold enters
    assert evaluate_entry(1.49) is None            # below threshold holds
    assert evaluate_entry(float("nan")) is None    # no data → no entry


def test_evaluate_exit_stop_takes_precedence_over_take_profit():
    # Even an impossibly small |Z| cannot occur with |Z| >= stop, but verify the
    # stop wins when both a stop and time condition could apply.
    sig = evaluate_exit(4.0, position_age_hours=1000.0, half_life=1.0)
    assert sig.reason is ExitReason.STOP_LOSS_ZSCORE


def test_evaluate_exit_nan_zscore_allows_time_stop_only():
    nan = float("nan")
    # No age info → cannot decide → hold.
    assert evaluate_exit(nan) is None
    # Aged out → time stop fires despite missing Z-score.
    sig = evaluate_exit(nan, position_age_hours=100.0, half_life=10.0)
    assert sig.reason is ExitReason.STOP_LOSS_TIME


def test_evaluate_exit_hold_in_open_band():
    # Between exit (0.5) and stop (4.0), with a fresh position → hold.
    assert evaluate_exit(2.0, position_age_hours=1.0, half_life=10.0) is None
