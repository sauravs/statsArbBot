"""
Unit tests for the simulation cost model (PRD F6.3) — pure functions, no DB.

Covers sizing/sides per direction, adverse slippage, the per-leg signed P&L on
exit, funding sign, and that ``net = gross − fees + funding`` (the convention that
fixes the prototype's double-counted entry fee).
"""

from __future__ import annotations

import pytest

from simulation.costs import (
    LONG_BASE,
    SHORT_BASE,
    compute_exit_pnl,
    compute_funding,
    compute_unrealized_pnl,
    direction_from_z,
    simulate_pair_entry,
)


def test_direction_from_z_matches_statcore_rule():
    assert direction_from_z(-2.0) == LONG_BASE   # z<0 → long the spread
    assert direction_from_z(2.0) == SHORT_BASE    # z≥0 → short the spread
    assert direction_from_z(0.0) == SHORT_BASE


def test_entry_sizing_and_sides_long_base():
    fill = simulate_pair_entry(
        base_market="A", quote_market="B", direction=LONG_BASE,
        base_price=100.0, quote_price=50.0, hedge_ratio=2.0,
        usd_per_trade=100.0, slippage_pct=0.0, taker_fee_pct=0.0,
    )
    # base_size = 100/100 = 1 ; quote_size = base_size·β = 2
    assert fill.base.size == pytest.approx(1.0)
    assert fill.quote.size == pytest.approx(2.0)
    # LONG_BASE = BUY base / SELL quote
    assert fill.base.side == "BUY" and fill.quote.side == "SELL"
    assert fill.total_fee == 0.0


def test_entry_sides_short_base():
    fill = simulate_pair_entry(
        base_market="A", quote_market="B", direction=SHORT_BASE,
        base_price=100.0, quote_price=50.0, hedge_ratio=1.0,
        usd_per_trade=100.0, slippage_pct=0.0, taker_fee_pct=0.0,
    )
    assert fill.base.side == "SELL" and fill.quote.side == "BUY"


def test_slippage_is_adverse():
    fill = simulate_pair_entry(
        base_market="A", quote_market="B", direction=LONG_BASE,
        base_price=100.0, quote_price=50.0, hedge_ratio=1.0,
        usd_per_trade=100.0, slippage_pct=0.1, taker_fee_pct=0.0,
    )
    # BUY fills above, SELL fills below.
    assert fill.base.fill_price == pytest.approx(100.0 * 1.001)
    assert fill.quote.fill_price == pytest.approx(50.0 * 0.999)


def test_per_leg_slippage_overrides_flat_on_entry():
    # base/quote get their OWN half-spreads; the flat slippage_pct is ignored per leg.
    fill = simulate_pair_entry(
        base_market="A", quote_market="B", direction=LONG_BASE,
        base_price=100.0, quote_price=50.0, hedge_ratio=1.0,
        usd_per_trade=100.0, slippage_pct=0.0, taker_fee_pct=0.0,
        base_slippage_pct=0.1, quote_slippage_pct=0.2,
    )
    # BUY base fills above by its own 0.1%; SELL quote fills below by its own 0.2%.
    assert fill.base.fill_price == pytest.approx(100.0 * 1.001)
    assert fill.quote.fill_price == pytest.approx(50.0 * 0.998)


def test_per_leg_slippage_defaults_to_flat_when_none():
    # Only base overridden; quote falls back to the flat slippage_pct.
    fill = simulate_pair_entry(
        base_market="A", quote_market="B", direction=LONG_BASE,
        base_price=100.0, quote_price=50.0, hedge_ratio=1.0,
        usd_per_trade=100.0, slippage_pct=0.05, taker_fee_pct=0.0,
        base_slippage_pct=0.1,
    )
    assert fill.base.fill_price == pytest.approx(100.0 * 1.001)   # own 0.1%
    assert fill.quote.fill_price == pytest.approx(50.0 * 0.9995)  # flat 0.05%


def test_per_leg_slippage_on_exit():
    pnl = compute_exit_pnl(
        direction=LONG_BASE,
        entry_base_px=100.0, entry_quote_px=50.0,
        exit_base_px=100.0, exit_quote_px=50.0,
        base_size=1.0, quote_size=1.0,
        entry_fee=0.0, slippage_pct=0.0, taker_fee_pct=0.0,
        base_slippage_pct=0.1, quote_slippage_pct=0.2,
    )
    # LONG_BASE closes: SELL base (fills below 0.1%), BUY quote (fills above 0.2%).
    # base leg long: (99.9 − 100)·1 = −0.1 ; quote leg short: (50 − 50.1)·1 = −0.1.
    assert pnl["gross_pnl"] == pytest.approx(-0.2, abs=1e-6)


