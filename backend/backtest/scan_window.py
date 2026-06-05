"""
Per-window cointegration scan for the walk-forward backtest (PRD F8.1) — pure,
no DB/IO (the engine fetches candles and offloads this whole function to a worker
thread, since ``statsmodels.coint`` over a 90-day window is CPU-bound).

It is the historical twin of ``scan.orchestrator``: build an aligned close-price
matrix over the formation window, then run the SAME ``statcore.analyze_pair`` (the
single source of statistical truth — Engle-Granger, OLS hedge ratio **with
intercept**, OU half-life, Option-B filters) on every market pair. Survivors are
returned as the minimal pair dicts ``replay.historical_feed.align_pairs`` consumes,
so the trade window replays the very pairs this window selected.
"""

from __future__ import annotations

import itertools
import logging
from datetime import datetime

import numpy as np
import pandas as pd

from statcore import analyze_pair

logger = logging.getLogger(__name__)


def build_window_matrix(
    candles_by_market: dict[str, list[dict]],
    start: datetime,
    end: datetime,
    *,
    min_completeness: float | None = None,
) -> pd.DataFrame:
    """Aligned close-price matrix over [start, end] (inclusive).

    ``candles_by_market`` maps a market to ascending ``{"timestamp", "close"}``
    dicts (a superset window is fine — only the in-range bars are used). Columns
    are markets, the index is the union of timestamps.

    Completeness-aware cleaning (issue #93): cointegration needs aligned, dense
    series, but real history has sporadic gaps and an all-or-nothing drop discarded
    a whole market for a single missing bar (a 90-day real-data window kept only 6
    of 38 markets). Instead a market is **kept only if it has at least
    ``min_completeness`` of the window's bars** (markets below that are genuinely
    absent — not-yet-listed / thin — and filling them would fabricate long flat
    stretches), then the survivors' small residual gaps are **forward-filled then
    back-filled**. Prices are non-stationary, so we never mean/median-fill (that
    injects artificial jumps and destroys the spread dynamics).
    """
    if min_completeness is None:
        import config

        min_completeness = config.BACKTEST_MIN_COMPLETENESS

    price_data: dict[str, dict[datetime, float]] = {}
    for market, candles in candles_by_market.items():
        series = {
            c["timestamp"]: float(c["close"])
            for c in candles
            if start <= c["timestamp"] <= end
        }
        if series:
            price_data[market] = series
    if not price_data:
        return pd.DataFrame()

    # Union index of all in-range timestamps; missing bars surface as NaN.
    df = pd.DataFrame(price_data)
    df.sort_index(inplace=True)
    n = len(df.index)
    if n == 0:
        return pd.DataFrame()

    # Keep markets covering at least the threshold fraction of the window's bars.
    threshold = min_completeness * n
    keep = [m for m in df.columns if df[m].notna().sum() >= threshold]
    df = df[keep]
    if df.shape[1] == 0:
        return pd.DataFrame()

    # Fill the survivors' small residual gaps: forward-fill (carry the last close),
    # then back-fill any leading gap. Drop anything still entirely NaN (defensive).
    df = df.ffill().bfill()
    df.dropna(axis=1, how="any", inplace=True)
    return df


def scan_window_pairs(
    candles_by_market: dict[str, list[dict]],
    start: datetime,
    end: datetime,
    *,
    pvalue_max: float,
    max_half_life: float,
    min_rows: int,
    should_stop=None,
) -> list[dict]:
    """Cointegrated pairs found over the formation window [start, end].

    Returns ``[{base_market, quote_market, hedge_ratio, intercept, half_life,
    p_value, zero_crossings}, …]`` for survivors only. One degenerate market never
    aborts the window — a per-pair ``analyze_pair`` failure is logged and skipped
    (mirrors ``scan.orchestrator._analyze_chunk``).
    """
    df = build_window_matrix(candles_by_market, start, end)
    if df.empty or df.shape[0] < min_rows or df.shape[1] < 2:
        return []

    markets = list(df.columns)
    found: list[dict] = []
    for base, quote in itertools.combinations(markets, 2):
        # Cooperative cancel (issue #100): let a pause/stop bail the CPU-heavy scan
        # between pairs rather than only at the window boundary.
        if should_stop is not None and should_stop():
            break
        s1 = df[base].to_numpy(dtype=float)
        s2 = df[quote].to_numpy(dtype=float)
        try:
            analysis = analyze_pair(
                s1, s2, pvalue_max=pvalue_max, max_half_life=max_half_life
            )
        except Exception as exc:  # noqa: BLE001 — skip the pair, keep the scan alive
            logger.warning("backtest pair %s/%s analysis failed: %s", base, quote, exc)
            continue
        if not analysis.passes_filter:
            continue
        found.append(
            {
                "base_market": base,
                "quote_market": quote,
                "hedge_ratio": analysis.hedge_ratio,
                "intercept": analysis.intercept,
                "half_life": analysis.half_life,
                "p_value": analysis.p_value,
                "zero_crossings": analysis.zero_crossings,
            }
        )
    return found
