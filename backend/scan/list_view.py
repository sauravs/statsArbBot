"""
Read-time enrichment + minimisation of the manual/scan pair list (Phase-3 WS2).

Bridges the stored scan rows (base/quote market + half_life + p_value) to the pure
scoring in ``scan.tradability`` by pulling the two data inputs the rows lack:

  * per-market mean hourly **dollar-volume** (``ingest.cache_repository`` — the same
    source the backtest universe filter uses), over a trailing window, and
  * per-market modelled **half-spread** (``simulation.spread_cost``).

It then attaches ``dollar_volume_base/quote``, ``min_dollar_volume``,
``max_half_spread_pct`` and ``tradability`` to each pair and applies the operator's
runtime knobs (half-spread ceiling + top-N). Purely read-time and non-destructive —
the stored scan is never touched, so the knobs can be adjusted with no re-scan.

A single-slot memo keyed by ``(exchange, mode, scanned_at)`` keeps the ~2s dashboard
poll from re-running the dollar-volume aggregate on every call; a **content
signature** of the pair set (not just its timestamp) invalidates it whenever the
stored pairs change (a new scan, cleared pairs).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config
from scan.tradability import minimise_pairs, tradability_score

# Enrichment cache: {(exchange, mode): (signature, enriched_pairs)}. The signature
# identifies the exact pair SET, so two different scans that happen to share a
# scanned_at can never serve each other's stale enrichment.
_enrich_cache: dict[tuple[str, str], tuple[int, list[dict]]] = {}


def _signature(pairs: list[dict], scanned_at: object) -> int:
    return hash(
        (scanned_at, tuple((p["base_market"], p["quote_market"]) for p in pairs))
    )


async def _dollar_volumes(exchange: str, markets: list[str]) -> dict[str, float]:
    """Mean hourly dollar-volume per market over the trailing lookback window.

    Fake/demo mode has no OHLCV cache, so returns ``{}`` (every pair then scores 0
    on liquidity — the half-spread ceiling still applies via the seed/curve)."""
    if config.SCAN_DATA_SOURCE == "fake" or not markets:
        return {}
    from ingest.cache_repository import get_ohlcv_cache_repository

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(1, config.SCAN_DVOL_LOOKBACK_DAYS))
    return await get_ohlcv_cache_repository().get_dollar_volumes(
        exchange=exchange,
        resolution=config.CANDLE_RESOLUTION,
        start=start,
        end=end,
        markets=markets,
    )


async def enrich_pairs(pairs: list[dict], *, exchange: str) -> list[dict]:
    """Attach the tradability inputs + score to each pair (new list; inputs copied)."""
    from simulation.spread_cost import half_spread_pct

    markets = sorted({m for p in pairs for m in (p["base_market"], p["quote_market"])})
    dvols = await _dollar_volumes(exchange, markets)

    enriched: list[dict] = []
    for p in pairs:
        base, quote = p["base_market"], p["quote_market"]
        dv_base = dvols.get(base)
        dv_quote = dvols.get(quote)
        # min($-vol) is the fillability bottleneck; unknown legs contribute 0.
        min_dvol = min(dv_base or 0.0, dv_quote or 0.0)
        hs_base = half_spread_pct(base, dv_base)
        hs_quote = half_spread_pct(quote, dv_quote)
        enriched.append(
            {
                **p,
                "dollar_volume_base": dv_base,
                "dollar_volume_quote": dv_quote,
                "min_dollar_volume": min_dvol,
                "max_half_spread_pct": max(hs_base, hs_quote),
                "tradability": tradability_score(
                    min_dvol, p.get("half_life"), p.get("p_value")
                ),
            }
        )
    return enriched


async def minimised_pairs(
    pairs: list[dict], *, exchange: str, scanned_at: object = None, mode: str = ""
) -> list[dict]:
    """Enrich (memoised per scan) then apply the runtime ceiling + top-N cap."""
    if not pairs:
        return pairs
    key = (exchange, mode)
    sig = _signature(pairs, scanned_at)
    cached = _enrich_cache.get(key)
    if cached is not None and cached[0] == sig:
        enriched = cached[1]
    else:
        enriched = await enrich_pairs(pairs, exchange=exchange)
        _enrich_cache[key] = (sig, enriched)
    return minimise_pairs(
        enriched,
        max_half_spread_pct=config.SCAN_MAX_HALF_SPREAD_PCT,
        top_n=config.SCAN_TOP_N,
    )
