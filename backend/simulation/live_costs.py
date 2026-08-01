"""
Honest costs for the *real-time* simulation (Phase 5).

Before this, a paper run was systematically more optimistic than the backtest that
produced the project's NO-GO verdict, in three separate ways
(``docs/PHASE5_PAPER_TRADING_PLAN.md`` §1):

  1. flat ``slippage_pct`` instead of each market's real half-spread,
  2. **no market impact at all** (``simulation.market_impact`` was never imported
     by the sim engine), and
  3. **no funding at all** — ``SimulationEngine.tick`` called ``run_tick`` without
     ``funding_rates``, so ``_accrue_funding`` never ran.

(3) is the largest of the three: funding is the dominant explicit cost (29% of
gross at the recommended config, ≈−$0.72/trade) against a measured edge of
+$0.248/trade. Charging none of it would overstate a fortnight's P&L several-fold.

This module supplies both from the same caches the backtest reads
(``ohlcv_cache`` / ``funding_rate_cache``, both kept current by the ingest job), on
an **hourly** refresh: the inputs are trailing-window aggregates that move slowly,
the tick runs every 60–300s, and the box is 2 vCPU — rebuilding per tick would put
a ``GROUP BY`` over the candle cache on the event loop dozens of times an hour.

On a refresh failure the **last good** values are reused. That matters: silently
reverting to flat cost / zero funding would reintroduce exactly the optimism this
module exists to remove, and it would do it invisibly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import config
from replay.candle_source import make_candle_source
from replay.historical_feed import FundingTable
from simulation.cost_map import build_cost_map, load_dollar_volumes

logger = logging.getLogger(__name__)

#: How long a built cost map / funding table stays valid.
REFRESH_SECONDS = 3600

#: Trailing window for ADV and σ. Matches the backtest's per-window scale
#: (scan 21d / trade 7d) without re-reading months of history.
LOOKBACK_DAYS = 7

#: Trailing window for funding. Deliberately wider than LOOKBACK_DAYS: the funding
#: table is a *step function* (latest rate at-or-before now), so a wider window costs
#: one bounded indexed read an hour but keeps resolving rates when the ingest job
#: lags. The failure it prevents is silent and expensive — an empty table means the
#: sim charges ZERO funding, and funding is the dominant cost (~29% of gross), so a
#: stale cache would quietly restore the optimism this module exists to remove.
FUNDING_LOOKBACK_DAYS = 30


class LiveCostCache:
    """Per-exchange cost map + funding table with an hourly TTL and last-good fallback."""

    def __init__(self) -> None:
        self._maps: dict[tuple, tuple[datetime, dict[str, float]]] = {}
        self._funding: dict[str, tuple[datetime, FundingTable]] = {}

    @staticmethod
    def _stale(built_at: datetime, now: datetime) -> bool:
        return (now - built_at).total_seconds() >= REFRESH_SECONDS

    async def slippage_map(
        self,
        *,
        exchange: str,
        markets: set[str],
        flat_slippage_pct: float,
        per_leg_usd: float,
        now: datetime | None = None,
    ) -> dict[str, float]:
        """``{market: per-leg cost %}`` — half-spread (or flat) + size-aware impact.

        Returns ``{}`` when both honest-cost flags are off, so the caller leaves
        ``slippage_by_market`` unset and the existing flat behaviour is preserved
        exactly (Phase-1 parity).
        """
        if not (config.PER_MARKET_SLIPPAGE or config.MARKET_IMPACT):
            return {}
        now = now or datetime.now(timezone.utc)
        key = (exchange, per_leg_usd, flat_slippage_pct, frozenset(markets))
        cached = self._maps.get(key)
        if cached and not self._stale(cached[0], now):
            return cached[1]

        start = now - timedelta(days=LOOKBACK_DAYS)
        try:
            dollar_volumes = await load_dollar_volumes(
                exchange=exchange, start=start, end=now, markets=markets
            )
            closes = await self._closes(exchange, markets, start, now)
            built = build_cost_map(
                markets,
                dollar_volumes=dollar_volumes,
                closes_by_market=closes,
                flat_slippage_pct=flat_slippage_pct,
                per_leg_usd=per_leg_usd,
            )
        except Exception as exc:
            if cached:
                logger.warning("cost map refresh failed (%s) — reusing last good map", exc)
                return cached[1]
            # No previous map: charging flat cost here would be the silent
            # optimism this module removes, so surface it instead.
            logger.error("cost map build failed with no cached fallback: %s", exc)
            raise
        self._maps[key] = (now, built)
        return built

    async def funding_rates(
        self, *, exchange: str, markets: set[str], now: datetime | None = None
    ) -> dict[str, float]:
        """Latest known funding rate per market (step function, as the backtest uses)."""
        if not markets:
            return {}
        now = now or datetime.now(timezone.utc)
        cached = self._funding.get(exchange)
        table = cached[1] if cached else None
        if cached is None or self._stale(cached[0], now):
            try:
                table = await self._funding_table(exchange, markets, now)
                self._funding[exchange] = (now, table)
            except Exception as exc:
                if table is None:
                    logger.error("funding load failed with no cached fallback: %s", exc)
                    return {}
                logger.warning("funding refresh failed (%s) — reusing last good table", exc)
        if table is None or table.empty:
            logger.warning(
                "no funding rates for %s over the last %dd — the sim will charge ZERO "
                "funding, which understates cost by ~29%% of gross. Check the ingest job.",
                exchange, FUNDING_LOOKBACK_DAYS,
            )
            return {}
        rates = table.rates_at(now, set(markets))
        missing = len(markets) - len(rates)
        if missing:
            logger.warning(
                "funding rate missing for %d/%d markets on %s — those legs accrue no carry",
                missing, len(markets), exchange,
            )
        return rates

    # ── loaders ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _closes(exchange: str, markets: set[str], start, end) -> dict[str, list[float]]:
        source = make_candle_source(exchange=exchange)
        out: dict[str, list[float]] = {}
        for market in markets:
            try:
                bars = await source.get_candles(market, start=start, end=end)
            except Exception as exc:  # one bad market must not lose the whole map
                logger.warning("closes fetch failed for %s: %s", market, exc)
                continue
            out[market] = [b["close"] for b in bars]
        return out

    @staticmethod
    async def _funding_table(exchange: str, markets: set[str], now: datetime) -> FundingTable:
        source = make_candle_source(exchange=exchange)
        start = now - timedelta(days=FUNDING_LOOKBACK_DAYS)
        by_market: dict[str, list[dict]] = {}
        for market in markets:
            try:
                by_market[market] = await source.get_funding(market, start=start, end=now)
            except Exception as exc:
                logger.warning("funding fetch failed for %s: %s", market, exc)
        return FundingTable(by_market)


_cache = LiveCostCache()


def get_live_cost_cache() -> LiveCostCache:
    return _cache
