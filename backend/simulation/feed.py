"""
Real-time price feed for the simulation engine (PRD F6.1/F6.2).

Turns the latest scan's cointegrated pairs into a list of :class:`PairTick`
snapshots — each carrying the current per-leg price and a **proper rolling
Z-score** computed by ``statcore`` over real historical closes. This is the
headline fix for Phase 6: the prototype estimated the spread std as
``abs(spread_ref) * 0.02`` (``simulation/engine.py`` in the old code), producing
wrong exits/entries; here the Z comes from the exact same
:func:`marketdata.pair_series.current_pair_snapshot` path the live bot uses, so
there is one source of truth across live / sim / fast-forward.

The feed depends only on the ``PriceSource`` protocol, so the deterministic demo
client (``SCAN_DATA_SOURCE=fake``) drives it offline for tests/E2E, and the live
mainnet indexer drives it in production (simulation uses mainnet prices for
realistic dynamics even though it trades virtual money).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from marketdata.pair_series import current_pair_snapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PairTick:
    """A pair's current price + rolling-Z snapshot, ready for the engine tick."""

    base_market: str
    quote_market: str
    hedge_ratio: float
    half_life: float
    base_price: float
    quote_price: float
    z_score: float
    spread_value: float


async def _tick_for_pair(client, pair: dict, *, window: int | None, now) -> PairTick | None:
    try:
        snap = await current_pair_snapshot(
            client,
            base_market=pair["base_market"],
            quote_market=pair["quote_market"],
            hedge_ratio=pair["hedge_ratio"],
            intercept=pair.get("intercept", 0.0) or 0.0,
            window=window,
            now=now,
        )
    except Exception as exc:
        # One bad pair (malformed candle, missing field, transient parse error)
        # must not abort the whole tick — drop just this pair, as the docstring
        # promises. Mirrors marketdata/price_matrix.py's per-market isolation.
        logger.warning(
            "sim snapshot failed for %s/%s: %s",
            pair.get("base_market"), pair.get("quote_market"), exc,
        )
        return None
    if snap is None:
        return None
    return PairTick(
        base_market=pair["base_market"],
        quote_market=pair["quote_market"],
        hedge_ratio=pair["hedge_ratio"],
        half_life=pair.get("half_life") or 0.0,
        base_price=snap.base_price,
        quote_price=snap.quote_price,
        z_score=snap.z_score,
        spread_value=snap.spread_value,
    )


async def build_realtime_snapshots(
    client,  # PriceSource (live dYdX data client or demo client)
    pairs: list[dict],
    *,
    window: int | None = None,
    now=None,
) -> list[PairTick]:
    """
    Build a :class:`PairTick` for every pair that has a usable live Z right now.

    Pairs with no overlapping history or an undefined Z (warm-up / zero-variance)
    are silently dropped — the engine simply doesn't act on them this tick.
    """
    results = await asyncio.gather(
        *(_tick_for_pair(client, p, window=window, now=now) for p in pairs)
    )
    return [t for t in results if t is not None]
