"""Unit tests for the WS2 tradability score + read-time list minimisation."""

from __future__ import annotations

from scan.tradability import (
    max_leg_half_spread,
    minimise_pairs,
    tradability_score,
)


def test_score_rewards_liquidity_speed_and_cointegration():
    # Higher $-vol, shorter half-life, lower p-value → higher score.
    liquid_fast = tradability_score(1_000_000, half_life=6, p_value=0.01)
    thin_slow = tradability_score(10_000, half_life=48, p_value=0.04)
    assert liquid_fast > thin_slow


def test_score_uses_min_leg_volume_as_bottleneck():
    # The score input is the THINNER leg's volume (the caller passes min); a huge
    # base leg can't rescue a tiny quote leg.
    assert tradability_score(10_000, 6, 0.01) < tradability_score(500_000, 6, 0.01)


def test_score_is_zero_on_unknown_or_bad_inputs():
    assert tradability_score(0, 6, 0.01) == 0.0            # unknown liquidity
    assert tradability_score(1_000_000, None, 0.01) == 0.0  # missing half-life
    assert tradability_score(1_000_000, 0, 0.01) == 0.0     # zero half-life
    # A None p-value degrades to coint=1, not a crash.
    assert tradability_score(1_000_000, 6, None) > 0.0


def test_max_leg_half_spread_takes_the_wider_leg():
    assert max_leg_half_spread(0.02, 0.09) == 0.09
    assert max_leg_half_spread(0.09, 0.02) == 0.09


def _p(name, tradability, spread):
    return {"pair": name, "tradability": tradability, "max_half_spread_pct": spread}


def test_minimise_off_by_default_is_identity():
    pairs = [_p("A", 3.0, 0.02), _p("B", 1.0, 0.10)]
    assert minimise_pairs(pairs) == pairs  # both knobs 0 → no-op, order preserved


def test_half_spread_ceiling_drops_wide_pairs():
    pairs = [_p("tight", 1.0, 0.02), _p("wide", 5.0, 0.10)]
    kept = minimise_pairs(pairs, max_half_spread_pct=0.05)
    assert [p["pair"] for p in kept] == ["tight"]  # wide dropped despite higher score


def test_unknown_spread_is_kept_under_ceiling():
    pairs = [{"pair": "mystery", "tradability": 1.0, "max_half_spread_pct": None}]
    assert minimise_pairs(pairs, max_half_spread_pct=0.05) == pairs


def test_top_n_keeps_most_tradable():
    pairs = [_p("lo", 1.0, 0.02), _p("hi", 9.0, 0.02), _p("mid", 5.0, 0.02)]
    kept = minimise_pairs(pairs, top_n=2)
    assert [p["pair"] for p in kept] == ["hi", "mid"]


def test_ceiling_then_top_n_compose():
    pairs = [
        _p("hi-wide", 9.0, 0.10),   # dropped by ceiling first
        _p("hi-tight", 8.0, 0.02),
        _p("lo-tight", 1.0, 0.02),
    ]
    kept = minimise_pairs(pairs, max_half_spread_pct=0.05, top_n=1)
    assert [p["pair"] for p in kept] == ["hi-tight"]
