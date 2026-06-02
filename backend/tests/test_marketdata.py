"""Unit tests for the market-data layer: time windows + price-matrix builder."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from marketdata import build_price_matrix, iso_time_windows
from tests.conftest import FakeDydxClient, make_cointegrated_series


def test_iso_time_windows_oldest_first_and_contiguous():
    now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    windows = iso_time_windows(3, resolution="1HOUR", candles_per_page=100, now=now)
    assert len(windows) == 3
    # Oldest first: each window's to_iso equals the next window's from_iso.
    assert windows[0]["to_iso"] == windows[1]["from_iso"]
    assert windows[1]["to_iso"] == windows[2]["from_iso"]
    # Newest window ends at `now`.
    assert windows[-1]["to_iso"] == "2025-06-01T00:00:00Z"


def test_iso_time_windows_zero_pages():
    assert iso_time_windows(0) == []


@pytest.mark.asyncio
async def test_build_price_matrix_aligns_and_filters():
    s1, s2 = make_cointegrated_series()
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2})

    seen: list[tuple[int, int]] = []
    matrix = await build_price_matrix(
        client, progress_callback=lambda d, t: seen.append((d, t))
    )

    assert not matrix.is_empty
    assert matrix.num_markets == 2
    assert matrix.num_rows == len(s1)
    assert set(matrix.df.columns) == {"AAA-USD", "BBB-USD"}
    assert matrix.window_end > matrix.window_start
    # Progress fired once per market, ending at (2, 2).
    assert seen[-1] == (2, 2)


@pytest.mark.asyncio
async def test_build_price_matrix_drops_short_markets():
    s1, s2 = make_cointegrated_series()
    client = FakeDydxClient(
        {"AAA-USD": s1, "BBB-USD": s2, "SHORT-USD": [1.0, 2.0, 3.0]}
    )
    matrix = await build_price_matrix(client)
    assert "SHORT-USD" not in matrix.df.columns
    assert matrix.num_markets == 2


@pytest.mark.asyncio
async def test_build_price_matrix_empty_when_no_markets():
    matrix = await build_price_matrix(FakeDydxClient({}))
    assert matrix.is_empty
    assert matrix.num_markets == 0
    assert matrix.dropped == {}


# ── dropped-market reporting (issues #6 / #7) ────────────────────────────────


@pytest.mark.asyncio
async def test_reports_fetch_failed_market():
    """A market whose fetch raises (e.g. 429 exhaustion) is recorded, not silent."""
    s1, s2 = make_cointegrated_series(n=120)
    series = {"AAA-USD": s1, "BBB-USD": s2}

    class RaisingClient(FakeDydxClient):
        async def get_historical_closes(self, market, *, num_pages=None, now=None):
            if market == "FAIL-USD":
                raise RuntimeError("429 exhausted")
            return await super().get_historical_closes(market, num_pages=num_pages, now=now)

    client = RaisingClient(series)
    matrix = await build_price_matrix(client, markets=["AAA-USD", "BBB-USD", "FAIL-USD"])

    assert matrix.dropped.get("FAIL-USD") == "fetch_failed"
    assert "FAIL-USD" not in matrix.df.columns
    assert matrix.num_markets == 2
    assert matrix.dropped_by_reason.get("fetch_failed") == 1


@pytest.mark.asyncio
async def test_reports_misaligned_market():
    """A market with a shorter/offset history dropped by the union join is recorded."""
    s1, s2 = make_cointegrated_series(n=120)
    partial = s1[:60]  # 60 candles (≥ min) but only covers hours 0..59 of 0..119
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2, "PARTIAL-USD": partial})

    matrix = await build_price_matrix(
        client, markets=["AAA-USD", "BBB-USD", "PARTIAL-USD"]
    )

    assert matrix.dropped.get("PARTIAL-USD") == "misaligned"
    assert matrix.num_markets == 2
    assert matrix.num_dropped == 1


@pytest.mark.asyncio
async def test_reports_too_short_and_no_data():
    s1, s2 = make_cointegrated_series(n=120)
    client = FakeDydxClient(
        {"AAA-USD": s1, "BBB-USD": s2, "TINY-USD": [1.0, 2.0, 3.0], "EMPTY-USD": []}
    )
    matrix = await build_price_matrix(
        client, markets=["AAA-USD", "BBB-USD", "TINY-USD", "EMPTY-USD"]
    )

    assert matrix.dropped.get("TINY-USD") == "too_short"
    assert matrix.dropped.get("EMPTY-USD") == "no_data"
    assert matrix.num_markets == 2
