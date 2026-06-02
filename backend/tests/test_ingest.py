"""
Unit tests for the Phase 2.5 historical-data ingest.

Focus is the pure cleaning rules (the highest-risk surface) plus gap/coverage
logic and an end-to-end pipeline run against the in-memory fake cache repo. No
DB, no network — the real Postgres seed is verified separately as the phase gate.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from ingest.cleaning import clean_funding, clean_ohlcv, detect_gaps
from ingest.pipeline import run_ingest
from ingest.report import IngestReport
from tests.conftest import FakeOhlcvCacheRepository

_ANCHOR = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _ts(i: int) -> str:
    return (_ANCHOR + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S+00:00")


def _ohlcv_rows(specs: list[tuple]) -> pd.DataFrame:
    """specs: list of (hour_index, open, high, low, close, volume)."""
    return pd.DataFrame(
        [
            {"timestamp": _ts(i), "open": o, "high": h, "low": l, "close": c, "volume": v}
            for (i, o, h, l, c, v) in specs
        ]
    )


def _good(i: int) -> tuple:
    """A clean, consistent, traded candle at hour i."""
    base = 100 + i
    return (i, base, base + 1.0, base - 1.0, base + 0.5, 10.0 + i)


# ── individual cleaning rules ────────────────────────────────────────────────


def test_clean_keeps_good_candles():
    df = _ohlcv_rows([_good(0), _good(1), _good(2)])
    clean, stats = clean_ohlcv(df)
    assert stats.clean_rows == 3
    assert stats.dropped_total == 0
    assert list(clean.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_drops_zero_volume():
    df = _ohlcv_rows([_good(0), (1, 50, 51, 49, 50.5, 0.0), _good(2)])
    clean, stats = clean_ohlcv(df)
    assert stats.dropped_zero_volume == 1
    assert stats.clean_rows == 2


def test_keeps_zero_volume_when_disabled():
    df = _ohlcv_rows([_good(0), (1, 50, 51, 49, 50.5, 0.0)])
    clean, stats = clean_ohlcv(df, drop_zero_volume=False)
    assert stats.dropped_zero_volume == 0
    assert stats.clean_rows == 2


def test_drops_flat_candle_even_with_volume():
    # high == low → flat forward-fill artefact, dropped despite nominal volume.
    df = _ohlcv_rows([_good(0), (1, 90.22, 90.22, 90.22, 90.22, 1.0)])
    clean, stats = clean_ohlcv(df)
    assert stats.dropped_flat == 1
    assert stats.clean_rows == 1


def test_keeps_flat_when_disabled():
    df = _ohlcv_rows([_good(0), (1, 90.22, 90.22, 90.22, 90.22, 1.0)])
    clean, stats = clean_ohlcv(df, drop_flat=False)
    assert stats.dropped_flat == 0
    assert stats.clean_rows == 2


def test_drops_nonpositive_price():
    df = _ohlcv_rows([_good(0), (1, 0.0, 1.0, 0.0, 0.5, 5.0), (2, -1, 1, -2, 0.5, 5.0)])
    clean, stats = clean_ohlcv(df)
    assert stats.dropped_nonpositive == 2
    assert stats.clean_rows == 1


def test_drops_ohlc_inconsistent():
    # high < low ; and high below open/close
    df = _ohlcv_rows([
        _good(0),
        (1, 100, 95, 99, 100, 5.0),   # high < low (95 < 99) -> inconsistent
        (2, 100, 100.5, 99, 102, 5.0),  # high < close (100.5 < 102) -> inconsistent
    ])
    clean, stats = clean_ohlcv(df)
    assert stats.dropped_inconsistent == 2
    assert stats.clean_rows == 1


def test_drops_duplicate_timestamps():
    df = _ohlcv_rows([_good(0), _good(0), _good(1)])
    clean, stats = clean_ohlcv(df)
    assert stats.duplicates_dropped == 1
    assert stats.clean_rows == 2
    assert clean["timestamp"].is_unique


def test_drops_unparseable_rows():
    # Build with a non-numeric close so the column is object dtype (mirrors a
    # malformed CSV cell); clean_ohlcv coerces it to NaN and drops the row.
    df = pd.DataFrame([
        {"timestamp": _ts(0), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 5.0},
        {"timestamp": _ts(1), "open": 100, "high": 101, "low": 99, "close": "not-a-number", "volume": 5.0},
    ])
    clean, stats = clean_ohlcv(df)
    assert stats.dropped_unparseable == 1
    assert stats.clean_rows == 1


def test_counts_are_disjoint_and_additive():
    df = _ohlcv_rows([
        _good(0),
        _good(0),                              # duplicate
        (1, 50, 51, 49, 50.5, 0.0),            # zero volume
        (2, 90, 90, 90, 90, 5.0),              # flat
        (3, 0.0, 1.0, 0.0, 0.5, 5.0),          # nonpositive
        (4, 100, 95, 99, 100, 5.0),            # inconsistent
        _good(5),
    ])
    clean, s = clean_ohlcv(df)
    assert s.raw_rows == (
        s.dropped_unparseable + s.duplicates_dropped + s.dropped_nonpositive
        + s.dropped_inconsistent + s.dropped_zero_volume + s.dropped_flat + s.clean_rows
    )
    assert s.clean_rows == 2  # the two _good rows


def test_sorts_unsorted_input():
    df = _ohlcv_rows([_good(2), _good(0), _good(1)])
    clean, _ = clean_ohlcv(df)
    assert list(clean["timestamp"]) == sorted(clean["timestamp"])


def test_missing_column_raises():
    df = _ohlcv_rows([_good(0)]).drop(columns=["volume"])
    with pytest.raises(ValueError):
        clean_ohlcv(df)


# ── gap detection ────────────────────────────────────────────────────────────


def test_detect_gaps_none_when_contiguous():
    ts = pd.to_datetime([_ts(i) for i in range(5)], utc=True).to_series()
    assert detect_gaps(ts) == (0, 0)


def test_detect_gaps_counts_missing_bars():
    # hours 0,1, then jump to 5 (missing 2,3,4 = 3), then 6, then 9 (missing 7,8 = 2)
    ts = pd.to_datetime([_ts(i) for i in [0, 1, 5, 6, 9]], utc=True).to_series()
    total, largest = detect_gaps(ts)
    assert total == 5
    assert largest == 3


def test_detect_gaps_single_point():
    ts = pd.to_datetime([_ts(0)], utc=True).to_series()
    assert detect_gaps(ts) == (0, 0)


def test_clean_reports_gap_after_dropping_dirty_bar():
    # Drop the middle bar (flat) → leaves a 1-bar gap between hour 0 and hour 2.
    df = _ohlcv_rows([_good(0), (1, 90, 90, 90, 90, 5.0), _good(2)])
    clean, stats = clean_ohlcv(df)
    assert stats.clean_rows == 2
    assert stats.gap_count == 1
    assert stats.largest_gap_hours == 1


# ── funding cleaning ─────────────────────────────────────────────────────────


def test_clean_funding_dedups_and_sorts():
    df = pd.DataFrame({
        "timestamp": [_ts(2), _ts(0), _ts(0), _ts(1)],
        "funding_rate": [0.003, 0.001, 0.001, 0.002],
    })
    clean, raw, dup = clean_funding(df)
    assert raw == 4
    assert dup == 1
    assert len(clean) == 3
    assert list(clean["timestamp"]) == sorted(clean["timestamp"])


# ── pipeline (end-to-end, fake repo) ─────────────────────────────────────────


def _write_market_csvs(d: Path, market: str, n_good: int, n_flat: int) -> None:
    specs = [_good(i) for i in range(n_good)]
    specs += [(n_good + j, 90, 90, 90, 90, 1.0) for j in range(n_flat)]  # flat tail
    _ohlcv_rows(specs).to_csv(d / f"{market}_ohlcv_1h.csv", index=False)
    pd.DataFrame({
        "timestamp": [_ts(i) for i in range(n_good)],
        "funding_rate": [1e-5] * n_good,
    }).to_csv(d / f"{market}_funding.csv", index=False)


async def test_pipeline_includes_excludes_and_seeds(tmp_path: Path):
    data_dir = tmp_path / "dydx"
    data_dir.mkdir()
    _write_market_csvs(data_dir, "RICH-USD", n_good=10, n_flat=3)   # 10 clean
    _write_market_csvs(data_dir, "POOR-USD", n_good=2, n_flat=5)    # 2 clean

    repo = FakeOhlcvCacheRepository()
    report = await run_ingest(
        [data_dir], repo=repo, min_coverage_rows=5, exchange="dydx", resolution="1HOUR"
    )

    assert isinstance(report, IngestReport)
    assert report.markets_included == 1
    assert report.markets_excluded == 1

    by_market = {m.market: m for m in report.markets}
    assert by_market["RICH-USD"].included is True
    assert by_market["RICH-USD"].cached_rows == 10
    assert by_market["RICH-USD"].stats.dropped_flat == 3
    assert by_market["POOR-USD"].included is False
    assert by_market["POOR-USD"].exclusion_reason == "low_coverage"

    # Only the included market is written to the cache.
    assert ("dydx", "RICH-USD", "1HOUR") in repo.candles
    assert ("dydx", "POOR-USD", "1HOUR") not in repo.candles
    assert len(repo.candles[("dydx", "RICH-USD", "1HOUR")]) == 10
    # Funding seeded only for the included market.
    assert ("dydx", "RICH-USD") in repo.funding
    assert ("dydx", "POOR-USD") not in repo.funding


async def test_pipeline_dry_run_writes_nothing(tmp_path: Path):
    data_dir = tmp_path / "dydx"
    data_dir.mkdir()
    _write_market_csvs(data_dir, "RICH-USD", n_good=10, n_flat=0)

    repo = FakeOhlcvCacheRepository()
    report = await run_ingest(
        [data_dir], repo=repo, min_coverage_rows=5, dry_run=True
    )
    assert report.markets_included == 1
    assert report.markets[0].cached_rows == 0
    assert repo.candles == {}
    assert repo.funding == {}


async def test_pipeline_report_markdown_renders(tmp_path: Path):
    data_dir = tmp_path / "dydx"
    data_dir.mkdir()
    _write_market_csvs(data_dir, "RICH-USD", n_good=8, n_flat=2)

    repo = FakeOhlcvCacheRepository()
    report = await run_ingest([data_dir], repo=repo, min_coverage_rows=5)
    md = report.to_markdown()
    assert "Historical Data Ingest" in md
    assert "RICH-USD" in md
    assert "Per-market OHLCV" in md


async def test_pipeline_skips_missing_dir(tmp_path: Path):
    repo = FakeOhlcvCacheRepository()
    report = await run_ingest(
        [tmp_path / "does-not-exist"], repo=repo, min_coverage_rows=5
    )
    assert report.markets == []
    assert report.total_cached_rows == 0
