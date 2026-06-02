"""Unit tests for manual-trade per-leg P&L (Phase 4, PRD F4.7)."""

from __future__ import annotations

import pytest

from manual.pnl import compute_manual_pnl


def test_long_spread_both_legs_move_favourably():
    # z < 0 → long base (leg1), short quote (leg2).
    # Base rises (good for long), quote falls (good for short) → both legs profit.
    r = compute_manual_pnl(
        z_score=-2.0,
        entry_price_leg1=100.0,
        entry_price_leg2=50.0,
        exit_price_leg1=110.0,  # +10%
        exit_price_leg2=45.0,   # -10%
        capital_leg1_usd=100.0,
        capital_leg2_usd=100.0,
    )
    assert r.base_is_long is True
    # leg1: 1 unit * (110-100) * +1 = +10
    assert r.pnl_leg1 == pytest.approx(10.0)
    # leg2: 2 units * (45-50) * -1 = +10
    assert r.pnl_leg2 == pytest.approx(10.0)
    assert r.pnl == pytest.approx(20.0)


def test_short_spread_direction_flips_signs():
    # z > 0 → short base (leg1), long quote (leg2).
    r = compute_manual_pnl(
        z_score=2.0,
        entry_price_leg1=100.0,
        entry_price_leg2=50.0,
        exit_price_leg1=110.0,  # base up → bad for short
        exit_price_leg2=55.0,   # quote up → good for long
        capital_leg1_usd=100.0,
        capital_leg2_usd=100.0,
    )
    assert r.base_is_long is False
    # leg1 short: 1 * (110-100) * -1 = -10
    assert r.pnl_leg1 == pytest.approx(-10.0)
    # leg2 long: 2 * (55-50) * +1 = +10
    assert r.pnl_leg2 == pytest.approx(10.0)
    assert r.pnl == pytest.approx(0.0)


def test_no_price_change_is_zero_pnl():
    r = compute_manual_pnl(
        z_score=-1.7,
        entry_price_leg1=100.0,
        entry_price_leg2=50.0,
        exit_price_leg1=100.0,
        exit_price_leg2=50.0,
        capital_leg1_usd=250.0,
        capital_leg2_usd=250.0,
    )
    assert r.pnl == pytest.approx(0.0)


def test_capital_scales_pnl_linearly():
    base = dict(
        z_score=-2.0,
        entry_price_leg1=100.0,
        entry_price_leg2=50.0,
        exit_price_leg1=110.0,
        exit_price_leg2=45.0,
    )
    small = compute_manual_pnl(capital_leg1_usd=100.0, capital_leg2_usd=100.0, **base)
    big = compute_manual_pnl(capital_leg1_usd=300.0, capital_leg2_usd=300.0, **base)
    assert big.pnl == pytest.approx(3 * small.pnl)


def test_nonpositive_entry_price_raises():
    with pytest.raises(ValueError):
        compute_manual_pnl(
            z_score=-1.0,
            entry_price_leg1=0.0,
            entry_price_leg2=50.0,
            exit_price_leg1=10.0,
            exit_price_leg2=45.0,
            capital_leg1_usd=100.0,
            capital_leg2_usd=100.0,
        )
