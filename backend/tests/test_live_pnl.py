"""Unit tests for live two-leg P&L (Phase 5a, trading/pnl.py)."""

from __future__ import annotations

import pytest

from trading.pnl import compute_live_pnl


def test_long_base_short_quote_both_profit():
    # base BUY (long): 100→110 over 2 units = +20; quote SELL (short): 200→190 over 1 = +10.
    p = compute_live_pnl(
        base_side="BUY",
        quote_side="SELL",
        base_size=2.0,
        quote_size=1.0,
        entry_price_leg1=100.0,
        entry_price_leg2=200.0,
        exit_price_leg1=110.0,
        exit_price_leg2=190.0,
    )
    assert p.pnl_leg1 == pytest.approx(20.0)
    assert p.pnl_leg2 == pytest.approx(10.0)
    assert p.pnl == pytest.approx(30.0)


def test_short_base_long_quote_both_loss():
    # base SELL (short): 100→110 over 1 = -10; quote BUY (long): 50→45 over 2 = -10.
    p = compute_live_pnl(
        base_side="SELL",
        quote_side="BUY",
        base_size=1.0,
        quote_size=2.0,
        entry_price_leg1=100.0,
        entry_price_leg2=50.0,
        exit_price_leg1=110.0,
        exit_price_leg2=45.0,
    )
    assert p.pnl_leg1 == pytest.approx(-10.0)
    assert p.pnl_leg2 == pytest.approx(-10.0)
    assert p.pnl == pytest.approx(-20.0)


def test_no_price_move_is_zero():
    p = compute_live_pnl(
        base_side="BUY",
        quote_side="SELL",
        base_size=3.0,
        quote_size=4.0,
        entry_price_leg1=10.0,
        entry_price_leg2=20.0,
        exit_price_leg1=10.0,
        exit_price_leg2=20.0,
    )
    assert p.pnl == pytest.approx(0.0)


def test_to_dict_keys():
    p = compute_live_pnl(
        base_side="BUY", quote_side="SELL", base_size=1, quote_size=1,
        entry_price_leg1=1, entry_price_leg2=1, exit_price_leg1=2, exit_price_leg2=1,
    )
    assert set(p.to_dict()) == {"pnl_leg1", "pnl_leg2", "pnl"}


def test_invalid_side_raises():
    with pytest.raises(ValueError):
        compute_live_pnl(
            base_side="LONG", quote_side="SELL", base_size=1, quote_size=1,
            entry_price_leg1=1, entry_price_leg2=1, exit_price_leg1=1, exit_price_leg2=1,
        )
