"""Unit tests for leaderboard DSR significance (Phase-2 Slice 4)."""

from __future__ import annotations

from stats.significance import compute_leaderboard_dsr, strategy_window_returns


def _strat(sid, net_pnls, cap=10_000.0):
    return {
        "id": sid,
        "starting_capital": cap,
        "per_window": [{"net_pnl": p} for p in net_pnls],
    }


def test_window_returns_normalises_by_capital():
    assert strategy_window_returns(_strat("a", [100, -50, 200])) == [0.01, -0.005, 0.02]


def test_window_returns_guards():
    assert strategy_window_returns({"id": "x", "starting_capital": 0, "per_window": [{"net_pnl": 1}]}) == []
    assert strategy_window_returns({"id": "x", "starting_capital": 1e4, "per_window": []}) == []


def test_leaderboard_dsr_shape_and_bounds():
    strats = [_strat(f"s{i}", [10 * i, -5, 8, 3, -2, 6]) for i in range(1, 6)]
    out = compute_leaderboard_dsr(strats)
    assert out["n_trials"] == 5
    assert set(out["dsr"]) == {f"s{i}" for i in range(1, 6)}
    assert all(0.0 <= v <= 1.0 for v in out["dsr"].values())


def test_leaderboard_dsr_skips_too_short_series():
    out = compute_leaderboard_dsr([_strat("long", [1, 2, 3, 4]), _strat("short", [1])])
    assert "long" in out["dsr"] and "short" not in out["dsr"]
    assert out["n_trials"] == 1
