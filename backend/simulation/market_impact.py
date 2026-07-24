"""
First-order market-impact cost (Phase-2 Slice 3, gate B5) — pure functions, no IO.

Every cost measured so far assumes **$100/leg at top-of-book**, where impact is
negligible. Manual size is 10–100× that, and in the thin alt perps where the
strategy's gross lives, a market order **walks the book** — a cost that appears
nowhere in the half-spread and scales *against* you as size grows.

Modelled with the standard **square-root law**:

    impact_pct = 100 · σ · √(Q / ADV)

  * ``σ``   — the market's realized **daily** return volatility (fraction).
  * ``Q``   — the per-leg order size in USD (``usd_per_trade``).
  * ``ADV`` — the market's average **daily** dollar-volume (USD).

Sanity check against ``docs/PHASE2_STRATEGY_PLAN.md`` §4.3 (a thin market, ADV ≈
$0.7M/day, σ ≈ 5%): Q=$1,000 → ≈0.19%; Q=$5,000 → ≈0.42% per leg — several times the
entire modelled top-of-book cost, exactly the plan's "structurally unharvestable at
real manual size" finding. This is an **honesty** charge (gate B5), not an alpha lever.
"""

from __future__ import annotations

import math

# Hourly bars → daily vol. sqrt-of-time scaling of hourly return std.
_HOURS_PER_DAY = 24.0

# Per-leg impact is capped: below the floor ADV the square-root law blows up, and a
# market that would cost >5%/leg to cross is untradeable anyway. Keeps a degenerate
# (near-zero ADV) market from dominating the cost layer with an absurd number.
_MAX_IMPACT_PCT = 5.0


def realized_daily_vol(closes: list[float]) -> float:
    """Realized **daily** return volatility from an hourly close series.

    Std of simple hourly returns, scaled by √24. Returns 0.0 for a series too short
    (or flat) to have a return — impact is then 0 (unknown vol → don't invent cost).
    """
    prev = None
    rets: list[float] = []
    for c in closes:
        c = float(c)
        if prev is not None and prev > 0:
            rets.append(c / prev - 1.0)
        prev = c
    n = len(rets)
    if n < 2:
        return 0.0
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)  # sample variance
    return math.sqrt(var) * math.sqrt(_HOURS_PER_DAY)


def impact_pct(daily_vol: float, per_leg_usd: float, adv_usd: float) -> float:
    """First-order market-impact, percent per leg: ``100 · σ · √(Q/ADV)``.

    Guards: non-positive ``ADV``/``σ``/``Q`` → 0 (can't estimate → charge nothing);
    result clamped to ``_MAX_IMPACT_PCT``.
    """
    if daily_vol <= 0 or per_leg_usd <= 0 or adv_usd <= 0:
        return 0.0
    raw = 100.0 * daily_vol * math.sqrt(per_leg_usd / adv_usd)
    return min(_MAX_IMPACT_PCT, raw)
