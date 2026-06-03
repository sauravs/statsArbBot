"""
Walk-forward window math (PRD F8.1) — pure, no DB/IO.

A walk-forward backtest slides a (scan, trade) window pair across history: scan a
formation window of ``scan_days`` to select cointegrated pairs, then trade the
immediately-following ``trade_days`` test window on out-of-sample data, then step
forward by ``trade_days`` and repeat. Stepping by the trade length tiles the test
windows edge-to-edge so every hour after the first formation window is traded
exactly once (no overlap, no gap).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Window:
    """One walk-forward step: a formation (scan) window then a test (trade) window."""

    index: int
    scan_start: datetime
    scan_end: datetime      # == trade_start (the formation/test boundary)
    trade_start: datetime
    trade_end: datetime


def build_windows(
    start: datetime, end: datetime, *, scan_days: int, trade_days: int
) -> list[Window]:
    """Tile [start, end] into walk-forward windows.

    Window i scans ``[start + i·trade, start + i·trade + scan]`` and trades the
    following ``trade`` span. Adjacent windows share the formation/test boundary
    timestamp (``trade_end`` of window i == ``trade_start`` of window i+1); the
    engine trades strictly *after* ``trade_start`` (see ``engine._run_window``), so
    every hour after the first formation window is traded exactly once — no overlap,
    no gap, and no bar is both fit-on and traded-on. Only windows whose **trade**
    span fits entirely within ``end`` are kept (a partial final test window is
    dropped — there is no out-of-sample data to score it). Returns ``[]`` when the
    span is too short to hold even one scan+trade window.
    """
    if scan_days <= 0 or trade_days <= 0 or end <= start:
        return []
    scan = timedelta(days=scan_days)
    trade = timedelta(days=trade_days)
    windows: list[Window] = []
    i = 0
    while True:
        scan_start = start + i * trade
        scan_end = scan_start + scan
        trade_end = scan_end + trade
        if trade_end > end:
            break
        windows.append(
            Window(
                index=i,
                scan_start=scan_start,
                scan_end=scan_end,
                trade_start=scan_end,
                trade_end=trade_end,
            )
        )
        i += 1
    return windows
