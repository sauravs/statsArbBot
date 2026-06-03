"""Unit tests for the walk-forward window math (Phase 8, PRD F8.1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backtest.windows import build_windows

_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)


def test_windows_tile_test_spans_edge_to_edge():
    # 1 year of history, 90d scan / 30d trade → tiled test windows step by 30d.
    end = _ANCHOR + timedelta(days=365)
    windows = build_windows(_ANCHOR, end, scan_days=90, trade_days=30)
    assert len(windows) > 0
    # First window: scan [0,90], trade [90,120].
    w0 = windows[0]
    assert w0.scan_start == _ANCHOR
    assert w0.scan_end == _ANCHOR + timedelta(days=90)
    assert w0.trade_start == w0.scan_end
    assert w0.trade_end == _ANCHOR + timedelta(days=120)
    # Test windows are contiguous (each trade_start == previous trade_end).
    for prev, nxt in zip(windows, windows[1:]):
        assert nxt.trade_start == prev.trade_end
        assert nxt.index == prev.index + 1
    # No window's trade span runs past the history end.
    assert all(w.trade_end <= end for w in windows)


def test_too_short_span_yields_no_windows():
    # Only 100 days but a 90+30 window needs 120 → nothing to score.
    end = _ANCHOR + timedelta(days=100)
    assert build_windows(_ANCHOR, end, scan_days=90, trade_days=30) == []


def test_exact_fit_yields_one_window():
    end = _ANCHOR + timedelta(days=120)
    windows = build_windows(_ANCHOR, end, scan_days=90, trade_days=30)
    assert len(windows) == 1
    assert windows[0].trade_end == end


def test_invalid_inputs_yield_no_windows():
    end = _ANCHOR + timedelta(days=120)
    assert build_windows(_ANCHOR, end, scan_days=0, trade_days=30) == []
    assert build_windows(_ANCHOR, end, scan_days=90, trade_days=0) == []
    assert build_windows(end, _ANCHOR, scan_days=90, trade_days=30) == []


def test_short_windows_for_demo():
    # The offline demo uses short windows over ~16 days of synthetic history.
    end = _ANCHOR + timedelta(hours=399)
    windows = build_windows(_ANCHOR, end, scan_days=7, trade_days=3)
    assert len(windows) >= 2
    assert windows[0].scan_end - windows[0].scan_start == timedelta(days=7)
    assert windows[0].trade_end - windows[0].trade_start == timedelta(days=3)
