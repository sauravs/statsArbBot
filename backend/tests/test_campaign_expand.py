"""Unit tests for the WS3 campaign grid expansion (pure)."""

from __future__ import annotations

import pytest

from backtest.campaign import (
    MAX_CONFIGS,
    CampaignSpecError,
    cost_flags,
    expand_campaign_spec,
)

_W = [
    {"label": "s2", "start": "2025-11-07T00:00:00Z", "end": "2026-03-01T00:00:00Z"},
    {"label": "s3", "start": "2025-07-16T00:00:00Z", "end": "2025-11-07T00:00:00Z"},
]


def test_product_of_axes_and_windows():
    spec = {
        "name": "entry-sweep",
        "windows": _W,
        "axes": {"entry_threshold": [3.0, 3.5], "zscore_window": [21]},
    }
    configs = expand_campaign_spec(spec)
    # 2 entry × 1 window-size × 2 windows = 4 configs.
    assert len(configs) == 4
    # Each carries the window span + the axis values + a descriptive name.
    combos = {(c["entry_threshold"], c["start_time"]) for c in configs}
    assert combos == {
        (3.0, _W[0]["start"]), (3.5, _W[0]["start"]),
        (3.0, _W[1]["start"]), (3.5, _W[1]["start"]),
    }
    assert all(c["name"].startswith("entry-sweep · ") for c in configs)
    assert any("s2" in c["name"] for c in configs)


def test_base_params_applied_and_overridden_by_axes():
    spec = {
        "name": "c",
        "windows": [_W[0]],
        "base": {"usd_per_trade": 1000, "entry_threshold": 1.5},
        "axes": {"entry_threshold": [3.0]},  # axis wins over base
    }
    (cfg,) = expand_campaign_spec(spec)
    assert cfg["usd_per_trade"] == 1000       # from base
    assert cfg["entry_threshold"] == 3.0      # axis overrides base
    assert cfg["end_time"] == _W[0]["end"]


def test_no_axes_is_one_config_per_window():
    spec = {"name": "c", "windows": _W}
    configs = expand_campaign_spec(spec)
    assert len(configs) == 2
    assert {c["name"] for c in configs} == {"c · s2", "c · s3"}


def test_missing_windows_rejected():
    with pytest.raises(CampaignSpecError):
        expand_campaign_spec({"name": "c", "axes": {"entry_threshold": [3.0]}})
    with pytest.raises(CampaignSpecError):
        expand_campaign_spec({"name": "c", "windows": []})


def test_bad_window_rejected():
    with pytest.raises(CampaignSpecError):
        expand_campaign_spec({"windows": [{"start": "x"}]})  # missing end


def test_empty_axis_list_rejected():
    with pytest.raises(CampaignSpecError):
        expand_campaign_spec({"windows": _W, "axes": {"entry_threshold": []}})


def test_grid_explosion_guarded():
    # 501 windows × 1 = 501 > MAX_CONFIGS → rejected.
    big = [{"label": f"w{i}", "start": "a", "end": "b"} for i in range(MAX_CONFIGS + 1)]
    with pytest.raises(CampaignSpecError):
        expand_campaign_spec({"windows": big})


def test_deterministic_order():
    spec = {"name": "c", "windows": _W, "axes": {"entry_threshold": [3.5, 3.0]}}
    a = [c["name"] for c in expand_campaign_spec(spec)]
    b = [c["name"] for c in expand_campaign_spec(spec)]
    assert a == b  # stable across calls


def test_cost_flags_default_on():
    assert cost_flags({}) == {"per_market_slippage": True, "market_impact": True}
    assert cost_flags({"cost_flags": {"market_impact": False}}) == {
        "per_market_slippage": True,
        "market_impact": False,
    }
