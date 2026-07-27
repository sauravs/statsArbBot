"""
Campaign grid expansion (Phase-3 WS3).

A *campaign* automates a phase-1-style sweep: a parameter **grid** (the `spec`) is
expanded into many concrete strategy configs, each of which becomes a `Strategy` row
the execution queue (WS3 Slice 2) runs with bounded concurrency. This module is the
**pure** expansion + validation — no DB, no I/O — so the grid math is trivially
testable and the same expansion is reproducible from the stored spec.

Spec shape (operator-approved 2026-07-27 — explicit windows, not named spans)::

    {
      "name": "entry-sweep",
      "windows": [                       # REQUIRED, >= 1 — the OOS date spans
        {"label": "s2", "start": "2025-11-07T00:00:00Z", "end": "2026-03-01T00:00:00Z"},
        ...
      ],
      "axes": {                          # optional — each key crossed combinatorially
        "entry_threshold": [3.0, 3.5],
        "zscore_window": [21, 30]
      },
      "base": {"usd_per_trade": 1000},   # optional — fixed params on every config
      "cost_flags": {                    # optional — honest defaults (ON)
        "per_market_slippage": true, "market_impact": true
      },
      "concurrency": 2                   # optional — max members running at once
    }

Expansion = the Cartesian product of the axis value-lists, crossed with the windows,
one config per combination. Each config is a `StrategyBody`-shaped dict (the router
validates it) carrying the window's start/end + the axis values on top of `base`.

`cost_flags` are **campaign-level**, not per-strategy: `PER_MARKET_SLIPPAGE` /
`MARKET_IMPACT` are process-global engine flags, so they are recorded on the spec and
honoured by the execution queue at run time (Slice 2), not stamped onto each config.
"""

from __future__ import annotations

import itertools
from typing import Any

# Guard against a fat-finger grid that would create thousands of runs on a 2-vCPU box.
MAX_CONFIGS = 500


class CampaignSpecError(ValueError):
    """Raised when a campaign spec is malformed (mapped to HTTP 422 by the router)."""


def _validate_window(w: Any, i: int) -> dict:
    if not isinstance(w, dict) or "start" not in w or "end" not in w:
        raise CampaignSpecError(
            f"windows[{i}] must be an object with 'start' and 'end'"
        )
    return {
        "label": str(w.get("label") or f"w{i + 1}"),
        "start": w["start"],
        "end": w["end"],
    }


def _validate_axes(axes: Any) -> dict[str, list]:
    if not isinstance(axes, dict):
        raise CampaignSpecError("axes must be an object of {param: [values]}")
    out: dict[str, list] = {}
    for k, v in axes.items():
        if not isinstance(v, list) or not v:
            raise CampaignSpecError(f"axes['{k}'] must be a non-empty list")
        out[str(k)] = list(v)
    return out


def _axis_summary(combo: dict) -> str:
    """A short, deterministic label of the axis values in a config (for the name)."""
    return ", ".join(f"{k}={combo[k]}" for k in sorted(combo))


def expand_campaign_spec(spec: dict) -> list[dict]:
    """Expand a campaign grid `spec` into concrete strategy config dicts.

    Deterministic order: axes are combined by sorted key, and windows are the outer
    loop so a config's siblings across spans are adjacent. Raises
    ``CampaignSpecError`` on a malformed spec or if the product exceeds
    ``MAX_CONFIGS``.
    """
    if not isinstance(spec, dict):
        raise CampaignSpecError("spec must be an object")

    name = str(spec.get("name") or "Campaign").strip() or "Campaign"

    windows_raw = spec.get("windows")
    if not isinstance(windows_raw, list) or not windows_raw:
        raise CampaignSpecError("spec.windows must be a non-empty list")
    windows = [_validate_window(w, i) for i, w in enumerate(windows_raw)]

    axes = _validate_axes(spec.get("axes", {}))
    base = spec.get("base", {})
    if not isinstance(base, dict):
        raise CampaignSpecError("spec.base must be an object")

    # Cartesian product of the axis values, by sorted key for determinism.
    axis_keys = sorted(axes)
    value_lists = [axes[k] for k in axis_keys]
    combos = [dict(zip(axis_keys, values)) for values in itertools.product(*value_lists)] or [{}]

    total = len(combos) * len(windows)
    if total > MAX_CONFIGS:
        raise CampaignSpecError(
            f"grid expands to {total} configs (> {MAX_CONFIGS}); narrow the spec"
        )

    configs: list[dict] = []
    for w in windows:
        for combo in combos:
            cfg: dict = {**base, **combo}
            cfg["start_time"] = w["start"]
            cfg["end_time"] = w["end"]
            summary = _axis_summary(combo)
            cfg["name"] = f"{name} · {summary} · {w['label']}" if summary else f"{name} · {w['label']}"
            configs.append(cfg)
    return configs


def cost_flags(spec: dict) -> dict:
    """The campaign's honest-cost intent (defaults ON — phase-2 cost model).

    These are process-global engine flags, applied by the execution queue at run
    time (WS3 Slice 2), so they live on the campaign, not on each strategy config.
    """
    raw = spec.get("cost_flags") or {}
    return {
        "per_market_slippage": bool(raw.get("per_market_slippage", True)),
        "market_impact": bool(raw.get("market_impact", True)),
    }
