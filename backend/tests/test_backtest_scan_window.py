"""Unit tests for the per-window historical cointegration scan (Phase 8, PRD F8.1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from backtest.scan_window import build_window_matrix, scan_window_pairs

_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles(closes):
    return [
        {"timestamp": _ANCHOR + timedelta(hours=i), "close": float(c)}
        for i, c in enumerate(closes)
    ]


def _cointegrated(seed, beta, alpha, n):
    rng = np.random.default_rng(seed)
    s2 = 100 + np.cumsum(rng.normal(0, 1, n))
    eps = np.zeros(n)
    for t in range(1, n):
        eps[t] = 0.5 * eps[t - 1] + rng.normal(0, 0.6)
    s1 = beta * s2 + alpha + eps
    return s1, s2


def test_matrix_aligns_on_shared_window():
    n = 60
    a = _candles(range(100, 100 + n))
    b = _candles(range(200, 200 + n))
    candles = {"AAA-USD": a, "BBB-USD": b}
    df = build_window_matrix(candles, _ANCHOR, _ANCHOR + timedelta(hours=29))
    # Only the first 30 in-range bars, both markets present.
    assert df.shape == (30, 2)
    assert set(df.columns) == {"AAA-USD", "BBB-USD"}


def test_scan_finds_cointegrated_pair():
    n = 200
    s1, s2 = _cointegrated(11, beta=2.0, alpha=5.0, n=n)
    candles = {
        "AAA-USD": _candles(s1),
        "BBB-USD": _candles(s2),
        "NOISE-USD": _candles(50 + np.cumsum(np.random.default_rng(9).normal(0, 1, n))),
    }
    found = scan_window_pairs(
        candles, _ANCHOR, _ANCHOR + timedelta(hours=n - 1),
        pvalue_max=0.05, max_half_life=72.0, min_rows=31,
    )
    pairs = {(f["base_market"], f["quote_market"]) for f in found}
    assert ("AAA-USD", "BBB-USD") in pairs
    row = next(f for f in found if f["base_market"] == "AAA-USD")
    # Hedge ratio recovered near the true β=2.0; intercept present (Option-B #1).
    assert row["hedge_ratio"] == _approx(2.0, 0.3)
    assert "intercept" in row and "half_life" in row


def test_scan_returns_empty_when_too_few_rows():
    candles = {"AAA-USD": _candles(range(40)), "BBB-USD": _candles(range(40))}
    found = scan_window_pairs(
        candles, _ANCHOR, _ANCHOR + timedelta(hours=39),
        pvalue_max=0.05, max_half_life=72.0, min_rows=60,
    )
    assert found == []


def _approx(target, tol):
    class _A:
        def __eq__(self, other):
            return abs(other - target) <= tol

    return _A()
