"""
Phase 5 — the real-time simulation charges the SAME honest costs as the backtest.

Before this, a paper run was optimistic three ways at once: flat slippage instead
of each market's half-spread, **no** market impact, and **no funding at all**. The
last is the biggest — funding is ~29% of gross at the recommended config while the
measured edge is +$0.248/trade — so a flat run would have printed several times the
true P&L (``docs/PHASE5_PAPER_TRADING_PLAN.md`` §1).

These tests pin all three, plus the refactor's key safety property: the shared cost
map must reproduce the backtest's own numbers exactly, because the Phase-4 campaign
results are the control.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import config
from simulation.cost_map import build_cost_map
from simulation.feed import PairTick, filter_pairs_by_quality
from simulation.live_costs import REFRESH_SECONDS, LiveCostCache

NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)

THIN = "THIN-USD"      # ~$2k/hr → wide spread + material impact
LIQUID = "LIQUID-USD"  # ~$5M/hr → tight spread, ~no impact

VOLUMES = {THIN: 2_000.0, LIQUID: 5_000_000.0}
# A gently trending series gives a non-zero realised vol for the impact term.
CLOSES = {m: [100.0 + (i % 7) for i in range(200)] for m in (THIN, LIQUID)}


# ── the shared cost map ───────────────────────────────────────────────────────


def test_cost_map_is_flat_when_both_flags_off(monkeypatch):
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", False)
    monkeypatch.setattr(config, "MARKET_IMPACT", False)
    m = build_cost_map(
        [THIN, LIQUID], dollar_volumes=VOLUMES, closes_by_market=CLOSES,
        flat_slippage_pct=0.05, per_leg_usd=100.0,
    )
    assert m == {THIN: 0.05, LIQUID: 0.05}


def test_cost_map_charges_thin_markets_more(monkeypatch):
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", True)
    monkeypatch.setattr(config, "MARKET_IMPACT", False)
    m = build_cost_map(
        [THIN, LIQUID], dollar_volumes=VOLUMES, closes_by_market=CLOSES,
        flat_slippage_pct=0.05, per_leg_usd=100.0,
    )
    # The whole point of Slice 1: the thin market pays a wider half-spread.
    assert m[THIN] > m[LIQUID]


def test_cost_map_impact_grows_superlinearly_with_size(monkeypatch):
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", True)
    monkeypatch.setattr(config, "MARKET_IMPACT", True)

    def at(size):
        return build_cost_map(
            [THIN], dollar_volumes=VOLUMES, closes_by_market=CLOSES,
            flat_slippage_pct=0.05, per_leg_usd=size,
        )[THIN]

    spread_only = build_cost_map(
        [THIN], dollar_volumes=VOLUMES, closes_by_market=CLOSES,
        flat_slippage_pct=0.05, per_leg_usd=100.0,
    )[THIN]
    monkeypatch.setattr(config, "MARKET_IMPACT", False)
    base = build_cost_map(
        [THIN], dollar_volumes=VOLUMES, closes_by_market=CLOSES,
        flat_slippage_pct=0.05, per_leg_usd=100.0,
    )[THIN]
    monkeypatch.setattr(config, "MARKET_IMPACT", True)

    assert spread_only > base                    # impact is actually added
    assert at(1_000.0) > at(100.0)               # bigger size costs more per leg
    # impact ∝ √Q per leg, so 10× size is >3× the impact component
    assert (at(1_000.0) - base) > 3.0 * (at(100.0) - base)


def test_cost_map_impact_is_zero_without_volume(monkeypatch):
    """Fake mode has no dollar-volume, so impact (which needs ADV) must be 0."""
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", True)
    monkeypatch.setattr(config, "MARKET_IMPACT", True)
    m = build_cost_map(
        [THIN], dollar_volumes={}, closes_by_market=CLOSES,
        flat_slippage_pct=0.05, per_leg_usd=1_000.0,
    )
    no_impact = build_cost_map(
        [THIN], dollar_volumes={}, closes_by_market=CLOSES,
        flat_slippage_pct=0.05, per_leg_usd=100.0,
    )
    assert m[THIN] == pytest.approx(no_impact[THIN])


@pytest.mark.asyncio
async def test_backtest_adapter_matches_shared_builder(monkeypatch):
    """The backtest's numbers must not move: its adapter and the shared builder agree.

    The Phase-4 campaign results are the control for this refactor — if these ever
    diverge, every saved figure in docs/strategy.md is silently invalidated.
    """
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", True)
    monkeypatch.setattr(config, "MARKET_IMPACT", True)
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "hyperliquid")

    from backtest import engine as bt_engine
    from ingest import cache_repository as cache_module

    class _FakeCacheRepo:
        async def get_dollar_volumes(self, **_):
            return VOLUMES

    monkeypatch.setattr(cache_module, "get_ohlcv_cache_repository", lambda: _FakeCacheRepo())

    candles = {m: [{"close": c} for c in CLOSES[m]] for m in (THIN, LIQUID)}
    row = {"slippage_pct": 0.05, "usd_per_trade": 1_000.0}
    via_backtest = await bt_engine._build_slippage_map(
        "hyperliquid", [THIN, LIQUID], NOW - timedelta(days=7), NOW, row, candles
    )
    via_shared = build_cost_map(
        [THIN, LIQUID], dollar_volumes=VOLUMES, closes_by_market=CLOSES,
        flat_slippage_pct=0.05, per_leg_usd=1_000.0,
    )
    assert via_backtest == via_shared


# ── the live cost cache ───────────────────────────────────────────────────────


class _StubSource:
    """Stands in for the OHLCV/funding cache source."""

    def __init__(self, *, fail: bool = False, rate: float = -0.0001) -> None:
        self.fail = fail
        self.rate = rate
        self.candle_calls = 0

    async def get_candles(self, market, *, start, end):
        self.candle_calls += 1
        if self.fail:
            raise RuntimeError("cache down")
        return [{"close": c} for c in CLOSES.get(market, [100.0] * 50)]

    async def get_funding(self, market, *, start, end):
        if self.fail:
            raise RuntimeError("cache down")
        return [{"timestamp": start + timedelta(hours=i), "funding_rate": self.rate}
                for i in range(24)]


def _patch_sources(monkeypatch, source, volumes=None):
    monkeypatch.setattr("simulation.live_costs.make_candle_source", lambda **_: source)

    async def _volumes(**_):
        return VOLUMES if volumes is None else volumes

    monkeypatch.setattr("simulation.live_costs.load_dollar_volumes", _volumes)


@pytest.mark.asyncio
async def test_live_cache_returns_empty_map_when_flags_off(monkeypatch):
    """Flags off ⇒ no map ⇒ the caller keeps the flat slippage_pct path untouched."""
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", False)
    monkeypatch.setattr(config, "MARKET_IMPACT", False)
    _patch_sources(monkeypatch, _StubSource())
    got = await LiveCostCache().slippage_map(
        exchange="hyperliquid", markets={THIN}, flat_slippage_pct=0.05,
        per_leg_usd=100.0, now=NOW,
    )
    assert got == {}


@pytest.mark.asyncio
async def test_live_cache_builds_per_market_map(monkeypatch):
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", True)
    monkeypatch.setattr(config, "MARKET_IMPACT", True)
    _patch_sources(monkeypatch, _StubSource())
    got = await LiveCostCache().slippage_map(
        exchange="hyperliquid", markets={THIN, LIQUID}, flat_slippage_pct=0.05,
        per_leg_usd=1_000.0, now=NOW,
    )
    assert got[THIN] > got[LIQUID] > 0


@pytest.mark.asyncio
async def test_live_cache_refreshes_hourly_not_every_tick(monkeypatch):
    """A 60s tick must not rebuild a GROUP BY over the candle cache every time."""
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", True)
    monkeypatch.setattr(config, "MARKET_IMPACT", True)
    source = _StubSource()
    _patch_sources(monkeypatch, source)
    cache = LiveCostCache()
    kw = dict(exchange="hyperliquid", markets={THIN}, flat_slippage_pct=0.05, per_leg_usd=100.0)

    await cache.slippage_map(**kw, now=NOW)
    first = source.candle_calls
    await cache.slippage_map(**kw, now=NOW + timedelta(seconds=60))
    assert source.candle_calls == first, "rebuilt within the TTL"

    await cache.slippage_map(**kw, now=NOW + timedelta(seconds=REFRESH_SECONDS + 1))
    assert source.candle_calls > first, "did not rebuild after the TTL"


@pytest.mark.asyncio
async def test_live_cache_reuses_last_good_map_on_failure(monkeypatch):
    """A failed refresh must NOT silently revert to flat cost — that is the optimism
    this module exists to remove, and it would be invisible."""
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", True)
    monkeypatch.setattr(config, "MARKET_IMPACT", True)
    source = _StubSource()
    _patch_sources(monkeypatch, source)
    cache = LiveCostCache()
    kw = dict(exchange="hyperliquid", markets={THIN}, flat_slippage_pct=0.05, per_leg_usd=100.0)
    good = await cache.slippage_map(**kw, now=NOW)

    source.fail = True

    async def _boom(**_):
        raise RuntimeError("volumes down")

    monkeypatch.setattr("simulation.live_costs.load_dollar_volumes", _boom)
    after = await cache.slippage_map(**kw, now=NOW + timedelta(seconds=REFRESH_SECONDS + 1))
    assert after == good


@pytest.mark.asyncio
async def test_live_cache_supplies_funding_rates(monkeypatch):
    _patch_sources(monkeypatch, _StubSource(rate=-0.0002))
    rates = await LiveCostCache().funding_rates(
        exchange="hyperliquid", markets={THIN, LIQUID}, now=NOW
    )
    assert rates[THIN] == pytest.approx(-0.0002)
    assert rates[LIQUID] == pytest.approx(-0.0002)


@pytest.mark.asyncio
async def test_funding_lookback_is_wide_enough_to_survive_a_lagging_ingest(monkeypatch):
    """A stale funding cache must not silently mean "no funding".

    Funding is the dominant cost (~29% of gross). If the ingest job lags by more
    than the lookback the table comes back empty and the sim charges nothing —
    restoring exactly the optimism this module removes, invisibly. The window is
    therefore much wider than the cost lookback, because the table is a step
    function and only needs the latest rate at-or-before now.
    """
    from simulation.live_costs import FUNDING_LOOKBACK_DAYS, LOOKBACK_DAYS

    assert FUNDING_LOOKBACK_DAYS > LOOKBACK_DAYS

    seen: dict[str, object] = {}

    class _LaggingSource(_StubSource):
        async def get_funding(self, market, *, start, end):
            seen["start"] = start
            # Ingest last ran 10 days ago — inside the funding window, outside a 7d one.
            stamp = end - timedelta(days=10)
            return [{"timestamp": stamp, "funding_rate": -0.00025}]

    _patch_sources(monkeypatch, _LaggingSource())
    rates = await LiveCostCache().funding_rates(
        exchange="hyperliquid", markets={THIN}, now=NOW
    )
    assert rates[THIN] == pytest.approx(-0.00025)
    assert (NOW - seen["start"]).days >= 30


@pytest.mark.asyncio
async def test_live_cache_funding_empty_when_unavailable(monkeypatch):
    _patch_sources(monkeypatch, _StubSource(fail=True))
    rates = await LiveCostCache().funding_rates(
        exchange="hyperliquid", markets={THIN}, now=NOW
    )
    assert rates == {}


# ── the tick actually applies them ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_tick_attaches_cost_map_and_funding(monkeypatch):
    """The regression that matters: tick() must hand run_tick a per-market map AND
    live funding rates, not a bare session."""
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", True)
    monkeypatch.setattr(config, "MARKET_IMPACT", True)
    _patch_sources(monkeypatch, _StubSource(rate=-0.0003))

    from simulation.engine import SimulationEngine

    engine = SimulationEngine()
    session = {
        "id": "s1", "exchange": "hyperliquid", "slippage_pct": 0.05,
        "usd_per_trade": 1_000.0,
    }
    snapshots = [
        PairTick(base_market=THIN, quote_market=LIQUID, hedge_ratio=1.0, half_life=10.0,
                 base_price=100.0, quote_price=50.0, z_score=4.2, spread_value=0.0)
    ]
    enriched, funding = await engine._apply_live_costs(session, snapshots)

    assert "slippage_by_market" in enriched
    assert enriched["slippage_by_market"][THIN] > enriched["slippage_by_market"][LIQUID]
    assert funding[THIN] == pytest.approx(-0.0003)
    # the caller's dict is not mutated
    assert "slippage_by_market" not in session


# ── per-session pair quality ─────────────────────────────────────────────────


def _pair(base, p, hl):
    return {"base_market": base, "quote_market": "Q-USD", "p_value": p, "half_life": hl}


def test_quality_filter_is_a_noop_without_bounds():
    pairs = [_pair("A", 0.04, 60.0), _pair("B", 0.005, 10.0)]
    assert filter_pairs_by_quality(pairs) == pairs


def test_quality_filter_applies_pvalue_bound():
    pairs = [_pair("A", 0.04, 10.0), _pair("B", 0.005, 10.0)]
    kept = filter_pairs_by_quality(pairs, pvalue_max=0.01)
    assert [p["base_market"] for p in kept] == ["B"]


def test_quality_filter_applies_half_life_bound():
    pairs = [_pair("A", 0.005, 90.0), _pair("B", 0.005, 10.0)]
    kept = filter_pairs_by_quality(pairs, max_half_life_h=72.0)
    assert [p["base_market"] for p in kept] == ["B"]


def test_quality_filter_keeps_pairs_missing_the_field():
    """Tighten on evidence, don't reject on absence."""
    pairs = [{"base_market": "A", "quote_market": "Q-USD"}]
    assert filter_pairs_by_quality(pairs, pvalue_max=0.01, max_half_life_h=72.0) == pairs


