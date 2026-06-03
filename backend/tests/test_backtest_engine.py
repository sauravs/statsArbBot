"""
Integration tests for the walk-forward backtest engine (Phase 8, PRD F8).

Drives the real ``BacktestEngine`` against an injected in-memory candle source +
``FakeStrategyRepository`` (no DB, no network). Verifies the gate's core: a backtest
sweeps walk-forward windows to completion (re-scanning each formation window and
trading the test window through the shared ``run_tick``), persists viewable
aggregates + a report, ranks strategies by net P&L, and supports pause→resume and
stop with partial save.
"""

from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import config
import db.backtest_repository as repo_module
from backtest.engine import BacktestEngine
from tests.conftest import FakeStrategyRepository

_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)
_N = 420  # hourly bars (~17.5 days) — enough for 3 short walk-forward windows


class FakeCandleSource:
    def __init__(self, candles_by_market, funding_by_market=None):
        self._candles = candles_by_market
        self._funding = funding_by_market or {}

    async def get_candles(self, market, *, start, end):
        return [c for c in self._candles.get(market, []) if start <= c["timestamp"] <= end]

    async def get_funding(self, market, *, start, end):
        return [c for c in self._funding.get(market, []) if start <= c["timestamp"] <= end]

    async def available_markets(self):
        return sorted(self._candles.keys())


def _candles(closes):
    return [
        {"timestamp": _ANCHOR + timedelta(hours=i), "close": float(c)}
        for i, c in enumerate(closes)
    ]


def _cointegrated(seed, beta, alpha):
    rng = np.random.default_rng(seed)
    s2 = 100 + np.cumsum(rng.normal(0, 1, _N))
    eps = np.zeros(_N)
    for t in range(1, _N):
        eps[t] = 0.5 * eps[t - 1] + rng.normal(0, 0.6)
    s1 = beta * s2 + alpha + eps
    return s1, s2


@pytest.fixture
def ctx(monkeypatch):
    repo = FakeStrategyRepository()
    monkeypatch.setattr(repo_module, "_repo", repo)
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "fake")
    s1, s2 = _cointegrated(11, beta=2.0, alpha=5.0)
    candles = {"AAA-USD": _candles(s1), "BBB-USD": _candles(s2)}
    source = {"value": FakeCandleSource(candles)}
    import backtest.engine as engine_module
    monkeypatch.setattr(engine_module, "make_candle_source", lambda **_: source["value"])
    return types.SimpleNamespace(repo=repo, source=source, candles=candles)


def _params(**over):
    p = {
        "exchange": "dydx", "name": "S1", "description": "t",
        "scan_window_days": 7, "trade_window_days": 3,
        "zscore_window": 21, "entry_threshold": 0.5, "exit_threshold": 0.5,
        "stop_threshold": 4.0, "pvalue_max": 0.05, "max_half_life_h": 72.0,
        "start_time": _ANCHOR, "end_time": _ANCHOR + timedelta(hours=_N - 1),
        "starting_capital": 10_000.0, "usd_per_trade": 100.0,
        "max_active_pairs": None, "slippage_pct": 0.0, "taker_fee_pct": 0.0,
        "funding_freq_h": 1, "status": "PENDING",
    }
    p.update(over)
    return p


async def test_backtest_completes_with_aggregates(ctx):
    engine = BacktestEngine()
    row = await ctx.repo.create(_params())
    await engine.run(row["id"])
    done = await ctx.repo.get(row["id"])

    assert done["status"] == "COMPLETED"
    assert done["total_windows"] >= 2
    assert done["processed_windows"] == done["total_windows"]
    assert done["progress"] == 1.0
    # A low entry threshold over the mean-reverting demo spread → real trades.
    assert done["total_trades"] > 0
    assert done["final_capital"] is not None
    # net_pnl = final − starting.
    assert done["net_pnl"] == pytest.approx(done["final_capital"] - 10_000.0, abs=1e-4)
    # Aggregates populated.
    assert done["equity_curve"] and all("equity" in p for p in done["equity_curve"])
    assert len(done["per_window"]) == done["total_windows"]
    assert "AAA-USD/BBB-USD" in done["per_pair_pnl"]
    assert sum(done["exit_reasons"].values()) == done["total_trades"]
    # win_rate is a fraction.
    assert 0.0 <= done["win_rate"] <= 1.0
    # Report generated + rank assigned (single strategy → rank 1).
    assert done["report_md"] and "Backtest Report" in done["report_md"]
    assert done["rank"] == 1


async def test_no_windows_fails(ctx):
    engine = BacktestEngine()
    # Span shorter than one scan+trade window (7+3=10d) → nothing to score.
    row = await ctx.repo.create(_params(end_time=_ANCHOR + timedelta(days=5)))
    await engine.run(row["id"])
    done = await ctx.repo.get(row["id"])
    assert done["status"] == "FAILED"
    assert "window" in done["error"].lower()


async def test_pause_then_resume(ctx):
    engine = BacktestEngine()
    row = await ctx.repo.create(_params())
    sid = row["id"]

    # Pause after the first window completes (deterministic, not racy).
    orig = engine._run_window
    seen = {"n": 0}

    async def wrapped(*a, **k):
        cap = await orig(*a, **k)
        seen["n"] += 1
        if seen["n"] == 1:
            engine._control[sid] = "pause"
        return cap

    engine._run_window = wrapped
    await engine.run(sid)

    paused = await ctx.repo.get(sid)
    assert paused["status"] == "PAUSED"
    assert paused["processed_windows"] == 1
    assert paused["processed_windows"] < paused["total_windows"]
    trades_at_pause = paused["total_trades"]

    # Resume → completes from window 1, accumulating onto the paused state.
    await engine.run(sid)
    done = await ctx.repo.get(sid)
    assert done["status"] == "COMPLETED"
    assert done["processed_windows"] == done["total_windows"]
    assert done["total_trades"] >= trades_at_pause
    assert len(done["per_window"]) == done["total_windows"]
    assert done["rank"] == 1


async def test_stop_is_terminal_with_partial_results(ctx):
    engine = BacktestEngine()
    row = await ctx.repo.create(_params())
    sid = row["id"]

    orig = engine._run_window
    seen = {"n": 0}

    async def wrapped(*a, **k):
        cap = await orig(*a, **k)
        seen["n"] += 1
        if seen["n"] == 1:
            engine._control[sid] = "stop"
        return cap

    engine._run_window = wrapped
    await engine.run(sid)

    stopped = await ctx.repo.get(sid)
    assert stopped["status"] == "STOPPED"
    assert stopped["processed_windows"] == 1
    assert stopped["processed_windows"] < stopped["total_windows"]
    # A stopped run still books its partial result + report + rank.
    assert stopped["net_pnl"] is not None
    assert stopped["report_md"]
    assert stopped["rank"] == 1


async def test_ranking_orders_by_net_pnl(ctx):
    engine = BacktestEngine()
    a = await ctx.repo.create(_params(name="A", entry_threshold=0.5))
    b = await ctx.repo.create(_params(name="B", entry_threshold=1.5))
    await engine.run(a["id"])
    await engine.run(b["id"])

    rows = await engine.list()
    ranked = [r for r in rows if r["rank"] is not None]
    assert len(ranked) == 2
    ranked.sort(key=lambda r: r["rank"])
    assert ranked[0]["rank"] == 1 and ranked[1]["rank"] == 2
    # Rank 1 has the higher (or equal) net P&L.
    assert ranked[0]["net_pnl"] >= ranked[1]["net_pnl"]
