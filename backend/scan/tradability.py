"""
Tradability scoring + read-time list minimisation (Phase-3 WS2).

The manual/scan pair list can grow to thousands of rows; the operator needs a
short, *fillable* shortlist. This module scores each cointegrated pair by how
tradable it is and trims the list — a **tractability** lens, NOT an alpha lever
(the Phase-2 §4 refutation shows filtering toward liquid names *loses* backtest
money; this is about surfacing names you can actually fill at market size, not
about edge). Everything here is pure + read-time: it never mutates a stored scan.

Score (operator-approved 2026-07-27):

    tradability = min(dvol_base, dvol_quote) · (1 / half_life) · (1 - p_value)

  * ``min($-vol)`` — the fillability bottleneck: a pair can only be traded as big
    as its *thinner* leg, so the smaller of the two legs' dollar-volumes caps size.
  * ``1 / half_life`` — faster mean-reversion is more tradable (less funding drag).
  * ``1 - p_value`` — stronger cointegration is more trustworthy.

Higher = more tradable. Market-cap is deliberately NOT used (needs an external
API + brittle symbol mapping, and is a worse fillability proxy than liquidity).
"""

from __future__ import annotations

from typing import Optional


def tradability_score(
    min_dollar_volume: float,
    half_life: Optional[float],
    p_value: Optional[float],
) -> float:
    """The tradability score for a pair (higher = more tradable).

    ``min_dollar_volume`` is the smaller of the two legs' mean hourly dollar-volume
    (0 when unknown → the pair scores 0 and sorts to the bottom, never crashing).
    ``half_life`` in hours (> 0); ``p_value`` in [0, 1]. Non-positive/None inputs
    degrade gracefully to a 0 contribution so an incomplete row can't blow up the
    read path.
    """
    liq = max(0.0, float(min_dollar_volume or 0.0))
    if not half_life or half_life <= 0:
        return 0.0
    revert = 1.0 / float(half_life)
    p = 0.0 if p_value is None else float(p_value)
    coint = max(0.0, 1.0 - p)
    return liq * revert * coint


def max_leg_half_spread(
    base_half_spread: float, quote_half_spread: float
) -> float:
    """The worse (wider) of the two legs' half-spreads — a pair costs the sum of
    both legs' spreads to trade, so the ceiling is applied to the wider leg (drop
    the pair if *either* leg is too wide)."""
    return max(float(base_half_spread), float(quote_half_spread))


def minimise_pairs(
    pairs: list[dict],
    *,
    max_half_spread_pct: float = 0.0,
    top_n: int = 0,
) -> list[dict]:
    """Trim an enriched pair list (read-time, non-destructive).

    Each pair must already carry ``tradability`` and ``max_half_spread_pct`` (added
    by the enrichment step). Applies, in order:

      1. **half-spread ceiling** — drop pairs whose wider leg exceeds
         ``max_half_spread_pct`` (0 = off).
      2. **top-N cap** — keep the ``top_n`` most tradable survivors (0 = off).

    A stable sort by descending tradability is applied whenever a cap is set so the
    kept rows are the genuinely-best ones; the input order is otherwise preserved.
    Returns a new list; the input is not mutated.
    """
    out = list(pairs)
    if max_half_spread_pct and max_half_spread_pct > 0:
        out = [
            p
            for p in out
            if p.get("max_half_spread_pct") is None
            or p["max_half_spread_pct"] <= max_half_spread_pct
        ]
    if top_n and top_n > 0:
        out = sorted(out, key=lambda p: p.get("tradability", 0.0), reverse=True)[:top_n]
    return out
