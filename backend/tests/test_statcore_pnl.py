"""Unit tests for the shared per-leg P&L primitive (Phase 10, statcore/pnl.py).

The primitive is the single home for the signed leg arithmetic that the live,
manual, and simulation P&L cores all delegate to (issue #18).
"""

from __future__ import annotations

import pytest

from statcore import Side, leg_pnl, side_sign


def test_side_sign_long_and_short():
    assert side_sign("BUY") == 1.0
    assert side_sign("SELL") == -1.0
    # Accepts the Side enum as well as its string value.
    assert side_sign(Side.BUY) == 1.0
    assert side_sign(Side.SELL) == -1.0


def test_side_sign_rejects_unknown():
    with pytest.raises(ValueError):
        side_sign("LONG")


def test_leg_pnl_long_profits_on_rise():
    # BUY 2 units, 100 → 110 = +20.
    assert leg_pnl(side="BUY", entry_price=100.0, exit_price=110.0, size=2.0) == pytest.approx(20.0)


def test_leg_pnl_short_profits_on_fall():
    # SELL 1 unit, 200 → 190 = +10.
    assert leg_pnl(side="SELL", entry_price=200.0, exit_price=190.0, size=1.0) == pytest.approx(10.0)


def test_leg_pnl_no_move_is_zero():
    assert leg_pnl(side="BUY", entry_price=50.0, exit_price=50.0, size=9.0) == 0.0


def test_leg_pnl_rejects_unknown_side():
    with pytest.raises(ValueError):
        leg_pnl(side="HOLD", entry_price=1.0, exit_price=2.0, size=1.0)
