"""
Build the per-pair chart series for the pair-detail view (PRD F3, PLAN Phase 3).

Given a price source and the pair parameters a scan already computed (hedge
ratio β and intercept α), this produces the three panels the detail page draws:

  1. Normalized price overlay — both legs rebased to 100 at the window start.
  2. Spread = S1 − β·S2 − α, with its mean and σ (for the ±1σ / ±2σ bands).
  3. Rolling Z-score, plus entry/exit markers derived by walking the Z series
     through the same ``statcore`` signal rules used everywhere else (single
     source of truth — no bespoke signal logic here).

The builder is exchange-agnostic: it depends only on the ``PriceSource`` protocol
(the live :class:`DydxDataClient`, the demo client, or a test fake all satisfy
it). Pure apart from the price fetch — no DB, no config mutation.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

import config
from marketdata.price_matrix import PriceSource
from statcore import (
    PairAnalysis,
    analyze_pair,
    compute_spread,
    evaluate_entry,
    evaluate_exit,
    latest_zscore,
    rolling_zscore,
)

logger = logging.getLogger(__name__)

# Cap concurrent per-market price fetches so a large pairs set doesn't burst the
# live indexer into rate-limiting (issue #50).
_PRICE_FETCH_CONCURRENCY = 8


@dataclass(frozen=True)
class TimePoint:
    """A single ``{time, value}`` chart point; ``time`` is UNIX seconds (UTC)."""

    time: int
    value: float

    def to_dict(self) -> dict:
        return {"time": self.time, "value": self.value}


@dataclass(frozen=True)
class Marker:
    """An entry/exit annotation on the Z-score panel."""

    time: int
    kind: str  # "entry" | "exit"
    side: str  # "LONG_SPREAD" | "SHORT_SPREAD" (entry) | "" (exit)
    reason: str  # entry: "ENTRY"; exit: ExitReason value (TAKE_PROFIT, …)
    zscore: float

    def to_dict(self) -> dict:
        return {
            "time": self.time,
            "kind": self.kind,
            "side": self.side,
            "reason": self.reason,
            "zscore": self.zscore,
        }


@dataclass(frozen=True)
class PairSeries:
    """All chart data for one pair, ready to serialise for the detail endpoint."""

    base_market: str
    quote_market: str
    hedge_ratio: float
    intercept: float
    half_life: float | None
    zscore_window: int
    entry_threshold: float
    exit_threshold: float
    stop_threshold: float
    window_start: str | None
    window_end: str | None
    base_norm: list[TimePoint]
    quote_norm: list[TimePoint]
    base_raw: list[TimePoint]
    quote_raw: list[TimePoint]
    spread: list[TimePoint]
    spread_mean: float
    spread_std: float
    zscore: list[TimePoint]
    markers: list[Marker]

    def to_dict(self) -> dict:
        return {
            "base_market": self.base_market,
            "quote_market": self.quote_market,
            "hedge_ratio": self.hedge_ratio,
            "intercept": self.intercept,
            "half_life": self.half_life,
            "zscore_window": self.zscore_window,
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "stop_threshold": self.stop_threshold,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "count": len(self.spread),
            "normalized": {
                "base": [p.to_dict() for p in self.base_norm],
                "quote": [p.to_dict() for p in self.quote_norm],
            },
            # Actual per-leg prices (issue #68) — the raw-price panel plots these on
            # dual axes so the operator can read each leg's real price, alongside
            # the rebased-to-100 overlay above.
            "raw": {
                "base": [p.to_dict() for p in self.base_raw],
                "quote": [p.to_dict() for p in self.quote_raw],
            },
            "spread": {
                "mean": self.spread_mean,
                "std": self.spread_std,
                "series": [p.to_dict() for p in self.spread],
            },
            "zscore": {
                "series": [p.to_dict() for p in self.zscore],
                "markers": [m.to_dict() for m in self.markers],
            },
        }


@dataclass(frozen=True)
class PairSnapshot:
    """Current per-leg prices + spread/Z for a pair, captured at a point in time."""

    base_price: float
    quote_price: float
    spread_value: float
    z_score: float

    def to_dict(self) -> dict:
        return {
            "base_price": self.base_price,
            "quote_price": self.quote_price,
            "spread_value": self.spread_value,
            "z_score": self.z_score,
        }


async def _aligned_closes(
    client: PriceSource,
    base_market: str,
    quote_market: str,
    *,
    num_pages: int | None,
    now,
    concurrent: bool = False,
) -> tuple[list[str], np.ndarray, np.ndarray] | None:
    """Fetch both legs concurrently and align on shared timestamps.

    Returns ``(sorted_shared_iso, s1, s2)`` or ``None`` if there is no usable
    overlapping history. Shared by the chart builder and the record snapshot so
    the fetch/align logic lives in one place. ``concurrent`` also parallelises the
    per-leg page fetches (issue #61) for the chart's fast path.
    """
    base_closes, quote_closes = await asyncio.gather(
        client.get_historical_closes(
            base_market, num_pages=num_pages, now=now, concurrent=concurrent
        ),
        client.get_historical_closes(
            quote_market, num_pages=num_pages, now=now, concurrent=concurrent
        ),
    )
    if not base_closes or not quote_closes:
        return None
    base_by_ts = {c["datetime"]: float(c["close"]) for c in base_closes}
    quote_by_ts = {c["datetime"]: float(c["close"]) for c in quote_closes}
    shared = sorted(set(base_by_ts) & set(quote_by_ts))
    if len(shared) < 2:
        return None
    s1 = np.array([base_by_ts[ts] for ts in shared], dtype=float)
    s2 = np.array([quote_by_ts[ts] for ts in shared], dtype=float)
    return shared, s1, s2


async def current_pair_snapshot(
    client: PriceSource,
    *,
    base_market: str,
    quote_market: str,
    hedge_ratio: float,
    intercept: float,
    window: int | None = None,
    num_pages: int | None = None,
    now=None,
) -> PairSnapshot | None:
    """
    The pair's current entry prices, spread, and rolling Z — what a manual trade
    is recorded against (PRD F4.5).

    Uses the pair's stored β/α so the recorded spread matches the scan. Returns
    ``None`` if there's no overlapping history or the Z-score is undefined
    (fewer than ``window`` bars / zero-variance window) — the caller rejects the
    record in that case, since direction can't be determined.
    """
    window = window or config.ZSCORE_WINDOW
    aligned = await _aligned_closes(
        client, base_market, quote_market, num_pages=num_pages, now=now
    )
    if aligned is None:
        return None
    _, s1, s2 = aligned

    spread = compute_spread(s1, s2, hedge_ratio, intercept)
    z = latest_zscore(spread, window=window)
    if not np.isfinite(z):
        return None
    return PairSnapshot(
        base_price=float(s1[-1]),
        quote_price=float(s2[-1]),
        spread_value=float(spread[-1]),
        z_score=float(z),
    )


async def current_pair_analysis(
    client: PriceSource,
    *,
    base_market: str,
    quote_market: str,
    pvalue_max: float,
    max_half_life: float,
    num_pages: int | None = None,
    now=None,
) -> PairAnalysis | None:
    """Re-run the full cointegration / half-life filter on **fresh** candles at
    record time (issue #147).

    Manual entry re-validates the pair's *current* statistics rather than
    trusting the (possibly stale) values the scan stored — cointegration and
    half-life drift, and a pair that passed the scan hours ago may no longer
    hold. This mirrors the backtest, which re-applies the filter every formation
    window, and reuses the same ``statcore.analyze_pair`` (single source of
    statistical truth) at the scan's own page depth so it's a like-for-like
    re-check.

    Returns ``None`` when there is no usable overlapping history or the
    statistics can't be computed (a degenerate series) — the caller rejects the
    record in that case rather than falling back to the stale scan values.
    """
    aligned = await _aligned_closes(
        client, base_market, quote_market, num_pages=num_pages, now=now
    )
    if aligned is None:
        return None
    _, s1, s2 = aligned
    try:
        return analyze_pair(
            s1, s2, pvalue_max=pvalue_max, max_half_life=max_half_life
        )
    except Exception as exc:  # degenerate series → unusable, don't trust the scan
        logger.warning(
            "fresh pair analysis failed for %s/%s: %s", base_market, quote_market, exc
        )
        return None


async def current_prices(
    client: PriceSource,
    markets: list[str],
    *,
    num_pages: int | None = 1,
    now=None,
) -> dict[str, float]:
    """
    Latest close per market — a *light* price read for the pairs table and the
    manual-trade mark-to-market (PRD F4 / issue #37 PR-2).

    Fetches each *unique* market once, concurrently, taking the most recent
    candle's close (max timestamp). ``num_pages=1`` keeps it to a single candle
    page per market so it stays cheap even against the live dYdX indexer. The
    "current price" is therefore the last closed hourly candle — the same data
    source the charts and the record snapshot use (there is no live ticker).

    Markets with no data are omitted from the result (the caller renders "—").

    Resilient by design (issue #50): a single market's failure — including a
    network error — can never blank the whole batch; it is caught and that market
    is simply omitted, so the others still render. Concurrency is capped so a
    large pairs set doesn't burst the indexer into rate-limiting right after a
    scan (a likely cause of an all-"—" column).

    Bulk fast path (issue #142): a venue with a single-request "all current
    prices" endpoint (Hyperliquid's ``allMids``) exposes ``get_current_prices``;
    when present we use it so a large pairs set costs ONE request instead of one
    per market. The per-market loop below stays the path for dYdX / demo, which
    have no such endpoint.
    """
    unique = list(dict.fromkeys(markets))  # de-dupe, preserve order

    bulk = getattr(client, "get_current_prices", None)
    if callable(bulk):
        try:
            return await bulk(unique)
        except Exception as exc:  # resilient: an empty column beats a 500
            logger.warning("bulk current_prices failed: %s", exc)
            return {}

    sem = asyncio.Semaphore(_PRICE_FETCH_CONCURRENCY)

    async def _one(market: str) -> tuple[str, float] | None:
        try:
            async with sem:
                closes = await client.get_historical_closes(
                    market, num_pages=num_pages, now=now
                )
            if not closes:
                return None
            latest = max(closes, key=lambda c: c["datetime"])
            return market, float(latest["close"])
        except Exception as exc:  # one market must never fail the whole batch
            logger.warning("current price fetch failed for %s: %s", market, exc)
            return None

    results = await asyncio.gather(*(_one(m) for m in unique))
    return {market: price for r in results if r is not None for (market, price) in (r,)}


def _to_unix(iso: str) -> int:
    """dYdX ISO timestamp (``…Z``) → UNIX seconds (UTC)."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return int(dt.timestamp())


def _build_markers(
    times: list[int],
    zscores: np.ndarray,
    *,
    half_life: float | None,
    entry_threshold: float,
    exit_threshold: float,
    stop_threshold: float,
) -> list[Marker]:
    """
    Walk the Z-score series through the statcore entry/exit rules, emitting an
    entry marker when a flat book opens a position and an exit marker when an
    open position closes. ``NaN`` Z-scores (warm-up window) never trigger either.

    The time stop is intentionally omitted: this is a single historical-window
    visualisation, not a clock-driven backtest, so positions only open and close
    on the Z thresholds (the take-profit / stop-loss rules). Markers therefore
    always alternate entry → exit.
    """
    markers: list[Marker] = []
    in_position = False
    for t, z in zip(times, zscores):
        if np.isnan(z):
            continue
        zf = float(z)
        if not in_position:
            entry = evaluate_entry(zf, entry_threshold=entry_threshold)
            if entry is not None:
                side = "LONG_SPREAD" if zf < 0 else "SHORT_SPREAD"
                markers.append(
                    Marker(time=t, kind="entry", side=side, reason="ENTRY", zscore=zf)
                )
                in_position = True
        else:
            exit_sig = evaluate_exit(
                zf,
                half_life=half_life,
                exit_threshold=exit_threshold,
                stop_threshold=stop_threshold,
            )
            if exit_sig is not None:
                markers.append(
                    Marker(
                        time=t,
                        kind="exit",
                        side="",
                        reason=exit_sig.reason.value,
                        zscore=zf,
                    )
                )
                in_position = False
    return markers


async def build_pair_series(
    client: PriceSource,
    *,
    base_market: str,
    quote_market: str,
    hedge_ratio: float,
    intercept: float,
    half_life: float | None = None,
    window: int | None = None,
    num_pages: int | None = None,
    now=None,
    concurrent: bool = False,
) -> PairSeries | None:
    """
    Fetch both legs, align them, and compute the three chart panels.

    Args:
        client: a ``PriceSource`` (live dYdX client, demo client, or fake).
        base_market / quote_market: the pair's tickers (S1 / S2).
        hedge_ratio / intercept: β and α as stored by the scan that found the
            pair — reused verbatim so the chart's spread matches the scan's.
        half_life: the pair's OU half-life (only annotates markers; may be None).
        window: rolling Z-score window (defaults to ``config.ZSCORE_WINDOW``).
        num_pages / now: passed through to the price source for history depth /
            deterministic time windows in tests.

    Returns ``None`` when the two legs share no usable overlapping history (the
    caller maps this to a 404/empty response); otherwise a :class:`PairSeries`.
    """
    window = window or config.ZSCORE_WINDOW

    aligned = await _aligned_closes(
        client,
        base_market,
        quote_market,
        num_pages=num_pages,
        now=now,
        concurrent=concurrent,
    )
    if aligned is None:
        return None
    shared, s1, s2 = aligned
    times = [_to_unix(ts) for ts in shared]

    # Normalize each leg to 100 at the window start (the overlay panel).
    base_norm = [
        TimePoint(time=t, value=float(v / s1[0] * 100.0)) for t, v in zip(times, s1)
    ]
    quote_norm = [
        TimePoint(time=t, value=float(v / s2[0] * 100.0)) for t, v in zip(times, s2)
    ]
    # Actual prices per leg (issue #68) — the dual-axis raw-price panel.
    base_raw = [TimePoint(time=t, value=float(v)) for t, v in zip(times, s1)]
    quote_raw = [TimePoint(time=t, value=float(v)) for t, v in zip(times, s2)]

    spread = compute_spread(s1, s2, hedge_ratio, intercept)
    spread_points = [
        TimePoint(time=t, value=float(v)) for t, v in zip(times, spread)
    ]
    spread_mean = float(np.mean(spread))
    spread_std = float(np.std(spread, ddof=1)) if spread.size > 1 else 0.0

    z = rolling_zscore(spread, window=window)
    # Drop the warm-up NaNs: invalid in JSON and not plottable.
    z_points = [
        TimePoint(time=t, value=float(v))
        for t, v in zip(times, z)
        if not np.isnan(v)
    ]

    entry_threshold = config.ZSCORE_THRESH
    exit_threshold = config.EXIT_ZSCORE
    stop_threshold = config.STOP_LOSS_ZSCORE
    markers = _build_markers(
        times,
        z,
        half_life=half_life,
        entry_threshold=entry_threshold,
        exit_threshold=exit_threshold,
        stop_threshold=stop_threshold,
    )

    return PairSeries(
        base_market=base_market,
        quote_market=quote_market,
        hedge_ratio=hedge_ratio,
        intercept=intercept,
        half_life=half_life,
        zscore_window=window,
        entry_threshold=entry_threshold,
        exit_threshold=exit_threshold,
        stop_threshold=stop_threshold,
        window_start=shared[0],
        window_end=shared[-1],
        base_norm=base_norm,
        quote_norm=quote_norm,
        base_raw=base_raw,
        quote_raw=quote_raw,
        spread=spread_points,
        spread_mean=spread_mean,
        spread_std=spread_std,
        zscore=z_points,
        markers=markers,
    )
