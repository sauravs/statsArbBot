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

import asyncio
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
        # Stamp the active source (the router does this in production) so the
        # source-scoped list (#98) surfaces these strategies.
        "exchange": "dydx", "data_source": config.SCAN_DATA_SOURCE, "name": "S1", "description": "t",
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


async def test_persists_per_trade_blotter(ctx):
    """Every closed trade is persisted, stamped with its window, with Z + prices."""
    engine = BacktestEngine()
    row = await ctx.repo.create(_params())
    await engine.run(row["id"])
    done = await ctx.repo.get(row["id"])
    assert done["total_trades"] > 0

    # All trades readable back; total matches the aggregate count.
    page = await engine.list_trades(row["id"], limit=10_000)
    assert page["total"] == done["total_trades"]
    trades = page["trades"]
    assert len(trades) == done["total_trades"]

    n_windows = done["total_windows"]
    for t in trades:
        # Stamped with a real window index.
        assert 0 <= t["window_index"] < n_windows
        # The "where on the spread" + rationale the UI surfaces.
        assert t["entry_z"] is not None
        assert t["exit_reason"]
        # Leg fill prices (the entry/exit "spot") captured.
        assert t["entry_base_px"] is not None and t["entry_quote_px"] is not None
        assert t["exit_base_px"] is not None and t["exit_quote_px"] is not None
        assert t["base_market"] == "AAA-USD" and t["quote_market"] == "BBB-USD"
        # Pair cointegration params stamped (issue #166) → chart can rebuild spread/z.
        assert t["hedge_ratio"] is not None and t["hedge_ratio"] > 0
        assert t["intercept"] is not None
        assert t["half_life"] is not None and t["half_life"] > 0

    # Per-window scoping matches the per_window aggregate trade counts.
    for w in done["per_window"]:
        scoped = await engine.list_trades(
            row["id"], window_index=w["index"], limit=10_000
        )
        assert scoped["total"] == w["trades"]


async def test_trades_pagination(ctx):
    engine = BacktestEngine()
    row = await ctx.repo.create(_params())
    await engine.run(row["id"])
    total = (await engine.list_trades(row["id"], limit=1))["total"]
    assert total >= 2

    first = await engine.list_trades(row["id"], limit=1, offset=0)
    second = await engine.list_trades(row["id"], limit=1, offset=1)
    assert len(first["trades"]) == 1 and len(second["trades"]) == 1
    # Distinct rows, stable order (entry_time then id).
    assert first["trades"][0]["id"] != second["trades"][0]["id"]


async def test_rerun_replaces_trades(ctx):
    """A fresh re-run clears the prior run's trades (no accumulation)."""
    engine = BacktestEngine()
    row = await ctx.repo.create(_params())
    await engine.run(row["id"])
    first = (await engine.list_trades(row["id"], limit=1))["total"]

    await engine.run(row["id"])  # re-run from scratch (was COMPLETED)
    second = (await engine.list_trades(row["id"], limit=1))["total"]
    assert second == first  # replaced, not doubled


async def test_resume_does_not_duplicate_trades(ctx):
    """Pause→resume persists each window's trades exactly once (issue #162)."""
    engine = BacktestEngine()
    row = await ctx.repo.create(_params())
    sid = row["id"]

    orig = engine._run_window
    seen = {"n": 0}

    async def wrapped(*a, **k):
        cap = await orig(*a, **k)
        seen["n"] += 1
        if seen["n"] == 1:
            engine._control[sid] = "pause"
        return cap

    engine._run_window = wrapped
    await engine.run(sid)  # completes window 0, then pauses
    paused_trades = (await engine.list_trades(sid, limit=1))["total"]

    engine._run_window = orig
    await engine.run(sid)  # resume → complete
    done = await ctx.repo.get(sid)
    page = await engine.list_trades(sid, limit=10_000)
    # Exactly the aggregate count — no window persisted twice.
    assert page["total"] == done["total_trades"]
    assert page["total"] >= paused_trades


async def test_load_history_bounds_concurrency(monkeypatch):
    """_load_history caps concurrent per-market reads so a large venue (e.g. 180
    Hyperliquid markets → ~360 queries) can't swamp the query engine (issue #170)."""
    import backtest.engine as eng

    state = {"cur": 0, "max": 0}

    class TrackingSource:
        async def _track(self):
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
            await asyncio.sleep(0.01)
            state["cur"] -= 1

        async def get_candles(self, m, *, start, end):
            await self._track()
            return [{"timestamp": start, "close": 1.0}]

        async def get_funding(self, m, *, start, end):
            await self._track()
            return []

    monkeypatch.setattr(eng, "make_candle_source", lambda **_: TrackingSource())
    markets = [f"M{i}-USD" for i in range(60)]
    candles, funding = await eng._load_history("hyperliquid", markets, _ANCHOR, _ANCHOR)

    assert len(candles) == 60 and len(funding) == 60
    # Never exceeds the cap, yet still runs concurrently (not serialised).
    assert state["max"] <= eng._HISTORY_FETCH_CONCURRENCY
    assert state["max"] > 1


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


