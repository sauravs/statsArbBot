"""
Unit tests for the per-pair chart-series builder (Phase 3, PRD F3).

Pure builder driven by an in-memory price source — no DB, no network.
"""

from __future__ import annotations

import numpy as np
import pytest

import config
from marketdata.pair_series import build_pair_series
from statcore import analyze_pair, compute_spread
from tests.conftest import (
    FakeDydxClient,
    closes_to_candles,
    make_cointegrated_series,
)

pytestmark = pytest.mark.asyncio


class _ExplicitClient:
    """A PriceSource returning preset {datetime, close} rows verbatim per market."""

    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self._rows = rows

    async def get_markets(self):
        return {m: {"status": "ACTIVE"} for m in self._rows}

    async def get_historical_closes(
        self, market, *, num_pages=None, now=None, concurrent=False
    ):
        return list(self._rows.get(market, []))

    async def aclose(self):
        return None


async def _fit(s1, s2):
    a = analyze_pair(s1, s2)
    return a.hedge_ratio, a.intercept, a.half_life


async def test_build_basic_shapes_and_normalization():
    s1, s2 = make_cointegrated_series()
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2})
    beta, alpha, hl = await _fit(s1, s2)

    series = await build_pair_series(
        client,
        base_market="AAA-USD",
        quote_market="BBB-USD",
        hedge_ratio=beta,
        intercept=alpha,
        half_life=hl,
    )
    assert series is not None
    n = len(s1)
    # Every panel spans the full aligned window.
    assert len(series.base_norm) == n
    assert len(series.quote_norm) == n
    assert len(series.spread) == n
    # Both legs rebased to 100 at the window start.
    assert series.base_norm[0].value == pytest.approx(100.0)
    assert series.quote_norm[0].value == pytest.approx(100.0)
    # Timestamps strictly increasing UNIX seconds.
    times = [p.time for p in series.spread]
    assert times == sorted(times)
    assert len(set(times)) == n


async def test_spread_matches_statcore():
    s1, s2 = make_cointegrated_series()
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2})
    beta, alpha, hl = await _fit(s1, s2)
    expected = compute_spread(np.array(s1), np.array(s2), beta, alpha)

    series = await build_pair_series(
        client,
        base_market="AAA-USD",
        quote_market="BBB-USD",
        hedge_ratio=beta,
        intercept=alpha,
    )
    got = np.array([p.value for p in series.spread])
    np.testing.assert_allclose(got, expected, rtol=1e-9, atol=1e-9)
    assert series.spread_mean == pytest.approx(float(np.mean(expected)))
    assert series.spread_std == pytest.approx(float(np.std(expected, ddof=1)))


async def test_zscore_drops_warmup_nans():
    s1, s2 = make_cointegrated_series()
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2})
    beta, alpha, _ = await _fit(s1, s2)
    window = config.ZSCORE_WINDOW

    series = await build_pair_series(
        client,
        base_market="AAA-USD",
        quote_market="BBB-USD",
        hedge_ratio=beta,
        intercept=alpha,
        window=window,
    )
    # First window-1 entries are NaN warm-up and must be omitted; the rest finite.
    assert len(series.zscore) == len(s1) - (window - 1)
    assert all(np.isfinite(p.value) for p in series.zscore)


async def test_markers_alternate_entry_exit():
    s1, s2 = make_cointegrated_series()
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2})
    beta, alpha, hl = await _fit(s1, s2)

    series = await build_pair_series(
        client,
        base_market="AAA-USD",
        quote_market="BBB-USD",
        hedge_ratio=beta,
        intercept=alpha,
        half_life=hl,
    )
    # A fast-reverting cointegrated spread should trip the entry threshold.
    assert len(series.markers) >= 1
    # Markers strictly alternate, starting with an entry.
    assert series.markers[0].kind == "entry"
    for i, m in enumerate(series.markers):
        assert m.kind == ("entry" if i % 2 == 0 else "exit")
        assert m.time > 0
        if m.kind == "entry":
            assert m.side in ("LONG_SPREAD", "SHORT_SPREAD")
            assert abs(m.zscore) >= series.entry_threshold
        else:
            assert m.reason in ("TAKE_PROFIT", "STOP_LOSS_ZSCORE")


async def test_no_overlap_returns_none():
    # Disjoint timestamps → no shared bars → None.
    base = closes_to_candles([100.0, 101.0, 102.0])  # hours 0,1,2 from anchor
    rows = {
        "AAA-USD": base,
        "BBB-USD": [
            {"datetime": "2030-01-01T00:00:00Z", "close": 50.0},
            {"datetime": "2030-01-01T01:00:00Z", "close": 51.0},
        ],
    }
    client = _ExplicitClient(rows)
    series = await build_pair_series(
        client,
        base_market="AAA-USD",
        quote_market="BBB-USD",
        hedge_ratio=1.0,
        intercept=0.0,
    )
    assert series is None


async def test_empty_history_returns_none():
    client = FakeDydxClient({"AAA-USD": [], "BBB-USD": []})
    series = await build_pair_series(
        client,
        base_market="AAA-USD",
        quote_market="BBB-USD",
        hedge_ratio=1.0,
        intercept=0.0,
    )
    assert series is None


async def test_alignment_uses_intersection_only():
    # AAA has hours 0..4, BBB has hours 2..6 → overlap is hours 2,3,4 (3 bars).
    from datetime import datetime, timedelta, timezone

    anchor = datetime(2025, 1, 1, tzinfo=timezone.utc)

    def row(h, c):
        return {
            "datetime": (anchor + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "close": float(c),
        }

    rows = {
        "AAA-USD": [row(h, 100 + h) for h in range(0, 5)],
        "BBB-USD": [row(h, 50 + h) for h in range(2, 7)],
    }
    client = _ExplicitClient(rows)
    series = await build_pair_series(
        client,
        base_market="AAA-USD",
        quote_market="BBB-USD",
        hedge_ratio=1.0,
        intercept=0.0,
    )
    assert series is not None
    assert len(series.spread) == 3  # only the 3 overlapping bars
    assert series.base_norm[0].value == pytest.approx(100.0)
