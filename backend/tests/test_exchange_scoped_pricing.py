"""
Phase 5 — a paper-trading session prices from ITS OWN venue, not a global.

The bug this pins: ``SimulationEngine._snapshots_for`` selected pairs from
``session["exchange"]`` but built its price client from ``make_data_client()``,
which dispatched on the **mutable process-global** ``SCAN_DATA_SOURCE``. That
global is changed at runtime by the data-source endpoint and **resets to its env
default on every api restart**, so a long-lived hyperliquid session would have
started pricing HL pairs against the dYdX indexer.

That failure is not loud. The two venues share market names (BTC, XRP, SUI, LDO…),
so those legs fetch *successfully* from the wrong exchange and open virtual
positions on another venue's prices — in a run whose entire purpose is to check
that fills and costs behave honestly.
"""

from __future__ import annotations

import pytest

import config
from exchanges import EXCHANGE_REGISTRY, make_data_client


def test_explicit_exchange_beats_the_mutable_global(monkeypatch):
    """The core regression: the session's venue wins over SCAN_DATA_SOURCE."""
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "dydx")
    client = make_data_client("hyperliquid")
    assert type(client).__name__ == "HyperliquidDataClient"


def test_survives_the_restart_that_resets_the_global(monkeypatch):
    """A restart reverts SCAN_DATA_SOURCE to its env default; the session must not
    silently change venue with it."""
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "hyperliquid")
    before = type(make_data_client("hyperliquid")).__name__
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "dydx")  # the restart
    after = type(make_data_client("hyperliquid")).__name__
    assert before == after == "HyperliquidDataClient"


def test_omitting_the_exchange_still_follows_the_global(monkeypatch):
    """Callers driven by the UI's data-source toggle (scan, pair detail) are unchanged."""
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "hyperliquid")
    assert type(make_data_client()).__name__ == "HyperliquidDataClient"
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "dydx")
    assert type(make_data_client()).__name__ == "DydxDataClient"


def test_fake_mode_wins_over_an_explicit_exchange(monkeypatch):
    """`fake` is a whole-process offline mode. A session created against dydx must
    not start making real network calls because the process is in demo."""
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "fake")
    assert type(make_data_client("dydx")).__name__ == "DemoDataClient"
    assert type(make_data_client("hyperliquid")).__name__ == "DemoDataClient"


def test_unknown_exchange_raises_rather_than_defaulting(monkeypatch):
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "dydx")
    with pytest.raises(ValueError):
        make_data_client("kraken")


def test_hyperliquid_paper_trading_is_enabled_but_live_trading_is_not():
    """Opening the paper-trading gate must not open the live-trading one."""
    hl = EXCHANGE_REGISTRY["hyperliquid"]
    assert hl.sim_enabled is True
    # The thing that actually places orders stays shut.
    assert hl.live_modes == []


@pytest.mark.asyncio
async def test_sim_snapshots_use_the_session_exchange(monkeypatch):
    """End of the wire: the engine passes the session's venue to the factory."""
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "dydx")

    seen: dict = {}

    class _Client:
        async def aclose(self):
            pass

    def _fake_factory(exchange=None):
        seen["exchange"] = exchange
        return _Client()

    async def _pairs(**_):
        return [{"base_market": "CRV", "quote_market": "LIT", "hedge_ratio": 1.0,
                 "p_value": 0.001, "half_life": 5.0}]

    async def _snaps(client, pairs, **kw):
        return []

    import simulation.engine as eng

    monkeypatch.setattr(eng, "make_data_client", _fake_factory)
    monkeypatch.setattr(eng, "build_realtime_snapshots", _snaps)

    class _Repo:
        async def get_latest_pairs(self, **kw):
            return await _pairs(**kw)

    monkeypatch.setattr(eng, "get_scan_repository", lambda: _Repo())

    engine = eng.SimulationEngine()
    await engine._snapshots_for({"id": "s1", "exchange": "hyperliquid", "zscore_window": 21})

    assert seen["exchange"] == "hyperliquid", (
        "the sim priced from the global instead of the session's venue"
    )