async def test_resume_does_not_refund_zero_capital(ctx):
    # A paused run whose capital was driven to exactly 0 must resume with 0, not be
    # silently re-funded back to starting_capital (the `current_capital or starting`
    # falsy-zero trap).
    engine = BacktestEngine()
    row = await ctx.repo.create(_params())
    sid = row["id"]
    # Simulate a paused run after window 0 with a wiped-out account.
    await ctx.repo.update(
        sid,
        {
            "status": "PAUSED", "processed_windows": 1, "total_windows": 3,
            "current_capital": 0.0, "starting_capital": 10_000.0,
            "equity_curve": [], "per_window": [], "per_pair_pnl": {},
            "exit_reasons": {}, "total_trades": 0,
        },
    )
    await engine.run(sid)
    done = await ctx.repo.get(sid)
    assert done["status"] == "COMPLETED"
    # With zero carried capital the margin guard blocks every entry, so the run
    # books no further trades and finishes at ~0 — never re-funded to 10k.
    assert done["final_capital"] == pytest.approx(0.0, abs=1e-6)
    assert done["net_pnl"] == pytest.approx(-10_000.0, abs=1e-6)


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


async def test_list_is_scoped_by_data_source(ctx, monkeypatch):
    """A strategy is visible only under the source it was created with (#98)."""
    engine = BacktestEngine()
    # ctx sets fake (DEMO) — create a demo strategy.
    await ctx.repo.create(_params(name="demo-strat"))
    assert [r["name"] for r in await engine.list()] == ["demo-strat"]

    # Switch to LIVE: the demo strategy is hidden, and a new one is scoped to live.
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "dydx")
    assert await engine.list() == []
    await ctx.repo.create(_params(name="live-strat"))
    assert [r["name"] for r in await engine.list()] == ["live-strat"]

    # Back to DEMO: only the demo strategy shows.
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "fake")
    assert [r["name"] for r in await engine.list()] == ["demo-strat"]


async def test_pause_mid_window_discards_partial_window(ctx, monkeypatch):
    """A pause that lands during a window aborts it without recording it (#100)."""
    import backtest.engine as eng_mod

    engine = BacktestEngine()
    row = await ctx.repo.create(_params(name="P"))

    # Simulate the pause request arriving DURING the first window: the scan flips the
    # control flag, so the engine's post-scan check must abort before recording it.
    real_scan = eng_mod.scan_window_pairs

    def scan_then_pause(*a, **k):
        engine._control[row["id"]] = "pause"
        return real_scan(*a, **k)

    monkeypatch.setattr(eng_mod, "scan_window_pairs", scan_then_pause)
    await engine.run(row["id"])

    done = await ctx.repo.get(row["id"])
    assert done["status"] == "PAUSED"
    assert done["processed_windows"] == 0            # no window completed
    assert not done["per_window"]                    # partial window not recorded
    assert not done["equity_curve"]                  # no half-window equity points


# ── Per-market realistic cost model (Phase-2 Slice 1) ────────────────────────


async def _run_net(ctx, **param_over) -> float:
    """Run one fake-mode sweep to completion; return its net P&L."""
    engine = BacktestEngine()
    row = await ctx.repo.create(_params(**param_over))
    await engine.run(row["id"])
    done = await ctx.repo.get(row["id"])
    assert done["status"] == "COMPLETED"
    assert done["total_trades"] > 0
    return done["net_pnl"]


async def test_per_market_uniform_spread_reproduces_flat(ctx, monkeypatch):
    """A per-market model with a uniform half-spread == the flat run (exactly).

    Proves the per-leg wiring is a faithful generalisation: charging every market
    the same 0.1% via the map yields the same net as the flat slippage_pct=0.1.
    """
    from simulation import spread_cost

    flat_net = await _run_net(ctx, slippage_pct=0.1, taker_fee_pct=0.0)

    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", True)
    monkeypatch.setattr(
        spread_cost, "SEED_HALF_SPREAD_PCT", {"AAA-USD": 0.1, "BBB-USD": 0.1}
    )
    pm_net = await _run_net(ctx, slippage_pct=0.0, taker_fee_pct=0.0)
    assert pm_net == pytest.approx(flat_net, abs=1e-6)


async def test_per_market_wider_spread_cuts_net_deterministically(ctx, monkeypatch):
    """Wider per-market half-spreads charge more, so net falls — and it's stable."""
    from simulation import spread_cost

    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", True)

    monkeypatch.setattr(
        spread_cost, "SEED_HALF_SPREAD_PCT", {"AAA-USD": 0.1, "BBB-USD": 0.1}
    )
    cheap = await _run_net(ctx, slippage_pct=0.0, taker_fee_pct=0.0)

    monkeypatch.setattr(
        spread_cost, "SEED_HALF_SPREAD_PCT", {"AAA-USD": 0.5, "BBB-USD": 0.5}
    )
    dear = await _run_net(ctx, slippage_pct=0.0, taker_fee_pct=0.0)
    dear_again = await _run_net(ctx, slippage_pct=0.0, taker_fee_pct=0.0)

    assert dear < cheap                       # wider spread → more cost → lower net
    assert dear == pytest.approx(dear_again)  # deterministic across identical runs


async def test_per_market_off_ignores_map(ctx, monkeypatch):
    """With PER_MARKET_SLIPPAGE off, the seed table has no effect (flat cost)."""
    from simulation import spread_cost

    base = await _run_net(ctx, slippage_pct=0.1, taker_fee_pct=0.0)
    # A loud override table must NOT change the net while the flag is off (default).
    monkeypatch.setattr(
        spread_cost, "SEED_HALF_SPREAD_PCT", {"AAA-USD": 0.9, "BBB-USD": 0.9}
    )
    still_flat = await _run_net(ctx, slippage_pct=0.1, taker_fee_pct=0.0)
    assert still_flat == pytest.approx(base, abs=1e-6)
