"""
Integration tests for the fast-forward replay engine (Phase 7).

Drives the real ``FastForwardReplayEngine`` against an injected in-memory candle
source + ``FakeScanRepository`` + ``FakeFFRepository`` (no DB, no network). Verifies
the gate's core: a replay over a date range completes, opens/closes virtual trades
on real signals through the shared ``run_tick``, and persists viewable aggregates
(equity curve, per-pair P&L, exit reasons). Also covers funding accrual from the
supplied rates (issue #23, replay half) and mid-run cancellation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import config
import db.ff_repository as ff_repo_module
import db.scan_repository as scan_repo_module
import replay.engine as engine_module
from replay.engine import FastForwardReplayEngine
from tests.conftest import FakeFFRepository, FakeScanRepository

_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)
_N = 250
_WINDOW = 21


class FakeCandleSource:
    """In-memory candle/funding source the engine reads instead of OhlcvCache."""

    def __init__(self, candles_by_market, funding_by_market=None):
        self._candles = candles_by_market
        self._funding = funding_by_market or {}

    async def get_candles(self, market, *, start, end):
        return [c for c in self._candles.get(market, []) if start <= c["timestamp"] <= end]

    async def get_funding(self, market, *, start, end):
        return [c for c in self._funding.get(market, []) if start <= c["timestamp"] <= end]


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
    scan_repo = FakeScanRepository()
    ff_repo = FakeFFRepository()
    monkeypatch.setattr(scan_repo_module, "_repo", scan_repo)
    monkeypatch.setattr(ff_repo_module, "_repo", ff_repo)
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "fake")

    s1, s2 = _cointegrated(11, beta=2.0, alpha=5.0)
    candles = {"AAA-USD": _candles(s1), "BBB-USD": _candles(s2)}
    source = {"value": FakeCandleSource(candles)}
    monkeypatch.setattr(engine_module, "make_candle_source", lambda **_: source["value"])

    # Seed the latest scan with the pair's true β/α so the spread matches.
    async def _seed():
        await scan_repo.replace_scan_results(
            [{
                "base_market": "AAA-USD", "quote_market": "BBB-USD",
                "hedge_ratio": 2.0, "intercept": 5.0, "half_life": 2.0,
                "zero_crossings": 40, "p_value": 0.001, "z_score": 0.0,
                "spread_std": 1.0,
                "scanned_at": _ANCHOR, "window_start": _ANCHOR, "window_end": _ANCHOR,
                "exchange": "dydx", "mode": config.DEFAULT_MODE,
            }],
            exchange="dydx", mode=config.DEFAULT_MODE,
        )

    import types

    return types.SimpleNamespace(
        scan_repo=scan_repo, ff_repo=ff_repo, source=source, seed=_seed, candles=candles
    )


def _params(**over):
    p = {
        "exchange": "dydx", "label": "t",
        "start_time": _ANCHOR + timedelta(hours=_WINDOW),
        "end_time": _ANCHOR + timedelta(hours=_N - 1),
        "speed": 3600, "starting_capital": 10_000.0,
        "zscore_window": _WINDOW, "entry_threshold": 0.5, "exit_threshold": 0.5,
        "stop_threshold": 4.0, "usd_per_trade": 100.0, "max_active_pairs": None,
        "slippage_pct": 0.0, "taker_fee_pct": 0.0, "funding_freq_h": 1,
        "status": "RUNNING",
    }
    p.update(over)
    return p


async def _run(ctx, **over):
    await ctx.seed()
    engine = FastForwardReplayEngine()
    row = await ctx.ff_repo.create(_params(**over))
    await engine.run_replay(row["id"])
    return await ctx.ff_repo.get(row["id"]), engine


@pytest.mark.asyncio
async def test_replay_completes_with_aggregates(ctx):
    row, _ = await _run(ctx)
    assert row["status"] == "COMPLETED"
    assert row["pairs_count"] == 1
    assert row["total_ticks"] > 0
    assert row["progress"] == 1.0
    # A low entry threshold over a mean-reverting spread → real trades.
    assert row["total_trades"] > 0
    assert row["final_capital"] is not None
    # Aggregates are populated and viewable.
    assert row["equity_curve"] and all("equity" in p and "t" in p for p in row["equity_curve"])
    assert "AAA-USD/BBB-USD" in row["per_pair_pnl"]
    assert sum(row["exit_reasons"].values()) == row["total_trades"]
    # realised_pnl is the Σ of per-pair net P&L.
    assert row["realised_pnl"] == pytest.approx(
        sum(b["net_pnl"] for b in row["per_pair_pnl"].values()), abs=1e-6
    )


@pytest.mark.asyncio
async def test_no_scan_pairs_fails(ctx):
    # Don't seed the scan → the replay fails fast.
    engine = FastForwardReplayEngine()
    row = await ctx.ff_repo.create(_params())
    await engine.run_replay(row["id"])
    done = await ctx.ff_repo.get(row["id"])
    assert done["status"] == "FAILED"
    assert "scan" in done["error"].lower()


@pytest.mark.asyncio
async def test_funding_accrues_only_when_rates_supplied(ctx):
    # Baseline: no funding data → trades carry zero funding.
    row, _ = await _run(ctx)
    base_funding = sum(b["net_pnl"] for b in row["per_pair_pnl"].values())

    # Now attach a constant funding rate to both legs and re-run.
    funding = {
        m: [{"timestamp": _ANCHOR + timedelta(hours=i), "funding_rate": 0.001} for i in range(_N)]
        for m in ("AAA-USD", "BBB-USD")
    }
    ctx.source["value"] = FakeCandleSource(ctx.candles, funding)
    row2, _ = await _run(ctx)
    # Funding shifts realised P&L away from the no-funding baseline.
    assert row2["realised_pnl"] != pytest.approx(base_funding, abs=1e-6)


@pytest.mark.asyncio
async def test_end_of_replay_close_uses_historical_time():
    # A position opened deep in history and force-closed at the final cursor must
    # book a hold measured on the replay's timeline — not (wall-clock now − entry),
    # which would be years.
    from replay.working_repo import WorkingSimRepository

    entry = _ANCHOR + timedelta(hours=10)
    cursor = _ANCHOR + timedelta(hours=40)  # 30h later, still historical
    session = {"id": "ff_x", "exchange": "dydx", "current_capital": 10_000.0,
               "slippage_pct": 0.0, "taker_fee_pct": 0.0}
    wrepo = WorkingSimRepository(session)
    await wrepo.create_position({
        "session_id": "ff_x", "exchange": "dydx",
        "base_market": "AAA-USD", "quote_market": "BBB-USD", "direction": "LONG_BASE",
        "base_size": 1.0, "quote_size": 2.0, "hedge_ratio": 2.0, "half_life": 2.0,
        "entry_z": -1.0, "entry_base_px": 100.0, "entry_quote_px": 50.0,
        "entry_time": entry, "fee_cost": 0.0, "funding_pnl": 0.0, "status": "OPEN",
    })
    engine = FastForwardReplayEngine()
    # No aligned data → synthetic close at the final cursor.
    await engine._close_remaining(wrepo, [], cursor, _WINDOW)
    trades = await wrepo.list_trades("ff_x")
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "END_OF_REPLAY"
    assert trades[0]["hold_hours"] == pytest.approx(30.0, abs=1e-6)


@pytest.mark.asyncio
async def test_cancellation_marks_stopped(ctx):
    await ctx.seed()
    engine = FastForwardReplayEngine()
    row = await ctx.ff_repo.create(_params())
    # Pre-arm the cancel flag so the loop breaks on its first iteration.
    engine._cancelled.add(row["id"])
    await engine.run_replay(row["id"])
    done = await ctx.ff_repo.get(row["id"])
    assert done["status"] == "STOPPED"
    assert done["progress"] < 1.0
