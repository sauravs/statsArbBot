"""
Unit tests for the simulation engine core (PRD F6.1/F6.2) and the realtime feed.

``run_tick`` is driven directly with scripted :class:`PairTick` snapshots and a
``FakeSimRepository`` (no DB), so entry/exit/funding/time-stop behaviour is
deterministic. The feed tests prove the headline fix: the Z-score is the proper
``statcore`` rolling Z — not the prototype's ``abs(spread)·0.02`` approximation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from simulation.engine import run_tick
from simulation.feed import PairTick, build_realtime_snapshots
from statcore import compute_spread, latest_zscore
from tests.conftest import FakeDydxClient, FakeSimRepository, make_cointegrated_series

pytestmark = pytest.mark.asyncio

NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _snap(base="DEMO1-USD", quote="DEMO2-USD", *, z, base_price=100.0, quote_price=50.0,
          hedge_ratio=2.0, half_life=10.0) -> PairTick:
    return PairTick(
        base_market=base, quote_market=quote, hedge_ratio=hedge_ratio,
        half_life=half_life, base_price=base_price, quote_price=quote_price,
        z_score=z, spread_value=0.0,
    )


async def _make_session(repo, **overrides) -> dict:
    params = {
        "exchange": "dydx", "starting_capital": 10_000.0, "interval_seconds": 60,
        "entry_threshold": 1.5, "exit_threshold": 0.5, "stop_threshold": 4.0,
        "usd_per_trade": 100.0, "slippage_pct": 0.0, "taker_fee_pct": 0.0,
    }
    params.update(overrides)
    return await repo.create_session(params)


# ── entries ──────────────────────────────────────────────────────────────────


async def test_entry_opens_on_signal():
    repo = FakeSimRepository()
    session = await _make_session(repo)
    summary = await run_tick(repo, session, [_snap(z=2.5)], now=NOW)
    assert summary["entries"] == 1 and summary["exits"] == 0
    positions = await repo.get_open_positions(session["id"])
    assert len(positions) == 1
    p = positions[0]
    assert p["direction"] == "SHORT_BASE"  # z>0
    assert p["entry_z"] == 2.5
    assert p["base_size"] == pytest.approx(1.0) and p["quote_size"] == pytest.approx(2.0)


async def test_no_entry_below_threshold():
    repo = FakeSimRepository()
    session = await _make_session(repo)
    summary = await run_tick(repo, session, [_snap(z=1.0)], now=NOW)
    assert summary["entries"] == 0
    assert await repo.get_open_positions(session["id"]) == []


async def test_no_double_open_same_pair():
    repo = FakeSimRepository()
    session = await _make_session(repo)
    await run_tick(repo, session, [_snap(z=2.5)], now=NOW)
    session = await repo.get_session(session["id"])
    summary = await run_tick(repo, session, [_snap(z=2.5)], now=NOW)
    assert summary["entries"] == 0
    assert len(await repo.get_open_positions(session["id"])) == 1


async def test_max_active_pairs_cap():
    repo = FakeSimRepository()
    session = await _make_session(repo, max_active_pairs=1)
    snaps = [_snap("A-USD", "B-USD", z=2.5), _snap("C-USD", "D-USD", z=2.5)]
    summary = await run_tick(repo, session, snaps, now=NOW)
    assert summary["entries"] == 1


async def test_capital_margin_guard_blocks_entry():
    repo = FakeSimRepository()
    session = await _make_session(repo, starting_capital=50.0, usd_per_trade=100.0)
    summary = await run_tick(repo, session, [_snap(z=2.5)], now=NOW)
    assert summary["entries"] == 0  # capital 50 < usd_per_trade 100


async def test_aggregate_margin_cap_limits_simultaneous_entries():
    # Capital fits exactly one $100 leg, not two — the second signal is blocked
    # even with no max_active_pairs cap (the over-leverage guard).
    repo = FakeSimRepository()
    session = await _make_session(repo, starting_capital=150.0, usd_per_trade=100.0)
    snaps = [_snap("A-USD", "B-USD", z=2.5), _snap("C-USD", "D-USD", z=2.5)]
    summary = await run_tick(repo, session, snaps, now=NOW)
    assert summary["entries"] == 1
    assert len(await repo.get_open_positions(session["id"])) == 1


# ── exits ────────────────────────────────────────────────────────────────────


async def _open_one(repo, session, **snap_kw):
    await run_tick(repo, session, [_snap(z=2.0, **snap_kw)], now=NOW)
    return await repo.get_session(session["id"])


async def test_take_profit_exit_updates_capital():
    repo = FakeSimRepository()
    session = await _make_session(repo)
    session = await _open_one(repo, session)
    # z reverts below exit threshold; prices move so the short-base trade profits.
    snap = _snap(z=0.1, base_price=90.0, quote_price=55.0)
    summary = await run_tick(repo, session, [snap], now=NOW + timedelta(hours=1))
    assert summary["exits"] == 1
    trades = await repo.list_trades(session["id"])
    assert trades[0]["exit_reason"] == "TAKE_PROFIT"
    # SHORT_BASE: base 1u 100→90 = +10 ; quote(long) 2u 50→55 = +10 → +20
    assert trades[0]["net_pnl"] == pytest.approx(20.0)
    session = await repo.get_session(session["id"])
    assert session["current_capital"] == pytest.approx(10_020.0)
    assert await repo.get_open_positions(session["id"]) == []


async def test_stop_loss_zscore_exit():
    repo = FakeSimRepository()
    session = await _make_session(repo)
    session = await _open_one(repo, session)
    summary = await run_tick(repo, session, [_snap(z=4.5)], now=NOW + timedelta(hours=1))
    assert summary["exits"] == 1
    assert (await repo.list_trades(session["id"]))[0]["exit_reason"] == "STOP_LOSS_ZSCORE"


async def test_stop_loss_does_not_reenter_same_tick():
    # A stop-loss close must NOT be re-opened on the same snapshot (it would churn
    # stop→reopen→stop on a broken pair). |Z|=4.5 ≥ stop 4.0 closes; the same snap
    # passes evaluate_entry (no upper bound) but the just-exited guard blocks it.
    repo = FakeSimRepository()
    session = await _make_session(repo)
    session = await _open_one(repo, session)
    summary = await run_tick(repo, session, [_snap(z=4.5)], now=NOW + timedelta(hours=1))
    assert summary["exits"] == 1 and summary["entries"] == 0
    assert await repo.get_open_positions(session["id"]) == []


async def test_hold_between_thresholds():
    repo = FakeSimRepository()
    session = await _make_session(repo)
    session = await _open_one(repo, session)
    summary = await run_tick(repo, session, [_snap(z=1.0)], now=NOW + timedelta(hours=1))
    assert summary["exits"] == 0
    assert len(await repo.get_open_positions(session["id"])) == 1


async def test_time_stop_fires_when_aged_out():
    repo = FakeSimRepository()
    session = await _make_session(repo)
    # Open at NOW with a short half-life.
    await run_tick(repo, session, [_snap(z=2.0, half_life=2.0)], now=NOW)
    session = await repo.get_session(session["id"])
    # 7h later, |Z|=1.0 holds on price but age 7 > 3×2=6 → time stop.
    summary = await run_tick(repo, session, [_snap(z=1.0, half_life=2.0)],
                             now=NOW + timedelta(hours=7))
    assert summary["exits"] == 1
    assert (await repo.list_trades(session["id"]))[0]["exit_reason"] == "STOP_LOSS_TIME"


async def test_no_snapshot_holds_position():
    repo = FakeSimRepository()
    session = await _make_session(repo)
    session = await _open_one(repo, session)
    # Tick with snapshots for a *different* pair → the open pair has no price → hold.
    summary = await run_tick(repo, session, [_snap("X-USD", "Y-USD", z=0.1)],
                             now=NOW + timedelta(hours=1))
    assert summary["exits"] == 0
    assert len(await repo.get_open_positions(session["id"])) == 1


# ── statelessness across ticks (F6.1) ────────────────────────────────────────


async def test_stateless_across_ticks_via_repo():
    repo = FakeSimRepository()
    session = await _make_session(repo)
    await run_tick(repo, session, [_snap(z=2.5)], now=NOW)
    # Simulate a restart: nothing in memory; re-read the session and tick again.
    reloaded = await repo.get_session(session["id"])
    assert reloaded["tick_count"] == 1
    await run_tick(repo, reloaded, [_snap(z=0.1, base_price=90.0, quote_price=55.0)],
                   now=NOW + timedelta(hours=1))
    assert (await repo.get_session(session["id"]))["tick_count"] == 2
    assert len(await repo.list_trades(session["id"])) == 1


# ── funding accrual (F6.3) ───────────────────────────────────────────────────


async def test_funding_accrues_between_ticks():
    repo = FakeSimRepository()
    session = await _make_session(repo, funding_freq_h=1)
    # Open at NOW (sets last_tick_at = NOW).
    await run_tick(repo, session, [_snap(z=2.0)], now=NOW)
    session = await repo.get_session(session["id"])
    # 1h later, a positive funding rate accrues onto the open SHORT_BASE position.
    await run_tick(
        repo, session, [_snap(z=2.0)], now=NOW + timedelta(hours=1),
        funding_rates={"DEMO1-USD": 0.01, "DEMO2-USD": 0.0},
    )
    pos = (await repo.get_open_positions(session["id"]))[0]
    # SHORT_BASE receives base funding: +0.01 · (1u·100) · 1 period = +1.0
    assert pos["funding_pnl"] == pytest.approx(1.0)


# ── feed: proper rolling Z (F6.2 — the headline fix) ─────────────────────────


async def test_feed_uses_statcore_rolling_zscore_not_002_approx():
    s1, s2 = make_cointegrated_series(seed=7)
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2})
    pairs = [{"base_market": "AAA-USD", "quote_market": "BBB-USD",
              "hedge_ratio": 2.0, "intercept": 5.0, "half_life": 3.0}]
    snaps = await build_realtime_snapshots(client, pairs, window=21)
    assert len(snaps) == 1
    snap = snaps[0]
    # The feed's Z equals statcore's latest rolling Z over the real spread …
    spread = compute_spread(np.array(s1), np.array(s2), 2.0, 5.0)
    expected_z = latest_zscore(spread, window=21)
    assert snap.z_score == pytest.approx(expected_z)
    # … and is nothing like the prototype's abs(spread)·0.02 std approximation.
    bad_std = abs(float(spread[-1])) * 0.02 + 1e-9
    approx_z = (float(spread[-1]) - float(np.mean(spread))) / bad_std
    assert abs(snap.z_score - approx_z) > 1.0


async def test_feed_drops_pairs_without_overlapping_history():
    client = FakeDydxClient({"AAA-USD": [1.0, 2.0, 3.0]})  # BBB missing
    pairs = [{"base_market": "AAA-USD", "quote_market": "BBB-USD",
              "hedge_ratio": 1.0, "intercept": 0.0, "half_life": 3.0}]
    assert await build_realtime_snapshots(client, pairs, window=21) == []
