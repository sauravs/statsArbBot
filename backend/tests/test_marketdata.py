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
