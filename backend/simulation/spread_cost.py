"""
Per-market half-spread cost model (Phase-2 Slice 1) — pure functions, no DB / IO.

The flat ``slippage_pct`` the sim/backtest charges every fill is a single number for
all markets, but the real cost of crossing the spread is *market-dependent*: a
liquid perp costs a basis point, a thin alt costs tens. This module resolves a
per-market **half-spread** (percent, per leg) so the honest backtest can charge
each leg what that market actually costs to cross.

Resolution order (``half_spread_pct``):
  1. **Override table** ``SEED_HALF_SPREAD_PCT`` — real, measured per-coin
     half-spreads. **Empty by default**: the 160-coin measurement behind the
     aggregate percentiles below was an ephemeral live-order-book snapshot that was
     never persisted, so there is no per-coin table to seed from yet. Real
     measurements go here as they are captured. (Operator decision 2026-07-24:
     use the volume curve now, keep this as the extensible override hook.)
  2. **Volume → half-spread curve** — the workhorse. Maps a market's typical
     dollar-volume (per hour) to a half-spread, calibrated to the measured
     *aggregate* distribution (see below). This is a liquidity **proxy**, not a
     per-coin measurement — documented as such.
  3. **Default** — the measured mean, when no volume is available (e.g. the
     offline demo source, which carries no volume).

Measured aggregate half-spread distribution (2026-07-22 execution-economics work,
160 coins, 97% leg-fill coverage): P25 **0.0086%**, median **0.0165%**, mean
**0.0316%**, P90 **0.0615%**, max **0.279%** (``docs/strategy.md`` §execution).

Standing verdict (``docs/PHASE2_STRATEGY_PLAN.md`` §4): raising the liquidity floor
does **not** create edge — the gross lives in the thinnest markets. This model
exists to charge cost *honestly per market*, not to chase alpha.
"""

from __future__ import annotations

import math

# ── Real per-coin overrides (measured half-spreads, percent per leg) ──────────
# Empty until real per-coin measurements are captured; see module docstring.
SEED_HALF_SPREAD_PCT: dict[str, float] = {}

# ── Deterministic half-spreads for the synthetic offline/demo markets ─────────
# Used ONLY under SCAN_DATA_SOURCE=fake (the demo candle source has no volume), so
# a fake-mode backtest yields an asserted, network-free net in unit/e2e tests. A
# real venue never lists a DEMO*/NOISE* symbol, so this can never leak into a live
# cost. Kept separate from SEED_HALF_SPREAD_PCT so the override table stays "real
# measurements only".
_DEMO_HALF_SPREAD_PCT: dict[str, float] = {
    "DEMO1-USD": 0.02,
    "DEMO2-USD": 0.04,
    "DEMO3-USD": 0.06,
    "DEMO4-USD": 0.08,
    "NOISE1-USD": 0.10,
    "NOISE2-USD": 0.12,
}

# ── Volume → half-spread curve, calibrated to the measured percentiles ────────
# A market's half-spread falls log-linearly with its hourly dollar-volume between
# two measured anchors, clamped to the measured P25 (floor) and max (cap):
#   • $1M/hr  → 0.0165%  (median half-spread)
#   • $10k/hr → 0.0615%  (P90 half-spread)
# Slope/intercept are derived from these anchors so the calibration is legible.
_ANCHOR_HI_DV = 1_000_000.0   # $/hr
_ANCHOR_HI_HS = 0.0165        # % (measured median)
_ANCHOR_LO_DV = 10_000.0      # $/hr
_ANCHOR_LO_HS = 0.0615        # % (measured P90)
_FLOOR_PCT = 0.0086           # measured P25 — most-liquid tier
_CAP_PCT = 0.279              # measured max — thinnest market

# half_spread% = _SLOPE·log10(dv) + _INTERCEPT, clamped to [_FLOOR_PCT, _CAP_PCT].
_SLOPE = (_ANCHOR_LO_HS - _ANCHOR_HI_HS) / (
    math.log10(_ANCHOR_LO_DV) - math.log10(_ANCHOR_HI_DV)
)
_INTERCEPT = _ANCHOR_HI_HS - _SLOPE * math.log10(_ANCHOR_HI_DV)

# Default when no dollar-volume is available: the measured mean.
DEFAULT_HALF_SPREAD_PCT = 0.0316


def _volume_curve(dollar_volume: float) -> float:
    """Half-spread % from hourly dollar-volume (log-linear, clamped)."""
    dv = max(float(dollar_volume), 1.0)  # log10 guard; sub-$1/hr is dust anyway
    raw = _SLOPE * math.log10(dv) + _INTERCEPT
    return min(_CAP_PCT, max(_FLOOR_PCT, raw))


def half_spread_pct(market: str, dollar_volume: float | None = None) -> float:
    """Resolve a market's per-leg half-spread (percent).

    Override table → volume curve → measured-mean default. ``dollar_volume`` is the
    market's typical **hourly** dollar-volume (``close × volume``); pass ``None``
    when unknown (falls through to the default, or the demo table for demo markets).
    """
    if market in SEED_HALF_SPREAD_PCT:
        return SEED_HALF_SPREAD_PCT[market]
    if market in _DEMO_HALF_SPREAD_PCT:
        return _DEMO_HALF_SPREAD_PCT[market]
    if dollar_volume is None:
        return DEFAULT_HALF_SPREAD_PCT
    return _volume_curve(dollar_volume)


def build_slippage_map(
    markets: list[str], dollar_volumes: dict[str, float] | None = None
) -> dict[str, float]:
    """Per-market half-spread map for a backtest run: ``{market: half_spread_pct}``.

    ``dollar_volumes`` maps market → hourly dollar-volume (empty/omitted in fake
    mode, where markets resolve via the demo table / default).
    """
    dv = dollar_volumes or {}
    return {m: half_spread_pct(m, dv.get(m)) for m in markets}
