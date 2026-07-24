"""
Unit tests for the first-order market-impact cost model (Phase-2 Slice 3).

Pins realized-vol computation, the √-law impact formula (hand-computed +
monotonic in size, decreasing in ADV), and the guards/cap.
"""

from __future__ import annotations

import math

import pytest

from simulation.market_impact import (
    _MAX_IMPACT_PCT,
    impact_pct,
    realized_daily_vol,
)


def test_realized_daily_vol_flat_or_short_is_zero():
    assert realized_daily_vol([]) == 0.0
    assert realized_daily_vol([100.0]) == 0.0
    assert realized_daily_vol([100.0, 100.0, 100.0]) == 0.0  # flat → no vol


def test_realized_daily_vol_matches_hand_computed():
    closes = [100.0, 101.0, 100.0, 102.0]
    rets = [101 / 100 - 1, 100 / 101 - 1, 102 / 100 - 1]
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    expected = math.sqrt(var) * math.sqrt(24.0)
    assert realized_daily_vol(closes) == pytest.approx(expected)


def test_impact_pct_matches_sqrt_law():
    # 100·σ·√(Q/ADV); σ=0.05, Q=$1,000, ADV=$700k/day → ≈0.19% (plan §4.3).
    val = impact_pct(0.05, 1_000.0, 700_000.0)
    assert val == pytest.approx(100 * 0.05 * math.sqrt(1_000 / 700_000))
    assert val == pytest.approx(0.189, abs=1e-2)


def test_impact_pct_monotonic_in_size_sqrt_law():
    small = impact_pct(0.05, 1_000.0, 700_000.0)
    big = impact_pct(0.05, 5_000.0, 700_000.0)
    assert big > small
    assert big / small == pytest.approx(math.sqrt(5), abs=1e-9)  # √-law: ×√5 for 5× size


def test_impact_pct_decreases_with_deeper_adv():
    thin = impact_pct(0.05, 1_000.0, 700_000.0)
    deep = impact_pct(0.05, 1_000.0, 70_000_000.0)
    assert deep < thin


def test_impact_pct_guards_return_zero():
    assert impact_pct(0.0, 1_000.0, 1e6) == 0.0     # no vol
    assert impact_pct(0.05, 0.0, 1e6) == 0.0        # no size
    assert impact_pct(0.05, 1_000.0, 0.0) == 0.0    # unknown ADV
    assert impact_pct(0.05, 1_000.0, -5.0) == 0.0   # bad ADV


def test_impact_pct_is_capped():
    # Degenerate near-zero ADV would blow up → clamped to the cap.
    assert impact_pct(0.5, 1e9, 1.0) == _MAX_IMPACT_PCT
