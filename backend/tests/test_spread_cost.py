"""
Unit tests for the per-market half-spread cost model (Phase-2 Slice 1).

Pins the resolution order (override → volume curve → default), the curve's
calibration to the measured anchors, its monotonicity/clamps, and the per-run
``build_slippage_map`` helper.
"""

from __future__ import annotations

import pytest

from simulation import spread_cost
from simulation.spread_cost import (
    DEFAULT_HALF_SPREAD_PCT,
    _CAP_PCT,
    _FLOOR_PCT,
    build_slippage_map,
    filter_universe,
    half_spread_pct,
)


def test_curve_hits_measured_anchors():
    # $1M/hr → median 0.0165% ; $10k/hr → P90 0.0615% (the two calibration knots).
    assert half_spread_pct("ANY", 1_000_000.0) == pytest.approx(0.0165, abs=1e-9)
    assert half_spread_pct("ANY", 10_000.0) == pytest.approx(0.0615, abs=1e-9)


def test_curve_is_monotone_decreasing_in_volume():
    spreads = [half_spread_pct("X", dv) for dv in (1e3, 1e4, 1e5, 1e6, 1e7)]
    assert spreads == sorted(spreads, reverse=True)


def test_curve_clamps_to_measured_floor_and_cap():
    # Ultra-liquid → floored at the measured P25; dust → never exceeds measured max.
    assert half_spread_pct("BTC", 1e12) == pytest.approx(_FLOOR_PCT)
    assert half_spread_pct("DUST", 1e-6) <= _CAP_PCT
    # Every curve output stays within [floor, cap].
    for dv in (1e-3, 1.0, 1e3, 1e6, 1e9, 1e15):
        hs = half_spread_pct("X", dv)
        assert _FLOOR_PCT <= hs <= _CAP_PCT


def test_default_when_no_volume():
    assert half_spread_pct("UNKNOWN", None) == pytest.approx(DEFAULT_HALF_SPREAD_PCT)


def test_override_table_wins_over_curve(monkeypatch):
    monkeypatch.setitem(spread_cost.SEED_HALF_SPREAD_PCT, "FOO-USD", 0.5)
    # Override beats the curve even at a volume that would otherwise floor.
    assert half_spread_pct("FOO-USD", 1e12) == 0.5


def test_demo_markets_resolve_deterministically():
    # Demo markets carry no volume; they resolve from the demo table, not the curve.
    assert half_spread_pct("DEMO1-USD") == pytest.approx(0.02)
    assert half_spread_pct("NOISE2-USD", None) == pytest.approx(0.12)


def test_build_slippage_map_uses_volumes_and_falls_back():
    markets = ["DEMO1-USD", "LIQUID", "THIN"]
    volumes = {"LIQUID": 1_000_000.0, "THIN": 10_000.0}  # DEMO1 absent → demo table
    m = build_slippage_map(markets, volumes)
    assert m["DEMO1-USD"] == pytest.approx(0.02)
    assert m["LIQUID"] == pytest.approx(0.0165, abs=1e-9)
    assert m["THIN"] == pytest.approx(0.0615, abs=1e-9)


def test_build_slippage_map_no_volumes_is_demo_or_default():
    m = build_slippage_map(["DEMO2-USD", "SOMECOIN"])
    assert m["DEMO2-USD"] == pytest.approx(0.04)
    assert m["SOMECOIN"] == pytest.approx(DEFAULT_HALF_SPREAD_PCT)


# ── Universe liquidity/spread filter (Phase-2 Slice 2) ───────────────────────


def test_filter_universe_off_by_default():
    m = ["A", "B", "C"]
    assert filter_universe(m, {"A": 1.0, "B": 2.0}) == m  # both thresholds 0 → no-op


def test_filter_universe_dollar_volume_floor():
    dv = {"BIG": 2_000_000.0, "SMALL": 5_000.0}
    assert filter_universe(["BIG", "SMALL"], dv, min_dollar_volume=1_000_000.0) == ["BIG"]


def test_filter_universe_keeps_unknown_volume_on_floor():
    # A market absent from dollar_volumes (unknown vol) is kept — never dropped on
    # missing data (this is what makes the floor a no-op in fake/demo mode).
    kept = filter_universe(["BIG", "MYSTERY"], {"BIG": 2e6}, min_dollar_volume=1e6)
    assert kept == ["BIG", "MYSTERY"]


def test_filter_universe_half_spread_ceiling():
    dv = {"BIG": 1e8, "TINY": 2_000.0}  # BIG→~floor 0.0086%; TINY→~0.077%
    assert filter_universe(["BIG", "TINY"], dv, max_half_spread_pct=0.05) == ["BIG"]


def test_filter_universe_ceiling_uses_override_table(monkeypatch):
    monkeypatch.setitem(spread_cost.SEED_HALF_SPREAD_PCT, "WIDE", 0.2)
    monkeypatch.setitem(spread_cost.SEED_HALF_SPREAD_PCT, "TIGHT", 0.01)
    assert filter_universe(["WIDE", "TIGHT"], {}, max_half_spread_pct=0.05) == ["TIGHT"]


def test_filter_universe_both_filters_compose():
    dv = {"BIG": 2e6, "SMALL": 5_000.0, "MID": 1.5e6}
    kept = filter_universe(
        ["BIG", "SMALL", "MID"], dv, min_dollar_volume=1e6, max_half_spread_pct=0.05
    )
    assert kept == ["BIG", "MID"]  # SMALL dropped by floor; BIG/MID clear both