def test_session_serialiser_round_trips_the_new_fields():
    """Regression: the serialiser WHITELISTS columns, so a new column that is written
    to the DB can still be invisible to the engine.

    ``_snapshots_for`` reads ``pvalue_max`` / ``max_half_life_h`` off this dict — if
    they are dropped here the pair filter silently never applies, and the session
    trades whatever the scan produced while its row claims otherwise. Caught in local
    e2e, pinned here.
    """
    from db.sim_repository import PrismaSimRepository

    class _Rec:
        id = "s1"
        exchange = "hyperliquid"
        mode = "simulation"
        label = "x"
        status = "RUNNING"
        starting_capital = 2_000.0
        current_capital = 2_000.0
        interval_seconds = 300
        zscore_window = 21
        entry_threshold = 4.0
        exit_threshold = 0.5
        stop_threshold = 5.0
        usd_per_trade = 100.0
        max_active_pairs = 5
        slippage_pct = 0.0316
        taker_fee_pct = 0.045
        funding_freq_h = 1
        pvalue_max = 0.01
        max_half_life_h = 72.0
        per_market_slippage = True
        market_impact = True
        source_strategy_id = "bt_1"
        tick_count = 0
        last_tick_at = None
        created_at = None
        stopped_at = None

    d = PrismaSimRepository._session_to_dict(_Rec())
    assert d["pvalue_max"] == 0.01
    assert d["max_half_life_h"] == 72.0
    assert d["per_market_slippage"] is True
    assert d["market_impact"] is True
    # The strategy link drives the dashboard's "In sim" highlight; dropping it here
    # would leave the badge permanently dark with no other symptom.
    assert d["source_strategy_id"] == "bt_1"
