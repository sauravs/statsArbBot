"""Unit tests for the markdown backtest report (Phase 8, PRD F8.3)."""

from __future__ import annotations

from backtest.report import build_report


def _row(**over):
    row = {
        "id": "strat_1",
        "name": "S1 — Baseline",
        "description": "Entry |Z|≥1.5",
        "status": "COMPLETED",
        "rank": 1,
        "scan_window_days": 90,
        "trade_window_days": 30,
        "zscore_window": 21,
        "entry_threshold": 1.5,
        "exit_threshold": 0.5,
        "stop_threshold": 4.0,
        "pvalue_max": 0.05,
        "max_half_life_h": 72.0,
        "starting_capital": 10_000.0,
        "usd_per_trade": 100.0,
        "start_time": "2025-01-01T00:00:00+00:00",
        "end_time": "2025-12-31T00:00:00+00:00",
        "net_pnl": 153.25,
        "final_capital": 10_153.25,
        "total_trades": 12,
        "win_rate": 0.5,
        "processed_windows": 9,
        "total_windows": 9,
        "per_window": [
            {"index": 0, "scan_start": "2025-01-01", "scan_end": "2025-04-01",
             "trade_start": "2025-04-01", "trade_end": "2025-05-01",
             "pairs": 3, "trades": 5, "net_pnl": 40.0},
        ],
        "per_pair_pnl": {"AAA-USD/BBB-USD": {"net_pnl": 153.25, "trades": 12, "wins": 6}},
        "exit_reasons": {"TAKE_PROFIT": 8, "STOP_LOSS_ZSCORE": 4},
    }
    row.update(over)
    return row


def test_report_renders_all_sections():
    md = build_report(_row())
    assert "# Backtest Report — S1 — Baseline" in md
    assert "**Status:** COMPLETED" in md and "**Rank:** #1" in md
    assert "## Parameters" in md
    assert "## Results" in md
    assert "Net P&L" in md and "$153.25" in md
    assert "50.0%" in md  # win rate
    assert "## Walk-Forward Windows" in md
    assert "AAA-USD/BBB-USD" in md
    assert "## Exit Reasons" in md and "TAKE_PROFIT" in md


def test_report_handles_empty_run():
    md = build_report(_row(
        net_pnl=None, final_capital=None, total_trades=0, win_rate=None,
        per_window=[], per_pair_pnl={}, exit_reasons={},
    ))
    assert "_No windows processed._" in md
    assert "_No closed trades._" in md
    assert "_No exits._" in md
