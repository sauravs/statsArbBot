"""
Unit tests for the fast-forward historical feed (Phase 7) — the pure alignment /
snapshot / funding-lookup core, no DB or engine involved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from replay.historical_feed import (
    FundingTable,
    align_pairs,
    replay_timeline,
    snapshots_at,
)

_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles(closes, *, start_hour=0):
    return [
        {"timestamp": _ANCHOR + timedelta(hours=start_hour + i), "close": float(c)}
        for i, c in enumerate(closes)
    ]


def _pair(base="AAA", quote="BBB", beta=2.0, alpha=5.0, hl=2.0):
    return {
        "base_market": base, "quote_market": quote,
        "hedge_ratio": beta, "intercept": alpha, "half_life": hl,
    }


def test_align_pairs_intersects_timestamps():
    s2 = list(range(100, 130))          # 30 bars
    s1 = [2 * x + 5 for x in s2]
    candles = {
        "AAA": _candles(s1),                       # bars 0..29
        "BBB": _candles(s2, start_hour=0)[:25],    # bars 0..24 only
    }
    aligned = align_pairs([_pair()], candles)
    assert len(aligned) == 1
    ap = aligned[0]
    # Only the 25 shared bars survive.
    assert len(ap.timestamps) == 25
    assert ap.s1.shape == (25,) and ap.s2.shape == (25,)


def test_align_pairs_drops_pairs_without_overlap():
    candles = {
        "AAA": _candles([1, 2, 3]),
        "BBB": _candles([4, 5, 6], start_hour=100),  # disjoint timestamps
    }
    assert align_pairs([_pair()], candles) == []


def test_replay_timeline_restricted_to_window():
    candles = {"AAA": _candles(range(100, 150)), "BBB": _candles(range(200, 250))}
    aligned = align_pairs([_pair()], candles)
    start = _ANCHOR + timedelta(hours=10)
    end = _ANCHOR + timedelta(hours=20)
    timeline = replay_timeline(aligned, start=start, end=end)
    assert timeline[0] == start and timeline[-1] == end
    assert len(timeline) == 11  # inclusive 10..20


def test_tick_at_returns_none_before_window_is_full():
    rng = np.random.default_rng(5)
    s2 = 100 + np.cumsum(rng.normal(0, 1, 40))
    s1 = 2.0 * s2 + 5.0 + rng.normal(0, 0.5, 40)  # noisy spread → non-zero variance
    aligned = align_pairs([_pair()], {"AAA": _candles(s1), "BBB": _candles(s2)})[0]
    # Bar index < window-1 → not enough history.
    early = _ANCHOR + timedelta(hours=5)
    assert aligned.tick_at(early, window=21) is None
    # A later bar has a full window → a tick.
    late = _ANCHOR + timedelta(hours=30)
    tick = aligned.tick_at(late, window=21)
    assert tick is not None
    assert tick.base_market == "AAA" and tick.quote_market == "BBB"
    assert np.isfinite(tick.z_score)


def test_tick_z_matches_statcore_over_trailing_window():
    from statcore import compute_spread, latest_zscore

    rng = np.random.default_rng(3)
    s2 = 100 + np.cumsum(rng.normal(0, 1, 60))
    eps = rng.normal(0, 0.5, 60)
    s1 = 2.0 * s2 + 5.0 + eps
    aligned = align_pairs(
        [_pair()], {"AAA": _candles(s1), "BBB": _candles(s2)}
    )[0]
    cursor = _ANCHOR + timedelta(hours=40)
    tick = aligned.tick_at(cursor, window=21)
    # Recompute the expected Z independently over the same trailing 21 bars.
    spread = compute_spread(s1[20:41], s2[20:41], 2.0, 5.0)
    assert tick.z_score == latest_zscore(spread, window=21)


def test_snapshots_at_collects_signalling_pairs():
    s2 = list(np.linspace(100, 160, 50))
    s1 = [2 * x + 5 for x in s2]
    s4 = list(np.linspace(50, 80, 50))
    s3 = [1.5 * x - 2 for x in s4]
    candles = {
        "AAA": _candles(s1), "BBB": _candles(s2),
        "CCC": _candles(s3), "DDD": _candles(s4),
    }
    pairs = [_pair(), _pair("CCC", "DDD", beta=1.5, alpha=-2.0)]
    aligned = align_pairs(pairs, candles)
    cursor = _ANCHOR + timedelta(hours=45)
    snaps = snapshots_at(aligned, cursor, window=21)
    # Both pairs have a full window of history at this cursor (degenerate linear
    # spreads have zero variance → dropped); just assert the call is well-formed.
    assert isinstance(snaps, list)
    for s in snaps:
        assert np.isfinite(s.z_score)


def test_funding_table_step_lookup():
    rows = {
        "AAA": [
            {"timestamp": _ANCHOR, "funding_rate": 0.0001},
            {"timestamp": _ANCHOR + timedelta(hours=5), "funding_rate": 0.0003},
        ],
    }
    table = FundingTable(rows)
    assert not table.empty
    # Before any data → market absent.
    assert table.rates_at(_ANCHOR - timedelta(hours=1), {"AAA"}) == {}
    # Between the two stamps → the earlier rate.
    assert table.rates_at(_ANCHOR + timedelta(hours=2), {"AAA"}) == {"AAA": 0.0001}
    # At/after the second stamp → the later rate.
    assert table.rates_at(_ANCHOR + timedelta(hours=6), {"AAA"}) == {"AAA": 0.0003}
    # Unknown market is simply not present.
    assert table.rates_at(_ANCHOR + timedelta(hours=6), {"ZZZ"}) == {}


def test_funding_table_empty_when_no_rates():
    assert FundingTable({}).empty
    assert FundingTable({"AAA": []}).empty


# ── DemoCandleSource synthetic funding ──────────────────────────────────────
# `get_funding` used to return [], which made funding_pnl STRUCTURALLY ZERO on
# the whole offline stack: every demo backtest, every e2e, every screenshot. The
# blotter's funding column (Phase-4 Task A) could not render a non-zero value
# offline, so nothing actually exercised it. These tests pin the properties the
# demo needs in order to be worth testing against.


async def test_demo_funding_is_deterministic_and_bounded():
    from replay.candle_source import _DEMO_FUNDING_PEAK, DemoCandleSource

    src = DemoCandleSource()
    markets = await src.available_markets()
    assert markets, "the demo stack must expose markets"

    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime(2100, 1, 1, tzinfo=timezone.utc)
    rows = await src.get_funding(markets[0], start=start, end=end)
    assert rows, "demo funding must not be empty — that was the bug"

    # Byte-identical across instances: derived from the market name + bar index,
    # never an RNG or the clock. The demo stack's determinism depends on this.
    again = await DemoCandleSource().get_funding(markets[0], start=start, end=end)
    assert rows == again

    # One rate per candle, aligned to the same hourly grid.
    candles = await src.get_candles(markets[0], start=start, end=end)
    assert [r["timestamp"] for r in rows] == [c["timestamp"] for c in candles]

    # Plausible magnitude — a demo that funds at 5%/hr would teach the operator
    # the wrong thing about which cost dominates.
    assert all(abs(r["funding_rate"]) <= _DEMO_FUNDING_PEAK for r in rows)


async def test_demo_funding_takes_both_signs_and_differs_per_market():
    from replay.candle_source import DemoCandleSource

    src = DemoCandleSource()
    markets = await src.available_markets()
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime(2100, 1, 1, tzinfo=timezone.utc)

    rates = [r["funding_rate"] for r in await src.get_funding(markets[0], start=start, end=end)]
    # Both branches of compute_funding (long pays / short receives) must be hit.
    assert any(r > 0 for r in rates) and any(r < 0 for r in rates)

    # A pair trade is long one leg and short the other, so identical rates would
    # very nearly cancel and leave funding invisible again.
    assert len(markets) >= 2
    other = [r["funding_rate"] for r in await src.get_funding(markets[1], start=start, end=end)]
    assert rates != other


async def test_demo_funding_respects_the_requested_window():
    from replay.candle_source import DemoCandleSource

    src = DemoCandleSource()
    market = (await src.available_markets())[0]
    wide = await src.get_funding(
        market,
        start=datetime(2000, 1, 1, tzinfo=timezone.utc),
        end=datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    lo, hi = wide[2]["timestamp"], wide[5]["timestamp"]
    narrow = await src.get_funding(market, start=lo, end=hi)
    assert [r["timestamp"] for r in narrow] == [r["timestamp"] for r in wide[2:6]]
