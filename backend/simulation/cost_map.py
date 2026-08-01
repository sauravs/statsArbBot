"""
Shared per-market cost map (Phase-2 Slices 1 & 3, generalised in Phase 5).

Builds ``{market: half_spread_or_flat + impact}`` (percent, per leg) — the single
piece of arithmetic that turns a market's *liquidity* into what a fill actually
costs. It lived inside ``backtest/engine.py`` and was therefore **backtest-only**,
which meant the real-time simulation charged a flat slippage and no impact at all
and was systematically more optimistic than the backtest that produced the
project's NO-GO verdict (``docs/PHASE5_PAPER_TRADING_PLAN.md`` §1).

Extracting it here makes it what CONTEXT.md says the statistical core should be: one
source of truth, reused by backtest and simulation alike. The backtest keeps a thin
adapter so its numbers are bit-for-bit unchanged — the Phase-4 campaign results are
the control, and a refactor that moved them would be a defect.

- **Base** cost per leg is the market's half-spread (Slice 1, when
  ``PER_MARKET_SLIPPAGE``) else the caller's flat ``slippage_pct``.
- **Impact** (Slice 3, when ``MARKET_IMPACT``) adds a size-aware ``σ·√(Q/ADV)``
  term: σ from the supplied closes, ADV = mean hourly dollar-volume × 24,
  Q = per-leg notional.

Real mode reads per-market dollar-volume from the OHLCV cache; fake mode
(``SCAN_DATA_SOURCE=fake``) has none, so the spread falls back to the demo/mean
default and impact (which needs ADV) is 0.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import config
from simulation.market_impact import impact_pct, realized_daily_vol
from simulation.spread_cost import half_spread_pct


async def load_dollar_volumes(
    *, exchange: str, start, end, markets: Iterable[str]
) -> dict[str, float]:
    """Per-market mean hourly dollar-volume over ``[start, end]`` (empty in fake mode)."""
    if config.SCAN_DATA_SOURCE == "fake":
        return {}
    from ingest.cache_repository import get_ohlcv_cache_repository

    return await get_ohlcv_cache_repository().get_dollar_volumes(
        exchange=exchange,
        resolution=config.CANDLE_RESOLUTION,
        start=start,
        end=end,
        markets=list(markets),
    )


def build_cost_map(
    markets: Iterable[str],
    *,
    dollar_volumes: Mapping[str, float],
    closes_by_market: Mapping[str, list[float]],
    flat_slippage_pct: float,
    per_leg_usd: float,
) -> dict[str, float]:
    """``{market: per-leg cost %}`` = half-spread (or flat) + size-aware impact.

    Pure: every input is passed in, so both engines and the tests can drive it
    without touching a database.
    """
    out: dict[str, float] = {}
    for market in markets:
        dv = dollar_volumes.get(market)
        base = half_spread_pct(market, dv) if config.PER_MARKET_SLIPPAGE else flat_slippage_pct
        impact = 0.0
        if config.MARKET_IMPACT:
            sigma = realized_daily_vol(list(closes_by_market.get(market, [])))
            adv = (dv or 0.0) * 24.0
            impact = impact_pct(sigma, per_leg_usd, adv)
        out[market] = base + impact
    return out