def test_entry_fee_on_notional():
    fill = simulate_pair_entry(
        base_market="A", quote_market="B", direction=LONG_BASE,
        base_price=100.0, quote_price=50.0, hedge_ratio=1.0,
        usd_per_trade=100.0, slippage_pct=0.0, taker_fee_pct=0.05,
    )
    # base notional 100, quote notional 50 → fee 0.05% each = 0.05 + 0.025
    assert fill.total_fee == pytest.approx(0.075)


def test_exit_pnl_long_base_gross_no_costs():
    pnl = compute_exit_pnl(
        direction=LONG_BASE,
        entry_base_px=100.0, entry_quote_px=50.0,
        exit_base_px=110.0, exit_quote_px=48.0,
        base_size=1.0, quote_size=2.0,
        entry_fee=0.0, slippage_pct=0.0, taker_fee_pct=0.0,
    )
    # base long 1·(110−100)=+10 ; quote short 2·(50−48)=+4 → gross 14
    assert pnl["gross_pnl"] == pytest.approx(14.0)
    assert pnl["net_pnl"] == pytest.approx(14.0)
    assert pnl["fee_cost"] == 0.0


def test_exit_pnl_short_base_matches_live_convention():
    # Mirror the live P&L test: short base 1u 100→90 = +10 ; long quote 2u 50→55 = +10.
    pnl = compute_exit_pnl(
        direction=SHORT_BASE,
        entry_base_px=100.0, entry_quote_px=50.0,
        exit_base_px=90.0, exit_quote_px=55.0,
        base_size=1.0, quote_size=2.0,
        entry_fee=0.0, slippage_pct=0.0, taker_fee_pct=0.0,
    )
    assert pnl["gross_pnl"] == pytest.approx(20.0)


def test_net_pnl_nets_entry_and_exit_fees_and_funding():
    pnl = compute_exit_pnl(
        direction=LONG_BASE,
        entry_base_px=100.0, entry_quote_px=50.0,
        exit_base_px=100.0, exit_quote_px=50.0,  # gross 0
        base_size=1.0, quote_size=1.0,
        entry_fee=0.10, slippage_pct=0.0, taker_fee_pct=0.05,
        funding_pnl=0.30,
    )
    # exit fee = (100·1 + 50·1)·0.05% = 0.075 ; total fee = 0.10 + 0.075 = 0.175
    assert pnl["fee_cost"] == pytest.approx(0.175)
    # net = gross(0) − fee(0.175) + funding(0.30) = 0.125
    assert pnl["net_pnl"] == pytest.approx(0.125)
    assert pnl["funding_pnl"] == pytest.approx(0.30)


def test_unrealized_pnl_marks_to_market():
    u = compute_unrealized_pnl(
        direction=LONG_BASE,
        entry_base_px=100.0, entry_quote_px=50.0,
        base_price=105.0, quote_price=50.0,
        base_size=1.0, quote_size=1.0,
    )
    assert u == pytest.approx(5.0)


def test_funding_long_base_pays_base_receives_quote():
    # LONG_BASE: long base pays funding (negative), short quote receives (positive).
    f = compute_funding(
        direction=LONG_BASE,
        base_size=1.0, quote_size=1.0,
        entry_base_px=100.0, entry_quote_px=100.0,
        base_rate=0.01, quote_rate=0.01,
    )
    # −0.01·100 + 0.01·100 = 0
    assert f == pytest.approx(0.0)
    f2 = compute_funding(
        direction=LONG_BASE,
        base_size=1.0, quote_size=1.0,
        entry_base_px=100.0, entry_quote_px=100.0,
        base_rate=0.02, quote_rate=0.0,
    )
    assert f2 == pytest.approx(-2.0)  # pays funding on the long base leg


def test_funding_short_base_is_opposite_sign():
    f = compute_funding(
        direction=SHORT_BASE,
        base_size=1.0, quote_size=1.0,
        entry_base_px=100.0, entry_quote_px=100.0,
        base_rate=0.02, quote_rate=0.0,
    )
    assert f == pytest.approx(2.0)  # short base receives funding
